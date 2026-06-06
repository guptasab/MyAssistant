"""Generic IMAP email reader and SMTP sender.

Connects to any email provider that supports IMAP + SMTP:
  - iCloud Mail (imap.mail.me.com / smtp.mail.me.com)
  - Yahoo Mail   (imap.mail.yahoo.com / smtp.mail.yahoo.com)
  - ProtonMail (via Bridge: localhost:1143 / localhost:1025)
  - Fastmail    (imap.fastmail.com / smtp.fastmail.com)
  - Zoho Mail   (imap.zoho.com / smtp.zoho.com)
  - Any corporate / custom IMAP/SMTP server

Connection details are stored in myassistant.core.accounts with extra_json::

    {
      "imap_host": "imap.mail.me.com",
      "imap_port": 993,
      "smtp_host": "smtp.mail.me.com",
      "smtp_port": 587,
      "password":  "<app-specific password>"   # stored encrypted
    }

Add an IMAP account from the admin UI or via the agent::

    "Connect my iCloud mail at me@icloud.com"
"""
from __future__ import annotations

import email as email_lib
import imaplib
import json
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from loguru import logger

from myassistant.core.registry import skill
from myassistant.core.accounts import list_accounts, get_tokens, get_extra


# ── IMAP helpers ──────────────────────────────────────────────────────────

def _imap_connect(email_addr: str) -> imaplib.IMAP4_SSL | None:
    """Open an IMAP connection for the given account."""
    extra = get_extra(email_addr)
    tokens = get_tokens(email_addr)
    host = extra.get("imap_host", "")
    port = int(extra.get("imap_port", 993))
    password = tokens.get("password", "")
    if not host or not password:
        return None
    try:
        ctx = ssl.create_default_context()
        conn = imaplib.IMAP4_SSL(host, port, ssl_context=ctx)
        conn.login(email_addr, password)
        return conn
    except Exception as e:
        logger.warning(f"IMAP connect for {email_addr} failed: {e}")
        return None


def _smtp_connect(email_addr: str):
    """Open an SMTP connection for the given account."""
    extra = get_extra(email_addr)
    tokens = get_tokens(email_addr)
    host = extra.get("smtp_host", "")
    port = int(extra.get("smtp_port", 587))
    password = tokens.get("password", "")
    if not host or not password:
        return None
    try:
        if port == 465:
            conn = smtplib.SMTP_SSL(host, port)
        else:
            conn = smtplib.SMTP(host, port)
            conn.ehlo()
            conn.starttls()
        conn.login(email_addr, password)
        return conn
    except Exception as e:
        logger.warning(f"SMTP connect for {email_addr} failed: {e}")
        return None


def _decode_msg(raw: bytes) -> dict:
    """Parse a raw RFC 2822 message into a simple dict."""
    msg = email_lib.message_from_bytes(raw)
    subject = email_lib.header.decode_header(msg.get("Subject", ""))[0][0]
    if isinstance(subject, bytes):
        subject = subject.decode(errors="replace")
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                body = part.get_payload(decode=True).decode(errors="replace")
                break
    else:
        body = msg.get_payload(decode=True).decode(errors="replace")
    return {
        "from":    msg.get("From", ""),
        "subject": subject,
        "date":    msg.get("Date", ""),
        "body":    body[:4000],
    }


# ── Skills ────────────────────────────────────────────────────────────────

