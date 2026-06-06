"""Hugging Face model manager — download, list, delete, and run local models.

This module lets users discover and install local AI models directly from
HuggingFace with a single function call (or button click in the admin UI).

Key features:
  - One-click download with real-time progress callbacks
  - Automatic hardware detection (GPU VRAM, CPU RAM) to suggest compatible models
  - Integration with Ollama: if Ollama is installed, models are pulled there
    (easier to manage, no Python dependencies at inference time)
  - Direct transformers pipeline fallback when Ollama is not available
  - Registration of downloaded models into MyAssistant's LLM router so they are
    automatically used for "private" and "cheap" tasks

Typical usage::

    from myassistant.skills.hf.manager import download_model, list_installed, run_model

    # Download recommended embedding model
    download_model("BAAI/bge-small-en-v1.5", progress_cb=print)

    # List what's already installed
    for m in list_installed():
        print(m["repo_id"], m["size_gb"])

    # Ask a question
    answer = run_model("microsoft/Phi-3-mini-4k-instruct", "What is the capital of France?")
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable

from loguru import logger

from myassistant.core.config import settings
from myassistant.skills.hf.catalog import HFModel, get as catalog_get, ALL_MODELS

# ── Constants ─────────────────────────────────────────────────────────────

# Where downloaded HF models are cached on disk
_HF_CACHE = Path(os.environ.get("HF_HOME", str(Path.home() / ".cache" / "huggingface")))
_INSTALLED_DB = Path(settings.myassistant_data_dir) / "hf_installed.json"


# ── Hardware detection ────────────────────────────────────────────────────

def detect_hardware() -> dict:
    """Detect available hardware and return a capability summary.

    Returns:
        dict with keys:
          - ``gpu_vram_gb``: VRAM in the best available GPU (0 = no GPU)
          - ``ram_gb``:      Total system RAM
          - ``has_cuda``:    True if NVIDIA CUDA is available
          - ``has_mps``:     True if Apple Metal (MPS) is available
          - ``tier``:        Suggested hardware tier ("cpu", "gpu4", …)
    """
    import platform
    gpu_vram_gb = 0
    has_cuda = False
    has_mps = False

    # Try PyTorch first (most reliable VRAM detection)
    try:
        import torch
        if torch.cuda.is_available():
            has_cuda = True
            gpu_vram_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            has_mps = True
            # Apple Silicon has unified memory — estimate from system RAM
            import psutil
            gpu_vram_gb = psutil.virtual_memory().total / 1e9 * 0.75  # ~75% is GPU-accessible
    except ImportError:
        pass

    # Fallback: nvidia-smi
    if not has_cuda and shutil.which("nvidia-smi"):
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                text=True, timeout=5
            )
            gpu_vram_gb = float(out.strip().splitlines()[0]) / 1024
            has_cuda = True
        except Exception:
            pass

    import psutil
    ram_gb = psutil.virtual_memory().total / 1e9

    # Determine tier
    if gpu_vram_gb >= 24:
        tier = "gpu24plus"
    elif gpu_vram_gb >= 16:
        tier = "gpu16"
    elif gpu_vram_gb >= 8:
        tier = "gpu8"
    elif gpu_vram_gb >= 4:
        tier = "gpu4"
    else:
        tier = "cpu"

    return {
        "gpu_vram_gb": round(gpu_vram_gb, 1),
        "ram_gb": round(ram_gb, 1),
        "has_cuda": has_cuda,
        "has_mps": has_mps,
        "tier": tier,
    }


def suggest_models(max_count: int = 5) -> list[HFModel]:
    """Return the best models for the user's hardware.

    Detects GPU/CPU capabilities, then returns recommended models that fit.
    Non-technical users can call this and trust the result.

    Args:
        max_count: Maximum number of suggestions to return.

    Returns:
        List of :class:`HFModel` objects, best first.
    """
    hw = detect_hardware()
    tier = hw["tier"]
    _order = {"cpu": 0, "gpu4": 1, "gpu8": 2, "gpu16": 3, "gpu24plus": 4}
    max_idx = _order[tier]

    candidates = [
        m for m in ALL_MODELS
        if _order.get(m.tier, 99) <= max_idx
    ]
    # Recommended first, then sort by tier (best hardware use), then size
    candidates.sort(key=lambda m: (not m.recommended, _order.get(m.tier, 0), m.size_gb))
    return candidates[:max_count]


# ── Installed model registry ──────────────────────────────────────────────

def _load_db() -> list[dict]:
    """Load the installed-models JSON database."""
    if _INSTALLED_DB.exists():
        try:
            return json.loads(_INSTALLED_DB.read_text())
        except Exception:
            pass
    return []


def _save_db(entries: list[dict]) -> None:
    """Persist the installed-models database to disk."""
    _INSTALLED_DB.parent.mkdir(parents=True, exist_ok=True)
    _INSTALLED_DB.write_text(json.dumps(entries, indent=2))


def list_installed() -> list[dict]:
    """Return all locally installed HF models.

    Returns:
        List of dicts with ``repo_id``, ``name``, ``category``,
        ``size_gb``, ``installed_at``, ``via`` (ollama | hf_cache | transformers).
    """
    return _load_db()


def is_installed(repo_id: str) -> bool:
    """Check whether a model is already installed locally."""
    return any(m["repo_id"] == repo_id for m in _load_db())


def _record_install(model: HFModel, via: str) -> None:
    """Record a successful install in the local database."""
    db = [m for m in _load_db() if m["repo_id"] != model.repo_id]
    db.append({
        "repo_id": model.repo_id,
        "name": model.name,
        "category": model.category,
        "size_gb": model.size_gb,
        "tags": model.tags,
        "tier": model.tier,
        "via": via,
        "ollama_name": model.ollama_name,
        "installed_at": time.strftime("%Y-%m-%d %H:%M"),
    })
    _save_db(db)


def remove_model(repo_id: str) -> str:
    """Remove a locally installed model.

    Deletes from HF cache and from the installed database.

    Args:
        repo_id: The HuggingFace ``owner/model-name`` to remove.

    Returns:
        Human-readable status message.
    """
    db = [m for m in _load_db() if m["repo_id"] != repo_id]
    _save_db(db)

    # Remove from HuggingFace cache
    try:
        from huggingface_hub import scan_cache_dir
        cache_info = scan_cache_dir()
        for repo in cache_info.repos:
            if repo.repo_id == repo_id:
                revisions = {rev.commit_hash for rev in repo.revisions}
                delete_strategy = cache_info.delete_revisions(*revisions)
                delete_strategy.execute()
                return f"Removed {repo_id} ({repo.size_on_disk_str})"
    except Exception as e:
        logger.debug(f"HF cache removal failed: {e}")

    # Ollama removal
    m_entry = next((m for m in _load_db() if m["repo_id"] == repo_id), None)
    if m_entry and m_entry.get("ollama_name") and shutil.which("ollama"):
        subprocess.run(["ollama", "rm", m_entry["ollama_name"]], capture_output=True)

    return f"Removed {repo_id} from database"


# ── Download ──────────────────────────────────────────────────────────────

def download_model(
    repo_id: str,
    progress_cb: Callable[[str], None] | None = None,
    via_ollama: bool | None = None,
) -> str:
    """Download a model from HuggingFace and make it available to MyAssistant.

    This is the one-click install function.  It:
    1. Checks if the model is in the catalog (and warns if not).
    2. Tries to pull via Ollama first (if available) — simpler to manage.
    3. Falls back to direct huggingface_hub download into the HF cache.
    4. Registers the model in MyAssistant's LLM router for "private" tasks.

    Args:
        repo_id:     HuggingFace ``owner/model-name`` (e.g. "microsoft/Phi-3-mini-4k-instruct").
        progress_cb: Optional callback called with status strings during download.
        via_ollama:  Force Ollama (True) or HF cache (False). None = auto-detect.

    Returns:
        Human-readable result message.
    """
    def _log(msg: str) -> None:
        logger.info(msg)
        if progress_cb:
            progress_cb(msg)

    model_info = catalog_get(repo_id)
    if not model_info:
        _log(f"⚠️  {repo_id} is not in the curated catalog — proceeding anyway.")
        # Create a minimal entry so we can still track it
        model_info = HFModel(
            repo_id=repo_id, name=repo_id.split("/")[-1],
            category="chat", tier="gpu8", size_gb=0, description="Custom model",
        )

    if is_installed(repo_id):
        return f"✅ {model_info.name} is already installed."

    _log(f"📥 Starting download: {model_info.name} (~{model_info.size_gb} GB)")

    # ── Try Ollama first (easiest to use, no Python inference code needed) ──
    use_ollama = via_ollama if via_ollama is not None else bool(
        model_info.ollama_name and shutil.which("ollama")
    )

    if use_ollama and model_info.ollama_name:
        result = _download_via_ollama(model_info, _log)
        if result:
            _record_install(model_info, "ollama")
            _register_in_router(model_info, "ollama")
            return f"✅ {model_info.name} installed via Ollama and ready to use!"

    # ── Fallback: direct HuggingFace download ──────────────────────────────
    result = _download_via_hf_hub(model_info, _log)
    if result:
        _record_install(model_info, "hf_cache")
        _register_in_router(model_info, "hf_cache")
        return f"✅ {model_info.name} downloaded and ready to use!"

    return f"❌ Download failed for {repo_id}. Check your internet connection and try again."


def _download_via_ollama(model: HFModel, log: Callable[[str], None]) -> bool:
    """Pull a model using the Ollama CLI."""
    log(f"🦙 Pulling {model.ollama_name} via Ollama…")
    try:
        proc = subprocess.Popen(
            ["ollama", "pull", model.ollama_name],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        for line in proc.stdout:
            stripped = line.strip()
            if stripped:
                log(f"   {stripped}")
        proc.wait(timeout=1800)
        if proc.returncode == 0:
            log(f"✅ Ollama pull complete: {model.ollama_name}")
            return True
        log(f"❌ Ollama returned exit code {proc.returncode}")
        return False
    except FileNotFoundError:
        log("Ollama not found — install from https://ollama.com/download")
        return False
    except Exception as e:
        log(f"Ollama pull failed: {e}")
        return False


def _download_via_hf_hub(model: HFModel, log: Callable[[str], None]) -> bool:
    """Download model files directly using huggingface_hub."""
    try:
        from huggingface_hub import snapshot_download
        log(f"⬇️  Downloading {model.repo_id} from HuggingFace Hub…")
        log("   (This may take several minutes depending on your connection.)")

        hf_token = os.environ.get("HF_TOKEN") or getattr(settings, "hf_token", "")

        snapshot_download(
            repo_id=model.repo_id,
            token=hf_token or None,
            ignore_patterns=["*.msgpack", "*.h5", "flax_model*", "tf_model*"],
        )
        log(f"✅ Download complete: {model.repo_id}")
        return True
    except ImportError:
        log("huggingface_hub not installed. Run: pip install huggingface_hub")
        return False
    except Exception as e:
        log(f"HF Hub download failed: {e}")
        return False


# ── Register in LLM router ────────────────────────────────────────────────

def _register_in_router(model: HFModel, via: str) -> None:
    """Dynamically add a downloaded model to the LLM router catalog.

    This means the model becomes available for "private" tasks immediately
    after installation — no restart required.
    """
    try:
        from myassistant.core.llm import _CATALOG, ProviderModel
        provider = "ollama" if via == "ollama" else "hf_local"
        model_id = model.ollama_name if via == "ollama" else model.repo_id
        tasks = tuple(model.tags) if model.tags else ("private", "fast")
        _CATALOG.append(ProviderModel(
            provider=provider,
            model=model_id,
            tasks=tasks,
            cost=0,    # free — runs locally
            latency=6, # slightly slower than API on consumer hardware
            quality=7,
        ))
        logger.info(f"Registered {model_id} in LLM router as {provider}/{model_id}")
    except Exception as e:
        logger.warning(f"Could not register {model.repo_id} in router: {e}")


# ── Inference ─────────────────────────────────────────────────────────────

def run_model(
    repo_id: str,
    prompt: str,
    max_tokens: int = 512,
    system: str = "",
) -> str:
    """Run inference on a locally installed model.

    Tries in order: Ollama API → transformers pipeline.

    Args:
        repo_id:    HF repo_id or Ollama model name.
        prompt:     User message.
        max_tokens: Maximum tokens in the response.
        system:     Optional system prompt.

    Returns:
        Generated text, or an error message prefixed with "ERROR:".
    """
    # Check if this is an Ollama model
    entry = next((m for m in _load_db() if m["repo_id"] == repo_id), None)
    ollama_name = (entry or {}).get("ollama_name", "")

    if ollama_name:
        result = _run_via_ollama(ollama_name, prompt, system, max_tokens)
        if not result.startswith("ERROR:"):
            return result

    # Direct transformers inference
    return _run_via_transformers(repo_id, prompt, system, max_tokens)


def _run_via_ollama(model_name: str, prompt: str, system: str, max_tokens: int) -> str:
    """Call the local Ollama REST API."""
    try:
        import httpx
        base = getattr(settings, "ollama_base_url", "http://localhost:11434")
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        r = httpx.post(
            f"{base}/api/chat",
            json={"model": model_name, "messages": messages,
                  "options": {"num_predict": max_tokens}, "stream": False},
            timeout=120,
        )
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        return f"ERROR: Ollama call failed: {e}"


def _run_via_transformers(repo_id: str, prompt: str, system: str, max_tokens: int) -> str:
    """Run inference directly via HuggingFace transformers."""
    try:
        from transformers import pipeline
        pipe = pipeline("text-generation", model=repo_id, max_new_tokens=max_tokens)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        result = pipe(messages)
        return result[0]["generated_text"][-1]["content"].strip()
    except Exception as e:
        return f"ERROR: transformers inference failed: {e}"
