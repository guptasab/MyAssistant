"""Send a notification through every active channel. Useful for proactive nudges."""
from __future__ import annotations

from myassistant.core.registry import skill


# Channels register themselves here at startup so notify_owner can fan out.
_CHANNELS: list = []


def register_channel(ch) -> None:
    _CHANNELS.append(ch)


@skill(
    name="notify_owner",
    description="Push a short message to the owner across every connected channel (Discord/Telegram/PWA/etc.).",
)
def notify_owner(message: str) -> str:
    import asyncio
    sent = []
    for ch in _CHANNELS:
        try:
            coro = ch.send("owner", message)
            if asyncio.iscoroutine(coro):
                asyncio.create_task(coro)
            sent.append(ch.name)
        except Exception:
            pass
    return f"notified via: {', '.join(sent) or '(no channels)'}"
