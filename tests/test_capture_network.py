"""Network camera source: the setup where the payload camera is a separate
device (in testing, a phone running an IP-camera app) streaming MJPEG over
HTTP to the co-pilot machine. A tiny local MJPEG server stands in for the
phone, so this runs without one.
"""

import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from src.runtime.capture import CaptureConfig, VideoSource  # noqa: E402


class _MJPEGHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        i = 0
        try:
            while not self.server.stop.is_set():
                img = np.full((120, 160, 3), (i * 7) % 255, dtype=np.uint8)
                ok, jpg = cv2.imencode(".jpg", img)
                data = jpg.tobytes()
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n"
                                 + f"Content-Length: {len(data)}\r\n\r\n".encode() + data + b"\r\n")
                i += 1
                time.sleep(1 / 30)
        except (ConnectionError, OSError):
            pass


def _serve(port=0):
    srv = ThreadingHTTPServer(("127.0.0.1", port), _MJPEGHandler)
    srv.stop = threading.Event()
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _stop(srv):
    srv.stop.set()
    srv.shutdown()
    srv.server_close()


def _wait(pred, timeout):
    t = time.monotonic() + timeout
    while time.monotonic() < t:
        if pred():
            return True
        time.sleep(0.05)
    return False


def test_http_mjpeg_camera_is_captured():
    srv = _serve()
    url = f"http://127.0.0.1:{srv.server_address[1]}/video"
    frames = []
    src = VideoSource(CaptureConfig(source=url, backend="ffmpeg"), frames.append,
                      printer=lambda _: None)
    src.start()
    try:
        assert _wait(lambda: len(frames) >= 30, 15.0), f"only {len(frames)} frames"
        assert src.frame_size == (160, 120)
        assert src.stats.measured_fps > 15
    finally:
        src.stop()
        _stop(srv)


def test_network_camera_dropout_reconnects():
    srv = _serve()
    port = srv.server_address[1]
    url = f"http://127.0.0.1:{port}/video"
    frames = []
    src = VideoSource(CaptureConfig(source=url, backend="ffmpeg", reconnect_s=0.5,
                                    max_read_failures=3), frames.append, printer=lambda _: None)
    src.start()
    try:
        assert _wait(lambda: len(frames) >= 10, 15.0)
        _stop(srv)                                  # phone app closed / Wi-Fi drop
        time.sleep(1.0)
        n_before = len(frames)
        with socket.socket() as s:                  # make sure the port is free again
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv2 = _serve(port)
        try:
            assert _wait(lambda: len(frames) > n_before + 10, 20.0), "did not recover"
            assert src.stats.reopens >= 1
        finally:
            _stop(srv2)
    finally:
        src.stop()
