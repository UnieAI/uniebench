from omegaconf import DictConfig
import logging
from hydra import main

from benchmark.genai_perf import genai_perf
from benchmark.inferencemax_h100 import inferencemax_h100

def run_benchmark(cfg: DictConfig, benchmark_name, container, token_lengths, concurrency, seed):
    if benchmark_name == 'genai-perf':
        genai_perf(cfg, container, token_lengths, concurrency)
    elif benchmark_name == 'inferencemax-h100':
        inferencemax_h100(cfg, container, token_lengths, concurrency, seed)

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
                    run_benchmark(cfg, name, container, token_lengths, concurrency, seed)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()