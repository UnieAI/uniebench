from hydra import main
from omegaconf import DictConfig
import logging
from datetime import datetime
import os

from pyarrow import LoggingMemoryPool

from run_container import run_container
from wait_for_healthcheck import wait_for_healthcheck
from run_benchmark import run_benchmark
from stop_container import stop_container
from export import export


@main(config_path="config", config_name="config", version_base="1.2")
def main(cfg: DictConfig) -> None:
    # if autotest.name is not set, set to random name
    if cfg.server.id:
        for server_config in cfg.default_config.server:
            if server_config.id == cfg.server.id:
                cfg.server = {
                    **cfg.server,
                    **server_config.config
                }
    if cfg.benchmark.id:
        for benchmark_config in cfg.default_config.benchmark:
            if benchmark_config.id == cfg.benchmark.id:
                cfg.benchmark = {
                    **cfg.benchmark,
                    **benchmark_config.config
                }

    if not ('autotest' in cfg and 'name' in cfg.autotest):
        cfg.autotest.name = f'autotest_{datetime.now().strftime("%Y%m%d_%H%M%S")}'

    os.makedirs(f'./results/{cfg.autotest.name}', exist_ok=True)

    # start server (outer loop)
    for container in cfg.server.container:
        if container.port:
            cfg.server.port = container.port
        if container.name == "none":
            container.name = f'server_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        if container.path == "none":
            logging.info('assume server is running')
        else:
            run_container(cfg, container.path)

        # check health
        try:
            if container.path == "none":
                logging.info('assume server is running')
            else:
                wait_for_healthcheck(cfg, container.name)
        except RuntimeError as e:
            logging.error(f'start server failed: {e}')
            stop_container(cfg, container.name)
            continue

        # run benchmark (inner loop)
        for benchmark_name in cfg.benchmark.name:
            for token_lengths in cfg.benchmark.token_lengths:
                for concurrency in cfg.benchmark.concurrency:
                    try:
                        run_benchmark(cfg, benchmark_name, container, token_lengths, concurrency)
                    except BaseException as e:
                        logging.error(f'benchmark failed.  name: {benchmark_name}, token_lengths: {token_lengths.input_len}/{token_lengths.output_len}, concurrency: {concurrency}')
                        logging.error(e)

        # stop server
        stop_container(cfg, container.name)

    # export to google-sheet
    export(cfg.autotest.name)
    logging.info('export completed')
    logging.info(f'or you can see the full result under ./results/{cfg.autotest.name}')

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
