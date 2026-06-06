"""Group SMS broadcast — text the whole family or a subset."""
from __future__ import annotations

from ram.core import family as fam
from ram.core.registry import skill


@skill(
    name="group_text",
    description=("Send the same SMS to multiple family members. role can be 'all', "
                 "'parents', 'kids'. Confirm the message before sending."),
    requires=["twilio_account_sid", "twilio_sms_from"],
    sensitive=True,
)
def group_text(message: str, role: str = "all") -> str:
    f = fam.get_or_create_default_family()
    members = fam.list_members(f.id)
    targets = []
    for m in members:
        if role == "all" or m.role == role.rstrip("s"):
            if m.phone:
                targets.append(m)
    if not targets:
        return f"no members found for role={role}"
    try:
        from ram.channels.sms_channel import send_sms
    except Exception:
        return "ERROR: sms channel unavailable"
    sent = []
    for m in targets:
        try:
            send_sms(m.phone, message)
            sent.append(m.name)
        except Exception as e:
            sent.append(f"{m.name}(FAIL:{e})")
    return f"sent to {len(sent)}: {', '.join(sent)}"
