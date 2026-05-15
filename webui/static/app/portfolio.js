import {
  portfolioCurrentHoldings,
  portfolioCurrentMeta,
  portfolioCurrentSummary,
  portfolioExecutePlanButton,
  portfolioExecutionMeta,
  portfolioExecutionTable,
  portfolioGeneratePlanButton,
  portfolioLoadCurrentButton,
  portfolioMessage,
  portfolioOrderIntents,
  portfolioPlanMeta,
  portfolioPlanSummary,
  portfolioPositionsInput,
  portfolioRankingTable,
  portfolioSaveCurrentButton,
  portfolioSelectedTickers,
  portfolioSyncBrokerButton,
  portfolioTargetHoldings,
  portfolioTargetSummary,
  portfolioTradeDateInput,
} from "./dom.js?v=portfolio-tab-3";
import { state } from "./state.js?v=portfolio-tab-3";
import { escapeHtml, formatCurrency, formatDateTime, formatPercent, isValidTradeDate, setMessage, statusClass } from "./utils.js?v=portfolio-tab-3";

const FIXED_MAX_POSITIONS = 10;

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

  const broker = payload.broker || null;
  portfolioCurrentSummary.className = "summary-strip";
  portfolioCurrentSummary.innerHTML = [
    ["As of", escapeHtml(payload.as_of || "n/a")],
    ["Equity", escapeHtml(formatCurrency(payload.total_equity))],
    ["Cash", escapeHtml(formatCurrency(payload.cash_notional))],
    ["Buying power", escapeHtml(formatCurrency(broker?.buying_power || 0))],
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
          <th>Shares</th>
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
                <td>${escapeHtml(position.shares ?? "n/a")}</td>
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
    ["Target names", String(plan.max_positions || FIXED_MAX_POSITIONS)],
    ["Sizing", "Equal weight +/- 10%"],
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
          <th>Sell qty</th>
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
                <td>${escapeHtml(order.estimated_sell_qty ?? "n/a")}</td>
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
  renderTargetPortfolio(plan.target_portfolio);
}

function selectedTotalEquity() {
  const portfolioEquity = Number(state.currentPortfolio?.total_equity || 0);
  return portfolioEquity > 0 ? portfolioEquity : null;
}

