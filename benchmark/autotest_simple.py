#!/usr/bin/env python3
"""Run benchmark_serving.py against a set of docker compose services."""
# Example:
# python3 benchmark/autotest_simple.py \
#   --service-dir /workspace/nctu6/ascend/service_test \
#   --dataset-path ./data/ShareGPT_V3_unfiltered_cleaned_split.json \
#   --result-dir ./results \
#   --concurrency 1,2 \
#   --with-container \
#   --base-url http://127.0.0.1:8080 \
#   --tokenizer /workspace/model \
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
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

DEFAULT_SERVICE_DIR = Path("/workspace/nctu6/ascend/service")
DEFAULT_HEALTH_TIMEOUT_SEC = 36 * 60
DEFAULT_PORT_FREE_WAIT_SEC = 90
DEFAULT_MODEL_NAME = "test"
DEFAULT_TEXT_OUTPUT_LEN = 1024
DEFAULT_VLM_OUTPUT_LEN = 32
DEFAULT_VLM_DATASET_PATH = "lmms-lab/VQAv2"
DEFAULT_VLM_HF_SPLIT = "validation"
DEFAULT_EMBEDDING_DATASET_PATH = "BeIR/scifact"
DEFAULT_EMBEDDING_HF_SUBSET = "corpus"
DEFAULT_EMBEDDING_HF_SPLIT = "corpus"
LOG = logging.getLogger("autotest_simple")


@dataclass
class ComposeInfo:
    compose_file: Path
    service_name: str
    host_port: int | None
    tokenizer: str
    base_url: str | None = None


@dataclass
class BenchmarkConfig:
    task: str
    benchmark_script: Path
    dataset_name: str
    dataset_path: str
    backend: str | None
    endpoint: str | None
    hf_subset: str | None
    hf_split: str | None
    output_len: int | None


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


def normalize_base_url(raw_url: str) -> str:
    url = raw_url.strip().rstrip("/")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Invalid URL: {raw_url}")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def benchmark_base_url(info: ComposeInfo) -> str:
    if info.base_url:
        return info.base_url
    if info.host_port is None:
        raise RuntimeError(f"No host port/base URL available for {info.service_name}")
    return f"http://0.0.0.0:{info.host_port}"


def healthcheck_url(info: ComposeInfo) -> str:
    if info.base_url:
        parsed = urlsplit(info.base_url)
        path = parsed.path.rstrip("/")
        if path.endswith("/v1"):
            path = path[:-3]
        health_path = f"{path}/health" if path else "/health"
        return urlunsplit((parsed.scheme, parsed.netloc, health_path, "", ""))
    if info.host_port is None:
        raise RuntimeError(f"No host port/base URL available for {info.service_name}")
    return f"http://127.0.0.1:{info.host_port}/health"


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


def resolve_request_model_name(configured_model_name: str, info: ComposeInfo) -> str:
    if configured_model_name != DEFAULT_MODEL_NAME:
        return configured_model_name
    return info.service_name


def infer_text_dataset_name(dataset_path: str) -> str:
    lower = dataset_path.lower()
    if lower.endswith(".json") or lower.endswith(".jsonl"):
        return "sharegpt"
    return "hf"


def infer_benchmark_task(task: str, dataset_path: str | None) -> str:
    if task != "auto":
        return task
    lower = (dataset_path or "").strip().lower()
    if lower == DEFAULT_VLM_DATASET_PATH.lower():
        return "vlm"
    if lower == DEFAULT_EMBEDDING_DATASET_PATH.lower():
        return "embedding"
    return "text"


def resolve_dataset_path(task: str, dataset_path: str | None, root: Path) -> str:
    if dataset_path and dataset_path.strip():
        return dataset_path.strip()
    if task == "vlm":
        return DEFAULT_VLM_DATASET_PATH
    if task == "embedding":
        return DEFAULT_EMBEDDING_DATASET_PATH
    return str(root / "data/ShareGPT_V3_unfiltered_cleaned_split.json")


def resolve_benchmark_script(task: str, benchmark_script: Path | None, root: Path) -> Path:
    if benchmark_script is not None:
        return benchmark_script
    return root / "benchmark/inferencemax-h100/bench_serving/benchmark_serving.py"


