# TradingAgents WebUI

Run the app from the repo root:

```bash
uvicorn webui.app:app --reload
```

Docker Compose starts the WebUI on port `2026` and runs a companion updater
that checks `origin/main` every 15 minutes. When the local checkout is on
`main` and a newer commit is available, it runs a fast-forward-only pull and
restarts the WebUI container:

```bash
docker compose up -d webui webui-watchtower
```

The updater runs inside its own container, so host Git authorization is not
inherited automatically. The compose service mounts `/root/.ssh` into the
updater container; make sure the server's root user can run
`git fetch origin main` from `/root/TradingAgents`.

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
- Shows the current daily watchlist.
- Prepares a per-date manifest under `reports/daily_runs/`.
- Queues only incomplete tickers for the selected date.
- Supports retrying failed tickers.
- Uses the Seeking Alpha watchlist artifact as the daily ticker source.
- Can screen the Daily Coverage list through HalalScreener before queueing analysis.
- Includes a `Rescrape tickers` button to force-refresh the watchlist.

### Saved Reports
- Browses saved markdown snapshots from `reports/<ticker>/SavedReports/<date>_<hash>/`.
- Falls back to legacy JSON logs from `reports/<ticker>/TradingAgentsStrategy_logs/` when no saved snapshot exists.
- Lets you inspect the individual markdown documents inside a saved report bundle.

### Token Usage
- Aggregates OpenCode token telemetry across saved runs and in-memory jobs.
- Shows totals and time-series charts.

### Portfolio Automation
- Builds a daily rebalance plan from completed Daily Coverage ratings.
- Syncs the selected broker before generating live order intents.
- Supports `alpaca_paper` and `webull_paper` brokerage providers.
- Automatic Daily Coverage finalization uses the persisted Settings broker; default is `alpaca_paper`.

### Telegram Notifications and HTML Reports
- Generates a daily HTML report under `reports/daily_html/<trade-date>.html`.
- Serves share links through `GET /reports/share?path=reports/daily_html/<trade-date>.html`.
- Uses the report path in the URL query string, so no database table is required for sharing.
- Sends Telegram updates when automatic Daily Coverage is queued and again when final portfolio automation completes.
- Includes portfolio status, coverage status, proposed trades, trade reasoning, and a shareable HTML report link.

### Settings
- Toggle the halal checker. It defaults to enabled; when disabled, Shariah compliance is not checked or marked.
- Configure the automatic Daily Coverage run time. It defaults to `09:30` in `America/New_York`.

## Seeking Alpha Watchlist

The Daily Coverage watchlist is fetched from Seeking Alpha screen:

- `https://seekingalpha.com/screeners/95bd0cd23361-HC-top`

Current implementation:

- prefers direct API extraction from Seeking Alpha using a cookie secret file
- reuses the most recent cached watchlist if a refresh fails, and returns an empty watchlist with an error when no usable cache exists
- stores preserved watchlist/debug artifacts under `webui_artifacts/seeking_alpha_watchlist/`

## Halal Screening

Zoya does not provide a free API key for this workflow. Musaffa documents B2B access with a `secretKey` and `clientId`. This app uses HalalScreener because its developer docs expose bearer API key access.

If you want the Daily Coverage list to block non-halal names, configure HalalScreener screening:

```bash
export HALALSCREENER_API_KEY=your_halalscreener_api_key
```

Optional auth overrides:

```bash
export HALALSCREENER_API_URL_TEMPLATE='https://halalscreener.app/api/v1/screen?symbol={ticker}'
export HALALSCREENER_API_AUTH_HEADER=Authorization
export HALALSCREENER_API_AUTH_SCHEME=Bearer
export HALALSCREENER_API_TIMEOUT_SECONDS=10
```

Notes:

- screening is refreshed when a daily manifest is prepared or loaded
- `questionable`, `doubtful`, `not covered`, and explicitly non-compliant names are blocked
- blocked names stay visible and are marked red in the UI, but daily queueing skips them
- the Settings tab can disable halal screening completely
- if HalalScreener is not configured, the WebUI falls back to the unfiltered list

Set the cookie secret path before running WebUI:

```bash
export SEEKING_ALPHA_COOKIES_PATH=/absolute/path/to/seeking_alpha_cookies.json
```

Bootstrap that file once with:

```bash
python scripts/bootstrap_seeking_alpha_auth.py --output /absolute/path/to/seeking_alpha_cookies.json
```

That helper opens a real browser, lets you log in manually, and writes a reusable cookie secret file for server-side watchlist refreshes.

## Broker Configuration

Select the brokerage used by automatic daily execution in the Settings tab. The value is saved in `webui_artifacts/settings.json`.

The environment variable remains a fallback for first-run defaults and non-UI use:

```bash
export TRADINGAGENTS_BROKER_PROVIDER=webull_paper
```

Alpaca paper trading:

```bash
export APCA_API_KEY_ID=your_alpaca_key
export APCA_API_SECRET_KEY=your_alpaca_secret
```

Webull paper/test trading uses Webull OpenAPI signed HTTPS requests. By default it points at Webull's UAT host `us-openapi-alb.uat.webullbroker.com`; override it only if Webull gives you a different endpoint.

```bash
export WEBULL_APP_KEY=your_webull_app_key
export WEBULL_APP_SECRET=your_webull_app_secret
export WEBULL_ACCOUNT_ID=your_webull_account_id
export WEBULL_ACCESS_TOKEN=optional_2fa_token
export WEBULL_API_HOST=us-openapi-alb.uat.webullbroker.com
export WEBULL_ENV=paper
```

If `WEBULL_ACCOUNT_ID` is omitted, the integration calls `/openapi/account/list` and uses the first account returned. If your Webull app has 2FA enabled, set `WEBULL_ACCESS_TOKEN` to an active token.

## Telegram Configuration

Create a Telegram bot with BotFather, add it to the target chat, and configure:

```bash
export TELEGRAM_BOT_TOKEN=123456:your_bot_token
export TELEGRAM_CHAT_ID=your_chat_id
export TRADINGAGENTS_PUBLIC_BASE_URL=https://your-public-webui-host
```

Optional overrides:

```bash
export TELEGRAM_API_BASE_URL=https://api.telegram.org
export TELEGRAM_TIMEOUT_SECONDS=10
```

`TRADINGAGENTS_PUBLIC_BASE_URL` is used to build report links in Telegram. If it is omitted, links default to `http://localhost:2026`.

## Main API Endpoints

- `GET /api/jobs`
- `GET /api/jobs/{job_id}`
- `POST /api/jobs`
- `POST /api/on-demand/run`
- `GET /api/providers`
- `GET /api/brokers`
- `POST /api/portfolio/{broker_provider}/sync`
- `GET /api/daily-watchlist`
- `POST /api/daily-watchlist/refresh`
- `GET /api/daily-runs/{trade_date}`
- `POST /api/daily-runs/{trade_date}/prepare`
- `POST /api/daily-runs/{trade_date}/run-missing`
- `POST /api/daily-runs/{trade_date}/tickers/{ticker}/retry`
- `POST /api/daily-runs/{trade_date}/html-report`
- `POST /api/daily-runs/{trade_date}/notify`
- `GET /reports/share?path=reports/daily_html/{trade_date}.html`
- `GET /api/tickers`
- `GET /api/tickers/{ticker}/reports`
- `GET /api/tickers/{ticker}/reports/{report_id}`
- `GET /api/token-usage`

## Notes

- The WebUI writes TradingAgents outputs under `reports/`.
- Daily watchlist refresh artifacts are intentionally stored in a readable tracked directory, not a disposable hidden cache directory.
