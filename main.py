import logging

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

from dotenv import load_dotenv


def _print_section(title: str, content: str) -> None:
    print(f"\n{'=' * 24} {title} {'=' * 24}")
    print(content or "[empty]")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# Load environment variables from .env file
load_dotenv()

# Create a custom config
config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "opencode"
config["deep_think_llm"] = "opencode"  # Model name is ignored by the local wrapper
config["quick_think_llm"] = "opencode"  # Model name is ignored by the local wrapper
config["max_debate_rounds"] = 1  # Increase debate rounds

# Configure data vendors (default uses yfinance, no extra API keys needed)
config["data_vendors"] = {
    "core_stock_apis": "yfinance",           # Options: alpha_vantage, yfinance
    "technical_indicators": "yfinance",      # Options: alpha_vantage, yfinance
    "fundamental_data": "yfinance",          # Options: alpha_vantage, yfinance
    "news_data": "yfinance",                 # Options: alpha_vantage, yfinance
}

# Initialize with custom config
ta = TradingAgentsGraph(debug=True, config=config)

ticker = "NVDA"
trade_date = "2026-05-05"

logging.info(
    "Starting analysis for %s on %s with provider=%s",
    ticker,
    trade_date,
    config["llm_provider"],
)
logging.info(
    "Debug streaming is enabled; intermediate agent outputs will be printed during the run."
)

final_state, decision = ta.propagate(ticker, trade_date)

logging.info("Run finished with final decision: %s", decision)

_print_section("Market Report", final_state.get("market_report", ""))
_print_section("Sentiment Report", final_state.get("sentiment_report", ""))
_print_section("News Report", final_state.get("news_report", ""))
_print_section("Fundamentals Report", final_state.get("fundamentals_report", ""))
_print_section("Investment Plan", final_state.get("investment_plan", ""))
_print_section("Trader Plan", final_state.get("trader_investment_plan", ""))
_print_section("Final Trade Decision", final_state.get("final_trade_decision", ""))

# Memorize mistakes and reflect
# ta.reflect_and_remember(1000) # parameter is the position returns
