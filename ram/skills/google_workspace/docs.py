"""Google Docs integration — read, create, and edit Google Documents.

All operations use the Gmail OAuth credentials stored in ``core/accounts.py``.
Required scope: ``https://www.googleapis.com/auth/documents``
"""
from __future__ import annotations

from loguru import logger
from ram.core.registry import skill


def _docs_service(account: str = ""):
    """Build a Google Docs API client."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        from ram.core.accounts import list_accounts, get_tokens, update_tokens
        import json

        accts = list_accounts(kind="gmail")
        acct = next((a for a in accts if not account or a.email == account), None)
        if not acct:
            return None
        tokens = get_tokens(acct.email)
        if not tokens:
            return None
        creds = Credentials(
            token=tokens.get("access_token"),
            refresh_token=tokens.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=tokens.get("client_id"),
            client_secret=tokens.get("client_secret"),
            scopes=["https://www.googleapis.com/auth/documents",
                    "https://www.googleapis.com/auth/drive"],
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            update_tokens(acct.email, json.loads(creds.to_json()))
        return build("docs", "v1", credentials=creds)
    except Exception as e:
        logger.debug(f"Docs service: {e}")
        return None


def _drive_service_for_docs(account: str = ""):
    """Drive service used for creating Docs files."""
    try:
        from ram.skills.google_workspace.drive import _drive_service
        return _drive_service(account)
    except Exception:
        return None


def _extract_text(doc: dict) -> str:
    """Extract plain text from a Google Docs document body."""
    body = doc.get("body", {}).get("content", [])
    lines = []
    for element in body:
        para = element.get("paragraph")
        if para:
            for pe in para.get("elements", []):
                text = pe.get("textRun", {}).get("content", "")
                lines.append(text)
    return "".join(lines)


@skill(
    name="docs_read",
    description=(
        "Read the contents of a Google Doc. "
        "Use for 'read my meeting notes doc', 'show me the project plan document'."
    ),
    parameters={
        "document_id": {"type": "string",
                        "description": "Google Doc ID or URL"},
        "account":     {"type": "string", "default": ""},
    },
    requires=[],
)
def docs_read(document_id: str, account: str = "") -> str:
    """Read a Google Doc and return its text content."""
    # Extract ID from URL if needed
    if "docs.google.com" in document_id:
        import re
        m = re.search(r'/d/([a-zA-Z0-9_-]+)', document_id)
        if m:
            document_id = m.group(1)

    svc = _docs_service(account)
    if not svc:
        return "Google Docs not connected. Connect a Google account in Settings."
    try:
        doc = svc.documents().get(documentId=document_id).execute()
        title = doc.get("title", "Untitled")
        text = _extract_text(doc)
        return f"📄 **{title}**\n\n{text[:3000]}" + ("…" if len(text) > 3000 else "")
    except Exception as e:
        return f"Docs read error: {e}"


@skill(
    name="docs_create",
    description=(
        "Create a new Google Doc with the given title and content. "
        "Use for 'create a doc titled X with content Y', 'draft a meeting notes doc'."
    ),
    parameters={
        "title":   {"type": "string"},
        "content": {"type": "string", "default": "",
                    "description": "Initial text content (optional)"},
        "account": {"type": "string", "default": ""},
    },
    sensitive=True,
    requires=[],
)
def docs_create(title: str, content: str = "", account: str = "") -> str:
    """Create a new Google Doc."""
    svc = _docs_service(account)
    if not svc:
        return "Google Docs not connected."
    try:
        doc = svc.documents().create(body={"title": title}).execute()
        doc_id = doc.get("documentId")

        if content:
            svc.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": [{"insertText": {"location": {"index": 1}, "text": content}}]},
            ).execute()

        url = f"https://docs.google.com/document/d/{doc_id}"
        return f"✅ Created Google Doc: **{title}**\n{url}"
    except Exception as e:
        return f"Docs create error: {e}"


@skill(
    name="docs_append",
    description=(
        "Append text to an existing Google Doc. "
        "Use for 'add to my notes doc', 'append to the meeting minutes'."
    ),
    parameters={
        "document_id": {"type": "string", "description": "Doc ID or URL"},
        "text":        {"type": "string", "description": "Text to append"},
        "account":     {"type": "string", "default": ""},
    },
    sensitive=True,
    requires=[],
)
def docs_append(document_id: str, text: str, account: str = "") -> str:
    """Append text to the end of a Google Doc."""
    if "docs.google.com" in document_id:
        import re
        m = re.search(r'/d/([a-zA-Z0-9_-]+)', document_id)
        if m:
            document_id = m.group(1)

    svc = _docs_service(account)
    if not svc:
        return "Google Docs not connected."
    try:
        doc = svc.documents().get(documentId=document_id).execute()
        # Find the end index
        content = doc.get("body", {}).get("content", [])
        end_index = max((e.get("endIndex", 1) for e in content), default=1) - 1
        svc.documents().batchUpdate(
            documentId=document_id,
            body={"requests": [
                {"insertText": {"location": {"index": end_index}, "text": f"\n{text}"}}
            ]},
        ).execute()
        return f"✅ Appended text to doc (id: {document_id[:20]}…)"
    except Exception as e:
        return f"Docs append error: {e}"
