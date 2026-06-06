"""Git skills — log, status, blame, branch, PR creation."""
from __future__ import annotations

import subprocess
from pathlib import Path

from myassistant.core.registry import skill
from myassistant.core.config import settings

_WORKSPACE = getattr(settings, "myassistant_repo_workspace", str(Path.home() / "repos"))


def _git(repo: str, *args, timeout: int = 20) -> str:
    cwd = str(Path(_WORKSPACE) / repo)
    r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=timeout)
    return (r.stdout + r.stderr)[:4000]


@skill(name="git_log", description="Show recent git commits",
       parameters={"repo": {"type": "string"},
                   "n": {"type": "integer", "default": 20},
                   "author": {"type": "string", "default": ""},
                   "file": {"type": "string", "default": ""}},
       requires=[])
def git_log(repo: str, n: int = 20, author: str = "", file: str = "") -> str:
    args = ["log", f"--max-count={n}", "--oneline",
            "--format=%h %ad %an │ %s", "--date=short"]
    if author:
        args += [f"--author={author}"]
    if file:
        args += ["--", file]
    return _git(repo, *args)


@skill(name="git_status", description="Show git status and staged changes",
       parameters={"repo": {"type": "string"}}, requires=[])
def git_status(repo: str) -> str:
    return _git(repo, "status", "-sb") + "\n" + _git(repo, "diff", "--stat", "HEAD")


@skill(name="git_blame", description="Show git blame for a file section",
       parameters={"repo": {"type": "string"},
                   "file": {"type": "string"},
                   "start_line": {"type": "integer", "default": 1},
                   "end_line": {"type": "integer", "default": 30}},
       requires=[])
def git_blame(repo: str, file: str, start_line: int = 1, end_line: int = 30) -> str:
    return _git(repo, "blame", f"-L{start_line},{end_line}", "--date=short", file)


@skill(name="git_show_commit", description="Show full details of a specific commit",
       parameters={"repo": {"type": "string"}, "sha": {"type": "string"}},
       requires=[])
def git_show_commit(repo: str, sha: str) -> str:
    return _git(repo, "show", "--stat", sha) + "\n" + _git(repo, "show", "-U3", sha)[:2000]


@skill(name="git_list_branches", description="List all branches in a repo",
       parameters={"repo": {"type": "string"}}, requires=[])
def git_list_branches(repo: str) -> str:
    return _git(repo, "branch", "-a", "--sort=-committerdate")


@skill(name="git_checkout", description="Checkout a branch in a repo",
       parameters={"repo": {"type": "string"}, "branch": {"type": "string"}},
       requires=[], sensitive=True)
def git_checkout(repo: str, branch: str) -> str:
    return _git(repo, "checkout", branch)


@skill(name="git_commit", description="Stage all changes and create a commit",
       parameters={"repo": {"type": "string"}, "message": {"type": "string"},
                   "dry_run": {"type": "boolean", "default": False}},
       requires=[], sensitive=True)
def git_commit(repo: str, message: str, dry_run: bool = False) -> str:
    if dry_run:
        return "DRY RUN: would run git add -A && git commit -m '{}' in {}".format(message, repo)
    _git(repo, "add", "-A")
    return _git(repo, "commit", "-m", message)


@skill(name="git_push", description="Push a branch to origin",
       parameters={"repo": {"type": "string"},
                   "branch": {"type": "string", "default": "HEAD"},
                   "dry_run": {"type": "boolean", "default": False}},
       requires=[], sensitive=True)
def git_push(repo: str, branch: str = "HEAD", dry_run: bool = False) -> str:
    if dry_run:
        return f"DRY RUN: would push {branch} in {repo} to origin"
    return _git(repo, "push", "origin", branch, timeout=60)
