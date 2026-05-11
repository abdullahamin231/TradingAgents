const tabButtons = [...document.querySelectorAll(".tab-button")];
const tabPanels = [...document.querySelectorAll(".tab-panel")];
const jobsList = document.querySelector("#jobs-list");
const tickerSelect = document.querySelector("#ticker-select");
const reportSelect = document.querySelector("#report-select");
const tickerSummary = document.querySelector("#ticker-summary");
const reportTitle = document.querySelector("#report-title");
const reportMeta = document.querySelector("#report-meta");
const reportFileList = document.querySelector("#report-file-list");
const reportView = document.querySelector("#report-view");
const dailyWatchlist = document.querySelector("#daily-watchlist");
const dailyPolicy = document.querySelector("#daily-policy");
const dailySummary = document.querySelector("#daily-summary");
const dailyStatusTable = document.querySelector("#daily-status-table");
const dailyStatusDate = document.querySelector("#daily-status-date");
const tokenUsageSummary = document.querySelector("#token-usage-summary");
const tokenUsageCharts = document.querySelector("#token-usage-charts");
const tokenUsageRuns = document.querySelector("#token-usage-runs");

const onDemandSubmitButton = document.querySelector("#on-demand-submit");
const onDemandTickerInput = document.querySelector("#on-demand-ticker");
const onDemandDateInput = document.querySelector("#on-demand-date");
const onDemandMessage = document.querySelector("#on-demand-message");

const dailyPrepareButton = document.querySelector("#prepare-daily-run");
const dailyRunMissingButton = document.querySelector("#run-missing-daily");
const dailyDateInput = document.querySelector("#daily-date");
const dailyMessage = document.querySelector("#daily-message");

const providerGroups = {
  "on-demand": {
    select: document.querySelector("#on-demand-provider-select"),
    providerFields: document.querySelector("#on-demand-provider-model-fields"),
    quickInput: document.querySelector("#on-demand-quick-model-input"),
    deepInput: document.querySelector("#on-demand-deep-model-input"),
  },
  daily: {
    select: document.querySelector("#daily-provider-select"),
    providerFields: document.querySelector("#daily-provider-model-fields"),
    quickInput: document.querySelector("#daily-quick-model-input"),
    deepInput: document.querySelector("#daily-deep-model-input"),
  },
};

let providerOptions = [];
let activeDailyTradeDate = window.TRADINGAGENTS_DEFAULT_DATE;
let activeReportPayload = null;

const usageMetrics = [
  ["tokens_total", "Total Tokens"],
  ["tokens_input", "Input"],
  ["tokens_output", "Output"],
  ["tokens_reasoning", "Reasoning"],
  ["tokens_cache_read", "Cache Read"],
  ["tokens_cache_write", "Cache Write"],
];

function setTab(target) {
  tabButtons.forEach((button) => button.classList.toggle("active", button.dataset.tabTarget === target));
  tabPanels.forEach((panel) => panel.classList.toggle("active", panel.id === target));
}

function setMessage(node, message = "", isError = false) {
  node.textContent = message;
  node.style.color = isError ? "var(--text)" : "var(--muted)";
}

function isValidTradeDate(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value);
}

