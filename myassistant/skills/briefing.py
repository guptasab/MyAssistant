"""Daily briefing — Ollie's signature morning text.

Composes a short, scannable update: calendar, school to-dos, carpool, open
groceries/todos, tonight's dinner, and any new school-email actions.
Sent once a day per opted-in family member via SMS / WhatsApp / etc.
"""
from __future__ import annotations

import time
from datetime import date, datetime

from loguru import logger

from myassistant.core import family as fam, memory
from myassistant.core.memory import db
from myassistant.core.registry import skill

# We import lazily inside the function to avoid load-order surprises.


def _calendar_lines() -> list[str]:
    try:
        from myassistant.skills.calendar_skill import _list_range
        raw = _list_range(0)
        if raw.startswith("ERROR") or raw.startswith("no events"):
            return []
        return raw.splitlines()[1:5]   # drop header, cap at 4
    except Exception:
        return []


def _reminder_lines(user_id: str) -> list[str]:
    now = time.time()
    end_of_day = now + 24 * 3600
    with db() as s:
        rows = (
            s.query(memory.Reminder)
            .filter(memory.Reminder.user_id == user_id,
                    memory.Reminder.fired == 0,
                    memory.Reminder.due_ts <= end_of_day)
            .order_by(memory.Reminder.due_ts)
            .all()
        )
    return [f"  ⏰ {datetime.fromtimestamp(r.due_ts).strftime('%H:%M')} — {r.text}" for r in rows[:5]]


def _school_lines(family_id: int) -> list[str]:
    with db() as s:
        rows = (
            s.query(fam.SchoolEmail)
            .filter(fam.SchoolEmail.family_id == family_id,
                    fam.SchoolEmail.action_required == True,
                    fam.SchoolEmail.surfaced == False)
            .order_by(fam.SchoolEmail.received_ts.desc())
            .limit(4)
            .all()
        )
    out = []
    for r in rows:
        d = f" (by {r.deadline})" if r.deadline else ""
        who = f"[{r.child_name}] " if r.child_name else ""
        out.append(f"  📬 {who}{r.summary}{d}")
    return out


def _carpool_lines(family_id: int) -> list[str]:
    from myassistant.skills.carpool import carpools_for_today
    rows = carpools_for_today(family_id)
    return [f"  🚗 {r.pickup_time} — {r.driver} drives {r.child}" for r in rows]


def _open_lists_lines(family_id: int) -> list[str]:
    out = []
    with db() as s:
        lists = s.query(fam.FamilyList).filter(fam.FamilyList.family_id == family_id).all()
        for L in lists:
            n_open = (
                s.query(fam.ListItem)
                .filter(fam.ListItem.list_id == L.id, fam.ListItem.done == False)
                .count()
            )
            if n_open > 0:
                out.append(f"  📝 {L.name}: {n_open} open")
    return out[:4]


def _dinner_line(family_id: int) -> list[str]:
    today = date.today().isoformat()
    with db() as s:
        mp = (
            s.query(fam.MealPlan)
            .filter(fam.MealPlan.family_id == family_id,
                    fam.MealPlan.date == today,
                    fam.MealPlan.slot == "dinner")
            .one_or_none()
        )
        if mp:
            return [f"  🍽️ Dinner: {mp.title}"]
    return []


def _work_lines() -> list[str]:
    """Today's top work items: urgent/high tasks + projects due soon."""
    try:
        from myassistant.core import contexts as ctx
    except Exception:
        return []
    today_s = date.today().isoformat()
    out: list[str] = []
    with db() as s:
        work_ctx = s.query(ctx.Context).filter(ctx.Context.name == "work").one_or_none()
        if not work_ctx:
            return []
        tasks = (
            s.query(ctx.Task)
            .filter(ctx.Task.context_id == work_ctx.id,
                    ctx.Task.status != "done")
            .all()
        )
        pri = {"urgent": 0, "high": 1, "med": 2, "low": 3}
        tasks.sort(key=lambda t: (pri.get(t.priority, 4), t.due or "9999"))
        urgent = [t for t in tasks if t.priority in ("urgent", "high")
                  or (t.due and t.due[:10] <= today_s)]
        for t in urgent[:5]:
            mark = {"urgent": "🔴", "high": "🟠"}.get(t.priority, "🟡")
            due = f" ⏳ {t.due}" if t.due else ""
            out.append(f"  {mark} {t.title}{due}")
    return out


