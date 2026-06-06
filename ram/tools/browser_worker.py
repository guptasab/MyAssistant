"""Long-running worker that owns a logged-in Chromium profile and processes
queued Google Voice / DoorDash / UberEats jobs from data/*_queue/.

Run separately:  python -m ram.tools.browser_worker
First run will pop a Chromium window — log in to voice.google.com,
doordash.com, etc., then close. Sessions persist in data/browser_profile/.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import time
from pathlib import Path

from loguru import logger

from ram.core.config import settings


PROFILE = settings.ram_data_dir / "browser_profile"


async def _run():
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("playwright not installed. pip install playwright && playwright install chromium")
        return

    PROFILE.mkdir(exist_ok=True)
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            str(PROFILE), headless=False, args=["--start-maximized"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        logger.info("Browser worker ready. Ensure you're logged in at voice.google.com, doordash.com, etc.")

        while True:
            for kind, q in [("gvoice", settings.ram_data_dir / "gvoice_queue"),
                            ("order", settings.ram_data_dir / "order_queue")]:
                if not q.exists():
                    continue
                for jp in sorted(q.glob("*.json")):
                    try:
                        job = json.loads(jp.read_text())
                        await _process(page, kind, job)
                        done = q / "done"
                        done.mkdir(exist_ok=True)
                        shutil.move(str(jp), str(done / jp.name))
                    except Exception as e:
                        logger.exception(f"job {jp} failed: {e}")
            await asyncio.sleep(3)


async def _process(page, kind: str, job: dict):
    """Demo stubs — flesh out the actual selectors for each site as needed."""
    logger.info(f"processing {kind}: {job}")
    if kind == "gvoice":
        await page.goto("https://voice.google.com/u/0/messages")
        # ... locate compose, type recipient + message, send. Site-specific.
    elif kind == "order":
        platform = job["payload"].get("platform") if "payload" in job else job.get("platform")
        if platform == "doordash":
            await page.goto("https://www.doordash.com/")
        elif platform == "ubereats":
            await page.goto("https://www.ubereats.com/")
        # ... search restaurant, add items, checkout. Site-specific.


if __name__ == "__main__":
    asyncio.run(_run())
