import difflib
import json
import os
import select
import stat
import subprocess
import sys
import termios
import time
import tty
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from omegaconf import DictConfig, ListConfig, OmegaConf

from log_utils import configure_logging, consume_verbosity_flags
from run_container import run_container
from stop_container import stop_container
from wait_for_healthcheck import wait_for_healthcheck


CONFIG_PATH = Path("config/config.yaml")
SHEET_ID_LIST_PATH = Path("sheet_id_list.json")
SERVICE_ACCOUNT_PATH = Path("config/service_account.json")
SERVICES_DIR = Path("services")


def prompt_input(message: str, default: Optional[str] = None) -> str:
    suffix = f" [{default}]" if default is not None and default != "" else ""
    raw = input(f"{message}{suffix}: ").strip()
    if raw == "" and default is not None:
        return str(default)
    return raw


def wait_for_confirm(message: str = "按 Enter 返回選單") -> None:
    input(f"{message}...")


def prompt_int(message: str, default: Optional[int] = None, min_value: Optional[int] = None) -> int:
    while True:
        raw = prompt_input(message, None if default is None else str(default))
        try:
            value = int(raw)
        except ValueError:
            print("請輸入整數")
            continue
        if min_value is not None and value < min_value:
            print(f"數值需 >= {min_value}")
            continue
        return value


def prompt_float(message: str, default: Optional[float] = None, min_value: Optional[float] = None) -> float:
    while True:
        raw = prompt_input(message, None if default is None else str(default))
        try:
            value = float(raw)
        except ValueError:
            print("請輸入數字")
            continue
        if min_value is not None and value < min_value:
            print(f"數值需 >= {min_value}")
            continue
        return value


def _read_key() -> str:
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        first = os.read(fd, 1)
        if first in (b"\r", b"\n"):
            return "ENTER"
        if first == b"\x1b":
            # Arrow keys are escape sequences (ESC [ A/B or ESC O A/B).
            seq = b""
            deadline = time.time() + 0.25
            while time.time() < deadline:
                ready, _, _ = select.select([fd], [], [], 0.03)
                if not ready:
                    break
                seq += os.read(fd, 1)
                if seq.endswith((b"[A", b"[B", b"OA", b"OB")):
                    break
            if seq.endswith((b"[A", b"OA")):
                return "UP"
            if seq.endswith((b"[B", b"OB")):
                return "DOWN"
            if not seq:
                return "ESC"
            return "ESC"
        try:
            return first.decode("utf-8")
        except UnicodeDecodeError:
            return ""
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def choose_index(
    title: str,
    options: List[str],
    allow_back: bool = True,
    default_index: int = 0,
    esc_mode: str = "single",
) -> Optional[int]:
    if not options:
        print("沒有可選項目")
        return None

    cursor = max(0, min(default_index, len(options) - 1))
    while True:
        if sys.stdout.isatty():
            print("\x1b[2J\x1b[H", end="")
        print(title)
        print("-" * max(8, len(title)))
        for i, item in enumerate(options):
            marker = "▸" if i == cursor else " "
            print(f"{marker} {item}")
        if allow_back:
            print("  返回")
        print("使用 ↑/↓ 選擇，Enter 確認，Esc 返回")

        key = _read_key() if sys.stdin.isatty() else input("輸入 up/down/enter/back: ").strip()
        key_lower = key.lower() if isinstance(key, str) else ""
        if key in ("\x1b[A", "\x1bOA") or key_lower in ("up", "k", "w"):
            key = "UP"
        elif key in ("\x1b[B", "\x1bOB") or key_lower in ("down", "j", "s"):
            key = "DOWN"
        elif key in ("\r", "\n") or key_lower in ("enter",):
            key = "ENTER"
        elif key == "\x1b" or key_lower in ("esc", "back", "b"):
            key = "ESC"

        if key == "ENTER":
            return cursor
        if key == "DOWN":
            cursor = (cursor + 1) % len(options)
            continue
        if key == "UP":
            cursor = (cursor - 1) % len(options)
            continue
        if allow_back and key == "ESC":
            return None


def choose_yes_no(message: str, default_yes: bool = False) -> bool:
    options = ["是", "否"]
    default_idx = 0 if default_yes else 1
    idx = choose_index(message, options, allow_back=False, default_index=default_idx)
    return idx == 0


def load_cfg() -> DictConfig:
    return OmegaConf.load(CONFIG_PATH)


