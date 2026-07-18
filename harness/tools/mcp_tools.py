from __future__ import annotations

from harness.config.schema import MCPServerConfig
from harness.tools.mcp import StdioMCPClient
from harness.tools.registry import ToolDefinition, ToolRegistry


def create_connect_mcp_tool(registry: ToolRegistry, servers: list[MCPServerConfig]) -> ToolDefinition:
    configured = {server.name: server for server in servers if server.enabled}
    connected: set[str] = set()

    async def execute(args: dict) -> str:
        name = args.get("name", "")
        server = configured.get(name)
        if not server:
            return f"未配置 MCP Server: {name}"
        if name in connected:
            return f"MCP Server 已连接: {name}"
        client = StdioMCPClient(server.command, server.args, server.env)
        try:
            tools = await registry.register_mcp_server(name, client)
        except Exception as error:
            return f"MCP 连接失败: {error}"
        connected.add(name)
        return f"MCP Server {name} 已连接，发现 {len(tools)} 个工具: {', '.join(tools)}"

    return ToolDefinition(
        "connect_mcp",
        "按配置名称连接真实 stdio MCP Server，并把发现的工具加入当前工具池。",
        {
            "type": "object",
            "properties": {"name": {"type": "string", "enum": sorted(configured)}},
            "required": ["name"],
            "additionalProperties": False,
        },
        execute,
    )
