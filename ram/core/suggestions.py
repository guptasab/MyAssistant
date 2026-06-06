"""Proactive suggestions — Ollie's running 'what should I bring up?' brain.

Looks at upcoming calendar, weather, recent finance anomalies, idle reminders,
follow-up dates on contacts, and emits short messages worth proactively
texting. Used by the proactive scheduler.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from ram.core import contexts as ctx
from ram.core.memory import db


def collect() -> list[str]:
    out: list[str] = []
    now = time.time()

    with db() as s:
        # Contacts due for follow-up
        try:
            due = s.query(ctx.Contact).filter(
                ctx.Contact.follow_up_ts > 0, ctx.Contact.follow_up_ts <= now
            ).limit(3).all()
            for c in due:
                out.append(f"You said you'd follow up with {c.name} — want me to draft a note?")
        except Exception:
            pass

        # Tasks overdue >2 days (Task.due is YYYY-MM-DD string)
        try:
            from datetime import datetime as _dt, timedelta
            cutoff_date = (_dt.now() - timedelta(days=2)).strftime("%Y-%m-%d")
            stale = s.query(ctx.Task).filter(
                ctx.Task.status != "done",
                ctx.Task.due != "", ctx.Task.due < cutoff_date,
            ).limit(3).all()
            for t in stale:
                out.append(f"'{t.title}' is past due — bump it or drop it?")
        except Exception:
            pass

        # Birthdays in next 7 days
        try:
            today = datetime.now()
            for c in s.query(ctx.Contact).filter(ctx.Contact.birthday != "").all():
                bd = c.birthday
                try:
                    if len(bd) == 5:  # MM-DD
                        m, d = bd.split("-")
                        bdt = datetime(today.year, int(m), int(d))
                    else:
                        bdt = datetime.fromisoformat(bd[:10])
                        bdt = bdt.replace(year=today.year)
                    delta = (bdt - today).days
                    if 0 <= delta <= 7:
                        out.append(f"🎂 {c.name}'s birthday in {delta}d — want a card draft?")
                except Exception:
                    continue
        except Exception:
            pass

    return out[:5]
