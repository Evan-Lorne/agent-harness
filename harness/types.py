from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

Message = dict[str, Any]


@dataclass(slots=True)
class ModelUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass(slots=True)
class StreamPart:
    type: str
    text: str = ""
    tool_name: str = ""
    tool_call_id: str = ""
    input: dict[str, Any] = field(default_factory=dict)
    output: Any = None


@dataclass(slots=True)
class ModelStep:
    messages: list[Message]
    usage: ModelUsage
    parts: list[StreamPart]
    finish_reason: str | None = None

    async def stream(self) -> AsyncIterator[StreamPart]:
        for part in self.parts:
            yield part


class Model(Protocol):
    model_id: str

    async def run_step(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: dict[str, Any],
        tool_choice: str = "auto",
        on_text_delta: Callable[[str], None] | None = None,
        max_output_tokens: int | None = None,
    ) -> ModelStep: ...

    async def generate(self, *, system: str, prompt: str) -> str: ...


def content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content or "")
    texts: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            texts.append(str(part.get("text", "")))
        elif part.get("type") == "tool-result":
            output = part.get("output")
            if isinstance(output, dict) and "value" in output:
                texts.append(str(output["value"]))
            elif output is not None:
                texts.append(str(output))
    return "".join(texts)
