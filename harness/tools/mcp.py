from __future__ import annotations

import importlib
import os
from contextlib import AsyncExitStack
from typing import Any


class StdioMCPClient:
    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        *,
        client_name: str = "agent-harness",
        client_version: str = "1.0.0",
    ) -> None:
        self.command = command
        self.args = args or []
        self.env = env
        self.client_name = client_name
        self.client_version = client_version
        self.stack: AsyncExitStack | None = None
        self.session: Any = None

    async def connect(self) -> None:
        try:
            mcp = importlib.import_module("mcp")
            stdio = importlib.import_module("mcp.client.stdio")
        except ImportError as error:
            raise RuntimeError("真实 MCP 连接需要: uv sync --extra mcp") from error

        self.stack = AsyncExitStack()
        child_env = {**os.environ, **self.env} if self.env else None
        parameters = mcp.StdioServerParameters(command=self.command, args=self.args, env=child_env)
        read, write = await self.stack.enter_async_context(stdio.stdio_client(parameters))
        self.session = await self.stack.enter_async_context(mcp.ClientSession(read, write))
        await self.session.initialize()

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self.session.list_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description or "",
                "inputSchema": tool.inputSchema,
                "isReadOnly": bool(tool.annotations and tool.annotations.readOnlyHint),
                "isDestructive": bool(tool.annotations and tool.annotations.destructiveHint),
            }
            for tool in result.tools
        ]

    async def call_tool(self, name: str, args: dict[str, Any]) -> str:
        result = await self.session.call_tool(name, arguments=args)
        texts = [
            item.text
            for item in result.content
            if getattr(item, "type", None) == "text" and getattr(item, "text", None)
        ]
        return "\n".join(texts) or "(无返回内容)"

    async def close(self) -> None:
        if self.stack:
            await self.stack.aclose()
            self.stack = None


class MockMCPClient:
    async def connect(self) -> None:
        return None

    async def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "list_issues",
                "description": "列出 GitHub 仓库的 Issues",
                "inputSchema": {
                    "type": "object",
                    "properties": {"owner": {"type": "string"}, "repo": {"type": "string"}},
                    "required": ["owner", "repo"],
                },
                "isReadOnly": True,
            },
            {
                "name": "search_repositories",
                "description": "搜索 GitHub 仓库",
                "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
                "isReadOnly": True,
            },
            {
                "name": "get_file_contents",
                "description": "获取仓库中文件的内容",
                "inputSchema": {
                    "type": "object",
                    "properties": {"owner": {"type": "string"}, "repo": {"type": "string"}, "path": {"type": "string"}},
                    "required": ["owner", "repo", "path"],
                },
                "isReadOnly": True,
            },
        ]

    async def call_tool(self, name: str, args: dict[str, Any]) -> str:
        import json

        values = {
            "list_issues": [
                {"number": 42, "title": "支持 MCP 协议接入", "state": "open", "labels": ["enhancement"]},
                {"number": 41, "title": "循环检测阈值可配置化", "state": "open", "labels": ["feature"]},
                {"number": 39, "title": "Token 预算用完后的优雅降级", "state": "closed", "labels": ["bug"]},
            ],
            "search_repositories": [
                {"full_name": "openai/openai-python", "stars": 28000, "description": "OpenAI Python SDK"},
                {"full_name": "modelcontextprotocol/python-sdk", "stars": 19000, "description": "MCP Python SDK"},
            ],
        }
        if name == "get_file_contents":
            return (
                f"# README\n\nThis is a mock file content for {args.get('owner')}/{args.get('repo')}/{args.get('path')}"
            )
        return json.dumps(values.get(name, f"未知工具: {name}"), ensure_ascii=False, indent=2)

    async def close(self) -> None:
        return None
