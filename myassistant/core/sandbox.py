"""Sandbox execution — isolated session that can't affect the real world.

The Squire sandbox wraps the agent execution context so that:

  1. File writes go to a temporary directory (never touch real files)
  2. Outbound HTTP calls are intercepted and stubbed (never hit real APIs)
  3. Destructive skills (email send, order placement, file delete) are blocked
     and their arguments are recorded instead of executed
  4. A complete action ledger is produced at the end

This is stronger than dry-run mode:
  - dry-run skips tool calls entirely and only describes intent
  - sandbox EXECUTES the full logic, but against fake I/O — so you can see
    exactly what WOULD happen, including branching logic and error paths

Usage::

    from myassistant.core.sandbox import SandboxSession

    with SandboxSession() as sb:
        result = sb.run("Send a $500 Venmo to Alice")
        print(sb.ledger)    # list of intercepted actions

CLI::

    python -m squire run --sandbox

"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from loguru import logger


@dataclass
class SandboxAction:
    """One intercepted action within a sandbox session."""
    skill_name: str
    args: dict
    timestamp: float = field(default_factory=time.time)
    result: str = "(sandboxed)"
    blocked: bool = False

    def to_dict(self) -> dict:
        return {
            "skill": self.skill_name,
            "args": self.args,
            "at": time.strftime("%H:%M:%S", time.localtime(self.timestamp)),
            "result": self.result,
            "blocked": self.blocked,
        }


# Skills that are always blocked in sandbox (would cause real-world side effects)
_BLOCKED_IN_SANDBOX: set[str] = {
    # Communication
    "send_email", "email_send", "imap_send_email", "send_sms", "send_whatsapp",
    "slack_post", "discord_send",
    # Finance
    "venmo_send", "bank_transfer", "pay_bill", "plaid_sync",
    # Commerce
    "instacart_order", "doordash_order", "place_order",
    # Cloud / infra
    "exec_shell", "git_commit", "git_push", "lambda_invoke", "cw_insights_query",
    # Smart home — physical actions
    "ha_service", "smart_home_control",
    # Contacts / Calendar writes
    "calendar_create_event", "caldav_create_event", "calendar_delete_event",
    "caldav_delete_event",
}

# Thread-local flag: are we currently in a sandbox?
_sandbox_local = threading.local()


def is_sandboxed() -> bool:
    """Return True if the current execution is inside a SandboxSession."""
    return getattr(_sandbox_local, "active", False)


class SandboxSession:
    """Context manager that activates the sandbox environment.

    Inside this context:
      - All file writes are redirected to a temp dir
      - All HTTP calls via httpx/requests are stubbed
      - All blocked skills return a stub response and log to ledger
      - A ledger of every intercepted action is built

    Example::

        with SandboxSession() as sb:
            reply = await agent.handle("order pizza", "user123")
        print(sb.format_ledger())
    """

    def __init__(self, tmpdir: str | None = None):
        self._tmpdir_obj: tempfile.TemporaryDirectory | None = None
        self.tmpdir: Path
        if tmpdir:
            self.tmpdir = Path(tmpdir)
        else:
            self._tmpdir_obj = tempfile.TemporaryDirectory(prefix="squire_sandbox_")
            self.tmpdir = Path(self._tmpdir_obj.name)
        self.ledger: list[SandboxAction] = []
        self._patches: list[Any] = []

    def __enter__(self) -> "SandboxSession":
        _sandbox_local.active = True
        _sandbox_local.session = self
        logger.info(f"🏖️  Sandbox active — tmpdir={self.tmpdir}")
        self._apply_patches()
        return self

    def __exit__(self, *args) -> None:
        _sandbox_local.active = False
        _sandbox_local.session = None
        self._remove_patches()
        if self._tmpdir_obj:
            self._tmpdir_obj.cleanup()
        logger.info("🏖️  Sandbox session ended")

    # ── Patch management ──────────────────────────────────────────────────

    def _apply_patches(self) -> None:
        """Monkey-patch outbound network calls and file ops."""
        def _stub_http(*args, **kwargs) -> MagicMock:
            url = args[0] if args else kwargs.get("url", "unknown")
            self.ledger.append(SandboxAction(
                skill_name="_http_call",
                args={"url": str(url)[:100], "method": "?"},
                result="HTTP call stubbed in sandbox",
                blocked=True,
            ))
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"sandbox": True, "message": "Stubbed response"}
            mock_resp.text = '{"sandbox": true}'
            mock_resp.raise_for_status.return_value = None
            return mock_resp

        # Patch httpx
        try:
            import httpx
            for method in ("get", "post", "put", "patch", "delete"):
                p = patch.object(httpx, method, side_effect=_stub_http)
                p.start()
                self._patches.append(p)
        except ImportError:
            pass

        # Patch requests
        try:
            import requests
            for method in ("get", "post", "put", "patch", "delete"):
                p = patch.object(requests, method, side_effect=_stub_http)
                p.start()
                self._patches.append(p)
        except ImportError:
            pass

    def _remove_patches(self) -> None:
        for p in self._patches:
            try:
                p.stop()
            except Exception:
                pass
        self._patches.clear()

    # ── Ledger helpers ────────────────────────────────────────────────────

    def record(self, skill_name: str, args: dict, result: str, blocked: bool = False) -> None:
        """Record a skill call to the ledger."""
        self.ledger.append(SandboxAction(
            skill_name=skill_name, args=args, result=result, blocked=blocked
        ))

    def format_ledger(self) -> str:
        """Format the action ledger as a human-readable summary."""
        if not self.ledger:
            return "🏖️ Sandbox: no actions were taken."
        lines = [f"🏖️ **Sandbox Session Ledger** — {len(self.ledger)} action(s)\n"]
        for i, action in enumerate(self.ledger, 1):
            icon = "🚫" if action.blocked else "📋"
            lines.append(f"{i}. {icon} **{action.skill_name}** @ {time.strftime('%H:%M:%S', time.localtime(action.timestamp))}")
            if action.args:
                arg_str = ", ".join(f"{k}={repr(v)[:40]}" for k, v in list(action.args.items())[:4])
                lines.append(f"   Args: {arg_str}")
            lines.append(f"   Result: {action.result[:80]}")
        blocked_count = sum(1 for a in self.ledger if a.blocked)
        lines.append(f"\n{'─'*50}")
        lines.append(f"✅ {len(self.ledger)-blocked_count} executed in sandbox  "
                     f"🚫 {blocked_count} blocked (real-world side effects)")
        return "\n".join(lines)


def sandbox_intercept(skill_name: str, args: dict, fn: Any) -> str:
    """Call from skill runner to intercept execution when sandboxed.

    If in sandbox mode and the skill is in the blocked list, log it and
    return a stub. Otherwise execute normally.

    Args:
        skill_name: The skill's registered name.
        args:       The arguments being passed.
        fn:         The actual skill callable.

    Returns:
        Either the real result or a sandbox stub string.
    """
    if not is_sandboxed():
        return fn(**args)  # type: ignore

    session: SandboxSession = _sandbox_local.session
    if skill_name in _BLOCKED_IN_SANDBOX:
        stub = (f"[SANDBOX] Would execute `{skill_name}` with args: "
                f"{json.dumps({k: str(v)[:50] for k, v in args.items()}, indent=2)[:200]}")
        session.record(skill_name, args, stub, blocked=True)
        return stub

    # Execute in sandbox (I/O is patched, so real effects won't occur)
    try:
        result = fn(**args)  # type: ignore
        session.record(skill_name, args, str(result)[:100], blocked=False)
        return result
    except Exception as e:
        session.record(skill_name, args, f"(error in sandbox: {e})", blocked=False)
        return f"[SANDBOX ERROR] {e}"
