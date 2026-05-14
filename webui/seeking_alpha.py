from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from tradingagents.dataflows.utils import safe_ticker_component

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - exercised through fallback behavior
    PlaywrightTimeoutError = Exception
    sync_playwright = None


SEEKING_ALPHA_SCREEN_URL = "https://seekingalpha.com/screeners/95bd0cd23361-HC-top"
SEEKING_ALPHA_LOGIN_URL = "https://seekingalpha.com/account/login"
SEEKING_ALPHA_SCREENER_API_URL = "https://seekingalpha.com/api/v3/screener_results"
SEEKING_ALPHA_TOP_COUNT = 20
SEEKING_ALPHA_CACHE_TTL_HOURS = 6
SEEKING_ALPHA_COOKIES_ENV = "SEEKING_ALPHA_COOKIES_PATH"
SEEKING_ALPHA_STORAGE_STATE_ENV = "SEEKING_ALPHA_STORAGE_STATE_PATH"
SEEKING_ALPHA_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
SEEKING_ALPHA_SCREENER_PAYLOAD = {
    "filter": {
        "quant_rating": {"in": ["strong_buy", "buy", "hold", "sell", "strong_sell"]},
        "industry_id": {
            "in": [
                10101010, 10101020, 10102010, 10102020, 10102030, 10102040, 10102050, 15101010, 15101020, 15101030, 15101040, 15101050,
                15102010, 15103010, 15103020, 15104010, 15104020, 15104025, 15104030, 15104040, 15104045, 15104050, 15105010, 15105020,
                20101010, 20102010, 20103010, 20104010, 20104020, 20105010, 20106010, 20106015, 20106020, 20107010, 20201010, 20201050,
                20201060, 20201070, 20201080, 20202010, 20202020, 20202030, 20301010, 20302010, 20303010, 20304010, 20304030, 20304040,
                20305010, 20305020, 20305030, 25101010, 25101020, 25102010, 25102020, 25201010, 25201020, 25201030, 25201040, 25201050,
                25202010, 25203010, 25203020, 25203030, 25301010, 25301020, 25301030, 25301040, 25302010, 25302020, 25501010, 25503030,
                25504010, 25504020, 25504030, 25504040, 25504050, 25504060, 30101010, 30101020, 30101030, 30101040, 30201010, 30201020,
                30201030, 30202010, 30202030, 30203010, 30301010, 30302010, 35101010, 35101020, 35102010, 35102015, 35102020, 35102030,
                35103010, 35201010, 35202010, 35203010, 40101010, 40101015, 40201020, 40201030, 40201040, 40201050, 40201060, 40202010,
                40203010, 40203020, 40203030, 40203040, 40204010, 40301010, 40301020, 40301030, 40301040, 40301050, 45102010, 45102030,
                45103010, 45103020, 45201020, 45202030, 45203010, 45203015, 45203020, 45203030, 45301010, 45301020, 50101010, 50101020,
                50102010, 50201010, 50201020, 50201030, 50201040, 50202010, 50202020, 50203010, 55101010, 55102010, 55103010, 55104010,
                55105010, 55105020,
            ]
        },
        "marketcap_display": {
            "in": [
                {"id": 3, "gte": 2000000000, "lte": 10000000000},
                {"id": 433, "gte": 10000000000, "lte": 200000000000},
                {"id": 436, "gte": 200000000000, "lte": None},
            ]
        },
        "pe_ratio": {},
        "net_income": {},
        "div_yield_fwd": {},
        "price_return_1m": {},
        "price_return_6m": {},
        "authors_rating": {},
        "ebitda_change_display": {},
        "close_to_52w": {},
    },
    "page": 1,
    "per_page": 500,
    "sort": None,
    "type": "stock",
}


@dataclass
class SeekingAlphaWatchlist:
    source: str
    tickers: tuple[str, ...]
    fetched_at: str | None = None
    screenshots: tuple[str, ...] = ()
    error: str | None = None
    stale: bool = False

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _local_artifact_timestamp() -> str:
    return datetime.now().astimezone().strftime("%d-%b-%Y-%I-%M-%p")


