"""Long-term memory and conversation history tools.

Gives the agent full control over what it remembers, how long it keeps
conversations, and whether a session is incognito.

Categories for facts
────────────────────
  preference  — likes/dislikes, dietary, habits
  date        — birthdays, anniversaries, deadlines
  person      — family, friends, colleagues
  place       — home, work, favourite spots
  work        — projects, teams, companies
  health      — allergies, medications, conditions
  general     — anything else
"""
from __future__ import annotations

import time
from myassistant.core import memory
from myassistant.core.registry import skill


# ── Fact management ───────────────────────────────────────────────────────────

@skill(
    name="remember_fact",
    description=(
        "Persist a long-term fact about the owner so it's available in ALL future "
        "conversations. Use proactively whenever the user reveals a preference, date, "
        "person, place, or piece of info worth remembering. "
        "Examples: dietary preferences, family names, work projects, allergies, "
        "anniversaries, favourite restaurants. "
        "Parameters: key (snake_case identifier), value (the fact), "
        "category (preference|date|person|place|work|health|general)."
    ),
    parameters={
        "key":      {"type": "string", "description": "snake_case key, e.g. 'prefers_oat_milk'"},
        "value":    {"type": "string", "description": "The fact to remember"},
        "category": {"type": "string", "description": "preference|date|person|place|work|health|general"},
    },
)
def remember_fact(key: str, value: str, category: str = "general") -> str:
    memory.remember(key, value, category=category, source="manual")
    return f"✅ Remembered: {key} = {value}"


@skill(
    name="recall_fact",
    description="Look up a previously stored fact by its key.",
    parameters={"key": {"type": "string", "description": "The key to look up"}},
)
def recall_fact(key: str) -> str:
    v = memory.recall(key)
    return v if v is not None else f"(no fact stored for '{key}')"


@skill(
    name="forget_fact",
    description="Delete a stored fact permanently. Use when the user corrects outdated info.",
    parameters={"key": {"type": "string", "description": "The key to delete"}},
)
def forget_fact(key: str) -> str:
    removed = memory.forget(key)
    return f"✅ Forgotten: {key}" if removed else f"(no fact found for '{key}')"


@skill(
    name="list_facts",
    description=(
        "List all long-term facts in memory, optionally filtered by category. "
        "Use when the user asks 'what do you know about me?' or 'what have you remembered?'"
    ),
    parameters={"category": {"type": "string", "description": "Optional filter: preference|date|person|place|work|health|general"}},
)
def list_facts(category: str = "") -> str:
    facts = memory.facts_by_category(category) if category else memory.all_facts()
    if not facts:
        return "(no facts stored)"
    lines = [f"📋 Stored facts ({len(facts)}):"]
    by_cat: dict[str, list[str]] = {}
    for k, v in facts.items():
        cat = "general"
        try:
            from myassistant.core.memory import db, Fact
            with db() as s:
                f = s.query(Fact).filter(Fact.key == k).one_or_none()
                if f:
                    cat = f.category
        except Exception:
            pass
        by_cat.setdefault(cat, []).append(f"  • {k}: {v}")

    for cat, items in sorted(by_cat.items()):
        lines.append(f"\n{cat.upper()}")
        lines.extend(items)
    return "\n".join(lines)


@skill(
    name="search_facts",
    description="Search stored facts by keyword — matches against both key and value.",
    parameters={"query": {"type": "string", "description": "Search term"}},
)
def search_facts_skill(query: str) -> str:
    results = memory.search_facts(query)
    if not results:
        return f"(no facts matching '{query}')"
    return "\n".join(f"• {r['key']} [{r['category']}]: {r['value']}" for r in results)


# ── Conversation history ───────────────────────────────────────────────────────

@skill(
    name="search_memory",
    description=(
        "Search through past conversation history for messages containing a keyword. "
        "Use when the user references something discussed before, e.g. "
        "'remember when we talked about my knee surgery?' or "
        "'what was that restaurant you suggested last week?'"
    ),
    parameters={
        "query":   {"type": "string",  "description": "Keyword or phrase to search for"},
        "user_id": {"type": "string",  "description": "User session ID (use 'cli' for CLI users)"},
        "limit":   {"type": "integer", "description": "Max results, default 5"},
    },
)
def search_memory(query: str, user_id: str = "cli", limit: int = 5) -> str:
    results = memory.search_history(user_id, query, limit=limit)
    if not results:
        return f"(no conversation history found matching '{query}')"
    lines = [f"🔍 Found {len(results)} match(es) for '{query}':"]
    for r in results:
        lines.append(f"\n  [{r['date']}] {r['role'].upper()}: {r['text'][:200]}")
    return "\n".join(lines)


