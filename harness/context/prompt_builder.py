from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(slots=True)
class PromptContext:
    tool_count: int
    deferred_tool_summary: str
    session_message_count: int
    session_id: str


Pipe = Callable[[PromptContext], str | None]


class PromptBuilder:
    def __init__(self) -> None:
        self.pipes: list[tuple[str, Pipe]] = []
        self._last_values: tuple[str | None, ...] | None = None
        self._last_prompt = ""

    def pipe(self, name: str, function: Pipe) -> PromptBuilder:
        self.pipes.append((name, function))
        return self

    def build(self, context: PromptContext) -> str:
        values = tuple(function(context) for _, function in self.pipes)
        if values == self._last_values:
            return self._last_prompt
        self._last_values = values
        self._last_prompt = "\n\n".join(value for value in values if value is not None)
        return self._last_prompt

    def debug(self, context: PromptContext) -> None:
        print("\n=== Prompt Pipe Debug ===")
        for name, function in self.pipes:
            value = function(context)
            status = f"[ON] {len(value)} chars" if value is not None else "[OFF]"
            print(f"  {name}: {status}")
        print("========================\n")


def core_rules() -> Pipe:
    return lambda _context: (
        """你是 Agent Harness，一个有工具调用能力的 AI 助手。
你的行为准则：
- 先读文件再修改，不要凭记忆编辑
- 多步骤任务先用 todo_write 规划；跨会话工作用 create_task 等任务工具持久化
- 只有任务确实需要独立上下文时才派生子 Agent 或队友
- 不要加没被要求的功能
- 工具调用失败时，换一个思路而不是重复同样的操作
- 回答要简洁直接"""
    )


def tool_guide() -> Pipe:
    return lambda context: (
        f"你有 {context.tool_count} 个工具可用。需要操作本地文件时使用内置工具，需要访问外部服务时使用 MCP 工具。"
        if context.tool_count
        else None
    )


def deferred_tools() -> Pipe:
    return lambda context: (
        f"如果你需要的工具不在当前列表中，使用 tool_search 工具搜索。{context.deferred_tool_summary}"
        if context.deferred_tool_summary
        else None
    )


def session_context() -> Pipe:
    return lambda context: (
        f"[会话信息] 当前会话 {context.session_id}，已有 {context.session_message_count} 条历史消息。"
        if context.session_message_count
        else None
    )
