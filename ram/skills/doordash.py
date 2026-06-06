"""DoorDash helper — drafts a deep-link order from a restaurant + items."""
from __future__ import annotations

from urllib.parse import quote

from ram.core.registry import skill


@skill(
    name="doordash_draft_order",
    description=("Compose a DoorDash search URL for a restaurant + items the family wants. "
                 "User taps to open and complete the order."),
)
def doordash_draft_order(restaurant: str, items_csv: str = "") -> str:
    q = quote(restaurant)
    base = f"https://www.doordash.com/search/store/{q}/"
    notes = f" (asking for: {items_csv})" if items_csv else ""
    return f"DoorDash → {base}{notes}"
