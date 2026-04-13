import logging
import os
import subprocess
from typing import Optional

from hydra import main
from omegaconf import DictConfig

from log_utils import consume_verbosity_flags, configure_logging, TRACE_LEVEL


def _is_host_shell_script(container_path: str) -> bool:
    return container_path.endswith(".sh")


def _pid_file_path(container_name: str) -> str:
    safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in container_name)
    os.makedirs(".runtime_pids", exist_ok=True)
    return os.path.join(".runtime_pids", f"{safe_name}.pid")


def run_container(cfg: DictConfig,
                  container_path: str,
                  service_name: str = None,
                  detected: bool = True,
                  container_name: Optional[str] = None) -> Optional[int]:
    logging.info("start server from %s", container_path)
    if _is_host_shell_script(container_path):
        cmd = ["bash", container_path]
    else:
        cmd = ["docker", "compose", "-f", container_path, "up"]
        if service_name and service_name != "none":
            cmd.append(service_name)
        if detected:
            cmd.append("-d")
    logging.debug("startup command: %s", cmd)
    logging.log(TRACE_LEVEL, "startup options: service_name=%s detected=%s", service_name, detected)
    popen_kwargs = {}
    if _is_host_shell_script(container_path):
        # Show inference engine stdout/stderr only on -vv / -vvv.
        if logging.getLogger().getEffectiveLevel() > TRACE_LEVEL:
            popen_kwargs["stdout"] = subprocess.DEVNULL
            popen_kwargs["stderr"] = subprocess.DEVNULL
            logging.debug("suppressing shell service logs (enable -vv or -vvv to show)")
        else:
            logging.debug("shell service logs are enabled")

    try:
        process = subprocess.Popen(
            cmd,
            start_new_session=_is_host_shell_script(container_path),
            **popen_kwargs,
        )
    except OSError as exc:
        logging.error("server startup failed: %s", exc)
        raise RuntimeError(f"failed to start server command: {cmd}") from exc

    if _is_host_shell_script(container_path) and container_name:
        pid_path = _pid_file_path(container_name)
        with open(pid_path, "w", encoding="utf-8") as pid_file:
            pid_file.write(str(process.pid))
        logging.debug("recorded shell script pid %s in %s", process.pid, pid_path)
        return process.pid

    return None

@main(config_path="config", config_name="config", version_base="1.2")
def main(cfg: DictConfig) -> None:
    # start server (outer loop)
    if cfg.server.id:
        for server_config in cfg.default_config.server:
            if server_config.id == cfg.server.id:
                cfg.server = {
                    **cfg.server,
                    **server_config.config
                }
    for container in cfg.server.container:
        service_name = getattr(container, "service_name", None)
        run_container(cfg, container.path, service_name, container_name=container.name)


if __name__ == "__main__":
    configure_logging(consume_verbosity_flags())
    main()
