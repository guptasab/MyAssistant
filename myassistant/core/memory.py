"""Persistent memory + per-user conversation history (SQLite, no server needed).

Memory architecture
───────────────────
  Message            — full conversation history, per user_id
  Fact               — long-term key/value facts about owner + world
  ConversationSummary — compressed summaries of old conversations
  Reminder           — time-based reminders

Incognito mode
──────────────
  • Global: set MEMORY_INCOGNITO_DEFAULT=true in .env
  • Per-session: user_id starts with "incognito_", or call set_incognito(user_id)
  • Incognito sessions: no messages, no facts saved; history not loaded

Auto-learning
─────────────
  After each conversation turn the agent can call remember_fact() to persist
  any preferences, dates, or info it discovers. The agent loop also calls
  _auto_extract_facts() which uses the LLM to scan recent messages and
  extract structured facts without user intervention.
"""
from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Column, Integer, String, Text, Float, Boolean, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from myassistant.core.config import settings

Base = declarative_base()

# ── Thread-local incognito flag (set per-session, not persisted) ──────────────
_incognito_store: threading.local = threading.local()


class Message(Base):
    """One turn of conversation (user or assistant)."""
    __tablename__ = "messages"
    id      = Column(Integer, primary_key=True)
    user_id = Column(String, index=True)
    role    = Column(String)                    # user | assistant | tool
    content = Column(Text)                      # JSON-encoded message blocks
    ts      = Column(Float, default=time.time, index=True)


class Fact(Base):
    """Long-lived facts the assistant has learned about the owner / world."""
    __tablename__ = "facts"
    id       = Column(Integer, primary_key=True)
    key      = Column(String, unique=True, index=True)
    value    = Column(Text)
    category = Column(String, default="general")  # preference | date | person | place | general
    source   = Column(String, default="manual")   # manual | auto_extracted | inferred
    ts       = Column(Float, default=time.time, index=True)
    confirmed = Column(Boolean, default=True)      # False = low-confidence, pending confirm


class ConversationSummary(Base):
    """Compressed summaries of old conversations to stay within context limits."""
    __tablename__ = "conversation_summaries"
    id       = Column(Integer, primary_key=True)
    user_id  = Column(String, index=True)
    summary  = Column(Text)
    from_ts  = Column(Float)                   # earliest message ts in this batch
    to_ts    = Column(Float)                   # latest message ts in this batch
    msg_count = Column(Integer, default=0)
    ts       = Column(Float, default=time.time)


class Reminder(Base):
    __tablename__ = "reminders"
    id      = Column(Integer, primary_key=True)
    user_id = Column(String, index=True)
    text    = Column(Text)
    due_ts  = Column(Float, index=True)
    fired   = Column(Integer, default=0)


_engine = create_engine(
    f"sqlite:///{settings.myassistant_data_dir / 'myassistant.db'}",
    future=True,
    connect_args={"check_same_thread": False},
)
Base.metadata.create_all(_engine)
SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)


@contextmanager
def db() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


# ── Incognito mode ────────────────────────────────────────────────────────────

def is_incognito(user_id: str) -> bool:
    """
    Return True if this user/session is in incognito mode.

    Incognito is active when ANY of:
      • MEMORY_ENABLED=false (global — disables ALL persistence)
      • MEMORY_INCOGNITO_DEFAULT=true (global default)
      • user_id starts with "incognito_"
      • set_incognito() was called for this user_id in the current process
    """
    if not settings.memory_enabled:
        return True
    if settings.memory_incognito_default:
        return True
    if user_id.startswith("incognito_"):
        return True
    store = getattr(_incognito_store, "users", set())
    return user_id in store


def set_incognito(user_id: str, enabled: bool) -> None:
    """Toggle incognito mode for *user_id* within this process (not persisted)."""
    if not hasattr(_incognito_store, "users"):
        _incognito_store.users = set()
    if enabled:
        _incognito_store.users.add(user_id)
    else:
        _incognito_store.users.discard(user_id)


# ── Conversation history ───────────────────────────────────────────────────────

def append_message(user_id: str, role: str, content: list | str) -> None:
    """Persist one message turn. No-op in incognito mode."""
    if is_incognito(user_id):
        return
    payload = json.dumps(content) if not isinstance(content, str) else content
    with db() as s:
        s.add(Message(user_id=user_id, role=role, content=payload))


def recent_messages(user_id: str, limit: int | None = None) -> list[dict]:
    """
    Return Anthropic-shaped messages in chronological order.

    Uses ``MEMORY_CONTEXT_MESSAGES`` setting if *limit* is None.
    Returns empty list in incognito mode.
    """
    if is_incognito(user_id):
        return []
    if limit is None:
        limit = settings.memory_context_messages
    with db() as s:
        rows = (
            s.query(Message)
            .filter(Message.user_id == user_id, Message.role.in_(("user", "assistant")))
            .order_by(Message.ts.desc())
            .limit(limit)
            .all()
        )
    rows.reverse()
    out = []
    for r in rows:
        try:
            content = json.loads(r.content)
        except json.JSONDecodeError:
            content = r.content
        out.append({"role": r.role, "content": content})
    return out


