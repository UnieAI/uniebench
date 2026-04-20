import { requestJson } from "../core/api.js";
import { t } from "../core/i18n.js";
import { escapeHtml, setStatus } from "../core/ui.js";

let modelNames = [];
let globalSaveTimer = null;
let suppressAutoSave = false;

function normalizeModelNames(values) {
  if (!Array.isArray(values)) return [];
  const seen = new Set();
  const out = [];
  values.forEach((value) => {
    const text = String(value || "").trim();
    if (!text || seen.has(text)) return;
    seen.add(text);
    out.push(text);
  });
  return out;
}

function renderModelNameList() {
  const root = document.getElementById("globalModelNameList");
  if (!root) return;
  if (!modelNames.length) {
    root.innerHTML = `<div class="hint">${escapeHtml(t("globalModelNamesEmpty"))}</div>`;
    return;
  }

  root.innerHTML = modelNames
    .map((name) => {
      const safe = escapeHtml(name);
      return `<div class="global-model-chip"><span title="${safe}">${safe}</span><button class="action danger model-remove-btn" data-name="${safe}">${escapeHtml(t("btnRemove"))}</button></div>`;
    })
    .join("");
}

function getValue(id) {
  const el = document.getElementById(id);
  return el instanceof HTMLInputElement ? el.value.trim() : "";
}

function setValue(id, value) {
  const el = document.getElementById(id);
  if (!(el instanceof HTMLInputElement)) return;
  el.value = String(value || "");
}

function onAddModelName() {
  const input = document.getElementById("globalModelNameInput");
  if (!(input instanceof HTMLInputElement)) return;
  const name = input.value.trim();
  if (!name) return;
  modelNames = normalizeModelNames([...modelNames, name]);
  input.value = "";
  renderModelNameList();
  scheduleGlobalConfigSave();
}

function onModelListClick(event) {
  const target = event.target;
  if (!(target instanceof HTMLButtonElement)) return;
  if (!target.classList.contains("model-remove-btn")) return;
  const name = target.dataset.name || "";
  modelNames = modelNames.filter((item) => item !== name);
  renderModelNameList();
  scheduleGlobalConfigSave();
}

export async function discoverGlobalModelNames() {
  try {
    const modelPath = getValue("globalModelPath");
    const params = new URLSearchParams({ model_path: modelPath });
    const { ok, status, data } = await requestJson(`/api/global-config/discover-model-names?${params.toString()}`);
    if (!ok) {
      throw new Error(data.detail || status);
    }
    modelNames = normalizeModelNames(data.model_names || []);
    renderModelNameList();
    setStatus("globalConfigStatus", t("statusGlobalConfigDiscovered", { count: modelNames.length, path: data.model_path || modelPath }), "ok");
    await saveGlobalConfig();
  } catch (err) {
    setStatus("globalConfigStatus", t("statusGlobalConfigDiscoverFail", { reason: err }), "err");
  }
}

export async function loadGlobalConfig() {
  const modelPath = document.getElementById("globalModelPath");
  if (!(modelPath instanceof HTMLInputElement)) return;

  try {
    const { ok, status, data } = await requestJson("/api/global-config");
    if (!ok) {
      throw new Error(data.detail || status);
    }
    suppressAutoSave = true;
    setValue("globalModelPath", data.model_path || "");
    setValue("globalDefaultBaseUrl", data.default_base_url || "");
    modelNames = normalizeModelNames(data.model_names || []);
    renderModelNameList();
    suppressAutoSave = false;
    setStatus("globalConfigStatus", t("statusGlobalConfigLoaded", { time: data.time }), "ok");
  } catch (err) {
    suppressAutoSave = false;
    setStatus("globalConfigStatus", t("statusGlobalConfigLoadFail", { reason: err }), "err");
  }
}

export async function saveGlobalConfig() {
  try {
    const payload = {
      model_path: getValue("globalModelPath"),
      default_base_url: getValue("globalDefaultBaseUrl"),
      model_names: normalizeModelNames(modelNames),
    };
    const { ok, status, data } = await requestJson("/api/global-config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!ok) {
      throw new Error(data.detail || status);
    }
    modelNames = normalizeModelNames(data.model_names || payload.model_names);
    renderModelNameList();
    setStatus("globalConfigStatus", t("statusGlobalConfigSaved", { time: data.time }), "ok");
  } catch (err) {
    setStatus("globalConfigStatus", t("statusGlobalConfigSaveFail", { reason: err }), "err");
  }
}

function scheduleGlobalConfigSave() {
  if (suppressAutoSave) return;
  if (globalSaveTimer !== null) {
    window.clearTimeout(globalSaveTimer);
  }
  globalSaveTimer = window.setTimeout(() => {
    globalSaveTimer = null;
    void saveGlobalConfig();
  }, 350);
}

export function initGlobalConfigFeature() {
  const loadBtn = document.getElementById("loadGlobalConfig");
  const discoverBtn = document.getElementById("discoverGlobalModelNames");
  const addBtn = document.getElementById("addGlobalModelName");
  const modelInput = document.getElementById("globalModelNameInput");
  const modelPathInput = document.getElementById("globalModelPath");
  const defaultBaseUrlInput = document.getElementById("globalDefaultBaseUrl");
  const list = document.getElementById("globalModelNameList");
  if (!loadBtn || !discoverBtn || !addBtn || !modelInput || !modelPathInput || !defaultBaseUrlInput || !list) return;

  loadBtn.addEventListener("click", loadGlobalConfig);
  discoverBtn.addEventListener("click", discoverGlobalModelNames);
  addBtn.addEventListener("click", onAddModelName);
  modelPathInput.addEventListener("input", scheduleGlobalConfigSave);
  defaultBaseUrlInput.addEventListener("input", scheduleGlobalConfigSave);
  modelInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      onAddModelName();
    }
  });
  list.addEventListener("click", onModelListClick);
}
