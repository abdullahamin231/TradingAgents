from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import urllib.parse
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

from tradingagents.dataflows.utils import safe_ticker_component

from .service_broker import BrokerError


DEFAULT_WEBULL_PAPER_HOST = "us-openapi-alb.uat.webullbroker.com"
DEFAULT_WEBULL_PRODUCTION_HOST = "api.webull.com"


def _utcnow() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _round_money(value: float) -> float:
    return round(float(value), 2)


def _first_number(payload: dict[str, Any], keys: tuple[str, ...], default: float = 0.0) -> float:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def _extract_items(payload: Any, keys: tuple[str, ...]) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return _extract_items(data, keys)
    return []


@dataclass(frozen=True)
class WebullPaperConfig:
    app_key: str
    app_secret: str
    account_id: str | None = None
    access_token: str | None = None
    host: str = DEFAULT_WEBULL_PAPER_HOST
    environment: str = "paper"

    @property
    def base_url(self) -> str:
        return f"https://{self.host}"


class WebullPaperError(BrokerError):
    pass


def load_webull_paper_config() -> WebullPaperConfig:
    app_key = (os.getenv("WEBULL_APP_KEY") or "").strip()
    app_secret = (os.getenv("WEBULL_APP_SECRET") or "").strip()
    account_id = (os.getenv("WEBULL_ACCOUNT_ID") or "").strip() or None
    access_token = (os.getenv("WEBULL_ACCESS_TOKEN") or "").strip() or None
    environment = "paper"
    default_host = DEFAULT_WEBULL_PAPER_HOST
    host = (os.getenv("WEBULL_API_HOST") or default_host).strip().removeprefix("https://").rstrip("/")
    if not app_key or not app_secret:
        raise WebullPaperError("Webull paper trading credentials are missing. Set WEBULL_APP_KEY and WEBULL_APP_SECRET.")
    return WebullPaperConfig(
        app_key=app_key,
        app_secret=app_secret,
        account_id=account_id,
        access_token=access_token,
        host=host,
        environment=environment if environment else "paper",
    )


