#!/usr/bin/env python3
"""Real clip -> detector -> fusion -> engine -> alerts, scored against a
hand-written timeline (harness/clip_fixtures/<clip>.json) with the SAME
matching as the synthetic harness (harness/replay.py).

    python scripts/replay_clip.py test_clips/*.mp4
    python scripts/replay_clip.py test_clips/train*.mp4 --stride 2
    python scripts/replay_clip.py test_clips/test2.mp4 --show-events

Detections are cached per (clip, weights, imgsz, conf, stride) under
runs/detections/, so re-tuning fusion (configs/runtime.yaml `perception`)
re-scores in seconds. A new model = new cache, automatically.

--stride 3 (default) processes 10 of every 30 frames: roughly the rate
the live detector sustains on a laptop CPU (measured ~95-105 ms per
1080p frame), so debounce timing matches what runs live.

Tune ONLY on clips whose fixture says "split": "tune". The held-out clips
are reported separately; a gap between the two is the overfitting signal
(CLAUDE.md anti-overfitting rules). Prints a summary table.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from harness.replay import format_result, run_replay  # noqa: E402
from src.perception.detector import Detection, Detector, DetectorConfig, required_classes  # noqa: E402
from src.perception.fusion import FusionConfig, SceneFusion, binding_for, with_hand_classes  # noqa: E402
from src.protocol.events import StateEvent  # noqa: E402
from src.protocol.loader import resolve  # noqa: E402
from src.runtime.config import load_runtime_config  # noqa: E402

FIXTURES = REPO_ROOT / "harness" / "clip_fixtures"
CACHE = REPO_ROOT / "runs" / "detections"


def detections_for(clip: Path, cfg: DetectorConfig, stride: int, det_holder: dict) -> list[dict]:
    key = f"{clip.stem}__{Path(cfg.weights).stem}_i{cfg.imgsz}_c{cfg.conf:g}_s{stride}.jsonl"
    path = CACHE / key
    if path.is_file():
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l]
    import cv2

    if "det" not in det_holder:
        det_holder["det"] = Detector(cfg, REPO_ROOT)
    det = det_holder["det"]
    cap = cv2.VideoCapture(str(clip))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    rows, idx = [], 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        if idx % stride == 0:
            ds = det.detect(img)
            rows.append({"t": idx / fps, "ms": round(det.last_inference_ms, 1),
                         "dets": [[d.cls, round(d.conf, 3), round(d.cx, 1), round(d.cy, 1),
                                   round(d.w, 1), round(d.h, 1), round(d.angle_deg, 1),
                                   [list(map(lambda v: round(v, 1), p)) for p in d.corners]]
                                  for d in ds]})
        idx += 1
    cap.release()
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return rows


def markers_for(clip: Path, stride: int, rack_cfg) -> list[dict]:
    """ArUco markers per processed frame (same frames as detections_for),
    cached next to the detections -- only needed for --geometry auto."""
    key = f"{clip.stem}__markers_{rack_cfg.dictionary}_s{stride}.jsonl"
    path = CACHE / key
    if path.is_file():
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l]
    import cv2

    from src.perception.rack import detect_markers, make_detector

    det = make_detector(rack_cfg.dictionary)
    cap = cv2.VideoCapture(str(clip))
    rows, idx = [], 0
    while cap.grab():
        if idx % stride == 0:
            ok, img = cap.retrieve()
            mk = detect_markers(det, img, rack_cfg.marker_ids) if ok else {}
            rows.append({str(i): c.tolist() for i, c in mk.items()})
        idx += 1
    cap.release()
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return rows


def to_detection(row: list) -> Detection:
    cls, conf, cx, cy, w, h, ang, corners = row
    return Detection(cls, conf, cx, cy, w, h, ang, tuple(tuple(p) for p in corners))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="+", type=Path)
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--show-events", action="store_true")
    ap.add_argument("--geometry", choices=("config", "image", "auto"), default="config",
                    help="containment geometry (default: configs/runtime.yaml perception.geometry); "
                         "auto = rack space from ArUco markers where visible")
    args = ap.parse_args()

    runtime = load_runtime_config()
    dcfg = DetectorConfig.from_config(runtime)
    holder: dict = {}
    rows_out = []
    for clip in args.clips:
        fx_path = FIXTURES / f"{clip.stem}.json"
        fixture = json.loads(fx_path.read_text(encoding="utf-8")) if fx_path.is_file() else None
        profile = (fixture or {}).get("object_profile")
        resolved = resolve(REPO_ROOT / "configs/protocols/bas_specimen_v1.json", object_profile=profile)
        if "det" not in holder:
            holder["det"] = Detector(dcfg, REPO_ROOT)  # also used to fill the cache
        missing = required_classes(resolved.parsed.object_profile) - set(holder["det"].names.values())
        if missing:
            print(f"{clip.stem}: model lacks {sorted(missing)}")
            return 1
        frames = detections_for(clip, dcfg, args.stride, holder)
        fcfg = FusionConfig.from_config(runtime, resolved.timing)
        if args.geometry != "config":
            fcfg = replace(fcfg, geometry=args.geometry)
        fusion = SceneFusion(with_hand_classes(binding_for(resolved), runtime), fcfg)
        tracker = None
        if fcfg.geometry == "auto":
            import numpy as np

            from src.perception.rack import RackTracker, load_rack_config

            rack_cfg = load_rack_config(REPO_ROOT / (runtime.get("perception") or {}).get(
                "rack_config", "configs/rack.yaml"))
            tracker = RackTracker(replace(rack_cfg, enabled=False))
            tracker.cfg = rack_cfg
            marks = markers_for(clip, args.stride, rack_cfg)
        events = []
        for i, fr in enumerate(frames):
            pose = None
            if tracker is not None and i < len(marks):
                pose = tracker.update_markers(fr["t"], {int(k): np.array(v) for k, v in marks[i].items()})
            for e in fusion.update(fr["t"], [to_detection(r) for r in fr["dets"]], pose):
                if isinstance(e, StateEvent):  # operator presence (hands in view)
                    events.append({"t": round(e.ts, 3), "state": e.key, "value": e.value})
                    continue
                ev = {"t": round(e.ts, 3), "action": e.action, "target": e.target,
                      "confidence": round(e.confidence, 3)}
                for k in ("source", "dest", "zone"):
                    if getattr(e, k):
                        ev[k] = getattr(e, k)
                events.append(ev)
        duration = frames[-1]["t"] if frames else 0.0
        stream = {"clip_id": clip.stem, "protocol_id": "bas_specimen_v1",
                  "object_profile": profile, "events": events, "clip_duration_s": duration}
        result = run_replay(stream, fixture)
        ms = sorted(f["ms"] for f in frames)
        print(format_result(result))
        if args.show_events:
            for ev in events:
                if "state" in ev:
                    print(f"      {ev['t']:6.2f}s  {ev['state']} = {ev['value']}")
                else:
                    print(f"      {ev['t']:6.2f}s  {ev['action']:12s} {ev['target']}")
        split = (fixture or {}).get("split", "-")
        exp = [e for e in (fixture or {}).get("expected_events", [])]
        found = len(exp) - result.missed_violations - sum(
            1 for m in result.mismatches if m.kind == "missing" and "step_complete" in m.detail)
        rows_out.append((clip.stem, split, len(frames), ms[len(ms) // 2] if ms else 0,
                         len(events), found, len(exp), result.passed))

    print("\n" + "-" * 84)
    print(f"{'clip':8s} {'split':9s} {'frames':>6s} {'ms p50':>7s} {'events':>7s} "
          f"{'expected found':>15s}  result")
    for name, split, n, ms, ne, found, nexp, passed in rows_out:
        res = "SMOKE" if passed is None else ("PASS" if passed else "FAIL")
        print(f"{name:8s} {split:9s} {n:6d} {ms:7.1f} {ne:7d} {found:>7d}/{nexp:<7d}  {res}")
    for split in ("tune", "held_out"):
        sel = [r for r in rows_out if r[1] == split]
        if sel:
            print(f"{split:9s}: {sum(r[5] for r in sel)}/{sum(r[6] for r in sel)} expected events found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
