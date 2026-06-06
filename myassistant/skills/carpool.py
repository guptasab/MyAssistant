"""Carpool schedule — the recurring 'you're driving Tuesday morning' nudge."""
from __future__ import annotations

from datetime import datetime

from myassistant.core import family as fam
from myassistant.core.memory import db
from myassistant.core.registry import skill

_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _wd_to_int(weekday: str) -> int:
    w = weekday.strip().lower()[:3]
    if w not in _WEEKDAYS:
        raise ValueError(f"bad weekday: {weekday}")
    return _WEEKDAYS.index(w)


@skill(
    name="add_carpool",
    description=("Add a recurring carpool slot. weekday is mon..sun, "
                 "pickup_time is HH:MM (24h), driver is the family member's name."),
)
def add_carpool(weekday: str, pickup_time: str, driver: str, child: str,
                destination: str = "", notes: str = "") -> str:
    f = fam.get_or_create_default_family()
    try:
        wd = _wd_to_int(weekday)
    except ValueError as e:
        return f"ERROR: {e}"
    with db() as s:
        c = fam.CarpoolEntry(family_id=f.id, weekday=wd, pickup_time=pickup_time,
                             driver=driver, child=child, destination=destination,
                             notes=notes)
        s.add(c)
        s.flush()
        cid = c.id
    return f"carpool #{cid}: {weekday} {pickup_time} — {driver} drives {child}"


@skill(
    name="list_carpools",
    description="Show all recurring carpool slots.",
)
def list_carpools() -> str:
    f = fam.get_or_create_default_family()
    with db() as s:
        rows = (
            s.query(fam.CarpoolEntry)
            .filter(fam.CarpoolEntry.family_id == f.id)
            .order_by(fam.CarpoolEntry.weekday, fam.CarpoolEntry.pickup_time)
            .all()
        )
    if not rows:
        return "no carpools set"
    out = ["🚗 Carpools:"]
    for r in rows:
        dest = f" → {r.destination}" if r.destination else ""
        out.append(f"  {_WEEKDAYS[r.weekday]} {r.pickup_time} — {r.driver} drives {r.child}{dest}")
    return "\n".join(out)


@skill(
    name="remove_carpool",
    description="Remove a carpool slot by id.",
)
def remove_carpool(carpool_id: int) -> str:
    with db() as s:
        r = s.query(fam.CarpoolEntry).filter(fam.CarpoolEntry.id == carpool_id).one_or_none()
        if not r:
            return f"no carpool #{carpool_id}"
        s.delete(r)
    return f"removed carpool #{carpool_id}"


def carpools_for_today(family_id: int = 1) -> list[fam.CarpoolEntry]:
    wd = datetime.now().weekday()
    with db() as s:
        rows = (
            s.query(fam.CarpoolEntry)
            .filter(fam.CarpoolEntry.family_id == family_id,
                    fam.CarpoolEntry.weekday == wd)
            .order_by(fam.CarpoolEntry.pickup_time)
            .all()
        )
        for r in rows:
            s.expunge(r)
        return rows
