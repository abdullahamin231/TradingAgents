from __future__ import annotations

import copy
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

try:
    import markdown
except ModuleNotFoundError:  # pragma: no cover - exercised only in minimal envs
    markdown = None


MARKDOWN_JSON_KEYS = ("report", "markdown", "content", "text", "body", "value")
SAVED_REPORT_ID_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}_[A-Za-z0-9._-]+$")
TOKEN_USAGE_FILENAME = "token_usage.json"


@dataclass(frozen=True)
class PathsConfig:
    repo_root: Path
    reports_dir: Path


def markdown_to_html(text: str) -> str:
    normalized_text = normalize_markdown_text(text)
    if markdown is None:
        return f"<pre>{escape(normalized_text or '')}</pre>"
    return markdown.markdown(
        normalized_text or "",
        extensions=["tables", "fenced_code", "sane_lists", "toc"],
    )


def normalize_markdown_text(text: Any) -> str:
    if not isinstance(text, str):
        return "" if text is None else str(text)

    stripped = text.strip()
    if stripped[:1] in {"{", "["}:
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if parsed is not None:
            extracted = extract_markdown_from_json_value(parsed)
            if extracted is not None:
                return normalize_markdown_tables(replace_embedded_json_blocks(extracted))

    return normalize_markdown_tables(replace_embedded_json_blocks(text))


def replace_embedded_json_blocks(text: str) -> str:
    decoder = json.JSONDecoder()
    parts: list[str] = []
    cursor = 0

    while cursor < len(text):
        marker = text.find("{", cursor)
        if marker == -1:
            parts.append(text[cursor:])
            break

        parts.append(text[cursor:marker])
        try:
            payload, next_cursor = decoder.raw_decode(text, marker)
        except json.JSONDecodeError:
            parts.append(text[marker])
            cursor = marker + 1
            continue

        extracted = extract_markdown_from_json_value(payload)
        if extracted is None:
            parts.append(text[marker:next_cursor])
        else:
            parts.append(normalize_markdown_text(extracted))
        cursor = next_cursor

    return "".join(parts)


def extract_markdown_from_json_value(value: Any, depth: int = 0) -> str | None:
    if depth > 8:
        return None

    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        for key in MARKDOWN_JSON_KEYS:
            if key in value:
                extracted = extract_markdown_from_json_value(value[key], depth + 1)
                if extracted is not None:
                    return extracted

        if len(value) == 1:
            only_value = next(iter(value.values()))
            extracted = extract_markdown_from_json_value(only_value, depth + 1)
            if extracted is not None:
                return extracted
        return None

    if isinstance(value, list):
        extracted_items = [
            extracted
            for item in value
            if (extracted := extract_markdown_from_json_value(item, depth + 1)) is not None
        ]
        if extracted_items:
            return "\n\n".join(extracted_items)
        return None

    return None


def normalize_markdown_tables(text: str) -> str:
    lines = text.splitlines()
    if not lines:
        return text

    normalized: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if is_markdown_table_header(line, lines[index + 1] if index + 1 < len(lines) else None):
            if normalized and normalized[-1].strip():
                normalized.append("")
            normalized.append(line)
            normalized.append(lines[index + 1])
            index += 2
            while index < len(lines) and lines[index].lstrip().startswith("|"):
                normalized.append(lines[index])
                index += 1
            continue

        normalized.append(line)
        index += 1

    return "\n".join(normalized)


