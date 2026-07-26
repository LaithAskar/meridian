"""Runtime proof for the Ubuntu job-level egress boundary.

Run only after ``ci/egress_guard.sh enable``.  The raw libcurl and clean child
probes intentionally bypass Meridian's Python monkeypatch.
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests
import yfinance as yf
from curl_cffi import Curl, CurlOpt
from curl_cffi import requests as curl_requests
from jupyter_client import KernelManager

# A literal-IP HTTP endpoint avoids false positives from DNS or TLS failures:
# if the OS boundary is absent, this endpoint is reachable from GitHub runners.
EXTERNAL_URL = "http://1.1.1.1/"


def expect_denied(label, operation) -> None:
    try:
        operation()
    except Exception as exc:
        print(f"PASS denied {label}: {type(exc).__name__}: {exc}")
    else:
        raise AssertionError(f"external egress unexpectedly succeeded via {label}")


def prove_local_ipc() -> None:
    if hasattr(socket, "AF_UNIX"):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "probe.sock")
            server = socket.socket(socket.AF_UNIX)
            server.bind(path)
            server.listen()
            client = socket.socket(socket.AF_UNIX)
            client.connect(path)
            accepted, _ = server.accept()
            client.sendall(b"unix")
            assert accepted.recv(4) == b"unix"
            client.close(); accepted.close(); server.close()
        print("PASS Unix-domain socket IPC")

    udp_server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_server.bind(("127.0.0.1", 0))
    udp_client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_client.sendto(b"udp", udp_server.getsockname())
    assert udp_server.recvfrom(3)[0] == b"udp"
    udp_client.close(); udp_server.close()
    print("PASS loopback UDP IPC")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b"local")
        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/"
    try:
        assert requests.get(url, timeout=2).content == b"local"
        assert curl_requests.get(url, timeout=2).content == b"local"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
    print("PASS loopback TCP/HTTP IPC (requests + curl_cffi)")


def raw_curl() -> None:
    curl = Curl()
    try:
        curl.setopt(CurlOpt.URL, EXTERNAL_URL.encode())
        curl.setopt(CurlOpt.TIMEOUT_MS, 2000)
        curl.perform()
    finally:
        curl.close()


async def async_curl() -> None:
    async with curl_requests.AsyncSession() as session:
        await session.get(EXTERNAL_URL, timeout=2)


def prove_external_denial() -> None:
    expect_denied("socket", lambda: socket.create_connection(("1.1.1.1", 443), timeout=2))
    expect_denied("requests", lambda: requests.get(EXTERNAL_URL, timeout=2))
    expect_denied("yfinance", lambda: yf.download("SPY", period="1d", progress=False))
    expect_denied("curl_cffi sync", lambda: curl_requests.get(EXTERNAL_URL, timeout=2))
    expect_denied("curl_cffi async", lambda: asyncio.run(async_curl()))
    expect_denied("raw native curl_cffi Curl", raw_curl)

    child_env = os.environ.copy()
    child_env.pop("PYTHONPATH", None)  # bypass sitecustomize/Python diagnostics
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            f"from curl_cffi import requests; requests.get({EXTERNAL_URL!r}, timeout=2)",
        ],
        env=child_env,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert child.returncode != 0, "unguarded child process unexpectedly reached the internet"
    assert "CurlError" in child.stderr, child.stderr
    print("PASS denied clean child native curl_cffi process")

    native_curl = subprocess.run(
        ["curl", "--fail", "--silent", "--show-error", "--max-time", "2", EXTERNAL_URL],
        env=child_env,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert native_curl.returncode != 0, "native curl unexpectedly reached the internet"
    print("PASS denied native curl child process")

    manager = KernelManager(kernel_name="python3")
    manager.start_kernel(env=child_env)
    kernel = manager.client()
    kernel.start_channels()
    try:
        kernel.wait_for_ready(timeout=15)
        message_id = kernel.execute(
            "from curl_cffi import Curl, CurlOpt\n"
            "c = Curl()\n"
            "try:\n"
            f" c.setopt(CurlOpt.URL, {EXTERNAL_URL.encode()!r})\n"
            " c.setopt(CurlOpt.TIMEOUT_MS, 2000)\n"
            " c.perform()\n"
            " print('MERIDIAN_EGRESS_SUCCEEDED')\n"
            "except Exception as exc:\n"
            " print('MERIDIAN_EGRESS_DENIED', type(exc).__name__)\n"
            "finally:\n"
            " c.close()"
        )
        output = []
        while True:
            message = kernel.get_iopub_msg(timeout=10)
            if message.get("parent_header", {}).get("msg_id") != message_id:
                continue
            if message["msg_type"] == "stream":
                output.append(message["content"]["text"])
            if message["msg_type"] == "status" and message["content"]["execution_state"] == "idle":
                break
        rendered = "".join(output)
        assert "MERIDIAN_EGRESS_DENIED" in rendered, rendered
        assert "MERIDIAN_EGRESS_SUCCEEDED" not in rendered, rendered
    finally:
        kernel.stop_channels()
        manager.shutdown_kernel(now=True)
    print("PASS denied native curl_cffi from an actual notebook kernel process")


def main() -> None:
    prove_local_ipc()
    prove_external_denial()


if __name__ == "__main__":
    main()
