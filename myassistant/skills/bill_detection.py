"""Bill detection + subscription audit — parses recurring charges from finance ledger."""
from __future__ import annotations

import time
from collections import defaultdict

from myassistant.core import contexts as ctx
from myassistant.core.memory import db
from myassistant.core.registry import skill


@skill(name="detect_bills",
       description=("Surface recurring charges (likely bills/subscriptions) from the last "
                    "120 days. Groups by merchant name."))
def detect_bills() -> str:
    cutoff = time.time() - 120 * 86400
    by_merch: dict[str, list[float]] = defaultdict(list)
    with db() as s:
        rows = s.query(ctx.FinanceEntry).filter(ctx.FinanceEntry.created_ts >= cutoff,
                                                ctx.FinanceEntry.kind == "expense").all()
        for r in rows:
            key = ((r.merchant or r.note) or "").lower().strip()[:30]
            if key:
                by_merch[key].append(float(r.amount))
    bills = []
    for merch, amts in by_merch.items():
        if len(amts) >= 3:
            avg = sum(amts) / len(amts)
            spread = max(amts) - min(amts)
            if spread / max(avg, 1) < 0.2:  # consistent
                bills.append((merch, len(amts), avg))
    bills.sort(key=lambda x: -x[2])
    if not bills:
        return "no recurring charges detected"
    return "\n".join(f"{m[:30]:<30} x{n:<3} ~${a:.2f}" for m, n, a in bills[:30])


@skill(name="subscription_audit",
       description="List likely subscriptions and rough monthly burn.")
def subscription_audit() -> str:
    raw = detect_bills()
    if "no recurring" in raw:
        return raw
    total = 0.0
    for line in raw.splitlines():
        try:
            total += float(line.split("$")[-1])
        except Exception:
            continue
    return f"{raw}\n\nMonthly subscription burn (rough): ${total:.2f}"
