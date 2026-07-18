from __future__ import annotations

import re
import time

from harness.agent.loop import agent_loop
from harness.commands import CommandContext, CommandHandler
from harness.skills.loader import SkillLoader


def create_skill_commands(loader: SkillLoader, active_skills: set[str]) -> list[CommandHandler]:
    async def handler(command: str, context: CommandContext) -> bool:
        if command in {"/skill", "/skill list", "skill list"}:
            skills = loader.list()
            if not skills:
                print("\n[skills] 没有找到任何 skill。在 .skills/ 目录下创建 skill-name/SKILL.md 即可。\n")
            else:
                print(f"\n[skills] 共 {len(skills)} 个可用：")
                for skill in skills:
                    print(f"  /{skill.name} — {skill.description}{' ✓ 已激活' if skill.name in active_skills else ''}")
                print()
            return True
        match = re.match(r"^/skill\s+(load|unload)\s+(\S+)$", command)
        if match:
            action, name = match.groups()
            skill = loader.get(name)
            if action == "load" and not skill:
                print(f"\n[skills] 找不到 skill: {name}\n")
            elif action == "load":
                assert skill is not None
                active_skills.add(name)
                print(f"\n[skills] 已激活: {name} — {skill.description}\n")
            elif name not in active_skills:
                print(f"\n[skills] {name} 未激活\n")
            else:
                active_skills.remove(name)
                print(f"\n[skills] 已卸载: {name}\n")
            return True
        if not command.startswith("/"):
            return False
        parts = command[1:].split()
        skill = loader.get(parts[0]) if parts else None
        if not skill:
            return False
        active_skills.add(skill.name)
        print(f"\n[skills] 激活 {skill.name}，开始执行...")
        arguments = " ".join(parts[1:])
        # The system prompt already includes the Skill body and root path; the user message only carries the requested review target.
        content = f"执行 {skill.name} Skill。用户指令: {arguments}" if arguments else f"执行 {skill.name} Skill。"
        user_message = {"role": "user", "content": content}
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
        return True

    return [handler]
