import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from webui import service


def test_build_opencode_config_uses_opencode_json(tmp_path, monkeypatch):
    opencode_path = tmp_path / "opencode.json"
    opencode_path.write_text(json.dumps({"model": "opencode/test-model"}), encoding="utf-8")

    monkeypatch.setattr(service, "OPENCODE_CONFIG_PATH", opencode_path)
    monkeypatch.setattr(service, "REPORTS_DIR", tmp_path / "reports")

    config = service.build_opencode_config()

    assert config["llm_provider"] == "opencode"
    assert config["deep_think_llm"] == "opencode/test-model"
    assert config["quick_think_llm"] == "opencode/test-model"
    assert Path(config["results_dir"]) == tmp_path / "reports"


def test_build_run_config_supports_google_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "REPORTS_DIR", tmp_path / "reports")

    config = service.build_run_config(
        "google",
        "gemini-3.1-flash-preview",
        "gemini-3.1-pro-preview",
    )

    assert config["llm_provider"] == "google"
    assert config["quick_think_llm"] == "gemini-3.1-flash-preview"
    assert config["deep_think_llm"] == "gemini-3.1-pro-preview"
    assert config["backend_url"] is None


def test_list_llm_providers_includes_opencode_and_google():
    providers = service.list_llm_providers()
    values = {provider["value"] for provider in providers}

    assert "opencode" in values
    assert "google" in values
    google = next(provider for provider in providers if provider["value"] == "google")
    assert "default_quick_model" in google
    assert "default_deep_model" in google


