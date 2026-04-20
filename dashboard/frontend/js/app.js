import { initTabs } from "./core/tabs.js";
import { applyI18n, initLanguageSelector } from "./core/i18n.js";
import { initMonitor, refreshMonitor } from "./features/monitor.js";
import { initConfigEditor, loadConfig } from "./features/configEditor.js";
import { initScriptsFeature, refreshScripts, rerenderScriptsUi } from "./features/scripts.js";

const TAB_PARTIALS = {
  gpu: "./partials/tab-monitor.html",
  config: "./partials/tab-config.html",
  scripts: "./partials/tab-scripts.html",
};

let activeTab = "gpu";
let monitorPollingStarted = false;

function getTabContentRoot() {
  return document.getElementById("tabContent");
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
  await loadTabPartial(tab);
  activeTab = tab;

  if (tab === "gpu") {
    initMonitor();
    if (!monitorPollingStarted) {
      setInterval(refreshMonitor, 2000);
      monitorPollingStarted = true;
    }
    return;
  }

  if (tab === "config") {
    initConfigEditor();
    await loadConfig();
    return;
  }

  if (tab === "scripts") {
    initScriptsFeature();
    rerenderScriptsUi();
    await refreshScripts();
  }
}

function detectInitialTab() {
  const activeBtn = document.querySelector(".tab-btn.active");
  return activeBtn?.dataset.tab || "gpu";
}

async function onLanguageChanged() {
  if (activeTab === "gpu") {
    await refreshMonitor();
    return;
  }

  if (activeTab === "config") {
    await loadConfig();
    return;
  }

  if (activeTab === "scripts") {
    rerenderScriptsUi();
    await refreshScripts();
  }
}

async function init() {
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
