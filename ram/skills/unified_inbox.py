"""Unified inbox — aggregates email from ALL connected accounts in one view.

This is the primary email skill the agent calls when the user asks about
"my email", "what's in my inbox", or "any important messages?". It pulls
from every connected account (Gmail, Outlook, IMAP) and presents a
single prioritised view.

Priority tiers:
  🔴 URGENT    — keyword or sender matches a known VIP, deadline < 24h
  🟡 ACTION    — classified as requiring a reply or action
  📬 FYI       — informational, no action needed
  🔇 NOISE     — newsletters, receipts, promos (suppressed by default)
"""
from __future__ import annotations

from loguru import logger

from ram.core.registry import skill
from ram.core.accounts import list_accounts


def _get_all_emails(max_per_account: int = 20, unread_only: bool = True) -> list[dict]:
    """Pull unread messages from every connected account.

    Returns a flat list of message dicts with unified fields:
      source, account, date, sender, subject, snippet, raw_body (truncated)
    """
    messages: list[dict] = []

    # ── Gmail accounts ────────────────────────────────────────────────────
    for acct in list_accounts(kind="gmail"):
        try:
            from ram.core.accounts import gmail_service_for
            from ram.skills.gmail_skill import _headers, _decode_body
            svc = gmail_service_for(acct.email)
            if not svc:
                continue
            q = "is:unread -category:promotions -category:social" if unread_only else ""
            res = svc.users().messages().list(userId="me", q=q, maxResults=max_per_account).execute()
            for item in res.get("messages", []):
                try:
                    m = svc.users().messages().get(
                        userId="me", id=item["id"], format="full"
                    ).execute()
                    hdrs = _headers(m)
                    body = _decode_body(m.get("payload", {}))
                    messages.append({
                        "source":   "gmail",
                        "account":  acct.email,
                        "id":       item["id"],
                        "date":     hdrs.get("Date", "")[:10],
                        "sender":   hdrs.get("From", ""),
                        "subject":  hdrs.get("Subject", "(no subject)"),
                        "snippet":  m.get("snippet", ""),
                        "raw_body": body[:1500],
                    })
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Unified inbox Gmail {acct.email}: {e}")

    # ── Outlook accounts ──────────────────────────────────────────────────
    for acct in list_accounts(kind="outlook"):
        try:
            from ram.core.accounts import graph_client_for
            client = graph_client_for(acct.email)
            if not client:
                continue
            import re
            params: dict = {"$top": max_per_account, "$orderby": "receivedDateTime desc",
                            "$select": "subject,from,receivedDateTime,bodyPreview,isRead"}
            if unread_only:
                params["$filter"] = "isRead eq false"
            r = client.get("https://graph.microsoft.com/v1.0/me/messages", params=params, timeout=20)
            r.raise_for_status()
            for m in r.json().get("value", []):
                messages.append({
                    "source":   "outlook",
                    "account":  acct.email,
                    "id":       m.get("id", ""),
                    "date":     m.get("receivedDateTime", "")[:10],
                    "sender":   m.get("from", {}).get("emailAddress", {}).get("address", ""),
                    "subject":  m.get("subject", "(no subject)"),
                    "snippet":  m.get("bodyPreview", ""),
                    "raw_body": m.get("bodyPreview", ""),
                })
        except Exception as e:
            logger.debug(f"Unified inbox Outlook {acct.email}: {e}")

    # ── IMAP accounts ─────────────────────────────────────────────────────
    for acct in list_accounts(kind="imap"):
        try:
            from ram.skills.imap_skill import _imap_connect, _decode_msg
            conn = _imap_connect(acct.email)
            if not conn:
                continue
            conn.select("INBOX")
            criteria = "(UNSEEN)" if unread_only else "ALL"
            _, data = conn.search(None, criteria)
            ids = data[0].split()[-max_per_account:]
            for uid in reversed(ids):
                try:
                    _, raw = conn.fetch(uid, "(RFC822)")
                    parsed = _decode_msg(raw[0][1])
                    messages.append({
                        "source":   "imap",
                        "account":  acct.email,
                        "id":       uid.decode(),
                        "date":     parsed["date"][:10],
                        "sender":   parsed["from"],
                        "subject":  parsed["subject"],
                        "snippet":  parsed["body"][:200],
                        "raw_body": parsed["body"][:1500],
                    })
                except Exception:
                    pass
            conn.logout()
        except Exception as e:
            logger.debug(f"Unified inbox IMAP {acct.email}: {e}")

    return messages


