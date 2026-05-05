import logging
import time

import requests
from hydra import main
from omegaconf import DictConfig

from log_utils import consume_verbosity_flags, configure_logging, TRACE_LEVEL


def wait_for_healthcheck(cfg: DictConfig, container_name: str) -> None:
    logging.info('waiting for healthcheck: %s', container_name)
    url = cfg.healthcheck.url
    timeout = cfg.healthcheck.timeout
    interval = cfg.healthcheck.interval
    max_tries = cfg.healthcheck.max_tries
    for attempt in range(max_tries):
        logging.log(TRACE_LEVEL, 'healthcheck polling %s... %s/%s', url, attempt + 1, max_tries)
        time.sleep(interval)
        try:
            if requests.get(url, timeout=timeout).status_code == 200:
                logging.info('healthcheck completed')
                return
        except requests.RequestException:
            pass

    raise RuntimeError("Health check timed out")


@main(config_path="config", config_name="config", version_base="1.2")
def main(cfg: DictConfig) -> None:
    for container in cfg.server.container:
        # check health
        try:
            wait_for_healthcheck(cfg, container.name)
        except RuntimeError as e:
            logging.error(f'start server failed: {e}')


if __name__ == "__main__":
    configure_logging(consume_verbosity_flags())
    main()
