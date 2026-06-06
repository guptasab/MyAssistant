"""Multi-calendar merge + smart scheduling + auto-RSVP + drive-time."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ram.core.registry import skill


def _calendar_events(days: int = 7) -> list[dict]:
    try:
        from ram.skills.calendar_skill import _service  # existing
    except Exception:
        return []
    try:
        svc = _service()
        if not svc:
            return []
        from datetime import timezone
        now = datetime.now(timezone.utc).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
        cals = svc.calendarList().list().execute().get("items", [])
        all_evts = []
        for c in cals:
            try:
                evts = svc.events().list(calendarId=c["id"], timeMin=now, timeMax=end,
                                         singleEvents=True, orderBy="startTime").execute()
                for e in evts.get("items", []):
                    e["_calendar"] = c.get("summary", "?")
                    all_evts.append(e)
            except Exception:
                continue
        return all_evts
    except Exception:
        return []


@skill(name="all_calendars_today",
       description="List events from ALL connected Google calendars for today/this week.")
def all_calendars_today(days: int = 1) -> str:
    evts = _calendar_events(days=days)
    if not evts:
        return "(no events or calendar not connected)"
    out = []
    for e in evts[:30]:
        start = e.get("start", {}).get("dateTime", e.get("start", {}).get("date", "?"))[:16]
        out.append(f"{start}  [{e.get('_calendar','?')[:10]}]  {e.get('summary','(no title)')}")
    return "\n".join(out)


@skill(name="find_free_slot",
       description=("Find first free 30-60 min window across all calendars in next N days, "
                    "respecting work_hours and avoiding evenings/weekends if asked."),
)
def find_free_slot(duration_minutes: int = 30, days: int = 5,
                   start_hour: int = 9, end_hour: int = 17) -> str:
    evts = _calendar_events(days=days)
    busy: list[tuple[datetime, datetime]] = []
    for e in evts:
        try:
            s = e.get("start", {}).get("dateTime")
            t = e.get("end", {}).get("dateTime")
            if s and t:
                busy.append((datetime.fromisoformat(s.replace("Z", "+00:00")),
                             datetime.fromisoformat(t.replace("Z", "+00:00"))))
        except Exception:
            continue
    busy.sort()
    cursor = datetime.now().replace(microsecond=0)
    for _ in range(days * 24):
        if cursor.hour < start_hour:
            cursor = cursor.replace(hour=start_hour, minute=0)
        if cursor.hour >= end_hour:
            cursor = (cursor + timedelta(days=1)).replace(hour=start_hour, minute=0)
            continue
        if cursor.weekday() >= 5:
            cursor = (cursor + timedelta(days=1)).replace(hour=start_hour, minute=0)
            continue
        slot_end = cursor + timedelta(minutes=duration_minutes)
        conflict = any(s < slot_end and cursor < e for s, e in busy)
        if not conflict:
            return f"first free: {cursor.strftime('%a %m/%d %H:%M')}–{slot_end.strftime('%H:%M')}"
        cursor += timedelta(minutes=15)
    return "no free slot found"


@skill(name="drive_time_to",
       description="Estimate drive time from home to an address using Google Maps.",
       requires=["google_maps_api_key"])
def drive_time_to(destination: str) -> str:
    import httpx
    from ram.core.config import settings
    home = "Home"  # could pull from facts
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    r = httpx.get(url, params={"origins": home, "destinations": destination,
                                "key": settings.google_maps_api_key}, timeout=10)
    if r.status_code >= 300:
        return f"ERROR: {r.status_code}"
    rows = r.json().get("rows", [])
    if not rows or not rows[0].get("elements"):
        return "no route"
    e = rows[0]["elements"][0]
    return f"{destination}: {e.get('duration', {}).get('text', '?')} ({e.get('distance', {}).get('text', '?')})"


@skill(name="auto_rsvp",
       description=("Auto-RSVP to a calendar invite by event id. response: 'accepted' | "
                    "'tentative' | 'declined'."),
       sensitive=True)
def auto_rsvp(event_id: str, response: str = "accepted", calendar_id: str = "primary") -> str:
    try:
        from ram.skills.calendar_skill import _service
        svc = _service()
        if not svc:
            return "ERROR: calendar not connected"
        evt = svc.events().get(calendarId=calendar_id, eventId=event_id).execute()
        for a in evt.get("attendees", []):
            if a.get("self"):
                a["responseStatus"] = response
        svc.events().update(calendarId=calendar_id, eventId=event_id, body=evt,
                            sendUpdates="all").execute()
        return f"RSVP {response} for {evt.get('summary','?')}"
    except Exception as e:
        return f"ERROR: {e}"
