from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MemoryType = Literal["user", "feedback", "project", "reference"]


@dataclass(slots=True)
class MemoryEntry:
    name: str
    description: str
    type: MemoryType
    content: str
    file_path: str
    last_write_at: int | None = None
    last_read_at: int | None = None
