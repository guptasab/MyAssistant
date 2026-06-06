"""Microsoft Outlook email and calendar via Microsoft Graph API.

Supports personal Microsoft accounts (Hotmail, Outlook.com) and
work/school Microsoft 365 accounts (Office 365, Exchange Online).

Setup:
  1. Register an app at https://portal.azure.com → Azure Active Directory → App registrations
  2. Add the following delegated permissions:
       Mail.Read, Mail.Send, Mail.ReadWrite,
       Calendars.ReadWrite, User.Read, offline_access
  3. Set these in your .env:
       MICROSOFT_CLIENT_ID=<your-app-client-id>
       MICROSOFT_CLIENT_SECRET=<your-app-client-secret>
       MICROSOFT_TENANT_ID=common   # or your specific tenant for work accounts
  4. Connect an account from the admin UI or say "connect my Outlook"

Each email account is stored in ram.core.accounts and is accessed via
Microsoft Graph (https://graph.microsoft.com/v1.0).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

from loguru import logger

from ram.core.registry import skill
from ram.core.config import settings


_GRAPH = "https://graph.microsoft.com/v1.0"


def _get_client(email: str | None = None):
    """Return a Graph API client for the given Outlook account.

    Args:
        email: Outlook account email. If None, uses the first connected Outlook account.

    Returns:
        Authenticated requests.Session, or None if no account is connected.
    """
    from ram.core.accounts import list_accounts, graph_client_for
    if email:
        return graph_client_for(email)
    accounts = list_accounts(kind="outlook")
    if not accounts:
        return None
    return graph_client_for(accounts[0].email)


def _all_clients():
    """Yield (email, client) for every connected, enabled Outlook account."""
    from ram.core.accounts import list_accounts, graph_client_for
    for acct in list_accounts(kind="outlook"):
        client = graph_client_for(acct.email)
        if client:
            yield acct.email, client


# ── Email skills ──────────────────────────────────────────────────────────

@skill(
    name="outlook_list_messages",
    description=(
        "List recent messages from an Outlook / Office 365 inbox. "
        "Use for 'check my Outlook', 'what's in my work email', etc."
    ),
    parameters={
        "account":     {"type": "string", "default": "", "description": "Email address of the account (optional)"},
        "folder":      {"type": "string", "default": "inbox", "description": "Folder name: inbox, sent, drafts, junk"},
        "max_results": {"type": "integer", "default": 15},
        "unread_only": {"type": "boolean", "default": True},
    },
    requires=["microsoft_client_id"],
)
def outlook_list_messages(account: str = "", folder: str = "inbox",
                           max_results: int = 15, unread_only: bool = True) -> str:
    """List messages from an Outlook inbox."""
    client = _get_client(account or None)
    if not client:
        return "Outlook not connected. Go to Settings → Channels → connect Microsoft account."

    params: dict = {"$top": max_results, "$orderby": "receivedDateTime desc",
                    "$select": "subject,from,receivedDateTime,isRead,bodyPreview"}
    if unread_only:
        params["$filter"] = "isRead eq false"

    try:
        r = client.get(f"{_GRAPH}/me/mailFolders/{folder}/messages", params=params, timeout=20)
        r.raise_for_status()
        msgs = r.json().get("value", [])
    except Exception as e:
        return f"ERROR: {e}"

    if not msgs:
        return f"No {'unread ' if unread_only else ''}messages in {folder}."

    lines = []
    for m in msgs:
        dt_str = m.get("receivedDateTime", "")[:10]
        sender  = m.get("from", {}).get("emailAddress", {}).get("address", "?")
        subject = m.get("subject", "(no subject)")[:60]
        unread  = "●" if not m.get("isRead") else " "
        lines.append(f"{unread} {dt_str} {sender:<28} {subject}")
    return f"Outlook {folder} ({account or 'default'}):\n" + "\n".join(lines)


@skill(
    name="outlook_read_message",
    description="Read the full body of a specific Outlook message by subject keyword.",
    parameters={
        "subject_keyword": {"type": "string"},
        "account":         {"type": "string", "default": ""},
    },
    requires=["microsoft_client_id"],
)
def outlook_read_message(subject_keyword: str, account: str = "") -> str:
    """Read an Outlook email that matches a subject keyword."""
    client = _get_client(account or None)
    if not client:
        return "Outlook not connected."
    try:
        r = client.get(
            f"{_GRAPH}/me/messages",
            params={
                "$filter": f"contains(subject, '{subject_keyword}')",
                "$top": 3,
                "$select": "subject,from,receivedDateTime,body",
            },
            timeout=20,
        )
        r.raise_for_status()
        msgs = r.json().get("value", [])
    except Exception as e:
        return f"ERROR: {e}"

    if not msgs:
        return f"No messages matching '{subject_keyword}'"

    m = msgs[0]
    body = m.get("body", {}).get("content", "")
    # Strip HTML tags for plain display
    import re
    body_plain = re.sub(r"<[^>]+>", " ", body).strip()[:2000]
    return (f"From: {m.get('from',{}).get('emailAddress',{}).get('address','?')}\n"
            f"Subject: {m.get('subject','')}\n"
            f"Date: {m.get('receivedDateTime','')[:16]}\n\n{body_plain}")


@skill(
    name="outlook_send_email",
    description="Send an email from an Outlook / Office 365 account.",
    parameters={
        "to":      {"type": "string"},
        "subject": {"type": "string"},
        "body":    {"type": "string"},
        "account": {"type": "string", "default": ""},
        "dry_run": {"type": "boolean", "default": False},
    },
    requires=["microsoft_client_id"],
    sensitive=True,
)
def outlook_send_email(to: str, subject: str, body: str,
                        account: str = "", dry_run: bool = False) -> str:
    """Send an email via Outlook."""
    if dry_run:
        return f"DRY RUN: Would send Outlook email to {to}\nSubject: {subject}\n\n{body[:200]}"
    client = _get_client(account or None)
    if not client:
        return "Outlook not connected."
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": addr.strip()}}
                             for addr in to.split(",")],
        },
        "saveToSentItems": True,
    }
    try:
        r = client.post(f"{_GRAPH}/me/sendMail", json=payload, timeout=30)
        r.raise_for_status()
        return f"✉️ Email sent to {to} via Outlook."
    except Exception as e:
        return f"ERROR: {e}"


# ── Calendar skills ───────────────────────────────────────────────────────

@skill(
    name="outlook_calendar_events",
    description="List upcoming events from Outlook Calendar / Office 365.",
    parameters={
        "days":    {"type": "integer", "default": 7},
        "account": {"type": "string", "default": ""},
    },
    requires=["microsoft_client_id"],
)
def outlook_calendar_events(days: int = 7, account: str = "") -> str:
    """List calendar events from Outlook over the next N days."""
    client = _get_client(account or None)
    if not client:
        return "Outlook Calendar not connected."

    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)

    try:
        r = client.get(
            f"{_GRAPH}/me/calendarView",
            params={
                "startDateTime": now.isoformat(),
                "endDateTime": end.isoformat(),
                "$orderby": "start/dateTime",
                "$top": 30,
                "$select": "subject,start,end,organizer,location,bodyPreview,isAllDay",
            },
            timeout=20,
        )
        r.raise_for_status()
        events = r.json().get("value", [])
    except Exception as e:
        return f"ERROR: {e}"

    if not events:
        return f"No events in Outlook Calendar over the next {days} days."

    lines = []
    for e in events:
        start  = e.get("start", {}).get("dateTime", "")[:16].replace("T", " ")
        title  = e.get("subject", "(no title)")[:50]
        org    = e.get("organizer", {}).get("emailAddress", {}).get("name", "")
        loc    = e.get("location", {}).get("displayName", "")
        suffix = f" @ {loc}" if loc else (f" by {org}" if org else "")
        lines.append(f"📅 {start}  {title}{suffix}")
    return "\n".join(lines)


@skill(
    name="outlook_create_event",
    description="Create a calendar event in Outlook Calendar.",
    parameters={
        "title":       {"type": "string"},
        "start":       {"type": "string", "description": "ISO datetime e.g. 2025-01-15T14:00:00"},
        "end":         {"type": "string", "description": "ISO datetime"},
        "attendees":   {"type": "string", "default": "", "description": "Comma-separated emails"},
        "location":    {"type": "string", "default": ""},
        "body":        {"type": "string", "default": ""},
        "account":     {"type": "string", "default": ""},
        "dry_run":     {"type": "boolean", "default": False},
    },
    requires=["microsoft_client_id"],
    sensitive=True,
)
def outlook_create_event(title: str, start: str, end: str,
                          attendees: str = "", location: str = "",
                          body: str = "", account: str = "", dry_run: bool = False) -> str:
    """Create an Outlook calendar event."""
    if dry_run:
        return f"DRY RUN: Would create event '{title}' on {start} in Outlook Calendar."
    client = _get_client(account or None)
    if not client:
        return "Outlook Calendar not connected."

    payload: dict = {
        "subject": title,
        "start": {"dateTime": start, "timeZone": settings.ram_timezone},
        "end":   {"dateTime": end,   "timeZone": settings.ram_timezone},
    }
    if location:
        payload["location"] = {"displayName": location}
    if body:
        payload["body"] = {"contentType": "Text", "content": body}
    if attendees:
        payload["attendees"] = [
            {"emailAddress": {"address": a.strip()}, "type": "required"}
            for a in attendees.split(",") if a.strip()
        ]
    try:
        r = client.post(f"{_GRAPH}/me/events", json=payload, timeout=20)
        r.raise_for_status()
        ev = r.json()
        return f"📅 Event '{title}' created at {start} (ID: {ev.get('id','')})"
    except Exception as e:
        return f"ERROR: {e}"


@skill(
    name="outlook_search_email",
    description="Search Outlook email using a keyword query.",
    parameters={
        "query":       {"type": "string"},
        "max_results": {"type": "integer", "default": 10},
        "account":     {"type": "string", "default": ""},
    },
    requires=["microsoft_client_id"],
)
def outlook_search_email(query: str, max_results: int = 10, account: str = "") -> str:
    """Search Outlook messages."""
    client = _get_client(account or None)
    if not client:
        return "Outlook not connected."
    try:
        r = client.get(
            f"{_GRAPH}/me/messages",
            params={
                "$search": f'"{query}"',
                "$top": max_results,
                "$select": "subject,from,receivedDateTime,bodyPreview",
            },
            timeout=20,
        )
        r.raise_for_status()
        msgs = r.json().get("value", [])
    except Exception as e:
        return f"ERROR: {e}"

    if not msgs:
        return f"No messages matching '{query}' in Outlook."
    lines = [f"{m.get('receivedDateTime','')[:10]}  {m.get('from',{}).get('emailAddress',{}).get('address','?'):<25}  {m.get('subject','')[:60]}"
             for m in msgs]
    return f"Outlook search '{query}':\n" + "\n".join(lines)
