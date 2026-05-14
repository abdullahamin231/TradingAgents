from __future__ import annotations

import copy
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from tradingagents.agents.utils.rating import parse_rating
from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.llm_clients.model_catalog import get_model_options
from tradingagents.llm_clients.provider_urls import get_ollama_base_url
from tradingagents.reporting import save_complete_report

from . import service_daily, service_reports
from .seeking_alpha import fetch_seeking_alpha_watchlist
from .service_helpers import PathsConfig, SAVED_REPORT_ID_PATTERN, TOKEN_USAGE_FILENAME, atomic_write_json, markdown_to_html, token_usage_path
from .service_usage import TokenUsageCollector, get_token_usage_payload, iter_saved_usage_records


load_dotenv()
load_dotenv(".env.enterprise", override=False)

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = REPO_ROOT / "reports"
OPENCODE_CONFIG_PATH = REPO_ROOT / "opencode.json"
DAILY_RUNS_DIRNAME = "daily_runs"
REPORTS_SYSTEM_DIRS = {"cache", "memory", DAILY_RUNS_DIRNAME, "_legacy_root_artifacts"}
_daily_manifest_lock = threading.RLock()
OPENCODE_DEFAULT_QUICK_MODEL = "openai/gpt-5.4-mini"
OPENCODE_DEFAULT_DEEP_MODEL = "openai/gpt-5.4"
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
    "openrouter": lambda mode: DEFAULT_CONFIG["quick_think_llm"] if mode == "quick" else DEFAULT_CONFIG["deep_think_llm"],
    "azure": lambda mode: DEFAULT_CONFIG["quick_think_llm"] if mode == "quick" else DEFAULT_CONFIG["deep_think_llm"],
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
_SAVED_REPORT_DOCUMENT_ORDER = {
    "complete_report.md": 0,
    "1_analysts/market.md": 10,
    "1_analysts/sentiment.md": 11,
    "1_analysts/news.md": 12,
    "1_analysts/fundamentals.md": 13,
    "1_analysts/market_sources.md": 14,
    "1_analysts/sentiment_sources.md": 15,
    "1_analysts/news_sources.md": 16,
    "1_analysts/fundamentals_sources.md": 17,
    "2_research/bull.md": 20,
    "2_research/bear.md": 21,
    "2_research/manager.md": 22,
    "3_trading/trader.md": 30,
    "4_risk/aggressive.md": 40,
    "4_risk/neutral.md": 41,
    "4_risk/conservative.md": 42,
    "5_portfolio/decision.md": 50,
}
_SAVED_REPORT_DOCUMENT_TITLES = {
    "complete_report.md": "Complete Report",
    "1_analysts/market.md": "Market Analyst",
    "1_analysts/sentiment.md": "Social Analyst",
    "1_analysts/news.md": "News Analyst",
    "1_analysts/fundamentals.md": "Fundamentals Analyst",
    "1_analysts/market_sources.md": "Market Analyst Sources",
    "1_analysts/sentiment_sources.md": "Social Analyst Sources",
    "1_analysts/news_sources.md": "News Analyst Sources",
    "1_analysts/fundamentals_sources.md": "Fundamentals Analyst Sources",
    "2_research/bull.md": "Bull Researcher",
    "2_research/bear.md": "Bear Researcher",
    "2_research/manager.md": "Research Manager",
    "3_trading/trader.md": "Trader",
    "4_risk/aggressive.md": "Aggressive Analyst",
    "4_risk/neutral.md": "Neutral Analyst",
    "4_risk/conservative.md": "Conservative Analyst",
    "5_portfolio/decision.md": "Portfolio Manager Decision",
}


@dataclass
class JobState:
    job_id: str
    ticker: str
    trade_date: str
    workflow: str = WORKFLOW_ON_DEMAND
    provider: str = "opencode"
    quick_model: str = ""
    deep_model: str = ""
    status: str = "queued"
    decision: str | None = None
    report_path: str | None = None
    usage_summary: dict[str, Any] | None = None
    usage_events: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    started_at: str | None = None
    completed_at: str | None = None


