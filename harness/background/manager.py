from __future__ import annotations

import asyncio
import html
from collections.abc import Awaitable
from dataclasses import dataclass


@dataclass(slots=True)
class BackgroundTask:
    id: str
    command: str
    status: str = "running"
    output: str = ""


class BackgroundTaskManager:
    def __init__(self) -> None:
        self.counter = 0
        self.tasks: dict[str, BackgroundTask] = {}
        self.workers: dict[str, asyncio.Task[None]] = {}

    def start(self, command: str, awaitable: Awaitable[str]) -> str:
        self.counter += 1
        task_id = f"bg_{self.counter:04d}"
        state = BackgroundTask(task_id, command)
        self.tasks[task_id] = state

        async def run() -> None:
            try:
                state.output = await awaitable
                state.status = "completed"
            except asyncio.CancelledError:
                state.status = "cancelled"
                raise
            except Exception as error:
                state.output = str(error)
                state.status = "error"

        self.workers[task_id] = asyncio.create_task(run())
        return task_id

    def collect_notifications(self) -> list[str]:
        ready = [task for task in self.tasks.values() if task.status != "running"]
        notifications = []
        for task in ready:
            notifications.append(
                "<task_notification>\n"
                f"<task_id>{task.id}</task_id>\n"
                f"<status>{task.status}</status>\n"
                f"<command>{html.escape(task.command)}</command>\n"
                f"<summary>{html.escape(task.output[:1000])}</summary>\n"
                "</task_notification>"
            )
            self.tasks.pop(task.id, None)
            self.workers.pop(task.id, None)
        return notifications

    async def close(self) -> None:
        workers = list(self.workers.values())
        for worker in workers:
            worker.cancel()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)
        self.workers.clear()
        self.tasks.clear()
