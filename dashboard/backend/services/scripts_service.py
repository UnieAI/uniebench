import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import stat
import subprocess
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib import error, parse, request
import yaml


TEST_INTERVAL_SECONDS = 10
TEST_TIMEOUT_SECONDS = 10 * 60
MAX_LOG_LINES = 800

STEP_HEALTH = "health"
STEP_MODELS = "models"
STEP_COMPLETIONS = "completions"
STEP_KEYS = (STEP_HEALTH, STEP_MODELS, STEP_COMPLETIONS)

STATUS_TESTING = "testing"
STATUS_SUCCESS = "success"
STATUS_FAIL = "fail"

_SCRIPT_TEST_LOCK = threading.RLock()
_SCRIPT_TEST_STATE: Optional[Dict[str, Any]] = None
_SCRIPT_TEST_THREAD: Optional[threading.Thread] = None
_SCRIPT_TEST_RESULTS: Dict[str, Dict[str, Any]] = {}

DEFAULT_GROUP = "default"
TEST_HELPER_GROUP = "__test__"
CONFIG_DASHBOARD_KEY = "dashboard"
CONFIG_SCRIPTS_KEY = "scripts"
CONFIG_ENABLED_KEY = "enabled"
CONFIG_METADATA_KEY = "metadata"
CONFIG_GLOBAL_CONFIG_KEY = "global_config"
CONFIG_MODEL_PATH_KEY = "model_path"
CONFIG_MODEL_NAMES_KEY = "model_names"
CONFIG_DEFAULT_BASE_URL_KEY = "default_base_url"
DEFAULT_MODEL_PATH = "/home/ubuntu/models"
DEFAULT_BASE_URL = "http://localhost"

SCRIPT_META_FIELDS = ("tp_size", "model_name", "model_id", "base_url", "port")
CONFIG_DEFAULT_CONFIG_KEY = "default_config"
CONFIG_SERVER_KEY = "server"
CONFIG_CONFIG_KEY = "config"
CONFIG_CONTAINER_KEY = "container"


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def pick_scripts_dir(candidates: Iterable[Path], create: bool = False) -> Path:
    candidate_list = list(candidates)
    for candidate in candidate_list:
        if candidate.exists() and candidate.is_dir():
            return candidate

    target = candidate_list[0]
    if create:
        target.mkdir(parents=True, exist_ok=True)
    return target


def _normalize_group_name(group_name: str) -> str:
    text = (group_name or "").strip()
    if text == "":
        return DEFAULT_GROUP
    if "/" in text or "\\" in text or ".." in text:
        raise ValueError("Invalid group name")
    if Path(text).name != text:
        raise ValueError("Invalid group name")
    if text == TEST_HELPER_GROUP:
        raise ValueError("Reserved group name")
    return text


def _normalize_script_file_name(raw_name: str) -> str:
    clean = Path(raw_name).name.strip()
    if clean == "":
        raise ValueError("Script name is empty")
    if "/" in clean or "\\" in clean or ".." in clean:
        raise ValueError("Invalid script name")
    if not clean.endswith(".sh"):
        clean += ".sh"
    return clean


def _normalize_rel_script_path(raw_path: str) -> str:
    text = (raw_path or "").strip().replace("\\", "/")
    if text == "":
        raise ValueError("Script path is empty")
    if text.startswith("/"):
        raise ValueError("Invalid script path")

    parts = [p for p in text.split("/") if p not in {"", "."}]
    if any(p == ".." for p in parts):
        raise ValueError("Invalid script path")

    if len(parts) == 1:
        group = DEFAULT_GROUP
        name = _normalize_script_file_name(parts[0])
    else:
        group = _normalize_group_name(parts[0])
        name = _normalize_script_file_name(parts[-1])
    return f"{group}/{name}"


def ensure_default_group_structure(script_dir: Path) -> None:
    default_dir = script_dir / DEFAULT_GROUP
    default_dir.mkdir(parents=True, exist_ok=True)

    for script_path in sorted(script_dir.glob("*.sh")):
        if not script_path.is_file():
            continue
        target_path = default_dir / script_path.name
        if target_path.exists():
            if target_path.read_text(encoding="utf-8") == script_path.read_text(encoding="utf-8"):
                script_path.unlink()
                continue
            raise ValueError(f"Script conflict while moving into {DEFAULT_GROUP}: {script_path.name}")
        shutil.move(str(script_path), str(target_path))


def resolve_script_path(script_dir: Path, script_ref: str) -> Tuple[Path, str]:
    normalized_rel = _normalize_rel_script_path(script_ref)
    resolved_dir = script_dir.resolve()
    resolved_path = (script_dir / normalized_rel).resolve()
    if resolved_path.suffix != ".sh":
        raise ValueError("Invalid script path")
    if resolved_dir not in resolved_path.parents:
        raise ValueError("Invalid script path")
    return resolved_path, normalized_rel


