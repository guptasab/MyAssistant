"""Travel: flight watcher, TripIt import, packing list, currency."""
from __future__ import annotations

import time

import httpx
from sqlalchemy import Column, Integer, String, Float

from myassistant.core.config import settings
from myassistant.core.memory import Base, db, _engine
from myassistant.core.registry import skill


class FlightWatch(Base):
    __tablename__ = "flight_watches"
    id = Column(Integer, primary_key=True)
    flight_number = Column(String, index=True)
    date = Column(String)
    last_status = Column(String, default="")
    last_check_ts = Column(Float, default=0)


Base.metadata.create_all(_engine)


@skill(name="watch_flight",
       description="Add a flight to the watch list (ex: AA100 2025-01-15). Ollie polls and texts on changes.")
def watch_flight(flight_number: str, date: str) -> str:
    with db() as s:
        s.add(FlightWatch(flight_number=flight_number.upper(), date=date))
    return f"watching {flight_number} on {date}"


@skill(name="flight_status",
       description="Get current flight status via aviationstack.",
       requires=["aviationstack_key"])
def flight_status(flight_number: str) -> str:
    r = httpx.get("https://api.aviationstack.com/v1/flights",
                  params={"access_key": settings.aviationstack_key,
                          "flight_iata": flight_number}, timeout=15)
    if r.status_code >= 300:
        return f"ERROR: {r.status_code}"
    data = r.json().get("data", [])
    if not data:
        return "no flight found"
    f = data[0]
    return (f"{f['flight']['iata']} {f['flight_status']}: "
            f"{f['departure']['airport']} → {f['arrival']['airport']} "
            f"(scheduled {f['departure']['scheduled']})")


@skill(name="auto_pack",
       description=("Generate a packing list for a trip given destination + days + activities. "
                    "Uses LLM for context-aware suggestions."))
def auto_pack(destination: str, days: int, activities: str = "general") -> str:
    try:
        from myassistant.core.llm import llm_chat
        return llm_chat([{"role": "user", "content": (
            f"Pack list for {days} days in {destination} ({activities}). "
            f"Be practical, group by category. Plain bullets."
        )}], task="draft", max_tokens=500)
    except Exception as e:
        return f"ERROR: {e}"


@skill(name="currency_convert",
       description="Convert amount from one currency to another via open.er-api.")
def currency_convert(amount: float, from_currency: str, to_currency: str) -> str:
    r = httpx.get(f"https://open.er-api.com/v6/latest/{from_currency.upper()}", timeout=10)
    if r.status_code >= 300:
        return f"ERROR: {r.status_code}"
    rates = r.json().get("rates", {})
    rate = rates.get(to_currency.upper())
    if not rate:
        return f"unknown currency {to_currency}"
    return f"{amount} {from_currency.upper()} = {amount * rate:.2f} {to_currency.upper()}"


@skill(name="tripit_import",
       description=("Import a TripIt .ics URL, parse and add events to calendar. Pass URL."),
       sensitive=True)
def tripit_import(ics_url: str) -> str:
    try:
        import icalendar
    except ImportError:
        return "ERROR: install icalendar"
    r = httpx.get(ics_url, timeout=15)
    if r.status_code >= 300:
        return f"ERROR: {r.status_code}"
    cal = icalendar.Calendar.from_ical(r.content)
    count = 0
    for comp in cal.walk():
        if comp.name == "VEVENT":
            count += 1
    return f"parsed {count} trip events (calendar.create not yet wired)"
