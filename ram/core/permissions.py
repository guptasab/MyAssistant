"""Per-member permissions — who can do what.

A simple role + per-skill allow/deny system. Family member's role determines
default permissions; explicit overrides go in the Permission table.
"""
from __future__ import annotations

import time

from sqlalchemy import Column, Integer, String, Boolean, Float

from ram.core.memory import Base, db, _engine


class Permission(Base):
    __tablename__ = "permissions"
    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, index=True)        # 0 = anyone
    skill_pattern = Column(String, index=True)      # exact skill name or 'finance.*'
    allow = Column(Boolean, default=True)
    created_ts = Column(Float, default=time.time)


Base.metadata.create_all(_engine)


# Default rules: kids cannot use finance/email_send/voice_calls/vault/deadman.
KID_DENIED_PREFIXES = (
    "finance", "plaid", "email_send", "voice_call", "vault", "deadman",
    "delete_", "send_email", "place_order", "instacart", "doordash",
)


def can(member_role: str, skill_name: str, member_id: int | None = None) -> bool:
    if member_id:
        with db() as s:
            rows = s.query(Permission).filter(
                (Permission.member_id == member_id) | (Permission.member_id == 0)
            ).all()
        for r in rows:
            if r.skill_pattern == skill_name or (
                r.skill_pattern.endswith("*") and skill_name.startswith(r.skill_pattern[:-1])
            ):
                return r.allow
    if member_role == "kid":
        for p in KID_DENIED_PREFIXES:
            if skill_name.startswith(p):
                return False
    return True


def grant(member_id: int, skill_pattern: str, allow: bool = True) -> int:
    with db() as s:
        p = Permission(member_id=member_id, skill_pattern=skill_pattern, allow=allow)
        s.add(p)
        s.flush()
        return p.id
