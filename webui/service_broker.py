from __future__ import annotations

import os
from typing import Any, Protocol


DEFAULT_BROKER_PROVIDER = "alpaca_paper"


class BrokerError(RuntimeError):
    pass


class PaperBroker(Protocol):
    provider: str
    environment: str

    def get_account_snapshot(self) -> dict[str, Any]:
        ...

    def submit_rebalance_orders(
        self,
        order_intents: list[dict[str, Any]],
        *,
        current_portfolio: dict[str, Any],
        trade_date: str,
    ) -> dict[str, Any]:
        ...


def normalize_broker_provider(provider: str | None = None) -> str:
    value = (provider or os.getenv("TRADINGAGENTS_BROKER_PROVIDER") or DEFAULT_BROKER_PROVIDER).strip().lower()
    aliases = {
        "alpaca": "alpaca_paper",
        "alpaca-paper": "alpaca_paper",
        "alpaca_paper": "alpaca_paper",
        "webull": "webull_paper",
        "webull-paper": "webull_paper",
        "webull_paper": "webull_paper",
    }
    resolved = aliases.get(value)
    if not resolved:
        raise BrokerError(f"Unsupported broker provider '{provider or value}'.")
    return resolved


def get_broker(provider: str | None = None) -> PaperBroker:
    resolved = normalize_broker_provider(provider)
    if resolved == "alpaca_paper":
        from .service_alpaca import AlpacaPaperBroker

        return AlpacaPaperBroker()
    if resolved == "webull_paper":
        from .service_webull import WebullPaperBroker

        return WebullPaperBroker()
    raise BrokerError(f"Unsupported broker provider '{resolved}'.")


def list_broker_options() -> list[dict[str, str]]:
    return [
        {"label": "Alpaca Paper", "value": "alpaca_paper"},
        {"label": "Webull Paper", "value": "webull_paper"},
    ]
