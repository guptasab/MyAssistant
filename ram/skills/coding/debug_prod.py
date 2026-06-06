"""debug_prod — composite "Hey Ram, debug the last call in prod" skill.

Orchestration:
  1. Detect which services are configured (Lambda names, CW log groups, ECS)
  2. Pull recent errors from CloudWatch (last 30 min by default)
  3. Find X-Ray trace IDs that have errors
  4. Parse stack traces → identify file + line numbers
  5. If a local repo is available, read relevant source files
  6. Call LLM (task="code") for root-cause analysis + fix proposal
  7. Optionally stage a draft GitHub issue with the analysis
"""
from __future__ import annotations

import json
import re
import time
from typing import Optional

from loguru import logger

from ram.core.registry import skill
from ram.core.config import settings
from ram.core.llm import llm_chat


_REQUIRES_AWS = ["aws_access_key_id", "aws_secret_access_key"]

# Heuristics to extract service/file from a stack trace line
_TRACE_FILE_RE = re.compile(r'File "([^"]+)", line (\d+)')
_JS_TRACE_RE   = re.compile(r'at \S+ \(([^:)]+):(\d+):\d+\)')


def _extract_file_refs(text: str) -> list[tuple[str, int]]:
    refs = []
    for m in _TRACE_FILE_RE.finditer(text):
        refs.append((m.group(1), int(m.group(2))))
    for m in _JS_TRACE_RE.finditer(text):
        refs.append((m.group(1), int(m.group(2))))
    return refs[:10]


@skill(
    name="debug_prod",
    description=(
        "Debug the most recent production error. "
        "Pulls CloudWatch logs + X-Ray traces, reads relevant source files, "
        "and returns a root-cause analysis with a fix suggestion. "
        "Use for: 'debug the last call in prod', 'what broke in prod?', 'production error'."
    ),
    parameters={
        "service": {
            "type": "string", "default": "",
            "description": "Lambda function name or CW log group prefix (auto-detect if empty)",
        },
        "minutes": {
            "type": "integer", "default": 30,
            "description": "How far back to look (minutes)",
        },
        "repo": {
            "type": "string", "default": "",
            "description": "Local repo name under workspace for source context",
        },
        "open_issue": {
            "type": "boolean", "default": False,
            "description": "Open a draft GitHub issue with the analysis",
        },
    },
    requires=[],  # AWS keys optional — gracefully degrades
)
def debug_prod(service: str = "", minutes: int = 30,
               repo: str = "", open_issue: bool = False) -> str:
    sections: list[str] = []

    # ─── 1. Gather error logs ──────────────────────────────────────────────
    error_text = ""
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        try:
            from ram.skills.aws.cloudwatch import cw_list_groups, cw_filter_logs, cw_error_summary
            from ram.skills.aws.lambda_skill import lambda_list, lambda_find_errors

            # Auto-detect: list Lambda functions, pick first one if service not specified
            if not service:
                fn_list = lambda_list(limit=10)
                fn_names = [l.split()[0] for l in fn_list.splitlines() if l.strip()]
                if fn_names:
                    service = fn_names[0]
                    sections.append(f"🔍 Auto-detected Lambda function: **{service}**")

            if service:
                error_text = lambda_find_errors(service, minutes=minutes)
                sections.append(f"### CloudWatch errors (last {minutes}min)\n```\n{error_text[:1500]}\n```")
            else:
                sections.append("⚠️ No Lambda functions found. Set AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY "
                                 "and ensure the IAM role has CloudWatch read access.")
        except Exception as e:
            sections.append(f"⚠️ CloudWatch fetch failed: {e}")

    # ─── 2. X-Ray traces ──────────────────────────────────────────────────
    xray_text = ""
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        try:
            from ram.skills.aws.xray import xray_traces
            xray_text = xray_traces(service=service, minutes=minutes, errors_only=True)
            if not xray_text.startswith("(no "):
                sections.append(f"### X-Ray error traces\n```\n{xray_text[:800]}\n```")
        except Exception as e:
            logger.debug(f"xray optional: {e}")

    # ─── 3. Source context ────────────────────────────────────────────────
    source_snippets: dict[str, str] = {}
    if error_text and repo:
        try:
            from ram.skills.coding.repo import repo_read
            refs = _extract_file_refs(error_text)
            for fpath, lineno in refs[:4]:
                # Normalise absolute container path → repo-relative
                rel = re.sub(r"^.*?/(?:app|src|lambda)/", "", fpath)
                start = max(1, lineno - 10)
                end = lineno + 20
                snippet = repo_read(repo, rel, start_line=start, end_line=end)
                if "not found" not in snippet:
                    source_snippets[rel] = snippet
                    sections.append(f"### Source: {rel} (around line {lineno})\n```\n{snippet}\n```")
        except Exception as e:
            logger.debug(f"source read optional: {e}")

    if not error_text and not xray_text:
        sections.append("✅ No errors found in the last window — prod looks clean!")
        return "\n\n".join(sections)

    # ─── 4. LLM root-cause analysis ───────────────────────────────────────
    context_for_llm = "\n\n".join([
        f"Error logs:\n{error_text[:2000]}" if error_text else "",
        f"X-Ray traces:\n{xray_text[:800]}" if xray_text else "",
        "\n".join(f"File {k}:\n{v[:600]}" for k, v in source_snippets.items()),
    ]).strip()

    prompt = f"""You are an expert SRE debugging a production incident.

Below is evidence from AWS CloudWatch and X-Ray.
Provide:
1. **Root cause** — 2-3 sentences
2. **Affected service/function** — name it
3. **Fix suggestion** — concrete code change or config change (show the diff if possible)
4. **Prevention** — one line on how to prevent this class of bug

Evidence:
{context_for_llm[:3500]}"""

    try:
        analysis = llm_chat(
            [{"role": "user", "content": prompt}],
            task="code", max_tokens=800
        )
    except Exception as e:
        analysis = f"(LLM analysis unavailable: {e})"

    sections.append(f"### 🤖 Root-Cause Analysis\n{analysis}")

    # ─── 5. Open GitHub issue (optional) ──────────────────────────────────
    if open_issue and settings.github_token:
        try:
            from ram.skills.github_skill import github_create_issue
            repo_full = getattr(settings, "github_default_repo", "")
            if repo_full:
                title = f"[auto] Production error in {service or 'unknown'}"
                body = "\n\n".join(sections)
                result = github_create_issue(repo=repo_full, title=title, body=body[:6000],
                                             labels=["bug", "production"])
                sections.append(f"📌 {result}")
        except Exception as e:
            sections.append(f"⚠️ Could not open GitHub issue: {e}")

    return "\n\n".join(sections)
