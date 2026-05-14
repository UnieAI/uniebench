import { requestJson } from "../core/api.js";
import { t } from "../core/i18n.js";
import { escapeHtml, setStatus } from "../core/ui.js";

const DEFAULT_DATASET_PATH = "/workspace/jeff/Benchmark-Autotest/datasets/neural-bridge/rag-dataset-12000/data/train-00000-of-00001-9df3a936e1f63191.parquet";
const DEFAULT_PROFILE = {
  id: "default",
  name: ["inferencemax-h100"],
  endpoint_type: "completions",
  dataset_path: DEFAULT_DATASET_PATH,
  subset: "",
  split: "",
  token_lengths: ["none/1024"],
  concurrency: [1, 16, 32, 64, 128, 256, 512],
  request_rate: [1, 2, 4, 8, 16, 32, 64, 128, 192, 256, 320, 384],
};
const BENCHMARK_AUTOSAVE_MS = 700;
const DEFAULT_CONCURRENCY_OPTIONS = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048];
const DEFAULT_REQUEST_RATE_OPTIONS = [1, 2, 4, 8, 16, 32, 64, 128, 192, 256, 320, 384];
const AUDIO_FIXED_TOKEN_LENGTH = "none/none";

let profiles = [];
let selectedProfileId = "default";
let runtimeBenchmarkProfileId = "";
let nameOptions = ["inferencemax-h100", "vllm-bench"];
let tokenLengthOptions = ["none/1024"];
let concurrencyOptions = [...DEFAULT_CONCURRENCY_OPTIONS];
let requestRateOptions = [...DEFAULT_REQUEST_RATE_OPTIONS];
let benchmarkAutoSaveTimer = null;
let isBenchmarkSaving = false;

function normalizeEndpointType(raw) {
  const text = String(raw || "").trim().toLowerCase();
  if (text === "chat" || text === "completions" || text === "audio") return text;
  return "completions";
}

function isAudioEndpointType(endpointType) {
  return normalizeEndpointType(endpointType) === "audio";
}

function normalizeProfile(raw) {
  if (!raw || typeof raw !== "object") return { ...DEFAULT_PROFILE };
  return {
    id: String(raw.id || "default").trim() || "default",
    name: Array.isArray(raw.name) && raw.name.length > 0 ? raw.name.map((v) => String(v)).filter(Boolean) : ["inferencemax-h100"],
    endpoint_type: normalizeEndpointType(raw.endpoint_type),
    dataset_path: String(raw.dataset_path || "").trim() || DEFAULT_DATASET_PATH,
    subset: String(raw.subset || "").trim(),
    split: String(raw.split || "").trim(),
    token_lengths: Array.isArray(raw.token_lengths) && raw.token_lengths.length > 0 ? raw.token_lengths.map((v) => String(v)).filter(Boolean) : ["none/1024"],
    concurrency: Array.isArray(raw.concurrency) && raw.concurrency.length > 0 ? raw.concurrency.map((v) => Number(v)).filter((v) => Number.isFinite(v)) : [1, 16, 32, 64, 128, 256, 512],
    request_rate: Array.isArray(raw.request_rate) && raw.request_rate.length > 0 ? raw.request_rate.map((v) => Number(v)).filter((v) => Number.isFinite(v)) : [1, 2, 4, 8, 16, 32, 64, 128, 192, 256, 320, 384],
  };
}

function setRateLabel(endpointType) {
  const labelEl = document.getElementById("benchmarkRateLabel");
  if (!labelEl) return;
  labelEl.textContent = isAudioEndpointType(endpointType) ? t("benchmarkRequestRateLabel") : t("benchmarkConcurrencyLabel");
}

function getRateOptions(endpointType) {
  return isAudioEndpointType(endpointType) ? requestRateOptions : concurrencyOptions;
}

function getSelectedProfile() {
  const found = profiles.find((p) => p.id === selectedProfileId);
  return found || profiles[0] || null;
}

function selectedValues(selectEl) {
  if (!(selectEl instanceof HTMLSelectElement)) return [];
  return Array.from(selectEl.selectedOptions).map((opt) => opt.value);
}

function setSelectOptions(selectEl, options, selected) {
  if (!(selectEl instanceof HTMLSelectElement)) return;
  const selectedSet = new Set(selected.map((v) => String(v)));
  selectEl.innerHTML = options.map((option) => {
    const value = String(option);
    const sel = selectedSet.has(value) ? " selected" : "";
    return `<option value="${escapeHtml(value)}"${sel}>${escapeHtml(value)}</option>`;
  }).join("");
}