def load_sheet_map() -> Dict[str, str]:
    with SHEET_ID_LIST_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def cfg_to_yaml(cfg: DictConfig) -> str:
    text = OmegaConf.to_yaml(cfg, resolve=False)
    return text if text.endswith("\n") else text + "\n"


def sheet_map_to_text(sheet_map: Dict[str, str]) -> str:
    return json.dumps(sheet_map, ensure_ascii=False, indent=4) + "\n"


def validate_sheet_url(url: str) -> bool:
    return "https://docs.google.com/spreadsheets/d/" in url


def _server_entries(cfg: DictConfig) -> ListConfig:
    if "default_config" not in cfg or "server" not in cfg.default_config:
        cfg.default_config.server = []
    return cfg.default_config.server


def _benchmark_entries(cfg: DictConfig) -> ListConfig:
    if "default_config" not in cfg or "benchmark" not in cfg.default_config:
        cfg.default_config.benchmark = []
    return cfg.default_config.benchmark


def find_entry_by_id(entries: ListConfig, target_id: str) -> Optional[DictConfig]:
    for entry in entries:
        if str(entry.id) == str(target_id):
            return entry
    return None


def edit_autotest(cfg: DictConfig, sheet_map: Dict[str, str]) -> bool:
    changed = False
    print(f"\n[autotest] name={cfg.autotest.name}, sheet_name={cfg.autotest.sheet_name}")
    new_name = prompt_input("autotest.name", str(cfg.autotest.name))
    if new_name != str(cfg.autotest.name):
        cfg.autotest.name = new_name
        changed = True

    keys = list(sheet_map.keys())
    options = keys + ["新增 sheet_name + URL"]
    idx = choose_index("選擇 sheet_name", options)
    if idx is None:
        return changed

    if idx < len(keys):
        selected = keys[idx]
        if selected != str(cfg.autotest.sheet_name):
            cfg.autotest.sheet_name = selected
            changed = True
        return changed

    new_key = prompt_input("輸入新的 sheet_name")
    if not new_key:
        print("sheet_name 不可空白")
        return changed
    new_url = prompt_input("輸入 Google Sheet URL")
    if not validate_sheet_url(new_url):
        print("URL 格式錯誤，需包含 /spreadsheets/d/")
        return changed

    if new_key in sheet_map:
        overwrite = choose_yes_no(f"{new_key} 已存在，是否覆蓋?", default_yes=False)
        if not overwrite:
            return changed

    sheet_map[new_key] = new_url
    cfg.autotest.sheet_name = new_key
    changed = True
    print(f"已新增並切換 sheet_name: {new_key}")
    return changed


def edit_healthcheck(cfg: DictConfig) -> bool:
    print(
        f"\n[healthcheck] timeout={cfg.healthcheck.timeout}, "
        f"max_tries={cfg.healthcheck.max_tries}, interval={cfg.healthcheck.interval}"
    )
    changed = False
    timeout = prompt_float("timeout (>0)", float(cfg.healthcheck.timeout), min_value=0.0001)
    max_tries = prompt_int("max_tries (>=1)", int(cfg.healthcheck.max_tries), min_value=1)
    interval = prompt_float("interval (>0)", float(cfg.healthcheck.interval), min_value=0.0001)
    if timeout != float(cfg.healthcheck.timeout):
        cfg.healthcheck.timeout = timeout
        changed = True
    if max_tries != int(cfg.healthcheck.max_tries):
        cfg.healthcheck.max_tries = max_tries
        changed = True
    if interval != float(cfg.healthcheck.interval):
        cfg.healthcheck.interval = interval
        changed = True
    return changed


def parse_int_list(text: str) -> List[int]:
    items = [x.strip() for x in text.split(",") if x.strip()]
    return [int(x) for x in items]


def parse_str_list(text: str) -> List[str]:
    return [x.strip() for x in text.split(",") if x.strip()]


def parse_token_lengths(text: str) -> List[Dict[str, Any]]:
    # format: input:output,input:output ; input can be 'none'
    result: List[Dict[str, Any]] = []
    pairs = [x.strip() for x in text.split(",") if x.strip()]
    for pair in pairs:
        if ":" not in pair:
            raise ValueError(f"無效格式: {pair}")
        left, right = pair.split(":", 1)
        input_len: Any = left.strip()
        if input_len.lower() != "none":
            input_len = int(input_len)
            if input_len < 0:
                raise ValueError(f"input_len 需 >= 0: {pair}")
        output_len = int(right.strip())
        if output_len < 0:
            raise ValueError(f"output_len 需 >= 0: {pair}")
        result.append({"input_len": input_len, "output_len": output_len})
    return result


