import {
  dailyDateInput,
  dailyMessage,
  dailyPortfolioExecution,
  dailyPolicy,
  dailyPrepareButton,
  dailyRescrapeButton,
  dailyRunMissingButton,
  dailyStatusDate,
  dailyStatusTable,
  dailySummary,
  dailyWatchlist,
  dailyWatchlistDiff,
  dailyWatchlistHoldings,
  dailyWatchlistMeta,
} from "./dom.js?v=settings-tab-2";
import { fetchJobs } from "./jobs.js?v=settings-tab-2";
import { providerPayload } from "./providers.js?v=settings-tab-2";
import { state } from "./state.js?v=settings-tab-2";
import { escapeHtml, isValidTradeDate, setMessage, statusClass } from "./utils.js?v=settings-tab-2";

function uniqueTickers(tickers) {
  return [...new Set((tickers || []).filter((ticker) => typeof ticker === "string" && ticker))];
}

function diffTickers(previousTickers, nextTickers) {
  const previous = new Set(uniqueTickers(previousTickers));
  const next = new Set(uniqueTickers(nextTickers));
  return {
    added: [...next].filter((ticker) => !previous.has(ticker)),
    removed: [...previous].filter((ticker) => !next.has(ticker)),
  };
}

function screeningByTicker(screening = {}) {
  return Object.fromEntries((screening.results || []).map((item) => [item.ticker, item]));
}

function shouldShowCompliance(screening = null) {
  if (state.settings?.halal_checker_enabled === false) {
    return false;
  }
  return Boolean(screening?.enabled);
}

function complianceClass(compliance = null) {
  if (!compliance) {
    return "";
  }
  if (["screening_error", "unknown"].includes(compliance.status)) {
    return " shariah-warning";
  }
  return compliance.allowed === false ? " shariah-blocked" : " shariah-compliant";
}

function isBlockingCompliance(compliance = null) {
  return compliance?.allowed === false && !["screening_error", "unknown"].includes(compliance.status);
}

function complianceTitle(compliance = null) {
  if (!compliance) {
    return "";
  }
  const provider = compliance.provider || "halal screener";
  const status = compliance.status || "unknown";
  const error = compliance.error ? `. ${compliance.error}` : "";
  return ` title="${escapeHtml(`${provider}: ${status}${error}`)}"`;
}

function renderTickerChips(tickers, className = "ticker-chip", screening = {}) {
  const results = shouldShowCompliance(screening) ? screeningByTicker(screening) : {};
  return tickers
    .map((ticker) => {
      const compliance = results[ticker] || null;
      return `<span class="${className}${complianceClass(compliance)}"${complianceTitle(compliance)}>${escapeHtml(ticker)}</span>`;
    })
    .join("");
}

function renderWatchlistHoldings(metadata = {}, tickers = []) {
  const existingHoldings = uniqueTickers(metadata.existing_holdings || []);
  const holdingsOutsideWatchlist = existingHoldings.filter((ticker) => !tickers.includes(ticker));
  const screening = metadata.screening || {};
  if (!holdingsOutsideWatchlist.length) {
    dailyWatchlistHoldings.className = "watchlist-note empty-state";
    dailyWatchlistHoldings.textContent = "All current holdings are already present in the live watchlist.";
    return;
  }

  dailyWatchlistHoldings.className = "watchlist-note";
  dailyWatchlistHoldings.innerHTML = `
    <strong>Held outside live watchlist</strong>
    <p>These are not in the latest rescrape, but they still get added to the daily coverage manifest because they are current holdings.</p>
    <div class="ticker-list ticker-list-inline">
      ${renderTickerChips(holdingsOutsideWatchlist, "ticker-chip ticker-chip-held", screening)}
    </div>
  `;
}

