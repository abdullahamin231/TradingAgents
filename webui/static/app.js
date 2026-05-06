const runRows = document.querySelector("#run-rows");
const addRowButton = document.querySelector("#add-row");
const submitRunsButton = document.querySelector("#submit-runs");
const jobsList = document.querySelector("#jobs-list");
const tickerSelect = document.querySelector("#ticker-select");
const reportSelect = document.querySelector("#report-select");
const tickerSummary = document.querySelector("#ticker-summary");
const reportTitle = document.querySelector("#report-title");
const reportView = document.querySelector("#report-view");
const providerSelect = document.querySelector("#provider-select");
const modelInput = document.querySelector("#model-input");
const opencodeModelField = document.querySelector("#opencode-model-field");
const providerModelFields = document.querySelector("#provider-model-fields");
const quickModelInput = document.querySelector("#quick-model-input");
const deepModelInput = document.querySelector("#deep-model-input");
const sharedDateInput = document.querySelector("#shared-date");
const composerMessage = document.querySelector("#composer-message");

let providerOptions = [];

function createRunRow(initialTicker = "") {
  const row = document.createElement("div");
  row.className = "run-row";
  row.innerHTML = `
    <input class="ticker-input" type="text" placeholder="Symbol (e.g. NVDA)" value="${initialTicker}" spellcheck="false" />
    <button class="remove-row" type="button" aria-label="Remove symbol">-</button>
  `;
  row.querySelector(".remove-row").addEventListener("click", () => {
    if (runRows.children.length > 1) {
      row.remove();
    }
  });
  runRows.appendChild(row);
}

function setComposerMessage(message = "", isError = false) {
  composerMessage.textContent = message;
  composerMessage.style.color = isError ? "var(--danger)" : "var(--muted)";
}

function isValidTradeDate(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value);
}

function statusClass(status) {
  return `status-pill status-${status || "queued"}`;
}

function updateModelDefault(providerValue) {
  const provider = providerOptions.find((item) => item.value === providerValue);
  if (!provider) {
    return;
  }

  const isOpenCode = providerValue === "opencode";
  opencodeModelField.classList.toggle("hidden", !isOpenCode);
  providerModelFields.classList.toggle("hidden", isOpenCode);

  if (isOpenCode) {
    modelInput.value = provider.default_deep_model || provider.default_quick_model || "";
    modelInput.placeholder = provider.note || "Model name or deployment";
    return;
  }

  quickModelInput.value = provider.default_quick_model || "";
  deepModelInput.value = provider.default_deep_model || "";
  quickModelInput.placeholder = provider.note || "Quick think model";
  deepModelInput.placeholder = provider.note || "Deep think model";
}

function renderProviders() {
  if (!providerOptions.length) {
    return;
  }

  providerSelect.innerHTML = providerOptions
    .map(
      (provider) => `
        <option value="${provider.value}">${provider.label}</option>
      `
    )
    .join("");

  providerSelect.value = providerOptions[0].value;
  updateModelDefault(providerSelect.value);
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
          <p class="job-meta">Job ${job.job_id.slice(0, 8)} · Provider: ${job.provider || "opencode"}</p>
          ${
            job.provider === "opencode"
              ? `<p class="job-meta">Model: ${job.deep_model || job.quick_model || "default"}</p>`
              : `<p class="job-meta">Quick: ${job.quick_model || "default"} · Deep: ${job.deep_model || "default"}</p>`
          }
          <p>${job.decision || job.error || "Waiting for completion..."}</p>
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
    renderProviders();
  } catch (error) {
    providerOptions = [];
    providerSelect.innerHTML = `<option value="opencode">OpenCode</option>`;
    providerSelect.value = "opencode";
    opencodeModelField.classList.remove("hidden");
    providerModelFields.classList.add("hidden");
    modelInput.placeholder = "Model name or deployment";
  }
}

async function fetchJobs() {
  const response = await fetch("/api/jobs");
  const payload = await response.json();
  renderJobs(payload.jobs || []);
}

async function submitRuns() {
  const tradeDate = sharedDateInput.value.trim();
  if (!isValidTradeDate(tradeDate)) {
    setComposerMessage("Date must use YYYY-MM-DD.", true);
    return;
  }

  const rows = [...runRows.querySelectorAll(".run-row")];
  const runs = rows
    .map((row) => ({
      ticker: row.querySelector(".ticker-input").value.trim(),
      trade_date: tradeDate,
      provider: providerSelect.value,
      model: providerSelect.value === "opencode" ? modelInput.value.trim() : null,
      quick_model: providerSelect.value === "opencode" ? null : quickModelInput.value.trim(),
      deep_model: providerSelect.value === "opencode" ? null : deepModelInput.value.trim(),
    }))
    .filter((run) => run.ticker);

  if (!runs.length) {
    setComposerMessage("Enter at least one symbol.", true);
    return;
  }

  submitRunsButton.disabled = true;
  setComposerMessage("");
  try {
    const response = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ runs }),
    });
    if (!response.ok) {
      const payload = await response.json();
      setComposerMessage(payload.detail || "Run submission failed.", true);
      return;
    }
    const providerLabel = providerSelect.options[providerSelect.selectedIndex]?.textContent || providerSelect.value;
    setComposerMessage(
      `Queued ${runs.length} symbol${runs.length === 1 ? "" : "s"} for ${tradeDate} with ${providerLabel}.`
    );
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
  reportSelect.innerHTML = `<option value="">Trade date</option>`;
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
sharedDateInput.addEventListener("input", () => setComposerMessage(""));
providerSelect.addEventListener("change", (event) => updateModelDefault(event.target.value));

createRunRow("SPY");
createRunRow("NVDA");
loadProviders();
fetchJobs();
loadTickers();
setInterval(fetchJobs, 5000);
