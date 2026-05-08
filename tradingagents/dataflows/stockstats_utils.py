import hashlib
import hmac
import logging
import os
import time
from typing import Annotated, Optional, TypedDict

import pandas as pd
import requests
from requests import RequestException
import yfinance as yf
from yfinance.exceptions import YFRateLimitError
from stockstats import wrap

from .config import get_config
from .utils import safe_ticker_component

logger = logging.getLogger(__name__)

VOLUME_INDICATORS = {"vwma", "mfi"}


class PriceApiResponse(TypedDict, total=False):
    ticker: str
    source: str
    dates: list[str]
    opens: list[float]
    closes: list[float]
    highs: list[float]
    lows: list[float]


def yf_retry(func, max_retries=3, base_delay=2.0):
    """Execute a yfinance call with exponential backoff on rate limits.

    yfinance raises YFRateLimitError on HTTP 429 responses but does not
    retry them internally. This wrapper adds retry logic specifically
    for rate limits. Other exceptions propagate immediately.
    """
    for attempt in range(max_retries + 1):
        try:
            return func()
        except YFRateLimitError:
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Yahoo Finance rate limited, retrying in {delay:.0f}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
            else:
                raise


def build_price_hmac_headers(body: str = "") -> Optional[dict[str, str]]:
    secret = os.getenv("BACKTESTKING_HMAC_SECRET")
    if not secret:
        return None

    timestamp = str(int(time.time()))
    hmac_digest = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.{body}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "X-Backtest-Timestamp": timestamp,
        "X-Backtest-Signature": hmac_digest,
    }


def _price_api_response_to_dataframe(payload: PriceApiResponse) -> Optional[pd.DataFrame]:
    dates = payload.get("dates") or []
    opens = payload.get("opens") or []
    closes = payload.get("closes") or []
    highs = payload.get("highs") or []
    lows = payload.get("lows") or []

    if not dates:
        return None

    lengths = {len(dates), len(opens), len(closes), len(highs), len(lows)}
    if len(lengths) != 1:
        return None

    data = pd.DataFrame(
        {
            "Date": pd.to_datetime(dates, errors="coerce"),
            "Open": pd.to_numeric(opens, errors="coerce"),
            "High": pd.to_numeric(highs, errors="coerce"),
            "Low": pd.to_numeric(lows, errors="coerce"),
            "Close": pd.to_numeric(closes, errors="coerce"),
        }
    )
    data = data.dropna(subset=["Date", "Open", "High", "Low", "Close"])
    if data.empty:
        return None

    # The fallback yfinance path carries volume, so keep a compatible column
    # for downstream code that expects OHLCV-shaped data.
    data["Volume"] = 0
    return data


