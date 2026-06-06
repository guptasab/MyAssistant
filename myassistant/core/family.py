"""Family domain model — the heart of Ollie.

A Family groups Members (parents, kids, caregivers), shared Lists (grocery,
weekend, custom), Meals, and parsed SchoolEmails. Everything Ollie texts
about ultimately lives here.

Designed so a single Ollie instance can serve multiple families, but a
"home install" defaults to family_id=1 for the owner's household.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean, ForeignKey, Index,
)
from sqlalchemy.orm import relationship

from myassistant.core.memory import Base, db, SessionLocal, _engine  # reuse engine

# -------- models --------


class Family(Base):
    __tablename__ = "families"
    id = Column(Integer, primary_key=True)
    name = Column(String, default="Our Family")
    timezone = Column(String, default="America/Los_Angeles")
    briefing_time = Column(String, default="07:00")   # HH:MM local
    briefing_enabled = Column(Boolean, default=True)
    created_ts = Column(Float, default=time.time)


class Member(Base):
    __tablename__ = "members"
    id = Column(Integer, primary_key=True)
    family_id = Column(Integer, ForeignKey("families.id"), index=True)
    name = Column(String)
    role = Column(String, default="parent")  # parent | kid | caregiver
    phone = Column(String, default="", index=True)   # E.164, used for SMS
    email = Column(String, default="")
    age = Column(Integer, default=0)
    school = Column(String, default="")
    notes = Column(Text, default="")
    receives_briefing = Column(Boolean, default=True)
    created_ts = Column(Float, default=time.time)


class FamilyList(Base):
    """A shared list. Kind is grocery | todo | weekend | packing | custom."""
    __tablename__ = "family_lists"
    id = Column(Integer, primary_key=True)
    family_id = Column(Integer, ForeignKey("families.id"), index=True)
    name = Column(String)
    kind = Column(String, default="todo")
    created_ts = Column(Float, default=time.time)


class ListItem(Base):
    __tablename__ = "list_items"
    id = Column(Integer, primary_key=True)
    list_id = Column(Integer, ForeignKey("family_lists.id"), index=True)
    text = Column(String)
    qty = Column(String, default="")
    done = Column(Boolean, default=False)
    added_by = Column(String, default="")     # member name
    added_ts = Column(Float, default=time.time)
    done_ts = Column(Float, default=0.0)


class MealPlan(Base):
    """One row = one planned meal on a given date."""
    __tablename__ = "meal_plans"
    id = Column(Integer, primary_key=True)
    family_id = Column(Integer, ForeignKey("families.id"), index=True)
    date = Column(String, index=True)          # YYYY-MM-DD
    slot = Column(String, default="dinner")    # breakfast | lunch | dinner | snack
    title = Column(String)
    recipe = Column(Text, default="")          # full recipe text
    ingredients_json = Column(Text, default="[]")  # JSON list of {item, qty}
    notes = Column(Text, default="")
    created_ts = Column(Float, default=time.time)


class SchoolEmail(Base):
    """Parsed school email — every important field Ollie pulled from the inbox."""
    __tablename__ = "school_emails"
    id = Column(Integer, primary_key=True)
    family_id = Column(Integer, ForeignKey("families.id"), index=True)
    gmail_id = Column(String, unique=True, index=True)
    received_ts = Column(Float, default=time.time)
    sender = Column(String)
    subject = Column(String)
    snippet = Column(Text, default="")
    child_name = Column(String, default="")
    category = Column(String, default="general")
        # general | permission_slip | early_dismissal | event | volunteer
        # | absence | conference | supplies | newsletter | sick_alert
    action_required = Column(Boolean, default=False)
    deadline = Column(String, default="")      # YYYY-MM-DD or ""
    summary = Column(Text, default="")         # 1-2 sentences
    surfaced = Column(Boolean, default=False)  # has Ollie texted about this?


class CarpoolEntry(Base):
    __tablename__ = "carpool"
    id = Column(Integer, primary_key=True)
    family_id = Column(Integer, ForeignKey("families.id"), index=True)
    weekday = Column(Integer)                  # 0=Mon..6=Sun
    pickup_time = Column(String)               # HH:MM
    driver = Column(String)                    # member name
    child = Column(String)
    destination = Column(String, default="")
    notes = Column(Text, default="")


class InboxState(Base):
    """Tracks last-seen gmail history id so we don't re-parse every tick."""
    __tablename__ = "inbox_state"
    id = Column(Integer, primary_key=True)
    family_id = Column(Integer, ForeignKey("families.id"), index=True)
    last_history_id = Column(String, default="")
    last_check_ts = Column(Float, default=0.0)


# create the new tables on the existing engine
Base.metadata.create_all(_engine)

Index("idx_listitem_done", ListItem.list_id, ListItem.done)


# -------- helpers --------

def get_or_create_default_family() -> Family:
    """Single-household install: always return family #1, creating if needed."""
    with db() as s:
        fam = s.query(Family).filter(Family.id == 1).one_or_none()
        if not fam:
            from myassistant.core.config import settings
            fam = Family(
                id=1,
                name=f"{settings.myassistant_owner_name}'s Family",
                timezone=settings.myassistant_timezone,
                briefing_time=getattr(settings, "ollie_briefing_time", "07:00"),
            )
            s.add(fam)
            s.flush()
            s.refresh(fam)
        # detach
        s.expunge(fam)
        return fam


def find_member_by_phone(phone: str) -> Member | None:
    """Match an inbound SMS sender to a known member (E.164 phone)."""
    if not phone:
        return None
    norm = phone.strip().replace(" ", "")
    with db() as s:
        m = s.query(Member).filter(Member.phone == norm).one_or_none()
        if m:
            s.expunge(m)
        return m


def list_members(family_id: int = 1) -> list[Member]:
    with db() as s:
        rows = s.query(Member).filter(Member.family_id == family_id).all()
        for r in rows:
            s.expunge(r)
        return rows


def get_or_create_list(family_id: int, name: str, kind: str = "todo") -> FamilyList:
    with db() as s:
        lst = (
            s.query(FamilyList)
            .filter(FamilyList.family_id == family_id, FamilyList.name == name)
            .one_or_none()
        )
        if not lst:
            lst = FamilyList(family_id=family_id, name=name, kind=kind)
            s.add(lst)
            s.flush()
            s.refresh(lst)
        s.expunge(lst)
        return lst
