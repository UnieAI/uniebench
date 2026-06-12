import logging
import subprocess
import sys
import os
from log_utils import TRACE_LEVEL

def warmup(base_url, port, model_id, warmup_dataset_path, warmup_requests = 50, output_length = 256, openai_api_key = None):
    if port != 0:
        base_url += f':{port}'
    
    backend = 'openai'
    endpoint = '/v1/completions'
    cmd = [
        'vllm', 'bench', 'serve',
        '--base-url', base_url,
        '--endpoint', endpoint,
        '--backend', backend,
        '--served-model-name', model_id,
        '--num-prompts', f'{warmup_requests}',
        '--request-rate', '0.5',
        '--ignore-eos',
        '--percentile-metrics', 'ttft,tpot,itl,e2el',
        '--seed', '0',
        '--dataset-name', 'hf',
        '--dataset-path', warmup_dataset_path,
        '--hf-output-len', str(output_length),
    ]

    local_env = os.environ.copy()
    if openai_api_key:
        local_env['OPENAI_API_KEY'] = openai_api_key
    
    logging.info("warmup")
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
        logging.error("warmup command failed (vllm_bench), returncode=%s", exc.returncode)
        raise

    logging.info("warmup completed")
