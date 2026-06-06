"""Writing style learning and smart email drafting.

MyAssistant studies your sent emails to learn your personal writing style, then
generates email drafts that sound like *you* — not like a generic AI.

How it works:
  1. ``learn_style()`` is called periodically (or on demand) to pull 
     sent emails and build a style profile stored in vector_memory.
  2. The style profile captures: tone, formality, avg sentence length,
     sign-off patterns, salutation patterns, and topic-specific examples.
  3. ``draft_email()`` retrieves the style profile and a few example emails,
     then asks the LLM to write a new draft in that style.
  4. ``draft_reply()`` works the same but includes the original thread.

This is what separates MyAssistant from generic AI — your emails sound like *you*.
"""
from __future__ import annotations

import json
import time
from typing import Optional

from loguru import logger

from myassistant.core.registry import skill
from myassistant.core.memory import db
from myassistant.core.llm import llm_chat


_STYLE_KEY = "email_style_profile"


def _load_style_profile() -> dict:
    """Load user's writing style profile from memory."""
    try:
        from myassistant.core.vector_memory import query as vmem_query
        results = vmem_query(_STYLE_KEY, top_k=1)
        if results:
            return json.loads(results[0]["text"])
    except Exception:
        pass
    return {}


def _save_style_profile(profile: dict) -> None:
    """Save the style profile to vector memory."""
    try:
        from myassistant.core.vector_memory import upsert as vmem_upsert
        vmem_upsert(_STYLE_KEY, json.dumps(profile), metadata={"kind": "style_profile"})
    except Exception as e:
        logger.debug(f"style profile save: {e}")


@skill(
    name="learn_email_style",
    description=(
        "Analyse recent sent emails to learn the user's personal writing style. "
        "Run this after connecting an email account, or say 'learn my email style'."
    ),
    parameters={"max_samples": {"type": "integer", "default": 30}},
    requires=[],
)
def learn_email_style(max_samples: int = 30) -> str:
    """Analyse sent emails and build a personal style profile."""
    samples: list[str] = []

    # Collect from Gmail accounts
    from myassistant.core.accounts import list_accounts
    for acct in list_accounts(kind="gmail"):
        try:
            from myassistant.core.accounts import gmail_service_for
            from myassistant.skills.gmail_skill import _headers, _decode_body
            svc = gmail_service_for(acct.email)
            if not svc:
                continue
            res = svc.users().messages().list(
                userId="me", labelIds=["SENT"], maxResults=max_samples
            ).execute()
            for item in (res.get("messages") or []):
                try:
                    m = svc.users().messages().get(
                        userId="me", id=item["id"], format="full"
                    ).execute()
                    body = _decode_body(m.get("payload", {}))
                    if len(body.strip()) > 50:
                        samples.append(body[:600])
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Style learn Gmail {acct.email}: {e}")

    if not samples:
        return ("No sent emails found. Connect a Gmail account first "
                "(Settings → Channels → Connect Gmail).")

    # Ask LLM to build style profile
    sample_text = "\n\n---\n\n".join(samples[:20])
    prompt = f"""Analyse these sent emails and extract a writing style profile.
Return JSON with these fields:
{{
  "tone": "formal|semi-formal|casual",
  "avg_sentence_length": "short|medium|long",
  "salutation_patterns": ["Hi <name>,", "Hello,"],
  "sign_off_patterns": ["Best,", "Thanks,", "Cheers,"],
  "uses_contractions": true|false,
  "uses_emojis": true|false,
  "bullet_style": true|false,
  "paragraph_count": "1-2|2-4|4+",
  "personality_notes": "e.g. direct and concise, warm opener, action-first"
}}

Emails:
{sample_text[:4000]}"""

    try:
        profile = llm_chat([{"role": "user", "content": prompt}], task="fast", max_tokens=400)
        # Parse JSON from response
        import re
        match = re.search(r'\{.*\}', profile, re.DOTALL)
        if match:
            profile_dict = json.loads(match.group())
            profile_dict["sample_count"] = len(samples)
            profile_dict["last_updated"] = time.strftime("%Y-%m-%d")
            # Store a few example openings and closings
            profile_dict["example_snippets"] = [s[:150] for s in samples[:3]]
            _save_style_profile(profile_dict)
            return (f"✅ Email style profile built from {len(samples)} sent emails.\n"
                    f"Tone: {profile_dict.get('tone', '?')}, "
                    f"Sign-offs: {profile_dict.get('sign_off_patterns', [])}")
    except Exception as e:
        logger.debug(f"Style profile build: {e}")

    return f"Analysed {len(samples)} emails but could not parse the style profile."