function renderWatchlistDiff(diff = null) {
  if (!diff || (!diff.added.length && !diff.removed.length)) {
    dailyWatchlistDiff.className = "watchlist-diff empty-state";
    dailyWatchlistDiff.textContent = diff ? "Last rescrape did not change the ticker list." : "Rescrape tickers to see additions and removals.";
    return;
  }

  dailyWatchlistDiff.className = "watchlist-diff";
  dailyWatchlistDiff.innerHTML = `
    <strong>Last rescrape changes</strong>
    <div class="watchlist-diff-grid">
      <div class="watchlist-diff-group">
        <span class="watchlist-diff-label watchlist-diff-label-added">Added</span>
        <div class="ticker-list ticker-list-inline">
          ${diff.added.length ? renderTickerChips(diff.added, "ticker-chip ticker-chip-added") : '<span class="empty-state">None</span>'}
        </div>
      </div>
      <div class="watchlist-diff-group">
        <span class="watchlist-diff-label watchlist-diff-label-removed">Removed</span>
        <div class="ticker-list ticker-list-inline">
          ${diff.removed.length ? renderTickerChips(diff.removed, "ticker-chip ticker-chip-removed") : '<span class="empty-state">None</span>'}
        </div>
      </div>
    </div>
  `;
}

export function renderDailyWatchlist(payload) {
  const tickers = uniqueTickers(payload.tickers || []);
  const policy = payload.policy || [];
  const metadata = payload.metadata || {};
  const screening = metadata.screening || {};
  const displayScreening = shouldShowCompliance(screening) ? screening : {};
  const sourceLabel = (payload.source || "unknown").replaceAll("_", " ");
  const fetchedAt = metadata.fetched_at ? new Date(metadata.fetched_at).toLocaleString() : "n/a";
  const freshnessLabel = metadata.stale ? "Last successful refresh" : "Last refresh";
  dailyWatchlistMeta.textContent = metadata.error
    ? `Source: ${sourceLabel}. ${freshnessLabel}: ${fetchedAt}. Last error: ${metadata.error}`
    : `Source: ${sourceLabel}. ${freshnessLabel}: ${fetchedAt}.`;

  dailyWatchlist.className = tickers.length ? "ticker-list" : "ticker-list empty-state";
  dailyWatchlist.innerHTML = tickers.length
    ? renderTickerChips(tickers, "ticker-chip", displayScreening)
    : "No watchlist configured.";
  renderWatchlistHoldings({ ...metadata, screening: displayScreening }, tickers);
  renderWatchlistDiff(state.dailyWatchlistDiff);

  dailyPolicy.className = policy.length ? "policy-list" : "policy-list empty-state";
  dailyPolicy.innerHTML = policy.length
    ? policy
        .map(
          (item) => `
            <article class="policy-item">
              <strong>${escapeHtml(item.rating)}</strong>
              <p>${escapeHtml(item.action)}</p>
            </article>
          `
        )
        .join("")
    : "No policy configured.";
  state.dailyWatchlistPayload = payload;
}

export function renderDailySummary(summary = null, { screeningEnabled = true } = {}) {
  if (!summary) {
    dailySummary.className = "summary-strip empty-state";
    dailySummary.textContent = "Prepare a daily run to create the manifest.";
    return;
  }

  const items = [
    ["Total", summary.total],
    ["Pending", summary.pending],
    ["Queued", summary.queued],
    ["Running", summary.running],
    ["Completed", summary.completed],
    ["Failed", summary.failed],
  ];
  if (screeningEnabled) {
    items.push(["Blocked", summary.blocked || 0], ["Check errors", summary.screening_errors || 0]);
  }

  dailySummary.className = "summary-strip";
  dailySummary.innerHTML = items
    .map(
      ([label, value]) => `
        <div class="summary-item">
          <span class="table-label">${escapeHtml(label)}</span>
          <strong>${escapeHtml(value)}</strong>
        </div>
      `
    )
    .join("");
}

