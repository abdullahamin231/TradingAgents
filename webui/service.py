from __future__ import annotations

import copy
import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.dataflows.utils import safe_ticker_component

try:
    import markdown
except ModuleNotFoundError:  # pragma: no cover - exercised only in minimal envs
    markdown = None


load_dotenv()
load_dotenv(".env.enterprise", override=False)


REPO_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = REPO_ROOT / "reports"
OPENCODE_CONFIG_PATH = REPO_ROOT / "opencode.json"
_SECTION_TITLES = {
    "market_report": "Market Analysis",
    "sentiment_report": "Social Sentiment",
    "news_report": "News Analysis",
    "fundamentals_report": "Fundamentals Analysis",
    "investment_plan": "Research Team Decision",
    "trader_investment_decision": "Trader Plan",
    "final_trade_decision": "Portfolio Decision",
}


def _markdown_to_html(text: str) -> str:
    if markdown is None:
        return f"<pre>{escape(text or '')}</pre>"
    return markdown.markdown(
        text or "",
        extensions=["tables", "fenced_code", "sane_lists", "toc"],
    )


def _load_opencode_model() -> str | None:
    if not OPENCODE_CONFIG_PATH.exists():
        return None

    try:
        payload = json.loads(OPENCODE_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    model = payload.get("model")
    return model if isinstance(model, str) and model.strip() else None


def build_opencode_config() -> dict[str, Any]:
    config = copy.deepcopy(DEFAULT_CONFIG)
    opencode_model = _load_opencode_model() or "opencode"

    config["llm_provider"] = "opencode"
    config["deep_think_llm"] = opencode_model
    config["quick_think_llm"] = opencode_model
    config["results_dir"] = str(REPORTS_DIR)
    config["data_cache_dir"] = str(REPORTS_DIR / "cache")
    config["memory_log_path"] = str(REPORTS_DIR / "memory" / "trading_memory.md")
    config["max_debate_rounds"] = 1
    config["data_vendors"] = {
        "core_stock_apis": "yfinance",
        "technical_indicators": "yfinance",
        "fundamental_data": "yfinance",
        "news_data": "yfinance",
    }
    return config


@dataclass
class JobState:
    job_id: str
    ticker: str
    trade_date: str
    status: str = "queued"
    decision: str | None = None
    report_path: str | None = None
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    started_at: str | None = None
    completed_at: str | None = None
    opencode_model: str | None = None


class TradingJobManager:
    def __init__(self, max_workers: int = 4, max_history: int = 100) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="trading-web")
        self._jobs: dict[str, JobState] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()
        self._max_history = max_history

    def submit(self, ticker: str, trade_date: str) -> JobState:
        safe_ticker = safe_ticker_component(ticker.strip().upper())
        job = JobState(
            job_id=uuid.uuid4().hex,
            ticker=safe_ticker,
            trade_date=trade_date,
            opencode_model=_load_opencode_model(),
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._order.insert(0, job.job_id)
            self._trim_history_locked()

        self._executor.submit(self._run_job, job.job_id)
        return job

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(self._jobs[job_id]) for job_id in self._order]

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return asdict(job) if job else None

    def _trim_history_locked(self) -> None:
        if len(self._order) <= self._max_history:
            return

        for stale_id in self._order[self._max_history:]:
            self._jobs.pop(stale_id, None)
        del self._order[self._max_history:]

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "running"
            job.started_at = datetime.utcnow().isoformat() + "Z"

        try:
            config = build_opencode_config()
            graph = TradingAgentsGraph(debug=False, config=config)
            _, decision = graph.propagate(job.ticker, job.trade_date)

            report_path = (
                REPORTS_DIR
                / job.ticker
                / "TradingAgentsStrategy_logs"
                / f"full_states_log_{job.trade_date}.json"
            )

            with self._lock:
                job.status = "completed"
                job.decision = decision
                job.report_path = str(report_path.relative_to(REPO_ROOT))
                job.completed_at = datetime.utcnow().isoformat() + "Z"
        except Exception as exc:  # pragma: no cover - surfaced to API
            with self._lock:
                job.status = "failed"
                job.error = str(exc)
                job.completed_at = datetime.utcnow().isoformat() + "Z"


def list_report_tickers() -> list[dict[str, Any]]:
    tickers: list[dict[str, Any]] = []
    if not REPORTS_DIR.exists():
        return tickers

    for path in sorted(REPORTS_DIR.iterdir()):
        if not path.is_dir() or path.name in {"cache", "memory"}:
            continue

        logs = list_report_runs(path.name)
        tickers.append(
            {
                "ticker": path.name,
                "report_count": len(logs),
                "latest_trade_date": logs[0]["trade_date"] if logs else None,
            }
        )

    return tickers


def list_report_runs(ticker: str) -> list[dict[str, Any]]:
    safe_ticker = safe_ticker_component(ticker)
    log_dir = REPORTS_DIR / safe_ticker / "TradingAgentsStrategy_logs"
    if not log_dir.exists():
        return []

    runs: list[dict[str, Any]] = []
    for path in sorted(log_dir.glob("full_states_log_*.json"), reverse=True):
        trade_date = path.stem.removeprefix("full_states_log_")
        runs.append(
            {
                "ticker": safe_ticker,
                "trade_date": trade_date,
                "file_name": path.name,
                "relative_path": str(path.relative_to(REPO_ROOT)),
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
            }
        )
    return runs


def load_report(ticker: str, trade_date: str) -> dict[str, Any]:
    safe_ticker = safe_ticker_component(ticker)
    log_path = (
        REPORTS_DIR
        / safe_ticker
        / "TradingAgentsStrategy_logs"
        / f"full_states_log_{trade_date}.json"
    )
    payload = json.loads(log_path.read_text(encoding="utf-8"))

    sections = []
    for key, title in _SECTION_TITLES.items():
        value = payload.get(key)
        if not value:
            continue
        sections.append(
            {
                "key": key,
                "title": title,
                "markdown": value,
                "html": _markdown_to_html(value),
            }
        )

    debate_sections = []
    investment = payload.get("investment_debate_state") or {}
    for key, title in (
        ("bull_history", "Bull Researcher"),
        ("bear_history", "Bear Researcher"),
        ("judge_decision", "Research Manager"),
    ):
        if investment.get(key):
            debate_sections.append(
                {
                    "group": "research",
                    "key": key,
                    "title": title,
                    "markdown": investment[key],
                    "html": _markdown_to_html(investment[key]),
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
            debate_sections.append(
                {
                    "group": "risk",
                    "key": key,
                    "title": title,
                    "markdown": risk[key],
                    "html": _markdown_to_html(risk[key]),
                }
            )

    return {
        "ticker": safe_ticker,
        "trade_date": payload.get("trade_date", trade_date),
        "company_of_interest": payload.get("company_of_interest", safe_ticker),
        "sections": sections,
        "debates": debate_sections,
        "raw": payload,
    }
