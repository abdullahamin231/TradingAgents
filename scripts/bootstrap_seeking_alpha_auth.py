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
    SEEKING_ALPHA_USER_AGENT,
    resolve_cookies_path,
)

try:
    from selenium import webdriver
    from selenium.common.exceptions import TimeoutException, WebDriverException
    from selenium.webdriver import ActionChains
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.remote.webelement import WebElement
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
except ImportError:  # pragma: no cover - exercised by hosts without selenium installed
    webdriver = None
    ActionChains = None
    By = None
    EC = None
    Keys = None
    TimeoutException = WebDriverException = Exception
    Options = None
    Service = None
    WebDriver = Any
    WebDriverWait = None
    WebElement = Any


SEEKING_ALPHA_EMAIL_ENV = "SEEKING_ALPHA_EMAIL"
SEEKING_ALPHA_PASSWORD_ENV = "SEEKING_ALPHA_PASSWORD"
DEFAULT_OUTPUT_PATH = "secrets/seeking_alpha_cookies.json"
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_HOLD_SECONDS = 10.0
DEFAULT_HOLD_GATE_WAIT_SECONDS = 20
DEFAULT_DEBUG_DIR = "debug"
LOGGER = logging.getLogger("seeking_alpha_bootstrap")
THIRD_PARTY_LOGGERS = (
    "selenium",
    "urllib3",
    "trio",
)
HOLD_GATE_FIND_SCRIPT = """
const terms = ["press", "hold", "verify", "human"];
const selector = [
  "button",
  "[role='button']",
  "input[type='button']",
  "input[type='submit']",
  ".px-captcha",
  "#px-captcha",
  "[class*='captcha']",
  "[id*='captcha']"
].join(",");

function textFor(element) {
  return [
    element.innerText || "",
    element.textContent || "",
    element.getAttribute("aria-label") || "",
    element.getAttribute("value") || "",
    element.getAttribute("class") || "",
    element.getAttribute("id") || ""
  ].join(" ").toLowerCase();
}

function visible(element) {
  const style = window.getComputedStyle(element);
  const rect = element.getBoundingClientRect();
  return style.visibility !== "hidden"
    && style.display !== "none"
    && rect.width > 0
    && rect.height > 0;
}

function findIn(root) {
  for (const element of root.querySelectorAll(selector)) {
    const label = textFor(element);
    if (visible(element) && terms.some(term => label.includes(term))) {
      return element;
    }
  }
  for (const element of root.querySelectorAll("*")) {
    if (element.shadowRoot) {
      const found = findIn(element.shadowRoot);
      if (found) {
        return found;
      }
    }
  }
  return null;
}

return findIn(document);
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bootstrap a Seeking Alpha cookie secret for server-side API access."
    )
    parser.add_argument(
        "--output",
        default=os.getenv(SEEKING_ALPHA_COOKIES_ENV, "").strip() or DEFAULT_OUTPUT_PATH,
        help=f"Path to write the Seeking Alpha cookie secret. Defaults to ${SEEKING_ALPHA_COOKIES_ENV} or {DEFAULT_OUTPUT_PATH}.",
    )
    parser.add_argument(
        "--email",
        default=os.getenv(SEEKING_ALPHA_EMAIL_ENV, "").strip(),
        help=f"Seeking Alpha account email. Defaults to ${SEEKING_ALPHA_EMAIL_ENV}.",
    )
    parser.add_argument(
        "--password",
        default=os.getenv(SEEKING_ALPHA_PASSWORD_ENV, ""),
        help=f"Seeking Alpha account password. Defaults to ${SEEKING_ALPHA_PASSWORD_ENV}.",
    )
    parser.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run Chrome in headless mode. Use --no-headless for local debugging.",
    )
    parser.add_argument(
        "--chrome-binary",
        default=os.getenv("CHROME_BINARY", "").strip(),
        help="Optional Chrome/Chromium binary path.",
    )
    parser.add_argument(
        "--driver-path",
        default=os.getenv("CHROMEDRIVER_PATH", "").strip(),
        help="Optional chromedriver path.",
    )
    parser.add_argument(
        "--user-data-dir",
        default=os.getenv("CHROME_USER_DATA_DIR", "").strip(),
        help="Optional persistent Chrome profile path.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Page and element wait timeout in seconds.",
    )
    parser.add_argument(
        "--hold-seconds",
        type=float,
        default=DEFAULT_HOLD_SECONDS,
        help="Seconds to hold a detected verification button.",
    )
    parser.add_argument(
        "--hold-gate-wait",
        type=int,
        default=DEFAULT_HOLD_GATE_WAIT_SECONDS,
        help="Seconds to wait for a Press & Hold challenge before continuing.",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default=os.getenv("SEEKING_ALPHA_BOOTSTRAP_LOG_LEVEL", "INFO").upper(),
        help="Logging verbosity. Defaults to $SEEKING_ALPHA_BOOTSTRAP_LOG_LEVEL or INFO.",
    )
    parser.add_argument(
        "--debug-dir",
        default=os.getenv("SEEKING_ALPHA_BOOTSTRAP_DEBUG_DIR", DEFAULT_DEBUG_DIR),
        help=f"Directory for debug screenshots. Defaults to $SEEKING_ALPHA_BOOTSTRAP_DEBUG_DIR or {DEFAULT_DEBUG_DIR}.",
    )
    return parser.parse_args()


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    for logger_name in THIRD_PARTY_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def _require_selenium() -> None:
    if webdriver is None:
        raise SystemExit(
            "Selenium is not installed. Install project dependencies, or run: python -m pip install selenium"
        )


def _build_driver(args: argparse.Namespace, debug_dir: Path) -> WebDriver:
    assert Options is not None
    LOGGER.info("Starting Chrome via Selenium (headless=%s)", args.headless)
    if args.chrome_binary:
        LOGGER.info("Using Chrome binary: %s", args.chrome_binary)
    if args.driver_path:
        LOGGER.info("Using chromedriver: %s", args.driver_path)
    if args.user_data_dir:
        LOGGER.info("Using Chrome user data dir: %s", args.user_data_dir)

    options = Options()
    if args.headless:
        options.add_argument("--headless=new")
    if args.chrome_binary:
        options.binary_location = args.chrome_binary
    if args.user_data_dir:
        options.add_argument(f"--user-data-dir={args.user_data_dir}")
    options.add_argument("--window-size=1440,2200")
    options.add_argument(f"--user-agent={SEEKING_ALPHA_USER_AGENT}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--remote-debugging-port=0")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    debug_dir.mkdir(parents=True, exist_ok=True)
    chromedriver_log = debug_dir / "chromedriver.log"
    service = (
        Service(executable_path=args.driver_path, service_args=["--verbose"], log_output=str(chromedriver_log))
        if args.driver_path
        else Service(service_args=["--verbose"], log_output=str(chromedriver_log))
    )
    LOGGER.info("ChromeDriver verbose log: %s", chromedriver_log)
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(args.timeout)
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = window.chrome || { runtime: {} };
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4] });
            """
        },
    )
    LOGGER.info("Chrome started")
    return driver