export function renderDailyManifest(payload) {
  state.activeDailyTradeDate = payload.trade_date || dailyDateInput.value.trim();
  dailyStatusDate.textContent = state.activeDailyTradeDate;
  const watchlistScreening = state.dailyWatchlistPayload?.metadata?.screening || {};
  const screeningEnabled = shouldShowCompliance(payload.screening) || shouldShowCompliance(watchlistScreening);
  const watchlistCompliance = screeningByTicker(watchlistScreening);
  renderDailySummary(payload.summary || null, { screeningEnabled });
  renderPortfolioExecution(payload.portfolio_execution || null);

  const tickers = payload.tickers || [];
  if (!tickers.length) {
    dailyStatusTable.className = "daily-table-shell empty-state";
    dailyStatusTable.textContent = "No manifest prepared yet.";
    return;
  }

  dailyStatusTable.className = "daily-table-shell";
  dailyStatusTable.innerHTML = `
    <table class="daily-table">
      <thead>
        <tr>
          <th>Ticker</th>
          ${screeningEnabled ? "<th>Shariah</th>" : ""}
          <th>Status</th>
          <th>Rating</th>
          <th>Report</th>
          <th>Error</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody>
        ${tickers
          .map(
            (entry) => {
              const compliance = entry.shariah_compliance || watchlistCompliance[entry.ticker] || null;
              return `
              <tr class="${screeningEnabled && isBlockingCompliance(compliance) ? "daily-row-blocked" : ""}">
                <td><strong>${escapeHtml(entry.ticker)}</strong></td>
                ${screeningEnabled ? `<td>${renderComplianceBadge(compliance)}</td>` : ""}
                <td><span class="${statusClass(entry.status)}">${escapeHtml(entry.status)}</span></td>
                <td>${escapeHtml(entry.rating || "n/a")}</td>
                <td>${entry.report_path ? `<code>${escapeHtml(entry.report_path)}</code>` : "n/a"}</td>
                <td class="error-cell">${escapeHtml(entry.error || "")}</td>
                <td>
                  ${
                    entry.status === "failed"
                      ? `<button type="button" data-retry-ticker="${escapeHtml(entry.ticker)}">Retry</button>`
                      : entry.status === "completed"
                        ? "Complete"
                        : "Waiting"
                  }
                </td>
              </tr>
            `;
            }
          )
          .join("")}
      </tbody>
    </table>
  `;
}

function renderPortfolioExecution(execution = null) {
  if (!dailyPortfolioExecution) {
    return;
  }
  if (!execution) {
    dailyPortfolioExecution.className = "portfolio-banner empty-state";
    dailyPortfolioExecution.textContent = "Portfolio execution will appear after daily coverage completes.";
    return;
  }
  const status = execution.status || "unknown";
  dailyPortfolioExecution.className = `portfolio-banner ${status === "failed" ? "portfolio-banner-pending" : "portfolio-banner-ready"}`;
  const detail = status === "submitted"
    ? `Submitted ${execution.submitted_order_count || 0} broker paper order${execution.submitted_order_count === 1 ? "" : "s"}.`
    : status === "no_orders"
      ? "No broker paper orders were required."
      : status === "running"
        ? "Syncing broker and finalizing portfolio orders."
        : execution.error || execution.detail || "Waiting for daily coverage to finish.";
  dailyPortfolioExecution.innerHTML = `
    <strong>Portfolio: ${escapeHtml(status)}</strong>
    <span>${escapeHtml(detail)}</span>
  `;
}

function renderComplianceBadge(compliance = null) {
  if (!compliance) {
    return '<span class="compliance-badge compliance-unknown">not checked</span>';
  }
  const status = compliance.status || "unknown";
  const label = status === "screening_error" ? "check failed" : isBlockingCompliance(compliance) ? `blocked · ${status}` : status;
  return `<span class="compliance-badge${complianceClass(compliance)}"${complianceTitle(compliance)}>${escapeHtml(label)}</span>`;
}

export async function loadDailyWatchlist({ forceRefresh = false } = {}) {
  const previousPayload = state.dailyWatchlistPayload;
  const response = await fetch(forceRefresh ? "/api/daily-watchlist/refresh" : "/api/daily-watchlist", {
    method: forceRefresh ? "POST" : "GET",
  });
  const payload = await response.json();
  if (!response.ok) {
    setMessage(dailyMessage, payload.detail || "Failed to load daily watchlist.", true);
    return;
  }
  state.dailyWatchlistDiff = forceRefresh && previousPayload
    ? diffTickers(previousPayload.tickers || [], payload.tickers || [])
    : null;
  renderDailyWatchlist(payload);
}

