"""Smart home via Home Assistant REST API.

Why Home Assistant rather than Alexa directly? Alexa's API requires a Login
With Amazon app + skill, which is painful for personal use. Home Assistant
already integrates Alexa (and HomeKit, Google Home, Hue, Nest, Ecobee, etc.)
and exposes a clean REST/WebSocket API. Set HA_BASE_URL and HA_TOKEN to a
long-lived access token from your HA profile page.
"""
from __future__ import annotations

import httpx
from loguru import logger

from ram.core.config import settings
from ram.core.registry import skill


def _ha_call(method: str, path: str, json=None) -> dict | str:
    if not (settings.ha_base_url and settings.ha_token):
        return {"error": "Home Assistant not configured (set HA_BASE_URL, HA_TOKEN)"}
    try:
        r = httpx.request(
            method, f"{settings.ha_base_url.rstrip('/')}/api/{path}",
            headers={"Authorization": f"Bearer {settings.ha_token}",
                     "Content-Type": "application/json"},
            json=json, timeout=15,
        )
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return r.text
    except Exception as e:
        logger.exception("HA call failed")
        return {"error": str(e)}


@skill(name="list_devices", description="List smart-home devices and their current states.")
def list_devices(domain: str = "") -> str:
    states = _ha_call("GET", "states")
    if isinstance(states, dict) and "error" in states:
        return f"ERROR: {states['error']}"
    out = []
    for s in states:
        eid = s.get("entity_id", "")
        if domain and not eid.startswith(f"{domain}."):
            continue
        out.append(f"- {eid} = {s.get('state')} ({s.get('attributes', {}).get('friendly_name','')})")
    return "\n".join(out[:80]) or "no devices"


@skill(
    name="set_thermostat",
    description="Set a thermostat to a target temperature (Fahrenheit).",
    sensitive=True,
)
def set_thermostat(entity_id: str, temperature_f: float) -> str:
    res = _ha_call("POST", "services/climate/set_temperature",
                   json={"entity_id": entity_id, "temperature": temperature_f})
    return f"set {entity_id} -> {temperature_f}°F" if not isinstance(res, dict) or "error" not in res else f"ERROR: {res['error']}"


@skill(name="turn_on", description="Turn on a device (light, switch, etc.) by entity_id.")
def turn_on(entity_id: str) -> str:
    domain = entity_id.split(".")[0]
    res = _ha_call("POST", f"services/{domain}/turn_on", json={"entity_id": entity_id})
    return f"on: {entity_id}" if not isinstance(res, dict) or "error" not in res else f"ERROR: {res['error']}"


@skill(name="turn_off", description="Turn off a device by entity_id.")
def turn_off(entity_id: str) -> str:
    domain = entity_id.split(".")[0]
    res = _ha_call("POST", f"services/{domain}/turn_off", json={"entity_id": entity_id})
    return f"off: {entity_id}" if not isinstance(res, dict) or "error" not in res else f"ERROR: {res['error']}"


@skill(
    name="run_scene",
    description="Activate a Home Assistant scene (e.g. 'goodnight', 'movie_time').",
)
def run_scene(scene_id: str) -> str:
    entity = scene_id if scene_id.startswith("scene.") else f"scene.{scene_id}"
    res = _ha_call("POST", "services/scene/turn_on", json={"entity_id": entity})
    return f"activated {entity}" if not isinstance(res, dict) or "error" not in res else f"ERROR: {res['error']}"
