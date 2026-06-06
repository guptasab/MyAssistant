"""Send email via Gmail (uses the OAuth tokens from gmail_skill)."""
from __future__ import annotations

import base64
from email.mime.text import MIMEText

from ram.core.registry import skill


def _service():
    try:
        from ram.skills.gmail_skill import gmail_service
        return gmail_service()
    except Exception:
        return None


@skill(
    name="send_email",
    description=("Send an email via the connected Gmail account. ALWAYS confirm the draft "
                 "with the user before calling this. Use for replies, recurring weekly "
                 "notes, RSVPs, etc."),
    requires=["google_oauth_client_secrets"],
    sensitive=True,
)
def send_email(to: str, subject: str, body: str, cc: str = "", reply_to_message_id: str = "") -> str:
    svc = _service()
    if not svc:
        return "ERROR: Gmail not connected. Run google OAuth first."
    msg = MIMEText(body)
    msg["to"] = to
    msg["subject"] = subject
    if cc:
        msg["cc"] = cc
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    body_payload: dict = {"raw": raw}
    if reply_to_message_id:
        body_payload["threadId"] = reply_to_message_id
    sent = svc.users().messages().send(userId="me", body=body_payload).execute()
    return f"sent id={sent.get('id', '?')}"
