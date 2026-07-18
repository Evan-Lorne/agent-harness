from __future__ import annotations

import json
import os

from harness.commands import CommandContext, CommandHandler
from harness.context.view import build_context_snapshot, render_context_view, render_usage_view


async def context_handler(command: str, context: CommandContext) -> bool:
    if command not in {"/context", "context"}:
        return False
    system = context.builder.build(context.make_prompt_context())
    tool_chars = sum(
        len(tool.name) + len(tool.description) + len(json.dumps(tool.parameters, ensure_ascii=False))
        for tool in context.registry.get_active_tools()
    )
    snapshot = build_context_snapshot(
        model_name="GPT Plus" if os.getenv("OPENAI_API_KEY") else "Mock Model (开发用)",
        model_id=context.model.model_id,
        window_tokens=1_000_000,
        system_prompt_chars=len(system),
        tool_description_chars=tool_chars,
        memory_chars=len(context.memory_store.build_prompt_section()),
        skills_chars=0,
        messages=context.messages,
    )
    print(render_context_view(snapshot))
    return True


async def usage_handler(command: str, context: CommandContext) -> bool:
    if command not in {"/usage", "usage"}:
        return False
    print(render_usage_view(context.tracker))
    return True


context_commands: list[CommandHandler] = [context_handler, usage_handler]
