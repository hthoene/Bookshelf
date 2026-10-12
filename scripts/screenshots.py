"""Regenerate the README screenshots in docs/screenshots/.

pip install playwright            # uses an installed Chrome/Edge, or: playwright install chromium
BOOKSHELF_DATA_DIR=./data-shots python -m bookshelf serve --port 8765
python scripts/dev_seed.py --url http://localhost:8765
python scripts/screenshots.py --url http://localhost:8765 [--channel msedge]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

OUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
USERNAME, PASSWORD = "demo", "demo1234"


def login(page: Page, base: str) -> None:
    page.goto(f"{base}/login")
    page.fill("#username", USERNAME)
    page.fill("#password", PASSWORD)
    page.click("button:has-text('Log in')")
    page.wait_for_url(f"{base}/")


def shoot(page: Page, name: str, *, full_page: bool = False) -> None:
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(300)  # let transitions settle
    page.screenshot(path=OUT / f"{name}.png", full_page=full_page)
    print(f"saved {name}.png")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8765")
    parser.add_argument("--channel", default=None, help="e.g. msedge or chrome")
    args = parser.parse_args()
    base = args.url.rstrip("/")
    OUT.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=args.channel)
        desktop = {"viewport": {"width": 1280, "height": 820}, "device_scale_factor": 2}
        mobile = {
            "viewport": {"width": 390, "height": 844},
            "device_scale_factor": 3,
            "is_mobile": True,
            "has_touch": True,
        }

        for scheme in ("light", "dark"):
            page = browser.new_context(color_scheme=scheme, **desktop).new_page()
            login(page, base)
            shoot(page, f"library-{scheme}")
            if scheme == "light":
                page.click("a.book-card:has-text('Moby-Dick')")
                shoot(page, "book")
                page.goto(f"{base}/stats")
                shoot(page, "stats")
                page.goto(f"{base}/settings")
                shoot(page, "settings")
            page.context.close()

        page = browser.new_context(color_scheme="dark", **mobile).new_page()
        login(page, base)
        shoot(page, "mobile-library")
        page.click("a.book-card:has-text('Dracula')")
        shoot(page, "mobile-book")
        page.goto(f"{base}/stats")
        shoot(page, "mobile-stats")
        page.context.close()

        page = browser.new_context(color_scheme="light", **desktop).new_page()
        page.goto(f"{base}/login")
        shoot(page, "login")
        browser.close()


if __name__ == "__main__":
    main()
