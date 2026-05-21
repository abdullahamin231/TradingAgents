from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any

import requests

from tradingagents.dataflows.utils import safe_ticker_component


HALALSCREENER_API_KEY_ENV = "HALALSCREENER_API_KEY"

DEFAULT_HALALSCREENER_URL_TEMPLATE = "https://halalscreener.app/api/v1/screen?symbol={ticker}"

_ALLOW_STATUSES = {
    "compliant",
    "halal",
    "pass",
    "passed",
    "shariah compliant",
    "shariah-compliant",
}
_BLOCK_STATUSES = {
    "doubtful",
    "dubious",
    "fail",
    "failed",
    "f",
    "gray area",
    "grey area",
    "haram",
    "mixed",
    "non compliant",
    "non-compliant",
    "not covered",
    "not halal",
    "questionable",
    "review",
}
_STATUS_KEYS = (
    "compliance",
    "grade",
    "halal",
    "rating",
    "screen",
    "shariah",
    "status",
    "verdict",
)


@dataclass(frozen=True)
class HalalScreeningConfig:
    api_key: str
    url_template: str = DEFAULT_HALALSCREENER_URL_TEMPLATE
    auth_header: str = "Authorization"
    auth_scheme: str = "Bearer"
    timeout_seconds: float = 10.0

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.url_template)


@dataclass(frozen=True)
class HalalScreeningResult:
    ticker: str
    allowed: bool
    status: str
    provider: str = "halalscreener"
    raw_status: str | None = None
    error: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


def load_config() -> HalalScreeningConfig:
    timeout_raw = "10"
    try:
        timeout_seconds = float(timeout_raw)
    except ValueError:
        timeout_seconds = 10.0
    return HalalScreeningConfig(
        api_key=(os.getenv(HALALSCREENER_API_KEY_ENV) or "").strip(),
        url_template=(DEFAULT_HALALSCREENER_URL_TEMPLATE).strip(),
        auth_header="Authorization",
        auth_scheme="Bearer",
        timeout_seconds=max(timeout_seconds, 1.0),
    )


def screening_enabled() -> bool:
    return load_config().enabled


def screen_tickers(tickers: tuple[str, ...]) -> dict[str, Any]:
    config = load_config()
    normalized = tuple(dict.fromkeys(safe_ticker_component(ticker.strip().upper()) for ticker in tickers if ticker))
    if not config.enabled:
        return {
            "enabled": False,
            "provider": "halalscreener",
            "tickers": list(normalized),
            "kept_tickers": list(normalized),
            "excluded": [],
            "results": [],
            "error": None,
        }

    session = requests.Session()
    auth_value = f"{config.auth_scheme} {config.api_key}" if config.auth_scheme else config.api_key
    session.headers.update({config.auth_header: auth_value, "accept": "application/json"})

    kept: list[str] = []
    excluded: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    for ticker in normalized:
        result = _screen_ticker(session, config, ticker)
        payload = result.to_payload()
        results.append(payload)
        if result.allowed:
            kept.append(ticker)
            continue
        excluded.append(
            {
                "ticker": ticker,
                "status": result.status,
                "raw_status": result.raw_status,
                "error": result.error,
            }
        )

    return {
        "enabled": True,
        "provider": "halalscreener",
        "tickers": list(normalized),
        "kept_tickers": kept,
        "excluded": excluded,
        "results": results,
        "error": None,
    }


def _screen_ticker(session: requests.Session, config: HalalScreeningConfig, ticker: str) -> HalalScreeningResult:
    url = config.url_template.format(ticker=ticker)
    try:
        response = session.get(url, timeout=config.timeout_seconds)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        return HalalScreeningResult(
            ticker=ticker,
            allowed=False,
            status="screening_error",
            error=str(exc),
        )

    raw_status = _extract_status(payload)
    if raw_status is None:
        return HalalScreeningResult(
            ticker=ticker,
            allowed=False,
            status="unknown",
            error="Unable to determine HalalScreener compliance status from API response.",
        )

    normalized = _normalize_status(raw_status)
    if normalized in _ALLOW_STATUSES:
        return HalalScreeningResult(ticker=ticker, allowed=True, status="halal", raw_status=raw_status)
    if normalized in _BLOCK_STATUSES:
        return HalalScreeningResult(ticker=ticker, allowed=False, status=normalized, raw_status=raw_status)
    return HalalScreeningResult(
        ticker=ticker,
        allowed=False,
        status="unknown",
        raw_status=raw_status,
        error=f"Unsupported HalalScreener compliance status: {raw_status}",
    )


def _extract_status(payload: Any) -> str | None:
    return _extract_status_from_value(payload)


def _extract_status_from_value(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, nested in value.items():
            key_normalized = str(key).strip().lower()
            if any(marker in key_normalized for marker in _STATUS_KEYS) and isinstance(nested, (bool, str)):
                return "halal" if nested is True else "not halal" if nested is False else nested
            candidate = _extract_status_from_value(nested)
            if candidate is not None:
                return candidate
        return None
    if isinstance(value, list):
        for item in value:
            candidate = _extract_status_from_value(item)
            if candidate is not None:
                return candidate
        return None
    if isinstance(value, str):
        normalized = _normalize_status(value)
        if normalized in _ALLOW_STATUSES or normalized in _BLOCK_STATUSES:
            return value
    return None


def _normalize_status(value: str) -> str:
    return " ".join(str(value).strip().lower().replace("_", " ").replace("-", " ").split())


def describe_env() -> dict[str, str]:
    return {
        "api_key_env": HALALSCREENER_API_KEY_ENV,
    }
