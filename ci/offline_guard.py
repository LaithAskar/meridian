"""Fail-closed Python diagnostics for Meridian's offline pytest gate.

The operating-system egress guard in ``ci/egress_guard.sh`` is the security
boundary.  This module gives earlier, clearer failures for common Python
clients while deliberately preserving Unix-domain sockets and IP loopback.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

OFFLINE_ERROR = "external network access is disabled by Meridian's pytest offline guard"

_SOCKET_CONNECT = socket.socket.connect
_SOCKET_CONNECT_EX = socket.socket.connect_ex
_SOCKET_SENDTO = socket.socket.sendto
_CREATE_CONNECTION = socket.create_connection


def blocked_network(*_args, **_kwargs):
    raise RuntimeError(OFFLINE_ERROR)


def _is_loopback_host(host: object) -> bool:
    if not isinstance(host, str):
        return False
    normalized = host.rstrip(".").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        # Fail closed rather than performing DNS, which is itself external I/O.
        return False


def _is_local_address(sock: socket.socket, address: object) -> bool:
    if sock.family == socket.AF_UNIX:
        return True
    return (
        sock.family in (socket.AF_INET, socket.AF_INET6)
        and isinstance(address, tuple)
        and bool(address)
        and _is_loopback_host(address[0])
    )


def _guarded_connect(sock: socket.socket, address: object):
    if not _is_local_address(sock, address):
        return blocked_network()
    return _SOCKET_CONNECT(sock, address)


def _guarded_connect_ex(sock: socket.socket, address: object):
    if not _is_local_address(sock, address):
        return blocked_network()
    return _SOCKET_CONNECT_EX(sock, address)


def _guarded_sendto(sock: socket.socket, *args):
    if not args or not _is_local_address(sock, args[-1]):
        return blocked_network()
    return _SOCKET_SENDTO(sock, *args)


def _guarded_create_connection(address, *args, **kwargs):
    if not (
        isinstance(address, tuple)
        and bool(address)
        and _is_loopback_host(address[0])
    ):
        return blocked_network()
    return _CREATE_CONNECTION(address, *args, **kwargs)


def _is_local_url(url: object) -> bool:
    return isinstance(url, str) and _is_loopback_host(urlsplit(url).hostname)


def install() -> None:
    """Install IPC-safe diagnostics for common Python network paths."""
    socket.socket.connect = _guarded_connect
    socket.socket.connect_ex = _guarded_connect_ex
    socket.socket.sendto = _guarded_sendto
    socket.create_connection = _guarded_create_connection

    try:
        import requests
    except ImportError:
        pass
    else:
        original = requests.sessions.Session.request
        if not getattr(original, "_meridian_guard", False):
            def guarded_requests(session, method, url, *args, _original=original, **kwargs):
                if not _is_local_url(url):
                    return blocked_network()
                return _original(session, method, url, *args, **kwargs)

            guarded_requests._meridian_guard = True
            requests.sessions.Session.request = guarded_requests

    # curl_cffi uses native libcurl and therefore still requires the OS guard.
    # These wrappers are defense-in-depth diagnostics for its high-level sync
    # and async APIs; raw Curl and child-process denial are proven separately.
    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        pass
    else:
        for session_type in (curl_requests.Session, curl_requests.AsyncSession):
            original = session_type.request
            if getattr(original, "_meridian_guard", False):
                continue

            def guarded_curl(session, method, url, *args, _original=original, **kwargs):
                if not _is_local_url(url):
                    return blocked_network()
                return _original(session, method, url, *args, **kwargs)

            guarded_curl._meridian_guard = True
            session_type.request = guarded_curl

    try:
        import yfinance as yf
    except ImportError:
        pass
    else:
        yf.download = blocked_network
