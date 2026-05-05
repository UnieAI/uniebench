import { t } from "./i18n.js";

export function setStatus(id, message, type) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = message;
  el.className = "status" + (type ? " " + type : "");
}

export function num(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return t("na");
  return v;
}

export function pct(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return null;
  return Math.max(0, Math.min(100, Number(v)));
}

export function shortenGpuName(name) {
  const text = String(name || "");
  if (text.length <= 20) return text;
  return text.slice(0, 16) + "...";
}

export function formatMemText(used, total) {
  const usedVal = Number(used);
  const totalVal = Number(total);
  if (!Number.isFinite(usedVal) || !Number.isFinite(totalVal) || totalVal <= 0) return t("na");
  const p = Math.max(0, Math.min(100, (usedVal / totalVal) * 100));
  return `${usedVal}MB/${totalVal}MB (${p.toFixed(1)}%)`;
}

export function memPct(used, total) {
  const usedVal = Number(used);
  const totalVal = Number(total);
  if (!Number.isFinite(usedVal) || !Number.isFinite(totalVal) || totalVal <= 0) return 0;
  return Math.max(0, Math.min(100, (usedVal / totalVal) * 100));
}

export function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
