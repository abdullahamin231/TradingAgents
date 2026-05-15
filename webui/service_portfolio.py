from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from tradingagents.agents.utils.rating import parse_rating
from tradingagents.dataflows.utils import safe_ticker_component

from .service_helpers import atomic_write_json


DEFAULT_PORTFOLIO_TOTAL_EQUITY = 100000.0
DEFAULT_TARGET_POSITION_COUNT = 10
RATING_TO_SCORE = {
    "Buy": 5,
    "Overweight": 4,
    "Hold": 3,
    "Underweight": 2,
    "Sell": 1,
}
RATING_TO_WEIGHT_MULTIPLIER = {
    "Buy": 1.0,
    "Overweight": 0.7,
    "Hold": 1.0,
    "Underweight": 1.3,
    "Sell": 0.0,
}


@dataclass(frozen=True)
class PortfolioPaths:
    reports_dir: Path
    dirname: str = "portfolio"

    @property
    def root(self) -> Path:
        return self.reports_dir / self.dirname

    @property
    def state_path(self) -> Path:
        return self.root / "current.json"

    @property
    def rebalances_dir(self) -> Path:
        return self.root / "rebalances"


def _utcnow() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _round_money(value: float) -> float:
    return round(float(value), 2)


def _normalize_tickers(values: list[str] | tuple[str, ...] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        try:
            ticker = safe_ticker_component(str(value).strip().upper())
        except ValueError:
            continue
        if ticker in seen:
            continue
        seen.add(ticker)
        normalized.append(ticker)
    return normalized


def default_portfolio_state(total_equity: float = DEFAULT_PORTFOLIO_TOTAL_EQUITY) -> dict[str, Any]:
    total = _round_money(total_equity)
    return {
        "as_of": None,
        "total_equity": total,
        "cash_notional": total,
        "positions": [],
        "source": "paper",
        "updated_at": _utcnow(),
    }


def load_portfolio_state(paths: PortfolioPaths, total_equity: float = DEFAULT_PORTFOLIO_TOTAL_EQUITY) -> dict[str, Any]:
    if not paths.state_path.exists():
        return default_portfolio_state(total_equity)
    payload = json.loads(paths.state_path.read_text(encoding="utf-8"))
    positions: list[dict[str, Any]] = []
    for item in payload.get("positions", []):
        if not isinstance(item, dict):
            continue
        ticker = item.get("ticker")
        if not isinstance(ticker, str):
            continue
        try:
            safe_ticker = safe_ticker_component(ticker)
        except ValueError:
            continue
        positions.append(
            {
                "ticker": safe_ticker,
                "shares": item.get("shares"),
                "current_notional": _round_money(float(item.get("current_notional", 0.0) or 0.0)),
                "current_weight": float(item.get("current_weight", 0.0) or 0.0),
                "last_rating": parse_rating(str(item.get("last_rating", "Hold"))),
            }
        )
    total = _round_money(float(payload.get("total_equity", total_equity) or total_equity))
    cash = _round_money(float(payload.get("cash_notional", max(total - sum(item["current_notional"] for item in positions), 0.0)) or 0.0))
    return {
        "as_of": payload.get("as_of"),
        "total_equity": total,
        "cash_notional": cash,
        "positions": positions,
        "source": payload.get("source") or "paper",
        "updated_at": payload.get("updated_at"),
    }


def write_portfolio_state(paths: PortfolioPaths, state: dict[str, Any]) -> dict[str, Any]:
    paths.root.mkdir(parents=True, exist_ok=True)
    payload = {
        **state,
        "updated_at": _utcnow(),
    }
    atomic_write_json(paths.state_path, payload)
    return payload


def portfolio_holdings_tickers(paths: PortfolioPaths) -> tuple[str, ...]:
    state = load_portfolio_state(paths)
    holdings = [
        position["ticker"]
        for position in state["positions"]
        if float(position.get("current_notional", 0.0) or 0.0) > 0.0
    ]
    return tuple(_normalize_tickers(holdings))


def latest_previous_manifest(trade_date: str, manifests_dir: Path, manifest_loader: Callable[[str], dict[str, Any]]) -> dict[str, Any] | None:
    if not manifests_dir.exists():
        return None
    candidates = sorted(
        path.stem
        for path in manifests_dir.glob("*.json")
        if path.stem < trade_date
    )
    if not candidates:
        return None
    return manifest_loader(candidates[-1])


def build_rebalance_plan(
    *,
    trade_date: str,
    manifest: dict[str, Any],
    portfolio_state: dict[str, Any],
    watchlist_tickers: tuple[str, ...],
    previous_watchlist_tickers: tuple[str, ...] = (),
    total_equity: float | None = None,
    max_positions: int = DEFAULT_TARGET_POSITION_COUNT,
    rating_multipliers: dict[str, float] | None = None,
) -> dict[str, Any]:
    multipliers = {**RATING_TO_WEIGHT_MULTIPLIER, **(rating_multipliers or {})}
    normalized_watchlist = _normalize_tickers(list(watchlist_tickers))
    normalized_previous_watchlist = _normalize_tickers(list(previous_watchlist_tickers))
    new_watchlist_additions = [ticker for ticker in normalized_watchlist if ticker not in normalized_previous_watchlist]
    dropped_watchlist_tickers = [ticker for ticker in normalized_previous_watchlist if ticker not in normalized_watchlist]

    total_value = _round_money(total_equity if total_equity is not None else float(portfolio_state.get("total_equity", DEFAULT_PORTFOLIO_TOTAL_EQUITY)))
    current_positions = {
        position["ticker"]: position
        for position in portfolio_state.get("positions", [])
        if isinstance(position, dict) and isinstance(position.get("ticker"), str)
    }
    existing_holdings = sorted(current_positions)
    completed_entries = {
        entry["ticker"]: entry
        for entry in manifest.get("tickers", [])
        if isinstance(entry, dict) and entry.get("status") == "completed" and isinstance(entry.get("ticker"), str)
    }

    required_universe = _normalize_tickers([*normalized_watchlist, *existing_holdings])
    pending_analysis = [
        ticker
        for ticker in required_universe
        if completed_entries.get(ticker) is None
    ]

    ranked_candidates: list[dict[str, Any]] = []
    for ticker in required_universe:
        entry = completed_entries.get(ticker)
        if entry is None:
            continue
        rating = parse_rating(str(entry.get("rating") or "Hold"))
        score = RATING_TO_SCORE.get(rating, 0)
        ranked_candidates.append(
            {
                "ticker": ticker,
                "rating": rating,
                "score": score,
                "report_path": entry.get("report_path"),
                "status": entry.get("status"),
                "is_existing_holding": ticker in current_positions,
                "is_new_watchlist_addition": ticker in new_watchlist_additions,
                "current_weight": float(current_positions.get(ticker, {}).get("current_weight", 0.0) or 0.0),
                "current_notional": _round_money(float(current_positions.get(ticker, {}).get("current_notional", 0.0) or 0.0)),
                "target_multiplier": float(multipliers.get(rating, 0.0) or 0.0),
            }
        )

    ranked_candidates.sort(
        key=lambda item: (
            -item["score"],
            -item["target_multiplier"],
            not item["is_existing_holding"],
            item["ticker"],
        )
    )

    selected = [
        item
        for item in ranked_candidates
        if item["rating"] != "Sell"
    ][:max_positions]
    selected_tickers = {item["ticker"] for item in selected}
    multiplier_total = sum(max(item["target_multiplier"], 0.0) for item in selected)

    target_positions: list[dict[str, Any]] = []
    for item in ranked_candidates:
        if item["ticker"] not in selected_tickers or multiplier_total <= 0:
            target_weight = 0.0
        else:
            target_weight = max(item["target_multiplier"], 0.0) / multiplier_total
        target_notional = _round_money(total_value * target_weight)
        current_notional = item["current_notional"]
        delta_notional = _round_money(target_notional - current_notional)
        side = "buy" if delta_notional > 0.01 else "sell" if delta_notional < -0.01 else "hold"
        target_positions.append(
            {
                **item,
                "selected_for_target_portfolio": item["ticker"] in selected_tickers,
                "target_weight": round(target_weight, 6),
                "target_notional": target_notional,
                "delta_notional": delta_notional,
                "rebalance_action": side,
            }
        )

    order_intents = [
        {
            "ticker": item["ticker"],
            "side": item["rebalance_action"],
            "order_type": "market",
            "time_in_force": "day",
            "current_weight": round(item["current_weight"], 6),
            "target_weight": item["target_weight"],
            "current_notional": item["current_notional"],
            "target_notional": item["target_notional"],
            "delta_notional": item["delta_notional"],
            "rating": item["rating"],
            "report_path": item["report_path"],
            "broker_payload": {
                "symbol": item["ticker"],
                "side": item["rebalance_action"],
                "order_type": "market",
                "time_in_force": "day",
                "notional_delta": abs(item["delta_notional"]),
            },
        }
        for item in target_positions
        if item["rebalance_action"] != "hold"
    ]

    total_target_notional = _round_money(sum(item["target_notional"] for item in target_positions))
    cash_target = _round_money(max(total_value - total_target_notional, 0.0))
    target_state = {
        "as_of": trade_date,
        "total_equity": total_value,
        "cash_notional": cash_target,
        "positions": [
            {
                "ticker": item["ticker"],
                "current_notional": item["target_notional"],
                "current_weight": item["target_weight"],
                "shares": None,
                "last_rating": item["rating"],
            }
            for item in target_positions
            if item["target_notional"] > 0.0
        ],
        "source": "paper_rebalance_target",
    }

    return {
        "trade_date": trade_date,
        "ready": not pending_analysis,
        "max_positions": max_positions,
        "total_equity": total_value,
        "watchlist_tickers": normalized_watchlist,
        "existing_holdings": existing_holdings,
        "new_watchlist_additions": new_watchlist_additions,
        "dropped_watchlist_tickers": dropped_watchlist_tickers,
        "pending_analysis": pending_analysis,
        "analysis_coverage": {
            "required": len(required_universe),
            "completed": len(required_universe) - len(pending_analysis),
            "pending": len(pending_analysis),
        },
        "ranking": target_positions,
        "selected_tickers": [item["ticker"] for item in target_positions if item["selected_for_target_portfolio"]],
        "order_intents": order_intents,
        "current_portfolio": portfolio_state,
        "target_portfolio": target_state,
        "assumptions": {
            "ranking_order": ["Buy", "Overweight", "Hold", "Underweight", "Sell"],
            "rating_weight_multipliers": multipliers,
            "execution_mode": "notional_only",
            "broker_ready": True,
        },
        "generated_at": _utcnow(),
    }


def write_rebalance_plan(paths: PortfolioPaths, plan: dict[str, Any]) -> dict[str, Any]:
    paths.rebalances_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(paths.rebalances_dir / f"{plan['trade_date']}.json", plan)
    return plan


def apply_rebalance_plan(paths: PortfolioPaths, plan: dict[str, Any]) -> dict[str, Any]:
    state = {
        **plan["target_portfolio"],
        "updated_at": _utcnow(),
    }
    return write_portfolio_state(paths, state)
