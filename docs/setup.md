# Setup (full path, ~30 minutes the first time)

## 1. Install

```powershell
cd "c:\Users\sagupta7\OneDrive - Cisco\Desktop\MyAssistant"
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium   # only if you want Google Voice / food ordering
```

## 2. Configure

```powershell
copy config\.env.example .env
notepad .env
```

You need at minimum `ANTHROPIC_API_KEY`. Add others as you wire up integrations
— skills no-op gracefully when their creds are missing.

## 3. Try it locally

```powershell
python -m myassistant run --channel cli
```

Talk to it in your terminal. Try:
- "What time is it?"
- "Remind me to call mom in 5 minutes."
- "List my skills."

```powershell
python -m myassistant skills    # see every skill, ✓ = active, · = waiting on creds
```

## 4. Wire up channels

### Discord (recommended)
1. Create a bot at https://discord.com/developers/applications
2. Enable Message Content Intent
3. Invite to a server (or use direct DMs)
4. `DISCORD_BOT_TOKEN` and `DISCORD_OWNER_USER_ID` (your numeric user id) in `.env`

### Telegram
1. `@BotFather` → `/newbot` → token → `TELEGRAM_BOT_TOKEN`
2. Send any DM to your new bot, then `https://api.telegram.org/bot<TOKEN>/getUpdates` → grab `chat.id` → `TELEGRAM_OWNER_CHAT_ID`

### HTTP / Mobile PWA
1. Set `MYASSISTANT_HTTP_TOKEN` to a long random string
2. Make `MYASSISTANT_HTTP_PORT` reachable from your phone (Tailscale is easiest)
3. On your phone: visit `https://<your-host>:8765/app`, tap "Add to Home Screen"
4. First launch: tap ⚙ Settings, enter the URL + token

### WhatsApp (Twilio)
Twilio sandbox is free for testing. Set `TWILIO_*` in `.env`, configure the
Twilio inbound webhook to `https://<your-host>:8765/twilio/whatsapp`.

## 5. Run with all channels

```powershell
python -m myassistant run --channel all
```

## 6. Install as a Windows service (production)

```powershell
# As Administrator
powershell -ExecutionPolicy Bypass -File scripts\install_service.ps1
```

Service runs on boot, restarts on failure. Logs at `data\logs\myassistant.log` and in
the Windows Application Event Log.

## 7. Optional: browser worker for Google Voice + food ordering

In a separate terminal:
```powershell
python -m myassistant.tools.browser_worker
```

A Chromium window opens; log in to voice.google.com, doordash.com,
ubereats.com once. Sessions persist. Leave the window minimized.

## 8. Test the full loop

From your phone (over Tailscale, Discord, Telegram — pick one):
- "MyAssistant, what's on my calendar today?"
- "MyAssistant, set the thermostat to 68."
- "MyAssistant, find a Starbucks near 1 Market Street San Francisco."
- "MyAssistant, text Dan via group chat that I need to cancel Friday class." → MyAssistant should ask for confirmation, then send.
- "MyAssistant, open VS Code and tell Claude to fix the build."
