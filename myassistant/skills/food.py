"""Food ordering & local commerce.

Most major delivery apps (DoorDash, UberEats) don't expose a public ordering
API. Our strategy:

1. `find_food` uses Yelp/Maps to discover places (no auth issues).
2. `order_food` queues a browser-automation job that a logged-in Playwright
   worker on the desktop completes (the worker holds the user's session
   cookies for doordash.com/ubereats.com). Always confirms first.
"""
from __future__ import annotations

import json
import time

from myassistant.core.config import settings
from myassistant.core.registry import skill
from myassistant.skills.maps import find_nearby


@skill(
    name="find_food",
    description="Find restaurants near a location, optionally filtered by cuisine.",
)
def find_food(near: str, cuisine: str = "") -> str:
    q = f"{cuisine} restaurant".strip() if cuisine else "restaurant"
    return find_nearby(query=q, location=near, radius_meters=4000)


@skill(
    name="order_food",
    description=("Place a food order on DoorDash/UberEats via browser automation. "
                 "Always confirm full order with user (items, restaurant, address, total est.) before calling."),
    sensitive=True,
)
def order_food(platform: str, restaurant: str, items: list, delivery_address: str,
               notes: str = "") -> str:
    q = settings.myassistant_data_dir / "order_queue"
    q.mkdir(exist_ok=True)
    job = {
        "platform": platform.lower(),
        "restaurant": restaurant,
        "items": items,
        "delivery_address": delivery_address,
        "notes": notes,
        "ts": time.time(),
    }
    p = q / f"{int(time.time()*1000)}.json"
    p.write_text(json.dumps(job, indent=2))
    return (f"queued {platform} order: {len(items)} items from {restaurant}. "
            f"Job file: {p.name}. The browser-automation worker will execute it; "
            "you'll get a notification when it's placed.")