def _paths() -> PathsConfig:
    return PathsConfig(repo_root=REPO_ROOT, reports_dir=REPORTS_DIR)


def _daily_watchlist_cache_dir() -> Path:
    return REPO_ROOT / "webui_artifacts" / "seeking_alpha_watchlist"


def _resolve_daily_watchlist(force_refresh: bool = False) -> dict[str, Any]:
    payload = fetch_seeking_alpha_watchlist(
        cache_dir=_daily_watchlist_cache_dir(),
        default_tickers=DEFAULT_DAILY_TICKERS,
        force_refresh=force_refresh,
    )
    return payload.to_payload()


def _ensure_reports_layout() -> None:
    service_reports.ensure_reports_layout(_paths(), REPORTS_SYSTEM_DIRS)


def _markdown_to_html(text: str) -> str:
    return markdown_to_html(text)


def _load_opencode_models() -> tuple[str | None, str | None]:
    if not OPENCODE_CONFIG_PATH.exists():
        return None, None
    try:
        payload = json.loads(OPENCODE_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None

    shared_model = payload.get("model")
    quick_model = payload.get("quick_model")
    deep_model = payload.get("deep_model")
    resolved_shared = shared_model.strip() if isinstance(shared_model, str) and shared_model.strip() else None
    resolved_quick = quick_model.strip() if isinstance(quick_model, str) and quick_model.strip() else resolved_shared
    resolved_deep = deep_model.strip() if isinstance(deep_model, str) and deep_model.strip() else resolved_shared
    return resolved_quick, resolved_deep


def get_provider_default_model(provider: str, mode: str = "deep") -> str:
    provider_lower = provider.lower()
    if provider_lower == "opencode":
        opencode_quick_model, opencode_deep_model = _load_opencode_models()
        return opencode_quick_model or OPENCODE_DEFAULT_QUICK_MODEL if mode == "quick" else opencode_deep_model or OPENCODE_DEFAULT_DEEP_MODEL

    default_model_factory = _PROVIDER_DEFAULT_MODELS.get(provider_lower)
    if default_model_factory is not None:
        return default_model_factory(mode)
    return DEFAULT_CONFIG["quick_think_llm"] if mode == "quick" else DEFAULT_CONFIG["deep_think_llm"]


def _normalize_model_name(model: str | None) -> str:
    return model.strip() if isinstance(model, str) else ""


def resolve_run_models(provider: str, quick_model: str | None = None, deep_model: str | None = None) -> tuple[str, str]:
    provider_lower = provider.lower()
    resolved_quick_model = _normalize_model_name(quick_model) or get_provider_default_model(provider_lower, "quick")
    resolved_deep_model = _normalize_model_name(deep_model) or get_provider_default_model(provider_lower, "deep")
    return resolved_quick_model, resolved_deep_model


def build_run_config(provider: str, quick_model: str | None = None, deep_model: str | None = None) -> dict[str, Any]:
    _ensure_reports_layout()
    config = copy.deepcopy(DEFAULT_CONFIG)
    provider_lower = provider.lower()
    resolved_quick_model, resolved_deep_model = resolve_run_models(provider_lower, quick_model, deep_model)
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
                "note": "Azure, OpenRouter, and Ollama may require a custom deployment/model name." if provider in {"azure", "openrouter", "ollama"} else "",
            }
        )
    return providers


def _saved_report_snapshot(ticker: str, trade_date: str) -> dict[str, Any] | None:
    return service_reports.saved_report_snapshot(ticker, trade_date, _paths())


def _load_daily_manifest(trade_date: str) -> dict[str, Any]:
    watchlist = _resolve_daily_watchlist()
    return service_daily.load_daily_manifest(
        trade_date,
        reports_dir=REPORTS_DIR,
        dirname=DAILY_RUNS_DIRNAME,
        lock=_daily_manifest_lock,
        source=str(watchlist["source"]),
        default_daily_tickers=tuple(watchlist["tickers"]),
        daily_coverage_policy=DAILY_COVERAGE_POLICY,
        snapshot_loader=_saved_report_snapshot,
    )


