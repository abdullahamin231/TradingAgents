from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from webui.seeking_alpha import (  # noqa: E402
    SEEKING_ALPHA_COOKIES_ENV,
    SEEKING_ALPHA_LOGIN_URL,
    SEEKING_ALPHA_SCREEN_URL,
    SEEKING_ALPHA_TOP_COUNT,
    _fetch_watchlist_via_api,
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
SEEKING_ALPHA_SECURITY_CODE_ENV = "SEEKING_ALPHA_SECURITY_CODE"
POST_LOGIN_SETTLE_SECONDS = 45
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
        "--security-code",
        default=os.getenv(SEEKING_ALPHA_SECURITY_CODE_ENV, "").strip(),
        help=f"Seeking Alpha emailed security code. Defaults to ${SEEKING_ALPHA_SECURITY_CODE_ENV}.",
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


def _looks_like_bot_gate(page: Any) -> bool:
    try:
        body_text = page.locator("body").inner_text(timeout=3000).lower()
    except Exception:
        return False
    return any(
        marker in body_text
        for marker in (
            "prove you are not a robot",
            "press & hold",
            "enable javascript and cookies",
            "captcha",
        )
    )


def _press_and_hold_bot_gate(page: Any, debug_dir: Path, *, timeout: int) -> bool:
    wrapper = page.locator("#px-captcha-wrapper").first
    try:
        wrapper.wait_for(state="visible", timeout=5000)
    except Exception:
        return False

    LOGGER.info("Seeking Alpha showed a press-and-hold verification gate")
    _save_screenshot(page, debug_dir, "bot-gate-press-and-hold-before")

    captcha = page.locator("#px-captcha").first
    challenge_timeout = max(15000, min(timeout, 45000))
    for attempt in range(1, 4):
        try:
            box = captcha.bounding_box(timeout=5000)
        except Exception:
            box = None
        if not box:
            break

        x = box["x"] + box["width"] / 2
        y = box["y"] + min(box["height"] / 2, 45)
        LOGGER.info("Holding verification button attempt %s", attempt)
        page.mouse.move(x, y)
        page.mouse.down()
        page.wait_for_timeout(9000 + attempt * 2000)
        page.mouse.up()
        try:
            wrapper.wait_for(state="hidden", timeout=challenge_timeout)
            LOGGER.info("Press-and-hold verification gate cleared")
            _save_screenshot(page, debug_dir, "bot-gate-press-and-hold-cleared")
            return True
        except Exception:
            page.wait_for_timeout(1500)

    _save_screenshot(page, debug_dir, "bot-gate-press-and-hold-failed")
    _save_page_html(page, debug_dir, "bot-gate-press-and-hold-failed")
    raise RuntimeError("Seeking Alpha press-and-hold verification did not clear.")


def _submit_security_code_if_required(page: Any, *, security_code: str, timeout: int, debug_dir: Path) -> bool:
    selectors = (
        'input[autocomplete="one-time-code"]',
        'input[name="otp"]',
        'input[id*="otp" i]',
        'input[placeholder*="code" i]',
        'input[aria-label*="code" i]',
    )
    code_input = None
    selector_timeout = max(1000, min(timeout, 15000))
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            locator.wait_for(state="visible", timeout=selector_timeout)
            code_input = locator
            LOGGER.info("Found security-code selector: %s", selector)
            break
        except Exception:
            continue
    if code_input is None:
        return False

    _save_screenshot(page, debug_dir, "security-code-required")
    if not security_code:
        raise RuntimeError(f"Seeking Alpha requires an emailed security code. Set {SEEKING_ALPHA_SECURITY_CODE_ENV} or pass --security-code.")

    code_input.fill("")
    code_input.type(security_code, delay=50)
    LOGGER.info("Filled security-code field")
    if not _submit_enabled_login_button(page, timeout=timeout):
        code_input.press("Enter")
    LOGGER.info("Submitted security-code form")
    _save_screenshot(page, debug_dir, "security-code-submitted")
    return True


def _submit_enabled_login_button(page: Any, *, timeout: int) -> bool:
    selector_timeout = max(1000, min(timeout, 10000))
    selectors = (
        'button[type="submit"]:not([disabled])',
        'button:has-text("Sign in"):not([disabled])',
        'button:has-text("Sign In"):not([disabled])',
        'button:has-text("Log in"):not([disabled])',
        'button:has-text("Log In"):not([disabled])',
        'button:has-text("Login"):not([disabled])',
    )
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            locator.wait_for(state="visible", timeout=selector_timeout)
            locator.click(timeout=selector_timeout)
            LOGGER.info("Clicked enabled login submit selector: %s", selector)
            return True
        except Exception:
            continue
    return False


def _submit_login(page: Any, *, email: str, password: str, timeout: int, debug_dir: Path) -> None:
    LOGGER.info("Looking for login form")
    if _looks_like_bot_gate(page):
        _save_screenshot(page, debug_dir, "bot-gate-before-login")
        _save_page_html(page, debug_dir, "bot-gate-before-login")
        raise RuntimeError("Seeking Alpha showed a bot verification gate before the login form.")

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
    email_input.fill("")
    email_input.type(email, delay=35)
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
    password_input.fill("")
    password_input.type(password, delay=35)
    LOGGER.info("Filled password field")

    submitted = _submit_enabled_login_button(page, timeout=timeout)
    if not submitted:
        LOGGER.info("Enabled submit button not found; pressing Enter in password field")
        password_input.press("Enter")
    LOGGER.info("Submitted login form")


def _wait_for_authenticated_state(page: Any, *, timeout: int, debug_dir: Path) -> None:
    LOGGER.info("Waiting for login navigation/network idle")
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
        LOGGER.info("Network idle reached after login submit")
    except Exception:
        LOGGER.info("Network idle wait timed out; continuing to URL/auth checks")
        pass

    url_wait_timeout = max(5000, min(timeout, 90000))
    try:
        page.wait_for_url(lambda url: "/account/login" not in str(url).lower(), timeout=url_wait_timeout)
        LOGGER.info("Login URL changed to: %s", page.url)
    except Exception:
        LOGGER.info("Login URL did not change within %s ms; checking page body before continuing", url_wait_timeout)
        body_text = ""
        try:
            body_text = page.locator("body").inner_text(timeout=3000).lower()
        except Exception:
            pass
        if any(marker in body_text for marker in ("verification code", "two-factor", "2fa", "captcha")):
            _save_screenshot(page, debug_dir, "auth-timeout-verification")
            _save_page_html(page, debug_dir, "auth-timeout-verification")
            raise RuntimeError("Seeking Alpha requires an interactive verification step; cookie bootstrap cannot continue headlessly.")
        if "/account/login" in page.url.lower():
            _save_screenshot(page, debug_dir, "auth-timeout-login-page")
            _save_page_html(page, debug_dir, "auth-timeout-login-page")
            raise RuntimeError("Seeking Alpha login did not complete; still on the login page after submit.")


def _open_screener_if_authenticated(page: Any, *, timeout: int, debug_dir: Path) -> bool:
    LOGGER.info("Opening screener: %s", SEEKING_ALPHA_SCREEN_URL)
    page.goto(SEEKING_ALPHA_SCREEN_URL, wait_until="domcontentloaded", timeout=timeout)
    LOGGER.info("Screener page loaded: %s", page.url)
    _save_screenshot(page, debug_dir, "screener-loaded")
    _click_if_visible(page, ('button:has-text("Accept")', 'button:has-text("I agree")', '[data-testid*="accept" i]'))

    if _looks_like_login_or_bot_gate(page):
        LOGGER.info("Screener is not available from the current browser profile")
        _save_screenshot(page, debug_dir, "login-or-bot-gate")
        _save_page_html(page, debug_dir, "login-or-bot-gate")
        return False

    LOGGER.info("Waiting for screener content")
    try:
        _wait_for_screener_content(page, timeout_ms=timeout)
    except RuntimeError:
        if _looks_like_login_or_bot_gate(page):
            LOGGER.info("Seeking Alpha redirected away from the screener while waiting for content")
            _save_screenshot(page, debug_dir, "login-or-bot-gate")
            _save_page_html(page, debug_dir, "login-or-bot-gate")
            return False
        raise

    LOGGER.info("Screener content is visible")
    _save_screenshot(page, debug_dir, "screener-content-visible")
    return True


def _open_login_or_detect_existing_session(page: Any, *, timeout: int, debug_dir: Path) -> bool:
    LOGGER.info("Opening login page: %s", SEEKING_ALPHA_LOGIN_URL)
    page.goto(SEEKING_ALPHA_LOGIN_URL, wait_until="domcontentloaded", timeout=timeout)
    LOGGER.info("Login page loaded: %s", page.url)
    _save_screenshot(page, debug_dir, "login-loaded")
    _click_if_visible(page, ('button:has-text("Accept")', 'button:has-text("I agree")', '[data-testid*="accept" i]'))

    if _looks_like_bot_gate(page):
        _save_screenshot(page, debug_dir, "bot-gate-before-login")
        _save_page_html(page, debug_dir, "bot-gate-before-login")
        raise RuntimeError("Seeking Alpha showed a bot verification gate before the login form.")

    current_url = page.url.lower()
    if "/account/login" not in current_url:
        LOGGER.info("Login page redirected to %s; existing Seeking Alpha session is active", page.url)
        return True
    return False


def _cookie_map_from_context(context: Any) -> dict[str, str]:
    LOGGER.info("Collecting cookies from browser context")
    cookie_map = {cookie["name"]: cookie["value"] for cookie in context.cookies() if cookie.get("name") and cookie.get("value")}
    if not cookie_map:
        raise RuntimeError("No cookies were collected from the Seeking Alpha browser context.")
    return cookie_map


def _validate_cookie_map(*, cookie_map: dict[str, str], debug_dir: Path) -> None:
    LOGGER.info("Validating cookies against Seeking Alpha screener API")
    api_debug_dir = debug_dir / f"{datetime.now().astimezone().strftime('%Y%m%d-%H%M%S')}-cookie-validation"
    api_debug_dir.mkdir(parents=True, exist_ok=True)
    tickers, debug_paths = _fetch_watchlist_via_api(
        cookies=cookie_map,
        limit=SEEKING_ALPHA_TOP_COUNT,
        debug_dir=api_debug_dir,
    )
    LOGGER.info("Cookie validation fetched %s tickers; debug artifacts: %s", len(tickers), ", ".join(debug_paths))


def _save_cookie_secret(*, output_path: Path, cookie_map: dict[str, str]) -> None:
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

        is_authenticated = _open_login_or_detect_existing_session(page, timeout=args.timeout, debug_dir=debug_dir)
        if not is_authenticated:
            if not args.email:
                raise SystemExit(f"Set {SEEKING_ALPHA_EMAIL_ENV} or pass --email.")
            if not args.password:
                raise SystemExit(f"Set {SEEKING_ALPHA_PASSWORD_ENV} or pass --password.")

            _submit_login(page, email=args.email, password=args.password, timeout=args.timeout, debug_dir=debug_dir)
            _save_screenshot(page, debug_dir, "login-submitted")
            _press_and_hold_bot_gate(page, debug_dir, timeout=args.timeout)
            _submit_security_code_if_required(page, security_code=args.security_code, timeout=args.timeout, debug_dir=debug_dir)
            LOGGER.info("Waiting %s seconds after login submit for session setup", POST_LOGIN_SETTLE_SECONDS)
            time.sleep(POST_LOGIN_SETTLE_SECONDS)
            _wait_for_authenticated_state(page, timeout=args.timeout, debug_dir=debug_dir)

        if not _open_screener_if_authenticated(page, timeout=args.timeout, debug_dir=debug_dir):
            _save_screenshot(page, debug_dir, "login-or-bot-gate")
            _save_page_html(page, debug_dir, "login-or-bot-gate")
            raise RuntimeError("Seeking Alpha redirected to login or bot verification instead of the screener.")

        if _looks_like_login_or_bot_gate(page):
            raise RuntimeError("Seeking Alpha redirected to login or bot verification instead of the screener.")
        cookie_map = _cookie_map_from_context(context)
        _validate_cookie_map(cookie_map=cookie_map, debug_dir=debug_dir)
        _save_cookie_secret(output_path=output_path, cookie_map=cookie_map)
    finally:
        if context is not None:
            LOGGER.info("Closing CloakBrowser context")
            context.close()

    print(f"Saved Seeking Alpha cookie secret to {output_path}")
    print(f"Set {SEEKING_ALPHA_COOKIES_ENV}={output_path} on the server.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