def _cache_file(cache_dir: Path) -> Path:
    return cache_dir / "seeking_alpha_top_tickers.json"


def resolve_storage_state_path(storage_state_path: str | Path | None = None) -> Path | None:
    candidate = storage_state_path or os.getenv(SEEKING_ALPHA_STORAGE_STATE_ENV, "").strip()
    if not candidate:
        return None
    return Path(candidate).expanduser().resolve()


def resolve_cookies_path(cookies_path: str | Path | None = None) -> Path | None:
    candidate = cookies_path or os.getenv(SEEKING_ALPHA_COOKIES_ENV, "").strip()
    if not candidate:
        return None
    return Path(candidate).expanduser().resolve()


def _load_cache(cache_dir: Path, ttl_hours: int | None = None) -> SeekingAlphaWatchlist | None:
    path = _cache_file(cache_dir)
    if not path.exists():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = payload.get("fetched_at")
        if not isinstance(fetched_at, str):
            return None
        fetched_dt = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
        if ttl_hours is not None and _utcnow() - fetched_dt > timedelta(hours=ttl_hours):
            return None
        tickers = tuple(_sanitize_tickers(payload.get("tickers", ()), SEEKING_ALPHA_TOP_COUNT))
        if not tickers:
            return None
        screenshots = tuple(str(item) for item in payload.get("screenshots", ()))
        return SeekingAlphaWatchlist(
            source=str(payload.get("source") or "seeking_alpha_cache"),
            tickers=tickers,
            fetched_at=fetched_at,
            screenshots=screenshots,
            error=payload.get("error"),
            stale=bool(payload.get("stale", False)),
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _fresh_cache(cache_dir: Path, ttl_hours: int) -> SeekingAlphaWatchlist | None:
    return _load_cache(cache_dir, ttl_hours=ttl_hours)


def _stale_cache(cache_dir: Path) -> SeekingAlphaWatchlist | None:
    return _load_cache(cache_dir, ttl_hours=None)


def _write_cache(cache_dir: Path, payload: SeekingAlphaWatchlist) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    _cache_file(cache_dir).write_text(json.dumps(payload.to_payload(), indent=2), encoding="utf-8")


def _sanitize_tickers(symbols: Any, limit: int) -> list[str]:
    sanitized: list[str] = []
    seen: set[str] = set()
    for symbol in symbols or ():
        if not isinstance(symbol, str):
            continue
        try:
            cleaned = safe_ticker_component(symbol.strip().upper())
        except ValueError:
            continue
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        sanitized.append(cleaned)
        if len(sanitized) >= limit:
            break
    return sanitized


def _load_storage_state_cookies(storage_state_path: Path) -> dict[str, str]:
    payload = json.loads(storage_state_path.read_text(encoding="utf-8"))
    cookies = payload.get("cookies")
    if not isinstance(cookies, list):
        raise RuntimeError(f"Invalid Playwright storage state file: {storage_state_path}")
    resolved: dict[str, str] = {}
    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue
        name = cookie.get("name")
        value = cookie.get("value")
        if isinstance(name, str) and isinstance(value, str) and name:
            resolved[name] = value
    if not resolved:
        raise RuntimeError(f"No cookies found in Playwright storage state file: {storage_state_path}")
    return resolved


def _load_cookie_secret(cookies_path: Path) -> dict[str, str]:
    payload = json.loads(cookies_path.read_text(encoding="utf-8"))
    cookies = payload.get("cookies")
    if not isinstance(cookies, dict):
        raise RuntimeError(f"Invalid Seeking Alpha cookie secret file: {cookies_path}")
    resolved = {str(name): str(value) for name, value in cookies.items() if str(name)}
    if not resolved:
        raise RuntimeError(f"No cookies found in Seeking Alpha cookie secret file: {cookies_path}")
    return resolved


def _resolve_runtime_cookies(
    cookies_path: str | Path | None = None,
    storage_state_path: str | Path | None = None,
) -> tuple[dict[str, str], str]:
    resolved_cookies_path = resolve_cookies_path(cookies_path)
    if resolved_cookies_path is not None:
        if not resolved_cookies_path.exists():
            raise RuntimeError(f"Seeking Alpha cookies file is missing: {resolved_cookies_path}")
        return _load_cookie_secret(resolved_cookies_path), str(resolved_cookies_path)

    resolved_storage_state_path = resolve_storage_state_path(storage_state_path)
    if resolved_storage_state_path is not None:
        if not resolved_storage_state_path.exists():
            raise RuntimeError(f"Seeking Alpha storage state file is missing: {resolved_storage_state_path}")
        return _load_storage_state_cookies(resolved_storage_state_path), str(resolved_storage_state_path)

    raise RuntimeError(f"{SEEKING_ALPHA_COOKIES_ENV} or {SEEKING_ALPHA_STORAGE_STATE_ENV} must be configured")


def _build_screener_session(cookies: dict[str, str]) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "accept": "application/json",
            "content-type": "application/json",
            "origin": "https://seekingalpha.com",
            "referer": SEEKING_ALPHA_SCREEN_URL,
            "user-agent": SEEKING_ALPHA_USER_AGENT,
        }
    )
    for name, value in cookies.items():
        session.cookies.set(name, value, domain=".seekingalpha.com")
    return session


