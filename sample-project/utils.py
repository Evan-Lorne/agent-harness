"""示例项目：通用工具函数。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any


def format_date(value: datetime) -> str:
    # TODO: 支持多时区，目前按输入时间输出
    return value.isoformat()[:10]


def debounce(function: Callable[..., Awaitable[Any]], milliseconds: int) -> Callable[..., Awaitable[None]]:
    task: asyncio.Task[Any] | None = None

    async def wrapped(*args: Any, **kwargs: Any) -> None:
        nonlocal task
        if task:
            task.cancel()

        async def invoke() -> None:
            await asyncio.sleep(milliseconds / 1000)
            await function(*args, **kwargs)

        task = asyncio.create_task(invoke())

    return wrapped
