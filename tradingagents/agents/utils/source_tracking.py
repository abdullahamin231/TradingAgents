from __future__ import annotations

import contextvars
import json
import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from langchain_core.messages import AIMessage, ToolMessage

_CURRENT_ANALYST: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "tradingagents_current_analyst",
    default=None,
)
_SOURCE_LOGS: contextvars.ContextVar[dict[str, list[dict[str, Any]]] | None] = contextvars.ContextVar(
    "tradingagents_source_logs",
    default=None,
)

_URL_RE = re.compile(r"https?://[^\s<>)\"']+")


def begin_run() -> None:
    """Reset source tracking for a fresh graph invocation."""
    _SOURCE_LOGS.set({})
    _CURRENT_ANALYST.set(None)


def set_current_analyst(analyst: str) -> None:
    _CURRENT_ANALYST.set(analyst)


def get_current_analyst() -> str | None:
    return _CURRENT_ANALYST.get()


def _source_bucket(analyst: str | None = None) -> list[dict[str, Any]]:
    bucket = _SOURCE_LOGS.get() or {}
    analyst_key = analyst or _CURRENT_ANALYST.get() or "unassigned"
    if analyst_key not in bucket:
        bucket = {**bucket, analyst_key: []}
        _SOURCE_LOGS.set(bucket)
    return bucket[analyst_key]


def record_tool_source(
    tool_name: str,
    args: dict[str, Any],
    result: Any,
    *,
    vendor: str | None = None,
    analyst: str | None = None,
) -> None:
    """Record a structured source entry for the current analyst."""
    analyst_key = analyst or _CURRENT_ANALYST.get() or "unassigned"
    vendor_name = vendor or _resolve_vendor(tool_name)
    entry = {
        "tool": tool_name,
        "vendor": vendor_name,
        "args": args,
        "source_uri": _build_source_uri(tool_name, vendor_name, args),
        "visited_urls": _extract_urls(result),
        "summary": _summarize_result(result),
    }
    _source_bucket(analyst_key).append(entry)


def consume_sources(analyst: str) -> list[dict[str, Any]]:
    """Return and clear the collected source entries for one analyst."""
    bucket = _SOURCE_LOGS.get() or {}
    entries = list(bucket.get(analyst, []))
    if not entries:
        return []
    bucket = {**bucket, analyst: []}
    _SOURCE_LOGS.set(bucket)
    return entries


def get_all_sources() -> dict[str, list[dict[str, Any]]]:
    """Return a snapshot of all currently collected source entries."""
    bucket = _SOURCE_LOGS.get() or {}
    return {key: list(value) for key, value in bucket.items()}


def _resolve_vendor(tool_name: str) -> str:
    from tradingagents.dataflows.interface import get_vendor

    if tool_name == "get_stock_data":
        category = "core_stock_apis"
    elif tool_name == "get_indicators":
        category = "technical_indicators"
    elif tool_name in {"get_fundamentals", "get_balance_sheet", "get_cashflow", "get_income_statement"}:
        category = "fundamental_data"
    elif tool_name in {"get_news", "get_global_news", "get_insider_transactions"}:
        category = "news_data"
    else:
        return "unknown"
    return get_vendor(category, tool_name)


def _build_source_uri(tool_name: str, vendor: str, args: dict[str, Any]) -> str:
    if vendor == "alpha_vantage":
        return _alpha_vantage_source_uri(tool_name, args)
    if vendor == "yfinance":
        return f"yfinance://{tool_name}"
    return f"{vendor}://{tool_name}"


