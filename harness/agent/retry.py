from __future__ import annotations

import asyncio
import random
import re


def is_retryable(error: BaseException) -> bool:
    message = str(error)
    match = re.search(r"(\d{3})", message)
    if match:
        status = int(match.group(1))
        if status in {429, 529, 408} or 500 <= status < 600:
            return True
        if 400 <= status < 500:
            return False
    retryable_text = ("ECONNRESET", "EPIPE", "ETIMEDOUT", "timeout", "fetch failed", "network", "No output generated")
    return any(value in message for value in retryable_text)


def is_prompt_too_long(error: BaseException) -> bool:
    message = str(error).lower()
    return any(value in message for value in ("prompt_too_long", "context length", "maximum context", "413"))


def retry_after_ms(error: BaseException) -> int | None:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    value = headers.get("retry-after") if headers else None
    if value is None:
        match = re.search(r"retry[- ]after[:=]\s*(\d+(?:\.\d+)?)", str(error), re.I)
        value = match.group(1) if match else None
    try:
        return round(float(value) * 1000) if value is not None else None
    except (TypeError, ValueError):
        return None


def calculate_delay(attempt: int, base_ms: int = 500, max_ms: int = 30000) -> int:
    capped = min(base_ms * 2 ** (attempt - 1), max_ms)
    jitter_range = capped * 0.25
    return max(0, round(capped + (random.random() * 2 - 1) * jitter_range))


async def sleep(ms: int) -> None:
    await asyncio.sleep(ms / 1000)
