# ============================================================
# services.py — Discord messaging utilities
# Owns send_to_channel, send_long_message, and post_status
# so both bot.py and orchestrator.py can import them without
# circular dependencies.
# ============================================================

import discord
from config import STATUS_CHANNEL


async def send_to_channel(
    guild, channel_name: str, message: str
) -> None:
    """Finds a channel by name and sends a message to it."""
    channel = discord.utils.get(
        guild.channels, name=channel_name
    )
    if channel:
        await channel.send(message)


async def send_long_message(
    channel, message: str
) -> None:
    """Splits messages exceeding Discord's 2000 char limit."""
    if len(message) <= 2000:
        await channel.send(message)
    else:
        for i in range(0, len(message), 2000):
            await channel.send(message[i:i + 2000])


async def post_status(
    guild,
    message: str,
    memory_mode: str = "global"
) -> None:
    """
    Posts a one-line status to STATUS_CHANNEL.
    Skips ephemeral channels.
    """
    if memory_mode == "ephemeral":
        return
    await send_to_channel(guild, STATUS_CHANNEL, message)