def is_markdown_table_header(line: str, next_line: str | None) -> bool:
    if next_line is None:
        return False
    if "|" not in line:
        return False
    return bool(re.match(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+(?:\s*:?-{3,}:?\s*)\|?\s*$", next_line))


def coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def coerce_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def iso_from_ms(value: Any) -> str | None:
    try:
        return datetime.utcfromtimestamp(float(value) / 1000.0).isoformat() + "Z"
    except (TypeError, ValueError, OSError):
        return None


def normalize_token_usage_event(event: dict[str, Any], index: int) -> dict[str, Any] | None:
    if not isinstance(event, dict):
        return None

    # Saved token_usage.json files already contain normalized flat metrics, while
    # live opencode callbacks provide nested tokens/time payloads. Accept both.
    if any(
        key in event
        for key in (
            "tokens_total",
            "tokens_input",
            "tokens_output",
            "tokens_reasoning",
            "tokens_cache_read",
            "tokens_cache_write",
            "started_at_ms",
            "completed_at_ms",
        )
    ):
        start_ms = event.get("started_at_ms")
        end_ms = event.get("completed_at_ms")
        started_at_ms = coerce_int(start_ms)
        completed_at_ms = coerce_int(end_ms)
        duration_ms = event.get("duration_ms")
        if duration_ms is None and started_at_ms and completed_at_ms:
            duration_ms = max(0, completed_at_ms - started_at_ms)

        return {
            "index": coerce_int(event.get("index")) if event.get("index") is not None else index,
            "provider": event.get("provider") or "opencode",
            "model": event.get("model") or "",
            "session_id": event.get("session_id"),
            "message_id": event.get("message_id"),
            "reason": event.get("reason"),
            "snapshot": event.get("snapshot"),
            "cost": coerce_float(event.get("cost")),
            "tokens_total": coerce_int(event.get("tokens_total")),
            "tokens_input": coerce_int(event.get("tokens_input")),
            "tokens_output": coerce_int(event.get("tokens_output")),
            "tokens_reasoning": coerce_int(event.get("tokens_reasoning")),
            "tokens_cache_read": coerce_int(event.get("tokens_cache_read")),
            "tokens_cache_write": coerce_int(event.get("tokens_cache_write")),
            "started_at_ms": started_at_ms,
            "completed_at_ms": completed_at_ms,
            "started_at": event.get("started_at") or iso_from_ms(start_ms),
            "completed_at": event.get("completed_at") or iso_from_ms(end_ms),
            "duration_ms": coerce_int(duration_ms),
        }

    tokens = event.get("tokens") if isinstance(event.get("tokens"), dict) else {}
    cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
    timing = event.get("time") if isinstance(event.get("time"), dict) else {}

    start_ms = timing.get("start")
    end_ms = timing.get("end")
    duration_ms = None
    if isinstance(start_ms, (int, float)) and isinstance(end_ms, (int, float)):
        duration_ms = max(0, int(end_ms - start_ms))

    return {
        "index": index,
        "provider": event.get("provider") or "opencode",
        "model": event.get("model") or "",
        "session_id": event.get("session_id"),
        "message_id": event.get("message_id"),
        "reason": event.get("reason"),
        "snapshot": event.get("snapshot"),
        "cost": coerce_float(event.get("cost")),
        "tokens_total": coerce_int(tokens.get("total")),
        "tokens_input": coerce_int(tokens.get("input")),
        "tokens_output": coerce_int(tokens.get("output")),
        "tokens_reasoning": coerce_int(tokens.get("reasoning")),
        "tokens_cache_read": coerce_int(cache.get("read")),
        "tokens_cache_write": coerce_int(cache.get("write")),
        "started_at_ms": coerce_int(start_ms),
        "completed_at_ms": coerce_int(end_ms),
        "started_at": iso_from_ms(start_ms),
        "completed_at": iso_from_ms(end_ms),
        "duration_ms": duration_ms,
    }


def token_usage_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    if not events:
        return {
            "call_count": 0,
            "cost": 0.0,
            "tokens_total": 0,
            "tokens_input": 0,
            "tokens_output": 0,
            "tokens_reasoning": 0,
            "tokens_cache_read": 0,
            "tokens_cache_write": 0,
            "started_at": None,
            "completed_at": None,
            "started_at_ms": None,
            "completed_at_ms": None,
            "duration_ms": 0,
        }

    started_values = [event["started_at_ms"] for event in events if event.get("started_at_ms")]
    completed_values = [event["completed_at_ms"] for event in events if event.get("completed_at_ms")]
    started_at_ms = min(started_values) if started_values else None
    completed_at_ms = max(completed_values) if completed_values else None
    duration_ms = (
        max(0, int(completed_at_ms - started_at_ms))
        if started_at_ms is not None and completed_at_ms is not None
        else 0
    )

    return {
        "call_count": len(events),
        "cost": round(sum(coerce_float(event.get("cost")) for event in events), 8),
        "tokens_total": sum(coerce_int(event.get("tokens_total")) for event in events),
        "tokens_input": sum(coerce_int(event.get("tokens_input")) for event in events),
        "tokens_output": sum(coerce_int(event.get("tokens_output")) for event in events),
        "tokens_reasoning": sum(coerce_int(event.get("tokens_reasoning")) for event in events),
        "tokens_cache_read": sum(coerce_int(event.get("tokens_cache_read")) for event in events),
        "tokens_cache_write": sum(coerce_int(event.get("tokens_cache_write")) for event in events),
        "started_at": iso_from_ms(started_at_ms),
        "completed_at": iso_from_ms(completed_at_ms),
        "started_at_ms": started_at_ms,
        "completed_at_ms": completed_at_ms,
        "duration_ms": duration_ms,
    }


def build_token_usage_payload(events: list[dict[str, Any]], metadata: dict[str, Any]) -> dict[str, Any]:
    normalized_events = sorted(
        (copy.deepcopy(event) for event in events),
        key=lambda event: (event.get("started_at_ms") or 0, event.get("completed_at_ms") or 0, event.get("index") or 0),
    )
    return {
        **metadata,
        "summary": token_usage_summary(normalized_events),
        "events": normalized_events,
    }


def token_usage_path(report_dir: Path) -> Path:
    return report_dir / TOKEN_USAGE_FILENAME


def load_token_usage_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None

    try:
        payload, _ = load_json_payload(path)
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    events = payload.get("events") if isinstance(payload.get("events"), list) else []
    metadata = {key: value for key, value in payload.items() if key not in {"summary", "events"}}
    normalized_events = [
        normalized
        for index, event in enumerate(events)
        if (normalized := normalize_token_usage_event(event, index)) is not None
    ]
    normalized_payload = build_token_usage_payload(normalized_events, metadata)
    if summary and not normalized_events:
        normalized_payload["summary"] = summary
    return normalized_payload


def load_json_payload(path: Path) -> tuple[dict[str, Any], bool]:
    text = path.read_text(encoding="utf-8")

    try:
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise json.JSONDecodeError("Expected JSON object", text, 0)
        return payload, False
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        idx = 0
        recovered: dict[str, Any] | None = None
        parsed_multiple = False

        while idx < len(text):
            while idx < len(text) and text[idx].isspace():
                idx += 1
            if idx >= len(text):
                break

            try:
                payload, next_idx = decoder.raw_decode(text, idx)
            except json.JSONDecodeError:
                break

            if isinstance(payload, dict):
                recovered = payload
                parsed_multiple = recovered is not None and next_idx < len(text)
            idx = next_idx

        if recovered is None:
            raise

        return recovered, parsed_multiple


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)
