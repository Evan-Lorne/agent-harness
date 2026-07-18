from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(slots=True)
class SubAgentConfig:
    max_spawn_depth: int = 1
    max_concurrent: int = 3
    default_timeout: int = 60_000


@dataclass(slots=True)
class SpawnRequest:
    task: str
    tools: list[str] | None = None
    timeout: int | None = None


@dataclass(slots=True)
class SubAgentRun:
    id: str
    task: str
    status: Literal["running", "completed", "error", "timeout"]
    depth: int
    started_at: str
    finished_at: str | None = None
    result: str | None = None
    error: str | None = None
