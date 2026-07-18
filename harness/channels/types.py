from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(slots=True)
class IncomingMessage:
    channel_id: str
    sender_id: str
    sender_name: str
    text: str
    raw: Any = None


@dataclass(slots=True)
class OutgoingMessage:
    channel_id: str
    recipient_id: str
    text: str


class ChannelDefinition(Protocol):
    name: str
    description: str

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def send(self, message: OutgoingMessage) -> None: ...
    def on_message(self, handler: Any) -> None: ...
