from harness.tools.registry import ToolDefinition, ToolRegistry


def create_tool_search_tool(registry: ToolRegistry) -> ToolDefinition:
    async def execute(args: dict):
        results = registry.search_tools(args["query"])
        if not results:
            return f"没有找到工具: {args['query']}"
        return [{"name": item.name, "description": item.description, "parameters": item.parameters} for item in results]

    return ToolDefinition(
        "tool_search",
        "获取延迟工具的完整定义",
        {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        execute,
        True,
        True,
    )
