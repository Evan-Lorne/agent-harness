from __future__ import annotations

import asyncio
import json
from pathlib import Path

from harness.tasks.store import TaskStore
from harness.teams.bus import MessageBus
from harness.teams.types import ProtocolState, TeammateState
from harness.tools.registry import ToolRegistry
from harness.types import Message, Model, content_to_text
from harness.workspace import WORKING_DIRECTORY
from harness.worktrees.manager import WorktreeManager

LEAD_ONLY_TOOLS = {
    "spawn_agent",
    "spawn_teammate",
    "request_shutdown",
    "request_plan",
    "review_plan",
    "create_worktree",
    "remove_worktree",
    "keep_worktree",
}


class TeamManager:
    def __init__(
        self,
        model: Model,
        registry: ToolRegistry,
        task_store: TaskStore,
        worktrees: WorktreeManager,
        base_dir: str | Path = ".",
    ) -> None:
        self.model = model
        self.registry = registry
        self.task_store = task_store
        self.worktrees = worktrees
        self.bus = MessageBus(base_dir)
        self.teammates: dict[str, TeammateState] = {}
        self.workers: dict[str, asyncio.Task[None]] = {}
        self.pending: dict[str, ProtocolState] = {}
        self.request_counter = 0

    def _request_id(self) -> str:
        self.request_counter += 1
        return f"req_{self.request_counter:06d}"

    def spawn(self, name: str, role: str, task: str = "") -> str:
        self.bus.validate_name(name)
        if name in self.workers and not self.workers[name].done():
            return f"队友 {name} 已在运行"
        state = TeammateState(name, role)
        self.teammates[name] = state
        self.workers[name] = asyncio.create_task(self._run(state, task))
        return f"队友 {name} 已启动，角色: {role}"

    async def _run(self, state: TeammateState, initial_task: str) -> None:
        messages: list[Message] = []
        idle_seconds = 0
        if initial_task:
            messages.append({"role": "user", "content": initial_task})
        cwd_token = None
        try:
            while True:
                inbox = self.bus.read(state.name)
                if inbox:
                    idle_seconds = 0
                for message in inbox:
                    if message.get("type") == "shutdown_request":
                        request_id = message.get("metadata", {}).get("request_id", "")
                        self.bus.send(
                            state.name,
                            "lead",
                            "shutdown acknowledged",
                            "shutdown_response",
                            {"request_id": request_id, "approve": True},
                        )
                        state.status = "shutdown"
                        return
                    messages.append(
                        {"role": "user", "content": f"[来自 {message.get('from')}] {message.get('content')}"}
                    )

                if not messages:
                    available = self.task_store.available()
                    if available:
                        claimed = self.task_store.claim(available[0].id, state.name)
                        if claimed.worktree:
                            cwd_token = WORKING_DIRECTORY.set(self.worktrees.path_for(claimed.worktree))
                        messages.append(
                            {
                                "role": "user",
                                "content": f"你已自动认领任务 {claimed.id}: {claimed.subject}\n{claimed.description}",
                            }
                        )
                    else:
                        state.status = "idle"
                        try:
                            await asyncio.sleep(1)
                        except asyncio.CancelledError:
                            return
                        idle_seconds += 1
                        if idle_seconds >= 60:
                            state.status = "shutdown"
                            self.bus.send(state.name, "lead", state.summary or "idle timeout", "result")
                            return
                        continue

                state.status = "working"
                idle_seconds = 0
                tools = self.registry.to_model_format_for_subagent(LEAD_ONLY_TOOLS)
                for _ in range(10):
                    result = await self.model.run_step(
                        system=f"你是持久队友 {state.name}，角色 {state.role}。完成任务，必要时使用 send_message；不要创建新队友。",
                        messages=messages,
                        tools=tools,
                    )
                    messages.extend(result.messages)
                    if not any(part.type == "tool-call" for part in result.parts):
                        break
                assistant = next(
                    (message for message in reversed(messages) if message.get("role") == "assistant"), None
                )
                state.summary = content_to_text(assistant.get("content")) if assistant else ""
                self.bus.send(state.name, "lead", state.summary or "任务阶段完成", "result")
                messages.clear()
                if cwd_token is not None:
                    WORKING_DIRECTORY.reset(cwd_token)
                    cwd_token = None
        except Exception as error:
            state.status = "error"
            state.summary = str(error)
            self.bus.send(state.name, "lead", str(error), "error")
        finally:
            try:
                self.task_store.release_owner(state.name)
            finally:
                if cwd_token is not None:
                    WORKING_DIRECTORY.reset(cwd_token)

    def send(self, sender: str, recipient: str, content: str) -> str:
        self.bus.send(sender, recipient, content)
        return f"消息已发送给 {recipient}"

    def request_shutdown(self, teammate: str) -> str:
        if teammate not in self.workers or self.workers[teammate].done():
            raise ValueError(f"队友 {teammate} 未运行")
        request_id = self._request_id()
        self.pending[request_id] = ProtocolState(request_id, "shutdown", teammate)
        self.bus.send("lead", teammate, "please shutdown", "shutdown_request", {"request_id": request_id})
        return request_id

    def request_plan(self, teammate: str, prompt: str) -> str:
        if teammate not in self.workers or self.workers[teammate].done():
            raise ValueError(f"队友 {teammate} 未运行")
        request_id = self._request_id()
        self.pending[request_id] = ProtocolState(request_id, "plan_approval", teammate, payload=prompt)
        self.bus.send("lead", teammate, prompt, "plan_request", {"request_id": request_id})
        return request_id

    def review_plan(self, request_id: str, approve: bool, feedback: str = "") -> str:
        state = self.pending.get(request_id)
        if not state or state.type != "plan_approval" or state.status != "submitted":
            return "找不到待审批计划"
        state.status = "approved" if approve else "rejected"
        self.bus.send(
            "lead",
            state.teammate,
            feedback or state.status,
            "plan_approval_response",
            {"request_id": request_id, "approve": approve},
        )
        return state.status

    def submit_plan(self, teammate: str, request_id: str, plan: str) -> str:
        state = self.pending.get(request_id)
        if not state or state.type != "plan_approval" or state.teammate != teammate or state.status != "pending":
            return "找不到对应计划请求"
        state.payload = plan
        state.status = "submitted"
        self.bus.send(teammate, "lead", plan, "plan_approval_request", {"request_id": request_id})
        return "计划已提交审批"

    def collect_lead_inbox(self) -> list[str]:
        messages = self.bus.read("lead")
        values = []
        for message in messages:
            metadata = message.get("metadata", {})
            request_id = metadata.get("request_id")
            state = self.pending.get(request_id) if request_id else None
            expected = "shutdown_response" if state and state.type == "shutdown" else "plan_approval_response"
            if (
                state
                and message.get("from") == state.teammate
                and message.get("type") == expected
                and state.status == "pending"
            ):
                state.status = "approved" if metadata.get("approve") else "rejected"
            values.append(json.dumps(message, ensure_ascii=False))
        return values

    async def close(self) -> None:
        workers = list(self.workers.values())
        for worker in workers:
            worker.cancel()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)
        self.workers.clear()
