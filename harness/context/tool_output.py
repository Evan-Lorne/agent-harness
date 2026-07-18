from __future__ import annotations

import json
from typing import Any


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(value)


def tool_output_to_text(output: Any) -> str:
    if isinstance(output, str):
        return output
    if not isinstance(output, dict):
        return _stringify(output)
    output_type = output.get("type")
    if output_type in {"text", "error-text", "json", "error-json"}:
        return _stringify(output.get("value"))
    if output_type == "execution-denied":
        reason = output.get("reason")
        return reason if isinstance(reason, str) else "execution denied"
    if output_type == "content":
        value = output.get("value")
        if not isinstance(value, list):
            return _stringify(value)
        return "\n".join(
            str(part.get("text", "")) if isinstance(part, dict) and part.get("type") == "text" else _stringify(part)
            for part in value
        )
    return _stringify(output)


def is_tool_output_error(output: Any) -> bool:
    return isinstance(output, dict) and output.get("type") in {"error-text", "error-json", "execution-denied"}


def replace_tool_output_text(output: Any, text: str) -> Any:
    if isinstance(output, str):
        return text
    if not isinstance(output, dict):
        return output
    replaced = dict(output)
    if output.get("type") in {"text", "json", "error-text", "error-json"}:
        replaced["value"] = text
    elif output.get("type") == "content":
        replaced["value"] = [{"type": "text", "text": text}]
    elif output.get("type") == "execution-denied":
        replaced["reason"] = text
    return replaced
