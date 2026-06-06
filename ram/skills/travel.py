"""Trips + wishlist. Packing lists are reused from todo_lists (kind='packing')."""
from __future__ import annotations

from datetime import date

from ram.core import contexts as ctx
from ram.core.memory import db
from ram.core.registry import skill


@skill(
    name="create_trip",
    description=("Add a trip. dates are YYYY-MM-DD. context defaults to family. "
                 "Confirmation numbers can be a free-text dump (flight, hotel, car)."),
)
def create_trip(name: str, destination: str = "", start_date: str = "",
                end_date: str = "", context: str = "family",
                itinerary: str = "", confirmation_numbers: str = "",
                notes: str = "") -> str:
    cid = ctx.resolve_context_id(context)
    with db() as s:
        t = ctx.Trip(context_id=cid, name=name, destination=destination,
                     start_date=start_date, end_date=end_date,
                     itinerary=itinerary, confirmation_numbers=confirmation_numbers,
                     notes=notes)
        s.add(t)
        s.flush()
        tid = t.id
    return f"✈️ trip #{tid} '{name}' → {destination} ({start_date} → {end_date})"


@skill(
    name="upcoming_trips",
    description="List upcoming trips (start_date >= today).",
)
def upcoming_trips() -> str:
    today = date.today().isoformat()
    with db() as s:
        rows = (
            s.query(ctx.Trip)
            .filter(ctx.Trip.start_date >= today)
            .order_by(ctx.Trip.start_date)
            .all()
        )
    if not rows:
        return "no upcoming trips"
    return "\n".join(
        f"✈️ {r.start_date} → {r.end_date} · {r.name} ({r.destination})"
        for r in rows
    )


@skill(
    name="trip_details",
    description="Show full details (itinerary, confirmation numbers, notes) for a trip by id.",
)
def trip_details(trip_id: int) -> str:
    with db() as s:
        t = s.query(ctx.Trip).filter(ctx.Trip.id == trip_id).one_or_none()
        if not t:
            return f"no trip #{trip_id}"
        parts = [f"✈️ {t.name} → {t.destination}", f"   {t.start_date} → {t.end_date}"]
        if t.confirmation_numbers:
            parts.append(f"\nConfirmations:\n{t.confirmation_numbers}")
        if t.itinerary:
            parts.append(f"\nItinerary:\n{t.itinerary}")
        if t.notes:
            parts.append(f"\nNotes:\n{t.notes}")
        return "\n".join(parts)


# ---- wishlist ----

@skill(
    name="add_wishlist",
    description=("Add an item to a wishlist. for_person is the recipient (yourself by "
                 "default). occasion is birthday/anniversary/etc."),
)
def add_wishlist(name: str, url: str = "", price: float = 0.0,
                 for_person: str = "", occasion: str = "", priority: str = "med",
                 context: str = "personal") -> str:
    cid = ctx.resolve_context_id(context)
    with db() as s:
        w = ctx.WishlistItem(context_id=cid, name=name, url=url, price=price,
                             for_person=for_person, occasion=occasion,
                             priority=priority)
        s.add(w)
        s.flush()
        wid = w.id
    return f"🎁 #{wid} {name}" + (f" for {for_person}" if for_person else "")


@skill(
    name="show_wishlist",
    description="Show the wishlist. Filter optional: for_person, occasion, context.",
)
def show_wishlist(for_person: str = "", occasion: str = "", context: str = "") -> str:
    with db() as s:
        q = s.query(ctx.WishlistItem).filter(ctx.WishlistItem.bought == False)
        if context:
            q = q.filter(ctx.WishlistItem.context_id == ctx.resolve_context_id(context))
        if for_person:
            q = q.filter(ctx.WishlistItem.for_person == for_person)
        if occasion:
            q = q.filter(ctx.WishlistItem.occasion == occasion)
        rows = q.all()
    if not rows:
        return "wishlist is empty"
    out = []
    for w in rows:
        price = f" — ${w.price:.0f}" if w.price else ""
        who = f" → {w.for_person}" if w.for_person else ""
        occ = f" ({w.occasion})" if w.occasion else ""
        out.append(f"  #{w.id} {w.name}{price}{who}{occ}")
    return "\n".join(out)


@skill(
    name="mark_wishlist_bought",
    description="Mark a wishlist item as bought.",
)
def mark_wishlist_bought(item_id: int) -> str:
    with db() as s:
        w = s.query(ctx.WishlistItem).filter(ctx.WishlistItem.id == item_id).one_or_none()
        if not w:
            return f"no wishlist item #{item_id}"
        w.bought = True
    return f"✓ #{item_id} bought"
