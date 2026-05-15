from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from tradingagents.dataflows.utils import safe_ticker_component


DEFAULT_ALPACA_PAPER_BASE_URL = "https://paper-api.alpaca.markets"


def _utcnow() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _round_money(value: float) -> float:
    return round(float(value), 2)


@dataclass(frozen=True)
class AlpacaPaperConfig:
    api_key: str
    secret_key: str
    base_url: str = DEFAULT_ALPACA_PAPER_BASE_URL


class AlpacaPaperError(RuntimeError):
    pass


def load_alpaca_paper_config() -> AlpacaPaperConfig:
    api_key = (os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID") or "").strip()
    secret_key = (os.getenv("ALPACA_API_SECRET") or os.getenv("APCA_API_SECRET_KEY") or "").strip()
    base_url = DEFAULT_ALPACA_PAPER_BASE_URL.strip().rstrip("/")
    if not api_key or not secret_key:
        raise AlpacaPaperError(
            "Alpaca paper trading credentials are missing. Set APCA_API_KEY_ID and APCA_API_SECRET_KEY."
        )
    return AlpacaPaperConfig(api_key=api_key, secret_key=secret_key, base_url=base_url)


def _session(config: AlpacaPaperConfig) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "APCA-API-KEY-ID": config.api_key,
            "APCA-API-SECRET-KEY": config.secret_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
    )
    return session


def _request_json(session: requests.Session, method: str, url: str, *, json_payload: dict[str, Any] | None = None) -> Any:
    response = session.request(method, url, json=json_payload, timeout=20)
    try:
        payload = response.json()
    except ValueError:
        payload = response.text
    if response.status_code >= 400:
        detail = payload.get("message") if isinstance(payload, dict) else str(payload)
        raise AlpacaPaperError(f"Alpaca paper API request failed ({response.status_code}): {detail}")
    return payload


def get_account_snapshot(config: AlpacaPaperConfig | None = None) -> dict[str, Any]:
    resolved = config or load_alpaca_paper_config()
    session = _session(resolved)
    account = _request_json(session, "GET", f"{resolved.base_url}/v2/account")
    positions = _request_json(session, "GET", f"{resolved.base_url}/v2/positions")

    equity = _round_money(float(account.get("equity", 0.0) or 0.0))
    cash = _round_money(float(account.get("cash", 0.0) or 0.0))
    buying_power = _round_money(float(account.get("buying_power", 0.0) or 0.0))
    normalized_positions: list[dict[str, Any]] = []
    for item in positions:
        symbol = safe_ticker_component(str(item.get("symbol", "")).strip().upper())
        market_value = _round_money(float(item.get("market_value", 0.0) or 0.0))
        qty = float(item.get("qty", 0.0) or 0.0)
        current_weight = round(market_value / equity, 6) if equity > 0 else 0.0
        normalized_positions.append(
            {
                "ticker": symbol,
                "shares": qty,
                "current_notional": market_value,
                "current_weight": current_weight,
                "last_rating": "Hold",
            }
        )

    normalized_positions.sort(key=lambda item: item["ticker"])
    return {
        "as_of": _utcnow()[:10],
        "total_equity": equity,
        "cash_notional": cash,
        "positions": normalized_positions,
        "broker": {
            "provider": "alpaca",
            "environment": "paper",
            "account_id": account.get("account_number") or account.get("id"),
            "account_status": account.get("status"),
            "buying_power": buying_power,
            "equity": equity,
            "cash": cash,
            "currency": account.get("currency") or "USD",
            "pattern_day_trader": bool(account.get("pattern_day_trader", False)),
            "updated_at": _utcnow(),
        },
        "source": "alpaca_paper",
        "updated_at": _utcnow(),
    }


def submit_rebalance_orders(
    order_intents: list[dict[str, Any]],
    *,
    current_portfolio: dict[str, Any],
    trade_date: str,
    config: AlpacaPaperConfig | None = None,
) -> dict[str, Any]:
    if not order_intents:
        raise AlpacaPaperError("No rebalance orders were generated.")

    resolved = config or load_alpaca_paper_config()
    session = _session(resolved)
    current_positions = {
        item.get("ticker"): item
        for item in current_portfolio.get("positions", [])
        if isinstance(item, dict)
    }

    submitted_orders: list[dict[str, Any]] = []
    for index, intent in enumerate(order_intents, start=1):
        symbol = safe_ticker_component(str(intent.get("ticker", "")).strip().upper())
        side = str(intent.get("side", "")).strip().lower()
        if side not in {"buy", "sell"}:
            continue

        delta_notional = abs(float(intent.get("delta_notional", 0.0) or 0.0))
        if delta_notional <= 0.01:
            continue

        payload: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": "market",
            "time_in_force": "day",
            "client_order_id": f"ta-{trade_date.replace('-', '')}-{index}-{uuid.uuid4().hex[:10]}",
        }

        current_position = current_positions.get(symbol, {})
        shares = current_position.get("shares")
        current_notional = float(current_position.get("current_notional", 0.0) or 0.0)

        estimated_sell_qty = intent.get("estimated_sell_qty")
        if side == "sell" and isinstance(estimated_sell_qty, (int, float)) and estimated_sell_qty > 0:
            payload["qty"] = round(float(estimated_sell_qty), 6)
        elif side == "sell" and isinstance(shares, (int, float)) and shares > 0 and current_notional > 0:
            payload["qty"] = round(min(float(shares), float(shares) * delta_notional / current_notional), 6)
        else:
            payload["notional"] = _round_money(delta_notional)

        order = _request_json(session, "POST", f"{resolved.base_url}/v2/orders", json_payload=payload)
        submitted_orders.append(
            {
                "ticker": symbol,
                "side": side,
                "submitted_payload": payload,
                "alpaca_order_id": order.get("id"),
                "alpaca_status": order.get("status"),
                "submitted_at": order.get("submitted_at") or _utcnow(),
            }
        )

    if not submitted_orders:
        raise AlpacaPaperError("No valid Alpaca paper orders were submitted.")

    return {
        "execution_id": f"{trade_date}-{uuid.uuid4().hex[:12]}",
        "trade_date": trade_date,
        "broker": {"provider": "alpaca", "environment": "paper", "base_url": resolved.base_url},
        "submitted_orders": submitted_orders,
        "submitted_order_count": len(submitted_orders),
        "submitted_at": _utcnow(),
    }
