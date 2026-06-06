"""Multi-account registry — stores credentials for Gmail, Outlook, IMAP, and CalDAV.

Every email/calendar account in Ram is represented as an ``Account`` row in
SQLite.  OAuth tokens are stored encrypted (using the vault passphrase when
available, otherwise plain-base64 as a fallback for dev setups).

Supported account types:
  ``gmail``    — Google OAuth2, accesses Gmail + Google Calendar
  ``outlook``  — Microsoft Graph OAuth2, accesses Outlook + Outlook Calendar
  ``imap``     — Generic IMAP (read) + SMTP (send): iCloud, Yahoo, ProtonMail, etc.
  ``caldav``   — Generic CalDAV: Apple Calendar, Fastmail, Nextcloud, etc.
  ``exchange`` — EWS / Exchange on-premise (placeholder for future)

Usage::

    from ram.core.accounts import list_accounts, get_account, add_account

    # Add a new Gmail account
    add_account("work@gmail.com", "gmail",
                tokens={"access_token": "...", "refresh_token": "..."})

    # List all connected accounts
    for acct in list_accounts():
        print(acct.email, acct.kind, acct.display_name)

    # Get the service client for a specific account
    acct = get_account("work@gmail.com")
    svc = acct.gmail_service()    # or .graph_client() for Outlook
"""
from __future__ import annotations

import base64
import json
import time
from typing import Any, Optional

from sqlalchemy import Column, String, Text, Float, Boolean
from loguru import logger

from ram.core.memory import Base, db, _engine


class Account(Base):
    """One connected email / calendar account.

    Attributes:
        id:           Primary key — same as ``email`` for uniqueness.
        email:        Account email address (also the unique key).
        kind:         Provider type: ``gmail`` | ``outlook`` | ``imap`` | ``caldav``.
        display_name: Human-friendly label (e.g. "Work Gmail", "iCloud").
        tokens_json:  Serialised OAuth tokens or IMAP credentials (encrypted at rest).
        scopes:       Space-separated OAuth scopes that were granted.
        enabled:      If False, account is paused (not polled or queried).
        primary:      If True, this is the default account for new emails.
        sync_email:   If True, poll inbox for new messages.
        sync_calendar:If True, pull calendar events.
        last_sync_ts: Unix timestamp of most recent successful sync.
        extra_json:   Provider-specific config (IMAP host, CalDAV URL, etc.).
    """
    __tablename__ = "accounts"
    id             = Column(String, primary_key=True)   # email address
    email          = Column(String, unique=True, index=True, nullable=False)
    kind           = Column(String, nullable=False)     # gmail | outlook | imap | caldav
    display_name   = Column(String, default="")
    tokens_json    = Column(Text, default="{}")         # encrypted JSON
    scopes         = Column(Text, default="")
    enabled        = Column(Boolean, default=True)
    primary        = Column(Boolean, default=False)
    sync_email     = Column(Boolean, default=True)
    sync_calendar  = Column(Boolean, default=True)
    last_sync_ts   = Column(Float, default=0.0)
    extra_json     = Column(Text, default="{}")         # host, port, caldav_url, etc.


Base.metadata.create_all(_engine)


# ── Token encryption helpers ──────────────────────────────────────────────

def _encrypt(data: dict) -> str:
    """Serialize + optionally encrypt account tokens for storage."""
    raw = json.dumps(data)
    try:
        from ram.core.vault import _fernet
        f = _fernet()
        if f:
            return "enc:" + f.encrypt(raw.encode()).decode()
    except Exception:
        pass
    # Fallback: base64 obfuscation (not real encryption — set OLLIE_VAULT_PASSPHRASE)
    return "b64:" + base64.b64encode(raw.encode()).decode()


def _decrypt(stored: str) -> dict:
    """Deserialize stored token string back to a dict."""
    if not stored or stored == "{}":
        return {}
    try:
        if stored.startswith("enc:"):
            from ram.core.vault import _fernet
            f = _fernet()
            if f:
                raw = f.decrypt(stored[4:].encode()).decode()
                return json.loads(raw)
        if stored.startswith("b64:"):
            return json.loads(base64.b64decode(stored[4:]).decode())
        return json.loads(stored)
    except Exception as e:
        logger.warning(f"token decrypt failed: {e}")
        return {}


# ── Public CRUD ────────────────────────────────────────────────────────────

def add_account(
    email: str,
    kind: str,
    tokens: dict | None = None,
    display_name: str = "",
    extra: dict | None = None,
    primary: bool = False,
) -> Account:
    """Register a new account (or update an existing one).

    Args:
        email:        Account email address.
        kind:         ``gmail`` | ``outlook`` | ``imap`` | ``caldav``.
        tokens:       OAuth tokens or credentials dict.
        display_name: Friendly label, e.g. "Personal Gmail".
        extra:        Provider-specific settings (IMAP host, CalDAV URL, etc.).
        primary:      Set as the default account for new emails/events.

    Returns:
        The saved :class:`Account` instance.
    """
    with db() as s:
        existing = s.query(Account).filter(Account.email == email).one_or_none()
        if existing:
            acct = existing
        else:
            acct = Account(id=email, email=email)
            s.add(acct)

        acct.kind = kind
        acct.display_name = display_name or email
        if tokens:
            acct.tokens_json = _encrypt(tokens)
        if extra:
            acct.extra_json = json.dumps(extra)
        if primary:
            # Demote any current primary
            for a in s.query(Account).filter(Account.kind == kind).all():
                a.primary = False
            acct.primary = True
        s.flush()
        s.expunge(acct)
        return acct


