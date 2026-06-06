"""Print helper — sends a file/text to the default system printer (Windows lpr/mspaint fallback).

Wrapped behind sensitive=True since it produces physical output.
"""
from __future__ import annotations

import os
import platform
import subprocess
import tempfile
from pathlib import Path

from myassistant.core.registry import skill


@skill(
    name="print_text",
    description="Print plain text to the default system printer.",
    sensitive=True,
)
def print_text(text: str, title: str = "Ollie") -> str:
    f = Path(tempfile.gettempdir()) / f"ollie_{title.replace(' ','_')}.txt"
    f.write_text(text, encoding="utf-8")
    try:
        if platform.system() == "Windows":
            os.startfile(str(f), "print")  # type: ignore[attr-defined]
        else:
            subprocess.run(["lpr", str(f)], check=False)
        return f"queued: {f}"
    except Exception as e:
        return f"ERROR: {e}"
