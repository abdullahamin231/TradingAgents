import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from webui.service_webull import WebullPaperBroker, WebullPaperConfig, generate_signature


def test_generate_signature_matches_webull_docs_example():
    signature = generate_signature(
        "/trade/place_order",
        {"a1": "webull", "a2": "123", "a3": "xxx", "q1": "yyy"},
        '{"k1":123,"k2":"this is the api request body","k3":true,"k4":{"foo":[1,2]}}',
        app_key="776da210ab4a452795d74e726ebd74b6",
        app_secret="0f50a2e853334a9aae1a783bee120c1f",
        host="api.webull.com",
        timestamp="2022-01-04T03:55:31Z",
        nonce="48ef5afed43d4d91ae514aaeafbc29ba",
    )

    assert signature == "kvlS6opdZDhEBo5jq40nHYXaLvM="


def test_webull_submit_rebalance_orders_uses_amount_for_buys_and_qty_for_sells():
    calls = []

    class FakeClient:
        def request(self, method, path, *, query_params=None, body=None):
            calls.append({"method": method, "path": path, "query_params": query_params, "body": body})
            return {"order_id": f"order-{len(calls)}"}

    broker = WebullPaperBroker(
        config=WebullPaperConfig(app_key="key", app_secret="secret", account_id="acct"),
        client=FakeClient(),
    )
    result = broker.submit_rebalance_orders(
        [
            {"ticker": "BUYME", "side": "buy", "delta_notional": 125.5},
            {"ticker": "SELLME", "side": "sell", "delta_notional": 50.0, "estimated_sell_qty": 3},
        ],
        current_portfolio={"positions": [{"ticker": "SELLME", "shares": 10, "current_notional": 100.0}]},
        trade_date="2026-05-23",
    )

    assert result["broker"]["provider"] == "webull"
    assert result["submitted_order_count"] == 2
    buy_order = calls[0]["body"]["new_orders"][0]
    sell_order = calls[1]["body"]["new_orders"][0]
    assert calls[0]["path"] == "/openapi/trade/order/place"
    assert buy_order["entrust_type"] == "AMOUNT"
    assert buy_order["total_cash_amount"] == "125.50"
    assert sell_order["entrust_type"] == "QTY"
    assert sell_order["quantity"] == "3.0"
