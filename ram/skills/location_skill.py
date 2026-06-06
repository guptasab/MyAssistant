"""Location services — device GPS, IP geolocation, named places, and directions.

Location is foundational for any great personal assistant. Squire uses
location context for:
  - Nearby restaurant / service search
  - Weather at current location
  - Location-aware reminders ("remind me when I get home")
  - Travel time estimates
  - Smart home geofencing

Location resolution priority:
  1. Real-time device GPS (via mobile PWA WebSocket)
  2. Named location (home, work, custom saved places)
  3. IP geolocation (approximate, no API key needed)
  4. City from settings (fallback)
"""
from __future__ import annotations

import json
import time
from typing import Optional

from loguru import logger
from ram.core.registry import skill
from ram.core.config import settings
from ram.core.memory import db, save_fact, all_facts


# In-memory cache for last known location (updated by mobile PWA WebSocket)
_last_known: dict = {}


def update_location(lat: float, lon: float, accuracy: float = 0,
                    source: str = "gps") -> None:
    """Called by the mobile PWA WebSocket handler when GPS updates arrive.

    Args:
        lat:      Latitude in decimal degrees.
        lon:      Longitude in decimal degrees.
        accuracy: GPS accuracy in meters.
        source:   Where the location came from (gps / ip / manual).
    """
    global _last_known
    _last_known = {
        "lat": lat, "lon": lon,
        "accuracy": accuracy,
        "source": source,
        "ts": time.time(),
    }
    logger.debug(f"Location updated: {lat:.4f},{lon:.4f} ({source})")


def get_current_location() -> dict | None:
    """Get the most recent location, falling back through all resolution methods.

    Returns:
        Dict with lat, lon, display_name, source — or None if unavailable.
    """
    # 1. Real-time GPS (max 5 min stale)
    if _last_known and time.time() - _last_known.get("ts", 0) < 300:
        loc = dict(_last_known)
        loc["display_name"] = _reverse_geocode(loc["lat"], loc["lon"])
        return loc

    # 2. Saved named locations
    facts = all_facts()
    home = getattr(settings, "squire_home_address", "") or facts.get("home_address", "")
    if home:
        return {"display_name": home, "source": "saved_home", "lat": None, "lon": None}

    # 3. IP geolocation (no key required)
    try:
        import httpx
        token = getattr(settings, "ipinfo_token", "")
        url = f"https://ipinfo.io/json?token={token}" if token else "https://ipinfo.io/json"
        r = httpx.get(url, timeout=5)
        r.raise_for_status()
        data = r.json()
        loc_str = data.get("loc", "")
        if loc_str and "," in loc_str:
            lat, lon = map(float, loc_str.split(","))
            city = data.get("city", "")
            region = data.get("region", "")
            display = f"{city}, {region}" if city else region
            return {"lat": lat, "lon": lon, "display_name": display, "source": "ip"}
    except Exception:
        pass

    # 4. Settings fallback
    city = getattr(settings, "squire_default_city", "") or facts.get("city", "")
    if city:
        return {"display_name": city, "source": "settings", "lat": None, "lon": None}

    return None


def _reverse_geocode(lat: float, lon: float) -> str:
    """Convert lat/lon to a human-readable address using Nominatim (free, no key)."""
    try:
        import httpx
        r = httpx.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "json"},
            headers={"User-Agent": "squire-assistant/1.0 (mysquire.ai)"},
            timeout=5,
        )
        r.raise_for_status()
        data = r.json()
        address = data.get("address", {})
        parts = [
            address.get("neighbourhood") or address.get("suburb", ""),
            address.get("city") or address.get("town") or address.get("village", ""),
            address.get("state", ""),
        ]
        return ", ".join(p for p in parts if p) or data.get("display_name", "")[:60]
    except Exception:
        return f"{lat:.3f},{lon:.3f}"


# ── Skills ────────────────────────────────────────────────────────────────────

@skill(
    name="get_my_location",
    description=(
        "Get the current location. "
        "Use when the user asks 'where am I?', 'what city am I in?', "
        "or before any location-aware task."
    ),
    requires=[],
)
def get_my_location() -> str:
    """Resolve and return the current location."""
    loc = get_current_location()
    if not loc:
        return (
            "I don't know your location yet.\n"
            "To fix this:\n"
            "  • Say 'my home is at <address>' to save it\n"
            "  • Set SQUIRE_HOME_ADDRESS in Settings\n"
            "  • Open Squire in a mobile browser (GPS will be shared automatically)"
        )
    source_label = {"gps": "📍 GPS", "saved_home": "🏠 Home", "ip": "🌐 IP estimate",
                    "settings": "⚙️ Settings"}.get(loc.get("source", ""), "📌")
    coords = f" ({loc['lat']:.4f}, {loc['lon']:.4f})" if loc.get("lat") else ""
    return f"{source_label}: {loc['display_name']}{coords}"


