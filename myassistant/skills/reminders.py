"""Reminders & quick scheduling. Backed by APScheduler + SQLite."""
from __future__ import annotations

import time
from datetime import datetime, timedelta
import re

from myassistant.core import scheduler, memory
from myassistant.core.registry import skill


def _parse_when(when: str) -> float:
    """Parse 'in 10 minutes', 'tomorrow 9am', '2026-06-15 14:30', or ISO timestamp."""
    s = when.strip().lower()
    now = datetime.now()

    m = re.match(r"in\s+(\d+)\s*(second|seconds|sec|s|minute|minutes|min|m|hour|hours|hr|h|day|days|d)", s)
    if m:
        n = int(m.group(1)); unit = m.group(2)
        mult = {"s": 1, "sec": 1, "second": 1, "seconds": 1,
                "m": 60, "min": 60, "minute": 60, "minutes": 60,
                "h": 3600, "hr": 3600, "hour": 3600, "hours": 3600,
                "d": 86400, "day": 86400, "days": 86400}[unit]
        return time.time() + n * mult

    try:
        return datetime.fromisoformat(when).timestamp()
    except ValueError:
        pass

    if s.startswith("tomorrow"):
        rest = s.replace("tomorrow", "").strip()
        t = _parse_time_of_day(rest) or (9, 0)
        target = (now + timedelta(days=1)).replace(hour=t[0], minute=t[1], second=0, microsecond=0)
        return target.timestamp()

    t = _parse_time_of_day(s)
    if t:
        target = now.replace(hour=t[0], minute=t[1], second=0, microsecond=0)
        if target < now:
            target += timedelta(days=1)
        return target.timestamp()

    raise ValueError(f"could not parse time '{when}'")


def _parse_time_of_day(s: str) -> tuple[int, int] | None:
    m = re.match(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", s.strip())
    if not m:
        return None
    h = int(m.group(1)); mi = int(m.group(2) or 0); ap = m.group(3)
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return h, mi


@skill(
    name="set_reminder",
    description=("Schedule a reminder. `when` accepts natural phrases like 'in 10 minutes', "
                 "'tomorrow 9am', '6:30pm', or an ISO timestamp."),
)
def set_reminder(text: str, when: str, user_id: str = "owner") -> str:
    try:
        ts = _parse_when(when)
    except ValueError as e:
        return f"ERROR: {e}"
    rid = scheduler.schedule_reminder(user_id, text, ts)
    return f"Reminder #{rid} set for {datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')}: {text}"


@skill(
    name="list_reminders",
    description="List upcoming (not-yet-fired) reminders.",
)
def list_reminders(user_id: str = "owner") -> str:
    with memory.db() as s:
        rows = s.query(memory.Reminder).filter(
            memory.Reminder.user_id == user_id, memory.Reminder.fired == 0,
        ).order_by(memory.Reminder.due_ts).all()
    if not rows:
        return "no upcoming reminders"
    return "\n".join(
        f"#{r.id} {datetime.fromtimestamp(r.due_ts).strftime('%a %b %d %H:%M')} — {r.text}"
        for r in rows
    )


@skill(
    name="cancel_reminder",
    description="Cancel a reminder by its id.",
)
def cancel_reminder(reminder_id: int) -> str:
    with memory.db() as s:
        r = s.query(memory.Reminder).filter(memory.Reminder.id == reminder_id).one_or_none()
        if not r:
            return f"reminder #{reminder_id} not found"
        s.delete(r)
    return f"cancelled #{reminder_id}"
