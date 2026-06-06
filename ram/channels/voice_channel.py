"""Real-time voice conversation channel — the "Gemini app" experience for Ram.

Provides two interfaces:

1. **WebSocket** ``/voice/realtime``
   JSON protocol::

     Client  → {"type": "audio",   "data": "<base64 audio>", "mime": "audio/webm"}
     Client  → {"type": "text",    "text": "..."}           # typed fallback
     Client  → {"type": "control", "action": "interrupt"}   # stop current response
     Server  → {"type": "transcript",  "text": "..."}       # what Ram heard
     Server  → {"type": "thinking",    "text": "..."}       # status while working
     Server  → {"type": "text_chunk",  "text": "..."}       # streaming reply token
     Server  → {"type": "audio_chunk", "data": "<base64>"}  # streaming TTS audio
     Server  → {"type": "done",        "text": "..."}       # full reply finished
     Server  → {"type": "confirm",     "text": "..."}       # confirmation gate triggered

2. **REST** ``POST /voice/transcribe``
   Upload audio, get transcript back (useful for testing).

The session manager runs the agent in a background asyncio task so it can
stream partial text tokens to TTS while simultaneously continuing to reason —
matching the Gemini-app UX where Ram starts speaking before it finishes thinking.

Architecture::

    browser/tray → WebSocket → VoiceSession
                                    ├── STT     (Groq / OpenAI / local)
                                    ├── Agent   (ram.core.agent)
                                    ├── TTS     (streaming ElevenLabs / OpenAI / pyttsx3)
                                    └── WS push

Usage — start alongside the HTTP channel (wired automatically by http_channel.py)::

    from ram.channels.voice_channel import build_voice_router
    app.include_router(build_voice_router(agent_handle))
"""
from __future__ import annotations

import asyncio
import base64
import json
from typing import Callable, Awaitable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, UploadFile, File, Header, HTTPException
from loguru import logger

from ram.core import voice
from ram.core.config import settings


# ── Sentence splitter for streaming TTS ──────────────────────────────────

def _split_sentences(text: str) -> list[str]:
    """Split text into sentences suitable for incremental TTS.

    We want chunks large enough to sound natural but small enough
    to start playing quickly (~1 sentence at a time).
    """
    import re
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    return [p.strip() for p in parts if p.strip()]


# ── Voice session ─────────────────────────────────────────────────────────

