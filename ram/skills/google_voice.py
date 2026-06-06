"""Phone calls + SMS.

Google Voice has no official API. Two viable paths:
  1. Twilio (recommended, requires a Twilio number) — works out of the box.
  2. Google Voice via Playwright browser automation — fragile but free.

We default to Twilio if configured, fall back to a queued Playwright job.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from loguru import logger

from ram.core.config import settings
from ram.core.registry import skill


def _twilio():
    if not (settings.twilio_account_sid and settings.twilio_auth_token):
        return None
    try:
        from twilio.rest import Client
        return Client(settings.twilio_account_sid, settings.twilio_auth_token)
    except ImportError:
        return None


@skill(
    name="send_sms",
    description="Send an SMS to a phone number. Always confirm with user before sending.",
    sensitive=True,
)
def send_sms(to_number: str, message: str) -> str:
    client = _twilio()
    if client and settings.twilio_sms_from:
        try:
            m = client.messages.create(from_=settings.twilio_sms_from, to=to_number, body=message)
            return f"sent SMS to {to_number} (sid {m.sid})"
        except Exception as e:
            return f"ERROR: {e}"
    # Fallback — queue a job for the Google Voice automator
    return _queue_gvoice_job("sms", {"to": to_number, "message": message})


@skill(
    name="place_call",
    description=("Place a phone call. For the simple case 'leave a short voice message', "
                 "we use Twilio Programmable Voice with a TwiML <Say>. Confirm before calling."),
    sensitive=True,
)
def place_call(to_number: str, say_message: str) -> str:
    client = _twilio()
    if client and settings.twilio_sms_from:
        try:
            # Twilio needs a TwiML URL; we use the public echo endpoint twimlets.com
            from urllib.parse import quote
            twiml = f"http://twimlets.com/message?Message%5B0%5D={quote(say_message)}"
            call = client.calls.create(from_=settings.twilio_sms_from, to=to_number, url=twiml)
            return f"calling {to_number} (sid {call.sid})"
        except Exception as e:
            return f"ERROR: {e}"
    return _queue_gvoice_job("call", {"to": to_number, "message": say_message})


def _queue_gvoice_job(kind: str, payload: dict) -> str:
    """Queue a job for the Google Voice automator to pick up.

    The automator (ram/tools/gvoice_worker.py) is a separate process that owns
    a logged-in Chromium profile and drives voice.google.com. Decoupling lets
    the main agent stay async-safe.
    """
    q = settings.ram_data_dir / "gvoice_queue"
    q.mkdir(exist_ok=True)
    job = {"kind": kind, "payload": payload, "ts": time.time()}
    p = q / f"{int(time.time()*1000)}.json"
    p.write_text(json.dumps(job))
    return f"queued Google Voice {kind} job ({p.name}). Make sure gvoice_worker is running."
