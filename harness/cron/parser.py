from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from croniter import croniter

INTERVAL_RE = re.compile(r"^every\s+(\d+)\s*(s|sec|m|min|h|hour)s?$", re.I)


@dataclass(slots=True)
class ParsedSchedule:
    type: str
    interval_ms: int | None = None
    cron_expression: str | None = None
    once_at: datetime | None = None


def parse_schedule(expression: str) -> ParsedSchedule:
    match = INTERVAL_RE.match(expression)
    if match:
        unit = match.group(2).lower()
        multiplier = 3_600_000 if unit.startswith("h") else 60_000 if unit.startswith("m") else 1000
        return ParsedSchedule("interval", int(match.group(1)) * multiplier)
    if re.match(r"^\d{4}-\d{2}-\d{2}", expression):
        try:
            return ParsedSchedule("once", once_at=datetime.fromisoformat(expression.replace("Z", "+00:00")))
        except ValueError:
            pass
    if not croniter.is_valid(expression):
        raise ValueError(f"Invalid cron expression: {expression}")
    return ParsedSchedule("cron", cron_expression=expression)


def get_next_cron_delay_ms(expression: str) -> int:
    now = datetime.now().astimezone()
    return max(0, round((croniter(expression, now).get_next(datetime) - now).total_seconds() * 1000))
