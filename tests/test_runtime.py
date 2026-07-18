from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import harness.main as main_module
from harness.channels.feishu import FeishuChannel
from harness.config.schema import MCPServerConfig, RagConfig
from harness.main import _ingest_docs, create_vector_store, register_configured_mcp
from harness.model import OpenAIModel
from harness.rag.store import VectorStore
from harness.tools.registry import ToolRegistry


async def test_mcp_configuration_uses_mock_only_without_enabled_servers(monkeypatch) -> None:
    mock_registry = ToolRegistry()
    mock_tools = await register_configured_mcp(mock_registry, [])
    assert len(mock_tools) == 3
    assert "mcp__github__list_issues" in mock_registry.tools

    class FakeClient:
        async def connect(self) -> None:
            return None

        async def list_tools(self) -> list[dict[str, Any]]:
            return [{"name": "ping", "description": "ping", "inputSchema": {}, "isReadOnly": True}]

        async def call_tool(self, _name: str, _args: dict[str, Any]) -> str:
            return "pong"

        async def close(self) -> None:
            return None

    monkeypatch.setattr(main_module, "StdioMCPClient", lambda *_args: FakeClient())
    real_registry = ToolRegistry()
    real_tools = await register_configured_mcp(
        real_registry,
        [MCPServerConfig(name="demo", command="demo-server")],
    )
    assert real_tools == ["mcp__demo__ping"]
    assert "mcp__github__list_issues" not in real_registry.tools


def test_rag_store_selection_is_configuration_driven(monkeypatch) -> None:
    assert isinstance(create_vector_store(RagConfig.model_validate({})), VectorStore)

    sentinel = VectorStore()
    monkeypatch.setattr(main_module, "SqliteVectorStore", lambda _path: sentinel)
    assert create_vector_store(RagConfig.model_validate({"store": "sqlite", "databasePath": "test.db"})) is sentinel
    assert isinstance(create_vector_store(RagConfig.model_validate({"enabled": False, "store": "sqlite"})), VectorStore)


async def test_feishu_stop_waits_for_graceful_server_exit() -> None:
    channel = FeishuChannel("", "")
    server = SimpleNamespace(should_exit=False)
    channel.server = cast(Any, server)

    async def serve() -> None:
        while not server.should_exit:
            await asyncio.sleep(0)

    task = asyncio.create_task(serve())
    channel.server_task = task
    await asyncio.sleep(0)

    await channel.stop()

    assert task.done()
    assert not task.cancelled()


async def test_openai_model_streams_text_and_reassembles_tool_calls() -> None:
    chunks = [
        SimpleNamespace(
            usage=None,
            choices=[SimpleNamespace(delta=SimpleNamespace(content="hel", tool_calls=[]))],
        ),
        SimpleNamespace(
            usage=None,
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content="lo",
                        tool_calls=[
                            SimpleNamespace(
                                index=0,
                                id="call-1",
                                function=SimpleNamespace(name="echo", arguments='{"value":'),
                            )
                        ],
                    )
                )
            ],
        ),
        SimpleNamespace(
            usage=None,
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                index=0,
                                id=None,
                                function=SimpleNamespace(name=None, arguments='"ok"}'),
                            )
                        ],
                    )
                )
            ],
        ),
        SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=3, prompt_tokens_details=None),
            choices=[],
        ),
    ]

    class FakeStream:
        def __init__(self) -> None:
            self.values = iter(chunks)

        def __aiter__(self) -> FakeStream:
            return self

        async def __anext__(self) -> Any:
            try:
                return next(self.values)
            except StopIteration as error:
                raise StopAsyncIteration from error

    class FakeCompletions:
        def __init__(self) -> None:
            self.kwargs: dict[str, Any] = {}

        async def create(self, **kwargs: Any) -> FakeStream:
            self.kwargs = kwargs
            return FakeStream()

    completions = FakeCompletions()
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    model = OpenAIModel("test-model", api_key="test-key")
    model.client = cast(Any, fake_client)
    deltas: list[str] = []

    async def echo(args: dict[str, Any]) -> str:
        return args["value"]

    result = await model.run_step(
        system="system",
        messages=[{"role": "user", "content": "say hello"}],
        tools={"echo": {"name": "echo", "description": "echo", "parameters": {}, "execute": echo}},
        on_text_delta=deltas.append,
    )

    assert deltas == ["hel", "lo"]
    assert completions.kwargs["stream"] is True
    assert result.messages[0]["content"][0]["text"] == "hello"
    assert result.messages[0]["content"][1]["input"] == {"value": "ok"}
    assert result.messages[1]["content"][0]["output"] == "ok"
    assert result.usage.input_tokens == 12


async def test_doc_ingest_degrades_when_embedding_provider_is_unavailable(tmp_path, capsys) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("# Guide\n\ncontent", encoding="utf-8")

    async def unavailable(_texts: list[str]) -> list[list[float]]:
        raise RuntimeError("provider unavailable")

    store = VectorStore()
    await _ingest_docs(str(docs), store, unavailable)

    assert store.size() == 0
    assert "跳过知识库初始化" in capsys.readouterr().out
