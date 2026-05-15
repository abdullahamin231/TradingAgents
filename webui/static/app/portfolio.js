import {
  portfolioApplyPlanButton,
  portfolioCashNotionalInput,
  portfolioCurrentHoldings,
  portfolioCurrentMeta,
  portfolioCurrentSummary,
  portfolioGeneratePlanButton,
  portfolioLoadCurrentButton,
  portfolioMaxPositionsInput,
  portfolioMessage,
  portfolioOrderIntents,
  portfolioPlanMeta,
  portfolioPlanSummary,
  portfolioPositionsInput,
  portfolioRankingTable,
  portfolioSaveCurrentButton,
  portfolioSelectedTickers,
  portfolioTotalEquityInput,
  portfolioTradeDateInput,
} from "./dom.js?v=portfolio-tab-2";
import { state } from "./state.js?v=portfolio-tab-2";
import { escapeHtml, formatCurrency, formatDateTime, formatPercent, isValidTradeDate, setMessage, statusClass } from "./utils.js?v=portfolio-tab-2";

function parsePositionsInput() {
  const lines = portfolioPositionsInput.value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  return lines.map((line) => {
    const [ticker, currentNotional, currentWeight, lastRating] = line.split(",").map((part) => part?.trim() || "");
    if (!ticker) {
      throw new Error(`Invalid holding line: ${line}`);
    }
    const notional = Number(currentNotional || 0);
    const weight = Number(currentWeight || 0);
    if (Number.isNaN(notional) || Number.isNaN(weight)) {
      throw new Error(`Invalid numeric values in line: ${line}`);
    }
    return {
      ticker,
      current_notional: notional,
      current_weight: weight,
      last_rating: lastRating || "Hold",
    };
  });
}

function renderPositionsInput(positions = []) {
  portfolioPositionsInput.value = positions
    .map((position) =>
      [position.ticker, position.current_notional ?? 0, position.current_weight ?? 0, position.last_rating || "Hold"]
        .map((value) => value ?? "")
        .join(", ")
    )
    .join("\n");
}

function renderCurrentPortfolio(payload) {
  state.currentPortfolio = payload;
  portfolioTradeDateInput.value = payload.as_of || portfolioTradeDateInput.value || window.TRADINGAGENTS_DEFAULT_DATE;
  portfolioTotalEquityInput.value = Number(payload.total_equity || 100000);
  portfolioCashNotionalInput.value = Number(payload.cash_notional || 0);
  renderPositionsInput(
    (payload.positions || []).map((position) => ({
      ticker: position.ticker,
      current_notional: position.current_notional,
      current_weight: position.current_weight,
      last_rating: position.last_rating,
    }))
  );

  portfolioCurrentMeta.textContent = payload.updated_at
    ? `Updated ${formatDateTime(payload.updated_at)} from ${payload.source || "paper"}.`
    : `Source: ${payload.source || "paper"}.`;

  portfolioCurrentSummary.className = "summary-strip";
  portfolioCurrentSummary.innerHTML = [
    ["As of", escapeHtml(payload.as_of || "n/a")],
    ["Equity", escapeHtml(formatCurrency(payload.total_equity))],
    ["Cash", escapeHtml(formatCurrency(payload.cash_notional))],
    ["Positions", escapeHtml(String((payload.positions || []).length))],
  ]
    .map(
      ([label, value]) => `
        <div class="summary-item">
          <span class="table-label">${label}</span>
          <strong>${value}</strong>
        </div>
      `
    )
    .join("");

  const positions = payload.positions || [];
  if (!positions.length) {
    portfolioCurrentHoldings.className = "daily-table-shell empty-state";
    portfolioCurrentHoldings.textContent = "No current holdings.";
    return;
  }

  portfolioCurrentHoldings.className = "daily-table-shell";
  portfolioCurrentHoldings.innerHTML = `
    <table class="daily-table">
      <thead>
        <tr>
          <th>Ticker</th>
          <th>Notional</th>
          <th>Weight</th>
          <th>Last rating</th>
        </tr>
      </thead>
      <tbody>
        ${positions
          .map(
            (position) => `
              <tr>
                <td><strong>${escapeHtml(position.ticker)}</strong></td>
                <td>${escapeHtml(formatCurrency(position.current_notional))}</td>
                <td>${escapeHtml(formatPercent(position.current_weight))}</td>
                <td>${escapeHtml(position.last_rating || "Hold")}</td>
              </tr>
            `
          )
          .join("")}
      </tbody>
    </table>
  `;
}

