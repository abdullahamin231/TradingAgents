This directory stores WebUI artifacts that should remain in version control.

Current usage:
- `seeking_alpha_watchlist/seeking_alpha_top_tickers.json`: latest resolved watchlist payload
- `seeking_alpha_watchlist/debug_runs/<DD-Mon-YYYY-HH-MM-AM|PM>/`: preserved debug outputs for Seeking Alpha fetches

The readable timestamp format is intentional so runs are easy to inspect and less likely to be treated as disposable cache.
