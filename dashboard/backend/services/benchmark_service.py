from pathlib import Path
import threading
from typing import Any, Dict, List, Tuple

import yaml


DEFAULT_PROFILE_ID = "default"
DEFAULT_DATASET_PATH = "/workspace/jeff/Benchmark-Autotest/datasets/neural-bridge/rag-dataset-12000/data/train-00000-of-00001-9df3a936e1f63191.parquet"
DEFAULT_NAME_OPTIONS = ["inferencemax", "vllm-bench"]
DEFAULT_NAME_SELECTED = ["inferencemax"]
DEFAULT_ENDPOINT_TYPE = "completions"
DEFAULT_TOKEN_LENGTHS = ["none/1024"]
DEFAULT_AUDIO_TOKEN_LENGTHS = ["none/none"]
DEFAULT_CONCURRENCY = [1, 16, 32, 64, 128, 256, 512]
DEFAULT_REQUEST_RATE = [1, 2, 4, 8, 16, 32, 64, 128, 192, 256, 320, 384]
CONCURRENCY_OPTIONS = [2**i for i in range(12)]  # 1..2048
REQUEST_RATE_OPTIONS = [1, 2, 4, 8, 16, 32, 64, 128, 192, 256, 320, 384]
MODEL_NAME_EXPRESSION = "${server.model_name}"

KEY_DEFAULT_CONFIG = "default_config"
KEY_BENCHMARK = "benchmark"


