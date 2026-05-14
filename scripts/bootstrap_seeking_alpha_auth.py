from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from webui.seeking_alpha import (  # noqa: E402
    SEEKING_ALPHA_COOKIES_ENV,
    SEEKING_ALPHA_LOGIN_URL,
    SEEKING_ALPHA_SCREEN_URL,
    apply_stealth_init_script,
    build_browser_context_kwargs,
    resolve_cookies_path,
    sync_playwright,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap a minimal Seeking Alpha cookie secret for server-side API access.")
    parser.add_argument(
        "--output",
        default=os.getenv(SEEKING_ALPHA_COOKIES_ENV, "").strip() or "secrets/seeking_alpha_cookies.json",
        help=f"Path to write the Seeking Alpha cookie secret. Defaults to ${SEEKING_ALPHA_COOKIES_ENV} or secrets/seeking_alpha_cookies.json.",
    )
    return parser.parse_args()


def main() -> int:
    if sync_playwright is None:
        raise SystemExit("Playwright is not installed in this environment.")

    args = parse_args()
    output_path = resolve_cookies_path(args.output)
    if output_path is None:
        raise SystemExit("Could not resolve output path for Seeking Alpha cookie secret.")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False, slow_mo=150)
        context = browser.new_context(**build_browser_context_kwargs(None))
        apply_stealth_init_script(context)
        page = context.new_page()
        page.goto(SEEKING_ALPHA_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        print("Log into Seeking Alpha in the opened browser, open the HC-top screener, then press Enter here to save the cookie secret.")
        input()
        page.goto(SEEKING_ALPHA_SCREEN_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        cookie_map = {cookie["name"]: cookie["value"] for cookie in context.cookies() if cookie.get("name") and cookie.get("value")}
        output_path.write_text(
            json.dumps(
                {
                    "source": "playwright_bootstrap",
                    "created_at": datetime.now().astimezone().isoformat(),
                    "screen_url": SEEKING_ALPHA_SCREEN_URL,
                    "cookies": cookie_map,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        context.close()
        browser.close()

    os.chmod(output_path, 0o600)
    print(f"Saved Seeking Alpha cookie secret to {output_path}")
    print(f"Set {SEEKING_ALPHA_COOKIES_ENV}={output_path} on the server.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