def _visible(driver: WebDriver, selector: str, timeout: int) -> WebElement:
    assert WebDriverWait is not None
    return WebDriverWait(driver, timeout).until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, selector))
    )


def _first_visible(driver: WebDriver, selectors: tuple[str, ...], timeout: int) -> WebElement:
    last_error: Exception | None = None
    for selector in selectors:
        try:
            LOGGER.debug("Waiting for visible element: %s", selector)
            return _visible(driver, selector, timeout)
        except TimeoutException as exc:
            last_error = exc
    raise TimeoutException(f"Could not find a visible element for selectors: {', '.join(selectors)}") from last_error


def _page_text_sample(driver: WebDriver, max_chars: int = 500) -> str:
    try:
        text = driver.find_element(By.TAG_NAME, "body").text
    except WebDriverException:
        return ""
    return " ".join(text.split())[:max_chars]


def _log_page_state(driver: WebDriver, label: str) -> None:
    try:
        LOGGER.warning("%s URL: %s", label, driver.current_url)
        LOGGER.warning("%s title: %s", label, driver.title)
        text_sample = _page_text_sample(driver)
        if text_sample:
            LOGGER.warning("%s body text sample: %s", label, text_sample)
    except WebDriverException as exc:
        LOGGER.warning("Could not capture %s page state: %s", label, exc)


def _safe_label(label: str) -> str:
    return "".join(char if char.isalnum() else "-" for char in label.lower()).strip("-")


def _save_screenshot(driver: WebDriver, debug_dir: Path, label: str) -> Path | None:
    debug_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    path = debug_dir / f"{timestamp}-{_safe_label(label)}.png"
    try:
        driver.switch_to.default_content()
        driver.save_screenshot(str(path))
    except WebDriverException as exc:
        LOGGER.warning("Could not save debug screenshot %s: %s", path, exc)
        return None
    LOGGER.info("Saved debug screenshot: %s", path)
    return path


def _find_hold_element_in_current_context(driver: WebDriver) -> WebElement | None:
    element = driver.execute_script(HOLD_GATE_FIND_SCRIPT)
    if element:
        return element
    return None