def format_token_lengths(items: Any) -> str:
    parts: List[str] = []
    for item in items:
        parts.append(f"{item.input_len}:{item.output_len}")
    return ",".join(parts)


def ensure_server_entry(cfg: DictConfig) -> DictConfig:
    entries = _server_entries(cfg)
    current_id = str(cfg.server.id)
    found = find_entry_by_id(entries, current_id)
    if found is not None:
        return found

    base_config = {
        "container": [],
        "base_url": getattr(cfg.server, "base_url", "http://localhost"),
        "port": getattr(cfg.server, "port", 8000),
        "model_path": getattr(cfg.server, "model_path", ""),
        "model_name": getattr(cfg.server, "model_name", ""),
        "model_id": getattr(cfg.server, "model_id", ""),
    }
    new_entry = OmegaConf.create({"id": current_id, "config": base_config})
    entries.append(new_entry)
    return new_entry


def ensure_benchmark_entry(cfg: DictConfig) -> DictConfig:
    entries = _benchmark_entries(cfg)
    current_id = str(cfg.benchmark.id)
    found = find_entry_by_id(entries, current_id)
    if found is not None:
        return found

    base_config = {
        "name": ["inferencemax-h100"],
        "endpoint_type": "completions",
        "dataset_path": "none",
        "token_lengths": [{"input_len": "none", "output_len": 1024}],
        "concurrency": [1],
    }
    new_entry = OmegaConf.create({"id": current_id, "config": base_config})
    entries.append(new_entry)
    return new_entry


def add_service(server_cfg: DictConfig, benchmark_cfg: Optional[DictConfig]) -> bool:
    defaults = {
        "port": getattr(server_cfg, "port", None),
        "base_url": getattr(server_cfg, "base_url", None),
        "model_name": getattr(server_cfg, "model_name", None),
        "model_path": getattr(server_cfg, "model_path", None),
        "model_id": getattr(server_cfg, "model_id", None),
        "endpoint_type": getattr(benchmark_cfg, "endpoint_type", None) if benchmark_cfg is not None else None,
    }

    name = prompt_input("服務 name")
    if not name:
        print("name 不可空白")
        return False

    path = prompt_input("服務腳本 path", "services/run_service.sh")
    service_name = prompt_input("service_name (none 代表不指定)", "none")
    tp_size = prompt_int("tp_size", 1, min_value=1)

    data: Dict[str, Any] = {
        "name": name,
        "path": path,
        "service_name": service_name,
        "tp_size": tp_size,
    }

    for key in ["port", "base_url", "model_name", "model_path", "model_id", "endpoint_type"]:
        default = defaults[key]
        value = prompt_input(f"{key} (Enter 使用預設)", "" if default is None else str(default))
        if value == "":
            continue
        if key == "port":
            try:
                data[key] = int(value)
            except ValueError:
                print("port 格式錯誤，略過")
                continue
        else:
            data[key] = value

    if "container" not in server_cfg or server_cfg.container is None:
        server_cfg.container = []
    server_cfg.container.append(OmegaConf.create(data))
    print(f"已新增服務: {name}")
    return True


def edit_service(server_cfg: DictConfig) -> bool:
    services = list(getattr(server_cfg, "container", []))
    names = [str(getattr(s, "name", f"service_{i+1}")) for i, s in enumerate(services)]
    idx = choose_index("選擇要編輯的服務", names)
    if idx is None:
        return False

    target = services[idx]
    fields = ["name", "path", "service_name", "tp_size", "port", "base_url", "model_name", "model_path", "model_id", "endpoint_type"]
    optional_fields = {"port", "base_url", "model_name", "model_path", "model_id", "endpoint_type"}
    changed = False
    for field in fields:
        current = getattr(target, field, "")
        new_val = prompt_input(f"{field}（Enter 維持原值，輸入 NONE 清除可選欄位）", "")
        if new_val == "":
            continue
        if new_val.upper() == "NONE" and field in optional_fields:
            if field in target:
                del target[field]
                changed = True
            continue
        if field in ("tp_size", "port"):
            try:
                setattr(target, field, int(new_val))
                changed = True
            except ValueError:
                print(f"{field} 需為整數，保持原值")
                continue
        else:
            setattr(target, field, new_val)
            changed = True

    server_cfg.container[idx] = target
    print(f"已更新服務: {getattr(target, 'name', names[idx])}")
    return changed


