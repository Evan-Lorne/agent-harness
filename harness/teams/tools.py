from __future__ import annotations

from harness.teams.manager import TeamManager
from harness.tools.registry import ToolDefinition


def create_team_tools(manager: TeamManager) -> list[ToolDefinition]:
    async def spawn(args: dict) -> str:
        try:
            return manager.spawn(args["name"], args.get("role", "general"), args.get("task", ""))
        except (KeyError, ValueError) as error:
            return f"启动失败: {error}"

    async def send(args: dict) -> str:
        try:
            return manager.send(args.get("from", "lead"), args["to"], args["content"])
        except (KeyError, ValueError) as error:
            return f"发送失败: {error}"

    async def inbox(_args: dict) -> str:
        values = manager.collect_lead_inbox()
        return "收件箱为空" if not values else "\n".join(values)

    async def shutdown(args: dict) -> str:
        try:
            return f"关机请求已发送: {manager.request_shutdown(args['teammate'])}"
        except (KeyError, ValueError) as error:
            return f"请求失败: {error}"

    async def request_plan(args: dict) -> str:
        try:
            return f"计划请求已发送: {manager.request_plan(args['teammate'], args['prompt'])}"
        except (KeyError, ValueError) as error:
            return f"请求失败: {error}"

    async def review(args: dict) -> str:
        try:
            return manager.review_plan(args["request_id"], args["approve"], args.get("feedback", ""))
        except (KeyError, ValueError) as error:
            return f"审批失败: {error}"

    async def submit(args: dict) -> str:
        try:
            return manager.submit_plan(args["from"], args["request_id"], args["plan"])
        except (KeyError, ValueError) as error:
            return f"提交失败: {error}"

    return [
        ToolDefinition(
            "spawn_teammate",
            "启动有独立上下文和持久收件箱的队友。",
            {
                "type": "object",
                "properties": {"name": {"type": "string"}, "role": {"type": "string"}, "task": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            },
            spawn,
        ),
        ToolDefinition(
            "send_message",
            "向 Lead 或队友发送消息。",
            {
                "type": "object",
                "properties": {"from": {"type": "string"}, "to": {"type": "string"}, "content": {"type": "string"}},
                "required": ["to", "content"],
                "additionalProperties": False,
            },
            send,
            True,
        ),
        ToolDefinition(
            "check_inbox",
            "读取 Lead 收件箱并处理协议回复。",
            {"type": "object", "properties": {}, "additionalProperties": False},
            inbox,
            True,
            True,
        ),
        ToolDefinition(
            "request_shutdown",
            "通过 request_id 握手请求队友关机。",
            {
                "type": "object",
                "properties": {"teammate": {"type": "string"}},
                "required": ["teammate"],
                "additionalProperties": False,
            },
            shutdown,
        ),
        ToolDefinition(
            "request_plan",
            "请求队友提交计划。",
            {
                "type": "object",
                "properties": {"teammate": {"type": "string"}, "prompt": {"type": "string"}},
                "required": ["teammate", "prompt"],
                "additionalProperties": False,
            },
            request_plan,
        ),
        ToolDefinition(
            "review_plan",
            "批准或拒绝带 request_id 的队友计划。",
            {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string"},
                    "approve": {"type": "boolean"},
                    "feedback": {"type": "string"},
                },
                "required": ["request_id", "approve"],
                "additionalProperties": False,
            },
            review,
        ),
        ToolDefinition(
            "submit_plan",
            "队友提交计划供 Lead 审批。",
            {
                "type": "object",
                "properties": {
                    "from": {"type": "string"},
                    "request_id": {"type": "string"},
                    "plan": {"type": "string"},
                },
                "required": ["from", "request_id", "plan"],
                "additionalProperties": False,
            },
            submit,
        ),
    ]
