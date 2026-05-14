from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any, Callable

from tradingagents.dataflows.utils import safe_ticker_component

from .service_helpers import PathsConfig, atomic_write_json, load_json_payload


def daily_runs_dir(reports_dir: Path, dirname: str) -> Path:
    return reports_dir / dirname


def daily_run_path(reports_dir: Path, dirname: str, trade_date: str) -> Path:
    return daily_runs_dir(reports_dir, dirname) / f"{trade_date}.json"


def default_daily_entry(
    ticker: str,
    trade_date: str,
    snapshot_loader: Callable[[str, str], dict[str, Any] | None],
) -> dict[str, Any]:
    safe_ticker = safe_ticker_component(ticker)
    snapshot = snapshot_loader(safe_ticker, trade_date)
    return {
        "ticker": safe_ticker,
        "trade_date": trade_date,
        "status": snapshot["status"] if snapshot else "pending",
        "rating": snapshot["rating"] if snapshot else None,
        "job_id": None,
        "report_path": snapshot["report_path"] if snapshot else None,
        "error": None,
        "started_at": None,
        "completed_at": snapshot["completed_at"] if snapshot else None,
    }


def write_daily_manifest(
    manifest: dict[str, Any],
    *,
    reports_dir: Path,
    dirname: str,
    lock: RLock,
) -> dict[str, Any]:
    with lock:
        daily_runs_dir(reports_dir, dirname).mkdir(parents=True, exist_ok=True)
        path = daily_run_path(reports_dir, dirname, manifest["trade_date"])
        manifest["updated_at"] = datetime.utcnow().isoformat() + "Z"
        atomic_write_json(path, manifest)
        return manifest


def new_daily_manifest(
    trade_date: str,
    *,
    source: str,
    default_daily_tickers: tuple[str, ...],
    daily_coverage_policy: tuple[dict[str, str], ...],
    snapshot_loader: Callable[[str, str], dict[str, Any] | None],
) -> dict[str, Any]:
    return {
        "trade_date": trade_date,
        "source": source,
        "policy": list(daily_coverage_policy),
        "tickers": [default_daily_entry(ticker, trade_date, snapshot_loader) for ticker in default_daily_tickers],
        "created_at": datetime.utcnow().isoformat() + "Z",
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }


def load_daily_manifest(
    trade_date: str,
    *,
    reports_dir: Path,
    dirname: str,
    lock: RLock,
    source: str,
    default_daily_tickers: tuple[str, ...],
    daily_coverage_policy: tuple[dict[str, str], ...],
    snapshot_loader: Callable[[str, str], dict[str, Any] | None],
) -> dict[str, Any]:
    with lock:
        path = daily_run_path(reports_dir, dirname, trade_date)
        if not path.exists():
            return new_daily_manifest(
                trade_date,
                source=source,
                default_daily_tickers=default_daily_tickers,
                daily_coverage_policy=daily_coverage_policy,
                snapshot_loader=snapshot_loader,
            )

        manifest, repaired = load_json_payload(path)
        if repaired:
            atomic_write_json(path, manifest)
        return manifest


def find_daily_entry(manifest: dict[str, Any], ticker: str) -> dict[str, Any]:
    safe_ticker = safe_ticker_component(ticker)
    for entry in manifest["tickers"]:
        if entry["ticker"] == safe_ticker:
            return entry
    raise ValueError(f"{safe_ticker} is not configured for daily coverage")


def manifest_summary(manifest: dict[str, Any]) -> dict[str, int]:
    summary = {"pending": 0, "queued": 0, "running": 0, "completed": 0, "failed": 0}
    for entry in manifest["tickers"]:
        summary[entry["status"]] = summary.get(entry["status"], 0) + 1
    summary["total"] = len(manifest["tickers"])
    return summary


