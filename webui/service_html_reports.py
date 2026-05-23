from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .service_helpers import PathsConfig, markdown_to_html, normalize_markdown_text


DAILY_HTML_DIRNAME = "daily_html"


def daily_html_report_path(paths: PathsConfig, trade_date: str) -> Path:
    return paths.reports_dir / DAILY_HTML_DIRNAME / f"{trade_date}.html"


def repo_relative_path(paths: PathsConfig, path: Path) -> str:
    return path.relative_to(paths.repo_root).as_posix()


def share_url(base_url: str, relative_path: str) -> str:
    root = base_url.rstrip("/")
    return f"{root}/reports/share?path={quote(relative_path)}"


def resolve_shared_report_path(paths: PathsConfig, relative_path: str) -> Path:
    if not relative_path or Path(relative_path).is_absolute():
        raise ValueError("Report path must be relative.")
    candidate = (paths.repo_root / relative_path).resolve()
    reports_root = paths.reports_dir.resolve()
    if candidate.suffix.lower() != ".html":
        raise ValueError("Shared report path must point to an HTML report.")
    if reports_root != candidate and reports_root not in candidate.parents:
        raise ValueError("Shared report path must stay under the reports directory.")
    if not candidate.exists():
        raise FileNotFoundError(candidate)
    return candidate


def write_daily_html_report(
    *,
    trade_date: str,
    paths: PathsConfig,
    manifest: dict[str, Any],
    portfolio_state: dict[str, Any],
    rebalance_plan: dict[str, Any] | None,
    ticker_reports: list[dict[str, Any]],
) -> Path:
    path = daily_html_report_path(paths, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_daily_html_report(
            trade_date=trade_date,
            manifest=manifest,
            portfolio_state=portfolio_state,
            rebalance_plan=rebalance_plan,
            ticker_reports=ticker_reports,
        ),
        encoding="utf-8",
    )
    return path


def render_daily_html_report(
    *,
    trade_date: str,
    manifest: dict[str, Any],
    portfolio_state: dict[str, Any],
    rebalance_plan: dict[str, Any] | None,
    ticker_reports: list[dict[str, Any]],
) -> str:
    summary = manifest.get("summary") or {}
    plan = rebalance_plan or {}
    orders = plan.get("order_intents") if isinstance(plan.get("order_intents"), list) else []
    ranking = plan.get("ranking") if isinstance(plan.get("ranking"), list) else []
    positions = portfolio_state.get("positions") if isinstance(portfolio_state.get("positions"), list) else []
    generated_at = datetime.utcnow().isoformat() + "Z"

    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>TradingAgents Daily Report - {escape(trade_date)}</title>",
            f"<style>{_stylesheet()}</style>",
            "</head>",
            "<body>",
            "<main>",
            "<header>",
            f"<p class=\"eyebrow\">Generated {escape(generated_at)}</p>",
            f"<h1>Daily Trading Report - {escape(trade_date)}</h1>",
            f"<p>{escape(_portfolio_sentence(portfolio_state, plan))}</p>",
            "</header>",
            '<section class="metrics">',
            _metric("Total equity", _money(portfolio_state.get("total_equity"))),
            _metric("Cash", _money(portfolio_state.get("cash_notional"))),
            _metric("Coverage", f"{summary.get('completed', 0)}/{summary.get('total', 0)} complete"),
            _metric("Proposed trades", str(len(orders))),
            "</section>",
            '<section class="grid">',
            _panel("Portfolio Weights", _bars_for_positions(positions)),
            _panel("Target Weights", _bars_for_ranking(ranking)),
            "</section>",
            _section("Proposed Trades", _orders_table(orders)),
            _section("Why These Trades", _reasoning_list(ranking, orders)),
            _section("Daily Coverage Status", _coverage_table(manifest.get("tickers", []))),
            _section("Agent Reasoning", _ticker_report_sections(ticker_reports)),
            "</main>",
            "</body>",
            "</html>",
        ]
    )


