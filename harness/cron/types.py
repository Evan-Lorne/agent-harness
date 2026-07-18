from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ScheduleType = Literal["cron", "interval", "once"]


@dataclass(slots=True)
class CronJobConfig:
    id: str
    name: str
    schedule: str
    schedule_type: ScheduleType
    enabled: bool
    payload: dict[str, Any]
    source: Literal["config", "runtime"]
    description: str | None = None
    timeout: int | None = None
    max_retries: int | None = None


@dataclass(slots=True)
class RunLog:
    job_id: str
    started_at: str
    finished_at: str
    status: Literal["success", "error", "timeout"]
    output: str | None = None
    error: str | None = None
