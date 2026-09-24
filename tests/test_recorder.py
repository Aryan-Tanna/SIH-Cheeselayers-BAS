import json
import socket
import threading
import time
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from src.runtime.recorder import (  # noqa: E402
    Recorder,
    RecorderConfig,
    build_ffmpeg_cmd,
    cfr_writes,
    find_ffmpeg,
    stream_format,
)

W, H = 64, 48


class FakeEncoder:
    def __init__(self, w, h, pattern):
        self.size = (w, h)
        self.frames: list[bytes] = []
        self.closed = False

    def write(self, b):
        self.frames.append(b)

    def close(self):
        self.closed = True
        return ""


def _rec(tmp_path, fail_after=None, **cfg):
    made = []

    def factory(w, h, pat):
        enc = FakeEncoder(w, h, pat)
        if fail_after is not None:
            orig = enc.write

            def write(b):
                if len(enc.frames) >= fail_after:
                    raise BrokenPipeError("encoder died")
                orig(b)
            enc.write = write
        made.append(enc)
        return enc

    c = RecorderConfig(**{"fps": 10.0, "out_dir": str(tmp_path), "queue_maxsize": 1000, **cfg})
    lines = []
    r = Recorder(c, "sess1", tmp_path, encoder_factory=factory, printer=lines.append)
    return r, made, lines


def _frame(v, w=W, h=H):
    return np.full((h, w, 3), v, dtype=np.uint8)


# --- CFR alignment (pure) -------------------------------------------------------

def test_cfr_on_time_frames_write_once():
    assert cfr_writes(0.0, 0.0, 10, -1) == (0, 0)
    assert cfr_writes(0.1, 0.0, 10, 0) == (0, 1)


def test_cfr_gap_fills_with_previous_frame():
    assert cfr_writes(0.5, 0.0, 10, 1) == (3, 5)  # frames 2,3,4 repeat the last


def test_cfr_late_or_duplicate_frame_dropped():
    assert cfr_writes(0.1, 0.0, 10, 1) == (0, -1)
    assert cfr_writes(0.12, 0.0, 10, 1) == (0, -1)


def test_cfr_jitter_rounds_to_nearest_slot():
    assert cfr_writes(0.26, 0.0, 10, 2) == (0, 3)


# --- recorder with a fake encoder --------------------------------------------------

def _run(r, frames):
    r.start()
    for f, ts in frames:
        r.submit(f, ts)
    return r.stop()


def test_video_time_equals_capture_time(tmp_path):
    r, made, _ = _rec(tmp_path)
    # 10 fps capture, then a 0.5 s stall, then more frames
    frames = [(_frame(i), 100.0 + i * 0.1) for i in range(5)]
    frames += [(_frame(50), 100.9), (_frame(51), 101.0)]
    side = _run(r, frames)
    enc = made[0]
    # frames 0..4, fill 5..8 with frame 4, then 9, 10 -> 11 video frames = 1.1 s
    assert len(enc.frames) == 11
    assert enc.frames[5] == enc.frames[4] == _frame(4).tobytes()
    assert enc.frames[9] == _frame(50).tobytes()
    assert r.stats.frames_duplicated == 4
    assert side.t0_monotonic == 100.0 and enc.closed


def test_late_frame_dropped(tmp_path):
    r, made, _ = _rec(tmp_path)
    _run(r, [(_frame(0), 0.0), (_frame(1), 0.1), (_frame(2), 0.12), (_frame(3), 0.2)])
    assert len(made[0].frames) == 3 and r.stats.frames_skipped == 1


def test_sidecar_written_with_time_mapping(tmp_path):
    r, _, _ = _rec(tmp_path)
    _run(r, [(_frame(0), 5.0), (_frame(1), 5.1)])
    side = json.loads((tmp_path / "sess1" / "video.json").read_text(encoding="utf-8"))
    assert side["t0_monotonic"] == 5.0 and side["t0_utc"] and side["stopped_utc"]
    assert side["fps"] == 10.0 and (side["width"], side["height"]) == (W, H)
    assert side["stats"]["frames_written"] == 2


def test_resolution_change_is_resized(tmp_path):
    pytest.importorskip("cv2")
    r, made, _ = _rec(tmp_path)
    _run(r, [(_frame(0), 0.0), (_frame(1, w=128, h=96), 0.1)])
    assert all(len(b) == W * H * 3 for b in made[0].frames)
    assert r.stats.frames_resized == 1


