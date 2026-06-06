"""Telegram channel — DM bot. Supports text + voice notes."""
from __future__ import annotations

from loguru import logger

from myassistant.channels.base import Channel
from myassistant.core.config import settings
from myassistant.core import voice


class TelegramChannel(Channel):
    name = "telegram"

    def __init__(self, handle):
        super().__init__(handle)
        self._app = None

    async def start(self) -> None:
        if not settings.telegram_bot_token:
            logger.warning("Telegram disabled: no TELEGRAM_BOT_TOKEN")
            return
        try:
            from telegram import Update
            from telegram.ext import Application, MessageHandler, filters
        except ImportError:
            logger.error("python-telegram-bot not installed")
            return

        owner_chat = settings.telegram_owner_chat_id
        handle = self.handle

        app = Application.builder().token(settings.telegram_bot_token).build()
        self._app = app

        async def on_msg(update, context):
            chat_id = str(update.effective_chat.id)
            if owner_chat and chat_id != owner_chat:
                return
            text = update.message.text or ""
            if update.message.voice:
                f = await update.message.voice.get_file()
                buf = bytes(await f.download_as_bytearray())
                text = (text + "\n" + voice.transcribe(buf, "audio/ogg")).strip()
            if not text:
                return
            reply = await handle(f"telegram:{chat_id}", text)
            await update.message.reply_text(reply.text)

        app.add_handler(MessageHandler(filters.TEXT | filters.VOICE, on_msg))
        # Run polling in background — initialize/start without blocking event loop
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        logger.info("Telegram channel started")

    async def send(self, user_id: str, text: str) -> None:
        if not (self._app and settings.telegram_owner_chat_id):
            return
        try:
            await self._app.bot.send_message(chat_id=int(settings.telegram_owner_chat_id), text=text)
        except Exception as e:
            logger.exception(f"Telegram push failed: {e}")
