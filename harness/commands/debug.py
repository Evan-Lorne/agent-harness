from __future__ import annotations

import time

from harness.commands import CommandContext, CommandHandler
from harness.context.defense import apply_defense, estimate_message_tokens
from harness.mock_model import set_cache_enabled


async def simulate(command: str, context: CommandContext) -> bool:
    if command not in {"模拟长对话", "sim"}:
        return False
    now = int(time.time() * 1000)
    print("\n[模拟] 注入 20 条历史消息（含大量工具结果）...")
    for index in range(5):
        age = (20 - index * 4) * 60 * 1000
        start = len(context.messages)
        context.messages.extend(
            [
                {"role": "user", "content": f"第 {index + 1} 轮：帮我读文件 file-{index}.py"},
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool-call",
                            "toolCallId": f"sim-{index}",
                            "toolName": "read_file",
                            "input": {"path": f"file-{index}.py"},
                        }
                    ],
                },
                {
                    "role": "tool",
                    "content": [
                        {
                            "type": "tool-result",
                            "toolCallId": f"sim-{index}",
                            "toolName": "read_file",
                            "output": {
                                "type": "text",
                                "value": f"# file-{index}.py\n" + "def handler():\n    pass\n" * 200,
                            },
                        }
                    ],
                },
                {"role": "assistant", "content": [{"type": "text", "text": f"文件 file-{index}.py 的内容已读取。"}]},
            ]
        )
        for offset in range(4):
            context.timestamps[start + offset] = now - age
    print(f"[模拟完成] {len(context.messages)} 条消息, ~{estimate_message_tokens(context.messages)} tokens\n")
    return True


async def defend(command: str, context: CommandContext) -> bool:
    if command not in {"执行防线", "defend"}:
        return False
    before = estimate_message_tokens(context.messages)
    result = apply_defense(context.messages, context.timestamps)
    context.messages[:] = result.messages
    print(f"\n--- 执行三层防线 ---\n  [Layer 2] 截断: {result.truncated} 条, 预算清理: {result.compacted} 条")
    print(f"  [Layer 3] 软修剪: {result.soft_pruned}, 硬清除: {result.hard_pruned}")
    print(f"  [结果] ~{before} → ~{result.token_estimate} tokens (节省 {before - result.token_estimate})\n")
    return True


async def status(command: str, context: CommandContext) -> bool:
    if command not in {"status", "查看状态"}:
        return False
    print(
        f"\n[状态] {len(context.messages)} 条消息, ~{estimate_message_tokens(context.messages)} tokens, {len(context.memory_store.list())} 条记忆\n"
    )
    return True


async def cache(command: str, _context: CommandContext) -> bool:
    if command in {"/cache off", "cache off"}:
        set_cache_enabled(False)
        print("\n  已关闭 cache 模拟\n")
        return True
    if command in {"/cache on", "cache on"}:
        set_cache_enabled(True)
        print("\n  已开启 cache 模拟\n")
        return True
    return False


debug_commands: list[CommandHandler] = [simulate, defend, status, cache]