def remove_service(server_cfg: DictConfig) -> bool:
    services = list(getattr(server_cfg, "container", []))
    names = [str(getattr(s, "name", f"service_{i+1}")) for i, s in enumerate(services)]
    idx = choose_index("選擇要移除的服務", names)
    if idx is None:
        return False

    target_name = names[idx]
    confirm = choose_yes_no(f"確認刪除服務 {target_name} ?", default_yes=False)
    if not confirm:
        print("已取消刪除")
        return False

    del server_cfg.container[idx]
    print(f"已移除服務: {target_name}")
    return True


def edit_server_current_id(cfg: DictConfig, entry: DictConfig) -> bool:
    changed = False
    server_cfg = entry.config

    benchmark_entry = find_entry_by_id(_benchmark_entries(cfg), str(cfg.benchmark.id))
    benchmark_cfg = benchmark_entry.config if benchmark_entry is not None else None

    print(f"\n[server config] id={entry.id}")
    base_url = prompt_input("base_url", str(getattr(server_cfg, "base_url", "http://localhost")))
    port = prompt_int("port", int(getattr(server_cfg, "port", 8000)), min_value=1)
    model_id = prompt_input("model_id", str(getattr(server_cfg, "model_id", "")))
    model_name = prompt_input("model_name", str(getattr(server_cfg, "model_name", "")))
    model_path = prompt_input("model_path", str(getattr(server_cfg, "model_path", "")))

    if base_url != str(getattr(server_cfg, "base_url", "http://localhost")):
        server_cfg.base_url = base_url
        changed = True
    if port != int(getattr(server_cfg, "port", 8000)):
        server_cfg.port = port
        changed = True
    if model_id != str(getattr(server_cfg, "model_id", "")):
        server_cfg.model_id = model_id
        changed = True
    if model_name != str(getattr(server_cfg, "model_name", "")):
        server_cfg.model_name = model_name
        changed = True
    if model_path != str(getattr(server_cfg, "model_path", "")):
        server_cfg.model_path = model_path
        changed = True

    while True:
        service_choice = choose_index("[服務管理]", ["新增服務", "編輯服務", "移除服務", "完成返回"])
        if service_choice is None or service_choice == 3:
            break
        if service_choice == 0:
            changed = add_service(server_cfg, benchmark_cfg) or changed
            continue
        if service_choice == 1:
            changed = edit_service(server_cfg) or changed
            continue
        if service_choice == 2:
            changed = remove_service(server_cfg) or changed
            continue
    return changed


def edit_server(cfg: DictConfig) -> bool:
    changed = False
    entries = _server_entries(cfg)
    current_id = str(cfg.server.id)
    current_entry = ensure_server_entry(cfg)

    while True:
        choice = choose_index(
            f"[server] 目前 server.id: {current_id}",
            ["切換 id", "建立並切換新 id", "編輯目前 id 設定"],
        )
        if choice is None:
            return changed
        if choice == 0:
            ids = [str(item.id) for item in entries]
            idx = choose_index("選擇 server id", ids)
            if idx is not None:
                cfg.server.id = ids[idx]
                current_id = ids[idx]
                current_entry = find_entry_by_id(entries, current_id)
                if current_entry is None:
                    current_entry = ensure_server_entry(cfg)
                changed = True
            continue
        if choice == 1:
            new_id = prompt_input("輸入新 server id")
            if not new_id:
                print("id 不可空白")
                continue
            if find_entry_by_id(entries, new_id) is not None:
                print("id 已存在")
                continue
            template = OmegaConf.to_container(current_entry.config, resolve=False)
            entries.append(OmegaConf.create({"id": new_id, "config": template}))
            cfg.server.id = new_id
            current_id = new_id
            current_entry = find_entry_by_id(entries, current_id)
            changed = True
            print(f"已建立並切換到 {new_id}")
            continue
        if choice == 2:
            if current_entry is None:
                current_entry = ensure_server_entry(cfg)
            changed = edit_server_current_id(cfg, current_entry) or changed
            continue


