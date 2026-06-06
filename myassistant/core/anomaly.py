"""Lightweight anomaly detection over finance + habits + health.

Uses simple z-score / ratio thresholds. Surfaces anomalies via briefing /
proactive nudges. Not an ML pipeline — Ollie should *notice*, not *diagnose*.
"""
from __future__ import annotations

import statistics
import time
from typing import Iterable


def zscore(values: list[float], target: float) -> float:
    if len(values) < 4:
        return 0.0
    try:
        mu = statistics.mean(values)
        sd = statistics.pstdev(values) or 1.0
        return (target - mu) / sd
    except Exception:
        return 0.0


def detect_finance_anomalies(transactions: Iterable[dict]) -> list[dict]:
    """transactions: [{amount, category, date, description}, ...]"""
    by_cat: dict[str, list[float]] = {}
    for t in transactions:
        by_cat.setdefault(t.get("category") or "other", []).append(float(t.get("amount", 0)))
    out = []
    for cat, vals in by_cat.items():
        if len(vals) < 5:
            continue
        latest = vals[-1]
        z = zscore(vals[:-1], latest)
        if abs(z) > 2.5 and abs(latest) > 25:
            out.append({"category": cat, "amount": latest, "zscore": round(z, 2),
                        "msg": f"{cat}: ${latest:.0f} is {z:+.1f}σ vs typical"})
    return out
