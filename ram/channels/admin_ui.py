"""Full-featured admin + configuration web UI for Ram.

Routes:
  GET  /admin                   — Main SPA (all config tabs)
  GET  /admin/config            — Current settings as JSON (keys masked)
  POST /admin/config            — Save key=value pairs → writes .env
  POST /admin/test/provider     — Test an LLM provider connection
  POST /admin/test/channel      — Test a messaging channel
  POST /admin/skill/toggle      — Enable/disable a skill (via permissions)
  GET  /admin/audit             — Recent audit log (JSON)
  GET  /admin/skills            — All skills (JSON)
  POST /admin/backup            — Create backup zip
  POST /admin/revoke/{resource} — Revoke a local resource (clear its env vars)

iOS Shortcuts:
  GET/POST /shortcut/ask        — Plain text in/out
  GET      /shortcut/briefing   — Morning briefing text
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse

from ram.core.config import settings

# ── env file path ──────────────────────────────────────────────────────────
_ENV_FILE = Path(".env")

# Map of field name → display metadata (label, group, type, help)
_FIELDS: list[dict] = [
    # ── Profile ──────────────────────────────────────────────────────────
    {"key": "squire_agent_name",      "label": "Assistant Name",           "group": "profile",    "type": "text",   "help": "Sets the name in UI, wake word, and system prompt (e.g. Squire, Aria, Max)"},
    {"key": "squire_agent_website",   "label": "Assistant Website",        "group": "profile",    "type": "text",   "help": "e.g. mysquire.ai"},
    {"key": "ram_owner_name",         "label": "Your Name",                "group": "profile",    "type": "text"},
    {"key": "ram_timezone",           "label": "Timezone (e.g. US/Pacific)","group": "profile",   "type": "text"},
    {"key": "ram_data_dir",           "label": "Data Directory",           "group": "profile",    "type": "text"},
    {"key": "ollie_briefing_time",    "label": "Morning Briefing Time",    "group": "profile",    "type": "text",  "help": "HH:MM 24h"},
    {"key": "ollie_evening_brief_time","label": "Evening Briefing Time",   "group": "profile",    "type": "text",  "help": "HH:MM 24h"},
    {"key": "ollie_default_context",  "label": "Default Context",          "group": "profile",    "type": "select","options": ["personal", "family", "work"]},
    {"key": "ram_model_main",         "label": "Main Model ID",            "group": "profile",    "type": "text",  "help": "e.g. claude-opus-4-7"},
    {"key": "ram_model_fast",         "label": "Fast Model ID",            "group": "profile",    "type": "text"},
    # ── AI Providers ─────────────────────────────────────────────────────
    {"key": "anthropic_api_key",      "label": "Anthropic API Key",        "group": "ai",         "type": "secret", "test": "anthropic"},
    {"key": "openai_api_key",         "label": "OpenAI API Key",           "group": "ai",         "type": "secret", "test": "openai"},
    {"key": "google_api_key",         "label": "Google / Gemini API Key",  "group": "ai",         "type": "secret", "test": "google"},
    {"key": "gemini_api_key",         "label": "Gemini API Key (alt)",     "group": "ai",         "type": "secret"},
    {"key": "perplexity_api_key",     "label": "Perplexity API Key",       "group": "ai",         "type": "secret", "test": "perplexity"},
    {"key": "groq_api_key",           "label": "Groq API Key",             "group": "ai",         "type": "secret", "test": "groq"},
    {"key": "mistral_api_key",        "label": "Mistral API Key",          "group": "ai",         "type": "secret"},
    {"key": "together_api_key",       "label": "Together.ai API Key",      "group": "ai",         "type": "secret"},
    {"key": "azure_openai_api_key",   "label": "Azure OpenAI API Key",     "group": "ai",         "type": "secret", "test": "azure"},
    {"key": "azure_openai_endpoint",  "label": "Azure OpenAI Endpoint",    "group": "ai",         "type": "text"},
    {"key": "azure_openai_api_version","label": "Azure API Version",       "group": "ai",         "type": "text"},
    {"key": "azure_openai_deployment","label": "Azure Deployment Name",    "group": "ai",         "type": "text"},
    {"key": "aws_access_key_id",      "label": "AWS Access Key ID",        "group": "ai",         "type": "secret", "test": "aws"},
    {"key": "aws_secret_access_key",  "label": "AWS Secret Access Key",    "group": "ai",         "type": "secret"},
    {"key": "aws_region",             "label": "AWS Region",               "group": "ai",         "type": "text",  "help": "e.g. us-east-1"},
    {"key": "ollama_base_url",        "label": "Ollama Base URL",          "group": "ai",         "type": "text",  "help": "http://localhost:11434", "test": "ollama"},
    # New providers (no Anthropic needed)
    {"key": "deepseek_api_key",       "label": "DeepSeek API Key",         "group": "ai",         "type": "secret", "help": "platform.deepseek.com — best value code+reasoning"},
    {"key": "fireworks_api_key",      "label": "Fireworks AI API Key",     "group": "ai",         "type": "secret", "help": "fireworks.ai — fast open-model inference"},
    {"key": "openrouter_api_key",     "label": "OpenRouter API Key",       "group": "ai",         "type": "secret", "help": "openrouter.ai — 100+ models via one key"},
    {"key": "cerebras_api_key",       "label": "Cerebras API Key",         "group": "ai",         "type": "secret", "help": "cerebras.ai — world's fastest inference"},
    {"key": "lmstudio_base_url",      "label": "LM Studio Base URL",       "group": "ai",         "type": "text",   "help": "http://localhost:1234 — fully private local AI"},
    {"key": "venice_api_key",         "label": "Venice AI API Key",        "group": "ai",         "type": "secret", "help": "venice.ai — privacy-first, no conversation logging"},
    {"key": "mcp_servers",            "label": "MCP Servers",              "group": "ai",         "type": "text",   "help": "Comma-separated: stdio:///path or http://host:port"},
    # ── Channels ─────────────────────────────────────────────────────────
    {"key": "twilio_account_sid",     "label": "Twilio Account SID",       "group": "channels",   "type": "secret", "test": "twilio"},
    {"key": "twilio_auth_token",      "label": "Twilio Auth Token",        "group": "channels",   "type": "secret"},
    {"key": "twilio_sms_from",        "label": "Twilio SMS From Number",   "group": "channels",   "type": "text",  "help": "+1XXXXXXXXXX"},
    {"key": "twilio_whatsapp_from",   "label": "Twilio WhatsApp From",     "group": "channels",   "type": "text",  "help": "whatsapp:+14155238886"},
    {"key": "twilio_voice_from",      "label": "Twilio Voice From",        "group": "channels",   "type": "text"},
    {"key": "discord_bot_token",      "label": "Discord Bot Token",        "group": "channels",   "type": "secret", "test": "discord"},
    {"key": "discord_owner_user_id",  "label": "Discord Owner User ID",    "group": "channels",   "type": "text"},
    {"key": "telegram_bot_token",     "label": "Telegram Bot Token",       "group": "channels",   "type": "secret", "test": "telegram"},
    {"key": "telegram_owner_chat_id", "label": "Telegram Owner Chat ID",   "group": "channels",   "type": "text"},
    {"key": "bluebubbles_url",        "label": "BlueBubbles URL (iMessage)","group": "channels",  "type": "text"},
    {"key": "bluebubbles_password",   "label": "BlueBubbles Password",     "group": "channels",   "type": "secret"},
    {"key": "ram_http_host",          "label": "HTTP Host",                "group": "channels",   "type": "text"},
    {"key": "ram_http_port",          "label": "HTTP Port",                "group": "channels",   "type": "text"},
    {"key": "ram_http_token",         "label": "HTTP Bearer Token",        "group": "channels",   "type": "secret"},
    # ── Safety & Security ────────────────────────────────────────────────
    {"key": "ollie_admin_password",   "label": "Admin UI Password",        "group": "safety",     "type": "secret"},
    {"key": "ollie_vault_passphrase", "label": "Vault Encryption Passphrase","group": "safety",   "type": "secret"},
    {"key": "ollie_deadman_hours",    "label": "Deadman Switch Hours",     "group": "safety",     "type": "text",  "help": "Alert if no activity for N hours"},
    {"key": "ollie_deadman_contact",  "label": "Deadman Alert Contact",    "group": "safety",     "type": "text",  "help": "+1XXXXXXXXXX"},
    # ── Local Resources ──────────────────────────────────────────────────
    {"key": "ram_repo_workspace",     "label": "Repo Workspace Path",      "group": "resources",  "type": "text",  "help": "Local path where repos are cloned"},
    {"key": "ram_shell_allowlist",    "label": "Shell Allowlist (extra)",  "group": "resources",  "type": "text",  "help": "Comma-separated command prefixes"},
    {"key": "ram_shell_timeout",      "label": "Shell Timeout (seconds)",  "group": "resources",  "type": "text"},
    {"key": "ha_base_url",            "label": "Home Assistant URL",       "group": "resources",  "type": "text",  "test": "ha"},
    {"key": "ha_token",               "label": "Home Assistant Token",     "group": "resources",  "type": "secret"},
    {"key": "google_maps_api_key",    "label": "Google Maps API Key",      "group": "resources",  "type": "secret"},
    {"key": "brave_search_api_key",   "label": "Brave Search API Key",     "group": "resources",  "type": "secret"},
    {"key": "tavily_api_key",         "label": "Tavily API Key",           "group": "resources",  "type": "secret"},
    # ── Integrations ─────────────────────────────────────────────────────
    {"key": "github_token",           "label": "GitHub Personal Access Token","group": "integrations","type": "secret","test": "github"},
    {"key": "github_default_repo",    "label": "Default GitHub Repo",     "group": "integrations","type": "text",  "help": "owner/repo"},
    {"key": "notion_api_key",         "label": "Notion API Key",           "group": "integrations","type": "secret","test": "notion"},
    {"key": "linear_api_key",         "label": "Linear API Key",           "group": "integrations","type": "secret"},
    {"key": "slack_bot_token",        "label": "Slack Bot Token",          "group": "integrations","type": "secret","test": "slack"},
    {"key": "slack_user_id",          "label": "Slack User ID",            "group": "integrations","type": "text"},
    {"key": "plaid_client_id",        "label": "Plaid Client ID",          "group": "integrations","type": "secret"},
    {"key": "plaid_secret",           "label": "Plaid Secret",             "group": "integrations","type": "secret"},
    {"key": "plaid_env",              "label": "Plaid Environment",        "group": "integrations","type": "select","options": ["sandbox", "development", "production"]},
    {"key": "fitbit_client_id",       "label": "Fitbit Client ID",         "group": "integrations","type": "text"},
    {"key": "fitbit_client_secret",   "label": "Fitbit Client Secret",     "group": "integrations","type": "secret"},
    {"key": "oura_access_token",      "label": "Oura Access Token",        "group": "integrations","type": "secret"},
    {"key": "elevenlabs_api_key",     "label": "ElevenLabs API Key",       "group": "integrations","type": "secret"},
    {"key": "elevenlabs_voice_id",    "label": "ElevenLabs Voice ID",      "group": "integrations","type": "text"},
    {"key": "aviationstack_key",      "label": "AviationStack API Key",    "group": "integrations","type": "secret"},
    {"key": "instacart_api_key",      "label": "Instacart API Key",        "group": "integrations","type": "secret"},
    {"key": "doordash_developer_key", "label": "DoorDash Developer Key",   "group": "integrations","type": "secret"},
    {"key": "ring_email",             "label": "Ring Account Email",       "group": "integrations","type": "text"},
    {"key": "ring_password",          "label": "Ring Account Password",    "group": "integrations","type": "secret"},
    # Location
    {"key": "squire_home_address",    "label": "Home Address",             "group": "location",   "type": "text",  "help": "Used for location-aware features"},
    {"key": "squire_work_address",    "label": "Work Address",             "group": "location",   "type": "text"},
    {"key": "squire_default_city",    "label": "Default City",             "group": "location",   "type": "text",  "help": "Fallback when GPS unavailable"},
    {"key": "ipinfo_token",           "label": "IPInfo Token",             "group": "location",   "type": "secret","help": "ipinfo.io — IP geolocation (free tier available)"},
    {"key": "google_maps_api_key",    "label": "Google Maps API Key",      "group": "location",   "type": "secret"},
    # Voice assistants
    {"key": "alexa_skill_id",         "label": "Alexa Skill ID",           "group": "voice",      "type": "text",  "help": "From Alexa Developer Console"},
    {"key": "google_action_project_id","label": "Google Action Project ID","group": "voice",      "type": "text",  "help": "From Google Actions Console"},
    # Microsoft
    {"key": "microsoft_client_id",    "label": "Microsoft App Client ID",  "group": "integrations","type": "text",  "help": "For Outlook + Teams integration"},
    {"key": "microsoft_client_secret","label": "Microsoft App Secret",     "group": "integrations","type": "secret"},
    {"key": "microsoft_tenant_id",    "label": "Microsoft Tenant ID",      "group": "integrations","type": "text",  "help": "Leave as 'common' for personal accounts"},
    # ── Memory ────────────────────────────────────────────────────────────
    {"key": "memory_enabled",         "label": "Enable Memory",            "group": "memory",     "type": "bool",  "help": "Set false to disable all conversation persistence"},
    {"key": "memory_retention_days",  "label": "Retention (days)",         "group": "memory",     "type": "text",  "help": "How long to keep conversation history before compressing"},
    {"key": "memory_context_messages","label": "Context Window (messages)","group": "memory",     "type": "text",  "help": "Max messages loaded per LLM call (default 50)"},
    {"key": "memory_auto_learn",      "label": "Auto-learn Facts",         "group": "memory",     "type": "bool",  "help": "Automatically extract preferences and facts from conversations"},
    {"key": "memory_incognito_default","label": "Incognito by Default",    "group": "memory",     "type": "bool",  "help": "When ON, nothing is saved unless user explicitly disables incognito"},
]

_GROUP_META = {
    "profile":      {"icon": "👤", "title": "Profile & Preferences"},
    "ai":           {"icon": "🧠", "title": "AI Providers"},
    "channels":     {"icon": "📡", "title": "Channels (WhatsApp, Discord, SMS…)"},
    "safety":       {"icon": "🔒", "title": "Safety & Security"},
    "resources":    {"icon": "💻", "title": "Local Resources"},
    "integrations": {"icon": "🔌", "title": "Integrations"},
    "location":     {"icon": "📍", "title": "Location Services"},
    "memory":       {"icon": "🧠", "title": "Memory & Privacy"},
    "voice":        {"icon": "🎙️", "title": "Voice Assistants (Alexa / Google Home)"},
}


# ── helpers ────────────────────────────────────────────────────────────────

def _mask(val: str) -> str:
    if not val or len(val) < 8:
        return "••••" if val else ""
    return "••••••••" + val[-4:]


def _read_env() -> dict[str, str]:
    """Read current .env file into dict."""
    if not _ENV_FILE.exists():
        return {}
    result = {}
    for line in _ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def _write_env(updates: dict[str, str]) -> None:
    """Merge updates into .env file, creating it if needed."""
    existing: dict[str, str] = {}
    lines: list[str] = []

    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k, _, v = stripped.partition("=")
                existing[k.strip()] = line  # preserve original line
            lines.append(line)

    # Update/add each key
    for key, val in updates.items():
        env_key = key.upper()
        # Remove existing line for this key
        lines = [l for l in lines if not (
            l.strip() and not l.strip().startswith("#") and
            l.strip().partition("=")[0].strip() == env_key
        )]
        if val:  # only write non-empty values
            lines.append(f'{env_key}="{val}"')

    # Deduplicate trailing blanks
    while lines and lines[-1].strip() == "":
        lines.pop()
    lines.append("")

    _ENV_FILE.write_text("\n".join(lines))


# ── connection testers ─────────────────────────────────────────────────────

def _test_provider(name: str) -> dict:
    try:
        if name == "anthropic":
            from anthropic import Anthropic
            c = Anthropic(api_key=settings.anthropic_api_key)
            c.models.list()
            return {"ok": True, "msg": "Anthropic connected ✓"}
        if name == "openai":
            from openai import OpenAI
            c = OpenAI(api_key=settings.openai_api_key)
            c.models.list()
            return {"ok": True, "msg": "OpenAI connected ✓"}
        if name == "google":
            import google.generativeai as genai
            genai.configure(api_key=settings.google_api_key or settings.gemini_api_key)
            list(genai.list_models())
            return {"ok": True, "msg": "Google/Gemini connected ✓"}
        if name == "groq":
            from groq import Groq
            c = Groq(api_key=settings.groq_api_key)
            c.models.list()
            return {"ok": True, "msg": "Groq connected ✓"}
        if name == "perplexity":
            import httpx
            r = httpx.get("https://api.perplexity.ai/models",
                          headers={"Authorization": f"Bearer {settings.perplexity_api_key}"}, timeout=8)
            return {"ok": r.status_code < 400, "msg": f"Perplexity HTTP {r.status_code}"}
        if name == "azure":
            from openai import AzureOpenAI
            c = AzureOpenAI(api_key=settings.azure_openai_api_key,
                            azure_endpoint=settings.azure_openai_endpoint,
                            api_version=settings.azure_openai_api_version)
            c.models.list()
            return {"ok": True, "msg": "Azure OpenAI connected ✓"}
        if name == "aws":
            import boto3
            sts = boto3.client("sts",
                               aws_access_key_id=settings.aws_access_key_id,
                               aws_secret_access_key=settings.aws_secret_access_key,
                               region_name=settings.aws_region or "us-east-1")
            ident = sts.get_caller_identity()
            return {"ok": True, "msg": f"AWS ✓ account {ident['Account']}"}
        if name == "ollama":
            import httpx
            r = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=4)
            models = [m["name"] for m in r.json().get("models", [])]
            return {"ok": True, "msg": f"Ollama ✓ — {len(models)} models"}
        if name == "twilio":
            from twilio.rest import Client
            c = Client(settings.twilio_account_sid, settings.twilio_auth_token)
            acc = c.api.accounts(settings.twilio_account_sid).fetch()
            return {"ok": True, "msg": f"Twilio ✓ {acc.friendly_name}"}
        if name == "discord":
            import httpx
            r = httpx.get("https://discord.com/api/v10/users/@me",
                          headers={"Authorization": f"Bot {settings.discord_bot_token}"}, timeout=8)
            d = r.json()
            return {"ok": r.status_code == 200, "msg": f"Discord ✓ {d.get('username','')}#{d.get('discriminator','')}"}
        if name == "telegram":
            import httpx
            r = httpx.get(f"https://api.telegram.org/bot{settings.telegram_bot_token}/getMe", timeout=8)
            d = r.json()
            return {"ok": d.get("ok"), "msg": f"Telegram ✓ @{d.get('result',{}).get('username','')}"}
        if name == "ha":
            import httpx
            r = httpx.get(f"{settings.ha_base_url}/api/",
                          headers={"Authorization": f"Bearer {settings.ha_token}"}, timeout=8)
            return {"ok": r.status_code == 200, "msg": f"Home Assistant ✓ v{r.json().get('version','')}"}
        if name == "github":
            import httpx
            r = httpx.get("https://api.github.com/user",
                          headers={"Authorization": f"token {settings.github_token}"}, timeout=8)
            return {"ok": r.status_code == 200, "msg": f"GitHub ✓ @{r.json().get('login','')}"}
        if name == "notion":
            import httpx
            r = httpx.get("https://api.notion.com/v1/users/me",
                          headers={"Authorization": f"Bearer {settings.notion_api_key}",
                                   "Notion-Version": "2022-06-28"}, timeout=8)
            return {"ok": r.status_code == 200, "msg": "Notion ✓"}
        if name == "slack":
            import httpx
            r = httpx.post("https://slack.com/api/auth.test",
                           headers={"Authorization": f"Bearer {settings.slack_bot_token}"}, timeout=8)
            d = r.json()
            return {"ok": d.get("ok"), "msg": f"Slack ✓ {d.get('team','')}"}
        return {"ok": False, "msg": f"Unknown provider: {name}"}
    except Exception as e:
        return {"ok": False, "msg": str(e)[:120]}


# ── UI HTML (single-page app) ──────────────────────────────────────────────

def _build_html() -> str:
    groups_order = ["profile", "memory", "ai", "channels", "safety", "resources", "integrations"]
    tabs_html = ""
    panels_html = ""

    for g in groups_order:
        meta = _GROUP_META[g]
        tabs_html += f'<button class="tab-btn" data-tab="{g}">{meta["icon"]} {meta["title"]}</button>\n'
        fields_html = ""
        for f in _FIELDS:
            if f["group"] != g:
                continue
            key = f["key"]
            label = f["label"]
            ftype = f["type"]
            help_txt = f.get("help", "")
            test_id = f.get("test", "")
            options = f.get("options", [])

            if ftype == "select":
                opts = "".join(f'<option value="{o}">{o}</option>' for o in options)
                inp = f'<select name="{key}" id="f_{key}" class="inp">{opts}</select>'
            elif ftype == "secret":
                inp = (f'<div class="secret-row">'
                       f'<input type="password" name="{key}" id="f_{key}" class="inp" autocomplete="off" '
                       f'placeholder="(current value hidden)" />'
                       f'<button type="button" class="eye-btn" onclick="toggleVis(\'f_{key}\')" title="Show/hide">👁</button>'
                       f'</div>')
            elif ftype == "bool":
                inp = (f'<label class="toggle-switch">'
                       f'<input type="checkbox" name="{key}" id="f_{key}" value="true" />'
                       f'<span class="toggle-slider"></span></label>')
            else:
                inp = f'<input type="text" name="{key}" id="f_{key}" class="inp" />'

            test_btn = (f'<button type="button" class="test-btn" '
                        f'onclick="testConnection(\'{test_id}\', this)">Test</button>') if test_id else ""
            revoke_btn = (f'<button type="button" class="revoke-btn" '
                          f'onclick="revokeField(\'{key}\', this)">Revoke</button>') if ftype == "secret" else ""

            fields_html += f"""
