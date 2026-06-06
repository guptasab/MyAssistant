"""Curated Hugging Face model catalog for Ram.

This module contains hand-curated, expert-vetted model recommendations
across all categories Ram needs: chat/LLM, speech, embeddings, vision,
and coding.  It is designed so non-technical users can pick a model
with a single click from the admin UI.

Each entry specifies:
  - What hardware it needs (VRAM or RAM)
  - What it is good at
  - Whether it is "recommended" for first-time users
  - The exact HuggingFace repo ID needed to download it

Tier definitions:
  cpu       — runs on any modern laptop, no GPU needed  (~4-16 GB RAM)
  gpu4      — needs a GPU with ≥4 GB VRAM (GTX 1650, RTX 3050, M1 base)
  gpu8      — needs ≥8 GB VRAM (RTX 3060, M1 Pro/Max)
  gpu16     — needs ≥16 GB VRAM (RTX 3090, RTX 4080, M2 Max)
  gpu24plus — needs ≥24 GB VRAM (RTX 3090 Ti, RTX 4090, Mac Ultra)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


Tier = Literal["cpu", "gpu4", "gpu8", "gpu16", "gpu24plus"]
Category = Literal["chat", "code", "embed", "stt", "tts", "vision", "tools"]


@dataclass
class HFModel:
    """A single model entry in the catalog.

    Attributes:
        repo_id:     HuggingFace ``owner/model-name`` identifier.
        name:        Human-readable display name.
        category:    What the model is for (chat, code, embed, stt, tts, vision, tools).
        tier:        Minimum hardware tier required to run it well.
        size_gb:     Approximate download size in gigabytes.
        description: Short plain-English description for non-technical users.
        tags:        Task tags that map to the LLM router (reasoning, fast, code, …).
        recommended: If True, shown first and labelled "⭐ Recommended" in the UI.
        quantized:   If True, this is a GGUF/GPTQ quantized variant (smaller, faster).
        ollama_name: Ollama model name if this model can be pulled via Ollama as well.
        notes:       Extra setup notes shown in the admin UI.
    """
    repo_id: str
    name: str
    category: Category
    tier: Tier
    size_gb: float
    description: str
    tags: list[str] = field(default_factory=list)
    recommended: bool = False
    quantized: bool = False
    ollama_name: str = ""
    notes: str = ""


# ── Chat / LLM models ────────────────────────────────────────────────────
CHAT_MODELS: list[HFModel] = [
    HFModel(
        repo_id="microsoft/Phi-3-mini-4k-instruct",
        name="Phi-3 Mini (4k)",
        category="chat",
        tier="cpu",
        size_gb=2.4,
        description=(
            "Microsoft's remarkably capable 3.8B model. Runs on any modern laptop "
            "with no GPU. Great for everyday tasks: scheduling, notes, answering "
            "questions, drafting emails."
        ),
        tags=["fast", "cheap", "private"],
        recommended=True,
        ollama_name="phi3:mini",
        notes="Best choice if you have no GPU. Very fast on CPU.",
    ),
    HFModel(
        repo_id="microsoft/Phi-3-medium-4k-instruct",
        name="Phi-3 Medium (4k)",
        category="chat",
        tier="gpu8",
        size_gb=7.6,
        description=(
            "Phi-3's bigger 14B sibling. Significantly better reasoning than Mini. "
            "A great balance of quality and speed for an 8GB GPU."
        ),
        tags=["reasoning", "fast", "private"],
        recommended=True,
        ollama_name="phi3:medium",
    ),
    HFModel(
        repo_id="Qwen/Qwen2.5-7B-Instruct",
        name="Qwen 2.5 7B",
        category="chat",
        tier="gpu8",
        size_gb=7.6,
        description=(
            "Alibaba's excellent 7B instruction model. Consistently outperforms "
            "Llama 3 8B on benchmarks. Good for reasoning, coding, and multilingual tasks."
        ),
        tags=["reasoning", "fast", "code", "private"],
        recommended=True,
        ollama_name="qwen2.5:7b",
    ),
    HFModel(
        repo_id="Qwen/Qwen2.5-14B-Instruct",
        name="Qwen 2.5 14B",
        category="chat",
        tier="gpu16",
        size_gb=14.5,
        description="Qwen's 14B model — near GPT-4o quality for text tasks at zero API cost.",
        tags=["reasoning", "draft", "code", "private"],
        ollama_name="qwen2.5:14b",
    ),
    HFModel(
        repo_id="meta-llama/Meta-Llama-3.1-8B-Instruct",
        name="Llama 3.1 8B",
        category="chat",
        tier="gpu8",
        size_gb=8.0,
        description=(
            "Meta's open-source flagship. Rock-solid for conversations, summarising, "
            "and following complex instructions. Needs a HuggingFace login for access."
        ),
        tags=["reasoning", "fast", "private"],
        ollama_name="llama3.1:8b",
        notes="Requires accepting Meta's license at huggingface.co/meta-llama.",
    ),
    HFModel(
        repo_id="meta-llama/Meta-Llama-3.1-70B-Instruct",
        name="Llama 3.1 70B",
        category="chat",
        tier="gpu24plus",
        size_gb=39.0,
        description="State-of-the-art open-source model. Rival to GPT-4o. Needs a powerful GPU.",
        tags=["reasoning", "draft", "code", "private"],
        ollama_name="llama3.1:70b",
        notes="Requires accepting Meta's license. Needs 24 GB+ VRAM or multi-GPU.",
    ),
    HFModel(
        repo_id="TheBloke/Llama-3-8B-Instruct-GGUF",
        name="Llama 3 8B (GGUF / CPU-friendly)",
        category="chat",
        tier="cpu",
        size_gb=4.6,
        description=(
            "Quantized Llama 3 8B that runs on CPU with llama.cpp. "
            "Slower than GPU but works on any machine."
        ),
        tags=["fast", "cheap", "private"],
        quantized=True,
        ollama_name="llama3:8b",
    ),
    HFModel(
        repo_id="mistralai/Mistral-7B-Instruct-v0.3",
        name="Mistral 7B",
        category="chat",
        tier="gpu8",
        size_gb=7.3,
        description="Mistral's fast and capable 7B model. Excellent instruction following.",
        tags=["fast", "reasoning", "private"],
        ollama_name="mistral:7b",
    ),
    HFModel(
        repo_id="google/gemma-2-9b-it",
        name="Gemma 2 9B",
        category="chat",
        tier="gpu8",
        size_gb=9.2,
        description=(
            "Google's newest open model. Unusually strong reasoning for its size. "
            "Great default choice for an 8-12 GB GPU."
        ),
        tags=["reasoning", "fast", "private"],
        recommended=True,
        ollama_name="gemma2:9b",
    ),
]

# ── Code models ──────────────────────────────────────────────────────────
CODE_MODELS: list[HFModel] = [
    HFModel(
        repo_id="Qwen/Qwen2.5-Coder-7B-Instruct",
        name="Qwen 2.5 Coder 7B",
        category="code",
        tier="gpu8",
        size_gb=7.6,
        description=(
            "Best-in-class open-source code model at 7B. Beats most 70B models on "
            "HumanEval. Handles Python, JS, TS, Go, Rust, Java."
        ),
        tags=["code", "private"],
        recommended=True,
        ollama_name="qwen2.5-coder:7b",
    ),
    HFModel(
        repo_id="deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct",
        name="DeepSeek Coder V2 Lite",
        category="code",
        tier="gpu8",
        size_gb=8.1,
        description="DeepSeek's MoE coding model. State-of-the-art for code generation.",
        tags=["code", "reasoning", "private"],
        ollama_name="deepseek-coder-v2:16b",
    ),
]

# ── Embedding models ─────────────────────────────────────────────────────
EMBED_MODELS: list[HFModel] = [
    HFModel(
        repo_id="BAAI/bge-small-en-v1.5",
        name="BGE Small English",
        category="embed",
        tier="cpu",
        size_gb=0.13,
        description=(
            "Lightning-fast embedding model for semantic search and memory. "
            "Runs on CPU with no GPU needed. Perfect for Ram's semantic recall."
        ),
        tags=["embed", "private"],
        recommended=True,
        notes="Great for powering 'remind me about…' and note search.",
    ),
    HFModel(
        repo_id="BAAI/bge-large-en-v1.5",
        name="BGE Large English",
        category="embed",
        tier="cpu",
        size_gb=1.34,
        description="Higher quality embeddings than BGE Small. Still CPU-friendly.",
        tags=["embed", "private"],
    ),
    HFModel(
        repo_id="nomic-ai/nomic-embed-text-v1.5",
        name="Nomic Embed Text v1.5",
        category="embed",
        tier="cpu",
        size_gb=0.27,
        description="Excellent open-source embedding model optimised for long documents.",
        tags=["embed", "private"],
        ollama_name="nomic-embed-text",
    ),
]

# ── Speech-to-Text models ────────────────────────────────────────────────
STT_MODELS: list[HFModel] = [
    HFModel(
        repo_id="openai/whisper-base",
        name="Whisper Base (local)",
        category="stt",
        tier="cpu",
        size_gb=0.15,
        description=(
            "OpenAI's Whisper in Base size. Runs entirely on your computer "
            "with no API key. Good enough for clear speech in quiet environments."
        ),
        tags=["private"],
        recommended=True,
        notes="Enable with RAM_LOCAL_WHISPER=true in your .env",
    ),
    HFModel(
        repo_id="openai/whisper-large-v3-turbo",
        name="Whisper Large v3 Turbo (local)",
        category="stt",
        tier="gpu4",
        size_gb=1.5,
        description=(
            "Best open-source speech-to-text. Near-human accuracy, "
            "supports 100+ languages, handles accents well."
        ),
        tags=["private"],
        recommended=True,
    ),
    HFModel(
        repo_id="distil-whisper/distil-large-v3",
        name="Distil-Whisper Large v3",
        category="stt",
        tier="gpu4",
        size_gb=0.75,
        description="6x faster than Whisper Large with only 1% accuracy loss. Best speed/quality tradeoff.",
        tags=["private"],
    ),
]

# ── Vision models ────────────────────────────────────────────────────────
VISION_MODELS: list[HFModel] = [
    HFModel(
        repo_id="llava-hf/llava-1.5-7b-hf",
        name="LLaVA 1.5 7B",
        category="vision",
        tier="gpu8",
        size_gb=7.8,
        description=(
            "Understands images and answers questions about them. "
            "Powers receipt scanning, document reading, and photo analysis in Ram."
        ),
        tags=["vision", "private"],
        recommended=True,
    ),
    HFModel(
        repo_id="microsoft/Phi-3-vision-128k-instruct",
        name="Phi-3 Vision",
        category="vision",
        tier="gpu8",
        size_gb=7.9,
        description="Microsoft's small vision-language model. Great at reading documents and receipts.",
        tags=["vision", "private"],
    ),
]


# ── Full catalog ─────────────────────────────────────────────────────────
ALL_MODELS: list[HFModel] = (
    CHAT_MODELS + CODE_MODELS + EMBED_MODELS + STT_MODELS + VISION_MODELS
)


def recommended() -> list[HFModel]:
    """Return models marked as recommended — shown by default in the UI."""
    return [m for m in ALL_MODELS if m.recommended]


def by_category(category: Category) -> list[HFModel]:
    """Return all models in a specific category."""
    return [m for m in ALL_MODELS if m.category == category]


def by_tier(max_tier: Tier) -> list[HFModel]:
    """Return models that fit within a hardware tier budget."""
    _order = ["cpu", "gpu4", "gpu8", "gpu16", "gpu24plus"]
    idx = _order.index(max_tier)
    return [m for m in ALL_MODELS if _order.index(m.tier) <= idx]


def get(repo_id: str) -> HFModel | None:
    """Look up a model by its repo_id."""
    return next((m for m in ALL_MODELS if m.repo_id == repo_id), None)
