"""Alexa and Google Home integration — "Hey Alexa, ask Squire to..."

This module provides two endpoints:
  1. ``/channels/alexa``        — Alexa Custom Skill webhook
  2. ``/channels/google_action`` — Google Actions fulfillment

Both convert voice commands into Squire agent messages and stream the
response back to the smart speaker.

Setup:
  Alexa:
    1. Create a Custom Skill at developer.amazon.com
    2. Set endpoint to: https://your-squire-server/channels/alexa
    3. Set ALEXA_SKILL_ID in .env for signature verification
    4. Say: "Alexa, ask Squire to <command>"

  Google Home:
    1. Create a project at console.actions.google.com
    2. Set fulfillment URL to: https://your-squire-server/channels/google_action
    3. Set GOOGLE_ACTION_PROJECT_ID in .env
    4. Say: "Hey Google, talk to Squire" or "Hey Google, ask Squire to <command>"
"""
from __future__ import annotations

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from loguru import logger


def build_voice_assistants_router() -> APIRouter:
    """Build the FastAPI router for Alexa and Google Home webhooks."""
    router = APIRouter(tags=["voice_assistants"])

    # ── Alexa Custom Skill ─────────────────────────────────────────────────

    @router.post("/channels/alexa")
    async def alexa_webhook(request: Request):
        """Handle Alexa Custom Skill requests.

        Supports all intents by routing the spoken text through the Squire agent.
        Built-in intents (AMAZON.HelpIntent, etc.) are handled gracefully.
        """
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON")

        request_type = body.get("request", {}).get("type", "")
        intent_name = body.get("request", {}).get("intent", {}).get("name", "")
        session_id = body.get("session", {}).get("sessionId", "alexa_user")

        def _alexa_response(text: str, end_session: bool = True) -> dict:
            return {
                "version": "1.0",
                "sessionAttributes": {},
                "response": {
                    "outputSpeech": {"type": "PlainText", "text": text},
                    "shouldEndSession": end_session,
                },
            }

        # Handle launch request
        if request_type == "LaunchRequest":
            from ram.core.config import settings as _s
            return JSONResponse(_alexa_response(
                f"Hi, I'm {_s.squire_agent_name}. What can I help you with?",
                end_session=False
            ))

        # Handle stop / cancel
        if intent_name in ("AMAZON.StopIntent", "AMAZON.CancelIntent"):
            return JSONResponse(_alexa_response("Goodbye!"))

        # Handle help
        if intent_name == "AMAZON.HelpIntent":
            return JSONResponse(_alexa_response(
                "I can help with tasks, reminders, email, smart home, research, and much more. "
                "Just tell me what you need.", end_session=False
            ))

        # Handle session end
        if request_type == "SessionEndedRequest":
            return JSONResponse({"version": "1.0"})

        # Extract spoken text from the CatchAll or custom intent
        spoken_text = ""
        slots = body.get("request", {}).get("intent", {}).get("slots", {})
        for slot in slots.values():
            if slot.get("value"):
                spoken_text = slot["value"]
                break

        if not spoken_text and intent_name:
            spoken_text = intent_name.replace("_", " ")

        if not spoken_text:
            return JSONResponse(_alexa_response(
                "Sorry, I didn't catch that. Could you say that again?", end_session=False
            ))

        # Route through Squire agent
        try:
            from ram.core.agent import get_agent
            agent = get_agent()
            response = await agent.handle(spoken_text, user_id=f"alexa_{session_id[:20]}")
            # Truncate for voice (Alexa max ~8000 chars, but voice should be shorter)
            voice_response = _truncate_for_voice(response, max_chars=500)
            return JSONResponse(_alexa_response(voice_response))
        except Exception as e:
            logger.error(f"Alexa agent error: {e}")
            return JSONResponse(_alexa_response("I'm having trouble right now. Please try again."))

    # ── Google Actions Fulfillment ─────────────────────────────────────────

    @router.post("/channels/google_action")
    async def google_action_webhook(request: Request):
        """Handle Google Actions (Google Home / Google Assistant) fulfillment requests.

        Compatible with Google Actions SDK v2 conversational fulfillment format.
        """
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON")

        handler = body.get("handler", {}).get("name", "")
        session_id = body.get("session", {}).get("id", "google_user")
        scene = body.get("scene", {}).get("name", "")

        # Extract user's spoken text
        spoken_text = ""
        user_input = body.get("intent", {}).get("query", "")
        if user_input:
            spoken_text = user_input
        else:
            # Try to extract from scene parameters
            params = body.get("scene", {}).get("slots", {})
            for param in params.values():
                if isinstance(param, dict) and param.get("value"):
                    spoken_text = str(param["value"])
                    break

        def _google_response(text: str, close: bool = True) -> dict:
            return {
                "session": {"id": session_id, "params": {}},
                "prompt": {
                    "override": False,
                    "firstSimple": {"speech": text, "text": text},
                },
                "scene": {
                    "name": scene or "main",
                    "slots": {},
                    "next": {"name": "actions.scene.END_CONVERSATION" if close else scene or "main"},
                },
            }

        if handler in ("actions.intent.MAIN", "WELCOME"):
            from ram.core.config import settings as _s
            return JSONResponse(_google_response(
                f"Hi, I'm {_s.squire_agent_name}. Tell me what you need.", close=False
            ))

        if not spoken_text:
            return JSONResponse(_google_response(
                "I didn't catch that. Can you say that again?", close=False
            ))

        try:
            from ram.core.agent import get_agent
            agent = get_agent()
            response = await agent.handle(spoken_text, user_id=f"google_{session_id[:20]}")
            voice_response = _truncate_for_voice(response, max_chars=400)
            return JSONResponse(_google_response(voice_response))
        except Exception as e:
            logger.error(f"Google Action agent error: {e}")
            return JSONResponse(_google_response("I'm having trouble right now. Please try again."))

    return router


def _truncate_for_voice(text: str, max_chars: int = 400) -> str:
    """Clean up text for voice output — remove markdown, truncate intelligently."""
    import re
    # Remove markdown formatting
    text = re.sub(r'\*+', '', text)
    text = re.sub(r'#+\s*', '', text)
    text = re.sub(r'`[^`]+`', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    text = re.sub(r'  +', ' ', text).strip()

    if len(text) <= max_chars:
        return text

    # Truncate at sentence boundary
    sentences = re.split(r'(?<=[.!?])\s+', text)
    result = ""
    for s in sentences:
        if len(result) + len(s) + 1 > max_chars:
            break
        result = (result + " " + s).strip()

    return result or text[:max_chars] + "…"
