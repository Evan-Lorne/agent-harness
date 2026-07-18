from __future__ import annotations

import time

from harness.agent.loop import agent_loop
from harness.commands import CommandContext, CommandHandler

DREAM_PROMPT = """请对记忆库做一次完整的整理（dream），按以下四个阶段执行：

**阶段 1：定位** — 用 memory lint 扫描全库（lint 结果已包含内容预览和问题清单，不需要再逐条 read）。
**阶段 2：整理** — 根据 lint 报告直接操作：
  - 路径过期且长期未用的，直接 memory delete（传 filename）删掉
  - 同名重复的，用 memory save 保存合并后的版本（同名自动覆盖），再 delete 多余的
  - 内容仍然有效但描述不准确的，用 memory save 覆盖更新
**阶段 3：报告** — 用一段文字总结这次整理做了什么。

注意：memory 的 read 和 delete 都需要传 filename 参数，不是 name。lint 报告里已经有 filename 了，直接用。"""


async def dream_handler(command: str, context: CommandContext) -> bool:
    if command not in {"/dream", "dream"}:
        return False
    print("\n[dream] 开始记忆整理...")
    user_message = {"role": "user", "content": DREAM_PROMPT}
    context.messages.append(user_message)
    context.timestamps[len(context.messages) - 1] = int(time.time() * 1000)
    context.session_store.append(user_message)
    await agent_loop(
        context.model,
        context.registry,
        context.messages,
        context.builder.build(context.make_prompt_context()),
        context.tracker,
        context.budget,
        context.timestamps,
        context.context_state,
    )
    context.session_store.replace_all(context.messages)
    print("  [dream 完成]\n")
    return True


dream_commands: list[CommandHandler] = [dream_handler]
