"""Family safety: check-in, emergency packet, deadman switch."""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from sqlalchemy import Column, Integer, String, Float

from ram.core.config import settings
from ram.core.memory import Base, db, _engine
from ram.core.registry import skill


class CheckIn(Base):
    __tablename__ = "checkins"
    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, index=True)
    location = Column(String, default="")
    note = Column(String, default="")
    ts = Column(Float, default=time.time, index=True)


Base.metadata.create_all(_engine)


@skill(name="checkin",
       description="Register a 'safe' check-in for a family member. Used by deadman switch.")
def checkin(member_id: int, location: str = "", note: str = "") -> str:
    with db() as s:
        s.add(CheckIn(member_id=member_id, location=location, note=note))
    return f"checked in @ {location or 'unspecified'}"


@skill(name="last_checkin",
       description="Show most recent check-in for everyone.")
def last_checkin() -> str:
    with db() as s:
        rows = s.query(CheckIn).order_by(CheckIn.ts.desc()).limit(50).all()
    seen = {}
    for r in rows:
        if r.member_id not in seen:
            seen[r.member_id] = r
    if not seen:
        return "(no check-ins)"
    out = []
    for mid, r in seen.items():
        ago = int((time.time() - r.ts) / 60)
        out.append(f"member#{mid}  {ago}m ago  {r.location} {r.note}")
    return "\n".join(out)


@skill(name="emergency_packet",
       description=("Generate an emergency packet (allergies, meds, doctors, blood types, "
                    "ICE contacts) for the family. Read-only summary."))
def emergency_packet() -> str:
    from ram.core import family as fam
    f = fam.get_or_create_default_family()
    members = fam.list_members(f.id)
    out = [f"=== EMERGENCY PACKET — {f.name} ==="]
    for m in members:
        out.append(f"\n{m.name} ({m.role}, age {m.age})")
        out.append(f"  phone: {m.phone}")
        out.append(f"  notes: {m.notes or '(none)'}")
    try:
        from ram.skills.medications import Medication
        with db() as s:
            meds = s.query(Medication).all()
        if meds:
            out.append("\n-- Medications --")
            for m in meds:
                out.append(f"  member#{m.member_id} {m.name} {m.dose}")
    except Exception:
        pass
    return "\n".join(out)


@skill(name="deadman_status",
       description=("Check if owner has interacted recently. If silence > OLLIE_DEADMAN_HOURS, "
                    "Ollie should alert OLLIE_DEADMAN_CONTACT."))
def deadman_status() -> str:
    from ram.core.memory import Message
    with db() as s:
        last = s.query(Message).filter(Message.role == "user").order_by(Message.ts.desc()).first()
    if not last:
        return "no user activity ever recorded"
    age_h = (time.time() - last.ts) / 3600
    threshold = settings.ollie_deadman_hours
    status = "OK" if age_h < threshold else "ALERT"
    return f"{status}: last user msg {age_h:.1f}h ago (threshold {threshold}h)"


def deadman_check_and_alert() -> bool:
    """Called by scheduler. Sends alert SMS if exceeded."""
    from ram.core.memory import Message
    with db() as s:
        last = s.query(Message).filter(Message.role == "user").order_by(Message.ts.desc()).first()
    if not last:
        return False
    age_h = (time.time() - last.ts) / 3600
    if age_h < settings.ollie_deadman_hours:
        return False
    if not settings.ollie_deadman_contact:
        return False
    try:
        from ram.channels.sms_channel import send_sms
        send_sms(settings.ollie_deadman_contact,
                 f"Ollie deadman: no activity from {settings.ram_owner_name} in {age_h:.0f}h.")
        return True
    except Exception:
        return False