def update_daily_run_job_state(
    trade_date: str,
    ticker: str,
    *,
    reports_dir: Path,
    dirname: str,
    lock: RLock,
    manifest_loader: Callable[[str], dict[str, Any]],
    manifest_writer: Callable[[dict[str, Any]], dict[str, Any]],
    status: str | None = None,
    job_id: str | None = None,
    rating: str | None = None,
    report_path: str | None = None,
    error: str | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
) -> None:
    with lock:
        path = daily_run_path(reports_dir, dirname, trade_date)
        if not path.exists():
            return

        manifest = manifest_loader(trade_date)
        entry = find_daily_entry(manifest, ticker)
        if status is not None:
            entry["status"] = status
        if job_id is not None:
            entry["job_id"] = job_id
        if rating is not None:
            entry["rating"] = rating
        if report_path is not None:
            entry["report_path"] = report_path
        if started_at is not None:
            entry["started_at"] = started_at
        if completed_at is not None:
            entry["completed_at"] = completed_at
        if error is not None or status == "failed":
            entry["error"] = error
        if status == "completed":
            entry["error"] = None
        manifest_writer(manifest)


def get_daily_watchlist(source: str, default_daily_tickers: tuple[str, ...], daily_coverage_policy: tuple[dict[str, str], ...], metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "source": source,
        "tickers": list(default_daily_tickers),
        "policy": list(daily_coverage_policy),
        "metadata": metadata or {},
    }


def prepare_daily_run(
    trade_date: str,
    *,
    lock: RLock,
    source: str,
    default_daily_tickers: tuple[str, ...],
    daily_coverage_policy: tuple[dict[str, str], ...],
    manifest_loader: Callable[[str], dict[str, Any]],
    manifest_writer: Callable[[dict[str, Any]], dict[str, Any]],
    snapshot_loader: Callable[[str, str], dict[str, Any] | None],
    get_daily_run_fn: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    with lock:
        manifest = manifest_loader(trade_date)
        manifest["policy"] = list(daily_coverage_policy)
        manifest["source"] = source
        known = {entry["ticker"]: entry for entry in manifest["tickers"]}
        tickers: list[dict[str, Any]] = []
        for ticker in default_daily_tickers:
            safe_ticker = safe_ticker_component(ticker)
            entry = known.get(safe_ticker, default_daily_entry(safe_ticker, trade_date, snapshot_loader))
            snapshot = snapshot_loader(safe_ticker, trade_date)
            if snapshot and entry["status"] != "running":
                entry.update(snapshot)
                entry["error"] = None
                entry["job_id"] = entry.get("job_id")
            tickers.append(entry)
        manifest["tickers"] = tickers
        manifest_writer(manifest)
        return get_daily_run_fn(trade_date)


def get_daily_run(trade_date: str, manifest_loader: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
    manifest = manifest_loader(trade_date)
    return {**manifest, "summary": manifest_summary(manifest)}


def queue_daily_run_entries(
    job_manager: Any,
    trade_date: str,
    *,
    lock: RLock,
    workflow_daily_coverage: str,
    provider: str,
    quick_model: str | None,
    deep_model: str | None,
    tickers: list[str] | None,
    retry_failed_only: bool,
    manifest_loader: Callable[[str], dict[str, Any]],
    manifest_writer: Callable[[dict[str, Any]], dict[str, Any]],
    prepare_daily_run_fn: Callable[[str], dict[str, Any]],
    get_daily_run_fn: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    with lock:
        prepare_daily_run_fn(trade_date)
        manifest_payload = manifest_loader(trade_date)
        selected = {safe_ticker_component(t) for t in tickers} if tickers else None
        queued: list[dict[str, Any]] = []

        for entry in manifest_payload["tickers"]:
            if selected and entry["ticker"] not in selected:
                continue
            if entry["status"] == "completed":
                continue
            if retry_failed_only and entry["status"] != "failed":
                continue
            if entry["status"] in {"queued", "running"}:
                continue

            job = job_manager.submit(
                entry["ticker"],
                trade_date,
                workflow_daily_coverage,
                provider,
                quick_model,
                deep_model,
            )
            entry["status"] = "queued"
            entry["job_id"] = job.job_id
            entry["error"] = None
            entry["started_at"] = None
            entry["completed_at"] = None
            queued.append({"ticker": entry["ticker"], "job_id": job.job_id})

        manifest_writer(manifest_payload)
        updated = get_daily_run_fn(trade_date)
        updated["queued_jobs"] = queued
        return updated