def list_scripts(script_dir: Path) -> List[Dict[str, str]]:
    ensure_default_group_structure(script_dir)
    resolved_dir = script_dir.resolve()
    rows: List[Dict[str, str]] = []
    for group_dir in sorted(script_dir.iterdir(), key=lambda p: p.name):
        if not group_dir.is_dir():
            continue
        if group_dir.name == TEST_HELPER_GROUP:
            continue
        group = _normalize_group_name(group_dir.name)
        for p in sorted(group_dir.glob("*.sh")):
            if not p.is_file():
                continue
            rel = p.resolve().relative_to(resolved_dir).as_posix()
            normalized_rel = _normalize_rel_script_path(rel)
            _, name = normalized_rel.split("/", 1)
            rows.append({
                "path": normalized_rel,
                "name": name,
                "group": group,
            })
    rows.sort(key=lambda r: (r["group"], r["name"]))
    return rows


def build_host_test_script(script_dir: Path, script_rel_path: str, endpoint_url: str) -> Dict[str, Any]:
    script_path, normalized_rel = resolve_script_path(script_dir, script_rel_path)
    if not script_path.exists() or not script_path.is_file():
        raise FileNotFoundError(f"Script not found: {normalized_rel}")

    endpoint = str(endpoint_url or "").strip() or "http://localhost:8000"
    endpoint = endpoint.rstrip("/")
    helper_dir = script_dir / TEST_HELPER_GROUP
    helper_dir.mkdir(parents=True, exist_ok=True)
    helper_path = helper_dir / "test.sh"
    log_file = "/tmp/host_script_test.log"

    content = "\n".join([
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        f"SCRIPT_PATH={shlex.quote(str(script_path.resolve()))}",
        f"ENDPOINT={shlex.quote(endpoint)}",
        f"LOG_FILE={shlex.quote(log_file)}",
        "FINAL_STATUS=\"PASS\"",
        "FINAL_REASON=\"ok\"",
        "",
        "echo \"[host-test] script=$SCRIPT_PATH\"",
        "echo \"[host-test] endpoint=$ENDPOINT\"",
        "echo \"[host-test] log_file=$LOG_FILE\"",
        "",
        "bash \"$SCRIPT_PATH\" > \"$LOG_FILE\" 2>&1 &",
        "PID=$!",
        "echo \"[host-test] pid=$PID\"",
        "",
        "on_exit() {",
        "  local exit_code=\"$?\"",
        "  if kill -0 \"$PID\" 2>/dev/null; then",
        "    kill \"$PID\" 2>/dev/null || true",
        "    wait \"$PID\" 2>/dev/null || true",
        "  fi",
        "  if [[ \"$exit_code\" -ne 0 && \"$FINAL_STATUS\" == \"PASS\" ]]; then",
        "    FINAL_STATUS=\"FAIL\"",
        "    FINAL_REASON=\"unexpected_error\"",
        "  fi",
        "  echo \"[host-test] log_file=$LOG_FILE\"",
        "  echo \"COPY_THIS_LINE: HOST_TEST_RESULT status=$FINAL_STATUS reason=$FINAL_REASON log_file=$LOG_FILE endpoint=$ENDPOINT script=$SCRIPT_PATH\"",
        "}",
        "trap on_exit EXIT",
        "",
        "health_ok=0",
        "for i in $(seq 1 60); do",
        "  if curl -fsS \"$ENDPOINT/health\" >/dev/null; then",
        "    health_ok=1",
        "    echo \"[host-test] health=PASS\"",
        "    break",
        "  fi",
        "  sleep 10",
        "done",
        "",
        "if [[ \"$health_ok\" -ne 1 ]]; then",
        "  echo \"[host-test] health=FAIL (timeout)\"",
        "  FINAL_STATUS=\"FAIL\"",
        "  FINAL_REASON=\"health_timeout\"",
        "  exit 1",
        "fi",
        "",
        "model_name=$(curl -fsS \"$ENDPOINT/v1/models\" | python3 -c 'import json,sys; d=json.load(sys.stdin); print((d.get(\"data\") or [{}])[0].get(\"id\", \"\"))')",
        "if [[ -z \"$model_name\" ]]; then",
        "  echo \"[host-test] models=FAIL (no model id)\"",
        "  FINAL_STATUS=\"FAIL\"",
        "  FINAL_REASON=\"models_missing_id\"",
        "  exit 1",
        "fi",
        "echo \"[host-test] models=PASS model=$model_name\"",
        "export MODEL_NAME=\"$model_name\"",
        "",
        "payload=$(python3 - <<'PY'",
        "import json, os",
        "print(json.dumps({",
        "  \"model\": os.environ.get(\"MODEL_NAME\", \"\"),",
        "  \"prompt\": \"hello\",",
        "  \"max_tokens\": 8",
        "}))",
        "PY",
        ")",
        "MODEL_NAME=\"$model_name\" curl -fsS -X POST \"$ENDPOINT/v1/completions\" \\",
        "  -H 'Content-Type: application/json' \\",
        "  -d \"$payload\" >/dev/null",
        "echo \"[host-test] completions=PASS\"",
        "",
        "FINAL_STATUS=\"PASS\"",
        "FINAL_REASON=\"ok\"",
        "echo \"[host-test] RESULT=PASS\"",
        "",
    ]) + "\n"

    helper_path.write_text(content, encoding="utf-8")
    helper_path.chmod(helper_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    command = f"bash {shlex.quote(str(helper_path.resolve()))}"
    return {
        "script_path": normalized_rel,
        "helper_path": str(helper_path.resolve()),
        "command": command,
        "content": content,
    }


def read_script(script_path: Path) -> str:
    return script_path.read_text(encoding="utf-8")


def write_script(script_path: Path, content: str, lock: threading.Lock) -> None:
    with lock:
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(content, encoding="utf-8")
        script_path.chmod(script_path.stat().st_mode | stat.S_IXUSR)


def create_script_path(script_dir: Path, group: str, name: str) -> Tuple[Path, str]:
    normalized_group = _normalize_group_name(group)
    normalized_name = _normalize_script_file_name(name)
    normalized_rel = f"{normalized_group}/{normalized_name}"
    return resolve_script_path(script_dir, normalized_rel)


def move_script_path(script_dir: Path, source_rel_path: str, target_group: str) -> Tuple[Path, str, str]:
    source_path, normalized_source = resolve_script_path(script_dir, source_rel_path)
    if not source_path.exists() or not source_path.is_file():
        raise FileNotFoundError(f"Script not found: {normalized_source}")

    normalized_group = _normalize_group_name(target_group)
    target_rel = f"{normalized_group}/{source_path.name}"
    target_path, normalized_target = resolve_script_path(script_dir, target_rel)

    if normalized_target == normalized_source:
        return source_path, normalized_source, normalized_target
    if target_path.exists():
        raise FileExistsError(f"Target script already exists: {normalized_target}")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source_path), str(target_path))
    return target_path, normalized_source, normalized_target


