from __future__ import annotations

import copy
import math
import re
import time
from dataclasses import dataclass

from harness.context.tool_output import is_tool_output_error, replace_tool_output_text, tool_output_to_text
from harness.types import Message

CONTEXT_WINDOW = 200_000


class TokenTracker:
    def __init__(self) -> None:
        self.last_precise_count = 0
        self.pending_chars = 0

    def update_from_api(self, prompt_tokens: int) -> None:
        self.last_precise_count = prompt_tokens
        self.pending_chars = 0

    def add_message(self, content: str) -> None:
        self.pending_chars += len(content)

    @property
    def estimated_tokens(self) -> int:
        return self.last_precise_count + math.ceil(self.pending_chars / 4)

    @property
    def status(self) -> dict[str, int | bool]:
        percent = round(self.estimated_tokens / CONTEXT_WINDOW * 100)
        return {"tokens": self.estimated_tokens, "percent": percent, "needsAction": percent >= 75}


def estimate_message_tokens(messages: list[Message]) -> int:
    characters = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            characters += len(content)
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if isinstance(part.get("text"), str):
                    characters += len(part["text"])
                elif "output" in part:
                    characters += len(tool_output_to_text(part["output"]))
    return math.ceil(characters / 4 * 1.2)


@dataclass(frozen=True, slots=True)
class TruncationConfig:
    max_single_result: int = CONTEXT_WINDOW
    context_budget_chars: int = CONTEXT_WINDOW * 3


def truncate_tool_results(
    messages: list[Message], config: TruncationConfig | None = None
) -> tuple[list[Message], int, int]:
    config = config or TruncationConfig()
    result = copy.deepcopy(messages)
    truncated = compacted = 0
    for message in result:
        if message.get("role") != "tool" or not isinstance(message.get("content"), list):
            continue
        for part in message["content"]:
            output = tool_output_to_text(part.get("output"))
            if len(output) <= config.max_single_result:
                continue
            truncated += 1
            head_size = math.floor(config.max_single_result * 0.6)
            tail_size = math.floor(config.max_single_result * 0.4)
            text = f"{output[:head_size]}\n\n[truncated: {len(output)} → {config.max_single_result} chars]\n\n{output[-tail_size:]}"
            part["output"] = replace_tool_output_text(part.get("output"), text)
    total = _message_chars(result)
    for message in result:
        if total <= config.context_budget_chars:
            break
        if message.get("role") != "tool" or not isinstance(message.get("content"), list):
            continue
        tool_name = message["content"][0].get("toolName", "unknown") if message["content"] else "unknown"
        old_size = sum(len(tool_output_to_text(part.get("output"))) for part in message["content"])
        for part in message["content"]:
            part["output"] = replace_tool_output_text(
                part.get("output"), f"[compacted: {tool_name} output removed to free context]"
            )
        total -= old_size
        compacted += 1
    return result, truncated, compacted


def _message_chars(messages: list[Message]) -> int:
    total = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            total += sum(
                len(tool_output_to_text(part.get("output"))) if "output" in part else len(str(part.get("text", "")))
                for part in content
                if isinstance(part, dict)
            )
    return total


@dataclass(frozen=True, slots=True)
class TTLConfig:
    soft_ttl_ms: int = 5 * 60 * 1000
    hard_ttl_ms: int = 10 * 60 * 1000
    keep_head_tail: int = 1500


def ttl_prune(
    messages: list[Message], timestamps: dict[int, int], config: TTLConfig | None = None
) -> tuple[list[Message], int, int]:
    config = config or TTLConfig()
    result = copy.deepcopy(messages)
    soft = hard = 0
    now = int(time.time() * 1000)
    for index, message in enumerate(result):
        if message.get("role") != "tool" or not isinstance(message.get("content"), list) or index not in timestamps:
            continue
        parts = message["content"]
        output_text = "".join(tool_output_to_text(part.get("output")) for part in parts)
        if any(is_tool_output_error(part.get("output")) for part in parts) or re.search(
            r"error|失败|不存在|denied|refused|timeout", output_text, re.I
        ):
            continue
        age = now - timestamps[index]
        tool_name = parts[0].get("toolName", "unknown") if parts else "unknown"
        if age >= config.hard_ttl_ms:
            hard += 1
            for part in parts:
                part["output"] = replace_tool_output_text(part.get("output"), f"[tool result expired: {tool_name}]")
        elif age >= config.soft_ttl_ms:
            for part in parts:
                output = tool_output_to_text(part.get("output"))
                if len(output) <= config.keep_head_tail * 2:
                    continue
                soft += 1
                removed = len(output) - config.keep_head_tail * 2
                text = f"{output[: config.keep_head_tail]}\n\n[soft pruned: {removed} chars removed, content older than {round(config.soft_ttl_ms / 60000)}min]\n\n{output[-config.keep_head_tail :]}"
                part["output"] = replace_tool_output_text(part.get("output"), text)
    return result, soft, hard


@dataclass(slots=True)
class DefenseResult:
    messages: list[Message]
    token_estimate: int
    truncated: int
    compacted: int
    soft_pruned: int
    hard_pruned: int


def apply_defense(messages: list[Message], timestamps: dict[int, int]) -> DefenseResult:
    defended, truncated, compacted = truncate_tool_results(messages)
    defended, soft, hard = ttl_prune(defended, timestamps)
    return DefenseResult(defended, estimate_message_tokens(defended), truncated, compacted, soft, hard)
