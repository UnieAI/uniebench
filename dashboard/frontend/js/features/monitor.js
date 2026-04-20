import { requestJson } from "../core/api.js";
import { t } from "../core/i18n.js";
import { formatMemText, memPct, num, pct, setStatus, shortenGpuName } from "../core/ui.js";

function setGpuBodyMessage(messageKey) {
  const gpuBody = document.getElementById("gpuBody");
  if (!gpuBody) return;
  gpuBody.innerHTML = `<tr><td colspan="6">${t(messageKey)}</td></tr>`;
}

function renderSystem(system) {
  const cpuEl = document.getElementById("cpuUsage");
  const ramPctEl = document.getElementById("ramUsagePct");
  const ramMbEl = document.getElementById("ramUsageMb");

  if (!cpuEl || !ramPctEl || !ramMbEl) return;

  if (!system) {
    cpuEl.textContent = t("na");
    ramPctEl.textContent = t("na");
    ramMbEl.textContent = t("na");
    return;
  }

  cpuEl.textContent = `${num(system.cpu_percent)}%`;
  ramPctEl.textContent = `${num(system.ram_percent)}%`;
  ramMbEl.textContent = `${num(system.ram_used_mb)} / ${num(system.ram_total_mb)}`;
}

export async function refreshMonitor() {
  const gpuBody = document.getElementById("gpuBody");
  if (!gpuBody) return;

  try {
    const { ok, status, data } = await requestJson("/api/gpu");
    renderSystem(data.system || null);

    if (!ok) {
      setStatus("gpuStatus", t("statusFetchFail", { reason: data.error || data.detail || status }), "err");
      setGpuBodyMessage("rowNoData");
      return;
    }

    if (!data.available) {
      setStatus("gpuStatus", t("statusGpuUnavailable", { reason: data.error || status }), "err");
      setGpuBodyMessage("rowNoData");
      return;
    }

    setStatus("gpuStatus", t("statusUpdated", { time: data.time }), "ok");
    if (!data.gpus || data.gpus.length === 0) {
      setGpuBodyMessage("rowNoGpu");
      return;
    }

    gpuBody.innerHTML = data.gpus.map((g) => `
      <tr>
        <td>${g.index}</td>
        <td><span class="gpu-name" title="${g.name || ""}">${shortenGpuName(g.name || t("na"))}</span></td>
        <td>
          <div class="util-wrap">
            <div class="util-bar">
              <div class="util-fill" style="width: ${pct(g.utilization_gpu_pct) === null ? 0 : pct(g.utilization_gpu_pct)}%"></div>
            </div>
            <span class="util-text">${pct(g.utilization_gpu_pct) === null ? t("na") : pct(g.utilization_gpu_pct) + "%"}</span>
          </div>
        </td>
        <td>
          <div class="mem-wrap">
            <div class="mem-bar">
              <div class="mem-fill" style="width: ${memPct(g.memory_used_mb, g.memory_total_mb)}%"></div>
            </div>
            <div class="mem-text">${formatMemText(g.memory_used_mb, g.memory_total_mb)}</div>
          </div>
        </td>
        <td>${g.temperature_c}</td>
        <td>${g.power_draw_w}</td>
      </tr>
    `).join("");
  } catch (err) {
    renderSystem(null);
    setStatus("gpuStatus", t("statusConnError", { reason: err }), "err");
    setGpuBodyMessage("rowCheckApi");
  }
}

export function initMonitor() {
  refreshMonitor();
}