def _default_enabled_for_path(script_rel_path: str) -> bool:
    return Path(script_rel_path).name == "default_script.sh"


def _read_config_dict(config_path: Path) -> Dict[str, Any]:
    if not config_path.exists():
        return {}
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _read_enabled_map(config_path: Path) -> Dict[str, bool]:
    data = _read_config_dict(config_path)
    dashboard = data.get(CONFIG_DASHBOARD_KEY)
    if not isinstance(dashboard, dict):
        return {}
    scripts = dashboard.get(CONFIG_SCRIPTS_KEY)
    if not isinstance(scripts, dict):
        return {}
    enabled = scripts.get(CONFIG_ENABLED_KEY)
    if not isinstance(enabled, dict):
        return {}

    normalized: Dict[str, bool] = {}
    for key, value in enabled.items():
        try:
            normalized_key = _normalize_rel_script_path(str(key))
        except ValueError:
            continue
        normalized[normalized_key] = bool(value)
    return normalized


def _normalize_script_metadata(raw: Any) -> Dict[str, str]:
    if not isinstance(raw, dict):
        return {field: "" for field in SCRIPT_META_FIELDS}
    normalized: Dict[str, str] = {}
    for field in SCRIPT_META_FIELDS:
        value = raw.get(field, "")
        normalized[field] = str(value).strip() if value is not None else ""
    return normalized


def _read_metadata_map(config_path: Path) -> Dict[str, Dict[str, str]]:
    data = _read_config_dict(config_path)
    dashboard = data.get(CONFIG_DASHBOARD_KEY)
    if not isinstance(dashboard, dict):
        return {}
    scripts = dashboard.get(CONFIG_SCRIPTS_KEY)
    if not isinstance(scripts, dict):
        return {}
    metadata = scripts.get(CONFIG_METADATA_KEY)
    if not isinstance(metadata, dict):
        return {}

    normalized: Dict[str, Dict[str, str]] = {}
    for key, value in metadata.items():
        try:
            normalized_key = _normalize_rel_script_path(str(key))
        except ValueError:
            continue
        normalized[normalized_key] = _normalize_script_metadata(value)
    return normalized


def _write_enabled_map(config_path: Path, lock: threading.Lock, enabled_map: Dict[str, bool]) -> None:
    with lock:
        data = _read_config_dict(config_path)
        dashboard = data.get(CONFIG_DASHBOARD_KEY)
        if not isinstance(dashboard, dict):
            dashboard = {}
            data[CONFIG_DASHBOARD_KEY] = dashboard
        scripts = dashboard.get(CONFIG_SCRIPTS_KEY)
        if not isinstance(scripts, dict):
            scripts = {}
            dashboard[CONFIG_SCRIPTS_KEY] = scripts

        scripts[CONFIG_ENABLED_KEY] = dict(sorted(enabled_map.items(), key=lambda kv: kv[0]))
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )


def _write_metadata_map(config_path: Path, lock: threading.Lock, metadata_map: Dict[str, Dict[str, str]]) -> None:
    with lock:
        data = _read_config_dict(config_path)
        dashboard = data.get(CONFIG_DASHBOARD_KEY)
        if not isinstance(dashboard, dict):
            dashboard = {}
            data[CONFIG_DASHBOARD_KEY] = dashboard
        scripts = dashboard.get(CONFIG_SCRIPTS_KEY)
        if not isinstance(scripts, dict):
            scripts = {}
            dashboard[CONFIG_SCRIPTS_KEY] = scripts
        scripts[CONFIG_METADATA_KEY] = dict(sorted(metadata_map.items(), key=lambda kv: kv[0]))
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )


