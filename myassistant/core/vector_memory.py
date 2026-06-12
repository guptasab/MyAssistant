"""Vector memory — semantic recall over notes, journals, emails, briefings, etc.

Stores embeddings as JSON blobs in SQLite. For ~10k-100k entries this is plenty
fast; we read all rows and do cosine in numpy. No external vector DB needed.
"""
from __future__ import annotations

import json
import math
import threading
import time
from typing import Any

from sqlalchemy import Column, Integer, String, Text, Float

from myassistant.core.memory import Base, db, _engine

_write_lock = threading.Lock()


class VectorEntry(Base):
    __tablename__ = "vector_memory"
    id = Column(Integer, primary_key=True)
    kind = Column(String, index=True)          # note | journal | email | briefing | task | contact
    ref_id = Column(String, default="")         # foreign id when applicable
    text = Column(Text)
    embedding = Column(Text)                    # JSON list[float]
    metadata_json = Column(Text, default="{}")
    ts = Column(Float, default=time.time, index=True)


Base.metadata.create_all(_engine)


def _embed(text: str) -> list[float] | None:
    try:
        from myassistant.core.llm import llm_embed
        return llm_embed(text[:6000])
    except Exception:
        return None


def add(kind: str, text: str, ref_id: str = "", metadata: dict | None = None) -> int | None:
    vec = _embed(text)
    if not vec:
        return None
    with _write_lock:
        with db() as s:
            e = VectorEntry(
                kind=kind, ref_id=ref_id, text=text[:8000],
                embedding=json.dumps(vec),
                metadata_json=json.dumps(metadata or {}),
            )
            s.add(e)
            s.flush()
            return e.id


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


def search(query: str, kind: str | None = None, k: int = 5) -> list[dict]:
    qv = _embed(query)
    if not qv:
        return []
    with db() as s:
        q = s.query(VectorEntry)
        if kind:
            q = q.filter(VectorEntry.kind == kind)
        rows = q.order_by(VectorEntry.ts.desc()).limit(2000).all()
    scored = []
    for r in rows:
        try:
            v = json.loads(r.embedding)
            score = _cosine(qv, v)
            scored.append((score, r))
        except Exception:
            continue
    scored.sort(key=lambda x: -x[0])
    return [
        {"score": s, "kind": r.kind, "text": r.text[:600], "ref_id": r.ref_id, "ts": r.ts}
        for s, r in scored[:k]
    ]


def remember_note(text: str, ref_id: str = "") -> int | None:
    return add("note", text, ref_id)


def reindex_all() -> int:
    """Re-embed everything (call after switching providers)."""
    count = 0
    with db() as s:
        rows = s.query(VectorEntry).all()
        for r in rows:
            v = _embed(r.text)
            if v:
                r.embedding = json.dumps(v)
                count += 1
    return count
