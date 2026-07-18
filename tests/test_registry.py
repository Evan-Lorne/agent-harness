from __future__ import annotations

from harness.security.hooks import HookPipeline, HookResult
from harness.tools.registry import ToolDefinition, ToolRegistry, truncate_result
from harness.tools.search_tools import glob_tool
from harness.tools.tool_search import create_tool_search_tool


async def test_deferred_discovery_role_filtering_and_hooks() -> None:
    calls: list[dict] = []

    async def execute(args: dict) -> str:
        calls.append(args)
        return "original"

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            "mcp__demo__read",
            "deferred",
            {"type": "object", "properties": {}},
            execute,
            True,
            True,
            should_defer=True,
        ),
        ToolDefinition(
            "bash",
            "shell",
            {"type": "object", "properties": {"command": {"type": "string"}}},
            execute,
        ),
    )
    registry.register(create_tool_search_tool(registry))
    assert "mcp__demo__read" not in registry.to_model_format()
    assert registry.search_tools("mcp__demo__read")[0].name == "mcp__demo__read"
    assert "mcp__demo__read" in registry.to_model_format()

    registry.set_role("guest")
    assert "bash" not in registry.to_model_format()
    registry.set_role("owner")

    hooks = HookPipeline()
    hooks.register_post("replace", lambda *_args: HookResult("modify", modified_output="modified"))
    registry.set_hook_pipeline(hooks)
    output = await registry.to_model_format()["mcp__demo__read"]["execute"]({"value": 1})
    assert output == "modified"
    assert calls == [{"value": 1}]


async def test_dangerous_bash_is_blocked_before_execution() -> None:
    called = False

    async def execute(_args: dict) -> str:
        nonlocal called
        called = True
        return "ran"

    registry = ToolRegistry()
    registry.register(ToolDefinition("bash", "shell", {}, execute))
    result = await registry.to_model_format()["bash"]["execute"]({"command": "rm -rf /tmp/demo"})

    assert "拒绝执行" in result
    assert called is False


async def test_subagent_tools_keep_security_wrapper_and_use_an_independent_gate() -> None:
    calls: list[str] = []

    async def execute(args: dict) -> str:
        calls.append(args["command"])
        return "ran"

    registry = ToolRegistry()
    registry.register(ToolDefinition("bash", "shell", {}, execute))
    tools = registry.to_model_format_for_subagent()

    blocked = await tools["bash"]["execute"]({"command": "rm -rf /tmp/demo"})
    assert "拒绝执行" in blocked
    assert calls == []

    await registry.gate.acquire_exclusive()
    try:
        assert await tools["bash"]["execute"]({"command": "pwd"}) == "ran"
    finally:
        await registry.gate.release_exclusive()
    assert calls == ["pwd"]


def test_result_truncation_preserves_head_and_tail() -> None:
    result = truncate_result("a" * 100 + "z" * 100, 100)
    assert result.startswith("a" * 60)
    assert result.endswith("z" * 40)
    assert "省略 100 字符" in result


async def test_glob_double_star_includes_root_files(tmp_path) -> None:
    (tmp_path / "root.py").write_text("", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "child.py").write_text("", encoding="utf-8")

    output = await glob_tool.execute({"pattern": "**/*.py", "path": str(tmp_path)})

    assert output.splitlines() == ["nested/child.py", "root.py"]
