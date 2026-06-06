"""Discord channel — direct messages with the owner.

DMs are private 1:1, so we treat the owner's user_id as the conversation key.
Voice notes are transcribed via the voice module if attached.
"""
from __future__ import annotations

import asyncio
from loguru import logger

from myassistant.channels.base import Channel
from myassistant.core.config import settings
from myassistant.core import voice


class DiscordChannel(Channel):
    name = "discord"

    def __init__(self, handle):
        super().__init__(handle)
        self._client = None
        self._owner_id = settings.discord_owner_user_id

    async def start(self) -> None:
        if not settings.discord_bot_token:
            logger.warning("Discord disabled: no DISCORD_BOT_TOKEN")
            return
        try:
            import discord
        except ImportError:
            logger.error("discord.py not installed")
            return

        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True
        client = discord.Client(intents=intents)
        self._client = client
        handle = self.handle
        owner_id = self._owner_id

        @client.event
        async def on_ready():
            logger.info(f"Discord connected as {client.user}")

        @client.event
        async def on_message(msg):
            if msg.author.bot:
                return
            # Only respond to DMs from the owner (or @mentions in shared servers).
            is_dm = isinstance(msg.channel, discord.DMChannel)
            is_owner = owner_id and str(msg.author.id) == owner_id
            if not (is_dm and is_owner):
                return

            text = msg.content
            # Handle voice attachments (Whisper)
            for att in msg.attachments:
                if att.content_type and "audio" in att.content_type:
                    data = await att.read()
                    transcript = voice.transcribe(data, mime=att.content_type)
                    text = (text + "\n" + transcript).strip()

            if not text:
                return
            async with msg.channel.typing():
                reply = await handle(f"discord:{msg.author.id}", text)
            await msg.channel.send(reply.text)

        asyncio.create_task(client.start(settings.discord_bot_token))

    async def send(self, user_id: str, text: str) -> None:
        if not (self._client and self._owner_id):
            return
        try:
            user = await self._client.fetch_user(int(self._owner_id))
            await user.send(text)
        except Exception as e:
            logger.exception(f"Discord push failed: {e}")
