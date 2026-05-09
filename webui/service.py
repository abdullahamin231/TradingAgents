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

from tradingagents.agents.utils.rating import parse_rating
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.llm_clients.model_catalog import get_model_options
from tradingagents.llm_clients.provider_urls import get_ollama_base_url
from tradingagents.reporting import save_complete_report

try:
    import markdown
except ModuleNotFoundError:  # pragma: no cover - exercised only in minimal envs
    markdown = None


load_dotenv()
load_dotenv(".env.enterprise", override=False)


REPO_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = REPO_ROOT / "reports"
OPENCODE_CONFIG_PATH = REPO_ROOT / "opencode.json"
DAILY_RUNS_DIRNAME = "daily_runs"
REPORTS_SYSTEM_DIRS = {"cache", "memory", DAILY_RUNS_DIRNAME, "_legacy_root_artifacts"}
DEFAULT_DAILY_TICKERS = (
    "MU","SNDK","MXL","LITE","AXTI","ICHR","AMD","SIMO","PBR.A","TSM","PBR","UCTT","SNEX","ASX","CRDO","DGELL","NVTS","TTE","COHU","BAC"
)
DAILY_COVERAGE_POLICY = (
    {"rating": "Buy", "action": "Allocate $5,000 into the ticker"},
    {"rating": "Sell", "action": "Sell off completely"},
    {"rating": "Underweight", "action": "Buy $2,000 more"},
    {"rating": "Overweight", "action": "Sell $2,000 and hold"},
    {"rating": "Hold", "action": "Hold the current position"},
)
WORKFLOW_ON_DEMAND = "analysis_on_demand"
WORKFLOW_DAILY_COVERAGE = "daily_coverage"
PROVIDER_OPTIONS = [
    {"label": "OpenCode", "value": "opencode"},
    {"label": "OpenAI", "value": "openai"},
    {"label": "Gemini", "value": "google"},
    {"label": "Anthropic", "value": "anthropic"},
    {"label": "xAI", "value": "xai"},
    {"label": "DeepSeek", "value": "deepseek"},
    {"label": "Qwen", "value": "qwen"},
    {"label": "GLM", "value": "glm"},
    {"label": "OpenRouter", "value": "openrouter"},
    {"label": "Azure OpenAI", "value": "azure"},
    {"label": "Ollama", "value": "ollama"},
]

_PROVIDER_DEFAULT_MODELS = {
    "openai": lambda mode: get_model_options("openai", mode)[0][1],
    "google": lambda mode: get_model_options("google", mode)[0][1],
    "anthropic": lambda mode: get_model_options("anthropic", mode)[0][1],
    "xai": lambda mode: get_model_options("xai", mode)[0][1],
    "deepseek": lambda mode: get_model_options("deepseek", mode)[0][1],
    "qwen": lambda mode: get_model_options("qwen", mode)[0][1],
    "glm": lambda mode: get_model_options("glm", mode)[0][1],
    "openrouter": lambda mode: DEFAULT_CONFIG["deep_think_llm"],
    "azure": lambda mode: DEFAULT_CONFIG["deep_think_llm"],
    "ollama": lambda mode: "llama3.1",
}
_SECTION_TITLES = {
    "market_report": "Market Analysis",
    "sentiment_report": "Social Sentiment",
    "news_report": "News Analysis",
    "fundamentals_report": "Fundamentals Analysis",
    "investment_plan": "Research Team Decision",
    "trader_investment_decision": "Trader Plan",
    "final_trade_decision": "Portfolio Decision",
}


