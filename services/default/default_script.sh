#!/bin/bash
set -euo pipefail

ENV_NAME="default_script_env"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_PATH="${SCRIPT_DIR}/${ENV_NAME}"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv command not found. Trying to install with pip..."
  python3 -m pip install --user --upgrade uv
  export PATH="${HOME}/.local/bin:${PATH}"
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "uv command still not found after installation attempt."
  exit 1
fi

if [ ! -d "${ENV_PATH}" ]; then
  uv venv "${ENV_PATH}"
fi

# shellcheck disable=SC1091
source "${ENV_PATH}/bin/activate"

uv pip install --upgrade pip
uv pip install --upgrade vllm

CUDA_VISIBLE_DEVICES=0 python -m vllm.entrypoints.cli.main serve Qwen/Qwen3-0.6B \
  --served-model-name qwen3-0.6b \
  --port 12470 \
  --trust-remote-code \
  --dtype float16