def edit_benchmark_current_id(entry: DictConfig) -> bool:
    changed = False
    bench_cfg = entry.config
    print(f"\n[benchmark config] id={entry.id}")

    names_raw = prompt_input("name 列表，逗號分隔", ",".join(getattr(bench_cfg, "name", [])))
    endpoint_type = prompt_input("endpoint_type", str(getattr(bench_cfg, "endpoint_type", "completions")))
    dataset_path = prompt_input("dataset_path", str(getattr(bench_cfg, "dataset_path", "none")))
    token_raw = prompt_input(
        "token_lengths 格式 input:output,input:output",
        format_token_lengths(getattr(bench_cfg, "token_lengths", [])),
    )
    concurrency_raw = prompt_input(
        "concurrency，逗號分隔",
        ",".join([str(x) for x in getattr(bench_cfg, "concurrency", [])]),
    )
    seeds_default = ",".join([str(x) for x in getattr(bench_cfg, "seeds", [])]) if "seeds" in bench_cfg else ""
    seeds_raw = prompt_input("seeds，逗號分隔；留空可清除", seeds_default)
    model_name = prompt_input("model_name", str(getattr(bench_cfg, "model_name", "")))

    names = parse_str_list(names_raw)
    if names and names != list(getattr(bench_cfg, "name", [])):
        bench_cfg.name = names
        changed = True

    if endpoint_type != str(getattr(bench_cfg, "endpoint_type", "completions")):
        bench_cfg.endpoint_type = endpoint_type
        changed = True

    if dataset_path != str(getattr(bench_cfg, "dataset_path", "none")):
        bench_cfg.dataset_path = dataset_path
        changed = True

    try:
        token_parsed = parse_token_lengths(token_raw)
        token_current = OmegaConf.to_container(getattr(bench_cfg, "token_lengths", []), resolve=False)
        if token_parsed != token_current:
            bench_cfg.token_lengths = OmegaConf.create(token_parsed)
            changed = True
    except ValueError as exc:
        print(f"token_lengths 格式錯誤，維持原值: {exc}")

    try:
        concurrency_parsed = parse_int_list(concurrency_raw)
        if concurrency_parsed != list(getattr(bench_cfg, "concurrency", [])):
            bench_cfg.concurrency = concurrency_parsed
            changed = True
    except ValueError:
        print("concurrency 格式錯誤，維持原值")

    if seeds_raw.strip() == "":
        if "seeds" in bench_cfg:
            del bench_cfg["seeds"]
            changed = True
    else:
        try:
            seeds_parsed = parse_int_list(seeds_raw)
            if "seeds" not in bench_cfg or seeds_parsed != list(getattr(bench_cfg, "seeds", [])):
                bench_cfg.seeds = seeds_parsed
                changed = True
        except ValueError:
            print("seeds 格式錯誤，維持原值")

    if model_name != str(getattr(bench_cfg, "model_name", "")):
        bench_cfg.model_name = model_name
        changed = True

    return changed


def edit_benchmark(cfg: DictConfig) -> bool:
    changed = False
    entries = _benchmark_entries(cfg)
    current_id = str(cfg.benchmark.id)
    current_entry = ensure_benchmark_entry(cfg)

    while True:
        choice = choose_index(
            f"[benchmark] 目前 benchmark.id: {current_id}",
            ["切換 id", "建立並切換新 id", "編輯目前 id 設定"],
        )
        if choice is None:
            return changed
        if choice == 0:
            ids = [str(item.id) for item in entries]
            idx = choose_index("選擇 benchmark id", ids)
            if idx is not None:
                cfg.benchmark.id = ids[idx]
                current_id = ids[idx]
                current_entry = find_entry_by_id(entries, current_id)
                if current_entry is None:
                    current_entry = ensure_benchmark_entry(cfg)
                changed = True
            continue
        if choice == 1:
            new_id = prompt_input("輸入新 benchmark id")
            if not new_id:
                print("id 不可空白")
                continue
            if find_entry_by_id(entries, new_id) is not None:
                print("id 已存在")
                continue
            template = OmegaConf.to_container(current_entry.config, resolve=False)
            entries.append(OmegaConf.create({"id": new_id, "config": template}))
            cfg.benchmark.id = new_id
            current_id = new_id
            current_entry = find_entry_by_id(entries, current_id)
            changed = True
            print(f"已建立並切換到 {new_id}")
            continue
        if choice == 2:
            if current_entry is None:
                current_entry = ensure_benchmark_entry(cfg)
            changed = edit_benchmark_current_id(current_entry) or changed
            continue


def edit_config_menu(cfg: DictConfig, sheet_map: Dict[str, str]) -> bool:
    changed = False
    while True:
        choice = choose_index("[編輯設定檔]", ["autotest", "healthcheck", "server", "benchmark"])
        if choice is None:
            return changed
        if choice == 0:
            changed = edit_autotest(cfg, sheet_map) or changed
            continue
        if choice == 1:
            changed = edit_healthcheck(cfg) or changed
            continue
        if choice == 2:
            changed = edit_server(cfg) or changed
            continue
        if choice == 3:
            changed = edit_benchmark(cfg) or changed
            continue


