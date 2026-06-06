"""Gmail integration — delegated OAuth, read-only by default.

This is how Ollie watches school emails. The agent can list recent messages,
read a specific one, and search. The school-email parser builds on top of this.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

from loguru import logger

from ram.core.config import settings
from ram.core.registry import skill

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",   # for marking read / labels
]
_TOKEN_PATH = settings.ram_data_dir / "google_token.json"


def gmail_service():
    """Returns an authorized Gmail v1 service or None if creds missing."""
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        return None

    creds = None
    if _TOKEN_PATH.exists():
        try:
            creds = Credentials.from_authorized_user_info(
                json.loads(_TOKEN_PATH.read_text()), SCOPES,
            )
        except Exception as e:
            logger.warning(f"token unreadable: {e}")
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                logger.warning(f"token refresh failed: {e}")
                creds = None
        if not creds:
            secrets = settings.google_oauth_client_secrets
            if not secrets or not Path(secrets).exists():
                return None
            flow = InstalledAppFlow.from_client_secrets_file(str(secrets), SCOPES)
            creds = flow.run_local_server(port=0)
        _TOKEN_PATH.write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def _decode_body(payload) -> str:
    """Extract a plain-text body from a Gmail message payload."""
    if not payload:
        return ""
    data = payload.get("body", {}).get("data")
    if data:
        try:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
        except Exception:
            return ""
    for part in payload.get("parts", []) or []:
        mt = part.get("mimeType", "")
        if mt == "text/plain":
            body = _decode_body(part)
            if body:
                return body
    # fallback to html stripped of tags
    for part in payload.get("parts", []) or []:
        if part.get("mimeType") == "text/html":
            body = _decode_body(part)
            if body:
                import re
                return re.sub(r"<[^>]+>", " ", body)
    return ""


def _headers(msg) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}


@skill(
    name="gmail_recent",
    description=("List recent inbox messages with sender/subject/snippet. "
                 "max defaults to 15. Use this to scan what came in today."),
)
def gmail_recent(max_results: int = 15, query: str = "newer_than:1d -category:promotions") -> str:
    svc = gmail_service()
    if not svc:
        return "ERROR: Gmail not connected. Run `python -m ram.tools.google_auth`."
    res = svc.users().messages().list(
        userId="me", q=query, maxResults=max(1, min(50, max_results))
    ).execute()
    ids = [m["id"] for m in res.get("messages", [])]
    if not ids:
        return "inbox quiet — nothing new"
    out = []
    for mid in ids:
        msg = svc.users().messages().get(userId="me", id=mid, format="metadata",
                                         metadataHeaders=["From", "Subject", "Date"]).execute()
        h = _headers(msg)
        out.append(f"[{mid}] {h.get('from','?')[:40]} — {h.get('subject','(no subject)')[:80]}")
    return "\n".join(out)


@skill(
    name="gmail_read",
    description="Read the full text of a specific message by its id.",
)
def gmail_read(message_id: str) -> str:
    svc = gmail_service()
    if not svc:
        return "ERROR: Gmail not connected."
    msg = svc.users().messages().get(userId="me", id=message_id, format="full").execute()
    h = _headers(msg)
    body = _decode_body(msg.get("payload", {}))
    return (
        f"From: {h.get('from','?')}\n"
        f"To: {h.get('to','?')}\n"
        f"Date: {h.get('date','?')}\n"
        f"Subject: {h.get('subject','(no subject)')}\n\n"
        f"{body[:4000]}"
    )


@skill(
    name="gmail_search",
    description=("Search Gmail using standard Gmail operators. "
                 "Example queries: 'from:school subject:permission', "
                 "'newer_than:7d label:important'."),
)
def gmail_search(query: str, max_results: int = 10) -> str:
    return gmail_recent(max_results=max_results, query=query)


@skill(
    name="gmail_mark_read",
    description="Mark a message as read (removes UNREAD label).",
)
def gmail_mark_read(message_id: str) -> str:
    svc = gmail_service()
    if not svc:
        return "ERROR: Gmail not connected."
    svc.users().messages().modify(
        userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]},
    ).execute()
    return f"marked {message_id} read"
