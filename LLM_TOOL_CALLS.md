# TradingAgents LLM Tool Calls

This file lists the tool-calling surface exposed to LLM-backed agents in the current codebase.

## Agents That Use Tool Calls

OpenCode support: yes, for the agents in this section when the client returns the expected JSON tool-call envelope.

### Market Analyst
- `get_stock_data`
- `get_indicators`

Notes:
- The prompt instructs the model to call `get_stock_data` first.
- `get_indicators` is meant to be called once per indicator.

### Social Media Analyst
- `get_news`

### News Analyst
- `get_news`
- `get_global_news`

### Fundamentals Analyst
- `get_fundamentals`
- `get_balance_sheet`
- `get_cashflow`
- `get_income_statement`

## LLM Calls That Do Not Use Tools

OpenCode support: no, because these agents do not call `bind_tools()`.

These agents invoke the LLM directly, without tool binding:

- Bull Researcher
- Bear Researcher
- Conservative Risk Analyst
- Aggressive Risk Analyst
- Neutral Risk Analyst

These agents use plain prompt-based generation.

## Structured-Output LLM Calls

OpenCode support: yes, when the provider can satisfy `with_structured_output()`; otherwise the agents fall back to free text.

These agents do not call tools, but they do use structured output when supported:

- Research Manager
- Trader
- Portfolio Manager

If structured output is unavailable or fails, they fall back to free-text generation.

## Where The Tool Calls Are Wired

- Tool nodes are assembled in [`tradingagents/graph/trading_graph.py`](tradingagents/graph/trading_graph.py).
- Tool binding happens in the analyst agents under [`tradingagents/agents/analysts/`](tradingagents/agents/analysts/).
- The individual tool definitions live in [`tradingagents/agents/utils/`](tradingagents/agents/utils/).

## Full Tool List By Category

### Market / Technical
- `get_stock_data`
- `get_indicators`

### Social / News
- `get_news`

### News / Macro
- `get_news`
- `get_global_news`
- `get_insider_transactions`

### Fundamentals
- `get_fundamentals`
- `get_balance_sheet`
- `get_cashflow`
- `get_income_statement`
