import {
  dailyDateInput,
  dailyMessage,
  dailyPrepareButton,
  dailyRescrapeButton,
  dailyRunMissingButton,
  dailyStatusDate,
  dailyStatusTable,
  onDemandDateInput,
  onDemandMessage,
  onDemandSubmitButton,
  onDemandTickerInput,
  portfolioMessage,
  portfolioTradeDateInput,
  providerGroups,
  reportFileList,
  reportSelect,
  tabButtons,
  tickerSelect,
} from "./dom.js?v=portfolio-tab-2";
import { loadDailyManifest, loadDailyWatchlist, prepareDailyRun, rescrapeDailyWatchlist, retryDailyTicker, runMissingDaily } from "./daily.js";
import { fetchJobs } from "./jobs.js";
import { submitOnDemandRun } from "./on-demand.js";
import { bindPortfolioActions, loadCurrentPortfolio } from "./portfolio.js?v=portfolio-tab-2";
import { loadProviders, updateModelDefault } from "./providers.js";
import { loadReport, loadReportsForTicker, loadTickers, renderReportDocument } from "./reports.js";
import { state } from "./state.js?v=portfolio-tab-2";
import { loadTokenUsage } from "./token-usage.js";
import { setMessage, setTab } from "./utils.js?v=portfolio-tab-2";

function registerEventHandlers() {
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
  dailyRescrapeButton.addEventListener("click", rescrapeDailyWatchlist);
  dailyStatusTable.addEventListener("click", (event) => {
    const button = event.target.closest("[data-retry-ticker]");
    if (!button) {
      return;
    }
    retryDailyTicker(button.dataset.retryTicker);
  });

  portfolioTradeDateInput.addEventListener("input", () => setMessage(portfolioMessage, ""));
  bindPortfolioActions();

  tickerSelect.addEventListener("change", (event) => loadReportsForTicker(event.target.value));
  reportSelect.addEventListener("change", () => loadReport(tickerSelect.value, reportSelect.value));
  reportFileList.addEventListener("click", (event) => {
    const button = event.target.closest("[data-document-path]");
    if (!button) {
      return;
    }
    renderReportDocument(button.dataset.documentPath);
  });
}

function startPolling() {
  setInterval(() => {
    fetchJobs();
    loadDailyManifest(state.activeDailyTradeDate, { quiet: true });
    loadTokenUsage();
  }, 5000);
}

export function initApp() {
  registerEventHandlers();
  loadProviders();
  fetchJobs();
  loadDailyWatchlist();
  loadDailyManifest(window.TRADINGAGENTS_DEFAULT_DATE, { quiet: true });
  loadCurrentPortfolio({ quiet: true });
  loadTickers();
  loadTokenUsage();
  startPolling();
}
