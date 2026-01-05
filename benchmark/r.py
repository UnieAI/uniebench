#
# Copyright (c) 2025 UnieAI. All rights reserved.
#
# This script is designed to benchmark the performance of an OpenAI-compatible API endpoint.
# It measures various performance metrics under concurrent loads.
#
# Key Functionalities:
#   - Concurrently sends multiple requests to an API endpoint.
#   - Utilizes the 'openai' library for asynchronous API communication.
#   - Fetches conversation data from the 'unieai/shareGPT' dataset using the 'datasets' library.
#   - Prepares and tokenizes the data using a tokenizer from the 'transformers' library.
#   - Calculates and displays key performance indicators, including:
#     - Time to First Token (TTFT): The latency before receiving the first token of the response.
#     - Time Between Tokens (TBT): The average time between consecutive tokens in a streamed response.
#     - Requests Per Second (RPS): The number of requests the server can handle per second.
#     - Requests Per Minute (RPM): The number of requests the server can handle per minute.
#     - Throughput: The rate at which tokens are processed (prompt and decode).
#     - Latency Percentiles (P50, P99): The 50th and 99th percentile of the time to first token.
#
# Usage:
#   The script is executed via the command line and accepts several arguments:
#   --model-name:       The name of the model to be tested (e.g., "test").
#   --max-new-tokens:   The maximum number of tokens to generate in each response.
#   --concurrency:      The number of concurrent threads to use for the test.
#   --debug:            Set to 1 to enable debug mode, which prints detailed request/response info.
#   --tokenizer:        The Hugging Face tokenizer model to use for token counting (e.g., "meta-llama/Meta-Llama-3-8B-Instruct").
#
# The script initializes by setting up the API client with credentials from environment
# variables (UNIEAI_API_KEY, UNIEAI_API_URL). It then loads and processes a dataset,
# distributing the conversational data among the concurrent threads. Each thread
# sends requests for a duration of 120 seconds. Finally, it aggregates the results
# from all threads and prints a formatted summary of the performance metrics.
#

# Requirements:
# pip install openai transformers datasets
#
import os
import sys
import argparse
import openai
import time
import asyncio
import aiohttp
from datasets import load_dataset
from collections import defaultdict
from math import floor
import numpy
from transformers import AutoTokenizer
import random
import string
import json
import shutil


api_key = os.getenv("UNIEAI_API_KEY", "sk-kQKMTKyEQA7X6eZ_K3oV1NyiQdjeppL9XZbNz5r3xBJnOju9j49dchfpTFk")
api_url = None
fetch_timeout = aiohttp.ClientTimeout(total=86400)
openai_client = None
mymodel = "test"
tokenizer = None

async def get_baseline_ttft(model, client):
    """Measures the TTFT for a minimal request to estimate overhead."""
    minimal_prompt = [{"role": "user", "content": "Hi"}]
    try:
        # Send a minimal request
        ret = await fetch_remote1(model, minimal_prompt, 1)
        return ret["ftts"] # Return the Time To First Token
    except Exception as e:
        print(f"Could not get baseline TTFT: {e}")
        return 0.1 # Return a default small value if it fails

def count_tokens(messages):
    """Counts the total number of tokens in a list of messages."""
    global tokenizer
    total_tokens = 0
    for message in messages:
        role_tokens = len(tokenizer.encode(message["role"], add_special_tokens=False))
        content_tokens = len(tokenizer.encode(message["content"], add_special_tokens=False))
        total_tokens += role_tokens + content_tokens
    return total_tokens

async def fetch_remote_ftts(model, prompt, max_new_tokens, openai_client):
    """
    Sends a request to the API and measures performance metrics for a streamed response.

    This function sends a chat completion request and processes the streamed response
    to calculate the time to first token (TTFT) and the average time between tokens (TBT).
    """
    start_time = time.time()

    # response = await openai_client.completions.create(
    response = await openai_client.chat.completions.create(
    model=model,
    # prompt=prompt,
    messages=prompt,
    max_tokens=max_new_tokens,
    n=1,
    stop=None,
    temperature=0.0,
    stream=True,
    extra_body={
        "ignore_eos": True, # Force vLLM to ignore EOS tokens and generate up to max_tokens
        "min_tokens": max_new_tokens, # Optional: uncomment if you want to force *at least* 1000 tokens
    },
    )
    chunks = []
    first_token_time = None
    previous_time = start_time
    time_intervals = []
    async for chunk in response:
        if first_token_time is None:
            first_token_time = time.time()
            current_time = first_token_time
        else:
            current_time = time.time()
        tbt = current_time - previous_time
        if previous_time != start_time:
            time_intervals.append(tbt)
        previous_time = current_time

        try:
            content = chunk.choices[0].delta.content
            if content:
                chunks.append(content)
        except:
            # print(f"Exception:\n{chunk}\n")
            continue

    end_time = time.time()
    chunks = "".join(chunks)
    if time_intervals:
        avg_tbt = sum(time_intervals) / len(time_intervals)
    else:
        avg_tbt = 0.0
    ftts = first_token_time - start_time
    ret = {
        "text": chunks,
        "ftts": ftts,
        "tbt": avg_tbt,
        "p_time": ftts,
        "d_time": end_time-first_token_time,
        "r_time": end_time-start_time,
    }
    return ret

