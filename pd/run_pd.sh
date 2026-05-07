#!/bin/bash
# This file demonstrates the example usage of disaggregated prefilling
# We will launch 2 vllm instances (1 for prefill and 1 for decode),
# and then transfer the KV cache between them.

#set -xe
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"
LOG_DIR="${SCRIPT_DIR}/logs"
mkdir -p "${LOG_DIR}"

echo "🚧🚧 Warning: The usage of disaggregated prefill is experimental and subject to change 🚧🚧"
sleep 1

# meta-llama/Meta-Llama-3.1-8B-Instruct or deepseek-ai/DeepSeek-V2-Lite
MODEL_NAME=test
TEST_REQUEST_TIMEOUT_SECONDS="${TEST_REQUEST_TIMEOUT_SECONDS:-120}"
UPSTREAM_REQUEST_TIMEOUT_SECONDS="${UPSTREAM_REQUEST_TIMEOUT_SECONDS:-110}"
export UPSTREAM_REQUEST_TIMEOUT_SECONDS

stop_pid() {
    local pid="$1"
    local name="$2"
    local grace_seconds="${3:-5}"
    local waited=0

    if [[ -z "${pid}" ]]; then
        return 0
    fi

    if ! kill -0 "${pid}" 2>/dev/null; then
        return 0
    fi

    kill "${pid}" 2>/dev/null || true

    while kill -0 "${pid}" 2>/dev/null; do
        if (( waited >= grace_seconds )); then
            echo "${name} did not exit after ${grace_seconds}s, forcing kill..."
            kill -9 "${pid}" 2>/dev/null || true
            break
        fi
        sleep 1
        waited=$((waited + 1))
    done

    wait "${pid}" 2>/dev/null || true
}

# Cleanup function
CLEANED_UP=0
cleanup() {
    trap - INT TERM EXIT

    if [[ "${CLEANED_UP}" -eq 1 ]]; then
        return
    fi
    CLEANED_UP=1

    echo "Cleaning up..."

    if [[ -n "${PREFILL_LOG_PID:-}" ]]; then
        stop_pid "${PREFILL_LOG_PID}" "prefill log tail" 2
    fi

    if [[ -n "${DECODE_LOG_PID:-}" ]]; then
        stop_pid "${DECODE_LOG_PID}" "decode log tail" 2
    fi

    if [[ -n "${PROXY_PID:-}" ]]; then
        stop_pid "${PROXY_PID}" "proxy" 5
        unset PROXY_PID
    fi

    # The docker image need to be fix: ModuleNotFoundError: No module named 'msgpack'
    docker compose -f service_p.yml down || true
    docker compose -f service_d.yml down || true

    echo "Cleanup complete."
}

handle_int() {
    trap - INT TERM EXIT
    echo "Caught interrupt/termination."
    cleanup
    exit 130
}

# Trap the SIGINT signal (triggered by Ctrl+C)
trap 'handle_int' INT TERM
trap 'cleanup' EXIT

# Create venv first if it does not exist
if [[ ! -d ".venv" ]]; then
    echo ".venv does not exist. Creating virtual environment..."
    python3 -m venv .venv
else
    echo ".venv already exists."
fi

# Activate venv
source .venv/bin/activate

# Upgrade pip first
python3 -m pip install --upgrade pip

# Install proxy dependencies.
python3 -m pip install quart httpx aiohttp fastapi uvicorn pyzmq msgpack


# A function that waits vLLM server to start
wait_for_server() {
    local port=$1
    local timeout_seconds=1200
    local start_time
    start_time=$(date +%s)

    echo -n "Waiting for server on port ${port}"

    while true; do
        if curl -s "localhost:${port}/v1/models" > /dev/null; then
            echo ""
            echo "Server on port ${port} is ready."
            return 0
        fi

        if (( $(date +%s) - start_time >= timeout_seconds )); then
            echo ""
            echo "Timeout waiting for server on port ${port}."
            return 1
        fi

        echo -n "."
        sleep 1
    done
}

check_connector_external_req_id() {
    local compose_file="$1"
    local service="$2"

    echo "Checking ${service} P2pNcclConnector external_req_id support..."
    set +e
    docker compose -f "${compose_file}" exec -T "${service}" python3 -c 'import inspect; from vllm.distributed.kv_transfer.kv_connector.v1.p2p.p2p_nccl_connector import P2pNcclConnector; src = inspect.getsource(P2pNcclConnector); print("external_req_id support:", "external_req_id" in src)'
    set -e
}

