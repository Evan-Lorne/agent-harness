from __future__ import annotations

import re
from typing import cast

from harness.commands import CommandContext, CommandHandler
from harness.security.hooks import HookPipeline
from harness.security.roles import Role
from harness.tools.registry import ToolRegistry


def create_security_commands(registry: ToolRegistry, hooks: HookPipeline) -> list[CommandHandler]:
    async def handler(command: str, _context: CommandContext) -> bool:
        match = re.match(r"^/role(?:\s+(owner|collaborator|guest))?$", command)
        if match:
            if match.group(1):
                registry.set_role(cast(Role, match.group(1)))
            print(f"\n[security] 当前角色: {registry.get_role()}，可用工具: {len(registry.get_active_tools())} 个\n")
            return True
        if command != "/hooks":
            return False
        values = hooks.list()
        print("\n[hooks]")
        labels = {
            "user": "UserPromptSubmit Hooks",
            "pre": "PreToolUse Hooks",
            "post": "PostToolUse Hooks",
            "stop": "Stop Hooks",
        }
        for phase in ("user", "pre", "post", "stop"):
            if values[phase]:
                print(f"  {labels[phase]}:")
                for name in values[phase]:
                    print(f"    - {name}")
        if not any(values.values()):
            print("  没有注册的 Hook")
        print()
        return True

    return [handler]
