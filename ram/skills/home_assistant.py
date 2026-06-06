"""Home Assistant bridge — control lights, locks, scenes, sensors."""
from __future__ import annotations

import httpx

from ram.core.config import settings
from ram.core.registry import skill


def _hdr():
    return {"Authorization": f"Bearer {settings.ha_token}", "Content-Type": "application/json"}


@skill(name="ha_states", description="List Home Assistant entity states (filtered by domain).",
       requires=["ha_base_url", "ha_token"])
def ha_states(domain: str = "") -> str:
    r = httpx.get(f"{settings.ha_base_url}/api/states", headers=_hdr(), timeout=10)
    if r.status_code >= 300:
        return f"ERROR: {r.status_code}"
    items = r.json()
    if domain:
        items = [i for i in items if i["entity_id"].startswith(f"{domain}.")]
    return "\n".join(f"{i['entity_id']:<40} {i['state']}" for i in items[:50]) or "(none)"


@skill(name="ha_call",
       description=("Call a Home Assistant service. domain='light', service='turn_on', "
                    "entity_id='light.kitchen'. Optionally pass a JSON service_data string."),
       requires=["ha_base_url", "ha_token"], sensitive=True)
def ha_call(domain: str, service: str, entity_id: str = "", service_data: str = "") -> str:
    import json
    body: dict = {}
    if entity_id:
        body["entity_id"] = entity_id
    if service_data:
        try:
            body.update(json.loads(service_data))
        except Exception:
            pass
    r = httpx.post(f"{settings.ha_base_url}/api/services/{domain}/{service}",
                   headers=_hdr(), json=body, timeout=10)
    return f"{r.status_code} {r.text[:200]}"