class VoiceSession:
    """Manages one WebSocket voice conversation with a user.

    Each connection gets its own session.  The session is stateless beyond
    what the RAM memory layer stores — reconnecting picks up where you left off.

    Protocol overview::

        1. Client sends audio chunk (base64-encoded) or text.
        2. Session transcribes audio via :mod:`ram.core.voice`.
        3. Session forwards transcript to the agent.
        4. As the agent produces text tokens, short sentences are sent to TTS.
        5. Audio chunks are base64-encoded and pushed back to the client.
        6. A "done" message signals end of turn.
    """

    def __init__(self, ws: WebSocket, agent_handle: Callable, user_id: str) -> None:
        self.ws = ws
        self.agent_handle = agent_handle
        self.user_id = user_id
        self._interrupted = False

    async def _send(self, payload: dict) -> None:
        """Send a JSON frame to the browser, ignoring closed-connection errors."""
        try:
            await self.ws.send_text(json.dumps(payload))
        except Exception:
            pass

    async def _handle_input(self, msg: dict) -> None:
        """Process one incoming message from the client."""
        mtype = msg.get("type", "text")

        # ── interrupt: stop current response ──────────────────────────────
        if mtype == "control" and msg.get("action") == "interrupt":
            self._interrupted = True
            return

        # ── audio input ───────────────────────────────────────────────────
        if mtype == "audio":
            raw_b64 = msg.get("data", "")
            if not raw_b64:
                return
            audio_bytes = base64.b64decode(raw_b64)
            mime = msg.get("mime", "audio/webm")

            await self._send({"type": "thinking", "text": "Listening…"})
            transcript = await asyncio.to_thread(voice.transcribe, audio_bytes, mime)
            if not transcript:
                await self._send({"type": "thinking", "text": "(could not transcribe audio)"})
                return
            await self._send({"type": "transcript", "text": transcript})
            await self._run_agent(transcript)
            return

        # ── plain text input (typed or from tray) ─────────────────────────
        if mtype == "text":
            text = (msg.get("text") or "").strip()
            if text:
                await self._run_agent(text)

    async def _run_agent(self, text: str) -> None:
        """Send user text to the agent and stream the reply back as text + audio."""
        self._interrupted = False
        await self._send({"type": "thinking", "text": "Thinking…"})

        try:
            reply = await self.agent_handle(self.user_id, text)
        except Exception as e:
            await self._send({"type": "done", "text": f"Error: {e}"})
            return

        full_text = reply.text

        # If a confirmation gate was triggered, highlight it
        if reply.pending_confirmation:
            await self._send({"type": "confirm", "text": full_text})
            await self._tts_chunk(full_text)
            return

        await self._send({"type": "done", "text": full_text})

        # Stream TTS sentence by sentence so the user hears Ram start speaking fast
        if not self._interrupted:
            await self._stream_tts(full_text)

    async def _stream_tts(self, text: str) -> None:
        """Convert text to speech sentence-by-sentence and push audio chunks."""
        sentences = _split_sentences(text)
        if not sentences:
            return

        for sentence in sentences:
            if self._interrupted:
                break
            await self._tts_chunk(sentence)

    async def _tts_chunk(self, text: str) -> None:
        """Synthesize one sentence and push it as a base64 audio_chunk frame."""
        try:
            # Run potentially-blocking TTS in a thread
            path = await asyncio.to_thread(voice.synthesize, text)
            if path and path.exists():
                audio_b64 = base64.b64encode(path.read_bytes()).decode()
                await self._send({
                    "type": "audio_chunk",
                    "data": audio_b64,
                    "text": text,
                    "format": path.suffix.lstrip("."),  # "mp3" or "wav"
                })
        except Exception as e:
            logger.debug(f"TTS chunk failed: {e}")

    async def run(self) -> None:
        """Main receive loop — runs until the WebSocket disconnects."""
        try:
            while True:
                raw = await self.ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    msg = {"type": "text", "text": raw}
                # Dispatch without blocking the receive loop
                asyncio.create_task(self._handle_input(msg))
        except WebSocketDisconnect:
            logger.info(f"Voice session {self.user_id} disconnected")
        except Exception as e:
            logger.warning(f"Voice session error: {e}")


# ── Router factory ────────────────────────────────────────────────────────

def build_voice_router(agent_handle: Callable) -> APIRouter:
    """Return a FastAPI router with the voice endpoints.

    Mount onto the main FastAPI app::

        app.include_router(build_voice_router(agent.handle))
    """
    router = APIRouter()

    @router.websocket("/voice/realtime")
    async def voice_realtime(ws: WebSocket):
        """WebSocket endpoint for real-time voice conversation.

        Query params:
            token   — Bearer token (matches RAM_HTTP_TOKEN if set)
            user    — optional user identifier (default: "voice")
        """
        token = ws.query_params.get("token", "")
        if settings.ram_http_token and token != settings.ram_http_token:
            await ws.close(code=4401)
            return

        await ws.accept()
        user_id = f"voice:{ws.query_params.get('user', 'default')}"
        session = VoiceSession(ws, agent_handle, user_id)

        # Greet with a short spoken welcome
        await session._send({"type": "thinking", "text": "Connected to Ram"})
        asyncio.create_task(
            session._tts_chunk("Hi, I'm Ram. What can I do for you?")
        )

        await session.run()

    @router.post("/voice/transcribe")
    async def transcribe_upload(
        file: UploadFile = File(...),
        authorization: str | None = Header(None),
    ):
        """Upload an audio file and get back the transcript.

        Useful for testing STT independently of the full agent.
        """
        if settings.ram_http_token and authorization != f"Bearer {settings.ram_http_token}":
            raise HTTPException(401, "unauthorized")
        data = await file.read()
        transcript = await asyncio.to_thread(
            voice.transcribe, data, file.content_type or "audio/webm"
        )
        return {"transcript": transcript}

    @router.get("/voice/tts")
    async def tts_preview(
        text: str,
        authorization: str | None = Header(None),
    ):
        """Synthesize text and return the audio file URL.

        Useful for testing TTS from the admin UI.
        """
        if settings.ram_http_token and authorization != f"Bearer {settings.ram_http_token}":
            raise HTTPException(401, "unauthorized")
        path = await asyncio.to_thread(voice.synthesize, text)
        if path:
            return {"audio_url": f"/audio/{path.name}"}
        return {"error": "TTS unavailable — configure ElevenLabs, OpenAI, or pyttsx3"}

    return router
