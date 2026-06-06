# 🐏 Ram — Your Personal Life-OS Assistant

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

**Ram** is an open-source, self-hosted personal assistant that runs on your computer and is always a text (or voice) away. It combines the mental-load automation of [Ollie.ai](https://ollie.ai/) with deep integrations across your family life, personal wellbeing, and professional work — all powered by the best available AI with your own API keys (or a fully local model).

> *"Hey Ram, what's up with my utilities bill this month?"*
> *"Ram, debug the last call in prod."*
> *"Ram, find dinner spots within 10 minutes of me."*

---

## ✨ What makes Ram different

| Feature | Ram |
|---|---|
| **Privacy-first** | Runs 100% locally with HuggingFace models — your data never leaves your machine |
| **Any AI model** | 10+ cloud providers + any local HuggingFace model. Ram auto-picks the best one per task |
| **Every channel** | SMS, WhatsApp, Discord, Telegram, voice (real-time), Windows tray, iOS Shortcuts, browser |
| **Full life coverage** | Family + Personal + Work in one place — not just a chatbot |
| **Confirmation gates** | Every sensitive action (send email, place order, run code) pauses for your approval |
| **Open source** | MIT licensed. You own your data. No subscriptions. |

---

## 🗺️ Capability Overview

### 👨‍👩‍👧 Family
- **School email watcher** — parses permission slips, early-dismissal alerts, conference RSVPs; surfaces only what needs action
- **Family calendar + carpool nudges** — texts the right parent 30 minutes before pickup
- **Morning & evening briefings** — daily rundown texted to each parent
- **Shared lists** — grocery, weekend, packing, custom; drop it in chat, it's saved
- **Meal planner** — plan the week; ingredients auto-flow to the grocery list
- **Kids corner** — homework tracker, allowance, screen-time log, reading log, milestones
- **Safety** — family check-in, emergency packet, encrypted vault, deadman switch

### 🙋 Personal
- **Health** — Apple Health import, Oura/Fitbit wearables, medication tracking, symptom journal
- **Habits** — streaks, reminders, weekly review
- **Journal** — mood, energy, gratitude with semantic search ("remind me what I wrote about...")
- **Finance** — Plaid bank sync, budget tracking, anomaly detection, bill detection, receipt OCR, tax folder, subscription audit
- **Travel** — flight watch, auto-pack lists, currency converter, TripIt import
- **Commerce** — price tracker, returns radar, DoorDash/Instacart integration
- **Birthday autopilot** — never forget a birthday again

### 💼 Work
- **Projects & tasks** — priorities, due dates, statuses with Notion/Linear sync
- **Contacts / CRM-lite** — last-touch tracking, follow-up reminders, tags
- **Email triage** — smart categorisation, send replies with confirmation
- **Meeting prep** — agenda builder, background research, action-item tracker
- **Standup composer** — auto-generates your daily standup from task activity
- **GitHub** — PR list, create issues, comment on PRs
- **Slack** — search, post, read channels
- **OOO autoresponder** — set your out-of-office on/off via chat

### 💻 Coding & DevOps
- **Production debugging** — `"Hey Ram, debug the last call in prod"`: pulls CloudWatch errors + X-Ray traces, reads source, LLM root-cause analysis, optional GitHub issue
- **Code review** — diff any branch, get bug + security + performance feedback
- **Repo navigation** — clone, read files, grep, blame, log across multiple repos
- **Sandboxed shell** — run pytest, linters, build tools with an allowlist
- **AWS** — CloudWatch log filtering, Insights queries, Lambda config inspection, X-Ray traces

### 🏠 Smart Home & Local
- **Home Assistant** — read device states, call services (lights, locks, thermostats)
- **Ring/Nest** — doorbell events
- **Print at home** — send documents to your printer via chat
- **Find My** — locate family members' devices

---

## 🤖 AI Provider Support

Ram automatically selects the best model for each task type. Add API keys for the providers you want; Ram falls back gracefully if one is unavailable.

| Provider | Best for | Env var |
|---|---|---|
| **Anthropic Claude** | Reasoning, coding, long context | `ANTHROPIC_API_KEY` |
| **OpenAI GPT** | Coding, vision, embeddings | `OPENAI_API_KEY` |
| **Google Gemini** | 1M-token context, web search | `GOOGLE_API_KEY` |
| **Azure OpenAI** | Enterprise / compliance | `AZURE_OPENAI_API_KEY` |
| **AWS Bedrock** | AWS-native workloads | `AWS_ACCESS_KEY_ID` |
| **Perplexity** | Fresh web data (search tasks) | `PERPLEXITY_API_KEY` |
| **Groq** | Fastest inference + Whisper STT | `GROQ_API_KEY` |
| **Mistral** | European data residency | `MISTRAL_API_KEY` |
| **Together.ai** | DeepSeek and other open models | `TOGETHER_API_KEY` |
| **Ollama** | Local models, always private | auto-detected |
| **HuggingFace local** | One-click install, fully offline | `HF_TOKEN` (optional) |

### Local AI (HuggingFace)

Ram has a built-in model manager that detects your hardware and recommends the best models:

```
You: What local AI models can I run on my laptop?
Ram: Your hardware: 16 GB RAM, GPU VRAM: 8 GB (NVIDIA CUDA)
     Recommended: Phi-3 Medium 14B, Qwen 2.5 7B, Gemma 2 9B...
     
You: Download Phi-3 for me
Ram: ⚠️ About to download microsoft/Phi-3-mini-4k-instruct (~2.4 GB). Reply YES to proceed.
You: yes
Ram: ✅ Phi-3 Mini installed via Ollama and ready to use!
```

Supported model categories: **chat**, **code**, **embeddings**, **speech-to-text**, **vision**

---

## 🎤 Voice Interface

Ram supports real-time voice conversation — start talking, and Ram starts answering before it finishes thinking (just like the Gemini app).

**Voice channels:**
- **Browser** — WebSocket endpoint at `/voice/realtime` (included in the web UI)
- **Windows tray** — click the microphone button in the chat window
- **iOS Shortcuts** — POST audio to `/voice/transcribe`

**STT providers** (in priority order):
1. Groq Whisper — fastest, free tier (`GROQ_API_KEY`)
2. OpenAI Whisper — highest accuracy (`OPENAI_API_KEY`)
3. Local Whisper — fully offline (`RAM_LOCAL_WHISPER=true`)

**TTS providers:**
1. ElevenLabs — most natural (`ELEVENLABS_API_KEY` + `ELEVENLABS_VOICE_ID`)
2. OpenAI TTS — good quality (`OPENAI_API_KEY`)
3. pyttsx3 — always works, no API needed

---

## 📡 Channels

| Channel | What it needs |
|---|---|
| **CLI** | Nothing — works out of the box |
| **SMS** | Twilio (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_SMS_FROM`) |
| **WhatsApp** | Twilio WhatsApp sandbox (`TWILIO_WHATSAPP_FROM`) |
| **Discord** | Discord bot (`DISCORD_BOT_TOKEN`) |
| **Telegram** | Telegram bot (`TELEGRAM_BOT_TOKEN`) |
| **Voice (real-time)** | Any STT/TTS provider — see above |
| **iMessage** | BlueBubbles server (`BLUEBUBBLES_URL`, `BLUEBUBBLES_PASSWORD`) |
| **HTTP / PWA** | Nothing — built-in web server at port 8765 |
| **Windows tray** | `pystray` + `Pillow` — `pip install pystray Pillow` |
| **iOS Shortcuts** | HTTP channel running — use `/shortcut/ask` endpoint |

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11 or later
- Windows, macOS, or Linux
- At least one LLM provider API key (or Ollama installed locally)

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/ram.git
cd ram

# 2. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate      # Windows
source .venv/bin/activate   # macOS / Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy the example configuration
copy .env.example .env      # Windows
cp .env.example .env        # macOS / Linux

# 5. Edit .env and add at minimum:
#    ANTHROPIC_API_KEY=sk-ant-...   (or any other provider key)
#    RAM_OWNER_NAME=Your Name

# 6. Run Ram
python -m ram                          # CLI (default)
python -m ram --channel http           # Web UI + API at http://localhost:8765
python -m ram --channel tray           # Windows system tray
python -m ram --channel cli,http,tray  # All channels simultaneously
```

### First run

```
You: Hi Ram, I'm [your name]. I live in San Francisco.
Ram: Nice to meet you! I've saved your name and location.
     I'm ready to help with anything — family, personal, or work.
     
You: What can you do?
Ram: Here's a quick overview of what I can help with today:
     📅 Calendar — I can see you have 3 events tomorrow...
     [continues with personalised briefing]
```

### Using the Config UI

Open `http://localhost:8765/admin` in your browser (when HTTP channel is running) to:
- Connect AI providers (test each one with the **Test** button)
- Set up messaging channels (WhatsApp, Discord, SMS, Telegram)
- Configure safety settings and the encrypted vault
- Browse, download, and manage local HuggingFace models
- View the audit log of all actions taken

---

## ⚙️ Configuration

All configuration is via environment variables in `.env`. The admin UI at `/admin` provides a visual editor for all settings.

### Essential settings

```env
# Your identity
RAM_OWNER_NAME=Jane Smith
RAM_TIMEZONE=America/New_York

# At least one LLM provider
ANTHROPIC_API_KEY=sk-ant-...

# Optional: messaging channels
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_SMS_FROM=+15551234567
DISCORD_BOT_TOKEN=...
TELEGRAM_BOT_TOKEN=...

# Optional: voice
GROQ_API_KEY=...              # fastest STT (Whisper)
ELEVENLABS_API_KEY=...        # natural TTS
ELEVENLABS_VOICE_ID=...

# Optional: AWS (for production debugging)
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1

# Optional: coding
RAM_REPO_WORKSPACE=/path/to/repos  # where to clone repos

# Optional: local AI
HF_TOKEN=hf_...                    # HuggingFace access token (for gated models)
RAM_LOCAL_WHISPER=true             # use local Whisper for offline STT
```

See `.env.example` for the full list of ~60 configurable options.

---

## 🔒 Safety & Correctness

Ram is designed to be safe to deploy in a household with children:

### Confirmation gates
Every action that is irreversible or has external side effects pauses and asks for your explicit **YES** before proceeding:
- Sending email / SMS / WhatsApp
- Placing orders (DoorDash, Instacart)
- Making voice calls
- Deleting data
- Running shell commands
- Deploying code or modifying cloud resources

### Dry-run mode
Prefix any message with **"dry run"** to see exactly what Ram would do without doing it:
```
You: dry run send an email to my boss about tomorrow's meeting
Ram: Would send email to boss@company.com
     Subject: Re: Tomorrow's meeting
     Body: Hi, just confirming our 2pm meeting tomorrow...
     (No email sent — dry run only)
```

### Undo
Type **"undo"** within 5 minutes to reverse the last reversible action.

### Encrypted vault
Store sensitive information (passwords, PINs, account numbers) in an encrypted vault:
```
You: Store my Chase PIN in the vault
Ram: ⚠️ About to store secret 'Chase PIN' in vault. Reply YES to confirm.
```
Protected by `OLLIE_VAULT_PASSPHRASE` — never sent to any AI model.

### Permissions
- Kids are automatically blocked from finance, vault, and communications skills
- Per-member skill allow/deny lists configurable

### Audit log
Every action is logged to SQLite with timestamp, user, action, and payload.
View at `/admin` → Audit Log tab.

---

## 🧩 Architecture

```
ram/
├── core/
│   ├── agent.py          # Main agent loop: multi-provider LLM + tool use + memory
│   ├── llm.py            # Multi-provider router (10 providers, task-based selection)
│   ├── config.py         # All settings (pydantic-settings, .env-based)
│   ├── memory.py         # SQLAlchemy message + fact store
│   ├── contexts.py       # Life-OS data model (Tasks, Notes, Finance, Health, etc.)
│   ├── family.py         # Family roster, member management
│   ├── registry.py       # Skill decorator + auto-discovery
│   ├── voice.py          # STT + TTS (multi-provider + streaming)
│   ├── confirm.py        # Confirmation gate (sensitive action approval)
│   ├── undo.py           # Undo stack (5-minute reversible action window)
│   ├── planner.py        # Plan-then-execute for complex multi-step tasks
│   ├── audit.py          # Audit log (every action to SQLite)
│   ├── permissions.py    # Per-member skill allow/deny
│   ├── vector_memory.py  # Semantic recall via embeddings + cosine similarity
│   ├── vault.py          # Fernet-encrypted secret store
│   ├── proactive.py      # Scheduled jobs (briefings, reminders, price checks)
│   └── suggestions.py    # Proactive suggestions engine
├── channels/
│   ├── cli_channel.py    # Interactive terminal
│   ├── http_channel.py   # FastAPI: REST + WebSocket
│   ├── voice_channel.py  # Real-time voice WebSocket (/voice/realtime)
│   ├── tray_channel.py   # Windows system tray + Tkinter chat window
│   ├── sms_channel.py    # Twilio SMS
│   ├── whatsapp_channel.py
│   ├── discord_channel.py
│   ├── telegram_channel.py
│   └── admin_ui.py       # Full configuration web UI
├── skills/
│   ├── briefing.py       # Morning/evening briefings
│   ├── calendar_skill.py # Google Calendar read/write
│   ├── email_triage.py   # Smart email categorisation + action
│   ├── finance.py        # Budgets, expenses, reports
│   ├── health.py         # Health log, habit tracking
│   ├── github_skill.py   # GitHub PRs, issues, comments
│   ├── coding/           # Repo nav, git, shell, code review
│   │   ├── repo.py       # File tree, read, grep, diff
│   │   ├── git_skill.py  # Log, blame, commit, push
│   │   ├── shell.py      # Sandboxed exec, test runner, linter
│   │   ├── code_review.py# LLM-powered review, explain, find-bug
│   │   └── debug_prod.py # "Debug last call in prod" composite skill
│   ├── aws/              # CloudWatch, Lambda, X-Ray
│   │   ├── cloudwatch.py
│   │   ├── lambda_skill.py
│   │   └── xray.py
│   └── hf/               # HuggingFace local model management
│       ├── catalog.py    # Curated model recommendations by hardware tier
│       ├── manager.py    # Download, install, run local models
│       └── skills.py     # Agent-facing skill functions
└── __main__.py           # CLI entry point
```

### Skill system

Skills are plain Python functions decorated with `@skill`:

```python
from ram.core.registry import skill

@skill(
    name="get_weather",
    description="Get current weather for a location",
    requires=["openweathermap_api_key"],  # only active when this env var is set
)
def get_weather(location: str) -> str:
    ...
```

Drop the file in `ram/skills/` — it's auto-discovered on startup. No registration needed.

### Adding a new integration

1. Create `ram/skills/my_integration.py`
2. Decorate your functions with `@skill(...)`
3. Add any required env vars to `ram/core/config.py` and `.env.example`
4. Run `python -m ram skills` to verify it shows up

---

## 🛠️ Development

```bash
# Install dev dependencies
pip install -r requirements.txt
pip install ruff pytest

# Lint
ruff check ram/

# Type check (optional, not enforced)
mypy ram/ --ignore-missing-imports

# Test
pytest tests/

# Compile check (quick sanity)
python -m compileall -q ram

# List all registered skills
python -m ram skills

# Show which LLM providers are configured + routing table
python -m ram providers
```

### Project conventions

- **Python 3.11+** — use `from __future__ import annotations` in every module
- **Pydantic v2** for all data models and settings
- **SQLAlchemy 2.0** for all database access — no raw SQL
- **loguru** for logging — `from loguru import logger`
- **Sensitive actions** — set `sensitive=True` on the `@skill` decorator; the agent will gate on user confirmation automatically
- **No hard imports at module level** — optional dependencies (boto3, pystray, etc.) must be imported inside functions and catch `ImportError` gracefully

---

## 🤝 Contributing

We welcome contributions! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

**Good first issues:**
- Add a new skill (see `ram/skills/` for examples)
- Add support for a new messaging channel
- Improve the admin UI
- Add tests for existing skills
- Improve documentation

---

## 📄 License

MIT — see [LICENSE](LICENSE). You own your data and your instance.

---

## 🙏 Acknowledgements

- [Ollie.ai](https://ollie.ai/) — the inspiration for the family life-OS concept
- [Anthropic](https://anthropic.com/) — Claude powers the default reasoning loop
- [HuggingFace](https://huggingface.co/) — local model ecosystem
- All the open-source model creators: Meta (Llama), Microsoft (Phi-3), Google (Gemma), Mistral, Qwen
