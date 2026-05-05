from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .service import TradingJobManager, list_report_tickers, list_report_runs, load_report


BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(title="TradingAgents Web Interface")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
job_manager = TradingJobManager(max_workers=int(os.getenv("TRADINGAGENTS_WEB_MAX_WORKERS", "4")))


class RunRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=32)
    trade_date: str


class BatchRunRequest(BaseModel):
    runs: list[RunRequest] = Field(min_length=1, max_length=24)


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


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/jobs")
def create_jobs(payload: BatchRunRequest) -> dict:
    try:
        jobs = [job_manager.submit(run.ticker, run.trade_date) for run in payload.runs]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"jobs": [job_manager.get_job(job.job_id) for job in jobs]}


@app.get("/api/tickers")
def get_tickers() -> dict:
    return {"tickers": list_report_tickers()}


@app.get("/api/tickers/{ticker}/reports")
def get_ticker_reports(ticker: str) -> dict:
    try:
        return {"reports": list_report_runs(ticker)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/tickers/{ticker}/reports/{trade_date}")
def get_report(ticker: str, trade_date: str) -> dict:
    try:
        return load_report(ticker, trade_date)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Report not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
