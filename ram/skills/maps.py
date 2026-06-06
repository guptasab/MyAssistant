"""Maps, traffic, nearby places. Uses Google Maps Platform."""
from __future__ import annotations

from loguru import logger

from ram.core.config import settings
from ram.core.registry import skill


def _client():
    if not settings.google_maps_api_key:
        return None
    try:
        import googlemaps
        return googlemaps.Client(key=settings.google_maps_api_key)
    except ImportError:
        return None


@skill(
    name="find_nearby",
    description="Find places near a location (e.g. 'starbucks near me'). location can be 'lat,lng' or an address.",
)
def find_nearby(query: str, location: str, radius_meters: int = 5000) -> str:
    c = _client()
    if not c:
        return "ERROR: GOOGLE_MAPS_API_KEY not set"
    res = c.places(query=query, location=location, radius=radius_meters)
    out = []
    for p in res.get("results", [])[:8]:
        out.append(f"- {p['name']} ({p.get('rating','?')}★, {p.get('user_ratings_total','?')} reviews) — {p.get('formatted_address','')}")
    return "\n".join(out) or "no results"


@skill(
    name="traffic_eta",
    description="Get current driving ETA + traffic conditions between two addresses.",
)
def traffic_eta(origin: str, destination: str) -> str:
    c = _client()
    if not c:
        return "ERROR: GOOGLE_MAPS_API_KEY not set"
    res = c.distance_matrix(
        origins=[origin], destinations=[destination],
        mode="driving", departure_time="now", traffic_model="best_guess",
    )
    try:
        e = res["rows"][0]["elements"][0]
        baseline = e["duration"]["value"]
        with_traffic = e.get("duration_in_traffic", e["duration"])["value"]
        delay = with_traffic - baseline
        status = "clear" if delay < 120 else "moderate" if delay < 600 else "heavy"
        return (f"{e['distance']['text']} — {e.get('duration_in_traffic', e['duration'])['text']} "
                f"(traffic: {status}, +{delay//60}min vs typical)")
    except Exception as ex:
        return f"ERROR: {ex}"


@skill(name="geocode", description="Convert an address to lat,lng coordinates.")
def geocode(address: str) -> str:
    c = _client()
    if not c:
        return "ERROR: GOOGLE_MAPS_API_KEY not set"
    res = c.geocode(address)
    if not res:
        return "not found"
    loc = res[0]["geometry"]["location"]
    return f"{loc['lat']},{loc['lng']} — {res[0]['formatted_address']}"
