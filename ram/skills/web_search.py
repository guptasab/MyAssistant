"""Web search & page fetch. Prefers Tavily (AI-friendly), falls back to Brave, then Serper."""
from __future__ import annotations

import httpx
from loguru import logger

from ram.core.config import settings
from ram.core.registry import skill


@skill(
    name="web_search",
    description="Search the web for current information (news, prices, facts, anything not in your training data).",
)
def web_search(query: str, num_results: int = 5) -> str:
    if settings.tavily_api_key:
        try:
            r = httpx.post(
                "https://api.tavily.com/search",
                json={"api_key": settings.tavily_api_key, "query": query,
                      "max_results": num_results, "include_answer": True},
                timeout=20,
            )
            r.raise_for_status()
            data = r.json()
            out = []
            if data.get("answer"):
                out.append(f"ANSWER: {data['answer']}\n")
            for res in data.get("results", [])[:num_results]:
                out.append(f"- {res['title']}\n  {res['url']}\n  {res.get('content','')[:300]}")
            return "\n".join(out) or "no results"
        except Exception as e:
            logger.warning(f"tavily failed: {e}")

    if settings.brave_search_api_key:
        try:
            r = httpx.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={"X-Subscription-Token": settings.brave_search_api_key},
                params={"q": query, "count": num_results}, timeout=15,
            )
            r.raise_for_status()
            results = r.json().get("web", {}).get("results", [])
            return "\n".join(
                f"- {x['title']}\n  {x['url']}\n  {x.get('description','')}" for x in results[:num_results]
            ) or "no results"
        except Exception as e:
            logger.warning(f"brave failed: {e}")

    if settings.serper_api_key:
        try:
            r = httpx.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": settings.serper_api_key},
                json={"q": query, "num": num_results}, timeout=15,
            )
            r.raise_for_status()
            data = r.json()
            out = []
            for x in data.get("organic", [])[:num_results]:
                out.append(f"- {x['title']}\n  {x['link']}\n  {x.get('snippet','')}")
            return "\n".join(out) or "no results"
        except Exception as e:
            logger.warning(f"serper failed: {e}")

    return "ERROR: no search provider configured (set TAVILY_API_KEY, BRAVE_SEARCH_API_KEY, or SERPER_API_KEY)"


@skill(
    name="fetch_url",
    description="Fetch the readable text content of a URL.",
)
def fetch_url(url: str) -> str:
    try:
        r = httpx.get(url, timeout=20, follow_redirects=True,
                      headers={"User-Agent": "RamAssistant/1.0"})
        r.raise_for_status()
        # Strip HTML cheaply
        import re
        text = re.sub(r"<script.*?</script>|<style.*?</style>", "", r.text, flags=re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:6000]
    except Exception as e:
        return f"ERROR fetching {url}: {e}"
