from omegaconf import DictConfig
import logging
from hydra import main

from benchmark.genai_perf import genai_perf
from benchmark.inferencemax_h100 import inferencemax_h100

def run_benchmark(cfg: DictConfig, benchmark_name, container, token_lengths, concurrency):
    if benchmark_name == 'genai-perf':
        genai_perf(cfg, container, token_lengths, concurrency)
    elif benchmark_name == 'inferencemax-h100':
        inferencemax_h100(cfg, container, token_lengths, concurrency)

@main(config_path="config", config_name="config", version_base="1.2")
def main(cfg: DictConfig) -> None:
    # run benchmark (inner loop)
    for container in cfg.server.container:
        for token_lengths in cfg.benchmark.token_lengths:
            for concurrency in cfg.benchmark.concurrency:
                run_benchmark(cfg, container, token_lengths, concurrency)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()