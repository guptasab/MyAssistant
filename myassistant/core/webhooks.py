"""Outbound webhook dispatcher — let other systems subscribe to Ollie events."""
from __future__ import annotations

import time

import httpx
from loguru import logger
from sqlalchemy import Column, Integer, String, Text, Float, Boolean

from myassistant.core.memory import Base, db, _engine


class Webhook(Base):
    __tablename__ = "webhooks"
    id = Column(Integer, primary_key=True)
    url = Column(String)
    event_pattern = Column(String, default="*")  # 'briefing', 'family.*', etc.
    secret = Column(String, default="")
    enabled = Column(Boolean, default=True)
    created_ts = Column(Float, default=time.time)


Base.metadata.create_all(_engine)


def register(url: str, event_pattern: str = "*", secret: str = "") -> int:
    with db() as s:
        w = Webhook(url=url, event_pattern=event_pattern, secret=secret)
        s.add(w)
        s.flush()
        return w.id


def emit(event: str, payload: dict) -> None:
    with db() as s:
        hooks = s.query(Webhook).filter(Webhook.enabled.is_(True)).all()
    for h in hooks:
        if h.event_pattern not in ("*", event) and not (
            h.event_pattern.endswith("*") and event.startswith(h.event_pattern[:-1])
        ):
            continue
        try:
            httpx.post(h.url, json={"event": event, "payload": payload, "secret": h.secret}, timeout=8)
        except Exception as e:
            logger.warning(f"webhook {h.url} failed: {e}")
