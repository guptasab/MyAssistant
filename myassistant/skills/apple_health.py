"""Apple Health import (CDA/XML export) → HealthLog rows."""
from __future__ import annotations

from pathlib import Path

from myassistant.core import contexts as ctx
from myassistant.core.memory import db
from myassistant.core.registry import skill


@skill(name="apple_health_import",
       description=("Import an Apple Health export.zip → export.xml file. Pass absolute path. "
                    "Adds steps, weight, heart rate, sleep entries to the personal HealthLog."))
def apple_health_import(xml_path: str, max_records: int = 5000) -> str:
    p = Path(xml_path)
    if not p.exists():
        return f"file not found: {xml_path}"
    try:
        import xml.etree.ElementTree as ET
        added = 0
        for _, elem in ET.iterparse(str(p), events=("end",)):
            if elem.tag != "Record":
                continue
            t = (elem.get("type") or "").replace("HKQuantityTypeIdentifier", "").lower()
            v = elem.get("value", "")
            d = (elem.get("startDate", "") or "")[:10]
            with db() as s:
                s.add(ctx.HealthLog(metric=t, value=v, date=d, note="apple_health"))
            added += 1
            elem.clear()
            if added >= max_records:
                break
        return f"imported {added} records"
    except Exception as e:
        return f"ERROR: {e}"
