from __future__ import annotations

import re
from pathlib import Path

from harness.commands import CommandContext, CommandHandler


async def memory_handler(command: str, context: CommandContext) -> bool:
    if command not in {"/memory", "memory"}:
        return False
    entries, reports = context.memory_store.list(), context.memory_store.lint()
    print(f"\n[记忆系统] 共 {len(entries)} 条记忆，{len(reports)} 条有警告")
    issue_paths = {report.entry.file_path for report in reports}
    for entry in entries:
        print(f"{'⚠ ' if entry.file_path in issue_paths else '  '} [{entry.type}] {entry.name} — {entry.description}")
    print()
    return True


async def lint_handler(command: str, context: CommandContext) -> bool:
    if command not in {"/lint", "lint"}:
        return False
    reports = context.memory_store.lint()
    if not reports:
        print("\n[lint] 记忆库健康，没有发现问题。\n")
    else:
        print(f"\n[lint] 记忆库 {len(reports)} 条有警告：")
        for report in reports:
            print(f"  {Path(report.entry.file_path).name}  [{report.entry.type}] {report.entry.name}")
            for issue in report.issues:
                print(f"     • {issue.kind}: {issue.message}")
        print()
    return True


async def search_handler(command: str, context: CommandContext) -> bool:
    if not command.startswith("/memory search ") and not command.startswith("搜记忆 "):
        return False
    query = re.sub(r"^/memory search |^搜记忆 ", "", command).strip()
    results = context.memory_store.search(query, 5)
    if not results:
        print(f'\n[记忆搜索] 没有找到与 "{query}" 相关的记忆。\n')
    else:
        print(f'\n[BM25 搜索] "{query}" → {len(results)} 条结果：')
        for hit in results:
            print(f"  [score={hit.score:.2f}] [{hit.entry.type}] {hit.entry.name} — {hit.entry.description}")
        print()
    return True


memory_commands: list[CommandHandler] = [memory_handler, lint_handler, search_handler]
