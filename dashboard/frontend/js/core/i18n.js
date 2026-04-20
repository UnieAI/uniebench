const LANG_KEY = "dashboard_lang";

const I18N = {
  zh: {
    pageTitle: "Benchmark Dashboard MVP",
    pageSubtitle: "MVP: 即時系統資源監看 + 設定檔編輯器",
    apiBaseLabel: "API Base URL",
    langLabel: "語言",
    tabMonitor: "系統資源監看",
    tabConfig: "設定檔編輯器",
    tabScripts: "服務腳本",
    tabGlobalConfig: "全域設定",
    loading: "讀取中...",
    configNotLoaded: "尚未載入 config",
    scriptsNotLoaded: "尚未載入腳本清單",
    btnReload: "重新載入",
    btnSave: "儲存設定",
    btnRefreshScripts: "重新載入腳本",
    btnCreateScript: "新增腳本",
    btnMoveScript: "移動腳本",
    btnSaveScript: "儲存腳本",
    btnTestScript: "測試腳本",
    btnAutoDetect: "自動偵測",
    btnStartTestScript: "啟動測試",
    btnStopTestScript: "停止測試",
    btnClose: "關閉",
    btnSaveGlobalConfig: "儲存全域設定",
    btnDiscoverModelNames: "自動讀取",
    btnAddModelName: "新增",
    btnRemove: "移除",
    scriptEndpointLabel: "Endpoint URL",
    scriptEndpointPlaceholder: "http://localhost:8000",
    testPopupTitle: "腳本測試狀態",
    testScriptLabel: "Script",
    testEndpointLabel: "Endpoint",
    testPidLabel: "PID",
    testStepHealth: "Health",
    testStepModels: "v1/models",
    testStepCompletions: "v1/completions",
    testStateTesting: "測試中",
    testStateSuccess: "成功",
    testStateFail: "失敗",
    testPidRunning: "執行中",
    testPidStopped: "已停止",
    testLogTitle: "執行 Log",
    testNoLogs: "尚無 log",
    metricCpu: "CPU 使用率",
    metricRamPct: "RAM 使用率",
    metricRamMb: "RAM 已用 / 總量 (MB)",
    colGpu: "GPU",
    colName: "Name",
    colUtil: "Util (%)",
    colMemory: "Memory (MB)",
    colTemp: "Temp (°C)",
    colPower: "Power (W)",
    na: "N/A",
    rowNoData: "無資料",
    rowNoGpu: "未偵測到 GPU",
    rowCheckApi: "請檢查 API 是否啟動",
    scriptEnable: "enable",
    moveScriptGroupPlaceholder: "輸入目標群組（留空則使用左側選單）",
    scriptVerified: "已驗證",
    scriptVerifyFailed: "驗證失敗",
    scriptUntested: "未測試",
    scriptLastTestTimeTooltip: "最後測試時間: {time}",
    scriptsNone: "目前沒有腳本",
    scriptsDirLabel: "腳本目錄: {dir}",
    newScriptPlaceholder: "輸入新腳本名稱（例如 run_xxx.sh）",
    scriptEditorPlaceholder: "#!/bin/bash\nset -euo pipefail\n",
    scriptMetaTpSizeLabel: "tp_size",
    scriptMetaModelNameLabel: "model_name",
    scriptMetaModelIdLabel: "model_id",
    scriptMetaBaseUrlLabel: "base_url",
    scriptMetaPortLabel: "port",
    scriptEditorHint: "點選左側腳本即可編輯",
    scriptEditing: "目前編輯: {name}",
    scriptEditingPath: "目前編輯: {name} ({path})",
    statusFetchFail: "讀取失敗: {reason}",
    statusGpuUnavailable: "GPU 不可用: {reason}",
    statusUpdated: "最後更新: {time}",
    statusConnError: "連線錯誤: {reason}",
    statusConfigLoaded: "已載入: {path} @ {time}",
    statusConfigLoadFail: "載入失敗: {reason}",
    statusConfigSaved: "儲存成功: {path} @ {time}",
    statusConfigSaveFail: "儲存失敗: {reason}",
    statusScriptsLoaded: "已載入 {count} 個腳本",
    statusScriptsLoadFail: "腳本清單載入失敗: {reason}",
    statusScriptLoaded: "已載入腳本: {name}",
    statusScriptLoadFail: "腳本載入失敗: {reason}",
    statusScriptCreated: "已新增腳本: {name}",
    statusScriptCreateFail: "新增腳本失敗: {reason}",
    statusScriptSaved: "腳本已儲存: {name}",
    statusScriptSaveFail: "儲存腳本失敗: {reason}",
    statusScriptMoved: "腳本已移動至群組: {group}",
    statusScriptMoveFail: "移動腳本失敗: {reason}",
    statusScriptEnableSaved: "腳本狀態已更新: {name} => {state}",
    statusScriptEnableSaveFail: "更新腳本狀態失敗: {reason}",
    statusScriptMoveNeedSelect: "請先選擇要移動的腳本",
    statusScriptMoveNeedGroup: "請輸入或選擇目標群組",
    statusScriptNeedSelect: "請先選擇腳本",
    statusScriptNameRequired: "請輸入腳本名稱",
    statusScriptEndpointRequired: "請輸入 endpoint URL",
    statusScriptTestStarted: "腳本測試已啟動: {name} (PID: {pid})",
    statusScriptTestStartFail: "啟動測試失敗: {reason}",
    statusScriptTestStopped: "測試已停止",
    statusScriptTestStopFail: "停止測試失敗: {reason}",
    statusScriptTestStatusFail: "讀取測試狀態失敗: {reason}",
    statusScriptTestDoneSuccess: "測試完成：health/models/completions 全部成功",
    statusScriptTestDoneFail: "測試完成：有步驟失敗",
    statusScriptTestDoneStopped: "測試已停止",
    statusScriptTestDoneTimeout: "測試逾時",
    statusScriptAutoDetectPending: "欄位 {field} 的自動偵測功能尚未實作",
    statusScriptAutoDetectApplied: "欄位 {field} 已套用自動偵測結果",
    statusScriptAutoDetectAppliedAll: "已套用全部欄位的自動偵測結果",
    globalConfigNotLoaded: "尚未載入全域設定",
    globalModelPathLabel: "model_path",
    globalModelNamesLabel: "model_name 可選列表",
    globalModelNamePlaceholder: "輸入 model_name",
    globalDefaultBaseUrlLabel: "default_base_url",
    globalCudaVersionLabel: "cuda_version（唯讀）",
    globalCpuModelLabel: "cpu_model（唯讀）",
    globalGpuModelLabel: "gpu_model（唯讀）",
    globalModelNamesEmpty: "尚無可選 model_name",
    statusGlobalConfigLoaded: "全域設定已載入 @ {time}",
    statusGlobalConfigLoadFail: "全域設定載入失敗: {reason}",
    statusGlobalConfigSaved: "全域設定已儲存 @ {time}",
    statusGlobalConfigSaveFail: "全域設定儲存失敗: {reason}",
    statusGlobalConfigDiscovered: "已從 {path} 自動讀取 {count} 個 model_name",
    statusGlobalConfigDiscoverFail: "自動讀取 model_name 失敗: {reason}",
  },
  en: {
    pageTitle: "Benchmark Dashboard MVP",
    pageSubtitle: "MVP: Real-time System Monitor + Config Editor",
    apiBaseLabel: "API Base URL",
    langLabel: "Language",
    tabMonitor: "System Monitor",
    tabConfig: "Config Editor",
    tabScripts: "Service Scripts",
    tabGlobalConfig: "Global Config",
    loading: "Loading...",
    configNotLoaded: "Config not loaded",
    scriptsNotLoaded: "Script list not loaded",
    btnReload: "Reload",
    btnSave: "Save Config",
    btnRefreshScripts: "Refresh Scripts",
    btnCreateScript: "Create Script",
    btnMoveScript: "Move Script",
    btnSaveScript: "Save Script",
    btnTestScript: "Test Script",
    btnAutoDetect: "Auto Detect",
    btnStartTestScript: "Start Test",
    btnStopTestScript: "Stop Test",
    btnClose: "Close",
    btnSaveGlobalConfig: "Save Global Config",
    btnDiscoverModelNames: "Auto Discover",
    btnAddModelName: "Add",
    btnRemove: "Remove",
    scriptEndpointLabel: "Endpoint URL",
    scriptEndpointPlaceholder: "http://localhost:8000",
    testPopupTitle: "Script Test Status",
    testScriptLabel: "Script",
    testEndpointLabel: "Endpoint",
    testPidLabel: "PID",
    testStepHealth: "Health",
    testStepModels: "v1/models",
    testStepCompletions: "v1/completions",
    testStateTesting: "Testing",
    testStateSuccess: "Success",
    testStateFail: "Fail",
    testPidRunning: "Running",
    testPidStopped: "Stopped",
    testLogTitle: "Execution Log",
    testNoLogs: "No logs yet",
    metricCpu: "CPU Usage",
    metricRamPct: "RAM Usage",
    metricRamMb: "RAM Used / Total (MB)",
    colGpu: "GPU",
    colName: "Name",
    colUtil: "Util (%)",
    colMemory: "Memory (MB)",
    colTemp: "Temp (°C)",
    colPower: "Power (W)",
    na: "N/A",
    rowNoData: "No data",
    rowNoGpu: "No GPU detected",
    rowCheckApi: "Please check whether the API is running",
    scriptEnable: "enable",
    moveScriptGroupPlaceholder: "Enter target group (blank uses the select)",
    scriptVerified: "Verified",
    scriptVerifyFailed: "Verification Failed",
    scriptUntested: "Not Tested",
    scriptLastTestTimeTooltip: "Last test time: {time}",
    scriptsNone: "No scripts yet",
    scriptsDirLabel: "Scripts directory: {dir}",
    newScriptPlaceholder: "Enter script name (e.g. run_xxx.sh)",
    scriptEditorPlaceholder: "#!/bin/bash\nset -euo pipefail\n",
    scriptMetaTpSizeLabel: "tp_size",
    scriptMetaModelNameLabel: "model_name",
    scriptMetaModelIdLabel: "model_id",
    scriptMetaBaseUrlLabel: "base_url",
    scriptMetaPortLabel: "port",
    scriptEditorHint: "Select a script from the left to edit",
    scriptEditing: "Editing: {name}",
    scriptEditingPath: "Editing: {name} ({path})",
    statusFetchFail: "Fetch failed: {reason}",
    statusGpuUnavailable: "GPU unavailable: {reason}",
    statusUpdated: "Last updated: {time}",
    statusConnError: "Connection error: {reason}",
    statusConfigLoaded: "Loaded: {path} @ {time}",
    statusConfigLoadFail: "Load failed: {reason}",
    statusConfigSaved: "Saved: {path} @ {time}",
    statusConfigSaveFail: "Save failed: {reason}",
    statusScriptsLoaded: "{count} scripts loaded",
    statusScriptsLoadFail: "Failed to load scripts: {reason}",
    statusScriptLoaded: "Script loaded: {name}",
    statusScriptLoadFail: "Failed to load script: {reason}",
    statusScriptCreated: "Script created: {name}",
    statusScriptCreateFail: "Failed to create script: {reason}",
    statusScriptSaved: "Script saved: {name}",
    statusScriptSaveFail: "Failed to save script: {reason}",
    statusScriptMoved: "Script moved to group: {group}",
    statusScriptMoveFail: "Failed to move script: {reason}",
    statusScriptEnableSaved: "Script state updated: {name} => {state}",
    statusScriptEnableSaveFail: "Failed to update script state: {reason}",
    statusScriptMoveNeedSelect: "Please select a script first",
    statusScriptMoveNeedGroup: "Please enter or select a target group",
    statusScriptNeedSelect: "Please select a script first",
    statusScriptNameRequired: "Please enter a script name",
    statusScriptEndpointRequired: "Please enter endpoint URL",
    statusScriptTestStarted: "Script test started: {name} (PID: {pid})",
    statusScriptTestStartFail: "Failed to start test: {reason}",
    statusScriptTestStopped: "Test stopped",
    statusScriptTestStopFail: "Failed to stop test: {reason}",
    statusScriptTestStatusFail: "Failed to fetch test status: {reason}",
    statusScriptTestDoneSuccess: "Test finished: health/models/completions all succeeded",
    statusScriptTestDoneFail: "Test finished: one or more steps failed",
    statusScriptTestDoneStopped: "Test stopped",
    statusScriptTestDoneTimeout: "Test timeout",
    statusScriptAutoDetectPending: "Auto-detect for field {field} is not implemented yet",
    statusScriptAutoDetectApplied: "Applied auto-detect result for {field}",
    statusScriptAutoDetectAppliedAll: "Applied auto-detect results to all fields",
    globalConfigNotLoaded: "Global config not loaded",
    globalModelPathLabel: "model_path",
    globalModelNamesLabel: "model_name options",
    globalModelNamePlaceholder: "Enter model_name",
    globalDefaultBaseUrlLabel: "default_base_url",
    globalCudaVersionLabel: "cuda_version (read-only)",
    globalCpuModelLabel: "cpu_model (read-only)",
    globalGpuModelLabel: "gpu_model (read-only)",
    globalModelNamesEmpty: "No model_name options",
    statusGlobalConfigLoaded: "Global config loaded @ {time}",
    statusGlobalConfigLoadFail: "Failed to load global config: {reason}",
    statusGlobalConfigSaved: "Global config saved @ {time}",
    statusGlobalConfigSaveFail: "Failed to save global config: {reason}",
    statusGlobalConfigDiscovered: "Discovered {count} model_name items from {path}",
    statusGlobalConfigDiscoverFail: "Failed to discover model_name: {reason}",
  },
};