function syncProfileFromForm() {
  const profile = getSelectedProfile();
  if (!profile) return;

  const nameSelect = document.getElementById("benchmarkNameSelect");
  const endpointType = document.getElementById("benchmarkEndpointType");
  const datasetPath = document.getElementById("benchmarkDatasetPath");
  const subset = document.getElementById("benchmarkSubset");
  const split = document.getElementById("benchmarkSplit");
  const tokenSelect = document.getElementById("benchmarkTokenLengthsSelect");
  const concurrencySelect = document.getElementById("benchmarkConcurrencySelect");

  if (!(endpointType instanceof HTMLSelectElement) || !(datasetPath instanceof HTMLInputElement)) return;

  profile.name = selectedValues(nameSelect);
  if (profile.name.length === 0) {
    profile.name = ["inferencemax-h100"];
  }
  profile.endpoint_type = normalizeEndpointType(endpointType.value);
  profile.dataset_path = datasetPath.value.trim() || DEFAULT_DATASET_PATH;
  if (isAudioEndpointType(profile.endpoint_type)) {
    profile.subset = subset instanceof HTMLInputElement ? subset.value.trim() : "";
    profile.split = split instanceof HTMLInputElement ? split.value.trim() : "";
  } else {
    profile.subset = "";
    profile.split = "";
  }
  if (isAudioEndpointType(profile.endpoint_type)) {
    profile.token_lengths = [AUDIO_FIXED_TOKEN_LENGTH];
  } else {
    profile.token_lengths = selectedValues(tokenSelect);
    if (profile.token_lengths.length === 0) profile.token_lengths = ["none/1024"];
  }
  const selectedRateValues = selectedValues(concurrencySelect).map((v) => Number(v)).filter((v) => Number.isFinite(v));
  if (isAudioEndpointType(profile.endpoint_type)) {
    profile.request_rate = selectedRateValues.length > 0 ? selectedRateValues : [...DEFAULT_REQUEST_RATE_OPTIONS];
  } else {
    profile.concurrency = selectedRateValues.length > 0 ? selectedRateValues : [1, 16, 32, 64, 128, 256, 512];
  }
}

function renderProfileSelect() {
  const selectEl = document.getElementById("benchmarkProfileSelect");
  if (!(selectEl instanceof HTMLSelectElement)) return;
  if (!profiles.length) {
    profiles = [{ ...DEFAULT_PROFILE }];
  }
  if (!profiles.some((p) => p.id === selectedProfileId)) {
    selectedProfileId = profiles[0].id;
  }
  selectEl.innerHTML = profiles
    .map((p) => {
      const sel = p.id === selectedProfileId ? " selected" : "";
      return `<option value="${escapeHtml(p.id)}"${sel}>${escapeHtml(p.id)}</option>`;
    })
    .join("");
}

function renderRuntimeBenchmarkProfileSelect() {
  const selectEl = document.getElementById("runtimeBenchmarkProfileSelect");
  if (!(selectEl instanceof HTMLSelectElement)) return;
  const options = profiles.map((p) => p.id);
  selectEl.innerHTML = options
    .map((id) => `<option value="${escapeHtml(id)}">${escapeHtml(id)}</option>`)
    .join("");
  const target = runtimeBenchmarkProfileId && options.includes(runtimeBenchmarkProfileId)
    ? runtimeBenchmarkProfileId
    : (options[0] || "default");
  runtimeBenchmarkProfileId = target;
  if (target) selectEl.value = target;
}

async function loadRuntimeBenchmarkProfile() {
  try {
    const { ok, status, data } = await requestJson("/api/config/runtime-target");
    if (!ok) throw new Error(data.detail || status);
    runtimeBenchmarkProfileId = String(data.benchmark_id || "").trim();
  } catch {
    runtimeBenchmarkProfileId = "";
  }
  renderRuntimeBenchmarkProfileSelect();
}

async function saveRuntimeBenchmarkProfile(profileId) {
  const value = String(profileId || "").trim();
  if (!value) return;
  try {
    const { ok, status, data } = await requestJson("/api/config/runtime-target", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ benchmark_id: value }),
    });
    if (!ok) {
      throw new Error(data.detail || status);
    }
    runtimeBenchmarkProfileId = String(data.benchmark_id || value).trim() || value;
    renderRuntimeBenchmarkProfileSelect();
    setStatus("benchmarkStatus", t("statusRuntimeBenchmarkProfileSaved", { id: runtimeBenchmarkProfileId }), "ok");
  } catch (err) {
    setStatus("benchmarkStatus", t("statusRuntimeBenchmarkProfileSaveFail", { reason: err }), "err");
    renderRuntimeBenchmarkProfileSelect();
  }
}

