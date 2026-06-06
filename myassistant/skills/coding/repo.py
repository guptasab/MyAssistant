"""Repo navigation tools — read local or remote code without mutation."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from myassistant.core.registry import skill
from myassistant.core.config import settings

_WORKSPACE = getattr(settings, "myassistant_repo_workspace", os.path.expanduser("~/repos"))
_BINARY_EXTS = {".pyc", ".so", ".dll", ".exe", ".png", ".jpg", ".jpeg", ".gif",
                ".ico", ".zip", ".tar", ".gz", ".bin", ".db", ".sqlite"}


def _safe_path(repo: str, rel: str = "") -> Path:
    base = Path(_WORKSPACE) / repo
    if rel:
        p = (base / rel).resolve()
        if not str(p).startswith(str(base.resolve())):
            raise ValueError("path traversal blocked")
        return p
    return base


@skill(name="repo_clone", description="Clone a Git repository into the workspace",
       parameters={"url": {"type": "string", "description": "Git URL"},
                   "name": {"type": "string", "description": "Local folder name (optional)"}},
       requires=[], sensitive=False)
def repo_clone(url: str, name: str = "") -> str:
    dest = Path(_WORKSPACE) / (name or url.split("/")[-1].replace(".git", ""))
    if dest.exists():
        return f"already exists at {dest}"
    os.makedirs(_WORKSPACE, exist_ok=True)
    r = subprocess.run(["git", "clone", "--depth", "50", url, str(dest)],
                       capture_output=True, text=True, timeout=120)
    if r.returncode:
        return f"CLONE FAILED:\n{r.stderr[:800]}"
    return f"cloned to {dest}"


@skill(name="repo_file_tree", description="List directory tree of a repo",
       parameters={"repo": {"type": "string"},
                   "subdir": {"type": "string", "default": ""},
                   "depth": {"type": "integer", "default": 3}},
       requires=[])
def repo_file_tree(repo: str, subdir: str = "", depth: int = 3) -> str:
    base = _safe_path(repo, subdir)
    if not base.exists():
        return f"not found: {base}"
    lines = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        level = Path(root).relative_to(base).parts.__len__()
        if level >= depth:
            dirs.clear()
        indent = "  " * level
        lines.append(f"{indent}{Path(root).name}/")
        for f in sorted(files)[:60]:
            lines.append(f"{indent}  {f}")
    return "\n".join(lines[:300])


@skill(name="repo_read", description="Read a file from a cloned repo",
       parameters={"repo": {"type": "string"},
                   "path": {"type": "string"},
                   "start_line": {"type": "integer", "default": 1},
                   "end_line": {"type": "integer", "default": 200}},
       requires=[])
def repo_read(repo: str, path: str, start_line: int = 1, end_line: int = 200) -> str:
    p = _safe_path(repo, path)
    if not p.exists():
        return f"file not found: {p}"
    if p.suffix in _BINARY_EXTS:
        return f"binary file ({p.suffix}) — cannot display"
    lines = p.read_text(errors="replace").splitlines()
    sl = max(0, start_line - 1)
    el = min(len(lines), end_line)
    numbered = [f"{sl+i+1:4}: {ln}" for i, ln in enumerate(lines[sl:el])]
    header = f"--- {repo}/{path} ({len(lines)} lines total, showing {sl+1}-{el}) ---"
    return header + "\n" + "\n".join(numbered)


@skill(name="repo_grep", description="Grep for a pattern in a repo",
       parameters={"repo": {"type": "string"},
                   "pattern": {"type": "string"},
                   "path": {"type": "string", "default": ""},
                   "case_sensitive": {"type": "boolean", "default": False}},
       requires=[])
def repo_grep(repo: str, pattern: str, path: str = "", case_sensitive: bool = False) -> str:
    base = _safe_path(repo, path)
    flags = [] if case_sensitive else ["-i"]
    r = subprocess.run(
        ["grep", "-rn", "--include=*.py", "--include=*.ts", "--include=*.js",
         "--include=*.go", "--include=*.java", "--include=*.rb",
         *flags, pattern, str(base)],
        capture_output=True, text=True, timeout=20)
    out = r.stdout[:4000] or r.stderr[:400] or "(no matches)"
    return out


@skill(name="repo_diff", description="Show diff between two refs in a repo",
       parameters={"repo": {"type": "string"},
                   "ref1": {"type": "string", "default": "HEAD~1"},
                   "ref2": {"type": "string", "default": "HEAD"},
                   "path": {"type": "string", "default": ""}},
       requires=[])
def repo_diff(repo: str, ref1: str = "HEAD~1", ref2: str = "HEAD", path: str = "") -> str:
    base = _safe_path(repo)
    cmd = ["git", "-C", str(base), "diff", "--stat", ref1, ref2]
    if path:
        cmd += ["--", path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    stat = r.stdout[:600]
    cmd2 = ["git", "-C", str(base), "diff", ref1, ref2, "-U3"]
    if path:
        cmd2 += ["--", path]
    r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=20)
    return (stat + "\n" + r2.stdout[:3000]).strip() or r.stderr[:400]
