import { requestJson } from "../core/api.js";
import { t } from "../core/i18n.js";
import { escapeHtml, setStatus } from "../core/ui.js";

const TEST_STATUS_POLL_MS = 1500;
const SCRIPT_AUTOSAVE_MS = 800;

let scriptListData = [];
let selectedScriptPath = "";
let selectedScriptName = "";
let selectedScriptGroup = "default";
let scriptsDir = "";
let runtimeServerGroupId = "";
let selectedScriptMeta = { tp_size: "", model_name: "", model_id: "", base_url: "", port: "" };
let scriptModelNameOptions = [];

let testStatusPollTimer = null;
let testState = null;
let lastEndpointUrl = "http://localhost:8000";
let hostTestResultText = "";
let hostTestCommand = "";
let hostTestDecodedResult = null;
let scriptAutoSaveTimer = null;
let isScriptSaving = false;

function defaultScriptTemplate() {
  return "#!/bin/bash\nset -euo pipefail\n\n";
}

function detectDefaultPortFromScriptContent(content) {
  const text = String(content || "");
  const re = /--port(?:\s+|=)(\d+)/g;
  let match;
  let port = "8000";
  while (true) {
    match = re.exec(text);
    if (!match) break;
    port = match[1];
  }
  return port;
}

function applyDefaultEndpointFromScriptContent(content) {
  const port = detectDefaultPortFromScriptContent(content);
  const endpoint = `http://localhost:${port}`;
  lastEndpointUrl = endpoint;
  const endpointInput = getPopupEndpointInput();
  if (endpointInput) {
    endpointInput.value = endpoint;
  }
}

function encodeScriptPath(path) {
  return String(path || "")
    .split("/")
    .map((seg) => encodeURIComponent(seg))
    .join("/");
}

function normalizeScriptMeta(raw) {
  const data = raw && typeof raw === "object" ? raw : {};
  return {
    tp_size: String(data.tp_size || "").trim(),
    model_name: String(data.model_name || "").trim(),
    model_id: String(data.model_id || "").trim(),
    base_url: String(data.base_url || "").trim(),
    port: String(data.port || "").trim(),
  };
}

function getMetaInput(id) {
  const el = document.getElementById(id);
  return el instanceof HTMLInputElement ? el : null;
}

function renderScriptMetaForm() {
  const tpEl = getMetaInput("scriptMetaTpSize");
  const modelNameEl = getMetaInput("scriptMetaModelName");
  const modelIdEl = getMetaInput("scriptMetaModelId");
  const baseUrlEl = getMetaInput("scriptMetaBaseUrl");
  const portEl = getMetaInput("scriptMetaPort");
  if (!tpEl || !modelNameEl || !modelIdEl || !baseUrlEl || !portEl) return;

  const meta = normalizeScriptMeta(selectedScriptMeta);
  tpEl.value = meta.tp_size;
  modelNameEl.value = meta.model_name;
  modelIdEl.value = meta.model_id;
  baseUrlEl.value = meta.base_url;
  portEl.value = meta.port;
}

function collectScriptMetaForm() {
  return normalizeScriptMeta({
    tp_size: getMetaInput("scriptMetaTpSize")?.value,
    model_name: getMetaInput("scriptMetaModelName")?.value,
    model_id: getMetaInput("scriptMetaModelId")?.value,
    base_url: getMetaInput("scriptMetaBaseUrl")?.value,
    port: getMetaInput("scriptMetaPort")?.value,
  });
}

function getScriptEditorContent() {
  const editor = document.getElementById("scriptEditor");
  if (!(editor instanceof HTMLTextAreaElement)) return "";
  return editor.value || "";
}

function stripWrappedQuotes(token) {
  const text = String(token || "").trim();
  if (!text) return "";
  if ((text.startsWith('"') && text.endsWith('"')) || (text.startsWith("'") && text.endsWith("'"))) {
    return text.slice(1, -1).trim();
  }
  return text;
}

function findLastMatchGroup(text, regex, groupIndex = 1) {
  let match;
  let value = "";
  while (true) {
    match = regex.exec(text);
    if (!match) break;
    value = String(match[groupIndex] || "");
  }
  return stripWrappedQuotes(value);
}