@skill(
    name="imap_list_messages",
    description=(
        "List recent messages from any IMAP email account "
        "(iCloud, Yahoo, Fastmail, ProtonMail, etc.)."
    ),
    parameters={
        "account":     {"type": "string", "default": "", "description": "Email address (optional)"},
        "folder":      {"type": "string", "default": "INBOX"},
        "max_results": {"type": "integer", "default": 15},
        "unread_only": {"type": "boolean", "default": True},
    },
    requires=[],
)
def imap_list_messages(account: str = "", folder: str = "INBOX",
                        max_results: int = 15, unread_only: bool = True) -> str:
    """List messages from an IMAP inbox."""
    accounts_to_check = []
    if account:
        acct_obj = get_extra(account)
        if acct_obj:
            accounts_to_check.append(account)
    else:
        accounts_to_check = [a.email for a in list_accounts(kind="imap")]

    if not accounts_to_check:
        return "No IMAP accounts connected. Add one in Settings → Channels."

    all_lines = []
    for email_addr in accounts_to_check[:3]:   # max 3 accounts at once
        conn = _imap_connect(email_addr)
        if not conn:
            all_lines.append(f"❌ {email_addr}: could not connect")
            continue
        try:
            conn.select(folder)
            criteria = "(UNSEEN)" if unread_only else "ALL"
            _, data = conn.search(None, criteria)
            ids = data[0].split()
            ids = ids[-max_results:]  # most recent
            lines = [f"── {email_addr} ──"]
            for uid in reversed(ids[-15:]):
                _, raw = conn.fetch(uid, "(RFC822)")
                parsed = _decode_msg(raw[0][1])
                lines.append(
                    f"  {parsed['date'][:11]}  {parsed['from'][:25]:<25}  {parsed['subject'][:50]}"
                )
            all_lines.extend(lines)
        except Exception as e:
            all_lines.append(f"❌ {email_addr}: {e}")
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    return "\n".join(all_lines) if all_lines else "No messages found."


@skill(
    name="imap_send_email",
    description="Send an email via any IMAP/SMTP account (iCloud, Yahoo, Fastmail, etc.).",
    parameters={
        "to":      {"type": "string"},
        "subject": {"type": "string"},
        "body":    {"type": "string"},
        "account": {"type": "string", "default": ""},
        "dry_run": {"type": "boolean", "default": False},
    },
    requires=[],
    sensitive=True,
)
def imap_send_email(to: str, subject: str, body: str,
                     account: str = "", dry_run: bool = False) -> str:
    """Send an email via SMTP."""
    if dry_run:
        return f"DRY RUN: Would send from {account or '(default IMAP)'} to {to}\nSubject: {subject}"

    if not account:
        accounts = list_accounts(kind="imap")
        if not accounts:
            return "No IMAP accounts connected."
        account = accounts[0].email

    conn = _smtp_connect(account)
    if not conn:
        return f"Cannot connect to SMTP for {account}."

    msg = MIMEMultipart()
    msg["From"]    = account
    msg["To"]      = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        conn.sendmail(account, to.split(","), msg.as_string())
        conn.quit()
        return f"✉️ Email sent to {to} from {account}."
    except Exception as e:
        return f"ERROR: {e}"


@skill(
    name="imap_search",
    description="Search for emails matching a keyword across IMAP accounts.",
    parameters={
        "query":       {"type": "string"},
        "account":     {"type": "string", "default": ""},
        "max_results": {"type": "integer", "default": 10},
    },
    requires=[],
)
def imap_search(query: str, account: str = "", max_results: int = 10) -> str:
    """Search IMAP mailbox by subject or sender."""
    accounts_to_check = [account] if account else [a.email for a in list_accounts(kind="imap")]
    if not accounts_to_check:
        return "No IMAP accounts connected."

    all_lines = []
    for email_addr in accounts_to_check[:3]:
        conn = _imap_connect(email_addr)
        if not conn:
            continue
        try:
            conn.select("INBOX")
            _, data = conn.search(None, f'(OR SUBJECT "{query}" FROM "{query}")')
            ids = data[0].split()
            for uid in list(reversed(ids))[:max_results]:
                _, raw = conn.fetch(uid, "(RFC822)")
                parsed = _decode_msg(raw[0][1])
                all_lines.append(
                    f"{email_addr}  {parsed['date'][:10]}  {parsed['from'][:25]}  {parsed['subject'][:50]}"
                )
        except Exception as e:
            logger.debug(f"IMAP search {email_addr}: {e}")
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    return "\n".join(all_lines) if all_lines else f"No messages matching '{query}'."