def _write_daily_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    return service_daily.write_daily_manifest(manifest, reports_dir=REPORTS_DIR, dirname=DAILY_RUNS_DIRNAME, lock=_daily_manifest_lock)


def _update_daily_run_job_state(trade_date: str, ticker: str, **kwargs: Any) -> None:
    service_daily.update_daily_run_job_state(
        trade_date,
        ticker,
        reports_dir=REPORTS_DIR,
        dirname=DAILY_RUNS_DIRNAME,
        lock=_daily_manifest_lock,
        manifest_loader=_load_daily_manifest,
        manifest_writer=_write_daily_manifest,
        **kwargs,
    )


class TradingJobManager:
    def __init__(self, max_workers: int = 4, max_history: int = 100) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="trading-web")
        self._jobs: dict[str, JobState] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()
        self._max_history = max_history

    def submit(self, ticker: str, trade_date: str, workflow: str = WORKFLOW_ON_DEMAND, provider: str = "opencode", quick_model: str | None = None, deep_model: str | None = None) -> JobState:
        safe_ticker = safe_ticker_component(ticker.strip().upper())
        provider_lower = provider.strip().lower()
        resolved_quick_model, resolved_deep_model = resolve_run_models(provider_lower, quick_model, deep_model)
        job = JobState(job_id=uuid.uuid4().hex, ticker=safe_ticker, trade_date=trade_date, workflow=workflow, provider=provider_lower, quick_model=resolved_quick_model, deep_model=resolved_deep_model)
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
        _update_daily_run_job_state(job.trade_date, job.ticker, status="running" if job.workflow == WORKFLOW_DAILY_COVERAGE else None, job_id=job.job_id if job.workflow == WORKFLOW_DAILY_COVERAGE else None, started_at=job.started_at if job.workflow == WORKFLOW_DAILY_COVERAGE else None)

        try:
            config = build_run_config(job.provider, job.quick_model, job.deep_model)
            usage_collector = None
            if job.provider == "opencode":
                usage_collector = TokenUsageCollector(job_id=job.job_id, ticker=job.ticker, trade_date=job.trade_date, workflow=job.workflow, provider=job.provider, quick_model=job.quick_model, deep_model=job.deep_model)
                config["_opencode_usage_callback"] = usage_collector.record
            graph = TradingAgentsGraph(debug=False, config=config)
            final_state, decision = graph.propagate(job.ticker, job.trade_date)
            export_dir = REPORTS_DIR / job.ticker / "SavedReports" / f"{job.trade_date}_{job.job_id[:8]}"
            complete_report_path = save_complete_report(final_state, job.ticker, export_dir)
            usage_payload = usage_collector.snapshot() if usage_collector is not None else None
            if usage_payload is not None and (usage_payload["summary"]["call_count"] or usage_payload["events"]):
                atomic_write_json(token_usage_path(export_dir), usage_payload)

            with self._lock:
                job.status = "completed"
                job.decision = decision
                job.report_path = str(complete_report_path.relative_to(REPO_ROOT))
                if usage_payload is not None:
                    job.usage_summary = usage_payload["summary"]
                    job.usage_events = usage_payload["events"]
                job.completed_at = datetime.utcnow().isoformat() + "Z"
            if job.workflow == WORKFLOW_DAILY_COVERAGE:
                _update_daily_run_job_state(job.trade_date, job.ticker, status="completed", job_id=job.job_id, rating=parse_rating(decision), report_path=job.report_path, started_at=job.started_at, completed_at=job.completed_at, error=None)
        except Exception as exc:  # pragma: no cover - surfaced to API
            usage_summary = usage_collector.snapshot() if "usage_collector" in locals() and usage_collector is not None else None
            with self._lock:
                job.status = "failed"
                job.error = str(exc)
                if usage_summary is not None:
                    job.usage_summary = usage_summary["summary"]
                    job.usage_events = usage_summary["events"]
                job.completed_at = datetime.utcnow().isoformat() + "Z"
            if job.workflow == WORKFLOW_DAILY_COVERAGE:
                _update_daily_run_job_state(job.trade_date, job.ticker, status="failed", job_id=job.job_id, started_at=job.started_at, completed_at=job.completed_at, error=str(exc))


