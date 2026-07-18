from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from harness.tools.registry import ToolDefinition


@dataclass(slots=True)
class PluginApi:
    register_tools: Callable[[list[ToolDefinition]], None]
    get_config: Callable[[], dict[str, Any]]
    log: Callable[[str], None]


@dataclass(slots=True)
class PluginDefinition:
    name: str
    version: str
    description: str
    activate: Callable[[PluginApi], None | Awaitable[None]]
    config: dict[str, Any] = field(default_factory=dict)
    destroy: Callable[[], None | Awaitable[None]] | None = None
