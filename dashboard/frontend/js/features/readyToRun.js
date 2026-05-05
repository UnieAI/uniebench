import { requestJson } from "../core/api.js";
import { escapeHtml, setStatus } from "../core/ui.js";
import { t } from "../core/i18n.js";

let readySaveTimer = null;
let suppressReadySave = false;
let readyItemsCollapsed = true;
let readyItemsCount = 0;

function getInput(id) {
  const el = document.getElementById(id);
  return el instanceof HTMLInputElement ? el : null;
}

function getSelect(id) {
  const el = document.getElementById(id);
  return el instanceof HTMLSelectElement ? el : null;
}

function setSheetOptions(options, selectedValue) {
  const selectEl = getSelect("readySheetNameSelect");
  if (!selectEl) return;
  const values = Array.isArray(options) ? options.map((v) => String(v).trim()).filter(Boolean) : [];
  selectEl.innerHTML = values.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("");
  if (selectedValue && values.includes(selectedValue)) {
    selectEl.value = selectedValue;
  } else if (values.length > 0) {
    selectEl.value = values[0];
  }
}

function payloadFromForm() {
  return {
    test_name: getInput("readyTestNameInput")?.value.trim() || "",
    sheet_name: getSelect("readySheetNameSelect")?.value || "",
    platform_name: getInput("readyPlatformNameInput")?.value.trim() || "",
  };
}

function renderReadyItems(items) {
  const listEl = document.getElementById("readyItemsList");
  const badgeEl = document.getElementById("readyItemsCountBadge");
  if (!listEl) return;
  const rows = Array.isArray(items) ? items : [];
  readyItemsCount = rows.length;
  if (badgeEl) badgeEl.textContent = String(readyItemsCount);
  if (rows.length === 0) {
    listEl.innerHTML = `<div class="ready-empty">${escapeHtml(t("readyItemsEmpty"))}</div>`;
    return;
  }
  listEl.innerHTML = rows.map((row) => `<div class="ready-item-row">${escapeHtml(String(row))}</div>`).join("");
}

function renderReadyItemsCollapse() {
  const wrapEl = document.getElementById("readyItemsListWrap");
  const toggleBtn = document.getElementById("readyItemsToggleBtn");
  if (!wrapEl || !toggleBtn) return;
  wrapEl.classList.toggle("collapsed", readyItemsCollapsed);
  toggleBtn.classList.toggle("collapsed", readyItemsCollapsed);
  toggleBtn.setAttribute(
    "aria-label",
    readyItemsCollapsed
      ? t("readyItemsExpandAria", { count: readyItemsCount })
      : t("readyItemsCollapseAria", { count: readyItemsCount }),
  );
}

function openReadyRunPopup() {
  const popup = document.getElementById("readyRunPopup");
  const pre = document.getElementById("readyRunCommandOutput");
  if (!popup || !pre) return;
  pre.textContent = "REPO_ROOT=\"$(git rev-parse --show-toplevel 2>/dev/null || pwd)\" && cd \"$REPO_ROOT\" && uv venv .venv.autotest && . .venv.autotest/bin/activate && uv pip install -r requirements.txt && python main.py";
  popup.classList.remove("hidden");
}

function closeReadyRunPopup() {
  const popup = document.getElementById("readyRunPopup");
  if (!popup) return;
  popup.classList.add("hidden");
}

export async function loadReadyItems() {
  try {
    const { ok, status, data } = await requestJson("/api/config/ready-items");
    if (!ok) throw new Error(data.detail || status);
    renderReadyItems(data.items || []);
    renderReadyItemsCollapse();
  } catch {
    renderReadyItems([]);
    renderReadyItemsCollapse();
  }
}

async function saveReadyMetaNow() {
  const payload = payloadFromForm();
  try {
    const { ok, status, data } = await requestJson("/api/config/test-meta", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!ok) throw new Error(data.detail || status);
    setStatus("readyStatus", t("statusReadyMetaSaved"), "ok");
    await loadReadyItems();
  } catch (err) {
    setStatus("readyStatus", t("statusReadyMetaSaveFail", { reason: err }), "err");
  }
}

function saveReadyMetaDebounced() {
  if (suppressReadySave) return;
  if (readySaveTimer !== null) {
    window.clearTimeout(readySaveTimer);
  }
  readySaveTimer = window.setTimeout(() => {
    readySaveTimer = null;
    void saveReadyMetaNow();
  }, 350);
}

export async function loadReadyToRun() {
  try {
    const { ok, status, data } = await requestJson("/api/config/test-meta");
    if (!ok) throw new Error(data.detail || status);
    suppressReadySave = true;
    const testName = getInput("readyTestNameInput");
    const platformName = getInput("readyPlatformNameInput");
    if (testName) testName.value = String(data.test_name || "");
    if (platformName) platformName.value = String(data.platform_name || "");
    setSheetOptions(data.sheet_name_options || [], String(data.sheet_name || ""));
    suppressReadySave = false;
    setStatus("readyStatus", t("statusReadyLoaded"), "ok");
  } catch (err) {
    suppressReadySave = false;
    setStatus("readyStatus", t("statusReadyLoadFail", { reason: err }), "err");
  }
  await loadReadyItems();
}

export function initReadyToRunFeature() {
  const testName = getInput("readyTestNameInput");
  const sheetName = getSelect("readySheetNameSelect");
  const platformName = getInput("readyPlatformNameInput");
  const toggleBtn = document.getElementById("readyItemsToggleBtn");
  const runBtn = document.getElementById("readyRunBtn");
  const closeRunPopupBtn = document.getElementById("closeReadyRunPopupBtn");
  if (!testName || !sheetName || !platformName || !toggleBtn || !runBtn || !closeRunPopupBtn) return;

  testName.addEventListener("input", saveReadyMetaDebounced);
  platformName.addEventListener("input", saveReadyMetaDebounced);
  sheetName.addEventListener("change", () => {
    void saveReadyMetaNow();
  });

  toggleBtn.addEventListener("click", () => {
    readyItemsCollapsed = !readyItemsCollapsed;
    renderReadyItemsCollapse();
  });

  runBtn.addEventListener("click", openReadyRunPopup);
  closeRunPopupBtn.addEventListener("click", closeReadyRunPopup);
  renderReadyItemsCollapse();
}
