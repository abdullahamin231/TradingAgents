import {
  settingsDailyRunTime,
  settingsHalalCheckerEnabled,
  settingsMessage,
  settingsSaveButton,
  settingsSummary,
} from "./dom.js?v=settings-tab-1";
import { escapeHtml, setMessage } from "./utils.js?v=settings-tab-1";

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

export function bindSettingsActions() {
  settingsSaveButton.addEventListener("click", saveSettings);
  settingsHalalCheckerEnabled.addEventListener("change", () => setMessage(settingsMessage, ""));
  settingsDailyRunTime.addEventListener("input", () => setMessage(settingsMessage, ""));
}
