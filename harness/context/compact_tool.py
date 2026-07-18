from harness.tools.registry import ToolDefinition


async def _request_compact(_args: dict) -> str:
    return "[Compaction requested. The harness will summarize history before the next model step.]"


compact_tool = ToolDefinition(
    "compact",
    "主动压缩当前会话历史，在上下文变得冗长时使用。",
    {"type": "object", "properties": {}, "additionalProperties": False},
    _request_compact,
)