def _personal_lines() -> list[str]:
    """Today's personal context: tasks due, habits not yet checked."""
    try:
        from myassistant.core import contexts as ctx
    except Exception:
        return []
    today_s = date.today().isoformat()
    out: list[str] = []
    with db() as s:
        pctx = s.query(ctx.Context).filter(ctx.Context.name == "personal").one_or_none()
        if pctx:
            due = (
                s.query(ctx.Task)
                .filter(ctx.Task.context_id == pctx.id,
                        ctx.Task.status != "done",
                        ctx.Task.due != "",
                        ctx.Task.due <= today_s + "T23:59")
                .all()
            )
            for t in due[:4]:
                out.append(f"  ✅ {t.title}")
        # habits not yet checked today
        habits = s.query(ctx.Habit).filter(ctx.Habit.active == True).all()
        for h in habits:
            done = (
                s.query(ctx.HabitCheck)
                .filter(ctx.HabitCheck.habit_id == h.id,
                        ctx.HabitCheck.date == today_s,
                        ctx.HabitCheck.done == True)
                .first()
            )
            if not done:
                out.append(f"  🌱 habit: {h.name}")
    return out[:6]


def _followups_lines() -> list[str]:
    try:
        from myassistant.core import contexts as ctx
    except Exception:
        return []
    import time as _t
    now = _t.time()
    with db() as s:
        rows = (
            s.query(ctx.Contact)
            .filter(ctx.Contact.follow_up_ts > 0,
                    ctx.Contact.follow_up_ts <= now,
                    ctx.Contact.last_contact_ts < ctx.Contact.follow_up_ts)
            .all()
        )
    return [f"  📞 follow up: {r.name}" for r in rows[:3]]


@skill(
    name="compose_briefing",
    description=("Compose the morning briefing text for a given family member. "
                 "If member_name is empty, composes a generic family briefing. "
                 "Returns the text only — does not send."),
)
def compose_briefing(member_name: str = "") -> str:
    f = fam.get_or_create_default_family()
    today = date.today()
    greeting = f"☀️ Good morning{', ' + member_name if member_name else ''}!"
    header = today.strftime("%A, %B %d")
    parts: list[str] = [greeting, header, ""]

    cal = _calendar_lines()
    if cal:
        parts.append("📅 Today:")
        parts.extend(f"  {c}" for c in cal)

    cp = _carpool_lines(f.id)
    if cp:
        parts.append("")
        parts.extend(cp)

    user_id = f"sms:{member_name}" if member_name else "owner"
    rem = _reminder_lines(user_id) or _reminder_lines("owner")
    if rem:
        parts.append("")
        parts.append("Reminders:")
        parts.extend(rem)

    sc = _school_lines(f.id)
    if sc:
        parts.append("")
        parts.append("From school:")
        parts.extend(sc)

    work = _work_lines()
    if work:
        parts.append("")
        parts.append("Work — top of pile:")
        parts.extend(work)

    pers = _personal_lines()
    if pers:
        parts.append("")
        parts.append("Personal:")
        parts.extend(pers)

    fu = _followups_lines()
    if fu:
        parts.append("")
        parts.extend(fu)

    lst = _open_lists_lines(f.id)
    if lst:
        parts.append("")
        parts.extend(lst)

    dinner = _dinner_line(f.id)
    if dinner:
        parts.append("")
        parts.extend(dinner)

    if len(parts) <= 3:
        parts.append("Nothing on the radar today. Enjoy it. 💛")

    return "\n".join(parts)


@skill(
    name="send_briefing_now",
    description=("Send the morning briefing immediately to all opted-in family members "
                 "(or just one if member_name given). Returns delivery summary."),
)
def send_briefing_now(member_name: str = "") -> str:
    f = fam.get_or_create_default_family()
    targets: list[fam.Member] = []
    if member_name:
        for m in fam.list_members(f.id):
            if m.name.lower() == member_name.lower():
                targets = [m]
                break
        if not targets:
            return f"no member named {member_name}"
    else:
        targets = [m for m in fam.list_members(f.id) if m.receives_briefing]

    if not targets:
        return "no recipients (add members with phones, or enable receives_briefing)"

    from myassistant.skills.notify import _CHANNELS
    sent = 0
    for m in targets:
        text = compose_briefing(m.name)
        user_id = f"sms:{m.phone}" if m.phone else f"member:{m.name}"
        for ch in _CHANNELS:
            try:
                import asyncio
                coro = ch.send(user_id, text)
                if asyncio.iscoroutine(coro):
                    asyncio.create_task(coro)
            except Exception as e:
                logger.warning(f"briefing send {ch.name}: {e}")
        sent += 1
    return f"briefing sent to {sent} member(s)"
