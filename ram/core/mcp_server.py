"""MCP (Model Context Protocol) Server — expose Squire skills as an MCP server.

This module lets Squire act as an MCP server, making all its 200+ skills
available to any MCP-compatible client: Claude Code, Cursor, Codex, Windsurf,
or any IDE with an MCP plugin.

Protocol: JSON-RPC 2.0 over stdio (primary) or HTTP SSE (secondary).
MCP spec: https://spec.modelcontextprotocol.io/

Once started, Claude Code can connect with:
  // .claude/settings.json
  {
    "mcpServers": {
      "squire": { "command": "python", "args": ["-m", "squire", "mcp"] }
    }
  }

Supported MCP methods:
  initialize            — handshake with client capabilities
  tools/list            — list all Squire skills as MCP tools
  tools/call            — execute a Squire skill and return result
  resources/list        — expose memory/notes/contacts as MCP resources
  resources/read        — read a specific resource
  prompts/list          — list suggested prompts
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from loguru import logger

from ram.core.registry import discover, all_skills, get_skill


_MCP_VERSION = "2024-11-05"
_SERVER_INFO = {
    "name": "squire",
    "version": "1.0.0",
    "description": "Squire — your personal life-OS assistant (mysquire.ai)",
}


def _skill_to_mcp_tool(skill: dict) -> dict:
    """Convert a Squire skill definition to MCP tool schema."""
    # Build input schema from skill parameters
    params = skill.get("parameters") or {}
    props: dict[str, Any] = {}
    required: list[str] = []

    if isinstance(params, dict):
        for name, spec in params.items():
            if isinstance(spec, dict):
                prop = {"type": spec.get("type", "string")}
                if "description" in spec:
                    prop["description"] = spec["description"]
                if "default" not in spec:
                    required.append(name)
                props[name] = prop

    return {
        "name": skill["name"],
        "description": skill.get("description", ""),
        "inputSchema": {
            "type": "object",
            "properties": props,
            "required": required,
        },
    }


def _handle_initialize(params: dict) -> dict:
    return {
        "protocolVersion": _MCP_VERSION,
        "capabilities": {
            "tools": {"listChanged": False},
            "resources": {"listChanged": False},
            "prompts": {"listChanged": False},
        },
        "serverInfo": _SERVER_INFO,
    }


def _handle_tools_list(_params: dict) -> dict:
    discover()
    tools = [_skill_to_mcp_tool(s) for s in all_skills()]
    return {"tools": tools}


def _handle_tools_call(params: dict) -> dict:
    name = params.get("name", "")
    args = params.get("arguments", {})

    fn = get_skill(name)
    if fn is None:
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"Unknown skill: {name}"}],
        }

    try:
        result = fn(**args)
        return {
            "content": [{"type": "text", "text": str(result)}],
        }
    except Exception as e:
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"Skill error: {e}"}],
        }


def _handle_resources_list(_params: dict) -> dict:
    """Expose key Squire data stores as MCP resources."""
    resources = [
        {
            "uri": "squire://memory/facts",
            "name": "Long-term memory facts",
            "description": "Persistent facts Ram has learned about you",
            "mimeType": "application/json",
        },
        {
            "uri": "squire://contacts/list",
            "name": "Contacts",
            "description": "Your saved contacts",
            "mimeType": "application/json",
        },
        {
            "uri": "squire://tasks/active",
            "name": "Active tasks",
            "description": "Your current open tasks",
            "mimeType": "application/json",
        },
    ]
    return {"resources": resources}


def _handle_resources_read(params: dict) -> dict:
    uri = params.get("uri", "")

    if uri == "squire://memory/facts":
        try:
            from ram.core.memory import all_facts
            facts = all_facts()
            content = json.dumps(facts, indent=2)
        except Exception as e:
            content = f"Error: {e}"
        return {"contents": [{"uri": uri, "mimeType": "application/json", "text": content}]}

    if uri == "squire://contacts/list":
        try:
            from ram.core import contexts as ctx
            from ram.core.memory import db
            with db() as s:
                contacts = s.query(ctx.Contact).all()
                data = [{"name": c.name, "email": c.email, "phone": c.phone} for c in contacts]
            content = json.dumps(data, indent=2)
        except Exception as e:
            content = f"Error: {e}"
        return {"contents": [{"uri": uri, "mimeType": "application/json", "text": content}]}

    if uri == "squire://tasks/active":
        try:
            from ram.core import contexts as ctx
            from ram.core.memory import db
            with db() as s:
                tasks = s.query(ctx.Task).filter(ctx.Task.status.in_(["todo","doing"])).all()
                data = [{"title": t.title, "due": t.due, "priority": t.priority} for t in tasks]
            content = json.dumps(data, indent=2)
        except Exception as e:
            content = f"Error: {e}"
        return {"contents": [{"uri": uri, "mimeType": "application/json", "text": content}]}

    return {"contents": [{"uri": uri, "mimeType": "text/plain", "text": "Resource not found"}]}


def _handle_prompts_list(_params: dict) -> dict:
    return {
        "prompts": [
            {"name": "morning_briefing", "description": "Get a morning briefing"},
            {"name": "check_email",      "description": "Check and triage all email"},
            {"name": "debug_prod",       "description": "Debug last production call"},
            {"name": "weekly_review",    "description": "Generate weekly review"},
        ]
    }


_HANDLERS = {
    "initialize":       _handle_initialize,
    "tools/list":       _handle_tools_list,
    "tools/call":       _handle_tools_call,
    "resources/list":   _handle_resources_list,
    "resources/read":   _handle_resources_read,
    "prompts/list":     _handle_prompts_list,
}


def _dispatch(request: dict) -> dict | None:
    """Dispatch one JSON-RPC request and return the response (or None for notifications)."""
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params") or {}

    # Notifications (no id) — acknowledge but no response
    if req_id is None:
        return None

    handler = _HANDLERS.get(method)
    if handler is None:
        return {
            "jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    try:
        result = handler(params)
        return {"jsonrpc": "2.0", "id": req_id, "result": result}
    except Exception as e:
        logger.exception(f"MCP handler error for {method}: {e}")
        return {
            "jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32603, "message": str(e)},
        }


def run_stdio_server() -> None:
    """Run the MCP server over stdio (one JSON object per line).

    This is the standard MCP transport for CLI tools.
    Claude Code connects with: ``python -m squire mcp``
    """
    discover()
    logger.remove()  # Don't pollute stdio with log output
    logger.add(sys.stderr, level="WARNING")

    logger.info("Squire MCP server started (stdio)")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as e:
            response = {"jsonrpc": "2.0", "id": None,
                        "error": {"code": -32700, "message": f"Parse error: {e}"}}
            print(json.dumps(response), flush=True)
            continue

        response = _dispatch(request)
        if response is not None:
            print(json.dumps(response), flush=True)


def build_mcp_fastapi_router():
    """Build a FastAPI router for HTTP+SSE MCP transport.

    Mount at /mcp in the main HTTP channel for remote MCP access.
    """
    from fastapi import APIRouter, Request
    from fastapi.responses import StreamingResponse, JSONResponse

    router = APIRouter(prefix="/mcp", tags=["mcp"])

    @router.post("/")
    async def mcp_endpoint(request: Request):
        body = await request.json()
        if isinstance(body, list):
            responses = [r for r in (_dispatch(req) for req in body) if r is not None]
            return JSONResponse(responses)
        response = _dispatch(body)
        if response is None:
            return JSONResponse({})
        return JSONResponse(response)

    @router.get("/tools")
    async def list_tools():
        """Quick endpoint to see all available tools."""
        return _handle_tools_list({})

    return router
