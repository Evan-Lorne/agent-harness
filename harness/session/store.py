from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from harness.types import Message

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class SessionStore:
    def __init__(self, session_id: str = "default", base_dir: str | Path = ".") -> None:
        if not SESSION_ID_RE.fullmatch(session_id):
            raise ValueError("非法会话 ID")
        self.session_id = session_id
        self.directory = Path(base_dir) / ".sessions"
        self.directory.mkdir(parents=True, exist_ok=True)

    @property
    def file_path(self) -> Path:
        return self.directory / f"{self.session_id}.jsonl"

    def append(self, message: Message) -> None:
        entry = {
            "type": "message",
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "message": message,
        }
        with self.file_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")

    def append_all(self, messages: list[Message]) -> None:
        for message in messages:
            self.append(message)

    def replace_all(self, messages: list[Message]) -> None:
        temporary = self.file_path.with_suffix(".jsonl.tmp")
        with temporary.open("w", encoding="utf-8") as file:
            for message in messages:
                entry = {
                    "type": "message",
                    "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    "message": message,
                }
                file.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
        temporary.replace(self.file_path)

    def load(self) -> list[Message]:
        if not self.file_path.exists():
            return []
        messages: list[Message] = []
        for line in self.file_path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
                if entry.get("type") == "message":
                    messages.append(entry["message"])
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        return messages

    def exists(self) -> bool:
        return self.file_path.exists()
