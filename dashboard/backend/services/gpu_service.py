import shutil
import subprocess
from typing import Any, Dict, List, Optional

import psutil


def _to_float(text: str) -> Optional[float]:
    clean = text.strip()
    if clean in {"", "N/A", "[N/A]"}:
        return None
    try:
        return float(clean)
    except ValueError:
        return None


def _parse_nvidia_smi_output(raw: str) -> List[Dict[str, Any]]:
    gpus: List[Dict[str, Any]] = []
    for line in raw.strip().splitlines():
        parts = [item.strip() for item in line.split(",")]
        if len(parts) != 7:
            continue
        try:
            index = int(parts[0])
        except ValueError:
            continue
        gpus.append(
            {
                "index": index,
                "name": parts[1],
                "utilization_gpu_pct": _to_float(parts[2]),
                "memory_used_mb": _to_float(parts[3]),
                "memory_total_mb": _to_float(parts[4]),
                "temperature_c": _to_float(parts[5]),
                "power_draw_w": _to_float(parts[6]),
            }
        )
    return gpus


def get_system_usage() -> Dict[str, float]:
    mem = psutil.virtual_memory()
    return {
        "cpu_percent": round(psutil.cpu_percent(interval=0.1), 2),
        "ram_used_mb": round(mem.used / (1024 * 1024), 1),
        "ram_total_mb": round(mem.total / (1024 * 1024), 1),
        "ram_percent": round(mem.percent, 2),
    }


def get_gpu_status(now_iso: str) -> Dict[str, Any]:
    system = get_system_usage()
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return {
            "available": False,
            "time": now_iso,
            "error": "nvidia-smi not found in container",
            "system": system,
            "gpus": [],
        }

    cmd = [
        nvidia_smi,
        "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
        "--format=csv,noheader,nounits",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=4)
    except subprocess.TimeoutExpired as exc:
        return {
            "available": False,
            "time": now_iso,
            "error": f"nvidia-smi timeout: {exc}",
            "system": system,
            "gpus": [],
        }

    if proc.returncode != 0:
        return {
            "available": False,
            "time": now_iso,
            "error": proc.stderr.strip() or "nvidia-smi failed",
            "system": system,
            "gpus": [],
        }

    gpus = _parse_nvidia_smi_output(proc.stdout)
    return {"available": True, "time": now_iso, "system": system, "gpus": gpus}
