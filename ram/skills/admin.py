"""Audit log skill — let the agent answer 'what did you do today?'"""
from __future__ import annotations

from datetime import datetime

from ram.core import audit
from ram.core.registry import skill


@skill(name="audit_recent",
       description="Show the last N sensitive actions Ollie has taken.")
def audit_recent(limit: int = 20) -> str:
    rows = audit.recent(limit)
    if not rows:
        return "(no audit entries)"
    out = []
    for r in rows:
        when = datetime.fromtimestamp(r["ts"]).strftime("%m-%d %H:%M")
        out.append(f"{when}  {r['action']:<22} {r['payload'][:80]}")
    return "\n".join(out)


@skill(name="weekly_review",
       description="Compose this week's review summary.")
def weekly_review() -> str:
    from ram.core.weekly_review import compose
    return compose()


@skill(name="proactive_suggestions",
       description="What Ollie thinks is worth bringing up right now.")
def proactive_suggestions() -> str:
    from ram.core.suggestions import collect
    out = collect()
    return "\n".join(f"• {s}" for s in out) or "(nothing pressing)"


@skill(name="export_backup",
       description="Create a zip backup of the data directory and return path.",
       sensitive=True)
def export_backup() -> str:
    from ram.core.backup import export_zip
    return str(export_zip())
