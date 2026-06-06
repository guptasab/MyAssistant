"""Ring / Nest doorbell helpers (read-only events, snapshot fetch)."""
from __future__ import annotations

from myassistant.core.config import settings
from myassistant.core.registry import skill


@skill(name="ring_recent_events",
       description="List recent Ring doorbell/motion events.",
       requires=["ring_email", "ring_password"])
def ring_recent_events(limit: int = 10) -> str:
    try:
        from ring_doorbell import Ring, Auth  # optional dep
    except ImportError:
        return "ERROR: install ring_doorbell"
    try:
        a = Auth("Ollie/1.0", None, lambda token: None)
        a.fetch_token(settings.ring_email, settings.ring_password)
        ring = Ring(a)
        ring.update_data()
        out = []
        for d in (ring.devices().get("doorbots", []) + ring.devices().get("stickup_cams", [])):
            for ev in (d.history(limit=limit) or []):
                out.append(f"{ev.get('created_at')}  {d.name}  {ev.get('kind')}")
        return "\n".join(out[:limit]) or "(no events)"
    except Exception as e:
        return f"ERROR: {e}"
