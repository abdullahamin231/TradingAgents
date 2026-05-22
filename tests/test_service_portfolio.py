import sys
from pathlib import Path

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


def _plan(entries, positions, watchlist, *, screening_enabled=False):
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
        total_equity=100000.0,
        max_positions=10,
    )


def _by_ticker(rows):
    return {row["ticker"]: row for row in rows}


def test_rebalance_plan_uses_top_10_but_sells_existing_sell_outside_top_10():
    watchlist = [f"T{i:02d}" for i in range(1, 12)]
    entries = [_entry(ticker, "Buy") for ticker in watchlist]
    entries.append(_entry("OLD", "Sell"))
    positions = [{"ticker": "OLD", "shares": 20, "current_notional": 2000.0, "current_weight": 0.02}]

    plan = _plan(entries, positions, watchlist)

    assert len(plan["selected_tickers"]) == 10
    assert "OLD" not in plan["selected_tickers"]
    orders = _by_ticker(plan["order_intents"])
    assert orders["OLD"]["side"] == "sell"
    assert orders["OLD"]["target_notional"] == 0.0
    assert orders["OLD"]["estimated_sell_qty"] == 20


def test_rebalance_plan_applies_existing_holding_rating_rules():
    entries = [
        _entry("BUYHELD", "Buy"),
        _entry("HOLDME", "Hold"),
        _entry("TRIM", "Overweight"),
        _entry("ADD", "Underweight"),
    ]
    positions = [
        {"ticker": "BUYHELD", "shares": 10, "current_notional": 1000.0, "current_weight": 0.01},
        {"ticker": "HOLDME", "shares": 10, "current_notional": 2000.0, "current_weight": 0.02},
        {"ticker": "TRIM", "shares": 10, "current_notional": 3000.0, "current_weight": 0.03},
        {"ticker": "ADD", "shares": 10, "current_notional": 4000.0, "current_weight": 0.04},
    ]

    plan = _plan(entries, positions, ["BUYHELD", "HOLDME", "TRIM", "ADD"])
    ranking = _by_ticker(plan["ranking"])
    orders = _by_ticker(plan["order_intents"])

    assert ranking["BUYHELD"]["rebalance_action"] == "hold"
    assert ranking["HOLDME"]["rebalance_action"] == "hold"
    assert ranking["TRIM"]["target_notional"] == 2700.0
    assert orders["TRIM"]["side"] == "sell"
    assert orders["TRIM"]["estimated_sell_qty"] == 1
    assert ranking["ADD"]["target_notional"] == 4400.0
    assert orders["ADD"]["side"] == "buy"
    assert orders["ADD"]["delta_notional"] == 400.0


def test_rebalance_plan_treats_non_held_selected_non_sell_as_buy():
    entries = [_entry("OW", "Overweight"), _entry("HOLD", "Hold"), _entry("UW", "Underweight")]

    plan = _plan(entries, [], ["OW", "HOLD", "UW"])
    orders = _by_ticker(plan["order_intents"])

    assert orders["OW"]["side"] == "buy"
    assert orders["OW"]["target_notional"] == 10000.0
    assert orders["HOLD"]["side"] == "buy"
    assert orders["UW"]["side"] == "buy"


def test_rebalance_plan_skips_halal_blocked_selected_ticker():
    entries = [_entry("HALAL", "Buy"), _entry("BLOCK", "Buy", allowed=False)]

    plan = _plan(entries, [], ["BLOCK", "HALAL"], screening_enabled=True)
    ranking = _by_ticker(plan["ranking"])

    assert "BLOCK" not in plan["selected_tickers"]
    assert ranking["BLOCK"]["rebalance_action"] == "skip"
    assert "BLOCK" not in _by_ticker(plan["order_intents"])
