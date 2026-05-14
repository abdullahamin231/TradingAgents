# TradingAgents WebUI

Run the app from the repo root:

```bash
uvicorn webui.app:app --reload
```

Optional worker count:

```bash
export TRADINGAGENTS_WEB_MAX_WORKERS=4
```

## Tabs

### On-Demand
- Queue a single ticker analysis for a selected trade date.
- Choose the LLM provider per run.
- Override separate quick/deep model names.
- Uses `opencode.json` defaults when provider is `opencode`.

### Daily Coverage
- Shows the current daily watchlist and policy mapping.
- Prepares a per-date manifest under `reports/daily_runs/`.
- Queues only incomplete tickers for the selected date.
- Supports retrying failed tickers.
- Uses a Seeking Alpha-backed watchlist instead of the hardcoded default when the fetch succeeds.
- Includes a `Rescrape tickers` button to force-refresh the watchlist.

### Saved Reports
- Browses saved markdown snapshots from `reports/<ticker>/SavedReports/<date>_<hash>/`.
- Falls back to legacy JSON logs from `reports/<ticker>/TradingAgentsStrategy_logs/` when no saved snapshot exists.
- Lets you inspect the individual markdown documents inside a saved report bundle.

### Token Usage
- Aggregates OpenCode token telemetry across saved runs and in-memory jobs.
- Shows totals and time-series charts.

## Seeking Alpha Watchlist

The Daily Coverage watchlist is fetched from Seeking Alpha screen:

- `https://seekingalpha.com/screeners/95bd0cd23361-HC-top`

Current implementation:

- prefers direct API extraction from Seeking Alpha using cookies from a Playwright `storageState` file
- reuses the most recent cached watchlist if a refresh fails, and falls back to the static `DEFAULT_DAILY_TICKERS` list only when no usable cache exists
- stores preserved watchlist/debug artifacts under `webui_artifacts/seeking_alpha_watchlist/`

Set the auth state path before running WebUI:

```bash
export SEEKING_ALPHA_STORAGE_STATE_PATH=/absolute/path/to/seeking_alpha_state.json
```

Bootstrap that file once with:

```bash
python scripts/bootstrap_seeking_alpha_auth.py --output /absolute/path/to/seeking_alpha_state.json
```

That helper opens a real browser, lets you log in manually, and writes a reusable Playwright `storageState` file for server-side watchlist refreshes.

## Main API Endpoints

- `GET /api/jobs`
- `GET /api/jobs/{job_id}`
- `POST /api/jobs`
- `POST /api/on-demand/run`
- `GET /api/providers`
- `GET /api/daily-watchlist`
- `POST /api/daily-watchlist/refresh`
- `GET /api/daily-runs/{trade_date}`
- `POST /api/daily-runs/{trade_date}/prepare`
- `POST /api/daily-runs/{trade_date}/run-missing`
- `POST /api/daily-runs/{trade_date}/tickers/{ticker}/retry`
- `GET /api/tickers`
- `GET /api/tickers/{ticker}/reports`
- `GET /api/tickers/{ticker}/reports/{report_id}`
- `GET /api/token-usage`

## Notes

- The WebUI writes TradingAgents outputs under `reports/`.
- Daily watchlist refresh artifacts are intentionally stored in a readable tracked directory, not a disposable hidden cache directory.
