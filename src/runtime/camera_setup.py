"""Network camera setup for the start screen: build the URL from the phone
app / camera type and an IP, check it stays on the local network, and
test it before an experiment depends on it."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from src.runtime.offline import is_local_ip

# name -> (scheme, default port, default path)
PRESETS: dict[str, tuple[str, int, str]] = {
    "DroidCam (phone app)": ("http", 4747, "/video"),
    "IP Webcam (Android app)": ("http", 8080, "/video"),
    "RTSP camera": ("rtsp", 554, "/stream1"),
    "Custom URL": ("http", 80, "/"),
}


def build_camera_url(preset: str, ip: str, port: str | int | None = None, path: str | None = None) -> str:
    scheme, dport, dpath = PRESETS.get(preset, PRESETS["Custom URL"])
    ip = ip.strip()
    if not ip:
        raise ValueError("Enter the camera's IP address (shown in the phone app), e.g. 192.168.1.23")
    p = str(port).strip() if port not in (None, "") else str(dport)
    if not p.isdigit():
        raise ValueError("Port must be a number")
    path = (path if path not in (None, "") else dpath) or "/"
    if not path.startswith("/"):
        path = "/" + path
    return f"{scheme}://{ip}:{p}{path}"


def check_local(url: str) -> str | None:
    """None if the camera is on this machine / the local network, else why
    not. Numeric IPs only: a host NAME would need a DNS lookup -- that is
    the internet, and the co-pilot runs offline."""
    host = urlsplit(url).hostname or ""
    if host in ("localhost",) or is_local_ip(host):
        return None
    if not host:
        return "no address in the URL"
    try:
        import ipaddress

        ipaddress.ip_address(host)
        return f"{host} is an internet address - the co-pilot only uses cameras on the local network"
    except ValueError:
        return f"use the camera's IP address, not the name {host!r} (a name needs DNS = internet)"


@dataclass
class ProbeResult:
    ok: bool
    message: str
    frame: Any = None  # BGR image when ok


def probe_source(source: int | str, timeout_s: float = 6.0) -> ProbeResult:
    """Open the source and read one frame, giving up after timeout_s (an
    unreachable IP camera can otherwise block for ~30 s)."""
    if isinstance(source, str) and "://" in source:
        why = check_local(source)
        if why:
            return ProbeResult(False, why)
    out: dict[str, ProbeResult] = {}

    def run() -> None:
        import cv2

        t0 = time.monotonic()
        if isinstance(source, str) and "://" in source:
            ms = int(timeout_s * 1000)
            cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG,
                                   [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, ms, cv2.CAP_PROP_READ_TIMEOUT_MSEC, ms])
        else:
            cap = cv2.VideoCapture(source)
        try:
            if not cap.isOpened():
                out["r"] = ProbeResult(False, "could not open it - check the IP, that the phone/camera app is "
                                              "running and on the same Wi-Fi, and that no other program uses it")
                return
            ok, frame = cap.read()
            if not ok or frame is None:
                out["r"] = ProbeResult(False, "opened, but no picture came")
                return
            h, w = frame.shape[:2]
            out["r"] = ProbeResult(True, f"OK - {w}x{h}, first frame in {time.monotonic() - t0:.1f} s", frame)
        finally:
            cap.release()

    t = threading.Thread(target=run, name="camera_probe", daemon=True)
    t.start()
    t.join(timeout_s + 2.0)
    return out.get("r") or ProbeResult(False, f"no answer in {timeout_s:.0f} s - check the IP and the Wi-Fi")
