"""Instacart helper — placeholder using Connect API (requires partnership) but
falls back to drafting a one-tap order URL with the grocery list."""
from __future__ import annotations

from urllib.parse import quote

from ram.core import family as fam
from ram.core.registry import skill


@skill(
    name="instacart_draft_order",
    description=("Build an Instacart deep-link URL pre-filled with the family grocery list. "
                 "User taps to open and confirm."),
)
def instacart_draft_order(list_name: str = "Grocery", store: str = "") -> str:
    f = fam.get_or_create_default_family()
    flist = fam.get_or_create_list(f.id, list_name)
    from ram.core.memory import db
    with db() as s:
        items = [i.text for i in s.query(fam.ListItem).filter(
            fam.ListItem.list_id == flist.id, fam.ListItem.done == False
        ).all()][:30]
    if not items:
        return "list is empty"
    q = "%0A".join(quote(i) for i in items)
    url = f"https://www.instacart.com/store/search?k={q}"
    return f"{len(items)} items. Open: {url}"
