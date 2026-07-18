from __future__ import annotations

import json
import time
from dataclasses import dataclass

from harness.agent.detection import detect, record_call, record_result, reset_history
from harness.agent.retry import calculate_delay, is_prompt_too_long, is_retryable, retry_after_ms, sleep
from harness.context.compressor import microcompact, reactive_compact, snip_compact, summarize
from harness.context.defense import apply_defense
from harness.memory.automation import consolidate_memories, extract_memories, load_relevant_memories
from harness.memory.store import MemoryStore
from harness.tools.registry import ToolRegistry
from harness.types import Message, Model
from harness.usage.tracker import UsageTracker, normalize_usage

MAX_STEPS = 15
MAX_RETRIES = 3
TOKEN_BUDGET = 15_000


@dataclass(slots=True)
class BudgetState:
    used: int = 0
    limit: int = TOKEN_BUDGET


@dataclass(slots=True)
class ContextState:
    summary: str = ""


async def prepare_context(
    model: Model,
    messages: list[Message],
    timestamps: dict[int, int],
    state: ContextState,
) -> None:
    original_length = len(messages)
    defense = apply_defense(messages, timestamps)
    compacted, cleared = microcompact(snip_compact(defense.messages))
    summarized = await summarize(model, compacted, state.summary)
    messages[:] = summarized.messages
    state.summary = summarized.summary

    if summarized.compressed_count or len(messages) != original_length:
        now = int(time.time() * 1000)
        timestamps.clear()
        timestamps.update({index: now for index in range(len(messages))})

    if defense.truncated or defense.compacted or defense.soft_pruned or defense.hard_pruned:
        print(
            "  [Context Defense] "
            f"截断 {defense.truncated}，预算清理 {defense.compacted}，"
            f"软修剪 {defense.soft_pruned}，硬清除 {defense.hard_pruned}"
        )
    if cleared:
        print(f"  [Microcompact] 清理了 {cleared} 个旧工具结果")
    if summarized.compressed_count:
        print(f"  [Summarization] 压缩了 {summarized.compressed_count} 条历史消息")


