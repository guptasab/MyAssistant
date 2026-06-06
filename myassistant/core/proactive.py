"""Proactive loop — Ollie's "watches when you can't" engine.

Every N minutes:
  1. Scans Gmail for new school emails → parses → stores.
  2. Surfaces any unsurfaced action items to opted-in members.
  3. Fires carpool nudges 30 minutes before pickup.

Lightweight — uses APScheduler intervals on top of the existing scheduler.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from myassistant.core import family as fam
from myassistant.core.config import settings

NotifyFn = Callable[[str, str], None]


def _send(notify: NotifyFn, phone: str, name: str, text: str) -> None:
    """Route a proactive message to a member via the best identifier."""
    uid = f"sms:{phone}" if phone else f"member:{name}"
    try:
        notify(uid, text)
    except Exception as e:
        logger.warning(f"proactive notify failed for {name}: {e}")


async def _poll_school_inbox(notify: NotifyFn) -> None:
    try:
        from myassistant.skills.school_inbox import scan_school_inbox, _unsurfaced_actions, _mark_surfaced
    except Exception as e:
        logger.debug(f"school_inbox unavailable: {e}")
        return
    try:
        msg = await asyncio.to_thread(scan_school_inbox)
        logger.info(f"school scan: {msg}")
    except Exception as e:
        logger.warning(f"school scan error: {e}")
        return

    f = fam.get_or_create_default_family()
    pending = _unsurfaced_actions(f.id)
    if not pending:
        return
    members = [m for m in fam.list_members(f.id) if m.role == "parent" and m.receives_briefing]
    if not members:
        return

    bundle = ["📬 Heads up — new from school:"]
    surfaced_ids: list[int] = []
    for p in pending[:5]:
        d = f" (by {p.deadline})" if p.deadline else ""
        who = f"[{p.child_name}] " if p.child_name else ""
        bundle.append(f"• {who}{p.summary}{d}")
        surfaced_ids.append(p.id)
    text = "\n".join(bundle)
    for m in members:
        _send(notify, m.phone, m.name, text)
    _mark_surfaced(surfaced_ids)


async def _carpool_nudges(notify: NotifyFn) -> None:
    """Fire a nudge 30 minutes before each pickup."""
    try:
        from myassistant.skills.carpool import carpools_for_today
    except Exception:
        return
    f = fam.get_or_create_default_family()
    rows = carpools_for_today(f.id)
    if not rows:
        return
    now = datetime.now()
    members = {m.name.lower(): m for m in fam.list_members(f.id)}
    for r in rows:
        try:
            h, mi = [int(x) for x in r.pickup_time.split(":")]
        except Exception:
            continue
        pickup = now.replace(hour=h, minute=mi, second=0, microsecond=0)
        delta_min = (pickup - now).total_seconds() / 60
        # Fire roughly within the 30-min window before pickup
        if 28 <= delta_min <= 32:
            who = members.get(r.driver.lower())
            phone = who.phone if who else ""
            text = (f"🚗 Carpool reminder: pickup at {r.pickup_time} — "
                    f"{r.driver} driving {r.child}"
                    + (f" → {r.destination}" if r.destination else ""))
            _send(notify, phone, r.driver, text)


async def _morning_briefing(notify: NotifyFn) -> None:
    try:
        from myassistant.skills.briefing import compose_briefing
    except Exception:
        return
    f = fam.get_or_create_default_family()
    for m in fam.list_members(f.id):
        if not m.receives_briefing:
            continue
        try:
            text = await asyncio.to_thread(compose_briefing, m.name)
            _send(notify, m.phone, m.name, text)
        except Exception as e:
            logger.warning(f"briefing for {m.name}: {e}")


async def _evening_brief(notify: NotifyFn) -> None:
    """Evening tomorrow-look + suggestions."""
    try:
        from myassistant.core.suggestions import collect
    except Exception:
        return
    f = fam.get_or_create_default_family()
    sugg = collect()
    if not sugg:
        return
    text = "🌙 Tonight's heads-up:\n" + "\n".join(f"• {s}" for s in sugg)
    for m in fam.list_members(f.id):
        if m.role == "parent" and m.receives_briefing and m.phone:
            _send(notify, m.phone, m.name, text)


async def _weekly_review_job(notify: NotifyFn) -> None:
    try:
        from myassistant.core.weekly_review import compose
    except Exception:
        return
    txt = await asyncio.to_thread(compose)
    f = fam.get_or_create_default_family()
    for m in fam.list_members(f.id):
        if m.role == "parent" and m.phone:
            _send(notify, m.phone, m.name, "📅 Weekly review:\n" + txt)


async def _deadman_job(notify: NotifyFn) -> None:
    try:
        from myassistant.skills.safety import deadman_check_and_alert
        await asyncio.to_thread(deadman_check_and_alert)
    except Exception as e:
        logger.warning(f"deadman: {e}")


async def _price_check_job(notify: NotifyFn) -> None:
    try:
        from myassistant.skills.commerce import check_prices
        out = await asyncio.to_thread(check_prices)
        if out and "no drops" not in out:
            f = fam.get_or_create_default_family()
            for m in fam.list_members(f.id):
                if m.role == "parent" and m.phone:
                    _send(notify, m.phone, m.name, "💰 Price drops:\n" + out)
    except Exception:
        pass


def start_proactive(scheduler_obj: AsyncIOScheduler, notify: NotifyFn) -> None:
    """Wire up Ollie's proactive jobs onto an existing AsyncIOScheduler."""
    interval = max(2, getattr(settings, "ollie_poll_interval_minutes", 15))
    scheduler_obj.add_job(
        _poll_school_inbox, IntervalTrigger(minutes=interval),
        args=[notify], id="ollie_inbox_poll", replace_existing=True,
        coalesce=True, max_instances=1,
    )
    scheduler_obj.add_job(
        _carpool_nudges, IntervalTrigger(minutes=2),
        args=[notify], id="ollie_carpool", replace_existing=True,
        coalesce=True, max_instances=1,
    )
    bt = getattr(settings, "ollie_briefing_time", "07:00")
    try:
        bh, bm = [int(x) for x in bt.split(":")]
    except Exception:
        bh, bm = 7, 0
    scheduler_obj.add_job(
        _morning_briefing, CronTrigger(hour=bh, minute=bm),
        args=[notify], id="ollie_briefing", replace_existing=True,
    )
    # Evening brief
    et = getattr(settings, "ollie_evening_brief_time", "20:30")
    try:
        eh, em = [int(x) for x in et.split(":")]
    except Exception:
        eh, em = 20, 30
    scheduler_obj.add_job(
        _evening_brief, CronTrigger(hour=eh, minute=em),
        args=[notify], id="ollie_evening", replace_existing=True,
    )
    # Weekly review
    wd = getattr(settings, "ollie_weekly_review_day", 6)
    wt = getattr(settings, "ollie_weekly_review_time", "18:00")
    try:
        wh, wm_ = [int(x) for x in wt.split(":")]
    except Exception:
        wh, wm_ = 18, 0
    scheduler_obj.add_job(
        _weekly_review_job, CronTrigger(day_of_week=wd, hour=wh, minute=wm_),
        args=[notify], id="ollie_weekly_review", replace_existing=True,
    )
    # Deadman switch — every 30 min
    scheduler_obj.add_job(
        _deadman_job, IntervalTrigger(minutes=30),
        args=[notify], id="ollie_deadman", replace_existing=True,
    )
    # Price check — every 6h
    scheduler_obj.add_job(
        _price_check_job, IntervalTrigger(hours=6),
        args=[notify], id="ollie_prices", replace_existing=True,
    )
    logger.info(f"Proactive jobs wired: inbox/{interval}m, carpool/2m, briefing@{bh:02d}:{bm:02d}, "
                f"evening@{eh:02d}:{em:02d}, weekly review day={wd} {wh:02d}:{wm_:02d}, deadman/30m, prices/6h")
