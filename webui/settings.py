from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .service_helpers import atomic_write_json, load_json_payload


DEFAULT_HALAL_CHECKER_ENABLED = True
DEFAULT_DAILY_RUN_TIME = "09:30"
DAILY_RUN_TIMEZONE = "America/New_York"
_TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def default_settings() -> dict[str, Any]:
    return {
        "halal_checker_enabled": DEFAULT_HALAL_CHECKER_ENABLED,
        "daily_run_time": DEFAULT_DAILY_RUN_TIME,
        "daily_run_timezone": DAILY_RUN_TIMEZONE,
        "last_scheduled_daily_run_date": None,
        "updated_at": None,
    }


def load_settings(path: Path) -> dict[str, Any]:
    settings = default_settings()
    if path.exists():
        try:
            payload, repaired = load_json_payload(path)
        except (OSError, ValueError):
            payload = {}
            repaired = False
        if isinstance(payload, dict):
            try:
                settings.update(_normalize_settings(payload, include_operational=True))
            except ValueError:
                pass
            if repaired:
                atomic_write_json(path, settings)
    return settings


def update_settings(path: Path, updates: dict[str, Any]) -> dict[str, Any]:
    current = load_settings(path)
    current.update(_normalize_settings(updates, include_operational=False))
    current["daily_run_timezone"] = DAILY_RUN_TIMEZONE
    current["updated_at"] = datetime.utcnow().isoformat() + "Z"
    atomic_write_json(path, current)
    return current


def mark_scheduled_daily_run(path: Path, run_date: str) -> dict[str, Any]:
    current = load_settings(path)
    current["last_scheduled_daily_run_date"] = run_date
    current["updated_at"] = datetime.utcnow().isoformat() + "Z"
    atomic_write_json(path, current)
    return current


def _normalize_settings(payload: dict[str, Any], *, include_operational: bool) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    if "halal_checker_enabled" in payload:
        normalized["halal_checker_enabled"] = bool(payload.get("halal_checker_enabled"))
    if "daily_run_time" in payload:
        normalized["daily_run_time"] = normalize_daily_run_time(payload.get("daily_run_time"))
    if include_operational and isinstance(payload.get("last_scheduled_daily_run_date"), str):
        normalized["last_scheduled_daily_run_date"] = payload["last_scheduled_daily_run_date"]
    return normalized


def normalize_daily_run_time(value: Any) -> str:
    candidate = str(value or "").strip()
    if not _TIME_PATTERN.match(candidate):
        raise ValueError("Daily run time must use 24-hour HH:MM format.")
    return candidate
