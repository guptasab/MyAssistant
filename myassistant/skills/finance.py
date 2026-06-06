"""Personal finance + work expenses. Same table, different contexts.

Use context='personal' for household budget, 'work' for reimbursables.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from myassistant.core import contexts as ctx
from myassistant.core.memory import db
from myassistant.core.registry import skill


@skill(
    name="log_expense",
    description=("Record an expense. context=personal|work|family. category is "
                 "free-text (groceries, dining, transit, utilities, software...). "
                 "is_reimbursable=True for work expenses you'll claim back."),
)
def log_expense(amount: float, category: str, merchant: str = "",
                context: str = "personal", note: str = "",
                is_reimbursable: bool = False, entry_date: str = "") -> str:
    cid = ctx.resolve_context_id(context)
    d = entry_date or date.today().isoformat()
    with db() as s:
        e = ctx.FinanceEntry(context_id=cid, date=d, kind="expense",
                             amount=float(amount), category=category,
                             merchant=merchant, note=note,
                             is_reimbursable=is_reimbursable)
        s.add(e)
        s.flush()
        eid = e.id
    tag = " (reimbursable)" if is_reimbursable else ""
    return f"💸 #{eid} {d} ${amount:.2f} {category}{(' @ ' + merchant) if merchant else ''}{tag}"


@skill(
    name="log_income",
    description="Record an income entry (paycheck, refund, gift). Same shape as log_expense.",
)
def log_income(amount: float, category: str = "salary", merchant: str = "",
               context: str = "personal", note: str = "",
               entry_date: str = "") -> str:
    cid = ctx.resolve_context_id(context)
    d = entry_date or date.today().isoformat()
    with db() as s:
        e = ctx.FinanceEntry(context_id=cid, date=d, kind="income",
                             amount=float(amount), category=category,
                             merchant=merchant, note=note)
        s.add(e)
    return f"💰 +${amount:.2f} {category} on {d}"


@skill(
    name="spending_summary",
    description=("Summarize spending for the last N days (default 30) grouped by category. "
                 "Optional context filter."),
)
def spending_summary(days: int = 30, context: str = "") -> str:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with db() as s:
        q = s.query(ctx.FinanceEntry).filter(
            ctx.FinanceEntry.kind == "expense",
            ctx.FinanceEntry.date >= cutoff,
        )
        if context:
            q = q.filter(ctx.FinanceEntry.context_id == ctx.resolve_context_id(context))
        rows = q.all()
    if not rows:
        return f"no expenses in last {days} days"
    by_cat: dict[str, float] = {}
    total = 0.0
    for r in rows:
        by_cat[r.category] = by_cat.get(r.category, 0.0) + r.amount
        total += r.amount
    lines = [f"💸 Last {days}d total: ${total:,.2f}"]
    for cat, amt in sorted(by_cat.items(), key=lambda x: -x[1]):
        lines.append(f"  {cat:<14} ${amt:,.2f}")
    return "\n".join(lines)


@skill(
    name="set_budget",
    description="Set a monthly budget for a category in a given context.",
)
def set_budget(category: str, monthly_limit: float, context: str = "personal") -> str:
    cid = ctx.resolve_context_id(context)
    with db() as s:
        b = (
            s.query(ctx.Budget)
            .filter(ctx.Budget.context_id == cid, ctx.Budget.category == category)
            .one_or_none()
        )
        if b:
            b.monthly_limit = float(monthly_limit)
        else:
            s.add(ctx.Budget(context_id=cid, category=category,
                             monthly_limit=float(monthly_limit)))
    return f"budget set: [{context}] {category} = ${monthly_limit:.2f}/mo"


@skill(
    name="budget_status",
    description="Show this month's spend vs. budget per category for a context.",
)
def budget_status(context: str = "personal") -> str:
    cid = ctx.resolve_context_id(context)
    today = date.today()
    month_start = today.replace(day=1).isoformat()
    with db() as s:
        budgets = s.query(ctx.Budget).filter(ctx.Budget.context_id == cid).all()
        if not budgets:
            return f"no budgets set for {context}"
        spend: dict[str, float] = {}
        for e in s.query(ctx.FinanceEntry).filter(
            ctx.FinanceEntry.context_id == cid,
            ctx.FinanceEntry.kind == "expense",
            ctx.FinanceEntry.date >= month_start,
        ).all():
            spend[e.category] = spend.get(e.category, 0.0) + e.amount
    out = [f"📊 {today.strftime('%B')} budget [{context}]:"]
    for b in budgets:
        used = spend.get(b.category, 0.0)
        pct = (used / b.monthly_limit * 100) if b.monthly_limit else 0
        bar = "🔴" if pct > 100 else "🟠" if pct > 80 else "🟢"
        out.append(f"  {bar} {b.category:<12} ${used:,.0f} / ${b.monthly_limit:,.0f} ({pct:.0f}%)")
    return "\n".join(out)


@skill(
    name="pending_reimbursements",
    description="List reimbursable expenses that haven't been reimbursed yet.",
)
def pending_reimbursements() -> str:
    with db() as s:
        rows = s.query(ctx.FinanceEntry).filter(
            ctx.FinanceEntry.is_reimbursable == True,
            ctx.FinanceEntry.reimbursed == False,
        ).order_by(ctx.FinanceEntry.date).all()
    if not rows:
        return "no pending reimbursements ✓"
    total = sum(r.amount for r in rows)
    out = [f"🧾 Pending reimbursements: ${total:,.2f}"]
    for r in rows:
        out.append(f"  #{r.id} {r.date} ${r.amount:.2f} {r.merchant or r.category}")
    return "\n".join(out)


@skill(
    name="mark_reimbursed",
    description="Mark a reimbursable expense as paid back by id.",
)
def mark_reimbursed(entry_id: int) -> str:
    with db() as s:
        e = s.query(ctx.FinanceEntry).filter(ctx.FinanceEntry.id == entry_id).one_or_none()
        if not e:
            return f"no entry #{entry_id}"
        e.reimbursed = True
    return f"✓ #{entry_id} marked reimbursed"
