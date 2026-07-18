from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from harness.cron.parser import get_next_cron_delay_ms, parse_schedule
from harness.cron.store import CronStore
from harness.cron.types import CronJobConfig, RunLog

QUOTES = [
    "“知之为知之，不知为不知，是知也。” —— 孔子",
    "“千里之行，始于足下。” —— 老子",
    "“Talk is cheap. Show me the code.” —— Linus Torvalds",
    "“Simplicity is the ultimate sophistication.” —— Leonardo da Vinci",
    "“First, solve the problem. Then, write the code.” —— John Johnson",
]


@dataclass(slots=True)
class CronExecutor:
    run_agent_prompt: Callable[[str, int | None], Awaitable[str]]
    notify: Callable[[str], None] | None = None


@dataclass(slots=True)
class CronJobState:
    config: CronJobConfig
    task: asyncio.Task[None] | None = None
    last_run: RunLog | None = None
    consecutive_failures: int = 0
    running: bool = False


class CronService:
    def __init__(self, base_dir: str = ".") -> None:
        self.store = CronStore(base_dir)
        self.store.init()
        self.jobs: dict[str, CronJobState] = {}
        self.executor: CronExecutor | None = None
        self.started = False

    def set_executor(self, executor: CronExecutor) -> None:
        self.executor = executor

    def load(self) -> None:
        for config in self.store.load_jobs():
            if config.enabled:
                self.jobs[config.id] = CronJobState(config)

    def start(self) -> None:
        if self.started:
            return
        self.started = True
        for state in self.jobs.values():
            if state.config.enabled:
                self._schedule(state)

    def stop(self) -> None:
        self.started = False
        for state in self.jobs.values():
            if state.task:
                state.task.cancel()
                state.task = None

    def add(self, config: CronJobConfig) -> None:
        if config.id in self.jobs:
            raise ValueError(f"任务 {config.id} 已存在")
        state = CronJobState(config)
        self.jobs[config.id] = state
        self._persist()
        if self.started and config.enabled:
            self._schedule(state)

    def remove(self, job_id: str) -> bool:
        state = self.jobs.pop(job_id, None)
        if not state:
            return False
        if state.task:
            state.task.cancel()
        self._persist()
        return True

    def enable(self, job_id: str) -> bool:
        state = self.jobs.get(job_id)
        if not state:
            return False
        state.config.enabled, state.consecutive_failures = True, 0
        self._persist()
        if self.started:
            self._schedule(state)
        return True

    def disable(self, job_id: str) -> bool:
        state = self.jobs.get(job_id)
        if not state:
            return False
        state.config.enabled = False
        if state.task:
            state.task.cancel()
            state.task = None
        self._persist()
        return True

    def list(self) -> list[tuple[CronJobConfig, str, RunLog | None]]:
        return [
            (
                state.config,
                "running"
                if state.running
                else "disabled"
                if not state.config.enabled
                else "scheduled"
                if state.task
                else "idle",
                state.last_run,
            )
            for state in self.jobs.values()
        ]

    async def run_now(self, job_id: str) -> str:
        state = self.jobs.get(job_id)
        return await self._execute(state) if state else f"任务 {job_id} 不存在"

    def get_recent_logs(self, job_id: str | None = None, limit: int = 10) -> list[RunLog]:
        return self.store.get_recent_logs(job_id, limit)

    def _schedule(self, state: CronJobState) -> None:
        if state.task:
            state.task.cancel()
        state.task = asyncio.create_task(self._wait_and_run(state))

    async def _wait_and_run(self, state: CronJobState) -> None:
        try:
            parsed = parse_schedule(state.config.schedule)
            if parsed.type == "interval":
                delay = (parsed.interval_ms or 1000) / 1000
            elif parsed.type == "once":
                target = parsed.once_at
                now = datetime.now(target.tzinfo) if target and target.tzinfo else datetime.now()
                delay = max(0, (target - now).total_seconds()) if target else 0
            else:
                delay = get_next_cron_delay_ms(parsed.cron_expression or state.config.schedule) / 1000
            await asyncio.sleep(delay)
            await self._execute(state)
            if parsed.type == "once":
                self.remove(state.config.id)
            elif self.started and state.config.enabled:
                self._schedule(state)
        except asyncio.CancelledError:
            return
        except Exception as error:
            print(f"  [cron] ✗ 调度失败 {state.config.id}: {error}")

    async def _execute(self, state: CronJobState) -> str:
        if state.running:
            return "任务正在执行中"
        state.running = True
        started = _now()
        status = "success"
        error_message = None
        try:
            output = await asyncio.wait_for(
                self._run_payload(state.config.payload, state.config.timeout or 60_000),
                (state.config.timeout or 60_000) / 1000,
            )
            state.consecutive_failures = 0
        except Exception as error:
            status = "timeout" if isinstance(error, TimeoutError) else "error"
            error_message = str(error) or "timeout"
            output = f"执行失败: {error_message}"
            state.consecutive_failures += 1
            if state.consecutive_failures >= (state.config.max_retries if state.config.max_retries is not None else 3):
                state.config.enabled = False
                self._persist()
        finally:
            state.running = False
        log = RunLog(state.config.id, started, _now(), status, output[:1000], error_message)
        state.last_run = log
        self.store.append_log(log)
        if self.executor and self.executor.notify:
            self.executor.notify(f"[cron] {'✓' if status == 'success' else '✗'} {state.config.name}: {output[:200]}")
        return output

    async def _run_payload(self, payload: dict, timeout: int) -> str:
        if not self.executor:
            return "[cron] 未设置执行器，无法运行任务"
        if payload.get("type") == "agent":
            return await self.executor.run_agent_prompt(payload["prompt"], timeout)
        if payload.get("type") == "handler":
            return (
                random.choice(QUOTES)
                if payload.get("handler") == "random-quote"
                else f"[handler] {payload.get('handler')} — handler 类型需要通过插件注册"
            )
        return "未知 payload 类型"

    def _persist(self) -> None:
        runtime = [state.config for state in self.jobs.values() if state.config.source == "runtime"]
        configured = [job for job in self.store.load_jobs() if job.source == "config"]
        self.store.save_jobs([*configured, *runtime])


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
