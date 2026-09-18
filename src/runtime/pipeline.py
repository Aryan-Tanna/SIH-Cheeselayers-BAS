"""Async skeleton: threads with bounded queues.

threading, not asyncio — the workload is CPU-bound inference and the
libraries involved (OpenCV, YOLO, MediaPipe) release the GIL during
their native calls, so threads actually parallelize here.

Two rules, non-negotiable:

  1. Every queue DROPS old frames rather than growing. A backed-up queue
     means alerting about something that happened two seconds ago, which
     is worse than not alerting at all — so every stage is allowed to
     lose frames under load, never allowed to fall behind and stay
     behind.
  2. Every frame carries a monotonic timestamp from capture, and that
     timestamp — not a processing-time timestamp — is what eventually
     reaches the session log.

This module is a skeleton: stage bodies are placeholders (identity /
no-op) until phase 2 wires in real capture, detection, and landmarks.
The threading/queue/shutdown scaffolding is what phase 0 needs to prove
out, since it is invasive to retrofit later.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from src.runtime.clock import Clock, SystemClock


@dataclass(frozen=True, slots=True)
class Frame:
    seq: int
    ts_monotonic: float
    payload: Any = None


class DroppingQueue:
    """Bounded queue that drops the OLDEST item on overflow rather than
    blocking the producer or growing unbounded. Wraps queue.Queue instead
    of subclassing it — Queue's internals aren't meant to be overridden
    safely across Python versions.
    """

    def __init__(self, maxsize: int) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be >= 1")
        self._q: queue.Queue[Any] = queue.Queue(maxsize=maxsize)
        self.dropped_count = 0
        self._lock = threading.Lock()

    def put(self, item: Any) -> None:
        while True:
            try:
                self._q.put_nowait(item)
                return
            except queue.Full:
                try:
                    self._q.get_nowait()
                    with self._lock:
                        self.dropped_count += 1
                except queue.Empty:
                    continue

    def get(self, timeout: float | None = None) -> Any:
        return self._q.get(timeout=timeout)

    def qsize(self) -> int:
        return self._q.qsize()


class PipelineStage:
    """One thread, one input queue, one output queue (output may be
    None for a terminal stage like the state machine or the logger).
    `process` is a pure function: Frame -> Frame | None (None = drop,
    e.g. detector found nothing worth passing downstream this frame).
    """

    def __init__(
        self,
        name: str,
        process: Callable[[Frame], Frame | None],
        in_queue: DroppingQueue,
        out_queues: list[DroppingQueue] | None,
    ) -> None:
        self.name = name
        self.process = process
        self.in_queue = in_queue
        # A list, not a single queue: fusion/state-machine fans out to
        # audio, recorder/streamer, and gui simultaneously. A bare
        # queue.Queue has single-consumer semantics — two stages calling
        # get() on the same queue would race and split the stream rather
        # than each seeing every frame, so fan-out means pushing the
        # same result onto N independent queues, not sharing one.
        self.out_queues = out_queues or []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.frames_processed = 0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
        self._thread.start()

    def stop(self, timeout: float | None = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                frame = self.in_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            result = self.process(frame)
            self.frames_processed += 1
            if result is not None:
                for out_q in self.out_queues:
                    out_q.put(result)


@dataclass
class Pipeline:
    """Wires capture -> detection -> landmarks -> fusion/state-machine ->
    {audio, recorder/streamer, gui} with bounded, dropping queues between
    every stage. Stage callables are placeholders in phase 0.
    """

    clock: Clock = field(default_factory=SystemClock)
    queue_maxsize: int = 4
    stages: list[PipelineStage] = field(default_factory=list)
    queues: dict[str, DroppingQueue] = field(default_factory=dict)

    def add_stage(
        self,
        name: str,
        process: Callable[[Frame], Frame | None],
        in_queue_name: str,
        out_queue_names: list[str] | None,
    ) -> None:
        in_q = self.queues.setdefault(in_queue_name, DroppingQueue(self.queue_maxsize))
        out_qs = [
            self.queues.setdefault(qn, DroppingQueue(self.queue_maxsize))
            for qn in (out_queue_names or [])
        ]
        self.stages.append(PipelineStage(name, process, in_q, out_qs))

    def start(self) -> None:
        for s in self.stages:
            s.start()

    def stop(self) -> None:
        for s in self.stages:
            s.stop()

    def submit(self, queue_name: str, frame: Frame) -> None:
        self.queues[queue_name].put(frame)


def build_default_pipeline(clock: Clock | None = None) -> Pipeline:
    """The seven named stages from CLAUDE.md's async skeleton section,
    wired with identity placeholders. Phase 2 replaces each `process`
    callable; the queue topology and drop/timestamp behavior does not
    need to change when that happens.
    """
    p = Pipeline(clock=clock or SystemClock())
    identity: Callable[[Frame], Frame | None] = lambda f: f
    p.add_stage("capture", identity, "capture_in", ["detection_in"])
    p.add_stage("detection", identity, "detection_in", ["landmarks_in"])
    p.add_stage("landmarks", identity, "landmarks_in", ["fusion_in"])
    p.add_stage(
        "fusion_state_machine",
        identity,
        "fusion_in",
        ["audio_in", "record_in", "gui_in"],
    )
    p.add_stage("audio", lambda f: None, "audio_in", None)
    p.add_stage("recorder_streamer", lambda f: None, "record_in", None)
    p.add_stage("gui", lambda f: None, "gui_in", None)
    return p
