from __future__ import annotations

from harness.agent.loop import ContextState, prepare_context
from harness.context.defense import TTLConfig, ttl_prune
from harness.mock_model import create_mock_model
from harness.types import ModelUsage
from harness.usage.tracker import UsageTracker, normalize_usage


def test_usage_normalization_subtracts_cached_input() -> None:
    normalized = normalize_usage(ModelUsage(100, 20, 40, 10))
    assert normalized.input_tokens == 60
    assert normalized.cache_read_tokens == 40
    assert normalized.cache_write_tokens == 10

    tracker = UsageTracker()
    tracker.record("mock-model", normalized)
    totals = tracker.totals()
    assert totals["steps"] == 1
    assert totals["hitRate"] > 0


def test_ttl_prune_keeps_errors_and_expires_success() -> None:
    messages = [
        {
            "role": "tool",
            "content": [
                {
                    "type": "tool-result",
                    "toolName": "read_file",
                    "output": {"type": "text", "value": "successful output"},
                }
            ],
        },
        {
            "role": "tool",
            "content": [
                {
                    "type": "tool-result",
                    "toolName": "read_file",
                    "output": {"type": "error-text", "value": "error: missing"},
                }
            ],
        },
    ]
    result, _soft, hard = ttl_prune(messages, {0: 0, 1: 0}, TTLConfig(1, 1, 10))
    assert hard == 1
    assert "expired" in result[0]["content"][0]["output"]["value"]
    assert result[1]["content"][0]["output"]["value"] == "error: missing"


async def test_prepare_context_runs_defense_microcompact_and_summarization() -> None:
    messages = [
        {"role": "user", "content": "x" * 700},
        {"role": "assistant", "content": "y" * 700},
        {"role": "user", "content": "first tool"},
        {
            "role": "tool",
            "content": [{"type": "tool-result", "toolName": "read_file", "output": {"type": "text", "value": "old"}}],
        },
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "second tool"},
        {
            "role": "tool",
            "content": [{"type": "tool-result", "toolName": "read_file", "output": {"type": "text", "value": "two"}}],
        },
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "third tool"},
        {
            "role": "tool",
            "content": [
                {
                    "type": "tool-result",
                    "toolName": "read_file",
                    "output": {"type": "text", "value": "three"},
                }
            ],
        },
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "fourth tool"},
        {
            "role": "tool",
            "content": [{"type": "tool-result", "toolName": "read_file", "output": {"type": "text", "value": "four"}}],
        },
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "latest"},
    ]
    timestamps = {index: 0 for index in range(len(messages))}
    state = ContextState()

    await prepare_context(create_mock_model(), messages, timestamps, state)

    assert state.summary.startswith("## 用户意图")
    assert messages[0]["content"].startswith("[以下是之前对话的压缩摘要]")
    assert len(timestamps) == len(messages)