async def fetch_remote1(model, prompt, max_new_tokens):
    """A wrapper function for fetch_remote_ftts."""
    ret = await fetch_remote_ftts(model, prompt, max_new_tokens, openai_client)
    return ret

current_finish_req = 0
current_total_req = 0
display_done = False
async def main_openai(args):
    """Main function to run the benchmarking test."""
    global openai_client
    global tokenizer
    global api_url
    api_url = os.getenv("UNIEAI_API_URL", f"http://localhost:{args.port}/v1")
    openai_client = openai.AsyncOpenAI(api_key=api_key, base_url=api_url, timeout=86400)

    model = args.model_name
    max_new_tokens = args.max_new_tokens
    n_thread = args.concurrency
    debug = args.debug

    reqs = [0] * n_thread
    reqs_speed = [[] for _ in range(n_thread)]
    p_tokens = [0] * n_thread
    p_speed = [[] for _ in range(n_thread)]
    ftts_times = [[] for _ in range(n_thread)]
    tbt_times = [0] * n_thread
    d_tokens = [0] * n_thread
    d_speed = [[] for _ in range(n_thread)]
    start_times = [0] * n_thread
    end_times = [0] * n_thread

    baseline_ttft = await get_baseline_ttft(args.model_name, openai_client)

    global current_finish_req, current_total_req, display_done
    async def display_progress(refresh_interval=0.5):
        global current_finish_req, current_total_req, display_done
        while True:
            await asyncio.sleep(refresh_interval)
            if current_total_req > 0:
                bar_len = 40
                filled_len = int(bar_len * current_finish_req / current_total_req)
                bar = "#" * filled_len + "-" * (bar_len - filled_len)
                sys.stdout.write(
                    f"\r|{bar}| {current_finish_req}/{current_total_req}"
                )
                sys.stdout.flush()
            else:
                sys.stdout.flush()

            if display_done:
                print()
                break

    async def send_request(i):
        """Sends requests in a loop for a fixed duration and collects stats."""
        global current_finish_req, current_total_req, display_done
        start_time = time.time()
        if start_times[i] <= 0.0 or start_time < start_times[i]:
            start_times[i] = start_time
        total_messages = len(args.messages[i])
        index = 0
        while (time.time() - start_times[i]) < 120.0:
            prompt = args.messages[i][index%total_messages]
            index += 1
            current_total_req += 1
            ret = await fetch_remote1(model, prompt, max_new_tokens)
            end_time = time.time()
            if end_times[i] <= 0.0 or end_time > end_times[i]:
                end_times[i] = end_time
            response_text = ret["text"]
            ftts = ret["ftts"]
            tbt = ret["tbt"]
            p_time = ret["p_time"] - baseline_ttft # Calculate estimated prompt processing time
            if p_time <= 0:
                p_time = ret["p_time"]
            d_time = ret["d_time"]
            r_time = ret["r_time"]
            if debug != 0:
                print("prompt-text----------------------------------------")
                print(prompt)
                print("response-text--------------------------------------")
                print(response_text)
                print("---------------------------------------------------")
            dtokens = len(tokenizer.encode(response_text, add_special_tokens=False))
            ptokens = count_tokens(prompt)
            p_tokens[i] += ptokens
            p_speed[i].append(ptokens/p_time)
            d_tokens[i] += dtokens
            d_speed[i].append(dtokens/d_time)
            ftts_times[i].append(ftts)
            tbt_times[i] += tbt
            reqs_speed[i].append((ptokens+dtokens)/r_time)
            reqs[i] += 1
            current_finish_req += 1
            if debug != 0:
                break

    tasks = [asyncio.create_task(send_request(i)) for i in range(n_thread)]
    progress_task = asyncio.create_task(display_progress())
    await asyncio.gather(*tasks)
    display_done = True
    await progress_task

    n_p_tokens = sum(p_tokens)
    n_d_tokens = sum(d_tokens)
    flat_p_speed = [item for sublist in p_speed for item in sublist]
    flat_d_speed = [item for sublist in d_speed for item in sublist]
    flat_r_speed = [item for sublist in reqs_speed for item in sublist]
    n_p_speed = numpy.mean(flat_p_speed)
    n_d_speed = numpy.mean(flat_d_speed)
    n_r_speed = numpy.mean(flat_r_speed)
    n_tbt = sum(tbt_times)
    n_reqs = sum(reqs)
    elapsed_time = max(end_times) - min(start_times)
    flat_ftts_times = [item for sublist in ftts_times for item in sublist]
    n_ftts = sum(flat_ftts_times)
    P99 = numpy.percentile(flat_ftts_times, 99)
    P50 = numpy.percentile(flat_ftts_times, 50)

    output_data = {
        "concurrency": args.concurrency,
        "total_requests": n_reqs,
        "elapsed_time": elapsed_time,
        "number_of_prompt_tokens": n_p_tokens,
        "number_of_decode_tokens": n_d_tokens,
        "prompt_tokens_throughput": (n_p_tokens) / elapsed_time,
        "decode_tokens_throughput": (n_d_tokens) / elapsed_time,
        "total_tokens_throughput": (n_p_tokens + n_d_tokens) / elapsed_time,
        "rps": n_reqs / elapsed_time,
        "rpm": n_reqs / elapsed_time * 60,
        "ttft": n_ftts / n_reqs,
        "p50": P50,
        "p99": P99,
        "tbt": n_tbt / n_reqs,
        "tps": n_r_speed,
        "tps_decode": n_d_speed,
        "tps_prompt": n_p_speed,
    }
    width = 36
    num_width = 15
    precision = 5
    print(
        f"{'concurrency:':<{width}} {output_data['concurrency']:{num_width}.{0}f}\n"
        f"{'total requests:':<{width}} {output_data['total_requests']:{num_width}.{0}f}\n"
        f"{'elapsed_time (second):':<{width}} {output_data['elapsed_time']:{num_width}.{precision}f}\n"
        f"{'number of prompt tokens:':<{width}} {output_data['number_of_prompt_tokens']:{num_width}.{0}f}\n"
        f"{'number of decode tokens:':<{width}} {output_data['number_of_decode_tokens']:{num_width}.{0}f}\n"
        f"{'prompt tokens throughput (token/s):':<{width}} {output_data['prompt_tokens_throughput']:{num_width}.{precision}f}\n"
        f"{'decode tokens throughput (token/s):':<{width}} {output_data['decode_tokens_throughput']:{num_width}.{precision}f}\n"
        f"{'total tokens throughput (token/s):':<{width}} {output_data['total_tokens_throughput']:{num_width}.{precision}f}\n"
        f"{'RPS (request per second):':<{width}} {output_data['rps']:{num_width}.{precision}f}\n"
        f"{'RPM (request per minute):':<{width}} {output_data['rpm']:{num_width}.{precision}f}\n"
        f"{'TTFT (time to first token(second)):':<{width}} {output_data['ttft']:{num_width}.{precision}f}\n"
        f"{'P50 (second):':<{width}} {output_data['p50']:{num_width}.{precision}f}\n"
        f"{'P99 (second):':<{width}} {output_data['p99']:{num_width}.{precision}f}\n"
        f"{'TBT (token latency in second):':<{width}} {output_data['tbt']:{num_width}.{precision}f}\n"
        f"{'TPS (token/s per request):':<{width}} {output_data['tps']:{num_width}.{precision}f}\n"
        f"{'TPS decode (token/s per request):':<{width}} {output_data['tps_decode']:{num_width}.{precision}f}\n"
        f"{'TPS prompt (token/s per request):':<{width}} {output_data['tps_prompt']:{num_width}.{precision}f}\n"
    )