@skill(
    name="unified_inbox",
    description=(
        "Show a unified view of all email accounts (Gmail, Outlook, iCloud, etc.). "
        "Triages by priority. Use for 'check my email', 'any important messages?', "
        "'what's in my inbox?'."
    ),
    parameters={
        "unread_only": {"type": "boolean", "default": True},
        "show_noise":  {"type": "boolean", "default": False},
        "max_per_account": {"type": "integer", "default": 15},
    },
    requires=[],
)
def unified_inbox(unread_only: bool = True, show_noise: bool = False,
                   max_per_account: int = 15) -> str:
    """Aggregate and triage all email accounts."""
    accounts = list_accounts()
    if not accounts:
        return (
            "No email accounts connected yet.\n"
            "Connect accounts in Settings → Channels, or say "
            "'connect my Gmail / Outlook / iCloud'."
        )

    messages = _get_all_emails(max_per_account=max_per_account, unread_only=unread_only)
    if not messages:
        return f"✅ No {'unread ' if unread_only else ''}messages across {len(accounts)} accounts."

    # Triage using LLM (batch to avoid too many calls)
    from ram.core.llm import llm_classify

    _PROMPT = """Classify this email in one JSON object:
{{"priority": "urgent"|"action"|"fyi"|"noise",
  "summary": "one short sentence of what is needed",
  "deadline": "YYYY-MM-DD or empty"}}

From: {sender}
Subject: {subject}
Snippet: {snippet}"""

    buckets: dict[str, list] = {"urgent": [], "action": [], "fyi": [], "noise": []}

    for msg in messages[:40]:   # triage at most 40
        try:
            result = llm_classify(_PROMPT.format(
                sender=msg["sender"][:80],
                subject=msg["subject"][:100],
                snippet=msg["snippet"][:300],
            ))
            priority = result.get("priority", "fyi")
            summary  = result.get("summary", msg["subject"])
            deadline = result.get("deadline", "")
            msg["_priority"] = priority
            msg["_summary"]  = summary
            msg["_deadline"] = deadline
            buckets.setdefault(priority, []).append(msg)
        except Exception:
            msg["_priority"] = "fyi"
            msg["_summary"]  = msg["subject"]
            buckets["fyi"].append(msg)

    lines = [f"📬 Unified Inbox — {len(messages)} unread across {len(accounts)} accounts\n"]

    _ICONS = {"urgent": "🔴", "action": "🟡", "fyi": "📬", "noise": "🔇"}
    for bucket in ("urgent", "action", "fyi"):
        items = buckets.get(bucket, [])
        if not items:
            continue
        lines.append(f"\n{_ICONS[bucket]} {bucket.upper()} ({len(items)})")
        for m in items[:8]:
            acct_label = m["account"].split("@")[1].split(".")[0][:6]  # e.g. "gmail"
            deadline = f" ⏰ {m['_deadline']}" if m.get("_deadline") else ""
            lines.append(
                f"  [{acct_label}] {m['date']}  {m['sender'].split('<')[0][:20]:<20} "
                f"| {m['_summary'][:60]}{deadline}"
            )

    if show_noise and buckets.get("noise"):
        lines.append(f"\n🔇 NOISE ({len(buckets['noise'])}) — skipped")

    return "\n".join(lines)