def test_odd_dimensions_trimmed_to_even(tmp_path):
    pytest.importorskip("cv2")
    r, made, _ = _rec(tmp_path)
    _run(r, [(_frame(0, w=65, h=49), 0.0)])
    assert made[0].size == (64, 48)


def test_queue_overflow_drops_oldest_never_blocks(tmp_path):
    gate = threading.Event()

    def slow_factory(w, h, pat):
        enc = FakeEncoder(w, h, pat)
        orig = enc.write
        enc.write = lambda b: (gate.wait(2.0), orig(b))
        return enc

    c = RecorderConfig(fps=10.0, out_dir=str(tmp_path), queue_maxsize=3)
    r = Recorder(c, "s", tmp_path, encoder_factory=slow_factory, printer=lambda _: None)
    r.start()
    t = time.perf_counter()
    for i in range(50):
        r.submit(_frame(i), i * 0.1)
    assert time.perf_counter() - t < 0.5          # submit never blocked
    gate.set()
    r.stop()
    assert r.stats.frames_dropped_queue > 0


def test_encoder_failure_degrades_without_raising(tmp_path):
    r, _, lines = _rec(tmp_path, fail_after=2)
    _run(r, [(_frame(i), i * 0.1) for i in range(6)])
    assert not r.active
    assert any("recording stopped" in ln for ln in lines)
    assert "BrokenPipeError" in (r.sidecar.error or "")


def test_disabled_recorder_is_a_no_op(tmp_path):
    r, made, _ = _rec(tmp_path, enabled=False)
    _run(r, [(_frame(0), 0.0)])
    assert made == [] and not (tmp_path / "sess1").exists()


def test_missing_ffmpeg_warns_and_disables(tmp_path):
    lines = []
    c = RecorderConfig(ffmpeg=str(tmp_path / "no_such_ffmpeg.exe"), out_dir=str(tmp_path))
    r = Recorder(c, "s", tmp_path, printer=lines.append)
    assert not r.active and any("no ffmpeg" in ln for ln in lines)
    r.submit(_frame(0), 0.0)  # must not raise
    r.stop()


# --- command construction -------------------------------------------------------------

def test_cmd_without_stream_has_only_local_output():
    tee = build_ffmpeg_cmd("ffmpeg", 848, 478, RecorderConfig(), "out/seg_%03d.ts")[-1]
    assert "|" not in tee and "segment_format=mpegts" in tee


def test_cmd_stream_is_teed_with_onfail_ignore():
    url = "udp://10.0.0.5:5000?pkt_size=1316"
    tee = build_ffmpeg_cmd("ffmpeg", 848, 478, RecorderConfig(), "out/seg_%03d.ts",
                           stream_udp_url=url)[-1]
    local, stream = tee.split("|")
    assert "onfail=ignore" in stream and stream.endswith(url)


def test_encoder_never_gets_an_rtsp_output():
    # measured: an unreachable RTSP server inside the encoder's tee stalls
    # the encoder and leaves a 0-byte local recording
    with pytest.raises(ValueError):
        build_ffmpeg_cmd("ffmpeg", 8, 8, RecorderConfig(), "x_%03d.ts",
                         stream_udp_url="rtsp://ground:8554/bas")


def test_rtsp_url_goes_through_isolated_relay(tmp_path):
    if find_ffmpeg("auto") is None:
        pytest.skip("no ffmpeg")
    assert stream_format("rtsp://ground:8554/bas") == "rtsp"
    c = RecorderConfig(stream_url="rtsp://ground:8554/bas", out_dir=str(tmp_path))
    r = Recorder(c, "s", tmp_path, printer=lambda _: None)
    assert r.relay is not None
    assert r.relay.input_url.startswith("udp://127.0.0.1:")
    assert r.relay.cmd[-1] == "rtsp://ground:8554/bas"


def test_stderr_flood_does_not_block_the_writer():
    import sys

    from src.runtime.recorder import FfmpegEncoder

    # a child that writes 2 MB to stderr before reading any stdin: with an
    # undrained stderr pipe it blocks, and so would our write()
    script = ("import sys; sys.stderr.write('x' * 2_000_000); sys.stderr.flush(); "
              "sys.stdin.buffer.read()")
    enc = FfmpegEncoder([sys.executable, "-c", script])
    done = threading.Event()

    def writer():
        for _ in range(50):
            enc.write(b"\x00" * 100_000)
        done.set()

    threading.Thread(target=writer, daemon=True).start()
    assert done.wait(10.0), "writer blocked behind an undrained stderr pipe"
    tail = enc.close()
    assert len(tail) <= 4096 + 1024


