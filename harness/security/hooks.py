from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class HookResult:
    action: str
    reason: str | None = None
    modified_input: Any = None
    modified_output: Any = None


Hook = Callable[..., HookResult | Awaitable[HookResult]]


class HookPipeline:
    def __init__(self) -> None:
        self.user_hooks: list[tuple[str, Hook]] = []
        self.pre_hooks: list[tuple[str, Hook]] = []
        self.post_hooks: list[tuple[str, Hook]] = []
        self.stop_hooks: list[tuple[str, Hook]] = []

    def register_user(self, name: str, function: Hook) -> None:
        self.user_hooks.append((name, function))

    def register_pre(self, name: str, function: Hook) -> None:
        self.pre_hooks.append((name, function))

    def register_post(self, name: str, function: Hook) -> None:
        self.post_hooks.append((name, function))

    def register_stop(self, name: str, function: Hook) -> None:
        self.stop_hooks.append((name, function))

    @staticmethod
    async def _call(function: Hook, *args: Any) -> HookResult:
        result = function(*args)
        return await result if inspect.isawaitable(result) else result

    async def run_pre(self, tool_name: str, input_value: Any) -> HookResult:
        current_input = input_value
        for name, function in self.pre_hooks:
            try:
                result = await self._call(function, tool_name, current_input)
                if result.action == "block":
                    print(f"  [hook:{name}] 拦截 {tool_name}: {result.reason}")
                    return result
                if result.action == "modify" and result.modified_input is not None:
                    current_input = result.modified_input
                    print(f"  [hook:{name}] 修改了 {tool_name} 的输入")
            except Exception as error:
                print(f"  [hook:{name}] pre 异常: {error}")
        return HookResult("allow", modified_input=current_input)

    async def run_user(self, query: str) -> HookResult:
        current_query = query
        for name, function in self.user_hooks:
            try:
                result = await self._call(function, current_query)
                if result.action == "block":
                    print(f"  [hook:{name}] 拦截用户输入: {result.reason}")
                    return result
                if result.action == "modify" and isinstance(result.modified_input, str):
                    current_query = result.modified_input
            except Exception as error:
                print(f"  [hook:{name}] user 异常: {error}")
        return HookResult("allow", modified_input=current_query)

    async def run_post(self, tool_name: str, input_value: Any, output: Any) -> HookResult:
        current_output = output
        for name, function in self.post_hooks:
            try:
                result = await self._call(function, tool_name, input_value, current_output)
                if result.action == "modify" and result.modified_output is not None:
                    current_output = result.modified_output
                    print(f"  [hook:{name}] 修改了 {tool_name} 的输出")
            except Exception as error:
                print(f"  [hook:{name}] post 异常: {error}")
        return HookResult("allow", modified_output=current_output)

    async def run_stop(self, messages: list[dict[str, Any]]) -> HookResult:
        for name, function in self.stop_hooks:
            try:
                result = await self._call(function, messages)
                if result.action in {"block", "continue"}:
                    print(f"  [hook:{name}] 阻止本轮结束")
                    return result
            except Exception as error:
                print(f"  [hook:{name}] stop 异常: {error}")
        return HookResult("allow")

    def list(self) -> dict[str, list[str]]:
        return {
            "user": [name for name, _ in self.user_hooks],
            "pre": [name for name, _ in self.pre_hooks],
            "post": [name for name, _ in self.post_hooks],
            "stop": [name for name, _ in self.stop_hooks],
        }
