import threading
import time

from src.perception.detector import Detection
from src.perception.fusion import FusionConfig, RoleBinding, SceneFusion
from src.runtime.perception_stage import PerceptionStage
from src.runtime.pipeline import Frame

BINDING = RoleBinding("container", "case_open", "case_closed", {"module_a": "red_module"})


def _det(cls, x0, y0, x1, y1):
    return Detection(cls, 0.9, (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0, 0.0,
                     ((x0, y0), (x1, y0), (x1, y1), (x0, y1)))


class FakeDetector:
    """payload is the list of detections to 'find' in that frame."""

    def __init__(self, delay=0.0, fail_on=None):
        self.delay, self.fail_on = delay, fail_on
        self.last_inference_ms = 0.0
        self.seen = []

    def detect(self, payload):
        self.seen.append(payload)
        if self.fail_on is not None and payload is self.fail_on:
            raise RuntimeError("bad frame")
        time.sleep(self.delay)
        self.last_inference_ms = self.delay * 1000
        return payload


def _stage(det):
    events = []
    st = PerceptionStage(det, SceneFusion(BINDING, FusionConfig(k=2, n=3)), events.append,
                         printer=lambda _: None)
    return st, events


def _wait(pred, t=3.0):
    end = time.monotonic() + t
    while time.monotonic() < end and not pred():
        time.sleep(0.01)
    return pred()


def test_events_carry_capture_timestamp_not_processing_time():
    st, events = _stage(FakeDetector())
    st.start()
    try:
        opened = [_det("case_open", 0, 0, 100, 100)]
        for i, ts in enumerate((100.0, 100.1, 100.2)):
            st.submit(Frame(seq=i, ts_monotonic=ts, payload=opened))
            assert _wait(lambda: st.stats.frames_processed >= i + 1)
        assert _wait(lambda: events)
        assert events[0].action == "open" and events[0].ts in (100.1, 100.2)
    finally:
        st.stop()


def test_newest_frame_wins_and_backlog_is_skipped():
    det = FakeDetector(delay=0.2)
    st, _ = _stage(det)
    st.start()
    try:
        for i in range(10):  # 10 frames arrive during one slow inference
            st.submit(Frame(seq=i, ts_monotonic=float(i), payload=[]))
            time.sleep(0.01)
        assert _wait(lambda: st.stats.frames_processed >= 2)
        assert st.stats.frames_skipped >= 5
        assert st.stats.frames_processed <= 3
    finally:
        st.stop()


def test_detector_failure_on_one_frame_does_not_stop_perception():
    bad = []
    det = FakeDetector(fail_on=bad)
    st, _ = _stage(det)
    st.start()
    try:
        st.submit(Frame(seq=0, ts_monotonic=0.0, payload=bad))
        assert _wait(lambda: len(det.seen) >= 1)
        st.submit(Frame(seq=1, ts_monotonic=0.1, payload=[]))
        assert _wait(lambda: st.stats.frames_processed >= 1)
    finally:
        st.stop()


def test_latest_detections_for_gui_overlay():
    st, _ = _stage(FakeDetector())
    st.start()
    try:
        dets = [_det("red_module", 0, 0, 10, 10)]
        st.submit(Frame(seq=7, ts_monotonic=time.monotonic(), payload=dets))
        assert _wait(lambda: st.latest_detections()[0] == 7)
        assert st.latest_detections()[1] == dets
        assert st.stats.frame_latency_ms >= 0
    finally:
        st.stop()


def test_stop_is_prompt_when_idle():
    st, _ = _stage(FakeDetector())
    st.start()
    t = time.perf_counter()
    st.stop()
    assert time.perf_counter() - t < 2.0
    assert not any(th.name == "perception" and th.is_alive() for th in threading.enumerate())


class CountingRack:
    """Stands in for RackTracker: counts marker detections; status settable."""

    def __init__(self, status="ok"):
        from src.perception.rack import RackPose

        self.calls = 0
        self.status = status
        self.last_markers = {1: None, 2: None}
        self._pose = RackPose
        self.latest = RackPose(status, None, (1, 2), 0.0, 0.0)

    def update(self, ts, image):
        self.calls += 1
        self.latest = self._pose(self.status, None, (1, 2), 0.0, ts)
        return self.latest


def _run_frames(st, n):
    st.start()
    try:
        for i in range(n):
            st.submit(Frame(seq=i, ts_monotonic=float(i), payload=[]))
            assert _wait(lambda: st.stats.frames_processed >= i + 1)
    finally:
        st.stop()


def test_markers_detected_every_nth_frame_while_the_pose_is_ok():
    rack = CountingRack("ok")
    st = PerceptionStage(FakeDetector(), SceneFusion(BINDING, FusionConfig(k=2, n=3)), lambda e: None,
                         printer=lambda _: None, rack=rack, rack_every_n=5)
    _run_frames(st, 20)
    assert rack.calls == 4


def test_markers_detected_every_frame_while_lost_or_calibrating():
    lost = CountingRack("none")
    st = PerceptionStage(FakeDetector(), SceneFusion(BINDING, FusionConfig(k=2, n=3)), lambda e: None,
                         printer=lambda _: None, rack=lost, rack_every_n=5)
    _run_frames(st, 10)
    assert lost.calls == 10
    ok = CountingRack("ok")
    st = PerceptionStage(FakeDetector(), SceneFusion(BINDING, FusionConfig(k=2, n=3)), lambda e: None,
                         printer=lambda _: None, rack=ok, rack_every_n=5)
    sink: list = []
    st.collect_markers(sink)
    _run_frames(st, 10)
    assert ok.calls == 10 and len(sink) == 10
