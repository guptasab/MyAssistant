"""Sandboxed shell execution for coding tasks.

Only allowlisted command prefixes are permitted. The user can extend the
allowlist via RAM_SHELL_ALLOWLIST (comma-separated prefixes) in .env.
"""
from __future__ import annotations

import os
import subprocess
import shlex
from pathlib import Path

from ram.core.registry import skill
from ram.core.config import settings

_WORKSPACE = getattr(settings, "ram_repo_workspace", str(Path.home() / "repos"))
_TIMEOUT = int(getattr(settings, "ram_shell_timeout", 60))

_DEFAULT_ALLOWLIST = [
    "pytest", "python -m pytest", "python -m", "python3",
    "npm test", "npm run", "npx jest", "npx",
    "go test", "go build", "go vet",
    "cargo test", "cargo build", "cargo check",
    "ls", "cat", "head", "tail", "find", "grep", "wc",
    "pip install", "pip list", "pip show",
    "git log", "git diff", "git status", "git show",
    "ruff", "flake8", "pylint", "mypy",
    "eslint", "tsc",
    "curl -s", "wget -q",
    "jq",
    "echo",
]

def _get_allowlist() -> list[str]:
    extra = getattr(settings, "ram_shell_allowlist", "")
    if extra:
        return _DEFAULT_ALLOWLIST + [x.strip() for x in extra.split(",") if x.strip()]
    return _DEFAULT_ALLOWLIST


def _is_allowed(cmd: str) -> bool:
    stripped = cmd.strip()
    for prefix in _get_allowlist():
        if stripped.startswith(prefix):
            return True
    return False


@skill(name="exec_shell",
       description="Run an allowlisted shell command in a repo working directory",
       parameters={"command": {"type": "string",
                               "description": "Shell command (must match allowlist)"},
                   "repo": {"type": "string", "default": "",
                            "description": "Repo subfolder under workspace (optional)"},
                   "timeout": {"type": "integer", "default": 60},
                   "dry_run": {"type": "boolean", "default": False}},
       requires=[], sensitive=True)
def exec_shell(command: str, repo: str = "", timeout: int = 60, dry_run: bool = False) -> str:
    if not _is_allowed(command):
        return (f"BLOCKED: '{command}' is not in the shell allowlist.\n"
                f"Allowed prefixes: {', '.join(_DEFAULT_ALLOWLIST[:12])}…\n"
                f"Add more via RAM_SHELL_ALLOWLIST env var.")
    if dry_run:
        return f"DRY RUN: would execute: {command}" + (f" in repo/{repo}" if repo else "")

    cwd = str(Path(_WORKSPACE) / repo) if repo else _WORKSPACE
    try:
        r = subprocess.run(
            command, shell=True, cwd=cwd,
            capture_output=True, text=True,
            timeout=min(timeout, _TIMEOUT)
        )
        out = r.stdout[:4000]
        err = r.stderr[:2000]
        parts = []
        if out:
            parts.append(f"STDOUT:\n{out}")
        if err:
            parts.append(f"STDERR:\n{err}")
        parts.append(f"EXIT: {r.returncode}")
        return "\n".join(parts)
    except subprocess.TimeoutExpired:
        return f"TIMEOUT: command exceeded {timeout}s"
    except Exception as e:
        return f"ERROR: {e}"


@skill(name="run_tests",
       description="Run test suite and return pass/fail summary",
       parameters={"repo": {"type": "string"},
                   "framework": {"type": "string", "default": "auto",
                                 "description": "pytest | jest | go | cargo | auto"},
                   "path": {"type": "string", "default": "."},
                   "filter": {"type": "string", "default": "",
                              "description": "Test name filter / -k expression"}},
       requires=[])
def run_tests(repo: str, framework: str = "auto", path: str = ".", filter: str = "") -> str:
    cwd = str(Path(_WORKSPACE) / repo)

    if framework == "auto":
        if (Path(cwd) / "package.json").exists():
            framework = "jest"
        elif (Path(cwd) / "go.mod").exists():
            framework = "go"
        elif (Path(cwd) / "Cargo.toml").exists():
            framework = "cargo"
        else:
            framework = "pytest"

    cmds = {
        "pytest": f"pytest {path} -v --tb=short {'- k '+filter if filter else ''}",
        "jest":   f"npx jest {path} {('--testNamePattern='+filter) if filter else ''}",
        "go":     f"go test {path}/... -v {('-run '+filter) if filter else ''}",
        "cargo":  f"cargo test {filter}",
    }
    cmd = cmds.get(framework, f"pytest {path}")
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=300)
    # Parse summary line
    lines = (r.stdout + r.stderr).splitlines()
    summary_lines = [l for l in lines if any(k in l for k in
                      ["passed", "failed", "error", "FAILED", "ok", "FAIL", "test result"])]
    out = "\n".join(summary_lines[-5:]) or lines[-1] if lines else "(no output)"
    full = (r.stdout + r.stderr)[-2000:]
    return f"=== {framework} test run (exit {r.returncode}) ===\nSUMMARY: {out}\n\n{full}"


@skill(name="run_linter",
       description="Run a linter on a repo and return issues",
       parameters={"repo": {"type": "string"},
                   "framework": {"type": "string", "default": "auto",
                                 "description": "ruff | flake8 | pylint | mypy | eslint | tsc | auto"},
                   "path": {"type": "string", "default": "."}},
       requires=[])
def run_linter(repo: str, framework: str = "auto", path: str = ".") -> str:
    cwd = str(Path(_WORKSPACE) / repo)
    if framework == "auto":
        if (Path(cwd) / "tsconfig.json").exists():
            framework = "tsc"
        elif (Path(cwd) / "package.json").exists():
            framework = "eslint"
        else:
            framework = "ruff"

    cmds = {
        "ruff":   f"ruff check {path} --output-format=concise",
        "flake8": f"flake8 {path} --max-line-length=120",
        "pylint": f"pylint {path} --score=no",
        "mypy":   f"mypy {path} --ignore-missing-imports",
        "eslint": f"npx eslint {path} --max-warnings=0",
        "tsc":    f"tsc --noEmit",
    }
    cmd = cmds.get(framework, f"ruff check {path}")
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=120)
    out = (r.stdout + r.stderr)[:3000] or "(no issues)"
    return f"=== {framework} (exit {r.returncode}) ===\n{out}"
