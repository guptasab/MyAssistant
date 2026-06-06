"""Family roster — add/list parents, kids, caregivers. Used during onboarding."""
from __future__ import annotations

from myassistant.core import family as fam
from myassistant.core.memory import db
from myassistant.core.registry import skill


@skill(
    name="family_setup",
    description=("Initialize or update the family profile (name, timezone, "
                 "morning briefing time HH:MM). Safe to call multiple times."),
)
def family_setup(family_name: str = "", timezone: str = "", briefing_time: str = "") -> str:
    f = fam.get_or_create_default_family()
    with db() as s:
        row = s.query(fam.Family).filter(fam.Family.id == f.id).one()
        if family_name:
            row.name = family_name
        if timezone:
            row.timezone = timezone
        if briefing_time:
            row.briefing_time = briefing_time
    return f"Family set: name={family_name or f.name}, tz={timezone or f.timezone}, briefing={briefing_time or f.briefing_time}"


@skill(
    name="add_family_member",
    description=("Add a member to the family. role is one of: parent, kid, caregiver. "
                 "Phone should be E.164 (e.g. +14155551234) so Ollie can text them."),
)
def add_family_member(name: str, role: str = "parent", phone: str = "",
                      email: str = "", age: int = 0, school: str = "",
                      notes: str = "") -> str:
    f = fam.get_or_create_default_family()
    phone = phone.strip().replace(" ", "")
    with db() as s:
        existing = (
            s.query(fam.Member)
            .filter(fam.Member.family_id == f.id, fam.Member.name == name)
            .one_or_none()
        )
        if existing:
            existing.role = role or existing.role
            existing.phone = phone or existing.phone
            existing.email = email or existing.email
            existing.age = age or existing.age
            existing.school = school or existing.school
            existing.notes = notes or existing.notes
            return f"updated {name} ({existing.role})"
        m = fam.Member(family_id=f.id, name=name, role=role, phone=phone,
                       email=email, age=age, school=school, notes=notes)
        s.add(m)
    return f"added {name} as {role}" + (f" ({phone})" if phone else "")


@skill(name="list_family_members", description="List everyone in the family.")
def list_family_members() -> str:
    members = fam.list_members()
    if not members:
        return "no family members yet — say 'add my wife Jane, phone +1...' to start"
    out = []
    for m in members:
        parts = [f"{m.name} ({m.role})"]
        if m.age:
            parts.append(f"age {m.age}")
        if m.school:
            parts.append(m.school)
        if m.phone:
            parts.append(m.phone)
        out.append(" — ".join(parts))
    return "\n".join(out)


@skill(
    name="remove_family_member",
    description="Remove a member from the family by name.",
    sensitive=True,
)
def remove_family_member(name: str) -> str:
    f = fam.get_or_create_default_family()
    with db() as s:
        m = (
            s.query(fam.Member)
            .filter(fam.Member.family_id == f.id, fam.Member.name == name)
            .one_or_none()
        )
        if not m:
            return f"no member named {name}"
        s.delete(m)
    return f"removed {name}"


@skill(
    name="set_briefing_preference",
    description="Toggle whether a member receives the daily morning briefing.",
)
def set_briefing_preference(name: str, enabled: bool) -> str:
    f = fam.get_or_create_default_family()
    with db() as s:
        m = (
            s.query(fam.Member)
            .filter(fam.Member.family_id == f.id, fam.Member.name == name)
            .one_or_none()
        )
        if not m:
            return f"no member named {name}"
        m.receives_briefing = enabled
    return f"{name} briefing = {enabled}"