def _stylesheet() -> str:
    return """
:root {
  color-scheme: light;
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --ink: #17202a;
  --muted: #586574;
  --line: #dbe3eb;
  --soft-line: #e7edf3;
  --paper: #ffffff;
  --page: #f5f7f9;
  --green: #0f766e;
  --red: #b42318;
  --blue: #315f9f;
}
* { box-sizing: border-box; }
html { overflow-x: hidden; }
body { margin: 0; background: var(--page); color: var(--ink); overflow-x: hidden; }
main { width: min(1180px, 100%); margin: 0 auto; padding: 32px 20px 56px; }
header { padding: 24px 0 18px; border-bottom: 1px solid var(--line); }
h1 { margin: 0 0 10px; font-size: 34px; line-height: 1.15; letter-spacing: 0; }
h2 { margin: 0 0 16px; font-size: 22px; line-height: 1.25; letter-spacing: 0; }
h3 { margin: 20px 0 8px; font-size: 17px; line-height: 1.3; letter-spacing: 0; }
p { line-height: 1.55; }
.eyebrow { margin: 0 0 8px; color: var(--muted); font-size: 13px; text-transform: uppercase; }
.metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 22px 0; }
.metric, .panel, section.report-section { background: var(--paper); border: 1px solid var(--line); border-radius: 8px; padding: 16px; }
.metric strong { display: block; font-size: 24px; line-height: 1.15; margin-top: 6px; overflow-wrap: anywhere; }
.label { color: var(--muted); font-size: 13px; }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin: 16px 0; }
section.report-section { margin: 16px 0; overflow: hidden; }
.table-scroll { width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { padding: 10px 8px; border-bottom: 1px solid var(--soft-line); text-align: left; vertical-align: top; }
th { color: var(--muted); font-weight: 650; }
.bar-row { display: grid; grid-template-columns: minmax(56px, 82px) minmax(80px, 1fr) 64px; align-items: center; gap: 10px; margin: 10px 0; font-size: 13px; }
.bar-row strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar-track { height: 10px; background: #e8edf3; border-radius: 999px; overflow: hidden; }
.bar { height: 100%; background: var(--green); }
.bar.target { background: var(--blue); }
.buy { color: var(--green); font-weight: 650; }
.sell { color: var(--red); font-weight: 650; }
.hold, .skip { color: var(--muted); font-weight: 650; }
.reason-list { display: grid; gap: 10px; }
.reason { border-left: 3px solid var(--blue); padding-left: 12px; line-height: 1.5; }
.markdown { max-width: 100%; overflow-x: auto; overflow-wrap: anywhere; -webkit-overflow-scrolling: touch; }
.markdown table { min-width: 620px; }
.markdown pre { white-space: pre-wrap; background: #f1f4f8; padding: 12px; border-radius: 6px; overflow-x: auto; }
.markdown img { max-width: 100%; height: auto; }
@media (max-width: 860px) {
  .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .grid { grid-template-columns: 1fr; }
}
@media (max-width: 620px) {
  main { padding: 18px 12px 40px; }
  header { padding: 14px 0 16px; }
  h1 { font-size: 25px; line-height: 1.18; }
  h2 { font-size: 18px; margin-bottom: 12px; }
  h3 { font-size: 15px; }
  .eyebrow { font-size: 11px; }
  .metrics { gap: 8px; margin: 14px 0; }
  .metric, .panel, section.report-section { padding: 12px; }
  .metric strong { font-size: 18px; }
  .bar-row { grid-template-columns: 54px 1fr 52px; gap: 8px; font-size: 12px; }
  table.data-table, table.data-table thead, table.data-table tbody, table.data-table tr, table.data-table td { display: block; width: 100%; }
  table.data-table thead { display: none; }
  table.data-table tr { border: 1px solid var(--soft-line); border-radius: 8px; padding: 8px 10px; margin: 10px 0; background: #fbfcfd; }
  table.data-table td { display: grid; grid-template-columns: minmax(88px, 38%) minmax(0, 1fr); gap: 10px; padding: 7px 0; border-bottom: 1px solid #edf1f5; overflow-wrap: anywhere; }
  table.data-table td:last-child { border-bottom: 0; }
  table.data-table td::before { content: attr(data-label); color: var(--muted); font-size: 12px; font-weight: 650; }
  .reason { padding-left: 10px; font-size: 14px; }
  .markdown { font-size: 14px; }
}
@media (max-width: 380px) {
  main { padding-left: 10px; padding-right: 10px; }
  .metrics { grid-template-columns: 1fr; }
  table.data-table td { grid-template-columns: 1fr; gap: 3px; }
}
"""


def _metric(label: str, value: str) -> str:
    return f'<div class="metric"><span class="label">{escape(label)}</span><strong>{escape(value)}</strong></div>'


def _panel(title: str, body: str) -> str:
    return f'<section class="panel"><h2>{escape(title)}</h2>{body}</section>'


def _section(title: str, body: str) -> str:
    return f'<section class="report-section"><h2>{escape(title)}</h2>{body}</section>'


def _money(value: Any) -> str:
    try:
        return f"${float(value or 0):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def _percent(value: Any) -> str:
    try:
        return f"{float(value or 0) * 100:.2f}%"
    except (TypeError, ValueError):
        return "0.00%"