def generate_signature(
    path: str,
    query_params: dict[str, Any],
    body_string: str | None,
    *,
    app_key: str,
    app_secret: str,
    host: str,
    timestamp: str,
    nonce: str,
) -> str:
    signing_headers = {
        "host": host,
        "x-app-key": app_key,
        "x-signature-algorithm": "HMAC-SHA1",
        "x-signature-nonce": nonce,
        "x-signature-version": "1.0",
        "x-timestamp": timestamp,
    }
    all_params = {key: str(value) for key, value in query_params.items()}
    all_params.update(signing_headers)
    str1 = "&".join(f"{key}={all_params[key]}" for key in sorted(all_params))
    str3 = f"{path}&{str1}"
    if body_string:
        str3 = f"{str3}&{hashlib.md5(body_string.encode('utf-8')).hexdigest().upper()}"
    encoded = urllib.parse.quote(str3, safe="")
    digest = hmac.new(f"{app_secret}&".encode("utf-8"), encoded.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


class WebullRestClient:
    def __init__(self, config: WebullPaperConfig):
        self.config = config

    def request(
        self,
        method: str,
        path: str,
        *,
        query_params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        params = query_params or {}
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        nonce = uuid.uuid4().hex
        body_string = json.dumps(body, separators=(",", ":")) if body else None
        signature = generate_signature(
            path,
            params,
            body_string,
            app_key=self.config.app_key,
            app_secret=self.config.app_secret,
            host=self.config.host,
            timestamp=timestamp,
            nonce=nonce,
        )
        headers = {
            "Accept": "application/json",
            "x-app-key": self.config.app_key,
            "x-timestamp": timestamp,
            "x-signature": signature,
            "x-signature-algorithm": "HMAC-SHA1",
            "x-signature-version": "1.0",
            "x-signature-nonce": nonce,
            "x-version": "v2",
        }
        if self.config.access_token:
            headers["x-access-token"] = self.config.access_token
        if body_string is not None:
            headers["Content-Type"] = "application/json"

        response = requests.request(
            method.upper(),
            f"{self.config.base_url}{path}",
            params=params or None,
            data=body_string,
            headers=headers,
            timeout=20,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
        if response.status_code >= 400:
            detail = payload.get("message") if isinstance(payload, dict) else str(payload)
            raise WebullPaperError(f"Webull paper API request failed ({response.status_code}): {detail}")
        return payload


class WebullPaperBroker:
    provider = "webull"

    def __init__(self, config: WebullPaperConfig | None = None, client: WebullRestClient | None = None):
        self.config = config or load_webull_paper_config()
        self.environment = self.config.environment
        self.client = client or WebullRestClient(self.config)

    def _account_id(self) -> str:
        if self.config.account_id:
            return self.config.account_id
        accounts = _extract_items(self.client.request("GET", "/openapi/account/list"), ("accounts", "account_list"))
        if not accounts:
            raise WebullPaperError("Webull account list was empty. Set WEBULL_ACCOUNT_ID explicitly.")
        first = accounts[0]
        if not isinstance(first, dict):
            raise WebullPaperError("Webull account list returned an unsupported shape.")
        account_id = first.get("account_id") or first.get("accountId") or first.get("id")
        if not account_id:
            raise WebullPaperError("Webull account list did not include an account_id.")
        return str(account_id)

    def get_account_snapshot(self) -> dict[str, Any]:
        account_id = self._account_id()
        query = {"account_id": account_id}
        balance = self.client.request("GET", "/openapi/assets/balance", query_params=query)
        positions_payload = self.client.request("GET", "/openapi/assets/positions", query_params=query)
        balance_data = balance.get("data", balance) if isinstance(balance, dict) else {}
        positions = _extract_items(positions_payload, ("positions", "position_list", "holdings"))

        equity = _round_money(_first_number(balance_data, ("net_liquidation", "netLiquidation", "equity", "total_equity", "account_value")))
        cash = _round_money(_first_number(balance_data, ("cash", "cash_balance", "cashBalance", "available_cash")))
        buying_power = _round_money(_first_number(balance_data, ("buying_power", "buyingPower", "day_buying_power", "available_funds"), equity))
        total_equity = equity if equity > 0 else _round_money(cash + sum(_first_number(item, ("market_value", "marketValue")) for item in positions if isinstance(item, dict)))

        normalized_positions: list[dict[str, Any]] = []
        for item in positions:
            if not isinstance(item, dict):
                continue
            symbol = safe_ticker_component(str(item.get("symbol") or item.get("ticker") or item.get("instrument_symbol") or "").strip().upper())
            if not symbol:
                continue
            market_value = _round_money(_first_number(item, ("market_value", "marketValue", "position_value", "positionValue")))
            qty = _first_number(item, ("quantity", "qty", "position", "holding_quantity"))
            current_weight = round(market_value / total_equity, 6) if total_equity > 0 else 0.0
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
            "total_equity": total_equity,
            "cash_notional": cash,
            "positions": normalized_positions,
            "broker": {
                "provider": self.provider,
                "environment": self.environment,
                "account_id": account_id,
                "buying_power": buying_power,
                "equity": total_equity,
                "cash": cash,
                "currency": balance_data.get("currency") or "USD" if isinstance(balance_data, dict) else "USD",
                "base_url": self.config.base_url,
                "updated_at": _utcnow(),
            },
            "source": "webull_paper",
            "updated_at": _utcnow(),
        }

    def submit_rebalance_orders(
        self,
        order_intents: list[dict[str, Any]],
        *,
        current_portfolio: dict[str, Any],
        trade_date: str,
    ) -> dict[str, Any]:
        if not order_intents:
            raise WebullPaperError("No rebalance orders were generated.")

        account_id = self._account_id()
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

            client_order_id = f"ta{trade_date.replace('-', '')}{index}{uuid.uuid4().hex[:8]}"[:32]
            order: dict[str, Any] = {
                "client_order_id": client_order_id,
                "combo_type": "NORMAL",
                "symbol": symbol,
                "instrument_type": "EQUITY",
                "market": "US",
                "order_type": "MARKET",
                "side": side.upper(),
                "time_in_force": "DAY",
                "support_trading_session": "CORE",
            }
            current_position = current_positions.get(symbol, {})
            shares = current_position.get("shares")
            current_notional = float(current_position.get("current_notional", 0.0) or 0.0)
            estimated_sell_qty = intent.get("estimated_sell_qty")
            if side == "sell" and isinstance(estimated_sell_qty, (int, float)) and estimated_sell_qty > 0:
                order["entrust_type"] = "QTY"
                order["quantity"] = str(round(float(estimated_sell_qty), 6))
            elif side == "sell" and isinstance(shares, (int, float)) and shares > 0 and current_notional > 0:
                order["entrust_type"] = "QTY"
                order["quantity"] = str(round(min(float(shares), float(shares) * delta_notional / current_notional), 6))
            else:
                order["entrust_type"] = "AMOUNT"
                order["total_cash_amount"] = f"{_round_money(delta_notional):.2f}"

            payload = {"account_id": account_id, "new_orders": [order]}
            response = self.client.request("POST", "/openapi/trade/order/place", body=payload)
            submitted_orders.append(
                {
                    "ticker": symbol,
                    "side": side,
                    "submitted_payload": payload,
                    "webull_order_id": response.get("order_id") if isinstance(response, dict) else None,
                    "webull_client_order_id": order["client_order_id"],
                    "webull_status": response.get("status") if isinstance(response, dict) else None,
                    "submitted_at": _utcnow(),
                }
            )

        if not submitted_orders:
            raise WebullPaperError("No valid Webull paper orders were submitted.")

        return {
            "execution_id": f"{trade_date}-{uuid.uuid4().hex[:12]}",
            "trade_date": trade_date,
            "broker": {"provider": self.provider, "environment": self.environment, "base_url": self.config.base_url},
            "submitted_orders": submitted_orders,
            "submitted_order_count": len(submitted_orders),
            "submitted_at": _utcnow(),
        }


def get_account_snapshot(config: WebullPaperConfig | None = None) -> dict[str, Any]:
    return WebullPaperBroker(config=config).get_account_snapshot()


def submit_rebalance_orders(
    order_intents: list[dict[str, Any]],
    *,
    current_portfolio: dict[str, Any],
    trade_date: str,
    config: WebullPaperConfig | None = None,
) -> dict[str, Any]:
    return WebullPaperBroker(config=config).submit_rebalance_orders(
        order_intents,
        current_portfolio=current_portfolio,
        trade_date=trade_date,
    )
