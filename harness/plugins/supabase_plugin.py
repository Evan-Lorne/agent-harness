from __future__ import annotations

import json
import random

from harness.plugins.types import PluginApi, PluginDefinition
from harness.tools.registry import ToolDefinition


def _activate(api: PluginApi) -> None:
    config = api.get_config()
    url = str(config.get("supabaseUrl", ""))
    key = str(config.get("supabaseKey", ""))
    if not url or not key:
        api.log("未配置 SUPABASE_URL / SUPABASE_KEY，使用 Mock 模式")

    async def list_tables(_args: dict) -> str:
        return (
            f"连接 {url} 查询表列表...（真实实现会调用 Supabase API）"
            if url
            else json.dumps(
                {
                    "tables": ["users", "posts", "comments", "sessions"],
                    "note": "Mock 模式 — 配置 SUPABASE_URL 和 SUPABASE_KEY 连接真实数据库",
                },
                ensure_ascii=False,
            )
        )

    async def query(args: dict) -> str:
        table, select, where, limit = args["table"], args.get("select", "*"), args.get("where"), args.get("limit", 10)
        if url:
            return f"SELECT {select} FROM {table}{f' WHERE {where}' if where else ''} LIMIT {limit}"
        data = {
            "users": [
                {"id": 1, "name": "张三", "email": "zhang@example.com", "role": "admin"},
                {"id": 2, "name": "李四", "email": "li@example.com", "role": "user"},
                {"id": 3, "name": "王五", "email": "wang@example.com", "role": "user"},
            ],
            "posts": [
                {"id": 1, "title": "Agent 开发入门", "author_id": 1, "status": "published"},
                {"id": 2, "title": "Plugin 架构设计", "author_id": 1, "status": "draft"},
            ],
            "comments": [{"id": 1, "post_id": 1, "user_id": 2, "content": "写得不错！"}],
            "sessions": [{"id": "sess-001", "user_id": 1, "created_at": "2026-05-01T10:00:00Z"}],
        }
        rows = data.get(table, [])
        if where and "=" in where:
            field, value = where.split("=", 1)
            rows = [row for row in rows if str(row.get(field)) == value]
        return json.dumps(
            {"table": table, "rows": rows[:limit], "total": len(rows)}, ensure_ascii=False, separators=(",", ":")
        )

    async def insert(args: dict) -> str:
        if url:
            return f"INSERT INTO {args['table']} — {json.dumps(args['data'], ensure_ascii=False)}"
        return json.dumps(
            {
                "success": True,
                "table": args["table"],
                "inserted": {"id": random.randrange(1000), **args["data"]},
                "note": "Mock 模式",
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    api.register_tools(
        [
            ToolDefinition(
                "list_tables",
                "列出数据库中所有表",
                {"type": "object", "properties": {}, "required": []},
                list_tables,
                True,
                True,
            ),
            ToolDefinition(
                "query",
                "查询指定表的数据，支持 select / where / limit",
                {
                    "type": "object",
                    "properties": {
                        "table": {"type": "string"},
                        "select": {"type": "string"},
                        "where": {"type": "string"},
                        "limit": {"type": "number"},
                    },
                    "required": ["table"],
                },
                query,
                True,
                True,
            ),
            ToolDefinition(
                "insert",
                "向指定表插入一条记录",
                {
                    "type": "object",
                    "properties": {"table": {"type": "string"}, "data": {"type": "object"}},
                    "required": ["table", "data"],
                },
                insert,
            ),
        ]
    )
    api.log("已注册 3 个工具（list_tables / query / insert）")


def _destroy() -> None:
    print("  [plugin:supabase] 连接已释放")


supabase_plugin = PluginDefinition(
    "supabase",
    "1.0.0",
    "提供 Supabase 数据库操作能力（query / insert / list_tables）",
    _activate,
    {"supabaseUrl": "${SUPABASE_URL}", "supabaseKey": "${SUPABASE_KEY}"},
    _destroy,
)
