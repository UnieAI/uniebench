from omegaconf import DictConfig, OmegaConf
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

    base_url = f'{cfg.server.base_url}'
    if cfg.server.port != 0:
        base_url += f':{cfg.server.port}'
    if cfg.benchmark.endpoint_type == 'audio':
        backend = 'openai-audio'
        endpoint = '/v1/audio/transcriptions'
        # Extract last two segments from dataset_path separated by '/'
        dataset_parts = cfg.benchmark.dataset_path.rstrip('/').split('/')
        hf_name = '/'.join(dataset_parts[-2:])
        
        cmd = [
            'vllm', 'bench', 'serve',
            '--base-url', base_url,
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
    elif cfg.benchmark.endpoint_type == 'embedding':
        backend = 'openai-embeddings'
        endpoint = '/v1/embeddings'
        cmd = [
            'vllm', 'bench', 'serve',
            '--base-url', base_url,
            '--endpoint', endpoint,
            '--served-model-name', cfg.server.model_id,
            '--backend', backend,
            '--dataset-name', 'sharegpt',
            '--dataset-path', cfg.benchmark.dataset_path,
            '--num-prompts', f'{concurrency * 4}',
            '--max-concurrency', f'{concurrency}',
            '--request-rate', 'inf',
            '--skip-chat-template',
            '--save-result',
            '--percentile-metrics', 'e2el',
            '--result-dir', RESULT_ROOT,
            '--result-filename', 'full_result.json',
            '--seed', f'{seed}',
        ]
    elif cfg.benchmark.endpoint_type == 'image-text':
        backend = 'openai-chat'
        endpoint = '/v1/chat/completions'
        cmd = [
            'vllm', 'bench', 'serve',
            '--base-url', base_url,
            '--endpoint', endpoint,
            '--served-model-name', cfg.server.model_id,
            '--backend', backend,
            '--dataset-name', 'hf',
            '--dataset-path', cfg.benchmark.dataset_path,
            '--hf-split', cfg.benchmark.split,
            '--num-prompts', f'{concurrency * 4}',
            '--max-concurrency', f'{concurrency}',
            '--request-rate', 'inf',
            '--save-result',
            '--percentile-metrics', 'ttft,tpot,itl,e2el',
            '--result-dir', RESULT_ROOT,
            '--result-filename', 'full_result.json',
            '--ignore-eos',
            '--seed', f'{seed}',
            '--hf-output-len', str(token_lengths.output_len)
        ]
    elif cfg.benchmark.endpoint_type == 'text':
        backend = 'openai'
        endpoint = '/v1/completions'

        cmd = [
            'vllm', 'bench', 'serve',
            '--base-url', base_url,
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

    local_env = os.environ.copy()
    if 'openai_api_key' in cfg.autotest:
        local_env['OPENAI_API_KEY'] = cfg.autotest.openai_api_key
    
    logging.debug("run vllm_bench command")
    logging.log(TRACE_LEVEL, "command: %s", cmd)
    try:
        subprocess.run(
            cmd,
            env=local_env,
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
    NaN = float('nan')
    NA = 'N/A'
    os.makedirs(RESULT_ROOT, exist_ok=True)

    benchmark_date = dt.now().strftime('%Y%m%d-%H%M%S')
    dist_folder = f'{RESULT_ROOT}/{benchmark_date}'
    os.makedirs(dist_folder, exist_ok=True)
    
    # result.json
    source = f'{RESULT_ROOT}/full_result.json'
    with open(source, 'r') as fr:
        data = json.load(fr)
    try:
        result = {
            "platform": cfg.server.platform,
            "engine": container.name,
            "tp_size": container.tp_size,
            "benchmark": 'vllm-bench',
            "remark": OmegaConf.select(cfg, "server.remark", default=NA),
            "seed": seed if seed is not None else "random",
            "request_count": data.get('completed', NaN),
            "interval": data.get('duration', NaN) * 1000, # second to ms
            "concurrency": data.get('max_concurrency', NaN),
            "request_rate": data.get('request_rate', NaN),
            "model_name": data.get('tokenizer_id', NA),
            "input_tokens": data.get('total_input_tokens', NaN) / data.get('completed', NaN),
            "output_tokens": data.get('total_output_tokens', NaN) / data.get('completed', NaN),
            "request_throughput": data.get('request_throughput', NaN),
            "output_token_throughput": data.get('output_throughput', NaN),

            "request_latency.avg": data.get('mean_e2el_ms', NaN),
            "request_latency.median": data.get('median_e2el_ms', NaN),
            "request_latency.std": data.get('std_e2el_ms', NaN),
            "request_latency.p99": data.get('p99_e2el_ms', NaN),

            "time_to_first_token.avg": data.get('mean_ttft_ms', NaN),
            "time_to_first_token.median": data.get('median_ttft_ms', NaN),
            "time_to_first_token.std": data.get('std_ttft_ms', NaN),
            "time_to_first_token.p99": data.get('p99_ttft_ms', NaN),

            "inter_token_latency.avg": data.get('mean_itl_ms', NaN),
            "inter_token_latency.median": data.get('median_itl_ms', NaN),
            "inter_token_latency.std": data.get('std_itl_ms', NaN),
            "inter_token_latency.p99": data.get('p99_itl_ms', NaN),
        }

    except Exception as e:
        print('failed', e)
        exit()
    result.update(collect_runtime_metadata(cfg))
    
    dist = os.path.join(dist_folder, 'result.json')
    with open(dist, 'w') as fw:
        json.dump(result, fw, indent=4)

    shutil.copy(source, dist_folder)
