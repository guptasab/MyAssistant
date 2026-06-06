"""Composite code review skill — review a PR or repo diff with LLM analysis."""
from __future__ import annotations

import os
from pathlib import Path

from myassistant.core.registry import skill
from myassistant.core.config import settings
from myassistant.core.llm import llm_chat


_WORKSPACE = getattr(settings, "myassistant_repo_workspace", str(Path.home() / "repos"))


@skill(
    name="code_review",
    description="Review code changes — diff, recent commit, or entire file. Returns bugs, issues, suggestions.",
    parameters={
        "repo": {"type": "string", "description": "Local repo name"},
        "ref1": {"type": "string", "default": "HEAD~1"},
        "ref2": {"type": "string", "default": "HEAD"},
        "path": {"type": "string", "default": ""},
        "focus": {"type": "string", "default": "bugs",
                  "description": "bugs | security | performance | style | all"},
    },
    requires=[],
)
def code_review(repo: str, ref1: str = "HEAD~1", ref2: str = "HEAD",
                path: str = "", focus: str = "bugs") -> str:
    from myassistant.skills.coding.repo import repo_diff
    diff = repo_diff(repo, ref1=ref1, ref2=ref2, path=path)
    if not diff.strip():
        return "(no diff to review)"

    focus_prompts = {
        "bugs": "Focus on logic errors, null-dereferences, off-by-one, and incorrect assumptions.",
        "security": "Focus on injection, auth bypasses, exposed secrets, input validation.",
        "performance": "Focus on N+1 queries, blocking I/O, unnecessary allocations, caching gaps.",
        "style": "Focus on readability, naming, dead code, and test coverage.",
        "all": "Cover bugs, security, performance, and style.",
    }
    instruction = focus_prompts.get(focus, focus_prompts["bugs"])

    prompt = f"""You are a senior code reviewer. {instruction}

Diff to review:
```
{diff[:4000]}
```

Format your response as:
## Issues Found
- **[SEVERITY]** file:line — description + suggested fix

## Summary
One paragraph summary.

Be specific and actionable. If no issues, say so."""

    return llm_chat([{"role": "user", "content": prompt}], task="code", max_tokens=1200)


@skill(
    name="explain_code",
    description="Explain what a file or function does in plain English",
    parameters={
        "repo": {"type": "string"},
        "path": {"type": "string", "description": "File path relative to repo root"},
        "start_line": {"type": "integer", "default": 1},
        "end_line": {"type": "integer", "default": 100},
    },
    requires=[],
)
def explain_code(repo: str, path: str, start_line: int = 1, end_line: int = 100) -> str:
    from myassistant.skills.coding.repo import repo_read
    code = repo_read(repo, path, start_line=start_line, end_line=end_line)
    prompt = f"Explain what this code does, its purpose, and any notable patterns:\n```\n{code[:3000]}\n```"
    return llm_chat([{"role": "user", "content": prompt}], task="code", max_tokens=600)


@skill(
    name="find_bug",
    description="Search a repo for a described bug or symptom",
    parameters={
        "repo": {"type": "string"},
        "description": {"type": "string", "description": "Bug description or error message"},
    },
    requires=[],
)
def find_bug(repo: str, description: str) -> str:
    from myassistant.skills.coding.repo import repo_grep, repo_file_tree
    # Extract keywords from description
    keywords = [w for w in description.split() if len(w) > 4 and w.isalpha()][:4]
    grep_results = []
    for kw in keywords:
        r = repo_grep(repo, kw, case_sensitive=False)
        if not r.startswith("(no matches"):
            grep_results.append(f"### {kw}\n{r[:600]}")

    context = "\n\n".join(grep_results) or "(no matching code found)"
    prompt = f"""Bug description: {description}

Relevant code found in repo:
{context[:3000]}

Where is the bug likely located? What is the fix?"""
    return llm_chat([{"role": "user", "content": prompt}], task="code", max_tokens=600)
