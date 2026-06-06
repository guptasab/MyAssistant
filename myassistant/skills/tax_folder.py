"""Tax folder — collect deductible-looking items into a virtual folder by year."""
from __future__ import annotations

import time
from datetime import datetime

from myassistant.core import contexts as ctx
from myassistant.core.memory import db
from myassistant.core.registry import skill


DEDUCTIBLE = ("home_office", "medical", "charity", "business", "tax", "deduct")


@skill(name="tax_summary",
       description="Summarize deductible-looking finance entries for a given year.")
def tax_summary(year: int = 0) -> str:
    if not year:
        year = datetime.now().year
    start = f"{year}-01-01"
    end = f"{year + 1}-01-01"
    with db() as s:
        rows = s.query(ctx.FinanceEntry).filter(
            ctx.FinanceEntry.date >= start, ctx.FinanceEntry.date < end
        ).all()
    flagged = [r for r in rows if any(d in (r.category or "").lower() or d in (r.note or "").lower()
                                      for d in DEDUCTIBLE)]
    total = sum(float(r.amount) for r in flagged)
    return f"{year}: {len(flagged)} deductible-looking items, ${total:.2f} total"


@skill(name="tax_tag",
       description="Tag a finance entry as deductible (appends to its note).")
def tax_tag(entry_id: int, note: str = "") -> str:
    with db() as s:
        r = s.query(ctx.FinanceEntry).filter(ctx.FinanceEntry.id == entry_id).first()
        if not r:
            return "not found"
        r.note = (r.note or "") + " [tax_deductible]"
        if note:
            r.note += f" {note}"
    return f"tagged #{entry_id}"
