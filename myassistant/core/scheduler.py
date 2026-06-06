"""Background scheduler for reminders and proactive nudges."""
from __future__ import annotations

import time
from typing import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from myassistant.core import memory

_scheduler: AsyncIOScheduler | None = None
_notify_cb: Callable[[str, str], None] | None = None


def start(notify: Callable[[str, str], None]) -> None:
    """`notify(user_id, text)` is called when a reminder fires."""
    global _scheduler, _notify_cb
    if _scheduler:
        return
    _notify_cb = notify
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(_check_due_reminders, CronTrigger(second=0), id="reminder_tick")
    _scheduler.start()
    logger.info("Scheduler started")

    # Wire Ollie's proactive jobs on the same scheduler
    try:
        from myassistant.core.proactive import start_proactive
        start_proactive(_scheduler, notify)
    except Exception as e:
        logger.warning(f"proactive jobs not started: {e}")


def get_scheduler():
    return _scheduler


def schedule_reminder(user_id: str, text: str, due_ts: float) -> int:
    with memory.db() as s:
        r = memory.Reminder(user_id=user_id, text=text, due_ts=due_ts)
        s.add(r)
        s.flush()
        return r.id


async def _check_due_reminders() -> None:
    now = time.time()
    with memory.db() as s:
        due = s.query(memory.Reminder).filter(
            memory.Reminder.fired == 0, memory.Reminder.due_ts <= now
        ).all()
        for r in due:
            try:
                if _notify_cb:
                    _notify_cb(r.user_id, f"⏰ Reminder: {r.text}")
                r.fired = 1
            except Exception as e:
                logger.exception(f"reminder fire failed: {e}")
