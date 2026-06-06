"""Receipt OCR — extract structured fields from a receipt image using llm_vision."""
from __future__ import annotations

import json
from pathlib import Path

from ram.core import contexts as ctx
from ram.core.memory import db
from ram.core.registry import skill


@skill(
    name="receipt_ocr",
    description=("Read a receipt image and extract merchant, date, total, line items. "
                 "Pass the absolute path to the image. Auto-files into finance ledger."),
)
def receipt_ocr(image_path: str, context: str = "personal") -> str:
    p = Path(image_path)
    if not p.exists():
        return f"file not found: {image_path}"
    try:
        from ram.core.llm import llm_vision
        prompt = ("Extract from this receipt: merchant, date (ISO), total (number), "
                  "category (one of food/grocery/transport/health/entertainment/home/other). "
                  "Return ONLY JSON.")
        out = llm_vision(prompt, image_path=str(p))
        out = out.strip().lstrip("`").rstrip("`")
        if out.startswith("json"):
            out = out[4:]
        data = json.loads(out)
    except Exception as e:
        return f"ERROR parsing: {e}"
    ctx_id = ctx.resolve_context_id(context) if hasattr(ctx, "resolve_context_id") else 2
    with db() as s:
        e = ctx.FinanceEntry(
            context_id=ctx_id, kind="expense",
            amount=float(data.get("total", 0)),
            merchant=data.get("merchant", "receipt"),
            category=data.get("category", "other"),
            date=str(data.get("date", "")),
        )
        s.add(e)
    return f"logged: {data.get('merchant','?')} ${data.get('total','?')} ({data.get('category','?')})"
