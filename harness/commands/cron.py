from __future__ import annotations

from harness.commands import CommandContext, CommandHandler
from harness.cron.service import CronService


def create_cron_commands(service: CronService) -> list[CommandHandler]:
    async def handler(command: str, _context: CommandContext) -> bool:
        if not command.startswith("/cron"):
            return False
        subcommand = command[5:].strip()
        if not subcommand or subcommand == "list":
            jobs = service.list()
            if not jobs:
                print("  暂无定时任务")
            else:
                print(f"  定时任务 ({len(jobs)}):")
                for config, status, _last in jobs:
                    icon = (
                        "⟳"
                        if status == "running"
                        else "◉"
                        if status == "scheduled"
                        else "○"
                        if status == "disabled"
                        else "·"
                    )
                    print(f"    {icon} {config.id} — {config.name} [{config.schedule}] ({status})")
        elif subcommand == "logs":
            logs = service.get_recent_logs(limit=10)
            if not logs:
                print("  暂无执行记录")
            else:
                print("  最近执行记录:")
                for log in logs:
                    print(
                        f"    {'✓' if log.status == 'success' else '✗'} {log.job_id} @ {log.started_at} — {(log.output or log.error or '')[:80]}"
                    )
        else:
            print("  用法: /cron [list|logs]")
        return True

    return [handler]
