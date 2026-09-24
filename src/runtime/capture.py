"""Capture stage: camera, video file or network source -> Frames.

Every Frame is stamped with time.monotonic() the moment read() returns --
acquisition time, per CLAUDE.md: that value, not any later processing
time, is what reaches the session log and aligns the recording.

Failure posture (a demo must not die because a USB cable wiggled):
  camera/URL -- consecutive read failures -> release and reopen, backing
                off `reconnect_s`; the session keeps running meanwhile.
  file       -- end of file stops the source (or loops, if configured).

cv2 is imported lazily: it is an optional extra, and nothing under src/
may need it at import time.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from src.runtime.audio import console_printer
from src.runtime.pipeline import Frame

_BACKENDS = {  # name -> cv2 attribute
    "auto": "CAP_ANY",
    "dshow": "CAP_DSHOW",
    "msmf": "CAP_MSMF",
    "v4l2": "CAP_V4L2",
    "avfoundation": "CAP_AVFOUNDATION",
    "ffmpeg": "CAP_FFMPEG",
}


@dataclass(frozen=True)
class CaptureConfig:
    # int = camera index; str = file path or stream URL (rtsp://, udp://, http://)
    source: int | str = 0
    backend: str = "auto"
    width: int | None = None  # request only: the device may ignore it
    height: int | None = None
    fps: float | None = None
    realtime: bool = True  # files: pace to their own fps (like a live camera)
    loop: bool = False  # files: restart at EOF
    reconnect_s: float = 2.0
    max_read_failures: int = 10  # consecutive, before a reopen

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "CaptureConfig":
        c = cfg.get("capture") or {}
        src = c.get("source", 0)
        if isinstance(src, str) and src.strip().isdigit():
            src = int(src)
        backend = str(c.get("backend", "auto"))
        if backend not in _BACKENDS:
            raise ValueError(f"capture.backend must be one of {sorted(_BACKENDS)}, got {backend!r}")
        return cls(
            source=src, backend=backend,
            width=c.get("width"), height=c.get("height"), fps=c.get("fps"),
            realtime=bool(c.get("realtime", True)), loop=bool(c.get("loop", False)),
            reconnect_s=float(c.get("reconnect_s", 2.0)),
            max_read_failures=int(c.get("max_read_failures", 10)),
        )

    @property
    def is_file(self) -> bool:
        return isinstance(self.source, str) and "://" not in self.source


def _default_opener(cfg: CaptureConfig) -> Any:
    import cv2

    api = getattr(cv2, _BACKENDS[cfg.backend], cv2.CAP_ANY)
    cap = cv2.VideoCapture(cfg.source, api)
    if cfg.width:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.width)
    if cfg.height:
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.height)
    if cfg.fps:
        cap.set(cv2.CAP_PROP_FPS, cfg.fps)
    return cap


def _source_fps(cap: Any) -> float | None:
    try:
        import cv2

        fps = float(cap.get(cv2.CAP_PROP_FPS))
    except Exception:  # noqa: BLE001 -- fake captures in tests
        return None
    return fps if 1.0 <= fps <= 240.0 else None


@dataclass
class CaptureStats:
    frames: int = 0
    read_failures: int = 0
    reopens: int = 0
    measured_fps: float = 0.0


class VideoSource:
    """Runs capture on its own thread and hands each Frame to `on_frame`
    (which must be quick -- enqueue, never process inline)."""

    def __init__(
        self,
        cfg: CaptureConfig,
        on_frame: Callable[[Frame], None],
        opener: Callable[[CaptureConfig], Any] = _default_opener,
        clock: Callable[[], float] = time.monotonic,
        printer: Callable[[str], None] = console_printer,
        on_end: Callable[[], None] | None = None,
    ) -> None:
        self.cfg = cfg
        self.on_frame = on_frame
        self.opener = opener
        self.clock = clock
        self.printer = printer
        self.on_end = on_end
        self.stats = CaptureStats()
        self.frame_size: tuple[int, int] | None = None  # (width, height) of the last frame
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._seq = 0

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="capture", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def _open(self) -> Any | None:
        try:
            cap = self.opener(self.cfg)
        except Exception as exc:  # noqa: BLE001
            self.printer(f"WARNING: capture open failed: {exc}")
            return None
        if not cap.isOpened():
            cap.release()
            return None
        return cap

    def _run(self) -> None:
        cap = self._open()
        if cap is None:
            self.printer(f"WARNING: capture source {self.cfg.source!r} not available; retrying")
        fps_window: list[float] = []
        pace_t0: float | None = None
        pace_n = 0
        failures = 0
        try:
            while not self._stop.is_set():
                if cap is None:
                    if self.cfg.is_file:
                        break  # a missing file will not appear by waiting
                    self._stop.wait(self.cfg.reconnect_s)
                    cap = self._open()
                    if cap is not None:
                        self.stats.reopens += 1
                        self.printer("capture: source reopened")
                    continue

                if self.cfg.is_file and self.cfg.realtime:
                    src_fps = _source_fps(cap) or 30.0
                    now = self.clock()
                    if pace_t0 is None:
                        pace_t0 = now
                    due = pace_t0 + pace_n / src_fps
                    if due > now:
                        self._stop.wait(due - now)
                    pace_n += 1

                ok, img = cap.read()
                ts = self.clock()  # acquisition time
                if not ok or img is None:
                    if self.cfg.is_file:
                        if self.cfg.loop:
                            cap.release()
                            cap = self._open()
                            pace_t0, pace_n = None, 0
                            continue
                        break  # end of file
                    failures += 1
                    self.stats.read_failures += 1
                    if failures >= self.cfg.max_read_failures:
                        self.printer("WARNING: capture lost; reopening")
                        cap.release()
                        cap = None
                        failures = 0
                    continue

                failures = 0
                self._seq += 1
                self.stats.frames += 1
                self.frame_size = (int(img.shape[1]), int(img.shape[0]))
                fps_window.append(ts)
                if len(fps_window) > 30:
                    fps_window.pop(0)
                if len(fps_window) >= 2 and fps_window[-1] > fps_window[0]:
                    self.stats.measured_fps = (len(fps_window) - 1) / (fps_window[-1] - fps_window[0])
                try:
                    self.on_frame(Frame(seq=self._seq, ts_monotonic=ts, payload=img))
                except Exception as exc:  # noqa: BLE001 -- a consumer bug must not stop capture
                    self.printer(f"WARNING: frame consumer failed: {exc!r}")
        finally:
            if cap is not None:
                cap.release()
            if self.on_end is not None:
                self.on_end()
