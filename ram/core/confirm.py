"""Confirmation gate — every sensitive action pauses for owner approval.

Flow:
1. Agent wants to call a sensitive skill.
2. agent.py intercepts, creates a PendingAction in SQLite, returns a
   human-readable "I'm about to do X — reply YES to confirm or NO to cancel."
3. Next message from the user routes through `resolve()`.
4. If YES → the action executes, result returned to the conversation.
5. If NO  → action cancelled, stored in audit log.
6. Pending actions expire after CONFIRM_TTL_SECONDS (default 5 min).
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from sqlalchemy import Column, String, Text, Float, Boolean

from ram.core.memory import Base, db, _engine

CONFIRM_TTL = 300  # 5 minutes


class PendingAction(Base):
    __tablename__ = "pending_actions"
    id = Column(String, primary_key=True)        # UUID
    user_id = Column(String, index=True)
    skill_name = Column(String)
    args_json = Column(Text)
    description = Column(Text)                   # human-readable "I'm about to…"
    dry_run_result = Column(Text, default="")    # preview of what would happen
    created_ts = Column(Float, default=time.time)
    resolved = Column(Boolean, default=False)
    approved = Column(Boolean, default=False)


Base.metadata.create_all(_engine)


def create(user_id: str, skill_name: str, args: dict,
           description: str, dry_run_result: str = "") -> PendingAction:
    with db() as s:
        p = PendingAction(
            id=str(uuid.uuid4())[:8],
            user_id=user_id,
            skill_name=skill_name,
            args_json=json.dumps(args),
            description=description,
            dry_run_result=dry_run_result,
        )
        s.add(p)
        s.flush()
        s.expunge(p)
        return p


def get_pending(user_id: str) -> PendingAction | None:
    """Return the most recent unresolved, non-expired action for this user."""
    cutoff = time.time() - CONFIRM_TTL
    with db() as s:
        p = (
            s.query(PendingAction)
            .filter(
                PendingAction.user_id == user_id,
                PendingAction.resolved.is_(False),
                PendingAction.created_ts >= cutoff,
            )
            .order_by(PendingAction.created_ts.desc())
            .first()
        )
        if p:
            s.expunge(p)
        return p


def resolve(action_id: str, approved: bool) -> dict:
    with db() as s:
        p = s.query(PendingAction).filter(PendingAction.id == action_id).first()
        if not p:
            return {"error": "not found"}
        p.resolved = True
        p.approved = approved
        result = {"skill": p.skill_name, "args": json.loads(p.args_json), "approved": approved}
        s.expunge(p)
        return result


def prompt_text(p: PendingAction) -> str:
    """Format the confirmation ask for the user."""
    lines = [f"⚠️  I'm about to: **{p.description}**"]
    if p.dry_run_result:
        lines.append(f"\nPreview:\n{p.dry_run_result[:600]}")
    lines.append(f"\nReply **YES** to proceed or **NO** to cancel. (expires in 5 min, ID: {p.id})")
    return "\n".join(lines)


# ---- YES/NO parser ----
_YES = {"yes", "y", "yep", "yup", "sure", "ok", "okay", "go", "do it", "proceed", "confirm"}
_NO  = {"no", "n", "nope", "cancel", "stop", "abort", "never mind", "nevermind", "skip"}


def parse_user_response(text: str) -> bool | None:
    """Returns True=approve, False=reject, None=not a confirmation response."""
    t = text.strip().lower().rstrip("!.")
    if t in _YES:
        return True
    if t in _NO:
        return False
    return None