function renderProfileForm() {
  const profile = getSelectedProfile();
  if (!profile) return;

  const endpointType = document.getElementById("benchmarkEndpointType");
  const datasetPath = document.getElementById("benchmarkDatasetPath");
  const subset = document.getElementById("benchmarkSubset");
  const split = document.getElementById("benchmarkSplit");
  const tokenInput = document.getElementById("benchmarkTokenLengthInput");
  const tokenAddBtn = document.getElementById("benchmarkAddTokenLengthBtn");
  const tokenSelect = document.getElementById("benchmarkTokenLengthsSelect");

  const endpointTypeValue = normalizeEndpointType(profile.endpoint_type);
  const isAudio = isAudioEndpointType(endpointTypeValue);
  const effectiveTokenLengthOptions = isAudio ? [AUDIO_FIXED_TOKEN_LENGTH] : tokenLengthOptions;
  const effectiveSelectedTokenLengths = isAudio ? [AUDIO_FIXED_TOKEN_LENGTH] : profile.token_lengths;
  const selectedRates = isAudioEndpointType(endpointTypeValue) ? profile.request_rate : profile.concurrency;

  setSelectOptions(document.getElementById("benchmarkNameSelect"), nameOptions, profile.name);
  setSelectOptions(tokenSelect, effectiveTokenLengthOptions, effectiveSelectedTokenLengths);
  setSelectOptions(
    document.getElementById("benchmarkConcurrencySelect"),
    getRateOptions(endpointTypeValue).map((v) => String(v)),
    selectedRates.map((v) => String(v)),
  );
  setRateLabel(endpointTypeValue);

  if (endpointType instanceof HTMLSelectElement) {
    endpointType.value = endpointTypeValue;
  }
  if (datasetPath instanceof HTMLInputElement) {
    datasetPath.value = profile.dataset_path || DEFAULT_DATASET_PATH;
  }
  if (subset instanceof HTMLInputElement) {
    subset.value = isAudio ? (profile.subset || "") : "";
    subset.disabled = !isAudio;
  }
  if (split instanceof HTMLInputElement) {
    split.value = isAudio ? (profile.split || "") : "";
    split.disabled = !isAudio;
  }
  if (tokenInput instanceof HTMLInputElement) {
    tokenInput.disabled = isAudio;
  }
  if (tokenAddBtn instanceof HTMLButtonElement) {
    tokenAddBtn.disabled = isAudio;
  }
  if (tokenSelect instanceof HTMLSelectElement) {
    tokenSelect.disabled = isAudio;
  }
}

function rerenderAll() {
  renderProfileSelect();
  renderRuntimeBenchmarkProfileSelect();
  renderProfileForm();
}

function scheduleBenchmarkAutoSave() {
  if (benchmarkAutoSaveTimer !== null) {
    window.clearTimeout(benchmarkAutoSaveTimer);
  }
  benchmarkAutoSaveTimer = window.setTimeout(() => {
    benchmarkAutoSaveTimer = null;
    void saveBenchmarkConfig({ quiet: true, rerenderAfter: false });
  }, BENCHMARK_AUTOSAVE_MS);
}

export async function loadBenchmarkConfig() {
  try {
    const { ok, status, data } = await requestJson("/api/benchmark-config");
    if (!ok) {
      throw new Error(data.detail || status);
    }
    profiles = Array.isArray(data.profiles) ? data.profiles.map(normalizeProfile) : [{ ...DEFAULT_PROFILE }];
    nameOptions = Array.isArray(data.name_options) && data.name_options.length > 0 ? data.name_options.map((v) => String(v)) : ["inferencemax-h100", "vllm-bench"];
    tokenLengthOptions = Array.isArray(data.token_length_options) && data.token_length_options.length > 0
      ? data.token_length_options.map((v) => String(v))
      : ["none/1024"];
    concurrencyOptions = Array.isArray(data.concurrency_options) && data.concurrency_options.length > 0
      ? data.concurrency_options.map((v) => Number(v)).filter((v) => Number.isFinite(v))
      : [...DEFAULT_CONCURRENCY_OPTIONS];
    requestRateOptions = Array.isArray(data.request_rate_options) && data.request_rate_options.length > 0
      ? data.request_rate_options.map((v) => Number(v)).filter((v) => Number.isFinite(v))
      : [...DEFAULT_REQUEST_RATE_OPTIONS];
    selectedProfileId = profiles[0]?.id || "default";
    await loadRuntimeBenchmarkProfile();
    rerenderAll();
    setStatus("benchmarkStatus", t("statusBenchmarkLoaded", { count: profiles.length, time: data.time }), "ok");
  } catch (err) {
    setStatus("benchmarkStatus", t("statusBenchmarkLoadFail", { reason: err }), "err");
  }
}