<div class="field-row" id="row_{key}">
  <label for="f_{key}">{label}</label>
  <div class="field-inputs">
    {inp}
    <span class="status-dot" id="dot_{key}"></span>
    {test_btn}{revoke_btn}
  </div>
  {'<span class="help">'+help_txt+'</span>' if help_txt else ''}
</div>"""

        panels_html += f"""
<div class="tab-panel" id="panel_{g}">
  <h2>{meta["icon"]} {meta["title"]}</h2>
  <form id="form_{g}" onsubmit="saveGroup(event, '{g}')">
    {fields_html}
    <div class="save-row">
      <button type="submit" class="save-btn">💾 Save {meta["title"]}</button>
      <span class="save-status" id="save_{g}"></span>
    </div>
  </form>
</div>"""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Squire — mysquire.ai</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {{
  /* mysquire.ai design system */
  --bg:      #0F172A;   /* navy primary */
  --panel:   #1E293B;   /* card/sidebar */
  --card:    #243044;
  --accent:  #3B82F6;   /* blue */
  --accent2: #2563EB;
  --text:    #F8FAFC;
  --muted:   #94A3B8;
  --ok:      #10B981;   /* emerald */
  --err:     #EF4444;
  --warn:    #F59E0B;
  --border:  #334155;
  --inp-bg:  #0F172A;
  --font:    'DM Sans', system-ui, sans-serif;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: var(--bg); color: var(--text); font-family: var(--font); min-height: 100vh; }}

/* Header */
.header {{ background: var(--panel); padding: 1rem 2rem; display: flex; align-items: center;
           gap: 1rem; border-bottom: 1px solid var(--border); }}
.logo-mark {{ width: 32px; height: 32px; background: var(--accent); border-radius: 8px;
              display: flex; align-items: center; justify-content: center; flex-shrink: 0; }}
.header h1 {{ font-size: 1.3rem; font-weight: 700; color: var(--text); letter-spacing: -0.3px; }}
.header small {{ color: var(--muted); font-size: .82rem; }}
.header-right {{ margin-left: auto; display: flex; gap: .5rem; }}
.hbtn {{ background: var(--card); border: 1px solid var(--border); color: var(--text);
         padding: .4rem .9rem; border-radius: .4rem; cursor: pointer; font-size: .85rem;
         font-family: var(--font); }}
.hbtn:hover {{ background: var(--accent); border-color: var(--accent); color: #fff; }}

/* Layout */
.layout {{ display: flex; min-height: calc(100vh - 62px); }}
.sidebar {{ width: 240px; background: var(--panel); border-right: 1px solid var(--border);
            display: flex; flex-direction: column; padding: .75rem 0; flex-shrink: 0; }}
.tab-btn {{ display: block; width: 100%; text-align: left; padding: .75rem 1.25rem;
            background: none; border: none; color: var(--muted); cursor: pointer;
            font-size: .92rem; border-left: 3px solid transparent; transition: all .15s;
            font-family: var(--font); }}
.tab-btn:hover {{ color: var(--text); background: var(--card); }}
.tab-btn.active {{ color: var(--accent); border-left-color: var(--accent);
                   background: rgba(59,130,246,.1); font-weight: 600; }}
.sidebar-footer {{ margin-top: auto; padding: 1rem; border-top: 1px solid var(--border); }}
.sidebar-footer a {{ color: var(--muted); font-size: .8rem; text-decoration: none; }}
.sidebar-footer a:hover {{ color: var(--accent); }}

/* Main content */
.main {{ flex: 1; overflow-y: auto; padding: 2rem; }}
.tab-panel {{ display: none; max-width: 760px; }}
.tab-panel.active {{ display: block; }}
.tab-panel h2 {{ font-size: 1.3rem; margin-bottom: 1.5rem; color: var(--accent); }}

/* Fields */
.field-row {{ margin-bottom: 1.1rem; }}
label {{ display: block; font-size: .85rem; font-weight: 600; color: var(--muted);
         text-transform: uppercase; letter-spacing: .04em; margin-bottom: .35rem; }}
.field-inputs {{ display: flex; align-items: center; gap: .5rem; }}
.inp {{ flex: 1; background: var(--inp-bg); border: 1px solid var(--border); color: var(--text);
        padding: .55rem .75rem; border-radius: .4rem; font-size: .95rem; outline: none; }}
.inp:focus {{ border-color: var(--accent); }}
select.inp {{ cursor: pointer; }}
.secret-row {{ display: flex; flex: 1; align-items: center; gap: .3rem; }}
.secret-row .inp {{ flex: 1; }}
.eye-btn {{ background: none; border: none; cursor: pointer; font-size: 1rem; color: var(--muted); padding: 0 .2rem; }}
.help {{ display: block; font-size: .78rem; color: var(--muted); margin-top: .2rem; }}

/* Status dot */
.status-dot {{ width: 10px; height: 10px; border-radius: 50%; background: var(--border); flex-shrink: 0; }}
.status-dot.ok {{ background: var(--ok); }}
.status-dot.err {{ background: var(--err); }}
.status-dot.loading {{ background: #f5a623; animation: pulse .8s infinite; }}
@keyframes pulse {{ 0%,100% {{ opacity:1 }} 50% {{ opacity:.4 }} }}

/* Buttons */
.test-btn {{ background: rgba(123,104,238,.2); border: 1px solid var(--accent); color: var(--accent);
             padding: .35rem .75rem; border-radius: .35rem; cursor: pointer; font-size: .82rem; white-space: nowrap; }}
.test-btn:hover {{ background: rgba(123,104,238,.35); }}
.revoke-btn {{ background: rgba(240,64,96,.1); border: 1px solid var(--err); color: var(--err);
               padding: .35rem .75rem; border-radius: .35rem; cursor: pointer; font-size: .82rem; white-space: nowrap; }}
.revoke-btn:hover {{ background: rgba(240,64,96,.25); }}
.save-btn {{ background: var(--accent); border: none; color: #fff;
             padding: .65rem 1.5rem; border-radius: .45rem; cursor: pointer;
             font-size: .95rem; font-weight: 600; margin-top: .5rem; }}
.save-btn:hover {{ background: var(--accent2); }}
.save-row {{ margin-top: 1.5rem; display: flex; align-items: center; gap: 1rem; }}
.save-status {{ font-size: .85rem; }}
.save-status.ok {{ color: var(--ok); }}
.save-status.err {{ color: var(--err); }}

/* Extra panels */
#panel_skills table, #panel_audit table {{ width: 100%; border-collapse: collapse; font-size: .88rem; }}
#panel_skills td, #panel_audit td, #panel_skills th, #panel_audit th {{
  padding: .45rem .6rem; border-bottom: 1px solid var(--border); text-align: left; }}
#panel_skills th, #panel_audit th {{ color: var(--muted); font-size: .8rem; text-transform: uppercase; }}
.badge {{ display: inline-block; padding: .1rem .45rem; border-radius: .3rem; font-size: .75rem; }}
.badge.active {{ background: rgba(76,175,125,.2); color: var(--ok); }}
.badge.inactive {{ background: rgba(240,64,96,.1); color: var(--err); }}
.badge.sensitive {{ background: rgba(245,166,35,.15); color: #f5a623; }}

/* Connection cards */
.conn-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(160px,1fr)); gap: .75rem; margin-bottom: 1.5rem; }}
.conn-card {{ background: var(--card); border: 1px solid var(--border); border-radius: .5rem;
              padding: .8rem 1rem; text-align: center; }}
.conn-card .conn-icon {{ font-size: 1.6rem; }}
.conn-card .conn-name {{ font-size: .8rem; color: var(--muted); margin-top: .2rem; }}
.conn-card .conn-status {{ font-size: .75rem; margin-top: .3rem; }}
.conn-card.connected {{ border-color: var(--ok); }}
.conn-card.disconnected {{ border-color: var(--border); opacity: .7; }}

/* Scrollable audit / memory tables */
#audit-table-wrap {{ max-height: 500px; overflow-y: auto; }}
#provider-status {{ margin-bottom: 1.5rem; }}

/* Toggle switch (bool fields) */
.toggle-switch {{ position: relative; display: inline-block; width: 44px; height: 24px; cursor: pointer; }}
.toggle-switch input {{ opacity: 0; width: 0; height: 0; }}
.toggle-slider {{ position: absolute; inset: 0; background: var(--border); border-radius: 24px; transition: .2s; }}
.toggle-slider:before {{ content: ""; position: absolute; height: 18px; width: 18px; left: 3px; bottom: 3px;
  background: var(--text); border-radius: 50%; transition: .2s; }}
.toggle-switch input:checked + .toggle-slider {{ background: var(--accent); }}
.toggle-switch input:checked + .toggle-slider:before {{ transform: translateX(20px); }}

/* Fact category badge */
.cat-badge {{ display: inline-block; padding: .15rem .5rem; border-radius: .25rem; font-size: .75rem;
  background: var(--accent); color: #fff; text-transform: uppercase; letter-spacing: .04em; }}

.toast {{ position: fixed; bottom: 1.5rem; right: 1.5rem; background: var(--card);
          border: 1px solid var(--accent); color: var(--text); padding: .75rem 1.25rem;
          border-radius: .5rem; font-size: .9rem; z-index: 9999;
          animation: slideIn .2s ease; }}
@keyframes slideIn {{ from {{ transform: translateY(20px); opacity:0 }} to {{ transform: translateY(0); opacity:1 }} }}
</style>
</head>
<body>

<div class="header">
  <div class="logo-mark">
    <svg width="20" height="20" viewBox="0 0 32 32" fill="none">
      <path d="M8 8h10a5 5 0 0 1 0 10h-5a5 5 0 0 0 0 10h10" stroke="#fff" stroke-width="3"
            stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
  </div>
  <div>
    <h1>Squire</h1>
    <small id="hdr-status">mysquire.ai — Loading…</small>
  </div>
  <div class="header-right">
    <button class="hbtn" onclick="location.reload()">↺ Reload</button>
    <button class="hbtn" onclick="doBackup()">📦 Backup</button>
    <button class="hbtn" onclick="runDoctor()">🛡️ Doctor</button>
    <button class="hbtn" onclick="window.open('/canvas','_blank')">🎨 Canvas</button>
    <button class="hbtn" onclick="openChat()">💬 Chat</button>
  </div>
</div>

<div class="layout">
  <nav class="sidebar">
    <button class="tab-btn" data-tab="setup">🚀 Setup Wizard</button>
    {tabs_html}
    <button class="tab-btn" data-tab="status">🔮 Provider Status</button>
    <button class="tab-btn" data-tab="skills">🛠 Skills</button>
    <button class="tab-btn" data-tab="doctor">🛡️ Health Check</button>
    <button class="tab-btn" data-tab="audit">📋 Audit Log</button>
    <button class="tab-btn" data-tab="memory_facts">🧠 Memory</button>
    <div class="sidebar-footer">
      <a href="/docs" target="_blank">API Docs ↗</a>&nbsp;&nbsp;
      <a href="/pwa/" target="_blank">PWA ↗</a>&nbsp;&nbsp;
      <a href="/canvas" target="_blank">Canvas ↗</a>
    </div>
  </nav>
  <main class="main">

    <!-- ── Setup Wizard panel ──────────────────────────────────────────── -->
    <div class="tab-panel" id="panel_setup">
      <h2>🚀 Setup Wizard</h2>
      <p style="color:var(--muted);margin-bottom:1.5rem">
        Complete these steps to get the most out of Squire.
        Click any step to configure it.
      </p>
      <div id="setup-steps" style="display:flex;flex-direction:column;gap:1rem;max-width:640px">
        Loading…
      </div>
      <div style="margin-top:2rem;padding:1rem;background:var(--card);border-radius:10px;border:1px solid var(--border)">
        <strong>⌨️ Prefer the terminal?</strong>
        <p style="color:var(--muted);margin-top:.4rem;font-size:.9rem">
          Run the interactive setup wizard from your terminal:<br>
          <code style="background:var(--inp-bg);padding:.2rem .5rem;border-radius:4px;font-size:.88rem">
            python -m squire onboard
          </code>
        </p>
      </div>
    </div>

    {panels_html}

    <!-- Provider status panel -->
    <div class="tab-panel" id="panel_status">
      <h2>🔮 Provider Status</h2>
      <p style="color:var(--muted);margin-bottom:1rem">Real-time connection status for all configured integrations.</p>
      <div class="conn-grid" id="conn-grid">Loading…</div>
      <button class="save-btn" onclick="loadProviderStatus()">↺ Refresh All</button>
    </div>

    <!-- Doctor panel -->
    <div class="tab-panel" id="panel_doctor">
      <h2>🛡️ Health Check</h2>
      <p style="color:var(--muted);margin-bottom:1rem">Security and configuration audit — checks 25+ aspects of your Squire deployment.</p>
      <div id="doctor-results" style="font-family:monospace;white-space:pre-wrap;background:var(--card);padding:1rem;border-radius:8px;font-size:.85rem;min-height:200px">
        Click "Run Doctor" to start the audit.
      </div>
      <button class="save-btn" style="margin-top:1rem" onclick="runDoctor()">🛡️ Run Doctor</button>
    </div>

    <!-- Skills panel -->
    <div class="tab-panel" id="panel_skills">
      <h2>🛠 Skills</h2>
      <input type="text" class="inp" id="skill-search" placeholder="Filter skills…" oninput="filterSkills()"
             style="max-width:300px;margin-bottom:1rem">
      <table id="skills-table">
        <tr><th>Name</th><th>Description</th><th>Status</th><th>Requires</th></tr>
      </table>
    </div>

    <!-- Audit panel -->
    <div class="tab-panel" id="panel_audit">
      <h2>📋 Audit Log</h2>
      <div id="audit-table-wrap">
        <table id="audit-table">
          <tr><th>Time</th><th>User</th><th>Action</th><th>Detail</th></tr>
        </table>
      </div>
    </div>

    <!-- Memory panel -->
    <div class="tab-panel" id="panel_memory_facts">
      <h2>🧠 Memory & Learned Facts</h2>
      <p style="color:var(--muted);font-size:.9rem">
        Facts the assistant has learned about you from conversations.
        You can edit, delete individual facts, or wipe all conversation history.
      </p>
      <div style="display:flex;gap:.75rem;margin-bottom:1.25rem;flex-wrap:wrap">
        <button class="save-btn" onclick="loadMemoryFacts()">🔄 Refresh</button>
        <button class="save-btn" onclick="exportMemory()">📥 Export Memory</button>
        <button class="revoke-btn" style="padding:.5rem 1rem" onclick="wipeMemory()">🗑 Wipe Conversation History</button>
      </div>
      <div id="audit-table-wrap">
        <table id="memory-facts-table">
          <tr><th>Key</th><th>Value</th><th>Category</th><th></th></tr>
        </table>
      </div>
    </div>
  </main>
</div>

<script>
// ── State ───────────────────────────────────────────────────────────────
let CONFIG = {{}};   // current (unmasked) config loaded from backend
const ADMIN_TOKEN = localStorage.getItem('ram_admin_token') || '';

// ── Init ────────────────────────────────────────────────────────────────
async function init() {{
  await loadConfig();
  setupTabs();
  loadSkills();
  loadAudit();
  loadMemoryFacts();
  // Activate setup tab on first load, otherwise first tab
  const firstRun = !localStorage.getItem('squire_admin_visited');
  if (firstRun) {{
    localStorage.setItem('squire_admin_visited', '1');
    const setupBtn = document.querySelector('[data-tab="setup"]');
    if (setupBtn) setupBtn.click();
    else document.querySelector('.tab-btn').click();
  }} else {{
    document.querySelector('.tab-btn').click();
  }}
  loadSetupSteps();
}}

// ── Tabs ────────────────────────────────────────────────────────────────
function showTab(tabName) {{
  const btn = document.querySelector(`.tab-btn[data-tab="${{tabName}}"]`);
  if (btn) btn.click();
}}

function setupTabs() {{
  document.querySelectorAll('.tab-btn').forEach(btn => {{
    btn.addEventListener('click', () => {{
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      const panel = document.getElementById('panel_' + btn.dataset.tab);
      if (panel) panel.classList.add('active');
      if (btn.dataset.tab === 'status') loadProviderStatus();
      if (btn.dataset.tab === 'setup') loadSetupSteps();
    }});
  }});
}}

// ── Setup Wizard ─────────────────────────────────────────────────────────
async function loadSetupSteps() {{
  const container = document.getElementById('setup-steps');
  if (!container) return;

  let cfg = {{}};
  try {{ cfg = await apiFetch('/admin/config'); }} catch(e) {{}}

  const providerKeys = ['groq_api_key','gemini_api_key','openai_api_key',
    'anthropic_api_key','deepseek_api_key','openrouter_api_key',
    'fireworks_api_key','cerebras_api_key','venice_api_key','ollama_base_url'];
  const hasProvider  = providerKeys.some(k => cfg[k]);

  const googleOk     = cfg._google_connected;
  const telegramOk   = cfg.telegram_bot_token;
  const whatsappOk   = cfg.twilio_account_sid;
  const discordOk    = cfg.discord_bot_token;
  const channelOk    = telegramOk || whatsappOk || discordOk;
  const briefingOk   = cfg.ram_briefing_time && cfg.ram_briefing_time !== '07:30';
  const httpOk       = cfg.ram_http_token;

  const steps = [
    {{
      title: '1. AI Provider',
      desc:  hasProvider
        ? 'Your AI brain is connected and ready.'
        : 'Connect a free AI provider to get started. We recommend Groq (free tier).',
      ok: hasProvider,
      tab: 'llm_providers',
      links: [
        {{label: 'Get free Groq key →', url: 'https://console.groq.com/keys'}},
        {{label: 'Get free Gemini key →', url: 'https://aistudio.google.com/app/apikey'}},
      ],
    }},
    {{
      title: '2. Gmail & Calendar',
      desc: googleOk
        ? 'Gmail and Google Calendar are connected.'
        : 'Connect Gmail so Squire can triage your inbox, draft replies, and manage your calendar.',
      ok: googleOk,
      tab: 'google',
    }},
    {{
      title: '3. Messaging Channel',
      desc: channelOk
        ? 'You have a messaging channel — reach Squire from your phone.'
        : 'Connect Telegram, WhatsApp, or Discord to message Squire when away from your computer.',
      ok: channelOk,
      tab: 'telegram',
    }},
    {{
      title: '4. Daily Briefing',
      desc: briefingOk
        ? `Daily briefing set for ${{cfg.ram_briefing_time}}.`
        : 'Set a time for your morning briefing: calendar, emails, tasks, and weather in one message.',
      ok: briefingOk,
      tab: 'general',
    }},
    {{
      title: '5. Web Interface Password',
      desc: httpOk
        ? 'Your admin panel is password-protected.'
        : 'Add a password to keep your admin panel secure (anyone on your network can access it).',
      ok: httpOk,
      tab: 'safety',
    }},
  ];

  const total = steps.length;
  const done  = steps.filter(s => s.ok).length;
  const pct   = Math.round((done / total) * 100);

  container.innerHTML = `
    <div style="margin-bottom:1.5rem">
      <div style="display:flex;justify-content:space-between;margin-bottom:.4rem">
        <span style="font-weight:600">Setup Progress</span>
        <span style="color:var(--muted)">${{done}}/${{total}} steps</span>
      </div>
      <div style="background:var(--card);border-radius:8px;height:8px;overflow:hidden">
        <div style="background:var(--ok);width:${{pct}}%;height:100%;border-radius:8px;transition:width .4s"></div>
      </div>
    </div>
    ${{steps.map(s => `
      <div style="background:var(--card);border:1px solid var(--border);border-radius:12px;
                  padding:1rem 1.2rem;display:flex;align-items:flex-start;gap:1rem;cursor:pointer"
           onclick="showTab('${{s.tab}}')">
        <div style="font-size:1.5rem;line-height:1;flex-shrink:0">
          ${{s.ok ? '✅' : '⭕'}}
        </div>
        <div style="flex:1">
          <div style="font-weight:600;margin-bottom:.2rem">${{s.title}}</div>
          <div style="color:var(--muted);font-size:.9rem">${{s.desc}}</div>
          ${{(s.links||[]).map(l=>
            `<a href="${{l.url}}" target="_blank"
                style="color:var(--accent);font-size:.85rem;display:inline-block;margin-top:.4rem"
                onclick="event.stopPropagation()">${{l.label}}</a>`
          ).join(' &nbsp; ')}}
        </div>
        <div style="color:var(--muted);font-size:1.1rem;flex-shrink:0">›</div>
      </div>
    `).join('')}}
    ${{done === total ? `
      <div style="background:rgba(16,185,129,.1);border:1px solid var(--ok);border-radius:12px;
                  padding:1rem 1.2rem;text-align:center;color:var(--ok);font-weight:600">
        🎉 All set! Squire is fully configured and ready to serve you.
      </div>
    ` : ''}}
  `;
}}

// ── Load config ──────────────────────────────────────────────────────────
async function loadConfig() {{
  try {{
    const r = await apiFetch('/admin/config');
    CONFIG = r;
    // Populate fields
    for (const [key, val] of Object.entries(r)) {{
      const el = document.getElementById('f_' + key);
      if (!el) continue;
      const isSecret = el.type === 'password';
      if (!isSecret) {{
        el.value = val || '';
      }} else {{
        el.placeholder = val ? '(set — enter new value to change)' : '(not set)';
      }}
      // Status dot
      const dot = document.getElementById('dot_' + key);
      if (dot) {{
        dot.className = 'status-dot ' + (val ? 'ok' : '');
        dot.title = val ? 'Configured' : 'Not set';
      }}
    }}
    document.getElementById('hdr-status').textContent =
      `Owner: ${{r.ram_owner_name || '?'}} · ${{r.ram_timezone || 'UTC'}}`;
  }} catch(e) {{
    showToast('Could not load config: ' + e, true);
  }}
}}

// ── Save group ───────────────────────────────────────────────────────────
async function saveGroup(evt, group) {{
  evt.preventDefault();
  const form = document.getElementById('form_' + group);
  const data = {{}};
  for (const el of form.querySelectorAll('[name]')) {{
    const key = el.name;
    const val = el.value.trim();
    // For secrets: only send if user typed something new
    if (el.type === 'password' && !val) continue;
    data[key] = val;
  }}
  const status = document.getElementById('save_' + group);
  status.textContent = 'Saving…';
  status.className = 'save-status';
  try {{
    await apiFetch('/admin/config', 'POST', data);
    status.textContent = '✓ Saved';
    status.className = 'save-status ok';
    await loadConfig();
    setTimeout(() => {{ status.textContent = ''; }}, 3000);
  }} catch(e) {{
    status.textContent = '✗ ' + e;
    status.className = 'save-status err';
  }}
}}

// ── Test connection ───────────────────────────────────────────────────────
async function testConnection(provider, btn) {{
  btn.textContent = '…';
  btn.disabled = true;
  try {{
    const r = await apiFetch('/admin/test/provider', 'POST', {{provider}});
    showToast(r.msg, !r.ok);
    // Update dot for associated key
    const fieldEntry = document.querySelector(`[data-test="${{provider}}"]`);
  }} catch(e) {{
    showToast('Test failed: ' + e, true);
  }} finally {{
    btn.textContent = 'Test';
    btn.disabled = false;
  }}
}}

// ── Revoke field ─────────────────────────────────────────────────────────
async function revokeField(key, btn) {{
  if (!confirm(`Revoke ${{key}}? This will clear it from .env.`)) return;
  btn.disabled = true;
  try {{
    await apiFetch('/admin/config', 'POST', {{[key]: ''}});
    await loadConfig();
    showToast(key + ' revoked');
    const dot = document.getElementById('dot_' + key);
    if (dot) {{ dot.className = 'status-dot'; dot.title = 'Not set'; }}
    const el = document.getElementById('f_' + key);
    if (el) el.placeholder = '(not set)';
  }} catch(e) {{
    showToast('Revoke failed: ' + e, true);
  }} finally {{
    btn.disabled = false;
  }}
}}

// ── Toggle visibility ─────────────────────────────────────────────────────
function toggleVis(id) {{
  const el = document.getElementById(id);
  el.type = el.type === 'password' ? 'text' : 'password';
}}

// ── Provider status panel ─────────────────────────────────────────────────
async function loadProviderStatus() {{
  const grid = document.getElementById('conn-grid');
  grid.innerHTML = '<span style="color:var(--muted)">Testing connections…</span>';
  try {{
    const r = await apiFetch('/admin/status');
    grid.innerHTML = '';
    for (const item of r) {{
      const card = document.createElement('div');
      card.className = 'conn-card ' + (item.connected ? 'connected' : 'disconnected');
      card.innerHTML = `
        <div class="conn-icon">${{item.icon}}</div>
        <div class="conn-name">${{item.name}}</div>
        <div class="conn-status" style="color:${{item.connected ? 'var(--ok)' : 'var(--muted)'}}">${{item.connected ? '● Connected' : '○ Not set'}}</div>
      `;
      grid.appendChild(card);
    }}
  }} catch(e) {{
    grid.innerHTML = '<span style="color:var(--err)">Error: ' + e + '</span>';
  }}
}}

// ── Skills panel ──────────────────────────────────────────────────────────
let ALL_SKILLS = [];
async function loadSkills() {{
  try {{
    const skills = await apiFetch('/admin/skills');
    ALL_SKILLS = skills;
    renderSkills(skills);
  }} catch(e) {{}}
}}
function renderSkills(skills) {{
  const tb = document.getElementById('skills-table');
  const rows = skills.map(s => `
    <tr>
      <td><code style="color:var(--accent)">${{s.name}}</code></td>
      <td style="color:var(--muted);font-size:.83rem">${{s.desc}}</td>
      <td>
        <span class="badge ${{s.active ? 'active' : 'inactive'}}">${{s.active ? 'Active' : 'Inactive'}}</span>
        ${{s.sensitive ? '<span class="badge sensitive">Sensitive</span>' : ''}}
      </td>
      <td style="font-size:.78rem;color:var(--muted)">${{(s.requires||[]).join(', ')}}</td>
    </tr>`).join('');
  tb.innerHTML = '<tr><th>Name</th><th>Description</th><th>Status</th><th>Requires</th></tr>' + rows;
}}
function filterSkills() {{
  const q = document.getElementById('skill-search').value.toLowerCase();
  renderSkills(ALL_SKILLS.filter(s => s.name.includes(q) || s.desc.toLowerCase().includes(q)));
}}

// ── Audit log ────────────────────────────────────────────────────────────
async function loadAudit() {{
  try {{
    const entries = await apiFetch('/admin/audit');
    const tb = document.getElementById('audit-table');
    const rows = entries.slice(0,100).map(a => `
      <tr>
        <td style="color:var(--muted);white-space:nowrap;font-size:.8rem">${{a.ts ? new Date(a.ts*1000).toLocaleString() : ''}}</td>
        <td style="font-size:.82rem">${{a.user_id||''}}</td>
        <td><code style="font-size:.82rem">${{a.action||''}}</code></td>
        <td style="color:var(--muted);font-size:.8rem">${{(a.payload||'').slice(0,80)}}</td>
      </tr>`).join('');
    tb.innerHTML = '<tr><th>Time</th><th>User</th><th>Action</th><th>Detail</th></tr>' + rows;
  }} catch(e) {{}}
}}

// ── Memory facts management ───────────────────────────────────────────────
async function loadMemoryFacts() {{
  const tb = document.getElementById('memory-facts-table');
  if (!tb) return;
  try {{
    const facts = await apiFetch('/admin/memory/facts');
    if (!facts || !facts.length) {{
      tb.innerHTML = '<tr><td colspan="4" style="color:var(--muted)">No facts stored yet.</td></tr>';
      return;
    }}
    tb.innerHTML = '<tr><th>Key</th><th>Value</th><th>Category</th><th></th></tr>' +
      facts.map(f => `<tr>
        <td><code style="font-size:.82rem">${{f.key}}</code></td>
        <td style="font-size:.82rem">${{f.value}}</td>
        <td><span class="cat-badge">${{f.category}}</span></td>
        <td><button class="revoke-btn" onclick="forgetFact('${{f.key}}', this)">Forget</button></td>
      </tr>`).join('');
  }} catch(e) {{
    if (tb) tb.innerHTML = '<tr><td colspan="4">Could not load facts.</td></tr>';
  }}
}}

async function forgetFact(key, btn) {{
  btn.disabled = true; btn.textContent = '…';
  try {{
    await apiFetch('/admin/memory/facts/' + encodeURIComponent(key), 'DELETE');
    showToast('Fact "' + key + '" forgotten.');
    loadMemoryFacts();
  }} catch(e) {{
    showToast('Failed: ' + e, true);
    btn.disabled = false; btn.textContent = 'Forget';
  }}
}}

async function wipeMemory() {{
  if (!confirm('Wipe ALL conversation history for CLI user? This cannot be undone.')) return;
  try {{
    await apiFetch('/admin/memory/wipe', 'POST');
    showToast('✅ Conversation history wiped.');
    loadMemoryFacts();
  }} catch(e) {{
    showToast('Wipe failed: ' + e, true);
  }}
}}

async function exportMemory() {{
  try {{
    const r = await apiFetch('/admin/memory/export', 'POST');
    showToast('✅ Exported to: ' + (r.path || 'data dir'));
  }} catch(e) {{
    showToast('Export failed: ' + e, true);
  }}
}}

// ── Backup ────────────────────────────────────────────────────────────────
async function doBackup() {{
  try {{
    const r = await apiFetch('/admin/backup', 'POST');
    showToast('Backup created: ' + r.path);
  }} catch(e) {{
    showToast('Backup failed: ' + e, true);
  }}
}}

function openChat() {{
  window.open('/app', '_blank');
}}

async function runDoctor() {{
  showTab('doctor');
  const el = document.getElementById('doctor-results');
  el.textContent = 'Running health checks…';
  try {{
    const r = await apiFetch('/admin/doctor');
    const lines = r.results.map(c => {{
      const icons = {{pass:'✅',warn:'⚠️ ',fail:'❌',info:'ℹ️ '}};
      let line = `${{icons[c.status] || '?'}} ${{c.title}}\n   ${{c.message}}`;
      if (c.fix && (c.status === 'warn' || c.status === 'fail')) {{
        line += `\n   💡 Fix: ${{c.fix}}`;
      }}
      return line;
    }}).join('\n\n');
    const fails = r.results.filter(c=>c.status==='fail').length;
    const warns = r.results.filter(c=>c.status==='warn').length;
    const passes = r.results.filter(c=>c.status==='pass').length;
    el.textContent = lines + `\n\n${'─'.repeat(50)}\n✅ ${{passes}} passed  ⚠️  ${{warns}} warnings  ❌ ${{fails}} failures`;
  }} catch(e) {{
    el.textContent = 'Doctor check failed: ' + e;
  }}
}}

// ── API helper ────────────────────────────────────────────────────────────
async function apiFetch(url, method='GET', body=null) {{
  const opts = {{ method, headers: {{ 'Content-Type': 'application/json' }} }};
  const tok = localStorage.getItem('ram_admin_token');
  if (tok) opts.headers['Authorization'] = 'Bearer ' + tok;
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(url, opts);
  if (r.status === 401) {{
    const pw = prompt('Admin password:');
    if (pw) {{ localStorage.setItem('ram_admin_token', pw); }}
    return apiFetch(url, method, body);
  }}
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}}

// ── Toast ─────────────────────────────────────────────────────────────────
function showToast(msg, isError=false) {{
  const t = document.createElement('div');
  t.className = 'toast';
  t.style.borderColor = isError ? 'var(--err)' : 'var(--ok)';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 4000);
}}

init();
</script>
</body>
</html>"""