export async function rescrapeDailyWatchlist() {
  dailyRescrapeButton.disabled = true;
  setMessage(dailyMessage, "");
  try {
    await loadDailyWatchlist({ forceRefresh: true });
    const diff = state.dailyWatchlistDiff;
    const addedCount = diff?.added.length || 0;
    const removedCount = diff?.removed.length || 0;
    setMessage(
      dailyMessage,
      addedCount || removedCount
        ? `Rescraped daily tickers from Seeking Alpha. Added ${addedCount}, removed ${removedCount}.`
        : "Rescraped daily tickers from Seeking Alpha. No ticker changes."
    );
  } finally {
    dailyRescrapeButton.disabled = false;
  }
}

export async function loadDailyManifest(tradeDate, { quiet = false } = {}) {
  if (!isValidTradeDate(tradeDate)) {
    if (!quiet) {
      setMessage(dailyMessage, "Date must use YYYY-MM-DD.", true);
    }
    return;
  }

  const response = await fetch(`/api/daily-runs/${encodeURIComponent(tradeDate)}`);
  const payload = await response.json();
  renderDailyManifest(payload);
}

export async function prepareDailyRun() {
  const tradeDate = dailyDateInput.value.trim();
  if (!isValidTradeDate(tradeDate)) {
    setMessage(dailyMessage, "Date must use YYYY-MM-DD.", true);
    return;
  }

  dailyPrepareButton.disabled = true;
  setMessage(dailyMessage, "");
  try {
    const response = await fetch(`/api/daily-runs/${encodeURIComponent(tradeDate)}/prepare`, { method: "POST" });
    const payload = await response.json();
    if (!response.ok) {
      setMessage(dailyMessage, payload.detail || "Failed to prepare daily run.", true);
      return;
    }
    renderDailyManifest(payload);
    setMessage(dailyMessage, `Prepared daily manifest for ${tradeDate}.`);
  } finally {
    dailyPrepareButton.disabled = false;
  }
}

export async function runMissingDaily() {
  const tradeDate = dailyDateInput.value.trim();
  if (!isValidTradeDate(tradeDate)) {
    setMessage(dailyMessage, "Date must use YYYY-MM-DD.", true);
    return;
  }

  dailyRunMissingButton.disabled = true;
  setMessage(dailyMessage, "");
  try {
    const response = await fetch(`/api/daily-runs/${encodeURIComponent(tradeDate)}/run-missing`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(providerPayload("daily")),
    });
    const payload = await response.json();
    if (!response.ok) {
      setMessage(dailyMessage, payload.detail || "Failed to queue daily run.", true);
      return;
    }
    renderDailyManifest(payload);
    const queuedCount = (payload.queued_jobs || []).length;
    setMessage(
      dailyMessage,
      queuedCount ? `Queued ${queuedCount} ticker${queuedCount === 1 ? "" : "s"} for ${tradeDate}.` : `No missing tickers to queue for ${tradeDate}.`
    );
    await fetchJobs();
  } finally {
    dailyRunMissingButton.disabled = false;
  }
}

export async function retryDailyTicker(ticker) {
  const tradeDate = dailyDateInput.value.trim();
  const response = await fetch(`/api/daily-runs/${encodeURIComponent(tradeDate)}/tickers/${encodeURIComponent(ticker)}/retry`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(providerPayload("daily")),
  });
  const payload = await response.json();
  if (!response.ok) {
    setMessage(dailyMessage, payload.detail || `Failed to retry ${ticker}.`, true);
    return;
  }
  renderDailyManifest(payload);
  setMessage(dailyMessage, `Queued retry for ${ticker} on ${tradeDate}.`);
  await fetchJobs();
}
