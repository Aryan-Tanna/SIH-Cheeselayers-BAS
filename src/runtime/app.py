"""The co-pilot, assembled: every runtime stage wired to one Session.

    camera/file --> VideoSource --+--> Recorder (local segments + stream)
                                  +--> latest frame (GUI)
                                  '--> PerceptionStage (newest frame only):
                                       detector -> fusion -> step events
    scripted events (--events)  ---> Session  <--- "Hey BAS" commands / GUI buttons
                                        |  \\---> JSONL hash-chained log
                                        '-----> announcer -> AudioWorker -> speaker
    ticker (4 Hz) ---> Session.tick()   (timeouts fire with no new event)
    protocol file watcher ---> validate -> Session.reload_protocol()   (hot reload)

All timestamps are time.monotonic(): capture stamps frames with it and
the session clock is the same clock, so the log's ts_monotonic and the
recording's video offset (video.json: ts - t0) line up exactly.

Perception emits container open/close and module remove/return
(src/perception/fusion.py). Lid steps are not perceived yet: the
operator confirms them ("Hey BAS, next step" / the GUI). A scripted
event stream (harness/synthetic format) can still drive the session for
demos and tests, with or without perception.

Every optional part -- voice, microphone, camera, recording, stream --
degrades with a printed warning; none of them can stop a session.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.logging.report import build_report
from src.logging.session_log import SessionLogger, load_events, verify_chain
from src.protocol.engine import IMPLEMENTED_CONSTRAINT_IDS
from src.protocol.events import ActionEvent, AnomalyEvent, EngineEvent
from src.protocol.loader import (
    DEFAULT_DEFAULTS_PATH,
    REPO_ROOT,
    ResolvedProtocol,
    format_resolved_report,
    repo_path,
    resolve,
)
from src.runtime.announcer import (
    RESTART_CONFIRM_TEXT,
    RESTARTING_TEXT,
    AnnouncerSettings,
    AudioRequest,
    speakable_phrases,
)
from src.runtime.audio import console_printer
from src.runtime.capture import CaptureConfig, VideoSource
from src.runtime.clock import SystemClock
from src.runtime.config import AudioStage, build_audio_stage
from src.runtime.perception_stage import PerceptionStage, build_perception
from src.runtime.pipeline import Frame
from src.runtime.recorder import Recorder, RecorderConfig
from src.runtime.session import Session
from src.runtime.voice_control import build_listener


class ProtocolInvalid(ValueError):
    pass


def load_validated(protocol_path: Path, defaults_path: Path = DEFAULT_DEFAULTS_PATH,
                   object_profile: str | Path | None = None) -> ResolvedProtocol:
    """Validator first (line-numbered findings), then resolve. A malformed
    protocol fails loudly here -- at load or hot reload, never mid-run."""
    from scripts.validate_protocol import validate

    findings = validate(protocol_path, defaults_path, object_profile)
    if findings:
        raise ProtocolInvalid(
            f"{protocol_path} failed validation ({len(findings)} finding(s)):\n"
            + "\n".join(str(f) for f in findings)
        )
    return resolve(protocol_path, defaults_path, object_profile)


@dataclass
class AppOptions:
    protocol: Path | None = None  # default: configs/runtime.yaml session.protocol
    source: int | str | None = None  # override capture.source
    events: Path | None = None  # scripted event stream (harness/synthetic format)
    voice_control: bool = True
    capture: bool = True
    record: bool = True
    audio: bool = True
    session_id: str | None = None
    stream_url: str | None = None  # override stream.url (e.g. udp://<phone-ip>:5000)
    object_profile: str | None = None  # override session.object_profile / the protocol's
    perception: bool = True  # detector + fusion on camera frames (needs capture)
    downlink: str | None = None  # "host[:port]": send log + event snapshots to a ground station
    link_delay_s: float | None = None  # simulated one-way light-time (demo), overrides config


@dataclass
class AppStatus:
    """What a GUI shows. Built by CopilotApp.status()."""

    session_id: str
    protocol: dict[str, Any]
    capture_fps: float
    frame_size: tuple[int, int] | None
    recording: bool
    stream_url: str | None
    voice_control: bool
    listening_armed: bool
    mic_name: str | None = None
    mic_silent: bool = False
    perception: bool = False
    detector_fps: float = 0.0
    frame_latency_ms: float = 0.0
    perception_states: dict[str, str] = field(default_factory=dict)
    rack_status: str = "off"  # ok | held | none | uncalibrated | off
    rack_markers_seen: tuple[int, ...] = ()
    rack_reproj_px: float | None = None
    rack_summary: str = ""
    # hand skeletons (src/runtime/hand_stage.py): cues like
    # {"obj": "module_a", "state": "reaching", "eta_s": 0.8}
    hand_pose: bool = False
    hand_fps: float = 0.0
    hand_cues: list[dict[str, Any]] = field(default_factory=list)
    gloved_hands: int = 0
    recent_events: list[dict[str, Any]] = field(default_factory=list)
    recent_speech: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    uptime_s: float = 0.0
    downlink: dict[str, Any] | None = None  # src/link/sender.py Downlink.status()
    activity: str = ""  # derived activity (src/runtime/activity.py), "" without perception
    last_report: str | None = None


class CopilotApp:
    def __init__(
        self,
        cfg: dict[str, Any],
        opts: AppOptions | None = None,
        printer: Callable[[str], None] = console_printer,
    ) -> None:
        self.cfg = cfg
        self.opts = opts or AppOptions()
        self.printer = printer
        self.clock = SystemClock()
        self.warnings: list[str] = []
        sess_cfg = cfg.get("session") or {}
        # FIRST, before anything heavy is built: FFmpeg opens network cameras
        # in C, outside the offline guard, so the address itself must be on
        # the local network. (Refusing later leaks a MediaPipe landmarker whose
        # garbage-collected close() deadlocks the process -- found in tests.)
        if self.opts.capture:
            src = self.opts.source if self.opts.source is not None else (cfg.get("capture") or {}).get("source")
            if isinstance(src, str) and "://" in src:
                from src.runtime.camera_setup import check_local

                why = check_local(src)
                if why:
                    raise ValueError(f"camera {src} refused: {why}")

        # --- protocol -------------------------------------------------------
        self.protocol_path = repo_path(
            self.opts.protocol or sess_cfg.get("protocol", "configs/protocols/bas_specimen_v1.json")
        )
        self.defaults_path = DEFAULT_DEFAULTS_PATH
        # Which props are on the rig: the same protocol runs on jar, slab
        # or mixed props by swapping only the profile.
        self.object_profile = self.opts.object_profile or sess_cfg.get("object_profile")
        self.resolved = load_validated(self.protocol_path, self.defaults_path, self.object_profile)
        # CLAUDE.md: the resolved constraint set is printed at startup,
        # [default] vs [protocol], so nothing is enforced invisibly.
        self.printer(format_resolved_report(self.resolved, IMPLEMENTED_CONSTRAINT_IDS))

        # --- audio ----------------------------------------------------------
        audio_cfg = cfg
        if not self.opts.audio:
            audio_cfg = {**cfg, "audio": {**cfg["audio"], "enabled": False}}
        self.audio: AudioStage = build_audio_stage(audio_cfg, printer=printer)
        self.warnings += self.audio.warnings

        self._recent_events: deque[dict[str, Any]] = deque(maxlen=50)
        self._recent_speech: deque[dict[str, Any]] = deque(maxlen=20)
        self.last_report: Path | None = None
        from src.runtime.activity import ActivityTracker

        act_cfg = cfg.get("activity") or {}
        self.activity = ActivityTracker(min_hold_s=float(act_cfg.get("min_hold_s", 1.0)))
        self._activity_log = bool(act_cfg.get("log", True))
        # --- downlink to the ground (before the first session: its hello
        # must precede the session's first log line) -------------------------
        self.downlink = None
        from src.link.sender import Downlink, DownlinkConfig

        dl_cfg = DownlinkConfig.from_config(cfg)
        if self.opts.downlink:
            dl_cfg = dl_cfg.with_target(self.opts.downlink)
        if self.opts.link_delay_s is not None:
            dl_cfg = replace(dl_cfg, simulate_delay_s=float(self.opts.link_delay_s))
        # Always on: one image per step / alert, attested in the log and kept on
        # board with it (logs/<session>/), so a fully offline session can be
        # sent to Earth later. The network link only when enabled (LIVE mode).
        self.downlink = Downlink(dl_cfg, attest=self._attest_snapshot, printer=printer,
                                 send=dl_cfg.enabled,
                                 save_root=repo_path(sess_cfg.get("log_dir", "logs")))
        if dl_cfg.enabled:
            self.printer(f"downlink LIVE: log + event images to ground {dl_cfg.host}:{dl_cfg.port}"
                         + (f" (simulated light-time {dl_cfg.simulate_delay_s:g} s)"
                            if dl_cfg.simulate_delay_s else ""))
        else:
            self.printer("offline: log + event images kept on board (logs/); "
                         "send them to Earth later from Sessions")
        # --- session + log --------------------------------------------------
        self._restart_lock = threading.Lock()
        self._restart_armed_until = 0.0
        self.log_dir = repo_path(sess_cfg.get("log_dir", "logs"))
        self.session_id = ""
        self._new_session(self.opts.session_id)

        # --- voice control ----------------------------------------------------
        self.listener = None
        self._armed_until = 0.0
        if self.opts.voice_control:
            self.listener, warn = build_listener(cfg, REPO_ROOT, self._on_voice)
            if warn:
                self._warn(warn)

        # --- recording + capture ----------------------------------------------
        rec_cfg = RecorderConfig.from_config(cfg)
        if not self.opts.record:
            rec_cfg = replace(rec_cfg, enabled=False)
        if self.opts.stream_url:
            rec_cfg = replace(rec_cfg, stream_enabled=True, stream_url=self.opts.stream_url)
        self.recorder = Recorder(rec_cfg, self.session_id, REPO_ROOT, printer=printer)
        self.warnings += self.recorder.warnings

        self._latest_frame: Frame | None = None
        self._frame_lock = threading.Lock()

        # --- perception ---------------------------------------------------------
        self.perception: PerceptionStage | None = None
        if self.opts.perception and self.opts.capture:
            # Looked up per event, not bound once: a restart swaps the session.
            self.perception, why = build_perception(
                cfg, self.resolved, REPO_ROOT, lambda e: self.session.on_event(e), printer)
            if why:
                self._warn(why)
            else:
                self.printer(f"perception: {self.perception.detector.weights_path.name}, "
                             f"classes checked against the object profile")
        self.hand_stage = None
        if self.perception is not None:
            from src.runtime.hand_stage import build_hand_stage

            self.hand_stage, why = build_hand_stage(cfg, REPO_ROOT, self.perception, printer)
            if why:
                self._warn(why)
            elif self.hand_stage is not None:
                self.printer("hand skeletons: MediaPipe on bare hands (own thread)")
        self.capture: VideoSource | None = None
        if self.opts.capture:
            cap_cfg = CaptureConfig.from_config(cfg)
            if self.opts.source is not None:
                cap_cfg = replace(cap_cfg, source=self.opts.source)

            self.capture = VideoSource(cap_cfg, self._on_frame, printer=printer)

        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._started_at: float | None = None
        self._protocol_mtime = self.protocol_path.stat().st_mtime
        self.events_done = threading.Event()
        if self.opts.events is None:
            self.events_done.set()

    # ------------------------------------------------------------------
    # Callbacks (other threads -- keep them short)
    # ------------------------------------------------------------------

    def _warn(self, msg: str) -> None:
        self.warnings.append(msg)
        self.printer(f"WARNING: {msg}")

    def _attest_snapshot(self, session_id: str, ts: float, extra: dict[str, Any]) -> None:
        """Downlink thread: put the sent image's sha256 INTO the hash chain,
        so the ground can prove the image is the one the system saw."""
        if session_id == self.session_id:
            self.session.note("snapshot", f"image sent to ground for log line {extra.get('for_seq')}: "
                              f"{extra.get('label')}", ts=ts, extra=extra)

    def _on_frame(self, frame: Frame) -> None:
        self.recorder.submit(frame.payload, frame.ts_monotonic)
        if self.downlink is not None:
            self.downlink.offer_frame(frame.ts_monotonic, frame.payload)
        with self._frame_lock:
            self._latest_frame = frame
        if self.perception is not None:
            self.perception.submit(frame)
        if self.hand_stage is not None:
            self.hand_stage.submit(frame)

    def latest_hand_frame(self) -> Any:
        """Skeletons + cues of the most recent hand-pose frame (GUI), or None."""
        return self.hand_stage.latest() if self.hand_stage is not None else None

    def latest_detections(self) -> tuple[int, list]:
        return self.perception.latest_detections() if self.perception else (-1, [])

    # --- rack (ArUco) geometry --------------------------------------------------

    def _geometry_status(self) -> str:
        # Also called while Session is being built (session_start is logged
        # then), before perception exists.
        perception = getattr(self, "perception", None)
        rack = perception.rack if perception else None
        return rack.geometry_status if rack is not None else "image"

    def latest_rack_markers(self) -> dict:
        return self.perception.rack_markers() if self.perception else {}

    def rack_config(self) -> Any:
        from src.perception.rack import RackConfig

        rack = self.perception.rack if self.perception else None
        return rack.cfg if rack is not None else RackConfig(enabled=False)

    def apply_rack_config(self, cfg: Any, save: bool = True, note: str | None = None) -> str | None:
        """Validate, save to configs/rack.yaml and swap in live (no restart).
        Returns an error message, or None on success."""
        from src.perception.rack import save_rack_config
        from src.runtime.perception_stage import rack_config_path

        errs = cfg.validate()
        if errs:
            return "; ".join(errs)
        if self.perception is None:
            return "perception is off (no detector) -- rack tracking runs inside it"
        if save:
            try:
                save_rack_config(cfg, rack_config_path(self.cfg, REPO_ROOT), layout_note=note)
            except Exception as exc:  # noqa: BLE001
                return f"could not save: {exc}"
        self.perception.set_rack(cfg)
        self.printer(f"rack config applied: {cfg.dictionary} ids {list(cfg.marker_ids)} "
                     f"{cfg.marker_size_mm:g} mm, layout of {len(cfg.layout)} markers")
        return None

    def autodetect_markers(self) -> list[tuple[str, list[int]]]:
        """Dictionaries that find markers in the current camera frame."""
        from src.perception.rack import autodetect_dictionary

        frame = self.latest_frame()
        return [] if frame is None else autodetect_dictionary(frame.payload)

    def start_rack_calibration(self) -> list[dict]:
        sink: list[dict] = []
        if self.perception is not None:
            self.perception.collect_markers(sink)
        return sink

    def finish_rack_calibration(self, sink: list[dict], cfg: Any) -> tuple[Any, str]:
        """Stop collecting; fit the layout for `cfg` (dictionary / size / ids
        as entered). Returns (new cfg or None, human-readable report)."""
        import math

        from src.perception.rack import calibrate_layout

        if self.perception is not None:
            self.perception.collect_markers(None)
        frames = [{i: c for i, c in f.items() if i in cfg.marker_ids} for f in sink[-300:]]
        frames = [f for f in frames if len(f) >= 2]
        if len(frames) < 5:
            return None, (f"only {len(frames)} frames showed 2+ of markers {list(cfg.marker_ids)} "
                          "together -- keep hands out of the tub and check the ArUco type / IDs")
        try:
            res = calibrate_layout(frames, cfg.marker_size_mm)
        except ValueError as exc:
            return None, str(exc)
        new = type(cfg)(**{**cfg.__dict__, "layout": res.layout})
        msg = f"{len(frames)} frames, {len(res.layout)} markers placed, RMS {res.rms_reproj_px:.2f} px"
        if res.unplaced:
            msg += f"; never seen with another marker: {res.unplaced}"
        old = self.rack_config().layout
        common = [i for i in res.layout if i in old]
        if common:
            shift = max(math.hypot(res.layout[i].x_mm - old[i].x_mm, res.layout[i].y_mm - old[i].y_mm)
                        for i in common)
            msg += f"; max change vs saved layout {shift:.1f} mm"
        if res.rms_reproj_px > cfg.max_reproj_px:
            return None, msg + " -- too inaccurate, not applied (wrong marker size? a marker not flat?)"
        return new, msg

    def _new_session(self, session_id: str | None = None) -> None:
        """A fresh engine, alert state and hash-chained log. Used at start
        and by restart_session(); capture, recording, detector and voice
        keep running across a restart."""
        sess_cfg = self.cfg.get("session") or {}
        sid = session_id or datetime.now().strftime("session_%Y%m%d_%H%M%S")
        if sid == self.session_id:  # restarted within the same second
            sid += "_r"
        self.session_id = sid
        self.log_path = self.log_dir / f"{sid}.jsonl"
        if self.downlink is not None:
            self.downlink.begin_session(sid, {
                "protocol_id": self.resolved.parsed.protocol_id,
                "title": self.resolved.parsed.raw.get("title", self.resolved.parsed.protocol_id),
                "object_profile": str(self.object_profile or self.resolved.parsed.raw.get("object_profile", "")),
                "operator": sess_cfg.get("operator")})
        self.logger = SessionLogger(self.log_path, sid,
                                    on_line=self.downlink.on_log_line if self.downlink else None)
        self._recent_events.clear()
        self._recent_speech.clear()
        worker = self.audio.worker
        self.session = Session(
            self.resolved,
            clock=self.clock,
            audio_submit=worker.submit if worker is not None else None,
            settings=AnnouncerSettings.from_config(self.cfg["audio"].get("prompts", {})),
            logger=self.logger,
            operator=sess_cfg.get("operator"),
            event_listeners=[self._on_engine_event],
            audio_listeners=[self._on_speech],
            geometry_status=self._geometry_status,
        )
        if self.downlink is not None:
            self.downlink.send_steps(sid, self.session.snapshot()["steps"])

    def restart_session(self) -> dict[str, Any]:
        """Start the experiment again from step one, as a NEW session: the
        old log gets a closing line naming the new session, is closed and
        its hash chain verified; the new one starts clean (fresh engine,
        fresh alert cooldowns, fresh perception votes). Operator authority:
        never refused. Returns the old session's summary."""
        with self._restart_lock:
            old_id, old_log, old = self.session_id, self.log_path, self.session
            snap = old.snapshot()
            new_id = datetime.now().strftime("session_%Y%m%d_%H%M%S")
            if new_id == old_id:
                new_id += "_r"
            old.retire(self.clock.now(), f"restart -> new session {new_id}")
            self.logger.close()
            chain = verify_chain(old_log)
            report = self._write_report(old_log, old.snapshot(), chain)
            if self.audio.worker is not None:
                self.audio.worker.submit([AudioRequest(kind="system", flush_all=True,
                                                       segments=(RESTARTING_TEXT,))])
            if self.perception is not None:
                self._rebuild_fusion(self.resolved)  # fresh votes: closed box, modules in
            self._new_session(new_id)
            rec = self.recorder.dir if self.recorder.active else None
            self.session.command_note(
                f"restarted from {old_id}" + (f"; video continues in {rec}" if rec else ""))
            self.printer(f"experiment restarted: {old_id} -> {self.session_id} "
                         f"(old log chain {'OK' if chain.ok else 'BROKEN'}, "
                         f"{chain.lines_checked} lines)")
            return {
                "session_id": old_id, "log": str(old_log), "log_chain_ok": chain.ok,
                "steps_done": sum(s["status"] in ("done", "confirmed") for s in snap["steps"]),
                "steps_total": sum(s["status"] != "not_applicable" for s in snap["steps"]),
                "violations": snap["violations"],
                "report": str(report) if report else None,
            }

    def _write_report(self, log_path: Path, snap: dict[str, Any], chain: Any) -> Path | None:
        """The readable report next to the log (logs/<session>.report.txt),
        generated from the log itself. A failure here must never lose the
        session: the JSONL is already safe on disk."""
        try:
            text = build_report(load_events(log_path), snap["steps"], title=snap.get("title", ""),
                                chain_ok=chain.ok, chain_lines=chain.lines_checked,
                                log_name=log_path.name)
            out = log_path.with_suffix(".report.txt")
            out.write_text(text, encoding="utf-8")
            self.last_report = out
            if self.downlink is not None:
                self.downlink.send_report(log_path.stem, text)
            return out
        except Exception as exc:  # noqa: BLE001
            self._warn(f"session report not written: {exc}")
            return None

    def _voice_restart(self) -> None:
        """Restart by voice needs the command twice within
        voice_control.restart_confirm_s (configs/runtime.yaml):
        a misheard "Hey BAS" must not throw away an experiment."""
        now = time.monotonic()
        if now < self._restart_armed_until:
            self._restart_armed_until = 0.0
            self.restart_session()
            return
        self._restart_armed_until = now + float(
            (self.cfg.get("voice_control") or {}).get("restart_confirm_s", 8.0))
        self.session.command_note("restart requested by voice, waiting for confirmation")
        if self.audio.worker is not None:
            self.audio.worker.submit([
                AudioRequest(kind="system", release=True, replay_prompt=False),
                AudioRequest(kind="system", segments=(RESTART_CONFIRM_TEXT,)),
            ])

    def restart_pending(self) -> bool:
        """A voice restart is waiting for its confirmation (GUI shows it)."""
        return time.monotonic() < self._restart_armed_until

    def _on_voice(self, parsed: Any) -> None:
        if parsed.command == "restart":
            self._armed_until = 0.0
            self.printer(f"[voice] {parsed.text!r} -> restart")
            self._voice_restart()
            return
        if parsed.command == "wake":
            self._armed_until = time.monotonic() + float(
                (self.cfg.get("voice_control") or {}).get("command_window_s", 5.0))
        else:
            self._armed_until = 0.0
        self.printer(f"[voice] {parsed.text!r} -> {parsed.command}")
        self.session.command(parsed.command)

    def _on_engine_event(self, e: EngineEvent) -> None:
        self._recent_events.append({
            "ts": e.ts_monotonic, "type": e.event_type, "step": e.step_id,
            "code": e.violation_type, "severity": e.severity, "target": e.target,
            "message": e.message, "status": e.status,
        })

    def _on_speech(self, r: AudioRequest) -> None:
        if r.segments:
            self._recent_speech.append({"ts": self.clock.now(), "kind": r.kind,
                                        "severity": r.severity, "text": r.text})

    # ------------------------------------------------------------------
    # Operator actions (GUI buttons use these; voice uses session.command)
    # ------------------------------------------------------------------

    def command(self, command: str) -> None:
        self.session.command(command)

    def latest_frame(self) -> Frame | None:
        with self._frame_lock:
            return self._latest_frame

    def status(self) -> AppStatus:
        return AppStatus(
            session_id=self.session_id,
            protocol=self.session.snapshot(),
            capture_fps=self.capture.stats.measured_fps if self.capture else 0.0,
            frame_size=self.capture.frame_size if self.capture else None,
            recording=self.recorder.active,
            stream_url=self.recorder.cfg.stream_url
            if (self.recorder.active and self.recorder.cfg.stream_enabled) else None,
            voice_control=self.listener is not None,
            listening_armed=time.monotonic() < self._armed_until,
            mic_name=self.listener.device_name if self.listener else None,
            mic_silent=bool(self.listener
                            and self.listener.mic_silent_for() > self.MIC_SILENCE_WARN_S),
            perception=self.perception is not None,
            detector_fps=self.perception.stats.detector_fps if self.perception else 0.0,
            frame_latency_ms=self.perception.stats.frame_latency_ms if self.perception else 0.0,
            perception_states=self.perception.fusion.states() if self.perception else {},
            **self._rack_status_fields(),
            **self._hand_status_fields(),
            recent_events=list(self._recent_events),
            recent_speech=list(self._recent_speech),
            warnings=list(self.warnings),
            uptime_s=0.0 if self._started_at is None else time.monotonic() - self._started_at,
            downlink=self.downlink.status() if self.downlink is not None else None,
            last_report=str(self.last_report) if self.last_report else None,
            activity=self.activity.shown if self.perception is not None else "",
        )

    @staticmethod
    def _offline_summary() -> dict[str, Any]:
        from src.runtime.offline import blocked_attempts, guard_installed

        return {"offline_guard": "on" if guard_installed() else "off",
                "offline_blocked": len(blocked_attempts())}

    def _update_activity(self) -> None:
        """Derived activity from fusion states + fingertip holding cues;
        logged on change once stable (never spoken)."""
        if self.perception is None:
            return
        from src.runtime.activity import describe, holding_roles
        from src.runtime.gui import object_names

        try:
            states = self.perception.fusion.states()
            cues = self.hand_stage.latest().cues if self.hand_stage is not None else []
            names = {k: v for k, v in object_names(self.session.snapshot()).items()}
            label = describe(states, holding_roles(cues), names, self.perception.fusion.binding.container)
        except Exception:  # noqa: BLE001 -- a display nicety must never stop the ticker
            return
        now = self.clock.now()
        if self.activity.update(now, label) is not None and self._activity_log:
            self.session.note("activity", label, ts=now)

    def _link_summary(self, side: Any) -> dict[str, Any]:
        """Downlink bytes next to what the same session costs as video: the
        PS's bandwidth argument, measured, not assumed."""
        out: dict[str, Any] = {}
        if self.downlink is not None and self.downlink.send:
            st = self.downlink.status()
            out.update(downlink_bytes=st["bytes_sent"], downlink_log_bytes=st["log_bytes"],
                       downlink_snapshot_bytes=st["snapshot_bytes"], downlink_snapshots=st["snapshots"],
                       downlink_unacked=st["unacked"])
        rec_dir = self.recorder.dir if side.t0_monotonic is not None else None
        if rec_dir is not None and Path(rec_dir).is_dir():
            out["video_bytes"] = sum(f.stat().st_size for f in Path(rec_dir).glob("*.ts"))
        return out

    def _hand_status_fields(self) -> dict[str, Any]:
        hs = self.hand_stage
        if hs is None:
            return {}
        hf = hs.latest()
        return {"hand_pose": True, "hand_fps": hs.fps, "gloved_hands": hf.gloved_hands,
                "hand_cues": [{"obj": c.obj, "state": c.state, "eta_s": c.eta_s} for c in hf.cues]}

    def _rack_status_fields(self) -> dict[str, Any]:
        rack = self.perception.rack if self.perception else None
        if rack is None:
            return {}
        pose, cfg = rack.latest, rack.cfg
        return {
            "rack_status": pose.status,
            "rack_markers_seen": pose.markers_seen,
            "rack_reproj_px": pose.fit.reproj_px if pose.fit is not None else None,
            "rack_summary": f"{cfg.dictionary} {list(cfg.marker_ids)} {cfg.marker_size_mm:g} mm",
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._started_at = time.monotonic()
        if self.downlink is not None:
            self.downlink.start()
        if self.audio.worker is not None:
            self.audio.worker.start()
            self.audio.prewarm_async(speakable_phrases(self.resolved))
        self.recorder.start()
        if self.perception is not None:
            self.perception.start()
        if self.hand_stage is not None:
            self.hand_stage.start()
        if self.capture is not None:
            self.capture.start()
        if self.listener is not None:
            try:
                self.listener.start()
                self.printer(f"[voice] listening on: {self.listener.device_name}")
            except Exception as exc:  # noqa: BLE001 -- no microphone
                self._warn(f"voice control unavailable: {exc}")
                self.listener = None
        self._spawn(self._ticker, "ticker")
        self._spawn(self._watch_protocol, "protocol_watch")
        if self.opts.events is not None:
            self._spawn(self._play_events, "scripted_events")

    def _spawn(self, fn: Callable[[], None], name: str) -> None:
        t = threading.Thread(target=fn, name=name, daemon=True)
        t.start()
        self._threads.append(t)

    MIC_SILENCE_WARN_S = 8.0

    def _ticker(self) -> None:
        mic_warned = False
        while not self._stop.wait(0.25):
            self.session.tick()
            self._update_activity()
            if (not mic_warned and self.listener is not None
                    and self.listener.mic_silent_for() > self.MIC_SILENCE_WARN_S):
                mic_warned = True
                self._warn(
                    f"microphone '{self.listener.device_name}' has sent only digital silence for "
                    f"{self.MIC_SILENCE_WARN_S:g} s -- voice commands will not work. It is probably "
                    "a virtual or muted device: pick the real mic as the Windows default input, or "
                    "set voice_control.input_device in configs/runtime.yaml."
                )

    def _watch_protocol(self) -> None:
        """Hot reload: poll the protocol file; on change, validate and swap
        in. An invalid edit is reported and the running protocol kept --
        a typo in the JSON must never take down a live session."""
        while not self._stop.wait(1.0):
            try:
                mtime = self.protocol_path.stat().st_mtime
            except OSError:
                continue
            if mtime == self._protocol_mtime:
                continue
            self._protocol_mtime = mtime
            self.reload_protocol()

    def use_protocol(self, path: Path) -> bool:
        """Switch the running session to another protocol file (the GUI
        editor's "save as new"). Same validated path as a hot reload; on
        failure the running protocol is kept."""
        path = Path(path)
        old = self.protocol_path
        self.protocol_path = path
        if not self.reload_protocol():
            self.protocol_path = old
            return False
        self._protocol_mtime = path.stat().st_mtime  # the watcher now follows the new file
        return True

    def reload_protocol(self) -> bool:
        try:
            resolved = load_validated(self.protocol_path, self.defaults_path, self.object_profile)
        except Exception as exc:  # noqa: BLE001 -- ProtocolInvalid, JSON errors, missing profile
            self._warn(f"protocol reload REJECTED, keeping the running protocol:\n{exc}")
            return False
        self.session.reload_protocol(resolved)
        self.resolved = resolved
        if self.perception is not None:
            # roles/profile may have changed: rebuild the fusion (keeps the model)
            self._rebuild_fusion(resolved)
        self.audio.prewarm_async(speakable_phrases(resolved))
        self.printer("protocol reloaded:\n" + format_resolved_report(resolved, IMPLEMENTED_CONSTRAINT_IDS))
        return True

    def _rebuild_fusion(self, resolved: ResolvedProtocol) -> None:
        from src.perception.fusion import FusionConfig, SceneFusion, binding_for, with_hand_classes

        assert self.perception is not None
        fusion = SceneFusion(
            with_hand_classes(binding_for(resolved), self.cfg),
            FusionConfig.from_config(self.cfg, resolved.timing))
        if self.perception.rack is not None:
            fusion.set_workspace(self.perception.rack.cfg)
        self.perception.fusion = fusion
        hs = getattr(self, "hand_stage", None)
        if hs is not None:  # the protocol's jars / caps may have changed
            b = fusion.binding
            objects = {role: {c} for role, c in b.modules.items()}
            objects.update({f"{role}.lid": {c} for role, c in b.lids.items()})
            hs.estimator.objects = objects

    def _play_events(self) -> None:
        """Scripted event stream, replayed in real time from start()."""
        try:
            assert self.opts.events is not None
            stream = json.loads(Path(self.opts.events).read_text(encoding="utf-8"))
            # Start the script at the first camera frame, not at start():
            # a camera takes ~1-2 s to open (measured 1.7 s), and events
            # before the first frame have no footage in the recording.
            # Real detections cannot have this problem -- they come from
            # frames.
            if self.capture is not None:
                deadline = time.monotonic() + 10.0
                while (self.latest_frame() is None and time.monotonic() < deadline
                       and not self._stop.is_set()):
                    self._stop.wait(0.05)
            t0 = time.monotonic()
            for raw in sorted(stream.get("events", []), key=lambda e: e["t"]):
                while not self._stop.is_set():
                    if self.session.paused:
                        # Paused: the scripted operator waits too.
                        t0 += 0.05
                    remaining = t0 + raw["t"] - time.monotonic()
                    if remaining <= 0:
                        break
                    self._stop.wait(min(remaining, 0.05))
                if self._stop.is_set():
                    return
                now = self.clock.now()
                if "command" in raw:
                    self.session.command(raw["command"], now)
                elif "anomaly" in raw:
                    self.session.on_event(AnomalyEvent(ts=now, kind=raw["anomaly"], label=raw.get("label")))
                else:
                    self.session.on_event(ActionEvent(
                        ts=now, action=raw["action"], target=raw["target"],
                        source=raw.get("source"), dest=raw.get("dest"), zone=raw.get("zone"),
                        confidence=raw.get("confidence", 1.0),
                    ))
        finally:
            self.events_done.set()

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        for t in self._threads:
            t.join(2.0)
        if self.listener is not None:
            self.listener.stop()
        if self.capture is not None:
            self.capture.stop()
        if self.perception is not None:
            self.perception.stop()
        if self.hand_stage is not None:
            self.hand_stage.stop()
        side = self.recorder.stop()
        if self.audio.worker is not None:
            self.audio.worker.drain(10.0)
            self.audio.worker.stop()
        self.logger.close()
        chain = verify_chain(self.log_path)
        snap = self.session.snapshot()
        report = self._write_report(self.log_path, snap, chain)
        if self.downlink is not None:
            self.downlink.stop()
        return {
            "session_id": self.session_id,
            "log": str(self.log_path),
            "log_chain_ok": chain.ok,
            "log_lines": chain.lines_checked,
            "report": str(report) if report else None,
            "steps_done": sum(s["status"] in ("done", "confirmed") for s in snap["steps"]),
            "steps_total": sum(s["status"] != "not_applicable" for s in snap["steps"]),
            "violations": snap["violations"],
            "frames_captured": self.capture.stats.frames if self.capture else 0,
            "frames_detected": self.perception.stats.frames_processed if self.perception else 0,
            "detector_fps": round(self.perception.stats.detector_fps, 1) if self.perception else 0,
            "frame_latency_ms": round(self.perception.stats.frame_latency_ms) if self.perception else 0,
            "perceived_events": self.perception.stats.events if self.perception else 0,
            "video_frames": self.recorder.stats.frames_written,
            "recording_dir": str(self.recorder.dir) if side.t0_monotonic is not None else None,
            "recording_error": side.error,
            "warnings": len(self.warnings),
            **self._link_summary(side),
            **self._offline_summary(),
            "finished_utc": datetime.now(timezone.utc).isoformat(),
        }