# ── Router ────────────────────────────────────────────────────────────────

def build_admin_router() -> APIRouter:
    r = APIRouter()

    def _auth(authorization: str | None) -> None:
        if not settings.ollie_admin_password:
            return
        if authorization != f"Bearer {settings.ollie_admin_password}":
            raise HTTPException(401, "admin auth required")

    @r.get("/admin", response_class=HTMLResponse)
    def admin_home(authorization: str | None = Header(None)):
        _auth(authorization)
        return HTMLResponse(_build_html())

    @r.get("/admin/config")
    def get_config(authorization: str | None = Header(None)):
        """Return all settings (secrets masked)."""
        _auth(authorization)
        result: dict[str, Any] = {}
        env_vals = _read_env()
        for f in _FIELDS:
            key = f["key"]
            env_key = key.upper()
            raw = env_vals.get(env_key, "") or str(getattr(settings, key, "") or "")
            if f["type"] == "secret":
                result[key] = _mask(raw)
            else:
                result[key] = raw
        return JSONResponse(result)

    @r.post("/admin/config")
    async def save_config(request: Request, authorization: str | None = Header(None)):
        """Save one or more settings to .env file."""
        _auth(authorization)
        body = await request.json()
        # Only allow known keys
        allowed = {f["key"] for f in _FIELDS}
        updates: dict[str, str] = {}
        for k, v in body.items():
            if k in allowed:
                # For secrets: empty string = don't change (skip)
                # Explicit empty means revoke
                env_key = k.upper()
                updates[env_key] = str(v) if v is not None else ""
        _write_env({k: v for k, v in updates.items()})
        # Hot-reload settings from new .env
        try:
            new_settings = settings.__class__(_env_file=".env")
            for attr in new_settings.model_fields:
                try:
                    object.__setattr__(settings, attr, getattr(new_settings, attr))
                except Exception:
                    pass
        except Exception:
            pass
        return {"ok": True, "updated": list(updates.keys())}

    @r.post("/admin/test/provider")
    async def test_provider(request: Request, authorization: str | None = Header(None)):
        _auth(authorization)
        body = await request.json()
        name = body.get("provider", "")
        result = _test_provider(name)
        return JSONResponse(result)

    @r.get("/admin/status")
    def get_status(authorization: str | None = Header(None)):
        """Quick connected/not-connected status for all integrations (no live test)."""
        _auth(authorization)
        checks = [
            ("Anthropic",    "🤖", bool(settings.anthropic_api_key)),
            ("OpenAI",       "🔵", bool(settings.openai_api_key)),
            ("Gemini",       "♊", bool(settings.google_api_key or settings.gemini_api_key)),
            ("Perplexity",   "🔍", bool(settings.perplexity_api_key)),
            ("Groq",         "⚡", bool(settings.groq_api_key)),
            ("Mistral",      "🌊", bool(settings.mistral_api_key)),
            ("Azure OpenAI", "☁️", bool(settings.azure_openai_api_key)),
            ("AWS",          "🟠", bool(settings.aws_access_key_id)),
            ("Ollama",       "🦙", True),  # always available
            ("Twilio SMS",   "📱", bool(settings.twilio_account_sid)),
            ("WhatsApp",     "💬", bool(settings.twilio_whatsapp_from)),
            ("Discord",      "🎮", bool(settings.discord_bot_token)),
            ("Telegram",     "✈️", bool(settings.telegram_bot_token)),
            ("iMessage",     "💙", bool(settings.bluebubbles_url)),
            ("GitHub",       "🐙", bool(settings.github_token)),
            ("Notion",       "📓", bool(settings.notion_api_key)),
            ("Linear",       "🔷", bool(settings.linear_api_key)),
            ("Slack",        "💼", bool(settings.slack_bot_token)),
            ("Plaid",        "🏦", bool(settings.plaid_client_id)),
            ("Home Asst.",   "🏠", bool(settings.ha_base_url)),
            ("ElevenLabs",   "🔊", bool(settings.elevenlabs_api_key)),
            ("Oura",         "💍", bool(settings.oura_access_token)),
            ("Fitbit",       "⌚", bool(settings.fitbit_client_id)),
        ]
        return JSONResponse([{"name": n, "icon": i, "connected": c} for n, i, c in checks])

    @r.get("/admin/audit")
    def audit_json(authorization: str | None = Header(None)):
        _auth(authorization)
        from ram.core import audit
        return JSONResponse(audit.recent(200))

    @r.get("/admin/skills")
    def skills_json(authorization: str | None = Header(None)):
        _auth(authorization)
        from ram.core import registry
        active_names = {s.name for s in registry.available_skills()}
        return JSONResponse([
            {"name": s.name, "desc": s.description,
             "requires": s.requires, "sensitive": s.sensitive,
             "active": s.name in active_names}
            for s in registry.all_skills()
        ])

    @r.post("/admin/backup")
    def backup_now(authorization: str | None = Header(None)):
        _auth(authorization)
        from ram.core.backup import export_zip
        return {"path": str(export_zip())}

    @r.get("/admin/doctor")
    def doctor_check(authorization: str | None = Header(None)):
        """Run the Squire health and security audit."""
        _auth(authorization)
        from ram.core.doctor import run_doctor
        results = run_doctor()
        return {
            "results": [r.to_dict() for r in results],
            "summary": {
                "pass": sum(1 for r in results if r.status == "pass"),
                "warn": sum(1 for r in results if r.status == "warn"),
                "fail": sum(1 for r in results if r.status == "fail"),
            },
        }

    @r.get("/admin/memory/facts")
    def memory_facts_list(authorization: str | None = Header(None)):
        """Return all stored facts as a list of {key, value, category, date}."""
        _auth(authorization)
        from ram.core.memory import db, Fact
        import time
        with db() as s:
            rows = s.query(Fact).order_by(Fact.category, Fact.key).all()
        return [
            {"key": f.key, "value": f.value,
             "category": f.category or "general",
             "date": time.strftime("%Y-%m-%d", time.localtime(f.ts)),
             "source": f.source or "manual"}
            for f in rows
        ]

    @r.delete("/admin/memory/facts/{key:path}")
    def memory_fact_delete(key: str, authorization: str | None = Header(None)):
        """Delete a single fact by key."""
        _auth(authorization)
        from ram.core import memory as mem
        removed = mem.forget(key)
        return {"removed": removed, "key": key}

    @r.post("/admin/memory/wipe")
    def memory_wipe(authorization: str | None = Header(None)):
        """Wipe all conversation history for the CLI user (keeps facts)."""
        _auth(authorization)
        from ram.core.memory import clear_history
        clear_history("cli")
        return {"ok": True}

    @r.post("/admin/memory/export")
    def memory_export(authorization: str | None = Header(None)):
        """Export all memory to a JSON file and return the path."""
        _auth(authorization)
        import json, time
        from ram.core.memory import export_memory
        from ram.core.config import settings as s
        data = export_memory("cli")
        out_path = s.ram_data_dir / f"memory_export_{int(time.time())}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(data, indent=2))
        return {"path": str(out_path)}

    return r


def build_shortcuts_router(handle) -> APIRouter:
    """iOS Shortcuts-friendly endpoints (text in, text out)."""
    r = APIRouter()

    @r.get("/shortcut/ask")
    @r.post("/shortcut/ask")
    async def shortcut_ask(request: Request,
                            authorization: str | None = Header(None)):
        if settings.ram_http_token and authorization != f"Bearer {settings.ram_http_token}":
            raise HTTPException(401, "auth")
        if request.method == "GET":
            text = request.query_params.get("text", "")
        else:
            try:
                payload = await request.json()
                text = payload.get("text", "")
            except Exception:
                form = await request.form()
                text = form.get("text", "")
        if not text:
            return {"reply": "(empty)"}
        reply = await handle("shortcut", text)
        return {"reply": reply.text, "actions": reply.actions_taken}

    @r.get("/shortcut/briefing")
    async def shortcut_briefing(authorization: str | None = Header(None)):
        if settings.ram_http_token and authorization != f"Bearer {settings.ram_http_token}":
            raise HTTPException(401, "auth")
        try:
            from ram.skills.briefing import compose_briefing
            return {"text": compose_briefing()}
        except Exception as e:
            return {"text": f"ERROR: {e}"}

    return r
