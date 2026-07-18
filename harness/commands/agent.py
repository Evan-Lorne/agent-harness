from __future__ import annotations

from harness.agents.registry import SubAgentRegistry
from harness.commands import CommandContext, CommandHandler


def create_agent_commands(registry: SubAgentRegistry) -> list[CommandHandler]:
    async def handler(command: str, _context: CommandContext) -> bool:
        if not command.startswith("/agents"):
            return False
        runs = registry.get_all_runs()
        if not runs:
            print("  暂无子 Agent 记录")
            return True
        print(f"  子 Agent 记录 ({len(runs)}):")
        for run in runs:
            icon = "⟳" if run.status == "running" else "✓" if run.status == "completed" else "✗"
            detail = f"{(run.result or '')[:60]}..." if run.status == "completed" else run.error or "执行中..."
            print(f"    {icon} {run.id} (depth={run.depth}) — {run.task[:40]}\n      {detail}")
        active = len(registry.get_active_runs())
        completed = sum(run.status == "completed" for run in runs)
        failed = sum(run.status in {"error", "timeout"} for run in runs)
        config = registry.config
        print(f"\n  活跃: {active}/{config.max_concurrent} | 完成: {completed} | 失败: {failed}")
        print(f"  最大深度: {config.max_spawn_depth} | 最大并发: {config.max_concurrent}")
        return True

    return [handler]
