from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path

WORKING_DIRECTORY: ContextVar[Path | None] = ContextVar("working_directory", default=None)


def current_workdir() -> Path:
    return (WORKING_DIRECTORY.get() or Path.cwd()).resolve()


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (current_workdir() / path).resolve()