function extractServeTarget(scriptContent) {
  const text = String(scriptContent || "");
  const target = findLastMatchGroup(text, /\bserve\s+("[^"]+"|'[^']+'|[^\s|&;]+)/g, 1);
  return stripWrappedQuotes(target);
}

function extractModelNameFromServeTarget(serveTarget) {
  const clean = String(serveTarget || "").trim().replace(/\/+$/, "");
  if (!clean) return "";
  const parts = clean.split("/").filter(Boolean);
  if (parts.length >= 2) {
    return `${parts[parts.length - 2]}/${parts[parts.length - 1]}`;
  }
  return parts[0] || clean;
}

function detectMetaFromScriptContent(scriptContent) {
  const text = String(scriptContent || "");
  const serveTarget = extractServeTarget(text);
  const servedModelName = findLastMatchGroup(text, /--served-model-name(?:\s+|=)("[^"]+"|'[^']+'|[^\s|&;]+)/g, 1);
  const tpSize = findLastMatchGroup(text, /--(?:tp-size|tp)(?:\s+|=)([^\s|&;]+)/g, 1);
  const port = detectDefaultPortFromScriptContent(text);

  return {
    tp_size: tpSize || "1",
    model_name: extractModelNameFromServeTarget(serveTarget),
    model_id: servedModelName || serveTarget,
    base_url: "http://localhost",
    port: port || "8000",
  };
}

function renderScriptModelNameOptions() {
  const datalist = document.getElementById("scriptModelNameOptions");
  if (!(datalist instanceof HTMLDataListElement)) return;
  datalist.innerHTML = scriptModelNameOptions
    .map((name) => `<option value="${escapeHtml(name)}"></option>`)
    .join("");
}

async function refreshScriptModelNameOptions() {
  try {
    const { ok, status, data } = await requestJson("/api/global-config");
    if (!ok) {
      throw new Error(data.detail || status);
    }
    scriptModelNameOptions = Array.isArray(data.model_names)
      ? data.model_names.map((v) => String(v || "").trim()).filter((v) => v.length > 0)
      : [];
  } catch {
    scriptModelNameOptions = [];
  }
  renderScriptModelNameOptions();
}

function normalizeLastTest(raw) {
  if (!raw || typeof raw !== "object") {
    return { status: "untested", tested_at: "", detail: "" };
  }
  const status = raw.status === "success" || raw.status === "fail" ? raw.status : "untested";
  return {
    status,
    tested_at: raw.tested_at ? String(raw.tested_at) : "",
    detail: raw.detail ? String(raw.detail) : "",
  };
}

function normalizeScriptItem(raw) {
  const path = raw?.path ? String(raw.path) : "";
  const group = raw?.group ? String(raw.group) : (path.includes("/") ? path.split("/")[0] : "default");
  const name = raw?.name ? String(raw.name) : (path.split("/").pop() || "");
  return {
    name,
    path,
    group,
    enabled: Boolean(raw?.enabled),
    last_test: normalizeLastTest(raw?.last_test),
  };
}

function formatTestedAt(isoText) {
  if (!isoText) return "--";
  const d = new Date(isoText);
  if (Number.isNaN(d.getTime())) return isoText;
  return d.toLocaleString();
}

function getGroupNames() {
  const names = new Set(scriptListData.map((item) => item.group));
  if (!names.has("default")) names.add("default");
  return Array.from(names).sort((a, b) => a.localeCompare(b));
}

function setSelectOptions(selectEl, selectedValue) {
  if (!selectEl) return;
  const groups = getGroupNames();
  selectEl.innerHTML = groups.map((group) => `<option value="${escapeHtml(group)}">${escapeHtml(group)}</option>`).join("");
  const target = selectedValue && groups.includes(selectedValue) ? selectedValue : groups[0];
  if (target) selectEl.value = target;
}

function renderGroupSelectors() {
  const createSelect = document.getElementById("createScriptGroupSelect");
  const moveSelect = document.getElementById("moveScriptGroupSelect");
  setSelectOptions(createSelect, selectedScriptGroup || "default");
  setSelectOptions(moveSelect, selectedScriptGroup || "default");
}

function showCreateScriptPopup() {
  const popup = document.getElementById("createScriptPopup");
  if (!popup) return;
  renderGroupSelectors();
  const input = document.getElementById("newScriptName");
  if (input instanceof HTMLInputElement) {
    input.value = "";
    window.setTimeout(() => input.focus(), 0);
  }
  popup.classList.remove("hidden");
}

function hideCreateScriptPopup() {
  const popup = document.getElementById("createScriptPopup");
  if (!popup) return;
  popup.classList.add("hidden");
}

function showMoveScriptPopup() {
  if (!selectedScriptPath) {
    setStatus("scriptsStatus", t("statusScriptMoveNeedSelect"), "err");
    return;
  }
  const popup = document.getElementById("moveScriptPopup");
  if (!popup) return;
  renderGroupSelectors();
  const input = document.getElementById("moveScriptGroupInput");
  if (input instanceof HTMLInputElement) {
    input.value = "";
    window.setTimeout(() => input.focus(), 0);
  }
  popup.classList.remove("hidden");
}

function hideMoveScriptPopup() {
  const popup = document.getElementById("moveScriptPopup");
  if (!popup) return;
  popup.classList.add("hidden");
}

function renderRuntimeServerGroupSelect() {
  const selectEl = document.getElementById("runtimeServerGroupSelect");
  if (!(selectEl instanceof HTMLSelectElement)) return;
  const groups = getGroupNames();
  selectEl.innerHTML = groups
    .map((group) => `<option value="${escapeHtml(group)}">${escapeHtml(group)}</option>`)
    .join("");
  const target = runtimeServerGroupId && groups.includes(runtimeServerGroupId)
    ? runtimeServerGroupId
    : (groups[0] || "default");
  runtimeServerGroupId = target;
  if (target) {
    selectEl.value = target;
  }
}

async function loadRuntimeTargetServerGroup() {
  try {
    const { ok, status, data } = await requestJson("/api/config/runtime-target");
    if (!ok) {
      throw new Error(data.detail || status);
    }
    runtimeServerGroupId = String(data.server_id || "").trim();
  } catch {
    runtimeServerGroupId = "";
  }
  renderRuntimeServerGroupSelect();
}

async function saveRuntimeServerGroup(groupId) {
  const value = String(groupId || "").trim();
  if (!value) return;
  try {
    const { ok, status, data } = await requestJson("/api/config/runtime-target", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ server_id: value }),
    });
    if (!ok) {
      throw new Error(data.detail || status);
    }
    runtimeServerGroupId = String(data.server_id || value).trim() || value;
    renderRuntimeServerGroupSelect();
    setStatus("scriptsStatus", t("statusRuntimeServerGroupSaved", { id: runtimeServerGroupId }), "ok");
  } catch (err) {
    setStatus("scriptsStatus", t("statusRuntimeServerGroupSaveFail", { reason: err }), "err");
    renderRuntimeServerGroupSelect();
  }
}

function isStepStatus(value) {
  return value === "testing" || value === "success" || value === "fail";
}