def test_list_and_load_report(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    log_dir = reports_dir / "SPY" / "TradingAgentsStrategy_logs"
    log_dir.mkdir(parents=True)
    payload = {
        "company_of_interest": "SPY",
        "trade_date": "2026-05-05",
        "market_report": "# Market\n\n| Signal | Value |\n| --- | --- |\n| Trend | Up |",
        "sentiment_report": "",
        "news_report": "## News\n\nMacro context.",
        "fundamentals_report": "",
        "investment_debate_state": {
            "bull_history": "Bull case",
            "bear_history": "",
            "history": "",
            "current_response": "",
            "judge_decision": "Research manager view",
        },
        "trader_investment_decision": "Trader plan",
        "risk_debate_state": {
            "aggressive_history": "Aggressive stance",
            "conservative_history": "",
            "neutral_history": "",
            "history": "",
            "judge_decision": "Portfolio manager view",
        },
        "investment_plan": "Research plan",
        "final_trade_decision": "Final decision",
    }
    log_path = log_dir / "full_states_log_2026-05-05.json"
    log_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(service, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(service, "REPORTS_DIR", reports_dir)

    reports = service.list_report_runs("SPY")
    loaded = service.load_report("SPY", "2026-05-05")

    assert reports[0]["trade_date"] == "2026-05-05"
    assert reports[0]["report_id"] == "2026-05-05"
    assert loaded["ticker"] == "SPY"
    assert loaded["source"] == "legacy_log"
    assert any(section["title"] == "Market Analysis" for section in loaded["sections"])
    assert any(section["html"] for section in loaded["sections"])
    assert any(section["title"] == "Portfolio Manager" for section in loaded["debates"])
    assert loaded["documents"]


def test_list_and_load_saved_report_snapshot(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    report_dir = reports_dir / "SPY" / "SavedReports" / "2026-05-05_deadbeef"
    (report_dir / "1_analysts").mkdir(parents=True)
    (report_dir / "4_risk").mkdir(parents=True)
    (report_dir / "complete_report.md").write_text(
        '# Complete\n\n### Social Analyst\n{"report": "## Social\\n\\nMomentum is strong"}\n',
        encoding="utf-8",
    )
    (report_dir / "1_analysts" / "market.md").write_text("## Market\n\nTrend up", encoding="utf-8")
    (report_dir / "1_analysts" / "sentiment.md").write_text(
        '{"report": "# Sentiment\\n\\nBullish conversation"}',
        encoding="utf-8",
    )
    (report_dir / "4_risk" / "aggressive.md").write_text("## Aggressive\n\nTake risk", encoding="utf-8")

    monkeypatch.setattr(service, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(service, "REPORTS_DIR", reports_dir)

    reports = service.list_report_runs("SPY")
    loaded = service.load_report("SPY", "2026-05-05_deadbeef")

    assert reports[0]["report_id"] == "2026-05-05_deadbeef"
    assert reports[0]["source"] == "saved_report"
    assert reports[0]["document_count"] == 4
    assert loaded["ticker"] == "SPY"
    assert loaded["trade_date"] == "2026-05-05"
    assert loaded["report_hash"] == "deadbeef"
    assert loaded["source"] == "saved_report"
    assert loaded["default_document"] == "complete_report.md"
    assert [document["path"] for document in loaded["documents"]] == [
        "complete_report.md",
        "1_analysts/market.md",
        "1_analysts/sentiment.md",
        "4_risk/aggressive.md",
    ]
    assert loaded["documents"][0]["html"]
    assert '{"report"' not in loaded["documents"][0]["markdown"]
    assert "## Social" in loaded["documents"][0]["markdown"]
    assert loaded["documents"][2]["markdown"] == "# Sentiment\n\nBullish conversation"


def test_markdown_to_html_unwraps_json_and_renders_tables():
    html = service._markdown_to_html(
        '{"report": "**Recent Candle Analysis (May 1-8, 2026)**:\\n| Date | Close |\\n| --- | --- |\\n| May 1 | $542.21 |"}'
    )

    assert "Recent Candle Analysis" in html
    assert "<table>" in html
    assert "<td>May 1</td>" in html


def test_run_job_saves_complete_report(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    monkeypatch.setattr(service, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(service, "REPORTS_DIR", reports_dir)

    class FakeGraph:
        def __init__(self, debug, config):
            self.debug = debug
            self.config = config

        def propagate(self, ticker, trade_date):
            return {
                "company_of_interest": ticker,
                "trade_date": trade_date,
                "market_report": "# Market\n\nDetails",
                "sentiment_report": "",
                "news_report": "# News\n\nMacro context",
                "fundamentals_report": "",
                "investment_debate_state": {
                    "bull_history": "Bull case",
                    "bear_history": "",
                    "history": "",
                    "current_response": "",
                    "judge_decision": "Research manager view",
                },
                "trader_investment_plan": "Trader plan",
                "risk_debate_state": {
                    "aggressive_history": "Aggressive stance",
                    "conservative_history": "",
                    "neutral_history": "",
                    "history": "",
                    "judge_decision": "Portfolio manager view",
                },
                "investment_plan": "Research plan",
                "final_trade_decision": "Final decision",
            }, "BUY"

    monkeypatch.setattr(service, "TradingAgentsGraph", FakeGraph)

    manager = service.TradingJobManager(max_workers=1)
    job = service.JobState(
        job_id="job12345",
        ticker="SPY",
        trade_date="2026-05-05",
        provider="opencode",
        quick_model="opencode",
        deep_model="opencode",
    )
    manager._jobs[job.job_id] = job
    manager._order.insert(0, job.job_id)

    manager._run_job(job.job_id)

    saved_report = tmp_path / job.report_path
    assert job.status == "completed"
    assert job.decision == "BUY"
    assert saved_report.name == "complete_report.md"
    assert saved_report.exists()
    assert (saved_report.parent / "1_analysts" / "market.md").exists()
    assert (saved_report.parent / "3_trading" / "trader.md").exists()


def test_prepare_daily_run_builds_manifest(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    monkeypatch.setattr(service, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(service, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(service, "DEFAULT_DAILY_TICKERS", ("SPY", "NVDA", "AAPL"))

    manifest = service.prepare_daily_run("2026-05-09")

    manifest_path = reports_dir / service.DAILY_RUNS_DIRNAME / "2026-05-09.json"
    assert manifest["trade_date"] == "2026-05-09"
    assert manifest["summary"]["total"] == 3
    assert manifest["summary"]["pending"] == 3
    assert manifest_path.exists()


def test_queue_daily_run_only_queues_incomplete_entries(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    monkeypatch.setattr(service, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(service, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(service, "DEFAULT_DAILY_TICKERS", ("SPY", "NVDA"))

    log_dir = reports_dir / "SPY" / "TradingAgentsStrategy_logs"
    log_dir.mkdir(parents=True)
    (log_dir / "full_states_log_2026-05-09.json").write_text(
        json.dumps({"final_trade_decision": "Rating: Buy", "trade_date": "2026-05-09"}),
        encoding="utf-8",
    )

    class FakeJobManager:
        def __init__(self):
            self.calls = []

        def submit(self, ticker, trade_date, workflow, provider, quick_model, deep_model):
            self.calls.append((ticker, trade_date, workflow, provider, quick_model, deep_model))
            return type("Job", (), {"job_id": f"job-{ticker.lower()}"})()

    manager = FakeJobManager()
    queued = service.queue_daily_run_entries(manager, "2026-05-09", provider="opencode")

    assert len(manager.calls) == 1
    assert manager.calls[0][0] == "NVDA"
    assert queued["summary"]["completed"] == 1
    assert queued["summary"]["queued"] == 1


def test_run_job_updates_daily_manifest_with_rating(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    monkeypatch.setattr(service, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(service, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(service, "DEFAULT_DAILY_TICKERS", ("SPY",))

    class FakeGraph:
        def __init__(self, debug, config):
            self.debug = debug
            self.config = config

        def propagate(self, ticker, trade_date):
            return {
                "company_of_interest": ticker,
                "trade_date": trade_date,
                "market_report": "# Market\n\nDetails",
                "news_report": "# News\n\nContext",
                "final_trade_decision": "Rating: Overweight\nHold with selective trimming.",
            }, "Rating: Overweight\nHold with selective trimming."

    monkeypatch.setattr(service, "TradingAgentsGraph", FakeGraph)

    manager = service.TradingJobManager(max_workers=1)
    service.prepare_daily_run("2026-05-09")
    job = service.JobState(
        job_id="job999",
        ticker="SPY",
        trade_date="2026-05-09",
        workflow=service.WORKFLOW_DAILY_COVERAGE,
        provider="opencode",
        quick_model="opencode",
        deep_model="opencode",
    )
    manager._jobs[job.job_id] = job
    manager._order.insert(0, job.job_id)

    manager._run_job(job.job_id)

    daily_run = service.get_daily_run("2026-05-09")
    entry = daily_run["tickers"][0]
    assert job.status == "completed"
    assert entry["status"] == "completed"
    assert entry["rating"] == "Overweight"
    assert entry["report_path"].endswith("complete_report.md")


def test_queue_daily_run_recovers_concatenated_manifest(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    monkeypatch.setattr(service, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(service, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(service, "DEFAULT_DAILY_TICKERS", ("SPY", "NVDA"))

    daily_dir = reports_dir / service.DAILY_RUNS_DIRNAME
    daily_dir.mkdir(parents=True)
    bad_manifest = (
        json.dumps(
            {
                "trade_date": "2026-05-09",
                "source": "hardcoded",
                "policy": [],
                "tickers": [],
                "created_at": "2026-05-09T00:00:00Z",
                "updated_at": "2026-05-09T00:00:00Z",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
        + json.dumps(
            {
                "trade_date": "2026-05-09",
                "source": "hardcoded",
                "policy": [],
                "tickers": [],
                "created_at": "2026-05-09T01:00:00Z",
                "updated_at": "2026-05-09T01:00:00Z",
            },
            indent=2,
            sort_keys=True,
        )
    )
    (daily_dir / "2026-05-09.json").write_text(bad_manifest, encoding="utf-8")

    class FakeJobManager:
        def __init__(self):
            self.calls = []

        def submit(self, ticker, trade_date, workflow, provider, quick_model, deep_model):
            self.calls.append((ticker, trade_date, workflow, provider, quick_model, deep_model))
            return type("Job", (), {"job_id": f"job-{ticker.lower()}"})()

    manager = FakeJobManager()
    queued = service.queue_daily_run_entries(manager, "2026-05-09", provider="opencode")

    assert [call[0] for call in manager.calls] == ["SPY", "NVDA"]
    assert queued["summary"]["total"] == 2
    assert queued["summary"]["queued"] == 2
