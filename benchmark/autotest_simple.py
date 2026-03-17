#!/usr/bin/env python3
"""Run benchmark_serving.py against a set of docker compose services."""
# Example:
# python3 benchmark/autotest_simple.py \
#   --service-dir /workspace/nctu6/ascend/service_test \
#   --dataset-path ./data/ShareGPT_V3_unfiltered_cleaned_split.json \
#   --result-dir ./results \
#   --concurrency 1,2 \
#   --debug-break # stop test for debugging errors
from __future__ import annotations

import argparse
import json
import logging
import re
import shlex
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_SERVICE_DIR = Path("/workspace/nctu6/ascend/service")
DEFAULT_HEALTH_TIMEOUT_SEC = 36 * 60
DEFAULT_PORT_FREE_WAIT_SEC = 90
LOG = logging.getLogger("autotest_simple")


@dataclass
class ComposeInfo:
    compose_file: Path
    service_name: str
    host_port: int
    tokenizer: str


def run_cmd(
    cmd: list[str],
    cwd: Path,
    check: bool = True,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        check=check,
        text=True,
        capture_output=capture_output,
    )


def compose_project_name(info: ComposeInfo) -> str:
    slug = re.sub(r"[^a-z0-9_-]", "_", info.compose_file.stem.lower())
    return f"autotest_{slug}"


def diagnose_port_usage(port: int) -> str:
    snippets: list[str] = []
    commands = [
        (
            "lsof",
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
        ),
        (
            "ss listen",
            ["ss", "-H", "-ltn", f"sport = :{port}"],
        ),
        (
            "ss all tcp",
            ["ss", "-H", "-tan", f"sport = :{port}"],
        ),
        (
            "docker ps (publish filter)",
            [
                "docker",
                "ps",
                "--filter",
                f"publish={port}",
                "--format",
                "table {{.ID}}\t{{.Names}}\t{{.Ports}}\t{{.Status}}",
            ],
        ),
    ]
    for label, cmd in commands:
        try:
            result = subprocess.run(
                cmd,
                check=False,
                text=True,
                capture_output=True,
            )
        except FileNotFoundError:
            snippets.append(f"[{label}] command not found: {cmd[0]}")
            continue
        output = (result.stdout or "").strip()
        error = (result.stderr or "").strip()
        if output:
            snippets.append(f"[{label}]\n{output}")
        elif error:
            snippets.append(f"[{label} stderr]\n{error}")
    return "\n".join(snippets)


def wait_for_port_free(port: int, timeout_sec: int) -> None:
    deadline = time.time() + timeout_sec
    owner_hint_logged = False
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            # SO_REUSEADDR avoids false "busy" results from transient TCP states
            # (e.g., TIME_WAIT) while still failing when another process listens.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                return
            except OSError:
                remaining = max(0, int(deadline - time.time()))
                LOG.info("[wait] port %s is busy, remaining=%ss", port, remaining)
                if not owner_hint_logged:
                    details = diagnose_port_usage(port)
                    if details:
                        LOG.info("[wait] port %s diagnostic:\n%s", port, details)
                    owner_hint_logged = True
        time.sleep(1)
    details = diagnose_port_usage(port)
    detail_text = f"\n{details}" if details else ""
    raise TimeoutError(
        f"Port {port} is still busy after {timeout_sec}s{detail_text}"
    )


def setup_logging(log_level: str, log_file: Path | None) -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


def parse_concurrency(raw: str) -> list[int]:
    values: list[int] = []
    for part in raw.split(","):
        value = int(part.strip())
        if value <= 0:
            raise ValueError(f"Concurrency must be positive: {value}")
        values.append(value)
    if not values:
        raise ValueError("At least one concurrency value is required")
    return values


def infer_dataset_name(dataset_path: str) -> str:
    lower = dataset_path.lower()
    if lower.endswith(".json") or lower.endswith(".jsonl"):
        return "sharegpt"
    return "hf"


def find_model_path(command: str | list[str] | None) -> str | None:
    if command is None:
        return None
    if isinstance(command, list):
        tokens: list[str] = []
        for part in command:
            part_str = str(part)
            try:
                tokens.extend(shlex.split(part_str))
            except ValueError:
                tokens.append(part_str)
    else:
        try:
            tokens = shlex.split(command)
        except ValueError:
            tokens = command.split()

    for i, token in enumerate(tokens):
        if token in {"--model", "--model-path"} and i + 1 < len(tokens):
            return tokens[i + 1]
        if token.startswith("--model="):
            return token.split("=", 1)[1]
        if token.startswith("--model-path="):
            return token.split("=", 1)[1]

    # Support `vllm serve <model_path>` style command.
    for i in range(len(tokens) - 2):
        if tokens[i] == "vllm" and tokens[i + 1] == "serve":
            candidate = tokens[i + 2]
            if not candidate.startswith("-"):
                return candidate
    return None


