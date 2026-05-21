import {
  settingsDailyRunTime,
  settingsHalalCheckerEnabled,
  settingsHalalStatus,
  settingsMessage,
  settingsRunHalalButton,
  settingsSaveButton,
  settingsSummary,
} from "./dom.js?v=settings-tab-1";
import { loadDailyManifest, loadDailyWatchlist } from "./daily.js?v=settings-tab-1";
import { state } from "./state.js?v=settings-tab-1";
import { escapeHtml, setMessage } from "./utils.js?v=settings-tab-1";

let halalStatusPoll = null;

function renderSettings(payload) {
  settingsHalalCheckerEnabled.checked = Boolean(payload.halal_checker_enabled);
  settingsDailyRunTime.value = payload.daily_run_time || "09:30";
  settingsSummary.className = "portfolio-banner";
  settingsSummary.innerHTML = `
    <strong>Daily automation</strong>
    <span>Runs at ${escapeHtml(payload.daily_run_time || "09:30")} ${escapeHtml(payload.daily_run_timezone || "America/New_York")}.</span>
    <span>Halal checker: ${payload.halal_checker_enabled ? "enabled" : "disabled"}.</span>
    <span>Last scheduled run: ${escapeHtml(payload.last_scheduled_daily_run_date || "none")}.</span>
  `;
}

export async function loadSettings() {
  const response = await fetch("/api/settings");
  const payload = await response.json();
  if (!response.ok) {
    setMessage(settingsMessage, payload.detail || "Failed to load settings.", true);
    return;
  }
  renderSettings(payload);
}

function complianceClass(compliance = null) {
  if (!compliance) {
    return "";
  }
  if (["screening_error", "unknown"].includes(compliance.status)) {
    return " shariah-warning";
  }
  return compliance.allowed === false ? " shariah-blocked" : " shariah-compliant";
}

function renderHalalStatus(payload) {
  const summary = payload.summary || {};
  const refresh = payload.refresh || {};
  const rows = payload.tickers || [];
  const running = refresh.status === "running";
  settingsRunHalalButton.disabled = running;
  const progress = refresh.total ? `${refresh.processed || 0}/${refresh.total}` : "0/0";
  settingsHalalStatus.className = rows.length ? "daily-table-shell" : "daily-table-shell empty-state";
  settingsHalalStatus.innerHTML = `
    <div class="settings-status-head">
      <div>
        <strong>Halal screening cache</strong>
        <p>${escapeHtml(payload.cache_path || "No cache path")}</p>
      </div>
      <div class="settings-status-metrics">
        <span>Cached ${escapeHtml(summary.cached || 0)}</span>
        <span>Missing ${escapeHtml(summary.missing || 0)}</span>
        <span>Status ${escapeHtml(refresh.status || "idle")}</span>
        <span>Progress ${escapeHtml(progress)}</span>
      </div>
    </div>
    ${
      running
        ? `<div class="settings-progress"><div style="width: ${Math.min(100, Math.round(((refresh.processed || 0) / Math.max(refresh.total || 1, 1)) * 100))}%"></div></div>`
        : ""
    }
    <table class="daily-table settings-halal-table">
      <thead>
        <tr>
          <th>Ticker</th>
          <th>Cache</th>
          <th>Status</th>
          <th>Checked</th>
        </tr>
      </thead>
      <tbody>
        ${rows
          .map((row) => {
            const compliance = row.compliance || null;
            const status = compliance?.status || "missing";
            return `
              <tr>
                <td><strong>${escapeHtml(row.ticker)}</strong></td>
                <td>${row.cached ? "cached" : "missing"}</td>
                <td><span class="compliance-badge${complianceClass(compliance)}">${escapeHtml(status)}</span></td>
                <td>${escapeHtml(compliance?.checked_at || "n/a")}</td>
              </tr>
            `;
          })
          .join("")}
      </tbody>
    </table>
  `;
}

export async function loadHalalScreeningStatus() {
  const response = await fetch("/api/halal-screening/status");
  const payload = await response.json();
  if (!response.ok) {
    settingsHalalStatus.className = "daily-table-shell empty-state";
    settingsHalalStatus.textContent = payload.detail || "Failed to load halal screening cache.";
    return;
  }
  renderHalalStatus(payload);
  if (payload.refresh?.status !== "running" && halalStatusPoll !== null) {
    clearInterval(halalStatusPoll);
    halalStatusPoll = null;
  }
}

export async function saveSettings() {
  settingsSaveButton.disabled = true;
  setMessage(settingsMessage, "");
  try {
    const response = await fetch("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        halal_checker_enabled: settingsHalalCheckerEnabled.checked,
        daily_run_time: settingsDailyRunTime.value || "09:30",
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      setMessage(settingsMessage, payload.detail || "Failed to save settings.", true);
      return;
    }
    renderSettings(payload);
    setMessage(settingsMessage, "Saved settings.");
  } finally {
    settingsSaveButton.disabled = false;
  }
}

export async function runHalalScreeningRefresh() {
  settingsRunHalalButton.disabled = true;
  setMessage(settingsMessage, "");
  if (halalStatusPoll === null) {
    halalStatusPoll = setInterval(loadHalalScreeningStatus, 2500);
  }
  try {
    const response = await fetch("/api/halal-screening/refresh", { method: "POST" });
    const payload = await response.json();
    if (!response.ok) {
      setMessage(settingsMessage, payload.detail || "Failed to rerun halal tickers.", true);
      return;
    }
    await loadDailyWatchlist();
    await loadDailyManifest(state.activeDailyTradeDate, { quiet: true });
    await loadHalalScreeningStatus();
    const cache = payload.cache || {};
    const checkedCount = cache.miss_count || 0;
    const cachedCount = cache.hit_count || 0;
    setMessage(settingsMessage, `Halal screening complete. Checked ${checkedCount}, reused ${cachedCount} cached ticker${cachedCount === 1 ? "" : "s"}.`);
  } finally {
    settingsRunHalalButton.disabled = false;
  }
}

export function bindSettingsActions() {
  settingsSaveButton.addEventListener("click", saveSettings);
  settingsRunHalalButton.addEventListener("click", runHalalScreeningRefresh);
  settingsHalalCheckerEnabled.addEventListener("change", () => setMessage(settingsMessage, ""));
  settingsDailyRunTime.addEventListener("input", () => setMessage(settingsMessage, ""));
}