export async function saveBenchmarkConfig({ quiet = false, rerenderAfter = true } = {}) {
  if (isBenchmarkSaving) return;
  isBenchmarkSaving = true;
  syncProfileFromForm();
  try {
    const payload = {
      profiles: profiles.map((p) => ({
        id: p.id,
        name: p.name,
        endpoint_type: p.endpoint_type,
        dataset_path: p.dataset_path,
        subset: p.subset,
        split: p.split,
        token_lengths: p.token_lengths,
        concurrency: p.concurrency,
        request_rate: p.request_rate,
      })),
    };
    const { ok, status, data } = await requestJson("/api/benchmark-config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!ok) {
      throw new Error(data.detail || status);
    }
    profiles = Array.isArray(data.profiles) ? data.profiles.map(normalizeProfile) : [{ ...DEFAULT_PROFILE }];
    nameOptions = Array.isArray(data.name_options) && data.name_options.length > 0 ? data.name_options.map((v) => String(v)) : ["inferencemax-h100", "vllm-bench"];
    tokenLengthOptions = Array.isArray(data.token_length_options) && data.token_length_options.length > 0
      ? data.token_length_options.map((v) => String(v))
      : ["none/1024"];
    concurrencyOptions = Array.isArray(data.concurrency_options) && data.concurrency_options.length > 0
      ? data.concurrency_options.map((v) => Number(v)).filter((v) => Number.isFinite(v))
      : [...DEFAULT_CONCURRENCY_OPTIONS];
    requestRateOptions = Array.isArray(data.request_rate_options) && data.request_rate_options.length > 0
      ? data.request_rate_options.map((v) => Number(v)).filter((v) => Number.isFinite(v))
      : [...DEFAULT_REQUEST_RATE_OPTIONS];
    if (!profiles.some((p) => p.id === selectedProfileId)) {
      selectedProfileId = profiles[0]?.id || "default";
    }
    if (!profiles.some((p) => p.id === runtimeBenchmarkProfileId)) {
      runtimeBenchmarkProfileId = profiles[0]?.id || "default";
      await saveRuntimeBenchmarkProfile(runtimeBenchmarkProfileId);
    }
    if (rerenderAfter) {
      rerenderAll();
    }
    if (!quiet) {
      setStatus("benchmarkStatus", t("statusBenchmarkSaved", { time: data.time }), "ok");
    }
  } catch (err) {
    if (!quiet) {
      setStatus("benchmarkStatus", t("statusBenchmarkSaveFail", { reason: err }), "err");
    }
  } finally {
    isBenchmarkSaving = false;
  }
}

function onProfileChange(event) {
  syncProfileFromForm();
  const target = event.target;
  if (!(target instanceof HTMLSelectElement)) return;
  scheduleBenchmarkAutoSave();
  selectedProfileId = target.value;
  renderProfileForm();
}

function addProfile() {
  syncProfileFromForm();
  const input = document.getElementById("benchmarkNewProfileId");
  if (!(input instanceof HTMLInputElement)) return;
  const newId = input.value.trim();
  if (!newId) {
    setStatus("benchmarkStatus", t("statusBenchmarkProfileNameRequired"), "err");
    return;
  }
  if (profiles.some((p) => p.id === newId)) {
    setStatus("benchmarkStatus", t("statusBenchmarkProfileExists", { id: newId }), "err");
    return;
  }
  const profile = normalizeProfile({ ...DEFAULT_PROFILE, id: newId });
  profiles.push(profile);
  selectedProfileId = newId;
  input.value = "";
  rerenderAll();
  setStatus("benchmarkStatus", t("statusBenchmarkProfileAdded", { id: newId }), "ok");
  void saveBenchmarkConfig({ quiet: true, rerenderAfter: false });
}

