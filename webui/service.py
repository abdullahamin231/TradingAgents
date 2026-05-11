from __future__ import annotations

import copy
import json
import os
import re
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
_MARKDOWN_JSON_KEYS = ("report", "markdown", "content", "text", "body", "value")
_SAVED_REPORT_ID_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}_[A-Za-z0-9._-]+$")
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
    normalized_text = _normalize_markdown_text(text)
    if markdown is None:
        return f"<pre>{escape(normalized_text or '')}</pre>"
    return markdown.markdown(
        normalized_text or "",
        extensions=["tables", "fenced_code", "sane_lists", "toc"],
    )


def _normalize_markdown_text(text: Any) -> str:
    if not isinstance(text, str):
        return "" if text is None else str(text)

    stripped = text.strip()
    if stripped[:1] in {"{", "["}:
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if parsed is not None:
            extracted = _extract_markdown_from_json_value(parsed)
            if extracted is not None:
                return _normalize_markdown_tables(_replace_embedded_json_blocks(extracted))

    return _normalize_markdown_tables(_replace_embedded_json_blocks(text))


def _replace_embedded_json_blocks(text: str) -> str:
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

        extracted = _extract_markdown_from_json_value(payload)
        if extracted is None:
            parts.append(text[marker:next_cursor])
        else:
            parts.append(_normalize_markdown_text(extracted))
        cursor = next_cursor

    return "".join(parts)


def _extract_markdown_from_json_value(value: Any, depth: int = 0) -> str | None:
    if depth > 8:
        return None

    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        for key in _MARKDOWN_JSON_KEYS:
            if key in value:
                extracted = _extract_markdown_from_json_value(value[key], depth + 1)
                if extracted is not None:
                    return extracted

        if len(value) == 1:
            only_value = next(iter(value.values()))
            extracted = _extract_markdown_from_json_value(only_value, depth + 1)
            if extracted is not None:
                return extracted
        return None

    if isinstance(value, list):
        extracted_items = [
            extracted
            for item in value
            if (extracted := _extract_markdown_from_json_value(item, depth + 1)) is not None
        ]
        if extracted_items:
            return "\n\n".join(extracted_items)
        return None

    return None


def _normalize_markdown_tables(text: str) -> str:
    lines = text.splitlines()
    if not lines:
        return text

    normalized: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if _is_markdown_table_header(line, lines[index + 1] if index + 1 < len(lines) else None):
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


