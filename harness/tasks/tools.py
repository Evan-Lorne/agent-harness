from __future__ import annotations

import json

from harness.tasks.store import TaskStore
from harness.tools.registry import ToolDefinition


def create_task_tools(store: TaskStore) -> list[ToolDefinition]:
    async def create(args: dict) -> str:
        try:
            task = store.create(args["subject"], args.get("description", ""), args.get("blockedBy", []))
            return json.dumps(store._to_dict(task), ensure_ascii=False)
        except (KeyError, ValueError) as error:
            return f"创建任务失败: {error}"

    async def list_tasks(_args: dict) -> str:
        tasks = store.list()
        return (
            "当前没有任务"
            if not tasks
            else "\n".join(
                f"[{task.status}] {task.id} — {task.subject} ({task.owner or 'unassigned'})" for task in tasks
            )
        )

    async def get(args: dict) -> str:
        try:
            task = store.get(args["id"])
        except (KeyError, ValueError) as error:
            return f"读取任务失败: {error}"
        return "任务不存在" if not task else json.dumps(store._to_dict(task), ensure_ascii=False, indent=2)

    async def claim(args: dict) -> str:
        try:
            task = store.claim(args["id"], args.get("owner", "agent"))
            return f"已认领 {task.id} ({task.subject})"
        except (KeyError, ValueError) as error:
            return f"认领失败: {error}"

    async def complete(args: dict) -> str:
        try:
            task, unlocked = store.complete(args["id"], args.get("owner"))
            suffix = f"\n已解锁: {', '.join(item.id for item in unlocked)}" if unlocked else ""
            return f"已完成 {task.id} ({task.subject}){suffix}"
        except (KeyError, ValueError) as error:
            return f"完成失败: {error}"

    id_schema = {
        "type": "object",
        "properties": {"id": {"type": "string"}},
        "required": ["id"],
        "additionalProperties": False,
    }
    return [
        ToolDefinition(
            "create_task",
            "创建可持久化任务，可通过 blockedBy 声明依赖。",
            {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "description": {"type": "string"},
                    "blockedBy": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["subject"],
                "additionalProperties": False,
            },
            create,
        ),
        ToolDefinition(
            "list_tasks",
            "列出任务及状态。",
            {"type": "object", "properties": {}, "additionalProperties": False},
            list_tasks,
            True,
            True,
        ),
        ToolDefinition("get_task", "读取一个任务的完整信息。", id_schema, get, True, True),
        ToolDefinition(
            "claim_task",
            "认领未被阻塞的任务。",
            {
                "type": "object",
                "properties": {"id": {"type": "string"}, "owner": {"type": "string"}},
                "required": ["id"],
                "additionalProperties": False,
            },
            claim,
        ),
        ToolDefinition(
            "complete_task",
            "完成已认领任务并报告新解锁任务。",
            {
                "type": "object",
                "properties": {"id": {"type": "string"}, "owner": {"type": "string"}},
                "required": ["id"],
                "additionalProperties": False,
            },
            complete,
        ),
    ]
