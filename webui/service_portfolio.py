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
    "Buy": 1.25,
    "Overweight": 1.25,
    "Hold": 1.0,
    "Underweight": 0.75,
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

    @property
    def executions_dir(self) -> Path:
        return self.root / "executions"


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


def _manifest_screening_enabled(manifest: dict[str, Any]) -> bool:
    return bool((manifest.get("screening") or {}).get("enabled"))


def _manifest_blocked_tickers(manifest: dict[str, Any]) -> set[str]:
    blocked: set[str] = set()
    if not _manifest_screening_enabled(manifest):
        return blocked
    for entry in manifest.get("tickers", []):
        if not isinstance(entry, dict) or not isinstance(entry.get("ticker"), str):
            continue
        compliance = entry.get("shariah_compliance") or {}
        if compliance.get("allowed") is False and compliance.get("status") not in {"screening_error", "unknown"}:
            blocked.add(entry["ticker"])
    return blocked


def _estimate_sell_qty(
    *,
    current_shares: Any,
    current_notional: float,
    sell_notional: float,
    sell_all: bool = False,
) -> float | None:
    if not isinstance(current_shares, (int, float)) or current_shares <= 0:
        return None
    if sell_all:
        return int(float(current_shares) * 1e6) / 1e6
    if current_notional <= 0:
        return None
    qty = min(float(current_shares), float(current_shares) * sell_notional / current_notional)
    return int(qty * 1e6) / 1e6


