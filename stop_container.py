import logging
import os
import signal
import time
from typing import Optional, Tuple

import docker
from hydra import main
from omegaconf import DictConfig

from log_utils import consume_verbosity_flags, configure_logging, TRACE_LEVEL


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


def _read_proc_stat(pid: int) -> Optional[Tuple[str, int]]:
    stat_path = f"/proc/{pid}/stat"
    try:
        with open(stat_path, "r", encoding="utf-8") as stat_file:
            content = stat_file.read().strip()
    except OSError:
        return None

    # Format: pid (comm) state ppid pgrp ...
    close_idx = content.rfind(")")
    if close_idx == -1 or close_idx + 2 >= len(content):
        return None
    fields = content[close_idx + 2 :].split()
    if len(fields) < 3:
        return None
    state = fields[0]
    try:
        pgrp = int(fields[2])
    except ValueError:
        return None
    return state, pgrp


def _reap_if_child(pid: int) -> bool:
    try:
        waited_pid, _ = os.waitpid(pid, os.WNOHANG)
        return waited_pid == pid
    except ChildProcessError:
        return False
    except OSError:
        return False


def _is_process_group_alive(pgid: int) -> bool:
    # Prefer /proc inspection so zombie processes do not block next rounds.
    if os.path.isdir("/proc"):
        try:
            for entry in os.listdir("/proc"):
                if not entry.isdigit():
                    continue
                stat = _read_proc_stat(int(entry))
                if stat is None:
                    continue
                state, pgrp = stat
                if pgrp == pgid and state != "Z":
                    return True
            return False
        except OSError:
            pass

    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _stop_shell_process(name: str, pid: Optional[int]) -> None:
    target_pid = pid if pid is not None else _read_pid(name)
    if target_pid is None:
        raise RuntimeError(f"server shutdown failed: no pid found for shell script container {name}")

    logging.info("stop shell script process group %s", target_pid)
    try:
        os.killpg(target_pid, signal.SIGTERM)
    except ProcessLookupError:
        _remove_pid_file(name)
        return

    for attempt in range(20):
        _reap_if_child(target_pid)
        if not _is_process_group_alive(target_pid):
            _reap_if_child(target_pid)
            _remove_pid_file(name)
            return
        logging.log(TRACE_LEVEL, "waiting process group %s to exit... attempt %s/20", target_pid, attempt + 1)
        time.sleep(0.25)

    try:
        os.killpg(target_pid, signal.SIGKILL)
    except ProcessLookupError:
        pass

    for attempt in range(20):
        _reap_if_child(target_pid)
        if not _is_process_group_alive(target_pid):
            _reap_if_child(target_pid)
            _remove_pid_file(name)
            return
        logging.log(
            TRACE_LEVEL,
            "waiting process group %s to exit after SIGKILL... attempt %s/20",
            target_pid,
            attempt + 1,
        )
        time.sleep(0.25)

    raise RuntimeError(f"server shutdown failed: process group {target_pid} is still alive after SIGKILL")


def stop_container(cfg: DictConfig, name: str, container_path: Optional[str] = None, pid: Optional[int] = None):
    logging.info("stop container: %s", name)
    if _is_host_shell_script(container_path):
        _stop_shell_process(name, pid)
        return

    try:
        container = docker.from_env().containers.get(name)
        logging.debug("stopping docker container %s", name)
        container.stop()
        container.wait()
        container.remove(force=True)
        time.sleep(5)
    except docker.errors.NotFound:
        logging.warning("server shutdown skipped: container not found (%s)", name)
    except docker.errors.DockerException as exc:
        logging.error("server shutdown failed: %s", exc)
        raise


@main(config_path="config", config_name="config", version_base="1.2")
def main(cfg: DictConfig) -> None:
    # start server (outer loop)
    for container in cfg.server.container:
        stop_container(cfg, container.name, getattr(container, "path", None))

if __name__ == "__main__":
    configure_logging(consume_verbosity_flags())
    main()
