"""Live Canvas skills — let the agent push rich content to the visual workspace.

The canvas is a browser tab at ``/canvas`` that displays agent-rendered blocks
in real time.  Any skill (or the agent itself) can call these functions to
push content without waiting for the user to ask.

Typical flow
────────────
  User: "Debug the last prod call"
  Agent: canvas_clear()
         canvas_metric("Searching CloudWatch…", "⏳")
         # … finds logs …
         canvas_code(trace, language="python", title="Stack Trace")
         canvas_table(errors, title="Error Summary")
         canvas_markdown("## Root Cause\n…", title="Analysis")
"""
from __future__ import annotations

from ram.core.registry import skill
from ram.core import canvas_state as _cv


# ── Primitive push helpers (not agent skills, used internally) ─────────────

def _push_markdown(text: str, title: str = "", pinned: bool = False,
                   block_id: str | None = None) -> str:
    b = _cv.push("markdown", {"text": text}, title=title, pinned=pinned,
                 block_id=block_id)
    return b["id"]


def _push_table(headers: list[str], rows: list[list[str]],
                title: str = "", pinned: bool = False) -> str:
    b = _cv.push("table", {"headers": headers, "rows": rows},
                 title=title, pinned=pinned)
    return b["id"]


def _push_code(code: str, language: str = "text",
               title: str = "", pinned: bool = False) -> str:
    b = _cv.push("code", {"language": language, "code": code},
                 title=title, pinned=pinned)
    return b["id"]


# ── Agent-callable skills ─────────────────────────────────────────────────────

@skill(
    name="canvas_show",
    description=(
        "Push a markdown block to the Live Canvas visual workspace so the user can see "
        "rich formatted content in real time. Use this to display research results, "
        "analysis, summaries, plans, or any content that benefits from formatting. "
        "Parameters: text (markdown string), title (optional header), pinned (bool, "
        "default false — pinned blocks survive canvas_clear)."
    ),
    params={
        "text":   {"type": "string",  "description": "Markdown content to display"},
        "title":  {"type": "string",  "description": "Optional block header"},
        "pinned": {"type": "boolean", "description": "Keep this block after canvas_clear"},
    },
)
def canvas_show(text: str, title: str = "", pinned: bool = False) -> str:
    """Push a markdown block to the canvas."""
    block_id = _push_markdown(text, title=title, pinned=pinned)
    return f"[canvas] Block {block_id!r} displayed on canvas."


@skill(
    name="canvas_table",
    description=(
        "Push a data table to the Live Canvas. Use for structured data: transactions, "
        "schedules, search results, comparisons. "
        "Parameters: headers (list of column names), rows (list of lists of strings), "
        "title (optional header)."
    ),
    params={
        "headers": {"type": "array",  "items": {"type": "string"}, "description": "Column names"},
        "rows":    {"type": "array",  "description": "List of row arrays"},
        "title":   {"type": "string", "description": "Optional table title"},
    },
)
def canvas_table(headers: list[str], rows: list, title: str = "") -> str:
    """Push a table block to the canvas."""
    # Normalise rows to list-of-str-lists
    normalised = [[str(c) for c in row] for row in rows]
    block_id = _push_table(headers, normalised, title=title)
    return f"[canvas] Table {block_id!r} with {len(rows)} rows displayed on canvas."


@skill(
    name="canvas_code",
    description=(
        "Push a syntax-highlighted code block to the Live Canvas. Use for stack traces, "
        "log excerpts, config snippets, diffs, or any code output. "
        "Parameters: code (the text), language (python/json/bash/yaml/…), title (optional)."
    ),
    params={
        "code":     {"type": "string", "description": "Code or log text to display"},
        "language": {"type": "string", "description": "Language for syntax highlighting"},
        "title":    {"type": "string", "description": "Optional block header"},
    },
)
def canvas_code(code: str, language: str = "text", title: str = "") -> str:
    """Push a syntax-highlighted code block to the canvas."""
    block_id = _push_code(code, language=language, title=title)
    return f"[canvas] Code block {block_id!r} displayed on canvas."


@skill(
    name="canvas_metric",
    description=(
        "Push a large metric / KPI card to the Live Canvas. Great for showing a single "
        "important number with context (e.g. '$247.50 — Utilities bill, +12% vs last month'). "
        "Parameters: value (main number/text), label (description), delta (optional change "
        "string like '+12%'), good (bool — green if True, red if False)."
    ),
    params={
        "value": {"type": "string", "description": "Main value to display large"},
        "label": {"type": "string", "description": "What this number means"},
        "delta": {"type": "string", "description": "Optional change vs prior period, e.g. '+12%'"},
        "good":  {"type": "boolean", "description": "True = green, False = red"},
    },
)
def canvas_metric(value: str, label: str = "", delta: str = "",
                  good: bool = True) -> str:
    """Push a metric card to the canvas."""
    b = _cv.push("metric", {
        "value": value, "label": label, "delta": delta, "good": good,
    })
    return f"[canvas] Metric card {b['id']!r} displayed."


