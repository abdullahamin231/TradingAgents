import {
  dailyDateInput,
  dailyMessage,
  dailyPrepareButton,
  dailyRerunHalalButton,
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
} from "./dom.js?v=settings-tab-1";
import { loadDailyManifest, loadDailyWatchlist, prepareDailyRun, rerunHalalCheck, rescrapeDailyWatchlist, retryDailyTicker, runMissingDaily } from "./daily.js?v=settings-tab-1";
import { fetchJobs } from "./jobs.js?v=settings-tab-1";
import { submitOnDemandRun } from "./on-demand.js?v=settings-tab-1";
import { bindPortfolioActions, loadCurrentPortfolio } from "./portfolio.js?v=settings-tab-1";
import { loadProviders, updateModelDefault } from "./providers.js?v=settings-tab-1";
import { loadReport, loadReportsForTicker, loadTickers, renderReportDocument } from "./reports.js?v=settings-tab-1";
import { bindSettingsActions, loadSettings } from "./settings.js?v=settings-tab-1";
import { state } from "./state.js?v=settings-tab-1";
import { loadTokenUsage } from "./token-usage.js?v=settings-tab-1";
import { setMessage, setTab } from "./utils.js?v=settings-tab-1";

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
  dailyRerunHalalButton.addEventListener("click", rerunHalalCheck);
  dailyStatusTable.addEventListener("click", (event) => {
    const button = event.target.closest("[data-retry-ticker]");
    if (!button) {
      return;
    }
    retryDailyTicker(button.dataset.retryTicker);
  });

  portfolioTradeDateInput.addEventListener("input", () => setMessage(portfolioMessage, ""));
  bindPortfolioActions();
  bindSettingsActions();

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
  loadSettings();
  startPolling();
}