def show_diff(title: str, before: str, after: str) -> None:
    if before == after:
        print(f"\n[{title}] 無變更")
        return
    print(f"\n[{title}] 變更預覽")
    diff = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=f"before/{title}",
        tofile=f"after/{title}",
        lineterm="",
    )
    for line in diff:
        print(line)


def open_in_editor(path: Path) -> None:
    editor = os.environ.get("EDITOR", "vim")
    subprocess.call([editor, str(path)])


def ensure_executable(path: Path) -> None:
    current_mode = path.stat().st_mode
    path.chmod(current_mode | stat.S_IXUSR)


def validate_script_basic(path: Path) -> None:
    with path.open("r", encoding="utf-8") as f:
        lines = f.readlines()

    if not lines:
        print("警告: 腳本為空")
        return

    if not lines[0].startswith("#!"):
        print("警告: 第一行缺少 shebang (#!)")

    if not any("set -euo pipefail" in line for line in lines[:8]):
        print("警告: 建議加入 set -euo pipefail")


def edit_service_script() -> None:
    SERVICES_DIR.mkdir(parents=True, exist_ok=True)
    scripts = sorted([str(p) for p in SERVICES_DIR.glob("*.sh")])
    print("\n[編輯服務腳本]")
    if scripts:
        idx = choose_index("選擇既有腳本（或返回自行輸入新路徑）", scripts)
        if idx is not None:
            script_path = Path(scripts[idx])
        else:
            script_path = Path(prompt_input("輸入腳本路徑", "services/run_service.sh"))
    else:
        script_path = Path(prompt_input("輸入腳本路徑", "services/run_service.sh"))

    script_path.parent.mkdir(parents=True, exist_ok=True)
    if not script_path.exists():
        script_path.write_text("#!/bin/bash\nset -euo pipefail\n\n", encoding="utf-8")

    open_in_editor(script_path)
    ensure_executable(script_path)
    validate_script_basic(script_path)
    print(f"腳本已保存: {script_path}")


def edit_service_account_json() -> None:
    SERVICE_ACCOUNT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not SERVICE_ACCOUNT_PATH.exists():
        template = {
            "type": "service_account",
            "project_id": "",
            "private_key_id": "",
            "private_key": "",
            "client_email": "",
            "client_id": "",
        }
        SERVICE_ACCOUNT_PATH.write_text(json.dumps(template, indent=4) + "\n", encoding="utf-8")

    required_keys = ["type", "project_id", "client_email", "private_key"]

    while True:
        open_in_editor(SERVICE_ACCOUNT_PATH)
        try:
            data = json.loads(SERVICE_ACCOUNT_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"JSON 格式錯誤: {exc}")
            retry = choose_yes_no("重新編輯?", default_yes=True)
            if retry:
                continue
            return

        missing = [k for k in required_keys if k not in data or str(data[k]).strip() == ""]
        if missing:
            print(f"缺少必要欄位: {', '.join(missing)}")
            retry = choose_yes_no("重新編輯?", default_yes=True)
            if retry:
                continue
            return

        os.chmod(SERVICE_ACCOUNT_PATH, 0o600)
        print(f"已更新 {SERVICE_ACCOUNT_PATH}")
        return


def _build_effective_cfg(cfg: DictConfig) -> DictConfig:
    merged = OmegaConf.create(OmegaConf.to_container(cfg, resolve=False))

    server_entry = find_entry_by_id(_server_entries(merged), str(merged.server.id))
    if server_entry is not None:
        merged.server = {**merged.server, **server_entry.config}

    bench_entry = find_entry_by_id(_benchmark_entries(merged), str(merged.benchmark.id))
    if bench_entry is not None:
        merged.benchmark = {**merged.benchmark, **bench_entry.config}

    return merged


def preview_benchmark(cfg: DictConfig) -> None:
    merged = _build_effective_cfg(cfg)
    total = (
        len(merged.server.container)
        * len(merged.benchmark.name)
        * len(merged.benchmark.token_lengths)
        * len(merged.benchmark.concurrency)
    )
    print("\n[Benchmark 預覽]")
    print(f"autotest.name: {merged.autotest.name}")
    print(f"輸出目錄: results/{merged.autotest.name}")
    print(f"總輪數: {total}")

    round_no = 0
    for container in merged.server.container:
        for benchmark_name in merged.benchmark.name:
            for token_lengths in merged.benchmark.token_lengths:
                for concurrency in merged.benchmark.concurrency:
                    round_no += 1
                    print(
                        f"{round_no}/{total} | 服務={container.name} | benchmark={benchmark_name} "
                        f"| input={token_lengths.input_len} | output={token_lengths.output_len} | concurrency={concurrency}"
                    )


