from __future__ import annotations

import asyncio

from harness.tools.registry import ToolDefinition
from harness.worktrees.manager import WorktreeManager


def create_worktree_tools(manager: WorktreeManager) -> list[ToolDefinition]:
    async def create(args: dict) -> str:
        try:
            return await asyncio.to_thread(manager.create, args["name"], args.get("task_id", ""))
        except (KeyError, ValueError) as error:
            return f"创建失败: {error}"

    async def remove(args: dict) -> str:
        try:
            return await asyncio.to_thread(manager.remove, args["name"], args.get("discard_changes", False))
        except (KeyError, ValueError) as error:
            return f"删除失败: {error}"

    async def keep(args: dict) -> str:
        try:
            return await asyncio.to_thread(manager.keep, args["name"])
        except (KeyError, ValueError) as error:
            return f"保留失败: {error}"

    return [
        ToolDefinition(
            "create_worktree",
            "为任务创建独立 Git worktree。",
            {
                "type": "object",
                "properties": {"name": {"type": "string"}, "task_id": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            },
            create,
        ),
        ToolDefinition(
            "remove_worktree",
            "删除无改动的 worktree；丢弃改动必须显式确认。",
            {
                "type": "object",
                "properties": {"name": {"type": "string"}, "discard_changes": {"type": "boolean"}},
                "required": ["name"],
                "additionalProperties": False,
            },
            remove,
            is_destructive=True,
        ),
        ToolDefinition(
            "keep_worktree",
            "保留 worktree 及分支供人工审查。",
            {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            },
            keep,
        ),
    ]
