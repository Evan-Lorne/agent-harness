from __future__ import annotations

from harness.memory.store import MemoryStore
from harness.tools.registry import ToolDefinition


def create_memory_tool(memory_store: MemoryStore) -> ToolDefinition:
    async def execute(args: dict) -> str:
        action = args.get("action")
        if action == "save":
            if not args.get("name") or not args.get("type") or not args.get("content"):
                return "保存失败：需要 name、type、content 参数"
            filename = memory_store.save(
                {
                    "name": args["name"],
                    "description": args.get("description") or args["name"],
                    "type": args["type"],
                    "content": args["content"],
                }
            )
            return f"已保存到记忆: {filename}"
        if action == "list":
            entries = memory_store.list()
            return (
                "当前没有存储任何记忆。"
                if not entries
                else f"记忆列表（共 {len(entries)} 条记忆）：\n"
                + "\n".join(f"  [{entry.type}] {entry.name} — {entry.description}" for entry in entries)
            )
        if action == "search":
            results = memory_store.search(args.get("query", ""))
            return (
                f'没有找到与 "{args.get("query")}" 相关的记忆。'
                if not results
                else f"搜索结果（{len(results)} 条匹配）：\n"
                + "\n".join(f"  [{hit.entry.type}] {hit.entry.name} — {hit.entry.description}" for hit in results)
            )
        if action == "read":
            if not args.get("filename"):
                return "读取失败：需要 filename 参数"
            try:
                return memory_store.load_file(args["filename"]) or f"文件不存在: {args['filename']}"
            except ValueError as error:
                return f"读取失败：{error}"
        if action == "delete":
            if not args.get("filename"):
                return "删除失败：需要 filename 参数"
            try:
                return (
                    f"已删除: {args['filename']}"
                    if memory_store.delete(args["filename"])
                    else f"文件不存在: {args['filename']}"
                )
            except ValueError as error:
                return f"删除失败：{error}"
        if action == "lint":
            reports = memory_store.lint()
            if not reports:
                return "记忆库健康，没有发现问题。"
            lines = [f"lint 报告（{len(reports)} 条记忆有问题）："]
            for report in reports:
                lines.append(f"\n[{report.entry.type}] {report.entry.name} ({report.entry.file_path})")
                lines.extend(f"  - {issue.message}" for issue in report.issues)
            return "\n".join(lines)
        return f"未知操作: {action}"

    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["save", "list", "search", "read", "delete", "lint"]},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "type": {"type": "string", "enum": ["user", "feedback", "project", "reference"]},
            "content": {"type": "string"},
            "query": {"type": "string"},
            "filename": {"type": "string"},
        },
        "required": ["action"],
        "additionalProperties": False,
    }
    return ToolDefinition(
        "memory",
        "管理跨会话记忆。action: save（保存）| list（列表）| search（搜索）| read（读取）| delete（删除）| lint（检查）",
        parameters,
        execute,
    )