@skill(
    name="set_named_location",
    description=(
        "Save a named location (home, work, gym, etc.) so Squire can use it "
        "for location-aware features. Example: 'my home is at 123 Main St, Seattle'."
    ),
    parameters={
        "label":   {"type": "string", "description": "Name like 'home', 'work', 'gym'"},
        "address": {"type": "string", "description": "Full address"},
    },
    requires=[],
)
def set_named_location(label: str, address: str) -> str:
    """Save a named location to memory."""
    key = f"{label.lower().replace(' ','_')}_address"
    save_fact(key, address)
    if label.lower() == "home":
        # Also update settings default
        try:
            from ram.core.config import settings as s
            object.__setattr__(s, "squire_home_address", address)
        except Exception:
            pass
    return f"✅ Saved {label}: {address}"


@skill(
    name="get_directions",
    description=(
        "Get directions from current location (or a start point) to a destination. "
        "Use for 'how do I get to Whole Foods?', 'directions to SFO'."
    ),
    parameters={
        "destination": {"type": "string"},
        "origin":      {"type": "string", "default": "",
                        "description": "Starting address (uses current location if empty)"},
        "mode":        {"type": "string", "default": "driving",
                        "description": "driving | walking | transit | bicycling"},
    },
    requires=[],
)
def get_directions(destination: str, origin: str = "", mode: str = "driving") -> str:
    """Get turn-by-turn directions using Google Maps or OpenStreetMap."""
    if not origin:
        loc = get_current_location()
        if not loc:
            return "I don't know your current location. Say 'my home is at <address>' first."
        origin = loc.get("display_name") or f"{loc.get('lat')},{loc.get('lon')}"

    # Google Maps (best quality)
    if getattr(settings, "google_maps_api_key", ""):
        try:
            import googlemaps
            gmaps = googlemaps.Client(key=settings.google_maps_api_key)
            result = gmaps.directions(origin, destination, mode=mode)
            if not result:
                return f"No route found from '{origin}' to '{destination}'."
            leg = result[0]["legs"][0]
            duration = leg["duration"]["text"]
            distance = leg["distance"]["text"]
            steps = leg.get("steps", [])[:8]
            import re
            step_lines = [
                f"  {i+1}. {re.sub('<[^>]+>', '', s.get('html_instructions',''))[:70]} ({s['distance']['text']})"
                for i, s in enumerate(steps)
            ]
            return (f"🗺️ **{origin}** → **{destination}**\n"
                    f"   {mode.title()}: {duration} ({distance})\n\n"
                    + "\n".join(step_lines))
        except Exception as e:
            logger.debug(f"Directions error: {e}")

    # Fallback: provide Google Maps link
    import urllib.parse
    q = urllib.parse.quote(f"{origin} to {destination}")
    return (f"Directions from {origin} to {destination}:\n"
            f"🗺️ https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(origin)}"
            f"&destination={urllib.parse.quote(destination)}&travelmode={mode}")


@skill(
    name="location_aware_reminder",
    description=(
        "Set a reminder that triggers when arriving at a location. "
        "Use for 'remind me to buy milk when I get to the grocery store'."
    ),
    parameters={
        "reminder":  {"type": "string", "description": "What to remind"},
        "location":  {"type": "string",
                      "description": "Place name or address (e.g. 'home', 'Whole Foods', '123 Main St')"},
        "trigger":   {"type": "string", "default": "arrive",
                      "description": "arrive | depart"},
    },
    requires=[],
)
def location_aware_reminder(reminder: str, location: str, trigger: str = "arrive") -> str:
    """Store a location-triggered reminder (polled by the proactive scheduler)."""
    try:
        save_fact(f"location_reminder_{int(time.time())}", json.dumps({
            "reminder": reminder, "location": location, "trigger": trigger,
            "created": time.strftime("%Y-%m-%d"),
        }))
        return (f"✅ Reminder saved: '{reminder}' when you {trigger} at {location}.\n"
                f"Note: Location reminders require the mobile PWA for real-time GPS.")
    except Exception as e:
        return f"Error saving reminder: {e}"