@skill(
    name="draft_email",
    description=(
        "Draft an email in the user's personal writing style. "
        "Use for: 'draft an email to X about Y', 'write an email following up on Z'."
    ),
    parameters={
        "to":        {"type": "string", "description": "Recipient name or email"},
        "subject":   {"type": "string"},
        "intent":    {"type": "string", "description": "What the email should accomplish"},
        "context":   {"type": "string", "default": "",
                      "description": "Additional context, e.g. prior conversation"},
        "tone_override": {"type": "string", "default": "",
                          "description": "Override the default style: formal|casual|direct|warm"},
    },
    requires=[],
)
def draft_email(to: str, subject: str, intent: str,
                context: str = "", tone_override: str = "") -> str:
    """Write an email draft in the user's learned style."""
    profile = _load_style_profile()

    # Build style description
    if profile:
        style_desc = (
            f"Writing style: {profile.get('tone', 'professional')}, "
            f"sentences: {profile.get('avg_sentence_length', 'medium')} length, "
            f"sign-off: {profile.get('sign_off_patterns', ['Best,'])[0]}, "
            f"contractions: {'yes' if profile.get('uses_contractions') else 'no'}. "
            f"Personality: {profile.get('personality_notes', 'professional and concise')}."
        )
        if tone_override:
            style_desc += f" Override tone to: {tone_override}."
        examples = profile.get("example_snippets", [])
        example_block = "\n\n".join(examples[:2]) if examples else ""
    else:
        style_desc = (
            "Writing style: professional, clear, concise. "
            "No style profile yet — will build one after connecting email."
        )
        example_block = ""

    context_clause = f"\n\nContext:\n{context}" if context else ""
    example_clause = f"\n\nExamples of this user's style:\n{example_block}" if example_block else ""

    prompt = f"""Write an email draft. Match the user's personal writing style exactly.

To: {to}
Subject: {subject}
Purpose: {intent}{context_clause}

{style_desc}{example_clause}

Write ONLY the email body (no subject line). Include greeting and sign-off."""

    draft = llm_chat([{"role": "user", "content": prompt}], task="draft", max_tokens=500)
    return f"**Draft email to {to}**\nSubject: {subject}\n\n{draft}"


@skill(
    name="draft_reply",
    description=(
        "Draft a reply to an email in the user's personal style. "
        "Use when the user says 'reply to this', 'write a response to X', "
        "or 'respond to that email about Y'."
    ),
    parameters={
        "original_email":  {"type": "string", "description": "The email to reply to"},
        "intent":          {"type": "string",
                            "description": "What the reply should accomplish or say"},
        "tone_override":   {"type": "string", "default": ""},
    },
    requires=[],
)
def draft_reply(original_email: str, intent: str, tone_override: str = "") -> str:
    """Write a reply to an email in the user's learned style."""
    profile = _load_style_profile()

    style_desc = ""
    if profile:
        style_desc = (
            f"Tone: {profile.get('tone', 'professional')}. "
            f"Sign-off: {profile.get('sign_off_patterns', ['Best,'])[0]}. "
            f"{profile.get('personality_notes', '')}."
        )
        if tone_override:
            style_desc += f" Override: {tone_override}."

    prompt = f"""Write a reply to this email. Match the user's style.
{style_desc}

Original email:
{original_email[:1500]}

Reply intent: {intent}

Write ONLY the reply body (no subject). Include greeting and sign-off."""

    draft = llm_chat([{"role": "user", "content": prompt}], task="draft", max_tokens=400)
    return f"**Draft reply:**\n\n{draft}"


@skill(
    name="improve_draft",
    description=(
        "Improve an existing email draft — fix tone, clarity, grammar, or length. "
        "Use when the user says 'this sounds too formal', 'make it shorter', 'fix my email'."
    ),
    parameters={
        "draft":       {"type": "string", "description": "The draft to improve"},
        "instruction": {"type": "string",
                        "description": "What to improve: shorter, warmer, more direct, fix grammar, etc."},
    },
    requires=[],
)
def improve_draft(draft: str, instruction: str) -> str:
    """Improve an existing email draft."""
    profile = _load_style_profile()
    style_hint = f"Match this writing style: {profile.get('personality_notes', 'professional and concise')}." if profile else ""

    prompt = f"""Improve this email draft.
Instruction: {instruction}
{style_hint}

Original draft:
{draft}

Return the improved version only."""

    return llm_chat([{"role": "user", "content": prompt}], task="draft", max_tokens=400)
