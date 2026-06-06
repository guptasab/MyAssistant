"""Symptom journal + doctor visit prep."""
from __future__ import annotations

import time

from sqlalchemy import Column, Integer, String, Text, Float

from ram.core.memory import Base, db, _engine
from ram.core.registry import skill


class Symptom(Base):
    __tablename__ = "symptoms"
    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, default=0, index=True)
    description = Column(Text)
    severity = Column(Integer, default=0)
    ts = Column(Float, default=time.time, index=True)


Base.metadata.create_all(_engine)


@skill(name="log_symptom",
       description="Record a symptom (description + severity 1-10) for self or a family member.")
def log_symptom(description: str, severity: int = 0, member_id: int = 0) -> str:
    with db() as s:
        s.add(Symptom(description=description, severity=severity, member_id=member_id))
    return "logged"


@skill(name="doctor_prep",
       description=("Compose a doctor-visit summary: recent symptoms, current meds, "
                    "and 2-3 questions to ask. Pass member_id=0 for owner."))
def doctor_prep(member_id: int = 0, days: int = 30) -> str:
    cutoff = time.time() - days * 86400
    with db() as s:
        syms = s.query(Symptom).filter(
            Symptom.ts >= cutoff,
            Symptom.member_id == member_id,
        ).order_by(Symptom.ts).all()
        try:
            from ram.skills.medications import Medication
            meds = s.query(Medication).filter(Medication.member_id == member_id).all()
        except Exception:
            meds = []
    sym_lines = "\n".join(f"  - [{s.severity}] {s.description}" for s in syms) or "(none)"
    med_lines = ", ".join(f"{m.name} {m.dose}" for m in meds) or "(none)"
    summary = f"Symptoms (last {days}d):\n{sym_lines}\n\nCurrent meds: {med_lines}\n"
    try:
        from ram.core.llm import llm_chat
        q = llm_chat([{"role": "user", "content":
            f"Given this patient summary, suggest 3 concise questions to ask a doctor:\n{summary}"
        }], task="reasoning", max_tokens=200)
        return summary + "\nSuggested questions:\n" + q
    except Exception:
        return summary
