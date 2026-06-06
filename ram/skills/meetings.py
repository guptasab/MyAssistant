"""Meeting preparation — for work or personal appointments.

Gathers context Ollie already knows about: calendar event + the people you're
meeting (from Contacts) + recent notes related to them or the project.
"""
from __future__ import annotations

import datetime as dt

from ram.core import contexts as ctx
from ram.core.memory import db
from ram.core.registry import skill


@skill(
    name="prep_for_meeting",
    description=("Build a quick brief for an upcoming meeting. Provide the meeting "
                 "title or a participant name. Returns: who they are, last notes, "
                 "recent touches, and any related project."),
)
def prep_for_meeting(query: str) -> str:
    q = query.lower().strip()
    with db() as s:
        # Match contacts by name substring
        contacts = [c for c in s.query(ctx.Contact).all() if q in c.name.lower()]
        notes = [n for n in s.query(ctx.Note).order_by(ctx.Note.created_ts.desc()).limit(200).all()
                 if q in (n.title or "").lower() or q in n.body.lower()
                 or q in (n.related_contact or "").lower()]
        projects = [p for p in s.query(ctx.Project).all()
                    if q in p.name.lower() or q in (p.stakeholders or "").lower()]
    out = [f"🗂️  Brief: {query}"]
    if contacts:
        out.append("\nPeople:")
        for c in contacts[:5]:
            line = f"  • {c.name}"
            if c.title or c.company:
                line += f" — {' @ '.join(x for x in [c.title, c.company] if x)}"
            if c.last_contact_ts:
                last = dt.datetime.fromtimestamp(c.last_contact_ts).strftime("%b %d")
                line += f" (last touch {last})"
            out.append(line)
            if c.notes:
                snippet = c.notes.strip().splitlines()[-1][:120]
                out.append(f"     ↳ {snippet}")
    if projects:
        out.append("\nProjects:")
        for p in projects[:3]:
            due = f" (due {p.due})" if p.due else ""
            out.append(f"  • {p.name} — {p.status}{due}")
            if p.goal:
                out.append(f"     ↳ {p.goal[:160]}")
    if notes:
        out.append("\nRelated notes:")
        for n in notes[:5]:
            head = (n.title or n.body[:80]).strip()
            out.append(f"  • #{n.id} {head}")
    if len(out) == 1:
        out.append("  (nothing on file — first meeting?)")
    return "\n".join(out)


@skill(
    name="post_meeting_note",
    description=("Capture meeting notes and (optionally) link to a contact + project. "
                 "Auto-logs a 'touch' on each named participant."),
)
def post_meeting_note(body: str, title: str = "", participants: list = None,
                      project: str = "", context: str = "work",
                      tags: str = "meeting") -> str:
    from ram.skills.notes import add_note
    from ram.skills.contacts import log_contact_touch
    parts = participants or []
    note_resp = add_note(
        body=body, title=title or "Meeting notes", context=context,
        tags=tags, related_contact=",".join(parts),
        related_project=project,
    )
    for p in parts:
        try:
            log_contact_touch(p, note=f"Met: {title or body[:60]}")
        except Exception:
            pass
    return note_resp
