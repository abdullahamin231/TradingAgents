const runRows = document.querySelector("#run-rows");
const addRowButton = document.querySelector("#add-row");
const submitRunsButton = document.querySelector("#submit-runs");
const jobsList = document.querySelector("#jobs-list");
const tickerSelect = document.querySelector("#ticker-select");
const reportSelect = document.querySelector("#report-select");
const tickerSummary = document.querySelector("#ticker-summary");
const reportTitle = document.querySelector("#report-title");
const reportView = document.querySelector("#report-view");

function createRunRow(initialTicker = "", initialDate = window.TRADINGAGENTS_DEFAULT_DATE) {
  const row = document.createElement("div");
  row.className = "run-row";
  row.innerHTML = `
    <input class="ticker-input" type="text" placeholder="Ticker (e.g. NVDA)" value="${initialTicker}" />
    <input class="date-input" type="date" value="${initialDate}" />
    <button class="remove-row" type="button">Remove</button>
  `;
  row.querySelector(".remove-row").addEventListener("click", () => {
    if (runRows.children.length > 1) {
      row.remove();
    }
  });
  runRows.appendChild(row);
}

function statusClass(status) {
  return `status-pill status-${status || "queued"}`;
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
        <article class="job-card">
          <div class="job-top">
            <strong>${job.ticker} / ${job.trade_date}</strong>
            <span class="${statusClass(job.status)}">${job.status}</span>
          </div>
          <p class="job-meta">Job ${job.job_id.slice(0, 8)} · OpenCode model: ${job.opencode_model || "from opencode.json"}</p>
          <p>${job.decision || job.error || "Waiting for completion..."}</p>
        </article>
      `
    )
    .join("");
}

async function fetchJobs() {
  const response = await fetch("/api/jobs");
  const payload = await response.json();
  renderJobs(payload.jobs || []);
}

async function submitRuns() {
  const rows = [...runRows.querySelectorAll(".run-row")];
  const runs = rows
    .map((row) => ({
      ticker: row.querySelector(".ticker-input").value.trim(),
      trade_date: row.querySelector(".date-input").value,
    }))
    .filter((run) => run.ticker && run.trade_date);

  if (!runs.length) {
    return;
  }

  submitRunsButton.disabled = true;
  try {
    await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ runs }),
    });
    await fetchJobs();
    await loadTickers();
  } finally {
    submitRunsButton.disabled = false;
  }
}

async function loadTickers() {
  const response = await fetch("/api/tickers");
  const payload = await response.json();
  const tickers = payload.tickers || [];

  tickerSelect.innerHTML = `<option value="">Select a ticker</option>`;
  tickers.forEach((ticker) => {
    const option = document.createElement("option");
    option.value = ticker.ticker;
    option.textContent = `${ticker.ticker} (${ticker.report_count})`;
    tickerSelect.appendChild(option);
  });

  if (!tickers.length) {
    tickerSummary.className = "ticker-summary empty-state";
    tickerSummary.textContent = "No saved reports found in reports/.";
    return;
  }

  tickerSummary.className = "ticker-summary";
  tickerSummary.innerHTML = `
    <div class="ticker-list">
      ${tickers
        .map(
          (ticker) => `<span class="report-chip">${ticker.ticker} · ${ticker.report_count} logs · latest ${ticker.latest_trade_date || "n/a"}</span>`
        )
        .join("")}
    </div>
  `;
}

async function loadReportsForTicker(ticker) {
  reportSelect.innerHTML = `<option value="">Select a report date</option>`;
  reportTitle.textContent = "No report selected";
  reportView.className = "report-view empty-state";
  reportView.textContent = "Select a ticker and report date to render the saved analysis.";

  if (!ticker) {
    return;
  }

  const response = await fetch(`/api/tickers/${encodeURIComponent(ticker)}/reports`);
  const payload = await response.json();
  const reports = payload.reports || [];

  reports.forEach((report) => {
    const option = document.createElement("option");
    option.value = report.trade_date;
    option.textContent = `${report.trade_date} · ${report.file_name}`;
    reportSelect.appendChild(option);
  });
}

async function loadReport(ticker, tradeDate) {
  if (!ticker || !tradeDate) {
    return;
  }

  const response = await fetch(`/api/tickers/${encodeURIComponent(ticker)}/reports/${encodeURIComponent(tradeDate)}`);
  const payload = await response.json();

  reportTitle.textContent = `${payload.ticker} · ${payload.trade_date}`;
  reportView.className = "report-view";
  reportView.innerHTML = `
    <div class="report-header">
      <p class="report-meta">Company of interest: ${payload.company_of_interest}</p>
    </div>
    ${payload.sections
      .map(
        (section) => `
          <section class="section-card">
            <h3>${section.title}</h3>
            <div class="html">${section.html}</div>
          </section>
        `
      )
      .join("")}
    ${payload.debates
      .map(
        (section) => `
          <section class="debate-card">
            <h3>${section.title}</h3>
            <div class="html">${section.html}</div>
          </section>
        `
      )
      .join("")}
  `;
}

addRowButton.addEventListener("click", () => createRunRow());
submitRunsButton.addEventListener("click", submitRuns);
tickerSelect.addEventListener("change", (event) => loadReportsForTicker(event.target.value));
reportSelect.addEventListener("change", () => loadReport(tickerSelect.value, reportSelect.value));

createRunRow("SPY");
createRunRow("NVDA");
fetchJobs();
loadTickers();
setInterval(fetchJobs, 5000);
