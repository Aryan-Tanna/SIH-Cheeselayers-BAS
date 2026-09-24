"""Local recording + live stream: one H.264 encode, two outputs.

    frames --> [bounded queue] --> CFR alignment --> ffmpeg (libx264)
                                                        |-- tee --> local segments  <out>/<session>/seg_000.ts ...
                                                        '-- tee --> stream URL      udp://<ip>:<port> (or rtsp://, srt://)

One encode feeds both, because the CPU budget belongs to the detector.

Choices below were measured on 2026-09-24 (848x478, 15 fps, libx264
ultrafast), not assumed:

* Local segments are MPEG-TS, not MP4. Killing ffmpeg mid-segment at a
  realistic bitrate left 96/105 frames decodable in the .ts versus 69/105
  in a fragmented MP4 -- and a plain MP4 teed with an MPEG-TS stream was
  undecodable outright (the two containers disagree on where SPS/PPS
  live). A recording that dies with the process is useless as evidence.
  VLC/ffplay play .ts directly; a lossless remux to .mp4 is one command.
* The encoder only ever sends the stream as MPEG-TS over UDP: push-only,
  no server, and never blocks -- to an unroutable address, an absent LAN
  host and a closed port alike, all frames were recorded locally. An
  RTSP output inside the same ffmpeg is NOT safe: pointed at an
  unreachable server it stalled while connecting (`onfail=ignore` never
  fired), and the local recording came out 0 bytes. So an rtsp:// URL is
  served by a separate relay process (StreamRelay: loopback UDP -> RTSP,
  copy, no re-encode), supervised and restarted on its own; whatever it
  does, the recording is unaffected.
* ffmpeg's stderr is drained continuously. An undrained stderr pipe
  fills up under repeated errors and blocks ffmpeg, which blocks us.

Frame timing: video time must equal log time, or "the alert at
t=41.2 s" can't be found in the recording. Frames carry their capture
monotonic timestamp; frame n of the video is the frame captured nearest
t0 + n/fps. A late frame (behind the video clock) is dropped; a gap
(stalled camera, dropped queue items) is filled by repeating the last
frame. So video offset = ts_monotonic - t0, and the sidecar video.json
records t0 in both monotonic and UTC terms.

Nothing here may stop a session: a missing ffmpeg, a crashed encoder or
a full disk degrade to "not recording" with a printed warning.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from src.runtime.audio import console_printer


# ----------------------------------------------------------------------
# Constant-frame-rate alignment (pure)
# ----------------------------------------------------------------------

def cfr_writes(ts: float, t0: float, fps: float, last_index: int) -> tuple[int, int]:
    """For a frame captured at `ts`, how the constant-rate video absorbs it.

    Returns (fill, index): write the PREVIOUS frame `fill` times, then this
    frame once as video frame `index`. index == -1 means drop this frame
    (the video clock is already past it).
    """
    index = int((ts - t0) * fps + 0.5)
    if index <= last_index:
        return 0, -1
    return index - last_index - 1, index


# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class RecorderConfig:
    enabled: bool = True
    out_dir: str = "recordings"
    fps: float = 15.0
    segment_s: int = 300
    crf: int = 28
    max_bitrate_kbps: int = 1000
    preset: str = "ultrafast"
    ffmpeg: str = "auto"
    queue_maxsize: int = 8
    stream_enabled: bool = True
    stream_url: str = "udp://127.0.0.1:5000?pkt_size=1316"

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "RecorderConfig":
        rec = cfg.get("recording") or {}
        st = cfg.get("stream") or {}
        c = cls(
            enabled=bool(rec.get("enabled", True)),
            out_dir=str(rec.get("out_dir", "recordings")),
            fps=float(rec.get("fps", 15)),
            segment_s=int(rec.get("segment_s", 300)),
            crf=int(rec.get("crf", 28)),
            max_bitrate_kbps=int(rec.get("max_bitrate_kbps", 1000)),
            preset=str(rec.get("preset", "ultrafast")),
            ffmpeg=str(rec.get("ffmpeg", "auto")),
            queue_maxsize=int(rec.get("queue_maxsize", 8)),
            stream_enabled=bool(st.get("enabled", True)),
            stream_url=str(st.get("url", "udp://127.0.0.1:5000?pkt_size=1316")),
        )
        if c.fps <= 0 or c.segment_s <= 0 or c.queue_maxsize < 1:
            raise ValueError("recording: fps, segment_s must be > 0 and queue_maxsize >= 1")
        return c


def find_ffmpeg(setting: str = "auto") -> str | None:
    """Explicit path > the pinned binary bundled by imageio-ffmpeg (known
    to have libx264 + tee on every OS) > ffmpeg on PATH (unknown build)."""
    if setting != "auto":
        return setting if Path(setting).is_file() or shutil.which(setting) else None
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).is_file():
            return exe
    except (ImportError, RuntimeError):
        pass
    return shutil.which("ffmpeg")


def stream_format(url: str) -> str:
    return "rtsp" if url.lower().startswith("rtsp://") else "mpegts"


def build_ffmpeg_cmd(
    exe: str, width: int, height: int, cfg: RecorderConfig, segment_pattern: str,
    stream_udp_url: str | None = None,
) -> list[str]:
    """stream_udp_url: where the encoder sends the stream. For a udp://
    stream URL that is the URL itself; for rtsp:// it is the relay's
    loopback input (see StreamRelay). Never an rtsp:// URL -- see the
    module docstring."""
    fps = cfg.fps
    gop = max(1, int(round(fps * 2)))  # keyframe every 2 s: stream join time + segment cut points
    outputs = [
        f"[f=segment:segment_time={cfg.segment_s}:reset_timestamps=1:segment_format=mpegts]"
        + segment_pattern.replace("\\", "/")
    ]
    if stream_udp_url is not None:
        if stream_format(stream_udp_url) != "mpegts":
            raise ValueError(f"encoder stream output must be UDP/MPEG-TS, got {stream_udp_url!r}")
        outputs.append(f"[f=mpegts:onfail=ignore]{stream_udp_url}")
    return [
        exe, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}", "-r", f"{fps:g}", "-i", "-",
        "-an", "-c:v", "libx264", "-preset", cfg.preset, "-tune", "zerolatency",
        "-crf", str(cfg.crf), "-maxrate", f"{cfg.max_bitrate_kbps}k",
        "-bufsize", f"{2 * cfg.max_bitrate_kbps}k",
        "-g", str(gop), "-force_key_frames", f"expr:gte(t,n_forced*{cfg.segment_s})",
        "-pix_fmt", "yuv420p",
        "-map", "0:v", "-f", "tee", "|".join(outputs),
    ]


# ----------------------------------------------------------------------
# Encoders
# ----------------------------------------------------------------------

class Encoder(Protocol):
    def write(self, frame_bytes: bytes) -> None: ...
    def close(self) -> None: ...


class _StderrTail:
    """Drains a subprocess's stderr on a thread, keeping the last few KB."""

    def __init__(self, stream: Any, keep: int = 4096) -> None:
        self._buf: deque[bytes] = deque()
        self._size = 0
        self._keep = keep
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._pump, args=(stream,), daemon=True)
        self._thread.start()

    def _pump(self, stream: Any) -> None:
        read = stream.read1 if hasattr(stream, "read1") else stream.read
        while True:
            chunk = read(1024)
            if not chunk:
                return
            with self._lock:
                self._buf.append(chunk)
                self._size += len(chunk)
                while self._size > self._keep and len(self._buf) > 1:
                    self._size -= len(self._buf.popleft())

    def text(self, join_timeout: float = 1.0) -> str:
        self._thread.join(join_timeout)
        with self._lock:
            return b"".join(self._buf).decode("utf-8", "replace").strip()


