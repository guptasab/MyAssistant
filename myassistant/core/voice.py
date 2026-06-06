"""Voice I/O — Speech-to-Text (STT) and Text-to-Speech (TTS).

Supports multiple providers with automatic fallback:

STT (transcription):
  1. Groq Whisper    — fastest, free tier, requires GROQ_API_KEY
  2. OpenAI Whisper  — high quality, requires OPENAI_API_KEY
  3. Local Whisper   — fully offline via HuggingFace transformers
                       (requires MYASSISTANT_LOCAL_WHISPER=true)

TTS (synthesis):
  1. ElevenLabs      — most natural, requires ELEVENLABS_API_KEY + ELEVENLABS_VOICE_ID
  2. OpenAI TTS      — natural, requires OPENAI_API_KEY
  3. pyttsx3         — offline, always available on Windows/Mac/Linux

Streaming TTS:
  Use ``synthesize_streaming()`` to receive audio chunks as they are generated.
  This powers the real-time voice conversation feature — MyAssistant starts speaking
  while it is still thinking, just like the Gemini app.

Usage example::

    text = transcribe(audio_bytes, mime="audio/webm")
    reply = await agent.handle("voice", text)
    path = synthesize(reply.text)
"""
from __future__ import annotations

import io
import time
from pathlib import Path
from typing import Generator, Iterator

from loguru import logger

from myassistant.core.config import settings


# ── STT (Speech → Text) ──────────────────────────────────────────────────

def transcribe(audio_bytes: bytes, mime: str = "audio/webm") -> str:
    """Transcribe audio bytes to text.

    Tries providers in order: Groq → OpenAI → local Whisper.
    Returns an empty string if all providers fail.

    Args:
        audio_bytes: Raw audio data (webm, mp3, wav, m4a, ogg accepted).
        mime:        MIME type of the audio, e.g. ``"audio/webm"``.

    Returns:
        Transcribed text, or ``""`` on failure.
    """
    # 1. Groq Whisper — fastest (real-time factor ~40x on large-v3-turbo)
    if settings.groq_api_key:
        result = _transcribe_groq(audio_bytes, mime)
        if result:
            return result

    # 2. OpenAI Whisper — benchmark quality
    if settings.openai_api_key:
        result = _transcribe_openai(audio_bytes, mime)
        if result:
            return result

    # 3. Local Whisper via HuggingFace transformers
    if getattr(settings, "myassistant_local_whisper", False):
        result = _transcribe_local(audio_bytes)
        if result:
            return result

    logger.warning(
        "transcribe: all STT providers unavailable. "
        "Set GROQ_API_KEY, OPENAI_API_KEY, or MYASSISTANT_LOCAL_WHISPER=true."
    )
    return ""


def _transcribe_groq(audio_bytes: bytes, mime: str) -> str:
    """Transcribe using Groq's ultra-fast Whisper API endpoint."""
    try:
        from groq import Groq
        client = Groq(api_key=settings.groq_api_key)
        # Groq expects a file-like with a name for MIME detection
        ext = _mime_to_ext(mime)
        result = client.audio.transcriptions.create(
            file=(f"audio{ext}", audio_bytes, mime),
            model="whisper-large-v3-turbo",
            response_format="text",
        )
        return (result or "").strip()
    except Exception as e:
        logger.debug(f"Groq STT failed: {e}")
        return ""


def _transcribe_openai(audio_bytes: bytes, mime: str) -> str:
    """Transcribe using OpenAI Whisper API."""
    try:
        import httpx
        ext = _mime_to_ext(mime)
        files = {"file": (f"clip{ext}", audio_bytes, mime)}
        data = {"model": "whisper-1", "response_format": "text"}
        headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
        r = httpx.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers=headers, files=files, data=data, timeout=60,
        )
        r.raise_for_status()
        # API returns plain text or JSON depending on response_format
        try:
            return r.json().get("text", "").strip()
        except Exception:
            return r.text.strip()
    except Exception as e:
        logger.debug(f"OpenAI STT failed: {e}")
        return ""


def _transcribe_local(audio_bytes: bytes) -> str:
    """Transcribe offline using openai-whisper or transformers Whisper.

    Requires one of:
      - ``pip install openai-whisper``
      - ``pip install transformers torch``  (auto-downloads ``openai/whisper-base``)
    """
    try:
        import whisper  # openai-whisper package
        import numpy as np, soundfile as sf
        audio_np, _ = sf.read(io.BytesIO(audio_bytes))
        model = whisper.load_model("base")
        result = model.transcribe(audio_np.astype(np.float32))
        return result.get("text", "").strip()
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"openai-whisper local STT failed: {e}")

    try:
        from transformers import pipeline
        pipe = pipeline("automatic-speech-recognition",
                        model="openai/whisper-base",
                        chunk_length_s=30)
        result = pipe(audio_bytes)
        return (result.get("text") or "").strip()
    except Exception as e:
        logger.debug(f"transformers local STT failed: {e}")
    return ""