def list_accounts(kind: str | None = None, enabled_only: bool = True) -> list[Account]:
    """List all registered accounts.

    Args:
        kind:         Filter by provider type (optional).
        enabled_only: If True, only return enabled accounts.

    Returns:
        List of :class:`Account` objects, primary account first.
    """
    with db() as s:
        q = s.query(Account)
        if kind:
            q = q.filter(Account.kind == kind)
        if enabled_only:
            q = q.filter(Account.enabled.is_(True))
        results = q.order_by(Account.primary.desc(), Account.email).all()
        for a in results:
            s.expunge(a)
        return results


def get_account(email: str) -> Account | None:
    """Get a specific account by email address."""
    with db() as s:
        a = s.query(Account).filter(Account.email == email).one_or_none()
        if a:
            s.expunge(a)
        return a


def get_tokens(email: str) -> dict:
    """Get decrypted tokens for an account."""
    acct = get_account(email)
    if not acct:
        return {}
    return _decrypt(acct.tokens_json)


def update_tokens(email: str, tokens: dict) -> None:
    """Update stored OAuth tokens after a refresh."""
    with db() as s:
        a = s.query(Account).filter(Account.email == email).one_or_none()
        if a:
            a.tokens_json = _encrypt(tokens)
            a.last_sync_ts = time.time()


def remove_account(email: str) -> bool:
    """Remove an account and all its stored credentials."""
    with db() as s:
        a = s.query(Account).filter(Account.email == email).one_or_none()
        if a:
            s.delete(a)
            return True
        return False


def get_extra(email: str) -> dict:
    """Get the extra_json config for an account."""
    acct = get_account(email)
    if not acct:
        return {}
    try:
        return json.loads(acct.extra_json or "{}")
    except Exception:
        return {}


def get_account_secret(account_id: str) -> str:
    """Get the primary credential secret for an account (password or access token).

    For IMAP/CalDAV accounts this is the password stored in ``extra_json``.
    For OAuth accounts this is the access token.

    Args:
        account_id: The account email / id.

    Returns:
        The secret string, or empty string if not found.
    """
    tokens = get_tokens(account_id)
    if tokens:
        return tokens.get("access_token") or tokens.get("password", "")
    # Fall back to extra_json password
    extra = get_extra(account_id)
    return extra.get("password", "")


# ── Service client builders ───────────────────────────────────────────────

def gmail_service_for(email: str):
    """Return an authenticated Gmail API client for the given account.

    Handles token refresh automatically.

    Args:
        email: The Gmail account email address.

    Returns:
        Google API service object, or ``None`` if not connected.
    """
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        return None

    tokens = get_tokens(email)
    if not tokens:
        return None

    SCOPES = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/calendar",
    ]
    try:
        creds = Credentials(
            token=tokens.get("access_token"),
            refresh_token=tokens.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=tokens.get("client_id"),
            client_secret=tokens.get("client_secret"),
            scopes=SCOPES,
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            update_tokens(email, json.loads(creds.to_json()))
        return build("gmail", "v1", credentials=creds)
    except Exception as e:
        logger.warning(f"Gmail service for {email} failed: {e}")
        return None


def calendar_service_for(email: str):
    """Return an authenticated Google Calendar API client for the given account."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        return None

    tokens = get_tokens(email)
    if not tokens:
        return None

    try:
        creds = Credentials(
            token=tokens.get("access_token"),
            refresh_token=tokens.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=tokens.get("client_id"),
            client_secret=tokens.get("client_secret"),
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            update_tokens(email, json.loads(creds.to_json()))
        return build("calendar", "v3", credentials=creds)
    except Exception as e:
        logger.warning(f"Calendar service for {email} failed: {e}")
        return None


def graph_client_for(email: str):
    """Return an authenticated Microsoft Graph HTTP session for the given account.

    Returns a ``requests.Session`` with Authorization header pre-set,
    or ``None`` if the account is not connected.
    """
    tokens = get_tokens(email)
    if not tokens:
        return None

    access_token = tokens.get("access_token", "")

    # Try to refresh if we have a refresh token
    if not access_token or tokens.get("expires_at", 0) < time.time() + 60:
        access_token = _refresh_microsoft_token(email, tokens)
        if not access_token:
            return None

    try:
        import requests
        session = requests.Session()
        session.headers.update({
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        })
        return session
    except ImportError:
        return None


def _refresh_microsoft_token(email: str, tokens: dict) -> str:
    """Refresh a Microsoft OAuth2 access token using the refresh token."""
    refresh_token = tokens.get("refresh_token", "")
    if not refresh_token:
        return ""
    try:
        import httpx
        from ram.core.config import settings
        client_id = tokens.get("client_id") or getattr(settings, "microsoft_client_id", "")
        client_secret = tokens.get("client_secret") or getattr(settings, "microsoft_client_secret", "")
        tenant = tokens.get("tenant") or getattr(settings, "microsoft_tenant_id", "common")

        r = httpx.post(
            f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "https://graph.microsoft.com/.default offline_access",
            },
            timeout=15,
        )
        r.raise_for_status()
        new_tokens = r.json()
        merged = {**tokens, **new_tokens, "expires_at": time.time() + new_tokens.get("expires_in", 3600)}
        update_tokens(email, merged)
        return new_tokens.get("access_token", "")
    except Exception as e:
        logger.warning(f"Microsoft token refresh for {email} failed: {e}")
        return ""
