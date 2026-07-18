from __future__ import annotations

import re
from typing import Any

from harness.commands import CommandContext, CommandHandler
from harness.plugins.manager import PluginManager
from harness.plugins.types import PluginDefinition


def create_plugin_commands(
    manager: PluginManager, available: dict[str, PluginDefinition], configured: dict[str, dict[str, Any]]
) -> list[CommandHandler]:
    async def handler(command: str, _context: CommandContext) -> bool:
        if command in {"/plugin", "/plugin list"}:
            loaded = manager.list()
            unloaded = [(name, definition) for name, definition in available.items() if manager.get(name) is None]
            print("\n[plugins]")
            if loaded:
                print("  已加载：")
                for plugin in loaded:
                    print(
                        f"    {plugin.definition.name} v{plugin.definition.version} — {plugin.definition.description}\n      工具: {', '.join(plugin.tools)}"
                    )
            if unloaded:
                print("  可加载：")
                for name, definition in unloaded:
                    print(f"    {name} v{definition.version} — {definition.description}")
            if not loaded and not unloaded:
                print("  没有可用的插件。")
            print()
            return True
        match = re.match(r"^/plugin\s+(load|unload)\s+(\S+)$", command)
        if not match:
            return False
        action, name = match.groups()
        if action == "unload":
            print(
                f"\n[plugins] {'已卸载 ' + name + '，相关工具已移除' if await manager.unload(name) else name + ' 未加载'}\n"
            )
            return True
        definition = available.get(name)
        if not definition:
            print(f"\n[plugins] 找不到插件: {name}\n")
        elif manager.get(name):
            print(f"\n[plugins] {name} 已经加载了\n")
        else:
            try:
                tools = await manager.load(definition, configured.get(name))
                print(
                    f"\n[plugins] 已加载 {name}，注册了 {len(tools)} 个工具：\n"
                    + "\n".join(f"    {tool}" for tool in tools)
                    + "\n"
                )
            except Exception as error:
                print(f"\n[plugins] 加载 {name} 失败: {error}\n")
        return True

    return [handler]