function deleteProfile() {
  if (profiles.length <= 1) {
    setStatus("benchmarkStatus", t("statusBenchmarkProfileNeedOne"), "err");
    return;
  }
  profiles = profiles.filter((p) => p.id !== selectedProfileId);
  selectedProfileId = profiles[0]?.id || "default";
  if (!profiles.some((p) => p.id === runtimeBenchmarkProfileId)) {
    runtimeBenchmarkProfileId = profiles[0]?.id || "default";
    void saveRuntimeBenchmarkProfile(runtimeBenchmarkProfileId);
  }
  rerenderAll();
  setStatus("benchmarkStatus", t("statusBenchmarkProfileDeleted"), "ok");
  void saveBenchmarkConfig({ quiet: true, rerenderAfter: false });
}

function addTokenLengthOption() {
  const profile = getSelectedProfile();
  if (profile && isAudioEndpointType(profile.endpoint_type)) {
    return;
  }

  const input = document.getElementById("benchmarkTokenLengthInput");
  if (!(input instanceof HTMLInputElement)) return;
  const text = input.value.trim();
  if (!text.includes("/")) {
    setStatus("benchmarkStatus", t("statusBenchmarkTokenLengthInvalid"), "err");
    return;
  }
  if (!tokenLengthOptions.includes(text)) {
    tokenLengthOptions.push(text);
  }
  if (profile && !profile.token_lengths.includes(text)) {
    profile.token_lengths.push(text);
  }
  input.value = "";
  renderProfileForm();
  scheduleBenchmarkAutoSave();
}

export function initBenchmarkConfigFeature() {
  const profileSelect = document.getElementById("benchmarkProfileSelect");
  const runtimeProfileSelect = document.getElementById("runtimeBenchmarkProfileSelect");
  const addProfileBtn = document.getElementById("benchmarkAddProfileBtn");
  const deleteProfileBtn = document.getElementById("benchmarkDeleteProfileBtn");
  const addTokenBtn = document.getElementById("benchmarkAddTokenLengthBtn");
  const reloadBtn = document.getElementById("benchmarkReloadBtn");
  const nameSelect = document.getElementById("benchmarkNameSelect");
  const endpointType = document.getElementById("benchmarkEndpointType");
  const datasetPath = document.getElementById("benchmarkDatasetPath");
  const subset = document.getElementById("benchmarkSubset");
  const split = document.getElementById("benchmarkSplit");
  const tokenLengthsSelect = document.getElementById("benchmarkTokenLengthsSelect");
  const concurrencySelect = document.getElementById("benchmarkConcurrencySelect");

  if (!profileSelect || !runtimeProfileSelect || !addProfileBtn || !deleteProfileBtn || !addTokenBtn || !reloadBtn || !(nameSelect instanceof HTMLSelectElement) || !(endpointType instanceof HTMLSelectElement) || !(datasetPath instanceof HTMLInputElement) || !(subset instanceof HTMLInputElement) || !(split instanceof HTMLInputElement) || !(tokenLengthsSelect instanceof HTMLSelectElement) || !(concurrencySelect instanceof HTMLSelectElement)) return;

  profileSelect.addEventListener("change", onProfileChange);
  runtimeProfileSelect.addEventListener("change", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLSelectElement)) return;
    void saveRuntimeBenchmarkProfile(target.value);
  });
  addProfileBtn.addEventListener("click", addProfile);
  deleteProfileBtn.addEventListener("click", deleteProfile);
  addTokenBtn.addEventListener("click", addTokenLengthOption);
  reloadBtn.addEventListener("click", loadBenchmarkConfig);
  nameSelect.addEventListener("change", scheduleBenchmarkAutoSave);
  endpointType.addEventListener("change", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLSelectElement)) return;
    const profile = getSelectedProfile();
    if (!profile) return;
    profile.endpoint_type = normalizeEndpointType(target.value);
    if (isAudioEndpointType(profile.endpoint_type)) {
      profile.token_lengths = [AUDIO_FIXED_TOKEN_LENGTH];
    }
    renderProfileForm();
    scheduleBenchmarkAutoSave();
  });
  datasetPath.addEventListener("input", scheduleBenchmarkAutoSave);
  subset.addEventListener("input", scheduleBenchmarkAutoSave);
  split.addEventListener("input", scheduleBenchmarkAutoSave);
  tokenLengthsSelect.addEventListener("change", scheduleBenchmarkAutoSave);
  concurrencySelect.addEventListener("change", scheduleBenchmarkAutoSave);
}
