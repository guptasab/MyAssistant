"""Onboarding and self-discovery skills for Squire.

Provides first-contact experience, setup status, and a rich capability guide
so non-technical users know exactly what Squire can do for them.
"""
from __future__ import annotations

from ram.core import family as fam
from ram.core.memory import db, all_facts
from ram.core.registry import skill


@skill(
    name="onboarding_status",
    description=(
        "Return a short summary of what Squire knows so far and what's "
        "missing (Gmail/Calendar OAuth, SMS, briefing time, email accounts). "
        "Use whenever the user asks 'what do you know about me?', "
        "'are you set up?', or right after first contact."
    ),
)
def onboarding_status() -> str:
    f = fam.get_or_create_default_family()
    members = fam.list_members(f.id)
    facts = all_facts()

    from pathlib import Path
    from ram.core.config import settings
    agent_name  = settings.squire_agent_name
    google_ok   = (settings.ram_data_dir / "google_token.json").exists()
    sms_ok      = bool(settings.twilio_account_sid and settings.twilio_sms_from)
    telegram_ok = bool(settings.telegram_bot_token)

    lines = [f"👋 Hi — I'm {agent_name}. Here's what I have so far:"]
    lines.append(f"  • Household members : {len(members)}"
                 + (" ✓" if members else " — tell me who's in your family"))
    lines.append(f"  • Gmail / Calendar  : {'connected ✓' if google_ok else 'not connected'}")
    lines.append(f"  • SMS (Twilio)      : {'ready ✓' if sms_ok else 'not configured'}")
    lines.append(f"  • Telegram          : {'ready ✓' if telegram_ok else 'not configured'}")
    lines.append(f"  • Daily briefing    : {f.briefing_time}")
    lines.append(f"  • Facts I remember  : {len(facts)}")

    todo = []
    if not members:
        todo.append("Tell me who's in your family: 'add my wife Jane +1415…'")
    if not google_ok:
        todo.append("Connect Gmail + Calendar so I can watch your inbox.")
    if not sms_ok and not telegram_ok:
        todo.append("Set up a messaging channel to reach me from your phone.")
    if todo:
        lines.append("\nNext steps:")
        for t in todo:
            lines.append(f"  → {t}")
    else:
        lines.append("\nFully set up — I'll send your briefing in the morning. 💛")
    lines.append(
        f"\nTip: run '{agent_name.lower()} onboard' from the terminal for a guided setup wizard."
    )
    return "\n".join(lines)


