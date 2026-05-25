from __future__ import annotations

import argparse
import html
import re
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from webui.seeking_alpha import SEEKING_ALPHA_LOGIN_URL, SEEKING_ALPHA_USER_AGENT  # noqa: E402

try:
    from selenium import webdriver
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.by import By
    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.remote.webelement import WebElement
    from selenium.webdriver.support.ui import WebDriverWait
except ImportError:  # pragma: no cover - exercised by hosts without selenium installed
    webdriver = None
    By = None
    TimeoutException = Exception
    Options = None
    Service = None
    ActionChains = None
    WebDriver = Any
    WebDriverWait = None
    WebElement = Any


DEFAULT_TIMEOUT_SECONDS = 30
TARGET_CAPTCHA_IFRAME_SCRIPT = """
const expectedText = [
  "To ensure this doesn't happen in the future, please enable Javascript and cookies in your browser.",
  "Is this happening to you frequently? Please report it on our feedback forum."
].join(" ");

function normalize(value) {
  return value.replace(/\\s+/g, " ").trim().replace("doesn\\u2019t", "doesn't");
}

for (const paragraph of document.querySelectorAll("p")) {
  const link = paragraph.querySelector("a[href='https://help.seekingalpha.com']");
  if (link && normalize(paragraph.innerText || paragraph.textContent || "") === expectedText) {
    const parent = paragraph.parentElement;
    if (!parent || parent.tagName.toLowerCase() !== "div" || !parent.classList.contains("content")) {
      console.log("Found the notice paragraph, but its parent is not div.content.");
      return null;
    }
    const captcha = parent.querySelector("div#px-captcha");
    const captchaHtml = captcha ? captcha.outerHTML : "";
    if (!captchaHtml.includes("<iframe")) {
      return null;
    }
    return {
      text: "",
      html: captchaHtml
    };
  }
}

return null;
"""

