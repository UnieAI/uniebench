# SPDX-License-Identifier: Apache-2.0
"""P2P NCCL disaggregated prefill proxy.

The P2pNcclConnector uses ``proxy_port`` for ZMQ service discovery, not for
the OpenAI-compatible HTTP endpoint. This proxy therefore exposes two ports:
one ZMQ ROUTER socket for P/D registration and one HTTP port for clients.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import socket
import threading
import time
import uuid
from typing import Any

import aiohttp
import msgpack
import zmq
from quart import Quart, make_response, request


DEFAULT_PING_SECONDS = 5
UPSTREAM_TIMEOUT_SECONDS = int(os.environ.get("UPSTREAM_REQUEST_TIMEOUT_SECONDS", "110"))
AIOHTTP_TIMEOUT = aiohttp.ClientTimeout(
    total=UPSTREAM_TIMEOUT_SECONDS,
    sock_connect=30,
    sock_read=UPSTREAM_TIMEOUT_SECONDS,
)

app = Quart(__name__)

count = 0
prefill_instances: dict[str, tuple[str, float]] = {}
decode_instances: dict[str, tuple[str, float]] = {}
prefill_cv = threading.Condition()
decode_cv = threading.Condition()


def _remove_oldest_instances(instances: dict[str, tuple[str, float]]) -> None:
    oldest_key = next(iter(instances), None)
    while oldest_key is not None:
        zmq_address, deadline = instances[oldest_key]
        if deadline > time.time():
            break
        print(f"Remove [HTTP:{oldest_key}, ZMQ:{zmq_address}, stamp:{deadline}]", flush=True)
        instances.pop(oldest_key, None)
        oldest_key = next(iter(instances), None)


def _listen_for_register(poller: zmq.Poller, router_socket: zmq.Socket) -> None:
    while True:
        socks = dict(poller.poll())
        if router_socket not in socks:
            continue

        remote_address, message = router_socket.recv_multipart()
        data = msgpack.loads(message)
        node_type = data.get("type")
        http_address = data.get("http_address")
        zmq_address = data.get("zmq_address")

        if not http_address or not zmq_address:
            print(f"Unexpected registration from {remote_address}: {data}", flush=True)
            continue

        if node_type == "P":
            with prefill_cv:
                is_new = http_address not in prefill_instances
                prefill_instances[http_address] = (
                    zmq_address,
                    time.time() + DEFAULT_PING_SECONDS,
                )
                _remove_oldest_instances(prefill_instances)
                prefill_cv.notify_all()
        elif node_type == "D":
            with decode_cv:
                is_new = http_address not in decode_instances
                decode_instances[http_address] = (
                    zmq_address,
                    time.time() + DEFAULT_PING_SECONDS,
                )
                _remove_oldest_instances(decode_instances)
                decode_cv.notify_all()
        else:
            print(f"Unexpected registration from {remote_address}: {data}", flush=True)
            continue

        if is_new:
            print(f"Add [HTTP:{http_address}, ZMQ:{zmq_address}]", flush=True)


def start_service_discovery(hostname: str, port: int) -> threading.Thread:
    if not hostname:
        hostname = socket.gethostname()
    if port == 0:
        raise ValueError("discovery port cannot be 0")

    context = zmq.Context()
    router_socket = context.socket(zmq.ROUTER)
    router_socket.bind(f"tcp://{hostname}:{port}")
    poller = zmq.Poller()
    poller.register(router_socket, zmq.POLLIN)

    listener = threading.Thread(
        target=_listen_for_register,
        args=(poller, router_socket),
        daemon=True,
    )
    listener.start()
    print(f"ZMQ discovery listening on {hostname}:{port}", flush=True)
    return listener


def random_uuid() -> str:
    return uuid.uuid4().hex


async def forward_request(url: str, data: dict[str, Any], request_id: str):
    async with aiohttp.ClientSession(timeout=AIOHTTP_TIMEOUT) as session:
        headers = {"X-Request-Id": request_id}
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        print(
            f"POST {url} request_id={request_id} timeout={UPSTREAM_TIMEOUT_SECONDS}s",
            flush=True,
        )
        async with session.post(url=url, json=data, headers=headers) as response:
            print(f"POST {url} status={response.status}", flush=True)
            response.raise_for_status()
            async for chunk_bytes in response.content.iter_chunked(1024):
                yield chunk_bytes


async def forward_request_collect(url: str, data: dict[str, Any], request_id: str):
    async with aiohttp.ClientSession(timeout=AIOHTTP_TIMEOUT) as session:
        headers = {"X-Request-Id": request_id}
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        print(
            f"POST {url} request_id={request_id} timeout={UPSTREAM_TIMEOUT_SECONDS}s",
            flush=True,
        )
        async with session.post(url=url, json=data, headers=headers) as response:
            print(f"POST {url} status={response.status}", flush=True)
            body = await response.read()
            print(f"POST {url} done bytes={len(body)}", flush=True)
            response.raise_for_status()
            return body, response.status, response.headers.get("content-type")


def _pick_instance(
    instances: dict[str, tuple[str, float]],
    cv: threading.Condition,
    role: str,
    index: int,
) -> tuple[str, str]:
    deadline = time.time() + 30
    with cv:
        while not instances:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise RuntimeError(f"No {role} instances registered")
            cv.wait(timeout=remaining)

        _remove_oldest_instances(instances)
        if not instances:
            raise RuntimeError(f"No live {role} instances registered")

        http_address, (zmq_address, _) = list(instances.items())[index % len(instances)]
        return http_address, zmq_address


@app.route("/v1/completions", methods=["POST"])
@app.route("/v1/chat/completions", methods=["POST"])
async def handle_request():
    global count

    original_request_data = await request.get_json()
    prefill_request = original_request_data.copy()
    prefill_request["max_tokens"] = 1
    if "max_completion_tokens" in prefill_request:
        prefill_request["max_completion_tokens"] = 1
    prefill_request["stream"] = False

    try:
        prefill_addr, prefill_zmq_addr = _pick_instance(
            prefill_instances,
            prefill_cv,
            "prefill",
            count,
        )
        decode_addr, decode_zmq_addr = _pick_instance(
            decode_instances,
            decode_cv,
            "decode",
            count,
        )

        print(
            f"handle_request count={count}, [HTTP:{prefill_addr}, ZMQ:{prefill_zmq_addr}] "
            f"[HTTP:{decode_addr}, ZMQ:{decode_zmq_addr}]",
            flush=True,
        )
        count += 1

        request_id = (
            f"___prefill_addr_{prefill_zmq_addr}"
            f"___decode_addr_{decode_zmq_addr}_{random_uuid()}"
        )

        decode_url = f"http://{decode_addr}{request.path}"
        decode_task = None
        if not original_request_data.get("stream"):
            print(f"starting decode request EARLY request_id={request_id}", flush=True)
            decode_task = asyncio.create_task(
                forward_request_collect(
                    decode_url,
                    original_request_data,
                    request_id,
                )
            )

        _, _, _ = await forward_request_collect(
            f"http://{prefill_addr}{request.path}",
            prefill_request,
            request_id,
        )

        if original_request_data.get("stream"):
            print(f"starting decode stream request request_id={request_id}", flush=True)
            generator = forward_request(decode_url, original_request_data, request_id)
            response = await make_response(generator)
        else:
            if decode_task is None:
                raise RuntimeError("decode task was not started")
            body, status, content_type = await decode_task
            response = await make_response(body, status)
            if content_type:
                response.headers["Content-Type"] = content_type
        response.timeout = None
        return response
    except Exception as exc:
        import traceback

        print("Error occurred in disagg prefill proxy server", flush=True)
        print(exc, flush=True)
        print(traceback.format_exc(), flush=True)
        return {"error": str(exc)}, 502


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="P2P NCCL disaggregated prefill proxy")
    parser.add_argument("--discovery-host", default="0.0.0.0")
    parser.add_argument("--discovery-port", type=int, default=30001)
    parser.add_argument("--http-host", default="0.0.0.0")
    parser.add_argument("--http-port", type=int, default=11001)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    listener_thread = start_service_discovery(args.discovery_host, args.discovery_port)
    app.run(host=args.http_host, port=args.http_port)
    listener_thread.join()