def test_models_endpoint(cfg: DictConfig) -> Tuple[bool, str]:
    url = f"{cfg.server.base_url}:{cfg.server.port}/v1/models"
    timeout = float(cfg.healthcheck.timeout)
    try:
        response = requests.get(url, timeout=timeout)
    except requests.RequestException as exc:
        return False, f"request failed: {exc}"

    if response.status_code != 200:
        return False, f"status={response.status_code}"

    try:
        payload = response.json()
    except ValueError:
        return False, "response is not valid JSON"

    if "data" not in payload:
        return False, "JSON missing 'data' field"
    return True, "ok"


def test_service_script(cfg: DictConfig) -> None:
    merged = _build_effective_cfg(cfg)
    services = list(getattr(merged.server, "container", []))
    script_path = ""
    container_name_for_test = ""

    if services:
        options = []
        for s in services:
            s_name = str(getattr(s, "name", "unnamed-service"))
            s_path = str(getattr(s, "path", ""))
            options.append(f"{s_name} | {s_path}")
        idx = choose_index("選擇要測試的服務", options)
        if idx is None:
            return
        selected = services[idx]
        script_path = str(getattr(selected, "path", "")).strip()
        container_name_for_test = str(getattr(selected, "name", "")).strip()
    else:
        script_path = prompt_input("輸入要測試的服務腳本路徑", "services/run_rs.sh")

    if not script_path:
        print("服務腳本路徑為空")
        return
    if not Path(script_path).exists():
        print(f"檔案不存在: {script_path}")
        return

    if not container_name_for_test:
        container_name = f"cli-test-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    else:
        container_name = container_name_for_test
    started_pid: Optional[int] = None

    health_ok = False
    health_msg = "not run"
    models_ok = False
    models_msg = "not run"

    try:
        started_pid = run_container(merged, script_path, service_name="none", container_name=container_name)
        try:
            wait_for_healthcheck(merged, container_name)
            health_ok, health_msg = True, "ok"
        except Exception as exc:  # pylint: disable=broad-except
            health_ok, health_msg = False, str(exc)

        if health_ok:
            models_ok, models_msg = test_models_endpoint(merged)
    finally:
        try:
            stop_container(merged, container_name, script_path, started_pid)
        except Exception as exc:  # pylint: disable=broad-except
            print(f"停止服務失敗: {exc}")

    print("\n[測試結果]")
    print(f"healthcheck: {'PASS' if health_ok else 'FAIL'} ({health_msg})")
    print(f"/v1/models: {'PASS' if models_ok else 'FAIL'} ({models_msg})")


def run_full_benchmark(verbosity: int) -> None:
    args = ["python3", "main.py"]
    if verbosity == 1:
        args.append("-v")
    elif verbosity == 2:
        args.append("-vv")
    elif verbosity >= 3:
        args.append("-vvv")

    print("\n即將執行:", " ".join(args))
    confirm = choose_yes_no("確認執行完整 Benchmark ?", default_yes=False)
    if not confirm:
        print("已取消")
        return

    rc = subprocess.call(args)
    if rc == 0:
        print("Benchmark 執行完成")
    else:
        print(f"Benchmark 失敗，返回碼: {rc}")


def configure_flow() -> None:
    cfg = load_cfg()
    sheet_map = load_sheet_map()

    original_cfg_text = CONFIG_PATH.read_text(encoding="utf-8")
    original_sheet_text = SHEET_ID_LIST_PATH.read_text(encoding="utf-8")

    changed = edit_config_menu(cfg, sheet_map)
    if not changed:
        print("沒有變更")
        return

    new_cfg_text = cfg_to_yaml(cfg)
    new_sheet_text = sheet_map_to_text(sheet_map)

    show_diff(str(CONFIG_PATH), original_cfg_text, new_cfg_text)
    show_diff(str(SHEET_ID_LIST_PATH), original_sheet_text, new_sheet_text)

    confirm = choose_yes_no("套用以上變更?", default_yes=False)
    if not confirm:
        print("已取消保存")
        return

    CONFIG_PATH.write_text(new_cfg_text, encoding="utf-8")
    SHEET_ID_LIST_PATH.write_text(new_sheet_text, encoding="utf-8")
    print("設定已更新")


