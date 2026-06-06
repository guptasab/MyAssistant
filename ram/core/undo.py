"""Undo registry — keep a reversible-action log for the last N sensitive actions.

Each reversible action stores an `undo_fn` description + args so that within
UNDO_TTL_SECONDS the user can type "undo" and reverse it. Not all actions are
reversible (e.g., sent SMS, placed order) — those are marked irreversible and
a receipt SMS is sent instead.
"""
from __future__ import annotations

import json
import time

from sqlalchemy import Column, Integer, String, Text, Float, Boolean

from ram.core.memory import Base, db, _engine

UNDO_TTL = 300  # 5 min window
MAX_UNDO_STACK = 20


class UndoEntry(Base):
    __tablename__ = "undo_stack"
    id = Column(Integer, primary_key=True)
    user_id = Column(String, index=True)
    skill_name = Column(String)
    description = Column(Text)
    undo_skill = Column(String, default="")      # skill name to call to reverse
    undo_args_json = Column(Text, default="{}")
    reversible = Column(Boolean, default=True)
    used = Column(Boolean, default=False)
    ts = Column(Float, default=time.time, index=True)


Base.metadata.create_all(_engine)


def push(user_id: str, skill_name: str, description: str,
         undo_skill: str = "", undo_args: dict | None = None,
         reversible: bool = True) -> int:
    with db() as s:
        e = UndoEntry(
            user_id=user_id, skill_name=skill_name,
            description=description, undo_skill=undo_skill,
            undo_args_json=json.dumps(undo_args or {}),
            reversible=reversible,
        )
        s.add(e)
        s.flush()
        eid = e.id
    _trim(user_id)
    return eid


def _trim(user_id: str) -> None:
    with db() as s:
        rows = (s.query(UndoEntry).filter(UndoEntry.user_id == user_id)
                .order_by(UndoEntry.ts.desc()).all())
        if len(rows) > MAX_UNDO_STACK:
            for old in rows[MAX_UNDO_STACK:]:
                s.delete(old)


def pop(user_id: str) -> UndoEntry | None:
    """Return and mark-used the most recent undoable action within TTL."""
    cutoff = time.time() - UNDO_TTL
    with db() as s:
        e = (s.query(UndoEntry)
             .filter(UndoEntry.user_id == user_id,
                     UndoEntry.used.is_(False),
                     UndoEntry.reversible.is_(True),
                     UndoEntry.ts >= cutoff)
             .order_by(UndoEntry.ts.desc()).first())
        if e:
            e.used = True
            s.expunge(e)
        return e


def last_action_text(user_id: str) -> str:
    with db() as s:
        e = (s.query(UndoEntry).filter(UndoEntry.user_id == user_id)
             .order_by(UndoEntry.ts.desc()).first())
    if not e:
        return "no recent actions"
    ago = int(time.time() - e.ts)
    status = "✓ undone" if e.used else ("reversible" if e.reversible else "irreversible")
    return f"{e.description} ({ago}s ago, {status})"