function renderPlanSummary(plan) {
  state.currentRebalancePlan = plan;
  const readyLabel = plan.ready ? "Ready to execute" : "Analysis pending";
  const pending = plan.pending_analysis || [];
  const additions = plan.new_watchlist_additions || [];

  portfolioPlanMeta.className = `portfolio-banner ${plan.ready ? "portfolio-banner-ready" : "portfolio-banner-pending"}`;
  portfolioPlanMeta.innerHTML = `
    <strong>${escapeHtml(readyLabel)}</strong>
    <span>Trade date ${escapeHtml(plan.trade_date)}. ${pending.length ? `Waiting on ${escapeHtml(pending.join(", "))}.` : `All required names analyzed.`}</span>
    <span>${additions.length ? `New additions: ${escapeHtml(additions.join(", "))}.` : "No new watchlist additions."}</span>
  `;

  portfolioPlanSummary.className = "summary-strip";
  portfolioPlanSummary.innerHTML = [
    ["Required", String(plan.analysis_coverage?.required || 0)],
    ["Pending", String(plan.analysis_coverage?.pending || 0)],
    ["Selected", String((plan.selected_tickers || []).length)],
    ["Orders", String((plan.order_intents || []).length)],
    ["Equity", formatCurrency(plan.total_equity)],
    ["Max positions", String(plan.max_positions || 0)],
  ]
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

function renderSelectedTickers(plan) {
  const tickers = plan.selected_tickers || [];
  portfolioSelectedTickers.className = tickers.length ? "ticker-list" : "ticker-list empty-state";
  portfolioSelectedTickers.innerHTML = tickers.length
    ? tickers.map((ticker) => `<span class="ticker-chip">${escapeHtml(ticker)}</span>`).join("")
    : "No selected tickers yet.";
}

function renderRankingTable(plan) {
  const ranking = plan.ranking || [];
  if (!ranking.length) {
    portfolioRankingTable.className = "daily-table-shell empty-state";
    portfolioRankingTable.textContent = "No ranking available yet.";
    return;
  }

  portfolioRankingTable.className = "daily-table-shell";
  portfolioRankingTable.innerHTML = `
    <table class="daily-table">
      <thead>
        <tr>
          <th>Ticker</th>
          <th>Rating</th>
          <th>Current</th>
          <th>Target</th>
          <th>Delta</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody>
        ${ranking
          .map(
            (item) => `
              <tr>
                <td>
                  <strong>${escapeHtml(item.ticker)}</strong>
                  <div class="portfolio-row-meta">${item.selected_for_target_portfolio ? "selected" : "excluded"}${item.is_new_watchlist_addition ? " • new" : ""}${item.is_existing_holding ? " • held" : ""}</div>
                </td>
                <td>${escapeHtml(item.rating)}</td>
                <td>${escapeHtml(formatPercent(item.current_weight))}<div class="portfolio-row-meta">${escapeHtml(formatCurrency(item.current_notional))}</div></td>
                <td>${escapeHtml(formatPercent(item.target_weight))}<div class="portfolio-row-meta">${escapeHtml(formatCurrency(item.target_notional))}</div></td>
                <td>${escapeHtml(formatCurrency(item.delta_notional))}</td>
                <td><span class="${statusClass(item.rebalance_action)}">${escapeHtml(item.rebalance_action)}</span></td>
              </tr>
            `
          )
          .join("")}
      </tbody>
    </table>
  `;
}

function renderOrderIntents(plan) {
  const orders = plan.order_intents || [];
  if (!orders.length) {
    portfolioOrderIntents.className = "daily-table-shell empty-state";
    portfolioOrderIntents.textContent = "No order intents yet.";
    return;
  }

  portfolioOrderIntents.className = "daily-table-shell";
  portfolioOrderIntents.innerHTML = `
    <table class="daily-table">
      <thead>
        <tr>
          <th>Ticker</th>
          <th>Side</th>
          <th>Delta</th>
          <th>Target weight</th>
          <th>Broker payload</th>
        </tr>
      </thead>
      <tbody>
        ${orders
          .map(
            (order) => `
              <tr>
                <td><strong>${escapeHtml(order.ticker)}</strong></td>
                <td><span class="${statusClass(order.side)}">${escapeHtml(order.side)}</span></td>
                <td>${escapeHtml(formatCurrency(order.delta_notional))}</td>
                <td>${escapeHtml(formatPercent(order.target_weight))}</td>
                <td><code class="report-path-value">${escapeHtml(JSON.stringify(order.broker_payload))}</code></td>
              </tr>
            `
          )
          .join("")}
      </tbody>
    </table>
  `;
}

function renderRebalancePlan(plan) {
  renderPlanSummary(plan);
  renderSelectedTickers(plan);
  renderRankingTable(plan);
  renderOrderIntents(plan);
}

export async function loadCurrentPortfolio({ quiet = false } = {}) {
  try {
    const response = await fetch("/api/portfolio/current");
    const payload = await response.json();
    if (!response.ok) {
      if (!quiet) {
        setMessage(portfolioMessage, payload.detail || "Failed to load portfolio.", true);
      }
      return;
    }
    renderCurrentPortfolio(payload);
  } catch (error) {
    if (!quiet) {
      setMessage(portfolioMessage, error.message || "Failed to load portfolio.", true);
    }
  }
}

export async function saveCurrentPortfolio() {
  try {
    const positions = parsePositionsInput();
    const payload = {
      as_of: portfolioTradeDateInput.value.trim() || null,
      total_equity: Number(portfolioTotalEquityInput.value || 0),
      cash_notional: Number(portfolioCashNotionalInput.value || 0),
      positions,
      source: "paper_ui",
    };
    const response = await fetch("/api/portfolio/current", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const saved = await response.json();
    if (!response.ok) {
      setMessage(portfolioMessage, saved.detail || "Failed to save portfolio.", true);
      return;
    }
    renderCurrentPortfolio(saved);
    setMessage(portfolioMessage, "Saved current portfolio snapshot.");
  } catch (error) {
    setMessage(portfolioMessage, error.message || "Failed to parse positions.", true);
  }
}

async function requestRebalancePlan(applyTargets) {
  const tradeDate = portfolioTradeDateInput.value.trim();
  if (!isValidTradeDate(tradeDate)) {
    setMessage(portfolioMessage, "Date must use YYYY-MM-DD.", true);
    return;
  }

  try {
    const response = await fetch(`/api/daily-runs/${encodeURIComponent(tradeDate)}/rebalance-plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        total_equity: Number(portfolioTotalEquityInput.value || 0),
        max_positions: Number(portfolioMaxPositionsInput.value || 10),
        apply_targets: applyTargets,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      setMessage(portfolioMessage, payload.detail || "Failed to generate rebalance plan.", true);
      return;
    }
    renderRebalancePlan(payload);
    if (payload.target_portfolio) {
      renderCurrentPortfolio(payload.target_portfolio);
    }
    setMessage(
      portfolioMessage,
      applyTargets ? "Applied target portfolio snapshot." : "Generated rebalance plan."
    );
  } catch (error) {
    setMessage(portfolioMessage, error.message || "Failed to generate rebalance plan.", true);
  }
}

export async function generateRebalancePlan() {
  portfolioGeneratePlanButton.disabled = true;
  try {
    await requestRebalancePlan(false);
  } finally {
    portfolioGeneratePlanButton.disabled = false;
  }
}

export async function applyRebalancePlan() {
  portfolioApplyPlanButton.disabled = true;
  try {
    await requestRebalancePlan(true);
  } finally {
    portfolioApplyPlanButton.disabled = false;
  }
}

export function bindPortfolioActions() {
  portfolioLoadCurrentButton.addEventListener("click", () => loadCurrentPortfolio());
  portfolioSaveCurrentButton.addEventListener("click", saveCurrentPortfolio);
  portfolioGeneratePlanButton.addEventListener("click", generateRebalancePlan);
  portfolioApplyPlanButton.addEventListener("click", applyRebalancePlan);
}
