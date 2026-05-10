from langchain_core.messages import HumanMessage, RemoveMessage

# Import tools from separate utility files
from tradingagents.agents.utils.core_stock_tools import (
    get_stock_data
)
from tradingagents.agents.utils.technical_indicators_tools import (
    get_indicators
)
from tradingagents.agents.utils.fundamental_data_tools import (
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement
)
from tradingagents.agents.utils.news_data_tools import (
    get_news,
    get_insider_transactions,
    get_global_news
)
from tradingagents.agents.utils.source_tracking import (
    begin_run,
    consume_sources,
    extract_sources_from_messages,
)


def get_language_instruction() -> str:
    """Return a prompt instruction for the configured output language.

    Returns empty string when English (default), so no extra tokens are used.
    Only applied to user-facing agents (analysts, portfolio manager).
    Internal debate agents stay in English for reasoning quality.
    """
    from tradingagents.dataflows.config import get_config
    lang = get_config().get("output_language", "English")
    if lang.strip().lower() == "english":
        return ""
    return f" Write your entire response in {lang}."


def build_instrument_context(ticker: str) -> str:
    """Describe the exact instrument so agents preserve exchange-qualified tickers."""
    return (
        f"The instrument to analyze is `{ticker}`. "
        "Use this exact ticker in every tool call, report, and recommendation, "
        "preserving any exchange suffix (e.g. `.TO`, `.L`, `.HK`, `.T`)."
    )

_SOURCE_FIELD_BY_ANALYST = {
    "market": "market_sources",
    "social": "sentiment_sources",
    "news": "news_sources",
    "fundamentals": "fundamentals_sources",
}


def create_msg_delete(analyst_type: str):
    def delete_messages(state):
        """Clear messages and add placeholder for Anthropic compatibility"""
        messages = state["messages"]
        source_field = _SOURCE_FIELD_BY_ANALYST.get(analyst_type)
        sources = consume_sources(analyst_type) if source_field else []
        if source_field and not sources:
            sources = extract_sources_from_messages(messages, analyst_type)
            consume_sources("unassigned")

        # Remove all messages
        removal_operations = [RemoveMessage(id=m.id) for m in messages]

        # Add a minimal placeholder message
        placeholder = HumanMessage(content="Continue")

        result = {"messages": removal_operations + [placeholder]}
        if source_field:
            result[source_field] = sources
        return result

    return delete_messages


def begin_source_tracking():
    """Reset the source log for a fresh analysis run."""
    begin_run()


        
