import logging
import time

import docker
from hydra import main
from omegaconf import DictConfig


def stop_container(cfg: DictConfig, name: str):
    logging.info("stop container")
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
        stop_container(cfg, container.name)

    for container in cfg.server.container:
        stop_container(cfg, container.name)

        stop_container(cfg, container.name)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
