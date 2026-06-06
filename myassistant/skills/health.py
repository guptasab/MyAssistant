"""Health metrics + habits — track weight, sleep, workouts, meds; build streaks."""
from __future__ import annotations

from datetime import date, timedelta

from myassistant.core import contexts as ctx
from myassistant.core.memory import db
from myassistant.core.registry import skill


@skill(
    name="log_health",
    description=("Log a health metric. metric examples: weight, sleep_hours, "
                 "steps, workout, meds, mood, water_oz, blood_pressure."),
)
def log_health(metric: str, value: str, unit: str = "", note: str = "",
               entry_date: str = "") -> str:
    d = entry_date or date.today().isoformat()
    with db() as s:
        s.add(ctx.HealthLog(date=d, metric=metric, value=str(value), unit=unit, note=note))
    return f"📈 logged {metric}={value}{(' ' + unit) if unit else ''} on {d}"


@skill(
    name="health_trend",
    description="Show last N entries for a metric (default 14).",
)
def health_trend(metric: str, days: int = 14) -> str:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with db() as s:
        rows = (
            s.query(ctx.HealthLog)
            .filter(ctx.HealthLog.metric == metric, ctx.HealthLog.date >= cutoff)
            .order_by(ctx.HealthLog.date.desc())
            .all()
        )
    if not rows:
        return f"no {metric} entries in last {days}d"
    return "\n".join(f"{r.date}: {r.value}{(' ' + r.unit) if r.unit else ''}" for r in rows)


@skill(
    name="add_habit",
    description=("Define a daily/weekly habit. schedule = daily|weekdays|weekly. "
                 "target is free-text like '30 min' or '8 cups'."),
)
def add_habit(name: str, schedule: str = "daily", target: str = "") -> str:
    with db() as s:
        existing = s.query(ctx.Habit).filter(ctx.Habit.name == name).one_or_none()
        if existing:
            existing.schedule = schedule or existing.schedule
            existing.target = target or existing.target
            existing.active = True
            return f"updated habit '{name}'"
        s.add(ctx.Habit(name=name, schedule=schedule, target=target))
    return f"habit '{name}' added ({schedule}, target={target or '—'})"


@skill(
    name="check_habit",
    description="Mark a habit done today (or on a given date).",
)
def check_habit(name: str, entry_date: str = "", note: str = "") -> str:
    d = entry_date or date.today().isoformat()
    with db() as s:
        h = s.query(ctx.Habit).filter(ctx.Habit.name == name).one_or_none()
        if not h:
            return f"no habit '{name}' — add it first"
        existing = (
            s.query(ctx.HabitCheck)
            .filter(ctx.HabitCheck.habit_id == h.id, ctx.HabitCheck.date == d)
            .one_or_none()
        )
        if existing:
            existing.done = True
            if note:
                existing.note = note
        else:
            s.add(ctx.HabitCheck(habit_id=h.id, date=d, done=True, note=note))
    return f"✓ {name} on {d}"


@skill(
    name="habit_streaks",
    description="Show current streak for each active habit.",
)
def habit_streaks() -> str:
    today = date.today()
    with db() as s:
        habits = s.query(ctx.Habit).filter(ctx.Habit.active == True).all()
        if not habits:
            return "no active habits"
        out = []
        for h in habits:
            checks = {
                c.date for c in s.query(ctx.HabitCheck)
                .filter(ctx.HabitCheck.habit_id == h.id, ctx.HabitCheck.done == True)
                .all()
            }
            streak = 0
            d = today
            while d.isoformat() in checks:
                streak += 1
                d = d - timedelta(days=1)
            mark = "🔥" if streak >= 3 else "·"
            out.append(f"  {mark} {h.name}: {streak}d streak")
    return "\n".join(out)
