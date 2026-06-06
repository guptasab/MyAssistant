"""Hugging Face skills exposed to the MyAssistant agent.

These are the tool-callable functions the agent uses when the user asks
about local models, e.g.:
  - "What local AI models can I run on my laptop?"
  - "Download Phi-3 for me"
  - "Which models are already installed?"
  - "Ask the local model: what should I have for dinner?"

All download operations require user confirmation (``sensitive=True``) since
they may download several gigabytes of data.
"""
from __future__ import annotations

from myassistant.core.registry import skill


@skill(
    name="hf_suggest_models",
    description=(
        "Suggest the best local AI models for the user's hardware. "
        "Use when user asks 'what models can I run locally?' or 'recommend a local AI model'."
    ),
    requires=[],
)
def hf_suggest_models() -> str:
    """Detect hardware and return personalised model recommendations."""
    from myassistant.skills.hf.manager import detect_hardware, suggest_models
    hw = detect_hardware()
    models = suggest_models(max_count=6)

    lines = [
        f"Your hardware: {hw['ram_gb']:.0f} GB RAM, "
        f"GPU VRAM: {hw['gpu_vram_gb']:.0f} GB "
        f"({'CUDA' if hw['has_cuda'] else 'Apple MPS' if hw['has_mps'] else 'CPU only'})",
        f"Recommended tier: **{hw['tier']}**\n",
        "Best models for your machine:\n",
    ]
    for m in models:
        star = "⭐ " if m.recommended else "   "
        lines.append(
            f"{star}**{m.name}** ({m.size_gb} GB)\n"
            f"   Category: {m.category} | Needs: {m.tier}\n"
            f"   {m.description}\n"
            f"   Install: `hf_download_model` with repo_id=`{m.repo_id}`\n"
        )
    return "\n".join(lines)


@skill(
    name="hf_list_catalog",
    description="List all available models in the HuggingFace catalog by category.",
    requires=[],
    parameters={
        "category": {
            "type": "string",
            "description": "Filter by category: chat, code, embed, stt, tts, vision (or 'all')",
            "default": "all",
        },
        "recommended_only": {
            "type": "boolean",
            "description": "Show only recommended models",
            "default": False,
        },
    },
)
def hf_list_catalog(category: str = "all", recommended_only: bool = False) -> str:
    """Return a formatted list of models from the curated catalog."""
    from myassistant.skills.hf.catalog import ALL_MODELS, recommended
    models = recommended() if recommended_only else ALL_MODELS
    if category != "all":
        models = [m for m in models if m.category == category]
    if not models:
        return f"No models found for category='{category}'"

    lines = [f"{'⭐ ' if m.recommended else '  '}{m.name} [{m.category}] "
             f"({m.size_gb} GB, {m.tier}): {m.description[:80]}"
             for m in models]
    return "\n".join(lines)


@skill(
    name="hf_download_model",
    description=(
        "Download a local AI model from HuggingFace. "
        "Use when user says 'download X model', 'install Phi-3 locally', etc. "
        "This is a large download (1–40 GB) — always confirm with user first."
    ),
    requires=[],
    sensitive=True,
    parameters={
        "repo_id": {
            "type": "string",
            "description": "HuggingFace repo ID, e.g. 'microsoft/Phi-3-mini-4k-instruct'",
        },
        "dry_run": {
            "type": "boolean",
            "description": "If true, show what would be downloaded without downloading",
            "default": False,
        },
    },
)
def hf_download_model(repo_id: str, dry_run: bool = False) -> str:
    """Download a model — requires user confirmation (sensitive=True)."""
    from myassistant.skills.hf.catalog import get as catalog_get
    info = catalog_get(repo_id)

    if dry_run:
        if info:
            return (
                f"Would download: **{info.name}**\n"
                f"  Size: ~{info.size_gb} GB\n"
                f"  Hardware needed: {info.tier}\n"
                f"  Will be available for: {', '.join(info.tags)}\n"
                f"  {info.description}"
            )
        return f"Would attempt to download {repo_id} from HuggingFace Hub."

    from myassistant.skills.hf.manager import download_model
    messages = []
    result = download_model(repo_id, progress_cb=messages.append)
    return result