def fetch_price_api_ohlcv(symbol: str) -> Optional[pd.DataFrame]:
    base_url = os.getenv("BACKTESTKING_PRICE_API_URL")
    if not base_url:
        logger.info("Price API disabled for %s: BACKTESTKING_PRICE_API_URL is not set", symbol)
        return None

    headers = build_price_hmac_headers(body="")
    request_headers = headers if headers else None
    request_url = base_url.rstrip("/") + f"/{symbol.upper()}"

    logger.info(
        "Fetching price data for %s from primary endpoint %s",
        symbol.upper(),
        request_url,
    )

    try:
        response = requests.get(
            request_url,
            headers=request_headers,
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
    except (RequestException, ValueError, TypeError) as exc:
        logger.warning("Price API request failed for %s, falling back to yfinance: %s", symbol, exc)
        return None

    if not isinstance(payload, dict):
        return None

    data = _price_api_response_to_dataframe(payload)
    if data is None or data.empty:
        logger.warning("Price API returned no usable rows for %s, falling back to yfinance", symbol)
        return None

    logger.info("Price API returned %d rows for %s", len(data), symbol.upper())
    return data


def indicator_requires_volume(indicator: Optional[str]) -> bool:
    return bool(indicator and indicator in VOLUME_INDICATORS)


def _clean_dataframe(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize a stock DataFrame for stockstats: parse dates, drop invalid rows, fill price gaps."""
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data = data.dropna(subset=["Date"])

    price_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in data.columns]
    data[price_cols] = data[price_cols].apply(pd.to_numeric, errors="coerce")
    data = data.dropna(subset=["Close"])
    data[price_cols] = data[price_cols].ffill().bfill()

    return data


def load_ohlcv(symbol: str, curr_date: str, indicator: Optional[str] = None) -> pd.DataFrame:
    """Fetch OHLCV data with caching, filtered to prevent look-ahead bias.

    Downloads 15 years of data up to today and caches per symbol. On
    subsequent calls the cache is reused. Rows after curr_date are
    filtered out so backtests never see future prices.
    """
    # Reject ticker values that would escape the cache directory when
    # interpolated into the cache filename (e.g. ``../../tmp/x``).
    safe_symbol = safe_ticker_component(symbol)

    config = get_config()
    curr_date_dt = pd.to_datetime(curr_date)

    source = "yfinance" if indicator_requires_volume(indicator) else "price_api"
    logger.info(
        "Loading OHLCV for %s with indicator=%s using %s",
        symbol.upper(),
        indicator or "none",
        source,
    )

    # Cache uses a fixed window (15y to today) so one file per symbol/source.
    today_date = pd.Timestamp.today()
    start_date = today_date - pd.DateOffset(years=5)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = today_date.strftime("%Y-%m-%d")

    os.makedirs(config["data_cache_dir"], exist_ok=True)
    data_file = os.path.join(
        config["data_cache_dir"],
        f"{safe_symbol}-{source}-data-{start_str}-{end_str}.csv",
    )

    if os.path.exists(data_file):
        logger.info("Using cached %s data for %s from %s", source, symbol.upper(), data_file)
        data = pd.read_csv(data_file, on_bad_lines="skip", encoding="utf-8")
    else:
        if source == "yfinance":
            logger.info("Fetching volume-capable data for %s from yfinance", symbol.upper())
            data = yf_retry(lambda: yf.download(
                symbol,
                start=start_str,
                end=end_str,
                multi_level_index=False,
                progress=False,
                auto_adjust=True,
            ))
            data = data.reset_index()
        else:
            data = fetch_price_api_ohlcv(symbol)
            if data is None:
                logger.info("Falling back to yfinance for %s after price API miss", symbol.upper())
                data = yf_retry(lambda: yf.download(
                    symbol,
                    start=start_str,
                    end=end_str,
                    multi_level_index=False,
                    progress=False,
                    auto_adjust=True,
                ))
                data = data.reset_index()
        data.to_csv(data_file, index=False, encoding="utf-8")
        logger.info("Cached %s data for %s at %s", source, symbol.upper(), data_file)

    data = _clean_dataframe(data)

    # Filter to curr_date to prevent look-ahead bias in backtesting
    data = data[data["Date"] <= curr_date_dt]

    return data


def filter_financials_by_date(data: pd.DataFrame, curr_date: str) -> pd.DataFrame:
    """Drop financial statement columns (fiscal period timestamps) after curr_date.

    yfinance financial statements use fiscal period end dates as columns.
    Columns after curr_date represent future data and are removed to
    prevent look-ahead bias.
    """
    if not curr_date or data.empty:
        return data
    cutoff = pd.Timestamp(curr_date)
    mask = pd.to_datetime(data.columns, errors="coerce") <= cutoff
    return data.loc[:, mask]


class StockstatsUtils:
    @staticmethod
    def get_stock_stats(
        symbol: Annotated[str, "ticker symbol for the company"],
        indicator: Annotated[
            str, "quantitative indicators based off of the stock data for the company"
        ],
        curr_date: Annotated[
            str, "curr date for retrieving stock price data, YYYY-mm-dd"
        ],
    ):
        data = load_ohlcv(symbol, curr_date, indicator=indicator)
        df = wrap(data)
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
        curr_date_str = pd.to_datetime(curr_date).strftime("%Y-%m-%d")

        df[indicator]  # trigger stockstats to calculate the indicator
        matching_rows = df[df["Date"].str.startswith(curr_date_str)]

        if not matching_rows.empty:
            indicator_value = matching_rows[indicator].values[0]
            return indicator_value
        else:
            return "N/A: Not a trading day (weekend or holiday)"
