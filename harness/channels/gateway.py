from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass

from harness.agent.loop import BudgetState, ContextState, agent_loop
from harness.channels.types import ChannelDefinition, IncomingMessage, OutgoingMessage
from harness.tools.registry import ToolRegistry
from harness.types import Message, Model, content_to_text


@dataclass(slots=True)
class GatewayOptions:
    model: Model
    registry: ToolRegistry
    build_system: Callable[[], str]
    run_lock: asyncio.Lock | None = None


class ChannelGateway:
    def __init__(self, options: GatewayOptions) -> None:
        self.options = options
        self.channels: dict[str, ChannelDefinition] = {}
        self.sessions: dict[str, list[Message]] = {}
        self.budgets: dict[str, BudgetState] = {}
        self.timestamps: dict[str, dict[int, int]] = {}
        self.context_states: dict[str, ContextState] = {}
        self.session_locks: dict[str, asyncio.Lock] = {}
        self.incoming_tasks: set[asyncio.Task[None]] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    def register(self, channel: ChannelDefinition) -> None:
        self.channels[channel.name] = channel
        channel.on_message(lambda message: self._enqueue_incoming(channel.name, message))

    def _enqueue_incoming(self, channel_name: str, message: IncomingMessage) -> None:
        loop = self.loop
        if loop is None or loop.is_closed():
            print(f"  [gateway] 忽略未启动 Channel 的消息: {channel_name}")
            return
        loop.call_soon_threadsafe(self._start_incoming, channel_name, message)

    def _start_incoming(self, channel_name: str, message: IncomingMessage) -> None:
        task = asyncio.create_task(self._handle_incoming(channel_name, message))
        self.incoming_tasks.add(task)
        task.add_done_callback(self._incoming_done)

    def _incoming_done(self, task: asyncio.Task[None]) -> None:
        self.incoming_tasks.discard(task)
        if task.cancelled():
            return
        if error := task.exception():
            print(f"  [gateway] 消息处理失败: {error}")

    async def start_all(self) -> None:
        self.loop = asyncio.get_running_loop()
        for name, channel in self.channels.items():
            try:
                await channel.start()
                print(f"  [gateway] ✓ {name} 已启动")
            except Exception as error:
                print(f"  [gateway] ✗ {name} 启动失败: {error}")

    async def stop_all(self) -> None:
        if self.channels:
            await asyncio.gather(*(channel.stop() for channel in self.channels.values()), return_exceptions=True)
        tasks = list(self.incoming_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.incoming_tasks.clear()
        self.loop = None

    async def _handle_incoming(self, channel_name: str, message: IncomingMessage) -> None:
        key = f"{channel_name}:{message.sender_id}"
        async with self.session_locks.setdefault(key, asyncio.Lock()):
            print(f"\n  [{channel_name}] {message.sender_name}: {message.text}")
            messages = self.sessions.setdefault(key, [])
            messages.append({"role": "user", "content": message.text})
            timestamps = self.timestamps.setdefault(key, {})
            timestamps[len(messages) - 1] = int(time.time() * 1000)

            async def run() -> None:
                await agent_loop(
                    self.options.model,
                    self.options.registry,
                    messages,
                    self.options.build_system(),
                    budget=self.budgets.setdefault(key, BudgetState()),
                    timestamps=timestamps,
                    context_state=self.context_states.setdefault(key, ContextState()),
                )

            if self.options.run_lock:
                async with self.options.run_lock:
                    await run()
            else:
                await run()
            last = messages[-1] if messages else None
            reply = content_to_text(last.get("content")) if last and last.get("role") == "assistant" else ""
            if reply and channel_name in self.channels:
                await self.channels[channel_name].send(OutgoingMessage(message.channel_id, message.sender_id, reply))
                print(f"  [{channel_name}] → {reply[:80]}{'...' if len(reply) > 80 else ''}")

    def list(self) -> list[tuple[str, str]]:
        return [(channel.name, channel.description) for channel in self.channels.values()]
