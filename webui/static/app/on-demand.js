import { onDemandDateInput, onDemandMessage, onDemandSubmitButton, onDemandTickerInput } from "./dom.js";
import { fetchJobs } from "./jobs.js";
import { loadTickers } from "./reports.js";
import { providerPayload } from "./providers.js";
import { isValidTradeDate, setMessage } from "./utils.js";

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
