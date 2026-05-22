#!/bin/bash
set -euo pipefail
CUDA_VISIBLE_DEVICES=0 uvx vllm serve Qwen/Qwen3-0.6B --port 12470
