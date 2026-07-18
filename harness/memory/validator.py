from __future__ import annotations

import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from harness.memory.types import MemoryEntry

PATH_RE = re.compile(r"(?<![\w/])([\w./-]+\.(?:ts|tsx|js|jsx|json|md|mdx|sql|yml|yaml|toml|env|sh|py))")
TTL_BY_TYPE = {"user": 365, "feedback": 90, "project": 30, "reference": 14}


@dataclass(slots=True)
class ValidationIssue:
    kind: str
    message: str


@dataclass(slots=True)
class ValidationReport:
    entry: MemoryEntry
    issues: list[ValidationIssue]


def extract_paths(content: str) -> list[str]:
    return list(dict.fromkeys(PATH_RE.findall(content)))


def validate_entry(entry: MemoryEntry, base_dir: str | Path = ".") -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    base = Path(base_dir)
    for raw_path in extract_paths(entry.content):
        path = Path(raw_path)
        if not (path if path.is_absolute() else base / path).exists():
            issues.append(ValidationIssue("stale_path", f"引用的路径不存在：{raw_path}"))
    if entry.last_read_at is not None:
        stale_days = TTL_BY_TYPE.get(entry.type, 30)
        days = (time.time() * 1000 - entry.last_read_at) / 86_400_000
        if days > stale_days:
            issues.append(
                ValidationIssue(
                    "never_used", f"已 {int(days)} 天没被读过，超过 {entry.type} 类型的 {stale_days} 天保质期"
                )
            )
    return issues


def lint_all(entries: list[MemoryEntry], base_dir: str | Path = ".") -> list[ValidationReport]:
    counts = Counter(entry.name for entry in entries)
    reports: list[ValidationReport] = []
    for entry in entries:
        issues = validate_entry(entry, base_dir)
        if counts[entry.name] > 1:
            issues.append(ValidationIssue("duplicate_name", f"存在 {counts[entry.name]} 条同名记忆，可能需要合并"))
        if issues:
            reports.append(ValidationReport(entry, issues))
    return reports