function statusToLabel(status) {
  if (status === "success") return t("testStateSuccess");
  if (status === "fail") return t("testStateFail");
  return t("testStateTesting");
}

function normalizeStep(step) {
  if (!step || typeof step !== "object") {
    return { status: "testing", detail: "" };
  }
  const status = isStepStatus(step.status) ? step.status : "testing";
  return {
    status,
    detail: step.detail ? String(step.detail) : "",
  };
}

function normalizeLogs(logs) {
  if (!Array.isArray(logs)) return [];
  return logs.map((line) => String(line));
}

function normalizeIncomingTestState(data) {
  if (!data || !data.has_test) return null;

  const steps = data.steps || {};
  return {
    has_test: true,
    active: Boolean(data.active),
    script_name: data.script_name ? String(data.script_name) : "",
    endpoint_url: data.endpoint_url ? String(data.endpoint_url) : "",
    pid: data.pid === null || data.pid === undefined ? null : Number(data.pid),
    overall_status: data.overall_status ? String(data.overall_status) : "testing",
    overall_detail: data.overall_detail ? String(data.overall_detail) : "",
    updated_at: data.updated_at ? String(data.updated_at) : "",
    finished_at: data.finished_at ? String(data.finished_at) : "",
    steps: {
      health: normalizeStep(steps.health),
      models: normalizeStep(steps.models),
      completions: normalizeStep(steps.completions),
    },
    logs: normalizeLogs(data.logs),
  };
}

function popupOverallText() {
  if (!testState) return "--";
  if (testState.active) return testState.overall_detail || t("testStateTesting");

  if (testState.overall_status === "success") return t("statusScriptTestDoneSuccess");
  if (testState.overall_status === "stopped") return t("statusScriptTestDoneStopped");
  if (testState.overall_status === "timeout") return t("statusScriptTestDoneTimeout");
  if (testState.overall_status === "fail") return t("statusScriptTestDoneFail");
  return testState.overall_detail || "--";
}

function renderScriptDirHint() {
  const el = document.getElementById("scriptsDirHint");
  if (!el) return;
  el.textContent = scriptsDir ? t("scriptsDirLabel", { dir: scriptsDir }) : "--";
}

function updateScriptEditorHint() {
  const hint = document.getElementById("scriptEditorHint");
  if (!hint) return;

  if (selectedScriptPath) {
    hint.textContent = t("scriptEditingPath", { name: selectedScriptName || selectedScriptPath, path: selectedScriptPath });
  } else {
    hint.textContent = t("scriptEditorHint");
  }
}

function autoDetectAllScriptMeta() {
  const detected = detectMetaFromScriptContent(getScriptEditorContent());
  selectedScriptMeta = normalizeScriptMeta(detected);
  renderScriptMetaForm();
  setStatus("scriptsStatus", t("statusScriptAutoDetectAppliedAll"), "ok");
  scheduleScriptAutoSave();
}

function scheduleScriptAutoSave() {
  if (!selectedScriptPath) return;
  if (scriptAutoSaveTimer !== null) {
    window.clearTimeout(scriptAutoSaveTimer);
  }
  scriptAutoSaveTimer = window.setTimeout(() => {
    scriptAutoSaveTimer = null;
    void saveScript({ quiet: true, refreshAfter: false });
  }, SCRIPT_AUTOSAVE_MS);
}

function renderScriptList() {
  const listEl = document.getElementById("scriptList");
  if (!listEl) return;

  if (!scriptListData.length) {
    listEl.innerHTML = `<div class="hint">${t("scriptsNone")}</div>`;
    return;
  }

  const grouped = new Map();
  scriptListData.forEach((item) => {
    if (!grouped.has(item.group)) grouped.set(item.group, []);
    grouped.get(item.group).push(item);
  });

  const sections = Array.from(grouped.keys())
    .sort((a, b) => a.localeCompare(b))
    .map((group) => {
      const scripts = grouped.get(group) || [];
      const rows = scripts.map((item) => {
        const path = item.path;
        const pathKey = encodeURIComponent(path);
        const active = selectedScriptPath === path ? "active" : "";
        const lastTest = normalizeLastTest(item.last_test);
        const chipClass = `test-chip ${lastTest.status}`;
        const chipText = lastTest.status === "success"
          ? t("scriptVerified")
          : lastTest.status === "fail"
            ? t("scriptVerifyFailed")
            : t("scriptUntested");
        const chipTooltip = t("scriptLastTestTimeTooltip", { time: formatTestedAt(lastTest.tested_at) });

        return `
          <div class="script-item ${active}" data-path="${pathKey}">
            <div class="script-name-row-wrap">
              <div class="script-name-row" title="${escapeHtml(path)}">${escapeHtml(item.name)}</div>
              <span class="${chipClass}" title="${escapeHtml(chipTooltip)}">${escapeHtml(chipText)}</span>
            </div>
            <div class="script-toggle-row">
              <label>
                <input type="checkbox" class="script-enable" data-path="${pathKey}" ${item.enabled ? "checked" : ""}>
                ${t("scriptEnable")}
              </label>
            </div>
          </div>
        `;
      }).join("");

      return `
        <div class="script-group">
          <div class="script-group-title">${escapeHtml(group)}</div>
          <div class="script-group-list">${rows}</div>
        </div>
      `;
    }).join("");

  listEl.innerHTML = sections;
}

function getPopupEndpointInput() {
  return document.getElementById("popupScriptTestEndpoint");
}

function showTestPopup() {
  const popup = document.getElementById("scriptTestPopup");
  if (!popup) return;
  popup.classList.remove("hidden");
}

function hideTestPopup() {
  const popup = document.getElementById("scriptTestPopup");
  if (!popup) return;
  popup.classList.add("hidden");
}

