import threading

import pytest

np = pytest.importorskip("numpy")

from src.runtime.capture import CaptureConfig, VideoSource  # noqa: E402


class FakeCap:
    """Scripted capture: a list of frames / None (read failure)."""

    def __init__(self, script, opened=True):
        self.script = list(script)
        self.opened = opened
        self.released = False

    def isOpened(self):
        return self.opened

    def read(self):
        if not self.script:
            return False, None
        item = self.script.pop(0)
        return (item is not None), item

    def get(self, _prop):
        return 30.0

    def release(self):
        self.released = True


def _img(v):
    return np.full((4, 6, 3), v, dtype=np.uint8)


def _run(cfg, caps, clock=None, timeout=3.0):
    frames, ended = [], threading.Event()
    caps = list(caps)
    opened = []

    def opener(_cfg):
        cap = caps.pop(0) if caps else FakeCap([], opened=False)
        opened.append(cap)
        return cap

    kw = {"clock": clock} if clock else {}
    src = VideoSource(cfg, frames.append, opener=opener, printer=lambda _: None,
                      on_end=ended.set, **kw)
    src.start()
    return src, frames, ended, opened


def test_frames_carry_acquisition_timestamps():
    ticks = iter(float(i) for i in range(100))
    cfg = CaptureConfig(source="clip.mp4", realtime=False)
    src, frames, ended, _ = _run(cfg, [FakeCap([_img(1), _img(2), _img(3)])],
                                 clock=lambda: next(ticks))
    assert ended.wait(3.0)
    assert [f.seq for f in frames] == [1, 2, 3]
    ts = [f.ts_monotonic for f in frames]
    assert ts == sorted(ts) and len(set(ts)) == 3
    assert src.frame_size == (6, 4)


def test_file_end_stops_source_and_releases():
    cfg = CaptureConfig(source="clip.mp4", realtime=False)
    src, frames, ended, opened = _run(cfg, [FakeCap([_img(1)])])
    assert ended.wait(3.0)
    src.stop()  # on_end fires from inside the thread's finally; let it exit
    assert len(frames) == 1 and opened[0].released and not src.running


def test_file_loop_reopens_at_eof():
    cfg = CaptureConfig(source="clip.mp4", realtime=False, loop=True)
    src, frames, _, _ = _run(cfg, [FakeCap([_img(1)]), FakeCap([_img(2)]), FakeCap([_img(3)])])
    for _ in range(200):
        if len(frames) >= 3:
            break
        threading.Event().wait(0.01)
    src.stop()
    assert [int(f.payload[0, 0, 0]) for f in frames[:3]] == [1, 2, 3]


def test_camera_read_failures_trigger_reopen_and_recover():
    cfg = CaptureConfig(source=0, max_read_failures=3, reconnect_s=0.01)
    first = FakeCap([_img(1), None, None, None])
    second = FakeCap([_img(2), _img(3)])
    src, frames, _, opened = _run(cfg, [first, second])
    for _ in range(300):
        if len(frames) >= 3:
            break
        threading.Event().wait(0.01)
    src.stop()
    assert [int(f.payload[0, 0, 0]) for f in frames[:3]] == [1, 2, 3]
    assert src.stats.reopens == 1 and first.released


def test_camera_absent_at_start_keeps_retrying_without_raising():
    cfg = CaptureConfig(source=0, reconnect_s=0.01)
    src, frames, _, opened = _run(cfg, [FakeCap([], opened=False), FakeCap([], opened=False),
                                        FakeCap([_img(9)])])
    for _ in range(300):
        if frames:
            break
        threading.Event().wait(0.01)
    src.stop()
    assert frames and len(opened) >= 3


def test_missing_file_ends_instead_of_retrying_forever():
    cfg = CaptureConfig(source="missing.mp4", realtime=False)
    _, frames, ended, _ = _run(cfg, [FakeCap([], opened=False)])
    assert ended.wait(3.0) and frames == []


def test_consumer_exception_does_not_stop_capture():
    calls = []

    def bad_consumer(f):
        calls.append(f)
        raise RuntimeError("boom")

    cfg = CaptureConfig(source="clip.mp4", realtime=False)
    ended = threading.Event()
    src = VideoSource(cfg, bad_consumer, opener=lambda _c: FakeCap([_img(1), _img(2)]),
                      printer=lambda _: None, on_end=ended.set)
    src.start()
    assert ended.wait(3.0) and len(calls) == 2


def test_config_parsing():
    c = CaptureConfig.from_config({"capture": {"source": "1", "backend": "dshow"}})
    assert c.source == 1 and not c.is_file
    assert CaptureConfig.from_config({"capture": {"source": "rtsp://cam/1"}}).is_file is False
    assert CaptureConfig.from_config({"capture": {"source": "a.mp4"}}).is_file is True
    with pytest.raises(ValueError):
        CaptureConfig.from_config({"capture": {"backend": "directx"}})


def test_real_video_file_round_trip(tmp_path):
    cv2 = pytest.importorskip("cv2")
    path = tmp_path / "tiny.avi"
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (64, 48))
    if not w.isOpened():
        pytest.skip("no MJPG writer in this OpenCV build")
    for i in range(20):
        w.write(np.full((48, 64, 3), i * 10, dtype=np.uint8))
    w.release()
    frames, ended = [], threading.Event()
    src = VideoSource(CaptureConfig(source=str(path), realtime=False), frames.append,
                      printer=lambda _: None, on_end=ended.set)
    src.start()
    assert ended.wait(5.0)
    assert len(frames) == 20 and src.frame_size == (64, 48)
