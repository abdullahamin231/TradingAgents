import { onDemandDateInput, onDemandMessage, onDemandSubmitButton, onDemandTickerInput } from "./dom.js?v=portfolio-tab-5";
import { fetchJobs } from "./jobs.js?v=portfolio-tab-5";
import { loadTickers } from "./reports.js?v=portfolio-tab-5";
import { providerPayload } from "./providers.js?v=portfolio-tab-5";
import { isValidTradeDate, setMessage } from "./utils.js?v=portfolio-tab-5";

export async function submitOnDemandRun() {
  const tradeDate = onDemandDateInput.value.trim();
  const ticker = onDemandTickerInput.value.trim();
  if (!isValidTradeDate(tradeDate)) {
    setMessage(onDemandMessage, "Date must use YYYY-MM-DD.", true);
    return;
  }
  if (!ticker) {
    setMessage(onDemandMessage, "Enter one ticker.", true);
    return;
  }

  onDemandSubmitButton.disabled = true;
  setMessage(onDemandMessage, "");
  try {
    const response = await fetch("/api/on-demand/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ticker,
        trade_date: tradeDate,
        ...providerPayload("on-demand"),
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      setMessage(onDemandMessage, payload.detail || "Run submission failed.", true);
      return;
    }
    setMessage(onDemandMessage, `Queued ${ticker.toUpperCase()} for ${tradeDate}.`);
    await fetchJobs();
    await loadTickers();
  } finally {
    onDemandSubmitButton.disabled = false;
  }
}
