import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from webui import service


def test_ensure_reports_layout_moves_loose_markdown_into_ticker_legacy(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "mu_news_report.md").write_text("news", encoding="utf-8")
    (reports_dir / "MXL_Investment_Plan.md").write_text("plan", encoding="utf-8")
    (reports_dir / "MaxLinear_Bear_Argument.md").write_text("bear", encoding="utf-8")

    monkeypatch.setattr(service, "REPORTS_DIR", reports_dir)

    service._ensure_reports_layout()

    assert not (reports_dir / "mu_news_report.md").exists()
    assert not (reports_dir / "MXL_Investment_Plan.md").exists()
    assert not (reports_dir / "MaxLinear_Bear_Argument.md").exists()
    assert (reports_dir / "MU" / "legacy" / "mu_news_report.md").exists()
    assert (reports_dir / "MXL" / "legacy" / "MXL_Investment_Plan.md").exists()
    assert (reports_dir / "_legacy_root_artifacts" / "MaxLinear_Bear_Argument.md").exists()


def test_list_report_tickers_skips_system_directories(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    (reports_dir / "cache").mkdir(parents=True)
    (reports_dir / "memory").mkdir()
    (reports_dir / "daily_runs").mkdir()
    (reports_dir / "_legacy_root_artifacts").mkdir()
    (reports_dir / "SPY" / "TradingAgentsStrategy_logs").mkdir(parents=True)

    monkeypatch.setattr(service, "REPORTS_DIR", reports_dir)

    tickers = service.list_report_tickers()

    assert [entry["ticker"] for entry in tickers] == ["SPY"]