def _extract_tickers_from_api_payload(payload: Any, limit: int) -> list[str]:
    candidates: list[str] = []

    def visit(value: Any) -> None:
        if len(candidates) >= limit:
            return
        if isinstance(value, dict):
            slug = value.get("slug")
            symbol = value.get("symbol")
            for candidate in (slug, symbol):
                if isinstance(candidate, str):
                    cleaned = _sanitize_tickers((candidate,), limit=1)
                    if cleaned and cleaned[0] not in candidates:
                        candidates.append(cleaned[0])
                        if len(candidates) >= limit:
                            return
            for nested in value.values():
                visit(nested)
            return
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if isinstance(value, str) and "/symbol/" in value:
            symbol_candidate = value.split("/symbol/", 1)[1].split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
            cleaned = _sanitize_tickers((symbol_candidate,), limit=1)
            if cleaned and cleaned[0] not in candidates:
                candidates.append(cleaned[0])

    visit(payload)
    return candidates[:limit]


def _fetch_watchlist_via_api(
    *,
    cookies: dict[str, str],
    limit: int,
    debug_dir: Path,
) -> tuple[list[str], list[str]]:
    session = _build_screener_session(cookies)
    request_payload = json.loads(json.dumps(SEEKING_ALPHA_SCREENER_PAYLOAD))
    request_payload["page"] = 1
    response = session.post(SEEKING_ALPHA_SCREENER_API_URL, json=request_payload, timeout=60)
    response.raise_for_status()
    payload = response.json()
    debug_paths = [
        str(debug_dir / "01-screener_results.json"),
    ]
    (debug_dir / "01-screener_results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tickers = _extract_tickers_from_api_payload(payload, limit)
    if len(tickers) < limit:
        raise RuntimeError(f"Expected {limit} tickers from Seeking Alpha API, got {len(tickers)}")
    return tickers[:limit], debug_paths


def _extract_tickers(page: Any, limit: int) -> list[str]:
    ticker_selectors = [
        '[data-test-id="content"] a[href^="/symbol/"]',
        "a[href^='/symbol/']",
        "[data-test-id='screener-table'] a",
    ]
    matches: list[str] = []
    for selector in ticker_selectors:
        try:
            locator = page.locator(selector)
            hrefs = locator.evaluate_all(
                """elements => elements
                .map(element => element.getAttribute('href') || '')
                .filter(href => href.startsWith('/symbol/'))
                .map(href => href.split('/symbol/')[1]?.split(/[?#/]/)[0] || '')"""
            )
        except Exception:
            continue
        matches = _sanitize_tickers(hrefs, limit)
        if len(matches) >= limit:
            return matches[:limit]
    return matches[:limit]


def _wait_for_screener_content(page: Any, timeout_ms: int = 30000) -> None:
    selectors = [
        '[data-test-id="content"] a[href^="/symbol/"]',
        "a[href^='/symbol/']",
        "[data-test-id='screener-table'] a",
    ]
    for selector in selectors:
        try:
            page.locator(selector).first.wait_for(state="visible", timeout=timeout_ms)
            return
        except Exception:
            continue
    raise RuntimeError("Seeking Alpha screener content did not become visible")


def _looks_like_login_or_bot_gate(page: Any) -> bool:
    url = page.url.lower()
    if "/account/login" in url:
        return True
    content = page.locator("body").inner_text(timeout=2000).lower()
    return "prove you are not a robot" in content or "enable javascript and cookies" in content


def build_browser_context_kwargs(storage_state_path: Path | None) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "user_agent": SEEKING_ALPHA_USER_AGENT,
        "viewport": {"width": 1440, "height": 2200},
        "locale": "en-US",
        "timezone_id": "America/New_York",
    }
    if storage_state_path is not None:
        kwargs["storage_state"] = str(storage_state_path)
    return kwargs


