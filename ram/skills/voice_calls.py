"""Outbound voice calls + IVR — Twilio Voice."""
from __future__ import annotations

from ram.core.config import settings
from ram.core.registry import skill


def _client():
    if not (settings.twilio_account_sid and settings.twilio_auth_token):
        return None
    try:
        from twilio.rest import Client
        return Client(settings.twilio_account_sid, settings.twilio_auth_token)
    except ImportError:
        return None


@skill(
    name="voice_call_say",
    description=("Place an outbound phone call that speaks a message via TTS, then hangs up. "
                 "Use for callbacks, appointment confirmations, or alerting someone hands-free. "
                 "Confirm before placing."),
    requires=["twilio_account_sid", "twilio_voice_from"],
    sensitive=True,
)
def voice_call_say(to_number: str, message: str) -> str:
    c = _client()
    if not c:
        return "ERROR: twilio not configured"
    twiml = f"<Response><Say voice='Polly.Joanna'>{message}</Say></Response>"
    call = c.calls.create(to=to_number, from_=settings.twilio_voice_from, twiml=twiml)
    return f"call placed sid={call.sid} to {to_number}"


@skill(
    name="voice_call_ivr",
    description=("Place an outbound call that says a prompt, gathers DTMF digits, and "
                 "hangs up. Returns the digits collected. Use for 'call the school and "
                 "press 1 for absence line' type tasks."),
    requires=["twilio_account_sid", "twilio_voice_from"],
    sensitive=True,
)
def voice_call_ivr(to_number: str, prompt: str, digits_to_send: str = "") -> str:
    c = _client()
    if not c:
        return "ERROR: twilio not configured"
    if digits_to_send:
        twiml = (f"<Response><Pause length='2'/><Say>{prompt}</Say>"
                 f"<Play digits='{digits_to_send}'/></Response>")
    else:
        twiml = f"<Response><Say>{prompt}</Say></Response>"
    call = c.calls.create(to=to_number, from_=settings.twilio_voice_from, twiml=twiml)
    return f"ivr call sid={call.sid}"
