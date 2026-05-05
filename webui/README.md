# TradingAgents Web Interface

Run the web app from the repo root:

```bash
uvicorn webui.app:app --reload
```

The interface:

- runs `TradingAgentsGraph` directly for one or more ticker/date pairs
- keeps `llm_provider="opencode"` for every run
- reads the active OpenCode model from `opencode.json`
- lists and renders saved JSON logs from `reports/<ticker>/TradingAgentsStrategy_logs/`

If you want more or fewer concurrent runs, set:

```bash
export TRADINGAGENTS_WEB_MAX_WORKERS=4
```
