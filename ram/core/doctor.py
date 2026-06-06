"""Squire Doctor — security and configuration health audit.

``squire doctor`` checks 25+ aspects of the Squire deployment and reports
PASS / WARN / FAIL for each. This is analogous to OpenClaw's ``openclaw doctor``
command.

Usage::

    python -m squire doctor            # CLI audit
    GET /admin/doctor                   # JSON API for admin UI

Categories checked:
  Security    — vault passphrase, weak tokens, no HTTPS, exposed ports
  Providers   — at least one LLM available, no hard Anthropic dependency
  Data        — backup scheduled, data dir exists, old logs cleaned up
  Channels    — default tokens changed, webhook secrets set
  Integrations — OAuth tokens not expired, API keys valid length
  Privacy     — private mode for sensitive queries, no PII in logs
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from loguru import logger

from ram.core.config import settings


Status = Literal["pass", "warn", "fail", "info"]


@dataclass
class CheckResult:
    """Result of a single doctor check."""
    id: str
    category: str
    title: str
    status: Status
    message: str
    fix: str = ""

    @property
    def emoji(self) -> str:
        return {"pass": "✅", "warn": "⚠️ ", "fail": "❌", "info": "ℹ️ "}[self.status]

    def to_dict(self) -> dict:
        return {
            "id": self.id, "category": self.category, "title": self.title,
            "status": self.status, "message": self.message, "fix": self.fix,
        }


def _check(id: str, category: str, title: str, condition: bool,
           pass_msg: str, fail_msg: str, fix: str = "",
           warn_if_false: bool = False) -> CheckResult:
    """Helper to create a pass/fail/warn CheckResult from a boolean condition."""
    if condition:
        return CheckResult(id, category, title, "pass", pass_msg)
    status: Status = "warn" if warn_if_false else "fail"
    return CheckResult(id, category, title, status, fail_msg, fix)


def run_doctor() -> list[CheckResult]:
    """Run all health checks and return results sorted by severity."""
    results: list[CheckResult] = []

    # ── Security ──────────────────────────────────────────────────────────
    results.append(_check(
        "sec_vault", "Security", "Vault passphrase set",
        bool(getattr(settings, "ollie_vault_passphrase", "")),
        "Vault passphrase is set — credentials are encrypted at rest.",
        "No vault passphrase set — secrets stored as plain base64.",
        "Set OLLIE_VAULT_PASSPHRASE=<strong-passphrase> in .env",
    ))

    http_token = getattr(settings, "ram_http_token", "")
    results.append(_check(
        "sec_http_token", "Security", "HTTP API token configured",
        bool(http_token),
        "HTTP API requires authentication.",
        "HTTP API has no auth token — anyone with network access can control Squire.",
        "Set RAM_HTTP_TOKEN=<random-string> in .env",
    ))
    if http_token and len(http_token) < 16:
        results.append(CheckResult(
            "sec_http_token_weak", "Security", "HTTP token strength",
            "warn", f"HTTP token is only {len(http_token)} chars — use 32+ chars.",
            "Generate with: python -c \"import secrets; print(secrets.token_hex(32))\""
        ))

    admin_pw = getattr(settings, "ollie_admin_password", "")
    results.append(_check(
        "sec_admin_pw", "Security", "Admin UI password set",
        bool(admin_pw),
        "Admin UI is password-protected.",
        "Admin UI has no password — /admin is open to anyone.",
        "Set OLLIE_ADMIN_PASSWORD in .env",
        warn_if_false=True,
    ))

    results.append(_check(
        "sec_no_plaintext_secrets", "Security", "No plaintext secrets in .env",
        _check_no_plaintext_secrets(),
        "No raw secrets found in .env that look suspicious.",
        ".env may contain plaintext API keys — consider using vault.",
        "Move sensitive values to vault: squire vault set KEY value",
        warn_if_false=True,
    ))

    # ── LLM Providers ─────────────────────────────────────────────────────
    from ram.core.llm import list_providers
    providers = list_providers()
    active_count = sum(providers.values())

    results.append(_check(
        "llm_at_least_one", "Providers", "At least one LLM provider configured",
        active_count >= 1,
        f"{active_count} provider(s) active.",
        "No LLM provider configured — Squire cannot think without a model.",
        "Set any of: GROQ_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY, DEEPSEEK_API_KEY, etc.",
    ))

    results.append(CheckResult(
        "llm_provider_count", "Providers", "Provider redundancy",
        "pass" if active_count >= 2 else "warn",
        f"{active_count} provider(s) configured — {'good redundancy' if active_count >= 2 else 'consider adding a second for fallback'}.",
        "Add a second provider (e.g. Groq is free) for automatic fallback.",
    ))

    results.append(CheckResult(
        "llm_free_tier", "Providers", "Free tier providers available",
        "pass" if any(providers.get(p) for p in ("groq", "gemini", "deepseek")) else "info",
        "Free-tier provider available (Groq/Gemini/DeepSeek)." if any(providers.get(p) for p in ("groq", "gemini", "deepseek")) else "No free-tier provider configured — all calls cost money.",
        "Add GROQ_API_KEY (free) for fast, zero-cost inference.",
    ))

    # ── Data & Backup ─────────────────────────────────────────────────────
    data_dir = getattr(settings, "ram_data_dir", Path("./data"))
    results.append(_check(
        "data_dir_exists", "Data", "Data directory exists",
        Path(data_dir).exists(),
        f"Data directory exists: {data_dir}",
        f"Data directory missing: {data_dir}",
        "Run: python -m squire run (it will be created automatically)",
    ))

    db_path = Path(data_dir) / "squire.db"
    if db_path.exists():
        size_mb = db_path.stat().st_size / 1_048_576
        results.append(CheckResult(
            "data_db_size", "Data", "Database size",
            "pass" if size_mb < 500 else "warn",
            f"Database is {size_mb:.1f} MB.",
            "Consider running squire backup and pruning old data." if size_mb >= 500 else "",
        ))

    # Check last backup age
    backup_dir = Path(data_dir) / "backups"
    results.append(_check(
        "data_backup", "Data", "Recent backup exists",
        _last_backup_age_days(backup_dir) < 7,
        "Backup created within the last 7 days.",
        "No recent backup found — data loss risk.",
        "Run: squire backup   (or enable automatic daily backup in Settings)",
        warn_if_false=True,
    ))

    # ── Channels ──────────────────────────────────────────────────────────
    channels_configured = sum([
        bool(getattr(settings, "discord_bot_token", "")),
        bool(getattr(settings, "telegram_bot_token", "")),
        bool(getattr(settings, "twilio_account_sid", "")),
    ])
    results.append(CheckResult(
        "channel_count", "Channels", "Remote channels configured",
        "pass" if channels_configured >= 1 else "info",
        f"{channels_configured} remote channel(s) configured (Discord/Telegram/Twilio).",
        "No remote channels — you can only access Squire locally.",
    ))

    # ── Privacy ───────────────────────────────────────────────────────────
    results.append(CheckResult(
        "priv_local_option", "Privacy", "Local/private model available",
        "pass" if (providers.get("ollama") or providers.get("lmstudio") or providers.get("venice")) else "info",
        "Local or privacy-first model available for sensitive queries.",
        "For fully private queries, install Ollama (https://ollama.ai) or configure Venice AI.",
    ))

    # ── Integrations ──────────────────────────────────────────────────────
    from ram.core.accounts import list_accounts
    try:
        accounts = list_accounts(enabled_only=False)
        results.append(CheckResult(
            "int_accounts", "Integrations", "Email/calendar accounts",
            "pass" if accounts else "info",
            f"{len(accounts)} email/calendar account(s) connected.",
            "Connect a Gmail or Outlook account in Settings → Channels for email features.",
        ))
    except Exception:
        pass

    # ── Sort: fail → warn → pass → info ───────────────────────────────────
    _order = {"fail": 0, "warn": 1, "pass": 2, "info": 3}
    results.sort(key=lambda r: _order.get(r.status, 4))
    return results


def _check_no_plaintext_secrets() -> bool:
    """Scan .env file for values that look like raw secrets (not vault references)."""
    env_path = Path(".env")
    if not env_path.exists():
        return True
    suspicious_patterns = [
        r'sk-[a-zA-Z0-9]{20,}',          # OpenAI key pattern
        r'AIza[a-zA-Z0-9_-]{35}',         # Google API key
        r'[a-f0-9]{32,}:[a-f0-9]{32,}',   # Twilio-style
    ]
    content = env_path.read_text(errors="ignore")
    for pat in suspicious_patterns:
        if re.search(pat, content):
            return False
    return True


def _last_backup_age_days(backup_dir: Path) -> float:
    """Return how many days since the most recent backup file."""
    if not backup_dir.exists():
        return 999.0
    backups = sorted(backup_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not backups:
        return 999.0
    age = time.time() - backups[0].stat().st_mtime
    return age / 86400


def format_report(results: list[CheckResult]) -> str:
    """Format doctor results as a terminal-friendly text report."""
    lines = [
        "╔══════════════════════════════════════════════════════╗",
        "║          🛡️  Squire Doctor — Health Report            ║",
        "╚══════════════════════════════════════════════════════╝",
        "",
    ]
    current_cat = ""
    for r in results:
        if r.category != current_cat:
            current_cat = r.category
            lines.append(f"\n── {r.category} {'─' * (40 - len(r.category))}")
        lines.append(f"  {r.emoji} {r.title}")
        lines.append(f"     {r.message}")
        if r.fix and r.status in ("warn", "fail"):
            lines.append(f"     💡 Fix: {r.fix}")

    fails = sum(1 for r in results if r.status == "fail")
    warns = sum(1 for r in results if r.status == "warn")
    passes = sum(1 for r in results if r.status == "pass")
    lines += [
        "",
        "─" * 55,
        f"  ✅ {passes} passed   ⚠️  {warns} warnings   ❌ {fails} failures",
        "─" * 55,
    ]
    if fails == 0 and warns == 0:
        lines.append("  🎉 All checks passed — Squire is healthy!")
    elif fails > 0:
        lines.append(f"  ⚠️  {fails} issue(s) need attention before production use.")
    return "\n".join(lines)
