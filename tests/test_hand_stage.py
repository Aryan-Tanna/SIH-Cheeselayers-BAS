"""Hand-skeleton thread: newest frame only, detector's latest boxes, never fatal."""

import time

from src.perception.hand_pose import HandCue, HandFrame
from src.runtime.hand_stage import HandStage
from src.runtime.pipeline import Frame


class FakeEstimator:
    def __init__(self, fail_on=None, delay=0.0):
        self.seen, self.fail_on, self.delay, self.closed = [], fail_on, delay, False

    def process(self, frame, ts, dets):
        self.seen.append((frame, ts, list(dets)))
        if frame == self.fail_on:
            raise RuntimeError("bad frame")
        time.sleep(self.delay)
        return HandFrame(cues=[HandCue("module_a", "holding")])

    def close(self):
        self.closed = True


def _wait(pred, t=3.0):
    end = time.monotonic() + t
    while time.monotonic() < end and not pred():
        time.sleep(0.01)
    return pred()


def test_runs_on_frames_with_the_detectors_latest_boxes_and_publishes_cues():
    est = FakeEstimator()
    st = HandStage(est, lambda: (7, ["det"]), printer=lambda _: None)
    st.start()
    try:
        st.submit(Frame(seq=1, ts_monotonic=5.0, payload="img"))
        assert _wait(lambda: st.frames == 1)
        assert est.seen[0] == ("img", 5.0, ["det"])
        assert st.latest().cues[0].state == "holding"
    finally:
        st.stop()
    assert est.closed


def test_a_failing_frame_does_not_stop_it_and_backlog_keeps_only_the_newest():
    est = FakeEstimator(fail_on="bad", delay=0.05)
    st = HandStage(est, lambda: (0, []), printer=lambda _: None)
    st.start()
    try:
        st.submit(Frame(seq=1, ts_monotonic=1.0, payload="bad"))
        assert _wait(lambda: len(est.seen) == 1)
        for i in range(5):  # arrive faster than it runs: only the newest survives
            st.submit(Frame(seq=2 + i, ts_monotonic=2.0 + i, payload=f"f{i}"))
        assert _wait(lambda: st.frames >= 1)
        time.sleep(0.2)
        assert est.seen[-1][0] == "f4" and len(est.seen) < 6
    finally:
        st.stop()


def test_real_mediapipe_blank_frame_and_repeated_timestamps():
    import pytest

    pytest.importorskip("mediapipe")
    np = pytest.importorskip("numpy")
    from src.perception.hand_pose import HandPoseConfig, HandPoseEstimator
    from src.protocol.loader import REPO_ROOT

    if not (REPO_ROOT / HandPoseConfig().model).is_file():
        pytest.skip("no hand landmark model")
    est = HandPoseEstimator(HandPoseConfig(), REPO_ROOT, {"hand_bare", "hand_gloved"},
                            {"module_a": {"red_module"}})
    try:
        blank = np.zeros((720, 1280, 3), dtype=np.uint8)
        for ts in (1.0, 1.0, 0.9, 1.1):  # VIDEO mode needs increasing times: repeats/rewinds must not crash
            hf = est.process(blank, ts, [])
            assert hf.poses == [] and hf.cues == []
    finally:
        est.close()
