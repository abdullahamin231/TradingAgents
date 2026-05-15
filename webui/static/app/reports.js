import { reportFileList, reportMeta, reportSelect, reportTitle, reportView, tickerSelect, tickerSummary } from "./dom.js?v=portfolio-tab-5";
import { state } from "./state.js?v=portfolio-tab-5";
import { escapeHtml } from "./utils.js?v=portfolio-tab-5";

export function resetReportViewer() {
  state.activeReportPayload = null;
  reportTitle.textContent = "No report selected";
  reportMeta.className = "report-browser-meta empty-state";
  reportMeta.textContent = "Select a ticker and snapshot to inspect the markdown files inside that saved report.";
  reportFileList.className = "report-file-list hidden";
  reportFileList.innerHTML = "";
  reportView.className = "report-view empty-state";
  reportView.textContent = "Select a ticker and saved snapshot to render the report.";
}

export async function loadTickers() {
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

export async function loadReportsForTicker(ticker) {
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

export function renderReportDocument(documentPath) {
  if (!state.activeReportPayload) {
    resetReportViewer();
    return;
  }

  const documents = state.activeReportPayload.documents || [];
  const selectedDocument =
    documents.find((document) => document.path === documentPath) ||
    documents.find((document) => document.path === state.activeReportPayload.default_document) ||
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

export async function loadReport(ticker, reportId) {
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

  state.activeReportPayload = payload;
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
