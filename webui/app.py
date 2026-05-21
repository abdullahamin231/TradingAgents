from __future__ import annotations

import os
import threading
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .service import (
    TradingJobManager,
    build_daily_rebalance_plan,
    execute_daily_rebalance_plan,
    get_daily_run,
    get_settings,
    get_daily_watchlist,
    get_portfolio_state,
    get_token_usage,
    list_llm_providers,
    list_report_runs,
    list_report_tickers,
    load_report,
    mark_scheduled_daily_run,
    prepare_daily_run,
    queue_daily_run_entries,
    queue_single_ticker_run,
    rerun_daily_halal_check,
    sync_alpaca_paper_portfolio,
    update_settings,
    update_portfolio_state,
)


BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(title="TradingAgents Web Interface")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
job_manager = TradingJobManager(max_workers=int(os.getenv("TRADINGAGENTS_WEB_MAX_WORKERS", "4")))
_scheduler_stop = threading.Event()
_scheduler_thread: threading.Thread | None = None


class RunRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=32)
    trade_date: str
    provider: str = Field(default="opencode", min_length=1, max_length=32)
    quick_model: str = Field(default="", max_length=128)
    deep_model: str = Field(default="", max_length=128)


class BatchRunRequest(BaseModel):
    runs: list[RunRequest] = Field(min_length=1, max_length=24)


class DailyRunQueueRequest(BaseModel):
    provider: str = Field(default="opencode", min_length=1, max_length=32)
    quick_model: str = Field(default="", max_length=128)
    deep_model: str = Field(default="", max_length=128)


class SettingsRequest(BaseModel):
    halal_checker_enabled: bool = True
    daily_run_time: str = Field(default="09:30", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class PortfolioPositionRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=32)
    current_notional: float = Field(default=0.0, ge=0.0)
    current_weight: float = Field(default=0.0, ge=0.0)
    shares: float | None = Field(default=None, ge=0.0)
    last_rating: str = Field(default="Hold", min_length=1, max_length=32)


class PortfolioStateRequest(BaseModel):
    as_of: str | None = None
    total_equity: float = Field(default=100000.0, gt=0.0)
    cash_notional: float | None = Field(default=None, ge=0.0)
    source: str = Field(default="paper", min_length=1, max_length=64)
    positions: list[PortfolioPositionRequest] = Field(default_factory=list, max_length=64)


class RebalancePlanRequest(BaseModel):
    total_equity: float | None = Field(default=None, gt=0.0)
    max_positions: int = Field(default=10, ge=1, le=50)
    apply_targets: bool = False


class RebalanceExecutionRequest(BaseModel):
    total_equity: float | None = Field(default=None, gt=0.0)
    max_positions: int = Field(default=10, ge=1, le=50)


def _scheduler_loop() -> None:
    while not _scheduler_stop.wait(30):
        current_settings = get_settings()
        daily_run_time = str(current_settings.get("daily_run_time") or "09:30")
        now = datetime.now(ZoneInfo(str(current_settings.get("daily_run_timezone") or "America/New_York")))
        run_time = datetime.strptime(daily_run_time, "%H:%M").time()
        run_date = now.date().isoformat()
        if now.time() < run_time:
            continue
        if current_settings.get("last_scheduled_daily_run_date") == run_date:
            continue
        try:
            prepare_daily_run(run_date)
            queue_daily_run_entries(job_manager, run_date)
            mark_scheduled_daily_run(run_date)
        except Exception:
            continue


@app.on_event("startup")
def start_daily_scheduler() -> None:
    global _scheduler_thread
    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        return
    _scheduler_stop.clear()
    _scheduler_thread = threading.Thread(target=_scheduler_loop, name="daily-coverage-scheduler", daemon=True)
    _scheduler_thread.start()


@app.on_event("shutdown")
def stop_daily_scheduler() -> None:
    _scheduler_stop.set()
    if _scheduler_thread is not None:
        _scheduler_thread.join(timeout=2)


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        name="index.html",
        request=request,
        context={
            "today": date.today().isoformat(),
        },
    )