@skill(
    name="what_can_you_do",
    description=(
        "Return a comprehensive, friendly guide to all of Squire's capabilities "
        "organised by category with usage examples. Use when the user asks "
        "'what can you do?', 'what are your capabilities?', 'help', or 'show me what you can do'."
    ),
)
def what_can_you_do() -> str:  # noqa: D401
    """Return a friendly, categorised capability guide."""
    sections = [
        (
            "📬 Email & Calendar",
            [
                ("Check my emails",        "I'll triage your inbox, flag urgent items, and summarise the rest."),
                ("Draft a reply to Sarah",  "I'll match your writing style and draft a polished reply."),
                ("What's on my calendar?",  "I'll show today's and tomorrow's events across all calendars."),
                ("Schedule a meeting with John on Friday", "I'll find a free slot and send an invite."),
            ],
        ),
        (
            "📋 Tasks & Productivity",
            [
                ("What's on my plate?",         "Full daily briefing: emails, tasks, calendar, reminders."),
                ("Add a reminder to call mom at 5pm", "Saved — I'll alert you at 5 pm."),
                ("What tasks are overdue?",      "I'll scan all your to-do lists and flag overdue items."),
                ("Summarise my week",            "Highlights: completed tasks, upcoming deadlines, wins."),
            ],
        ),
        (
            "🔍 Research & Web",
            [
                ("Research the best electric cars under $40k", "Deep research with sourced answers."),
                ("Find Italian restaurants near me for pick-up", "Nearby results with ratings and hours."),
                ("What's the weather this week?", "Current conditions and 7-day forecast."),
                ("Who is the CEO of Apple?",      "Instant answer with supporting context."),
            ],
        ),
        (
            "💰 Finance & Bills",
            [
                ("What's up with my utilities bill this month?", "I'll pull your latest bills and compare to last month."),
                ("Show my recent spending",       "Categorised transactions from your connected accounts."),
                ("How much did I spend on food last month?", "Spending breakdown by category."),
                ("Any unusual charges?",          "I'll flag transactions that look out of the ordinary."),
            ],
        ),
        (
            "🏠 Smart Home & Family",
            [
                ("Turn off the living room lights", "Sent to Home Assistant / Google Home / Alexa."),
                ("Where is my daughter right now?", "Last known location from Find My."),
                ("Set the thermostat to 70°F",     "Done via smart home integration."),
                ("What's for dinner tonight?",     "Meal plan suggestion based on what's in the fridge."),
            ],
        ),
        (
            "💻 Coding & DevOps",
            [
                ("Review the last PR in my repo",  "I'll read the diff and give you actionable feedback."),
                ("Debug the last call in prod",    "I'll pull CloudWatch logs and trace the error."),
                ("Find bugs in this file",         "Deep static analysis with fix suggestions."),
                ("Explain what this function does","Plain-English explanation of any code snippet."),
            ],
        ),
        (
            "✈️ Travel & Logistics",
            [
                ("Track my flight AA 1234",        "Live status, gate info, delay alerts."),
                ("I'm travelling to NYC next week — what should I know?", "Weather, hotels, local tips."),
                ("Book me a hotel in Paris for two nights", "Search across booking sites."),
                ("Find the cheapest flight to London in July", "Price comparison across airlines."),
            ],
        ),
        (
            "🏥 Health & Wellbeing",
            [
                ("Log today's workout",            "Saved to your health log."),
                ("How many steps did I take this week?", "Summary from your connected wearable."),
                ("Remind me to take my medication at 8am", "Daily reminder set."),
                ("Symptoms checker: I have a headache and fever", "Guidance + when to see a doctor."),
            ],
        ),
        (
            "📁 Files & Documents",
            [
                ("Summarise this PDF",             "Upload any document — I'll extract the key points."),
                ("Find my presentation from last quarter", "Search Google Drive or local files."),
                ("Create a Google Doc with this outline", "I'll draft the document for you."),
                ("Update cell B5 in my budget spreadsheet to $500", "Direct Sheets edit."),
            ],
        ),
    ]

    lines = [
        "✨ Here's everything I can help you with:\n",
        "(You can ask me any of these — or just talk to me naturally!)\n",
    ]

    for title, examples in sections:
        lines.append(f"\n{title}")
        for cmd, desc in examples:
            lines.append(f"  • \"{cmd}\"")
            lines.append(f"    {desc}")

    from ram.core.config import settings
    agent_name = settings.squire_agent_name

    lines.append(
        f"\n─────────────────────────────────────────\n"
        f"💡 Tips:\n"
        f"  • Say 'Hey {agent_name}' on mobile to activate hands-free\n"
        f"  • Connect more services via the admin panel for more power\n"
        f"  • Ask 'am I set up?' to check your integration status\n"
        f"  • Use '{agent_name.lower()} doctor' in the terminal for a health audit"
    )

    return "\n".join(lines)


@skill(
    name="whats_on_my_plate",
    description=(
        "One-shot 'show me everything' — calendar today, urgent emails, "
        "personal tasks due, open list counts, follow-ups, and tonight's dinner. "
        "Use as default response to 'what's up?', 'today?', 'catch me up', or 'morning briefing'."
    ),
)
def whats_on_my_plate() -> str:
    # Reuses the briefing composer but framed as a status check.
    from ram.skills.briefing import compose_briefing
    return compose_briefing()

