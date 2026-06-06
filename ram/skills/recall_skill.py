"""Vector / semantic recall skill."""
from __future__ import annotations

from ram.core import vector_memory as vm
from ram.core.registry import skill


@skill(name="recall",
       description=("Semantic search across notes, journals, briefings, emails. "
                    "Returns top k matches with score."))
def recall(query: str, kind: str = "", k: int = 5) -> str:
    res = vm.search(query, kind=kind or None, k=k)
    if not res:
        return "(no matches)"
    out = []
    for r in res:
        out.append(f"[{r['kind']} {r['score']:.2f}] {r['text'][:200]}")
    return "\n".join(out)


@skill(name="remember_text",
       description="Store an arbitrary text as semantic memory (kind = note/journal/...)")
def remember_text(text: str, kind: str = "note") -> str:
    vid = vm.add(kind, text)
    return f"stored #{vid}" if vid else "ERROR: embedding failed (no provider?)"
