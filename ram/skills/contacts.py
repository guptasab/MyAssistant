"""Contacts — friends, coworkers, doctors, vendors. Cross-context CRM-lite.

The agent uses these for follow-ups, birthday nudges, meeting prep
("you're meeting Sarah at 3 — last note: she just had her second kid").
"""
from __future__ import annotations

import time
from datetime import datetime

from ram.core import contexts as ctx
from ram.core.memory import db
from ram.core.registry import skill


def _parse_when(when: str) -> float:
    """Reuse the reminders parser for natural language times."""
    from ram.skills.reminders import _parse_when as p
    return p(when)


@skill(
    name="add_contact",
    description=("Add or update a contact. context is family|personal|work. "
                 "relationship is free-text (friend, manager, pediatrician, etc)."),
)
def add_contact(name: str, context: str = "personal", relationship: str = "",
                company: str = "", title: str = "", phone: str = "",
                email: str = "", birthday: str = "", notes: str = "",
                tags: str = "") -> str:
    cid = ctx.resolve_context_id(context)
    with db() as s:
        existing = (
            s.query(ctx.Contact)
            .filter(ctx.Contact.context_id == cid, ctx.Contact.name == name)
            .one_or_none()
        )
        if existing:
            for f, v in [("relationship", relationship), ("company", company),
                         ("title", title), ("phone", phone), ("email", email),
                         ("birthday", birthday), ("notes", notes), ("tags", tags)]:
                if v:
                    setattr(existing, f, v)
            return f"updated contact {name} [{context}]"
        c = ctx.Contact(context_id=cid, name=name, relationship=relationship,
                        company=company, title=title, phone=phone, email=email,
                        birthday=birthday, notes=notes, tags=tags)
        s.add(c)
    return f"added contact {name} [{context}]"


@skill(
    name="find_contact",
    description=("Find contacts by name or tag substring (case-insensitive). "
                 "Returns up to 10 matches with key fields."),
)
def find_contact(query: str) -> str:
    q = query.lower().strip()
    with db() as s:
        rows = s.query(ctx.Contact).all()
        hits = [r for r in rows
                if q in r.name.lower() or q in r.tags.lower()
                or q in r.company.lower() or q in r.relationship.lower()]
        if not hits:
            return f"no contacts matched '{query}'"
        out = []
        for r in hits[:10]:
            extras = " · ".join(x for x in [r.relationship, r.company, r.phone, r.email] if x)
            out.append(f"{r.name}" + (f" — {extras}" if extras else ""))
        return "\n".join(out)


@skill(
    name="log_contact_touch",
    description=("Log that you interacted with a contact today (call, meeting, text). "
                 "Optionally append a note."),
)
def log_contact_touch(name: str, note: str = "") -> str:
    with db() as s:
        c = s.query(ctx.Contact).filter(ctx.Contact.name == name).one_or_none()
        if not c:
            return f"no contact named {name}"
        c.last_contact_ts = time.time()
        if note:
            stamp = datetime.now().strftime("%Y-%m-%d")
            c.notes = (c.notes or "") + f"\n[{stamp}] {note}"
    return f"logged touch with {name}"


@skill(
    name="set_followup",
    description=("Schedule a follow-up reminder for a contact. when accepts "
                 "natural phrases like 'in 2 weeks', 'next monday 9am'."),
)
def set_followup(name: str, when: str, reason: str = "follow up") -> str:
    try:
        ts = _parse_when(when)
    except ValueError as e:
        return f"ERROR: {e}"
    with db() as s:
        c = s.query(ctx.Contact).filter(ctx.Contact.name == name).one_or_none()
        if not c:
            return f"no contact named {name}"
        c.follow_up_ts = ts
    # also drop a reminder on the regular reminders system
    from ram.core import scheduler
    scheduler.schedule_reminder("owner", f"Follow up with {name}: {reason}", ts)
    return f"follow-up with {name} scheduled for {datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')}"


@skill(
    name="overdue_followups",
    description="List contacts whose follow-up date has passed and aren't touched since.",
)
def overdue_followups() -> str:
    now = time.time()
    with db() as s:
        rows = (
            s.query(ctx.Contact)
            .filter(ctx.Contact.follow_up_ts > 0,
                    ctx.Contact.follow_up_ts <= now,
                    ctx.Contact.last_contact_ts < ctx.Contact.follow_up_ts)
            .all()
        )
    if not rows:
        return "no overdue follow-ups ✓"
    out = ["📞 Overdue follow-ups:"]
    for r in rows:
        due = datetime.fromtimestamp(r.follow_up_ts).strftime("%b %d")
        out.append(f"  • {r.name} — was due {due}")
    return "\n".join(out)


@skill(
    name="upcoming_birthdays",
    description="List contact birthdays in the next N days (default 30).",
)
def upcoming_birthdays(days: int = 30) -> str:
    from datetime import date, timedelta
    today = date.today()
    horizon = today + timedelta(days=days)
    hits = []
    with db() as s:
        for c in s.query(ctx.Contact).filter(ctx.Contact.birthday != "").all():
            b = c.birthday
            try:
                if len(b) == 5:                       # MM-DD
                    mm, dd = [int(x) for x in b.split("-")]
                else:                                  # YYYY-MM-DD
                    _, mm, dd = [int(x) for x in b.split("-")]
            except Exception:
                continue
            this_year = date(today.year, mm, dd)
            next_occ = this_year if this_year >= today else date(today.year + 1, mm, dd)
            if next_occ <= horizon:
                hits.append((next_occ, c.name))
    if not hits:
        return f"no birthdays in next {days} days"
    hits.sort()
    return "\n".join(f"🎂 {d.strftime('%b %d')} — {n}" for d, n in hits)