def _find_hold_element(driver: WebDriver, depth: int = 0) -> WebElement | None:
    try:
        element = _find_hold_element_in_current_context(driver)
        if element is not None:
            return element
    except WebDriverException:
        return None

    if depth >= 3:
        return None

    frames = driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
    if frames:
        LOGGER.debug("Scanning %s frame(s) for hold challenge at depth %s", len(frames), depth)
    for frame in frames:
        try:
            driver.switch_to.frame(frame)
            element = _find_hold_element(driver, depth + 1)
            if element is not None:
                return element
        except WebDriverException:
            pass
        finally:
            driver.switch_to.parent_frame()
    return None


def _press_and_hold_element(driver: WebDriver, element: WebElement, hold_seconds: float) -> None:
    driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", element)
    ActionChains(driver).move_to_element(element).click_and_hold(element).pause(hold_seconds).release(
        element
    ).perform()


def _press_hold_gate_if_present(
    driver: WebDriver,
    *,
    hold_seconds: float,
    wait_seconds: int,
    max_seconds: int,
    debug_dir: Path,
    label: str,
) -> bool:
    wait_deadline = time.monotonic() + wait_seconds
    element = None
    while time.monotonic() < wait_deadline:
        driver.switch_to.default_content()
        element = _find_hold_element(driver)
        if element is not None:
            break
        time.sleep(0.5)

    if element is None:
        LOGGER.debug("No Press & Hold challenge detected after %s second(s)", wait_seconds)
        return False

    _save_screenshot(driver, debug_dir, f"{label}-press-hold-detected")
    deadline = time.monotonic() + max_seconds
    pressed = False
    attempt = 0
    while time.monotonic() < deadline:
        driver.switch_to.default_content()
        element = _find_hold_element(driver)
        if element is None:
            if pressed:
                LOGGER.info("Press & Hold challenge cleared")
                _save_screenshot(driver, debug_dir, f"{label}-press-hold-cleared")
            else:
                LOGGER.debug("Press & Hold challenge disappeared before interaction")
            return pressed
        attempt += 1
        LOGGER.info("Press & Hold challenge detected; holding for %.1f seconds (attempt %s)", hold_seconds, attempt)
        _press_and_hold_element(driver, element, hold_seconds)
        pressed = True
        time.sleep(2)
    LOGGER.warning("Press & Hold challenge was still present after %s seconds", max_seconds)
    _save_screenshot(driver, debug_dir, f"{label}-press-hold-timeout")
    return pressed


def _click_if_present(driver: WebDriver, selectors: tuple[str, ...], timeout: int = 5) -> bool:
    for selector in selectors:
        try:
            _visible(driver, selector, timeout).click()
            LOGGER.debug("Clicked element: %s", selector)
            return True
        except (TimeoutException, WebDriverException):
            continue
    LOGGER.debug("No clickable element found for selectors: %s", ", ".join(selectors))
    return False


def _login(
    driver: WebDriver,
    *,
    email: str,
    password: str,
    timeout: int,
    hold_seconds: float,
    hold_gate_wait: int,
    debug_dir: Path,
) -> None:
    LOGGER.info("Opening Seeking Alpha login page: %s", SEEKING_ALPHA_LOGIN_URL)
    driver.get(SEEKING_ALPHA_LOGIN_URL)
    _save_screenshot(driver, debug_dir, "login-page-loaded")
    _press_hold_gate_if_present(
        driver,
        hold_seconds=hold_seconds,
        wait_seconds=hold_gate_wait,
        max_seconds=timeout,
        debug_dir=debug_dir,
        label="login",
    )
    driver.switch_to.default_content()
    _save_screenshot(driver, debug_dir, "login-after-press-hold")

    LOGGER.info("Waiting for email field")
    try:
        email_input = _first_visible(
            driver,
            (
                "input[type='email']",
                "input[name='email']",
                "input[id*='email' i]",
                "input[autocomplete='email']",
            ),
            timeout,
        )
    except TimeoutException:
        _log_page_state(driver, "Login field lookup failed")
        _save_screenshot(driver, debug_dir, "login-field-lookup-failed")
        raise
    email_input.clear()
    email_input.send_keys(email)
    LOGGER.info("Entered email")
    _save_screenshot(driver, debug_dir, "login-email-entered")

    try:
        LOGGER.info("Waiting for password field")
        password_input = _first_visible(driver, ("input[type='password']", "input[name='password']"), 5)
    except TimeoutException:
        LOGGER.info("Password field not visible yet; clicking continue/login")
        _click_if_present(
            driver,
            (
                "button[type='submit']",
                "button[data-test-id*='continue' i]",
                "button[data-test-id*='login' i]",
            ),
            timeout=5,
        )
        password_input = _first_visible(driver, ("input[type='password']", "input[name='password']"), timeout)

    password_input.clear()
    password_input.send_keys(password)
    LOGGER.info("Submitting login form")
    _save_screenshot(driver, debug_dir, "login-before-submit")
    _click_if_present(
        driver,
        (
            "button[type='submit']",
            "button[data-test-id*='login' i]",
            "button[data-test-id*='sign' i]",
        ),
        timeout=5,
    ) or password_input.send_keys(Keys.ENTER)

    LOGGER.info("Waiting for login redirect")
    WebDriverWait(driver, timeout).until(
        lambda current: "/account/login" not in current.current_url.lower()
    )
    LOGGER.info("Login redirect completed: %s", driver.current_url)
    _save_screenshot(driver, debug_dir, "login-redirect-completed")
    _press_hold_gate_if_present(
        driver,
        hold_seconds=hold_seconds,
        wait_seconds=3,
        max_seconds=timeout,
        debug_dir=debug_dir,
        label="post-login",
    )


