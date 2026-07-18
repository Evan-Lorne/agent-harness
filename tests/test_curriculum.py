from __future__ import annotations

import asyncio
import re
import subprocess
from pathlib import Path
from typing import Any

from harness.agent.loop import BudgetState, agent_loop
from harness.context.prompt_builder import PromptBuilder, PromptContext
from harness.memory.automation import extract_memories, load_relevant_memories
from harness.memory.store import MemoryStore
from harness.security.hooks import HookPipeline, HookResult
from harness.skills.loader import SkillLoader, create_load_skill_tool
from harness.tasks.store import TaskStore
from harness.tasks.tools import create_task_tools
from harness.teams.manager import TeamManager
from harness.tools.file_tools import write_file_tool
from harness.tools.registry import ToolDefinition, ToolRegistry, normalize_mcp_name
from harness.tools.todo_tools import TodoStore, create_todo_tool
from harness.types import Message, ModelStep, ModelUsage, StreamPart, content_to_text
from harness.worktrees.manager import WorktreeManager


class TextModel:
    model_id = "test-model"

    async def run_step(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: dict[str, Any],
        tool_choice: str = "auto",
        on_text_delta: Any = None,
        max_output_tokens: int | None = None,
    ) -> ModelStep:
        message = {"role": "assistant", "content": [{"type": "text", "text": "done"}]}
        return ModelStep([message], ModelUsage(), [StreamPart("text-delta", text="done")])

    async def generate(self, *, system: str, prompt: str) -> str:
        return "[]"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


async def test_todo_and_persistent_task_dependency_flow(tmp_path) -> None:
    todos = TodoStore()
    todo_tool = create_todo_tool(todos)
    output = await todo_tool.execute(
        {"todos": [{"content": "implement", "status": "in_progress"}, {"content": "verify", "status": "pending"}]}
    )
    assert "[>] implement" in output
    assert "只能有一个" in await todo_tool.execute(
        {"todos": [{"content": "a", "status": "in_progress"}, {"content": "b", "status": "in_progress"}]}
    )

    store = TaskStore(tmp_path)
    first = store.create("schema")
    second = store.create("api", blocked_by=[first.id])
    assert not store.can_start(second)
    store.claim(first.id, "alice")
    completed, unlocked = store.complete(first.id, "alice")
    assert completed.status == "completed"
    assert [task.id for task in unlocked] == [second.id]
    assert TaskStore(tmp_path).get(first.id).status == "completed"  # type: ignore[union-attr]


async def test_permission_pipeline_and_all_four_hook_phases() -> None:
    calls: list[str] = []
    registry = ToolRegistry()
    registry.register(ToolDefinition("bash", "shell", {}, lambda args: calls.append(args["command"]) or "ok"))
    approvals: list[str] = []

    async def approve(_name: str, _args: dict, reason: str) -> bool:
        approvals.append(reason)
        return True

    registry.set_approval_handler(approve)
    assert await registry.to_model_format()["bash"]["execute"]({"command": "rm demo.txt"}) == "ok"
    assert approvals == ["删除文件"]
    assert calls == ["rm demo.txt"]

    hooks = HookPipeline()
    hooks.register_user("user", lambda query: HookResult("modify", modified_input=query + "!"))
    hooks.register_pre("pre", lambda *_args: HookResult("modify", modified_input={"value": 2}))
    hooks.register_post("post", lambda *_args: HookResult("modify", modified_output="changed"))
    hooks.register_stop("stop", lambda _messages: HookResult("continue", "verify"))
    assert (await hooks.run_user("hello")).modified_input == "hello!"
    assert (await hooks.run_pre("tool", {"value": 1})).modified_input == {"value": 2}
    assert (await hooks.run_post("tool", {}, "old")).modified_output == "changed"
    assert (await hooks.run_stop([])).action == "continue"


async def test_background_task_returns_placeholder_then_notification() -> None:
    registry = ToolRegistry()

    async def execute(_args: dict) -> str:
        return "background output"

    registry.register(ToolDefinition("bash", "shell", {}, execute))
    result = await registry.to_model_format()["bash"]["execute"]({"command": "long build", "run_in_background": True})
    assert "bg_0001" in result
    for _ in range(3):
        await asyncio.sleep(0)
    notifications = registry.collect_notifications()
    assert "<task_notification>" in notifications[0]
    assert "background output" in notifications[0]


async def test_skill_is_loaded_by_tool_result(tmp_path) -> None:
    skill_dir = tmp_path / ".skills/review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\ndescription: Review code\nwhen_to_use: reviews\n---\n\nFollow the checklist.", encoding="utf-8"
    )
    loader = SkillLoader(tmp_path)
    loader.load()
    output = await create_load_skill_tool(loader).execute({"name": "review"})
    assert "Follow the checklist" in output
    assert str(skill_dir.resolve()) in output


