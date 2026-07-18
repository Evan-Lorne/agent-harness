from __future__ import annotations

import time
from datetime import UTC, datetime

from harness.agents.types import SubAgentConfig, SubAgentRun


class SubAgentRegistry:
    def __init__(self, config: SubAgentConfig | None = None) -> None:
        self.config = config or SubAgentConfig()
        self.runs: dict[str, SubAgentRun] = {}
        self.id_counter = 0

    def generate_id(self) -> str:
        self.id_counter += 1
        suffix = base36(int(time.time() * 1000))[-4:]
        return f"sub-{self.id_counter}-{suffix}"

    def can_spawn(self, current_depth: int) -> tuple[bool, str | None]:
        if current_depth >= self.config.max_spawn_depth:
            return False, f"已达最大嵌套深度 {self.config.max_spawn_depth}"
        if len(self.get_active_runs()) >= self.config.max_concurrent:
            return False, f"已达最大并发数 {self.config.max_concurrent}，等待现有任务完成"
        return True, None

    def register(self, run: SubAgentRun) -> None:
        self.runs[run.id] = run

    def complete(self, run_id: str, result: str) -> None:
        run = self.runs.get(run_id)
        if run:
            run.status, run.result, run.finished_at = "completed", result, _now()

    def fail(self, run_id: str, error: str, *, timeout: bool = False) -> None:
        run = self.runs.get(run_id)
        if run:
            run.status, run.error, run.finished_at = ("timeout" if timeout else "error"), error, _now()

    def get(self, run_id: str) -> SubAgentRun | None:
        return self.runs.get(run_id)

    def get_active_runs(self) -> list[SubAgentRun]:
        return [run for run in self.runs.values() if run.status == "running"]

    def get_all_runs(self) -> list[SubAgentRun]:
        return list(self.runs.values())


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def base36(value: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    result = ""
    while value:
        value, remainder = divmod(value, 36)
        result = digits[remainder] + result
    return result or "0"
