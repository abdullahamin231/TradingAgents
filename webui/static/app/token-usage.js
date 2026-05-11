import { tokenUsageCharts, tokenUsageRuns, tokenUsageSummary } from "./dom.js";
import { escapeHtml, formatDateTime, formatDecimal, formatDuration, formatNumber, statusClass, usageMetrics } from "./utils.js";

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

export function renderTokenUsage(payload) {
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

export async function loadTokenUsage() {
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
