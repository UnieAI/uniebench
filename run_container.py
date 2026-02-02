from omegaconf import DictConfig
import subprocess
import logging
from hydra import main

def run_container(cfg: DictConfig, container_path: dict, service_name, detected = True):
    logging.info(f'start server {container_path}')
    cmd = ['docker', 'compose', '-f', container_path, 'up']
    if service_name:
        cmd.append(service_name)
    if detected:
        cmd.append('-d')
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
        run_container(cfg, container.path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()