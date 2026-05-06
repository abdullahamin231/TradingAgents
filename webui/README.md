# TradingAgents Web Interface

Run the web app from the repo root:

```bash
uvicorn webui.app:app --reload
```

The interface:

- runs `TradingAgentsGraph` directly for one or more ticker/date pairs
- lets you choose the LLM provider per batch run
- uses the active OpenCode model from `opencode.json` when provider is OpenCode
- lets you override the model/deployment name for OpenCode, or separate quick/deep models for other providers
- lists and renders saved JSON logs from `reports/<ticker>/TradingAgentsStrategy_logs/`

If you want more or fewer concurrent runs, set:

```bash
export TRADINGAGENTS_WEB_MAX_WORKERS=4
```
