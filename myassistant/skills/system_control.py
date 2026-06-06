"""Local desktop control — open apps, run shell commands, drive other agents.

Examples this enables:
  - "Open VS Code on the ramp project."   -> open_app("code", args=["C:/code/ramp"])
  - "Ask Claude in VS Code to fix the build." -> send_text_to_window("Visual Studio Code", "fix the build")
  - "Verify and commit." -> run_command("git add -A && git commit -m '...'", cwd=...)

These tools touch your machine, so they're marked sensitive — the agent will
confirm before running anything destructive.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

import psutil
from loguru import logger

from myassistant.core.registry import skill


@skill(
    name="open_app",
    description="Launch an application by name or path. Optional args list is passed on the command line.",
    sensitive=True,
)
def open_app(name: str, args: list = None) -> str:
    args = args or []
    # Friendly aliases
    aliases = {
        "vscode": "code", "code": "code", "vs code": "code",
        "chrome": "chrome", "edge": "msedge", "firefox": "firefox",
        "notepad": "notepad", "explorer": "explorer", "terminal": "wt",
    }
    cmd = aliases.get(name.lower(), name)
    try:
        if sys.platform == "win32":
            subprocess.Popen([cmd, *args], shell=True)
        else:
            subprocess.Popen([cmd, *args])
        return f"launched {cmd} {' '.join(args)}"
    except Exception as e:
        return f"ERROR: {e}"


@skill(
    name="run_command",
    description=("Run a shell command and return its output (truncated). "
                 "Confirm with user before any destructive command (rm, git push, etc.)."),
    sensitive=True,
)
def run_command(command: str, cwd: str = "", timeout_seconds: int = 60) -> str:
    try:
        r = subprocess.run(
            command, shell=True, cwd=cwd or None,
            capture_output=True, text=True, timeout=timeout_seconds,
        )
        out = (r.stdout + ("\n" + r.stderr if r.stderr else "")).strip()
        return f"exit={r.returncode}\n{out[:4000]}"
    except subprocess.TimeoutExpired:
        return f"ERROR: timed out after {timeout_seconds}s"
    except Exception as e:
        return f"ERROR: {e}"


@skill(name="list_running_apps", description="List currently running top-level GUI applications.")
def list_running_apps() -> str:
    names = set()
    for p in psutil.process_iter(["name"]):
        try:
            names.add(p.info["name"])
        except Exception:
            continue
    return ", ".join(sorted(names))


@skill(
    name="focus_window",
    description="Bring a window matching a title substring to the foreground (Windows only).",
    sensitive=True,
)
def focus_window(title_contains: str) -> str:
    if sys.platform != "win32":
        return "ERROR: windows-only"
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def cb(hwnd, _):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if title_contains.lower() in buf.value.lower():
                    found.append((hwnd, buf.value))
            return True

        user32.EnumWindows(cb, 0)
        if not found:
            return "no matching window"
        hwnd, title = found[0]
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        return f"focused: {title}"
    except Exception as e:
        return f"ERROR: {e}"


@skill(
    name="type_text",
    description=("Type a string into the currently-focused window (use focus_window first). "
                 "Useful for driving other agents (e.g. typing a prompt into the Claude Code panel)."),
    sensitive=True,
)
def type_text(text: str, press_enter: bool = True) -> str:
    if sys.platform != "win32":
        return "ERROR: windows-only"
    try:
        # Use SendKeys via PowerShell — no extra dep
        import subprocess
        escaped = text.replace('"', '`"').replace("'", "''")
        ps = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            f"[System.Windows.Forms.SendKeys]::SendWait('{escaped}')"
        )
        if press_enter:
            ps += "; [System.Windows.Forms.SendKeys]::SendWait('{ENTER}')"
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
        return "ok"
    except Exception as e:
        return f"ERROR: {e}"