@skill(
    name="memory_summary",
    description=(
        "Return a summary of all stored conversation summaries — compressed snapshots of "
        "past sessions. Use when the user asks about old conversations or what the assistant "
        "remembers from previous interactions."
    ),
    parameters={"user_id": {"type": "string", "description": "User session ID"}},
)
def memory_summary(user_id: str = "cli") -> str:
    summaries = memory.get_summaries(user_id)
    if not summaries:
        return "(no conversation summaries stored yet)"
    lines = [f"📚 Conversation history ({len(summaries)} period(s)):"]
    for s in summaries:
        lines.append(
            f"\n  {s['from_date']} → {s['to_date']} ({s['msg_count']} messages)\n"
            f"  {s['summary'][:300]}"
        )
    return "\n".join(lines)


@skill(
    name="memory_stats",
    description="Show memory usage: message count, facts stored, oldest conversation, incognito status.",
    parameters={"user_id": {"type": "string", "description": "User session ID"}},
)
def memory_stats_skill(user_id: str = "cli") -> str:
    stats = memory.memory_stats(user_id)
    if stats.get("incognito"):
        return "🔒 Incognito mode is ON — no conversation history is being saved."
    lines = [
        "🧠 Memory Stats:",
        f"  • Messages stored  : {stats['messages']}",
        f"  • Summaries        : {stats['summaries']}",
        f"  • Facts remembered : {stats['facts']}",
        f"  • Oldest message   : {stats['oldest_message'] or 'n/a'}",
        f"  • Incognito        : {'ON' if stats['incognito'] else 'OFF'}",
    ]
    return "\n".join(lines)


@skill(
    name="forget_conversation",
    description=(
        "Delete all stored conversation history for this session. "
        "Does NOT delete long-term facts. Use when user says 'forget our conversation', "
        "'clear my history', or 'start fresh'."
    ),
    parameters={"user_id": {"type": "string", "description": "User session ID to clear"}},
    sensitive=True,
)
def forget_conversation(user_id: str = "cli") -> str:
    memory.clear_history(user_id)
    return "✅ Conversation history cleared. Long-term facts are still stored."


@skill(
    name="set_incognito",
    description=(
        "Toggle incognito mode for this session. In incognito mode, nothing is saved — "
        "no messages, no auto-learned facts. Existing memories are not deleted. "
        "Use when the user says 'don't remember this', 'go incognito', "
        "'private mode on/off'."
    ),
    parameters={
        "enabled": {"type": "boolean", "description": "True = incognito on, False = incognito off"},
        "user_id": {"type": "string",  "description": "User session ID"},
    },
)
def set_incognito_skill(enabled: bool, user_id: str = "cli") -> str:
    memory.set_incognito(user_id, enabled)
    if enabled:
        return "🔒 Incognito mode ON — this conversation won't be saved."
    return "💾 Incognito mode OFF — conversations will be saved again."


@skill(
    name="compress_memory",
    description=(
        "Compress old conversation history into compact summaries to free up space "
        "while preserving important context. Safe to call at any time."
    ),
    parameters={"user_id": {"type": "string", "description": "User session ID"}},
)
def compress_memory(user_id: str = "cli") -> str:
    count = memory.compress_old_messages(user_id)
    if count == 0:
        return "Nothing to compress — all messages are within the retention window."
    return f"✅ Compressed {count} old messages into a summary."


@skill(
    name="export_memory",
    description="Export all memory (facts + summaries + recent history) as JSON for backup or inspection.",
    parameters={"user_id": {"type": "string", "description": "User session ID"}},
)
def export_memory_skill(user_id: str = "cli") -> str:
    import json
    data = memory.export_memory(user_id)
    facts_count  = len(data["facts"])
    summ_count   = len(data["summaries"])
    hist_count   = len(data["history"])
    # Save to data dir
    from myassistant.core.config import settings as s
    out_path = s.myassistant_data_dir / f"memory_export_{int(time.time())}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2))
    return (
        f"✅ Exported memory to {out_path}\n"
        f"  • {facts_count} facts\n"
        f"  • {summ_count} summaries\n"
        f"  • {hist_count} recent messages"
    )
