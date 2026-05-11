from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from tradingagents.agents.utils.rating import parse_rating
from tradingagents.dataflows.utils import safe_ticker_component

from .service_helpers import PathsConfig, markdown_to_html, normalize_markdown_text


def ensure_reports_layout(paths: PathsConfig, legacy_dirnames: set[str]) -> None:
    paths.reports_dir.mkdir(parents=True, exist_ok=True)

    for path in paths.reports_dir.glob("*.md"):
        target_dir = legacy_markdown_target_dir(paths.reports_dir, path.name)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / path.name
        if target_path.exists():
            continue
        path.replace(target_path)


def legacy_markdown_target_dir(reports_dir: Path, filename: str) -> Path:
    stem = Path(filename).stem
    ticker_token = stem.split("_", 1)[0].strip().upper()
    if ticker_token and 1 <= len(ticker_token) <= 5:
        try:
            safe_ticker = safe_ticker_component(ticker_token)
        except ValueError:
            safe_ticker = None
        if safe_ticker == ticker_token:
            return reports_dir / safe_ticker / "legacy"
    return reports_dir / "_legacy_root_artifacts"


def list_report_tickers(paths: PathsConfig, system_dirs: set[str], list_report_runs_fn: Callable[[str], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    ensure_reports_layout(paths, system_dirs)
    tickers: list[dict[str, Any]] = []
    if not paths.reports_dir.exists():
        return tickers

    for path in sorted(paths.reports_dir.iterdir()):
        if not path.is_dir() or path.name in system_dirs:
            continue

        logs = list_report_runs_fn(path.name)
        tickers.append(
            {
                "ticker": path.name,
                "report_count": len(logs),
                "latest_trade_date": logs[0]["trade_date"] if logs else None,
            }
        )

    return tickers


def list_report_runs(
    ticker: str,
    paths: PathsConfig,
    saved_report_id_pattern,
) -> list[dict[str, Any]]:
    safe_ticker = safe_ticker_component(ticker)
    saved_runs = list_saved_report_runs(safe_ticker, paths, saved_report_id_pattern)
    if saved_runs:
        return saved_runs
    return list_legacy_report_runs(safe_ticker, paths)


def list_saved_report_runs(safe_ticker: str, paths: PathsConfig, saved_report_id_pattern) -> list[dict[str, Any]]:
    saved_dir = paths.reports_dir / safe_ticker / "SavedReports"
    if not saved_dir.exists():
        return []

    runs: list[dict[str, Any]] = []
    for path in sorted(
        (candidate for candidate in saved_dir.iterdir() if candidate.is_dir()),
        key=lambda candidate: (candidate.name, candidate.stat().st_mtime),
        reverse=True,
    ):
        report_id = path.name
        if not saved_report_id_pattern.fullmatch(report_id):
            continue

        complete_report = path / "complete_report.md"
        trade_date, _, report_hash = report_id.partition("_")
        relative_dir = path.relative_to(paths.repo_root)
        document_count = sum(1 for _ in path.rglob("*.md"))
        runs.append(
            {
                "ticker": safe_ticker,
                "report_id": report_id,
                "trade_date": trade_date,
                "report_hash": report_hash or None,
                "file_name": complete_report.name if complete_report.exists() else path.name,
                "relative_path": str(relative_dir),
                "report_path": str(complete_report.relative_to(paths.repo_root)) if complete_report.exists() else None,
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
                "document_count": document_count,
                "source": "saved_report",
            }
        )
    return runs


def list_legacy_report_runs(safe_ticker: str, paths: PathsConfig) -> list[dict[str, Any]]:
    log_dir = paths.reports_dir / safe_ticker / "TradingAgentsStrategy_logs"
    if not log_dir.exists():
        return []

    runs: list[dict[str, Any]] = []
    for path in sorted(log_dir.glob("full_states_log_*.json"), reverse=True):
        trade_date = path.stem.removeprefix("full_states_log_")
        runs.append(
            {
                "ticker": safe_ticker,
                "trade_date": trade_date,
                "report_id": trade_date,
                "file_name": path.name,
                "relative_path": str(path.relative_to(paths.repo_root)),
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
                "document_count": 1,
                "source": "legacy_log",
            }
        )
    return runs


def load_report(
    ticker: str,
    report_id: str,
    paths: PathsConfig,
    saved_report_id_pattern,
    saved_report_document_order: dict[str, int],
    saved_report_document_titles: dict[str, str],
    section_titles: dict[str, str],
) -> dict[str, Any]:
    safe_ticker = safe_ticker_component(ticker)
    if saved_report_id_pattern.fullmatch(report_id):
        report_dir = paths.reports_dir / safe_ticker / "SavedReports" / report_id
        if report_dir.exists():
            return load_saved_report(safe_ticker, report_dir, paths, saved_report_document_order, saved_report_document_titles)
    return load_legacy_report(safe_ticker, report_id, paths, section_titles)


def load_saved_report(
    safe_ticker: str,
    report_dir: Path,
    paths: PathsConfig,
    document_order: dict[str, int],
    document_titles: dict[str, str],
) -> dict[str, Any]:
    report_id = report_dir.name
    trade_date, _, report_hash = report_id.partition("_")
    documents = []
    for path in sorted(
        report_dir.rglob("*.md"),
        key=lambda candidate: (
            document_order.get(candidate.relative_to(report_dir).as_posix(), 999),
            candidate.relative_to(report_dir).as_posix(),
        ),
    ):
        relative_path = path.relative_to(report_dir).as_posix()
        markdown_text = normalize_markdown_text(path.read_text(encoding="utf-8"))
        documents.append(
            {
                "path": relative_path,
                "title": saved_report_document_title(relative_path, document_titles),
                "markdown": markdown_text,
                "html": markdown_to_html(markdown_text),
                "kind": "saved_report_markdown",
            }
        )

    if not documents:
        raise FileNotFoundError(report_dir / "complete_report.md")

    return {
        "ticker": safe_ticker,
        "trade_date": trade_date,
        "report_id": report_id,
        "report_hash": report_hash or None,
        "company_of_interest": safe_ticker,
        "source": "saved_report",
        "relative_path": str(report_dir.relative_to(paths.repo_root)),
        "report_path": str((report_dir / "complete_report.md").relative_to(paths.repo_root)),
        "documents": documents,
        "default_document": "complete_report.md" if any(document["path"] == "complete_report.md" for document in documents) else documents[0]["path"],
        "sections": [],
        "debates": [],
        "raw": None,
    }


def saved_report_document_title(relative_path: str, document_titles: dict[str, str]) -> str:
    known_title = document_titles.get(relative_path)
    if known_title:
        return known_title
    path = Path(relative_path)
    return path.stem.replace("_", " ").title()


def load_legacy_report(
    safe_ticker: str,
    trade_date: str,
    paths: PathsConfig,
    section_titles: dict[str, str],
) -> dict[str, Any]:
    log_path = paths.reports_dir / safe_ticker / "TradingAgentsStrategy_logs" / f"full_states_log_{trade_date}.json"
    payload = json.loads(log_path.read_text(encoding="utf-8"))

    sections = []
    for key, title in section_titles.items():
        value = payload.get(key)
        if not value:
            continue
        normalized_value = normalize_markdown_text(value)
        sections.append(
            {
                "key": key,
                "title": title,
                "markdown": normalized_value,
                "html": markdown_to_html(normalized_value),
            }
        )

    debate_sections = build_legacy_debate_sections(payload)
    documents = [
        {
            "path": f"legacy/{section['key']}.md",
            "title": section["title"],
            "markdown": section["markdown"],
            "html": section["html"],
            "kind": "legacy_section",
        }
        for section in sections
    ]
    documents.extend(
        {
            "path": f"legacy/{section['group']}_{section['key']}.md",
            "title": section["title"],
            "markdown": section["markdown"],
            "html": section["html"],
            "kind": "legacy_debate",
        }
        for section in debate_sections
    )

    return {
        "ticker": safe_ticker,
        "trade_date": payload.get("trade_date", trade_date),
        "report_id": trade_date,
        "company_of_interest": payload.get("company_of_interest", safe_ticker),
        "source": "legacy_log",
        "relative_path": str(log_path.relative_to(paths.repo_root)),
        "report_path": str(log_path.relative_to(paths.repo_root)),
        "documents": documents,
        "default_document": documents[0]["path"] if documents else None,
        "sections": sections,
        "debates": debate_sections,
        "raw": payload,
    }


def build_legacy_debate_sections(payload: dict[str, Any]) -> list[dict[str, Any]]:
    debate_sections = []
    investment = payload.get("investment_debate_state") or {}
    for key, title in (
        ("bull_history", "Bull Researcher"),
        ("bear_history", "Bear Researcher"),
        ("judge_decision", "Research Manager"),
    ):
        if investment.get(key):
            normalized_value = normalize_markdown_text(investment[key])
            debate_sections.append(
                {
                    "group": "research",
                    "key": key,
                    "title": title,
                    "markdown": normalized_value,
                    "html": markdown_to_html(normalized_value),
                }
            )

    risk = payload.get("risk_debate_state") or {}
    for key, title in (
        ("aggressive_history", "Aggressive Analyst"),
        ("neutral_history", "Neutral Analyst"),
        ("conservative_history", "Conservative Analyst"),
        ("judge_decision", "Portfolio Manager"),
    ):
        if risk.get(key):
            normalized_value = normalize_markdown_text(risk[key])
            debate_sections.append(
                {
                    "group": "risk",
                    "key": key,
                    "title": title,
                    "markdown": normalized_value,
                    "html": markdown_to_html(normalized_value),
                }
            )
    return debate_sections


def report_log_path(ticker: str, trade_date: str, reports_dir: Path) -> Path:
    safe_ticker = safe_ticker_component(ticker)
    return reports_dir / safe_ticker / "TradingAgentsStrategy_logs" / f"full_states_log_{trade_date}.json"


def saved_report_snapshot(ticker: str, trade_date: str, paths: PathsConfig) -> dict[str, Any] | None:
    safe_ticker = safe_ticker_component(ticker)
    log_path = report_log_path(safe_ticker, trade_date, paths.reports_dir)
    if not log_path.exists():
        return None

    payload = json.loads(log_path.read_text(encoding="utf-8"))
    decision_text = payload.get("final_trade_decision", "")
    return {
        "status": "completed",
        "rating": parse_rating(decision_text),
        "report_path": str(log_path.relative_to(paths.repo_root)),
        "completed_at": datetime.fromtimestamp(log_path.stat().st_mtime).isoformat(),
    }
