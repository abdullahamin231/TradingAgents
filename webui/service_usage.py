from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .service_helpers import (
    build_token_usage_payload,
    load_token_usage_payload,
    normalize_token_usage_event,
    token_usage_path,
)


@dataclass
class TokenUsageCollector:
    job_id: str
    ticker: str
    trade_date: str
    workflow: str
    provider: str
    quick_model: str
    deep_model: str

    def __post_init__(self) -> None:
        self._events: list[dict[str, Any]] = []

    def record(self, event: dict[str, Any]) -> None:
        normalized = normalize_token_usage_event(event, len(self._events))
        if normalized is not None:
            self._events.append(normalized)

    def snapshot(self) -> dict[str, Any]:
        return build_token_usage_payload(
            self._events,
            {
                "job_id": self.job_id,
                "ticker": self.ticker,
                "trade_date": self.trade_date,
                "workflow": self.workflow,
                "provider": self.provider,
                "quick_model": self.quick_model,
                "deep_model": self.deep_model,
            },
        )


def iter_saved_usage_records(
    *,
    reports_dir: Path,
    repo_root: Path,
    system_dirs: set[str],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not reports_dir.exists():
        return records

    for ticker_dir in sorted(reports_dir.iterdir()):
        if not ticker_dir.is_dir() or ticker_dir.name in system_dirs:
            continue
        saved_dir = ticker_dir / "SavedReports"
        if not saved_dir.exists():
            continue
        for report_dir in sorted((path for path in saved_dir.iterdir() if path.is_dir()), reverse=True):
            payload = load_token_usage_payload(token_usage_path(report_dir))
            if payload is None:
                continue
            records.append(
                {
                    "record_id": payload.get("job_id") or report_dir.name,
                    "source": "saved_report",
                    "status": "completed",
                    "report_id": report_dir.name,
                    "relative_path": str(report_dir.relative_to(repo_root)),
                    "report_path": str((report_dir / "complete_report.md").relative_to(repo_root)) if (report_dir / "complete_report.md").exists() else None,
                    **payload,
                }
            )
    return records


def job_usage_record(job: dict[str, Any]) -> dict[str, Any] | None:
    summary = job.get("usage_summary")
    events = job.get("usage_events") or []
    if not summary and not events:
        return None

    metadata = {
        "job_id": job.get("job_id"),
        "ticker": job.get("ticker"),
        "trade_date": job.get("trade_date"),
        "workflow": job.get("workflow"),
        "provider": job.get("provider"),
        "quick_model": job.get("quick_model"),
        "deep_model": job.get("deep_model"),
    }
    payload = build_token_usage_payload(events, metadata)
    if summary:
        payload["summary"] = summary
    return {
        "record_id": job.get("job_id"),
        "source": "job",
        "status": job.get("status"),
        "report_id": None,
        "relative_path": None,
        "report_path": job.get("report_path"),
        "started_at": job.get("started_at"),
        "completed_at": job.get("completed_at"),
        **payload,
    }


def get_token_usage_payload(
    *,
    jobs: list[dict[str, Any]],
    saved_records_loader: Callable[[], list[dict[str, Any]]],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    dedupe_keys: set[str] = set()

    for record in saved_records_loader():
        key = record.get("job_id") or record.get("report_path") or record["record_id"]
        dedupe_keys.add(str(key))
        records.append(record)

    for job in jobs:
        if job.get("provider") != "opencode":
            continue
        record = job_usage_record(job)
        if record is None:
            continue
        key = record.get("job_id") or record.get("report_path") or record["record_id"]
        if str(key) in dedupe_keys:
            records = [existing for existing in records if str(existing.get("job_id") or existing.get("report_path") or existing["record_id"]) != str(key)]
        dedupe_keys.add(str(key))
        records.append(record)

    records.sort(
        key=lambda record: (
            (record.get("summary") or {}).get("completed_at_ms") or 0,
            (record.get("summary") or {}).get("started_at_ms") or 0,
            record.get("record_id") or "",
        ),
        reverse=True,
    )
    aggregate_events = [
        dict(event, record_id=record["record_id"], ticker=record.get("ticker"), trade_date=record.get("trade_date"))
        for record in records
        for event in (record.get("events") or [])
    ]
    aggregate = build_token_usage_payload(aggregate_events, {"provider": "opencode"})
    return {"summary": aggregate["summary"], "events": aggregate["events"], "records": records}