class FfmpegEncoder:
    def __init__(self, cmd: list[str]) -> None:
        self._proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )
        self._stderr = _StderrTail(self._proc.stderr)

    def write(self, frame_bytes: bytes) -> None:
        assert self._proc.stdin is not None
        self._proc.stdin.write(frame_bytes)

    def kill(self) -> None:
        """Unblocks a writer stuck in write() (it gets BrokenPipeError)."""
        self._proc.kill()

    def close(self) -> str:
        """Finish the encode; returns ffmpeg's stderr (empty when healthy)."""
        try:
            if self._proc.stdin is not None:
                self._proc.stdin.close()
        except OSError:
            pass
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
        return self._stderr.text()


class StreamRelay:
    """rtsp:// streaming, isolated from the recording: the encoder sends
    UDP to a loopback port, and this separate ffmpeg copies it (no
    re-encode) to the RTSP server. Restarted with back-off whenever it
    exits; a hung or unreachable server affects only the stream."""

    def __init__(self, exe: str, rtsp_url: str, restart_s: float = 5.0,
                 printer: Callable[[str], None] = console_printer) -> None:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.input_url = f"udp://127.0.0.1:{self.port}?pkt_size=1316"
        self.cmd = [
            exe, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-fflags", "nobuffer",
            "-i", f"udp://127.0.0.1:{self.port}?overrun_nonfatal=1&fifo_size=50000",
            "-c", "copy", "-f", "rtsp", "-rtsp_transport", "tcp", rtsp_url,
        ]
        self.restart_s = restart_s
        self.printer = printer
        self.restarts = 0
        self._stop = threading.Event()
        self._proc: subprocess.Popen[bytes] | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._supervise, name="stream_relay", daemon=True)
        self._thread.start()

    def _supervise(self) -> None:
        while not self._stop.is_set():
            self._proc = subprocess.Popen(
                self.cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            while self._proc.poll() is None and not self._stop.is_set():
                self._stop.wait(0.2)
            if self._stop.is_set():
                break
            self.restarts += 1
            if self.restarts == 1:
                self.printer("WARNING: RTSP relay exited; retrying every "
                             f"{self.restart_s:g} s (local recording unaffected)")
            self._stop.wait(self.restart_s)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(2.0)
        if self._proc is not None and self._proc.poll() is None:
            self._proc.kill()
            self._proc.wait()


EncoderFactory = Callable[[int, int, str], Encoder]  # (width, height, segment_pattern)


# ----------------------------------------------------------------------
# Recorder
# ----------------------------------------------------------------------

@dataclass
class RecorderStats:
    frames_in: int = 0
    frames_written: int = 0  # video frames, including gap fills
    frames_duplicated: int = 0  # gap fills (camera stalled / frames dropped upstream)
    # not needed: the video clock is already past this frame. Normal when
    # the camera runs faster than recording.fps (30 -> 15 fps skips half).
    frames_skipped: int = 0
    frames_dropped_queue: int = 0  # dropped: recorder queue full
    frames_resized: int = 0


@dataclass
class VideoSidecar:
    session_id: str
    t0_monotonic: float | None = None
    t0_utc: str | None = None
    fps: float = 0.0
    width: int = 0
    height: int = 0
    segment_s: int = 0
    segment_pattern: str = ""
    stream_url: str | None = None
    encoder: str = ""
    stopped_utc: str | None = None
    error: str | None = None
    stats: dict[str, int] = field(default_factory=dict)
    note: str = (
        "video offset (s) = ts_monotonic - t0_monotonic; "
        "segment k covers [k*segment_s, (k+1)*segment_s)"
    )


class Recorder:
    """The runtime's recorder/streamer stage. submit() never blocks the
    caller; encoding happens on the recorder's own thread."""

    def __init__(
        self,
        cfg: RecorderConfig,
        session_id: str,
        repo_root: Path,
        encoder_factory: EncoderFactory | None = None,
        printer: Callable[[str], None] = console_printer,
    ) -> None:
        self.cfg = cfg
        self.session_id = session_id
        out_dir = Path(cfg.out_dir)
        self.dir = (out_dir if out_dir.is_absolute() else repo_root / out_dir) / session_id
        self.printer = printer
        self.stats = RecorderStats()
        self.warnings: list[str] = []
        self.ffmpeg: str | None = None
        self.relay: StreamRelay | None = None
        if encoder_factory is None:
            self.ffmpeg = find_ffmpeg(cfg.ffmpeg)
            if self.ffmpeg is None:
                self._warn("recording unavailable: no ffmpeg found (pip install imageio-ffmpeg)")
            else:
                exe = self.ffmpeg
                udp_url: str | None = None
                if cfg.stream_enabled and cfg.enabled:
                    if stream_format(cfg.stream_url) == "rtsp":
                        self.relay = StreamRelay(exe, cfg.stream_url, printer=printer)
                        udp_url = self.relay.input_url
                    else:
                        udp_url = cfg.stream_url
                encoder_factory = lambda w, h, pat: FfmpegEncoder(  # noqa: E731
                    build_ffmpeg_cmd(exe, w, h, cfg, pat, stream_udp_url=udp_url)
                )
        self._factory = encoder_factory
        self.sidecar = VideoSidecar(
            session_id=session_id, fps=cfg.fps, segment_s=cfg.segment_s,
            segment_pattern=str(self.dir / "seg_%03d.ts"),
            stream_url=cfg.stream_url if cfg.stream_enabled else None,
            encoder=f"libx264 via {self.ffmpeg}" if self.ffmpeg else "injected",
        )

        self._q: deque[tuple[Any, float]] = deque()
        self._cond = threading.Condition()
        self._stopping = False
        self._thread: threading.Thread | None = None
        self._encoder: Encoder | None = None
        self._failed = False
        self._last_index = -1
        self._last_frame: bytes | None = None
        self._size: tuple[int, int] | None = None  # (width, height)

    @property
    def active(self) -> bool:
        return self.cfg.enabled and self._factory is not None and not self._failed

    def _warn(self, msg: str) -> None:
        self.warnings.append(msg)
        self.printer(f"WARNING: {msg}")

    # -- producer side ---------------------------------------------------

    def submit(self, frame: Any, ts_monotonic: float) -> None:
        """frame: HxWx3 uint8 BGR (OpenCV order). Drops the OLDEST queued
        frame when full -- same rule as every runtime queue."""
        if not self.active:
            return
        with self._cond:
            self._q.append((frame, ts_monotonic))
            while len(self._q) > self.cfg.queue_maxsize:
                self._q.popleft()
                self.stats.frames_dropped_queue += 1
            self._cond.notify()

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if not self.active:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        if self.relay is not None:
            self.relay.start()
        self._thread = threading.Thread(target=self._run, name="recorder", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 15.0) -> VideoSidecar:
        """Drain what is queued, finish the encode, write video.json."""
        with self._cond:
            self._stopping = True
            self._cond.notify()
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive() and self._encoder is not None:
                # Writer stuck inside ffmpeg's stdin: kill to unblock it
                # rather than hang shutdown (closing the pipe under a
                # pending write can itself block on Windows).
                kill = getattr(self._encoder, "kill", None)
                if kill is not None:
                    kill()
                self._thread.join(2.0)
                self.sidecar.error = (self.sidecar.error or "") + "encoder stalled; killed at stop. "
        if self.relay is not None:
            self.relay.stop()
        if self._encoder is not None:
            err = self._encoder.close()
            if err:
                self.sidecar.error = (self.sidecar.error or "") + str(err)[:2000]
            self._encoder = None
        self.sidecar.stopped_utc = datetime.now(timezone.utc).isoformat()
        self.sidecar.stats = asdict(self.stats)
        if self.sidecar.t0_monotonic is not None:
            self._write_sidecar()
        return self.sidecar

    def _write_sidecar(self) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            (self.dir / "video.json").write_text(
                json.dumps(asdict(self.sidecar), indent=2), encoding="utf-8"
            )
        except OSError as exc:
            self._warn(f"could not write video.json: {exc}")

    # -- consumer side -------------------------------------------------------

    def _run(self) -> None:
        while True:
            with self._cond:
                self._cond.wait_for(lambda: self._q or self._stopping)
                if not self._q:
                    return  # stopping and drained
                frame, ts = self._q.popleft()
            if self._failed:
                continue
            try:
                self._consume(frame, ts)
            except Exception as exc:  # noqa: BLE001 -- recording must never kill the session
                self._failed = True
                self.sidecar.error = f"{type(exc).__name__}: {exc}"
                self._warn(f"recording stopped: {exc}")

    def _consume(self, frame: Any, ts: float) -> None:
        self.stats.frames_in += 1
        h, w = int(frame.shape[0]), int(frame.shape[1])
        if self._encoder is None:
            self._open(w, h, ts)
        assert self._size is not None
        if (w, h) != self._size:
            frame = _resize(frame, self._size)
            self.stats.frames_resized += 1
        t0 = self.sidecar.t0_monotonic
        assert t0 is not None  # set by _open (0.0 is a valid t0: no `or`)
        fill, index = cfr_writes(ts, t0, self.cfg.fps, self._last_index)
        if index < 0:
            self.stats.frames_skipped += 1
            return
        data = _as_bgr_bytes(frame)
        enc = self._encoder
        assert enc is not None
        if self._last_frame is not None:
            for _ in range(fill):
                enc.write(self._last_frame)
            self.stats.frames_duplicated += fill
            self.stats.frames_written += fill
        enc.write(data)
        self.stats.frames_written += 1
        self._last_frame = data
        self._last_index = index

    def _open(self, w: int, h: int, ts: float) -> None:
        # libx264 + yuv420p need even dimensions.
        w -= w % 2
        h -= h % 2
        self._size = (w, h)
        self.sidecar.width, self.sidecar.height = w, h
        self.sidecar.t0_monotonic = ts
        self.sidecar.t0_utc = datetime.now(timezone.utc).isoformat()
        assert self._factory is not None
        self._encoder = self._factory(w, h, self.sidecar.segment_pattern)
        self._write_sidecar()  # early, so a crash still leaves the time mapping


def _resize(frame: Any, size: tuple[int, int]) -> Any:
    import cv2

    return cv2.resize(frame, size, interpolation=cv2.INTER_AREA)


def _as_bgr_bytes(frame: Any) -> bytes:
    import numpy as np

    return np.ascontiguousarray(frame, dtype=np.uint8).tobytes()
