import json
from pathlib import Path
import threading
from typing import Any

import yaml


def read_config(config_path: Path) -> str:
    return config_path.read_text(encoding="utf-8")


def validate_config_yaml(content: str) -> Any:
    return yaml.safe_load(content)


def save_config(config_path: Path, content: str, lock: threading.Lock) -> None:
    with lock:
        config_path.write_text(content, encoding="utf-8")


def _read_config_dict(config_path: Path) -> dict:
    if not config_path.exists():
        return {}
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def get_runtime_target(config_path: Path) -> dict:
    data = _read_config_dict(config_path)
    server = data.get("server")
    benchmark = data.get("benchmark")
    server_id = str(server.get("id", "")).strip() if isinstance(server, dict) else ""
    benchmark_id = str(benchmark.get("id", "")).strip() if isinstance(benchmark, dict) else ""
    return {
        "server_id": server_id,
        "benchmark_id": benchmark_id,
    }


def update_runtime_target(config_path: Path, lock: threading.Lock, server_id: str | None = None, benchmark_id: str | None = None) -> dict:
    with lock:
        data = _read_config_dict(config_path)

        if server_id is not None:
            value = str(server_id).strip()
            server = data.get("server")
            if not isinstance(server, dict):
                server = {}
                data["server"] = server
            server["id"] = value

        if benchmark_id is not None:
            value = str(benchmark_id).strip()
            benchmark = data.get("benchmark")
            if not isinstance(benchmark, dict):
                benchmark = {}
                data["benchmark"] = benchmark
            benchmark["id"] = value

        config_path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    return get_runtime_target(config_path)


def get_sheet_name_options(sheet_id_list_path: Path) -> list[str]:
    if not sheet_id_list_path.exists():
        return []
    try:
        loaded = json.loads(sheet_id_list_path.read_text(encoding="utf-8"))
        # Flatten nested dictionaries to collect all keys
        all_keys = set(loaded.keys())
        for value in loaded.values():
            if isinstance(value, dict):
                all_keys.update(value.keys())
        loaded = all_keys
    except Exception:
        return []
    if not isinstance(loaded, dict):
        return []
    return [str(key) for key in loaded.keys() if str(key).strip()]


def get_test_meta(config_path: Path, sheet_id_list_path: Path) -> dict:
    data = _read_config_dict(config_path)
    autotest = data.get("autotest")
    server = data.get("server")
    test_name = str(autotest.get("name", "")).strip() if isinstance(autotest, dict) else ""
    sheet_name = str(autotest.get("sheet_name", "")).strip() if isinstance(autotest, dict) else ""
    platform_name = str(server.get("platform", "")).strip() if isinstance(server, dict) else ""
    return {
        "test_name": test_name,
        "sheet_name": sheet_name,
        "platform_name": platform_name,
        "sheet_name_options": get_sheet_name_options(sheet_id_list_path),
    }


def update_test_meta(
    config_path: Path,
    lock: threading.Lock,
    test_name: str | None = None,
    sheet_name: str | None = None,
    platform_name: str | None = None,
) -> dict:
    with lock:
        data = _read_config_dict(config_path)

        autotest = data.get("autotest")
        if not isinstance(autotest, dict):
            autotest = {}
            data["autotest"] = autotest
        server = data.get("server")
        if not isinstance(server, dict):
            server = {}
            data["server"] = server

        if test_name is not None:
            autotest["name"] = str(test_name).strip()
        if sheet_name is not None:
            autotest["sheet_name"] = str(sheet_name).strip()
        if platform_name is not None:
            server["platform"] = str(platform_name).strip()

        config_path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    return {
        "test_name": str(test_name).strip() if test_name is not None else "",
        "sheet_name": str(sheet_name).strip() if sheet_name is not None else "",
        "platform_name": str(platform_name).strip() if platform_name is not None else "",
    }


def _format_token_length(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None
    input_len = str(item.get("input_len", "none") or "none").strip() or "none"
    output_len = item.get("output_len")
    try:
        output_int = int(output_len)
    except (TypeError, ValueError):
        return None
    return f"{input_len}/{output_int}"


def get_ready_test_items(config_path: Path) -> dict:
    data = _read_config_dict(config_path)
    runtime = get_runtime_target(config_path)
    server_id = runtime.get("server_id", "")
    benchmark_id = runtime.get("benchmark_id", "")

    default_config = data.get("default_config")
    if not isinstance(default_config, dict):
        return {"items": [], "count": 0, "server_id": server_id, "benchmark_id": benchmark_id}

    server_rows = default_config.get("server")
    benchmark_rows = default_config.get("benchmark")
    server_rows = server_rows if isinstance(server_rows, list) else []
    benchmark_rows = benchmark_rows if isinstance(benchmark_rows, list) else []

    selected_server = next((row for row in server_rows if isinstance(row, dict) and str(row.get("id", "")).strip() == server_id), None)
    selected_benchmark = next((row for row in benchmark_rows if isinstance(row, dict) and str(row.get("id", "")).strip() == benchmark_id), None)
    if selected_server is None and server_rows:
        selected_server = next((row for row in server_rows if isinstance(row, dict)), None)
    if selected_benchmark is None and benchmark_rows:
        selected_benchmark = next((row for row in benchmark_rows if isinstance(row, dict)), None)

    containers = []
    if isinstance(selected_server, dict):
        cfg = selected_server.get("config")
        if isinstance(cfg, dict) and isinstance(cfg.get("container"), list):
            containers = [item for item in cfg.get("container") if isinstance(item, dict)]

    token_lengths = []
    endpoint_type = ""
    concurrency = []
    request_rate = []
    if isinstance(selected_benchmark, dict):
        cfg = selected_benchmark.get("config")
        if isinstance(cfg, dict):
            endpoint_type = str(cfg.get("endpoint_type", "") or "").strip().lower()
            raw_token_lengths = cfg.get("token_lengths")
            if isinstance(raw_token_lengths, list):
                token_lengths = [_format_token_length(item) for item in raw_token_lengths]
            token_lengths = [item for item in token_lengths if item]
            raw_concurrency = cfg.get("concurrency")
            if isinstance(raw_concurrency, list):
                for c in raw_concurrency:
                    try:
                        concurrency.append(int(c))
                    except (TypeError, ValueError):
                        continue
            raw_request_rate = cfg.get("request_rate")
            if isinstance(raw_request_rate, list):
                for r in raw_request_rate:
                    try:
                        request_rate.append(int(r))
                    except (TypeError, ValueError):
                        continue

    items = []
    token_values = token_lengths if token_lengths else ["N/A"]
    rate_values = (request_rate if request_rate else ["N/A"]) if endpoint_type == "audio" else (concurrency if concurrency else ["N/A"])
    for container in containers:
        name = str(container.get("name", "")).strip() or "unknown"
        for token_text in token_values:
            for rate in rate_values:
                items.append(f"{name} - {token_text} - {rate}")

    return {
        "items": items,
        "count": len(items),
        "server_id": server_id,
        "benchmark_id": benchmark_id,
    }
