from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

from dotenv import load_dotenv

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
ta = TradingAgentsGraph(debug=False, config=config)

ticker = "SPY"
trade_date = "2026-05-05"

final_state, decision = ta.propagate(ticker, trade_date)

print(final_state.get("final_trade_decision") or decision or "")

# Memorize mistakes and reflect
# ta.reflect_and_remember(1000) # parameter is the position returns