function getHostTestEndpointInput() {
  return document.getElementById("hostTestEndpointInput");
}

function showHostTestPopup() {
  const popup = document.getElementById("hostTestPopup");
  if (!popup) return;
  popup.classList.remove("hidden");
}

function hideHostTestPopup() {
  const popup = document.getElementById("hostTestPopup");
  if (!popup) return;
  popup.classList.add("hidden");
}

function buildFallbackHostCommand() {
  const fallbackPath = "/workspace/jeff/Benchmark-Autotest/services/__test__/test.sh";
  return `bash ${fallbackPath}`;
}

function renderHostTestPopup() {
  const endpointInput = getHostTestEndpointInput();
  if (endpointInput) {
    if (!endpointInput.value) endpointInput.value = lastEndpointUrl;
  }

  const commandEl = document.getElementById("hostTestCommandOutput");
  if (commandEl) {
    commandEl.textContent = hostTestCommand || buildFallbackHostCommand();
  }

  const resultInput = document.getElementById("hostTestResultInput");
  if (resultInput instanceof HTMLTextAreaElement) {
    resultInput.value = hostTestResultText;
  }

  const resultEchoEl = document.getElementById("hostTestResultEcho");
  if (resultEchoEl) {
    if (!hostTestResultText.trim()) {
      resultEchoEl.textContent = "--";
      resultEchoEl.className = "hint";
      return;
    }

    if (hostTestDecodedResult && hostTestDecodedResult.status === "PASS") {
      const reason = hostTestDecodedResult.reason || "ok";
      resultEchoEl.textContent = `${t("hostTestResultSuccess")} (${reason})`;
      resultEchoEl.className = "hint host-result success";
      return;
    }
    if (hostTestDecodedResult && hostTestDecodedResult.status === "FAIL") {
      const reason = hostTestDecodedResult.reason || "unknown";
      resultEchoEl.textContent = `${t("hostTestResultFail")} (${reason})`;
      resultEchoEl.className = "hint host-result fail";
      return;
    }
    resultEchoEl.textContent = t("hostTestResultInvalid");
    resultEchoEl.className = "hint host-result fail";
  }
}

function decodeHostResult(rawText) {
  const text = String(rawText || "").trim();
  if (!text) {
    throw new Error(t("statusHostTestResultEmpty"));
  }

  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);

  const targetLine = lines.find((line) => line.includes("HOST_TEST_RESULT_B64=")) || "";
  if (!targetLine) {
    throw new Error(t("statusHostTestResultFormatInvalid"));
  }

  const match = targetLine.match(/HOST_TEST_RESULT_B64=([A-Za-z0-9+/=_-]+)/);
  if (!match || !match[1]) {
    throw new Error(t("statusHostTestResultFormatInvalid"));
  }

  let parsed;
  try {
    const b64 = match[1];
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
      bytes[i] = binary.charCodeAt(i);
    }
    const jsonText = new TextDecoder("utf-8").decode(bytes);
    parsed = JSON.parse(jsonText);
  } catch {
    throw new Error(t("statusHostTestResultDecodeFail"));
  }

  const statusRaw = String(parsed?.status || "").trim().toUpperCase();
  const status = statusRaw === "PASS" ? "PASS" : "FAIL";
  const result = {
    status,
    reason: String(parsed?.reason || "").trim(),
    log_file: String(parsed?.log_file || "").trim(),
    endpoint: String(parsed?.endpoint || "").trim(),
    script: String(parsed?.script || "").trim(),
  };
  return result;
}

function setPopupActionButtonsByTestState() {
  const startBtn = document.getElementById("popupStartTestScriptBtn");
  const stopBtn = document.getElementById("popupStopTestScriptBtn");
  if (!startBtn || !stopBtn) return;

  const active = Boolean(testState && testState.active);
  startBtn.disabled = active;
  stopBtn.disabled = !active;
}

function updatePopupStep(stepKey, elementId) {
  const el = document.getElementById(elementId);
  if (!el) return;

  const step = testState?.steps?.[stepKey] || { status: "testing", detail: "" };
  el.className = `test-step-state ${step.status}`;
  el.textContent = statusToLabel(step.status);
}

function renderPopupLogs() {
  const logEl = document.getElementById("testLogOutput");
  if (!logEl) return;

  const logs = Array.isArray(testState?.logs) ? testState.logs : [];
  if (logs.length === 0) {
    logEl.textContent = t("testNoLogs");
    return;
  }
  logEl.textContent = logs.join("\n");
  logEl.scrollTop = logEl.scrollHeight;
}

function renderTestPopup() {
  const endpointInput = getPopupEndpointInput();
  if (endpointInput) {
    if (testState?.endpoint_url) {
      endpointInput.value = testState.endpoint_url;
      lastEndpointUrl = testState.endpoint_url;
    } else if (!endpointInput.value) {
      endpointInput.value = lastEndpointUrl;
    }
  }

  const scriptEl = document.getElementById("testScriptNameValue");
  const endpointEl = document.getElementById("testEndpointValue");
  const pidEl = document.getElementById("testPidValue");
  const detailEl = document.getElementById("testPopupDetail");

  if (scriptEl) scriptEl.textContent = testState?.script_name || selectedScriptPath || "--";
  if (endpointEl) endpointEl.textContent = testState?.endpoint_url || lastEndpointUrl || "--";
  if (pidEl) {
    const pidText = testState?.pid === null || testState?.pid === undefined || Number.isNaN(testState?.pid) ? "--" : String(testState.pid);
    const stateText = testState?.active ? t("testPidRunning") : t("testPidStopped");
    pidEl.textContent = `${pidText} (${stateText})`;
  }
  if (detailEl) detailEl.textContent = popupOverallText();

  updatePopupStep("health", "testStepHealthState");
  updatePopupStep("models", "testStepModelsState");
  updatePopupStep("completions", "testStepCompletionsState");
  renderPopupLogs();
  setPopupActionButtonsByTestState();
}