function statusClass(status) {
  return `status-pill status-${status || "queued"}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatNumber(value) {
  return new Intl.NumberFormat("en-US").format(Number(value || 0));
}

function formatDecimal(value) {
  const numeric = Number(value || 0);
  return numeric ? numeric.toFixed(6).replace(/0+$/, "").replace(/\.$/, "") : "0";
}

function formatDateTime(value) {
  if (!value) {
    return "n/a";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleString();
}

function formatDuration(durationMs) {
  const totalSeconds = Math.max(0, Math.round(Number(durationMs || 0) / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes ? `${minutes}m ${seconds}s` : `${seconds}s`;
}

function resetReportViewer() {
  activeReportPayload = null;
  reportTitle.textContent = "No report selected";
  reportMeta.className = "report-browser-meta empty-state";
  reportMeta.textContent = "Select a ticker and snapshot to inspect the markdown files inside that saved report.";
  reportFileList.className = "report-file-list hidden";
  reportFileList.innerHTML = "";
  reportView.className = "report-view empty-state";
  reportView.textContent = "Select a ticker and saved snapshot to render the report.";
}

function buildUsageSeries(events, metricKey) {
  let runningTotal = 0;
  return events
    .slice()
    .sort((left, right) => (left.completed_at_ms || 0) - (right.completed_at_ms || 0))
    .map((event, index) => {
      runningTotal += Number(event[metricKey] || 0);
      return { x: index, y: runningTotal, label: event.completed_at || event.started_at || "" };
    });
}

function renderUsageChart(metricKey, label, events) {
  const series = buildUsageSeries(events, metricKey);
  if (!series.length) {
    return `
      <article class="usage-chart-card">
        <div class="section-head">
          <h2>${escapeHtml(label)}</h2>
          <p>No samples yet.</p>
        </div>
      </article>
    `;
  }

  const width = 320;
  const height = 112;
  const maxValue = Math.max(...series.map((point) => point.y), 1);
  const points = series
    .map((point, index) => {
      const x = series.length === 1 ? width / 2 : (index / (series.length - 1)) * (width - 16) + 8;
      const y = height - ((point.y / maxValue) * (height - 24) + 12);
      return `${x},${y}`;
    })
    .join(" ");
  const latest = series.at(-1)?.y || 0;

  return `
    <article class="usage-chart-card">
      <div class="usage-chart-head">
        <div>
          <h2>${escapeHtml(label)}</h2>
          <p>Cumulative</p>
        </div>
        <strong>${formatNumber(latest)}</strong>
      </div>
      <svg viewBox="0 0 ${width} ${height}" class="usage-chart" role="img" aria-label="${escapeHtml(label)} chart">
        <polyline points="${points}" />
      </svg>
    </article>
  `;
}

function renderTokenUsage(payload) {
  const summary = payload.summary || {};
  const events = payload.events || [];
  const records = payload.records || [];
  const summaryItems = [
    ["Total Tokens", formatNumber(summary.tokens_total)],
    ["Input", formatNumber(summary.tokens_input)],
    ["Output", formatNumber(summary.tokens_output)],
    ["Reasoning", formatNumber(summary.tokens_reasoning)],
    ["Cache Read", formatNumber(summary.tokens_cache_read)],
    ["Cache Write", formatNumber(summary.tokens_cache_write)],
    ["Calls", formatNumber(summary.call_count)],
    ["Cost", formatDecimal(summary.cost)],
    ["Window", summary.started_at && summary.completed_at ? `${formatDateTime(summary.started_at)} -> ${formatDateTime(summary.completed_at)}` : "n/a"],
  ];

  tokenUsageSummary.className = "usage-grid";
  tokenUsageSummary.innerHTML = summaryItems
    .map(
      ([label, value]) => `
        <article class="usage-card">
          <span class="table-label">${escapeHtml(label)}</span>
          <strong>${escapeHtml(value)}</strong>
        </article>
      `
    )
    .join("");

  if (!events.length) {
    tokenUsageCharts.className = "usage-chart-grid empty-state";
    tokenUsageCharts.textContent = "No token usage recorded yet.";
  } else {
    tokenUsageCharts.className = "usage-chart-grid";
    tokenUsageCharts.innerHTML = usageMetrics.map(([key, label]) => renderUsageChart(key, label, events)).join("");
  }

  if (!records.length) {
    tokenUsageRuns.className = "daily-table-shell empty-state";
    tokenUsageRuns.textContent = "No token usage recorded yet.";
    return;
  }

  tokenUsageRuns.className = "daily-table-shell";
  tokenUsageRuns.innerHTML = `
    <table class="daily-table usage-table">
      <thead>
        <tr>
          <th>Run</th>
          <th>Status</th>
          <th>Calls</th>
          <th>Total</th>
          <th>Input</th>
          <th>Output</th>
          <th>Reasoning</th>
          <th>Cache</th>
          <th>Duration</th>
          <th>Models</th>
        </tr>
      </thead>
      <tbody>
        ${records
          .map((record) => {
            const runSummary = record.summary || {};
            return `
              <tr>
                <td>
                  <strong>${escapeHtml(record.ticker || "n/a")} / ${escapeHtml(record.trade_date || "n/a")}</strong>
                  <div class="job-line">${escapeHtml(record.workflow || "analysis_on_demand")} · ${escapeHtml(record.source)}</div>
                  <div class="job-line">${escapeHtml(record.report_path || record.job_id || "n/a")}</div>
                </td>
                <td><span class="${statusClass(record.status || "completed")}">${escapeHtml(record.status || "completed")}</span></td>
                <td>${formatNumber(runSummary.call_count)}</td>
                <td>${formatNumber(runSummary.tokens_total)}</td>
                <td>${formatNumber(runSummary.tokens_input)}</td>
                <td>${formatNumber(runSummary.tokens_output)}</td>
                <td>${formatNumber(runSummary.tokens_reasoning)}</td>
                <td>${formatNumber(runSummary.tokens_cache_read)} / ${formatNumber(runSummary.tokens_cache_write)}</td>
                <td>${escapeHtml(formatDuration(runSummary.duration_ms))}</td>
                <td>
                  <div class="job-line">Quick: ${escapeHtml(record.quick_model || "n/a")}</div>
                  <div class="job-line">Deep: ${escapeHtml(record.deep_model || "n/a")}</div>
                </td>
              </tr>
            `;
          })
          .join("")}
      </tbody>
    </table>
  `;
}

function updateModelDefault(groupName, providerValue) {
  const group = providerGroups[groupName];
  const provider = providerOptions.find((item) => item.value === providerValue);
  if (!group || !provider) {
    return;
  }

  group.providerFields.classList.remove("hidden");
  group.quickInput.value = provider.default_quick_model || "";
  group.deepInput.value = provider.default_deep_model || "";
  group.quickInput.placeholder = provider.note || "Quick think model";
  group.deepInput.placeholder = provider.note || "Deep think model";
}

function renderProviders() {
  Object.entries(providerGroups).forEach(([groupName, group]) => {
    group.select.innerHTML = providerOptions
      .map((provider) => `<option value="${provider.value}">${provider.label}</option>`)
      .join("");
    group.select.value = providerOptions[0]?.value || "opencode";
    updateModelDefault(groupName, group.select.value);
  });
}

function providerPayload(groupName) {
  const group = providerGroups[groupName];
  return {
    provider: group.select.value,
    quick_model: group.quickInput.value.trim(),
    deep_model: group.deepInput.value.trim(),
  };
}

function renderJobs(jobs) {
  if (!jobs.length) {
    jobsList.className = "jobs-list empty-state";
    jobsList.textContent = "No jobs yet.";
    return;
  }

  jobsList.className = "jobs-list";
  jobsList.innerHTML = jobs
    .map(
      (job) => `
        <article class="job-entry">
          <div class="job-head">
            <strong>${escapeHtml(job.ticker)} / ${escapeHtml(job.trade_date)}</strong>
            <span class="${statusClass(job.status)}">${escapeHtml(job.status)}</span>
          </div>
          <div class="job-line">Workflow: ${escapeHtml(job.workflow || "analysis_on_demand")} · Job ${escapeHtml(job.job_id.slice(0, 8))}</div>
          <div class="job-line">Provider: ${escapeHtml(job.provider || "opencode")}</div>
          <div class="job-line">Quick: ${escapeHtml(job.quick_model || "default")} · Deep: ${escapeHtml(job.deep_model || "default")}</div>
          ${job.report_path ? `<div class="job-line">Report: <code>${escapeHtml(job.report_path)}</code></div>` : ""}
          <div>${escapeHtml(job.decision || job.error || "Waiting for completion...")}</div>
        </article>
      `
    )
    .join("");
}

async function loadProviders() {
  try {
    const response = await fetch("/api/providers");
    const payload = await response.json();
    providerOptions = payload.providers || [];
  } catch (error) {
    providerOptions = [{ label: "OpenCode", value: "opencode", default_deep_model: "", default_quick_model: "" }];
  }
  renderProviders();
}

async function fetchJobs() {
  const response = await fetch("/api/jobs");
  const payload = await response.json();
  renderJobs(payload.jobs || []);
}

async function loadTokenUsage() {
  try {
    const response = await fetch("/api/token-usage");
    const payload = await response.json();
    renderTokenUsage(payload);
  } catch (error) {
    tokenUsageSummary.className = "usage-grid empty-state";
    tokenUsageSummary.textContent = "Token usage is unavailable.";
    tokenUsageCharts.className = "usage-chart-grid empty-state";
    tokenUsageCharts.textContent = "Token usage is unavailable.";
    tokenUsageRuns.className = "daily-table-shell empty-state";
    tokenUsageRuns.textContent = "Token usage is unavailable.";
  }
}

async function submitOnDemandRun() {
  const tradeDate = onDemandDateInput.value.trim();
  const ticker = onDemandTickerInput.value.trim();
  if (!isValidTradeDate(tradeDate)) {
    setMessage(onDemandMessage, "Date must use YYYY-MM-DD.", true);
    return;
  }
  if (!ticker) {
    setMessage(onDemandMessage, "Enter one ticker.", true);
    return;
  }

  onDemandSubmitButton.disabled = true;
  setMessage(onDemandMessage, "");
  try {
    const response = await fetch("/api/on-demand/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ticker,
        trade_date: tradeDate,
        ...providerPayload("on-demand"),
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      setMessage(onDemandMessage, payload.detail || "Run submission failed.", true);
      return;
    }
    setMessage(onDemandMessage, `Queued ${ticker.toUpperCase()} for ${tradeDate}.`);
    await fetchJobs();
    await loadTickers();
  } finally {
    onDemandSubmitButton.disabled = false;
  }
}

function renderDailyWatchlist(payload) {
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

function renderDailySummary(summary = null) {
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

function renderDailyManifest(payload) {
  activeDailyTradeDate = payload.trade_date || dailyDateInput.value.trim();
  dailyStatusDate.textContent = activeDailyTradeDate;
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

async function loadDailyWatchlist() {
  const response = await fetch("/api/daily-watchlist");
  const payload = await response.json();
  renderDailyWatchlist(payload);
}

async function loadDailyManifest(tradeDate, { quiet = false } = {}) {
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

async function prepareDailyRun() {
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

async function runMissingDaily() {
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

async function retryDailyTicker(ticker) {
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

async function loadTickers() {
  const previousTicker = tickerSelect.value;
  const response = await fetch("/api/tickers");
  const payload = await response.json();
  const tickers = payload.tickers || [];

  tickerSelect.innerHTML = `<option value="">Ticker</option>`;
  tickers.forEach((ticker) => {
    const option = document.createElement("option");
    option.value = ticker.ticker;
    option.textContent = `${ticker.ticker} (${ticker.report_count})`;
    tickerSelect.appendChild(option);
  });

  if (!tickers.length) {
    tickerSummary.className = "ticker-summary empty-state";
    tickerSummary.textContent = "No saved reports found in reports/.";
    resetReportViewer();
    return;
  }

  tickerSummary.className = "ticker-summary";
  tickerSummary.innerHTML = `
    <div class="ticker-list">
      ${tickers
        .map(
          (ticker) =>
            `<span class="ticker-chip">${escapeHtml(ticker.ticker)} · ${escapeHtml(ticker.report_count)} snapshots · latest ${escapeHtml(
              ticker.latest_trade_date || "n/a"
            )}</span>`
        )
        .join("")}
    </div>
  `;

  if (tickers.some((ticker) => ticker.ticker === previousTicker)) {
    tickerSelect.value = previousTicker;
  }
}

async function loadReportsForTicker(ticker) {
  const previousReportId = reportSelect.value;
  reportSelect.innerHTML = `<option value="">Saved snapshot</option>`;
  resetReportViewer();

  if (!ticker) {
    return;
  }

  const response = await fetch(`/api/tickers/${encodeURIComponent(ticker)}/reports`);
  const payload = await response.json();
  const reports = payload.reports || [];

  reports.forEach((report) => {
    const option = document.createElement("option");
    option.value = report.report_id;
    option.textContent =
      report.source === "saved_report"
        ? `${report.trade_date} · ${report.report_hash || report.report_id}`
        : `${report.trade_date} · legacy log`;
    reportSelect.appendChild(option);
  });

  if (reports.some((report) => report.report_id === previousReportId)) {
    reportSelect.value = previousReportId;
  }
}

function renderReportDocument(documentPath) {
  if (!activeReportPayload) {
    resetReportViewer();
    return;
  }

  const documents = activeReportPayload.documents || [];
  const selectedDocument =
    documents.find((document) => document.path === documentPath) ||
    documents.find((document) => document.path === activeReportPayload.default_document) ||
    documents[0];

  if (!selectedDocument) {
    reportView.className = "report-view empty-state";
    reportView.textContent = "No markdown files were found in this report snapshot.";
    return;
  }

  reportFileList
    .querySelectorAll("[data-document-path]")
    .forEach((button) => button.classList.toggle("active", button.dataset.documentPath === selectedDocument.path));

  reportView.className = "report-view";
  reportView.innerHTML = `
    <article class="markdown-document">
      <p class="message">Viewing <code>${escapeHtml(selectedDocument.path)}</code></p>
      <h1>${escapeHtml(selectedDocument.title)}</h1>
      <div class="html">${selectedDocument.html}</div>
    </article>
  `;
}

async function loadReport(ticker, reportId) {
  if (!ticker || !reportId) {
    resetReportViewer();
    return;
  }

  const response = await fetch(`/api/tickers/${encodeURIComponent(ticker)}/reports/${encodeURIComponent(reportId)}`);
  const payload = await response.json();
  if (!response.ok) {
    resetReportViewer();
    reportView.className = "report-view empty-state";
    reportView.textContent = payload.detail || "Failed to load report.";
    return;
  }

  activeReportPayload = payload;
  reportTitle.textContent = `${payload.ticker} · ${payload.report_id || payload.trade_date}`;
  reportMeta.className = "report-browser-meta";
  reportMeta.innerHTML = `
    <div class="report-meta-grid">
      <div class="report-meta-item">
        <span class="report-meta-label">Ticker</span>
        <strong>${escapeHtml(payload.ticker)}</strong>
      </div>
      <div class="report-meta-item">
        <span class="report-meta-label">Trade Date</span>
        <strong>${escapeHtml(payload.trade_date)}</strong>
      </div>
      <div class="report-meta-item">
        <span class="report-meta-label">Source</span>
        <strong>${escapeHtml(payload.source === "saved_report" ? "SavedReports" : "Legacy Log")}</strong>
      </div>
      <div class="report-meta-item">
        <span class="report-meta-label">Path</span>
        <strong class="report-path-value">${escapeHtml(payload.relative_path || payload.report_path || "n/a")}</strong>
      </div>
    </div>
  `;

  const documents = payload.documents || [];
  if (!documents.length) {
    reportFileList.className = "report-file-list hidden";
    reportView.className = "report-view empty-state";
    reportView.textContent = "No markdown files were found in this report snapshot.";
    return;
  }

  reportFileList.className = "report-file-list";
  reportFileList.innerHTML = `
    <div class="report-file-toolbar">
      ${documents
        .map(
          (document) => `
            <button
              class="report-file-button"
              type="button"
              data-document-path="${escapeHtml(document.path)}"
            >
              ${escapeHtml(document.title)}
            </button>
          `
        )
        .join("")}
    </div>
  `;

  renderReportDocument(payload.default_document || documents[0].path);
}

tabButtons.forEach((button) => {
  button.addEventListener("click", () => setTab(button.dataset.tabTarget));
});

Object.entries(providerGroups).forEach(([groupName, group]) => {
  group.select.addEventListener("change", (event) => updateModelDefault(groupName, event.target.value));
});

onDemandSubmitButton.addEventListener("click", submitOnDemandRun);
onDemandDateInput.addEventListener("input", () => setMessage(onDemandMessage, ""));
onDemandTickerInput.addEventListener("input", () => setMessage(onDemandMessage, ""));
dailyDateInput.addEventListener("input", () => {
  setMessage(dailyMessage, "");
  dailyStatusDate.textContent = dailyDateInput.value.trim() || window.TRADINGAGENTS_DEFAULT_DATE;
});
dailyPrepareButton.addEventListener("click", prepareDailyRun);
dailyRunMissingButton.addEventListener("click", runMissingDaily);
dailyStatusTable.addEventListener("click", (event) => {
  const button = event.target.closest("[data-retry-ticker]");
  if (!button) {
    return;
  }
  retryDailyTicker(button.dataset.retryTicker);
});
tickerSelect.addEventListener("change", (event) => loadReportsForTicker(event.target.value));
reportSelect.addEventListener("change", () => loadReport(tickerSelect.value, reportSelect.value));
reportFileList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-document-path]");
  if (!button) {
    return;
  }
  renderReportDocument(button.dataset.documentPath);
});

loadProviders();
fetchJobs();
loadDailyWatchlist();
loadDailyManifest(window.TRADINGAGENTS_DEFAULT_DATE, { quiet: true });
loadTickers();
loadTokenUsage();
setInterval(() => {
  fetchJobs();
  loadDailyManifest(activeDailyTradeDate, { quiet: true });
  loadTokenUsage();
}, 5000);
