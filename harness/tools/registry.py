from __future__ import annotations

import asyncio
import inspect
import json
import re
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from harness.background.manager import BackgroundTaskManager
from harness.security.bash_classifier import classify_bash_command
from harness.security.hooks import HookPipeline
from harness.security.roles import Role, can_use_tool
from harness.workspace import current_workdir, resolve_path

ToolExecute = Callable[[dict[str, Any]], Any | Awaitable[Any]]
ApprovalHandler = Callable[[str, dict[str, Any], str], bool | Awaitable[bool]]
DEFAULT_MAX_RESULT_CHARS = 3000


@dataclass(slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    execute: ToolExecute
    is_concurrency_safe: bool = False
    is_read_only: bool = False
    max_result_chars: int | None = None
    profile: list[str] | None = None
    should_defer: bool = False
    search_hint: str | None = None
    is_destructive: bool = False


class _ReadWriteGate:
    def __init__(self) -> None:
        self.condition = asyncio.Condition()
        self.exclusive = False
        self.concurrent_count = 0
        self.waiting_exclusive = 0

    async def acquire_shared(self) -> None:
        async with self.condition:
            while self.exclusive or self.waiting_exclusive:
                await self.condition.wait()
            self.concurrent_count += 1

    async def release_shared(self) -> None:
        async with self.condition:
            self.concurrent_count -= 1
            if self.concurrent_count == 0:
                self.condition.notify_all()

    async def acquire_exclusive(self) -> None:
        async with self.condition:
            self.waiting_exclusive += 1
            try:
                while self.exclusive or self.concurrent_count > 0:
                    await self.condition.wait()
                self.exclusive = True
            finally:
                self.waiting_exclusive -= 1
                self.condition.notify_all()

    async def release_exclusive(self) -> None:
        async with self.condition:
            self.exclusive = False
            self.condition.notify_all()


class ToolRegistry:
    def __init__(self) -> None:
        self.tools: dict[str, ToolDefinition] = {}
        self.mcp_clients: list[Any] = []
        self.active_profile = "full"
        self.discovered_tools: set[str] = set()
        self.current_role: Role = "owner"
        self.hook_pipeline: HookPipeline | None = None
        self.approval_handler: ApprovalHandler | None = None
        self.gate = _ReadWriteGate()
        self.subagent_gate = _ReadWriteGate()
        self.background = BackgroundTaskManager()
        self.notification_providers: list[Callable[[], list[str]]] = []

    def register(self, *tools: ToolDefinition) -> None:
        for tool in tools:
            self.tools[tool.name] = tool

    def unregister(self, name: str) -> bool:
        self.discovered_tools.discard(name)
        return self.tools.pop(name, None) is not None

    async def register_mcp_server(self, server_name: str, client: Any) -> list[str]:
        registered: list[str] = []
        try:
            await client.connect()
            for tool in await client.list_tools():
                original_name = tool["name"]
                normalized_server = normalize_mcp_name(server_name)
                normalized_tool = normalize_mcp_name(original_name)
                prefixed_name = f"mcp__{normalized_server}__{normalized_tool}"
                if prefixed_name in self.tools:
                    continue

                async def execute(
                    input_value: dict[str, Any], *, name: str = original_name, tool_client: Any = client
                ) -> Any:
                    return await tool_client.call_tool(name, input_value)

                self.register(
                    ToolDefinition(
                        name=prefixed_name,
                        description=(
                            f"[MCP:{server_name}] {tool.get('description', '')} "
                            f"({'destructive' if tool.get('isDestructive') else 'readOnly' if tool.get('isReadOnly') else 'write'})"
                        ),
                        parameters=tool.get("inputSchema", {}),
                        execute=execute,
                        is_concurrency_safe=bool(tool.get("isReadOnly") and not tool.get("isDestructive")),
                        is_read_only=bool(tool.get("isReadOnly")),
                        max_result_chars=3000,
                        profile=["full"],
                        should_defer=True,
                        search_hint=f"{server_name} {original_name} {tool.get('description', '')}",
                        is_destructive=tool.get("isDestructive", False),
                    )
                )
                registered.append(prefixed_name)
        except BaseException:
            for name in registered:
                self.unregister(name)
            try:
                await client.close()
            except Exception:
                pass
            raise
        self.mcp_clients.append(client)
        return registered

    async def close_all_mcp(self) -> None:
        clients = list(self.mcp_clients)
        self.mcp_clients.clear()
        try:
            if clients:
                await asyncio.gather(*(client.close() for client in clients), return_exceptions=True)
        finally:
            await self.background.close()

    def set_profile(self, profile: str) -> None:
        self.active_profile = profile

    def get_profile(self) -> str:
        return self.active_profile

    def set_role(self, role: Role) -> None:
        self.current_role = role

    def get_role(self) -> Role:
        return self.current_role

    def set_hook_pipeline(self, pipeline: HookPipeline) -> None:
        self.hook_pipeline = pipeline

    def set_approval_handler(self, handler: ApprovalHandler) -> None:
        self.approval_handler = handler

    def register_notification_provider(self, provider: Callable[[], list[str]]) -> None:
        self.notification_providers.append(provider)

    def collect_notifications(self) -> list[str]:
        values = self.background.collect_notifications()
        for provider in self.notification_providers:
            values.extend(provider())
        return values

    def mark_discovered(self, name: str) -> None:
        self.discovered_tools.add(name)

    def get(self, name: str) -> ToolDefinition | None:
        return self.tools.get(name)

    def get_all(self) -> list[ToolDefinition]:
        return list(self.tools.values())

    def get_active_tools(self) -> list[ToolDefinition]:
        return [
            tool
            for tool in self.tools.values()
            if (not tool.profile or self.active_profile in tool.profile)
            and (not tool.should_defer or tool.name in self.discovered_tools)
            and can_use_tool(self.current_role, tool.name)
        ]

    def get_deferred_tool_summary(self) -> str:
        deferred = [
            tool for tool in self.tools.values() if tool.should_defer and tool.name not in self.discovered_tools
        ]
        if not deferred:
            return ""
        lines = [f"  - {tool.name}{f' — {tool.search_hint}' if tool.search_hint else ''}" for tool in deferred]
        return "\n以下工具可用，但需要先通过 tool_search 搜索获取完整定义：\n" + "\n".join(lines)

    def search_tools(self, query: str) -> list[ToolDefinition]:
        names = [name.strip() for name in query.split(",") if name.strip()]
        results: list[ToolDefinition] = []
        for name in names:
            tool = self.tools.get(name)
            if tool and tool.name != "tool_search":
                results.append(tool)
                self.discovered_tools.add(tool.name)
        return results

    def count_token_estimate(self) -> dict[str, int]:
        active = deferred = 0
        for tool in self.tools.values():
            if tool.profile and self.active_profile not in tool.profile:
                continue
            size = len(
                json.dumps(
                    {"name": tool.name, "description": tool.description, "parameters": tool.parameters},
                    ensure_ascii=False,
                )
            )
            tokens = (size + 3) // 4
            if tool.should_defer and tool.name not in self.discovered_tools:
                deferred += tokens
            else:
                active += tokens
        return {"active": active, "deferred": deferred, "total": active + deferred}

    @staticmethod
    async def _invoke(function: ToolExecute, input_value: dict[str, Any]) -> Any:
        value = function(input_value)
        return await value if inspect.isawaitable(value) else value

    async def _request_approval(self, tool_name: str, input_value: dict[str, Any], reason: str) -> bool:
        if not self.approval_handler:
            return False
        decision = self.approval_handler(tool_name, input_value, reason)
        return await decision if inspect.isawaitable(decision) else decision

    def _wrap(self, tool: ToolDefinition, gate: _ReadWriteGate) -> dict[str, Any]:
        async def execute(input_value: dict[str, Any]) -> str:
            if self.hook_pipeline:
                pre = await self.hook_pipeline.run_pre(tool.name, input_value)
                if pre.action == "block":
                    return f"[Hook 拦截] {pre.reason or '操作被阻止'}"
                if pre.modified_input is not None:
                    if not isinstance(pre.modified_input, dict):
                        return "[Hook 拦截] Pre Hook 返回了非法工具参数"
                    input_value = pre.modified_input

            approval_reason: str | None = "工具声明为破坏性操作" if tool.is_destructive else None
            if tool.name == "bash" and input_value.get("command"):
                risk = classify_bash_command(input_value["command"])
                if risk["level"] == "dangerous":
                    return f"[拒绝执行] 检测到危险操作: {risk.get('reason')}\n命令: {input_value['command']}"
                if risk["level"] == "moderate":
                    approval_reason = risk.get("reason", "中风险命令")
            if tool.name in {"write_file", "edit_file"} and input_value.get("path"):
                path = resolve_path(str(input_value["path"]))
                if not path.is_relative_to(current_workdir()):
                    approval_reason = "写入工作区外部"
            if approval_reason and not await self._request_approval(tool.name, input_value, approval_reason):
                return f"[审批拒绝] {approval_reason}"

            async def invoke() -> str:
                if tool.is_concurrency_safe:
                    await gate.acquire_shared()
                else:
                    await gate.acquire_exclusive()
                try:
                    try:
                        raw = await self._invoke(tool.execute, input_value)
                        text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False, indent=2)
                    except Exception as error:
                        text = f"[工具执行失败] {type(error).__name__}: {error}"
                    limit = tool.max_result_chars or DEFAULT_MAX_RESULT_CHARS
                    output = persist_or_truncate_result(text, limit, tool.name)
                    if self.hook_pipeline:
                        post = await self.hook_pipeline.run_post(tool.name, input_value, output)
                        if post.modified_output is not None:
                            output = str(post.modified_output)
                    return output
                finally:
                    if tool.is_concurrency_safe:
                        await gate.release_shared()
                    else:
                        await gate.release_exclusive()

            if tool.name == "bash" and input_value.get("run_in_background"):
                task_id = self.background.start(str(input_value.get("command", "")), invoke())
                return f"[Background task {task_id} started] Result will be delivered as a task notification."
            return await invoke()

        return {"name": tool.name, "description": tool.description, "parameters": tool.parameters, "execute": execute}

    def to_model_format(self) -> dict[str, dict[str, Any]]:
        return {tool.name: self._wrap(tool, self.gate) for tool in self.get_active_tools()}

    def to_model_format_for_subagent(self, exclude_tools: set[str] | None = None) -> dict[str, dict[str, Any]]:
        return {
            tool.name: self._wrap(tool, self.subagent_gate)
            for tool in self.get_active_tools()
            if not exclude_tools or tool.name not in exclude_tools
        }


def truncate_result(text: str, max_chars: int = DEFAULT_MAX_RESULT_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    head_size = int(max_chars * 0.6)
    tail_size = max_chars - head_size
    dropped = len(text) - head_size - tail_size
    return f"{text[:head_size]}\n\n... [省略 {dropped} 字符] ...\n\n{text[-tail_size:]}"


def normalize_mcp_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]", "_", value)
    return normalized[:64] or "unnamed"


def persist_or_truncate_result(text: str, max_chars: int, tool_name: str) -> str:
    if len(text) <= max_chars:
        return text
    output_dir = current_workdir() / ".task_outputs/tool-results"
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", tool_name)[:80] or "tool"
        path = output_dir / f"{safe_name}-{int(time.time() * 1000)}-{secrets.token_hex(3)}.txt"
        path.write_text(text, encoding="utf-8")
        preview = truncate_result(text, max_chars)
        return f'<persisted-output path="{path.resolve()}" chars="{len(text)}">\n{preview}'
    except OSError:
        return truncate_result(text, max_chars)