@skill(
    name="canvas_checklist",
    description=(
        "Push a checklist / task list to the Live Canvas. Use when the agent is working "
        "through a multi-step task and wants to show progress in real time. "
        "Parameters: items (list of dicts with 'text' and 'done' keys), title (optional)."
    ),
    params={
        "items": {"type": "array", "description": "List of {text, done} objects"},
        "title": {"type": "string", "description": "Optional header"},
    },
)
def canvas_checklist(items: list[dict], title: str = "") -> str:
    """Push a checklist block to the canvas."""
    normalised = [
        {"text": str(it) if not isinstance(it, dict) else it.get("text", str(it)),
         "done": it.get("done", False) if isinstance(it, dict) else False}
        for it in items
    ]
    b = _cv.push("checklist", {"items": normalised}, title=title)
    return f"[canvas] Checklist {b['id']!r} with {len(items)} items displayed."


@skill(
    name="canvas_progress",
    description=(
        "Push or update a progress bar on the Live Canvas. Call repeatedly to animate "
        "progress while running a long task. "
        "Parameters: label (what's happening), value (0.0–1.0), block_id (reuse to update "
        "an existing bar instead of creating a new one)."
    ),
    params={
        "label":    {"type": "string", "description": "Progress label"},
        "value":    {"type": "number", "description": "Progress 0.0 to 1.0"},
        "block_id": {"type": "string", "description": "ID of existing bar to update"},
    },
)
def canvas_progress(label: str, value: float = 0.0, block_id: str = "") -> str:
    """Push or update a progress bar on the canvas."""
    clamped = max(0.0, min(1.0, float(value)))
    if block_id:
        _cv.update_progress(block_id, clamped, label)
        return f"[canvas] Progress bar {block_id!r} updated to {int(clamped*100)}%."
    else:
        b = _cv.push("progress", {"label": label, "value": clamped},
                     block_id=block_id or None)
        return f"[canvas] Progress bar {b['id']!r} created. Use block_id={b['id']!r} to update it."


@skill(
    name="canvas_map",
    description=(
        "Push a map pin to the Live Canvas showing a location. "
        "Parameters: lat, lon, label (place name), zoom (1–18, default 13)."
    ),
    params={
        "lat":   {"type": "number", "description": "Latitude"},
        "lon":   {"type": "number", "description": "Longitude"},
        "label": {"type": "string", "description": "Place name / pin label"},
        "zoom":  {"type": "integer","description": "Zoom level 1–18"},
    },
)
def canvas_map(lat: float, lon: float, label: str = "", zoom: int = 13) -> str:
    """Push a map block to the canvas."""
    b = _cv.push("map", {"lat": lat, "lon": lon, "label": label, "zoom": zoom})
    return f"[canvas] Map block {b['id']!r} showing {label or f'{lat},{lon}'}."


@skill(
    name="canvas_chart",
    description=(
        "Push a bar or line chart to the Live Canvas. "
        "Parameters: kind ('bar' or 'line'), labels (list of x-axis labels), "
        "data (list of numbers), title (optional chart title)."
    ),
    params={
        "kind":   {"type": "string", "description": "'bar' or 'line'"},
        "labels": {"type": "array",  "description": "X-axis labels"},
        "data":   {"type": "array",  "description": "Y-axis values"},
        "title":  {"type": "string", "description": "Chart title"},
    },
)
def canvas_chart(kind: str, labels: list, data: list, title: str = "") -> str:
    """Push a chart block to the canvas."""
    b = _cv.push("chart", {
        "kind":   kind if kind in ("bar", "line") else "bar",
        "labels": [str(l) for l in labels],
        "data":   [float(d) for d in data],
    }, title=title)
    return f"[canvas] {kind.title()} chart {b['id']!r} with {len(data)} data points."


@skill(
    name="canvas_clear",
    description=(
        "Clear the Live Canvas. Removes all unpinned blocks. "
        "Call at the start of a new task to give the user a fresh view. "
        "Parameter: keep_pinned (bool, default True)."
    ),
    params={
        "keep_pinned": {"type": "boolean",
                        "description": "Keep pinned blocks (default True)"},
    },
)
def canvas_clear(keep_pinned: bool = True) -> str:
    """Clear the canvas."""
    _cv.clear(keep_pinned=keep_pinned)
    return "[canvas] Canvas cleared."