let currentLang = "zh";

export function getCurrentLanguage() {
  return currentLang;
}

export function detectLanguage() {
  const saved = localStorage.getItem(LANG_KEY);
  if (saved === "zh" || saved === "en") return saved;
  const navLang = (navigator.language || "").toLowerCase();
  return navLang.startsWith("en") ? "en" : "zh";
}

export function setLanguage(lang) {
  currentLang = lang === "en" ? "en" : "zh";
  localStorage.setItem(LANG_KEY, currentLang);
}

export function t(key, vars) {
  const dict = I18N[currentLang] || I18N.zh;
  const fallback = I18N.zh[key] || key;
  let text = dict[key] || fallback;
  if (!vars) return text;
  Object.entries(vars).forEach(([k, v]) => {
    text = text.replaceAll(`{${k}}`, String(v));
  });
  return text;
}

export function applyI18n() {
  document.documentElement.lang = currentLang === "en" ? "en" : "zh-Hant";
  document.title = t("pageTitle");
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.getAttribute("data-i18n");
    el.textContent = t(key);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    const key = el.getAttribute("data-i18n-placeholder");
    el.setAttribute("placeholder", t(key));
  });
}

export function initLanguageSelector(selectId, onLanguageChanged) {
  const langSelect = document.getElementById(selectId);
  if (!langSelect) return;

  currentLang = detectLanguage();
  langSelect.value = currentLang;
  applyI18n();

  langSelect.addEventListener("change", async (event) => {
    setLanguage(event.target.value);
    applyI18n();
    if (typeof onLanguageChanged === "function") {
      await onLanguageChanged(currentLang);
    }
  });
}
