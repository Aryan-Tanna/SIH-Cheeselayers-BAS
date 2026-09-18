import time

from src.runtime.pipeline import DroppingQueue, Frame, build_default_pipeline


def test_dropping_queue_drops_oldest_on_overflow():
    q = DroppingQueue(maxsize=2)
    q.put("a")
    q.put("b")
    q.put("c")  # should drop "a"
    assert q.dropped_count == 1
    assert q.get(timeout=1) == "b"
    assert q.get(timeout=1) == "c"


def test_dropping_queue_never_blocks_producer():
    q = DroppingQueue(maxsize=1)
    start = time.perf_counter()
    for i in range(50):
        q.put(i)
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0  # producer never waits on a full queue


def test_pipeline_frame_flows_capture_to_all_terminal_stages():
    pipeline = build_default_pipeline()
    pipeline.start()
    try:
        pipeline.submit("capture_in", Frame(seq=0, ts_monotonic=0.0, payload="x"))
        time.sleep(0.3)
        for stage in pipeline.stages:
            assert stage.frames_processed >= 1, f"{stage.name} never processed a frame"
    finally:
        pipeline.stop()


def test_every_frame_carries_a_monotonic_capture_timestamp():
    f = Frame(seq=0, ts_monotonic=123.456, payload=None)
    assert f.ts_monotonic == 123.456
