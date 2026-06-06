"""Backup + export — zip the SQLite + data dir, optionally encrypted with vault."""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from myassistant.core.config import settings


def export_zip(out_dir: Path | None = None) -> Path:
    out = out_dir or (settings.myassistant_data_dir / "backups")
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = out / f"ollie-backup-{stamp}"
    archive = shutil.make_archive(str(base), "zip", root_dir=settings.myassistant_data_dir)
    return Path(archive)


def list_backups() -> list[Path]:
    out = settings.myassistant_data_dir / "backups"
    if not out.exists():
        return []
    return sorted(out.glob("*.zip"))
