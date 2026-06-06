"""School-email parser — Ollie's flagship capability.

Uses Claude (the same client the agent uses) to classify and extract structured
data from inbox messages. Detects:
  - permission slips, early dismissal, parent conferences, supply requests,
    sick alerts, volunteer asks, events, fundraisers, newsletters

Persists each parsed email in `school_emails` so we don't re-parse and so
proactive logic can surface only the unsurfaced ones.
"""
from __future__ import annotations

import json
import re
import time
from typing import Optional

from loguru import logger

from myassistant.core import family as fam
from myassistant.core.config import settings
from myassistant.core.memory import db
from myassistant.core.registry import skill
from myassistant.skills.gmail_skill import gmail_service, _headers, _decode_body


SCHOOL_DOMAIN_HINTS = (
    "school", "k12", "edu", "pta", "classdojo", "seesaw", "blackbaud",
    "powerschool", "schoology", "remind.com", "parentsquare",
)

# JSON schema we ask Claude to fill out. Kept tight to minimize tokens.
_PARSE_PROMPT = """You are an expert at reading emails sent by US K-12 schools to parents.
Given the email below, return ONLY a JSON object with these keys:
  category: one of [general, permission_slip, early_dismissal, event,
            volunteer, absence, conference, supplies, newsletter, sick_alert, fundraiser]
  child_name: the student's first name if identifiable, else ""
  action_required: true if the parent needs to do something (sign, RSVP, send money/supplies, pick up early), else false
  deadline: YYYY-MM-DD if a deadline is mentioned, else ""
  summary: one short sentence (max 25 words) a busy parent can act on

EMAIL:
From: {sender}
Subject: {subject}
Body:
{body}

Return only the JSON object, nothing else."""


def _is_school_email(sender: str, subject: str) -> bool:
    s = (sender + " " + subject).lower()
    return any(h in s for h in SCHOOL_DOMAIN_HINTS) or "school" in subject.lower()


def _llm_parse(sender: str, subject: str, body: str) -> dict:
    """Use the multi-provider router to extract structured fields."""
    from myassistant.core.llm import llm_classify
    return llm_classify(_PARSE_PROMPT.format(
        sender=sender[:120], subject=subject[:160], body=body[:3500],
    ))


@skill(
    name="scan_school_inbox",
    description=("Scan recent inbox messages for school emails, parse out actions, "
                 "and stash them. Returns a summary. Safe to run repeatedly — "
                 "already-parsed messages are skipped."),
)
def scan_school_inbox(window: str = "newer_than:3d") -> str:
    svc = gmail_service()
    if not svc:
        return "ERROR: Gmail not connected."
    f = fam.get_or_create_default_family()

    res = svc.users().messages().list(
        userId="me", q=window + " -category:promotions -category:social",
        maxResults=50,
    ).execute()
    ids = [m["id"] for m in res.get("messages", [])]
    if not ids:
        return "no recent mail"

    new_parsed = 0
    actionable = 0
    with db() as s:
        for mid in ids:
            if s.query(fam.SchoolEmail).filter(fam.SchoolEmail.gmail_id == mid).first():
                continue
            full = svc.users().messages().get(userId="me", id=mid, format="full").execute()
            h = _headers(full)
            sender = h.get("from", "")
            subject = h.get("subject", "")
            if not _is_school_email(sender, subject):
                continue
            body = _decode_body(full.get("payload", {}))
            parsed = _llm_parse(sender, subject, body)
            if not parsed:
                continue
            row = fam.SchoolEmail(
                family_id=f.id,
                gmail_id=mid,
                received_ts=time.time(),
                sender=sender[:200],
                subject=subject[:300],
                snippet=full.get("snippet", "")[:500],
                child_name=parsed.get("child_name", "")[:100],
                category=parsed.get("category", "general"),
                action_required=bool(parsed.get("action_required")),
                deadline=parsed.get("deadline", "")[:20],
                summary=parsed.get("summary", "")[:500],
            )
            s.add(row)
            new_parsed += 1
            if row.action_required:
                actionable += 1
    return f"parsed {new_parsed} new school emails ({actionable} need action)"


@skill(
    name="school_action_items",
    description=("List unresolved (un-surfaced) school items that need parental action. "
                 "Returns most recent first."),
)
def school_action_items(limit: int = 10, include_surfaced: bool = False) -> str:
    f = fam.get_or_create_default_family()
    with db() as s:
        q = s.query(fam.SchoolEmail).filter(
            fam.SchoolEmail.family_id == f.id,
            fam.SchoolEmail.action_required == True,
        )
        if not include_surfaced:
            q = q.filter(fam.SchoolEmail.surfaced == False)
        rows = q.order_by(fam.SchoolEmail.received_ts.desc()).limit(limit).all()
        if not rows:
            return "no pending school actions"
        out = ["📬 School to-do:"]
        for r in rows:
            d = f" (by {r.deadline})" if r.deadline else ""
            who = f"[{r.child_name}] " if r.child_name else ""
            out.append(f"  • {who}{r.summary}{d}")
        return "\n".join(out)


@skill(
    name="mark_school_item_handled",
    description="Mark a parsed school email as handled (won't surface again).",
)
def mark_school_item_handled(school_email_id: int) -> str:
    with db() as s:
        r = s.query(fam.SchoolEmail).filter(fam.SchoolEmail.id == school_email_id).one_or_none()
        if not r:
            return f"no school email #{school_email_id}"
        r.surfaced = True
    return f"handled #{school_email_id}"


def _unsurfaced_actions(family_id: int = 1) -> list[fam.SchoolEmail]:
    """Used by the proactive loop."""
    with db() as s:
        rows = (
            s.query(fam.SchoolEmail)
            .filter(fam.SchoolEmail.family_id == family_id,
                    fam.SchoolEmail.action_required == True,
                    fam.SchoolEmail.surfaced == False)
            .order_by(fam.SchoolEmail.received_ts.asc())
            .all()
        )
        for r in rows:
            s.expunge(r)
        return rows


def _mark_surfaced(ids: list[int]) -> None:
    if not ids:
        return
    with db() as s:
        s.query(fam.SchoolEmail).filter(fam.SchoolEmail.id.in_(ids)).update(
            {fam.SchoolEmail.surfaced: True}, synchronize_session=False,
        )
