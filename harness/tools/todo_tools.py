from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from harness.tools.registry import ToolDefinition

TodoStatus = Literal["pending", "in_progress", "completed"]


@dataclass(slots=True)
class TodoItem:
    content: str
    status: TodoStatus


class TodoStore:
    def __init__(self) -> None:
        self.items: list[TodoItem] = []

    def replace(self, values: list[dict[str, str]]) -> list[TodoItem]:
        items: list[TodoItem] = []
        for value in values:
            content, status = value.get("content", "").strip(), value.get("status", "")
            if not content:
                continue
            if status not in {"pending", "in_progress", "completed"}:
                raise ValueError(f"非法 TODO 状态: {status}")
            items.append(TodoItem(content, cast(TodoStatus, status)))
        if sum(item.status == "in_progress" for item in items) > 1:
            raise ValueError("同一时间只能有一个 in_progress 项")
        self.items = items
        return items

    def render(self) -> str:
        if not self.items:
            return "TODO 列表为空"
        marks = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}
        return "\n".join(f"{marks[item.status]} {item.content}" for item in self.items)


def create_todo_tool(store: TodoStore) -> ToolDefinition:
    async def execute(args: dict) -> str:
        try:
            store.replace(args["todos"])
        except (KeyError, ValueError) as error:
            return f"TODO 更新失败: {error}"
        return store.render()

    return ToolDefinition(
        "todo_write",
        "创建或更新当前任务的执行清单。多步骤任务开始前先列清单，并随进度更新状态。",
        {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string"},
                            "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                        },
                        "required": ["content", "status"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["todos"],
            "additionalProperties": False,
        },
        execute,
    )
