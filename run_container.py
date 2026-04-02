import logging
import subprocess

from hydra import main
from omegaconf import DictConfig


def _is_host_shell_script(container_path: str) -> bool:
    return container_path.endswith(".sh")


def run_container(cfg: DictConfig,
                  container_path: str,
                  service_name: str = None,
                  detected: bool = True):
    logging.info(f"start server {container_path}")
    if _is_host_shell_script(container_path):
        cmd = ["bash", container_path]
    else:
        cmd = ["docker", "compose", "-f", container_path, "up"]
        if service_name and service_name != "none":
            cmd.append(service_name)
        if detected:
            cmd.append("-d")
    logging.info(cmd)
    subprocess.Popen(cmd)

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
        run_container(cfg, container.path, service_name)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
