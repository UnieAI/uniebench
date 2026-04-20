import { initTabs } from "./core/tabs.js";
import { applyI18n, initLanguageSelector } from "./core/i18n.js";
import { initBenchmarkConfigFeature, loadBenchmarkConfig } from "./features/benchmarkConfig.js";
import { initMonitor, refreshMonitor, setMonitorFloatingMode } from "./features/monitor.js";
import { initGlobalConfigFeature, loadGlobalConfig } from "./features/globalConfig.js";
import { initReadyToRunFeature, loadReadyToRun } from "./features/readyToRun.js";
import { initScriptsFeature, refreshScripts, rerenderScriptsUi } from "./features/scripts.js";

const TAB_PARTIALS = {
  gpu: "./partials/tab-monitor.html",
  scripts: "./partials/tab-scripts.html",
  globalConfig: "./partials/tab-global-config.html",
  benchmarkConfig: "./partials/tab-benchmark.html",
  readyToRun: "./partials/tab-ready.html",
};
const LAST_TAB_KEY = "dashboard_last_tab";

let activeTab = "gpu";
let monitorPollingStarted = false;

function syncTabButtonActive(tab) {
  const buttons = document.querySelectorAll(".tab-btn");
  buttons.forEach((btn) => {
    const isActive = btn.dataset.tab === tab;
    btn.classList.toggle("active", isActive);
  });
}

function getTabContentRoot() {
  return document.getElementById("tabContent");
}

function ensureMonitorPolling() {
  if (monitorPollingStarted) return;
  setInterval(refreshMonitor, 2000);
  monitorPollingStarted = true;
}

async function loadTabPartial(tab) {
  const root = getTabContentRoot();
  if (!root) return;

  const url = TAB_PARTIALS[tab];
  if (!url) return;

  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Failed to load tab partial: ${tab} (${res.status})`);
  }

  root.innerHTML = await res.text();
  applyI18n();
}

async function activateTab(tab) {
  if (!(tab in TAB_PARTIALS)) {
    tab = "gpu";
  }
  syncTabButtonActive(tab);
  await loadTabPartial(tab);
  activeTab = tab;
  localStorage.setItem(LAST_TAB_KEY, tab);
  setMonitorFloatingMode(tab !== "gpu");
  ensureMonitorPolling();
  await refreshMonitor();

  if (tab === "gpu") {
    initMonitor();
    return;
  }

  if (tab === "scripts") {
    initScriptsFeature();
    rerenderScriptsUi();
    await refreshScripts();
    return;
  }

  if (tab === "globalConfig") {
    initGlobalConfigFeature();
    await loadGlobalConfig();
    return;
  }

  if (tab === "benchmarkConfig") {
    initBenchmarkConfigFeature();
    await loadBenchmarkConfig();
    return;
  }

  if (tab === "readyToRun") {
    initReadyToRunFeature();
    await loadReadyToRun();
    return;
  }
}

function detectInitialTab() {
  const saved = localStorage.getItem(LAST_TAB_KEY);
  if (saved && saved in TAB_PARTIALS) {
    return saved;
  }
  const activeBtn = document.querySelector(".tab-btn.active");
  return activeBtn?.dataset.tab || "gpu";
}

async function onLanguageChanged() {
  if (activeTab !== "gpu") {
    setMonitorFloatingMode(true);
  }

  if (activeTab === "gpu") {
    await refreshMonitor();
    return;
  }

  if (activeTab === "scripts") {
    rerenderScriptsUi();
    await refreshScripts();
    return;
  }

  if (activeTab === "globalConfig") {
    await loadGlobalConfig();
    return;
  }

  if (activeTab === "benchmarkConfig") {
    await loadBenchmarkConfig();
    return;
  }

  if (activeTab === "readyToRun") {
    await loadReadyToRun();
  }
}

async function init() {
  ensureMonitorPolling();
  await activateTab(detectInitialTab());
  initLanguageSelector("langSelect", onLanguageChanged);
  initTabs({ onTabSelected: activateTab });
}

init().catch((err) => {
  const root = getTabContentRoot();
  if (root) {
    root.innerHTML = `<section class="panel active"><div class="status err">${String(err)}</div></section>`;
  }
});