def sync_enabled_map(script_rel_paths: List[str], config_path: Path, lock: threading.Lock) -> Dict[str, bool]:
    enabled_map = _read_enabled_map(config_path)
    valid_paths = {_normalize_rel_script_path(path) for path in script_rel_paths}
    changed = False

    for path in sorted(valid_paths):
        if path not in enabled_map:
            enabled_map[path] = _default_enabled_for_path(path)
            changed = True

    stale = [key for key in enabled_map.keys() if key not in valid_paths]
    if stale:
        for key in stale:
            enabled_map.pop(key, None)
        changed = True

    if changed:
        _write_enabled_map(config_path, lock, enabled_map)
    return enabled_map


def get_script_enabled(script_rel_path: str, config_path: Path) -> bool:
    normalized = _normalize_rel_script_path(script_rel_path)
    enabled_map = _read_enabled_map(config_path)
    if normalized in enabled_map:
        return enabled_map[normalized]
    return _default_enabled_for_path(normalized)


def set_script_enabled(script_rel_path: str, enabled: bool, config_path: Path, lock: threading.Lock) -> Dict[str, Any]:
    normalized = _normalize_rel_script_path(script_rel_path)
    enabled_map = _read_enabled_map(config_path)
    enabled_map[normalized] = bool(enabled)
    _write_enabled_map(config_path, lock, enabled_map)
    return {"path": normalized, "enabled": bool(enabled)}


def move_script_enabled_state(source_rel_path: str, target_rel_path: str, config_path: Path, lock: threading.Lock) -> None:
    normalized_source = _normalize_rel_script_path(source_rel_path)
    normalized_target = _normalize_rel_script_path(target_rel_path)
    enabled_map = _read_enabled_map(config_path)

    if normalized_source in enabled_map:
        enabled_map[normalized_target] = enabled_map.pop(normalized_source)
    else:
        enabled_map[normalized_target] = _default_enabled_for_path(normalized_source)
    _write_enabled_map(config_path, lock, enabled_map)


def get_script_metadata(script_rel_path: str, config_path: Path) -> Dict[str, str]:
    normalized = _normalize_rel_script_path(script_rel_path)
    metadata_map = _read_metadata_map(config_path)
    return _normalize_script_metadata(metadata_map.get(normalized, {}))


def set_script_metadata(script_rel_path: str, metadata: Dict[str, Any], config_path: Path, lock: threading.Lock) -> Dict[str, Any]:
    normalized = _normalize_rel_script_path(script_rel_path)
    metadata_map = _read_metadata_map(config_path)
    normalized_meta = _normalize_script_metadata(metadata or {})
    metadata_map[normalized] = normalized_meta
    _write_metadata_map(config_path, lock, metadata_map)
    return {
        "path": normalized,
        "metadata": normalized_meta,
    }


def move_script_metadata(source_rel_path: str, target_rel_path: str, config_path: Path, lock: threading.Lock) -> None:
    normalized_source = _normalize_rel_script_path(source_rel_path)
    normalized_target = _normalize_rel_script_path(target_rel_path)
    metadata_map = _read_metadata_map(config_path)
    if normalized_source in metadata_map:
        metadata_map[normalized_target] = metadata_map.pop(normalized_source)
        _write_metadata_map(config_path, lock, metadata_map)


