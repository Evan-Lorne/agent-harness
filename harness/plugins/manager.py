from __future__ import annotations

import inspect
import os
from dataclasses import dataclass
from typing import Any

from harness.plugins.types import PluginApi, PluginDefinition
from harness.tools.registry import ToolDefinition, ToolRegistry


@dataclass(slots=True)
class LoadedPlugin:
    definition: PluginDefinition
    tools: list[str]


class PluginManager:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry
        self.plugins: dict[str, LoadedPlugin] = {}

    async def load(self, definition: PluginDefinition, config: dict[str, Any] | None = None) -> list[str]:
        if definition.name in self.plugins:
            raise ValueError(f'插件 "{definition.name}" 已加载')
        resolved = self._resolve_env_vars({**definition.config, **(config or {})})
        registered: list[str] = []

        def register_tools(tools: list[ToolDefinition]) -> None:
            for tool in tools:
                name = f"{definition.name}__{tool.name}"
                if self.registry.get(name):
                    raise ValueError(f'工具 "{name}" 已注册')
                self.registry.register(
                    ToolDefinition(
                        name,
                        f"[Plugin:{definition.name}] {tool.description}",
                        tool.parameters,
                        tool.execute,
                        tool.is_concurrency_safe,
                        tool.is_read_only,
                        tool.max_result_chars,
                        tool.profile,
                        tool.should_defer,
                        tool.search_hint,
                        tool.is_destructive,
                    )
                )
                registered.append(name)

        api = PluginApi(
            register_tools, lambda: resolved, lambda message: print(f"  [plugin:{definition.name}] {message}")
        )
        try:
            result = definition.activate(api)
            if inspect.isawaitable(result):
                await result
        except BaseException:
            for name in registered:
                self.registry.unregister(name)
            raise
        self.plugins[definition.name] = LoadedPlugin(definition, registered)
        return registered

    async def unload(self, name: str) -> bool:
        plugin = self.plugins.get(name)
        if not plugin:
            return False
        if plugin.definition.destroy:
            result = plugin.definition.destroy()
            if inspect.isawaitable(result):
                await result
        for tool in plugin.tools:
            self.registry.unregister(tool)
        del self.plugins[name]
        return True

    async def unload_all(self) -> None:
        for name in list(self.plugins):
            await self.unload(name)

    def get(self, name: str) -> LoadedPlugin | None:
        return self.plugins.get(name)

    def list(self) -> list[LoadedPlugin]:
        return list(self.plugins.values())

    @staticmethod
    def _resolve_env_vars(config: dict[str, Any]) -> dict[str, Any]:
        resolved: dict[str, Any] = {}
        for key, value in config.items():
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                resolved[key] = os.getenv(value[2:-1], "")
            else:
                resolved[key] = value
        return resolved
