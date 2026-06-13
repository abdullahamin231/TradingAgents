import sys
import json
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from webui import service_portfolio


def _entry(ticker, rating, status="completed", allowed=True):
    return {
        "ticker": ticker,
        "status": status,
        "rating": rating,
        "report_path": f"reports/{ticker}.md",
        "shariah_compliance": {
            "provider": "halalscreener",
            "allowed": allowed,
            "status": "compliant" if allowed else "haram",
        },
    }


def _positions_from_plan(plan, *, drift_ticker=None, drift_notional=None):
    positions = []
    for item in plan["target_portfolio"]["positions"]:
        current_notional = item["current_notional"]
        if item["ticker"] == drift_ticker:
            current_notional = drift_notional
        positions.append(
            {
                "ticker": item["ticker"],
                "shares": 10,
                "current_notional": current_notional,
                "current_weight": current_notional / plan["total_equity"],
            }
        )
    return positions


def _plan(entries, positions, watchlist, *, screening_enabled=False, previous_rebalance_plan=None):
    return service_portfolio.build_rebalance_plan(
        trade_date="2026-05-23",
        manifest={
            "trade_date": "2026-05-23",
            "screening": {"enabled": screening_enabled},
            "tickers": entries,
        },
        portfolio_state={
            "as_of": "2026-05-23",
            "total_equity": 100000.0,
            "cash_notional": 50000.0,
            "positions": positions,
        },
        watchlist_tickers=tuple(watchlist),
        previous_rebalance_plan=previous_rebalance_plan,
        total_equity=100000.0,
        max_positions=10,
    )


def _ten_entries(rating="Hold"):
    return [_entry(f"T{i:02d}", rating) for i in range(1, 11)]


def _by_ticker(rows):
    return {row["ticker"]: row for row in rows}


def test_repeated_overweight_allocation_produces_no_new_orders():
    entries = _ten_entries("Overweight")
    watchlist = [entry["ticker"] for entry in entries]

    first_plan = _plan(entries, [], watchlist)
    assert len(first_plan["order_intents"]) == 10

    drifted_positions = _positions_from_plan(first_plan, drift_ticker="T01", drift_notional=15000.0)
    second_plan = _plan(entries, drifted_positions, watchlist, previous_rebalance_plan=first_plan)

    assert second_plan["order_intents"] == []
    assert second_plan["assumptions"]["allocation_unchanged_from_previous_completed_plan"] is True
    assert {row["rebalance_action"] for row in second_plan["ranking"] if row["selected_for_target_portfolio"]} == {"hold"}


def test_unchanged_allocation_still_sells_unselected_current_holding():
    entries = [*_ten_entries("Overweight"), _entry("OLD", "Hold")]
    watchlist = [entry["ticker"] for entry in entries]
    previous_plan = _plan(entries[:10], [], [entry["ticker"] for entry in entries[:10]])
    positions = [
        *_positions_from_plan(previous_plan, drift_ticker="T01", drift_notional=15000.0),
        {"ticker": "OLD", "shares": 20, "current_notional": 2000.0, "current_weight": 0.02},
    ]

    plan = _plan(entries, positions, watchlist, previous_rebalance_plan=previous_plan)
    orders = _by_ticker(plan["order_intents"])

    assert set(orders) == {"OLD"}
    assert orders["OLD"]["side"] == "sell"
    assert orders["OLD"]["estimated_sell_qty"] == 20


def test_hold_to_overweight_changes_normalized_target_weight_and_creates_deltas():
    hold_entries = _ten_entries("Hold")
    overweight_entries = [_entry("T01", "Overweight"), *[_entry(f"T{i:02d}", "Hold") for i in range(2, 11)]]
    watchlist = [entry["ticker"] for entry in hold_entries]

    previous_plan = _plan(hold_entries, [], watchlist)
    current_positions = _positions_from_plan(previous_plan)
    plan = _plan(overweight_entries, current_positions, watchlist, previous_rebalance_plan=previous_plan)
    ranking = _by_ticker(plan["ranking"])
    orders = _by_ticker(plan["order_intents"])

    assert ranking["T01"]["target_weight"] == pytest.approx(1.25 / 10.25, abs=1e-6)
    assert ranking["T02"]["target_weight"] == pytest.approx(1.0 / 10.25, abs=1e-6)
    assert orders["T01"]["side"] == "buy"
    assert orders["T01"]["delta_notional"] == pytest.approx(2195.12)
    assert orders["T02"]["side"] == "sell"
    assert orders["T02"]["delta_notional"] == pytest.approx(-243.9)


def test_overweight_to_underweight_changes_normalized_target_weight():
    overweight_entries = [_entry("T01", "Overweight"), *[_entry(f"T{i:02d}", "Hold") for i in range(2, 11)]]
    underweight_entries = [_entry("T01", "Underweight"), *[_entry(f"T{i:02d}", "Hold") for i in range(2, 11)]]
    watchlist = [entry["ticker"] for entry in overweight_entries]

    previous_plan = _plan(overweight_entries, [], watchlist)
    current_positions = _positions_from_plan(previous_plan)
    plan = _plan(underweight_entries, current_positions, watchlist, previous_rebalance_plan=previous_plan)
    ranking = _by_ticker(plan["ranking"])
    orders = _by_ticker(plan["order_intents"])

    assert ranking["T01"]["target_weight"] == pytest.approx(0.75 / 9.75, abs=1e-6)
    assert ranking["T02"]["target_weight"] == pytest.approx(1.0 / 9.75, abs=1e-6)
    assert orders["T01"]["side"] == "sell"
    assert orders["T01"]["delta_notional"] == pytest.approx(-4502.81)


