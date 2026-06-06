"""iMessage relay via BlueBubbles (self-hosted Mac bridge)."""
from __future__ import annotations

import httpx

from ram.core.config import settings
from ram.core.registry import skill


@skill(
    name="imessage_send",
    description=("Send a blue-bubble iMessage via BlueBubbles. Use for iPhone-only family "
                 "members or group chats addressed by GUID. Requires BlueBubbles server."),
    requires=["bluebubbles_url", "bluebubbles_password"],
    sensitive=True,
)
def imessage_send(chat_guid: str, text: str) -> str:
    url = f"{settings.bluebubbles_url.rstrip('/')}/api/v1/message/text?password={settings.bluebubbles_password}"
    r = httpx.post(url, json={"chatGuid": chat_guid, "message": text, "method": "apple-script"}, timeout=15)
    if r.status_code >= 300:
        return f"ERROR: {r.status_code} {r.text[:200]}"
    return "imessage sent"


@skill(
    name="imessage_chats",
    description="List recent iMessage chats and their GUIDs.",
    requires=["bluebubbles_url", "bluebubbles_password"],
)
def imessage_chats(limit: int = 20) -> str:
    url = (f"{settings.bluebubbles_url.rstrip('/')}/api/v1/chat/query?"
           f"password={settings.bluebubbles_password}&limit={limit}")
    r = httpx.post(url, json={"limit": limit}, timeout=15)
    if r.status_code >= 300:
        return f"ERROR: {r.status_code}"
    data = r.json().get("data", [])
    return "\n".join(f"{c.get('displayName','?')} :: {c.get('guid','')}" for c in data) or "(none)"
