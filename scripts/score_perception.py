#!/usr/bin/env python3
"""Score PERCEPTION (detector + fusion) against physical-action timelines,
independent of any protocol: harness/perception_fixtures/<clip>.json lists
what physically happened (box open/close, jar out/in, cap off/on) with
times. Clips need not follow the protocol, so any clip can be a fixture.

    python scripts/score_perception.py                     # all fixtures
    python scripts/score_perception.py --split tune        # tune on these only
    python scripts/score_perception.py --set perception.kinematics.gate_on_release=true

Per clip: true events found (same action + object within tolerance),
missed, EXTRA events (flicker, an early "returned" while the jar hovers),
and the median delay from the true time to the event -- the latency the
operator actually gets. Tune ONLY on "split": "tune"; held_out is reported
separately (CLAUDE.md anti-overfitting rules). Detections are cached per
clip/weights/stride by scripts/replay_clip.py's cache.
"""

from __future__ import annotations

import argparse
import copy
import json
import statistics
import sys
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.replay_clip import detections_for, markers_for, to_detection  # noqa: E402
from src.perception.detector import DetectorConfig  # noqa: E402
from src.perception.fusion import FusionConfig, SceneFusion, binding_for, with_hand_classes  # noqa: E402
from src.protocol.events import ActionEvent  # noqa: E402
from src.protocol.loader import resolve  # noqa: E402
from src.runtime.config import load_runtime_config  # noqa: E402

FIXTURES = REPO_ROOT / "harness" / "perception_fixtures"


def set_path(cfg: dict, dotted: str, raw: str) -> None:
    keys = dotted.split(".")
    node = cfg
    for k in keys[:-1]:
        node = node.setdefault(k, {})
    val: object = raw
    for conv in (json.loads,):
        try:
            val = conv(raw)
        except ValueError:
            pass
    node[keys[-1]] = val


def run_clip(fx: dict, runtime: dict, stride: int, holder: dict) -> list[dict]:
    resolved = resolve(REPO_ROOT / "configs/protocols/bas_specimen_v1.json", object_profile=fx["object_profile"])
    frames = detections_for(REPO_ROOT / fx["clip_path"], DetectorConfig.from_config(runtime), stride, holder)
    fcfg = FusionConfig.from_config(runtime, resolved.timing)
    fusion = SceneFusion(with_hand_classes(binding_for(resolved), runtime), fcfg)
    tracker = marks = None
    if fcfg.geometry == "auto":
        import numpy as np

        from src.perception.rack import RackTracker, load_rack_config

        rack_cfg = load_rack_config(REPO_ROOT / (runtime.get("perception") or {}).get("rack_config", "configs/rack.yaml"))
        tracker = RackTracker(replace(rack_cfg, enabled=False))
        tracker.cfg = rack_cfg
        marks = markers_for(REPO_ROOT / fx["clip_path"], stride, rack_cfg)
    out = []
    for i, fr in enumerate(frames):
        pose = None
        if tracker is not None and i < len(marks):
            pose = tracker.update_markers(fr["t"], {int(k): np.array(v) for k, v in marks[i].items()})
        for e in fusion.update(fr["t"], [to_detection(r) for r in fr["dets"]], pose):
            if isinstance(e, ActionEvent) and not e.target.endswith(".lid"):
                out.append({"t": e.ts, "action": e.action, "target": e.target})
    return out


def score(truth: list[dict], got: list[dict], tol: float, rough_tol: float) -> dict:
    """Greedy in time order: each true event takes the nearest unused event
    of the same action+object within its tolerance."""
    used: set[int] = set()
    found, missed, delays = [], [], []
    for t in sorted(truth, key=lambda e: e["t"]):
        lim = rough_tol if t.get("conf") == "rough" else tol
        best = None
        for i, g in enumerate(got):
            if i in used or g["action"] != t["action"] or g["target"] != t["target"]:
                continue
            d = g["t"] - t["t"]
            if abs(d) <= lim and (best is None or abs(d) < abs(best[1])):
                best = (i, d)
        if best is None:
            missed.append(t)
        else:
            used.add(best[0])
            found.append(t)
            delays.append(best[1])
    extra = [g for i, g in enumerate(got) if i not in used]
    return {"found": found, "missed": missed, "extra": extra, "delays": delays}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=("tune", "held_out", "all"), default="all")
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="override configs/runtime.yaml, e.g. perception.module_min_hold_s=0.5")
    ap.add_argument("--details", action="store_true", help="list missed and extra events")
    args = ap.parse_args()

    runtime = copy.deepcopy(load_runtime_config())
    for s in args.set:
        k, _, v = s.partition("=")
        set_path(runtime, k, v)
    holder: dict = {}
    rows = []
    for path in sorted(FIXTURES.glob("*.json")):
        fx = json.loads(path.read_text(encoding="utf-8"))
        if args.split != "all" and fx["split"] != args.split:
            continue
        r = score(fx["events"], run_clip(fx, runtime, args.stride, holder),
                  fx.get("tolerance_s", 1.5), fx.get("rough_tolerance_s", 2.5))
        rows.append((fx, r))
        if args.details:
            for m in r["missed"]:
                print(f"  {fx['clip_id']}: MISSED {m['t']:5.1f}s {m['action']} {m['target']}")
            for e in r["extra"]:
                print(f"  {fx['clip_id']}: extra  {e['t']:5.1f}s {e['action']} {e['target']}")

    print(f"\n{'clip':26s} {'split':9s} {'verified':8s} {'found':>7s} {'missed':>6s} {'extra':>5s} {'delay p50':>9s}")
    for fx, r in rows:
        n = len(fx["events"])
        d = f"{statistics.median(r['delays']):+.2f}s" if r["delays"] else "-"
        print(f"{fx['clip_id']:26s} {fx['split']:9s} {str(fx['verified']):8s} {len(r['found']):3d}/{n:<3d} "
              f"{len(r['missed']):6d} {len(r['extra']):5d} {d:>9s}")
    for split in ("tune", "held_out"):
        sel = [r for fx, r in rows if fx["split"] == split]
        if sel:
            n = sum(len(r["found"]) + len(r["missed"]) for r in sel)
            dl = [d for r in sel for d in r["delays"]]
            print(f"{split:9s}: found {sum(len(r['found']) for r in sel)}/{n}, extra "
                  f"{sum(len(r['extra']) for r in sel)}, delay p50 "
                  f"{statistics.median(dl):+.2f}s" if dl else f"{split}: nothing found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
