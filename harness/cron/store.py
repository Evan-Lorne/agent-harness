from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness.cron.types import CronJobConfig, RunLog


def _job_from_dict(data: dict[str, Any]) -> CronJobConfig:
    return CronJobConfig(
        data["id"],
        data["name"],
        data["schedule"],
        data.get("scheduleType", data.get("schedule_type", "cron")),
        data.get("enabled", True),
        data["payload"],
        data.get("source", "runtime"),
        data.get("description"),
        data.get("timeout"),
        data.get("maxRetries", data.get("max_retries")),
    )


def _job_to_dict(job: CronJobConfig) -> dict[str, Any]:
    return {
        "id": job.id,
        "name": job.name,
        "description": job.description,
        "schedule": job.schedule,
        "scheduleType": job.schedule_type,
        "enabled": job.enabled,
        "payload": job.payload,
        "timeout": job.timeout,
        "maxRetries": job.max_retries,
        "source": job.source,
    }


class CronStore:
    def __init__(self, base_dir: str | Path = ".") -> None:
        self.base_dir = Path(base_dir)
        self.jobs_path = self.base_dir / ".cron/jobs.json"
        self.logs_path = self.base_dir / ".cron/logs.jsonl"

    def init(self) -> None:
        self.jobs_path.parent.mkdir(parents=True, exist_ok=True)

    def load_jobs(self) -> list[CronJobConfig]:
        if not self.jobs_path.exists():
            return []
        try:
            return [
                _job_from_dict(item) for item in json.loads(self.jobs_path.read_text(encoding="utf-8")).get("jobs", [])
            ]
        except (OSError, ValueError, TypeError, KeyError):
            return []

    def save_jobs(self, jobs: list[CronJobConfig]) -> None:
        self.init()
        self.jobs_path.write_text(
            json.dumps({"jobs": [_job_to_dict(job) for job in jobs]}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def append_log(self, log: RunLog) -> None:
        self.init()
        data = {
            "jobId": log.job_id,
            "startedAt": log.started_at,
            "finishedAt": log.finished_at,
            "status": log.status,
            "output": log.output,
            "error": log.error,
        }
        with self.logs_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")

    def get_recent_logs(self, job_id: str | None = None, limit: int = 10) -> list[RunLog]:
        if not self.logs_path.exists():
            return []
        logs: list[RunLog] = []
        for line in self.logs_path.read_text(encoding="utf-8").splitlines():
            try:
                data = json.loads(line)
                log = RunLog(
                    data["jobId"],
                    data["startedAt"],
                    data["finishedAt"],
                    data["status"],
                    data.get("output"),
                    data.get("error"),
                )
                if job_id is None or log.job_id == job_id:
                    logs.append(log)
            except (ValueError, TypeError, KeyError):
                continue
        return logs[-limit:]
