"""Birthday autopilot — Ollie reminds you, drafts a card, and (with confirmation) sends it."""
from __future__ import annotations

from datetime import datetime

from ram.core import contexts as ctx
from ram.core.memory import db
from ram.core.registry import skill


@skill(
    name="upcoming_birthdays",
    description="List birthdays in the next N days (across contexts).",
)
def upcoming_birthdays(days: int = 14) -> str:
    today = datetime.now()
    out = []
    with db() as s:
        for c in s.query(ctx.Contact).filter(ctx.Contact.birthday != "").all():
            bd = c.birthday
            try:
                if len(bd) == 5:  # MM-DD
                    m, d = bd.split("-")
                    bdt = datetime(today.year, int(m), int(d))
                else:
                    bdt = datetime.fromisoformat(bd[:10]).replace(year=today.year)
                if bdt < today:
                    bdt = bdt.replace(year=today.year + 1)
                delta = (bdt - today).days
                if delta <= days:
                    out.append((delta, c.name, c.relationship or ""))
            except Exception:
                continue
    out.sort()
    if not out:
        return f"no birthdays in next {days}d"
    return "\n".join(f"in {d}d  {n}  ({r})" for d, n, r in out)


@skill(
    name="draft_birthday_message",
    description=("Draft a warm, personal birthday message for a contact. Returns the "
                 "draft for the user to approve before sending."),
)
def draft_birthday_message(contact_name: str, tone: str = "warm") -> str:
    with db() as s:
        c = s.query(ctx.Contact).filter(ctx.Contact.name.ilike(f"%{contact_name}%")).first()
        if not c:
            return f"contact '{contact_name}' not found"
        notes = (c.notes or "")[:400]
        rel = c.relationship or "friend"
    try:
        from ram.core.llm import llm_chat
        return llm_chat([{"role": "user", "content": (
            f"Draft a {tone} birthday message to {c.name} ({rel}). "
            f"Personal context: {notes}. 2-3 sentences, no emoji overload."
        )}], task="draft", max_tokens=200)
    except Exception:
        return f"Happy birthday {c.name}! Hope you have a wonderful day."