function startTestStatusPolling() {
  if (testStatusPollTimer !== null) return;
  testStatusPollTimer = window.setInterval(() => {
    fetchTestStatus(true, false);
  }, TEST_STATUS_POLL_MS);
}

function stopTestStatusPolling() {
  if (testStatusPollTimer === null) return;
  window.clearInterval(testStatusPollTimer);
  testStatusPollTimer = null;
}

function setInitialPopupTestingState(scriptPath, endpointUrl) {
  testState = {
    has_test: true,
    active: true,
    script_name: scriptPath,
    endpoint_url: endpointUrl,
    pid: null,
    overall_status: "testing",
    overall_detail: "Test started",
    updated_at: "",
    steps: {
      health: { status: "testing", detail: "" },
      models: { status: "testing", detail: "" },
      completions: { status: "testing", detail: "" },
    },
    logs: [],
  };
}

function updateScriptLastTestByPath(scriptPath, status, testedAt, detail = "") {
  if (!scriptPath) return;
  const idx = scriptListData.findIndex((item) => item && item.path === scriptPath);
  if (idx < 0) return;
  scriptListData[idx] = {
    ...scriptListData[idx],
    last_test: normalizeLastTest({
      status,
      tested_at: testedAt || new Date().toISOString(),
      detail,
    }),
  };
  renderScriptList();
}

function updateScriptLastTestFromFinalState(state) {
  if (!state || state.active || !state.script_name) return;
  const finalStatus = state.overall_status === "success" ? "success" : "fail";
  updateScriptLastTestByPath(
    state.script_name,
    finalStatus,
    state.finished_at || state.updated_at || new Date().toISOString(),
    state.overall_detail || "",
  );
}

async function fetchTestStatus(quiet = false, autoOpenPopup = false) {
  try {
    const { ok, status, data } = await requestJson("/api/scripts/test/status");
    if (!ok) {
      if (!quiet) {
        setStatus("scriptsStatus", t("statusScriptTestStatusFail", { reason: data.detail || status }), "err");
      }
      return;
    }

    if (!data.has_test) {
      testState = null;
      stopTestStatusPolling();
      renderTestPopup();
      return;
    }

    const previousActive = Boolean(testState?.active);
    const incoming = normalizeIncomingTestState(data);
    if (!incoming) return;
    testState = incoming;
    renderTestPopup();

    if (autoOpenPopup && incoming.active) {
      showTestPopup();
    }

    if (incoming.active) {
      startTestStatusPolling();
      return;
    }

    stopTestStatusPolling();
    if (previousActive || incoming.overall_status) {
      updateScriptLastTestFromFinalState(incoming);
    }
  } catch (err) {
    if (!quiet) {
      setStatus("scriptsStatus", t("statusScriptTestStatusFail", { reason: err }), "err");
    }
  }
}

async function loadScript(path, showStatus = true) {
  try {
    const encodedPath = encodeScriptPath(path);
    const { ok, status, data } = await requestJson(`/api/scripts/${encodedPath}`);
    if (!ok) {
      throw new Error(data.detail || status);
    }

    selectedScriptPath = data.script_path || path;
    selectedScriptName = data.name || selectedScriptPath.split("/").pop() || "";
    selectedScriptGroup = data.group || selectedScriptPath.split("/")[0] || "default";
    selectedScriptMeta = normalizeScriptMeta(data.metadata);

    const editor = document.getElementById("scriptEditor");
    if (!editor) return;
    editor.value = data.content || "";
    applyDefaultEndpointFromScriptContent(data.content || "");

    renderScriptList();
    renderGroupSelectors();
    renderScriptMetaForm();
    renderScriptModelNameOptions();
    updateScriptEditorHint();
    renderTestPopup();

    if (showStatus) {
      setStatus("scriptsStatus", t("statusScriptLoaded", { name: selectedScriptName }), "ok");
    }
  } catch (err) {
    setStatus("scriptsStatus", t("statusScriptLoadFail", { reason: err }), "err");
  }
}

export async function refreshScripts(preferPath = selectedScriptPath) {
  const editor = document.getElementById("scriptEditor");
  if (!editor) return;

  try {
    const { ok, status, data } = await requestJson("/api/scripts");
    if (!ok) {
      throw new Error(data.detail || status);
    }

    const scripts = Array.isArray(data.scripts) ? data.scripts.map(normalizeScriptItem) : [];
    scriptListData = scripts;
    scriptsDir = data.dir || "";

    renderScriptDirHint();
    renderScriptList();
    renderGroupSelectors();
    await loadRuntimeTargetServerGroup();

    const paths = new Set(scriptListData.map((item) => item.path));
    if (preferPath && paths.has(preferPath)) {
      selectedScriptPath = preferPath;
    } else if (!paths.has(selectedScriptPath)) {
      selectedScriptPath = scriptListData.length > 0 ? scriptListData[0].path : "";
    }

    if (selectedScriptPath) {
      await loadScript(selectedScriptPath, false);
    } else {
      editor.value = defaultScriptTemplate();
      selectedScriptName = "";
      selectedScriptGroup = "default";
      selectedScriptMeta = normalizeScriptMeta({});
      renderScriptMetaForm();
      updateScriptEditorHint();
    }

    setStatus("scriptsStatus", t("statusScriptsLoaded", { count: scriptListData.length }), "ok");
  } catch (err) {
    setStatus("scriptsStatus", t("statusScriptsLoadFail", { reason: err }), "err");
  }
}

