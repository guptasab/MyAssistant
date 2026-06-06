"""Centralized config. Loads .env + optional config.yaml. Single source of truth."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Core
    anthropic_api_key: str = ""
    ram_owner_name: str = "Owner"
    ram_timezone: str = "UTC"
    ram_data_dir: Path = Path("./data")

    # Agent identity — name used in UI, wake word, and system prompt
    # Change this to rename the assistant (e.g. "Aria", "Max", "Jarvis")
    squire_agent_name: str = "Squire"
    squire_agent_website: str = "mysquire.ai"

    ram_model_main: str = "claude-opus-4-7"
    ram_model_fast: str = "claude-haiku-4-5-20251001"

    # ── Memory settings ───────────────────────────────────────────────────
    # Set MEMORY_ENABLED=false to disable all persistence (useful for kiosk/shared deployments)
    memory_enabled: bool = True
    # How many days of conversation history to keep before compressing into summaries
    memory_retention_days: int = 365
    # Maximum recent messages loaded into every LLM context window
    memory_context_messages: int = 50
    # Automatically extract facts/preferences from conversations after each session
    memory_auto_learn: bool = True
    # Incognito mode — when True, nothing is saved (overridable per-session via skill)
    memory_incognito_default: bool = False

    # Channels
    discord_bot_token: str = ""
    discord_owner_user_id: str = ""
    telegram_bot_token: str = ""
    telegram_owner_chat_id: str = ""

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = ""
    twilio_sms_from: str = ""

    ram_http_host: str = "0.0.0.0"
    ram_http_port: int = 8765
    ram_http_token: str = ""

    # Skills
    brave_search_api_key: str = ""
    tavily_api_key: str = ""
    serper_api_key: str = ""
    google_maps_api_key: str = ""
    google_oauth_client_secrets: Optional[Path] = None
    ha_base_url: str = ""
    ha_token: str = ""

    # Voice
    openai_api_key: str = ""
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""

    # Multi-provider LLM routing
    google_api_key: str = ""
    gemini_api_key: str = ""
    perplexity_api_key: str = ""
    groq_api_key: str = ""
    mistral_api_key: str = ""
    together_api_key: str = ""
    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_api_version: str = "2024-08-01-preview"
    azure_openai_deployment: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = ""
    ollama_base_url: str = "http://localhost:11434"

    # Ollie / family + life-OS settings
    ollie_briefing_time: str = "07:00"
    ollie_poll_interval_minutes: int = 15
    ollie_evening_brief_time: str = "20:30"
    ollie_default_context: str = "personal"
    ollie_weekly_review_day: int = 6                  # 0=Mon..6=Sun
    ollie_weekly_review_time: str = "18:00"
    ollie_admin_password: str = ""                    # gate the /admin UI
    ollie_vault_passphrase: str = ""                  # encrypts secret vault
    ollie_deadman_hours: int = 24
    ollie_deadman_contact: str = ""                   # "+15551234567"

    # Slack (work integration)
    slack_bot_token: str = ""
    slack_user_id: str = ""

    # Productivity
    notion_api_key: str = ""
    linear_api_key: str = ""
    github_token: str = ""

    # Coding / DevOps
    ram_repo_workspace: str = ""                      # local path for cloned repos
    ram_shell_allowlist: str = ""                     # extra comma-separated allowed cmd prefixes
    ram_shell_timeout: int = 60                       # max seconds for exec_shell
    github_default_repo: str = ""                     # "owner/repo" for default issue creation

    # Voice
    ram_local_whisper: bool = False                   # use local Whisper model for STT (offline)

    # Local AI / HuggingFace
    hf_token: str = ""                                # HuggingFace access token (for gated models)

    # Microsoft (Outlook / Teams / OneDrive)
    microsoft_client_id: str = ""                     # Azure App Registration client ID
    microsoft_client_secret: str = ""                 # Azure App Registration client secret
    microsoft_tenant_id: str = "common"               # Tenant ID or "common" for multi-tenant

    # New LLM providers (no Anthropic dependency — all optional)
    deepseek_api_key: str = ""                        # DeepSeek — best open-weight code + reasoning
    fireworks_api_key: str = ""                       # Fireworks AI — fast open-model inference
    openrouter_api_key: str = ""                      # OpenRouter — 100+ models via one key
    cerebras_api_key: str = ""                        # Cerebras — world's fastest chip inference
    lmstudio_base_url: str = ""                       # LM Studio local server (e.g. http://localhost:1234)
    venice_api_key: str = ""                          # Venice AI — privacy-first, no logs

    # Location services
    squire_home_address: str = ""                     # Default home address for location-based queries
    squire_work_address: str = ""                     # Default work address
    squire_default_city: str = ""                     # City for when GPS is unavailable
    ipinfo_token: str = ""                            # IPInfo API token for IP geolocation

    # Alexa + Google Home integration
    alexa_skill_id: str = ""                          # Alexa Developer Console Skill ID
    google_action_project_id: str = ""                # Google Actions project ID

    # MCP (Model Context Protocol) servers to consume as tool providers
    # Format: comma-separated stdio://path or http://host:port
    mcp_servers: str = ""

    # Finance
    plaid_client_id: str = ""
    plaid_secret: str = ""
    plaid_env: str = "sandbox"                        # sandbox | development | production

    # Health & wearables
    fitbit_client_id: str = ""
    fitbit_client_secret: str = ""
    oura_access_token: str = ""

    # Commerce / errands
    instacart_api_key: str = ""
    doordash_developer_key: str = ""

    # Smart home
    ring_email: str = ""
    ring_password: str = ""

    # Twilio Voice (for outbound calls + IVR)
    twilio_voice_from: str = ""

    # iMessage relay (BlueBubbles)
    bluebubbles_url: str = ""
    bluebubbles_password: str = ""

    # Travel
    aviationstack_key: str = ""
    flightaware_key: str = ""

    def ensure_dirs(self) -> None:
        self.ram_data_dir.mkdir(parents=True, exist_ok=True)
        (self.ram_data_dir / "logs").mkdir(exist_ok=True)
        (self.ram_data_dir / "audio").mkdir(exist_ok=True)


settings = Settings()
settings.ensure_dirs()