def _ensure_reports_layout() -> None:
    """Keep UI-owned report artifacts under predictable subdirectories."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    for path in REPORTS_DIR.glob("*.md"):
        target_dir = _legacy_markdown_target_dir(path.name)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / path.name
        if target_path.exists():
            continue
        path.replace(target_path)


def _legacy_markdown_target_dir(filename: str) -> Path:
    stem = Path(filename).stem
    ticker_token = stem.split("_", 1)[0].strip().upper()
    if ticker_token and 1 <= len(ticker_token) <= 5:
        try:
            safe_ticker = safe_ticker_component(ticker_token)
        except ValueError:
            safe_ticker = None
        if safe_ticker == ticker_token:
            return REPORTS_DIR / safe_ticker / "legacy"
    return REPORTS_DIR / "_legacy_root_artifacts"


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


def get_provider_default_model(provider: str, mode: str = "deep") -> str:
    provider_lower = provider.lower()
    if provider_lower == "opencode":
        return _load_opencode_model() or "opencode"

    default_model_factory = _PROVIDER_DEFAULT_MODELS.get(provider_lower)
    if default_model_factory is not None:
        return default_model_factory(mode)

    return DEFAULT_CONFIG["deep_think_llm"]


def build_run_config(
    provider: str,
    quick_model: str | None = None,
    deep_model: str | None = None,
) -> dict[str, Any]:
    _ensure_reports_layout()
    config = copy.deepcopy(DEFAULT_CONFIG)
    provider_lower = provider.lower()
    resolved_quick_model = (
        quick_model.strip()
        if isinstance(quick_model, str) and quick_model.strip()
        else get_provider_default_model(provider_lower, "quick")
    )
    resolved_deep_model = (
        deep_model.strip()
        if isinstance(deep_model, str) and deep_model.strip()
        else get_provider_default_model(provider_lower, "deep")
    )

    if provider_lower == "opencode":
        resolved_quick_model = resolved_deep_model = (
            deep_model.strip()
            if isinstance(deep_model, str) and deep_model.strip()
            else quick_model.strip()
            if isinstance(quick_model, str) and quick_model.strip()
            else get_provider_default_model(provider_lower, "deep")
        )

    config["llm_provider"] = provider_lower
    config["deep_think_llm"] = resolved_deep_model
    config["quick_think_llm"] = resolved_quick_model
    config["results_dir"] = str(REPORTS_DIR)
    config["data_cache_dir"] = str(REPORTS_DIR / "cache")
    config["memory_log_path"] = str(REPORTS_DIR / "memory" / "trading_memory.md")
    config["max_debate_rounds"] = 1
    config["backend_url"] = get_ollama_base_url() if provider_lower == "ollama" else None
    config["data_vendors"] = {
        "core_stock_apis": "yfinance",
        "technical_indicators": "yfinance",
        "fundamental_data": "yfinance",
        "news_data": "yfinance",
    }
    return config


def build_opencode_config() -> dict[str, Any]:
    return build_run_config("opencode")


def list_llm_providers() -> list[dict[str, Any]]:
    providers = []
    for option in PROVIDER_OPTIONS:
        provider = option["value"]
        providers.append(
            {
                "label": option["label"],
                "value": provider,
                "default_quick_model": get_provider_default_model(provider, "quick"),
                "default_deep_model": get_provider_default_model(provider, "deep"),
                "note": (
                    "Azure, OpenRouter, and Ollama may require a custom deployment/model name."
                    if provider in {"azure", "openrouter", "ollama"}
                    else ""
                ),
            }
        )
    return providers


@dataclass
class JobState:
    job_id: str
    ticker: str
    trade_date: str
    workflow: str = WORKFLOW_ON_DEMAND
    provider: str = "opencode"
    quick_model: str | None = None
    deep_model: str | None = None
    status: str = "queued"
    decision: str | None = None
    report_path: str | None = None
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    started_at: str | None = None
    completed_at: str | None = None


class TradingJobManager:
    def __init__(self, max_workers: int = 4, max_history: int = 100) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="trading-web")
        self._jobs: dict[str, JobState] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()
        self._max_history = max_history

    def submit(
        self,
        ticker: str,
        trade_date: str,
        workflow: str = WORKFLOW_ON_DEMAND,
        provider: str = "opencode",
        quick_model: str | None = None,
        deep_model: str | None = None,
    ) -> JobState:
        safe_ticker = safe_ticker_component(ticker.strip().upper())
        provider_lower = provider.strip().lower()
        resolved_quick_model = (
            quick_model.strip()
            if isinstance(quick_model, str) and quick_model.strip()
            else get_provider_default_model(provider_lower, "quick")
        )
        resolved_deep_model = (
            deep_model.strip()
            if isinstance(deep_model, str) and deep_model.strip()
            else get_provider_default_model(provider_lower, "deep")
        )

        if provider_lower == "opencode":
            resolved_quick_model = resolved_deep_model = (
                deep_model.strip()
                if isinstance(deep_model, str) and deep_model.strip()
                else quick_model.strip()
                if isinstance(quick_model, str) and quick_model.strip()
                else get_provider_default_model(provider_lower, "deep")
            )
        job = JobState(
            job_id=uuid.uuid4().hex,
            ticker=safe_ticker,
            trade_date=trade_date,
            workflow=workflow,
            provider=provider_lower,
            quick_model=resolved_quick_model,
            deep_model=resolved_deep_model,
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
        _update_daily_run_job_state(
            job.trade_date,
            job.ticker,
            status="running" if job.workflow == WORKFLOW_DAILY_COVERAGE else None,
            job_id=job.job_id if job.workflow == WORKFLOW_DAILY_COVERAGE else None,
            started_at=job.started_at if job.workflow == WORKFLOW_DAILY_COVERAGE else None,
        )

        try:
            config = build_run_config(job.provider, job.quick_model, job.deep_model)
            graph = TradingAgentsGraph(debug=False, config=config)
            final_state, decision = graph.propagate(job.ticker, job.trade_date)

            export_dir = (
                REPORTS_DIR
                / job.ticker
                / "SavedReports"
                / f"{job.trade_date}_{job.job_id[:8]}"
            )
            complete_report_path = save_complete_report(final_state, job.ticker, export_dir)

            with self._lock:
                job.status = "completed"
                job.decision = decision
                job.report_path = str(complete_report_path.relative_to(REPO_ROOT))
                job.completed_at = datetime.utcnow().isoformat() + "Z"
            if job.workflow == WORKFLOW_DAILY_COVERAGE:
                _update_daily_run_job_state(
                    job.trade_date,
                    job.ticker,
                    status="completed",
                    job_id=job.job_id,
                    rating=parse_rating(decision),
                    report_path=job.report_path,
                    started_at=job.started_at,
                    completed_at=job.completed_at,
                    error=None,
                )
        except Exception as exc:  # pragma: no cover - surfaced to API
            with self._lock:
                job.status = "failed"
                job.error = str(exc)
                job.completed_at = datetime.utcnow().isoformat() + "Z"
            if job.workflow == WORKFLOW_DAILY_COVERAGE:
                _update_daily_run_job_state(
                    job.trade_date,
                    job.ticker,
                    status="failed",
                    job_id=job.job_id,
                    started_at=job.started_at,
                    completed_at=job.completed_at,
                    error=str(exc),
                )


def list_report_tickers() -> list[dict[str, Any]]:
    _ensure_reports_layout()
    tickers: list[dict[str, Any]] = []
    if not REPORTS_DIR.exists():
        return tickers

    for path in sorted(REPORTS_DIR.iterdir()):
        if not path.is_dir() or path.name in REPORTS_SYSTEM_DIRS:
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


def _daily_runs_dir() -> Path:
    return REPORTS_DIR / DAILY_RUNS_DIRNAME


def _daily_run_path(trade_date: str) -> Path:
    return _daily_runs_dir() / f"{trade_date}.json"


def _report_log_path(ticker: str, trade_date: str) -> Path:
    safe_ticker = safe_ticker_component(ticker)
    return REPORTS_DIR / safe_ticker / "TradingAgentsStrategy_logs" / f"full_states_log_{trade_date}.json"


def _saved_report_snapshot(ticker: str, trade_date: str) -> dict[str, Any] | None:
    safe_ticker = safe_ticker_component(ticker)
    log_path = _report_log_path(safe_ticker, trade_date)
    if not log_path.exists():
        return None

    payload = json.loads(log_path.read_text(encoding="utf-8"))
    decision_text = payload.get("final_trade_decision", "")
    return {
        "status": "completed",
        "rating": parse_rating(decision_text),
        "report_path": str(log_path.relative_to(REPO_ROOT)),
        "completed_at": datetime.fromtimestamp(log_path.stat().st_mtime).isoformat(),
    }


def _default_daily_entry(ticker: str, trade_date: str) -> dict[str, Any]:
    safe_ticker = safe_ticker_component(ticker)
    snapshot = _saved_report_snapshot(safe_ticker, trade_date)
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


def _write_daily_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    _daily_runs_dir().mkdir(parents=True, exist_ok=True)
    path = _daily_run_path(manifest["trade_date"])
    manifest["updated_at"] = datetime.utcnow().isoformat() + "Z"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def _new_daily_manifest(trade_date: str) -> dict[str, Any]:
    return {
        "trade_date": trade_date,
        "source": "hardcoded",
        "policy": list(DAILY_COVERAGE_POLICY),
        "tickers": [_default_daily_entry(ticker, trade_date) for ticker in DEFAULT_DAILY_TICKERS],
        "created_at": datetime.utcnow().isoformat() + "Z",
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }


def _load_daily_manifest(trade_date: str) -> dict[str, Any]:
    path = _daily_run_path(trade_date)
    if not path.exists():
        return _new_daily_manifest(trade_date)
    return json.loads(path.read_text(encoding="utf-8"))


def _find_daily_entry(manifest: dict[str, Any], ticker: str) -> dict[str, Any]:
    safe_ticker = safe_ticker_component(ticker)
    for entry in manifest["tickers"]:
        if entry["ticker"] == safe_ticker:
            return entry
    raise ValueError(f"{safe_ticker} is not configured for daily coverage")


def _manifest_summary(manifest: dict[str, Any]) -> dict[str, int]:
    summary = {"pending": 0, "queued": 0, "running": 0, "completed": 0, "failed": 0}
    for entry in manifest["tickers"]:
        summary[entry["status"]] = summary.get(entry["status"], 0) + 1
    summary["total"] = len(manifest["tickers"])
    return summary


def _update_daily_run_job_state(
    trade_date: str,
    ticker: str,
    *,
    status: str | None = None,
    job_id: str | None = None,
    rating: str | None = None,
    report_path: str | None = None,
    error: str | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
) -> None:
    path = _daily_run_path(trade_date)
    if not path.exists():
        return

    manifest = _load_daily_manifest(trade_date)
    entry = _find_daily_entry(manifest, ticker)
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
    _write_daily_manifest(manifest)


def get_daily_watchlist() -> dict[str, Any]:
    return {
        "source": "hardcoded",
        "tickers": list(DEFAULT_DAILY_TICKERS),
        "policy": list(DAILY_COVERAGE_POLICY),
    }


def prepare_daily_run(trade_date: str) -> dict[str, Any]:
    manifest = _load_daily_manifest(trade_date)
    manifest["policy"] = list(DAILY_COVERAGE_POLICY)
    manifest["source"] = "hardcoded"
    known = {entry["ticker"]: entry for entry in manifest["tickers"]}
    tickers: list[dict[str, Any]] = []
    for ticker in DEFAULT_DAILY_TICKERS:
        safe_ticker = safe_ticker_component(ticker)
        entry = known.get(safe_ticker, _default_daily_entry(safe_ticker, trade_date))
        snapshot = _saved_report_snapshot(safe_ticker, trade_date)
        if snapshot and entry["status"] != "running":
            entry.update(snapshot)
            entry["error"] = None
            entry["job_id"] = entry.get("job_id")
        tickers.append(entry)
    manifest["tickers"] = tickers
    _write_daily_manifest(manifest)
    return get_daily_run(trade_date)


def get_daily_run(trade_date: str) -> dict[str, Any]:
    manifest = _load_daily_manifest(trade_date)
    return {
        **manifest,
        "summary": _manifest_summary(manifest),
    }


def queue_daily_run_entries(
    job_manager: TradingJobManager,
    trade_date: str,
    *,
    provider: str = "opencode",
    quick_model: str | None = None,
    deep_model: str | None = None,
    tickers: list[str] | None = None,
    retry_failed_only: bool = False,
) -> dict[str, Any]:
    manifest = prepare_daily_run(trade_date)
    manifest_payload = _load_daily_manifest(trade_date)
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
            WORKFLOW_DAILY_COVERAGE,
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

    _write_daily_manifest(manifest_payload)
    updated = get_daily_run(trade_date)
    updated["queued_jobs"] = queued
    return updated
