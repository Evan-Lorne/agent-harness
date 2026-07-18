from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from harness.types import ModelUsage


@dataclass(frozen=True, slots=True)
class ModelPricing:
    input: float
    output: float
    cache_write: float
    cache_read: float


PRICE_TABLE = {
    "claude-opus-4-7": ModelPricing(15, 75, 18.75, 1.5),
    "claude-sonnet-4-7": ModelPricing(3, 15, 3.75, 0.3),
    "claude-haiku-4-5": ModelPricing(1, 5, 1.25, 0.1),
    "gpt-5-5": ModelPricing(5, 20, 5, 0.5),
    "gpt-5": ModelPricing(5, 15, 5, 1.25),
    "gemini-3-pro": ModelPricing(2.5, 12, 2.5, 0.625),
    "gemini-3-flash": ModelPricing(0.3, 1.2, 0.3, 0.075),
    "deepseek-v3-2": ModelPricing(0.27, 1.1, 0.27, 0.027),
    "qwen3-6-plus": ModelPricing(0.4, 1.2, 0.4, 0.04),
    "kimi-k2-6": ModelPricing(0.6, 2.5, 0.6, 0.15),
    "doubao-2-0-pro": ModelPricing(0.3, 0.9, 0.3, 0.12),
    "mock-model": ModelPricing(1, 5, 1.25, 0.1),
}


@dataclass(slots=True)
class StepUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass(slots=True)
class StepRecord(StepUsage):
    ts: int = 0
    model: str = ""
    cost: float = 0


def compute_cost(model: str, usage: StepUsage) -> float:
    pricing = PRICE_TABLE.get(model, PRICE_TABLE["mock-model"])
    return (
        usage.input_tokens * pricing.input
        + usage.output_tokens * pricing.output
        + usage.cache_read_tokens * pricing.cache_read
        + usage.cache_write_tokens * pricing.cache_write
    ) / 1_000_000


def normalize_usage(usage: ModelUsage | dict[str, Any] | None) -> StepUsage:
    if usage is None:
        return StepUsage()
    if isinstance(usage, ModelUsage):
        input_tokens = usage.input_tokens
        cache_read = usage.cached_input_tokens
        cache_write = usage.cache_creation_input_tokens
        output_tokens = usage.output_tokens
    else:
        metadata = usage.get("providerMetadata", {})
        cache_read = usage.get("cachedInputTokens", metadata.get("openai", {}).get("cachedTokens", 0))
        cache_write = usage.get(
            "cacheCreationInputTokens", metadata.get("anthropic", {}).get("cacheCreationInputTokens", 0)
        )
        input_tokens = usage.get("inputTokens", 0)
        output_tokens = usage.get("outputTokens", 0)
    if cache_read and input_tokens >= cache_read:
        input_tokens -= cache_read
    return StepUsage(max(0, input_tokens), output_tokens, cache_read, cache_write)


class UsageTracker:
    def __init__(self, log_path: str | Path | None = None) -> None:
        self.steps: list[StepRecord] = []
        self.log_path = Path(log_path) if log_path else None
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, model: str, usage: StepUsage) -> StepRecord:
        record = StepRecord(**asdict(usage), ts=int(time.time() * 1000), model=model, cost=compute_cost(model, usage))
        self.steps.append(record)
        if self.log_path:
            data = {
                "ts": record.ts,
                "model": record.model,
                "cost": record.cost,
                "inputTokens": record.input_tokens,
                "outputTokens": record.output_tokens,
                "cacheReadTokens": record.cache_read_tokens,
                "cacheWriteTokens": record.cache_write_tokens,
            }
            with self.log_path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")
        return record

    def totals(self) -> dict[str, int | float]:
        values = {"inputTokens": 0, "outputTokens": 0, "cacheReadTokens": 0, "cacheWriteTokens": 0, "cost": 0.0}
        baseline = 0.0
        for step in self.steps:
            values["inputTokens"] += step.input_tokens
            values["outputTokens"] += step.output_tokens
            values["cacheReadTokens"] += step.cache_read_tokens
            values["cacheWriteTokens"] += step.cache_write_tokens
            values["cost"] += step.cost
            pricing = PRICE_TABLE.get(step.model, PRICE_TABLE["mock-model"])
            baseline += (
                (step.input_tokens + step.cache_read_tokens + step.cache_write_tokens) * pricing.input
                + step.output_tokens * pricing.output
            ) / 1_000_000
        total_input = values["inputTokens"] + values["cacheReadTokens"] + values["cacheWriteTokens"]
        return {
            **values,
            "hitRate": values["cacheReadTokens"] / total_input if total_input else 0,
            "baselineCost": baseline,
            "savedCost": baseline - values["cost"],
            "steps": len(self.steps),
        }

    def recent(self, count: int) -> list[StepRecord]:
        return self.steps[-count:]