def to_openai_messages(conversation):
    """
    Converts a conversation from the dataset format to the OpenAI message format.

    The role 'human' is mapped to 'user', and other roles are mapped directly.
    """
    role_map = {
        "human": "user",
        "assistant": "assistant",
        "system": "system"
    }
    return [
        {
            "role": role_map.get(turn["role"].lower(), "user"),
            "content": turn["content"]
        }
        for turn in conversation
    ]

def reorder_chat_messages(messages):
    """
    Reorders a list of chat messages to ensure roles alternate
    user/assistant/user/assistant... after an optional system message.

    Args:
        messages (list of dict): Chat messages, each with "role" and "content".

    Returns:
        list of dict: Reordered messages in valid alternating format.
    """
    if not messages:
        return []

    # Separate messages by role
    system_messages = []
    user_messages = []
    assistant_messages = []

    for msg in messages:
        role = msg.get("role")
        if role == "system":
            system_messages.append(msg)
        elif role == "user":
            user_messages.append(msg)
        elif role == "assistant":
            assistant_messages.append(msg)

    # Build the alternating conversation
    reordered = []

    # Add a single system message if it exists
    if system_messages:
        reordered.append(system_messages[0])

    # Alternate user/assistant
    i = 0
    while i < max(len(user_messages), len(assistant_messages)):
        if i < len(user_messages):
            reordered.append(user_messages[i])
        if i < len(assistant_messages):
            reordered.append(assistant_messages[i])
        i += 1

    return reordered