async function createScript() {
  const input = document.getElementById("newScriptName");
  const groupSelect = document.getElementById("createScriptGroupSelect");
  if (!input || !groupSelect) return;

  const rawName = input.value.trim();
  if (!rawName) {
    setStatus("scriptsStatus", t("statusScriptNameRequired"), "err");
    return;
  }

  const group = (groupSelect.value || "default").trim() || "default";

  try {
    const { ok, status, data } = await requestJson("/api/scripts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: rawName, group, content: defaultScriptTemplate() }),
    });
    if (!ok) {
      throw new Error(data.detail || status);
    }

    input.value = "";
    const targetPath = data.script_path || `${group}/${rawName.endsWith(".sh") ? rawName : `${rawName}.sh`}`;
    await refreshScripts(targetPath);
    await loadScript(targetPath, false);
    setStatus("scriptsStatus", t("statusScriptCreated", { name: data.name || rawName }), "ok");
    hideCreateScriptPopup();
  } catch (err) {
    setStatus("scriptsStatus", t("statusScriptCreateFail", { reason: err }), "err");
  }
}

async function moveScript() {
  if (!selectedScriptPath) {
    setStatus("scriptsStatus", t("statusScriptMoveNeedSelect"), "err");
    return;
  }

  const moveSelect = document.getElementById("moveScriptGroupSelect");
  const moveInput = document.getElementById("moveScriptGroupInput");
  if (!moveSelect || !moveInput) return;

  const targetGroup = (moveInput.value.trim() || moveSelect.value || "").trim();
  if (!targetGroup) {
    setStatus("scriptsStatus", t("statusScriptMoveNeedGroup"), "err");
    return;
  }

  try {
    const { ok, status, data } = await requestJson("/api/scripts/move", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_path: selectedScriptPath, target_group: targetGroup }),
    });
    if (!ok) {
      throw new Error(data.detail || status);
    }

    moveInput.value = "";
    const targetPath = data.to || selectedScriptPath;
    await refreshScripts(targetPath);
    await loadScript(targetPath, false);
    setStatus("scriptsStatus", t("statusScriptMoved", { group: targetGroup }), "ok");
    hideMoveScriptPopup();
  } catch (err) {
    setStatus("scriptsStatus", t("statusScriptMoveFail", { reason: err }), "err");
  }
}

