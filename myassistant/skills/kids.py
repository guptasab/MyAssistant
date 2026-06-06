"""Kid-focused skills: homework, allowance, screen time, reading log, milestones."""
from __future__ import annotations

import time

from sqlalchemy import Column, Integer, String, Text, Float, Boolean

from myassistant.core.memory import Base, db, _engine
from myassistant.core.registry import skill


class Homework(Base):
    __tablename__ = "homework"
    id = Column(Integer, primary_key=True)
    kid_id = Column(Integer, index=True)
    subject = Column(String)
    description = Column(Text)
    due = Column(String, default="")
    done = Column(Boolean, default=False)
    ts = Column(Float, default=time.time)


class AllowanceLedger(Base):
    __tablename__ = "allowance"
    id = Column(Integer, primary_key=True)
    kid_id = Column(Integer, index=True)
    delta = Column(Float)
    reason = Column(String, default="")
    ts = Column(Float, default=time.time)


class ScreenTime(Base):
    __tablename__ = "screen_time"
    id = Column(Integer, primary_key=True)
    kid_id = Column(Integer, index=True)
    minutes = Column(Integer)
    note = Column(String, default="")
    ts = Column(Float, default=time.time)


class ReadingLog(Base):
    __tablename__ = "reading_log"
    id = Column(Integer, primary_key=True)
    kid_id = Column(Integer, index=True)
    title = Column(String)
    minutes = Column(Integer, default=0)
    pages = Column(Integer, default=0)
    ts = Column(Float, default=time.time)


class Milestone(Base):
    __tablename__ = "milestones"
    id = Column(Integer, primary_key=True)
    kid_id = Column(Integer, index=True)
    description = Column(Text)
    ts = Column(Float, default=time.time)


Base.metadata.create_all(_engine)


# -- homework --
@skill(name="homework_add", description="Add a homework item for a kid (use kid's member_id).")
def homework_add(kid_id: int, subject: str, description: str, due: str = "") -> str:
    with db() as s:
        h = Homework(kid_id=kid_id, subject=subject, description=description, due=due)
        s.add(h); s.flush()
        return f"homework #{h.id}"


@skill(name="homework_list", description="List open homework for a kid (or all kids if 0).")
def homework_list(kid_id: int = 0) -> str:
    with db() as s:
        q = s.query(Homework).filter(Homework.done.is_(False))
        if kid_id:
            q = q.filter(Homework.kid_id == kid_id)
        rows = q.order_by(Homework.due).all()
    return "\n".join(f"#{h.id} [{h.subject}] {h.description} due {h.due}" for h in rows) or "(none open)"


@skill(name="homework_done", description="Mark homework done.")
def homework_done(homework_id: int) -> str:
    with db() as s:
        h = s.query(Homework).filter(Homework.id == homework_id).first()
        if not h:
            return "not found"
        h.done = True
    return "✓"


# -- allowance --
@skill(name="allowance_change",
       description="Add to or deduct from a kid's allowance (positive=earn, negative=spend).")
def allowance_change(kid_id: int, delta: float, reason: str = "") -> str:
    with db() as s:
        s.add(AllowanceLedger(kid_id=kid_id, delta=delta, reason=reason))
        bal = sum(r.delta for r in s.query(AllowanceLedger).filter(AllowanceLedger.kid_id == kid_id).all())
    return f"balance: ${bal:.2f}"


@skill(name="allowance_balance", description="Show kid's allowance balance.")
def allowance_balance(kid_id: int) -> str:
    with db() as s:
        bal = sum(r.delta for r in s.query(AllowanceLedger).filter(AllowanceLedger.kid_id == kid_id).all())
    return f"${bal:.2f}"


# -- screen time --
@skill(name="screen_time_log", description="Log minutes of screen time for a kid.")
def screen_time_log(kid_id: int, minutes: int, note: str = "") -> str:
    with db() as s:
        s.add(ScreenTime(kid_id=kid_id, minutes=minutes, note=note))
    return "logged"


@skill(name="screen_time_today", description="Total screen time today for a kid.")
def screen_time_today(kid_id: int) -> str:
    cutoff = time.time() - 86400
    with db() as s:
        total = sum(r.minutes for r in s.query(ScreenTime).filter(
            ScreenTime.kid_id == kid_id, ScreenTime.ts >= cutoff
        ).all())
    return f"{total} minutes today"


# -- reading log --
@skill(name="reading_log_add", description="Log reading: title + minutes/pages.")
def reading_log_add(kid_id: int, title: str, minutes: int = 0, pages: int = 0) -> str:
    with db() as s:
        s.add(ReadingLog(kid_id=kid_id, title=title, minutes=minutes, pages=pages))
    return "📖 logged"


@skill(name="reading_log_summary", description="Reading summary for past N days.")
def reading_log_summary(kid_id: int, days: int = 7) -> str:
    cutoff = time.time() - days * 86400
    with db() as s:
        rows = s.query(ReadingLog).filter(
            ReadingLog.kid_id == kid_id, ReadingLog.ts >= cutoff
        ).all()
    return f"{len(rows)} sessions, {sum(r.minutes for r in rows)} min, {sum(r.pages for r in rows)} pages"


# -- milestones --
@skill(name="milestone_add", description="Record a kid milestone (lost tooth, first goal, etc.).")
def milestone_add(kid_id: int, description: str) -> str:
    with db() as s:
        s.add(Milestone(kid_id=kid_id, description=description))
    return "🌟 saved"


@skill(name="milestones_list", description="List milestones for a kid.")
def milestones_list(kid_id: int) -> str:
    with db() as s:
        rows = s.query(Milestone).filter(Milestone.kid_id == kid_id).order_by(Milestone.ts).all()
    if not rows:
        return "(none)"
    import datetime as dt
    return "\n".join(f"{dt.datetime.fromtimestamp(r.ts):%Y-%m-%d}  {r.description}" for r in rows)