async def test_memory_relevance_and_end_of_turn_extraction(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    store.save({"name": "Tabs", "description": "indentation preference", "type": "user", "content": "Use tabs."})

    class MemoryModel(TextModel):
        async def generate(self, *, system: str, prompt: str) -> str:
            if "Select up to" in prompt:
                return "[0]"
            return '[{"name":"Quotes","type":"user","description":"quote preference","content":"Use single quotes."}]'

    model = MemoryModel()
    messages = [{"role": "user", "content": "format my Python code"}]
    assert "Use tabs" in await load_relevant_memories(model, store, messages)
    assert await extract_memories(model, store, messages) == 1
    assert {entry.name for entry in store.list()} == {"Tabs", "Quotes"}


async def test_prompt_cache_and_recovery_paths(capsys) -> None:
    builder = PromptBuilder().pipe("identity", lambda context: f"tools={context.tool_count}")
    context = PromptContext(1, "", 0, "test")
    assert builder.build(context) is builder.build(context)

    class RecoveryModel(TextModel):
        def __init__(self) -> None:
            self.calls = 0
            self.max_values: list[int | None] = []

        async def run_step(self, **kwargs: Any) -> ModelStep:
            self.calls += 1
            self.max_values.append(kwargs.get("max_output_tokens"))
            if self.calls == 1:
                raise RuntimeError("413 prompt_too_long maximum context length")
            if self.calls == 2:
                return ModelStep([], ModelUsage(), [], "max_tokens")
            return await super().run_step(**kwargs)

    model = RecoveryModel()
    messages: list[Message] = [{"role": "user", "content": "x"}]
    await agent_loop(model, ToolRegistry(), messages, "system", budget=BudgetState(limit=100_000))
    assert model.max_values == [8000, 8000, 64000]
    output = capsys.readouterr().out
    assert "reactive compact" in output
    assert "提升输出上限" in output


async def test_mcp_names_and_destructive_annotations_require_approval() -> None:
    called = False

    class Client:
        async def connect(self) -> None:
            return None

        async def list_tools(self) -> list[dict[str, Any]]:
            return [
                {
                    "name": "delete issue!",
                    "description": "delete",
                    "inputSchema": {},
                    "isReadOnly": False,
                    "isDestructive": True,
                }
            ]

        async def call_tool(self, _name: str, _args: dict[str, Any]) -> str:
            nonlocal called
            called = True
            return "deleted"

        async def close(self) -> None:
            return None

    registry = ToolRegistry()
    names = await registry.register_mcp_server("issue server", Client())
    assert names == ["mcp__issue_server__delete_issue_"]
    assert normalize_mcp_name("a/b") == "a_b"
    registry.mark_discovered(names[0])
    tool = registry.to_model_format()[names[0]]
    assert "审批拒绝" in await tool["execute"]({})
    assert not called
    registry.set_approval_handler(lambda *_args: True)
    assert await tool["execute"]({}) == "deleted"
    assert called


async def test_team_auto_claim_uses_bound_worktree_and_protocols(tmp_path) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "README.md").write_text("root", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-m", "init")

    tasks = TaskStore(tmp_path)
    task = tasks.create("write isolated file")
    worktrees = WorktreeManager(tmp_path, tasks)
    assert "created" in worktrees.create("alice-work", task.id)

    class CompletingModel(TextModel):
        def __init__(self) -> None:
            self.written = False
            self.completed = False

        async def run_step(self, **kwargs: Any) -> ModelStep:
            messages, tools = kwargs["messages"], kwargs["tools"]
            task_id = re.search(r"task_[A-Za-z0-9_]+", content_to_text(messages[-1].get("content")))
            if task_id and not self.written:
                self.written = True
                await tools["write_file"]["execute"]({"path": "isolated.txt", "content": "alice"})
                return ModelStep([], ModelUsage(), [StreamPart("tool-call", tool_name="write_file")])
            if task_id and not self.completed:
                self.completed = True
                await tools["complete_task"]["execute"]({"id": task_id.group(0), "owner": "alice"})
                return ModelStep([], ModelUsage(), [StreamPart("tool-call", tool_name="complete_task")])
            return await super().run_step(**kwargs)

    model = CompletingModel()
    registry = ToolRegistry()
    registry.register(write_file_tool, *create_task_tools(tasks))
    manager = TeamManager(model, registry, tasks, worktrees, tmp_path)
    manager.spawn("alice", "developer")
    for _ in range(100):
        if tasks.get(task.id).status == "completed":  # type: ignore[union-attr]
            break
        await asyncio.sleep(0.01)
    assert tasks.get(task.id).status == "completed"  # type: ignore[union-attr]
    assert (worktrees.path_for("alice-work") / "isolated.txt").read_text(encoding="utf-8") == "alice"

    request_id = manager.request_plan("alice", "submit a plan")
    assert manager.submit_plan("alice", request_id, "1. implement\n2. test") == "计划已提交审批"
    assert manager.collect_lead_inbox()
    assert manager.review_plan(request_id, True) == "approved"
    await manager.close()
    assert "removed" in worktrees.remove("alice-work", discard_changes=True)
