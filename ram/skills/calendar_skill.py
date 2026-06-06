"""Google Calendar integration.

Stores a cached OAuth token in data/google_token.json after first auth.
First-run flow: agent will instruct the user to run `python -m ram.tools.google_auth`.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from loguru import logger

from ram.core.config import settings
from ram.core.registry import skill

SCOPES = ["https://www.googleapis.com/auth/calendar"]
_TOKEN_PATH = settings.ram_data_dir / "google_token.json"


def _service():
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        return None

    creds = None
    if _TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_info(json.loads(_TOKEN_PATH.read_text()), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            secrets = settings.google_oauth_client_secrets
            if not secrets or not Path(secrets).exists():
                return None
            flow = InstalledAppFlow.from_client_secrets_file(str(secrets), SCOPES)
            creds = flow.run_local_server(port=0)
        _TOKEN_PATH.write_text(creds.to_json())
    return build("calendar", "v3", credentials=creds)


@skill(name="calendar_today", description="Get the owner's schedule for today.")
def calendar_today() -> str:
    return _list_range(0)


@skill(name="calendar_day", description="Get the owner's schedule for a given date (YYYY-MM-DD).")
def calendar_day(date: str) -> str:
    target = dt.date.fromisoformat(date)
    delta = (target - dt.date.today()).days
    return _list_range(delta)


def _list_range(days_offset: int) -> str:
    svc = _service()
    if not svc:
        return "ERROR: Google Calendar not connected. Run `python -m ram.tools.google_auth`."
    d = dt.date.today() + dt.timedelta(days=days_offset)
    start = dt.datetime.combine(d, dt.time.min).isoformat() + "Z"
    end = dt.datetime.combine(d, dt.time.max).isoformat() + "Z"
    res = svc.events().list(calendarId="primary", timeMin=start, timeMax=end,
                            singleEvents=True, orderBy="startTime").execute()
    events = res.get("items", [])
    if not events:
        return f"no events on {d.isoformat()}"
    out = [f"Schedule for {d.isoformat()}:"]
    for e in events:
        s = e["start"].get("dateTime", e["start"].get("date"))
        out.append(f"- {s[11:16] if 'T' in s else 'all day'} — {e.get('summary','(no title)')}")
    return "\n".join(out)


@skill(
    name="schedule_event",
    description=("Create a calendar event. Always confirm with the user before calling. "
                 "Times are ISO 8601 in the owner's timezone."),
    sensitive=True,
)
def schedule_event(title: str, start_iso: str, end_iso: str, attendees_emails: list = None,
                   description: str = "") -> str:
    svc = _service()
    if not svc:
        return "ERROR: Google Calendar not connected."
    body = {
        "summary": title,
        "description": description,
        "start": {"dateTime": start_iso, "timeZone": settings.ram_timezone},
        "end": {"dateTime": end_iso, "timeZone": settings.ram_timezone},
    }
    if attendees_emails:
        body["attendees"] = [{"email": a} for a in attendees_emails]
    e = svc.events().insert(calendarId="primary", body=body, sendUpdates="all").execute()
    return f"created: {e.get('htmlLink')}"


@skill(
    name="find_free_slot",
    description="Find a free 30-minute slot on a given date (YYYY-MM-DD) between 9am-6pm.",
)
def find_free_slot(date: str, duration_minutes: int = 30) -> str:
    svc = _service()
    if not svc:
        return "ERROR: Google Calendar not connected."
    d = dt.date.fromisoformat(date)
    start = dt.datetime.combine(d, dt.time(9, 0))
    end = dt.datetime.combine(d, dt.time(18, 0))
    fb = svc.freebusy().query(body={
        "timeMin": start.isoformat() + "Z", "timeMax": end.isoformat() + "Z",
        "items": [{"id": "primary"}],
    }).execute()
    busy = fb["calendars"]["primary"]["busy"]
    cursor = start
    delta = dt.timedelta(minutes=duration_minutes)
    for b in busy:
        bs = dt.datetime.fromisoformat(b["start"].replace("Z", ""))
        if cursor + delta <= bs:
            return f"free: {cursor.strftime('%H:%M')}–{(cursor+delta).strftime('%H:%M')}"
        cursor = max(cursor, dt.datetime.fromisoformat(b["end"].replace("Z", "")))
    if cursor + delta <= end:
        return f"free: {cursor.strftime('%H:%M')}–{(cursor+delta).strftime('%H:%M')}"
    return "no free slot today in business hours"
