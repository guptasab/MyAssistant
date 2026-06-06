"""Medication tracker — schedule, log doses, and refill alerts."""
from __future__ import annotations

import time

from sqlalchemy import Column, Integer, String, Float, Boolean

from ram.core.memory import Base, db, _engine
from ram.core.registry import skill


class Medication(Base):
    __tablename__ = "medications"
    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, default=0, index=True)
    name = Column(String)
    dose = Column(String, default="")
    schedule = Column(String, default="")           # 'daily 08:00', '2x/day', etc.
    refill_remaining = Column(Integer, default=0)
    notes = Column(String, default="")
    created_ts = Column(Float, default=time.time)


class MedDose(Base):
    __tablename__ = "med_doses"
    id = Column(Integer, primary_key=True)
    med_id = Column(Integer, index=True)
    member_id = Column(Integer, default=0)
    ts = Column(Float, default=time.time, index=True)
    skipped = Column(Boolean, default=False)


Base.metadata.create_all(_engine)


@skill(name="med_add", description="Add a medication. Returns its id.")
def med_add(name: str, dose: str = "", schedule: str = "", refill_remaining: int = 30,
            member_id: int = 0) -> str:
    with db() as s:
        m = Medication(name=name, dose=dose, schedule=schedule,
                       refill_remaining=refill_remaining, member_id=member_id)
        s.add(m)
        s.flush()
        return f"med #{m.id} {name}"


@skill(name="med_log", description="Log a dose taken (or skipped=True).")
def med_log(med_id: int, skipped: bool = False) -> str:
    with db() as s:
        m = s.query(Medication).filter(Medication.id == med_id).first()
        if not m:
            return "not found"
        s.add(MedDose(med_id=med_id, member_id=m.member_id, skipped=skipped))
        if not skipped and m.refill_remaining > 0:
            m.refill_remaining -= 1
        return f"logged. {m.refill_remaining} doses left."


@skill(name="med_status", description="Show all meds + refill counts.")
def med_status(member_id: int = 0) -> str:
    with db() as s:
        q = s.query(Medication)
        if member_id:
            q = q.filter(Medication.member_id == member_id)
        rows = q.all()
        if not rows:
            return "no meds"
        return "\n".join(f"#{m.id} {m.name} {m.dose} ({m.schedule}) — {m.refill_remaining} left" for m in rows)
