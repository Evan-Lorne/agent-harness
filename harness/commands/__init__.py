from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from harness.agent.loop import BudgetState, ContextState
from harness.context.prompt_builder import PromptBuilder, PromptContext
from harness.memory.store import MemoryStore
from harness.session.store import SessionStore
from harness.tools.registry import ToolRegistry
from harness.types import Message, Model
from harness.usage.tracker import UsageTracker

CommandHandler = Callable[[str, "CommandContext"], Awaitable[bool]]


@dataclass(slots=True)
class CommandContext:
    messages: list[Message]
    timestamps: dict[int, int]
    registry: ToolRegistry
    builder: PromptBuilder
    tracker: UsageTracker
    session_store: SessionStore
    model: Model
    make_prompt_context: Callable[[], PromptContext]
    memory_store: MemoryStore
    budget: BudgetState
    context_state: ContextState
    vector_store: Any = None


def create_dispatcher(handlers: list[CommandHandler]) -> CommandHandler:
    async def dispatch(command: str, context: CommandContext) -> bool:
        for handler in handlers:
            if await handler(command, context):
                return True
        return False

    return dispatch
