from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from webui.seeking_alpha import (  # noqa: E402
    SEEKING_ALPHA_COOKIES_ENV,
    SEEKING_ALPHA_LOGIN_URL,
    SEEKING_ALPHA_SCREEN_URL,
    _looks_like_login_or_bot_gate,
    _wait_for_screener_content,
    resolve_cookies_path,
)

try:
    from cloakbrowser import launch_persistent_context as launch_cloakbrowser_context
except ImportError:  # pragma: no cover - exercised through runtime setup
    launch_cloakbrowser_context = None

SEEKING_ALPHA_EMAIL_ENV = "SEEKING_ALPHA_EMAIL"
SEEKING_ALPHA_PASSWORD_ENV = "SEEKING_ALPHA_PASSWORD"
LOGGER = logging.getLogger("bootstrap_seeking_alpha_auth")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap a minimal Seeking Alpha cookie secret for server-side API access.")
    parser.add_argument(
        "--output",
        default=os.getenv(SEEKING_ALPHA_COOKIES_ENV, "").strip() or "secrets/seeking_alpha_cookies.json",
        help=f"Path to write the Seeking Alpha cookie secret. Defaults to ${SEEKING_ALPHA_COOKIES_ENV} or secrets/seeking_alpha_cookies.json.",
    )
    parser.add_argument(
        "--email",
        default=os.getenv(SEEKING_ALPHA_EMAIL_ENV, "").strip(),
        help=f"Seeking Alpha login email. Defaults to ${SEEKING_ALPHA_EMAIL_ENV}.",
    )
    parser.add_argument(
        "--password",
        default=os.getenv(SEEKING_ALPHA_PASSWORD_ENV, ""),
        help=f"Seeking Alpha login password. Defaults to ${SEEKING_ALPHA_PASSWORD_ENV}.",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Run CloakBrowser headed for local debugging. Headless is the default.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60000,
        help="Navigation and login timeout in milliseconds. Defaults to 60000.",
    )
    parser.add_argument(
        "--debug-dir",
        default="webui_artifacts/seeking_alpha_auth_debug",
        help="Directory for bootstrap screenshots. Defaults to webui_artifacts/seeking_alpha_auth_debug.",
    )
    parser.add_argument(
        "--profile-dir",
        default="webui_artifacts/seeking_alpha_cloak_profile",
        help="Persistent CloakBrowser profile directory. Defaults to webui_artifacts/seeking_alpha_cloak_profile.",
    )
    return parser.parse_args()


def _launch_context(*, profile_dir: Path, headless: bool) -> Any:
    if launch_cloakbrowser_context is None:
        raise SystemExit("cloakbrowser is not installed. Install it with: pip install cloakbrowser")

    LOGGER.info("Launching CloakBrowser persistent context headless=%s profile=%s", headless, profile_dir)
    try:
        context = launch_cloakbrowser_context(
            str(profile_dir),
            headless=headless,
            humanize=True,
            human_preset="careful",
            locale="en-US",
            timezone="America/New_York",
            viewport={"width": 1440, "height": 2200},
        )
    except TypeError:
        context = launch_cloakbrowser_context(str(profile_dir), headless=headless)
    LOGGER.info("CloakBrowser persistent context launched")
    return context


def _save_screenshot(page: Any, debug_dir: Path, name: str) -> Path | None:
    try:
        debug_dir.mkdir(parents=True, exist_ok=True)
        path = debug_dir / f"{datetime.now().astimezone().strftime('%Y%m%d-%H%M%S')}-{name}.png"
        page.screenshot(path=str(path), full_page=True)
        LOGGER.info("Saved screenshot: %s", path)
        return path
    except Exception as exc:
        LOGGER.info("Could not save screenshot %s: %s", name, exc)
        return None


