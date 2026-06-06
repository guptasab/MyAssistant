"""CalDAV calendar skill — Apple Calendar, Fastmail, Nextcloud, and any CalDAV server.

CalDAV is the open standard used by:
  • Apple Calendar / iCloud
  • Fastmail
  • Nextcloud
  • Proton Calendar
  • Yahoo Calendar
  • Any self-hosted server (Radicale, Baikal, etc.)

Accounts are registered in ``ram.core.accounts`` with kind="caldav" and
``extra_json = {"caldav_url": "https://...", "username": "...", "password": "..."}``.

Install dependency: ``pip install caldav``
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger

from ram.core.registry import skill
from ram.core.accounts import list_accounts, get_account_secret


def _caldav_client(account_email: str):
    """Build a caldav.DAVClient for a connected CalDAV account.

    Args:
        account_email: The registered account email address.

    Returns:
        A caldav.DAVClient instance, or None if the account isn't found.
    """
    try:
        import caldav

        accts = list_accounts(kind="caldav")
        acct = next((a for a in accts if a.email == account_email), None)
        if acct is None and accts:
            acct = accts[0]   # fall back to first CalDAV account
        if acct is None:
            return None, None

        secret = get_account_secret(acct.id)
        extra = acct.extra_json or {}
        caldav_url = extra.get("caldav_url") or _default_url(acct.email)
        username = extra.get("username", acct.email)
        password = secret or extra.get("password", "")

        client = caldav.DAVClient(url=caldav_url, username=username, password=password)
        principal = client.principal()
        return client, principal
    except ImportError:
        logger.warning("caldav package not installed — run: pip install caldav")
        return None, None
    except Exception as e:
        logger.debug(f"CalDAV connect {account_email}: {e}")
        return None, None


def _default_url(email: str) -> str:
    """Guess the CalDAV URL from the email domain."""
    domain = email.split("@")[-1].lower()
    urls = {
        "icloud.com":   "https://caldav.icloud.com",
        "me.com":       "https://caldav.icloud.com",
        "mac.com":      "https://caldav.icloud.com",
        "fastmail.com": "https://caldav.fastmail.com/dav",
        "fastmail.fm":  "https://caldav.fastmail.com/dav",
        "yahoo.com":    "https://caldav.calendar.yahoo.com",
        "proton.me":    "https://caldav.proton.me",
        "protonmail.com": "https://caldav.proton.me",
    }
    return urls.get(domain, f"https://caldav.{domain}")


@skill(
    name="caldav_list_events",
    description=(
        "List calendar events from a CalDAV account (Apple iCloud, Fastmail, Nextcloud, etc.). "
        "Use when the user asks about their Apple Calendar or non-Google/Outlook calendar."
    ),
    parameters={
        "account": {"type": "string", "default": "",
                    "description": "Email address of the CalDAV account (uses first if empty)"},
        "days":    {"type": "integer", "default": 7,
                    "description": "Look ahead this many days"},
    },
    requires=[],
)
def caldav_list_events(account: str = "", days: int = 7) -> str:
    """List upcoming events from a CalDAV calendar."""
    _, principal = _caldav_client(account)
    if principal is None:
        return (
            "No CalDAV account connected. "
            "Connect one in Settings → Channels → Add CalDAV Account."
        )

    try:
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=days)
        calendars = principal.calendars()
        if not calendars:
            return "No calendars found on this CalDAV account."

        all_events: list[tuple[datetime, str, str, str]] = []
        for cal in calendars:
            try:
                events = cal.date_search(start=now, end=end, expand=True)
                for e in events:
                    vevent = e.vobject_instance.vevent
                    start = getattr(vevent.dtstart, "value", "")
                    title = str(getattr(vevent.summary, "value", "(no title)"))
                    location = str(getattr(vevent.location, "value", "")) if hasattr(vevent, "location") else ""
                    if isinstance(start, datetime):
                        start_str = start.strftime("%Y-%m-%d %H:%M")
                    elif hasattr(start, "strftime"):
                        start_str = start.strftime("%Y-%m-%d")
                    else:
                        start_str = str(start)[:16]
                    all_events.append((start, title, location, cal.name or ""))
            except Exception:
                pass

        if not all_events:
            return f"No events in the next {days} days."

        all_events.sort(key=lambda x: str(x[0]))
        lines = [f"📅 CalDAV Calendar — next {days} days:"]
        for start, title, location, calname in all_events[:20]:
            loc = f" @ {location[:30]}" if location else ""
            cal_label = f" [{calname}]" if calname else ""
            lines.append(f"  {str(start)[:16]}  {title}{loc}{cal_label}")
        return "\n".join(lines)

    except Exception as e:
        return f"Error reading CalDAV calendar: {e}"


@skill(
    name="caldav_create_event",
    description=(
        "Create a calendar event on a CalDAV account (Apple iCloud, Fastmail, etc.). "
        "Requires: title, start time. Optional: end, location, description, account."
    ),
    parameters={
        "title":       {"type": "string"},
        "start":       {"type": "string", "description": "ISO datetime, e.g. 2025-06-15T14:00"},
        "end":         {"type": "string", "default": "",
                        "description": "ISO datetime (defaults to start + 1 hour)"},
        "location":    {"type": "string", "default": ""},
        "description": {"type": "string", "default": ""},
        "account":     {"type": "string", "default": ""},
    },
    sensitive=True,
    requires=[],
)
def caldav_create_event(title: str, start: str, end: str = "",
                        location: str = "", description: str = "",
                        account: str = "") -> str:
    """Create an event on a CalDAV calendar."""
    _, principal = _caldav_client(account)
    if principal is None:
        return "No CalDAV account connected."

    try:
        import icalendar
        import uuid

        start_dt = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
        end_dt   = (datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
                    if end else start_dt + timedelta(hours=1))

        cal = icalendar.Calendar()
        cal.add("prodid", "-//Ram//caldav_skill//EN")
        cal.add("version", "2.0")
        event = icalendar.Event()
        event.add("uid", str(uuid.uuid4()))
        event.add("summary", title)
        event.add("dtstart", start_dt)
        event.add("dtend", end_dt)
        if location:
            event.add("location", location)
        if description:
            event.add("description", description)
        cal.add_component(event)

        # Add to first writable calendar
        calendars = principal.calendars()
        if not calendars:
            return "No writable calendars found."
        calendars[0].save_event(cal.to_ical().decode())
        return f"✅ Created '{title}' on {start_dt.strftime('%b %d at %I:%M %p')} in CalDAV calendar."

    except ImportError:
        return "Install icalendar: pip install icalendar"
    except Exception as e:
        return f"Error creating event: {e}"


@skill(
    name="caldav_delete_event",
    description="Delete a calendar event from a CalDAV account by title (best-effort match).",
    parameters={
        "title":   {"type": "string", "description": "Title or partial title of event to delete"},
        "date":    {"type": "string", "default": "", "description": "Date hint YYYY-MM-DD"},
        "account": {"type": "string", "default": ""},
    },
    sensitive=True,
    requires=[],
)
def caldav_delete_event(title: str, date: str = "", account: str = "") -> str:
    """Delete a CalDAV event by title."""
    _, principal = _caldav_client(account)
    if principal is None:
        return "No CalDAV account connected."

    try:
        now = datetime.now(timezone.utc)
        search_start = datetime.fromisoformat(date).replace(tzinfo=timezone.utc) if date else now
        search_end = search_start + timedelta(days=30)

        for cal in principal.calendars():
            try:
                events = cal.date_search(start=search_start, end=search_end, expand=True)
                for e in events:
                    vevent = e.vobject_instance.vevent
                    evt_title = str(getattr(vevent.summary, "value", ""))
                    if title.lower() in evt_title.lower():
                        e.delete()
                        return f"✅ Deleted '{evt_title}' from CalDAV calendar."
            except Exception:
                pass

        return f"No event matching '{title}' found in the next 30 days."
    except Exception as e:
        return f"Error deleting event: {e}"
