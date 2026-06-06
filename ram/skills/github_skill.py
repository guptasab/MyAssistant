"""GitHub helper — list PRs, issues, comment, create issue."""
from __future__ import annotations

from ram.core.config import settings
from ram.core.registry import skill


def _gh():
    if not settings.github_token:
        return None
    try:
        from github import Github
        return Github(settings.github_token)
    except ImportError:
        return None


@skill(name="github_my_prs", description="List my open PRs (review or authored).",
       requires=["github_token"])
def github_my_prs() -> str:
    g = _gh()
    if not g:
        return "ERROR: github not configured"
    me = g.get_user().login
    prs = g.search_issues(f"is:open is:pr involves:{me}")
    out = [f"#{p.number} {p.repository.full_name}  {p.title[:60]}" for p in prs[:25]]
    return "\n".join(out) or "(none)"


@skill(name="github_create_issue",
       description="Open a GitHub issue in 'owner/repo' with a title + body.",
       requires=["github_token"], sensitive=True)
def github_create_issue(repo: str, title: str, body: str = "") -> str:
    g = _gh()
    if not g:
        return "ERROR: github not configured"
    r = g.get_repo(repo)
    iss = r.create_issue(title=title, body=body)
    return f"created {iss.html_url}"


@skill(name="github_comment",
       description="Comment on an issue or PR. number = issue/PR number.",
       requires=["github_token"], sensitive=True)
def github_comment(repo: str, number: int, body: str) -> str:
    g = _gh()
    if not g:
        return "ERROR: github not configured"
    r = g.get_repo(repo)
    iss = r.get_issue(number)
    iss.create_comment(body)
    return "commented"