def _read_config_dict(config_path: Path) -> Dict[str, Any]:
    if not config_path.exists():
        return {}
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _normalize_id(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return DEFAULT_PROFILE_ID
    text = text.replace("\\", "/")
    if "/" in text or ".." in text:
        return DEFAULT_PROFILE_ID
    return text


def _normalize_name_list(raw: Any) -> List[str]:
    values = raw if isinstance(raw, list) else []
    names: List[str] = []
    for item in values:
        text = str(item or "").strip()
        if text in DEFAULT_NAME_OPTIONS and text not in names:
            names.append(text)
    return names or list(DEFAULT_NAME_SELECTED)


def _normalize_endpoint_type(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if text in {"chat", "completions", "audio"}:
        return text
    return DEFAULT_ENDPOINT_TYPE


def _normalize_dataset_path(raw: Any) -> str:
    text = str(raw or "").strip()
    return text or DEFAULT_DATASET_PATH


def _normalize_audio_meta_field(raw: Any) -> str:
    return str(raw or "").strip()


def _parse_token_length(text: str) -> Tuple[str, str | int] | None:
    raw = str(text or "").strip()
    if "/" not in raw:
        return None
    input_len, output_len = raw.split("/", 1)
    input_len = input_len.strip() or "none"
    output_text = output_len.strip().lower()
    if output_text == "none":
        return input_len, "none"
    try:
        output_int = int(output_len.strip())
    except (TypeError, ValueError):
        return None
    if output_int <= 0:
        return None
    return input_len, output_int


def _normalize_token_lengths(raw: Any) -> List[str]:
    values = raw if isinstance(raw, list) else []
    out: List[str] = []
    for item in values:
        parsed = _parse_token_length(str(item))
        if parsed is None:
            continue
        text = f"{parsed[0]}/{parsed[1]}"
        if text not in out:
            out.append(text)
    return out or list(DEFAULT_TOKEN_LENGTHS)


def _normalize_concurrency(raw: Any) -> List[int]:
    values = raw if isinstance(raw, list) else []
    out: List[int] = []
    for item in values:
        try:
            num = int(item)
        except (TypeError, ValueError):
            continue
        if num in CONCURRENCY_OPTIONS and num not in out:
            out.append(num)
    return out or list(DEFAULT_CONCURRENCY)


def _normalize_request_rate(raw: Any) -> List[int]:
    values = raw if isinstance(raw, list) else []
    out: List[int] = []
    for item in values:
        try:
            num = int(item)
        except (TypeError, ValueError):
            continue
        if num in REQUEST_RATE_OPTIONS and num not in out:
            out.append(num)
    return out or list(DEFAULT_REQUEST_RATE)


def _default_profile() -> Dict[str, Any]:
    return {
        "id": DEFAULT_PROFILE_ID,
        "name": list(DEFAULT_NAME_SELECTED),
        "endpoint_type": DEFAULT_ENDPOINT_TYPE,
        "dataset_path": DEFAULT_DATASET_PATH,
        "subset": "",
        "split": "",
        "token_lengths": list(DEFAULT_TOKEN_LENGTHS),
        "concurrency": list(DEFAULT_CONCURRENCY),
        "request_rate": list(DEFAULT_REQUEST_RATE),
    }


def _profile_from_yaml_row(row: Any) -> Dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    profile_id = _normalize_id(row.get("id"))
    cfg = row.get("config")
    if not isinstance(cfg, dict):
        cfg = {}

    token_lengths_raw = []
    for item in cfg.get("token_lengths", []) if isinstance(cfg.get("token_lengths"), list) else []:
        if not isinstance(item, dict):
            continue
        input_len = str(item.get("input_len", "none") or "none").strip()
        output_len = item.get("output_len", "")
        parsed = _parse_token_length(f"{input_len}/{output_len}")
        if parsed is None:
            continue
        token_lengths_raw.append(f"{parsed[0]}/{parsed[1]}")

    endpoint_type = _normalize_endpoint_type(cfg.get("endpoint_type"))
    profile = {
        "id": profile_id,
        "name": _normalize_name_list(cfg.get("name", [])),
        "endpoint_type": endpoint_type,
        "dataset_path": _normalize_dataset_path(cfg.get("dataset_path")),
        "subset": _normalize_audio_meta_field(cfg.get("subset", "")),
        "split": _normalize_audio_meta_field(cfg.get("split", "")),
        "token_lengths": _normalize_token_lengths(token_lengths_raw),
        "concurrency": _normalize_concurrency(cfg.get("concurrency", [])),
        "request_rate": _normalize_request_rate(cfg.get("request_rate", [])),
    }
    if endpoint_type == "audio":
        profile["token_lengths"] = list(DEFAULT_AUDIO_TOKEN_LENGTHS)
        profile["concurrency"] = []
    else:
        profile["subset"] = ""
        profile["split"] = ""
        profile["request_rate"] = []
    return profile


def get_benchmark_config(config_path: Path) -> Dict[str, Any]:
    data = _read_config_dict(config_path)
    default_config = data.get(KEY_DEFAULT_CONFIG)
    benchmark_rows = default_config.get(KEY_BENCHMARK) if isinstance(default_config, dict) else None
    rows = benchmark_rows if isinstance(benchmark_rows, list) else []

    profiles: List[Dict[str, Any]] = []
    seen = set()
    for row in rows:
        profile = _profile_from_yaml_row(row)
        if profile is None:
            continue
        profile_id = profile["id"]
        if profile_id in seen:
            continue
        seen.add(profile_id)
        profiles.append(profile)

    if not profiles:
        profiles = [_default_profile()]

    token_length_options = list(DEFAULT_TOKEN_LENGTHS)
    for profile in profiles:
        for token in profile["token_lengths"]:
            if token not in token_length_options:
                token_length_options.append(token)

    return {
        "profiles": profiles,
        "name_options": list(DEFAULT_NAME_OPTIONS),
        "token_length_options": token_length_options,
        "concurrency_options": list(CONCURRENCY_OPTIONS),
        "request_rate_options": list(REQUEST_RATE_OPTIONS),
    }


def save_benchmark_config(config_path: Path, lock: threading.Lock, payload_profiles: List[Dict[str, Any]]) -> Dict[str, Any]:
    normalized: List[Dict[str, Any]] = []
    seen = set()

    for raw in payload_profiles or []:
        profile_id = _normalize_id(raw.get("id") if isinstance(raw, dict) else "")
        if profile_id in seen:
            continue
        seen.add(profile_id)
        profile = {
            "id": profile_id,
            "name": _normalize_name_list(raw.get("name", []) if isinstance(raw, dict) else []),
            "endpoint_type": _normalize_endpoint_type(raw.get("endpoint_type") if isinstance(raw, dict) else ""),
            "dataset_path": _normalize_dataset_path(raw.get("dataset_path") if isinstance(raw, dict) else ""),
            "subset": _normalize_audio_meta_field(raw.get("subset", "") if isinstance(raw, dict) else ""),
            "split": _normalize_audio_meta_field(raw.get("split", "") if isinstance(raw, dict) else ""),
            "token_lengths": _normalize_token_lengths(raw.get("token_lengths", []) if isinstance(raw, dict) else []),
            "concurrency": _normalize_concurrency(raw.get("concurrency", []) if isinstance(raw, dict) else []),
            "request_rate": _normalize_request_rate(raw.get("request_rate", []) if isinstance(raw, dict) else []),
        }
        if profile["endpoint_type"] == "audio":
            profile["token_lengths"] = list(DEFAULT_AUDIO_TOKEN_LENGTHS)
            profile["concurrency"] = []
        else:
            profile["subset"] = ""
            profile["split"] = ""
            profile["request_rate"] = []
        normalized.append(profile)

    if not normalized:
        normalized = [_default_profile()]

    benchmark_yaml_rows: List[Dict[str, Any]] = []
    for profile in normalized:
        token_lengths_yaml = []
        for token_text in profile["token_lengths"]:
            parsed = _parse_token_length(token_text)
            if parsed is None:
                continue
            token_lengths_yaml.append({
                "input_len": parsed[0],
                "output_len": parsed[1],
            })
        if not token_lengths_yaml:
            token_lengths_yaml = [{"input_len": "none", "output_len": 1024}]

        config_payload = {
            "name": profile["name"],
            "endpoint_type": profile["endpoint_type"],
            "model_name": MODEL_NAME_EXPRESSION,
            "dataset_path": profile["dataset_path"],
            "token_lengths": token_lengths_yaml,
        }
        if profile["endpoint_type"] == "audio":
            config_payload["subset"] = profile["subset"]
            config_payload["split"] = profile["split"]
            config_payload["request_rate"] = profile["request_rate"]
        else:
            config_payload["concurrency"] = profile["concurrency"]

        benchmark_yaml_rows.append({
            "id": profile["id"],
            "config": config_payload,
        })

    with lock:
        data = _read_config_dict(config_path)
        default_config = data.get(KEY_DEFAULT_CONFIG)
        if not isinstance(default_config, dict):
            default_config = {}
            data[KEY_DEFAULT_CONFIG] = default_config
        default_config[KEY_BENCHMARK] = benchmark_yaml_rows
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    return get_benchmark_config(config_path)
