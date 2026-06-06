"""Audit log — every sensitive action Ollie takes is recorded here.

Used for: trust ("show me what you did today"), debugging, undo, security review.
"""
from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy import Column, Integer, String, Text, Float

from ram.core.memory import Base, db, _engine


class AuditEntry(Base):
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    ts = Column(Float, default=time.time, index=True)
    user_id = Column(String, index=True)
    action = Column(String, index=True)
    payload = Column(Text, default="")
    result = Column(Text, default="")


Base.metadata.create_all(_engine)


def record(user_id: str, action: str, payload: Any = None, result: str = "") -> None:
    try:
        with db() as s:
            s.add(AuditEntry(
                user_id=user_id or "system",
                action=action,
                payload=json.dumps(payload, default=str)[:4000] if payload else "",
                result=str(result)[:2000],
            ))
    except Exception:
        pass


def recent(limit: int = 50) -> list[dict]:
    with db() as s:
        rows = s.query(AuditEntry).order_by(AuditEntry.ts.desc()).limit(limit).all()
        return [
            {
                "ts": r.ts, "user": r.user_id, "action": r.action,
                "payload": r.payload, "result": r.result,
            } for r in rows
        ]


def since(seconds_ago: int) -> list[dict]:
    cutoff = time.time() - seconds_ago
    with db() as s:
        rows = s.query(AuditEntry).filter(AuditEntry.ts >= cutoff).order_by(AuditEntry.ts).all()
        return [
            {"ts": r.ts, "user": r.user_id, "action": r.action,
             "payload": r.payload, "result": r.result} for r in rows
        ]
