from __future__ import annotations

from harness.agent.detection import detect, hash_tool_call, record_call, record_result, reset_history
from harness.agent.loop import BudgetState, agent_loop
from harness.mock_model import create_mock_model
from harness.tools.mcp import MockMCPClient
from harness.tools.registry import ToolDefinition, ToolRegistry
from harness.tools.tool_search import create_tool_search_tool
from harness.types import Message, content_to_text
from harness.usage.tracker import UsageTracker


def test_detection_hash_is_stable_and_warns_on_repeat() -> None:
    reset_history()
    assert hash_tool_call("tool", {"a": 1, "b": 2}) == hash_tool_call("tool", {"b": 2, "a": 1})
    for _ in range(5):
        record_call("tool", {"a": 1})
        record_result("tool", {"a": 1}, "same")
    result = detect("tool", {"a": 1})
    assert result["stuck"] is True
    assert result["level"] == "warning"


async def test_mock_agent_loop_executes_tool_then_answers() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            "get_weather",
            "weather",
            {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
            lambda args: f"{args['city']}：晴，20°C",
            True,
            True,
        )
    )
    messages = [{"role": "user", "content": "北京天气怎么样"}]
    tracker = UsageTracker()

    await agent_loop(create_mock_model(), registry, messages, "system", tracker)

    assert any(message["role"] == "tool" for message in messages)
    assert messages[-1]["role"] == "assistant"
    assert "北京" in content_to_text(messages[-1]["content"])
    assert tracker.totals()["steps"] == 2


async def test_budget_is_persistent_across_user_turns(capsys) -> None:
    model = create_mock_model()
    registry = ToolRegistry()
    messages = []
    budget = BudgetState(limit=15_000)

    for _ in range(4):
        messages.append({"role": "user", "content": "测试预算"})
        await agent_loop(model, registry, messages, "system", budget=budget)

    assert budget.used == 18_000
    assert "Token 预算耗尽，强制停止" in capsys.readouterr().out
    before = len(messages)
    messages.append({"role": "user", "content": "测试预算"})
    await agent_loop(model, registry, messages, "system", budget=budget)
    assert len(messages) == before + 1


async def test_mock_mcp_flow_searches_calls_once_then_answers() -> None:
    registry = ToolRegistry()
    registry.register(create_tool_search_tool(registry))
    await registry.register_mcp_server("github", MockMCPClient())
    messages: list[Message] = [{"role": "user", "content": "查看 vercel/ai 的 GitHub issues"}]

    await agent_loop(
        create_mock_model(),
        registry,
        messages,
        "system",
        budget=BudgetState(limit=100_000),
        max_steps=5,
    )

    calls = [
        part["toolName"]
        for message in messages
        if message.get("role") == "assistant" and isinstance(message.get("content"), list)
        for part in message["content"]
        if isinstance(part, dict) and part.get("type") == "tool-call"
    ]
    assert calls == ["tool_search", "mcp__github__list_issues"]
    assert messages[-1]["role"] == "assistant"
