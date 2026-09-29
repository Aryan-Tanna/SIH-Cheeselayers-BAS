"""Message framing for the downlink, over one TCP connection.

Each message: 4-byte big-endian header length, the header as UTF-8 JSON,
then `size` bytes of binary payload (JPEG / report text; 0 for most).
Binary payloads are NOT base64'd: on a thin link, +33% matters.

Sender -> ground:  hello, steps, log, snapshot, report
Ground -> sender:  resume (on connect: the last msg_id it holds for this
                   link), ack (periodically: last msg_id stored)

Every sender message carries a `msg_id`, increasing for the lifetime of
the co-pilot process (`link_id`). The ground stores what it receives and
tells the sender where to resume after a drop, so nothing is lost or
duplicated: store-and-forward, as a real space link works.
"""

from __future__ import annotations

import json
import socket
import struct
from typing import Any

MAX_HEADER = 1 << 20
MAX_PAYLOAD = 64 << 20


def encode(header: dict[str, Any], payload: bytes = b"") -> bytes:
    h = dict(header)
    h["size"] = len(payload)
    raw = json.dumps(h, separators=(",", ":")).encode("utf-8")
    return struct.pack(">I", len(raw)) + raw + payload


def snapshot_name(seq: Any, label: Any) -> str:
    """File name of an event image, the same on board and on the ground."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(label or ""))
    return f"{int(seq or 0):05d}_{safe}.jpg"


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("link closed")
        buf += chunk
    return bytes(buf)


def read_message(sock: socket.socket) -> tuple[dict[str, Any], bytes]:
    (hlen,) = struct.unpack(">I", _recv_exact(sock, 4))
    if hlen > MAX_HEADER:
        raise ValueError(f"header too large: {hlen}")
    header = json.loads(_recv_exact(sock, hlen).decode("utf-8"))
    size = int(header.get("size", 0))
    if size > MAX_PAYLOAD:
        raise ValueError(f"payload too large: {size}")
    payload = _recv_exact(sock, size) if size else b""
    return header, payload