async def agent_loop(
    model: Model,
    registry: ToolRegistry,
    messages: list[Message],
    system: str,
    tracker: UsageTracker | None = None,
    budget: BudgetState | None = None,
    timestamps: dict[int, int] | None = None,
    context_state: ContextState | None = None,
    memory_store: MemoryStore | None = None,
    *,
    max_steps: int = MAX_STEPS,
) -> None:
    budget = budget or BudgetState()
    if budget.used > budget.limit:
        print("\n[Token 预算已耗尽，本轮未调用模型]")
        return
    runtime_system = system
    if memory_store:
        relevant = await load_relevant_memories(model, memory_store, messages)
        if relevant:
            runtime_system = f"{system}\n\n[与当前任务相关的长期记忆]\n\n{relevant}"
    if timestamps is not None:
        await prepare_context(model, messages, timestamps, context_state or ContextState())
    reset_history()
    step = 0
    rounds_since_todo = 0
    max_output_tokens = 8_000
    output_escalated = False
    continuation_count = 0
    reactive_attempted = False
    consecutive_overload = 0
    completed_turn = False
    result = None
    should_break = False

    def charge_usage(result: object) -> bool:
        usage = normalize_usage(getattr(result, "usage", None))
        record = tracker.record(model.model_id, usage) if tracker else None
        budget.used += usage.input_tokens + usage.output_tokens + usage.cache_read_tokens + usage.cache_write_tokens
        if record and (usage.cache_read_tokens or usage.cache_write_tokens):
            detail = (
                f"read {usage.cache_read_tokens}" if usage.cache_read_tokens else f"write {usage.cache_write_tokens}"
            )
            print(f"  [cache] {detail} tokens · 本步 ${record.cost:.5f}")
        percent = round(budget.used / budget.limit * 100) if budget.limit else 100
        print(f"  [Token] {budget.used}/{budget.limit} ({percent}%)")
        if budget.used > budget.limit:
            print("\n[Token 预算耗尽，强制停止]")
            return True
        return False

    while step < max_steps:
        step += 1
        notifications = registry.collect_notifications()
        if notifications:
            index = len(messages)
            messages.append({"role": "user", "content": "\n\n".join(notifications)})
            if timestamps is not None:
                timestamps[index] = int(time.time() * 1000)
        print(f"\n--- Step {step} ---")
        has_tool_call = should_break = False
        full_text = ""
        result = None
        for attempt in range(1, MAX_RETRIES + 2):
            has_tool_call = should_break = False
            received_delta = False
            attempt_text = ""

            def on_text_delta(text: str) -> None:
                nonlocal attempt_text, received_delta
                received_delta = True
                attempt_text += text
                print(text, end="", flush=True)

            try:
                result = await model.run_step(
                    system=runtime_system,
                    messages=messages,
                    tools=registry.to_model_format(),
                    on_text_delta=on_text_delta,
                    max_output_tokens=max_output_tokens,
                )
                if charge_usage(result):
                    result = None
                    break
                consecutive_overload = 0
                if result.finish_reason in {"length", "max_tokens"}:
                    if not output_escalated:
                        output_escalated = True
                        max_output_tokens = 64_000
                        print("  [恢复] 输出截断，提升输出上限后重试")
                        continue
                    if continuation_count < MAX_RETRIES:
                        messages.extend(result.messages)
                        messages.append(
                            {
                                "role": "user",
                                "content": "Output token limit hit. Resume directly — no apology or recap. Pick up mid-thought.",
                            }
                        )
                        continuation_count += 1
                        print(f"  [恢复] 续写截断输出 ({continuation_count}/{MAX_RETRIES})")
                        if attempt == MAX_RETRIES + 1:
                            result = None
                        continue
                continuation_count = 0
                full_text = attempt_text
                for part in result.parts:
                    if part.type == "text-delta":
                        if not received_delta:
                            print(part.text, end="", flush=True)
                            full_text += part.text
                    elif part.type == "tool-call":
                        has_tool_call = True
                        print(f"  [调用: {part.tool_name}({json.dumps(part.input, ensure_ascii=False)})]")
                        detection = detect(part.tool_name, part.input)
                        if detection["stuck"]:
                            print(f"  {detection['message']}")
                            if detection["level"] == "critical":
                                should_break = True
                            else:
                                reminder_index = len(messages)
                                messages.append(
                                    {
                                        "role": "user",
                                        "content": f"[系统提醒] {detection['message']}。请换一个思路解决问题，不要重复同样的操作。",
                                    }
                                )
                                if timestamps is not None:
                                    timestamps[reminder_index] = int(time.time() * 1000)
                        record_call(part.tool_name, part.input)
                    elif part.type == "tool-result":
                        output = (
                            part.output if isinstance(part.output, str) else json.dumps(part.output, ensure_ascii=False)
                        )
                        preview = output[:120] + "..." if len(output) > 120 else output
                        print(f"  [结果: {part.tool_name}] {preview}")
                        record_result(part.tool_name, part.input, part.output)
                break
            except Exception as error:
                if is_prompt_too_long(error) and not reactive_attempted:
                    messages[:] = reactive_compact(messages)
                    reactive_attempted = True
                    if timestamps is not None:
                        now = int(time.time() * 1000)
                        timestamps.clear()
                        timestamps.update({index: now for index in range(len(messages))})
                    print("  [恢复] 上下文超限，执行 reactive compact 后重试")
                    continue
                if attempt > MAX_RETRIES or not is_retryable(error):
                    raise
                if "529" in str(error):
                    consecutive_overload += 1
                    switch = getattr(model, "switch_to_fallback", None)
                    if consecutive_overload >= 3 and callable(switch) and switch():
                        print(f"  [恢复] 服务过载，切换到备用模型 {model.model_id}")
                        consecutive_overload = 0
                delay = retry_after_ms(error) or calculate_delay(attempt)
                print(f"  [重试] 第 {attempt}/{MAX_RETRIES} 次，{delay}ms 后...")
                await sleep(delay)
        if result is None:
            break
        if should_break:
            print("\n[循环检测触发，Agent 已停止]")
            break
        before = len(messages)
        messages.extend(result.messages)
        if timestamps is not None:
            now = int(time.time() * 1000)
            timestamps.update({index: now for index in range(before, len(messages))})
        if any(part.type == "tool-call" and part.tool_name == "compact" for part in result.parts):
            state = context_state or ContextState()
            compacted = await summarize(model, messages, state.summary, force=True)
            messages[:] = compacted.messages
            state.summary = compacted.summary
            if timestamps is not None:
                now = int(time.time() * 1000)
                timestamps.clear()
                timestamps.update({index: now for index in range(len(messages))})
            print(f"  [Compaction] 主动压缩了 {compacted.compressed_count} 条消息")
        if not has_tool_call:
            late_notifications = registry.collect_notifications()
            if late_notifications:
                index = len(messages)
                messages.append({"role": "user", "content": "\n\n".join(late_notifications)})
                if timestamps is not None:
                    timestamps[index] = int(time.time() * 1000)
                continue
            if registry.hook_pipeline:
                stop = await registry.hook_pipeline.run_stop(messages)
                if stop.action in {"block", "continue"}:
                    index = len(messages)
                    messages.append({"role": "user", "content": stop.reason or "继续执行剩余工作。"})
                    if timestamps is not None:
                        timestamps[index] = int(time.time() * 1000)
                    continue
            if memory_store:
                extracted = await extract_memories(model, memory_store, messages)
                consolidated = await consolidate_memories(model, memory_store)
                if extracted or consolidated:
                    print(f"  [Memory] 新增 {extracted}，整理合并 {consolidated}")
            if full_text:
                print()
            completed_turn = True
            break
        if any(part.type == "tool-call" and part.tool_name == "todo_write" for part in result.parts):
            rounds_since_todo = 0
        else:
            rounds_since_todo += 1
        if rounds_since_todo >= 3:
            index = len(messages)
            messages.append({"role": "user", "content": "<reminder>请更新 todo_write 清单后再继续。</reminder>"})
            if timestamps is not None:
                timestamps[index] = int(time.time() * 1000)
            rounds_since_todo = 0
        print("  → 继续下一步...")
    if step >= max_steps and not completed_turn and result is not None and not should_break:
        print("\n[达到最大步数]")
