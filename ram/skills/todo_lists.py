"""Shared family lists: grocery, weekend, custom to-dos.

Modeled after Ollie's "drop it in the group chat and it's truly a release" UX.
Anyone in the family can add, view, complete, or clear items.
"""
from __future__ import annotations

from ram.core import family as fam
from ram.core.memory import db
from ram.core.registry import skill


def _resolve_list(name: str, kind: str = "todo") -> fam.FamilyList:
    f = fam.get_or_create_default_family()
    return fam.get_or_create_list(f.id, name, kind=kind)


@skill(
    name="create_list",
    description=("Create a shared family list. kind is grocery, todo, weekend, "
                 "packing, or custom. Idempotent — returns existing list if name taken."),
)
def create_list(name: str, kind: str = "todo") -> str:
    lst = _resolve_list(name, kind)
    return f"list '{lst.name}' ({lst.kind}) ready (#{lst.id})"


@skill(
    name="list_all_lists",
    description="Show every shared list the family has.",
)
def list_all_lists() -> str:
    f = fam.get_or_create_default_family()
    with db() as s:
        lists = s.query(fam.FamilyList).filter(fam.FamilyList.family_id == f.id).all()
        if not lists:
            return "no lists yet"
        out = []
        for L in lists:
            n_open = (
                s.query(fam.ListItem)
                .filter(fam.ListItem.list_id == L.id, fam.ListItem.done == False)
                .count()
            )
            n_total = s.query(fam.ListItem).filter(fam.ListItem.list_id == L.id).count()
            out.append(f"{L.name} ({L.kind}) — {n_open} open / {n_total} total")
        return "\n".join(out)


@skill(
    name="add_to_list",
    description=("Add one or more items to a shared family list. items is a "
                 "list of strings like ['milk', 'eggs', '2 lb chicken']. "
                 "If the list doesn't exist it will be created (kind defaults to todo)."),
)
def add_to_list(list_name: str, items: list, added_by: str = "", kind: str = "todo") -> str:
    lst = _resolve_list(list_name, kind)
    added = []
    with db() as s:
        for raw in items:
            text = str(raw).strip()
            if not text:
                continue
            s.add(fam.ListItem(list_id=lst.id, text=text, added_by=added_by))
            added.append(text)
    return f"added {len(added)} to '{lst.name}': " + ", ".join(added[:8]) + ("…" if len(added) > 8 else "")


@skill(
    name="show_list",
    description="Show open items on a shared family list.",
)
def show_list(list_name: str, include_done: bool = False) -> str:
    f = fam.get_or_create_default_family()
    with db() as s:
        lst = (
            s.query(fam.FamilyList)
            .filter(fam.FamilyList.family_id == f.id, fam.FamilyList.name == list_name)
            .one_or_none()
        )
        if not lst:
            return f"no list named '{list_name}'"
        q = s.query(fam.ListItem).filter(fam.ListItem.list_id == lst.id)
        if not include_done:
            q = q.filter(fam.ListItem.done == False)
        items = q.order_by(fam.ListItem.added_ts).all()
        if not items:
            return f"'{list_name}' is empty ✓"
        lines = [f"📝 {lst.name}:"]
        for i in items:
            mark = "✓" if i.done else "•"
            by = f" ({i.added_by})" if i.added_by else ""
            lines.append(f"  {mark} {i.text}{by}")
        return "\n".join(lines)


@skill(
    name="complete_list_items",
    description=("Mark items done on a shared family list by their text "
                 "(case-insensitive partial match). items is a list of strings."),
)
def complete_list_items(list_name: str, items: list) -> str:
    f = fam.get_or_create_default_family()
    import time
    completed = []
    with db() as s:
        lst = (
            s.query(fam.FamilyList)
            .filter(fam.FamilyList.family_id == f.id, fam.FamilyList.name == list_name)
            .one_or_none()
        )
        if not lst:
            return f"no list named '{list_name}'"
        rows = s.query(fam.ListItem).filter(
            fam.ListItem.list_id == lst.id, fam.ListItem.done == False
        ).all()
        for needle in items:
            n = str(needle).lower().strip()
            for r in rows:
                if n in r.text.lower() and not r.done:
                    r.done = True
                    r.done_ts = time.time()
                    completed.append(r.text)
                    break
    return f"completed {len(completed)}: " + ", ".join(completed) if completed else "nothing matched"


@skill(
    name="clear_list",
    description="Remove all completed items from a list (keeps open ones).",
)
def clear_list(list_name: str) -> str:
    f = fam.get_or_create_default_family()
    with db() as s:
        lst = (
            s.query(fam.FamilyList)
            .filter(fam.FamilyList.family_id == f.id, fam.FamilyList.name == list_name)
            .one_or_none()
        )
        if not lst:
            return f"no list named '{list_name}'"
        n = (
            s.query(fam.ListItem)
            .filter(fam.ListItem.list_id == lst.id, fam.ListItem.done == True)
            .delete()
        )
    return f"cleared {n} done items from '{list_name}'"
