from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime

from harness.types import Message
from harness.usage.tracker import UsageTracker

COLORS = {
    "system": 63,
    "tools": 99,
    "memory": 220,
    "skills": 36,
    "messages": 111,
    "free": 240,
    "buffer": 244,
    "text": 255,
    "dim": 244,
}


@dataclass(slots=True)
class ContextSlice:
    name: str
    tokens: int
    color: int
    icon: str


@dataclass(slots=True)
class ContextSnapshot:
    model_name: str
    model_id: str
    window_tokens: int
    used_tokens: int
    slices: list[ContextSlice]
    autocompact_buffer_tokens: int


def _fg(code: int, text: str) -> str:
    return f"\033[38;5;{code}m{text}\033[0m"


def _percent(value: int | float, total: int | float) -> str:
    return f"{value / total * 100:.1f}%" if total else "0.0%"


def _format_tokens(value: int | float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1000:
        return f"{value / 1000:.1f}k"
    return str(int(value))


def render_context_matrix(snapshot: ContextSnapshot) -> str:
    tokens_per_cell = snapshot.window_tokens / 256
    cells: list[int] = []
    for item in snapshot.slices:
        if item.tokens <= 0:
            continue
        cells.extend([item.color] * min(256 - len(cells), max(1, round(item.tokens / tokens_per_cell))))
    buffer_cells = max(0, round(snapshot.autocompact_buffer_tokens / tokens_per_cell))
    cells.extend([-1] * max(0, 256 - len(cells) - buffer_cells))
    cells.extend([-2] * min(buffer_cells, 256 - len(cells)))
    symbols = {-1: _fg(COLORS["free"], "○"), -2: _fg(COLORS["buffer"], "▢")}
    lines = []
    for row in range(16):
        lines.append(" ".join(symbols.get(color, _fg(color, "●")) for color in cells[row * 16 : row * 16 + 16]))
    return "\n".join(lines)


def render_context_legend(snapshot: ContextSnapshot) -> str:
    lines = [
        _fg(255, f"\033[1m{snapshot.model_name}\033[0m"),
        _fg(COLORS["dim"], snapshot.model_id),
        f"{_format_tokens(snapshot.used_tokens)}/{_format_tokens(snapshot.window_tokens)} tokens ({_percent(snapshot.used_tokens, snapshot.window_tokens)})",
        "",
        _fg(COLORS["dim"], "\033[3mEstimated usage by category\033[0m"),
    ]
    for item in snapshot.slices:
        if item.tokens > 0:
            lines.append(
                f"{_fg(item.color, '●')} {item.icon} {item.name}: {_format_tokens(item.tokens)} tokens ({_percent(item.tokens, snapshot.window_tokens)})"
            )
    free = max(0, snapshot.window_tokens - snapshot.used_tokens - snapshot.autocompact_buffer_tokens)
    lines.extend(
        [
            f"{_fg(COLORS['free'], '○')}  Free space: {_format_tokens(free)} ({_percent(free, snapshot.window_tokens)})",
            f"{_fg(COLORS['buffer'], '▢')}  Autocompact buffer: {_format_tokens(snapshot.autocompact_buffer_tokens)} ({_percent(snapshot.autocompact_buffer_tokens, snapshot.window_tokens)})",
        ]
    )
    return "\n".join(lines)


def render_context_view(snapshot: ContextSnapshot) -> str:
    matrix, legend = render_context_matrix(snapshot).splitlines(), render_context_legend(snapshot).splitlines()
    return (
        "\n"
        + "\n".join(
            f"  {(matrix[index] if index < len(matrix) else ''):<80}  {legend[index] if index < len(legend) else ''}"
            for index in range(max(len(matrix), len(legend)))
        )
        + "\n"
    )


def _chars_to_tokens(characters: int) -> int:
    return math.ceil(characters / 3.5)


def _message_tokens(messages: list[Message]) -> int:
    characters = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            characters += len(content)
            continue
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                characters += len(str(part.get("text", "")))
            elif part.get("type") == "tool-call":
                characters += len(json.dumps(part.get("input", {}), ensure_ascii=False)) + 80
            elif part.get("type") == "tool-result":
                output = part.get("output")
                characters += (
                    len(str(output.get("value")))
                    if isinstance(output, dict) and output.get("value")
                    else len(json.dumps(output, ensure_ascii=False))
                )
                characters += 80
    return _chars_to_tokens(characters)


def build_context_snapshot(
    *,
    model_name: str,
    model_id: str,
    window_tokens: int,
    system_prompt_chars: int,
    tool_description_chars: int,
    memory_chars: int,
    skills_chars: int,
    messages: list[Message],
    autocompact_buffer_tokens: int | None = None,
) -> ContextSnapshot:
    slices = [
        ContextSlice("System prompt", _chars_to_tokens(system_prompt_chars), COLORS["system"], "◆"),
        ContextSlice("System tools", _chars_to_tokens(tool_description_chars), COLORS["tools"], "◇"),
        ContextSlice("Memory", _chars_to_tokens(memory_chars), COLORS["memory"], "◈"),
        ContextSlice("Skills", _chars_to_tokens(skills_chars), COLORS["skills"], "◉"),
        ContextSlice("Messages", _message_tokens(messages), COLORS["messages"], "◎"),
    ]
    return ContextSnapshot(
        model_name,
        model_id,
        window_tokens,
        sum(item.tokens for item in slices),
        slices,
        autocompact_buffer_tokens if autocompact_buffer_tokens is not None else round(window_tokens * 0.05),
    )


def render_usage_view(tracker: UsageTracker) -> str:
    totals = tracker.totals()
    hit_rate = float(totals["hitRate"])
    bar_width = 30
    filled = round(hit_rate * bar_width)
    cost = f"${float(totals['cost']):.4f}"
    baseline_cost = f"${float(totals['baselineCost']):.4f}"
    lines = [
        "\033[1m" + _fg(255, "  Usage Summary") + "\033[0m",
        _fg(244, f"  {totals['steps']} 步累计 · {datetime.now(UTC).isoformat()[:19].replace('T', ' ')}"),
        "",
        f"  {_fg(111, '◎')} Input          {_format_tokens(totals['inputTokens']):>8} tokens",
        f"  {_fg(220, '◈')} Cache write    {_format_tokens(totals['cacheWriteTokens']):>8} tokens",
        f"  {_fg(36, '◉')} Cache read     {_format_tokens(totals['cacheReadTokens']):>8} tokens   ({hit_rate * 100:.1f}% hit)",
        f"  {_fg(99, '◇')} Output         {_format_tokens(totals['outputTokens']):>8} tokens",
        "",
        f"  Cache hit rate  {_fg(36, '█' * filled)}{_fg(240, '░' * (bar_width - filled))}  {hit_rate * 100:.1f}%",
        "",
        f"  \033[1mCost\033[0m            {_fg(220, cost)}",
        f"  {_fg(244, 'Without cache')}   {_fg(244, baseline_cost)}",
    ]
    if float(totals["savedCost"]) > 0:
        saved_percent = (
            float(totals["savedCost"]) / float(totals["baselineCost"]) * 100 if totals["baselineCost"] else 0
        )
        saved_cost = f"${float(totals['savedCost']):.4f}"
        lines.append(f"  \033[1m{_fg(36, 'Saved')}\033[0m           {_fg(36, saved_cost)} ({saved_percent:.1f}% off)")
    return "\n" + "\n".join(lines) + "\n"
