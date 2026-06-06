"""SMS channel via Twilio — Ollie's signature "just a text" interface.

Inbound: Twilio posts to /twilio/sms (wired in http_channel).
Outbound: this channel sends text messages via Twilio's REST API.

A user_id of the form `sms:+1XXXXXXXXXX` will be routed here.
"""
from __future__ import annotations

from loguru import logger

from myassistant.channels.base import Channel
from myassistant.core.config import settings


class SMSChannel(Channel):
    name = "sms"

    def __init__(self, handle):
        super().__init__(handle)
        self._client = None

    async def start(self) -> None:
        if not (settings.twilio_account_sid and settings.twilio_auth_token
                and settings.twilio_sms_from):
            logger.warning("SMS disabled: missing TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_SMS_FROM")
            return
        try:
            from twilio.rest import Client
            self._client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
            logger.info(f"SMS (Twilio) ready, from {settings.twilio_sms_from}")
        except ImportError:
            logger.error("twilio package not installed")

    async def send(self, user_id: str, text: str) -> None:
        if not self._client:
            return
        # Only handle sms:* user ids (or raw E.164)
        if user_id.startswith("sms:"):
            to = user_id.split("sms:", 1)[1]
        elif user_id.startswith("+"):
            to = user_id
        else:
            return
        if not to:
            return
        # Twilio SMS hard limit ~1600 chars; chunk politely
        chunks = [text[i:i + 1500] for i in range(0, len(text), 1500)] or [""]
        for c in chunks:
            try:
                self._client.messages.create(
                    from_=settings.twilio_sms_from, to=to, body=c,
                )
            except Exception as e:
                logger.exception(f"SMS send failed: {e}")
                break
