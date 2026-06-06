"""Fitbit + Oura — read recent sleep + heart-rate snapshots."""
from __future__ import annotations

import httpx

from myassistant.core.config import settings
from myassistant.core.registry import skill


@skill(name="oura_recent_sleep",
       description="Get last 7 days of sleep summaries from Oura.",
       requires=["oura_access_token"])
def oura_recent_sleep() -> str:
    h = {"Authorization": f"Bearer {settings.oura_access_token}"}
    r = httpx.get("https://api.ouraring.com/v2/usercollection/sleep", headers=h, timeout=15)
    if r.status_code >= 300:
        return f"ERROR: {r.status_code}"
    out = []
    for d in r.json().get("data", [])[:7]:
        out.append(f"{d.get('day','?')}  {d.get('total_sleep_duration',0)/3600:.1f}h  HR avg {d.get('average_heart_rate','?')}")
    return "\n".join(out) or "(none)"


@skill(name="fitbit_recent",
       description="Read recent Fitbit activity (requires stored OAuth token in vault as 'fitbit_access_token').",
       requires=["fitbit_client_id"])
def fitbit_recent() -> str:
    from myassistant.core import vault
    tok = vault.reveal("fitbit_access_token")
    if not tok or "ERROR" in tok or "no vault" in tok:
        return "ERROR: store fitbit_access_token in vault"
    h = {"Authorization": f"Bearer {tok}"}
    r = httpx.get("https://api.fitbit.com/1/user/-/activities/date/today.json", headers=h, timeout=15)
    if r.status_code >= 300:
        return f"ERROR: {r.status_code}"
    s = r.json().get("summary", {})
    return f"steps {s.get('steps',0)}, active min {s.get('veryActiveMinutes',0)}, cal {s.get('caloriesOut',0)}"
