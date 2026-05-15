export const tabButtons = [...document.querySelectorAll(".tab-button")];
export const tabPanels = [...document.querySelectorAll(".tab-panel")];
export const jobsList = document.querySelector("#jobs-list");
export const tickerSelect = document.querySelector("#ticker-select");
export const reportSelect = document.querySelector("#report-select");
export const tickerSummary = document.querySelector("#ticker-summary");
export const reportTitle = document.querySelector("#report-title");
export const reportMeta = document.querySelector("#report-meta");
export const reportFileList = document.querySelector("#report-file-list");
export const reportView = document.querySelector("#report-view");
export const dailyWatchlist = document.querySelector("#daily-watchlist");
export const dailyWatchlistMeta = document.querySelector("#daily-watchlist-meta");
export const dailyWatchlistHoldings = document.querySelector("#daily-watchlist-holdings");
export const dailyWatchlistDiff = document.querySelector("#daily-watchlist-diff");
export const dailyPolicy = document.querySelector("#daily-policy");
export const dailySummary = document.querySelector("#daily-summary");
export const dailyStatusTable = document.querySelector("#daily-status-table");
export const dailyStatusDate = document.querySelector("#daily-status-date");
export const portfolioTradeDateInput = document.querySelector("#portfolio-trade-date");
export const portfolioPositionsInput = document.querySelector("#portfolio-positions-input");
export const portfolioLoadCurrentButton = document.querySelector("#portfolio-load-current");
export const portfolioSyncBrokerButton = document.querySelector("#portfolio-sync-broker");
export const portfolioSaveCurrentButton = document.querySelector("#portfolio-save-current");
export const portfolioGeneratePlanButton = document.querySelector("#portfolio-generate-plan");
export const portfolioExecutePlanButton = document.querySelector("#portfolio-execute-plan");
export const portfolioMessage = document.querySelector("#portfolio-message");
export const portfolioCurrentMeta = document.querySelector("#portfolio-current-meta");
export const portfolioCurrentSummary = document.querySelector("#portfolio-current-summary");
export const portfolioCurrentHoldings = document.querySelector("#portfolio-current-holdings");
export const portfolioPlanMeta = document.querySelector("#portfolio-plan-meta");
export const portfolioPlanSummary = document.querySelector("#portfolio-plan-summary");
export const portfolioSelectedTickers = document.querySelector("#portfolio-selected-tickers");
export const portfolioRankingTable = document.querySelector("#portfolio-ranking-table");
export const portfolioOrderIntents = document.querySelector("#portfolio-order-intents");
export const portfolioTargetSummary = document.querySelector("#portfolio-target-summary");
export const portfolioTargetHoldings = document.querySelector("#portfolio-target-holdings");
export const portfolioExecutionMeta = document.querySelector("#portfolio-execution-meta");
export const portfolioExecutionTable = document.querySelector("#portfolio-execution-table");
export const tokenUsageSummary = document.querySelector("#token-usage-summary");
export const tokenUsageCharts = document.querySelector("#token-usage-charts");
export const tokenUsageRuns = document.querySelector("#token-usage-runs");

export const onDemandSubmitButton = document.querySelector("#on-demand-submit");
export const onDemandTickerInput = document.querySelector("#on-demand-ticker");
export const onDemandDateInput = document.querySelector("#on-demand-date");
export const onDemandMessage = document.querySelector("#on-demand-message");

export const dailyPrepareButton = document.querySelector("#prepare-daily-run");
export const dailyRunMissingButton = document.querySelector("#run-missing-daily");
export const dailyRescrapeButton = document.querySelector("#rescrape-daily-watchlist");
export const dailyDateInput = document.querySelector("#daily-date");
export const dailyMessage = document.querySelector("#daily-message");

export const providerGroups = {
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