def sync_default_config_server_entry(
    config_path: Path,
    lock: threading.Lock,
    group_name: str,
    script_path: Path,
    script_name: str,
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    group_id = _normalize_group_name(group_name)
    meta = _normalize_script_metadata(metadata or {})
    script_path_text = str(script_path.resolve())

    container_item = {
        "path": script_path_text,
        "name": str(script_name or "").strip() or script_path.name,
        "tp_size": _to_int_or_zero(meta["tp_size"]),
        "model_name": meta["model_name"],
        "model_id": meta["model_id"],
        "base_url": meta["base_url"],
        "port": _to_int_or_zero(meta["port"]),
    }

    with lock:
        data = _read_config_dict(config_path)
        default_config = data.get(CONFIG_DEFAULT_CONFIG_KEY)
        if not isinstance(default_config, dict):
            default_config = {}
            data[CONFIG_DEFAULT_CONFIG_KEY] = default_config

        server_rows = default_config.get(CONFIG_SERVER_KEY)
        if not isinstance(server_rows, list):
            server_rows = []
            default_config[CONFIG_SERVER_KEY] = server_rows

        server_entry: Optional[Dict[str, Any]] = None
        for row in server_rows:
            if isinstance(row, dict) and str(row.get("id", "")).strip() == group_id:
                server_entry = row
                break

        if server_entry is None:
            server_entry = {
                "id": group_id,
                "config": {
                    "container": [],
                    "base_url": 0,
                    "port": 0,
                    "model_path": 0,
                    "model_name": 0,
                    "model_id": 0,
                },
            }
            server_rows.append(server_entry)

        cfg = server_entry.get(CONFIG_CONFIG_KEY)
        if not isinstance(cfg, dict):
            cfg = {}
            server_entry[CONFIG_CONFIG_KEY] = cfg

        cfg["base_url"] = 0
        cfg["port"] = 0
        cfg["model_path"] = 0
        cfg["model_name"] = 0
        cfg["model_id"] = 0

        container_list = cfg.get(CONFIG_CONTAINER_KEY)
        if not isinstance(container_list, list):
            container_list = []
            cfg[CONFIG_CONTAINER_KEY] = container_list

        updated = False
        for idx, item in enumerate(container_list):
            if isinstance(item, dict) and str(item.get("path", "")).strip() == script_path_text:
                container_list[idx] = container_item
                updated = True
                break
        if not updated:
            container_list.append(container_item)

        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    return {
        "group_id": group_id,
        "script_path": script_path_text,
        "container_item": container_item,
    }


def _script_name_without_ext(script_name: str) -> str:
    text = str(script_name or "").strip()
    if text == "":
        return ""
    return Path(text).stem


def _to_int_or_zero(value: Any) -> int:
    text = str(value or "").strip()
    if text == "":
        return 0
    try:
        return int(text)
    except (TypeError, ValueError):
        return 0


def sync_default_config_servers(script_dir: Path, config_path: Path, lock: threading.Lock) -> Dict[str, Any]:
    rows = list_scripts(script_dir)
    grouped: Dict[str, List[Dict[str, Any]]] = {}

    for row in rows:
        rel_path = row["path"]
        group = row["group"]
        name = row["name"]
        resolved_path, _ = resolve_script_path(script_dir, rel_path)
        meta = get_script_metadata(rel_path, config_path)
        grouped.setdefault(group, []).append({
            "path": str(resolved_path),
            "name": _script_name_without_ext(name) or _script_name_without_ext(resolved_path.name),
            "tp_size": _to_int_or_zero(meta["tp_size"]),
            "model_name": meta["model_name"],
            "model_id": meta["model_id"],
            "base_url": meta["base_url"],
            "port": _to_int_or_zero(meta["port"]),
        })

    server_rows = []
    for group in sorted(grouped.keys()):
        containers = grouped[group]
        containers.sort(key=lambda item: str(item.get("path", "")))
        server_rows.append({
            "id": _normalize_group_name(group),
            "config": {
                "container": containers,
                "base_url": 0,
                "port": 0,
                "model_path": 0,
                "model_name": 0,
                "model_id": 0,
            },
        })

    with lock:
        data = _read_config_dict(config_path)
        default_config = data.get(CONFIG_DEFAULT_CONFIG_KEY)
        if not isinstance(default_config, dict):
            default_config = {}
            data[CONFIG_DEFAULT_CONFIG_KEY] = default_config
        default_config[CONFIG_SERVER_KEY] = server_rows
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    return {
        "groups": len(server_rows),
        "scripts": len(rows),
    }


def _read_global_config(config_path: Path) -> Dict[str, Any]:
    data = _read_config_dict(config_path)
    dashboard = data.get(CONFIG_DASHBOARD_KEY)
    if not isinstance(dashboard, dict):
        return {}
    global_cfg = dashboard.get(CONFIG_GLOBAL_CONFIG_KEY)
    return global_cfg if isinstance(global_cfg, dict) else {}


def _normalize_model_names(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        return []
    names: List[str] = []
    seen = set()
    for item in raw:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        names.append(text)
    return names


def _discover_model_names_from_path(model_path: str) -> List[str]:
    root = Path(model_path)
    if not root.exists() or not root.is_dir():
        return []

    rows: List[str] = []
    for first in sorted(root.iterdir(), key=lambda p: p.name):
        if not first.is_dir():
            continue
        if first.name.startswith("."):
            continue
        for second in sorted(first.iterdir(), key=lambda p: p.name):
            if not second.is_dir():
                continue
            if second.name.startswith("."):
                continue
            rows.append(f"{first.name}/{second.name}")
    return rows


def _detect_cuda_version() -> str:
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=cuda_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if proc.returncode != 0:
            return ""
        for line in proc.stdout.splitlines():
            text = line.strip()
            if text:
                return text
    except Exception:
        return ""
    return ""


def _detect_gpu_model() -> str:
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if proc.returncode != 0:
            return ""
        names = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        if not names:
            return ""
        if len(names) == 1:
            return names[0]
        unique = sorted(set(names))
        return " / ".join(unique)
    except Exception:
        return ""


def _detect_cpu_model() -> str:
    cpuinfo = Path("/proc/cpuinfo")
    if not cpuinfo.exists():
        return ""
    try:
        for line in cpuinfo.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.lower().startswith("model name"):
                parts = line.split(":", 1)
                if len(parts) == 2:
                    return parts[1].strip()
    except Exception:
        return ""
    return ""


def get_global_config(config_path: Path) -> Dict[str, Any]:
    raw = _read_global_config(config_path)
    model_path = str(raw.get(CONFIG_MODEL_PATH_KEY, "") or "").strip() or DEFAULT_MODEL_PATH
    default_base_url = str(raw.get(CONFIG_DEFAULT_BASE_URL_KEY, "") or "").strip() or DEFAULT_BASE_URL
    model_names = _normalize_model_names(raw.get(CONFIG_MODEL_NAMES_KEY, []))

    return {
        "model_path": model_path,
        "model_names": model_names,
        "default_base_url": default_base_url,
        "cuda_version": _detect_cuda_version(),
        "cpu_model": _detect_cpu_model(),
        "gpu_model": _detect_gpu_model(),
    }


def save_global_config(config_path: Path, lock: threading.Lock, payload: Dict[str, Any]) -> Dict[str, Any]:
    model_path = str(payload.get(CONFIG_MODEL_PATH_KEY, "") or "").strip() or DEFAULT_MODEL_PATH
    model_names = _normalize_model_names(payload.get(CONFIG_MODEL_NAMES_KEY, []))
    default_base_url = str(payload.get(CONFIG_DEFAULT_BASE_URL_KEY, "") or "").strip() or DEFAULT_BASE_URL

    with lock:
        data = _read_config_dict(config_path)
        dashboard = data.get(CONFIG_DASHBOARD_KEY)
        if not isinstance(dashboard, dict):
            dashboard = {}
            data[CONFIG_DASHBOARD_KEY] = dashboard
        dashboard[CONFIG_GLOBAL_CONFIG_KEY] = {
            CONFIG_MODEL_PATH_KEY: model_path,
            CONFIG_MODEL_NAMES_KEY: model_names,
            CONFIG_DEFAULT_BASE_URL_KEY: default_base_url,
        }
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    return get_global_config(config_path)


def discover_model_names(model_path: str) -> Dict[str, Any]:
    normalized_path = str(model_path or "").strip() or DEFAULT_MODEL_PATH
    model_names = _discover_model_names_from_path(normalized_path)
    return {
        "model_path": normalized_path,
        "model_names": model_names,
    }


def _normalize_endpoint_url(raw: str) -> str:
    text = (raw or "").strip()
    if text == "":
        raise ValueError("endpoint_url is required")

    parsed = parse.urlparse(text)
    if parsed.scheme not in {"http", "https"} or parsed.netloc == "":
        raise ValueError("endpoint_url must start with http:// or https://")

    normalized = parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    return normalized.rstrip("/")


def _new_step() -> Dict[str, str]:
    return {
        "status": STATUS_TESTING,
        "detail": "",
        "updated_at": _iso_now(),
    }


def _deepcopy_state() -> Dict[str, Any]:
    with _SCRIPT_TEST_LOCK:
        if _SCRIPT_TEST_STATE is None:
            return {"has_test": False, "active": False}
        snapshot = json.loads(json.dumps(_SCRIPT_TEST_STATE))
    snapshot["has_test"] = True
    return snapshot


def _result_status_from_overall(overall_status: str) -> str:
    return STATUS_SUCCESS if overall_status == STATUS_SUCCESS else STATUS_FAIL


def _record_script_result(script_rel_path: str, overall_status: str, detail: str = "") -> None:
    if not script_rel_path:
        return
    with _SCRIPT_TEST_LOCK:
        _SCRIPT_TEST_RESULTS[script_rel_path] = {
            "status": _result_status_from_overall(overall_status),
            "overall_status": overall_status,
            "detail": detail,
            "tested_at": _iso_now(),
        }


def get_script_last_test_result(script_rel_path: str) -> Dict[str, str]:
    with _SCRIPT_TEST_LOCK:
        result = _SCRIPT_TEST_RESULTS.get(script_rel_path)
        if result is None:
            return {"status": "untested", "tested_at": "", "detail": ""}
        return {
            "status": str(result.get("status") or STATUS_FAIL),
            "tested_at": str(result.get("tested_at") or ""),
            "detail": str(result.get("detail") or ""),
        }


def move_script_test_result(source_rel_path: str, target_rel_path: str) -> None:
    with _SCRIPT_TEST_LOCK:
        if source_rel_path in _SCRIPT_TEST_RESULTS:
            _SCRIPT_TEST_RESULTS[target_rel_path] = _SCRIPT_TEST_RESULTS.pop(source_rel_path)


def _append_log(message: str) -> None:
    line = f"[{_iso_now()}] {message}"
    with _SCRIPT_TEST_LOCK:
        if _SCRIPT_TEST_STATE is None:
            return
        logs = _SCRIPT_TEST_STATE.setdefault("logs", [])
        logs.append(line)
        if len(logs) > MAX_LOG_LINES:
            del logs[: len(logs) - MAX_LOG_LINES]
        _SCRIPT_TEST_STATE["updated_at"] = _iso_now()


def _read_process_stream(stream: Any, source: str) -> None:
    if stream is None:
        return
    try:
        for raw in iter(stream.readline, ""):
            text = raw.rstrip("\n")
            if text.strip() == "":
                continue
            _append_log(f"{source}: {text}")
    except Exception as exc:
        _append_log(f"{source} stream read error: {exc}")
    finally:
        try:
            stream.close()
        except Exception:
            pass


def _set_step(step_key: str, status: str, detail: str = "") -> None:
    with _SCRIPT_TEST_LOCK:
        if _SCRIPT_TEST_STATE is None:
            return
        _SCRIPT_TEST_STATE["steps"][step_key] = {
            "status": status,
            "detail": detail,
            "updated_at": _iso_now(),
        }
        _SCRIPT_TEST_STATE["updated_at"] = _iso_now()


def _set_all_steps_fail(detail: str) -> None:
    with _SCRIPT_TEST_LOCK:
        if _SCRIPT_TEST_STATE is None:
            return
        for step_key in STEP_KEYS:
            _SCRIPT_TEST_STATE["steps"][step_key] = {
                "status": STATUS_FAIL,
                "detail": detail,
                "updated_at": _iso_now(),
            }
        _SCRIPT_TEST_STATE["updated_at"] = _iso_now()


def _set_overall(overall_status: str, detail: str = "", active: bool = False) -> None:
    script_name = ""
    with _SCRIPT_TEST_LOCK:
        if _SCRIPT_TEST_STATE is None:
            return
        script_name = str(_SCRIPT_TEST_STATE.get("script_name") or "")
        _SCRIPT_TEST_STATE["overall_status"] = overall_status
        _SCRIPT_TEST_STATE["overall_detail"] = detail
        _SCRIPT_TEST_STATE["active"] = active
        _SCRIPT_TEST_STATE["updated_at"] = _iso_now()
        if not active:
            _SCRIPT_TEST_STATE["finished_at"] = _iso_now()
    if not active:
        _record_script_result(script_name, overall_status, detail)


def _mark_stop_requested() -> Tuple[bool, Optional[int]]:
    with _SCRIPT_TEST_LOCK:
        if _SCRIPT_TEST_STATE is None or not _SCRIPT_TEST_STATE.get("active"):
            return False, None
        _SCRIPT_TEST_STATE["stop_requested"] = True
        _SCRIPT_TEST_STATE["updated_at"] = _iso_now()
        return True, _SCRIPT_TEST_STATE.get("pid")


def _stop_process_tree(pid: Optional[int]) -> None:
    if pid is None or pid <= 0:
        return

    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except Exception:
            return

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        except Exception:
            return
        time.sleep(0.2)

    try:
        os.killpg(pid, signal.SIGKILL)
    except Exception:
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass


def _should_stop_requested() -> bool:
    with _SCRIPT_TEST_LOCK:
        return bool(_SCRIPT_TEST_STATE and _SCRIPT_TEST_STATE.get("stop_requested"))


def _request_json(method: str, url: str, payload: Optional[Dict[str, Any]] = None, timeout: int = 8) -> Tuple[bool, int, Optional[Dict[str, Any]], str]:
    data_bytes: Optional[bytes] = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data_bytes = json.dumps(payload).encode("utf-8")

    req = request.Request(url=url, method=method, headers=headers, data=data_bytes)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            status_code = int(resp.status)
            body = resp.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        status_code = int(exc.code)
        body = exc.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return False, 0, None, str(exc)

    parsed_json: Optional[Dict[str, Any]] = None
    if body:
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                parsed_json = parsed
        except Exception:
            parsed_json = None

    ok = 200 <= status_code < 300
    return ok, status_code, parsed_json, body


def _check_health(endpoint_url: str) -> Tuple[bool, str]:
    ok, status_code, payload, _ = _request_json("GET", f"{endpoint_url}/health")
    if not ok:
        return False, f"HTTP {status_code or 'N/A'}"

    if payload is None:
        return True, "health ok"

    status_text = str(payload.get("status", "")).lower()
    if status_text in {"ok", "healthy", "ready"}:
        return True, "health ok"
    return True, f"health response: {status_text or 'ok'}"


def _check_models(endpoint_url: str) -> Tuple[bool, Optional[str], str]:
    ok, status_code, payload, _ = _request_json("GET", f"{endpoint_url}/v1/models")
    if not ok:
        return False, None, f"HTTP {status_code or 'N/A'}"
    if payload is None:
        return False, None, "Invalid JSON response"

    models = payload.get("data")
    if not isinstance(models, list) or len(models) == 0:
        return False, None, "No model data returned"

    for item in models:
        if isinstance(item, dict):
            model_id = item.get("id")
            if isinstance(model_id, str) and model_id.strip():
                return True, model_id.strip(), "models ok"

    return False, None, "No served model id in response"


def _check_completions(endpoint_url: str, model_id: str) -> Tuple[bool, str]:
    payload = {
        "model": model_id,
        "prompt": "hello",
        "max_tokens": 8,
        "temperature": 0,
    }
    ok, status_code, data, _ = _request_json("POST", f"{endpoint_url}/v1/completions", payload=payload, timeout=15)
    if not ok:
        return False, f"HTTP {status_code or 'N/A'}"
    if data is None:
        return False, "Invalid JSON response"
    choices = data.get("choices")
    if isinstance(choices, list) and len(choices) > 0:
        return True, "completions ok"
    return False, "No choices returned"


def _monitor_script_test(proc: subprocess.Popen[str], endpoint_url: str) -> None:
    deadline = time.monotonic() + TEST_TIMEOUT_SECONDS
    _append_log(f"Test worker started for endpoint: {endpoint_url}")

    try:
        health_ok = False
        while time.monotonic() < deadline:
            if _should_stop_requested():
                _append_log("Stop requested by user")
                _set_all_steps_fail("Stopped by user")
                _set_overall("stopped", "Stopped by user", active=False)
                return

            if proc.poll() is not None:
                code = proc.returncode
                _append_log(f"Script exited early with code: {code}")
                _set_all_steps_fail(f"Script exited early (code: {code})")
                _set_overall("fail", f"Script exited early (code: {code})", active=False)
                return

            ok, detail = _check_health(endpoint_url)
            if ok:
                _append_log(f"Health check success: {detail}")
                _set_step(STEP_HEALTH, STATUS_SUCCESS, detail)
                health_ok = True
                break

            _append_log(f"Health check pending: {detail}")
            _set_step(STEP_HEALTH, STATUS_TESTING, f"Waiting for health: {detail}")
            for _ in range(TEST_INTERVAL_SECONDS):
                if _should_stop_requested():
                    _append_log("Stop requested by user")
                    _set_all_steps_fail("Stopped by user")
                    _set_overall("stopped", "Stopped by user", active=False)
                    return
                if time.monotonic() >= deadline:
                    break
                time.sleep(1)

        if not health_ok:
            _append_log("Timeout waiting for /health")
            _set_all_steps_fail("Timeout waiting for health")
            _set_overall("timeout", "Timeout waiting for health", active=False)
            return

        if time.monotonic() >= deadline:
            _append_log("Timeout before models check")
            _set_all_steps_fail("Timeout")
            _set_overall("timeout", "Timeout", active=False)
            return

        models_ok, model_id, models_detail = _check_models(endpoint_url)
        if models_ok and model_id:
            _append_log(f"Models check success, model id: {model_id}")
            _set_step(STEP_MODELS, STATUS_SUCCESS, models_detail)
        else:
            _append_log(f"Models check failed: {models_detail}")
            _set_step(STEP_MODELS, STATUS_FAIL, models_detail)
            _set_step(STEP_COMPLETIONS, STATUS_FAIL, "Skipped because models failed")
            _set_overall("fail", models_detail, active=False)
            return

        if time.monotonic() >= deadline:
            _append_log("Timeout before completions check")
            _set_all_steps_fail("Timeout")
            _set_overall("timeout", "Timeout", active=False)
            return

        completions_ok, completions_detail = _check_completions(endpoint_url, model_id)
        if completions_ok:
            _append_log("Completions check success")
            _set_step(STEP_COMPLETIONS, STATUS_SUCCESS, completions_detail)
            _set_overall("success", "All checks passed", active=False)
        else:
            _append_log(f"Completions check failed: {completions_detail}")
            _set_step(STEP_COMPLETIONS, STATUS_FAIL, completions_detail)
            _set_overall("fail", completions_detail, active=False)
    finally:
        _append_log("Stopping script process")
        _stop_process_tree(proc.pid)
        with _SCRIPT_TEST_LOCK:
            if _SCRIPT_TEST_STATE is not None:
                _SCRIPT_TEST_STATE["active"] = False
                _SCRIPT_TEST_STATE["updated_at"] = _iso_now()
                _SCRIPT_TEST_STATE["finished_at"] = _iso_now()
            global _SCRIPT_TEST_THREAD
            _SCRIPT_TEST_THREAD = None
        _append_log("Test worker finished")


def start_script_test(script_path: Path, script_rel_path: str, endpoint_url: str) -> Dict[str, Any]:
    global _SCRIPT_TEST_STATE
    global _SCRIPT_TEST_THREAD

    normalized_endpoint = _normalize_endpoint_url(endpoint_url)

    with _SCRIPT_TEST_LOCK:
        if _SCRIPT_TEST_STATE is not None and _SCRIPT_TEST_STATE.get("active"):
            raise RuntimeError("Another script test is already running")

        script_cmd = shlex.quote(str(script_path))
        launch_cmd = f"source ~/.bashrc >/dev/null 2>&1 || true; bash {script_cmd}"
        proc = subprocess.Popen(
            ["bash", "-lc", launch_cmd],
            cwd=str(script_path.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )

        now = _iso_now()
        initial_state: Dict[str, Any] = {
            "active": True,
            "script_name": script_rel_path,
            "endpoint_url": normalized_endpoint,
            "pid": int(proc.pid),
            "overall_status": STATUS_TESTING,
            "overall_detail": "Test started",
            "started_at": now,
            "updated_at": now,
            "finished_at": None,
            "stop_requested": False,
            "logs": [],
            "steps": {
                STEP_HEALTH: _new_step(),
                STEP_MODELS: _new_step(),
                STEP_COMPLETIONS: _new_step(),
            },
        }

        _SCRIPT_TEST_STATE = initial_state
        _append_log(f"Script test started: {script_rel_path}")
        _append_log(f"Endpoint: {normalized_endpoint}")
        _append_log(f"PID: {proc.pid}")

        if proc.stdout is not None:
            threading.Thread(target=_read_process_stream, args=(proc.stdout, "stdout"), daemon=True).start()
        if proc.stderr is not None:
            threading.Thread(target=_read_process_stream, args=(proc.stderr, "stderr"), daemon=True).start()

        worker = threading.Thread(target=_monitor_script_test, args=(proc, normalized_endpoint), daemon=True)
        _SCRIPT_TEST_THREAD = worker
        worker.start()

    return _deepcopy_state()


def stop_script_test() -> Dict[str, Any]:
    found, pid = _mark_stop_requested()
    if not found:
        return {"has_test": False, "active": False}

    _append_log("Stop requested from API")
    _stop_process_tree(pid)
    return _deepcopy_state()


def get_script_test_status() -> Dict[str, Any]:
    return _deepcopy_state()
