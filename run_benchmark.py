from omegaconf import DictConfig
import logging
import random
from hydra import main

from benchmark.inferencemax import inferencemax
from benchmark.vllm_bench import vllm_bench
from log_utils import consume_verbosity_flags, configure_logging

benchmark_map = {
    'inferencemax': inferencemax,
    'vllm-bench': vllm_bench,
}

def run_benchmark(cfg: DictConfig, args: dict):
    benchmark_name, container, token_lengths, concurrency, seed, request_rate = args.values()
    logging.debug(
        "benchmark dispatch: name=%s container=%s input_len=%s output_len=%s concurrency=%s seed=%s",
        benchmark_name,
        getattr(container, "name", "unknown"),
        token_lengths.input_len,
        token_lengths.output_len,
        concurrency,
        seed,
        request_rate
    )
    try:
        benchmark = benchmark_map[benchmark_name]
        benchmark(cfg, container, token_lengths, concurrency, seed, request_rate)
    except KeyError:
        logging.error("benchmark failed: unsupported benchmark '%s'", benchmark_name)
        raise ValueError(f"unsupported benchmark: {benchmark_name}")

@main(config_path="config", config_name="config", version_base="1.2")
def main(cfg: DictConfig) -> None:
    # run benchmark (inner loop)
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
    for container in cfg.server.container:
        if container.port:
            cfg.server.port = container.port
        for token_lengths in cfg.benchmark.token_lengths:
            for concurrency in cfg.benchmark.concurrency:
                for name in cfg.benchmark.name:
                    seed = random.randint(0, 2147483647)
                    run_benchmark(cfg, {name, container, token_lengths, concurrency, seed})


if __name__ == "__main__":
    configure_logging(consume_verbosity_flags())
    main()
