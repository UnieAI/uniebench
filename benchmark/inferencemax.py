from omegaconf import DictConfig
import logging
import subprocess
import sys
import os
import json
import shutil
import random
import requests
from datetime import datetime as dt

from log_utils import TRACE_LEVEL
from benchmark.runtime_metadata import collect_runtime_metadata

def inferencemax(cfg: DictConfig, container, token_lengths, concurrency, seed, num_prompts):
    logging.info('run benchmark inferencemax...')
    benchmark(cfg, token_lengths, concurrency, seed)
    logging.info('standardize benchmark result...')
    benchmark_post_processing(cfg, container, concurrency, seed)
    logging.info('benchcmark completed')

def benchmark(cfg: DictConfig, token_lengths, concurrency, seed):
    RESULT_ROOT = f'./results/{cfg.autotest.name}/inferencemax'
    os.makedirs(RESULT_ROOT, exist_ok=True)

    if cfg.benchmark.endpoint_type == 'chat':
        backend = 'openai-chat'
        endpoint = '/v1/chat/completions'
    else:
        backend = 'openai'
        endpoint = '/v1/completions'

    cmd = [
        'python3', 'benchmark/inferencemax/bench_serving/benchmark_serving.py',
        '--backend', backend,
        '--endpoint', endpoint,
        '--model', cfg.server.model_id,
        '--base-url', f'{cfg.server.base_url}:{cfg.server.port}',
        '--tokenizer', f'{cfg.server.model_path}/{cfg.server.model_name}',
        '--num-prompts', f'{concurrency * 4}',
        '--seed', f'{seed}',
        '--max-concurrency', str(concurrency),
        '--request-rate', 'inf',
        '--ignore-eos',
        '--save-result', 
        '--percentile-metrics', 'ttft,tpot,itl,e2el',
        '--result-dir', RESULT_ROOT,
        '--result-filename', 'full_result.json'
    ]

    if 'dataset_path' in cfg.benchmark and cfg.benchmark.dataset_path != 'none':
        cmd.extend([
            '--dataset-name', 'sharegpt',
            '--dataset-path', cfg.benchmark.dataset_path,
            '--sharegpt-output-len', str(token_lengths.output_len),
        ])
    else:
        cmd.extend([
            '--dataset-name', 'random',
            '--random-input-len', str(token_lengths.input_len),
            '--random-output-len', str(token_lengths.output_len),
            '--random-range-ratio', '1',
        ])


    logging.debug("run inferencemax command")
    logging.log(TRACE_LEVEL, "command: %s", cmd)
    try:
        subprocess.run(
            cmd,
            capture_output=False,
            stdout=sys.stdout,
            stderr=sys.stderr,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        logging.error("benchmark command failed (inferencemax), returncode=%s", exc.returncode)
        raise

def benchmark_post_processing(cfg: DictConfig, container, concurrency, seed = None):
    RESULT_ROOT = f'./results/{cfg.autotest.name}/inferencemax'
    os.makedirs(RESULT_ROOT, exist_ok=True)

    benchmark_date = dt.now().strftime('%Y%m%d-%H%M%S')
    dist_folder = f'{RESULT_ROOT}/{benchmark_date}'
    os.makedirs(dist_folder, exist_ok=True)
    
    # result.json
    source = f'{RESULT_ROOT}/full_result.json'
    with open(source, 'r') as fr:
        data = json.load(fr)
    
    NaN = float('nan')
    
    result = {
        "platform": cfg.server.platform,
        "engine": container.name,
        "tp_size": container.tp_size,
        "benchmark": 'inferencemax',
        "remark": cfg.server.remark if 'remark' in cfg.server else '',
        "seed": seed if seed is not None else "random",

        "request_count": data['completed'],
        "interval": data['duration'] * 1000, # second to ms
        "concurrency": data['max_concurrency'],
        "model_name": data['tokenizer_id'],
        "input_tokens": data['total_input_tokens'] / data['completed'],
        "output_tokens": data['total_output_tokens'] / data['completed'],

        "request_throughput": data['request_throughput'],
        "output_token_throughput": data['output_throughput'],
        "total_token_throughput": data.get('total_token_throughput', NaN),

        "request_latency.avg": data['mean_e2el_ms'],
        "request_latency.median": data['median_e2el_ms'],
        "request_latency.std": data['std_e2el_ms'],
        "request_latency.p99": data['p99_e2el_ms'],

        "time_to_first_token.avg": data['mean_ttft_ms'],
        "time_to_first_token.median": data['median_ttft_ms'],
        "time_to_first_token.std": data['std_ttft_ms'],
        "time_to_first_token.p99": data['p99_ttft_ms'],

        "inter_token_latency.avg": data['mean_itl_ms'],
        "inter_token_latency.median": data['median_itl_ms'],
        "inter_token_latency.std": data['std_itl_ms'],
        "inter_token_latency.p99": data['p99_itl_ms'],
    }
    result.update(collect_runtime_metadata(cfg))
    
    dist = os.path.join(dist_folder, 'result.json')
    with open(dist, 'w') as fw:
        json.dump(result, fw, indent=4)

    shutil.copy(source, dist_folder)