def apply_stealth_init_script(context: Any) -> None:
    context.add_init_script(
        """
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        window.chrome = window.chrome || { runtime: {} };
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4] });
        """
    )


def _failed_refresh_fallback(
    *,
    cache_dir: Path,
    default_tickers: tuple[str, ...],
    stale_cached: SeekingAlphaWatchlist | None,
    error: str,
    screenshots: tuple[str, ...] = (),
) -> SeekingAlphaWatchlist:
    if stale_cached is not None:
        payload = SeekingAlphaWatchlist(
            source=stale_cached.source,
            tickers=stale_cached.tickers,
            fetched_at=stale_cached.fetched_at,
            screenshots=tuple(stale_cached.screenshots) or screenshots,
            error=error,
            stale=True,
        )
        _write_cache(cache_dir, payload)
        return payload

    payload = SeekingAlphaWatchlist(
        source="hardcoded",
        tickers=default_tickers,
        fetched_at=_utcnow().isoformat().replace("+00:00", "Z"),
        screenshots=screenshots,
        error=error,
        stale=False,
    )
    _write_cache(cache_dir, payload)
    return payload


def fetch_seeking_alpha_watchlist(
    *,
    cache_dir: Path,
    default_tickers: tuple[str, ...],
    cookies_path: str | Path | None = None,
    storage_state_path: str | Path | None = None,
    force_refresh: bool = False,
    ttl_hours: int = SEEKING_ALPHA_CACHE_TTL_HOURS,
    limit: int = SEEKING_ALPHA_TOP_COUNT,
) -> SeekingAlphaWatchlist:
    cached = None if force_refresh else _fresh_cache(cache_dir, ttl_hours)
    stale_cached = _stale_cache(cache_dir)
    if cached is not None:
        return cached

    try:
        runtime_cookies, auth_source_path = _resolve_runtime_cookies(
            cookies_path=cookies_path,
            storage_state_path=storage_state_path,
        )
    except RuntimeError as exc:
        return _failed_refresh_fallback(
            cache_dir=cache_dir,
            default_tickers=default_tickers,
            stale_cached=stale_cached,
            error=str(exc),
        )

    screenshots_dir = cache_dir / "debug_runs" / _local_artifact_timestamp()
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    screenshot_paths: list[str] = []

    try:
        tickers, debug_paths = _fetch_watchlist_via_api(
            cookies=runtime_cookies,
            limit=limit,
            debug_dir=screenshots_dir,
        )
        payload = SeekingAlphaWatchlist(
            source="seeking_alpha_api",
            tickers=tuple(tickers),
            fetched_at=_utcnow().isoformat().replace("+00:00", "Z"),
            screenshots=tuple(debug_paths),
        )
        _write_cache(cache_dir, payload)
        return payload
    except (requests.RequestException, RuntimeError, OSError, json.JSONDecodeError) as api_exc:
        return _failed_refresh_fallback(
            cache_dir=cache_dir,
            default_tickers=default_tickers,
            stale_cached=stale_cached,
            error=f"{api_exc} (auth source: {auth_source_path})",
            screenshots=tuple(screenshot_paths),
        )
