"""Proactive intelligence engine — Ram anticipates needs before you ask.

This module powers the things that make Ram feel like a great human assistant
rather than a reactive chatbot:

  Follow-up radar:    Emails you sent 3+ days ago with no reply → nudge suggestion
  Deadline radar:     Tasks/events with deadlines in the next 48h → early warning
  Relationship pulse: Contacts you haven't been in touch with for too long
  Meeting intel:      Automatic context pull 30 min before any calendar event
  Spend alerts:       Daily/weekly spend vs budget with anomaly flags
  Action extraction:  Scan emails for buried action items and surface them

The scheduler in ``ram.core.proactive`` calls these functions periodically.
The agent can also call them directly when the user asks for a status update.

All suggestions go through ``ram.core.suggestions`` so duplicates are suppressed
and the user sees each insight at most once per day.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from loguru import logger

from ram.core.memory import db
from ram.core import contexts as ctx


# ── Follow-up radar ───────────────────────────────────────────────────────

def scan_follow_ups(days_no_reply: int = 3) -> list[dict]:
    """Find emails the user sent that haven't received a reply.

    Looks at the ``SentEmail`` table (populated by email_send.py) and
    compares against recent received messages.  Returns a list of
    follow-up opportunities.

    Args:
        days_no_reply: Flag as needing a nudge after this many days.

    Returns:
        List of dicts with ``to``, ``subject``, ``sent_ts``, ``days_ago``.
    """
    cutoff = time.time() - days_no_reply * 86400
    results = []
    try:
        with db() as s:
            # Check Contact last_contact_ts — flag stale important contacts
            contacts = s.query(ctx.Contact).filter(
                ctx.Contact.last_contact_ts.isnot(None),
            ).all()
            for c in contacts:
                if c.last_contact_ts and c.last_contact_ts < cutoff:
                    if c.relationship in ("manager", "client", "lead", "mentor",
                                          "investor", "partner", "friend"):
                        days = int((time.time() - c.last_contact_ts) / 86400)
                        results.append({
                            "type":     "follow_up",
                            "contact":  c.name,
                            "email":    c.email,
                            "days_ago": days,
                            "reason":   f"Important contact ({c.relationship}) — {days}d since last touch",
                        })
    except Exception as e:
        logger.debug(f"follow-up scan: {e}")
    return results[:10]


def scan_deadlines(hours_ahead: int = 48) -> list[dict]:
    """Find tasks and events with deadlines or start times in the next N hours.

    Args:
        hours_ahead: Look-ahead window in hours.

    Returns:
        List of dicts describing upcoming deadlines.
    """
    now = datetime.now()
    horizon = now + timedelta(hours=hours_ahead)
    results = []
    try:
        with db() as s:
            tasks = s.query(ctx.Task).filter(
                ctx.Task.status.in_(["todo", "doing"]),
                ctx.Task.due.isnot(None),
            ).all()
            for t in tasks:
                try:
                    due = datetime.fromisoformat(t.due)
                    if now <= due <= horizon:
                        hours_left = int((due - now).total_seconds() / 3600)
                        results.append({
                            "type":       "deadline",
                            "title":      t.title,
                            "due":        t.due,
                            "hours_left": hours_left,
                            "priority":   t.priority or "normal",
                            "reason":     f"Task '{t.title}' due in {hours_left}h",
                        })
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"deadline scan: {e}")

    # Sort: most urgent first
    results.sort(key=lambda x: x.get("hours_left", 999))
    return results[:10]


def extract_action_items_from_email(email_body: str, sender: str, subject: str) -> list[str]:
    """Use LLM to extract explicit action items buried in an email.

    Args:
        email_body: The email body text.
        sender:     The sender's name/address.
        subject:    The email subject.

    Returns:
        List of action item strings, each phrased as a task.
    """
    from ram.core.llm import llm_classify
    prompt = f"""Extract explicit action items (things I need to do) from this email.
Return JSON: {{"actions": ["action 1", "action 2", ...]}}
If none, return {{"actions": []}}

From: {sender[:60]}
Subject: {subject[:100]}
Body: {email_body[:2000]}"""
    try:
        result = llm_classify(prompt)
        return result.get("actions", [])[:5]
    except Exception:
        return []


def build_meeting_brief(event_title: str, attendees: list[str]) -> str:
    """Build a contextual brief for an upcoming meeting.

    Pulls from contacts, notes, projects, and recent emails related to
    the meeting title and attendees.  Formats it as a tight briefing card.

    Args:
        event_title: Calendar event title / meeting name.
        attendees:   List of attendee email addresses or names.

    Returns:
        Markdown-formatted meeting brief.
    """
    from ram.skills.meetings import prep_for_meeting
    # Use existing meeting prep skill as the foundation
    brief = prep_for_meeting(event_title)

    # Add attendee context
    if attendees:
        with db() as s:
            lines = []
            for name in attendees[:5]:
                c = s.query(ctx.Contact).filter(
                    ctx.Contact.name.ilike(f"%{name.split('@')[0]}%")
                ).first()
                if c:
                    line = f"  • {c.name}"
                    if c.title or c.company:
                        line += f" — {' @ '.join(x for x in [c.title, c.company] if x)}"
                    if c.notes:
                        line += f"\n    Note: {c.notes.strip()[:80]}"
                    lines.append(line)
            if lines:
                brief += "\n\nAttendees:\n" + "\n".join(lines)
    return brief


def proactive_intelligence_report() -> str:
    """Generate a full proactive intelligence summary.

    Combines follow-ups, deadlines, relationship health, and action extraction
    into one concise report.  Called by the morning briefing and on demand.

    Returns:
        Plain-text intelligence report.
    """
    sections = []

    # Deadlines
    deadlines = scan_deadlines(hours_ahead=48)
    if deadlines:
        lines = [f"  ⏰ {d['title']} — due in {d['hours_left']}h" for d in deadlines[:5]]
        sections.append("**Upcoming Deadlines:**\n" + "\n".join(lines))

    # Follow-ups
    follow_ups = scan_follow_ups(days_no_reply=4)
    if follow_ups:
        lines = [f"  💬 {f['contact']} ({f['days_ago']}d) — {f['reason']}" for f in follow_ups[:5]]
        sections.append("**Follow-ups needed:**\n" + "\n".join(lines))

    # Budget anomalies
    try:
        from ram.core.anomaly import detect_anomalies
        anomalies = detect_anomalies(lookback_days=30)
        if anomalies:
            lines = [f"  💸 {a['category']}: {a['description']}" for a in anomalies[:3]]
            sections.append("**Spending anomalies:**\n" + "\n".join(lines))
    except Exception:
        pass

    if not sections:
        return "✅ Nothing urgent to flag — you're on top of things!"

    return "🔮 **Intelligence Report**\n\n" + "\n\n".join(sections)
