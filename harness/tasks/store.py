from __future__ import annotations

import json
import re
import secrets
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from harness.tasks.types import Task

TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class TaskStore:
    def __init__(self, base_dir: str | Path = ".") -> None:
        self.directory = Path(base_dir) / ".tasks"
        self.lock = threading.RLock()

    def init(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, task_id: str) -> Path:
        if not TASK_ID_RE.fullmatch(task_id):
            raise ValueError("非法任务 ID")
        return self.directory / f"{task_id}.json"

    @staticmethod
    def _to_dict(task: Task) -> dict[str, Any]:
        value = asdict(task)
        value["blockedBy"] = value.pop("blocked_by")
        return value

    @staticmethod
    def _from_dict(value: dict[str, Any]) -> Task:
        return Task(
            id=value["id"],
            subject=value["subject"],
            description=value.get("description", ""),
            status=value.get("status", "pending"),
            owner=value.get("owner"),
            blocked_by=list(value.get("blockedBy", value.get("blocked_by", []))),
            worktree=value.get("worktree"),
        )

    def save(self, task: Task) -> None:
        with self.lock:
            self.init()
            path = self._path(task.id)
            temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
            try:
                temporary.write_text(
                    json.dumps(self._to_dict(task), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)

    def create(self, subject: str, description: str = "", blocked_by: list[str] | None = None) -> Task:
        task = Task(
            f"task_{int(time.time() * 1000)}_{secrets.token_hex(2)}", subject, description, blocked_by=blocked_by or []
        )
        for dependency in task.blocked_by:
            if not self.get(dependency):
                raise ValueError(f"依赖任务不存在: {dependency}")
        self.save(task)
        return task

    def get(self, task_id: str) -> Task | None:
        path = self._path(task_id)
        if not path.exists():
            return None
        try:
            return self._from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def list(self) -> list[Task]:
        self.init()
        tasks = []
        for path in sorted(self.directory.glob("*.json")):
            task = self.get(path.stem)
            if task:
                tasks.append(task)
        return tasks

    def can_start(self, task: Task) -> bool:
        return all(
            (dependency := self.get(task_id)) is not None and dependency.status == "completed"
            for task_id in task.blocked_by
        )

    def claim(self, task_id: str, owner: str) -> Task:
        with self.lock:
            task = self.get(task_id)
            if not task:
                raise ValueError("任务不存在")
            if task.status != "pending" or task.owner:
                raise ValueError(f"任务已处于 {task.status} 状态")
            if not self.can_start(task):
                raise ValueError(f"任务仍被依赖阻塞: {', '.join(task.blocked_by)}")
            task.status, task.owner = "in_progress", owner
            self.save(task)
            return task

    def complete(self, task_id: str, owner: str | None = None) -> tuple[Task, list[Task]]:
        with self.lock:
            task = self.get(task_id)
            if not task:
                raise ValueError("任务不存在")
            if task.status != "in_progress":
                raise ValueError("只能完成 in_progress 任务")
            if owner and task.owner not in {None, owner}:
                raise ValueError(f"任务属于 {task.owner}")
            task.status = "completed"
            self.save(task)
            unlocked = [
                item
                for item in self.list()
                if item.status == "pending" and task.id in item.blocked_by and self.can_start(item)
            ]
            return task, unlocked

    def release_owner(self, owner: str) -> None:
        with self.lock:
            for task in self.list():
                if task.owner == owner and task.status == "in_progress":
                    task.owner, task.status = None, "pending"
                    self.save(task)

    def available(self) -> list[Task]:
        return [task for task in self.list() if task.status == "pending" and not task.owner and self.can_start(task)]

    def bind_worktree(self, task_id: str, worktree: str) -> Task:
        with self.lock:
            task = self.get(task_id)
            if not task:
                raise ValueError("任务不存在")
            task.worktree = worktree
            self.save(task)
            return task