function renderTargetPortfolio(targetPortfolio) {
  const positions = targetPortfolio?.positions || [];
  if (!targetPortfolio) {
    portfolioTargetSummary.className = "summary-strip empty-state";
    portfolioTargetSummary.textContent = "No proposed allocation yet.";
    portfolioTargetHoldings.className = "daily-table-shell empty-state";
    portfolioTargetHoldings.textContent = "No proposed positions yet.";
    return;
  }

  portfolioTargetSummary.className = "summary-strip";
  portfolioTargetSummary.innerHTML = [
    ["Trade date", targetPortfolio.as_of || "n/a"],
    ["Target equity", formatCurrency(targetPortfolio.total_equity)],
    ["Target cash", formatCurrency(targetPortfolio.cash_notional)],
    ["Target names", String(positions.length)],
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

  if (!positions.length) {
    portfolioTargetHoldings.className = "daily-table-shell empty-state";
    portfolioTargetHoldings.textContent = "No proposed positions yet.";
    return;
  }

  portfolioTargetHoldings.className = "daily-table-shell";
  portfolioTargetHoldings.innerHTML = `
    <table class="daily-table">
      <thead>
        <tr>
          <th>Ticker</th>
          <th>Target notional</th>
          <th>Target weight</th>
          <th>Rating</th>
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

function renderExecutionResult(execution) {
  state.lastExecution = execution;
  if (!execution) {
    portfolioExecutionMeta.textContent = "No paper-trade submission yet.";
    portfolioExecutionTable.className = "daily-table-shell empty-state";
    portfolioExecutionTable.textContent = "Submitted Alpaca paper orders will appear here.";
    return;
  }

  portfolioExecutionMeta.textContent = `Submitted ${execution.submitted_order_count || 0} Alpaca paper orders on ${formatDateTime(execution.submitted_at)}.`;
  const orders = execution.submitted_orders || [];
  portfolioExecutionTable.className = orders.length ? "daily-table-shell" : "daily-table-shell empty-state";
  if (!orders.length) {
    portfolioExecutionTable.textContent = "No submitted orders returned.";
    return;
  }

  portfolioExecutionTable.innerHTML = `
    <table class="daily-table">
      <thead>
        <tr>
          <th>Ticker</th>
          <th>Side</th>
          <th>Status</th>
          <th>Submitted payload</th>
        </tr>
      </thead>
      <tbody>
        ${orders
          .map(
            (order) => `
              <tr>
                <td><strong>${escapeHtml(order.ticker)}</strong></td>
                <td><span class="${statusClass(order.side)}">${escapeHtml(order.side)}</span></td>
                <td>${escapeHtml(order.alpaca_status || "submitted")}</td>
                <td><code class="report-path-value">${escapeHtml(JSON.stringify(order.submitted_payload || {}))}</code></td>
              </tr>
            `
          )
          .join("")}
      </tbody>
    </table>
  `;
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
    const positionsNotional = positions.reduce((sum, position) => sum + Number(position.current_notional || 0), 0);
    const totalEquity = Number(state.currentPortfolio?.total_equity || positionsNotional);
    const cashNotional = Number(state.currentPortfolio?.cash_notional || Math.max(totalEquity - positionsNotional, 0));
    const payload = {
      as_of: portfolioTradeDateInput.value.trim() || null,
      total_equity: totalEquity,
      cash_notional: cashNotional,
      positions,
      source: "paper_ui",
      broker: state.currentPortfolio?.broker || null,
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

async function requestRebalancePlan() {
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
        total_equity: selectedTotalEquity(),
        max_positions: FIXED_MAX_POSITIONS,
        apply_targets: false,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      setMessage(portfolioMessage, payload.detail || "Failed to generate rebalance plan.", true);
      return;
    }
    renderRebalancePlan(payload);
    setMessage(portfolioMessage, "Generated rebalance plan.");
  } catch (error) {
    setMessage(portfolioMessage, error.message || "Failed to generate rebalance plan.", true);
  }
}

export async function generateRebalancePlan() {
  portfolioGeneratePlanButton.disabled = true;
  try {
    await requestRebalancePlan();
  } finally {
    portfolioGeneratePlanButton.disabled = false;
  }
}

export async function syncBrokerPortfolio() {
  portfolioSyncBrokerButton.disabled = true;
  try {
    const response = await fetch("/api/portfolio/alpaca-paper/sync", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    const payload = await response.json();
    if (!response.ok) {
      setMessage(portfolioMessage, payload.detail || "Failed to sync Alpaca paper portfolio.", true);
      return;
    }
    renderCurrentPortfolio(payload);
    setMessage(portfolioMessage, "Synced live Alpaca paper portfolio.");
  } catch (error) {
    setMessage(portfolioMessage, error.message || "Failed to sync Alpaca paper portfolio.", true);
  } finally {
    portfolioSyncBrokerButton.disabled = false;
  }
}

export async function executeRebalancePlan() {
  const tradeDate = portfolioTradeDateInput.value.trim();
  if (!isValidTradeDate(tradeDate)) {
    setMessage(portfolioMessage, "Date must use YYYY-MM-DD.", true);
    return;
  }

  portfolioExecutePlanButton.disabled = true;
  try {
    const response = await fetch(`/api/daily-runs/${encodeURIComponent(tradeDate)}/rebalance-execution`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        total_equity: selectedTotalEquity(),
        max_positions: FIXED_MAX_POSITIONS,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      setMessage(portfolioMessage, payload.detail || "Failed to submit Alpaca paper orders.", true);
      return;
    }
    if (payload.plan) {
      renderRebalancePlan(payload.plan);
    }
    renderExecutionResult(payload);
    setMessage(portfolioMessage, `Submitted ${payload.submitted_order_count || 0} Alpaca paper orders.`);
  } catch (error) {
    setMessage(portfolioMessage, error.message || "Failed to submit Alpaca paper orders.", true);
  } finally {
    portfolioExecutePlanButton.disabled = false;
  }
}

export function bindPortfolioActions() {
  portfolioLoadCurrentButton.addEventListener("click", () => loadCurrentPortfolio());
  portfolioSyncBrokerButton.addEventListener("click", syncBrokerPortfolio);
  portfolioSaveCurrentButton.addEventListener("click", saveCurrentPortfolio);
  portfolioGeneratePlanButton.addEventListener("click", generateRebalancePlan);
  portfolioExecutePlanButton.addEventListener("click", executeRebalancePlan);
}