def _save_page_html(page: Any, debug_dir: Path, name: str) -> Path | None:
    try:
        debug_dir.mkdir(parents=True, exist_ok=True)
        path = debug_dir / f"{datetime.now().astimezone().strftime('%Y%m%d-%H%M%S')}-{name}.html"
        path.write_text(page.content(), encoding="utf-8")
        LOGGER.info("Saved page HTML: %s", path)
        return path
    except Exception as exc:
        LOGGER.info("Could not save page HTML %s: %s", name, exc)
        return None


def _first_visible(page: Any, selectors: tuple[str, ...], *, timeout: int) -> Any:
    last_error: Exception | None = None
    selector_timeout = max(1000, min(timeout, 5000))
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            LOGGER.info("Waiting for selector: %s", selector)
            locator.wait_for(state="visible", timeout=selector_timeout)
            LOGGER.info("Found selector: %s", selector)
            return locator
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Could not find any visible selector: {', '.join(selectors)}") from last_error


def _click_if_visible(page: Any, selectors: tuple[str, ...], *, timeout: int = 2500) -> bool:
    selector_timeout = max(500, min(timeout, 2500))
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            locator.wait_for(state="visible", timeout=selector_timeout)
            locator.click(timeout=selector_timeout)
            LOGGER.info("Clicked selector: %s", selector)
            return True
        except Exception:
            continue
    return False


def _submit_login(page: Any, *, email: str, password: str, timeout: int, debug_dir: Path) -> None:
    LOGGER.info("Looking for login form")
    password_selectors = (
        'input[type="password"]',
        'input[name="password"]',
        'input[autocomplete="current-password"]',
        'input[id*="password" i]',
    )
    email_selectors = (
        'input[type="email"]',
        'input[name="email"]',
        'input[name="username"]',
        'input[autocomplete="email"]',
        'input[id*="email" i]',
        'input[placeholder*="email" i]',
        'input[aria-label*="email" i]',
        'input[type="text"]',
    )
    try:
        email_input = _first_visible(page, email_selectors, timeout=timeout)
    except RuntimeError:
        LOGGER.info("Email field was not found on URL: %s", page.url)
        _save_screenshot(page, debug_dir, "email-field-not-found")
        _save_page_html(page, debug_dir, "email-field-not-found")
        raise
    email_input.fill(email)
    LOGGER.info("Filled email field")

    try:
        password_input = _first_visible(page, password_selectors, timeout=min(timeout, 5000))
    except RuntimeError:
        LOGGER.info("Password field not visible yet; trying two-step login continue button")
        _click_if_visible(
            page,
            (
                'button[type="submit"]',
                'button:has-text("Continue")',
                'button:has-text("Next")',
            ),
            timeout=5000,
        )
        password_input = _first_visible(page, password_selectors, timeout=timeout)
    password_input.fill(password)
    LOGGER.info("Filled password field")

    submitted = _click_if_visible(
        page,
        (
            'button[type="submit"]',
            'button:has-text("Sign in")',
            'button:has-text("Sign In")',
            'button:has-text("Log in")',
            'button:has-text("Log In")',
            'button:has-text("Login")',
        ),
        timeout=timeout,
    )
    if not submitted:
        LOGGER.info("Submit button not found; pressing Enter in password field")
        password_input.press("Enter")
    LOGGER.info("Submitted login form")


def _wait_for_authenticated_state(page: Any, *, timeout: int) -> None:
    LOGGER.info("Waiting for login navigation/network idle")
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
        LOGGER.info("Network idle reached after login submit")
    except Exception:
        LOGGER.info("Network idle wait timed out; continuing to URL/auth checks")
        pass

    try:
        page.wait_for_url(lambda url: "/account/login" not in str(url).lower(), timeout=timeout)
        LOGGER.info("Login URL changed to: %s", page.url)
    except Exception:
        LOGGER.info("Still on login URL or URL did not change before timeout; checking page body")
        body_text = ""
        try:
            body_text = page.locator("body").inner_text(timeout=3000).lower()
        except Exception:
            pass
        if any(marker in body_text for marker in ("verification code", "two-factor", "2fa", "captcha")):
            raise RuntimeError("Seeking Alpha requires an interactive verification step; cookie bootstrap cannot continue headlessly.")
        if "/account/login" in page.url.lower():
            raise RuntimeError("Seeking Alpha login did not complete before the timeout.")


