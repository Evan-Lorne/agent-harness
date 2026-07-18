from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

HISTORY_SIZE = 30
WARNING_THRESHOLD = 5
CRITICAL_THRESHOLD = 8
BREAKER_THRESHOLD = 10


@dataclass(slots=True)
class ToolCallRecord:
    tool_name: str
    args_hash: str
    timestamp: int
    result_hash: str | None = None


_history: list[ToolCallRecord] = []


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def hash_tool_call(tool_name: str, params: Any) -> str:
    return f"{tool_name}:{_hash(_stable_json(params))}"


def hash_result(result: Any) -> str:
    return _hash(_stable_json(result))


def record_call(tool_name: str, params: Any) -> None:
    _history.append(ToolCallRecord(tool_name, hash_tool_call(tool_name, params), int(time.time() * 1000)))
    if len(_history) > HISTORY_SIZE:
        _history.pop(0)


def record_result(tool_name: str, params: Any, result: Any) -> None:
    args_hash = hash_tool_call(tool_name, params)
    for record in reversed(_history):
        if record.tool_name == tool_name and record.args_hash == args_hash and record.result_hash is None:
            record.result_hash = hash_result(result)
            break


def reset_history() -> None:
    _history.clear()


def _no_progress_streak(tool_name: str, args_hash: str) -> int:
    streak = 0
    last_result: str | None = None
    for record in reversed(_history):
        if record.tool_name != tool_name or record.args_hash != args_hash or not record.result_hash:
            continue
        if last_result is None:
            last_result = record.result_hash
            streak = 1
        elif record.result_hash != last_result:
            break
        else:
            streak += 1
    return streak


def _ping_pong_count(current_hash: str) -> int:
    if len(_history) < 3:
        return 0
    last = _history[-1]
    other_hash = next((r.args_hash for r in reversed(_history[:-1]) if r.args_hash != last.args_hash), None)
    if other_hash is None:
        return 0
    count = 0
    for record in reversed(_history):
        expected = last.args_hash if count % 2 == 0 else other_hash
        if record.args_hash != expected:
            break
        count += 1
    return count + 1 if current_hash == other_hash and count >= 2 else 0


def detect(tool_name: str, params: Any) -> dict[str, Any]:
    args_hash = hash_tool_call(tool_name, params)
    no_progress = _no_progress_streak(tool_name, args_hash)
    if no_progress >= BREAKER_THRESHOLD:
        return {
            "stuck": True,
            "level": "critical",
            "detector": "global_circuit_breaker",
            "count": no_progress,
            "message": f"[熔断] {tool_name} 已重复 {no_progress} 次且无进展，强制停止",
        }
    ping_pong = _ping_pong_count(args_hash)
    if ping_pong >= CRITICAL_THRESHOLD:
        return {
            "stuck": True,
            "level": "critical",
            "detector": "ping_pong",
            "count": ping_pong,
            "message": f"[熔断] 检测到乒乓循环（{ping_pong} 次交替），强制停止",
        }
    if ping_pong >= WARNING_THRESHOLD:
        return {
            "stuck": True,
            "level": "warning",
            "detector": "ping_pong",
            "count": ping_pong,
            "message": f"[警告] 检测到乒乓循环（{ping_pong} 次交替），建议换个思路",
        }
    recent_count = sum(r.tool_name == tool_name and r.args_hash == args_hash for r in _history)
    if recent_count >= CRITICAL_THRESHOLD:
        return {
            "stuck": True,
            "level": "critical",
            "detector": "generic_repeat",
            "count": recent_count,
            "message": f"[熔断] {tool_name} 相同参数已调用 {recent_count} 次，强制停止",
        }
    if recent_count >= WARNING_THRESHOLD:
        return {
            "stuck": True,
            "level": "warning",
            "detector": "generic_repeat",
            "count": recent_count,
            "message": f"[警告] {tool_name} 相同参数已调用 {recent_count} 次，你可能陷入了重复",
        }
    return {"stuck": False}
