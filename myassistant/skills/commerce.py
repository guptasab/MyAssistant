"""Price tracker, returns radar, service finder."""
from __future__ import annotations

import time

import httpx
from sqlalchemy import Column, Integer, String, Float

from myassistant.core.memory import Base, db, _engine
from myassistant.core.registry import skill


class PriceWatch(Base):
    __tablename__ = "price_watches"
    id = Column(Integer, primary_key=True)
    url = Column(String)
    selector = Column(String, default="")
    target_price = Column(Float, default=0)
    last_price = Column(Float, default=0)
    last_check_ts = Column(Float, default=0)
    created_ts = Column(Float, default=time.time)


class ReturnReminder(Base):
    __tablename__ = "return_reminders"
    id = Column(Integer, primary_key=True)
    item = Column(String)
    purchased_at = Column(String)
    return_by = Column(String, index=True)
    notes = Column(String, default="")


Base.metadata.create_all(_engine)


@skill(name="watch_price",
       description=("Watch a product URL for price drops. Optionally pass CSS selector + target_price."))
def watch_price(url: str, selector: str = "", target_price: float = 0) -> str:
    with db() as s:
        w = PriceWatch(url=url, selector=selector, target_price=target_price)
        s.add(w); s.flush()
        return f"watching #{w.id}"


@skill(name="check_prices",
       description="Re-fetch all watched URLs and report any below target_price.")
def check_prices() -> str:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return "ERROR: install beautifulsoup4"
    out = []
    with db() as s:
        rows = s.query(PriceWatch).all()
    for w in rows:
        try:
            r = httpx.get(w.url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(r.text, "html.parser")
            text = soup.select_one(w.selector).text if w.selector else soup.text
            import re
            m = re.search(r"\$\s*(\d{1,5}(?:[.,]\d{2})?)", text)
            if m:
                price = float(m.group(1).replace(",", ""))
                with db() as s2:
                    obj = s2.query(PriceWatch).filter(PriceWatch.id == w.id).first()
                    obj.last_price = price; obj.last_check_ts = time.time()
                if not w.target_price or price <= w.target_price:
                    out.append(f"#{w.id} ${price:.2f}  {w.url[:60]}")
        except Exception as e:
            out.append(f"#{w.id} ERROR {e}")
    return "\n".join(out) or "no drops"


@skill(name="add_return",
       description="Track a return-by date for an item.")
def add_return(item: str, return_by: str, purchased_at: str = "", notes: str = "") -> str:
    with db() as s:
        s.add(ReturnReminder(item=item, return_by=return_by, purchased_at=purchased_at, notes=notes))
    return f"return reminder set: {item} by {return_by}"


@skill(name="upcoming_returns",
       description="List returns due in the next N days.")
def upcoming_returns(days: int = 14) -> str:
    from datetime import datetime, timedelta
    cutoff = datetime.now() + timedelta(days=days)
    with db() as s:
        rows = s.query(ReturnReminder).all()
    out = []
    for r in rows:
        try:
            d = datetime.fromisoformat(r.return_by[:10])
            if d <= cutoff:
                out.append(f"{r.return_by}  {r.item}  ({r.purchased_at})")
        except Exception:
            continue
    return "\n".join(sorted(out)) or "(none)"


@skill(name="find_service",
       description=("Find local businesses by category (plumber, dog walker, dentist) "
                    "via Google Places."),
       requires=["google_maps_api_key"])
def find_service(query: str, location: str = "") -> str:
    from myassistant.core.config import settings
    r = httpx.get("https://maps.googleapis.com/maps/api/place/textsearch/json",
                  params={"query": f"{query} near {location}".strip(),
                          "key": settings.google_maps_api_key}, timeout=10)
    if r.status_code >= 300:
        return f"ERROR: {r.status_code}"
    out = []
    for p in r.json().get("results", [])[:10]:
        out.append(f"{p.get('name','?')} ⭐{p.get('rating','?')}  {p.get('formatted_address','')[:60]}")
    return "\n".join(out) or "(none)"