def find_host_port(ports: object) -> int | None:
    if not isinstance(ports, list):
        return None
    for entry in ports:
        if isinstance(entry, dict):
            published = entry.get("published")
            if published is not None:
                return int(str(published))
        if isinstance(entry, str):
            value = entry.split("/", 1)[0]
            parts = value.split(":")
            if len(parts) >= 2 and parts[-2].isdigit():
                return int(parts[-2])
            if len(parts) == 1 and parts[0].isdigit():
                return int(parts[0])
    return None


def parse_compose_with_docker(compose_file: Path, root: Path) -> ComposeInfo:
    result = run_cmd(
        ["docker", "compose", "-f", str(compose_file), "config", "--format", "json"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    config = json.loads(result.stdout)
    services = config.get("services", {})
    if not services:
        raise RuntimeError(f"No services in compose config: {compose_file}")

    service_name = next(iter(services))
    service = services[service_name]
    host_port = find_host_port(service.get("ports"))
    tokenizer = find_model_path(service.get("command"))

    if host_port is None:
        raise RuntimeError(f"Unable to extract host port from {compose_file}")
    if not tokenizer:
        raise RuntimeError(f"Unable to extract model path from {compose_file}")

    return ComposeInfo(
        compose_file=compose_file,
        service_name=service_name,
        host_port=host_port,
        tokenizer=tokenizer,
    )


def parse_compose_fallback(compose_file: Path) -> ComposeInfo:
    content = compose_file.read_text(encoding="utf-8")

    service_match = re.search(r"(?m)^\s{2,}([A-Za-z0-9_.-]+):\s*$", content)
    if service_match:
        service_name = service_match.group(1)
    else:
        service_name = compose_file.stem

    port_match = re.search(r'(?m)^\s*-\s*"?(\d+):\d+(?:/\w+)?"?\s*$', content)
    if not port_match:
        raise RuntimeError(f"Unable to extract host port from {compose_file}")
    host_port = int(port_match.group(1))

    model_match = re.search(r"--model(?:-path)?(?:=|\s+)([^\s\"']+)", content)
    if model_match:
        tokenizer = model_match.group(1)
    else:
        vllm_match = re.search(r"vllm\s+serve\s+([^\s\"'\\]+)", content)
        if not vllm_match:
            raise RuntimeError(f"Unable to extract model path from {compose_file}")
        tokenizer = vllm_match.group(1)

    return ComposeInfo(
        compose_file=compose_file,
        service_name=service_name,
        host_port=host_port,
        tokenizer=tokenizer,
    )


def load_compose_info(compose_file: Path, root: Path) -> ComposeInfo:
    try:
        return parse_compose_with_docker(compose_file, root=root)
    except Exception as exc:
        LOG.warning(
            f"[warn] docker compose config parse failed for {compose_file.name}: {exc}; "
            "using text fallback parser"
        )
        return parse_compose_fallback(compose_file)


def wait_for_health(port: int, timeout_sec: int, interval_sec: int) -> None:
    url = f"http://127.0.0.1:{port}/health"
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            req = Request(url, method="GET")
            with urlopen(req, timeout=3) as resp:
                if 200 <= resp.status < 300:
                    LOG.info("[ok] health check passed: %s", url)
                    return
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            remaining = max(0, int(deadline - time.time()))
            LOG.info("[wait] %s (%s) remaining=%ss", url, exc, remaining)
        time.sleep(interval_sec)
    raise TimeoutError(f"Health check timed out for {url}")


def run_benchmark_for_concurrency(
    root: Path,
    benchmark_script: Path,
    dataset_path: str,
    result_dir: Path,
    model_name: str,
    info: ComposeInfo,
    concurrency: int,
    prompts_factor: int,
    seed: int,
    python_bin: str,
) -> None:
    dataset_name = infer_dataset_name(dataset_path)
    if dataset_name == "sharegpt":
        dataset_path_str = str(Path(dataset_path).expanduser().resolve())
    else:
        dataset_path_str = dataset_path

    result_filename = f"{info.service_name}.{concurrency}.json"
    cmd = [
        python_bin,
        str(benchmark_script),
        "--model",
        model_name,
        "--backend",
        "openai",
        "--base-url",
        f"http://0.0.0.0:{info.host_port}",
        "--tokenizer",
        info.tokenizer,
        "--dataset-name",
        dataset_name,
        "--dataset-path",
        dataset_path_str,
        "--num-prompts",
        str(concurrency * prompts_factor),
        "--seed",
        str(seed),
        "--max-concurrency",
        str(concurrency),
        "--request-rate",
        "inf",
        "--ignore-eos",
        "--save-result",
        "--percentile-metrics",
        "ttft,tpot,itl,e2el",
        "--result-dir",
        str(result_dir),
        "--result-filename",
        result_filename,
    ]
    if dataset_name == "hf":
        cmd.extend(["--hf-split", "train", "--hf-output-len", "1024"])
    else:
        cmd.extend(["--sharegpt-output-len", "1024"])

    LOG.info("[run] %s", " ".join(cmd))
    run_cmd(cmd, cwd=root, check=True, capture_output=False)


def result_file_path(result_dir: Path, service_name: str, concurrency: int) -> Path:
    return result_dir / f"{service_name}.{concurrency}.json"


def compose_up(root: Path, info: ComposeInfo) -> None:
    compose_dir = info.compose_file.parent
    compose_name = info.compose_file.name
    project_name = compose_project_name(info)
    cmd = [
        "docker",
        "compose",
        "-p",
        project_name,
        "-f",
        compose_name,
        "up",
        "-d",
        info.service_name,
    ]
    LOG.info("[run] %s (cwd=%s)", " ".join(cmd), compose_dir)
    result = run_cmd(cmd, cwd=compose_dir, check=False, capture_output=True)
    if result.stdout:
        LOG.info("[docker-compose-up stdout]\n%s", result.stdout.rstrip())
    if result.stderr:
        LOG.info("[docker-compose-up stderr]\n%s", result.stderr.rstrip())
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, cmd, output=result.stdout, stderr=result.stderr
        )


def compose_down(root: Path, info: ComposeInfo) -> None:
    compose_dir = info.compose_file.parent
    compose_name = info.compose_file.name
    project_name = compose_project_name(info)
    cmd = ["docker", "compose", "-p", project_name, "-f", compose_name, "down"]
    LOG.info("[run] %s (cwd=%s)", " ".join(cmd), compose_dir)
    run_cmd(cmd, cwd=compose_dir, check=False, capture_output=False)


def iterate_compose_files(service_dir: Path) -> Iterable[Path]:
    files = sorted(service_dir.glob("*.yml"))
    if not files:
        raise RuntimeError(f"No compose files found in {service_dir}")
    return files


def configure_argparse() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Autotest benchmark loop for docker-compose services."
    )
    parser.add_argument(
        "--service-dir",
        type=Path,
        default=DEFAULT_SERVICE_DIR,
        help="Directory containing docker compose *.yml files.",
    )
    parser.add_argument(
        "--benchmark-script",
        type=Path,
        default=root / "benchmark/inferencemax-h100/bench_serving/benchmark_serving.py",
    )
    parser.add_argument(
        "--dataset-path",
        default=str(root / "data/ShareGPT_V3_unfiltered_cleaned_split.json"),
    )
    parser.add_argument(
        "--result-dir",
        type=Path,
        default=root / "results",
    )
    parser.add_argument("--model-name", default="test")
    parser.add_argument("--python-bin", default="python3")
    parser.add_argument(
        "--health-timeout",
        type=int,
        default=DEFAULT_HEALTH_TIMEOUT_SEC,
        help="Health check timeout in seconds. Default: 2160 (36 minutes).",
    )
    parser.add_argument("--health-interval", type=int, default=6)
    parser.add_argument(
        "--prompts-factor",
        type=int,
        default=10,
        help="num-prompts = concurrency * prompts-factor",
    )
    parser.add_argument(
        "--concurrency",
        default="1,16,32,64,128,256,512",
        help="Comma-separated concurrency values.",
    )
    parser.add_argument("--seed", type=int, default=0, help="Random seed. Default: 0.")
    parser.add_argument(
        "--debug-break",
        action="store_true",
        help="Stop immediately on first failure for debugging.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level for autotest logs.",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=Path("./results/autotest_simple.log"),
        help="Log file path. Default: ./results/autotest_simple.log",
    )
    return parser


