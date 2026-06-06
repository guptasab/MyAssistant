"""Standup composer + OOO autoresponder + doc drafting."""
from __future__ import annotations

import time

from ram.core import contexts as ctx
from ram.core.memory import db
from ram.core.registry import skill


@skill(name="standup_compose",
       description=("Compose today's standup from work tasks finished yesterday + open today + blockers. "
                    "Uses LLM for natural phrasing."))
def standup_compose() -> str:
    cutoff = time.time() - 36 * 3600
    with db() as s:
        done = s.query(ctx.Task).filter(
            ctx.Task.status == "done", ctx.Task.done_ts >= cutoff
        ).all()
        open_t = s.query(ctx.Task).filter(ctx.Task.status != "done").limit(20).all()
        blockers = [t for t in open_t if t.status == "blocked" or "block" in (t.notes or "").lower()]
    yesterday = "; ".join(t.title for t in done) or "(nothing logged)"
    today = "; ".join(t.title for t in open_t[:5])
    block = "; ".join(t.title for t in blockers) or "none"
    try:
        from ram.core.llm import llm_chat
        return llm_chat([{"role": "user", "content": (
            f"Compose a 3-line standup. Yesterday: {yesterday}. "
            f"Today: {today}. Blockers: {block}. Tone: brief, professional."
        )}], task="draft", max_tokens=200)
    except Exception:
        return f"Y: {yesterday}\nT: {today}\nB: {block}"


@skill(name="ooo_autoresponder",
       description=("Set Gmail vacation responder. start/end as 'YYYY-MM-DD'. "
                    "Confirms before applying."),
       sensitive=True)
def ooo_autoresponder(start: str, end: str, message: str) -> str:
    try:
        from ram.skills.gmail_skill import gmail_service
        svc = gmail_service()
    except Exception as e:
        return f"ERROR: {e}"
    if not svc:
        return "ERROR: gmail not connected"
    from datetime import datetime
    body = {
        "enableAutoReply": True,
        "responseSubject": "Out of office",
        "responseBodyPlainText": message,
        "restrictToContacts": False,
        "restrictToDomain": False,
        "startTime": int(datetime.fromisoformat(start).timestamp() * 1000),
        "endTime": int(datetime.fromisoformat(end).timestamp() * 1000),
    }
    svc.users().settings().updateVacation(userId="me", body=body).execute()
    return f"OOO set {start} → {end}"


@skill(name="doc_draft",
       description=("Draft a document (memo/post/email/spec). Returns the draft for review."))
def doc_draft(prompt: str, format: str = "memo", length_words: int = 350) -> str:
    try:
        from ram.core.llm import llm_chat
        return llm_chat([{"role": "user", "content":
            f"Draft a ~{length_words} word {format}. Prompt: {prompt}\nReturn only the draft."
        }], task="draft", max_tokens=int(length_words * 2))
    except Exception as e:
        return f"ERROR: {e}"