def random_dataset(num_samples=1688, num_tokens=768):
    """
    Generates random input data where each 'content' is approximately
    num_tokens long according to the tokenizer.
    """
    global tokenizer
    import random
    import string

    dataset = []

    # Build a small vocabulary for efficiency
    vocab = string.ascii_lowercase + string.digits + " "

    for _ in range(num_samples):
        # Keep expanding text until tokenized length reaches the target
        text = ""
        while True:
            text += ''.join(random.choices(vocab, k=50))
            n_tokens = len(tokenizer.encode(text))
            if n_tokens >= num_tokens:
                # truncate to exactly 768 tokens
                tokens = tokenizer.encode(text)[:num_tokens]
                text = tokenizer.decode(tokens)
                break

        dataset.append({
            "conversation": [
                {"role": "user", "content": text}
            ]
        })
    return dataset



# --------------------

def inferencemax_h100(cfg: DictConfig, container, token_lengths, concurrency):
    logging.info('run benchmark inferencemax-h100...')
    benchmark(cfg, token_lengths, concurrency)
    logging.info('standardize benchmark result...')
    benchmark_post_processing(cfg, container, concurrency)
    logging.info('benchcmark completed')

def benchmark(cfg: DictConfig, token_lengths, concurrency):
    RESULT_ROOT = f'./results/{cfg.autotest.name}/inferencemax_h100'
    os.makedirs(RESULT_ROOT, exist_ok=True)

    cmd = [
        'python3', 'benchmark/inferencemax-h100/bench_serving/benchmark_serving.py',
        '--backend', 'openai',
        '--model', cfg.server.model_id,
        '--base-url', f'{cfg.server.base_url}:{cfg.server.port}',
        '--tokenizer', f'{cfg.server.model_path}/{cfg.server.model_name}',
        '--dataset-name', 'random',
        '--random-input-len', str(token_lengths.input_len),
        '--random-output-len', str(token_lengths.output_len),
        '--random-range-ratio', '0.8',
        '--num-prompts', f'{concurrency * 10}',
        '--max-concurrency', str(concurrency),
        '--request-rate', 'inf',
        '--ignore-eos',
        '--save-result', 
        '--percentile-metrics', 'ttft,tpot,itl,e2el',
        '--result-dir', RESULT_ROOT,
        '--result-filename', 'full_result.json'
    ]

    logging.info(cmd)
    subprocess.run(
        cmd,
        capture_output=False,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )

def benchmark_post_processing(cfg: DictConfig, container, concurrency):
    RESULT_ROOT = f'./results/{cfg.autotest.name}/inferencemax_h100'
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
        "benchmark": 'inferencemax-h100',

        "request_count": data['completed'],
        "interval": data['duration'] * 1000, # second to ms
        "concurrency": data['max_concurrency'],
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
    }
    
    dist = os.path.join(dist_folder, 'result.json')
    with open(dist, 'w') as fw:
        json.dump(result, fw, indent=4)

    shutil.copy(source, dist_folder)









if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-name", type=str, default=f"{mymodel}", help="OpenAI model name")
    parser.add_argument("--max-new-tokens", type=int, default=768, help="Max tokens to generate")
    parser.add_argument("--concurrency", type=int, default=1, help="Number of threads for testing")
    parser.add_argument("--port", type=str, default="8910")
    parser.add_argument("--debug", type=int, default=0)
    parser.add_argument("--tokenizer", type=str)
    args = parser.parse_args()

    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer)

    dataset = random_dataset(num_tokens=args.max_new_tokens)
    testdata = []
    for example in dataset:
        data = to_openai_messages(example["conversation"])
        data = reorder_chat_messages(data)
        testdata.append(data)
    messages = defaultdict(list)
    blocks = floor(len(testdata)/args.concurrency)
    limit = args.concurrency * blocks
    for i, d in enumerate(testdata):
        if i >= limit:
            break
        messages[i%args.concurrency].append(d)

    args.messages = messages
    # print(args.messages)
    asyncio.run(main_openai(args))