def search_history(user_id: str, query: str, limit: int = 10) -> list[dict]:
    """
    Full-text keyword search over stored conversation history.

    Returns matching messages with their roles and approximate timestamps.
    """
    if is_incognito(user_id):
        return []
    q = query.lower()
    with db() as s:
        rows = (
            s.query(Message)
            .filter(
                Message.user_id == user_id,
                Message.content.ilike(f"%{q}%"),
            )
            .order_by(Message.ts.desc())
            .limit(limit * 2)   # fetch extra; some may be tool blocks
            .all()
        )
    results = []
    for r in rows:
        try:
            content = json.loads(r.content)
            text = content if isinstance(content, str) else \
                " ".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
        except Exception:
            text = r.content[:300]
        if not text.strip():
            continue
        results.append({
            "role": r.role,
            "text": text[:400],
            "ts":   r.ts,
            "date": time.strftime("%Y-%m-%d %H:%M", time.localtime(r.ts)),
        })
        if len(results) >= limit:
            break
    return results


def get_summaries(user_id: str) -> list[dict]:
    """Return all stored conversation summaries for this user."""
    if is_incognito(user_id):
        return []
    with db() as s:
        rows = (
            s.query(ConversationSummary)
            .filter(ConversationSummary.user_id == user_id)
            .order_by(ConversationSummary.from_ts.asc())
            .all()
        )
    return [
        {
            "summary":    r.summary,
            "from_date":  time.strftime("%Y-%m-%d", time.localtime(r.from_ts)),
            "to_date":    time.strftime("%Y-%m-%d", time.localtime(r.to_ts)),
            "msg_count":  r.msg_count,
        }
        for r in rows
    ]


def compress_old_messages(user_id: str, keep_recent: int | None = None) -> int:
    """
    Compress messages older than ``MEMORY_RETENTION_DAYS`` into a summary.

    Returns number of messages compressed.
    """
    if is_incognito(user_id):
        return 0
    if keep_recent is None:
        keep_recent = settings.memory_context_messages

    cutoff = time.time() - settings.memory_retention_days * 86400

    with db() as s:
        old_rows = (
            s.query(Message)
            .filter(Message.user_id == user_id,
                    Message.ts < cutoff,
                    Message.role.in_(("user", "assistant")))
            .order_by(Message.ts.asc())
            .all()
        )
        if not old_rows:
            return 0

        # Build a text snippet for summarisation
        text_parts = []
        for r in old_rows:
            try:
                c = json.loads(r.content)
                txt = c if isinstance(c, str) else \
                    " ".join(b.get("text", "") for b in c
                             if isinstance(b, dict) and b.get("type") == "text")
            except Exception:
                txt = r.content
            if txt.strip():
                text_parts.append(f"[{r.role}] {txt[:300]}")

        if not text_parts:
            return 0

        raw_log = "\n".join(text_parts[:200])

        # Use LLM to summarise
        summary = _summarise_conversation(raw_log)

        # Store summary
        s.add(ConversationSummary(
            user_id=user_id,
            summary=summary,
            from_ts=old_rows[0].ts,
            to_ts=old_rows[-1].ts,
            msg_count=len(old_rows),
        ))

        # Delete the original rows
        ids = [r.id for r in old_rows]
        s.query(Message).filter(Message.id.in_(ids)).delete(synchronize_session=False)

    return len(old_rows)


def _summarise_conversation(text: str) -> str:
    """Use LLM to compress a conversation transcript into a compact summary."""
    try:
        from myassistant.core.llm import llm_chat
        prompt = [{"role": "user", "content":
            f"Summarise this conversation log in bullet points. "
            f"Focus on: preferences revealed, facts mentioned, decisions made, "
            f"important dates/numbers, and anything the user wants remembered.\n\n"
            f"{text[:4000]}"}]
        return llm_chat(prompt, task="fast", max_tokens=600)
    except Exception:
        # Fallback: just truncate
        return text[:800] + "…"


def clear_history(user_id: str) -> None:
    """Delete all messages and summaries for this user."""
    with db() as s:
        s.query(Message).filter(Message.user_id == user_id).delete()
        s.query(ConversationSummary).filter(
            ConversationSummary.user_id == user_id).delete()


def memory_stats(user_id: str) -> dict:
    """Return memory usage statistics for this user."""
    if is_incognito(user_id):
        return {"incognito": True}
    with db() as s:
        msg_count = s.query(Message).filter(Message.user_id == user_id).count()
        summary_count = s.query(ConversationSummary).filter(
            ConversationSummary.user_id == user_id).count()
        fact_count = s.query(Fact).count()
        oldest_msg = (
            s.query(Message.ts)
            .filter(Message.user_id == user_id)
            .order_by(Message.ts.asc())
            .first()
        )
    return {
        "messages":        msg_count,
        "summaries":       summary_count,
        "facts":           fact_count,
        "oldest_message":  time.strftime("%Y-%m-%d", time.localtime(oldest_msg[0]))
                           if oldest_msg else None,
        "incognito":       is_incognito(user_id),
    }


