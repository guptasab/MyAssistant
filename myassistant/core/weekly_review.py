"""Weekly review composer — Sunday evening retrospective.

Pulls from contexts (tasks done this week, finance summary, habits hit,
notes captured, top emails, calendar density) and asks LLM to summarize
+ suggest 3 priorities for next week.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from myassistant.core import contexts as ctx
from myassistant.core.memory import db


def gather_week() -> dict:
    cutoff = time.time() - 7 * 86400
    out: dict = {"window_days": 7, "now": datetime.now().isoformat()}

    with db() as s:
        out["tasks_done"] = s.query(ctx.Task).filter(
            ctx.Task.status == "done", ctx.Task.done_ts >= cutoff
        ).count()
        out["tasks_open"] = s.query(ctx.Task).filter(ctx.Task.status != "done").count()
        out["notes_added"] = s.query(ctx.Note).filter(ctx.Note.created_ts >= cutoff).count()
        try:
            spend = s.query(ctx.FinanceEntry).filter(ctx.FinanceEntry.created_ts >= cutoff).all()
            out["spend_total"] = round(sum(float(e.amount) for e in spend if e.kind == "expense"), 2)
            out["income_total"] = round(sum(float(e.amount) for e in spend if e.kind == "income"), 2)
        except Exception:
            out["spend_total"] = out["income_total"] = 0
        try:
            cutoff_date = datetime.fromtimestamp(cutoff).strftime("%Y-%m-%d")
            checks = s.query(ctx.HabitCheck).filter(ctx.HabitCheck.date >= cutoff_date,
                                                    ctx.HabitCheck.done.is_(True)).count()
            out["habit_checks"] = checks
        except Exception:
            out["habit_checks"] = 0
    return out


def compose() -> str:
    data = gather_week()
    try:
        from myassistant.core.llm import llm_chat
        prompt = (
            "You are Ollie. Compose a warm, concise weekly review (Sunday evening) "
            "from this data. 5–8 short lines. End with 3 suggested priorities for the upcoming week.\n\n"
            f"Data: {data}"
        )
        return llm_chat([{"role": "user", "content": prompt}], task="reasoning", max_tokens=500)
    except Exception:
        return f"Week recap: {data['tasks_done']} tasks done, {data['tasks_open']} open, ${data['spend_total']:.0f} spent."
