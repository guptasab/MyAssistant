"""MCP Client — consume external MCP servers as Squire tool providers.

Squire can connect to ANY MCP server and make its tools available as Squire
skills. This gives Squire access to the entire MCP ecosystem:
  - Filesystem access
  - Browser automation (Playwright MCP)
  - Database tools
  - Any custom MCP server

Configuration (in .env or Settings UI):
  MCP_SERVERS=stdio:///path/to/server,http://localhost:3001

Usage::

    from myassistant.core.mcp_client import load_mcp_servers
    load_mcp_servers()   # called once at startup — registers tools as skills
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
from typing import Any
from urllib.parse import urlparse

from loguru import logger


class MCPStdioClient:
    """Connect to an MCP server running as a child process over stdio.

    The child process receives JSON-RPC requests on stdin and sends
    responses on stdout — same as how Claude Code connects to MCP servers.

    Args:
        command: List of command + args to start the server process.
    """

    def __init__(self, command: list[str]):
        self.command = command
        self._proc: subprocess.Popen | None = None
        self._req_id = 0
        self._lock = threading.Lock()
        self.tools: list[dict] = []

    def start(self) -> bool:
        """Start the child process. Returns True on success."""
        try:
            self._proc = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
            # Handshake
            resp = self._call("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "squire", "version": "1.0.0"},
            })
            if resp and "result" in resp:
                logger.info(f"MCP server connected: {' '.join(self.command[:2])}")
                return True
        except Exception as e:
            logger.warning(f"MCP server start failed ({self.command[0]}): {e}")
        return False

    def _call(self, method: str, params: dict) -> dict | None:
        """Send a JSON-RPC request and wait for the response."""
        if not self._proc or self._proc.poll() is not None:
            return None
        with self._lock:
            self._req_id += 1
            req = {"jsonrpc": "2.0", "id": self._req_id, "method": method, "params": params}
            try:
                line = json.dumps(req) + "\n"
                self._proc.stdin.write(line)  # type: ignore
                self._proc.stdin.flush()      # type: ignore
                response_line = self._proc.stdout.readline()  # type: ignore
                if response_line:
                    return json.loads(response_line.strip())
            except Exception as e:
                logger.debug(f"MCP call {method} error: {e}")
        return None

    def list_tools(self) -> list[dict]:
        """Fetch the list of tools from the MCP server."""
        resp = self._call("tools/list", {})
        if resp and "result" in resp:
            self.tools = resp["result"].get("tools", [])
        return self.tools

    def call_tool(self, name: str, arguments: dict) -> str:
        """Call a tool on the MCP server and return the text result."""
        resp = self._call("tools/call", {"name": name, "arguments": arguments})
        if resp and "result" in resp:
            content = resp["result"].get("content", [])
            return "\n".join(
                c.get("text", "") for c in content if c.get("type") == "text"
            )
        if resp and "error" in resp:
            return f"MCP error: {resp['error'].get('message', 'unknown')}"
        return "(no response from MCP server)"

    def stop(self) -> None:
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                pass


class MCPHttpClient:
    """Connect to an MCP server over HTTP (SSE or simple POST).

    Args:
        base_url: Base URL of the MCP server, e.g. http://localhost:3001
    """

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.tools: list[dict] = []
        self._req_id = 0

    def _call(self, method: str, params: dict) -> dict | None:
        try:
            import httpx
            self._req_id += 1
            req = {"jsonrpc": "2.0", "id": self._req_id, "method": method, "params": params}
            r = httpx.post(f"{self.base_url}/mcp", json=req, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.debug(f"MCP HTTP call {method}: {e}")
        return None

    def start(self) -> bool:
        resp = self._call("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "squire", "version": "1.0.0"},
        })
        if resp and "result" in resp:
            logger.info(f"MCP HTTP server connected: {self.base_url}")
            return True
        return False

    def list_tools(self) -> list[dict]:
        resp = self._call("tools/list", {})
        if resp and "result" in resp:
            self.tools = resp["result"].get("tools", [])
        return self.tools

    def call_tool(self, name: str, arguments: dict) -> str:
        resp = self._call("tools/call", {"name": name, "arguments": arguments})
        if resp and "result" in resp:
            content = resp["result"].get("content", [])
            return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")
        return "(no response)"

    def stop(self) -> None:
        pass


# Global registry of active MCP clients
_active_clients: list[MCPStdioClient | MCPHttpClient] = []


def load_mcp_servers() -> int:
    """Connect to all configured MCP servers and register their tools as Squire skills.

    Reads from ``settings.mcp_servers`` — a comma-separated list of URIs:
      ``stdio:///usr/local/bin/mcp-server``       — local process
      ``stdio://python -m my_mcp_server``          — python module
      ``http://localhost:3001``                     — HTTP server

    Returns:
        Number of tools registered from all connected MCP servers.
    """
    from myassistant.core.config import settings
    from myassistant.core.registry import skill as skill_decorator, _registry

    mcp_spec = getattr(settings, "mcp_servers", "")
    if not mcp_spec:
        return 0

    total_tools = 0
    for uri in mcp_spec.split(","):
        uri = uri.strip()
        if not uri:
            continue

        client: MCPStdioClient | MCPHttpClient | None = None

        if uri.startswith("stdio://"):
            # Parse: stdio:///path/to/binary or stdio://command arg1 arg2
            path = uri[8:]
            if path.startswith("/"):
                cmd = [path]
            else:
                cmd = path.split()
            client = MCPStdioClient(cmd)
        elif uri.startswith("http://") or uri.startswith("https://"):
            client = MCPHttpClient(uri)
        else:
            logger.warning(f"Unknown MCP server URI format: {uri}")
            continue

        if not client.start():
            continue

        tools = client.list_tools()
        _active_clients.append(client)

        # Register each MCP tool as a Squire skill
        for tool in tools:
            _register_mcp_tool(tool, client)
            total_tools += 1

        logger.info(f"MCP server {uri}: {len(tools)} tools registered")

    return total_tools


def _register_mcp_tool(tool: dict, client: Any) -> None:
    """Dynamically create a Squire skill wrapper for an MCP tool."""
    from myassistant.core.registry import _registry

    name = tool.get("name", "")
    description = tool.get("description", f"MCP tool: {name}")
    input_schema = tool.get("inputSchema", {})

    if not name or name in _registry:
        return

    # Create a closure that calls the MCP server
    def _mcp_skill_fn(**kwargs: Any) -> str:
        return client.call_tool(name, kwargs)

    _mcp_skill_fn.__name__ = name
    _mcp_skill_fn.__doc__ = description

    # Register with the skill registry
    _registry[name] = {
        "name": name,
        "description": f"[MCP] {description}",
        "fn": _mcp_skill_fn,
        "sensitive": False,
        "requires": [],
        "parameters": input_schema.get("properties", {}),
        "module": f"mcp_client.{client.__class__.__name__}",
    }


def stop_all() -> None:
    """Disconnect from all MCP servers."""
    for client in _active_clients:
        try:
            client.stop()
        except Exception:
            pass
    _active_clients.clear()
