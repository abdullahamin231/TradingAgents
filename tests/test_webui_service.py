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
    assert loaded["ticker"] == "SPY"
    assert any(section["title"] == "Market Analysis" for section in loaded["sections"])
    assert any(section["html"] for section in loaded["sections"])
    assert any(section["title"] == "Portfolio Manager" for section in loaded["debates"])
