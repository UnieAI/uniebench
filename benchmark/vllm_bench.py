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

def vllm_bench(cfg: DictConfig, container, token_lengths, concurrency, seed, request_rate):
    logging.info(f'run benchmark {vllm_bench.__name__}...')
    benchmark(cfg, token_lengths, concurrency, seed, request_rate)
    logging.info('standardize benchmark result...')
    benchmark_post_processing(cfg, container, concurrency, seed)
    logging.info('benchcmark completed')

def benchmark(cfg: DictConfig, token_lengths, concurrency, seed, request_rate):
    RESULT_ROOT = f'./results/{cfg.autotest.name}/vllm_bench'
    os.makedirs(RESULT_ROOT, exist_ok=True)

    if cfg.benchmark.endpoint_type == 'audio':
        backend = 'openai-audio'
        endpoint = '/v1/audio/transcriptions'
        # Extract last two segments from dataset_path separated by '/'
        dataset_parts = cfg.benchmark.dataset_path.rstrip('/').split('/')
        hf_name = '/'.join(dataset_parts[-2:])
        
        cmd = [
            'vllm', 'bench', 'serve',
            '--base-url', f'{cfg.server.base_url}:{cfg.server.port}',
            '--endpoint', endpoint,
            '--backend', backend,
            '--served-model-name', cfg.server.model_id,
            '--dataset-name', 'hf',
            '--dataset-path', cfg.benchmark.dataset_path,
            '--hf-name', hf_name,
            '--hf-subset', cfg.benchmark.subset,
            '--hf-split', cfg.benchmark.split,
            '--asr-max-audio-len-sec', '60',
            '--num-prompts', f'{request_rate * 120}', # keep sending requests in 2 minutes 
            '--request-rate', f'{request_rate}', # like max-concurrency in text-to-text benchmark
            '--save-result', 
            '--percentile-metrics', 'ttft,tpot,itl,e2el',
            '--result-dir', RESULT_ROOT,
            '--result-filename', 'full_result.json',
            '--seed', f'{seed}',
        ]
    elif cfg.benchmark.endpoint_type == 'text':
        backend = 'openai'
        endpoint = '/v1/completions'

        cmd = [
            'vllm', 'bench', 'serve',
            '--base-url', f'{cfg.server.base_url}:{cfg.server.port}',
            '--endpoint', endpoint,
            '--backend', backend,
            '--served-model-name', cfg.server.model_id,
            '--num-prompts', f'{concurrency * 4}',
            '--max-concurrency', f'{concurrency}',
            '--request-rate', 'inf',
            '--ignore-eos',
            '--save-result',
            '--percentile-metrics', 'ttft,tpot,itl,e2el',
            '--result-dir', RESULT_ROOT,
            '--result-filename', 'full_result.json',
            '--seed', f'{seed}',
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
    else:
        raise ValueError(f"endpoint_type '{cfg.benchmark.endpoint_type}' not supported")

    logging.debug("run vllm_bench command")
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
        logging.error("benchmark command failed (vllm_bench), returncode=%s", exc.returncode)
        raise

def benchmark_post_processing(cfg: DictConfig, container, concurrency, seed = None):
    RESULT_ROOT = f'./results/{cfg.autotest.name}/vllm_bench'
    os.makedirs(RESULT_ROOT, exist_ok=True)

    benchmark_date = dt.now().strftime('%Y%m%d-%H%M%S')
    dist_folder = f'{RESULT_ROOT}/{benchmark_date}'
    os.makedirs(dist_folder, exist_ok=True)
    
    # result.json
    source = f'{RESULT_ROOT}/full_result.json'
    with open(source, 'r') as fr:
        data = json.load(fr)
    
    result = {
        "platform": cfg.server.platform,
        "engine": container.name,
        "tp_size": container.tp_size,
        "benchmark": 'inferencemax',
        "remark": cfg.server.remark if 'remark' in cfg.server else '',
        "seed": seed if seed is not None else "random",

        "request_count": data['completed'],
        "interval": data['duration'] * 1000, # second to ms
    }
    if cfg.benchmark.endpoint_type == 'text':
        result["concurrency"] = data['max_concurrency']
    else:
        result["request_rate"] = data['request_rate']
    result.update({
        "model_name": data['tokenizer_id'],
        "input_tokens": data['total_input_tokens'] / data['completed'],
        "output_tokens": data['total_output_tokens'] / data['completed'],

        "request_throughput": data['request_throughput'],
        "output_token_throughput": data['output_throughput'],

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
    })
    result.update(collect_runtime_metadata(cfg))
    
    dist = os.path.join(dist_folder, 'result.json')
    with open(dist, 'w') as fw:
        json.dump(result, fw, indent=4)

    shutil.copy(source, dist_folder)