def resolve_benchmark_config(
    args: argparse.Namespace,
    root: Path,
) -> BenchmarkConfig:
    task = infer_benchmark_task(args.benchmark_task, args.dataset_path)
    dataset_path = resolve_dataset_path(task, args.dataset_path, root)
    benchmark_script = resolve_benchmark_script(task, args.benchmark_script, root)

    if task == "embedding":
        return BenchmarkConfig(
            task=task,
            benchmark_script=benchmark_script,
            dataset_name="hf",
            dataset_path=dataset_path,
            backend="openai-embeddings",
            endpoint=args.endpoint or "/v1/embeddings",
            hf_subset=args.hf_subset or DEFAULT_EMBEDDING_HF_SUBSET,
            hf_split=args.hf_split or DEFAULT_EMBEDDING_HF_SPLIT,
            output_len=None,
        )

    if task == "vlm":
        return BenchmarkConfig(
            task=task,
            benchmark_script=benchmark_script,
            dataset_name="hf",
            dataset_path=dataset_path,
            backend=args.backend or "openai-chat",
            endpoint=args.endpoint or "/v1/chat/completions",
            hf_subset=args.hf_subset,
            hf_split=args.hf_split or DEFAULT_VLM_HF_SPLIT,
            output_len=args.output_len or DEFAULT_VLM_OUTPUT_LEN,
        )

    dataset_name = infer_text_dataset_name(dataset_path)
    return BenchmarkConfig(
        task=task,
        benchmark_script=benchmark_script,
        dataset_name=dataset_name,
        dataset_path=dataset_path,
        backend=args.backend or "openai",
        endpoint=args.endpoint or "/v1/completions",
        hf_subset=args.hf_subset,
        hf_split=args.hf_split or ("train" if dataset_name == "hf" else None),
        output_len=args.output_len or DEFAULT_TEXT_OUTPUT_LEN,
    )


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


def wait_for_health(url: str, timeout_sec: int, interval_sec: int) -> None:
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
    benchmark_config: BenchmarkConfig,
    result_dir: Path,
    model_name: str,
    info: ComposeInfo,
    concurrency: int,
    prompts_factor: int,
    seed: int,
    python_bin: str,
) -> None:
    result_filename = f"{info.service_name}.{concurrency}.json"
    if benchmark_config.dataset_name == "sharegpt":
        dataset_path_str = str(
            Path(benchmark_config.dataset_path).expanduser().resolve()
        )
    else:
        dataset_path_str = benchmark_config.dataset_path

    cmd = [
        python_bin,
        str(benchmark_config.benchmark_script),
        "--model",
        resolve_request_model_name(model_name, info),
        "--base-url",
        benchmark_base_url(info),
        "--tokenizer",
        info.tokenizer,
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
        "--save-result",
        "--result-dir",
        str(result_dir),
        "--result-filename",
        result_filename,
        "--backend",
        benchmark_config.backend or "openai",
        "--endpoint",
        benchmark_config.endpoint or "/v1/completions",
        "--dataset-name",
        benchmark_config.dataset_name,
        "--percentile-metrics",
        "ttft,tpot,itl,e2el",
    ]
    if benchmark_config.task != "embedding":
        cmd.append("--ignore-eos")
    if benchmark_config.dataset_name == "hf":
        if benchmark_config.hf_subset:
            cmd.extend(["--hf-subset", benchmark_config.hf_subset])
        if benchmark_config.hf_split:
            cmd.extend(["--hf-split", benchmark_config.hf_split])
        if benchmark_config.output_len is not None:
            cmd.extend(["--hf-output-len", str(benchmark_config.output_len)])
    elif benchmark_config.output_len is not None:
        cmd.extend(
            ["--sharegpt-output-len", str(benchmark_config.output_len)]
        )

    LOG.info("[run] %s", " ".join(cmd))
    run_cmd(cmd, cwd=root, check=True, capture_output=False)


def result_file_path(result_dir: Path, service_name: str, concurrency: int) -> Path:
    return result_dir / f"{service_name}.{concurrency}.json"


def docker_service_log_path(root: Path, service_name: str) -> Path:
    safe_service_name = re.sub(r"[^A-Za-z0-9_.-]", "_", service_name)
    return root / "logs" / f"docker_{safe_service_name}.log"


