"""Interactive first-run onboarding wizard for Squire.

Guides a non-technical user through:
  1. Choosing an LLM provider (with free-tier recommendations)
  2. Testing the AI connection
  3. Connecting Gmail / Calendar (optional OAuth flow)
  4. Connecting a messaging channel (WhatsApp / Telegram / SMS)
  5. Setting up a daily briefing time
  6. Sending a test message to verify everything works

Run via:  python -m squire onboard
"""
from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path
from typing import Optional

# ── ANSI colours (work on Windows 10+ and all Unix terminals) ────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
BLUE   = "\033[94m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
DIM    = "\033[2m"


def _c(color: str, text: str) -> str:
    """Wrap *text* in an ANSI colour code."""
    return f"{color}{text}{RESET}"


def _h(text: str) -> None:
    """Print a bold header line."""
    print(f"\n{BOLD}{BLUE}{'─' * 56}{RESET}")
    print(f"{BOLD}{BLUE}  {text}{RESET}")
    print(f"{BOLD}{BLUE}{'─' * 56}{RESET}\n")


def _ok(text: str) -> None:
    print(f"  {_c(GREEN, '✓')}  {text}")


def _warn(text: str) -> None:
    print(f"  {_c(YELLOW, '⚠')}  {text}")


def _step(n: int, total: int, text: str) -> None:
    print(f"\n{_c(CYAN, f'Step {n}/{total}:')} {BOLD}{text}{RESET}")


def _ask(prompt: str, default: str = "") -> str:
    """Prompt the user for input, returning *default* if they press Enter."""
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"  {_c(CYAN, '→')} {prompt}{suffix}: ").strip()
        return val or default
    except (KeyboardInterrupt, EOFError):
        print()
        return default


def _confirm(prompt: str, default: bool = True) -> bool:
    """Prompt for yes/no confirmation."""
    yn = "Y/n" if default else "y/N"
    try:
        raw = input(f"  {_c(CYAN, '→')} {prompt} ({yn}): ").strip().lower()
        if not raw:
            return default
        return raw.startswith("y")
    except (KeyboardInterrupt, EOFError):
        print()
        return default


def _choose(prompt: str, options: list[tuple[str, str]], default: int = 0) -> int:
    """
    Present a numbered menu and return the chosen index.

    *options* is a list of (label, description) tuples.
    """
    print(f"\n  {prompt}")
    for i, (label, desc) in enumerate(options):
        marker = _c(GREEN, "►") if i == default else " "
        print(f"  {marker} {_c(BOLD, str(i + 1))}. {label}")
        if desc:
            print(f"       {_c(DIM, desc)}")
    while True:
        try:
            raw = input(f"\n  {_c(CYAN, '→')} Choose (1-{len(options)}) [{default + 1}]: ").strip()
            if not raw:
                return default
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return idx
        except (ValueError, KeyboardInterrupt, EOFError):
            return default


# ── .env helpers ─────────────────────────────────────────────────────────────

def _find_env_file() -> Path:
    """Return the .env path next to the project root."""
    # Walk up from this file to find the root (contains requirements.txt)
    here = Path(__file__).resolve()
    for parent in [here.parent.parent.parent, here.parent.parent, Path.cwd()]:
        candidate = parent / ".env"
        if (parent / "requirements.txt").exists():
            return candidate
    return Path.cwd() / ".env"


