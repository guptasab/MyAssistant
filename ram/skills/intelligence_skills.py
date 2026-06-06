"""Intelligence skills — agent-callable wrappers for ram.core.intelligence.

These skills let the agent surface proactive insights on demand or when the
user asks vague status questions like "what's up?" or "anything I should know?".
"""
from __future__ import annotations

from ram.core.registry import skill


@skill(
    name="intelligence_report",
    description=(
        "Generate a proactive intelligence report covering upcoming deadlines, "
        "follow-ups needed, relationship health, and spending anomalies. "
        "Use when the user asks 'what should I know today?', 'anything urgent?', "
        "'what am I missing?', or 'give me a status check'."
    ),
    requires=[],
)
def intelligence_report() -> str:
    """Run the full proactive intelligence sweep and return a briefing."""
    from ram.core.intelligence import proactive_intelligence_report
    return proactive_intelligence_report()


@skill(
    name="scan_follow_ups",
    description=(
        "Scan for important contacts you haven't been in touch with recently. "
        "Use when the user asks 'who should I follow up with?' or 'any relationships I'm neglecting?'."
    ),
    parameters={
        "days_no_reply": {"type": "integer", "default": 4,
                          "description": "Flag contacts not touched in this many days"},
    },
    requires=[],
)
def scan_follow_ups_skill(days_no_reply: int = 4) -> str:
    """Surface contacts that need a follow-up."""
    from ram.core.intelligence import scan_follow_ups
    items = scan_follow_ups(days_no_reply=days_no_reply)
    if not items:
        return "✅ No follow-ups needed — you're on top of your important relationships."
    lines = [f"👥 Follow-ups needed ({len(items)}):"]
    for f in items:
        lines.append(f"  • {f['contact']} ({f['days_ago']}d) — {f['reason']}")
    return "\n".join(lines)


@skill(
    name="meeting_brief",
    description=(
        "Generate a contextual briefing for an upcoming meeting — who's attending, "
        "what they do, your shared history, and talking points. "
        "Use for 'prep me for my 2pm meeting', 'what should I know about the Acme call?'."
    ),
    parameters={
        "event_title": {"type": "string", "description": "Meeting title or name"},
        "attendees":   {"type": "array",  "items": {"type": "string"},
                        "default": [], "description": "List of attendee names or emails"},
    },
    requires=[],
)
def meeting_brief_skill(event_title: str, attendees: list = None) -> str:
    """Build a pre-meeting briefing card."""
    from ram.core.intelligence import build_meeting_brief
    return build_meeting_brief(event_title, attendees or [])


@skill(
    name="extract_action_items",
    description=(
        "Extract action items from an email or text. "
        "Use when the user pastes an email and asks 'what do I need to do?'."
    ),
    parameters={
        "text":    {"type": "string", "description": "Email or message body"},
        "sender":  {"type": "string", "default": ""},
        "subject": {"type": "string", "default": ""},
    },
    requires=[],
)
def extract_action_items_skill(text: str, sender: str = "", subject: str = "") -> str:
    """Extract and return action items from text."""
    from ram.core.intelligence import extract_action_items_from_email
    items = extract_action_items_from_email(text, sender, subject)
    if not items:
        return "No explicit action items found in this email."
    lines = ["📋 Action items:"]
    for i, item in enumerate(items, 1):
        lines.append(f"  {i}. {item}")
    return "\n".join(lines)
