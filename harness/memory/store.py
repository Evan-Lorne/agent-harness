from __future__ import annotations

import re
import secrets
import shutil
import time
from pathlib import Path
from typing import Any

from harness.memory.search import SearchHit, bm25_search
from harness.memory.types import MemoryEntry
from harness.memory.validator import ValidationReport, lint_all

MEMORY_DIR = ".memory"
INDEX_FILE = "MEMORY.md"
MAX_INDEX_LINES = 200
MAX_FILE_CHARS = 4000
MEMORY_TYPES = {"user", "feedback", "project", "reference"}


class MemoryStore:
    def __init__(self, base_dir: str | Path = ".") -> None:
        self.base_dir = Path(base_dir)

    @property
    def memory_dir(self) -> Path:
        return self.base_dir / MEMORY_DIR

    @property
    def index_path(self) -> Path:
        return self.memory_dir / INDEX_FILE

    def init(self) -> None:
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            self._write_text(self.index_path, "# Memory Index\n")

    @staticmethod
    def _write_text(path: Path, content: str) -> None:
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
        try:
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def _file_path(self, filename: str) -> Path:
        if Path(filename).name != filename or not filename.endswith(".md") or filename == INDEX_FILE:
            raise ValueError("非法记忆文件名")
        path = self.memory_dir / filename
        if not path.resolve().is_relative_to(self.memory_dir.resolve()):
            raise ValueError("非法记忆文件名")
        return path

    @staticmethod
    def _serialize(entry: dict[str, Any]) -> tuple[str, str, str, str]:
        entry_type = str(entry.get("type", ""))
        if entry_type not in MEMORY_TYPES:
            raise ValueError(f"非法记忆类型: {entry_type}")
        name = " ".join(str(entry.get("name", "")).splitlines()).strip()
        if not name:
            raise ValueError("记忆名称不能为空")
        description = " ".join(str(entry.get("description", "")).splitlines()).strip()
        slug = re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9一-鿿]+", "-", name.lower())) or "memory"
        filename = f"{entry_type}_{slug}.md"
        now = int(time.time() * 1000)
        content = "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: {description}",
                f"type: {entry_type}",
                f"lastWriteAt: {now}",
                f"lastReadAt: {now}",
                "---",
                "",
                str(entry.get("content", "")),
            ]
        )
        return filename, content, name, description

    def save(self, entry: dict[str, Any]) -> str:
        self.init()
        filename, content, name, description = self._serialize(entry)
        self._write_text(self._file_path(filename), content)
        self._update_index(name, filename, description)
        return filename

    def _update_index(self, name: str, filename: str, description: str) -> None:
        lines = self.index_path.read_text(encoding="utf-8").split("\n")
        new_line = f"- [{name}]({filename}) — {description}"
        existing = next((index for index, line in enumerate(lines) if f"({filename})" in line), -1)
        if existing >= 0:
            lines[existing] = new_line
        else:
            if len(lines) >= MAX_INDEX_LINES:
                print(f"[memory] 索引已达 {MAX_INDEX_LINES} 行上限，移除最早的条目")
                first = next((index for index, line in enumerate(lines) if line.startswith("- ")), -1)
                if first >= 0:
                    lines.pop(first)
            lines.append(new_line)
        self._write_text(self.index_path, "\n".join(lines))

    def replace_all(self, entries: list[dict[str, Any]]) -> None:
        """Replace the owned memory files only after a complete staged write succeeds."""
        self.init()
        token = secrets.token_hex(4)
        staging = self.memory_dir.with_name(f".{self.memory_dir.name}.stage-{token}")
        backup = self.memory_dir.with_name(f".{self.memory_dir.name}.backup-{token}")
        shutil.copytree(self.memory_dir, staging)
        try:
            for path in staging.glob("*.md"):
                path.unlink()
            index_lines = ["# Memory Index"]
            for entry in entries:
                filename, content, name, description = self._serialize(entry)
                (staging / filename).write_text(content, encoding="utf-8")
                index_lines.append(f"- [{name}]({filename}) — {description}")
            (staging / INDEX_FILE).write_text("\n".join(index_lines) + "\n", encoding="utf-8")

            self.memory_dir.replace(backup)
            try:
                staging.replace(self.memory_dir)
            except BaseException:
                backup.replace(self.memory_dir)
                raise
            shutil.rmtree(backup, ignore_errors=True)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def list(self) -> list[MemoryEntry]:
        self.init()
        entries: list[MemoryEntry] = []
        for path in self.memory_dir.iterdir():
            if path.suffix != ".md" or path.name == INDEX_FILE:
                continue
            if not path.resolve().is_relative_to(self.memory_dir.resolve()):
                continue
            try:
                parsed = self._parse_frontmatter(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if parsed:
                entries.append(MemoryEntry(file_path=str(path), **parsed))
        return entries

    def search(self, query: str, top_k: int = 5) -> list[SearchHit]:
        return bm25_search(self.list(), query, top_k)

    def load_index(self) -> str:
        self.init()
        return self._truncate(self.index_path.read_text(encoding="utf-8"))

    def load_file(self, filename: str) -> str | None:
        path = self._file_path(filename)
        if not path.exists():
            return None
        self._touch_read_at(path)
        return self._truncate(path.read_text(encoding="utf-8"))

    @staticmethod
    def _truncate(raw: str) -> str:
        return raw[:MAX_FILE_CHARS] + "\n...(已截断)" if len(raw) > MAX_FILE_CHARS else raw

    @staticmethod
    def _touch_read_at(path: Path) -> None:
        raw = path.read_text(encoding="utf-8")
        line = f"lastReadAt: {int(time.time() * 1000)}"
        updated = (
            re.sub(r"^lastReadAt:.*$", line, raw, flags=re.MULTILINE)
            if re.search(r"^lastReadAt:.*$", raw, re.MULTILINE)
            else raw.replace("---\n", f"---\n{line}\n", 1)
        )
        MemoryStore._write_text(path, updated)

    def delete(self, filename: str) -> bool:
        path = self._file_path(filename)
        if not path.exists():
            return False
        path.unlink()
        lines = [
            line for line in self.index_path.read_text(encoding="utf-8").split("\n") if f"({filename})" not in line
        ]
        self._write_text(self.index_path, "\n".join(lines))
        return True

    def lint(self) -> list[ValidationReport]:
        return lint_all(self.list(), self.base_dir)

    def build_prompt_section(self) -> str:
        self.init()
        entries = self.list()
        if not entries:
            return "[记忆系统] 当前没有存储任何记忆。你可以使用 memory 工具来保存重要信息。"
        return "\n".join(
            [
                f"[记忆系统] 共 {len(entries)} 条记忆",
                "",
                "记忆索引：",
                self.load_index(),
                "",
                "使用 memory 工具的 read 操作来读取具体记忆内容；用 search 做 BM25 搜索；用 lint 检查记忆库健康度。",
                "",
                "记忆使用原则：",
                "- 记忆是线索，不是事实——使用前先用工具验证（read_file、grep 确认路径和内容是否还存在）",
                "- 不存代码能推导的（技术栈、目录结构）、git 能查的（谁改了什么）、文档已经写了的",
                "- 只存对话中出现的、其他地方推导不出来的信息（用户偏好、纠正反馈、项目决策、外部资源）",
            ]
        )

    @staticmethod
    def _parse_frontmatter(raw: str) -> dict[str, Any] | None:
        match = re.match(r"^---\n([\s\S]*?)\n---\n([\s\S]*)$", raw)
        if not match:
            return None
        metadata: dict[str, str] = {}
        for line in match.group(1).split("\n"):
            key, separator, value = line.partition(":")
            if separator:
                metadata[key.strip()] = value.strip()
        valid_types = {"user", "feedback", "project", "reference"}
        if not metadata.get("name") or metadata.get("type") not in valid_types:
            return None
        return {
            "name": metadata["name"],
            "description": metadata.get("description", ""),
            "type": metadata["type"],
            "content": match.group(2).strip(),
            "last_write_at": int(metadata["lastWriteAt"]) if metadata.get("lastWriteAt") else None,
            "last_read_at": int(metadata["lastReadAt"]) if metadata.get("lastReadAt") else None,
        }