async function saveScript({ quiet = false, refreshAfter = true } = {}) {
  if (!selectedScriptPath) {
    if (!quiet) {
      setStatus("scriptsStatus", t("statusScriptNeedSelect"), "err");
    }
    return;
  }
  if (isScriptSaving) return;
  isScriptSaving = true;

  try {
    const editor = document.getElementById("scriptEditor");
    if (!editor) return;
    const content = editor.value;
    selectedScriptMeta = collectScriptMetaForm();

    const { ok, status, data } = await requestJson(`/api/scripts/${encodeScriptPath(selectedScriptPath)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content, metadata: selectedScriptMeta }),
    });
    if (!ok) {
      throw new Error(data.detail || status);
    }

    if (!quiet) {
      setStatus("scriptsStatus", t("statusScriptSaved", { name: data.name || selectedScriptName || selectedScriptPath }), "ok");
    }
    selectedScriptMeta = normalizeScriptMeta(data.metadata || selectedScriptMeta);
    renderScriptMetaForm();
    applyDefaultEndpointFromScriptContent(content);
    if (refreshAfter) {
      await refreshScripts(data.script_path || selectedScriptPath);
    }
  } catch (err) {
    if (!quiet) {
      setStatus("scriptsStatus", t("statusScriptSaveFail", { reason: err }), "err");
    }
  } finally {
    isScriptSaving = false;
  }
}

async function setScriptEnabled(path, enabled) {
  try {
    const { ok, status, data } = await requestJson(`/api/scripts/${encodeScriptPath(path)}/enabled`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: Boolean(enabled) }),
    });
    if (!ok) {
      throw new Error(data.detail || status);
    }

    const idx = scriptListData.findIndex((item) => item.path === path);
    if (idx >= 0) {
      scriptListData[idx] = { ...scriptListData[idx], enabled: Boolean(data.enabled) };
      renderScriptList();
    }

    const stateText = data.enabled ? "enable" : "disable";
    const itemName = (scriptListData.find((item) => item.path === path)?.name) || path;
    setStatus("scriptsStatus", t("statusScriptEnableSaved", { name: itemName, state: stateText }), "ok");
  } catch (err) {
    setStatus("scriptsStatus", t("statusScriptEnableSaveFail", { reason: err }), "err");
    renderScriptList();
  }
}

function openTestPopup() {
  if (!selectedScriptPath) {
    setStatus("scriptsStatus", t("statusScriptNeedSelect"), "err");
    return;
  }
  renderTestPopup();
  showTestPopup();
  fetchTestStatus(true, true);
}

function openHostTestPopup() {
  if (!selectedScriptPath) {
    setStatus("scriptsStatus", t("statusScriptNeedSelect"), "err");
    return;
  }
  const endpointInput = getHostTestEndpointInput();
  if (endpointInput) {
    endpointInput.value = lastEndpointUrl;
  }
  renderHostTestPopup();
  showHostTestPopup();
  void buildHostTestScriptFile();
}

function closeHostTestPopup() {
  hideHostTestPopup();
}

async function applyHostTestResult() {
  if (!selectedScriptPath) {
    setStatus("scriptsStatus", t("statusScriptNeedSelect"), "err");
    return;
  }
  const resultInput = document.getElementById("hostTestResultInput");
  if (!(resultInput instanceof HTMLTextAreaElement)) return;
  let decoded;
  try {
    decoded = decodeHostResult(resultInput.value);
    hostTestDecodedResult = decoded;
    hostTestResultText = [
      `HOST_TEST_RESULT status=${decoded.status}`,
      `reason=${decoded.reason || "unknown"}`,
      `log_file=${decoded.log_file || "-"}`,
      `endpoint=${decoded.endpoint || "-"}`,
      `script=${decoded.script || "-"}`,
    ].join(" ");
    if (selectedScriptPath) {
      updateScriptLastTestByPath(
        selectedScriptPath,
        decoded.status === "PASS" ? "success" : "fail",
        new Date().toISOString(),
        `${decoded.reason || "unknown"} | ${decoded.log_file || "-"}`,
      );
    }
  } catch (err) {
    hostTestDecodedResult = null;
    setStatus("scriptsStatus", t("statusHostTestResultDecodeFail", { reason: err }), "err");
    renderHostTestPopup();
    return;
  }

  try {
    const statusText = decoded.status === "PASS" ? "success" : "fail";
    const { ok, status, data } = await requestJson(`/api/scripts/${encodeScriptPath(selectedScriptPath)}/test/host-result`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status: statusText,
        reason: decoded.reason || "",
        log_file: decoded.log_file || "",
        endpoint: decoded.endpoint || "",
        script: decoded.script || "",
      }),
    });
    if (!ok) {
      throw new Error(data.detail || status);
    }
    await refreshScripts(selectedScriptPath);
  } catch (err) {
    setStatus("scriptsStatus", t("statusHostTestResultSaveFail", { reason: err }), "err");
    return;
  }

  renderHostTestPopup();
  setStatus("scriptsStatus", t("statusHostTestResultSaved"), "ok");
}

async function buildHostTestScriptFile() {
  if (!selectedScriptPath) return;
  const endpointInput = getHostTestEndpointInput();
  const endpointUrl = (endpointInput?.value || lastEndpointUrl || "").trim();
  if (!endpointUrl) {
    setStatus("scriptsStatus", t("statusScriptEndpointRequired"), "err");
    return;
  }
  try {
    const { ok, status, data } = await requestJson(`/api/scripts/${encodeScriptPath(selectedScriptPath)}/test/host-build`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ endpoint_url: endpointUrl }),
    });
    if (!ok) {
      throw new Error(data.detail || status);
    }
    hostTestCommand = String(data.command || "").trim();
    renderHostTestPopup();
    setStatus("scriptsStatus", t("statusHostTestScriptReady"), "ok");
  } catch (err) {
    hostTestCommand = "";
    renderHostTestPopup();
    setStatus("scriptsStatus", t("statusHostTestScriptBuildFail", { reason: err }), "err");
  }
}

async function startScriptTest() {
  if (!selectedScriptPath) {
    setStatus("scriptsStatus", t("statusScriptNeedSelect"), "err");
    return;
  }

  const endpointInput = getPopupEndpointInput();
  if (!endpointInput) return;

  const endpointUrl = endpointInput.value.trim();
  if (!endpointUrl) {
    setStatus("scriptsStatus", t("statusScriptEndpointRequired"), "err");
    return;
  }

  lastEndpointUrl = endpointUrl;
  setInitialPopupTestingState(selectedScriptPath, endpointUrl);
  renderTestPopup();
  startTestStatusPolling();

  try {
    const { ok, status, data } = await requestJson(`/api/scripts/${encodeScriptPath(selectedScriptPath)}/test/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ endpoint_url: endpointUrl }),
    });
    if (!ok) {
      throw new Error(data.detail || status);
    }

    const incoming = normalizeIncomingTestState(data);
    if (incoming) {
      testState = incoming;
      renderTestPopup();
    }
  } catch (err) {
    stopTestStatusPolling();
    if (testState) {
      testState.active = false;
      testState.overall_status = "fail";
      testState.overall_detail = String(err);
      testState.steps.health.status = "fail";
      testState.steps.models.status = "fail";
      testState.steps.completions.status = "fail";
      renderTestPopup();
    }
    setStatus("scriptsStatus", t("statusScriptTestStartFail", { reason: err }), "err");
  }
}

async function stopScriptTest({ silent = false } = {}) {
  if (!testState?.active) return;

  try {
    const { ok, status, data } = await requestJson("/api/scripts/test/stop", { method: "POST" });
    if (!ok) {
      throw new Error(data.detail || status);
    }

    const incoming = normalizeIncomingTestState(data);
    if (incoming) {
      testState = incoming;
    }
    renderTestPopup();
    stopTestStatusPolling();
    if (!silent) {
      setStatus("scriptsStatus", t("statusScriptTestStopped"), "ok");
    }
    await fetchTestStatus(true, false);
  } catch (err) {
    if (!silent) {
      setStatus("scriptsStatus", t("statusScriptTestStopFail", { reason: err }), "err");
    }
    throw err;
  }
}

async function closeTestPopup() {
  if (testState?.active) {
    try {
      await stopScriptTest({ silent: true });
    } catch {
      return;
    }
  }
  hideTestPopup();
}

function onScriptListClick(event) {
  const target = event.target;
  if (!(target instanceof Element)) return;

  if (target.closest(".script-toggle-row")) return;

  const item = target.closest(".script-item");
  if (!item) return;

  const path = decodeURIComponent(item.dataset.path || "");
  if (!path) return;
  loadScript(path);
}

function onScriptListToggleChange(event) {
  const target = event.target;
  if (!(target instanceof HTMLInputElement)) return;
  if (!target.classList.contains("script-enable")) return;

  const encodedPath = target.dataset.path || "";
  if (!encodedPath) return;

  const path = decodeURIComponent(encodedPath);
  void setScriptEnabled(path, target.checked);
}

