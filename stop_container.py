import logging
import os
import signal
import time
from typing import Optional

import docker
from hydra import main
from omegaconf import DictConfig


def _is_host_shell_script(container_path: Optional[str]) -> bool:
    return bool(container_path and container_path.endswith(".sh"))


def _pid_file_path(container_name: str) -> str:
    safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in container_name)
    return os.path.join(".runtime_pids", f"{safe_name}.pid")


def _read_pid(container_name: str) -> Optional[int]:
    pid_path = _pid_file_path(container_name)
    if not os.path.exists(pid_path):
        return None
    try:
        with open(pid_path, "r", encoding="utf-8") as pid_file:
            return int(pid_file.read().strip())
    except (OSError, ValueError):
        return None


def _remove_pid_file(container_name: str) -> None:
    pid_path = _pid_file_path(container_name)
    try:
        os.remove(pid_path)
    except FileNotFoundError:
        pass


def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _stop_shell_process(name: str, pid: Optional[int]) -> None:
    target_pid = pid if pid is not None else _read_pid(name)
    if target_pid is None:
        logging.warning(f"no pid found for shell script container {name}")
        return

    logging.info(f"stop shell script pid {target_pid}")
    try:
        os.kill(target_pid, signal.SIGTERM)
    except ProcessLookupError:
        _remove_pid_file(name)
        return

    for _ in range(20):
        if not _is_process_alive(target_pid):
            _remove_pid_file(name)
            return
        time.sleep(0.25)

    try:
        os.kill(target_pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    _remove_pid_file(name)


def stop_container(cfg: DictConfig, name: str, container_path: Optional[str] = None, pid: Optional[int] = None):
    logging.info("stop container")
    if _is_host_shell_script(container_path):
        _stop_shell_process(name, pid)
        return

    try:
        container = docker.from_env().containers.get(name)
        container.stop()
        container.wait()
        container.remove(force=True)
        time.sleep(5)
    except docker.errors.NotFound:
        pass


@main(config_path="config", config_name="config", version_base="1.2")
def main(cfg: DictConfig) -> None:
    # start server (outer loop)
    for container in cfg.server.container:
        stop_container(cfg, container.name, getattr(container, "path", None))

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
