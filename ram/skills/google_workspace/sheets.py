"""Google Sheets integration — read, write, and append spreadsheet data.

Required OAuth scope: ``https://www.googleapis.com/auth/spreadsheets``
"""
from __future__ import annotations

from loguru import logger
from ram.core.registry import skill


def _sheets_service(account: str = ""):
    """Build a Google Sheets API client."""
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
            scopes=["https://www.googleapis.com/auth/spreadsheets",
                    "https://www.googleapis.com/auth/drive.readonly"],
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            update_tokens(acct.email, json.loads(creds.to_json()))
        return build("sheets", "v4", credentials=creds)
    except Exception as e:
        logger.debug(f"Sheets service: {e}")
        return None


def _parse_sheet_id(ref: str) -> str:
    """Extract sheet ID from a URL or return as-is if already an ID."""
    if "spreadsheets.google.com" in ref:
        import re
        m = re.search(r'/d/([a-zA-Z0-9_-]+)', ref)
        if m:
            return m.group(1)
    return ref


@skill(
    name="sheets_read",
    description=(
        "Read data from a Google Sheets spreadsheet. "
        "Use for 'read my budget spreadsheet', 'show row 5 of the tracker sheet'."
    ),
    parameters={
        "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID or URL"},
        "range":          {"type": "string", "default": "A1:Z100",
                           "description": "Cell range, e.g. 'Sheet1!A1:D10' or 'A1:Z50'"},
        "account":        {"type": "string", "default": ""},
    },
    requires=[],
)
def sheets_read(spreadsheet_id: str, range: str = "A1:Z100", account: str = "") -> str:
    """Read data from a Google Sheets range."""
    spreadsheet_id = _parse_sheet_id(spreadsheet_id)
    svc = _sheets_service(account)
    if not svc:
        return "Google Sheets not connected. Connect a Google account in Settings."
    try:
        result = svc.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=range
        ).execute()
        rows = result.get("values", [])
        if not rows:
            return f"No data found in range {range}."

        # Format as a simple table
        col_widths = [max(len(str(r[i])) for r in rows if i < len(r)) for i in range(max(len(r) for r in rows))]
        lines = []
        for i, row in enumerate(rows[:50]):
            cells = []
            for j, col_w in enumerate(col_widths):
                cell = str(row[j]) if j < len(row) else ""
                cells.append(cell.ljust(col_w))
            lines.append("  " + "  │  ".join(cells))
            if i == 0:
                lines.append("  " + "──┼──".join("─" * w for w in col_widths))

        return f"📊 Spreadsheet range {range} ({len(rows)} rows):\n\n" + "\n".join(lines)
    except Exception as e:
        return f"Sheets read error: {e}"


@skill(
    name="sheets_write",
    description=(
        "Write data to a Google Sheets cell or range. "
        "Use for 'update cell B3 in my tracker to 500', 'write to my budget sheet'."
    ),
    parameters={
        "spreadsheet_id": {"type": "string"},
        "range":          {"type": "string",
                           "description": "Cell or range, e.g. 'A1' or 'Sheet1!B3'"},
        "values":         {"type": "array",  "items": {"type": "array"},
                           "description": "2D array of values, e.g. [[1, 2], [3, 4]]"},
        "account":        {"type": "string", "default": ""},
    },
    sensitive=True,
    requires=[],
)
def sheets_write(spreadsheet_id: str, range: str, values: list, account: str = "") -> str:
    """Write values to a Google Sheets range."""
    spreadsheet_id = _parse_sheet_id(spreadsheet_id)
    svc = _sheets_service(account)
    if not svc:
        return "Google Sheets not connected."
    try:
        body = {"values": values}
        result = svc.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range,
            valueInputOption="USER_ENTERED",
            body=body,
        ).execute()
        updated = result.get("updatedCells", 0)
        return f"✅ Updated {updated} cell(s) in range {range}."
    except Exception as e:
        return f"Sheets write error: {e}"


@skill(
    name="sheets_append",
    description=(
        "Append a new row to a Google Sheet. "
        "Use for 'add an expense row to my budget sheet', 'log this to my tracker'."
    ),
    parameters={
        "spreadsheet_id": {"type": "string"},
        "values":         {"type": "array",  "items": {},
                           "description": "List of values for the new row, e.g. ['2025-06-01', 'Groceries', 150]"},
        "sheet_name":     {"type": "string", "default": "Sheet1"},
        "account":        {"type": "string", "default": ""},
    },
    sensitive=True,
    requires=[],
)
def sheets_append(spreadsheet_id: str, values: list, sheet_name: str = "Sheet1", account: str = "") -> str:
    """Append a row to a Google Sheet."""
    spreadsheet_id = _parse_sheet_id(spreadsheet_id)
    svc = _sheets_service(account)
    if not svc:
        return "Google Sheets not connected."
    try:
        body = {"values": [values]}
        result = svc.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!A1",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body=body,
        ).execute()
        updated_range = result.get("updates", {}).get("updatedRange", "")
        return f"✅ Row appended to {updated_range or spreadsheet_id}."
    except Exception as e:
        return f"Sheets append error: {e}"


@skill(
    name="sheets_create",
    description="Create a new Google Sheets spreadsheet.",
    parameters={
        "title":   {"type": "string"},
        "account": {"type": "string", "default": ""},
    },
    sensitive=True,
    requires=[],
)
def sheets_create(title: str, account: str = "") -> str:
    """Create a new Google Sheets spreadsheet."""
    svc = _sheets_service(account)
    if not svc:
        return "Google Sheets not connected."
    try:
        sheet = svc.spreadsheets().create(
            body={"properties": {"title": title}},
            fields="spreadsheetId,spreadsheetUrl",
        ).execute()
        return f"✅ Created spreadsheet: **{title}**\n{sheet.get('spreadsheetUrl','')}"
    except Exception as e:
        return f"Sheets create error: {e}"
