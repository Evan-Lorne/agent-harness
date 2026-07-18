from __future__ import annotations

import re

from harness.cron.service import CronService
from harness.cron.types import CronJobConfig
from harness.tools.registry import ToolDefinition


def create_cron_tool(service: CronService) -> ToolDefinition:
    async def execute(args: dict) -> str:
        action = args.get("action")
        if action == "list":
            jobs = service.list()
            if not jobs:
                return "当前没有定时任务"
            return "\n\n".join(
                f"[{status}] {config.id} — {config.name}\n  调度: {config.schedule}{f' | 上次: {last.status} @ {last.finished_at}' if last else ''}"
                for config, status, last in jobs
            )
        if action == "add":
            if (
                not args.get("id")
                or not args.get("name")
                or not args.get("schedule")
                or not (args.get("prompt") or args.get("handler"))
            ):
                return "添加任务需要: id, name, schedule, prompt 或 handler"
            schedule = args["schedule"]
            schedule_type = (
                "interval" if schedule.startswith("every") else "once" if re.match(r"^\d{4}-", schedule) else "cron"
            )
            payload = (
                {"type": "handler", "handler": args["handler"]}
                if args.get("handler")
                else {"type": "agent", "prompt": args["prompt"]}
            )
            try:
                service.add(CronJobConfig(args["id"], args["name"], schedule, schedule_type, True, payload, "runtime"))
                return f'✓ 任务 "{args["name"]}" 已创建，调度: {schedule}'
            except Exception as error:
                return f"✗ 创建失败: {error}"
        if action in {"remove", "enable", "disable"}:
            if not args.get("id"):
                return "需要指定任务 id"
            success = getattr(service, action)(args["id"])
            return (
                (
                    "✓ 已启用"
                    if action == "enable"
                    else "✓ 已禁用"
                    if action == "disable"
                    else f"✓ 任务 {args['id']} 已删除"
                )
                if success
                else "✗ 任务不存在"
            )
        if action == "run":
            return "需要指定任务 id" if not args.get("id") else await service.run_now(args["id"])
        if action == "logs":
            logs = service.get_recent_logs(args.get("id"), 5)
            return (
                "暂无执行记录"
                if not logs
                else "\n\n".join(
                    f"[{log.status}] {log.job_id} @ {log.started_at}\n  {(log.output or log.error or '')[:100]}"
                    for log in logs
                )
            )
        return f"未知操作: {action}"

    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "add", "remove", "run", "enable", "disable", "logs"]},
            "id": {"type": "string"},
            "name": {"type": "string"},
            "schedule": {"type": "string"},
            "prompt": {"type": "string"},
            "handler": {"type": "string"},
        },
        "required": ["action"],
    }
    return ToolDefinition("cron_manage", "管理定时任务。支持创建、删除、查看、立即执行定时任务。", parameters, execute)