send_completion_request() {
    local prompt="$1"
    local output
    local curl_status

    set +e
    output=$(curl --max-time "${TEST_REQUEST_TIMEOUT_SECONDS}" -X POST -sS "http://localhost:${HTTP_PROXY_PORT}/v1/completions" \
        -H "Content-Type: application/json" \
        -d '{
"model": "'"$MODEL_NAME"'",
"prompt": "'"$prompt"'",
"max_tokens": 10,
"temperature": 0
}' 2>&1)
    curl_status=$?
    set -e

    if [[ "${curl_status}" -ne 0 ]]; then
        printf 'curl failed with exit=%s: %s\n' "${curl_status}" "${output}"
        return 0
    fi

    printf '%s\n' "${output}"
}

# P2pNcclConnector uses DISCOVERY_PORT for ZMQ registration. Clients send
# OpenAI-compatible HTTP requests to HTTP_PROXY_PORT.
DISCOVERY_PORT=30001
HTTP_PROXY_PORT=11001

PROXY_SERVER=disagg_proxy_p2p_nccl_xpyd.py
PROXY_LOG="${LOG_DIR}/proxy.log"

pkill -f "${PROXY_SERVER}" || true
sleep 1

if lsof -i TCP:${DISCOVERY_PORT} -sTCP:LISTEN -n -P >/dev/null 2>&1; then
    echo "Discovery port ${DISCOVERY_PORT} is still in use:"
    lsof -i TCP:${DISCOVERY_PORT} -sTCP:LISTEN -n -P || true
    exit 1
fi

if lsof -i TCP:${HTTP_PROXY_PORT} -sTCP:LISTEN -n -P >/dev/null 2>&1; then
    echo "HTTP proxy port ${HTTP_PROXY_PORT} is still in use:"
    lsof -i TCP:${HTTP_PROXY_PORT} -sTCP:LISTEN -n -P || true
    exit 1
fi

echo "Starting proxy server: discovery=${DISCOVERY_PORT}, http=${HTTP_PROXY_PORT}..."
echo "Proxy log: ${PROXY_LOG}"
python3 "${PROXY_SERVER}" \
  --discovery-host "0.0.0.0" \
  --discovery-port "${DISCOVERY_PORT}" \
  --http-host "0.0.0.0" \
  --http-port "${HTTP_PROXY_PORT}" \
  > "${PROXY_LOG}" 2>&1 &
PROXY_PID=$!
sleep 2

# You can also adjust --kv-ip and --kv-port for distributed inference.

# Prefilling instance, which is the KV producer
docker compose -f service_p.yml up -d

# Decoding instance, which is the KV consumer
docker compose -f service_d.yml up -d

echo ""
echo "========================================"
echo "Starting docker live logs ..."
echo "========================================"

docker compose -f service_p.yml logs -f service-p \
    > "${LOG_DIR}/prefill.log" 2>&1 &
PREFILL_LOG_PID=$!

docker compose -f service_d.yml logs -f service-d \
    > "${LOG_DIR}/decode.log" 2>&1 &
DECODE_LOG_PID=$!

# Wait until prefill and decode instances are ready
wait_for_server 8100
wait_for_server 8200
check_connector_external_req_id service_p.yml service-p
check_connector_external_req_id service_d.yml service-d

sleep 2

# Serve two example requests
echo "Sending test request 1..."
output1=$(send_completion_request "San Francisco is a")

echo "Sending test request 2..."
output2=$(send_completion_request "Santa Clara is a")


# Cleanup commands
# cleanup

echo ""

sleep 1

# Print the outputs of the curl requests
echo ""
echo "Output of first request: $output1"
echo "Output of second request: $output2"

if [[ "${output1}" == curl\ failed* || "${output2}" == curl\ failed* || "${output1}" == *'"error"'* || "${output2}" == *'"error"'* ]]; then
    echo "One or more test requests failed. Check ${PROXY_LOG}, ${LOG_DIR}/prefill.log, and ${LOG_DIR}/decode.log."
    exit 1
fi

echo "🎉🎉 Successfully finished 2 test requests! 🎉🎉"
echo ""
