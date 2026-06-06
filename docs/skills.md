# Skills — what each one needs

Skills are auto-discovered from `ram/skills/`. Each one declares its required
env vars; the agent only sees skills whose creds are present, so missing
integrations don't pollute the tool list.

| Skill module          | Tools exposed                                          | Required env / setup |
|-----------------------|--------------------------------------------------------|----------------------|
| `web_search`          | `web_search`, `fetch_url`                              | `TAVILY_API_KEY` (preferred) or `BRAVE_SEARCH_API_KEY` / `SERPER_API_KEY` |
| `reminders`           | `set_reminder`, `list_reminders`, `cancel_reminder`    | none |
| `memory_skill`        | `remember_fact`, `recall_fact`, `list_facts`           | none |
| `calendar_skill`      | `calendar_today`, `calendar_day`, `schedule_event`, `find_free_slot` | `GOOGLE_OAUTH_CLIENT_SECRETS` JSON + one-time `python -m ram.tools.google_auth` |
| `smart_home`          | `list_devices`, `set_thermostat`, `turn_on`, `turn_off`, `run_scene` | `HA_BASE_URL`, `HA_TOKEN` (Home Assistant long-lived token; HA integrates Alexa, Hue, Nest, Ecobee, etc.) |
| `google_voice`        | `send_sms`, `place_call`                               | Twilio creds preferred; falls back to the browser-automation worker for free Google Voice |
| `maps`                | `find_nearby`, `traffic_eta`, `geocode`                | `GOOGLE_MAPS_API_KEY` |
| `food`                | `find_food`, `order_food`                              | `GOOGLE_MAPS_API_KEY` for discovery; `order_food` queues jobs the browser worker executes against your logged-in DoorDash / UberEats session |
| `system_control`      | `open_app`, `run_command`, `list_running_apps`, `focus_window`, `type_text` | Windows host; no extra creds |
| `notify`              | `notify_owner`                                         | none — fans out to every active channel |
| `utils`               | `current_time`, `calculator`                           | none |

## Sensitive skills

Some skills (`schedule_event`, `set_thermostat`, `turn_on`/`off`, `send_sms`,
`place_call`, `order_food`, `open_app`, `run_command`, `focus_window`,
`type_text`) are flagged `sensitive=True`. The agent's system prompt tells it
to confirm with the owner before invoking them. Read-only skills (search,
calendar lookup, find_nearby, traffic_eta) execute without confirmation.

## Adding a skill

Create `ram/skills/<your_skill>.py`:

```python
from ram.core.registry import skill

@skill(
    name="get_stock_price",
    description="Look up the current price for a stock ticker.",
    requires=["ALPHAVANTAGE_API_KEY"],  # skill is hidden if env var missing
)
def get_stock_price(ticker: str) -> str:
    import httpx, os
    key = os.environ["ALPHAVANTAGE_API_KEY"]
    r = httpx.get("https://www.alphavantage.co/query",
                  params={"function": "GLOBAL_QUOTE", "symbol": ticker, "apikey": key})
    return r.json()["Global Quote"]["05. price"]
```

Add `ALPHAVANTAGE_API_KEY` to `ram/core/config.py:Settings` so it picks up
from `.env`. Restart Ram. The agent will autonomously call it whenever
relevant.

## Sensitive-skill confirmation flow (how it works)

The agent prompt directs Claude to:

> Confirm before any irreversible action (sending messages, placing orders,
> calling people, changing thermostat by more than 5 degrees, etc.).

So if you say "order me a pizza", Claude will reply with the full proposed
order and ask "OK to place?" before actually calling `order_food`. This works
well in practice because the LLM is generally cautious about side-effectful
tools, and because the descriptions on those tools explicitly say "confirm
with the user before calling."

If you want stricter enforcement (block tool execution until a separate
"yes" message), wrap the call site in `ram/core/agent.py:_run_tool` with a
check on `skill.sensitive` and an out-of-band confirmation queue.
