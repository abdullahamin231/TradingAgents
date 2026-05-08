import pandas as pd
import requests
from unittest.mock import MagicMock

from tradingagents.dataflows import stockstats_utils, y_finance


def _price_api_payload():
    return {
        "ticker": "AAPL",
        "source": "backtestking",
        "dates": ["2024-01-02", "2024-01-03", "2024-01-04"],
        "opens": [187.03, 184.20, 182.00],
        "closes": [185.64, 184.25, 181.91],
        "highs": [188.44, 185.88, 183.09],
        "lows": [183.89, 183.43, 180.88],
    }


def test_load_ohlcv_prefers_price_api_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(
        stockstats_utils,
        "get_config",
        lambda: {"data_cache_dir": str(tmp_path)},
    )
    monkeypatch.setenv("BACKTESTKING_PRICE_API_URL", "https://example.test/prices")
    monkeypatch.setenv("BACKTESTKING_HMAC_SECRET", "secret")

    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = _price_api_payload()
    request_get = MagicMock(return_value=response)
    monkeypatch.setattr(
        stockstats_utils,
        "requests",
        MagicMock(get=request_get),
    )

    yfinance_download = MagicMock(side_effect=AssertionError("fallback should not run"))
    monkeypatch.setattr("tradingagents.dataflows.stockstats_utils.yf.download", yfinance_download)

    first = stockstats_utils.load_ohlcv("AAPL", "2024-01-04")
    assert list(first["Date"].dt.strftime("%Y-%m-%d")) == [
        "2024-01-02",
        "2024-01-03",
        "2024-01-04",
    ]
    assert first["Open"].tolist() == [187.03, 184.2, 182.0]
    assert request_get.call_count == 1
    assert request_get.call_args.args[0] == "https://example.test/prices/AAPL"
    assert yfinance_download.call_count == 0

    cache_files = list(tmp_path.glob("*.csv"))
    assert len(cache_files) == 1

    request_get.reset_mock()
    second = stockstats_utils.load_ohlcv("AAPL", "2024-01-04")
    assert request_get.call_count == 0
    assert second["Close"].tolist() == [185.64, 184.25, 181.91]


def test_load_ohlcv_falls_back_to_yfinance_when_price_api_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(
        stockstats_utils,
        "get_config",
        lambda: {"data_cache_dir": str(tmp_path)},
    )
    monkeypatch.setenv("BACKTESTKING_PRICE_API_URL", "https://example.test/prices")

    request_get = MagicMock(side_effect=requests.RequestException("boom"))
    monkeypatch.setattr(
        stockstats_utils,
        "requests",
        MagicMock(get=request_get),
    )

    yfinance_frame = pd.DataFrame(
        {
            "Open": [10.0, 11.0],
            "High": [10.5, 11.5],
            "Low": [9.5, 10.5],
            "Close": [10.2, 11.2],
            "Volume": [100, 200],
        },
        index=pd.to_datetime(["2024-01-02", "2024-01-03"]),
    )
    yfinance_frame.index.name = "Date"
    yfinance_download = MagicMock(return_value=yfinance_frame)
    monkeypatch.setattr("tradingagents.dataflows.stockstats_utils.yf.download", yfinance_download)

    result = stockstats_utils.load_ohlcv("AAPL", "2024-01-03")

    assert request_get.call_count == 1
    assert request_get.call_args.args[0] == "https://example.test/prices/AAPL"
    assert yfinance_download.call_count == 1
    assert result["Open"].tolist() == [10.0, 11.0]
    assert result["Volume"].tolist() == [100, 200]


def test_get_yfin_data_online_uses_price_api_first(monkeypatch):
    monkeypatch.setenv("BACKTESTKING_PRICE_API_URL", "https://example.test/prices")

    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = _price_api_payload()
    monkeypatch.setattr(
        stockstats_utils,
        "requests",
        MagicMock(get=MagicMock(return_value=response)),
    )
    monkeypatch.setattr("tradingagents.dataflows.y_finance.yf.Ticker", MagicMock(side_effect=AssertionError("yfinance should not be called")))

    output = y_finance.get_YFin_data_online("AAPL", "2024-01-02", "2024-01-04")
    assert "# Stock data for AAPL" in output
    assert "2024-01-02" in output
    assert "185.64" in output


def test_volume_indicators_use_yfinance_and_separate_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(
        stockstats_utils,
        "get_config",
        lambda: {"data_cache_dir": str(tmp_path)},
    )
    monkeypatch.setenv("BACKTESTKING_PRICE_API_URL", "https://example.test/prices")

    price_response = MagicMock()
    price_response.raise_for_status.return_value = None
    price_response.json.return_value = _price_api_payload()
    price_get = MagicMock(return_value=price_response)
    monkeypatch.setattr(
        stockstats_utils,
        "requests",
        MagicMock(get=price_get),
    )

    volume_frame = pd.DataFrame(
        {
            "Open": [20.0, 21.0],
            "High": [20.5, 21.5],
            "Low": [19.5, 20.5],
            "Close": [20.2, 21.2],
            "Volume": [300, 400],
        },
        index=pd.to_datetime(["2024-01-02", "2024-01-03"]),
    )
    volume_frame.index.name = "Date"
    volume_download = MagicMock(return_value=volume_frame)
    monkeypatch.setattr("tradingagents.dataflows.stockstats_utils.yf.download", volume_download)

    price_data = stockstats_utils.load_ohlcv("AAPL", "2024-01-03")
    volume_data = stockstats_utils.load_ohlcv("AAPL", "2024-01-03", indicator="mfi")

    assert price_get.call_count == 1
    assert volume_download.call_count == 1
    assert price_data["Volume"].tolist() == [0, 0]
    assert volume_data["Volume"].tolist() == [300, 400]

    cache_files = sorted(p.name for p in tmp_path.glob("*.csv"))
    assert any("-price_api-data-" in name for name in cache_files)
    assert any("-yfinance-data-" in name for name in cache_files)


def test_source_logging_mentions_primary_and_volume_paths(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(
        stockstats_utils,
        "get_config",
        lambda: {"data_cache_dir": str(tmp_path)},
    )
    monkeypatch.setenv("BACKTESTKING_PRICE_API_URL", "https://example.test/prices")

    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = _price_api_payload()
    monkeypatch.setattr(
        stockstats_utils,
        "requests",
        MagicMock(get=MagicMock(return_value=response)),
    )

    yfinance_frame = pd.DataFrame(
        {
            "Open": [10.0, 11.0],
            "High": [10.5, 11.5],
            "Low": [9.5, 10.5],
            "Close": [10.2, 11.2],
            "Volume": [100, 200],
        },
        index=pd.to_datetime(["2024-01-02", "2024-01-03"]),
    )
    yfinance_frame.index.name = "Date"
    monkeypatch.setattr(
        "tradingagents.dataflows.stockstats_utils.yf.download",
        MagicMock(return_value=yfinance_frame),
    )

    caplog.set_level("INFO")

    stockstats_utils.load_ohlcv("AAPL", "2024-01-03")
    stockstats_utils.load_ohlcv("AAPL", "2024-01-03", indicator="mfi")

    messages = "\n".join(record.message for record in caplog.records)
    assert "using price_api" in messages
    assert "Fetching price data for AAPL from primary endpoint" in messages
    assert "using yfinance" in messages
    assert "Fetching volume-capable data for AAPL from yfinance" in messages