def _portfolio_sentence(portfolio_state: dict[str, Any], plan: dict[str, Any]) -> str:
    status = "ready" if plan.get("ready") else "not ready"
    return f"Portfolio snapshot is {portfolio_state.get('source') or 'paper'}; rebalance plan is {status}."


def _bars_for_positions(positions: list[dict[str, Any]]) -> str:
    rows = [
        _bar_row(str(item.get("ticker", "")), float(item.get("current_weight", 0.0) or 0.0), "bar")
        for item in positions
    ]
    return "".join(rows) or "<p>No current positions recorded.</p>"


def _bars_for_ranking(ranking: list[dict[str, Any]]) -> str:
    rows = [
        _bar_row(str(item.get("ticker", "")), float(item.get("target_weight", 0.0) or 0.0), "bar target")
        for item in ranking
        if float(item.get("target_weight", 0.0) or 0.0) > 0
    ]
    return "".join(rows) or "<p>No target positions proposed yet.</p>"


def _bar_row(ticker: str, weight: float, class_name: str) -> str:
    width = max(0.0, min(weight * 100.0, 100.0))
    return (
        '<div class="bar-row">'
        f"<strong>{escape(ticker)}</strong>"
        f'<div class="bar-track"><div class="{escape(class_name)}" style="width: {width:.2f}%"></div></div>'
        f"<span>{_percent(weight)}</span>"
        "</div>"
    )


def _orders_table(orders: list[dict[str, Any]]) -> str:
    if not orders:
        return "<p>No orders are currently proposed.</p>"
    rows = [
        '<div class="table-scroll"><table class="data-table"><thead><tr><th>Ticker</th><th>Side</th><th>Rating</th><th>Current</th><th>Target</th><th>Delta</th></tr></thead><tbody>'
    ]
    for order in orders:
        side = str(order.get("side", "hold"))
        rows.append(
            "<tr>"
            f"<td data-label=\"Ticker\">{escape(str(order.get('ticker', '')))}</td>"
            f'<td data-label="Side" class="{escape(side)}">{escape(side.upper())}</td>'
            f"<td data-label=\"Rating\">{escape(str(order.get('rating', '')))}</td>"
            f"<td data-label=\"Current\">{_money(order.get('current_notional'))}</td>"
            f"<td data-label=\"Target\">{_money(order.get('target_notional'))}</td>"
            f"<td data-label=\"Delta\">{_money(order.get('delta_notional'))}</td>"
            "</tr>"
        )
    rows.append("</tbody></table></div>")
    return "".join(rows)


def _reasoning_list(ranking: list[dict[str, Any]], orders: list[dict[str, Any]]) -> str:
    order_tickers = {order.get("ticker") for order in orders}
    relevant = [item for item in ranking if item.get("ticker") in order_tickers]
    if not relevant:
        return "<p>No rebalance action is required from the current analysis.</p>"
    return '<div class="reason-list">' + "".join(
        f'<div class="reason"><strong>{escape(str(item.get("ticker", "")))}</strong>: '
        f'{escape(str(item.get("action_reason", "")))} '
        f'Rating: {escape(str(item.get("rating", "")))}.</div>'
        for item in relevant
    ) + "</div>"


def _coverage_table(entries: list[dict[str, Any]]) -> str:
    rows = ['<div class="table-scroll"><table class="data-table"><thead><tr><th>Ticker</th><th>Status</th><th>Rating</th><th>Compliance</th><th>Error</th></tr></thead><tbody>']
    for entry in entries:
        compliance = entry.get("shariah_compliance") if isinstance(entry.get("shariah_compliance"), dict) else {}
        rows.append(
            "<tr>"
            f"<td data-label=\"Ticker\">{escape(str(entry.get('ticker', '')))}</td>"
            f"<td data-label=\"Status\">{escape(str(entry.get('status', '')))}</td>"
            f"<td data-label=\"Rating\">{escape(str(entry.get('rating') or ''))}</td>"
            f"<td data-label=\"Compliance\">{escape(str(compliance.get('status') or ''))}</td>"
            f"<td data-label=\"Error\">{escape(str(entry.get('error') or ''))}</td>"
            "</tr>"
        )
    rows.append("</tbody></table></div>")
    return "".join(rows)


def _ticker_report_sections(ticker_reports: list[dict[str, Any]]) -> str:
    if not ticker_reports:
        return "<p>No completed agent reports are available yet.</p>"
    sections: list[str] = []
    for report in ticker_reports:
        title = f"{report.get('ticker', '')} - {report.get('title', 'Agent Report')}"
        markdown = normalize_markdown_text(report.get("markdown", ""))
        sections.append(
            f"<article><h3>{escape(title)}</h3>"
            f'<div class="markdown">{markdown_to_html(markdown)}</div></article>'
        )
    return "".join(sections)