@skill(
    name="list_connected_accounts",
    description="List all connected email and calendar accounts.",
    requires=[],
)
def list_connected_accounts() -> str:
    """Show every account currently connected to Ram."""
    accounts = list_accounts(enabled_only=False)
    if not accounts:
        return "No accounts connected. Say 'connect my Gmail' or open Settings → Channels."

    lines = ["Connected accounts:\n"]
    for a in accounts:
        icon = {"gmail": "📧", "outlook": "📨", "imap": "📬", "caldav": "📅"}.get(a.kind, "📌")
        status = "✓ enabled" if a.enabled else "✗ paused"
        primary = " (primary)" if a.primary else ""
        features = []
        if a.sync_email:    features.append("email")
        if a.sync_calendar: features.append("calendar")
        lines.append(
            f"  {icon} {a.email}{primary}  [{a.kind}]  {status}  "
            f"syncing: {', '.join(features) or 'none'}"
        )
    return "\n".join(lines)


@skill(
    name="unified_calendar",
    description=(
        "Show events from ALL connected calendars (Google, Outlook, CalDAV) in one view. "
        "Use for 'what's on my calendar', 'any meetings today?', 'my schedule this week'."
    ),
    parameters={
        "days": {"type": "integer", "default": 7},
    },
    requires=[],
)
def unified_calendar(days: int = 7) -> str:
    """Merge events from all calendar providers into a single timeline."""
    from datetime import datetime, timezone, timedelta

    all_events: list[dict] = []
    now = datetime.now(timezone.utc)

    # ── Google Calendar ───────────────────────────────────────────────────
    for acct in list_accounts(kind="gmail"):
        try:
            from ram.core.accounts import calendar_service_for
            svc = calendar_service_for(acct.email)
            if not svc:
                continue
            end = (now + timedelta(days=days)).isoformat()
            cals = svc.calendarList().list().execute().get("items", [])
            for cal in cals:
                evts = svc.events().list(
                    calendarId=cal["id"], timeMin=now.isoformat(), timeMax=end,
                    singleEvents=True, orderBy="startTime"
                ).execute().get("items", [])
                for e in evts:
                    start = e.get("start", {}).get("dateTime", e.get("start", {}).get("date", ""))
                    all_events.append({
                        "start":    start[:16].replace("T", " "),
                        "title":    e.get("summary", "(no title)"),
                        "source":   f"Google/{acct.email.split('@')[0]}",
                        "location": e.get("location", ""),
                        "url":      e.get("htmlLink", ""),
                    })
        except Exception as e:
            logger.debug(f"Google Calendar {acct.email}: {e}")

    # ── Outlook Calendar ──────────────────────────────────────────────────
    for acct in list_accounts(kind="outlook"):
        try:
            from ram.core.accounts import graph_client_for
            client = graph_client_for(acct.email)
            if not client:
                continue
            end = (now + timedelta(days=days)).isoformat()
            r = client.get(
                "https://graph.microsoft.com/v1.0/me/calendarView",
                params={"startDateTime": now.isoformat(), "endDateTime": end,
                        "$orderby": "start/dateTime", "$top": 50,
                        "$select": "subject,start,location"},
                timeout=20,
            )
            r.raise_for_status()
            for e in r.json().get("value", []):
                start = e.get("start", {}).get("dateTime", "")[:16].replace("T", " ")
                all_events.append({
                    "start":    start,
                    "title":    e.get("subject", "(no title)"),
                    "source":   f"Outlook/{acct.email.split('@')[0]}",
                    "location": e.get("location", {}).get("displayName", ""),
                    "url":      "",
                })
        except Exception as e:
            logger.debug(f"Outlook Calendar {acct.email}: {e}")

    if not all_events:
        return f"No calendar events found in the next {days} days across all accounts."

    all_events.sort(key=lambda e: e["start"])
    lines = [f"📅 Unified Calendar — next {days} days\n"]
    for e in all_events[:50]:
        loc = f" @ {e['location'][:30]}" if e["location"] else ""
        lines.append(f"  {e['start']}  [{e['source']}]  {e['title']}{loc}")

    return "\n".join(lines)
