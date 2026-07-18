from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Callable
from typing import Any, cast

from openai import AsyncOpenAI

from harness.types import Message, ModelStep, ModelUsage, StreamPart


class OpenAIModel:
    """Small OpenAI-compatible adapter for the project's internal model protocol."""

    def __init__(self, model: str, *, api_key: str, base_url: str | None = None) -> None:
        self.model_id = model
        self.fallback_model_id = os.getenv("FALLBACK_MODEL_ID", "")
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url or None)

    def switch_to_fallback(self) -> bool:
        if not self.fallback_model_id or self.fallback_model_id == self.model_id:
            return False
        self.model_id = self.fallback_model_id
        return True

    @staticmethod
    def _to_openai_messages(system: str, messages: list[Message]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for message in messages:
            role, content = message.get("role"), message.get("content")
            if role == "assistant" and isinstance(content, list):
                text = "".join(
                    str(part.get("text", ""))
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
                calls = []
                for part in content:
                    if not isinstance(part, dict) or part.get("type") != "tool-call":
                        continue
                    calls.append(
                        {
                            "id": part.get("toolCallId"),
                            "type": "function",
                            "function": {
                                "name": part.get("toolName"),
                                "arguments": json.dumps(part.get("input", {}), ensure_ascii=False),
                            },
                        }
                    )
                value: dict[str, Any] = {"role": "assistant", "content": text or None}
                if calls:
                    value["tool_calls"] = calls
                converted.append(value)
            elif role == "tool" and isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    output = part.get("output", "")
                    converted.append(
                        {
                            "role": "tool",
                            "tool_call_id": part.get("toolCallId"),
                            "content": output if isinstance(output, str) else json.dumps(output, ensure_ascii=False),
                        }
                    )
            else:
                converted.append({"role": role, "content": content if isinstance(content, str) else str(content or "")})
        return converted

    async def run_step(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: dict[str, Any],
        tool_choice: str = "auto",
        on_text_delta: Callable[[str], None] | None = None,
        max_output_tokens: int | None = None,
    ) -> ModelStep:
        definitions = [
            {
                "type": "function",
                "function": {
                    "name": value["name"],
                    "description": value["description"],
                    "parameters": value["parameters"],
                },
            }
            for value in tools.values()
        ]
        kwargs: dict[str, Any] = {
            "model": self.model_id,
            "messages": self._to_openai_messages(system, messages),
            "tool_choice": tool_choice,
        }
        if definitions:
            kwargs["tools"] = definitions
            kwargs["parallel_tool_calls"] = True
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}
        if max_output_tokens:
            kwargs["max_tokens"] = max_output_tokens
        response = cast(AsyncIterator[Any], await self.client.chat.completions.create(**kwargs))
        text_parts: list[str] = []
        pending_calls: dict[int, dict[str, str]] = {}
        usage: Any = None
        finish_reason: str | None = None
        async for chunk in response:
            if chunk.usage:
                usage = chunk.usage
            for choice in chunk.choices:
                if getattr(choice, "finish_reason", None):
                    finish_reason = choice.finish_reason
                delta = choice.delta
                if delta.content:
                    text_parts.append(delta.content)
                    if on_text_delta:
                        on_text_delta(delta.content)
                for fragment in delta.tool_calls or []:
                    call = pending_calls.setdefault(fragment.index, {"id": "", "name": "", "arguments": ""})
                    if fragment.id:
                        call["id"] += fragment.id
                    if fragment.function and fragment.function.name:
                        call["name"] += fragment.function.name
                    if fragment.function and fragment.function.arguments:
                        call["arguments"] += fragment.function.arguments

        assistant_parts: list[dict[str, Any]] = []
        stream_parts: list[StreamPart] = []
        text = "".join(text_parts)
        if text:
            assistant_parts.append({"type": "text", "text": text})
            stream_parts.append(StreamPart("text-delta", text=text))
        calls: list[tuple[str, str, dict[str, Any], str | None]] = []
        complete_calls = {} if finish_reason in {"length", "max_tokens"} else pending_calls
        for index, call in sorted(complete_calls.items()):
            parse_error = None
            try:
                arguments = json.loads(call["arguments"] or "{}")
            except json.JSONDecodeError:
                arguments = {}
                parse_error = "工具参数不是有效 JSON"
            call_id = call["id"] or f"call-{index}"
            name = call["name"]
            calls.append((call_id, name, arguments, parse_error))
            assistant_parts.append({"type": "tool-call", "toolCallId": call_id, "toolName": name, "input": arguments})
            stream_parts.append(StreamPart("tool-call", tool_name=name, tool_call_id=call_id, input=arguments))

        response_messages: list[Message] = [{"role": "assistant", "content": assistant_parts}]
        if calls:

            async def execute(
                call: tuple[str, str, dict[str, Any], str | None],
            ) -> tuple[str, str, dict[str, Any], Any]:
                call_id, name, arguments, parse_error = call
                tool = tools.get(name)
                if parse_error:
                    output = f"[工具执行失败] {parse_error}"
                else:
                    try:
                        output = await tool["execute"](arguments) if tool else f"工具不存在: {name}"
                    except Exception as error:
                        output = f"[工具执行失败] {type(error).__name__}: {error}"
                return call_id, name, arguments, output

            results = await asyncio.gather(*(execute(call) for call in calls))
            tool_content: list[dict[str, Any]] = []
            for call_id, name, arguments, output in results:
                tool_content.append({"type": "tool-result", "toolCallId": call_id, "toolName": name, "output": output})
                stream_parts.append(
                    StreamPart("tool-result", tool_name=name, tool_call_id=call_id, input=arguments, output=output)
                )
            response_messages.append({"role": "tool", "content": tool_content})

        cached = 0
        details = getattr(usage, "prompt_tokens_details", None) if usage else None
        if details:
            cached = getattr(details, "cached_tokens", 0) or 0
        model_usage = ModelUsage(
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            cached_input_tokens=cached,
        )
        return ModelStep(response_messages, model_usage, stream_parts, finish_reason)

    async def generate(self, *, system: str, prompt: str) -> str:
        response = await self.client.chat.completions.create(
            model=self.model_id, messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content or ""
