from __future__ import annotations

from typing import Literal

Role = Literal["owner", "collaborator", "guest"]

TOOL_ACCESS: dict[str, dict[str, list[str] | str]] = {
    "owner": {"allow": "*", "deny": []},
    "collaborator": {"allow": "*", "deny": ["bash"]},
    "guest": {
        "allow": ["get_weather", "calculator", "read_file", "list_directory", "glob", "grep", "rag_search"],
        "deny": [],
    },
}


def can_use_tool(role: Role, tool_name: str) -> bool:
    access = TOOL_ACCESS[role]
    if tool_name in access["deny"]:
        return False
    return access["allow"] == "*" or tool_name in access["allow"]


def filter_tools_for_role(tool_names: list[str], role: Role) -> list[str]:
    return [name for name in tool_names if can_use_tool(role, name)]
