"""Life contexts — family, personal, professional.

Every Ollie data item (note, task, contact, finance entry, project) belongs to
exactly one Context. This is how a single assistant can serve your home life,
your inner life, and your job without bleeding them together.

Default contexts seeded on first run: family, personal, work.
"""
from __future__ import annotations

import time
from typing import Iterator

from sqlalchemy import Column, Integer, String, Text, Float, Boolean, ForeignKey, Index
from sqlalchemy.orm import relationship

from myassistant.core.memory import Base, db, _engine


# ---- core context ----

class Context(Base):
    __tablename__ = "contexts"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, index=True)    # family | personal | work | <custom>
    label = Column(String, default="")
    description = Column(Text, default="")
    color = Column(String, default="")                 # for UI hints
    timezone = Column(String, default="")
    work_hours = Column(String, default="")            # "09:00-18:00" for work
    created_ts = Column(Float, default=time.time)


# ---- people in your life (broader than family Member) ----

class Contact(Base):
    """Anyone you interact with — friends, coworkers, doctors, lawyers, vendors."""
    __tablename__ = "contacts"
    id = Column(Integer, primary_key=True)
    context_id = Column(Integer, ForeignKey("contexts.id"), index=True)
    name = Column(String, index=True)
    relationship = Column(String, default="")          # friend | coworker | manager | doctor | parent_of_kid_friend ...
    company = Column(String, default="")
    title = Column(String, default="")
    phone = Column(String, default="")
    email = Column(String, default="")
    birthday = Column(String, default="")              # MM-DD or YYYY-MM-DD
    last_contact_ts = Column(Float, default=0.0)
    follow_up_ts = Column(Float, default=0.0, index=True)
    notes = Column(Text, default="")
    tags = Column(String, default="")                  # comma-separated
    created_ts = Column(Float, default=time.time)


# ---- projects & work tasks ----

class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True)
    context_id = Column(Integer, ForeignKey("contexts.id"), index=True)
    name = Column(String, index=True)
    status = Column(String, default="active")          # active | on_hold | done | dropped
    goal = Column(Text, default="")
    due = Column(String, default="")                   # YYYY-MM-DD
    stakeholders = Column(String, default="")          # comma list of contact names
    created_ts = Column(Float, default=time.time)


class Task(Base):
    """Granular work task. Lighter than a list item — has status, priority, due."""
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True)
    context_id = Column(Integer, ForeignKey("contexts.id"), index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), default=None, index=True)
    title = Column(String)
    status = Column(String, default="todo")            # todo | doing | blocked | done
    priority = Column(String, default="med")           # low | med | high | urgent
    due = Column(String, default="")                   # YYYY-MM-DD or YYYY-MM-DDTHH:MM
    assignee = Column(String, default="")              # contact or member name
    notes = Column(Text, default="")
    created_ts = Column(Float, default=time.time)
    done_ts = Column(Float, default=0.0)


# ---- notes & journal ----

class Note(Base):
    __tablename__ = "notes"
    id = Column(Integer, primary_key=True)
    context_id = Column(Integer, ForeignKey("contexts.id"), index=True)
    title = Column(String, default="")
    body = Column(Text)
    tags = Column(String, default="")                  # comma list
    related_contact = Column(String, default="")
    related_project = Column(String, default="")
    pinned = Column(Boolean, default=False)
    created_ts = Column(Float, default=time.time, index=True)


class JournalEntry(Base):
    """Daily journal — personal context, optionally with mood + highlights."""
    __tablename__ = "journal"
    id = Column(Integer, primary_key=True)
    date = Column(String, unique=True, index=True)     # YYYY-MM-DD
    mood = Column(String, default="")                  # 1..5 or word
    energy = Column(Integer, default=0)                # 1..5
    body = Column(Text)
    gratitude = Column(Text, default="")
    created_ts = Column(Float, default=time.time)


# ---- finance ----

class FinanceEntry(Base):
    """Income or expense. Optional account / category for budgeting."""
    __tablename__ = "finance"
    id = Column(Integer, primary_key=True)
    context_id = Column(Integer, ForeignKey("contexts.id"), index=True)
    date = Column(String, index=True)                  # YYYY-MM-DD
    kind = Column(String, default="expense")           # expense | income | transfer
    amount = Column(Float, default=0.0)                # always positive; kind disambiguates
    currency = Column(String, default="USD")
    category = Column(String, default="misc")          # groceries, dining, salary, mortgage...
    merchant = Column(String, default="")
    note = Column(Text, default="")
    is_reimbursable = Column(Boolean, default=False)
    reimbursed = Column(Boolean, default=False)
    created_ts = Column(Float, default=time.time)