def start_compose_logs_stream(root: Path, info: ComposeInfo) -> subprocess.Popen[str]:
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
        "logs",
        "-f",
        "--timestamps",
        info.service_name,
    ]
    log_path = docker_service_log_path(root=root, service_name=info.service_name)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(
            f"\n===== stream start compose={compose_name} "
            f"service={info.service_name} ts={time.strftime('%Y-%m-%d %H:%M:%S')} =====\n"
        )
        log_file.flush()
        proc = subprocess.Popen(
            cmd,
            cwd=str(compose_dir),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
    LOG.info("[docker-logs] streaming %s -> %s", info.service_name, log_path)
    return proc


def stop_compose_logs_stream(proc: subprocess.Popen[str] | None) -> None:
    if proc is None:
        return
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    else:
        proc.wait(timeout=1)


def compose_up(root: Path, info: ComposeInfo) -> subprocess.Popen[str] | None:
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
    return start_compose_logs_stream(root=root, info=info)


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
        default=None,
        help=(
            "Optional benchmark script override. Defaults to the unified "
            "benchmark/inferencemax-h100/bench_serving/benchmark_serving.py "
            "for text, VLM, and embedding tasks."
        ),
    )
    parser.add_argument(
        "--benchmark-task",
        default="auto",
        choices=["auto", "text", "vlm", "embedding"],
        help=(
            "Benchmark mode. 'auto' infers from --dataset-path; "
            f"{DEFAULT_VLM_DATASET_PATH} maps to 'vlm' and "
            f"{DEFAULT_EMBEDDING_DATASET_PATH} maps to 'embedding'."
        ),
    )
    parser.add_argument(
        "--backend",
        default=None,
        help=(
            "Override backend for text/VLM runs. Defaults: openai for text, "
            "openai-chat for VLM, and openai-embeddings for embeddings."
        ),
    )
    parser.add_argument(
        "--endpoint",
        default=None,
        help=(
            "Override API endpoint. Defaults: /v1/completions for text, "
            "/v1/chat/completions for VLM, /v1/embeddings for embedding."
        ),
    )
    parser.add_argument(
        "--dataset-path",
        default=None,
        help=(
            "Local dataset path or Hugging Face dataset ID. Defaults to "
            f"{root / 'data/ShareGPT_V3_unfiltered_cleaned_split.json'} for "
            f"text, {DEFAULT_VLM_DATASET_PATH} for VLM, and "
            f"{DEFAULT_EMBEDDING_DATASET_PATH} for embeddings."
        ),
    )
    parser.add_argument(
        "--hf-subset",
        default=None,
        help="Optional Hugging Face dataset subset name.",
    )
    parser.add_argument(
        "--hf-split",
        default=None,
        help=(
            "Optional Hugging Face split override. Defaults: train for text HF, "
            f"{DEFAULT_VLM_HF_SPLIT} for VLM, {DEFAULT_EMBEDDING_HF_SPLIT} "
            "for embeddings. Some embedding datasets also require "
            "--hf-subset, e.g. BeIR/scifact -> corpus."
        ),
    )
    parser.add_argument(
        "--output-len",
        type=int,
        default=None,
        help=(
            "Fixed output length override for text/VLM benchmark requests. "
            f"Defaults to {DEFAULT_TEXT_OUTPUT_LEN} for text and "
            f"{DEFAULT_VLM_OUTPUT_LEN} for VLM."
        ),
    )
    parser.add_argument(
        "--result-dir",
        type=Path,
        default=root / "results",
    )
    parser.add_argument("--model-name", default="test")
    parser.add_argument("--python-bin", default="python3")
    parser.add_argument(
        "--service-name",
        default="with-container",
        help="Service name used for result filename in --with-container direct mode.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=(
            "Host port of an already-running endpoint. If set with --with-container, "
            "service-dir/compose files are not required."
        ),
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help=(
            "Base URL of an already-running endpoint in --with-container direct "
            "mode, for example http://127.0.0.1:8080 or "
            "http://172.20.150.11:60201."
        ),
    )
    parser.add_argument(
        "--tokenizer",
        default=None,
        help=(
            "Tokenizer/model path for benchmark_serving.py in --with-container "
            "direct mode. Defaults to --model-name when omitted."
        ),
    )
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
        "--with-container",
        action="store_true",
        help=(
            "Assume containers are already running. Skip docker compose "
            "up/down and docker compose log streaming."
        ),
    )
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
    benchmark_config = resolve_benchmark_config(args, root)
    result_dir = args.result_dir
    concurrency_values = parse_concurrency(args.concurrency)

    if not benchmark_config.benchmark_script.exists():
        raise RuntimeError(
            f"benchmark-script not found: {benchmark_config.benchmark_script}"
        )
    if not benchmark_config.dataset_path:
        raise RuntimeError("dataset-path is empty")
    if benchmark_config.dataset_name == "sharegpt":
        dataset_path_obj = Path(benchmark_config.dataset_path).expanduser()
        if not dataset_path_obj.exists():
            raise RuntimeError(f"dataset-path not found: {dataset_path_obj}")
        benchmark_config.dataset_path = str(dataset_path_obj.resolve())
    result_dir.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []
    total_cases = 0
    success_cases = 0
    skipped_cases = 0
    stop_requested = False
    LOG.info("[info] root: %s", root)
    LOG.info("[info] service-dir: %s", service_dir)
    LOG.info("[info] benchmark-task: %s", benchmark_config.task)
    LOG.info("[info] benchmark-script: %s", benchmark_config.benchmark_script)
    LOG.info("[info] dataset-name: %s", benchmark_config.dataset_name)
    LOG.info("[info] dataset-path: %s", benchmark_config.dataset_path)
    LOG.info("[info] backend: %s", benchmark_config.backend)
    LOG.info("[info] endpoint: %s", benchmark_config.endpoint)
    LOG.info("[info] hf-subset: %s", benchmark_config.hf_subset)
    LOG.info("[info] hf-split: %s", benchmark_config.hf_split)
    LOG.info("[info] output-len: %s", benchmark_config.output_len)
    LOG.info("[info] result-dir: %s", result_dir)
    LOG.info("[info] concurrency: %s", concurrency_values)
    LOG.info("[info] seed: %s", args.seed)
    LOG.info("[info] with-container: %s", args.with_container)
    LOG.info("[info] base-url: %s", args.base_url)
    LOG.info("[info] port: %s", args.port)
    LOG.info("[info] tokenizer: %s", args.tokenizer or args.model_name)
    LOG.info("[info] debug-break: %s", args.debug_break)

    compose_infos: list[ComposeInfo] = []
    if args.with_container:
        normalized_base_url = None
        parsed_port = args.port
        if args.base_url:
            normalized_base_url = normalize_base_url(args.base_url)
            parsed = urlsplit(normalized_base_url)
            parsed_port = parsed.port
        if parsed_port is None and normalized_base_url is None:
            raise RuntimeError(
                "Either --port or --base-url is required when --with-container is set"
            )
        compose_infos.append(
            ComposeInfo(
                compose_file=Path("with-container"),
                service_name=args.service_name,
                host_port=parsed_port,
                tokenizer=args.tokenizer or args.model_name,
                base_url=normalized_base_url,
            )
        )
        LOG.info(
            "[info] direct with-container mode: service=%s base-url=%s port=%s tokenizer=%s",
            args.service_name,
            normalized_base_url,
            parsed_port,
            args.tokenizer or args.model_name,
        )
    else:
        if not service_dir.exists():
            raise RuntimeError(f"service-dir not found: {service_dir}")
        compose_files = list(iterate_compose_files(service_dir))
        LOG.info("[info] compose files: %s", len(compose_files))
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
            compose_infos.append(info)

    if not compose_infos:
        raise RuntimeError(
            "No service targets found. Set --port/--base-url with --with-container, "
            "or provide compose files via --service-dir."
        )

    if not stop_requested:
        for conc in concurrency_values:
            LOG.info("[pass] concurrency=%s", conc)
            for info in compose_infos:
                compose_file = info.compose_file
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
                docker_log_proc: subprocess.Popen[str] | None = None
                try:
                    if args.with_container:
                        LOG.info(
                            "[container] skip compose up (use existing container): "
                            "compose=%s service=%s",
                            compose_file.name,
                            info.service_name,
                        )
                    else:
                        wait_for_port_free(
                            info.host_port,
                            timeout_sec=DEFAULT_PORT_FREE_WAIT_SEC,
                        )
                        docker_log_proc = compose_up(root=root, info=info)
                    wait_for_health(
                        url=healthcheck_url(info),
                        timeout_sec=args.health_timeout,
                        interval_sec=args.health_interval,
                    )
                    run_benchmark_for_concurrency(
                        root=root,
                        benchmark_config=benchmark_config,
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
                    if args.with_container:
                        LOG.info(
                            "[container] skip compose down (keep existing container): "
                            "compose=%s service=%s",
                            compose_file.name,
                            info.service_name,
                        )
                    else:
                        try:
                            compose_down(root=root, info=info)
                        except Exception as exc:
                            message = (
                                f"{compose_file.name} (concurrency={conc}, teardown): {exc}"
                            )
                            failures.append(message)
                            LOG.exception("[error] %s", message)
                            case_failed = True
                        try:
                            stop_compose_logs_stream(docker_log_proc)
                        except Exception as exc:
                            message = (
                                f"{compose_file.name} "
                                f"(concurrency={conc}, docker log stream): {exc}"
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
