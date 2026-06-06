"""Live Canvas state manager.

The canvas is a real-time visual workspace where the agent can push rich
content blocks (markdown, tables, code, charts, metric cards, checklists,
maps) that appear instantly on the user's screen.

Architecture
────────────
  Agent / skill  ──▶  canvas_push(block)  ──▶  CanvasState
                                                      │
                                               broadcast via WS
                                                      │
                                             /canvas  browser tab

Each block is an immutable dict:
  {
    "id":       str   — unique, deterministic (type+timestamp)
    "type":     str   — see BLOCK_TYPES
    "title":    str   — optional header line
    "content":  any   — type-specific payload (see below)
    "pinned":   bool  — pinned blocks survive canvas_clear()
    "ts":       float — unix timestamp
  }

Block content by type
─────────────────────
  markdown   {"text": "…markdown string…"}
  code       {"language": "python", "code": "…"}
  table      {"headers": ["Col1","Col2"], "rows": [["a","b"], …]}
  metric     {"value": "42", "label": "Open tasks", "delta": "+3", "good": true}
  checklist  {"items": [{"text": "…", "done": bool}, …]}
  image      {"url": "https://…", "alt": "…"}
  map        {"lat": 37.77, "lon": -122.41, "zoom": 13, "label": "SF"}
  progress   {"label": "…", "value": 0.6}   # 0..1 fraction
  chart      {"kind": "bar"|"line", "labels": […], "data": […]}
  error      {"text": "…", "detail": "…"}   # shown in red
"""
from __future__ import annotations

import asyncio
import threading
import time
import uuid
from typing import Any

# ── Valid block types ─────────────────────────────────────────────────────────

BLOCK_TYPES = {
    "markdown", "code", "table", "metric", "checklist",
    "image", "map", "progress", "chart", "error", "html",
}

# ── Shared state (module-level singleton) ─────────────────────────────────────

_lock   = threading.Lock()
_blocks: list[dict] = []
_listeners: set[asyncio.Queue] = set()   # one queue per open /canvas WebSocket


# ── Public API ────────────────────────────────────────────────────────────────

def push(
    block_type: str,
    content: Any,
    title: str = "",
    pinned: bool = False,
    block_id: str | None = None,
) -> dict:
    """
    Add a new block to the canvas and broadcast it to all connected browsers.

    Parameters
    ----------
    block_type:
        One of BLOCK_TYPES.
    content:
        Type-specific payload dict (see module docstring).
    title:
        Optional header rendered above the block.
    pinned:
        If True the block survives ``clear()``.
    block_id:
        Provide a stable ID to *replace* an existing block (upsert behaviour).
        Useful for progress updates.

    Returns
    -------
    The block dict that was pushed.
    """
    if block_type not in BLOCK_TYPES:
        raise ValueError(f"Unknown canvas block type: {block_type!r}. "
                         f"Choose from: {sorted(BLOCK_TYPES)}")

    block = {
        "id":      block_id or f"{block_type}_{uuid.uuid4().hex[:8]}",
        "type":    block_type,
        "title":   title,
        "content": content,
        "pinned":  pinned,
        "ts":      time.time(),
    }

    with _lock:
        # Upsert: replace existing block with same id
        existing = next((i for i, b in enumerate(_blocks) if b["id"] == block["id"]), None)
        if existing is not None:
            _blocks[existing] = block
        else:
            _blocks.append(block)

    _broadcast({"event": "block", "block": block})
    return block


def update_progress(block_id: str, value: float, label: str = "") -> None:
    """Shorthand to update a progress block in-place."""
    existing = get_block(block_id)
    if existing:
        content = {**existing.get("content", {}), "value": value}
        if label:
            content["label"] = label
        push("progress", content, title=existing.get("title", ""),
             pinned=existing.get("pinned", False), block_id=block_id)
    else:
        push("progress", {"label": label, "value": value}, block_id=block_id)


def clear(keep_pinned: bool = True) -> None:
    """
    Clear all canvas blocks.

    Parameters
    ----------
    keep_pinned:
        If True (default), blocks marked ``pinned=True`` are preserved.
    """
    with _lock:
        if keep_pinned:
            remaining = [b for b in _blocks if b.get("pinned")]
            _blocks.clear()
            _blocks.extend(remaining)
        else:
            _blocks.clear()

    _broadcast({"event": "clear", "keep_pinned": keep_pinned})


def all_blocks() -> list[dict]:
    """Return a snapshot of all current canvas blocks."""
    with _lock:
        return list(_blocks)


def get_block(block_id: str) -> dict | None:
    """Return a single block by id, or None."""
    with _lock:
        return next((b for b in _blocks if b["id"] == block_id), None)


def remove(block_id: str) -> bool:
    """Remove a block by id. Returns True if found and removed."""
    with _lock:
        before = len(_blocks)
        _blocks[:] = [b for b in _blocks if b["id"] != block_id]
        removed = len(_blocks) < before

    if removed:
        _broadcast({"event": "remove", "id": block_id})
    return removed


# ── WebSocket listener registry ───────────────────────────────────────────────

def subscribe() -> asyncio.Queue:
    """
    Register a new WebSocket listener.

    Returns a ``Queue`` that will receive broadcast dicts.
    The caller must call :func:`unsubscribe` when the WebSocket closes.
    """
    q: asyncio.Queue = asyncio.Queue()
    with _lock:
        _listeners.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    """Deregister a WebSocket listener."""
    with _lock:
        _listeners.discard(q)


def _broadcast(msg: dict) -> None:
    """Put *msg* on every active listener queue (non-blocking)."""
    with _lock:
        dead: list[asyncio.Queue] = []
        for q in _listeners:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            _listeners.discard(q)