def default_portfolio_state(total_equity: float = DEFAULT_PORTFOLIO_TOTAL_EQUITY) -> dict[str, Any]:
    total = _round_money(total_equity)
    return {
        "as_of": None,
        "total_equity": total,
        "cash_notional": total,
        "positions": [],
        "broker": None,
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
        "broker": payload.get("broker") if isinstance(payload.get("broker"), dict) else None,
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


def latest_previous_rebalance_plan(paths: PortfolioPaths, trade_date: str) -> dict[str, Any] | None:
    if not paths.executions_dir.exists():
        return None
    candidates = sorted(
        path
        for path in paths.executions_dir.glob("*.json")
        if path.stem[:10] < trade_date
    )
    for path in reversed(candidates):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        status = payload.get("status")
        submitted_without_status = status is None and "submitted_order_count" in payload and payload.get("submitted_at")
        if status not in {"submitted", "no_orders"} and not submitted_without_status:
            continue
        plan = payload.get("plan")
        if isinstance(plan, dict) and plan.get("ready") is True:
            return plan
    return None


def _allocation_signature_from_rows(rows: list[dict[str, Any]], selected_tickers: set[str]) -> dict[str, tuple[str, float, float]]:
    signature: dict[str, tuple[str, float, float]] = {}
    for item in rows:
        ticker = item.get("ticker")
        if ticker not in selected_tickers:
            continue
        rating = parse_rating(str(item.get("rating") or "Hold"))
        multiplier = round(float(item.get("target_multiplier", RATING_TO_WEIGHT_MULTIPLIER.get(rating, 0.0)) or 0.0), 6)
        target_weight = round(float(item.get("target_weight", 0.0) or 0.0), 6)
        signature[str(ticker)] = (rating, multiplier, target_weight)
    return signature


def _allocation_signature_from_plan(plan: dict[str, Any] | None) -> dict[str, tuple[str, float, float]] | None:
    if not isinstance(plan, dict):
        return None
    selected_tickers = set(_normalize_tickers(list(plan.get("selected_tickers") or ())))
    if not selected_tickers:
        return None
    ranking = [item for item in plan.get("ranking", []) if isinstance(item, dict)]
    signature = _allocation_signature_from_rows(ranking, selected_tickers)
    if set(signature) != selected_tickers:
        return None
    return signature


def build_rebalance_plan(
    *,
    trade_date: str,
    manifest: dict[str, Any],
    portfolio_state: dict[str, Any],
    watchlist_tickers: tuple[str, ...],
    previous_watchlist_tickers: tuple[str, ...] = (),
    previous_rebalance_plan: dict[str, Any] | None = None,
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
    blocked_tickers = _manifest_blocked_tickers(manifest)

    required_universe = _normalize_tickers([*normalized_watchlist, *existing_holdings])
    pending_analysis = [
        ticker
        for ticker in required_universe
        if ticker not in blocked_tickers and completed_entries.get(ticker) is None
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
                "shariah_blocked": ticker in blocked_tickers,
            }
        )

    ranked_candidates.sort(
        key=lambda item: (
            -item["score"],
            -item["target_multiplier"],
            item["ticker"],
        )
    )

    ranked_by_ticker = {item["ticker"]: item for item in ranked_candidates}
    selected = [
        item
        for item in ranked_candidates
        if item["rating"] != "Sell" and not item["shariah_blocked"] and item["target_multiplier"] > 0.0
    ][:max_positions]
    selected_tickers = {item["ticker"] for item in selected}
    selected_multiplier_sum = sum(item["target_multiplier"] for item in selected)
    selected_weights = {
        item["ticker"]: (item["target_multiplier"] / selected_multiplier_sum if selected_multiplier_sum > 0.0 else 0.0)
        for item in selected
    }

    target_positions: list[dict[str, Any]] = []
    for ticker in _normalize_tickers([*normalized_watchlist, *existing_holdings]):
        item = ranked_by_ticker.get(ticker)
        if item is None:
            position = current_positions.get(ticker)
            if position is None:
                continue
            item = {
                "ticker": ticker,
                "rating": parse_rating(str(position.get("last_rating", "Hold"))),
                "score": 0,
                "report_path": None,
                "status": completed_entries.get(ticker, {}).get("status") or "pending",
                "is_existing_holding": True,
                "is_new_watchlist_addition": ticker in new_watchlist_additions,
                "current_weight": float(position.get("current_weight", 0.0) or 0.0),
                "current_notional": _round_money(float(position.get("current_notional", 0.0) or 0.0)),
                "target_multiplier": 0.0,
                "shariah_blocked": ticker in blocked_tickers,
            }
        current_notional = item["current_notional"]
        current_shares = current_positions.get(ticker, {}).get("shares")
        action_reason = "not selected"
        selected_for_target = ticker in selected_tickers
        skipped = False
        sell_all = False

        if selected_for_target:
            target_notional = _round_money(total_value * selected_weights[ticker])
            action_reason = f"target static top-{max_positions} allocation from {item['rating']} rating"
        else:
            target_notional = 0.0
            if item["is_existing_holding"]:
                sell_all = True
                if item["shariah_blocked"]:
                    action_reason = "sell existing holding because it is blocked by halal screening"
                elif item["status"] != "completed":
                    action_reason = "sell existing holding because analysis is pending and it is outside the selected allocation"
                else:
                    action_reason = f"sell existing holding because it is outside the selected top-{max_positions}"

        target_weight = target_notional / total_value if total_value > 0 else 0.0
        delta_notional = _round_money(target_notional - current_notional)
        side = "skip" if skipped else "buy" if delta_notional > 0.01 else "sell" if delta_notional < -0.01 else "hold"
        estimated_sell_qty = None
        if side == "sell":
            estimated_sell_qty = _estimate_sell_qty(
                current_shares=current_shares,
                current_notional=current_notional,
                sell_notional=abs(delta_notional),
                sell_all=sell_all,
            )
        target_positions.append(
            {
                **item,
                "selected_for_target_portfolio": selected_for_target,
                "target_weight": round(target_weight, 6),
                "target_notional": target_notional,
                "delta_notional": delta_notional,
                "estimated_sell_qty": estimated_sell_qty,
                "rebalance_action": side,
                "action_reason": action_reason,
            }
        )

    current_signature = _allocation_signature_from_rows(target_positions, selected_tickers)
    previous_signature = _allocation_signature_from_plan(previous_rebalance_plan)
    allocation_unchanged = previous_signature is not None and current_signature == previous_signature
    if allocation_unchanged:
        for item in target_positions:
            if item["selected_for_target_portfolio"]:
                item["rebalance_action"] = "hold"
                item["estimated_sell_qty"] = None
                item["action_reason"] = "allocation unchanged from previous completed plan; drift rebalance disabled"

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
            "estimated_sell_qty": item["estimated_sell_qty"],
            "broker_payload": {
                "symbol": item["ticker"],
                "side": item["rebalance_action"],
                "order_type": "market",
                "time_in_force": "day",
                "notional_delta": abs(item["delta_notional"]),
                "estimated_sell_qty": item["estimated_sell_qty"],
            },
        }
        for item in target_positions
        if item["rebalance_action"] in {"buy", "sell"}
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
        "ready": len(selected_tickers) == max_positions,
        "max_positions": max_positions,
        "total_equity": total_value,
        "watchlist_tickers": normalized_watchlist,
        "existing_holdings": existing_holdings,
        "new_watchlist_additions": new_watchlist_additions,
        "dropped_watchlist_tickers": dropped_watchlist_tickers,
        "pending_analysis": pending_analysis,
        "insufficient_eligible_tickers": max(max_positions - len(selected_tickers), 0),
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
            "execution_mode": "static_top_10_rating_weighted",
            "drift_rebalance": False,
            "allocation_unchanged_from_previous_completed_plan": allocation_unchanged,
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


def write_execution_result(paths: PortfolioPaths, execution: dict[str, Any]) -> dict[str, Any]:
    paths.executions_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(paths.executions_dir / f"{execution['execution_id']}.json", execution)
    return execution
