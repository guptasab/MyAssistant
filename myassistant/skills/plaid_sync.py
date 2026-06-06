"""Plaid bank/credit card sync — pulls transactions, persists to FinanceEntry,
and surfaces anomalies + bills.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from myassistant.core import contexts as ctx
from myassistant.core.config import settings
from myassistant.core.memory import db
from myassistant.core.registry import skill


def _client():
    if not (settings.plaid_client_id and settings.plaid_secret):
        return None
    try:
        import plaid
        from plaid.api import plaid_api
        env_map = {"sandbox": plaid.Environment.Sandbox,
                   "development": plaid.Environment.Development,
                   "production": plaid.Environment.Production}
        cfg = plaid.Configuration(
            host=env_map.get(settings.plaid_env, plaid.Environment.Sandbox),
            api_key={"clientId": settings.plaid_client_id, "secret": settings.plaid_secret},
        )
        return plaid_api.PlaidApi(plaid.ApiClient(cfg))
    except ImportError:
        return None


@skill(
    name="plaid_sync_transactions",
    description=("Pull last N days of transactions from a stored Plaid access_token in the "
                 "vault under 'plaid_access_token' and store them in personal finance ledger."),
    requires=["plaid_client_id", "plaid_secret"],
)
def plaid_sync_transactions(days: int = 14) -> str:
    api = _client()
    if not api:
        return "ERROR: plaid not configured"
    from myassistant.core import vault
    tok = vault.reveal("plaid_access_token")
    if not tok or tok.startswith("ERROR") or tok.startswith("no vault"):
        return "ERROR: store plaid_access_token in vault first"
    try:
        from plaid.model.transactions_get_request import TransactionsGetRequest
        from datetime import date
        end = date.today()
        start = end - timedelta(days=days)
        req = TransactionsGetRequest(access_token=tok, start_date=start, end_date=end)
        resp = api.transactions_get(req).to_dict()
    except Exception as e:
        return f"ERROR: {e}"
    txns = resp.get("transactions", [])
    added = 0
    with db() as s:
        for t in txns:
            tdate = str(t.get("date"))
            existing = s.query(ctx.FinanceEntry).filter(
                ctx.FinanceEntry.date == tdate,
                ctx.FinanceEntry.amount == float(t.get("amount", 0)),
                ctx.FinanceEntry.merchant == (t.get("name", "")[:200]),
            ).first()
            if existing:
                continue
            e = ctx.FinanceEntry(
                context_id=2,
                date=tdate,
                kind="expense" if t.get("amount", 0) > 0 else "income",
                amount=abs(float(t.get("amount", 0))),
                merchant=t.get("name", "")[:200],
                category=(t.get("category") or [None])[0] or "uncategorized",
            )
            s.add(e)
            added += 1
    return f"synced {added} new transactions ({len(txns)} returned)"


@skill(name="finance_anomalies",
       description="Run anomaly detection on the last 90 days of finance entries.")
def finance_anomalies() -> str:
    from myassistant.core.anomaly import detect_finance_anomalies
    cutoff = time.time() - 90 * 86400
    with db() as s:
        rows = s.query(ctx.FinanceEntry).filter(ctx.FinanceEntry.created_ts >= cutoff).all()
        data = [{"amount": r.amount, "category": r.category, "description": r.merchant or r.note}
                for r in rows]
    out = detect_finance_anomalies(data)
    if not out:
        return "no anomalies"
    return "\n".join(o["msg"] for o in out)
