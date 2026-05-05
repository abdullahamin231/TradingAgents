import os

_DEFAULT_BACKEND_URL = os.getenv("TRADINGAGENTS_BACKEND_URL")
_DEFAULT_RESULTS_DIR = os.getenv("TRADINGAGENTS_RESULTS_DIR", os.path.join(os.getcwd(), "reports"))
_DEFAULT_DATA_CACHE_DIR = os.getenv(
    "TRADINGAGENTS_CACHE_DIR",
    os.path.join(_DEFAULT_RESULTS_DIR, "cache"),
)
_DEFAULT_MEMORY_LOG_PATH = os.getenv(
    "TRADINGAGENTS_MEMORY_LOG_PATH",
    os.path.join(_DEFAULT_RESULTS_DIR, "memory", "trading_memory.md"),
)

DEFAULT_CONFIG = {
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": _DEFAULT_RESULTS_DIR,
    "data_cache_dir": _DEFAULT_DATA_CACHE_DIR,
    "memory_log_path": _DEFAULT_MEMORY_LOG_PATH,
    # Optional cap on the number of resolved memory log entries. When set,
    # the oldest resolved entries are pruned once this limit is exceeded.
    # Pending entries are never pruned. None disables rotation entirely.
    "memory_log_max_entries": None,
    # LLM settings
    "llm_provider": "openai",
    "deep_think_llm": "gpt-5.4",
    "quick_think_llm": "gpt-5.4-mini",
    # When None, each provider's client falls back to its own default endpoint
    # (api.openai.com for OpenAI, generativelanguage.googleapis.com for Gemini, ...).
    # The CLI overrides this per provider when the user picks one. Keeping a
    # provider-specific URL here would leak (e.g. OpenAI's /v1 was previously
    # being forwarded to Gemini, producing malformed request URLs).
    "backend_url": _DEFAULT_BACKEND_URL,
    # Provider-specific thinking configuration
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # "medium", "high", "low"
    "anthropic_effort": None,           # "high", "medium", "low"
    # Checkpoint/resume: when True, LangGraph saves state after each node
    # so a crashed run can resume from the last successful step.
    "checkpoint_enabled": False,
    # Output language for analyst reports and final decision
    # Internal agent debate stays in English for reasoning quality
    "output_language": "English",
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    # Data vendor configuration
    # Category-level configuration (default for all tools in category)
    "data_vendors": {
        "core_stock_apis": "yfinance",       # Options: alpha_vantage, yfinance
        "technical_indicators": "yfinance",  # Options: alpha_vantage, yfinance
        "fundamental_data": "yfinance",      # Options: alpha_vantage, yfinance
        "news_data": "yfinance",             # Options: alpha_vantage, yfinance
    },
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {
        # Example: "get_stock_data": "alpha_vantage",  # Override category default
    },
}