def _open_screener(
    driver: WebDriver,
    *,
    timeout: int,
    hold_seconds: float,
    hold_gate_wait: int,
    debug_dir: Path,
) -> None:
    LOGGER.info("Opening Seeking Alpha screener: %s", SEEKING_ALPHA_SCREEN_URL)
    driver.get(SEEKING_ALPHA_SCREEN_URL)
    _save_screenshot(driver, debug_dir, "screener-page-loaded")
    _press_hold_gate_if_present(
        driver,
        hold_seconds=hold_seconds,
        wait_seconds=hold_gate_wait,
        max_seconds=timeout,
        debug_dir=debug_dir,
        label="screener",
    )
    driver.switch_to.default_content()
    _save_screenshot(driver, debug_dir, "screener-after-press-hold")
    LOGGER.info("Waiting for screener page readiness")
    WebDriverWait(driver, timeout).until(
        lambda current: current.execute_script("return document.readyState")
        in {"interactive", "complete"}
    )
    time.sleep(3)
    current_url = driver.current_url.lower()
    LOGGER.info("Screener navigation completed: %s", driver.current_url)
    _save_screenshot(driver, debug_dir, "screener-ready")
    if "/account/login" in current_url:
        _save_screenshot(driver, debug_dir, "screener-redirected-to-login")
        raise RuntimeError("Seeking Alpha redirected back to login after submitting credentials.")


def _cookie_map(driver: WebDriver) -> dict[str, str]:
    return {
        cookie["name"]: cookie["value"]
        for cookie in driver.get_cookies()
        if cookie.get("name") and cookie.get("value")
    }


def main() -> int:
    args = parse_args()
    _configure_logging(args.log_level)
    LOGGER.info("Seeking Alpha bootstrap started")
    _require_selenium()
    if not args.email or not args.password:
        raise SystemExit(
            f"{SEEKING_ALPHA_EMAIL_ENV} and {SEEKING_ALPHA_PASSWORD_ENV} must be set, "
            "or pass --email and --password."
        )

    output_path = resolve_cookies_path(args.output)
    if output_path is None:
        raise SystemExit("Could not resolve output path for Seeking Alpha cookie secret.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    LOGGER.info("Cookie secret output path: %s", output_path)
    debug_dir = Path(args.debug_dir).expanduser().resolve()
    debug_dir.mkdir(parents=True, exist_ok=True)
    LOGGER.info("Debug screenshots directory: %s", debug_dir)

    try:
        driver = _build_driver(args, debug_dir)
    except WebDriverException as exc:
        LOGGER.error("Chrome failed to start: %s", exc)
        LOGGER.error("Check ChromeDriver details in: %s", debug_dir / "chromedriver.log")
        raise

    try:
        _login(
            driver,
            email=args.email,
            password=args.password,
            timeout=args.timeout,
            hold_seconds=args.hold_seconds,
            hold_gate_wait=args.hold_gate_wait,
            debug_dir=debug_dir,
        )
        _open_screener(
            driver,
            timeout=args.timeout,
            hold_seconds=args.hold_seconds,
            hold_gate_wait=args.hold_gate_wait,
            debug_dir=debug_dir,
        )
        cookies = _cookie_map(driver)
        LOGGER.info("Captured %s cookie(s)", len(cookies))
        _save_screenshot(driver, debug_dir, "cookies-captured")
    except Exception:
        _save_screenshot(driver, debug_dir, "fatal-error")
        raise
    finally:
        LOGGER.info("Closing browser")
        driver.quit()

    if not cookies:
        raise SystemExit("Seeking Alpha login completed, but Selenium did not return any cookies.")

    output_path.write_text(
        json.dumps(
            {
                "source": "selenium_bootstrap",
                "created_at": datetime.now().astimezone().isoformat(),
                "screen_url": SEEKING_ALPHA_SCREEN_URL,
                "cookies": cookies,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    os.chmod(output_path, 0o600)
    LOGGER.info("Saved Seeking Alpha cookie secret to %s", output_path)
    LOGGER.info("Set %s=%s on the server", SEEKING_ALPHA_COOKIES_ENV, output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
