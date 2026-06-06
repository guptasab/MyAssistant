"""Notes & journal — fast capture, tag, search across all contexts."""
from __future__ import annotations

from datetime import date

from ram.core import contexts as ctx
from ram.core.memory import db
from ram.core.registry import skill


@skill(
    name="add_note",
    description=("Capture a quick note. context=family|personal|work|<custom>. "
                 "tags is a comma list. related_contact / related_project optional."),
)
def add_note(body: str, title: str = "", context: str = "personal",
             tags: str = "", related_contact: str = "",
             related_project: str = "", pinned: bool = False) -> str:
    cid = ctx.resolve_context_id(context)
    with db() as s:
        n = ctx.Note(context_id=cid, title=title, body=body, tags=tags,
                     related_contact=related_contact,
                     related_project=related_project, pinned=pinned)
        s.add(n)
        s.flush()
        nid = n.id
    return f"📝 note #{nid} saved [{context}]"


@skill(
    name="search_notes",
    description=("Search notes by text/title/tag substring (case-insensitive). "
                 "Optional context filter. Returns up to 10."),
)
def search_notes(query: str, context: str = "") -> str:
    q = query.lower().strip()
    with db() as s:
        rows = s.query(ctx.Note)
        if context:
            rows = rows.filter(ctx.Note.context_id == ctx.resolve_context_id(context))
        rows = rows.order_by(ctx.Note.created_ts.desc()).all()
        hits = [r for r in rows
                if q in (r.title or "").lower() or q in r.body.lower()
                or q in (r.tags or "").lower()]
        if not hits:
            return f"no notes matched '{query}'"
        out = []
        for r in hits[:10]:
            head = r.title or r.body[:60]
            out.append(f"#{r.id} {head}")
        return "\n".join(out)


@skill(
    name="read_note",
    description="Read the full body of a note by id.",
)
def read_note(note_id: int) -> str:
    with db() as s:
        n = s.query(ctx.Note).filter(ctx.Note.id == note_id).one_or_none()
        if not n:
            return f"no note #{note_id}"
        head = f"📝 {n.title}\n" if n.title else ""
        return f"{head}{n.body}"


@skill(
    name="recent_notes",
    description="Show the N most recent notes (default 5), optionally per context.",
)
def recent_notes(limit: int = 5, context: str = "") -> str:
    with db() as s:
        q = s.query(ctx.Note)
        if context:
            q = q.filter(ctx.Note.context_id == ctx.resolve_context_id(context))
        rows = q.order_by(ctx.Note.created_ts.desc()).limit(limit).all()
        if not rows:
            return "no notes yet"
        return "\n".join(f"#{r.id} {(r.title or r.body[:60])}" for r in rows)


# ---- journal ----

@skill(
    name="journal_today",
    description=("Write today's journal entry. mood is a word or 1-5; energy is 1-5. "
                 "Appends if an entry already exists for today."),
)
def journal_today(body: str, mood: str = "", energy: int = 0, gratitude: str = "") -> str:
    today = date.today().isoformat()
    with db() as s:
        e = s.query(ctx.JournalEntry).filter(ctx.JournalEntry.date == today).one_or_none()
        if e:
            e.body = (e.body or "") + "\n\n" + body
            if mood:
                e.mood = mood
            if energy:
                e.energy = energy
            if gratitude:
                e.gratitude = (e.gratitude or "") + "\n" + gratitude
        else:
            s.add(ctx.JournalEntry(date=today, body=body, mood=mood,
                                   energy=energy, gratitude=gratitude))
    return f"journal saved for {today}"


@skill(
    name="journal_read",
    description="Read a journal entry by date (YYYY-MM-DD, default today).",
)
def journal_read(entry_date: str = "") -> str:
    d = entry_date or date.today().isoformat()
    with db() as s:
        e = s.query(ctx.JournalEntry).filter(ctx.JournalEntry.date == d).one_or_none()
        if not e:
            return f"no journal for {d}"
        parts = [f"📓 {d}"]
        if e.mood:
            parts.append(f"mood: {e.mood}")
        if e.energy:
            parts.append(f"energy: {e.energy}/5")
        parts.append("")
        parts.append(e.body)
        if e.gratitude:
            parts.append(f"\n🙏 {e.gratitude}")
        return "\n".join(parts)
