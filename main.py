from hydra import main
from omegaconf import DictConfig, ListConfig, OmegaConf
import logging
from datetime import datetime
import os
import random
from concurrent.futures import ThreadPoolExecutor, as_completed

from pyarrow import LoggingMemoryPool

from log_utils import consume_verbosity_flags, configure_logging, TRACE_LEVEL, TRACE2_LEVEL
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
    concurrency_or_request_rate_length = len(cfg.benchmark.concurrency) if 'concurrency' in cfg.benchmark else len(cfg.benchmark.request_rate)
    total_rounds = (
        len(cfg.server.container)
        * len(cfg.benchmark.name)
        * len(cfg.benchmark.token_lengths)
        * concurrency_or_request_rate_length
    )
    round_index = 0

    # start server (outer loop)
    for container in cfg.server.container:
        # run benchmark (inner loop)
        for benchmark_name in cfg.benchmark.name:
            for token_lengths in cfg.benchmark.token_lengths:
                for c_index in range(concurrency_or_request_rate_length):
                    round_index += 1
                    if 'port' in container:
                        cfg.server.port = container.port
                    if 'base_url' in container:
                        cfg.server.base_url = container.base_url
                    if 'model_name' in container:
                        cfg.server.model_name = container.model_name
                    if 'model_path' in container:
                        cfg.server.model_path = container.model_path
                    if 'model_id' in container:
                        cfg.server.model_id = container.model_id
                    if 'endpoint_type' in container:
                        cfg.benchmark.endpoint_type = container.endpoint_type

                    if container.name == "none":
                        if cfg.server.name:
                            container.name = cfg.server.name
                        else:
                            container.name = f'server_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
                    concurrency = cfg.benchmark.concurrency[c_index] if 'concurrency' in cfg.benchmark else None
                    request_rate = cfg.benchmark.request_rate[c_index] if 'request_rate' in cfg.benchmark else None

                    logging.info(
                        "round %s/%s | benchmark=%s | container=%s | token_lengths=%s | concurrency=%s",
                        round_index,
                        total_rounds,
                        benchmark_name,
                        container.name,
                        token_lengths,
                        concurrency,
                    )
                    logging.log(TRACE_LEVEL, "round container config: %s", container)
                    logging.log(
                        TRACE2_LEVEL,
                        "current server cfg: base_url=%s port=%s model=%s",
                        cfg.server.base_url,
                        cfg.server.port,
                        cfg.server.model_id,
                    )

                    if container.path == "none":
                        logging.info("start service: skipped (assume existing service is already running)")
                    else:
                        logging.info("start service: %s", container.name)
                        service_name = None
                        if 'service_name' in container:
                            service_name = container.service_name
                        try:
                            started_pid = run_container(cfg, container.path, service_name, container_name=container.name)
                        except BaseException as e:
                            logging.error("server startup failed. container=%s path=%s", container.name, container.path)
                            logging.error(e)
                            continue

                    # check health
                    try:
                        if container.path == "none":
                            logging.debug('healthcheck skipped because service startup was skipped')
                        else:
                            wait_for_healthcheck(cfg, container.name)
                    except RuntimeError as e:
                        logging.error("server startup failed during healthcheck. container=%s url=%s", container.name, cfg.healthcheck.url)
                        logging.error(e)
                        if container.path != "none":
                            logging.info("stop service due to startup failure: %s", container.name)
                            try:
                                stop_container(cfg, container.name, container.path, started_pid)
                            except BaseException as stop_exc:
                                logging.error("server shutdown failed while handling startup failure. container=%s", container.name)
                                logging.error(stop_exc)
                                raise
                        continue

                    seed = 0
                    try:
                        logging.info("benchmark running: %s", benchmark_name)
                        run_benchmark(cfg, {
                            'benchmark_name': benchmark_name, 
                            'container': container, 
                            'token_lengths': token_lengths, 
                            'concurrency': concurrency, 
                            'seed': seed,
                            'request_rate': request_rate,
                        })
                        logging.info("benchmark completed: %s", benchmark_name)
                    except BaseException as e:
                        logging.error(f'benchmark failed.  name: {benchmark_name}, token_lengths: {token_lengths}, concurrency: {concurrency}')
                        logging.error(e)

                    # stop server
                    if container.path != "none":
                        logging.info("stop service: %s", container.name)
                        try:
                            stop_container(cfg, container.name, container.path, started_pid)
                        except BaseException as e:
                            logging.error("server shutdown failed. container=%s", container.name)
                            logging.error(e)
                            raise

                    if round_index < total_rounds:
                        logging.info("enter next round: %s/%s", round_index + 1, total_rounds)
                    else:
                        logging.info("all rounds completed for %s", cfg.autotest.name)

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
    configure_logging(consume_verbosity_flags())
    main()