def _mime_to_ext(mime: str) -> str:
    """Map audio MIME type to a file extension."""
    return {
        "audio/webm": ".webm",
        "audio/mp4":  ".m4a",
        "audio/ogg":  ".ogg",
        "audio/wav":  ".wav",
        "audio/mpeg": ".mp3",
        "audio/flac": ".flac",
    }.get(mime, ".webm")


# ── TTS (Text → Speech) ───────────────────────────────────────────────────

def synthesize(text: str, voice_id: str | None = None) -> Path | None:
    """Convert text to an audio file and return its path.

    Tries providers in order: ElevenLabs → OpenAI TTS → pyttsx3.
    Returns ``None`` only if every provider fails.

    Args:
        text:     Text to speak.
        voice_id: Override for ELEVENLABS_VOICE_ID (optional).

    Returns:
        Path to the generated audio file, or ``None``.
    """
    out_dir = settings.myassistant_data_dir / "audio"
    out_dir.mkdir(exist_ok=True, parents=True)
    ts = int(time.time() * 1000)

    vid = voice_id or settings.elevenlabs_voice_id

    # 1. ElevenLabs — most natural, supports many voices and cloning
    if settings.elevenlabs_api_key and vid:
        path = _tts_elevenlabs(text, vid, out_dir / f"tts_{ts}.mp3")
        if path:
            return path

    # 2. OpenAI TTS — good quality, very simple
    if settings.openai_api_key:
        path = _tts_openai(text, out_dir / f"tts_{ts}.mp3")
        if path:
            return path

    # 3. pyttsx3 — fully offline, always available on Windows/Mac/Linux
    return _tts_pyttsx3(text, out_dir / f"tts_{ts}.wav")


def _tts_elevenlabs(text: str, voice_id: str, out_path: Path) -> Path | None:
    """Call ElevenLabs TTS API and save the result."""
    try:
        import httpx
        r = httpx.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={"xi-api-key": settings.elevenlabs_api_key, "accept": "audio/mpeg"},
            json={
                "text": text[:5000],
                "model_id": "eleven_turbo_v2_5",       # lowest latency
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            },
            timeout=60,
        )
        r.raise_for_status()
        out_path.write_bytes(r.content)
        return out_path
    except Exception as e:
        logger.warning(f"ElevenLabs TTS failed: {e}")
        return None


def _tts_openai(text: str, out_path: Path) -> Path | None:
    """Call OpenAI TTS API (tts-1 model, alloy voice)."""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.openai_api_key)
        response = client.audio.speech.create(
            model="tts-1",   # tts-1-hd for higher quality
            voice="alloy",   # alloy | echo | fable | onyx | nova | shimmer
            input=text[:4096],
        )
        response.stream_to_file(str(out_path))
        return out_path
    except Exception as e:
        logger.warning(f"OpenAI TTS failed: {e}")
        return None


def _tts_pyttsx3(text: str, out_path: Path) -> Path | None:
    """Use pyttsx3 for fully offline TTS — always works on Windows."""
    try:
        import pyttsx3
        engine = pyttsx3.init()
        # Attempt to set a pleasant voice rate
        engine.setProperty("rate", 175)
        engine.save_to_file(text, str(out_path))
        engine.runAndWait()
        return out_path
    except Exception as e:
        logger.error(f"pyttsx3 TTS failed: {e}")
        return None


def synthesize_streaming(text: str) -> Iterator[bytes]:
    """Yield audio chunks as they arrive — enables real-time playback.

    Currently supported by ElevenLabs (chunked streaming).
    Falls back to returning the full synthesized file in one chunk.

    Yields:
        Raw audio bytes (MP3 chunks when using ElevenLabs, full file otherwise).
    """
    vid = settings.elevenlabs_voice_id
    if settings.elevenlabs_api_key and vid:
        try:
            import httpx
            with httpx.stream(
                "POST",
                f"https://api.elevenlabs.io/v1/text-to-speech/{vid}/stream",
                headers={"xi-api-key": settings.elevenlabs_api_key, "accept": "audio/mpeg"},
                json={"text": text[:5000], "model_id": "eleven_turbo_v2_5"},
                timeout=90,
            ) as r:
                r.raise_for_status()
                for chunk in r.iter_bytes(chunk_size=4096):
                    if chunk:
                        yield chunk
            return
        except Exception as e:
            logger.warning(f"ElevenLabs streaming TTS failed, falling back: {e}")

    # Fallback — synthesize whole file then yield it
    path = synthesize(text)
    if path and path.exists():
        yield path.read_bytes()

