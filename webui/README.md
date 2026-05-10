# TradingAgents Web Interface

Run the web app from the repo root:

```bash
uvicorn webui.app:app --reload
```

The interface:

- runs `TradingAgentsGraph` directly for one or more ticker/date pairs
- lets you choose the LLM provider per batch run
- uses the active OpenCode defaults from `opencode.json` when provider is OpenCode
- lets you override separate quick/deep models for OpenCode and other providers
- browses saved markdown snapshots from `reports/<ticker>/SavedReports/<date>_<hash>/`
- falls back to legacy JSON logs from `reports/<ticker>/TradingAgentsStrategy_logs/` when no saved snapshot exists

If you want more or fewer concurrent runs, set:

```bash
export TRADINGAGENTS_WEB_MAX_WORKERS=4
```
