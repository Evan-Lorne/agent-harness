from __future__ import annotations

from harness.channels.gateway import ChannelGateway
from harness.commands import CommandContext, CommandHandler


def create_channel_commands(gateway: ChannelGateway) -> list[CommandHandler]:
    async def handler(command: str, _context: CommandContext) -> bool:
        if command not in {"/channel", "/channel list"}:
            return False
        channels = gateway.list()
        if not channels:
            print("\n[channels] 没有注册的通道。\n")
        else:
            print("\n[channels]")
            for name, description in channels:
                print(f"  {name} — {description}")
            print()
        return True

    return [handler]
