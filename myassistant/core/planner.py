"""Plan-then-execute loop for complex multi-step tasks.

When the agent detects a task requiring multiple sensitive actions or many
steps, it can call `plan_task()` to present a numbered execution plan,
pause for approval, and then carry out each step with progress reporting.
"""
from __future__ import annotations

import json
import time
import uuid

from sqlalchemy import Column, String, Text, Float, Boolean, Integer

from myassistant.core.memory import Base, db, _engine


class ExecutionPlan(Base):
    __tablename__ = "plans"
    id = Column(String, primary_key=True)
    user_id = Column(String, index=True)
    goal = Column(Text)
    steps_json = Column(Text)          # list[{"n": 1, "desc": "...", "skill": "...", "args": {...}}]
    current_step = Column(Integer, default=0)
    status = Column(String, default="pending")  # pending | approved | running | done | cancelled
    result_json = Column(Text, default="[]")
    created_ts = Column(Float, default=time.time)


Base.metadata.create_all(_engine)


def create_plan(user_id: str, goal: str, steps: list[dict]) -> ExecutionPlan:
    with db() as s:
        p = ExecutionPlan(
            id=str(uuid.uuid4())[:8],
            user_id=user_id,
            goal=goal,
            steps_json=json.dumps(steps),
        )
        s.add(p)
        s.flush()
        s.expunge(p)
        return p


def get_active_plan(user_id: str) -> ExecutionPlan | None:
    with db() as s:
        p = (s.query(ExecutionPlan)
             .filter(ExecutionPlan.user_id == user_id,
                     ExecutionPlan.status.in_(["approved", "running"]))
             .order_by(ExecutionPlan.created_ts.desc()).first())
        if p:
            s.expunge(p)
        return p


def approve_plan(plan_id: str) -> None:
    with db() as s:
        p = s.query(ExecutionPlan).filter(ExecutionPlan.id == plan_id).first()
        if p:
            p.status = "approved"


def cancel_plan(plan_id: str) -> None:
    with db() as s:
        p = s.query(ExecutionPlan).filter(ExecutionPlan.id == plan_id).first()
        if p:
            p.status = "cancelled"


def format_plan(p: ExecutionPlan) -> str:
    steps = json.loads(p.steps_json)
    lines = [f"📋 Plan: **{p.goal}**\n"]
    for s in steps:
        lines.append(f"  {s['n']}. {s['desc']}")
    lines.append(f"\nPlan ID: {p.id}")
    lines.append("Reply **YES** to execute all steps, **NO** to cancel, or "
                 "**STEP N** to execute just step N.")
    return "\n".join(lines)