class Budget(Base):
    __tablename__ = "budgets"
    id = Column(Integer, primary_key=True)
    context_id = Column(Integer, ForeignKey("contexts.id"), index=True)
    category = Column(String, index=True)
    monthly_limit = Column(Float, default=0.0)
    currency = Column(String, default="USD")


# ---- health & habits ----

class HealthLog(Base):
    __tablename__ = "health_log"
    id = Column(Integer, primary_key=True)
    date = Column(String, index=True)                  # YYYY-MM-DD
    metric = Column(String, index=True)                # weight | sleep_hours | steps | workout | meds | mood | water_oz
    value = Column(String)
    unit = Column(String, default="")
    note = Column(Text, default="")
    created_ts = Column(Float, default=time.time)


class Habit(Base):
    __tablename__ = "habits"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    schedule = Column(String, default="daily")         # daily | weekdays | weekly | custom-cron
    target = Column(String, default="")                # e.g. "30 min" or "8 cups"
    active = Column(Boolean, default=True)
    created_ts = Column(Float, default=time.time)


class HabitCheck(Base):
    __tablename__ = "habit_checks"
    id = Column(Integer, primary_key=True)
    habit_id = Column(Integer, ForeignKey("habits.id"), index=True)
    date = Column(String, index=True)                  # YYYY-MM-DD
    done = Column(Boolean, default=True)
    note = Column(String, default="")


# ---- travel & wishlist ----

class Trip(Base):
    __tablename__ = "trips"
    id = Column(Integer, primary_key=True)
    context_id = Column(Integer, ForeignKey("contexts.id"), index=True)
    name = Column(String)
    destination = Column(String, default="")
    start_date = Column(String, default="")            # YYYY-MM-DD
    end_date = Column(String, default="")
    confirmation_numbers = Column(Text, default="")    # free text
    itinerary = Column(Text, default="")
    notes = Column(Text, default="")


class WishlistItem(Base):
    __tablename__ = "wishlist"
    id = Column(Integer, primary_key=True)
    context_id = Column(Integer, ForeignKey("contexts.id"), index=True)
    name = Column(String)
    url = Column(String, default="")
    price = Column(Float, default=0.0)
    priority = Column(String, default="med")
    occasion = Column(String, default="")              # birthday, anniversary, "just because"
    for_person = Column(String, default="")
    bought = Column(Boolean, default=False)
    created_ts = Column(Float, default=time.time)


# ---- create tables + indexes ----
Base.metadata.create_all(_engine)
Index("idx_task_status_due", Task.context_id, Task.status, Task.due)
Index("idx_finance_ctx_date", FinanceEntry.context_id, FinanceEntry.date)
Index("idx_note_ctx_ts", Note.context_id, Note.created_ts)


# ---- helpers ----

_DEFAULT_CONTEXTS = [
    ("family",   "Family",      "Home & kids"),
    ("personal", "Personal",    "Health, finances, friends, hobbies"),
    ("work",     "Work",        "Job, projects, colleagues"),
]


def ensure_default_contexts() -> None:
    with db() as s:
        existing = {c.name for c in s.query(Context).all()}
        for name, label, desc in _DEFAULT_CONTEXTS:
            if name not in existing:
                s.add(Context(name=name, label=label, description=desc))


def get_context(name: str) -> Context | None:
    with db() as s:
        c = s.query(Context).filter(Context.name == name.lower().strip()).one_or_none()
        if c:
            s.expunge(c)
        return c


def resolve_context_id(name: str | None) -> int:
    """Default to 'personal' if no name given. Auto-creates unknown contexts."""
    nm = (name or "personal").lower().strip()
    ensure_default_contexts()
    with db() as s:
        c = s.query(Context).filter(Context.name == nm).one_or_none()
        if not c:
            c = Context(name=nm, label=nm.capitalize())
            s.add(c)
            s.flush()
        return c.id


# Seed on import so skills can rely on contexts existing.
ensure_default_contexts()
