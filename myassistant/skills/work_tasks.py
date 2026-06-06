"""Projects & tasks — works for personal goals or work projects.

Context-aware: a task lives under family, personal, or work (or any custom
context like 'side_project'). Status workflow: todo → doing → done.
"""
from __future__ import annotations

import time
from datetime import datetime, date

from myassistant.core import contexts as ctx
from myassistant.core.memory import db
from myassistant.core.registry import skill


@skill(
    name="create_project",
    description=("Create a project (work or personal). context = work|personal|family|<custom>. "
                 "due is optional YYYY-MM-DD. stakeholders is a comma list of contact names."),
)
def create_project(name: str, context: str = "work", goal: str = "",
                   due: str = "", stakeholders: str = "") -> str:
    cid = ctx.resolve_context_id(context)
    with db() as s:
        existing = (
            s.query(ctx.Project)
            .filter(ctx.Project.context_id == cid, ctx.Project.name == name)
            .one_or_none()
        )
        if existing:
            for f, v in [("goal", goal), ("due", due), ("stakeholders", stakeholders)]:
                if v:
                    setattr(existing, f, v)
            return f"updated project {name}"
        p = ctx.Project(context_id=cid, name=name, goal=goal, due=due,
                        stakeholders=stakeholders)
        s.add(p)
    return f"created project '{name}' [{context}]"


@skill(
    name="list_projects",
    description="List active projects, optionally filtered by context.",
)
def list_projects(context: str = "", include_done: bool = False) -> str:
    with db() as s:
        q = s.query(ctx.Project)
        if context:
            cid = ctx.resolve_context_id(context)
            q = q.filter(ctx.Project.context_id == cid)
        if not include_done:
            q = q.filter(ctx.Project.status != "done")
        rows = q.all()
        if not rows:
            return "no projects"
        out = []
        ctxmap = {c.id: c.name for c in s.query(ctx.Context).all()}
        for p in rows:
            due = f" (due {p.due})" if p.due else ""
            out.append(f"[{ctxmap.get(p.context_id, '?')}] {p.name} — {p.status}{due}")
        return "\n".join(out)


@skill(
    name="add_task",
    description=("Add a task. context=work|personal|family|<custom>. priority=low|med|high|urgent. "
                 "due is YYYY-MM-DD or YYYY-MM-DDTHH:MM. project_name is optional."),
)
def add_task(title: str, context: str = "personal", priority: str = "med",
             due: str = "", project_name: str = "", assignee: str = "",
             notes: str = "") -> str:
    cid = ctx.resolve_context_id(context)
    pid = None
    if project_name:
        with db() as s:
            proj = (
                s.query(ctx.Project)
                .filter(ctx.Project.context_id == cid, ctx.Project.name == project_name)
                .one_or_none()
            )
            if proj:
                pid = proj.id
    with db() as s:
        t = ctx.Task(context_id=cid, project_id=pid, title=title,
                     priority=priority, due=due, assignee=assignee, notes=notes)
        s.add(t)
        s.flush()
        tid = t.id
    return f"task #{tid} added [{context}] {title}" + (f" (due {due})" if due else "")


@skill(
    name="list_tasks",
    description=("List open tasks. Filter by context and/or by 'today' (due today or overdue). "
                 "Sorted by priority then due."),
)
def list_tasks(context: str = "", today_only: bool = False, limit: int = 20) -> str:
    pri_order = {"urgent": 0, "high": 1, "med": 2, "low": 3}
    today_s = date.today().isoformat()
    with db() as s:
        q = s.query(ctx.Task).filter(ctx.Task.status != "done")
        if context:
            q = q.filter(ctx.Task.context_id == ctx.resolve_context_id(context))
        if today_only:
            q = q.filter((ctx.Task.due != "") & (ctx.Task.due <= today_s + "T23:59"))
        rows = q.all()
        if not rows:
            return "no open tasks"
        rows.sort(key=lambda t: (pri_order.get(t.priority, 4), t.due or "9999"))
        ctxmap = {c.id: c.name for c in s.query(ctx.Context).all()}
        out = []
        for t in rows[:limit]:
            pri = {"urgent": "🔴", "high": "🟠", "med": "🟡", "low": "⚪"}.get(t.priority, "·")
            due = f" ⏳ {t.due}" if t.due else ""
            out.append(f"  {pri} #{t.id} [{ctxmap.get(t.context_id,'?')}] {t.title}{due}")
        return "\n".join(out)


@skill(
    name="complete_task",
    description="Mark a task done by id.",
)
def complete_task(task_id: int) -> str:
    with db() as s:
        t = s.query(ctx.Task).filter(ctx.Task.id == task_id).one_or_none()
        if not t:
            return f"no task #{task_id}"
        t.status = "done"
        t.done_ts = time.time()
    return f"✓ task #{task_id} done"


@skill(
    name="update_task",
    description=("Update fields on a task. Pass only what changes. "
                 "status = todo|doing|blocked|done."),
)
def update_task(task_id: int, status: str = "", priority: str = "",
                due: str = "", title: str = "", notes: str = "") -> str:
    with db() as s:
        t = s.query(ctx.Task).filter(ctx.Task.id == task_id).one_or_none()
        if not t:
            return f"no task #{task_id}"
        for f, v in [("status", status), ("priority", priority), ("due", due),
                     ("title", title), ("notes", notes)]:
            if v:
                setattr(t, f, v)
        if status == "done":
            t.done_ts = time.time()
    return f"updated task #{task_id}"
