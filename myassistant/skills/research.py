"""Deep research skill — MyAssistant researches anything like an expert analyst.

Handles queries like:
  "Research Acme Corp before my meeting tomorrow"
  "What should I know about GPT-5?"
  "Find me the best Italian restaurant open now near Mountain View"
  "What are analysts saying about AAPL this week?"
  "Find dinner spots within 10 minutes of me"

Uses a layered strategy:
  1. Perplexity or Gemini (web-grounded) for fresh factual information
  2. Google Maps for location-aware queries
  3. LLM synthesis for structured analysis and recommendations

The research skill is the key differentiator between MyAssistant and a chatbot —
it combines real-time web search with intelligent synthesis, just like a
human researcher would.
"""
from __future__ import annotations

import json

from myassistant.core.registry import skill
from myassistant.core.config import settings
from myassistant.core.llm import llm_chat, llm_classify


def _web_search(query: str, max_results: int = 5) -> str:
    """Fetch real-time web search results using the best available provider."""
    # Perplexity — best for factual, current information
    if settings.perplexity_api_key:
        try:
            from myassistant.core.llm import _call_perplexity
            return _call_perplexity(
                "sonar-pro",
                [{"role": "user", "content": query}],
                max_tokens=800,
            )
        except Exception:
            pass

    # Brave Search API
    if settings.brave_search_api_key:
        try:
            import httpx
            r = httpx.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": max_results},
                headers={"Accept": "application/json",
                         "X-Subscription-Token": settings.brave_search_api_key},
                timeout=15,
            )
            r.raise_for_status()
            results = r.json().get("web", {}).get("results", [])
            return "\n\n".join(
                f"**{r.get('title','')}** ({r.get('url','')})\n{r.get('description','')}"
                for r in results[:max_results]
            )
        except Exception:
            pass

    # Tavily
    if settings.tavily_api_key:
        try:
            import httpx
            r = httpx.post(
                "https://api.tavily.com/search",
                json={"api_key": settings.tavily_api_key, "query": query,
                      "max_results": max_results, "include_answer": True},
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
            answer = data.get("answer", "")
            sources = "\n".join(
                f"• {x.get('title','')} — {x.get('url','')}"
                for x in data.get("results", [])[:max_results]
            )
            return (answer + "\n\nSources:\n" + sources).strip()
        except Exception:
            pass

    # Fallback: Gemini with web search grounding
    if settings.google_api_key or settings.gemini_api_key:
        try:
            return llm_chat(
                [{"role": "user", "content": f"Search the web and answer: {query}"}],
                task="search", max_tokens=600,
            )
        except Exception:
            pass

    return "(no web search provider configured — add PERPLEXITY_API_KEY, BRAVE_SEARCH_API_KEY, or TAVILY_API_KEY)"


@skill(
    name="deep_research",
    description=(
        "Research any topic using real-time web search + LLM synthesis. "
        "Use for: 'research X', 'what should I know about Y before my meeting', "
        "'what are people saying about Z', 'latest news on X'."
    ),
    parameters={
        "query":         {"type": "string", "description": "What to research"},
        "format":        {"type": "string", "default": "summary",
                          "description": "summary | bullets | deep_dive"},
        "context":       {"type": "string", "default": "",
                          "description": "Why you need this (for better synthesis)"},
    },
    requires=[],
)
def deep_research(query: str, format: str = "summary", context: str = "") -> str:
    """Research a topic and return a structured analysis."""
    # Step 1: Gather raw web information
    raw = _web_search(query, max_results=6)

    # Step 2: Synthesise with LLM
    context_clause = f"\nContext for why I need this: {context}" if context else ""
    format_instructions = {
        "summary":    "Write a concise 2-3 paragraph summary of key findings.",
        "bullets":    "Write 5-8 bullet points covering the most important facts.",
        "deep_dive":  "Write a structured analysis with sections: Overview, Key Facts, Opportunities/Risks, Recommended Actions.",
    }.get(format, "Write a concise summary.")

    prompt = f"""You are a research analyst. Based on the search results below, answer the query.
{format_instructions}{context_clause}

Query: {query}

Search results:
{raw[:3000]}"""

    return llm_chat([{"role": "user", "content": prompt}], task="reasoning", max_tokens=900)


@skill(
    name="find_nearby",
    description=(
        "Find places nearby — restaurants, services, stores, gas stations, etc. "
        "Use for: 'find dinner spots near me', 'coffee within 5 min', "
        "'Italian restaurant open now', 'where can I get my car serviced nearby'."
    ),
    parameters={
        "query":         {"type": "string",
                          "description": "What to find, e.g. 'Italian restaurant', 'coffee shop'"},
        "location":      {"type": "string", "default": "",
                          "description": "Address or 'current location'. Uses home if empty."},
        "max_drive_min": {"type": "integer", "default": 10,
                          "description": "Maximum drive time in minutes"},
        "open_now":      {"type": "boolean", "default": True},
        "max_results":   {"type": "integer", "default": 5},
    },
    requires=[],
)
def find_nearby(query: str, location: str = "", max_drive_min: int = 10,
                open_now: bool = True, max_results: int = 5) -> str:
    """Find nearby places using Google Maps or web search fallback."""
    # Resolve location
    if not location:
        from myassistant.core.memory import all_facts
        facts = all_facts()
        location = facts.get("home_address") or facts.get("city") or facts.get("location", "")

    if not location:
        return ("I don't know your location. Say 'my home is at <address>' to save it, "
                "or provide a location in your query.")

    # ── Google Maps (best quality) ────────────────────────────────────────
    if settings.google_maps_api_key:
        try:
            import googlemaps
            gmaps = googlemaps.Client(key=settings.google_maps_api_key)

            # Geocode location
            geo = gmaps.geocode(location)
            if not geo:
                return f"Could not find location: {location}"
            coords = geo[0]["geometry"]["location"]
            radius_m = max_drive_min * 700   # rough: 10min ≈ 7km in urban area

            places = gmaps.places_nearby(
                location=coords,
                radius=radius_m,
                keyword=query,
                open_now=open_now,
            ).get("results", [])

            if not places:
                return f"No {query} found within {max_drive_min} min of {location}."

            lines = [f"📍 {query} near {location} (within ~{max_drive_min} min drive):\n"]
            for p in places[:max_results]:
                name    = p.get("name", "")
                rating  = p.get("rating", "?")
                n_rates = p.get("user_ratings_total", 0)
                address = p.get("vicinity", "")
                price   = "💲" * (p.get("price_level", 0))
                status  = "🟢 Open" if p.get("opening_hours", {}).get("open_now") else "🔴 Closed"
                lines.append(f"  ⭐ {rating} ({n_rates}) {price}  **{name}**")
                lines.append(f"     {address}  {status}")

            # Get drive times for top results
            try:
                destinations = [p.get("vicinity", "") for p in places[:max_results]]
                matrix = gmaps.distance_matrix(location, destinations, mode="driving")
                for i, row in enumerate(matrix.get("rows", [{}])[0].get("elements", [])[:max_results]):
                    if row.get("status") == "OK":
                        dur = row["duration"]["text"]
                        lines[i * 2 + 1] += f"  🚗 {dur}"
            except Exception:
                pass

            return "\n".join(lines)

        except Exception as e:
            # Fallback to web search
            pass

    # ── Web search fallback ───────────────────────────────────────────────
    search_q = f"{query} near {location}" + (" open now" if open_now else "")
    return _web_search(search_q, max_results=max_results)


@skill(
    name="research_person",
    description=(
        "Research a person — their background, company, recent news, mutual connections. "
        "Use before important meetings, interviews, or when someone new reaches out."
    ),
    parameters={
        "name":    {"type": "string"},
        "company": {"type": "string", "default": ""},
        "context": {"type": "string", "default": "",
                    "description": "Why you need this, e.g. 'meeting them tomorrow'"},
    },
    requires=[],
)
def research_person(name: str, company: str = "", context: str = "") -> str:
    """Research a person and return a dossier."""
    # Check local contacts first
    local_notes = ""
    try:
        with __import__("myassistant.core.memory", fromlist=["db"]).db() as s:
            from myassistant.core import contexts
            contact = s.query(contexts.Contact).filter(
                contexts.Contact.name.ilike(f"%{name}%")
            ).first()
            if contact:
                local_notes = f"\nLocal notes: {contact.notes}" if contact.notes else ""
    except Exception:
        pass

    query = f"{name} {company} professional background LinkedIn".strip()
    raw = _web_search(query)

    context_clause = f" Context: {context}" if context else ""
    prompt = f"""Research brief for meeting/working with {name}:{context_clause}
    
Local info:{local_notes or ' (none)'}

Web research:
{raw[:2000]}

Write a concise professional brief with:
• Who they are (role, company, background)
• Notable achievements or recent news  
• Talking points / what they care about
• Any useful context for {context or 'working together'}"""

    return llm_chat([{"role": "user", "content": prompt}], task="reasoning", max_tokens=600)


@skill(
    name="research_company",
    description=(
        "Research a company — financials, news, culture, competitors. "
        "Use before sales calls, interviews, partnerships."
    ),
    parameters={
        "company": {"type": "string"},
        "depth":   {"type": "string", "default": "brief",
                    "description": "brief | deep"},
    },
    requires=[],
)
def research_company(company: str, depth: str = "brief") -> str:
    """Research a company and return a structured brief."""
    queries = [f"{company} company overview recent news 2024 2025"]
    if depth == "deep":
        queries.append(f"{company} financials revenue employees culture glassdoor")
        queries.append(f"{company} competitors market position")

    raw_parts = [_web_search(q) for q in queries]
    raw = "\n\n".join(raw_parts)[:3500]

    format_inst = "Write a detailed analysis with: Overview, Business Model, Recent News, Culture/People, Key Risks & Opportunities." if depth == "deep" else "Write a concise 3-bullet overview."

    prompt = f"""Company research brief for {company}.
{format_inst}

Sources:
{raw}"""
    return llm_chat([{"role": "user", "content": prompt}], task="reasoning", max_tokens=700)
