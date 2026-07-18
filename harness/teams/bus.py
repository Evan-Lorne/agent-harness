from __future__ import annotations

import json
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class MessageBus:
    def __init__(self, base_dir: str | Path = ".") -> None:
        self.directory = Path(base_dir) / ".team/inboxes"
        self.lock = threading.RLock()

    @staticmethod
    def validate_name(name: str) -> None:
        if not NAME_RE.fullmatch(name):
            raise ValueError("非法队友名称")

    def _path(self, name: str) -> Path:
        self.validate_name(name)
        return self.directory / f"{name}.jsonl"

    def send(
        self,
        sender: str,
        recipient: str,
        content: str,
        message_type: str = "message",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self.lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            message = {
                "from": sender,
                "to": recipient,
                "type": message_type,
                "content": content,
                "metadata": metadata or {},
                "timestamp": time.time(),
            }
            with self._path(recipient).open("a", encoding="utf-8") as file:
                file.write(json.dumps(message, ensure_ascii=False) + "\n")

    def read(self, recipient: str) -> list[dict[str, Any]]:
        with self.lock:
            path = self._path(recipient)
            claimed = path.with_name(f".{path.name}.{secrets.token_hex(4)}.reading")
            try:
                path.replace(claimed)
            except FileNotFoundError:
                return []
            try:
                lines = claimed.read_text(encoding="utf-8").splitlines()
            finally:
                claimed.unlink(missing_ok=True)
        values = []
        for line in lines:
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    values.append(value)
            except json.JSONDecodeError:
                continue
        return values
