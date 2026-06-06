"""Multi-provider LLM router — Squire (mysquire.ai).

Configure any combination of 18+ providers. Squire picks the best model for
each task class with graceful fallback. No Anthropic dependency required —
the default chain starts with free/cheap options first.

Public API (all return plain text):
  llm_chat(messages, *, task=..., max_tokens=..., temperature=...)
  llm_classify(prompt)                             # JSON-mode helper
  llm_search(query)                                # web-augmented
  llm_embed(texts) -> list[list[float]]            # vector embeddings
  llm_vision(image_bytes, prompt)                  # multimodal
  ensemble_chat(messages, *, task=..., strategy=...) # multi-model collective

Task classes:
  reasoning   — hard planning, multi-step thinking
  fast        — classify, parse JSON, extract fields
  search      — needs fresh web data
  vision      — image understanding
  embed       — vector embeddings
  draft       — long-form writing
  code        — code generation / review
  cheap       — bulk low-stakes classification
  private     — must not leave local box (Ollama only)
  ensemble    — run multiple cheap models, synthesise

Default routing preference (no Anthropic key needed):
  reasoning → Groq/DeepSeek/Gemini/OpenAI/Anthropic
  fast      → Groq Llama/Gemini Flash/Mistral/Anthropic Haiku
  code      → DeepSeek/Together DeepSeek/Groq/OpenAI Codex
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from loguru import logger

from ram.core.config import settings


# ---------- provider capability table ----------

@dataclass
class ProviderModel:
    provider: str
    model: str
    tasks: tuple[str, ...]
    cost: int = 5          # 1=cheapest, 10=priciest
    latency: int = 5       # 1=fastest, 10=slowest
    quality: int = 5       # 1..10
    ctx: int = 128_000

    @property
    def model_id(self) -> str:
        return self.model


# Order = preference within a task. No single provider required.
# Free/cheap providers are listed FIRST for each task so users with only
# free-tier keys get the best possible experience.
_CATALOG: list[ProviderModel] = [
    # ── Groq (free tier, fastest inference globally) ──────────────────────
    ProviderModel("groq", "moonshard-70b-8192",    ("reasoning", "draft"),              1, 1, 8, 8_192),
    ProviderModel("groq", "llama-3.3-70b-versatile",("fast", "cheap", "reasoning"),     1, 1, 7, 128_000),
    ProviderModel("groq", "llama-3.1-8b-instant",  ("fast", "cheap"),                   0, 1, 6, 128_000),
    ProviderModel("groq", "mixtral-8x7b-32768",    ("fast", "code"),                    1, 1, 7, 32_768),
    ProviderModel("groq", "whisper-large-v3",      ("transcribe",),                     1, 2, 9, 0),

    # ── Google Gemini (generous free tier) ────────────────────────────────
    ProviderModel("gemini", "gemini-2.5-pro",      ("reasoning", "draft", "vision", "search"), 7, 5, 9, 1_000_000),
    ProviderModel("gemini", "gemini-2.5-flash",    ("fast", "cheap", "vision", "search"),      1, 2, 8, 1_000_000),
    ProviderModel("gemini", "gemini-2.0-flash",    ("fast", "cheap"),                           1, 1, 7, 1_000_000),
    ProviderModel("gemini", "text-embedding-004",  ("embed",),                                  1, 2, 8, 2_048),

    # ── DeepSeek (open-weight, cheap API) ────────────────────────────────
    ProviderModel("deepseek", "deepseek-chat",     ("reasoning", "draft", "code"),      2, 4, 9, 128_000),
    ProviderModel("deepseek", "deepseek-coder",    ("code",),                           2, 4, 9, 128_000),
    ProviderModel("deepseek", "deepseek-reasoner", ("reasoning",),                      3, 6, 10, 64_000),

    # ── Together AI (cheap, many open models) ────────────────────────────
    ProviderModel("together", "deepseek-ai/DeepSeek-V3",  ("code", "reasoning", "cheap"), 2, 4, 8, 128_000),
    ProviderModel("together", "meta-llama/Llama-3.3-70B-Instruct-Turbo", ("reasoning","fast","cheap"), 2, 3, 8, 128_000),
    ProviderModel("together", "mistralai/Mixtral-8x22B-Instruct-v0.1",  ("reasoning","draft"),         3, 4, 8, 65_536),
    ProviderModel("together", "togethercomputer/m2-bert-80M-32k-retrieval", ("embed",),                1, 2, 7, 32_000),

    # ── Mistral ───────────────────────────────────────────────────────────
    ProviderModel("mistral", "mistral-large-latest",     ("reasoning", "code", "draft"), 6, 5, 8, 128_000),
    ProviderModel("mistral", "mistral-small-latest",     ("fast", "cheap"),              2, 2, 7, 128_000),
    ProviderModel("mistral", "codestral-latest",         ("code",),                      4, 3, 9, 256_000),
    ProviderModel("mistral", "mistral-embed",            ("embed",),                     2, 2, 8, 8_192),

    # ── Fireworks AI (fast inference) ────────────────────────────────────
    ProviderModel("fireworks", "accounts/fireworks/models/llama-v3p3-70b-instruct",
                               ("reasoning", "fast"), 2, 2, 8, 128_000),
    ProviderModel("fireworks", "accounts/fireworks/models/deepseek-v3",
                               ("code", "reasoning"), 2, 3, 9, 128_000),

    # ── OpenRouter (access to 100+ models via one key) ────────────────────
    ProviderModel("openrouter", "google/gemini-2.5-pro",       ("reasoning", "vision"),  7, 5, 9, 1_000_000),
    ProviderModel("openrouter", "deepseek/deepseek-chat-v3-0324", ("code", "reasoning"), 2, 4, 9, 128_000),
    ProviderModel("openrouter", "meta-llama/llama-3.3-70b-instruct", ("fast","cheap"),   1, 2, 7, 128_000),

    # ── Cerebras (extremely fast chip inference) ──────────────────────────
    ProviderModel("cerebras", "llama3.1-70b",    ("fast", "cheap"),                      2, 1, 7, 128_000),
    ProviderModel("cerebras", "llama3.3-70b",    ("reasoning", "fast"),                  2, 1, 8, 128_000),

    # ── OpenAI ────────────────────────────────────────────────────────────
    ProviderModel("openai", "gpt-5.2",            ("reasoning", "draft", "code", "vision"), 9, 6, 10, 200_000),
    ProviderModel("openai", "gpt-5-mini",         ("fast", "cheap"),                         2, 2, 7, 128_000),
    ProviderModel("openai", "gpt-5.3-codex",      ("code", "reasoning"),                     7, 5, 9, 200_000),
    ProviderModel("openai", "text-embedding-3-large", ("embed",),                             2, 2, 9, 8_191),

    # ── Perplexity (web-grounded) ─────────────────────────────────────────
    ProviderModel("perplexity", "sonar-pro",      ("search",),                            4, 4, 9, 200_000),
    ProviderModel("perplexity", "sonar",          ("search", "fast"),                     2, 3, 7, 128_000),

    # ── Azure OpenAI ──────────────────────────────────────────────────────
    ProviderModel("azure", "gpt-5",               ("reasoning", "draft", "code"),         8, 6, 10, 128_000),
    ProviderModel("azure", "gpt-5-mini",          ("fast", "cheap"),                      2, 2, 7, 128_000),

    # ── AWS Bedrock ───────────────────────────────────────────────────────
    ProviderModel("bedrock", "anthropic.claude-opus-4-v1:0",     ("reasoning", "draft"),  9, 7, 10, 200_000),
    ProviderModel("bedrock", "amazon.titan-embed-text-v2:0",     ("embed",),              1, 2, 7, 8_192),
    ProviderModel("bedrock", "meta.llama3-1-70b-instruct-v1:0",  ("reasoning", "fast"),   2, 4, 8, 128_000),

    # ── Anthropic (last fallback — not required) ──────────────────────────
    ProviderModel("anthropic", "claude-opus-4-7",           ("reasoning", "draft", "code", "vision"), 9, 7, 10, 200_000),
    ProviderModel("anthropic", "claude-sonnet-4-5",         ("reasoning", "draft", "code", "vision"), 6, 5, 9, 200_000),
    ProviderModel("anthropic", "claude-haiku-4-5-20251001", ("fast", "cheap", "vision"),               2, 2, 7, 200_000),

    # ── LM Studio (local OpenAI-compatible server) ────────────────────────
    ProviderModel("lmstudio", "local-model",      ("private", "fast", "cheap"),           0, 3, 6, 128_000),

    # ── Venice AI (privacy-first, no logs) ───────────────────────────────
    ProviderModel("venice", "llama-3.3-70b",      ("private", "reasoning"),               2, 4, 7, 128_000),

    # ── Ollama (fully local) ──────────────────────────────────────────────
    ProviderModel("ollama", "llama3.1:8b",         ("private", "fast", "cheap"),           0, 3, 6, 128_000),
    ProviderModel("ollama", "nomic-embed-text",    ("private", "embed"),                   0, 2, 6, 8_192),
    ProviderModel("ollama", "deepseek-coder:6.7b", ("private", "code"),                    0, 3, 7, 16_000),
]


# ---------- key + availability resolution ----------

def _has(*names: str) -> bool:
    return all(getattr(settings, n.lower(), "") for n in names)


def _provider_available(p: str) -> bool:
    if p == "anthropic":  return bool(getattr(settings, "anthropic_api_key", ""))
    if p == "openai":     return bool(getattr(settings, "openai_api_key", ""))
    if p == "gemini":     return bool(getattr(settings, "google_api_key", "") or getattr(settings, "gemini_api_key", ""))
    if p == "azure":      return _has("azure_openai_api_key", "azure_openai_endpoint")
    if p == "bedrock":    return _has("aws_access_key_id", "aws_secret_access_key") and bool(getattr(settings, "aws_region", ""))
    if p == "perplexity": return bool(getattr(settings, "perplexity_api_key", ""))
    if p == "groq":       return bool(getattr(settings, "groq_api_key", ""))
    if p == "mistral":    return bool(getattr(settings, "mistral_api_key", ""))
    if p == "together":   return bool(getattr(settings, "together_api_key", ""))
    if p == "deepseek":   return bool(getattr(settings, "deepseek_api_key", ""))
    if p == "fireworks":  return bool(getattr(settings, "fireworks_api_key", ""))
    if p == "openrouter": return bool(getattr(settings, "openrouter_api_key", ""))
    if p == "cerebras":   return bool(getattr(settings, "cerebras_api_key", ""))
    if p == "lmstudio":   return bool(getattr(settings, "lmstudio_base_url", ""))
    if p == "venice":     return bool(getattr(settings, "venice_api_key", ""))
    if p == "ollama":     return bool(getattr(settings, "ollama_base_url", "http://localhost:11434"))
    return False


def available_models(task: str) -> list[ProviderModel]:
    rows = [m for m in _CATALOG if task in m.tasks and _provider_available(m.provider)]
    # Sort by quality desc, then cost asc, then latency asc.
    return sorted(rows, key=lambda m: (-m.quality, m.cost, m.latency))


def pick(task: str, *, prefer_cheap: bool = False, prefer_fast: bool = False,
         require_private: bool = False) -> ProviderModel | None:
    if require_private:
        for m in _CATALOG:
            if "private" in m.tasks and _provider_available(m.provider):
                return m
        return None
    cands = available_models(task)
    if not cands:
        return None
    if prefer_cheap:
        cands = sorted(cands, key=lambda m: (m.cost, -m.quality))
    elif prefer_fast:
        cands = sorted(cands, key=lambda m: (m.latency, m.cost))
    return cands[0]


# ---------- low-level provider calls ----------

def _call_anthropic(model: str, messages: list[dict], system: str = "",
                    max_tokens: int = 1024, temperature: float = 0.5) -> str:
    from anthropic import Anthropic
    c = Anthropic(api_key=settings.anthropic_api_key)
    kwargs: dict[str, Any] = {"model": model, "max_tokens": max_tokens,
                              "messages": messages, "temperature": temperature}
    if system:
        kwargs["system"] = system
    r = c.messages.create(**kwargs)
    return "".join(b.text for b in r.content if b.type == "text").strip()


def _call_openai(model: str, messages: list[dict], system: str = "",
                 max_tokens: int = 1024, temperature: float = 0.5) -> str:
    from openai import OpenAI
    c = OpenAI(api_key=settings.openai_api_key)
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    r = c.chat.completions.create(model=model, messages=msgs,
                                  max_tokens=max_tokens, temperature=temperature)
    return (r.choices[0].message.content or "").strip()


def _call_gemini(model: str, messages: list[dict], system: str = "",
                 max_tokens: int = 1024, temperature: float = 0.5) -> str:
    import google.generativeai as genai
    genai.configure(api_key=getattr(settings, "google_api_key", "") or getattr(settings, "gemini_api_key", ""))
    g = genai.GenerativeModel(model, system_instruction=system or None)
    # Gemini takes a single prompt or chat-style
    parts = []
    for m in messages:
        role = "user" if m["role"] == "user" else "model"
        content = m["content"] if isinstance(m["content"], str) else json.dumps(m["content"])
        parts.append({"role": role, "parts": [content]})
    r = g.generate_content(parts, generation_config={
        "max_output_tokens": max_tokens, "temperature": temperature,
    })
    return (getattr(r, "text", "") or "").strip()


def _call_azure(model: str, messages: list[dict], system: str = "",
                max_tokens: int = 1024, temperature: float = 0.5) -> str:
    from openai import AzureOpenAI
    c = AzureOpenAI(
        api_key=settings.azure_openai_api_key,
        api_version=getattr(settings, "azure_openai_api_version", "2024-08-01-preview"),
        azure_endpoint=settings.azure_openai_endpoint,
    )
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    # `model` here is the Azure deployment name (settings.azure_openai_deployment fallback)
    deployment = getattr(settings, "azure_openai_deployment", "") or model
    r = c.chat.completions.create(model=deployment, messages=msgs,
                                  max_tokens=max_tokens, temperature=temperature)
    return (r.choices[0].message.content or "").strip()


def _call_bedrock(model: str, messages: list[dict], system: str = "",
                  max_tokens: int = 1024, temperature: float = 0.5) -> str:
    import boto3
    client = boto3.client(
        "bedrock-runtime",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens, "temperature": temperature, "messages": messages,
    }
    if system:
        body["system"] = system
    resp = client.invoke_model(modelId=model, body=json.dumps(body))
    payload = json.loads(resp["body"].read())
    return "".join(b.get("text", "") for b in payload.get("content", [])).strip()


def _call_perplexity(model: str, messages: list[dict], system: str = "",
                     max_tokens: int = 1024, temperature: float = 0.3) -> str:
    import httpx
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    r = httpx.post("https://api.perplexity.ai/chat/completions",
                   headers={"Authorization": f"Bearer {settings.perplexity_api_key}"},
                   json={"model": model, "messages": msgs,
                         "max_tokens": max_tokens, "temperature": temperature},
                   timeout=60)
    r.raise_for_status()
    j = r.json()
    text = j["choices"][0]["message"]["content"].strip()
    cites = j.get("citations") or []
    if cites:
        text += "\n\nSources:\n" + "\n".join(f"- {c}" for c in cites[:5])
    return text


def _call_groq(model: str, messages: list[dict], system: str = "",
               max_tokens: int = 1024, temperature: float = 0.5) -> str:
    import httpx
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    r = httpx.post("https://api.groq.com/openai/v1/chat/completions",
                   headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                   json={"model": model, "messages": msgs,
                         "max_tokens": max_tokens, "temperature": temperature},
                   timeout=60)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def _call_deepseek(model: str, messages: list[dict], system: str = "",
                   max_tokens: int = 1024, temperature: float = 0.5) -> str:
    """DeepSeek API — OpenAI-compatible endpoint."""
    import httpx
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    r = httpx.post("https://api.deepseek.com/v1/chat/completions",
                   headers={"Authorization": f"Bearer {getattr(settings, 'deepseek_api_key', '')}"},
                   json={"model": model, "messages": msgs,
                         "max_tokens": max_tokens, "temperature": temperature},
                   timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def _call_fireworks(model: str, messages: list[dict], system: str = "",
                    max_tokens: int = 1024, temperature: float = 0.5) -> str:
    """Fireworks AI — OpenAI-compatible, fast open-model inference."""
    import httpx
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    r = httpx.post("https://api.fireworks.ai/inference/v1/chat/completions",
                   headers={"Authorization": f"Bearer {getattr(settings, 'fireworks_api_key', '')}"},
                   json={"model": model, "messages": msgs,
                         "max_tokens": max_tokens, "temperature": temperature},
                   timeout=60)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def _call_openrouter(model: str, messages: list[dict], system: str = "",
                     max_tokens: int = 1024, temperature: float = 0.5) -> str:
    """OpenRouter — unified access to 100+ models via one API key."""
    import httpx
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    r = httpx.post("https://openrouter.ai/api/v1/chat/completions",
                   headers={
                       "Authorization": f"Bearer {getattr(settings, 'openrouter_api_key', '')}",
                       "HTTP-Referer": "https://mysquire.ai",
                       "X-Title": "Squire",
                   },
                   json={"model": model, "messages": msgs,
                         "max_tokens": max_tokens, "temperature": temperature},
                   timeout=60)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def _call_cerebras(model: str, messages: list[dict], system: str = "",
                   max_tokens: int = 1024, temperature: float = 0.5) -> str:
    """Cerebras — world's fastest inference chip, OpenAI-compatible."""
    import httpx
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    r = httpx.post("https://api.cerebras.ai/v1/chat/completions",
                   headers={"Authorization": f"Bearer {getattr(settings, 'cerebras_api_key', '')}"},
                   json={"model": model, "messages": msgs,
                         "max_tokens": max_tokens, "temperature": temperature},
                   timeout=30)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def _call_lmstudio(model: str, messages: list[dict], system: str = "",
                   max_tokens: int = 1024, temperature: float = 0.5) -> str:
    """LM Studio local server — OpenAI-compatible, fully private."""
    import httpx
    base = getattr(settings, "lmstudio_base_url", "http://localhost:1234")
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    r = httpx.post(f"{base}/v1/chat/completions",
                   json={"model": model, "messages": msgs,
                         "max_tokens": max_tokens, "temperature": temperature},
                   timeout=180)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def _call_venice(model: str, messages: list[dict], system: str = "",
                 max_tokens: int = 1024, temperature: float = 0.5) -> str:
    """Venice AI — privacy-first, no conversation logging, OpenAI-compatible."""
    import httpx
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    r = httpx.post("https://api.venice.ai/api/v1/chat/completions",
                   headers={"Authorization": f"Bearer {getattr(settings, 'venice_api_key', '')}"},
                   json={"model": model, "messages": msgs,
                         "max_tokens": max_tokens, "temperature": temperature},
                   timeout=60)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def _call_mistral(model: str, messages: list[dict], system: str = "",
                  max_tokens: int = 1024, temperature: float = 0.5) -> str:
    import httpx
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    r = httpx.post("https://api.mistral.ai/v1/chat/completions",
                   headers={"Authorization": f"Bearer {settings.mistral_api_key}"},
                   json={"model": model, "messages": msgs,
                         "max_tokens": max_tokens, "temperature": temperature},
                   timeout=60)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def _call_together(model: str, messages: list[dict], system: str = "",
                   max_tokens: int = 1024, temperature: float = 0.5) -> str:
    import httpx
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    r = httpx.post("https://api.together.xyz/v1/chat/completions",
                   headers={"Authorization": f"Bearer {settings.together_api_key}"},
                   json={"model": model, "messages": msgs,
                         "max_tokens": max_tokens, "temperature": temperature},
                   timeout=60)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def _call_ollama(model: str, messages: list[dict], system: str = "",
                 max_tokens: int = 1024, temperature: float = 0.5) -> str:
    import httpx
    base = getattr(settings, "ollama_base_url", "http://localhost:11434")
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    r = httpx.post(f"{base}/api/chat", json={
        "model": model, "messages": msgs, "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }, timeout=180)
    r.raise_for_status()
    j = r.json()
    return j.get("message", {}).get("content", "").strip()


_DISPATCH: dict[str, Callable[..., str]] = {
    "anthropic": _call_anthropic, "openai": _call_openai, "gemini": _call_gemini,
    "azure": _call_azure, "bedrock": _call_bedrock, "perplexity": _call_perplexity,
    "groq": _call_groq, "mistral": _call_mistral, "together": _call_together,
    "ollama": _call_ollama,
    "deepseek": _call_deepseek, "fireworks": _call_fireworks,
    "openrouter": _call_openrouter, "cerebras": _call_cerebras,
    "lmstudio": _call_lmstudio, "venice": _call_venice,
}


# ---------- public surface ----------

def llm_chat(messages: list[dict], *, task: str = "reasoning", system: str = "",
             max_tokens: int = 1024, temperature: float = 0.5,
             prefer_cheap: bool = False, prefer_fast: bool = False,
             require_private: bool = False, override: str | None = None) -> str:
    """Run a chat completion picking the best available model for `task`.

    `override` can be 'provider/model' to force a specific choice.
    Falls back across providers on error.
    """
    tried: list[str] = []
    candidates: list[ProviderModel] = []
    if override and "/" in override:
        prov, mdl = override.split("/", 1)
        candidates = [ProviderModel(prov, mdl, (task,))]
    else:
        primary = pick(task, prefer_cheap=prefer_cheap, prefer_fast=prefer_fast,
                       require_private=require_private)
        if primary:
            candidates.append(primary)
        # add 2 more fallbacks for resilience
        for m in available_models(task):
            if m not in candidates:
                candidates.append(m)
            if len(candidates) >= 3:
                break

    if not candidates:
        return f"(no LLM provider configured for task '{task}')"

    last_err: Exception | None = None
    for m in candidates:
        try:
            t0 = time.time()
            out = _DISPATCH[m.provider](
                m.model, messages, system=system,
                max_tokens=max_tokens, temperature=temperature,
            )
            logger.debug(f"llm_chat task={task} via {m.provider}/{m.model} in {time.time()-t0:.2f}s")
            return out
        except Exception as e:
            tried.append(f"{m.provider}/{m.model}")
            last_err = e
            logger.warning(f"llm fail {m.provider}/{m.model}: {e}")
    return f"(all providers failed for {task}: tried {', '.join(tried)} — last error: {last_err})"


def llm_classify(prompt: str, *, schema_hint: str = "JSON object",
                 prefer_cheap: bool = True) -> dict:
    """Force-JSON helper. Uses fast/cheap models by default."""
    out = llm_chat(
        [{"role": "user", "content": prompt + f"\n\nReturn ONLY a {schema_hint}."}],
        task="fast", prefer_cheap=prefer_cheap, max_tokens=600, temperature=0.0,
    )
    import re
    out = re.sub(r"^```(?:json)?|```$", "", out.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(out)
    except Exception:
        # last-ditch: extract first {...}
        m = re.search(r"\{.*\}", out, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        return {"_raw": out}


def llm_search(query: str, max_tokens: int = 600) -> str:
    """Web-grounded search via Perplexity, then Gemini, then a regular LLM
    (which will say it can't browse)."""
    if _provider_available("perplexity"):
        return llm_chat([{"role": "user", "content": query}], task="search",
                        max_tokens=max_tokens, temperature=0.3,
                        override="perplexity/sonar-pro")
    if _provider_available("gemini"):
        return llm_chat([{"role": "user", "content": query}], task="search",
                        max_tokens=max_tokens, override="gemini/gemini-2.5-pro")
    return llm_chat([{"role": "user", "content": query}], task="reasoning",
                    max_tokens=max_tokens)


def llm_embed(texts: list[str]) -> list[list[float]]:
    """Return embeddings. Picks first available embed-capable provider."""
    em = pick("embed")
    if not em:
        return [[] for _ in texts]
    try:
        if em.provider == "openai":
            from openai import OpenAI
            c = OpenAI(api_key=settings.openai_api_key)
            r = c.embeddings.create(model=em.model, input=texts)
            return [d.embedding for d in r.data]
        if em.provider == "gemini":
            import google.generativeai as genai
            genai.configure(api_key=getattr(settings, "google_api_key", "") or getattr(settings, "gemini_api_key", ""))
            return [genai.embed_content(model=em.model, content=t)["embedding"] for t in texts]
        if em.provider == "bedrock":
            import boto3
            client = boto3.client("bedrock-runtime", region_name=settings.aws_region,
                                  aws_access_key_id=settings.aws_access_key_id,
                                  aws_secret_access_key=settings.aws_secret_access_key)
            out = []
            for t in texts:
                resp = client.invoke_model(modelId=em.model,
                                           body=json.dumps({"inputText": t}))
                out.append(json.loads(resp["body"].read())["embedding"])
            return out
        if em.provider == "ollama":
            import httpx
            base = getattr(settings, "ollama_base_url", "http://localhost:11434")
            out = []
            for t in texts:
                r = httpx.post(f"{base}/api/embeddings",
                               json={"model": em.model, "prompt": t}, timeout=60)
                r.raise_for_status()
                out.append(r.json().get("embedding", []))
            return out
    except Exception as e:
        logger.warning(f"embed failed: {e}")
    return [[] for _ in texts]


def llm_vision(image_b64: str, prompt: str, mime: str = "image/jpeg") -> str:
    """Vision: image_b64 must be base64 (no data: prefix)."""
    m = pick("vision")
    if not m:
        return "(no vision-capable provider configured)"
    try:
        if m.provider == "anthropic":
            from anthropic import Anthropic
            c = Anthropic(api_key=settings.anthropic_api_key)
            r = c.messages.create(model=m.model, max_tokens=800, messages=[{
                "role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": mime, "data": image_b64}},
                    {"type": "text", "text": prompt},
                ],
            }])
            return "".join(b.text for b in r.content if b.type == "text").strip()
        if m.provider == "openai":
            from openai import OpenAI
            c = OpenAI(api_key=settings.openai_api_key)
            r = c.chat.completions.create(model=m.model, max_tokens=800, messages=[{
                "role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                ],
            }])
            return (r.choices[0].message.content or "").strip()
        if m.provider == "gemini":
            import base64, google.generativeai as genai
            genai.configure(api_key=getattr(settings, "google_api_key", "") or getattr(settings, "gemini_api_key", ""))
            g = genai.GenerativeModel(m.model)
            r = g.generate_content([{"mime_type": mime, "data": base64.b64decode(image_b64)}, prompt])
            return (getattr(r, "text", "") or "").strip()
    except Exception as e:
        logger.exception(f"vision failed: {e}")
    return f"(vision call failed)"


def list_providers() -> dict[str, bool]:
    """Return all known providers with their availability status."""
    all_providers = (
        "groq", "gemini", "deepseek", "together", "mistral",
        "fireworks", "openrouter", "cerebras",
        "openai", "perplexity", "azure", "bedrock",
        "anthropic", "lmstudio", "venice", "ollama",
    )
    return {p: _provider_available(p) for p in all_providers}


# ─── Ensemble / Mixture-of-Models ─────────────────────────────────────────────

def ensemble_chat(
    messages: list[dict],
    *,
    task: str = "reasoning",
    strategy: str = "synthesis",
    n_models: int = 3,
    max_tokens: int = 800,
    temperature: float = 0.5,
    system: str = "",
) -> str:
    """Run multiple cheap/free models in parallel and aggregate their answers.

    This is the "collective intelligence" mode — instead of spending money on
    one expensive frontier model, Squire polls N affordable models and combines
    their outputs. Useful for:
      - Fact-checking (majority vote)
      - Creative tasks (synthesis of diverse perspectives)
      - High-stakes decisions (judge model picks the best answer)

    Args:
        messages:    Chat messages (same format as llm_chat).
        task:        Task class — used to pick which models to query.
        strategy:    ``majority_vote`` | ``synthesis`` | ``best_of_n``
                     - majority_vote: for classification/yes-no — picks most common answer
                     - synthesis: synthesise all answers into one coherent response
                     - best_of_n: a judge model scores each answer and picks the best
        n_models:    How many models to query in parallel (2–5 recommended).
        max_tokens:  Per-model token budget.
        temperature: Generation temperature for member models.
        system:      Optional system prompt override.

    Returns:
        Aggregated answer string.
    """
    import concurrent.futures

    # Pick N diverse cheap models (prefer different providers for diversity)
    candidates: list[ProviderModel] = []
    seen_providers: set[str] = set()
    # First pass: one model per provider for maximum diversity
    for m in sorted(_CATALOG, key=lambda x: (x.cost, -x.quality)):
        if task in m.tasks and _provider_available(m.provider) and m.provider not in seen_providers:
            candidates.append(m)
            seen_providers.add(m.provider)
            if len(candidates) >= n_models:
                break
    # Second pass: fill remaining slots if not enough diverse providers
    if len(candidates) < n_models:
        for m in sorted(_CATALOG, key=lambda x: (x.cost, -x.quality)):
            if task in m.tasks and _provider_available(m.provider) and m not in candidates:
                candidates.append(m)
                if len(candidates) >= n_models:
                    break

    if not candidates:
        return llm_chat(messages, task=task, max_tokens=max_tokens,
                        temperature=temperature, system=system)

    def _query(m: ProviderModel) -> tuple[str, str]:
        try:
            fn = _DISPATCH.get(m.provider)
            if fn is None:
                return m.provider, f"(no handler for {m.provider})"
            out = fn(m.model, messages, system=system,
                     max_tokens=max_tokens, temperature=temperature)
            return m.provider, out
        except Exception as e:
            return m.provider, f"(error: {e})"

    # Query in parallel
    results: list[tuple[str, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=n_models) as pool:
        futures = {pool.submit(_query, m): m for m in candidates}
        for f in concurrent.futures.as_completed(futures, timeout=90):
            try:
                results.append(f.result())
            except Exception:
                pass

    if not results:
        return "(ensemble: all models failed)"

    valid = [(p, r) for p, r in results if not r.startswith("(")]
    if not valid:
        return results[0][1]  # return whatever we got

    # Apply aggregation strategy
    if strategy == "majority_vote":
        # For classification: strip whitespace and pick most common
        from collections import Counter
        answers = [r.strip().lower()[:100] for _, r in valid]
        most_common = Counter(answers).most_common(1)[0][0]
        logger.debug(f"ensemble majority_vote: {Counter(answers)}")
        return most_common

    elif strategy == "best_of_n":
        # Judge model scores each answer and picks the best
        labeled = "\n\n".join(
            f"[Answer {i+1} from {p}]:\n{r[:600]}"
            for i, (p, r) in enumerate(valid)
        )
        judge_prompt = (
            f"You are an expert judge. Multiple AI models answered the same question.\n"
            f"Pick the BEST answer (most accurate, complete, and helpful).\n"
            f"Return ONLY the text of the best answer, unchanged.\n\n"
            f"Original question:\n{messages[-1].get('content','')[:300]}\n\n"
            f"{labeled}"
        )
        return llm_chat(
            [{"role": "user", "content": judge_prompt}],
            task="reasoning", max_tokens=max_tokens + 200,
        )

    else:  # synthesis (default)
        if len(valid) == 1:
            return valid[0][1]
        labeled = "\n\n".join(
            f"[Model {i+1} — {p}]:\n{r[:800]}"
            for i, (p, r) in enumerate(valid)
        )
        synth_prompt = (
            f"Multiple AI models answered the same question. "
            f"Synthesise their responses into one comprehensive, accurate answer. "
            f"Resolve any contradictions by reasoning carefully. "
            f"Do not mention that multiple models were used — just give the best answer.\n\n"
            f"Question: {messages[-1].get('content','')[:300]}\n\n"
            f"Responses:\n{labeled}"
        )
        return llm_chat(
            [{"role": "user", "content": synth_prompt}],
            task="reasoning", max_tokens=max_tokens + 300,
        )
