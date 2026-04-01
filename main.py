from hydra import main
from omegaconf import DictConfig, ListConfig, OmegaConf
import logging
from datetime import datetime
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from pyarrow import LoggingMemoryPool

from run_container import run_container
from wait_for_healthcheck import wait_for_healthcheck
from run_benchmark import run_benchmark
from stop_container import stop_container
from export import export


def run_single_server(cfg: DictConfig) -> None:
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
        if 'port' in container:
            cfg.server.port = container.port
        if 'model_name' in container:
            cfg.server.model_name = container.model_name
        if 'model_id' in container:
            cfg.server.model_id = container.model_id
        if 'endpoint_type' in container:
            cfg.benchmark.endpoint_type = container.endpoint_type

        if container.name == "none":
            if cfg.server.name:
                container.name = cfg.server.name
            else:
                container.name = f'server_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        if container.path == "none":
            logging.info('assume server is running')
        else:
            service_name = None
            if 'service_name' in container:
                service_name = container.service_name
                run_container(cfg, container.path, service_name)

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

        import random
        # run benchmark (inner loop)
        for benchmark_name in cfg.benchmark.name:
            for token_lengths in cfg.benchmark.token_lengths:
                for c_index in range(len(cfg.benchmark.concurrency)):
                    concurrency = cfg.benchmark.concurrency[c_index]
                    seed = random.randint(0, 2147483647)
                    if 'seeds' in cfg.benchmark and len(cfg.benchmark.seeds) > 0:
                        seed = cfg.benchmark.seeds[c_index % len(cfg.benchmark.seeds)]
                    try:
                        run_benchmark(cfg, benchmark_name, container, token_lengths, concurrency, seed)
                    except BaseException as e:
                        logging.error(f'benchmark failed.  name: {benchmark_name}, token_lengths: {token_lengths.input_len}/{token_lengths.output_len}, concurrency: {concurrency}')
                        logging.error(e)

        # stop server
        stop_container(cfg, container.name)

    # export to google-sheet
    export(cfg.autotest.name, cfg.autotest.sheet_name)
    logging.info('export completed')
    logging.info(f'or you can see the full result under ./results/{cfg.autotest.name}')


@main(config_path="config", config_name="config", version_base="1.2")
def main(cfg: DictConfig) -> None:
    server_ids = cfg.server.id
    if isinstance(server_ids, ListConfig):
        server_ids = list(server_ids)

    if isinstance(server_ids, list):
        valid_server_ids = [server_id for server_id in server_ids if server_id]
        if len(valid_server_ids) == 0:
            logging.warning('cfg.server.id is an empty list; nothing to run')
            return

        base_autotest_name = cfg.autotest.name if ('autotest' in cfg and 'name' in cfg.autotest) else f'autotest_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        with ThreadPoolExecutor(max_workers=len(valid_server_ids)) as executor:
            futures = {}
            for server_id in valid_server_ids:
                thread_cfg = OmegaConf.create(OmegaConf.to_container(cfg, resolve=False))
                thread_cfg.server.id = server_id
                # Avoid result overwrite between threads.
                thread_cfg.autotest.name = f'{base_autotest_name}_{server_id}'
                futures[executor.submit(run_single_server, thread_cfg)] = server_id

            for future in as_completed(futures):
                server_id = futures[future]
                try:
                    future.result()
                except BaseException as e:
                    logging.error(f'run failed for server id "{server_id}"')
                    logging.error(e)
        return

    run_single_server(cfg)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
