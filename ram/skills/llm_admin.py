"""LLM provider introspection skill."""
from __future__ import annotations

from ram.core.registry import skill


@skill(name="llm_providers",
       description="List which LLM providers are configured and which models are available.")
def llm_providers() -> str:
    from ram.core.llm import list_providers, available_models
    p = list_providers()
    enabled = [k for k, v in p.items() if v]
    disabled = [k for k, v in p.items() if not v]
    models = available_models()
    out = [f"Enabled providers ({len(enabled)}): {', '.join(enabled) or '(none)'}",
           f"Disabled: {', '.join(disabled)}",
           "",
           f"Available models ({len(models)}):"]
    for m in models[:40]:
        out.append(f"  {m}")
    return "\n".join(out)


@skill(name="llm_route",
       description=("Show which model would be picked for a given task tag "
                    "(reasoning/fast/search/vision/embed/draft/code/cheap/private)."))
def llm_route(task: str = "reasoning") -> str:
    from ram.core.llm import pick
    m = pick(task)
    if not m:
        return f"no model for task={task}"
    return f"task={task} → {m.provider}/{m.model_id}"
