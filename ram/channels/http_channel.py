"""HTTP + WebSocket channel — backs the mobile PWA and any other custom client.

Endpoints:
  POST /chat       {"text": "..."}        -> {"reply": "...", "audio_url": "..."}
  POST /voice      multipart audio file   -> {"transcript": "...", "reply": "...", "audio_url": "..."}
  WS   /stream     bidirectional          -> low-latency push-to-talk

All endpoints require Authorization: Bearer <RAM_HTTP_TOKEN>.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from loguru import logger
import uvicorn

from ram.channels.base import Channel
from ram.core.config import settings
from ram.core import voice


def _check_auth(authorization: str | None) -> None:
    if not settings.ram_http_token:
        return  # no token configured -> open (dev only)
    if not authorization or authorization != f"Bearer {settings.ram_http_token}":
        raise HTTPException(status_code=401, detail="unauthorized")


class HTTPChannel(Channel):
    name = "http"

    def __init__(self, handle):
        super().__init__(handle)
        self._ws_clients: set[WebSocket] = set()
        self._app = self._build_app()
        self._server: uvicorn.Server | None = None

    def _build_app(self) -> FastAPI:
        app = FastAPI(title=f"{settings.squire_agent_name} API")
        handle = self.handle
        clients = self._ws_clients

        @app.get("/api/name")
        async def agent_name():
            """Public endpoint — returns agent identity (no auth required).
            Used by the PWA and Canvas to dynamically set the wake word and UI text.
            """
            return {
                "name":    settings.squire_agent_name,
                "website": settings.squire_agent_website,
                "owner":   settings.ram_owner_name,
            }

        @app.post("/chat")
        async def chat(payload: dict, authorization: str | None = Header(None)):
            _check_auth(authorization)
            text = (payload.get("text") or "").strip()
            user = payload.get("user", "mobile")
            if not text:
                raise HTTPException(400, "empty text")
            reply = await handle(f"http:{user}", text)
            audio = voice.synthesize(reply.text) if payload.get("speak") else None
            return {"reply": reply.text, "actions": reply.actions_taken,
                    "audio_url": f"/audio/{audio.name}" if audio else None}

        @app.post("/voice")
        async def voice_in(
            file: UploadFile = File(...),
            user: str = "mobile",
            authorization: str | None = Header(None),
        ):
            _check_auth(authorization)
            data = await file.read()
            transcript = voice.transcribe(data, file.content_type or "audio/webm")
            if not transcript:
                return JSONResponse({"error": "could not transcribe"}, status_code=422)
            reply = await handle(f"http:{user}", transcript)
            audio = voice.synthesize(reply.text)
            return {
                "transcript": transcript,
                "reply": reply.text,
                "audio_url": f"/audio/{audio.name}" if audio else None,
            }

        @app.get("/audio/{name}")
        async def audio_file(name: str):
            p = settings.ram_data_dir / "audio" / name
            if not p.exists():
                raise HTTPException(404)
            return FileResponse(p)

        @app.post("/location/update")
        async def location_update(payload: dict, authorization: str | None = Header(None)):
            """Receive GPS coordinates from the mobile PWA."""
            _check_auth(authorization)
            try:
                from ram.skills.location_skill import update_location
                update_location(payload.get("lat", 0.0), payload.get("lon", 0.0))
                return {"ok": True}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        @app.websocket("/stream")
        async def stream(ws: WebSocket):
            # Simple token-in-querystring auth for WS
            token = ws.query_params.get("token")
            if settings.ram_http_token and token != settings.ram_http_token:
                await ws.close(code=4401)
                return
            await ws.accept()
            clients.add(ws)
            try:
                while True:
                    data = await ws.receive_json()
                    text = data.get("text", "")
                    if not text:
                        continue
                    reply = await handle(f"ws:{data.get('user', 'mobile')}", text)
                    await ws.send_json({"reply": reply.text, "actions": reply.actions_taken})
            except WebSocketDisconnect:
                pass
            finally:
                clients.discard(ws)

        # Serve the PWA from /app
        pwa_dir = Path(__file__).resolve().parent.parent.parent / "mobile" / "pwa"
        if pwa_dir.exists():
            app.mount("/app", StaticFiles(directory=str(pwa_dir), html=True), name="pwa")

        # Mount built-in mobile PWA
        mobile_pwa_dir = Path(__file__).resolve().parent / "mobile_pwa"
        if mobile_pwa_dir.exists():
            app.mount("/pwa", StaticFiles(directory=str(mobile_pwa_dir), html=True), name="mobile_pwa")

        # Mount admin + iOS Shortcuts routers
        try:
            from ram.channels.admin_ui import build_admin_router, build_shortcuts_router
            app.include_router(build_admin_router())
            app.include_router(build_shortcuts_router(handle))
        except Exception as e:
            logger.warning(f"admin/shortcuts not mounted: {e}")

        # Mount real-time voice router
        try:
            from ram.channels.voice_channel import build_voice_router
            app.include_router(build_voice_router(handle))
        except Exception as e:
            logger.warning(f"voice router not mounted: {e}")

        # Mount Alexa + Google Home routers
        try:
            from ram.skills.voice_assistants import build_voice_assistants_router
            app.include_router(build_voice_assistants_router())
        except Exception as e:
            logger.warning(f"voice assistants router not mounted: {e}")

        # Mount MCP HTTP endpoint
        try:
            from ram.core.mcp_server import build_mcp_fastapi_router
            app.include_router(build_mcp_fastapi_router())
        except Exception as e:
            logger.warning(f"MCP router not mounted: {e}")

        # ── Live Canvas ──────────────────────────────────────────────────────
        _canvas_html = (Path(__file__).parent / "canvas.html").read_text(encoding="utf-8")

        @app.get("/canvas")
        async def canvas_page():
            """Serve the Live Canvas visual workspace."""
            return Response(content=_canvas_html, media_type="text/html")

        @app.websocket("/canvas/ws")
        async def canvas_ws(ws: WebSocket):
            """
            WebSocket endpoint for the Live Canvas browser client.

            On connect: sends all current blocks as an 'init' event.
            Receives: {'action': 'remove', 'id': '…'} or {'action': 'clear'}
            Sends:    block / remove / clear events as they happen.
            """
            await ws.accept()
            from ram.core import canvas_state as cv
            import json

            # Subscribe to future events
            q = cv.subscribe()

            # Send current state
            try:
                await ws.send_json({"event": "init", "blocks": cv.all_blocks()})
            except Exception:
                cv.unsubscribe(q)
                return

            # Two coroutines in parallel: push outbound events, receive inbound actions
            async def _outbound():
                while True:
                    try:
                        msg = await asyncio.wait_for(q.get(), timeout=30)
                        await ws.send_json(msg)
                    except asyncio.TimeoutError:
                        # Keepalive ping
                        try:
                            await ws.send_json({"event": "ping"})
                        except Exception:
                            break
                    except Exception:
                        break

            async def _inbound():
                while True:
                    try:
                        data = await ws.receive_json()
                        action = data.get("action")
                        if action == "remove":
                            cv.remove(data.get("id", ""))
                        elif action == "clear":
                            cv.clear(keep_pinned=data.get("keep_pinned", True))
                    except Exception:
                        break

            try:
                await asyncio.gather(_outbound(), _inbound(), return_exceptions=True)
            finally:
                cv.unsubscribe(q)

        @app.post("/twilio/whatsapp")
        async def twilio_whatsapp(request: Request):
            form = await request.form()
            from_num = form.get("From", "")
            body = (form.get("Body") or "").strip()
            reply = await handle(f"whatsapp:{from_num}", body)
            # Escape minimal XML special chars
            safe = reply.text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            twiml = (f'<?xml version="1.0" encoding="UTF-8"?>'
                     f'<Response><Message>{safe}</Message></Response>')
            return Response(content=twiml, media_type="application/xml")

        @app.post("/twilio/sms")
        async def twilio_sms(request: Request):
            """Inbound SMS webhook — Ollie's signature 'just a text' surface.

            If the sender's phone matches a known family member, we tag the
            user_id with their name so per-member context is preserved.
            """
            form = await request.form()
            from_num = (form.get("From") or "").strip()
            body = (form.get("Body") or "").strip()
            tag = from_num
            try:
                from ram.core.family import find_member_by_phone
                m = find_member_by_phone(from_num)
                if m:
                    tag = f"{from_num}|{m.name}"
            except Exception:
                pass
            reply = await handle(f"sms:{tag}", body)
            safe = reply.text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            twiml = (f'<?xml version="1.0" encoding="UTF-8"?>'
                     f'<Response><Message>{safe}</Message></Response>')
            return Response(content=twiml, media_type="application/xml")

        @app.get("/")
        async def root():
            return {"name": "Ollie", "channels": "see /docs"}

        return app

    async def start(self) -> None:
        cfg = uvicorn.Config(
            self._app, host=settings.ram_http_host, port=settings.ram_http_port,
            log_level="info", lifespan="on",
        )
        self._server = uvicorn.Server(cfg)
        asyncio.create_task(self._server.serve())
        logger.info(f"HTTP channel on http://{settings.ram_http_host}:{settings.ram_http_port}")

    async def send(self, user_id: str, text: str) -> None:
        for ws in list(self._ws_clients):
            try:
                await ws.send_json({"push": text})
            except Exception:
                self._ws_clients.discard(ws)
