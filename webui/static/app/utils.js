import { tabButtons, tabPanels } from "./dom.js";

export const usageMetrics = [
  ["tokens_total", "Total Tokens"],
  ["tokens_input", "Input"],
  ["tokens_output", "Output"],
  ["tokens_reasoning", "Reasoning"],
  ["tokens_cache_read", "Cache Read"],
  ["tokens_cache_write", "Cache Write"],
];

export function setTab(target) {
  tabButtons.forEach((button) => button.classList.toggle("active", button.dataset.tabTarget === target));
  tabPanels.forEach((panel) => panel.classList.toggle("active", panel.id === target));
}

export function setMessage(node, message = "", isError = false) {
  node.textContent = message;
  node.style.color = isError ? "var(--text)" : "var(--muted)";
}

export function isValidTradeDate(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value);
}

export function statusClass(status) {
  return `status-pill status-${status || "queued"}`;
}

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function formatNumber(value) {
  return new Intl.NumberFormat("en-US").format(Number(value || 0));
}

export function formatDecimal(value) {
  const numeric = Number(value || 0);
  return numeric ? numeric.toFixed(6).replace(/0+$/, "").replace(/\.$/, "") : "0";
}

export function formatDateTime(value) {
  if (!value) {
    return "n/a";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleString();
}

export function formatDuration(durationMs) {
  const totalSeconds = Math.max(0, Math.round(Number(durationMs || 0) / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes ? `${minutes}m ${seconds}s` : `${seconds}s`;
}