def _is_markdown_table_header(line: str, next_line: str | None) -> bool:
    if next_line is None:
        return False
    if "|" not in line:
        return False
    return bool(re.match(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+(?:\s*:?-{3,}:?\s*)\|?\s*$", next_line))


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
        return OPENCODE_DEFAULT_QUICK_MODEL if mode == "quick" else OPENCODE_DEFAULT_DEEP_MODEL

    default_model_factory = _PROVIDER_DEFAULT_MODELS.get(provider_lower)
    if default_model_factory is not None:
        return default_model_factory(mode)

    return DEFAULT_CONFIG["quick_think_llm"] if mode == "quick" else DEFAULT_CONFIG["deep_think_llm"]


def _normalize_model_name(model: str | None) -> str:
    if isinstance(model, str):
        return model.strip()
    return ""


def resolve_run_models(
    provider: str,
    quick_model: str | None = None,
    deep_model: str | None = None,
) -> tuple[str, str]:
    provider_lower = provider.lower()
    resolved_quick_model = _normalize_model_name(quick_model) or get_provider_default_model(provider_lower, "quick")
    resolved_deep_model = _normalize_model_name(deep_model) or get_provider_default_model(provider_lower, "deep")
    return resolved_quick_model, resolved_deep_model


def build_run_config(
    provider: str,
    quick_model: str | None = None,
    deep_model: str | None = None,
) -> dict[str, Any]:
    _ensure_reports_layout()
    config = copy.deepcopy(DEFAULT_CONFIG)
    provider_lower = provider.lower()
    resolved_quick_model, resolved_deep_model = resolve_run_models(
        provider_lower,
        quick_model,
        deep_model,
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
    quick_model: str = ""
    deep_model: str = ""
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
        resolved_quick_model, resolved_deep_model = resolve_run_models(
            provider_lower,
            quick_model,
            deep_model,
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
    saved_runs = _list_saved_report_runs(safe_ticker)
    if saved_runs:
        return saved_runs

    return _list_legacy_report_runs(safe_ticker)


def _list_saved_report_runs(safe_ticker: str) -> list[dict[str, Any]]:
    saved_dir = REPORTS_DIR / safe_ticker / "SavedReports"
    if not saved_dir.exists():
        return []

    runs: list[dict[str, Any]] = []
    for path in sorted(
        (candidate for candidate in saved_dir.iterdir() if candidate.is_dir()),
        key=lambda candidate: (candidate.name, candidate.stat().st_mtime),
        reverse=True,
    ):
        report_id = path.name
        if not _SAVED_REPORT_ID_PATTERN.fullmatch(report_id):
            continue

        complete_report = path / "complete_report.md"
        trade_date, _, report_hash = report_id.partition("_")
        relative_dir = path.relative_to(REPO_ROOT)
        document_count = sum(1 for _ in path.rglob("*.md"))
        runs.append(
            {
                "ticker": safe_ticker,
                "report_id": report_id,
                "trade_date": trade_date,
                "report_hash": report_hash or None,
                "file_name": complete_report.name if complete_report.exists() else path.name,
                "relative_path": str(relative_dir),
                "report_path": (
                    str(complete_report.relative_to(REPO_ROOT))
                    if complete_report.exists()
                    else None
                ),
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
                "document_count": document_count,
                "source": "saved_report",
            }
        )
    return runs


def _list_legacy_report_runs(safe_ticker: str) -> list[dict[str, Any]]:
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
                "report_id": trade_date,
                "file_name": path.name,
                "relative_path": str(path.relative_to(REPO_ROOT)),
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
                "document_count": 1,
                "source": "legacy_log",
            }
        )
    return runs


def load_report(ticker: str, report_id: str) -> dict[str, Any]:
    safe_ticker = safe_ticker_component(ticker)
    if _SAVED_REPORT_ID_PATTERN.fullmatch(report_id):
        report_dir = REPORTS_DIR / safe_ticker / "SavedReports" / report_id
        if report_dir.exists():
            return _load_saved_report(safe_ticker, report_dir)

    return _load_legacy_report(safe_ticker, report_id)


def _load_saved_report(safe_ticker: str, report_dir: Path) -> dict[str, Any]:
    report_id = report_dir.name
    trade_date, _, report_hash = report_id.partition("_")
    documents = []
    for path in sorted(
        report_dir.rglob("*.md"),
        key=lambda candidate: (
            _SAVED_REPORT_DOCUMENT_ORDER.get(
                candidate.relative_to(report_dir).as_posix(),
                999,
            ),
            candidate.relative_to(report_dir).as_posix(),
        ),
    ):
        relative_path = path.relative_to(report_dir).as_posix()
        markdown_text = _normalize_markdown_text(path.read_text(encoding="utf-8"))
        documents.append(
            {
                "path": relative_path,
                "title": _saved_report_document_title(relative_path),
                "markdown": markdown_text,
                "html": _markdown_to_html(markdown_text),
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
        "relative_path": str(report_dir.relative_to(REPO_ROOT)),
        "report_path": str((report_dir / "complete_report.md").relative_to(REPO_ROOT)),
        "documents": documents,
        "default_document": (
            "complete_report.md"
            if any(document["path"] == "complete_report.md" for document in documents)
            else documents[0]["path"]
        ),
        "sections": [],
        "debates": [],
        "raw": None,
    }


def _saved_report_document_title(relative_path: str) -> str:
    known_title = _SAVED_REPORT_DOCUMENT_TITLES.get(relative_path)
    if known_title:
        return known_title

    path = Path(relative_path)
    return path.stem.replace("_", " ").title()


def _load_legacy_report(safe_ticker: str, trade_date: str) -> dict[str, Any]:
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
        normalized_value = _normalize_markdown_text(value)
        sections.append(
            {
                "key": key,
                "title": title,
                "markdown": normalized_value,
                "html": _markdown_to_html(normalized_value),
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
            normalized_value = _normalize_markdown_text(investment[key])
            debate_sections.append(
                {
                    "group": "research",
                    "key": key,
                    "title": title,
                    "markdown": normalized_value,
                    "html": _markdown_to_html(normalized_value),
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
            normalized_value = _normalize_markdown_text(risk[key])
            debate_sections.append(
                {
                    "group": "risk",
                    "key": key,
                    "title": title,
                    "markdown": normalized_value,
                    "html": _markdown_to_html(normalized_value),
                }
            )

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
        "relative_path": str(log_path.relative_to(REPO_ROOT)),
        "report_path": str(log_path.relative_to(REPO_ROOT)),
        "documents": documents,
        "default_document": documents[0]["path"] if documents else None,
        "sections": sections,
        "debates": debate_sections,
        "raw": payload,
    }


def _daily_runs_dir() -> Path:
    return REPORTS_DIR / DAILY_RUNS_DIRNAME


def _daily_run_path(trade_date: str) -> Path:
    return _daily_runs_dir() / f"{trade_date}.json"


def _load_json_payload(path: Path) -> tuple[dict[str, Any], bool]:
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


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


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
    with _daily_manifest_lock:
        _daily_runs_dir().mkdir(parents=True, exist_ok=True)
        path = _daily_run_path(manifest["trade_date"])
        manifest["updated_at"] = datetime.utcnow().isoformat() + "Z"
        _atomic_write_json(path, manifest)
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
    with _daily_manifest_lock:
        path = _daily_run_path(trade_date)
        if not path.exists():
            return _new_daily_manifest(trade_date)

        manifest, repaired = _load_json_payload(path)
        if repaired:
            _atomic_write_json(path, manifest)
        return manifest


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
    with _daily_manifest_lock:
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
    with _daily_manifest_lock:
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
    with _daily_manifest_lock:
        prepare_daily_run(trade_date)
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


def queue_single_ticker_run(
    job_manager: TradingJobManager,
    ticker: str,
    trade_date: str,
    *,
    provider: str = "opencode",
    quick_model: str | None = None,
    deep_model: str | None = None,
) -> dict[str, Any]:
    job = job_manager.submit(
        ticker,
        trade_date,
        WORKFLOW_DAILY_COVERAGE,
        provider,
        quick_model,
        deep_model,
    )
    return {"job": job_manager.get_job(job.job_id)}
