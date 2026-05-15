import re
import subprocess
from typing import Dict, Optional

import requests


def _run_cmd(cmd: list[str], timeout: int = 5) -> str:
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if completed.returncode != 0:
        return ""
    return (completed.stdout or "").strip()


def _first_non_empty(lines: list[str]) -> Optional[str]:
    for line in lines:
        text = line.strip()
        if text:
            return text
    return None


def get_cpu_model() -> str:
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "unknown"


def get_gpu_model() -> str:
    # NVIDIA path
    output = _run_cmd(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"])
    if output:
        first = _first_non_empty(output.splitlines())
        if first:
            return first

    # ROCm path
    output = _run_cmd(["rocminfo"], timeout=10)
    if output:
        for line in output.splitlines():
            if "Marketing Name:" in line:
                return line.split(":", 1)[1].strip()

    return "unknown"


def get_cuda_version() -> str:
    output = _run_cmd(["nvidia-smi"])
    if output:
        match = re.search(r"CUDA Version:\s*([0-9.]+)", output)
        if match:
            return match.group(1)

    output = _run_cmd(["nvcc", "--version"])
    if output:
        match = re.search(r"release\s+([0-9.]+)", output)
        if match:
            return match.group(1)
    return "unknown"


def get_rocm_version() -> str:
    try:
        with open("/opt/rocm/.info/version", "r", encoding="utf-8") as f:
            version = f.read().strip()
            if version:
                return version
    except OSError:
        pass

    output = _run_cmd(["rocm-smi", "--showdriverversion"], timeout=10)
    if output:
        for line in output.splitlines():
            if "Driver version:" in line:
                return line.split(":", 1)[1].strip()

    output = _run_cmd(["rocminfo"], timeout=10)
    if output:
        for line in output.splitlines():
            if "ROCm version:" in line:
                return line.split(":", 1)[1].strip()
    return "unknown"


def get_sample_output(cfg) -> str:
    if cfg.benchmark.endpoint_type == 'audio':
        return 'not supported'
    url = f"{cfg.server.base_url}:{cfg.server.port}/v1/completions"
    payload = {
        "model": cfg.server.model_id,
        "prompt": "Who is Alan Turing?",
        "max_tokens": 100,
        "temperature": 0,
    }

    try:
        response = requests.post(url, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        return f"request_failed or not support(audio): {exc}"
    except ValueError as exc:
        return f"invalid_json: {exc}"

    choices = data.get("choices", [])
    if not choices:
        return "empty_choices"
    text = choices[0].get("text")
    if isinstance(text, str):
        return text.strip()
    return "missing_text"


def collect_runtime_metadata(cfg) -> Dict[str, str]:
    return {
        "cuda_version": get_cuda_version(),
        "rocm_version": get_rocm_version(),
        "cpu_model": get_cpu_model(),
        "gpu_model": get_gpu_model(),
        "SampleOutput": get_sample_output(cfg),
    }
