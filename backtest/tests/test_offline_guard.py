"""Proof that the pytest-wide offline guard blocks supported network paths."""

from __future__ import annotations

import socket
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests
import yfinance as yf
from curl_cffi import requests as curl_requests


_BLOCKED = "pytest offline guard"


def test_direct_socket_probe_is_blocked():
    with pytest.raises(RuntimeError, match=_BLOCKED):
        socket.create_connection(("example.com", 443), timeout=0.1)


def test_unix_domain_socket_ipc_is_allowed():
    path = tempfile.mktemp(prefix="meridian-", dir="/tmp")
    server = socket.socket(socket.AF_UNIX)
    server.bind(path)
    server.listen()
    client = socket.socket(socket.AF_UNIX)
    try:
        client.connect(path)
        accepted, _ = server.accept()
        client.sendall(b"ok")
        assert accepted.recv(2) == b"ok"
        accepted.close()
    finally:
        client.close()
        server.close()
        __import__("os").unlink(path)


def test_loopback_tcp_and_http_clients_are_allowed():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"local")

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
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_loopback_udp_is_allowed():
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        client.sendto(b"ok", server.getsockname())
        assert server.recvfrom(2)[0] == b"ok"
    finally:
        client.close()
        server.close()


def test_requests_probe_is_blocked():
    with pytest.raises(RuntimeError, match=_BLOCKED):
        requests.get("https://example.com", timeout=0.1)


def test_yfinance_probe_is_blocked():
    with pytest.raises(RuntimeError, match=_BLOCKED):
        yf.download("SPY", period="1d", progress=False)


def test_curl_cffi_sync_and_async_probes_are_blocked():
    with pytest.raises(RuntimeError, match=_BLOCKED):
        curl_requests.get("https://example.com", timeout=0.1)

    async def probe():
        async with curl_requests.AsyncSession() as session:
            await session.get("https://example.com", timeout=0.1)

    import asyncio
    with pytest.raises(RuntimeError, match=_BLOCKED):
        asyncio.run(probe())


def test_guard_is_inherited_by_notebook_kernel_processes():
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import socket; "
                "socket.create_connection(('example.com', 443), timeout=0.1)"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert probe.returncode != 0
    assert _BLOCKED in probe.stderr


def test_zero_skip_policy_fails_a_skipped_child_suite(tmp_path):
    test_file = tmp_path / "test_deliberate_skip.py"
    test_file.write_text("import pytest\ndef test_skip(): pytest.skip('proof')\n")
    env = dict(__import__("os").environ, MERIDIAN_FAIL_ON_SKIP="1")
    probe = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "ci.zero_skip", str(test_file), "-q"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert probe.returncode == pytest.ExitCode.TESTS_FAILED
    assert "skipped test(s) are forbidden" in probe.stdout


def test_zero_skip_policy_accepts_a_zero_skip_child_suite(tmp_path):
    test_file = tmp_path / "test_no_skip.py"
    test_file.write_text("def test_pass(): assert True\n")
    env = dict(__import__("os").environ, MERIDIAN_FAIL_ON_SKIP="1")
    probe = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "ci.zero_skip", str(test_file), "-q"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert probe.returncode == pytest.ExitCode.OK, probe.stdout + probe.stderr
    assert "1 passed" in probe.stdout


def test_linux_egress_boundary_is_dual_stack_loopback_safe_and_fail_closed():
    guard = (__import__("pathlib").Path(__file__).parents[2] / "ci" / "egress_guard.sh").read_text()
    assert "iptables -w" in guard
    assert "ip6tables -w" in guard
    assert '-o lo -j RETURN' in guard
    assert '--ctstate ESTABLISHED,RELATED -j RETURN' in guard
    assert '-j REJECT' in guard
    assert '-I OUTPUT 1 -m owner --uid-owner "$TARGET_UID" -j "$CHAIN"' in guard
    assert "TARGET_UID=${MERIDIAN_EGRESS_UID:-${SUDO_UID:-}}" in guard
    assert "refusing to apply the job egress guard to uid 0" in guard
    assert "trap rollback_enable ERR" in guard
