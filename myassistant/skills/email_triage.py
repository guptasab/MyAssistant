"""Email triage — Gmail-powered, classifies inbox into action / FYI / noise.

Complements school_inbox.py (which is family-specific). This is the broader
work + personal triage that asks: 'what actually needs me today?'
"""
from __future__ import annotations

import json
import re

from loguru import logger

from myassistant.core.config import settings
from myassistant.core.registry import skill
from myassistant.skills.gmail_skill import gmail_service, _headers, _decode_body


_TRIAGE_PROMPT = """Classify this email for a busy professional. Return ONLY a JSON object:
{
 "bucket": "action" | "fyi" | "noise",
 "category": "work" | "personal" | "school" | "finance" | "travel" | "health" | "shopping" | "social" | "newsletter" | "spam",
 "summary": "one short sentence",
 "deadline": "YYYY-MM-DD or empty",
 "suggested_reply": "one short draft if a reply is needed, else empty"
}

From: {sender}
Subject: {subject}
Body:
{body}"""


def _classify(sender: str, subject: str, body: str) -> dict:
    from myassistant.core.llm import llm_classify
    return llm_classify(_TRIAGE_PROMPT.format(
        sender=sender[:120], subject=subject[:160], body=body[:3500],
    ))


@skill(
    name="triage_inbox",
    description=("Triage recent inbox messages into action/fyi/noise with category & summary. "
                 "Returns the action items. Window is a Gmail query like 'newer_than:1d'."),
)
def triage_inbox(window: str = "newer_than:1d", max_results: int = 20) -> str:
    svc = gmail_service()
    if not svc:
        return "ERROR: Gmail not connected."
    res = svc.users().messages().list(
        userId="me", q=window + " -category:promotions",
        maxResults=max(1, min(50, max_results)),
    ).execute()
    ids = [m["id"] for m in res.get("messages", [])]
    if not ids:
        return "inbox clear"
    actions = []
    fyi = []
    for mid in ids:
        full = svc.users().messages().get(userId="me", id=mid, format="full").execute()
        h = _headers(full)
        body = _decode_body(full.get("payload", {}))
        c = _classify(h.get("from", ""), h.get("subject", ""), body)
        if not c:
            continue
        line = f"[{c.get('category','?')}] {c.get('summary','')}"
        if c.get("deadline"):
            line += f" (by {c['deadline']})"
        if c.get("bucket") == "action":
            actions.append("  🟢 " + line + f"  ({mid})")
        elif c.get("bucket") == "fyi":
            fyi.append("  · " + line)
    out = []
    if actions:
        out.append("📬 Needs you:")
        out.extend(actions[:10])
    if fyi:
        out.append("\nFYI:")
        out.extend(fyi[:6])
    if not out:
        out.append("inbox clear — only noise")
    return "\n".join(out)


@skill(
    name="draft_reply",
    description=("Draft a reply to a specific Gmail message. tone = friendly|formal|brief. "
                 "Returns the draft text only — does NOT send."),
    sensitive=False,
)
def draft_reply(message_id: str, intent: str, tone: str = "friendly") -> str:
    svc = gmail_service()
    if not svc:
        return "ERROR: Gmail not connected."
    msg = svc.users().messages().get(userId="me", id=message_id, format="full").execute()
    h = _headers(msg)
    body = _decode_body(msg.get("payload", {}))
    try:
        from myassistant.core.llm import llm_chat
        return llm_chat(
            [{"role": "user", "content": (
                f"Draft a {tone} email reply. Be concise.\n\n"
                f"ORIGINAL:\nFrom: {h.get('from','')}\nSubject: {h.get('subject','')}\n\n{body[:3000]}\n\n"
                f"INTENT FOR REPLY: {intent}\n\nReturn only the reply body."
            )}],
            task="draft", max_tokens=600,
        )
    except Exception as e:
        return f"ERROR drafting: {e}"