def test_config_from_runtime_yaml():
    from src.runtime.config import load_runtime_config

    c = RecorderConfig.from_config(load_runtime_config())
    assert c.fps > 0 and c.stream_url.startswith(("udp://", "rtsp://", "srt://"))
    with pytest.raises(ValueError):
        RecorderConfig.from_config({"recording": {"fps": 0}})


# --- real ffmpeg: segments decode, stream arrives -------------------------------------

def _count_frames(path: Path) -> int:
    cv2 = pytest.importorskip("cv2")
    cap = cv2.VideoCapture(str(path))
    n = 0
    while cap.read()[0]:
        n += 1
    cap.release()
    return n


@pytest.fixture
def udp_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    s.settimeout(0.2)
    got = {"bytes": 0}
    stop = threading.Event()

    def rx():
        while not stop.is_set():
            try:
                got["bytes"] += len(s.recvfrom(65536)[0])
            except (socket.timeout, OSError):
                pass

    t = threading.Thread(target=rx, daemon=True)
    t.start()
    yield s.getsockname()[1], got
    stop.set()
    t.join()
    s.close()


def test_real_ffmpeg_records_segments_and_streams(tmp_path, udp_port):
    if find_ffmpeg("auto") is None:
        pytest.skip("no ffmpeg")
    port, got = udp_port
    c = RecorderConfig(fps=15.0, segment_s=1, out_dir=str(tmp_path), queue_maxsize=1000,
                       stream_url=f"udp://127.0.0.1:{port}?pkt_size=1316")
    r = Recorder(c, "live", tmp_path, printer=lambda _: None)
    rng = np.random.default_rng(0)
    base = rng.integers(0, 255, (96, 128, 3), dtype=np.uint8)
    r.start()
    for i in range(45):  # 3 s at 15 fps
        r.submit(np.roll(base, i * 3, axis=1), 10.0 + i / 15)
    side = r.stop()
    time.sleep(0.3)
    assert side.error is None
    segs = sorted((tmp_path / "live").glob("seg_*.ts"))
    assert len(segs) >= 3
    assert sum(_count_frames(s) for s in segs) == r.stats.frames_written == 45
    assert got["bytes"] > 10_000  # the stream actually arrived
    assert (tmp_path / "live" / "video.json").is_file()


def test_real_ffmpeg_unreachable_rtsp_does_not_stop_local_recording(tmp_path):
    if find_ffmpeg("auto") is None:
        pytest.skip("no ffmpeg")
    c = RecorderConfig(fps=15.0, segment_s=5, out_dir=str(tmp_path), queue_maxsize=1000,
                       stream_url="rtsp://127.0.0.1:9/nobody_listening")
    r = Recorder(c, "norx", tmp_path, printer=lambda _: None)
    rng = np.random.default_rng(1)
    r.start()
    t = time.perf_counter()
    for i in range(30):
        r.submit(rng.integers(0, 255, (48, 64, 3), dtype=np.uint8), i / 15)
    r.stop()
    assert time.perf_counter() - t < 10.0      # no stall at shutdown either
    segs = sorted((tmp_path / "norx").glob("seg_*.ts"))
    assert segs and sum(_count_frames(s) for s in segs) == 30


def test_real_ffmpeg_unroutable_udp_does_not_stop_local_recording(tmp_path):
    if find_ffmpeg("auto") is None:
        pytest.skip("no ffmpeg")
    c = RecorderConfig(fps=15.0, segment_s=5, out_dir=str(tmp_path), queue_maxsize=1000,
                       stream_url="udp://10.255.255.1:5000?pkt_size=1316")
    r = Recorder(c, "unroutable", tmp_path, printer=lambda _: None)
    rng = np.random.default_rng(2)
    r.start()
    for i in range(30):
        r.submit(rng.integers(0, 255, (48, 64, 3), dtype=np.uint8), i / 15)
    r.stop()
    segs = sorted((tmp_path / "unroutable").glob("seg_*.ts"))
    assert sum(_count_frames(s) for s in segs) == 30
