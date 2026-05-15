import { providerGroups } from "./dom.js?v=portfolio-tab-5";
import { state } from "./state.js?v=portfolio-tab-5";

export function updateModelDefault(groupName, providerValue) {
  const group = providerGroups[groupName];
  const provider = state.providerOptions.find((item) => item.value === providerValue);
  if (!group || !provider) {
    return;
  }

  group.providerFields.classList.remove("hidden");
  group.quickInput.value = provider.default_quick_model || "";
  group.deepInput.value = provider.default_deep_model || "";
  group.quickInput.placeholder = provider.note || "Quick think model";
  group.deepInput.placeholder = provider.note || "Deep think model";
}

export function renderProviders() {
  Object.entries(providerGroups).forEach(([groupName, group]) => {
    group.select.innerHTML = state.providerOptions
      .map((provider) => `<option value="${provider.value}">${provider.label}</option>`)
      .join("");
    group.select.value = state.providerOptions[0]?.value || "opencode";
    updateModelDefault(groupName, group.select.value);
  });
}

export function providerPayload(groupName) {
  const group = providerGroups[groupName];
  return {
    provider: group.select.value,
    quick_model: group.quickInput.value.trim(),
    deep_model: group.deepInput.value.trim(),
  };
}

export async function loadProviders() {
  try {
    const response = await fetch("/api/providers");
    const payload = await response.json();
    state.providerOptions = payload.providers || [];
  } catch (error) {
    state.providerOptions = [{ label: "OpenCode", value: "opencode", default_deep_model: "", default_quick_model: "" }];
  }
  renderProviders();
}