def test_more_than_10_analyzed_tickers_selects_exactly_10_eligible_names():
    entries = [
        _entry("BLOCK", "Buy", allowed=False),
        _entry("EXIT", "Sell"),
        *[_entry(f"B{i:02d}", "Buy") for i in range(1, 9)],
        *[_entry(f"H{i:02d}", "Hold") for i in range(1, 5)],
        _entry("WAIT", "Buy", status="pending"),
    ]
    watchlist = [entry["ticker"] for entry in entries]

    plan = _plan(entries, [], watchlist, screening_enabled=True)

    assert plan["ready"] is True
    assert len(plan["selected_tickers"]) == 10
    assert "BLOCK" not in plan["selected_tickers"]
    assert "EXIT" not in plan["selected_tickers"]
    assert "WAIT" not in plan["selected_tickers"]
    assert {"H01", "H02"}.issubset(set(plan["selected_tickers"]))


def test_current_holdings_outside_selected_10_are_sold():
    entries = [*_ten_entries("Buy"), _entry("OLD", "Hold")]
    watchlist = [entry["ticker"] for entry in entries]
    positions = [{"ticker": "OLD", "shares": 20, "current_notional": 2000.0, "current_weight": 0.02}]

    plan = _plan(entries, positions, watchlist)
    orders = _by_ticker(plan["order_intents"])
    ranking = _by_ticker(plan["ranking"])

    assert "OLD" not in plan["selected_tickers"]
    assert ranking["OLD"]["target_notional"] == 0.0
    assert orders["OLD"]["side"] == "sell"
    assert orders["OLD"]["estimated_sell_qty"] == 20


def test_blocked_current_holding_is_sold_when_outside_selected_10():
    entries = [*_ten_entries("Buy"), _entry("BLOCK", "Hold", allowed=False)]
    watchlist = [entry["ticker"] for entry in entries]
    positions = [{"ticker": "BLOCK", "shares": 15, "current_notional": 1500.0, "current_weight": 0.015}]

    plan = _plan(entries, positions, watchlist, screening_enabled=True)
    orders = _by_ticker(plan["order_intents"])

    assert "BLOCK" not in plan["selected_tickers"]
    assert orders["BLOCK"]["side"] == "sell"
    assert orders["BLOCK"]["estimated_sell_qty"] == 15


def test_pending_current_holding_is_sold_when_10_other_names_are_selected():
    entries = [*_ten_entries("Buy"), _entry("PEND", "Hold", status="pending")]
    watchlist = [entry["ticker"] for entry in entries]
    positions = [{"ticker": "PEND", "shares": 15, "current_notional": 1500.0, "current_weight": 0.015}]

    plan = _plan(entries, positions, watchlist)
    orders = _by_ticker(plan["order_intents"])

    assert plan["ready"] is True
    assert "PEND" not in plan["selected_tickers"]
    assert orders["PEND"]["side"] == "sell"
    assert orders["PEND"]["estimated_sell_qty"] == 15


def test_selected_target_weights_sum_to_one():
    entries = [
        _entry("B01", "Buy"),
        _entry("B02", "Buy"),
        _entry("OW1", "Overweight"),
        *[_entry(f"H{i:02d}", "Hold") for i in range(1, 6)],
        _entry("UW1", "Underweight"),
        _entry("UW2", "Underweight"),
    ]
    watchlist = [entry["ticker"] for entry in entries]

    plan = _plan(entries, [], watchlist)

    selected_rows = [row for row in plan["ranking"] if row["selected_for_target_portfolio"]]
    assert sum(row["target_weight"] for row in selected_rows) == pytest.approx(1.0, abs=1e-6)
    assert plan["target_portfolio"]["cash_notional"] == pytest.approx(0.0, abs=0.1)


def test_latest_previous_rebalance_plan_uses_executions_not_generated_previews(tmp_path):
    paths = service_portfolio.PortfolioPaths(tmp_path)
    preview_plan = {"trade_date": "2026-05-22", "ready": True, "selected_tickers": ["PREVIEW"], "ranking": []}
    executed_plan = {"trade_date": "2026-05-21", "ready": True, "selected_tickers": ["EXEC"], "ranking": []}
    paths.rebalances_dir.mkdir(parents=True)
    paths.executions_dir.mkdir(parents=True)
    (paths.rebalances_dir / "2026-05-22.json").write_text(json.dumps(preview_plan), encoding="utf-8")
    (paths.executions_dir / "2026-05-21-exec.json").write_text(
        json.dumps(
            {
                "execution_id": "2026-05-21-exec",
                "submitted_order_count": 1,
                "submitted_at": "2026-05-21T14:00:00Z",
                "plan": executed_plan,
            }
        ),
        encoding="utf-8",
    )

    plan = service_portfolio.latest_previous_rebalance_plan(paths, "2026-05-23")

    assert plan == executed_plan
