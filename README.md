# 🐏 MyAssistant — Self-hosted Personal AI Assistant

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

This repository contains a self-hosted, modular personal assistant implemented in Python. It is built around the `myassistant/` package and supports multiple channels, voice, plugins, and a large collection of skills for family, personal, work, home, and productivity scenarios.

---

## What this codebase does

- Runs as a local assistant with a Python CLI and HTTP server
- Supports CLI, HTTP, Discord, Telegram, Twilio SMS/WhatsApp, and Windows tray channels
- Provides real-time voice via `/voice/realtime` plus REST speech endpoints
- Loads integrations automatically from `myassistant/skills/`
- Uses multiple LLM providers and optional local model support
- Includes safety, confirmation gating, undo, audit logging, and plugins

---

## Repo layout

- `myassistant/core/` — engine, settings, memory, permissions, voice, plugins, and skill registry
- `myassistant/channels/` — CLI, HTTP, Discord, Telegram, SMS, WhatsApp, tray, voice, and admin UI
- `myassistant/skills/` — integration modules for family, health, finance, work, home, and more
- `myassistant/tools/` — helper utilities such as browser automation and OAuth tools

---

## Quick start

### Prerequisites
- Python 3.11 or later
- Windows, macOS, or Linux
- At least one AI provider key or local model support

### Install

```bash
git clone https://github.com/yourusername/MyAssistant.git
cd MyAssistant
python -m venv .venv
.venv\Scripts\activate      # Windows
source .venv/bin/activate   # macOS / Linux
pip install -r requirements.txt
copy config\.env.example .env      # Windows
cp config/.env.example .env        # macOS / Linux
```

Edit `.env` and set at least:

```env
MYASSISTANT_OWNER_NAME=Your Name
MYASSISTANT_TIMEZONE=America/New_York
ANTHROPIC_API_KEY=sk-ant-...
```

### Run

```bash
python -m myassistant run --channel cli
python -m myassistant run --channel http
python -m myassistant run --channel discord,telegram
python -m myassistant run --channel all
python -m myassistant run --channel tray
```

If you do not have any provider configured yet, use:

```bash
python -m myassistant onboard
```

---

## Supported channels

| Channel | Notes |
|---|---|
| `cli` | Terminal chat interface |
| `http` | FastAPI server for web/PWA access |
| `discord` | Discord bot channel |
| `telegram` | Telegram bot channel |
| `sms` | Twilio SMS outbound channel |
| `whatsapp` | Twilio WhatsApp outbound channel |
| `tray` | Windows system tray chat window |

---

## Voice support

The HTTP channel includes voice support and exposes:
- `POST /voice` — audio upload and transcription
- `GET /voice/tts` — text-to-speech output
- `WebSocket /voice/realtime` — real-time voice conversation

Supported providers include Groq Whisper, OpenAI Whisper, ElevenLabs TTS, and optional local Whisper.

---

## Useful commands

```bash
python -m myassistant skills        # list registered skills
python -m myassistant providers     # show configured LLM providers and routing
python -m myassistant doctor        # run health and security checks
python -m myassistant mcp           # start MCP stdio server for tool integrations
python -m myassistant plugin list   # list installed plugins
python -m myassistant plugin install ./path/to/plugin
python -m myassistant plugin remove plugin_name
```

---

## Configuration

Configuration is stored in `.env` and populated from `config/.env.example`.

Important settings include:
- `MYASSISTANT_OWNER_NAME`
- `MYASSISTANT_TIMEZONE`
- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, etc.
- `DISCORD_BOT_TOKEN`
- `TELEGRAM_BOT_TOKEN`
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_SMS_FROM`, `TWILIO_WHATSAPP_FROM`
- `MYASSISTANT_HTTP_HOST`, `MYASSISTANT_HTTP_PORT`, `MYASSISTANT_HTTP_TOKEN`
- `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`
- `MYASSISTANT_LOCAL_WHISPER=true` for local Whisper STT

---

## Development

```bash
pip install -r requirements.txt
pip install ruff pytest
ruff check myassistant/
python -m compileall -q myassistant
pytest tests/
```

---

## Adding a new skill

1. Create a file under `myassistant/skills/`
2. Use `@skill(...)` from `myassistant.core.registry`
3. Add required env vars to `myassistant/core/config.py` and `config/.env.example`
4. Restart and run `python -m myassistant skills`

---

## License

MIT — see [LICENSE](LICENSE).
