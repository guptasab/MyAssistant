"""Channel base class. Every channel implements `start()` and pushes inbound
messages into the agent. Channels can also receive push notifications (e.g.
reminders firing) via `send(user_id, text)`.
"""
from __future__ import annotations

import abc
import asyncio
from typing import Awaitable, Callable


HandleFn = Callable[[str, str], Awaitable["AgentReply"]]  # noqa


class Channel(abc.ABC):
    name: str = "base"

    def __init__(self, handle: HandleFn):
        self.handle = handle

    @abc.abstractmethod
    async def start(self) -> None: ...

    async def stop(self) -> None:
        return

    async def send(self, user_id: str, text: str) -> None:
        """Push a message to the user (for proactive notifications)."""
        return