def quick_setup_flow() -> None:
    cfg = load_cfg()
    sheet_map = load_sheet_map()

    original_cfg_text = CONFIG_PATH.read_text(encoding="utf-8")
    original_sheet_text = SHEET_ID_LIST_PATH.read_text(encoding="utf-8")

    server_entry = ensure_server_entry(cfg)
    server_cfg = server_entry.config
    if "container" not in server_cfg or server_cfg.container is None:
        server_cfg.container = []

    if len(server_cfg.container) > 0:
        target_service = server_cfg.container[0]
    else:
        target_service = OmegaConf.create(
            {
                "name": "service-1",
                "path": "services/run_rs.sh",
                "service_name": "none",
                "tp_size": 1,
            }
        )
        server_cfg.container.append(target_service)

    print("\n[簡易設定]")
    test_name = prompt_input("test name", str(cfg.autotest.name))

    sheet_keys = list(sheet_map.keys())
    if not sheet_keys:
        print("sheet_id_list.json 沒有可用選項，請先新增後再執行簡易設定")
        return
    sheet_idx = choose_index("選擇 sheet_name", sheet_keys)
    if sheet_idx is None:
        print("已取消")
        return
    selected_sheet_name = sheet_keys[sheet_idx]

    script_path = prompt_input("目標腳本位置", str(getattr(target_service, "path", "services/run_rs.sh")))
    script_file = Path(script_path)
    script_file.parent.mkdir(parents=True, exist_ok=True)
    if not script_file.exists():
        script_file.write_text("#!/bin/bash\nset -euo pipefail\n\n", encoding="utf-8")
    open_in_editor(script_file)
    ensure_executable(script_file)
    validate_script_basic(script_file)

    service_name = prompt_input("服務名稱", str(getattr(target_service, "name", "service-1")))
    model_path = prompt_input("model path", str(getattr(server_cfg, "model_path", "")))
    model_name = prompt_input("model name", str(getattr(server_cfg, "model_name", "")))
    model_id = prompt_input("model id", str(getattr(server_cfg, "model_id", "")))
    host = prompt_input("host", str(getattr(server_cfg, "base_url", "http://localhost")))
    port = prompt_int("port", int(getattr(server_cfg, "port", 8000)), min_value=1)

    cfg.autotest.name = test_name
    cfg.autotest.sheet_name = selected_sheet_name

    server_cfg.base_url = host
    server_cfg.port = port
    server_cfg.model_path = model_path
    server_cfg.model_name = model_name
    server_cfg.model_id = model_id

    target_service.path = str(script_file)
    target_service.name = service_name
    target_service.base_url = host
    target_service.port = port
    target_service.model_path = model_path
    target_service.model_name = model_name
    target_service.model_id = model_id

    new_cfg_text = cfg_to_yaml(cfg)
    new_sheet_text = sheet_map_to_text(sheet_map)

    show_diff(str(CONFIG_PATH), original_cfg_text, new_cfg_text)
    show_diff(str(SHEET_ID_LIST_PATH), original_sheet_text, new_sheet_text)

    confirm = choose_yes_no("套用以上變更?", default_yes=False)
    if not confirm:
        print("已取消保存")
        return

    CONFIG_PATH.write_text(new_cfg_text, encoding="utf-8")
    SHEET_ID_LIST_PATH.write_text(new_sheet_text, encoding="utf-8")
    print("簡易設定已更新")


def main() -> int:
    verbosity = consume_verbosity_flags()
    configure_logging(verbosity)

    while True:
        choice = choose_index(
            "=== Benchmark CLI ===",
            [
                "簡易設定",
                "編輯設定檔",
                "編輯 service_account.json",
                "編輯服務腳本",
                "測試服務腳本",
                "預覽 Benchmark",
                "執行完整 Benchmark",
                "離開",
            ],
            allow_back=True,
            esc_mode="single",
        )
        if choice is None:
            return 0

        if choice == 0:
            quick_setup_flow()
            continue
        if choice == 1:
            configure_flow()
            continue
        if choice == 2:
            edit_service_account_json()
            continue
        if choice == 3:
            edit_service_script()
            continue
        if choice == 4:
            cfg = load_cfg()
            test_service_script(cfg)
            wait_for_confirm()
            continue
        if choice == 5:
            cfg = load_cfg()
            preview_benchmark(cfg)
            wait_for_confirm()
            continue
        if choice == 6:
            run_full_benchmark(verbosity)
            continue
        if choice == 7:
            return 0


if __name__ == "__main__":
    sys.exit(main())
