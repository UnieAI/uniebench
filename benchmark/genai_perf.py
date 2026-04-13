from omegaconf import DictConfig
import logging
import subprocess
import sys
import os
import json
from datetime import datetime as dt
import shutil

from log_utils import TRACE_LEVEL


def genai_perf(cfg: DictConfig, container, token_lengths, concurrency):
    logging.info('run benchmark genai-perf...')
    benchmark(cfg, token_lengths, concurrency)
    logging.info('standardize benchmark result...')
    benchmark_post_processing(cfg, container, concurrency)
    logging.info('benchcmark completed')

def benchmark(cfg: DictConfig, token_lengths, concurrency):
    RESULT_ROOT = f'./results/{cfg.autotest.name}/genai_perf'
    os.makedirs(RESULT_ROOT, exist_ok=True)

    cmd = [
        'genai-perf', 'profile',
        '--endpoint-type', cfg.benchmark.endpoint_type,
        '--streaming',
        '--url', f'{cfg.server.base_url}:{cfg.server.port}',
        '-m', cfg.server.model_id,
        '--tokenizer', f'{cfg.server.model_path}/{cfg.server.model_name}',
        '--extra-inputs', 'ignore_eos:true',
        '--synthetic-input-tokens-mean', str(token_lengths.input_len),
        '--output-tokens-mean', str(token_lengths.output_len),
        # '--measurement-interval', str(cfg.benchmark.interval),
        '--request-count', str(concurrency * 10),
        '--concurrency', str(concurrency),
        '--artifact-dir', RESULT_ROOT
    ]

    logging.debug("run genai-perf command")
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
        logging.error("benchmark command failed (genai-perf), returncode=%s", exc.returncode)
        raise


def benchmark_post_processing(cfg: DictConfig, container, concurrency):
    RESULT_ROOT = f'./results/{cfg.autotest.name}/genai_perf'
    os.makedirs(RESULT_ROOT, exist_ok=True)

    benchmark_date = dt.now().strftime('%Y%m%d-%H%M%S')
    dist_folder = f'{RESULT_ROOT}/{benchmark_date}'
    os.makedirs(dist_folder, exist_ok=True)
    
    # result.json
    source_folder = f'{RESULT_ROOT}/{cfg.server.model_id}-openai-{cfg.benchmark.endpoint_type}-concurrency{concurrency}'
    source = f'{source_folder}/profile_export_genai_perf.json'
    with open(source, 'r') as fr:
        data = json.load(fr)
    
    result = {
        "platform": cfg.server.platform,
        "engine": container.name,
        "tp_size": container.tp_size,
        "benchmark": 'genai-perf',

        "request_count": data['request_count']['avg'],
        "interval": data['request_count']['avg'] / data['request_throughput']['avg'] * 1000,  # ms
        "concurrency": data['input_config']['perf_analyzer']['stimulus']['concurrency'],
        "model_name": data['input_config']['tokenizer']['name'],
        "input_tokens": data['input_sequence_length']['avg'],
        "output_tokens": data['output_sequence_length']['avg'],

        "request_throughput": data['request_throughput']['avg'],
        "output_token_throughput": data['output_token_throughput']['avg'],

        "request_latency.avg": data['request_latency']['avg'],
        "request_latency.median": data['request_latency']['p50'],
        "request_latency.std": data['request_latency']['std'],
        "request_latency.p99": data['request_latency']['p99'],

        "time_to_first_token.avg": data['time_to_first_token']['avg'],
        "time_to_first_token.median": data['time_to_first_token']['p50'],
        "time_to_first_token.std": data['time_to_first_token']['std'],
        "time_to_first_token.p99": data['time_to_first_token']['p99'],

        "inter_token_latency.avg": data['inter_token_latency']['avg'],
        "inter_token_latency.median": data['inter_token_latency']['p50'],
        "inter_token_latency.std": data['inter_token_latency']['std'],
        "inter_token_latency.p99": data['inter_token_latency']['p99'],

    }
    
    dist = os.path.join(dist_folder, 'result.json')
    with open(dist, 'w') as fw:
        json.dump(result, fw, indent=4)

    shutil.copy(source, dist_folder)

    if os.path.exists(source_folder):
        try:
            shutil.rmtree(source_folder)
        except OSError as e:
            logging.warning(f'remove folder failed {source_folder}')
            logging.warning(e)
    else:
        pass
