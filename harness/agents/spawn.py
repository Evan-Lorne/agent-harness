from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from harness.agents.registry import SubAgentRegistry
from harness.agents.types import SpawnRequest, SubAgentRun
from harness.tools.registry import ToolRegistry
from harness.types import Message, Model, content_to_text

EXCLUDED_TOOLS = {"spawn_agent"}
AGENT_COLORS = ["\033[36m", "\033[33m", "\033[35m", "\033[32m", "\033[34m"]
RESET = "\033[0m"


@dataclass(slots=True)
class SpawnContext:
    model: Model
    registry: ToolRegistry
    agent_registry: SubAgentRegistry
    build_system: Callable[[], str]
    current_depth: int = 0


def _tag(index: int, run_id: str) -> str:
    return f"{AGENT_COLORS[index % len(AGENT_COLORS)]}[Agent-{index + 1}:{run_id}]{RESET}"


async def spawn_agent(request: SpawnRequest, context: SpawnContext, index: int = 0) -> str:
    allowed, reason = context.agent_registry.can_spawn(context.current_depth)
    if not allowed:
        return f"[spawn] 拒绝: {reason}"
    run_id = context.agent_registry.generate_id()
    tag = _tag(index, run_id)
    context.agent_registry.register(
        SubAgentRun(
            run_id,
            request.task,
            "running",
            context.current_depth + 1,
            datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )
    )
    timeout = (request.timeout or context.agent_registry.config.default_timeout) / 1000
    print(f"  {tag} 启动: {request.task[:50]}")

    async def run() -> str:
        messages: list[Message] = [{"role": "user", "content": request.task}]
        system = (
            context.build_system()
            + "\n\n[子 Agent 模式] 你是一个被派出去执行具体任务的子 Agent。直接完成任务并输出结论，保持简洁。\n当你需要同时获取多个独立信息时，尽可能在一次回复中并行调用多个工具。"
        )
        tools = context.registry.to_model_format_for_subagent(EXCLUDED_TOOLS)
        for step in range(1, 31):
            is_last = step == 30
            print(f"  {tag} Step {step}/30{' (总结)' if is_last else ''}")
            if is_last:
                messages.append(
                    {"role": "user", "content": "你已经收集了足够的信息。请直接输出文字总结，不要再调用任何工具。"}
                )
            result = await context.model.run_step(
                system=system, messages=messages, tools=tools, tool_choice="none" if is_last else "auto"
            )
            messages.extend(result.messages)
            if not any(part.type == "tool-call" for part in result.parts):
                break
        assistant = next((message for message in reversed(messages) if message.get("role") == "assistant"), None)
        return content_to_text(assistant.get("content")) if assistant else "(无输出)"

    try:
        result = await asyncio.wait_for(run(), timeout)
        context.agent_registry.complete(run_id, result)
        print(f"  {tag} 完成 ✓ ({len(result)} 字符)")
        return result
    except TimeoutError:
        error = f"执行超时 ({timeout:g}s)"
        context.agent_registry.fail(run_id, error, timeout=True)
        print(f"  {tag} 超时 ✗: {error}")
        return f"[sub-agent 执行失败] {error}"
    except Exception as exception:
        error = str(exception)
        context.agent_registry.fail(run_id, error)
        print(f"  {tag} 失败 ✗: {error}")
        return f"[sub-agent 执行失败] {error}"


async def spawn_parallel(requests: list[SpawnRequest], context: SpawnContext) -> list[tuple[str, str]]:
    available = context.agent_registry.config.max_concurrent - len(context.agent_registry.get_active_runs())
    if available <= 0:
        return [
            (request.task, f"[spawn] 拒绝: 已达最大并发数 {context.agent_registry.config.max_concurrent}")
            for request in requests
        ]
    running, rejected = requests[:available], requests[available:]
    print(f"\n  ┌─ 派发 {len(running)} 个子 Agent 并行执行 ─┐")
    values = await asyncio.gather(*(spawn_agent(request, context, index) for index, request in enumerate(running)))
    results = [(request.task, result) for request, result in zip(running, values, strict=True)]
    results.extend(
        (request.task, f"[spawn] 拒绝: 超出最大并发数 {context.agent_registry.config.max_concurrent}，本次未执行")
        for request in rejected
    )
    print(f"  └─ 全部完成 ({len(results)}/{len(requests)}) ─┘\n")
    return results