TARGET_PRESS_HOLD_IN_CAPTCHA_IFRAME_SCRIPT = """
const expectedText = [
  "To ensure this doesn't happen in the future, please enable Javascript and cookies in your browser.",
  "Is this happening to you frequently? Please report it on our feedback forum."
].join(" ");

function normalize(value) {
  return value.replace(/\\s+/g, " ").trim().replace("doesn\\u2019t", "doesn't");
}

for (const paragraph of document.querySelectorAll("p")) {
  const link = paragraph.querySelector("a[href='https://help.seekingalpha.com']");
  if (link && normalize(paragraph.innerText || paragraph.textContent || "") === expectedText) {
    const parent = paragraph.parentElement;
    if (!parent || parent.tagName.toLowerCase() !== "div" || !parent.classList.contains("content")) {
      return null;
    }
    const captcha = parent.querySelector("div#px-captcha");
    const iframe = captcha ? captcha.getElementsByTagName("iframe")[0] : null;
    if (!iframe) {
      return null;
    }
    let frameDocument = null;
    try {
      frameDocument = iframe.contentDocument || (iframe.contentWindow ? iframe.contentWindow.document : null);
    } catch (error) {
      return null;
    }
    if (!frameDocument || !frameDocument.body) {
      return null;
    }
    const button = frameDocument.evaluate(
      "/html/body/div[(@role='button' or .//p[normalize-space()='Press & Hold']) and .//*[normalize-space()='Press & Hold']]",
      frameDocument,
      null,
      XPathResult.FIRST_ORDERED_NODE_TYPE,
      null
    ).singleNodeValue;
    if (!button) {
      return null;
    }
    return {
      text: normalize(button.innerText || button.textContent || ""),
      html: button.outerHTML
    };
  }
}

return null;
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Visit Seeking Alpha login and extract the Press & Hold button inside the px-captcha iframe."
    )
    parser.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run Chrome in headless mode. Use --no-headless for local debugging.",
    )
    parser.add_argument(
        "--chrome-binary",
        default="",
        help="Optional Chrome/Chromium binary path.",
    )
    parser.add_argument(
        "--driver-path",
        default="",
        help="Optional chromedriver path.",
    )
    parser.add_argument(
        "--user-data-dir",
        default="",
        help="Optional persistent Chrome profile path.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Page and element wait timeout in seconds.",
    )
    parser.add_argument(
        "--html",
        action="store_true",
        help="Print the Press & Hold button outerHTML instead of visible text. Implies --no-press-hold.",
    )
    parser.add_argument(
        "--press-hold",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Actually press and hold the challenge button, then wait for the login page. Use --no-press-hold to only print the detected button.",
    )
    parser.add_argument(
        "--hold-seconds",
        type=float,
        default=15.0,
        help="Seconds to keep the mouse button held down on the Press & Hold control.",
    )
    parser.add_argument(
        "--post-hold-timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Seconds to wait after releasing the Press & Hold control for the login page to become available.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print debug details for the matching div.content and px-captcha container.",
    )
    return parser.parse_args()


def require_selenium() -> None:
    if webdriver is None:
        raise SystemExit(
            "Selenium is not installed. Install project dependencies, or run: python -m pip install selenium"
        )


def build_driver(args: argparse.Namespace) -> WebDriver:
    assert Options is not None
    options = Options()
    if args.headless:
        options.add_argument("--headless=new")
    if args.chrome_binary:
        options.binary_location = args.chrome_binary
    if args.user_data_dir:
        options.add_argument(f"--user-data-dir={args.user_data_dir}")
    options.add_argument("--window-size=1440,1200")
    options.add_argument(f"--user-agent={SEEKING_ALPHA_USER_AGENT}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    service = Service(executable_path=args.driver_path) if args.driver_path else Service()
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
    return driver


def get_captcha_iframe(driver: WebDriver, timeout: int) -> dict[str, str]:
    assert WebDriverWait is not None
    driver.get(SEEKING_ALPHA_LOGIN_URL)
    try:
        captcha = WebDriverWait(driver, timeout).until(
            lambda current: current.execute_script(TARGET_CAPTCHA_IFRAME_SCRIPT)
        )
    except TimeoutException as exc:
        raise RuntimeError(
            "Could not find an iframe inside the px-captcha div next to the Seeking Alpha notice paragraph."
        ) from exc
    match = re.search(r"<iframe\b[^>]*>(?:.*?)</iframe>", captcha["html"], flags=re.IGNORECASE | re.DOTALL)
    if not match:
        raise RuntimeError("Found px-captcha HTML, but could not parse an iframe from it.")
    iframe_html = match.group(0)
    src_match = re.search(r'\bsrc=(["\'])(.*?)\1', iframe_html, flags=re.IGNORECASE | re.DOTALL)
    return {
        "text": src_match.group(2) if src_match else "",
        "html": iframe_html,
    }


def wait_for_captcha_iframe_element(driver: WebDriver, timeout: int) -> WebElement:
    assert WebDriverWait is not None
    return WebDriverWait(driver, timeout).until(
        lambda current: current.execute_script(
            """
            const result = (() => {
              const expectedText = [
                "To ensure this doesn't happen in the future, please enable Javascript and cookies in your browser.",
                "Is this happening to you frequently? Please report it on our feedback forum."
              ].join(" ");

              function normalize(value) {
                return value.replace(/\\s+/g, " ").trim().replace("doesn\\u2019t", "doesn't");
              }

              for (const paragraph of document.querySelectorAll("p")) {
                const link = paragraph.querySelector("a[href='https://help.seekingalpha.com']");
                if (link && normalize(paragraph.innerText || paragraph.textContent || "") === expectedText) {
                  const parent = paragraph.parentElement;
                  if (!parent || parent.tagName.toLowerCase() !== "div" || !parent.classList.contains("content")) {
                    return null;
                  }
                  return parent.querySelector("div#px-captcha iframe");
                }
              }
              return null;
            })();
            return result;
            """
        )
    )


def find_press_hold_button_in_current_context(driver: WebDriver, depth: int = 0) -> dict[str, str] | None:
    assert By is not None
    button = driver.execute_script(
        """
        const button = document.evaluate(
          "/html/body/div[(@role='button' or .//p[normalize-space()='Press & Hold']) and .//*[normalize-space()='Press & Hold']]",
          document,
          null,
          XPathResult.FIRST_ORDERED_NODE_TYPE,
          null
        ).singleNodeValue;
        if (!button) {
          return null;
        }
        return {
          text: (button.innerText || button.textContent || "").replace(/\\s+/g, " ").trim(),
          html: button.outerHTML
        };
        """
    )
    if button:
        return button

    if depth >= 4:
        return None

    frames = driver.find_elements(By.TAG_NAME, "iframe")
    for frame in frames:
        try:
            driver.switch_to.frame(frame)
            found = find_press_hold_button_in_current_context(driver, depth + 1)
            if found:
                return found
        except Exception:
            pass
        finally:
            try:
                driver.switch_to.parent_frame()
            except Exception:
                driver.switch_to.default_content()
    return None


def find_press_hold_button_element_in_current_context(driver: WebDriver, depth: int = 0) -> WebElement | None:
    assert By is not None
    button = driver.execute_script(
        """
        return document.evaluate(
          "/html/body/div[(@role='button' or .//p[normalize-space()='Press & Hold']) and .//*[normalize-space()='Press & Hold']]",
          document,
          null,
          XPathResult.FIRST_ORDERED_NODE_TYPE,
          null
        ).singleNodeValue;
        """
    )
    if button:
        return button

    if depth >= 4:
        return None

    frames = driver.find_elements(By.TAG_NAME, "iframe")
    for frame in frames:
        try:
            driver.switch_to.frame(frame)
            found = find_press_hold_button_element_in_current_context(driver, depth + 1)
            if found:
                return found
        except Exception:
            pass
        try:
            driver.switch_to.parent_frame()
        except Exception:
            driver.switch_to.default_content()
    return None


def get_press_hold_button(driver: WebDriver, timeout: int) -> dict[str, str]:
    assert By is not None
    assert WebDriverWait is not None
    driver.get(SEEKING_ALPHA_LOGIN_URL)
    WebDriverWait(driver, timeout).until(
        lambda current: current.execute_script(TARGET_CAPTCHA_IFRAME_SCRIPT)
    )

    deadline = time.monotonic() + timeout
    last_frame_count = 0
    while time.monotonic() < deadline:
        driver.switch_to.default_content()
        button = driver.execute_script(TARGET_PRESS_HOLD_IN_CAPTCHA_IFRAME_SCRIPT)
        if button:
            return button
        last_frame_count = len(driver.find_elements(By.TAG_NAME, "iframe"))
        button = find_press_hold_button_in_current_context(driver)
        if button:
            return button
        time.sleep(0.5)

    button = get_press_hold_button_from_cdp_snapshot(driver)
    if button:
        return button

    raise RuntimeError(f"Could not find the Press & Hold button inside any iframe. Saw {last_frame_count} iframe(s).")


def wait_for_press_hold_button_element(driver: WebDriver, timeout: int) -> WebElement:
    assert WebDriverWait is not None
    driver.get(SEEKING_ALPHA_LOGIN_URL)
    WebDriverWait(driver, timeout).until(
        lambda current: current.execute_script(TARGET_CAPTCHA_IFRAME_SCRIPT)
    )

    def find_button(current: WebDriver) -> WebElement | None:
        current.switch_to.default_content()
        return find_press_hold_button_element_in_current_context(current)

    try:
        return WebDriverWait(driver, timeout).until(find_button)
    except TimeoutException as exc:
        raise RuntimeError("Could not find a clickable Press & Hold button inside any iframe.") from exc


def wait_for_login_page_after_hold(driver: WebDriver, timeout: int) -> dict[str, str]:
    assert WebDriverWait is not None

    def login_ready(current: WebDriver) -> dict[str, str] | None:
        current.switch_to.default_content()
        return current.execute_script(
            """
            const body = document.body;
            const bodyText = body ? (body.innerText || body.textContent || "") : "";
            const hasNotice = bodyText.includes("To ensure this doesn't happen in the future");
            const hasCaptcha = Boolean(document.querySelector("div#px-captcha iframe"));
            const hasEmail = Boolean(document.querySelector("input[type='email'], input[name='email'], input[name='user[email]']"));
            const hasPassword = Boolean(document.querySelector("input[type='password'], input[name='password'], input[name='user[password]']"));
            if (hasPassword || (hasEmail && !hasNotice) || (!hasNotice && !hasCaptcha)) {
              return {
                url: window.location.href,
                title: document.title,
                state: hasPassword ? "login_form" : hasEmail ? "email_form" : "challenge_cleared"
              };
            }
            return null;
            """
        )

    try:
        return WebDriverWait(driver, timeout).until(login_ready)
    except TimeoutException as exc:
        raise RuntimeError("Pressed and held the challenge button, but the login page did not become available.") from exc


def press_and_hold_button_with_js(driver: WebDriver, timeout: int, hold_seconds: float) -> None:
    assert WebDriverWait is not None
    driver.switch_to.default_content()
    WebDriverWait(driver, timeout).until(
        lambda current: current.execute_script(TARGET_PRESS_HOLD_IN_CAPTCHA_IFRAME_SCRIPT)
    )
    driver.switch_to.default_content()
    result = driver.execute_async_script(
        """
        const holdMs = arguments[0];
        const done = arguments[arguments.length - 1];

        function normalize(value) {
          return value.replace(/\\s+/g, " ").trim();
        }

        function findButton(documentRoot) {
          return documentRoot.evaluate(
            "/html/body/div[(@role='button' or .//p[normalize-space()='Press & Hold']) and .//*[normalize-space()='Press & Hold']]",
            documentRoot,
            null,
            XPathResult.FIRST_ORDERED_NODE_TYPE,
            null
          ).singleNodeValue;
        }

        const captcha = document.querySelector("div#px-captcha");
        const iframe = captcha ? captcha.getElementsByTagName("iframe")[0] : null;
        const frameDocument = iframe ? (iframe.contentDocument || (iframe.contentWindow ? iframe.contentWindow.document : null)) : null;
        const frameWindow = iframe ? iframe.contentWindow : null;
        const button = frameDocument ? findButton(frameDocument) : null;
        if (!button || !frameWindow) {
          done({ok: false, error: "Press & Hold button was not available through the captcha iframe document."});
          return;
        }

        const rect = button.getBoundingClientRect();
        const x = Math.max(1, rect.left + rect.width / 2);
        const y = Math.max(1, rect.top + rect.height / 2);
        const eventInit = {
          bubbles: true,
          cancelable: true,
          composed: true,
          view: frameWindow,
          clientX: x,
          clientY: y,
          screenX: x,
          screenY: y,
          button: 0,
          buttons: 1,
          pointerId: 1,
          pointerType: "mouse",
          isPrimary: true
        };

        button.dispatchEvent(new frameWindow.PointerEvent("pointerover", eventInit));
        button.dispatchEvent(new frameWindow.PointerEvent("pointerenter", eventInit));
        button.dispatchEvent(new frameWindow.PointerEvent("pointermove", eventInit));
        button.dispatchEvent(new frameWindow.MouseEvent("mouseover", eventInit));
        button.dispatchEvent(new frameWindow.MouseEvent("mousemove", eventInit));
        button.dispatchEvent(new frameWindow.PointerEvent("pointerdown", eventInit));
        button.dispatchEvent(new frameWindow.MouseEvent("mousedown", eventInit));

        frameWindow.setTimeout(() => {
          const releaseInit = {...eventInit, buttons: 0};
          button.dispatchEvent(new frameWindow.PointerEvent("pointerup", releaseInit));
          button.dispatchEvent(new frameWindow.MouseEvent("mouseup", releaseInit));
          button.dispatchEvent(new frameWindow.MouseEvent("click", releaseInit));
          done({ok: true, text: normalize(button.innerText || button.textContent || "")});
        }, holdMs);
        """,
        int(hold_seconds * 1000),
    )
    if not result or not result.get("ok"):
        raise RuntimeError((result or {}).get("error") or "JavaScript press-and-hold fallback failed.")


def press_and_hold_button_with_cdp_mouse(driver: WebDriver, timeout: int, hold_seconds: float) -> None:
    assert WebDriverWait is not None
    driver.switch_to.default_content()
    WebDriverWait(driver, timeout).until(
        lambda current: current.execute_script(TARGET_CAPTCHA_IFRAME_SCRIPT)
    )
    driver.switch_to.default_content()
    point = driver.execute_script(
        """
        const frames = document.querySelectorAll("div#px-captcha iframe");
        for (let index = 0; index < frames.length; index += 1) {
          frames[index].setAttribute(
            "style",
            "display: block; width: 100%; height: 102px; border: 0; visibility: visible; pointer-events: auto;"
          );
        }
        const captcha = document.querySelector("div#px-captcha");
        if (!captcha) {
          return null;
        }
        const rect = captcha.getBoundingClientRect();
        return {
          x: rect.left + Math.min(155, Math.max(1, rect.width / 2)),
          y: rect.top + Math.min(51, Math.max(1, rect.height / 2))
        };
        """
    )
    if not point:
        raise RuntimeError("Could not calculate captcha coordinates for CDP mouse hold.")

    x = float(point["x"])
    y = float(point["y"])
    driver.execute_cdp_cmd(
        "Input.dispatchMouseEvent",
        {"type": "mouseMoved", "x": x, "y": y, "button": "none", "buttons": 0},
    )
    driver.execute_cdp_cmd(
        "Input.dispatchMouseEvent",
        {"type": "mousePressed", "x": x, "y": y, "button": "left", "buttons": 1, "clickCount": 1},
    )
    time.sleep(hold_seconds)
    driver.execute_cdp_cmd(
        "Input.dispatchMouseEvent",
        {"type": "mouseReleased", "x": x, "y": y, "button": "left", "buttons": 0, "clickCount": 1},
    )


def press_and_hold_to_login(driver: WebDriver, timeout: int, hold_seconds: float, post_hold_timeout: int) -> dict[str, str]:
    if ActionChains is None:
        raise RuntimeError("Selenium ActionChains is not available.")
    if hold_seconds <= 0:
        raise ValueError("--hold-seconds must be greater than 0.")

    try:
        button = wait_for_press_hold_button_element(driver, timeout)
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", button)
        time.sleep(0.25)
        ActionChains(driver).move_to_element(button).click_and_hold(button).pause(hold_seconds).release(button).perform()
    except Exception:
        try:
            press_and_hold_button_with_cdp_mouse(driver, timeout, hold_seconds)
        except Exception:
            press_and_hold_button_with_js(driver, timeout, hold_seconds)
    return wait_for_login_page_after_hold(driver, post_hold_timeout)


def get_debug_details(driver: WebDriver) -> dict[str, str]:
    return driver.execute_script(
        """
        const content = document.querySelector("div.content");
        const captcha = content ? content.querySelector("div#px-captcha") : null;
        const captchaHtml = captcha ? captcha.outerHTML : null;
        return {
          url: window.location.href,
          readyState: document.readyState,
          contentHtml: content ? content.outerHTML : null,
          captchaHtml,
          iframeCount: String(document.querySelectorAll("iframe").length),
        };
        """
    )


def collect_frame_debug(driver: WebDriver, depth: int = 0, path: str = "top") -> list[dict[str, str]]:
    assert By is not None
    details: list[dict[str, str]] = []
    try:
        details.append(
            driver.execute_script(
                """
                const body = document.body;
                return {
                  path: arguments[0],
                  url: window.location.href,
                  title: document.title,
                  bodyText: body ? (body.innerText || body.textContent || "").replace(/\\s+/g, " ").trim().slice(0, 500) : null,
                  bodyHtml: body ? body.outerHTML.slice(0, 1500) : null,
                  iframeCount: String(document.querySelectorAll("iframe").length),
                };
                """,
                path,
            )
        )
    except Exception as exc:
        details.append({"path": path, "error": repr(exc)})

    if depth >= 4:
        return details

    try:
        frames = driver.find_elements(By.TAG_NAME, "iframe")
    except Exception:
        return details

    for index, frame in enumerate(frames):
        child_path = f"{path}/iframe[{index}]"
        try:
            driver.switch_to.frame(frame)
            details.extend(collect_frame_debug(driver, depth + 1, child_path))
        except Exception as exc:
            details.append({"path": child_path, "error": repr(exc)})
        finally:
            try:
                driver.switch_to.parent_frame()
            except Exception:
                driver.switch_to.default_content()
    return details


def collect_cdp_snapshot_matches(driver: WebDriver) -> dict[str, Any]:
    snapshot = driver.execute_cdp_cmd(
        "DOMSnapshot.captureSnapshot",
        {
            "computedStyles": [],
            "includeDOMRects": True,
            "includePaintOrder": True,
        },
    )
    strings = snapshot.get("strings", [])
    matches = [
        {"index": index, "value": value}
        for index, value in enumerate(strings)
        if isinstance(value, str)
        and any(term in value.lower() for term in ("press", "hold", "hgihug", "px-captcha", "human verification"))
    ]
    return {
        "documentCount": len(snapshot.get("documents", [])),
        "matches": matches[:100],
    }


def _snapshot_string(strings: list[Any], value: Any) -> str:
    if isinstance(value, int) and 0 <= value < len(strings):
        item = strings[value]
        return item if isinstance(item, str) else ""
    return ""


def _snapshot_node_attrs(strings: list[Any], attrs: Any) -> dict[str, str]:
    if not isinstance(attrs, list):
        return {}
    result: dict[str, str] = {}
    for index in range(0, len(attrs) - 1, 2):
        name = _snapshot_string(strings, attrs[index])
        value = _snapshot_string(strings, attrs[index + 1])
        if name:
            result[name] = value
    return result


def collect_cdp_node_debug(driver: WebDriver) -> list[dict[str, Any]]:
    snapshot = driver.execute_cdp_cmd("DOMSnapshot.captureSnapshot", {"computedStyles": []})
    strings = snapshot.get("strings", [])
    details: list[dict[str, Any]] = []
    for doc_index, document in enumerate(snapshot.get("documents", [])):
        nodes = document.get("nodes", {})
        node_names = nodes.get("nodeName", [])
        node_values = nodes.get("nodeValue", [])
        parent_indexes = nodes.get("parentIndex", [])
        attributes = nodes.get("attributes", [])
        text_values = nodes.get("textValue", {})
        rare_text_indexes = text_values.get("index", []) if isinstance(text_values, dict) else []
        rare_text_values = text_values.get("value", []) if isinstance(text_values, dict) else []
        rare_text_by_node = dict(zip(rare_text_indexes, rare_text_values))

        for node_index, node_name_index in enumerate(node_names):
            node_name = _snapshot_string(strings, node_name_index)
            node_value = _snapshot_string(strings, node_values[node_index] if node_index < len(node_values) else None)
            text_value = _snapshot_string(strings, rare_text_by_node.get(node_index))
            attrs = _snapshot_node_attrs(strings, attributes[node_index] if node_index < len(attributes) else None)
            haystack = " ".join((node_name, node_value, text_value, " ".join(attrs.keys()), " ".join(attrs.values()))).lower()
            if not any(term in haystack for term in ("press", "hold", "hgihug", "human challenge")):
                continue
            ancestors: list[dict[str, Any]] = []
            parent = parent_indexes[node_index] if node_index < len(parent_indexes) else -1
            while isinstance(parent, int) and parent >= 0 and len(ancestors) < 8:
                parent_name = _snapshot_string(strings, node_names[parent] if parent < len(node_names) else None)
                parent_attrs = _snapshot_node_attrs(strings, attributes[parent] if parent < len(attributes) else None)
                ancestors.append({"index": parent, "nodeName": parent_name, "attrs": parent_attrs})
                parent = parent_indexes[parent] if parent < len(parent_indexes) else -1
            details.append(
                {
                    "doc": doc_index,
                    "index": node_index,
                    "nodeName": node_name,
                    "nodeValue": node_value,
                    "textValue": text_value,
                    "attrs": attrs,
                    "ancestors": ancestors,
                }
            )
    return details[:100]


def _snapshot_context(driver: WebDriver) -> tuple[list[Any], list[dict[str, Any]]]:
    snapshot = driver.execute_cdp_cmd("DOMSnapshot.captureSnapshot", {"computedStyles": []})
    return snapshot.get("strings", []), snapshot.get("documents", [])


def _document_node_data(document: dict[str, Any]) -> dict[str, Any]:
    nodes = document.get("nodes", {})
    node_count = len(nodes.get("nodeName", []))
    parent_indexes = nodes.get("parentIndex", [])
    children: dict[int, list[int]] = {index: [] for index in range(node_count)}
    for node_index, parent in enumerate(parent_indexes):
        if isinstance(parent, int) and parent >= 0:
            children.setdefault(parent, []).append(node_index)
    return {
        "nodes": nodes,
        "node_count": node_count,
        "children": children,
        "attributes": nodes.get("attributes", []),
    }


def _snapshot_node_name(strings: list[Any], data: dict[str, Any], node_index: int) -> str:
    node_names = data["nodes"].get("nodeName", [])
    return _snapshot_string(strings, node_names[node_index] if node_index < len(node_names) else None)


def _snapshot_node_value(strings: list[Any], data: dict[str, Any], node_index: int) -> str:
    node_values = data["nodes"].get("nodeValue", [])
    return _snapshot_string(strings, node_values[node_index] if node_index < len(node_values) else None)


def _snapshot_node_attributes(strings: list[Any], data: dict[str, Any], node_index: int) -> dict[str, str]:
    attributes = data["attributes"]
    return _snapshot_node_attrs(strings, attributes[node_index] if node_index < len(attributes) else None)


def _snapshot_node_html(strings: list[Any], data: dict[str, Any], node_index: int) -> str:
    node_name = _snapshot_node_name(strings, data, node_index)
    if node_name == "#text":
        return html.escape(_snapshot_node_value(strings, data, node_index), quote=False)
    if node_name.startswith("#"):
        return "".join(_snapshot_node_html(strings, data, child) for child in data["children"].get(node_index, []))

    tag = node_name.lower()
    attrs = _snapshot_node_attributes(strings, data, node_index)
    attrs_html = "".join(
        f' {html.escape(name, quote=True)}="{html.escape(value, quote=True)}"'
        for name, value in attrs.items()
    )
    child_html = "".join(_snapshot_node_html(strings, data, child) for child in data["children"].get(node_index, []))
    return f"<{tag}{attrs_html}>{child_html}</{tag}>"


def _snapshot_subtree_text(strings: list[Any], data: dict[str, Any], node_index: int) -> str:
    parts = []
    if _snapshot_node_name(strings, data, node_index) == "#text":
        parts.append(_snapshot_node_value(strings, data, node_index))
    for child in data["children"].get(node_index, []):
        child_text = _snapshot_subtree_text(strings, data, child)
        if child_text:
            parts.append(child_text)
    return " ".join(parts).strip()


def get_press_hold_button_from_cdp_snapshot(driver: WebDriver) -> dict[str, str] | None:
    strings, documents = _snapshot_context(driver)
    fallback: tuple[list[Any], dict[str, Any], int] | None = None
    for document in documents:
        data = _document_node_data(document)
        for node_index in range(data["node_count"]):
            if _snapshot_node_name(strings, data, node_index) != "DIV":
                continue
            attrs = _snapshot_node_attributes(strings, data, node_index)
            subtree_text = _snapshot_subtree_text(strings, data, node_index)
            label = attrs.get("aria-label", "")
            has_press_hold = label == "Press & Hold" or "Press & Hold" in subtree_text
            if attrs.get("role") == "button" and has_press_hold:
                return {
                    "text": " ".join((label or subtree_text).split()),
                    "html": _snapshot_node_html(strings, data, node_index),
                }
            if has_press_hold and fallback is None:
                fallback = (strings, data, node_index)
    if fallback is None:
        return None
    fallback_strings, fallback_data, fallback_node_index = fallback
    return {
        "text": " ".join(_snapshot_subtree_text(fallback_strings, fallback_data, fallback_node_index).split()),
        "html": _snapshot_node_html(fallback_strings, fallback_data, fallback_node_index),
    }


def main() -> int:
    args = parse_args()
    require_selenium()
    if args.html:
        args.press_hold = False

    driver = build_driver(args)
    try:
        try:
            if args.press_hold:
                login_result = press_and_hold_to_login(
                    driver,
                    args.timeout,
                    args.hold_seconds,
                    args.post_hold_timeout,
                )
                press_hold_button = {
                    "text": f"{login_result['state']}: {login_result['url']}",
                    "html": "",
                }
            else:
                press_hold_button = get_press_hold_button(driver, args.timeout)
        except Exception:
            if args.debug:
                driver.switch_to.default_content()
                print(get_debug_details(driver))
                print(collect_cdp_snapshot_matches(driver))
                for node_detail in collect_cdp_node_debug(driver):
                    print(node_detail)
                for frame_detail in collect_frame_debug(driver):
                    print(frame_detail)
            raise
    finally:
        driver.quit()

    print(press_hold_button["html" if args.html else "text"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