def _alpha_vantage_source_uri(tool_name: str, args: dict[str, Any]) -> str:
    base = "https://www.alphavantage.co/query"
    params: dict[str, Any]
    if tool_name == "get_stock_data":
        params = {
            "function": "TIME_SERIES_DAILY_ADJUSTED",
            "symbol": args.get("symbol"),
            "outputsize": "compact",
            "datatype": "csv",
        }
    elif tool_name == "get_indicators":
        indicator = str(args.get("indicator", "")).strip().lower()
        indicator_to_function = {
            "close_50_sma": ("SMA", {"time_period": "50", "series_type": "close"}),
            "close_200_sma": ("SMA", {"time_period": "200", "series_type": "close"}),
            "close_10_ema": ("EMA", {"time_period": "10", "series_type": "close"}),
            "macd": ("MACD", {"series_type": "close"}),
            "macds": ("MACD", {"series_type": "close"}),
            "macdh": ("MACD", {"series_type": "close"}),
            "rsi": ("RSI", {"time_period": str(args.get("time_period", 14)), "series_type": "close"}),
            "boll": ("BBANDS", {"time_period": "20", "series_type": "close"}),
            "boll_ub": ("BBANDS", {"time_period": "20", "series_type": "close"}),
            "boll_lb": ("BBANDS", {"time_period": "20", "series_type": "close"}),
            "atr": ("ATR", {"time_period": str(args.get("time_period", 14))}),
            "vwma": ("VWMA", {}),
        }
        function_name, extra = indicator_to_function.get(indicator, ("UNKNOWN", {}))
        params = {
            "function": function_name,
            "symbol": args.get("symbol"),
            "interval": args.get("interval", "daily"),
            "datatype": "csv",
            **extra,
        }
    elif tool_name == "get_fundamentals":
        params = {"function": "OVERVIEW", "symbol": args.get("ticker")}
    elif tool_name == "get_balance_sheet":
        params = {"function": "BALANCE_SHEET", "symbol": args.get("ticker")}
    elif tool_name == "get_cashflow":
        params = {"function": "CASH_FLOW", "symbol": args.get("ticker")}
    elif tool_name == "get_income_statement":
        params = {"function": "INCOME_STATEMENT", "symbol": args.get("ticker")}
    elif tool_name == "get_news":
        from tradingagents.dataflows.alpha_vantage_common import format_datetime_for_api

        params = {
            "function": "NEWS_SENTIMENT",
            "tickers": args.get("ticker"),
            "time_from": format_datetime_for_api(args.get("start_date")),
            "time_to": format_datetime_for_api(args.get("end_date")),
        }
    elif tool_name == "get_global_news":
        from tradingagents.dataflows.alpha_vantage_common import format_datetime_for_api

        curr_date = args.get("curr_date")
        look_back_days = int(args.get("look_back_days", 7))
        curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        start_dt = curr_dt - timedelta(days=look_back_days)
        params = {
            "function": "NEWS_SENTIMENT",
            "topics": "financial_markets,economy_macro,economy_monetary",
            "limit": args.get("limit", 50),
            "time_from": format_datetime_for_api(start_dt.strftime("%Y-%m-%d")),
            "time_to": format_datetime_for_api(curr_date),
        }
    elif tool_name == "get_insider_transactions":
        params = {"function": "INSIDER_TRANSACTIONS", "symbol": args.get("ticker")}
    else:
        params = {"function": tool_name}
    return f"{base}?{urlencode({k: v for k, v in params.items() if v is not None})}"


def _extract_urls(result: Any) -> list[str]:
    if result is None:
        return []

    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
    urls = list(dict.fromkeys(_URL_RE.findall(text)))
    return urls


def _summarize_result(result: Any, limit: int = 220) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        text = result.strip()
    else:
        text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def format_sources_markdown(analyst_title: str, sources: list[dict[str, Any]]) -> str:
    """Render a compact markdown appendix for a single analyst."""
    if not sources:
        return ""

    lines = [f"## {analyst_title} Sources", ""]
    for index, source in enumerate(sources, start=1):
        lines.append(f"{index}. `{source.get('tool', 'tool')}` via `{source.get('vendor', 'unknown')}`")
        source_uri = source.get("source_uri")
        if source_uri:
            lines.append(f"   - Source: {source_uri}")
        urls = source.get("visited_urls") or []
        if urls:
            lines.append("   - Visited links:")
            for url in urls:
                lines.append(f"     - {url}")
        summary = source.get("summary")
        if summary:
            lines.append(f"   - Evidence: {summary}")
    return "\n".join(lines)


def extract_sources_from_messages(messages: list[Any], analyst: str) -> list[dict[str, Any]]:
    """Rebuild source entries from LangChain messages when the live collector is empty."""
    tool_calls: dict[str, dict[str, Any]] = {}
    sources: list[dict[str, Any]] = []

    for message in messages:
        if isinstance(message, AIMessage) and getattr(message, "tool_calls", None):
            for call in message.tool_calls:
                call_dict = call if isinstance(call, dict) else {
                    "id": getattr(call, "id", None),
                    "name": getattr(call, "name", None),
                    "args": getattr(call, "args", {}),
                }
                call_id = call_dict.get("id")
                if call_id:
                    tool_calls[call_id] = call_dict

        if isinstance(message, ToolMessage):
            call = tool_calls.get(getattr(message, "tool_call_id", ""))
            tool_name = (call or {}).get("name", "unknown")
            args = (call or {}).get("args", {})
            vendor = _resolve_vendor(tool_name) if tool_name != "unknown" else "unknown"
            result = getattr(message, "content", "")
            sources.append(
                {
                    "tool": tool_name,
                    "vendor": vendor,
                    "args": args,
                    "source_uri": _build_source_uri(tool_name, vendor, args),
                    "visited_urls": _extract_urls(result),
                    "summary": _summarize_result(result),
                    "analyst": analyst,
                }
            )

    return sources