# ── Long-term facts ───────────────────────────────────────────────────────────

def remember(key: str, value: str, category: str = "general",
             source: str = "manual") -> None:
    """Persist a key/value fact. Overwrites if key already exists."""
    if not settings.memory_enabled:
        return
    with db() as s:
        existing = s.query(Fact).filter(Fact.key == key).one_or_none()
        if existing:
            existing.value    = value
            existing.category = category
            existing.source   = source
            existing.ts       = time.time()
        else:
            s.add(Fact(key=key, value=value, category=category, source=source))

def save_fact(key: str, value: str, category: str = "general", source: str = "manual") -> None:
    """Alias for remember() for backwards compatibility."""
    remember(key, value, category=category, source=source)


def recall(key: str) -> str | None:
    """Return the value of a fact, or None."""
    with db() as s:
        f = s.query(Fact).filter(Fact.key == key).one_or_none()
        return f.value if f else None


def forget(key: str) -> bool:
    """Delete a fact. Returns True if found and deleted."""
    with db() as s:
        n = s.query(Fact).filter(Fact.key == key).delete()
    return n > 0


def all_facts() -> dict[str, str]:
    """Return all facts as a dict."""
    with db() as s:
        return {f.key: f.value for f in s.query(Fact).order_by(Fact.ts.desc()).all()}


def facts_by_category(category: str) -> dict[str, str]:
    """Return facts filtered by category."""
    with db() as s:
        return {f.key: f.value
                for f in s.query(Fact).filter(Fact.category == category)
                          .order_by(Fact.ts.desc()).all()}


def search_facts(query: str) -> list[dict]:
    """Full-text search over fact keys and values."""
    q = query.lower()
    with db() as s:
        rows = s.query(Fact).filter(
            (Fact.key.ilike(f"%{q}%")) | (Fact.value.ilike(f"%{q}%"))
        ).all()
    return [{"key": f.key, "value": f.value, "category": f.category,
             "date": time.strftime("%Y-%m-%d", time.localtime(f.ts))} for f in rows]


def export_memory(user_id: str) -> dict:
    """Export all memory for a user as a serialisable dict."""
    return {
        "facts":    all_facts(),
        "summaries": get_summaries(user_id),
        "history":  [
            {"role": m["role"],
             "content": m["content"] if isinstance(m["content"], str)
                        else str(m["content"])[:300]}
            for m in recent_messages(user_id, limit=200)
        ],
    }


# ── Auto fact extraction ───────────────────────────────────────────────────────

def auto_extract_facts(user_id: str, recent_turns: int = 6) -> list[dict]:
    """
    Scan the most recent conversation turns and extract new facts/preferences
    using the LLM. Returns a list of {key, value, category} dicts that were saved.

    Called automatically by the agent loop after each conversation turn when
    MEMORY_AUTO_LEARN=true.
    """
    if is_incognito(user_id) or not settings.memory_auto_learn:
        return []

    msgs = recent_messages(user_id, limit=recent_turns)
    if len(msgs) < 2:
        return []

    # Build a minimal transcript
    transcript = "\n".join(
        f"{m['role'].upper()}: " +
        (m["content"] if isinstance(m["content"], str)
         else " ".join(b.get("text", "") for b in m["content"]
                       if isinstance(b, dict) and b.get("type") == "text"))[:300]
        for m in msgs
    )

    try:
        from myassistant.core.llm import llm_chat
        prompt = [{"role": "user", "content":
            f"""Read this conversation and extract facts worth remembering long-term.
Only extract facts that are EXPLICITLY stated (preferences, dates, names, locations,
dietary restrictions, hobbies, work info, etc.) — do NOT infer or guess.

Return ONLY a JSON array like:
[{{"key": "prefers_coffee_not_tea", "value": "true", "category": "preference"}},
 {{"key": "daughters_name", "value": "Emma", "category": "person"}},
 {{"key": "allergic_to_shellfish", "value": "true", "category": "preference"}},
 {{"key": "anniversary_date", "value": "June 12", "category": "date"}}]

Categories: preference | date | person | place | work | health | general

Conversation:
{transcript[:2500]}

JSON array (empty array [] if nothing worth remembering):"""}]

        raw = llm_chat(prompt, task="fast", max_tokens=400).strip()

        # Extract JSON array from response
        start = raw.find("[")
        end   = raw.rfind("]") + 1
        if start == -1 or end == 0:
            return []

        facts_list = json.loads(raw[start:end])
        saved = []
        for item in facts_list:
            if not isinstance(item, dict):
                continue
            key   = str(item.get("key", "")).strip().replace(" ", "_").lower()[:80]
            value = str(item.get("value", "")).strip()[:500]
            cat   = item.get("category", "general")
            if not key or not value:
                continue
            # Don't overwrite manually set facts
            existing = recall(key)
            if existing:
                continue
            remember(key, value, category=cat, source="auto_extracted")
            saved.append({"key": key, "value": value, "category": cat})
        return saved

    except Exception:
        return []
