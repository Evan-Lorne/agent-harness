from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

TaskStatus = Literal["pending", "in_progress", "completed"]


@dataclass(slots=True)
class Task:
    id: str
    subject: str
    description: str = ""
    status: TaskStatus = "pending"
    owner: str | None = None
    blocked_by: list[str] = field(default_factory=list)
    worktree: str | None = None
