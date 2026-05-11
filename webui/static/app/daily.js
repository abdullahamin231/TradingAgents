import {
  dailyDateInput,
  dailyMessage,
  dailyPolicy,
  dailyPrepareButton,
  dailyRunMissingButton,
  dailyStatusDate,
  dailyStatusTable,
  dailySummary,
  dailyWatchlist,
} from "./dom.js";
import { fetchJobs } from "./jobs.js";
import { providerPayload } from "./providers.js";
import { state } from "./state.js";
import { escapeHtml, isValidTradeDate, setMessage, statusClass } from "./utils.js";

export function renderDailyWatchlist(payload) {
  const tickers = payload.tickers || [];
  const policy = payload.policy || [];

  dailyWatchlist.className = tickers.length ? "ticker-list" : "ticker-list empty-state";
  dailyWatchlist.innerHTML = tickers.length
    ? tickers.map((ticker) => `<span class="ticker-chip">${escapeHtml(ticker)}</span>`).join("")
    : "No watchlist configured.";

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
}

export function renderDailySummary(summary = null) {
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
  renderDailySummary(payload.summary || null);

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
            (entry) => `
              <tr>
                <td><strong>${escapeHtml(entry.ticker)}</strong></td>
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
            `
          )
          .join("")}
      </tbody>
    </table>
  `;
}

export async function loadDailyWatchlist() {
  const response = await fetch("/api/daily-watchlist");
  const payload = await response.json();
  renderDailyWatchlist(payload);
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