def _save_cookie_secret(*, output_path: Path, context: Any) -> None:
    LOGGER.info("Collecting cookies from browser context")
    cookie_map = {cookie["name"]: cookie["value"] for cookie in context.cookies() if cookie.get("name") and cookie.get("value")}
    if not cookie_map:
        raise RuntimeError("No cookies were collected from the Seeking Alpha browser context.")

    LOGGER.info("Writing %s cookies to %s", len(cookie_map), output_path)
    output_path.write_text(
        json.dumps(
            {
                "source": "cloakbrowser_bootstrap",
                "created_at": datetime.now().astimezone().isoformat(),
                "screen_url": SEEKING_ALPHA_SCREEN_URL,
                "cookies": cookie_map,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    os.chmod(output_path, 0o600)
    LOGGER.info("Cookie secret permissions set to 0600")


def main() -> int:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
    args = parse_args()
    if not args.email:
        raise SystemExit(f"Set {SEEKING_ALPHA_EMAIL_ENV} or pass --email.")
    if not args.password:
        raise SystemExit(f"Set {SEEKING_ALPHA_PASSWORD_ENV} or pass --password.")

    output_path = resolve_cookies_path(args.output)
    if output_path is None:
        raise SystemExit("Could not resolve output path for Seeking Alpha cookie secret.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    debug_dir = Path(args.debug_dir).expanduser().resolve()
    profile_dir = Path(args.profile_dir).expanduser().resolve()
    LOGGER.info("Cookie output path: %s", output_path)
    LOGGER.info("Debug artifact directory: %s", debug_dir)
    LOGGER.info("Persistent profile directory: %s", profile_dir)

    context = None
    try:
        context = _launch_context(profile_dir=profile_dir, headless=not args.no_headless)
        page = context.new_page()
        LOGGER.info("Opening login page: %s", SEEKING_ALPHA_LOGIN_URL)
        page.goto(SEEKING_ALPHA_LOGIN_URL, wait_until="domcontentloaded", timeout=args.timeout)
        LOGGER.info("Login page loaded: %s", page.url)
        _save_screenshot(page, debug_dir, "login-loaded")
        _click_if_visible(page, ('button:has-text("Accept")', 'button:has-text("I agree")', '[data-testid*="accept" i]'))
        _submit_login(page, email=args.email, password=args.password, timeout=args.timeout, debug_dir=debug_dir)
        _save_screenshot(page, debug_dir, "login-submitted")
        _wait_for_authenticated_state(page, timeout=args.timeout)
        LOGGER.info("Opening screener: %s", SEEKING_ALPHA_SCREEN_URL)
        page.goto(SEEKING_ALPHA_SCREEN_URL, wait_until="domcontentloaded", timeout=args.timeout)
        LOGGER.info("Screener page loaded: %s", page.url)
        _save_screenshot(page, debug_dir, "screener-loaded")
        LOGGER.info("Waiting for screener content")
        _wait_for_screener_content(page, timeout_ms=args.timeout)
        LOGGER.info("Screener content is visible")
        _save_screenshot(page, debug_dir, "screener-content-visible")
        if _looks_like_login_or_bot_gate(page):
            _save_screenshot(page, debug_dir, "login-or-bot-gate")
            _save_page_html(page, debug_dir, "login-or-bot-gate")
            raise RuntimeError("Seeking Alpha redirected to login or bot verification instead of the screener.")
        _save_cookie_secret(output_path=output_path, context=context)
    finally:
        if context is not None:
            LOGGER.info("Closing CloakBrowser context")
            context.close()

    print(f"Saved Seeking Alpha cookie secret to {output_path}")
    print(f"Set {SEEKING_ALPHA_COOKIES_ENV}={output_path} on the server.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
