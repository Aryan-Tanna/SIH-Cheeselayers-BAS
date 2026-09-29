"""Offline, enforced -- not just claimed.

install_offline_guard() adds a Python audit hook (PEP 578) to the process:
every outgoing connection and every name lookup is checked, and anything
that would leave the local network is REFUSED (the call raises) and
recorded -- except the addresses the operator configured on purpose (the
Earth downlink). Loopback, private LAN ranges (the phone camera, a second
PC) and link-local stay allowed: that is the station's own network.

Covers everything that uses Python sockets (our code, onnxruntime model
loading is file-only anyway, any library that tries to phone home). Native
libraries opening their own sockets in C (e.g. FFmpeg inside OpenCV for an
rtsp:// camera) bypass Python's audit hooks -- which is why camera URLs are
checked separately before they are opened (camera_setup.check_local).
"""

from __future__ import annotations

import ipaddress
import socket
import sys
from typing import Any, Callable

_state: dict[str, Any] = {"installed": False, "allow": set(), "blocked": [], "printer": None}


def is_local_ip(host: str) -> bool:
    """Loopback, private (10/8, 172.16/12, 192.168/16, fc00::/7) or link-local."""
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


def _local_name(host: str) -> bool:
    h = host.lower().rstrip(".")
    return h in ("localhost", "") or h == socket.gethostname().lower() or is_local_ip(h)


def _allowed(host: Any) -> bool:
    host = str(host)
    return _local_name(host) or host in _state["allow"]


def _hook(event: str, args: tuple) -> None:
    if event == "socket.connect":
        addr = args[1]
        if isinstance(addr, tuple) and addr and not _allowed(addr[0]):
            _refuse(f"connection to {addr[0]}:{addr[1] if len(addr) > 1 else ''}")
    elif event == "socket.getaddrinfo":
        host = args[0]
        if isinstance(host, bytes):
            host = host.decode(errors="replace")
        if host is not None and not _allowed(host):
            _refuse(f"name lookup of {host!r}")


def _refuse(what: str) -> None:
    _state["blocked"].append(what)
    pr = _state["printer"]
    if pr is not None and len(_state["blocked"]) <= 5:
        pr(f"OFFLINE GUARD: blocked {what} (outside the local network)")
    raise PermissionError(f"offline guard: {what} blocked - the co-pilot runs offline")


def install_offline_guard(allow_hosts: set[str] | None = None,
                          printer: Callable[[str], None] | None = print) -> None:
    """Idempotent. allow_hosts: extra hosts that may be reached (the Earth IP)."""
    _state["allow"] |= set(allow_hosts or ())
    _state["printer"] = printer
    if not _state["installed"]:
        sys.addaudithook(_hook)
        _state["installed"] = True


def allow_host(host: str) -> None:
    """E.g. the Earth IP typed on the start screen after the guard is on."""
    _state["allow"].add(host)


def guard_installed() -> bool:
    return bool(_state["installed"])


def blocked_attempts() -> list[str]:
    return list(_state["blocked"])