def _read_env(path: Path) -> dict[str, str]:
    """Parse a .env file into a dict (ignores comments, blank lines)."""
    env: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _write_env(path: Path, env: dict[str, str]) -> None:
    """Write a dict back as a .env file, preserving existing comments."""
    lines: list[str] = []
    existing_keys: set[str] = set()

    # Preserve existing content (comments, ordering)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k = stripped.partition("=")[0].strip()
                if k in env:
                    lines.append(f"{k}={env[k]}")
                    existing_keys.add(k)
                else:
                    lines.append(line)
            else:
                lines.append(line)

    # Append new keys that weren't in the original file
    new_keys = [k for k in env if k not in existing_keys]
    if new_keys:
        lines.append("")
        lines.append("# Added by squire onboard")
        for k in new_keys:
            lines.append(f"{k}={env[k]}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _ok(f"Saved to {path}")


# ── Individual setup steps ────────────────────────────────────────────────────

def _setup_llm(env: dict[str, str]) -> bool:
    """Step 1 — Choose and configure an LLM provider."""
    _step(1, 6, "AI Provider (the 'brain' of your assistant)")

    print(
        "  Your assistant needs an AI model to think. All options below work great.\n"
        "  Free options are highlighted — no credit card needed to start.\n"
    )

    providers = [
        ("Groq  🆓 FREE",        "groq.com — blazing fast, free tier, Llama 3 & Mixtral"),
        ("Gemini  🆓 FREE",      "aistudio.google.com — Google's AI, generous free tier"),
        ("DeepSeek  💲 ~$0.001", "platform.deepseek.com — very cheap, excellent quality"),
        ("OpenRouter  🆓/💲",    "openrouter.ai — access 100+ models from one API key"),
        ("OpenAI  💲",           "platform.openai.com — GPT-4o, well-known"),
        ("Ollama  🖥️ LOCAL",     "Run models privately on your own machine — no key needed"),
        ("Skip for now",          "I'll configure this manually later"),
    ]

    idx = _choose("Which provider would you like to use?", providers, default=0)

    key_map = {
        0: ("GROQ_API_KEY",       "https://console.groq.com/keys"),
        1: ("GEMINI_API_KEY",     "https://aistudio.google.com/app/apikey"),
        2: ("DEEPSEEK_API_KEY",   "https://platform.deepseek.com/api_keys"),
        3: ("OPENROUTER_API_KEY", "https://openrouter.ai/keys"),
        4: ("OPENAI_API_KEY",     "https://platform.openai.com/api-keys"),
        5: None,  # Ollama — no key
        6: None,  # Skip
    }

    entry = key_map.get(idx)
    if entry is None and idx == 5:
        _ok("Ollama selected — no API key needed. Make sure Ollama is running locally.")
        env["OLLAMA_BASE_URL"] = _ask("Ollama URL", "http://localhost:11434")
        return True
    if entry is None:
        _warn("Skipped — remember to add a provider key to .env before running Squire.")
        return False

    key_name, url = entry
    existing = env.get(key_name, "")
    if existing:
        _ok(f"{key_name} already set.")
        return True

    if _confirm(f"Open {url} in your browser to get a free API key?"):
        webbrowser.open(url)
        print(f"  {_c(DIM, '(page opened in your browser)')}")

    key_val = _ask(f"Paste your {key_name} here (or press Enter to skip)")
    if key_val:
        env[key_name] = key_val
        _ok(f"{key_name} saved.")
        return True
    else:
        _warn("No key entered — you can add it to .env later.")
        return False


def _test_llm(env: dict[str, str]) -> bool:
    """Quick test that the configured LLM actually responds."""
    # Apply env vars to current process so the LLM module sees them
    for k, v in env.items():
        os.environ.setdefault(k, v)

    try:
        from ram.core.llm import llm_chat, list_providers
        active = {k: v for k, v in list_providers().items() if v}
        if not active:
            _warn("No active providers — skipping LLM test.")
            return False
        print(f"\n  Testing AI ({', '.join(active.keys())})…")
        resp = llm_chat([{"role": "user", "content": "Say exactly: Hello from Squire!"}])
        _ok(f"AI responded: {resp.strip()[:80]}")
        return True
    except Exception as e:
        _warn(f"AI test failed: {e}")
        return False


def _setup_email(env: dict[str, str]) -> bool:
    """Step 2 — Connect Gmail (optional)."""
    _step(2, 6, "Email & Calendar (optional but very powerful)")

    print(
        "  Squire can read your emails, triage them by importance, draft\n"
        "  replies in your style, and manage your calendar.\n"
    )

    if not _confirm("Connect Gmail / Google Calendar?", default=True):
        _warn("Skipped — you can connect via the admin panel later.")
        return False

    from pathlib import Path as _P
    try:
        from ram.core.config import settings
        token_path = settings.ram_data_dir / "google_token.json"
    except Exception:
        token_path = _P.home() / ".squire" / "google_token.json"

    if token_path.exists():
        _ok("Gmail already connected!")
        return True

    print(
        "\n  Squire will open Google's permission screen.\n"
        "  Allow access to Gmail + Calendar. Your data stays on your machine.\n"
    )
    if _confirm("Open Google login now?"):
        try:
            from ram.skills.gmail_skill import _get_gmail_service
            _get_gmail_service()
            _ok("Gmail + Calendar connected!")
            return True
        except Exception as e:
            _warn(f"OAuth failed: {e}. You can retry from the admin panel.")
            return False
    return False


def _setup_channel(env: dict[str, str]) -> bool:
    """Step 3 — Connect a messaging channel (reach Squire remotely)."""
    _step(3, 6, "Messaging Channel (reach Squire from anywhere)")

    print(
        "  Connect a channel so you can message Squire from your phone\n"
        "  even when away from your computer.\n"
    )

    channels = [
        ("Telegram  📱 Easiest",   "Free, instant setup — recommended for most users"),
        ("WhatsApp  📱",           "Requires Twilio account (paid, ~$1/mo)"),
        ("Discord   💬",           "Great if you already use Discord"),
        ("SMS / Text  📟",         "Requires Twilio account"),
        ("Skip — use web chat only", ""),
    ]

    idx = _choose("Which channel do you want to use?", channels, default=0)

    if idx == 0:  # Telegram
        existing = env.get("TELEGRAM_BOT_TOKEN", "")
        if existing:
            _ok("Telegram already configured.")
            return True
        if _confirm("Open BotFather on Telegram to create your bot?"):
            webbrowser.open("https://t.me/BotFather")
            print(f"  {_c(DIM, 'Send /newbot to BotFather and follow the steps.')}")
        token = _ask("Paste your Telegram Bot Token")
        if token:
            env["TELEGRAM_BOT_TOKEN"] = token
            _ok("Telegram bot token saved.")
            return True

    elif idx == 1:  # WhatsApp
        print(
            f"  {_c(DIM, 'You need a Twilio account. Visit twilio.com/try-twilio')}"
        )
        if _confirm("Open Twilio sign-up page?"):
            webbrowser.open("https://www.twilio.com/try-twilio")
        sid = _ask("Twilio Account SID (from twilio.com/console)")
        tok = _ask("Twilio Auth Token")
        frm = _ask("WhatsApp-enabled number (e.g. whatsapp:+14155238886)")
        if sid and tok and frm:
            env["TWILIO_ACCOUNT_SID"] = sid
            env["TWILIO_AUTH_TOKEN"]  = tok
            env["TWILIO_SMS_FROM"]    = frm
            _ok("Twilio / WhatsApp configured.")
            return True

    elif idx == 2:  # Discord
        existing = env.get("DISCORD_BOT_TOKEN", "")
        if existing:
            _ok("Discord already configured.")
            return True
        if _confirm("Open Discord Developer Portal to create your bot?"):
            webbrowser.open("https://discord.com/developers/applications")
        token = _ask("Paste your Discord Bot Token")
        if token:
            env["DISCORD_BOT_TOKEN"] = token
            _ok("Discord bot token saved.")
            return True

    elif idx == 3:  # SMS
        sid = _ask("Twilio Account SID")
        tok = _ask("Twilio Auth Token")
        frm = _ask("Twilio phone number (e.g. +14155238886)")
        if sid and tok and frm:
            env["TWILIO_ACCOUNT_SID"] = sid
            env["TWILIO_AUTH_TOKEN"]  = tok
            env["TWILIO_SMS_FROM"]    = frm
            _ok("SMS configured.")
            return True

    _warn("Skipped — you can configure channels from the admin panel later.")
    return False


def _setup_briefing(env: dict[str, str]) -> bool:
    """Step 4 — Daily briefing preferences."""
    _step(4, 6, "Daily Briefing (Squire's morning summary)")

    print(
        "  Every morning Squire can send you a personalised briefing with:\n"
        "  today's calendar, important emails, tasks, weather, and more.\n"
    )

    if not _confirm("Enable daily briefing?", default=True):
        _warn("Skipped.")
        return False

    time_str = _ask("What time should the briefing arrive?", "07:30")
    env["RAM_BRIEFING_TIME"] = time_str

    name = _ask("What's your first name? (Squire will use this)")
    if name:
        env["RAM_OWNER_NAME"] = name

    city = _ask("Your city (for weather)? e.g. San Francisco")
    if city:
        env["SQUIRE_DEFAULT_CITY"] = city

    _ok(f"Daily briefing set for {time_str}.")
    return True


def _setup_http(env: dict[str, str]) -> bool:
    """Step 5 — HTTP server token for the web/admin UI."""
    _step(5, 6, "Web Interface Security")

    print(
        "  The Squire web interface (admin panel + mobile PWA) can be secured\n"
        "  with a password so only you can access it.\n"
    )

    existing = env.get("RAM_HTTP_TOKEN", "")
    if existing:
        _ok("HTTP token already set.")
        return True

    if _confirm("Set a password for the web interface?", default=True):
        import secrets
        suggested = secrets.token_urlsafe(12)
        token = _ask("Choose a password", suggested)
        if token:
            env["RAM_HTTP_TOKEN"] = token
            _ok("Web interface password saved.")
            return True

    _warn("No password set — the web interface will be open to anyone on your network.")
    return False


def _final_test(env: dict[str, str]) -> None:
    """Step 6 — Send a test message through the agent."""
    _step(6, 6, "First Message — let's make sure everything works")

    for k, v in env.items():
        os.environ[k] = v

    try:
        import asyncio
        from ram.core import registry
        from ram.core.agent import get_agent

        registry.discover()
        agent = get_agent()

        async def _test():
            name = env.get("RAM_OWNER_NAME", "")
            greeting = f"Hi {name}!" if name else "Hi!"
            return await agent.handle(
                f"{greeting} I just set up Squire. Give me a quick intro to what you can do for me.",
                "onboard"
            )

        print("  Asking Squire to introduce itself…\n")
        reply = asyncio.run(_test())
        print(f"  {_c(GREEN, BOLD + 'Squire says:' + RESET)}\n")
        # Word-wrap at 70 chars
        words = reply.text.split()
        line  = "  "
        for w in words:
            if len(line) + len(w) + 1 > 72:
                print(line)
                line = "  " + w + " "
            else:
                line += w + " "
        if line.strip():
            print(line)
        print()
        _ok("First message succeeded! Squire is ready. 🎉")
    except Exception as e:
        _warn(f"Test message failed: {e}")
        print(f"  {_c(DIM, 'This usually means a provider key is missing or incorrect.')}")
        print(f"  {_c(DIM, 'Run `squire doctor` to diagnose, or edit .env and try again.')}")


# ── Mark setup complete ───────────────────────────────────────────────────────

def _mark_complete(env_path: Path) -> None:
    """Write a sentinel file so future runs skip the auto-onboard prompt."""
    sentinel = env_path.parent / ".squire_setup_complete"
    sentinel.touch()


# ── Main entry point ──────────────────────────────────────────────────────────

def run_wizard(skip_existing: bool = False) -> None:
    """
    Run the full interactive onboarding wizard.

    Parameters
    ----------
    skip_existing:
        If True, quietly skip any step whose key is already configured.
    """
    # ── Welcome banner ────────────────────────────────────────────────────
    print()
    print(_c(BOLD, "  ╔══════════════════════════════════════════════════════╗"))
    # Read agent name from .env if already set, default to Squire
    _env_pre = _read_env(_find_env_file())
    _agent   = _env_pre.get("SQUIRE_AGENT_NAME", "Squire")
    _site    = _env_pre.get("SQUIRE_AGENT_WEBSITE", "mysquire.ai")
    banner_name = f"Welcome to {_agent}".center(52)
    banner_site = _site.center(52)
    print(_c(BOLD, "  ║") + _c(BLUE + BOLD, banner_name) + _c(BOLD, "║"))
    print(_c(BOLD, "  ║") + _c(DIM,          banner_site) + _c(BOLD, "║"))
    print(_c(BOLD, "  ╚══════════════════════════════════════════════════════╝"))
    print()
    print(
        "  This wizard takes about 3 minutes and sets up everything\n"
        "  you need to start using Squire.\n"
        "\n"
        "  Press Ctrl+C at any time to exit — progress is saved after\n"
        "  each step.\n"
    )

    env_path = _find_env_file()
    env      = _read_env(env_path)

    if _c("", "") and not _confirm("Ready to begin?", default=True):
        print("\n  Run `squire onboard` again whenever you're ready.\n")
        return

    results: dict[str, bool] = {}

    # ── Run each step ─────────────────────────────────────────────────────
    results["llm"]      = _setup_llm(env)
    _write_env(env_path, env)

    if results["llm"]:
        results["llm_test"] = _test_llm(env)

    results["email"]    = _setup_email(env)
    _write_env(env_path, env)

    results["channel"]  = _setup_channel(env)
    _write_env(env_path, env)

    results["briefing"] = _setup_briefing(env)
    _write_env(env_path, env)

    results["http"]     = _setup_http(env)
    _write_env(env_path, env)

    _final_test(env)

    # ── Summary ───────────────────────────────────────────────────────────
    _h("Setup Summary")

    labels = {
        "llm":      "AI provider",
        "llm_test": "AI connection test",
        "email":    "Gmail / Calendar",
        "channel":  "Messaging channel",
        "briefing": "Daily briefing",
        "http":     "Web UI password",
    }

    for key, label in labels.items():
        val = results.get(key, False)
        icon = _c(GREEN, "✓") if val else _c(YELLOW, "○")
        print(f"  {icon}  {label}")

    _mark_complete(env_path)

    print()
    print("  " + _c(BOLD, "Next steps:"))
    print(f"  • Start Squire:      {_c(CYAN, 'python -m squire run --channel all')}")
    print(f"  • Web admin panel:   {_c(CYAN, 'http://localhost:8000/admin')}")
    print(f"  • Mobile PWA:        {_c(CYAN, 'http://localhost:8000/pwa/')}")
    print(f"  • Health check:      {_c(CYAN, 'python -m squire doctor')}")
    print()


def needs_onboard() -> bool:
    """
    Return True if no provider is configured and the setup sentinel is absent.

    Called at startup to prompt first-time users to run the wizard.
    """
    env_path  = _find_env_file()
    sentinel  = env_path.parent / ".squire_setup_complete"
    if sentinel.exists():
        return False

    # Check if any provider key is present in .env OR environment
    provider_keys = [
        "GROQ_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "OPENROUTER_API_KEY",
        "FIREWORKS_API_KEY", "CEREBRAS_API_KEY", "VENICE_API_KEY",
        "OLLAMA_BASE_URL",
    ]
    env = _read_env(env_path)
    for k in provider_keys:
        if env.get(k) or os.environ.get(k):
            return False

    return True