def list_report_tickers() -> list[dict[str, Any]]:
    return service_reports.list_report_tickers(_paths(), REPORTS_SYSTEM_DIRS, list_report_runs)


def list_report_runs(ticker: str) -> list[dict[str, Any]]:
    return service_reports.list_report_runs(ticker, _paths(), SAVED_REPORT_ID_PATTERN)


def load_report(ticker: str, report_id: str) -> dict[str, Any]:
    return service_reports.load_report(ticker, report_id, _paths(), SAVED_REPORT_ID_PATTERN, _SAVED_REPORT_DOCUMENT_ORDER, _SAVED_REPORT_DOCUMENT_TITLES, _SECTION_TITLES)


def get_daily_watchlist(force_refresh: bool = False) -> dict[str, Any]:
    watchlist = _resolve_daily_watchlist(force_refresh=force_refresh)
    metadata = {
        "fetched_at": watchlist.get("fetched_at"),
        "screenshots": list(watchlist.get("screenshots", [])),
        "error": watchlist.get("error"),
        "stale": bool(watchlist.get("stale", False)),
    }
    return service_daily.get_daily_watchlist(str(watchlist["source"]), tuple(watchlist["tickers"]), DAILY_COVERAGE_POLICY, metadata)


def prepare_daily_run(trade_date: str) -> dict[str, Any]:
    watchlist = _resolve_daily_watchlist()
    return service_daily.prepare_daily_run(
        trade_date,
        lock=_daily_manifest_lock,
        source=str(watchlist["source"]),
        default_daily_tickers=tuple(watchlist["tickers"]),
        daily_coverage_policy=DAILY_COVERAGE_POLICY,
        manifest_loader=_load_daily_manifest,
        manifest_writer=_write_daily_manifest,
        snapshot_loader=_saved_report_snapshot,
        get_daily_run_fn=get_daily_run,
    )


def get_daily_run(trade_date: str) -> dict[str, Any]:
    return service_daily.get_daily_run(trade_date, _load_daily_manifest)


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
    return service_daily.queue_daily_run_entries(
        job_manager,
        trade_date,
        lock=_daily_manifest_lock,
        workflow_daily_coverage=WORKFLOW_DAILY_COVERAGE,
        provider=provider,
        quick_model=quick_model,
        deep_model=deep_model,
        tickers=tickers,
        retry_failed_only=retry_failed_only,
        manifest_loader=_load_daily_manifest,
        manifest_writer=_write_daily_manifest,
        prepare_daily_run_fn=prepare_daily_run,
        get_daily_run_fn=get_daily_run,
    )


def get_token_usage(job_manager: TradingJobManager) -> dict[str, Any]:
    return get_token_usage_payload(
        jobs=job_manager.list_jobs(),
        saved_records_loader=lambda: iter_saved_usage_records(
            reports_dir=REPORTS_DIR,
            repo_root=REPO_ROOT,
            system_dirs=REPORTS_SYSTEM_DIRS,
        ),
    )


def queue_single_ticker_run(
    job_manager: TradingJobManager,
    ticker: str,
    trade_date: str,
    *,
    provider: str = "opencode",
    quick_model: str | None = None,
    deep_model: str | None = None,
) -> dict[str, Any]:
    job = job_manager.submit(ticker, trade_date, WORKFLOW_DAILY_COVERAGE, provider, quick_model, deep_model)
    return {"job": job_manager.get_job(job.job_id)}
