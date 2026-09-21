"""Capture dashboard screenshots for the docs, in light and dark themes.

The dashboard follows prefers-color-scheme; Playwright emulates it, so each image shows the
real theme. Output: docs/assets/screenshots/<section>-<light|dark>.png
The docs show the matching one via MkDocs Material's #only-light / #only-dark.

  .venv/bin/pip install -e ".[docs]" && .venv/bin/python -m playwright install chromium
  .venv/bin/python scripts/screenshot_dashboard.py [--url http://127.0.0.1:8765]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "assets" / "screenshots"

# section name -> CSS selector (screenshot of that element)
SECTIONS = {
    "kpis": "#kpis",
    "value-and-holdings": "main > section:has(#chart)",
    "decisions": "main > section:has(#decisions)",
    "runs": "main > section:has(#runs)",
    "fills-and-llm": "main > section:has(#fills)",
}


def capture(url: str, scheme: str, page) -> list[Path]:
    page.emulate_media(color_scheme=scheme)
    page.goto(url, wait_until="networkidle")
    page.wait_for_selector("#runs table", timeout=15000)
    page.wait_for_timeout(500)  # let the chart lay out
    shots = []

    p = OUT / f"overview-{scheme}.png"
    page.screenshot(path=p)                       # first screen as a user sees it
    shots.append(p)

    for name, sel in SECTIONS.items():
        p = OUT / f"{name}-{scheme}.png"
        page.locator(sel).first.screenshot(path=p)
        shots.append(p)

    # Claude's reasoning drawer for the most recent run that has a transcript
    row = page.locator("#runs tr[data-run]").first
    if row.count():
        row.click()
        page.wait_for_selector("#drawer.open .step", timeout=10000)
        page.wait_for_timeout(400)
        p = OUT / f"transcript-{scheme}.png"
        page.locator("#drawer").screenshot(path=p)
        shots.append(p)
        page.keyboard.press("Escape")
    return shots


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for scheme in ("light", "dark"):
            ctx = browser.new_context(viewport={"width": 1280, "height": 900}, device_scale_factor=1.5)
            page = ctx.new_page()
            for p in capture(args.url, scheme, page):
                print(p.relative_to(ROOT))
            ctx.close()
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