def main() -> int:
    parser = configure_argparse()
    args = parser.parse_args()
    setup_logging(args.log_level, args.log_file)

    root = Path(__file__).resolve().parents[1]
    service_dir = args.service_dir
    benchmark_script = args.benchmark_script
    dataset_path = args.dataset_path.strip()
    result_dir = args.result_dir
    concurrency_values = parse_concurrency(args.concurrency)

    if not service_dir.exists():
        raise RuntimeError(f"service-dir not found: {service_dir}")
    if not benchmark_script.exists():
        raise RuntimeError(f"benchmark-script not found: {benchmark_script}")
    if not dataset_path:
        raise RuntimeError("dataset-path is empty")
    if infer_dataset_name(dataset_path) == "sharegpt":
        dataset_path_obj = Path(dataset_path).expanduser()
        if not dataset_path_obj.exists():
            raise RuntimeError(f"dataset-path not found: {dataset_path_obj}")
        dataset_path = str(dataset_path_obj.resolve())
    result_dir.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []
    total_cases = 0
    success_cases = 0
    skipped_cases = 0
    stop_requested = False
    compose_files = list(iterate_compose_files(service_dir))

    LOG.info("[info] root: %s", root)
    LOG.info("[info] service-dir: %s", service_dir)
    LOG.info("[info] benchmark-script: %s", benchmark_script)
    LOG.info("[info] dataset-path: %s", dataset_path)
    LOG.info("[info] result-dir: %s", result_dir)
    LOG.info("[info] compose files: %s", len(compose_files))
    LOG.info("[info] concurrency: %s", concurrency_values)
    LOG.info("[info] seed: %s", args.seed)
    LOG.info("[info] debug-break: %s", args.debug_break)

    for compose_file in compose_files:
        try:
            info = load_compose_info(compose_file, root=root)
        except Exception as exc:
            message = f"{compose_file.name} (parse compose): {exc}"
            failures.append(message)
            LOG.exception("[error] %s", message)
            if args.debug_break:
                LOG.warning("[debug-break] stopping after parse failure")
                stop_requested = True
                break
            continue
        LOG.info(
            "[info] service=%s compose=%s port=%s tokenizer=%s",
            info.service_name,
            compose_file.name,
            info.host_port,
            info.tokenizer,
        )
        pending_concurrency = [
            conc for conc in concurrency_values
            if not result_file_path(result_dir, info.service_name, conc).exists()
        ]
        if not pending_concurrency:
            skipped_cases += len(concurrency_values)
            LOG.info(
                "[skip] compose=%s all result json already exists in %s",
                compose_file.name,
                result_dir,
            )
            continue

        for conc in concurrency_values:
            result_json = result_file_path(result_dir, info.service_name, conc)
            if result_json.exists():
                skipped_cases += 1
                LOG.info(
                    "[skip] compose=%s service=%s concurrency=%s result exists: %s",
                    compose_file.name,
                    info.service_name,
                    conc,
                    result_json,
                )
                continue
            total_cases += 1
            case_failed = False
            LOG.info(
                "[start] compose=%s service=%s concurrency=%s",
                compose_file.name,
                info.service_name,
                conc,
            )
            start_ts = time.time()
            try:
                wait_for_port_free(info.host_port, timeout_sec=DEFAULT_PORT_FREE_WAIT_SEC)
                compose_up(root=root, info=info)
                wait_for_health(
                    port=info.host_port,
                    timeout_sec=args.health_timeout,
                    interval_sec=args.health_interval,
                )
                run_benchmark_for_concurrency(
                    root=root,
                    benchmark_script=benchmark_script,
                    dataset_path=dataset_path,
                    result_dir=result_dir,
                    model_name=args.model_name,
                    info=info,
                    concurrency=conc,
                    prompts_factor=args.prompts_factor,
                    seed=args.seed,
                    python_bin=args.python_bin,
                )
                elapsed = time.time() - start_ts
                LOG.info(
                    "[done] compose=%s service=%s concurrency=%s elapsed=%.1fs",
                    compose_file.name,
                    info.service_name,
                    conc,
                    elapsed,
                )
                success_cases += 1
            except Exception as exc:
                message = f"{compose_file.name} (concurrency={conc}): {exc}"
                failures.append(message)
                LOG.exception("[error] %s", message)
                case_failed = True
            finally:
                LOG.info(
                    "[teardown] compose=%s service=%s concurrency=%s",
                    compose_file.name,
                    info.service_name,
                    conc,
                )
                try:
                    compose_down(root=root, info=info)
                except Exception as exc:
                    message = (
                        f"{compose_file.name} (concurrency={conc}, teardown): {exc}"
                    )
                    failures.append(message)
                    LOG.exception("[error] %s", message)
                    case_failed = True
            if case_failed and args.debug_break:
                LOG.warning(
                    "[debug-break] stopping after failure at compose=%s concurrency=%s",
                    compose_file.name,
                    conc,
                )
                stop_requested = True
                break
        if stop_requested:
            break

    if failures:
        LOG.error("[summary] FAILURES")
        LOG.error(
            "[summary] cases success=%s/%s skipped=%s",
            success_cases,
            total_cases,
            skipped_cases,
        )
        for item in failures:
            LOG.error("- %s", item)
        return 1

    LOG.info(
        "[summary] cases success=%s/%s skipped=%s",
        success_cases,
        total_cases,
        skipped_cases,
    )
    LOG.info("[summary] all benchmarks completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
