"""Notion two-way sync."""
from __future__ import annotations

from myassistant.core.config import settings
from myassistant.core.registry import skill


def _client():
    if not settings.notion_api_key:
        return None
    try:
        from notion_client import Client
        return Client(auth=settings.notion_api_key)
    except ImportError:
        return None


@skill(name="notion_search", description="Search Notion pages and databases.",
       requires=["notion_api_key"])
def notion_search(query: str, max_results: int = 10) -> str:
    c = _client()
    if not c:
        return "ERROR: notion not configured"
    res = c.search(query=query, page_size=max_results)
    out = []
    for r in res.get("results", []):
        title = ""
        for p in (r.get("properties", {}) or {}).values():
            if p.get("type") == "title":
                title = "".join(t.get("plain_text", "") for t in p.get("title", []))
                break
        out.append(f"{r.get('object','?'):<8} {r.get('id','?')[:8]}  {title or r.get('url','?')}")
    return "\n".join(out) or "(none)"


@skill(name="notion_create_page",
       description="Create a Notion page under a parent_id (database or page).",
       requires=["notion_api_key"], sensitive=True)
def notion_create_page(parent_id: str, title: str, body: str = "") -> str:
    c = _client()
    if not c:
        return "ERROR: notion not configured"
    children = []
    if body:
        children.append({"object": "block", "type": "paragraph",
                         "paragraph": {"rich_text": [{"type": "text", "text": {"content": body[:2000]}}]}})
    res = c.pages.create(
        parent={"page_id": parent_id},
        properties={"title": [{"type": "text", "text": {"content": title}}]},
        children=children,
    )
    return f"created {res.get('id','?')}"