export function rerenderScriptsUi() {
  renderScriptDirHint();
  renderScriptList();
  renderGroupSelectors();
  renderRuntimeServerGroupSelect();
  renderScriptMetaForm();
  renderScriptModelNameOptions();
  updateScriptEditorHint();
  renderTestPopup();
  renderHostTestPopup();
}

export function initScriptsFeature() {
  const listEl = document.getElementById("scriptList");
  if (!listEl) return;

  const refreshBtn = document.getElementById("refreshScriptsBtn");
  const openCreateBtn = document.getElementById("openCreateScriptPopupBtn");
  const openMoveBtn = document.getElementById("openMoveScriptPopupBtn");
  const createBtn = document.getElementById("confirmCreateScriptBtn");
  const moveBtn = document.getElementById("confirmMoveScriptBtn");
  const cancelCreateBtn = document.getElementById("cancelCreateScriptBtn");
  const cancelMoveBtn = document.getElementById("cancelMoveScriptBtn");
  const testBtn = document.getElementById("testScriptBtn");
  const testInHostBtn = document.getElementById("testInHostBtn");
  const autoDetectBtn = document.getElementById("autoDetectScriptMetaBtn");
  const popupStartBtn = document.getElementById("popupStartTestScriptBtn");
  const popupStopBtn = document.getElementById("popupStopTestScriptBtn");
  const closePopupBtn = document.getElementById("closeTestPopupBtn");
  const closeHostPopupBtn = document.getElementById("closeHostTestPopupBtn");
  const hostEndpointInput = getHostTestEndpointInput();
  const hostApplyResultBtn = document.getElementById("applyHostTestResultBtn");
  const endpointInput = getPopupEndpointInput();
  const newScriptInput = document.getElementById("newScriptName");
  const runtimeServerSelect = document.getElementById("runtimeServerGroupSelect");
  const scriptEditor = document.getElementById("scriptEditor");
  const scriptMetaTpSize = getMetaInput("scriptMetaTpSize");
  const scriptMetaModelName = getMetaInput("scriptMetaModelName");
  const scriptMetaModelId = getMetaInput("scriptMetaModelId");
  const scriptMetaBaseUrl = getMetaInput("scriptMetaBaseUrl");
  const scriptMetaPort = getMetaInput("scriptMetaPort");

  if (!refreshBtn || !openCreateBtn || !openMoveBtn || !createBtn || !moveBtn || !cancelCreateBtn || !cancelMoveBtn || !testBtn || !testInHostBtn || !autoDetectBtn || !popupStartBtn || !popupStopBtn || !closePopupBtn || !closeHostPopupBtn || !hostEndpointInput || !hostApplyResultBtn || !endpointInput || !newScriptInput || !runtimeServerSelect || !(scriptEditor instanceof HTMLTextAreaElement) || !scriptMetaTpSize || !scriptMetaModelName || !scriptMetaModelId || !scriptMetaBaseUrl || !scriptMetaPort) {
    return;
  }

  endpointInput.value = lastEndpointUrl;
  endpointInput.addEventListener("input", () => {
    lastEndpointUrl = endpointInput.value;
  });
  hostEndpointInput.value = lastEndpointUrl;
  hostEndpointInput.addEventListener("input", () => {
    lastEndpointUrl = hostEndpointInput.value;
    hostTestCommand = "";
    hostTestDecodedResult = null;
    renderHostTestPopup();
  });

  listEl.addEventListener("click", onScriptListClick);
  listEl.addEventListener("change", onScriptListToggleChange);

  refreshBtn.addEventListener("click", () => refreshScripts(selectedScriptPath));
  openCreateBtn.addEventListener("click", showCreateScriptPopup);
  openMoveBtn.addEventListener("click", showMoveScriptPopup);
  createBtn.addEventListener("click", createScript);
  moveBtn.addEventListener("click", moveScript);
  cancelCreateBtn.addEventListener("click", hideCreateScriptPopup);
  cancelMoveBtn.addEventListener("click", hideMoveScriptPopup);
  testBtn.addEventListener("click", openTestPopup);
  testInHostBtn.addEventListener("click", openHostTestPopup);
  autoDetectBtn.addEventListener("click", autoDetectAllScriptMeta);
  scriptEditor.addEventListener("input", scheduleScriptAutoSave);
  scriptMetaTpSize.addEventListener("input", scheduleScriptAutoSave);
  scriptMetaModelName.addEventListener("input", scheduleScriptAutoSave);
  scriptMetaModelId.addEventListener("input", scheduleScriptAutoSave);
  scriptMetaBaseUrl.addEventListener("input", scheduleScriptAutoSave);
  scriptMetaPort.addEventListener("input", scheduleScriptAutoSave);

  popupStartBtn.addEventListener("click", startScriptTest);
  popupStopBtn.addEventListener("click", () => stopScriptTest({ silent: false }));
  closePopupBtn.addEventListener("click", closeTestPopup);
  closeHostPopupBtn.addEventListener("click", closeHostTestPopup);
  hostApplyResultBtn.addEventListener("click", applyHostTestResult);
  runtimeServerSelect.addEventListener("change", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLSelectElement)) return;
    void saveRuntimeServerGroup(target.value);
  });

  newScriptInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      createScript();
    }
  });
  const moveGroupInput = document.getElementById("moveScriptGroupInput");
  if (moveGroupInput instanceof HTMLInputElement) {
    moveGroupInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        moveScript();
      }
    });
  }

  renderTestPopup();
  renderHostTestPopup();
  renderScriptMetaForm();
  void refreshScriptModelNameOptions();
  fetchTestStatus(true, true);
}
