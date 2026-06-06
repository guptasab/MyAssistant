"""Google Drive integration — list, search, upload, and manage files.

Connects to any Google account registered in ``core/accounts.py`` with
Gmail/Google OAuth credentials that include Drive scopes.

Prerequisites:
  pip install google-api-python-client google-auth

Required OAuth scopes (add to google_oauth_client_secrets or accounts):
  https://www.googleapis.com/auth/drive
  https://www.googleapis.com/auth/drive.file

All operations require confirmation before modifying or deleting files.
"""
from __future__ import annotations

from loguru import logger
from myassistant.core.registry import skill
from myassistant.core.accounts import list_accounts, gmail_service_for


def _drive_service(account: str = ""):
    """Build a Google Drive API client for the specified account."""
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from myassistant.core.accounts import get_tokens, update_tokens
        import json

        accts = list_accounts(kind="gmail")
        acct = next((a for a in accts if not account or a.email == account), None)
        if not acct:
            return None

        tokens = get_tokens(acct.email)
        if not tokens:
            return None

        from google.auth.transport.requests import Request
        creds = Credentials(
            token=tokens.get("access_token"),
            refresh_token=tokens.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=tokens.get("client_id"),
            client_secret=tokens.get("client_secret"),
            scopes=["https://www.googleapis.com/auth/drive"],
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            update_tokens(acct.email, json.loads(creds.to_json()))
        return build("drive", "v3", credentials=creds)
    except ImportError:
        logger.warning("google-api-python-client not installed: pip install google-api-python-client")
        return None
    except Exception as e:
        logger.debug(f"Drive service: {e}")
        return None


@skill(
    name="drive_list_files",
    description=(
        "List files in Google Drive. Optionally filter by folder, type, or search query. "
        "Use for 'show my Drive files', 'find files in my Documents folder', 'list spreadsheets'."
    ),
    parameters={
        "query":    {"type": "string", "default": "",
                     "description": "Search query, e.g. 'name contains Report' or mime type filter"},
        "folder":   {"type": "string", "default": "",
                     "description": "Folder name to list (searches by folder name)"},
        "limit":    {"type": "integer", "default": 20},
        "account":  {"type": "string", "default": ""},
    },
    requires=[],
)
def drive_list_files(query: str = "", folder: str = "", limit: int = 20, account: str = "") -> str:
    """List Google Drive files with optional filtering."""
    svc = _drive_service(account)
    if not svc:
        return "Google Drive not connected. Connect a Google account in Settings → Channels."

    q_parts = ["trashed = false"]
    if folder:
        # Find folder ID first
        try:
            folder_result = svc.files().list(
                q=f"name = '{folder}' and mimeType = 'application/vnd.google-apps.folder'",
                fields="files(id,name)"
            ).execute()
            folders = folder_result.get("files", [])
            if folders:
                q_parts.append(f"'{folders[0]['id']}' in parents")
        except Exception:
            pass
    if query:
        q_parts.append(query)

    try:
        result = svc.files().list(
            q=" and ".join(q_parts),
            pageSize=limit,
            fields="files(id,name,mimeType,size,modifiedTime,webViewLink)",
            orderBy="modifiedTime desc",
        ).execute()
        files = result.get("files", [])
        if not files:
            return "No files found matching your criteria."

        _MIME_ICONS = {
            "application/vnd.google-apps.document":     "📄",
            "application/vnd.google-apps.spreadsheet":  "📊",
            "application/vnd.google-apps.presentation": "📑",
            "application/vnd.google-apps.folder":       "📁",
            "application/pdf":                           "📋",
        }
        lines = [f"Google Drive — {len(files)} file(s):\n"]
        for f in files:
            icon = _MIME_ICONS.get(f.get("mimeType", ""), "📎")
            mod = f.get("modifiedTime", "")[:10]
            size = f.get("size", "")
            size_str = f" ({int(size)//1024}KB)" if size else ""
            lines.append(f"  {icon} {f['name']}{size_str}  [{mod}]  {f.get('webViewLink','')[:60]}")
        return "\n".join(lines)
    except Exception as e:
        return f"Drive list error: {e}"


@skill(
    name="drive_search",
    description=(
        "Search Google Drive by content or file name. "
        "Use for 'find the Q3 report', 'search my Drive for budget'."
    ),
    parameters={
        "query":   {"type": "string", "description": "Search terms"},
        "account": {"type": "string", "default": ""},
    },
    requires=[],
)
def drive_search(query: str, account: str = "") -> str:
    """Full-text search across Google Drive."""
    svc = _drive_service(account)
    if not svc:
        return "Google Drive not connected."
    try:
        result = svc.files().list(
            q=f"fullText contains '{query}' and trashed = false",
            pageSize=10,
            fields="files(id,name,mimeType,modifiedTime,webViewLink)",
            orderBy="modifiedTime desc",
        ).execute()
        files = result.get("files", [])
        if not files:
            return f"No Drive files found matching '{query}'."
        lines = [f"Drive search results for '{query}':\n"]
        for f in files:
            mod = f.get("modifiedTime", "")[:10]
            lines.append(f"  📎 {f['name']}  [{mod}]  {f.get('webViewLink','')[:60]}")
        return "\n".join(lines)
    except Exception as e:
        return f"Drive search error: {e}"


@skill(
    name="drive_upload",
    description="Upload a local file to Google Drive.",
    parameters={
        "local_path": {"type": "string", "description": "Local file path to upload"},
        "folder":     {"type": "string", "default": "",
                       "description": "Target Google Drive folder name"},
        "account":    {"type": "string", "default": ""},
    },
    sensitive=True,
    requires=[],
)
def drive_upload(local_path: str, folder: str = "", account: str = "") -> str:
    """Upload a file to Google Drive."""
    import os
    svc = _drive_service(account)
    if not svc:
        return "Google Drive not connected."
    if not os.path.exists(local_path):
        return f"File not found: {local_path}"
    try:
        from googleapiclient.http import MediaFileUpload
        import mimetypes
        mime = mimetypes.guess_type(local_path)[0] or "application/octet-stream"
        metadata: dict = {"name": os.path.basename(local_path)}

        if folder:
            result = svc.files().list(
                q=f"name = '{folder}' and mimeType = 'application/vnd.google-apps.folder'",
                fields="files(id)"
            ).execute()
            fids = result.get("files", [])
            if fids:
                metadata["parents"] = [fids[0]["id"]]

        media = MediaFileUpload(local_path, mimetype=mime)
        uploaded = svc.files().create(body=metadata, media_body=media, fields="id,name,webViewLink").execute()
        return f"✅ Uploaded '{uploaded['name']}' to Drive: {uploaded.get('webViewLink','')}"
    except Exception as e:
        return f"Upload error: {e}"


@skill(
    name="drive_create_folder",
    description="Create a new folder in Google Drive.",
    parameters={
        "name":    {"type": "string"},
        "parent":  {"type": "string", "default": "", "description": "Parent folder name (optional)"},
        "account": {"type": "string", "default": ""},
    },
    sensitive=True,
    requires=[],
)
def drive_create_folder(name: str, parent: str = "", account: str = "") -> str:
    """Create a folder in Google Drive."""
    svc = _drive_service(account)
    if not svc:
        return "Google Drive not connected."
    try:
        metadata: dict = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent:
            result = svc.files().list(
                q=f"name = '{parent}' and mimeType = 'application/vnd.google-apps.folder'",
                fields="files(id)"
            ).execute()
            fids = result.get("files", [])
            if fids:
                metadata["parents"] = [fids[0]["id"]]

        folder = svc.files().create(body=metadata, fields="id,name,webViewLink").execute()
        return f"✅ Folder '{folder['name']}' created: {folder.get('webViewLink','')}"
    except Exception as e:
        return f"Create folder error: {e}"
