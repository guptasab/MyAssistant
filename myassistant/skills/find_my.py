"""Find My — read-only lookup using icloud_python (optional)."""
from __future__ import annotations

from myassistant.core.registry import skill


@skill(name="find_my_devices",
       description="List the locations of devices on the iCloud account (Find My).")
def find_my_devices(apple_id: str = "", password: str = "") -> str:
    try:
        from pyicloud import PyiCloudService
    except ImportError:
        return "ERROR: install pyicloud"
    if not (apple_id and password):
        from myassistant.core import vault
        apple_id = vault.reveal("icloud_email") or ""
        password = vault.reveal("icloud_app_password") or ""
        if not apple_id:
            return "ERROR: store icloud_email + icloud_app_password in vault first"
    try:
        api = PyiCloudService(apple_id, password)
        out = []
        for d in api.devices:
            loc = d.location() or {}
            out.append(f"{d['name']:<20} {loc.get('latitude','?'):.4f},{loc.get('longitude','?'):.4f}  {d.get('batteryLevel','?')}")
        return "\n".join(out) or "(none)"
    except Exception as e:
        return f"ERROR: {e}"
