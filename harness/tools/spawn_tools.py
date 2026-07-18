from __future__ import annotations

from collections.abc import Callable

from harness.agents.registry import SubAgentRegistry
from harness.agents.spawn import SpawnContext, spawn_agent, spawn_parallel
from harness.agents.types import SpawnRequest
from harness.tools.registry import ToolDefinition


def create_spawn_tool(
    agent_registry: SubAgentRegistry, get_spawn_context: Callable[[], SpawnContext]
) -> ToolDefinition:
    async def execute(args: dict) -> str:
        context = get_spawn_context()
        if args.get("tasks"):
            results = await spawn_parallel([SpawnRequest(task) for task in args["tasks"]], context)
            return "\n\n---\n\n".join(
                f"## 子 Agent {index}: {task[:40]}\n\n{result}" for index, (task, result) in enumerate(results, 1)
            )
        if args.get("task"):
            return await spawn_agent(SpawnRequest(args["task"]), context)
        return "需要提供 task 或 tasks 参数"

    return ToolDefinition(
        "spawn_agent",
        "派一个子 Agent 去执行任务。子 Agent 有独立的上下文，完成后返回结果摘要。支持同时派多个子 Agent 并行执行。",
        {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "单个任务描述（与 tasks 二选一）"},
                "tasks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "多个任务描述，并行执行（与 task 二选一）",
                },
            },
        },
        execute,
        False,
        True,
    )
