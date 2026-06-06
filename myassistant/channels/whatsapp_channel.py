"""WhatsApp channel via Twilio (webhook lives inside the HTTP channel).

Twilio sends inbound messages to /twilio/whatsapp on the HTTP server. Configure
that URL in your Twilio console for the sandbox or production number.
"""
from __future__ import annotations

from loguru import logger

from myassistant.channels.base import Channel
from myassistant.core.config import settings


class WhatsAppChannel(Channel):
    """Outbound channel wrapper; inbound handled via Twilio webhook in http_channel."""
    name = "whatsapp"

    def __init__(self, handle):
        super().__init__(handle)
        self._client = None

    async def start(self) -> None:
        if not (settings.twilio_account_sid and settings.twilio_auth_token):
            logger.warning("WhatsApp disabled: no Twilio creds")
            return
        try:
            from twilio.rest import Client
            self._client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
            logger.info("WhatsApp (Twilio) ready for outbound")
        except ImportError:
            logger.error("twilio not installed")

    async def send(self, user_id: str, text: str) -> None:
        if not self._client:
            return
        # user_id like "whatsapp:+15551234567"
        to = user_id if user_id.startswith("whatsapp:") else f"whatsapp:{user_id}"
        try:
            self._client.messages.create(
                from_=settings.twilio_whatsapp_from, to=to, body=text,
            )
        except Exception as e:
            logger.exception(f"WhatsApp send failed: {e}")
