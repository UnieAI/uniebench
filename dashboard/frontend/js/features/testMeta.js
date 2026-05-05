import { requestJson } from "../core/api.js";

let saveTimer = null;

function getInput(id) {
  const el = document.getElementById(id);
  return el instanceof HTMLInputElement ? el : null;
}

function getSelect(id) {
  const el = document.getElementById(id);
  return el instanceof HTMLSelectElement ? el : null;
}

function currentPayload() {
  return {
    test_name: getInput("testNameInput")?.value.trim() || "",
    sheet_name: getSelect("sheetNameSelect")?.value || "",
    platform_name: getInput("platformNameInput")?.value.trim() || "",
  };
}

function setSheetOptions(options, selectedValue) {
  const selectEl = getSelect("sheetNameSelect");
  if (!selectEl) return;
  const list = Array.isArray(options) ? options.map((v) => String(v).trim()).filter(Boolean) : [];
  selectEl.innerHTML = "";
  list.forEach((name) => {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    selectEl.appendChild(option);
  });
  if (selectedValue && list.includes(selectedValue)) {
    selectEl.value = selectedValue;
  } else if (list.length > 0) {
    selectEl.value = list[0];
  }
}

async function saveTestMetaNow() {
  const payload = currentPayload();
  try {
    await requestJson("/api/config/test-meta", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {
    // Keep silent here to avoid noisy UI status collisions with tab status blocks.
  }
}

function saveTestMetaDebounced() {
  if (saveTimer !== null) {
    window.clearTimeout(saveTimer);
  }
  saveTimer = window.setTimeout(() => {
    saveTimer = null;
    void saveTestMetaNow();
  }, 350);
}

export async function loadTestMeta() {
  try {
    const { ok, status, data } = await requestJson("/api/config/test-meta");
    if (!ok) {
      throw new Error(data.detail || status);
    }
    const testName = getInput("testNameInput");
    const platformName = getInput("platformNameInput");
    if (testName) testName.value = String(data.test_name || "");
    if (platformName) platformName.value = String(data.platform_name || "");
    setSheetOptions(data.sheet_name_options || [], String(data.sheet_name || ""));
  } catch {
    setSheetOptions([], "");
  }
}

export function initTestMetaFeature() {
  const testName = getInput("testNameInput");
  const platformName = getInput("platformNameInput");
  const sheetName = getSelect("sheetNameSelect");
  if (!testName || !platformName || !sheetName) return;

  testName.addEventListener("input", saveTestMetaDebounced);
  platformName.addEventListener("input", saveTestMetaDebounced);
  sheetName.addEventListener("change", () => {
    void saveTestMetaNow();
  });
}