@app.get("/api/jobs")
def get_jobs() -> dict:
    return {"jobs": job_manager.list_jobs()}


@app.get("/api/providers")
def get_providers() -> dict:
    return {"providers": list_llm_providers()}


@app.get("/api/settings")
def read_settings() -> dict:
    return get_settings()


@app.put("/api/settings")
def put_settings(payload: SettingsRequest) -> dict:
    try:
        return update_settings(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/token-usage")
def token_usage() -> dict:
    return get_token_usage(job_manager)


@app.post("/api/jobs")
def create_jobs(payload: BatchRunRequest) -> dict:
    try:
        jobs = [
            job_manager.submit(
                run.ticker,
                run.trade_date,
                "daily_coverage",
                run.provider,
                run.quick_model,
                run.deep_model,
            )
            for run in payload.runs
        ]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"jobs": [job_manager.get_job(job.job_id) for job in jobs]}


@app.post("/api/on-demand/run")
def run_on_demand(payload: RunRequest) -> dict:
    try:
        return queue_single_ticker_run(
            job_manager,
            payload.ticker,
            payload.trade_date,
            provider=payload.provider,
            quick_model=payload.quick_model,
            deep_model=payload.deep_model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/daily-watchlist")
def daily_watchlist() -> dict:
    return get_daily_watchlist()


@app.post("/api/daily-watchlist/refresh")
def refresh_daily_watchlist() -> dict:
    return get_daily_watchlist(force_refresh=True)


@app.get("/api/daily-runs/{trade_date}")
def daily_run(trade_date: str) -> dict:
    try:
        return get_daily_run(trade_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/daily-runs/{trade_date}/prepare")
def prepare_daily_coverage(trade_date: str) -> dict:
    try:
        return prepare_daily_run(trade_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/daily-runs/{trade_date}/halal-check")
def rerun_daily_halal_screening(trade_date: str) -> dict:
    try:
        return rerun_daily_halal_check(trade_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/daily-runs/{trade_date}/run-missing")
def queue_daily_coverage(trade_date: str, payload: DailyRunQueueRequest) -> dict:
    try:
        return queue_daily_run_entries(
            job_manager,
            trade_date,
            provider=payload.provider,
            quick_model=payload.quick_model,
            deep_model=payload.deep_model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/daily-runs/{trade_date}/tickers/{ticker}/retry")
def retry_daily_ticker(trade_date: str, ticker: str, payload: DailyRunQueueRequest) -> dict:
    try:
        return queue_daily_run_entries(
            job_manager,
            trade_date,
            provider=payload.provider,
            quick_model=payload.quick_model,
            deep_model=payload.deep_model,
            tickers=[ticker],
            retry_failed_only=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/portfolio/current")
def portfolio_current() -> dict:
    return get_portfolio_state()


@app.put("/api/portfolio/current")
def put_portfolio_current(payload: PortfolioStateRequest) -> dict:
    try:
        return update_portfolio_state(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/portfolio/alpaca-paper/sync")
def sync_portfolio_from_alpaca() -> dict:
    try:
        return sync_alpaca_paper_portfolio()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/daily-runs/{trade_date}/rebalance-plan")
def rebalance_plan(trade_date: str, payload: RebalancePlanRequest) -> dict:
    try:
        return build_daily_rebalance_plan(
            trade_date,
            total_equity=payload.total_equity,
            max_positions=payload.max_positions,
            apply_targets=payload.apply_targets,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/daily-runs/{trade_date}/rebalance-execution")
def rebalance_execution(trade_date: str, payload: RebalanceExecutionRequest) -> dict:
    try:
        return execute_daily_rebalance_plan(
            trade_date,
            total_equity=payload.total_equity,
            max_positions=payload.max_positions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/tickers")
def get_tickers() -> dict:
    return {"tickers": list_report_tickers()}


@app.get("/api/tickers/{ticker}/reports")
def get_ticker_reports(ticker: str) -> dict:
    try:
        return {"reports": list_report_runs(ticker)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/tickers/{ticker}/reports/{report_id}")
def get_report(ticker: str, report_id: str) -> dict:
    try:
        return load_report(ticker, report_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Report not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