@skill(
    name="hf_list_installed",
    description="List all locally installed HuggingFace / Ollama models.",
    requires=[],
)
def hf_list_installed() -> str:
    """Show what local models are available."""
    from myassistant.skills.hf.manager import list_installed
    installed = list_installed()
    if not installed:
        return (
            "No local models installed yet.\n"
            "Use `hf_suggest_models` to see what's recommended for your hardware,\n"
            "then `hf_download_model` to install one."
        )
    lines = [f"📦 {m['name']} ({m['category']}, {m.get('size_gb','?')} GB) "
             f"via {m.get('via','?')} — installed {m.get('installed_at','')}"
             for m in installed]
    return f"{len(installed)} local model(s) installed:\n" + "\n".join(lines)


@skill(
    name="hf_remove_model",
    description="Remove a locally installed model to free up disk space.",
    requires=[],
    sensitive=True,
    parameters={
        "repo_id": {
            "type": "string",
            "description": "HuggingFace repo ID to remove",
        },
        "dry_run": {
            "type": "boolean",
            "default": False,
        },
    },
)
def hf_remove_model(repo_id: str, dry_run: bool = False) -> str:
    """Remove a model — requires confirmation (sensitive=True)."""
    if dry_run:
        return f"Would remove {repo_id} and free up disk space."
    from myassistant.skills.hf.manager import remove_model
    return remove_model(repo_id)


@skill(
    name="hf_ask_local",
    description=(
        "Ask a question to a locally installed AI model (runs on your computer, "
        "no internet needed). Use for privacy-sensitive questions or offline mode."
    ),
    requires=[],
    parameters={
        "prompt": {
            "type": "string",
            "description": "Question or instruction to send to the local model",
        },
        "repo_id": {
            "type": "string",
            "description": "Model to use (omit to auto-select best available local model)",
            "default": "",
        },
    },
)
def hf_ask_local(prompt: str, repo_id: str = "") -> str:
    """Run inference on the best available local model."""
    from myassistant.skills.hf.manager import list_installed, run_model

    if not repo_id:
        installed = list_installed()
        if not installed:
            return (
                "No local models installed. "
                "Say 'suggest local models' to see what's available for your hardware."
            )
        # Prefer chat models
        chat = [m for m in installed if m.get("category") == "chat"]
        chosen = (chat or installed)[0]
        repo_id = chosen["repo_id"]

    return run_model(repo_id, prompt)


@skill(
    name="hf_hardware_check",
    description="Check what hardware (GPU, RAM) is available for running local AI models.",
    requires=[],
)
def hf_hardware_check() -> str:
    """Return a user-friendly hardware capability report."""
    from myassistant.skills.hf.manager import detect_hardware
    hw = detect_hardware()
    tier_names = {
        "cpu": "CPU only — no dedicated GPU",
        "gpu4": "Entry GPU (≥4 GB VRAM)",
        "gpu8": "Mid-range GPU (≥8 GB VRAM)",
        "gpu16": "High-end GPU (≥16 GB VRAM)",
        "gpu24plus": "Enthusiast GPU (≥24 GB VRAM)",
    }
    lines = [
        f"💻 System RAM:  {hw['ram_gb']:.0f} GB",
        f"🖥️  GPU VRAM:    {hw['gpu_vram_gb']:.0f} GB",
        f"⚡ GPU type:    {'NVIDIA CUDA' if hw['has_cuda'] else 'Apple MPS' if hw['has_mps'] else 'None detected'}",
        f"🎯 Tier:        {hw['tier']} — {tier_names.get(hw['tier'], '')}",
        "",
        "Say 'suggest local models' to see what AI models you can run.",
    ]
    return "\n".join(lines)
