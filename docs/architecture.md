# Architecture

## Goals

1. **Always-on**: lives as a Windows service, auto-restarts, survives reboots.
2. **Reachable from anywhere**: phone (PWA + Discord + Telegram + optional WhatsApp), desktop, voice or text.
3. **Driving-safe**: every channel that the owner uses while driving exposes
   push-to-talk and speaks responses back. The PWA does this natively with the
   Web Speech API + a server-side Whisper transcription endpoint.
4. **Tool-using agent**: Claude with prompt caching + function calling. The
   set of tools is the set of skills the agent can invoke.
5. **Extensible**: adding a new capability is a single decorated Python
   function. No code touches the agent loop, channel adapters, or registry.

## Process model

A single Python process hosts:

- The asyncio event loop (one per channel adapter coroutine).
- The Claude agent (shared across all channels — same brain everywhere).
- APScheduler for reminders / proactive nudges.
- FastAPI + uvicorn for the HTTP/WebSocket channel (mobile PWA, Twilio webhooks).
- Discord client (`discord.py`), Telegram client (`python-telegram-bot`).

Two **optional sidecar processes** decouple long-running browser sessions:

- `ram.tools.browser_worker` — owns a persistent Chromium profile (data/browser_profile/)
  and drains queued jobs for Google Voice + DoorDash + UberEats.
- These run as scheduled tasks rather than in the main service, so the agent
  stays async-safe and a crashing browser doesn't kill Ram.

## Conversation model

Every channel calls `agent.handle(user_id, text)` with a stable per-user id
(e.g. `discord:1234`, `telegram:5678`, `http:mobile`). The agent loads the
last 30 turns from SQLite, sends them to Claude with the system prompt + tool
definitions (both prompt-cached so repeat turns are cheap), runs any tool
calls, and loops until Claude returns end_turn.

**Long-term memory** is separate from conversation history — it's a
key→value table of facts, surfaced in the system prompt every turn. The
agent can write to it via `remember_fact` and reads from it on every reply.

## Why these choices

- **Python**: best LLM + integration ecosystem; pywin32 for service support.
- **Anthropic Claude with tool use**: native function calling, strong agentic
  behaviour, prompt caching keeps cost low for the stable system prompt.
- **SQLite**: zero-setup persistence, fine for single-user load.
- **Home Assistant as the smart-home bridge** instead of Alexa direct: avoids
  the painful Login With Amazon + custom skill flow, and you get a unified
  REST API across Alexa + HomeKit + Hue + Nest + Ecobee + everything else.
- **Twilio + browser-automation fallback for phone/SMS**: Twilio is the clean
  path; Google Voice automation is the free path. We support both.
- **PWA over native app**: installable, offline-capable, single codebase,
  iOS+Android, push-to-talk via MediaRecorder + native TTS, no app-store hassle.

## Reaching the home desktop from outside

Three options, in increasing order of complexity:
1. **Tailscale / Twingate / WireGuard** — give the PWA the tailnet hostname.
   Zero port-forwarding. Recommended.
2. **Cloudflare Tunnel** — public HTTPS endpoint with no inbound firewall holes.
3. **Port-forward 8765** + dynamic-DNS + Let's Encrypt cert (DIY).

In all cases, `RAM_HTTP_TOKEN` provides app-level auth on top of network auth.

## Threat model

Ram has powerful tools (run shell commands, send messages, place orders). The
defenses:
- All sensitive skills require confirmation via the system prompt.
- HTTP API requires a long bearer token.
- Discord / Telegram channels are pinned to a single owner user/chat id —
  other senders are ignored.
- The Windows service runs as the user account (not LocalSystem) so it can't
  do anything the user couldn't.

## Failure modes & extension points

- **LLM API down**: the agent returns "(Ram is having trouble reaching the model)";
  channels stay up and queue messages.
- **A skill module raises**: caught in `_run_tool`, surfaced to the LLM as
  `ERROR running ...`, which the LLM will explain to the user.
- **Adding a new channel**: subclass `ram.channels.base.Channel`, implement
  `start()` + optional `send()`, register in `ram/__main__.py`.
- **Swapping the LLM**: change `RAM_MODEL_MAIN` and adjust the
  `Agent._tools()` schema-conversion if the new provider expects a different
  tool format.
