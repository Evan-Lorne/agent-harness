from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

from harness.tasks.store import TaskStore

NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class WorktreeManager:
    def __init__(self, base_dir: str | Path = ".", task_store: TaskStore | None = None) -> None:
        self.base_dir = Path(base_dir).resolve()
        self.directory = self.base_dir / ".worktrees"
        self.task_store = task_store

    @staticmethod
    def validate_name(name: str) -> None:
        if not NAME_RE.fullmatch(name) or name in {".", ".."}:
            raise ValueError("worktree 名称只能包含字母、数字、点、下划线和连字符")

    def path_for(self, name: str) -> Path:
        self.validate_name(name)
        return self.directory / name

    def _git(self, args: list[str], cwd: Path | None = None) -> tuple[bool, str]:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd or self.base_dir,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        return result.returncode == 0, result.stdout.strip()

    def _log(self, event: str, name: str, task_id: str = "") -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / "events.jsonl").open("a", encoding="utf-8") as file:
            file.write(json.dumps({"type": event, "worktree": name, "task_id": task_id, "ts": time.time()}) + "\n")

    @property
    def _bases_path(self) -> Path:
        return self.directory / "bases.json"

    def _bases(self) -> dict[str, str]:
        if not self._bases_path.exists():
            return {}
        try:
            value = json.loads(self._bases_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _set_base(self, name: str, commit: str | None) -> None:
        bases = self._bases()
        if commit:
            bases[name] = commit
        else:
            bases.pop(name, None)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._bases_path.write_text(json.dumps(bases, indent=2) + "\n", encoding="utf-8")

    def create(self, name: str, task_id: str = "") -> str:
        path = self.path_for(name)
        self.directory.mkdir(parents=True, exist_ok=True)
        if path.exists():
            return f"Worktree 已存在: {path}"
        base_ok, base_commit = self._git(["rev-parse", "HEAD"])
        ok, output = self._git(["worktree", "add", str(path), "-b", f"wt/{name}", "HEAD"])
        if not ok:
            return f"Git error: {output}"
        try:
            if task_id and self.task_store:
                self.task_store.bind_worktree(task_id, name)
        except ValueError as error:
            self._git(["worktree", "remove", str(path), "--force"])
            self._git(["branch", "-D", f"wt/{name}"])
            return f"绑定任务失败: {error}"
        self._log("create", name, task_id)
        self._set_base(name, base_commit if base_ok else None)
        return f"Worktree '{name}' created at {path}"

    def remove(self, name: str, discard_changes: bool = False) -> str:
        path = self.path_for(name)
        if not path.exists():
            return "Worktree 不存在"
        dirty_ok, dirty = self._git(["status", "--porcelain"], path)
        base = self._bases().get(name)
        commits_ok, commits = self._git(["rev-list", "--count", f"{base}..HEAD"], path) if base else (True, "0")
        if not discard_changes:
            if not dirty_ok or not commits_ok:
                return "Worktree 状态检查失败；未执行删除"
            if dirty or commits not in {"", "0"}:
                return "Worktree 有未提交或未合并改动；请 keep，或显式设置 discard_changes=true"
        ok, output = self._git(["worktree", "remove", str(path), "--force"])
        if not ok:
            return f"删除失败: {output}"
        self._git(["branch", "-D", f"wt/{name}"])
        self._set_base(name, None)
        self._log("remove", name)
        return f"Worktree '{name}' removed"

    def keep(self, name: str) -> str:
        path = self.path_for(name)
        if not path.exists():
            return "Worktree 不存在"
        self._log("keep", name)
        return f"Worktree '{name}' kept for review (branch: wt/{name})"
