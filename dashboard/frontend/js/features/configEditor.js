import { requestJson } from "../core/api.js";
import { t } from "../core/i18n.js";
import { setStatus } from "../core/ui.js";

export async function loadConfig() {
  const editor = document.getElementById("configEditor");
  if (!editor) return;

  try {
    const { ok, status, data } = await requestJson("/api/config");
    if (!ok) {
      throw new Error(data.detail || status);
    }
    const activeEditor = document.getElementById("configEditor");
    if (!activeEditor) return;
    activeEditor.value = data.content || "";
    setStatus("configStatus", t("statusConfigLoaded", { path: data.path, time: data.time }), "ok");
  } catch (err) {
    setStatus("configStatus", t("statusConfigLoadFail", { reason: err }), "err");
  }
}

export async function saveConfig() {
  const editor = document.getElementById("configEditor");
  if (!editor) return;
  const content = editor.value;

  try {
    const { ok, status, data } = await requestJson("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    if (!ok) {
      throw new Error(data.detail || status);
    }
    setStatus("configStatus", t("statusConfigSaved", { path: data.path, time: data.time }), "ok");
  } catch (err) {
    setStatus("configStatus", t("statusConfigSaveFail", { reason: err }), "err");
  }
}

export function initConfigEditor() {
  const loadBtn = document.getElementById("loadConfig");
  const saveBtn = document.getElementById("saveConfig");
  if (!loadBtn || !saveBtn) return;

  loadBtn.addEventListener("click", loadConfig);
  saveBtn.addEventListener("click", saveConfig);
}
