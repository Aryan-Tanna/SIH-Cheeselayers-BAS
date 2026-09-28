#!/usr/bin/env python3
"""Score the hand-skeleton cues (src/perception/hand_pose.py) against the
physical-action fixtures (harness/perception_fixtures):

  prediction  for each true pickup (remove_from jar R at time T): did
              "reaching for R" come on in [T-3 s, T+0.3 s]? lead = T - onset.
  false reach reaching onsets for R followed by neither a pickup of R nor
              "holding R" within 3 s.
  holding     share of time "holding R" while R is truly out of the box
              (remove -> return), and while R sits in the box.
  skeleton    share of the detector's bare-hand boxes with a skeleton.

    python scripts/score_hand_cues.py --split tune
    python scripts/score_hand_cues.py --split tune --set perception.hand_pose.input_width=480

Tune ONLY on "split": "tune". Uses the cached detections (replay_clip.py)
and runs MediaPipe on the same frames (every 3rd = the live detector rate).
"""

from __future__ import annotations

import argparse
import copy
import json
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.replay_clip import detections_for, to_detection  # noqa: E402
from scripts.score_perception import FIXTURES, set_path  # noqa: E402
from src.perception.detector import DetectorConfig  # noqa: E402
from src.perception.hand_pose import HandPoseConfig, HandPoseEstimator  # noqa: E402
from src.runtime.config import load_runtime_config  # noqa: E402

HANDS = {"hand_bare", "hand_gloved"}
OBJECTS = {"module_a": {"red_module"}, "module_b": {"yellow_module"}}


def run(fx: dict, runtime: dict, stride: int) -> dict:
    import bisect

    import cv2

    cfg = HandPoseConfig.from_config(runtime) or HandPoseConfig()
    est = HandPoseEstimator(cfg, REPO_ROOT, HANDS, OBJECTS)
    rows = [r for r in detections_for(REPO_ROOT / fx["clip_path"], DetectorConfig.from_config(runtime), stride, {})
            if "dets" in r]
    ts = [r["t"] for r in rows]
    cap = cv2.VideoCapture(str(REPO_ROOT / fx["clip_path"]))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    timeline, n_bare, n_skel, ms, n_stray = [], 0, 0, [], 0
    idx = 0
    while True:
        ok, bgr = cap.read()
        if not ok:
            break
        if idx % stride == 0:
            t = idx / fps
            j = bisect.bisect_left(ts, t)
            j = min((c for c in (j - 1, j) if 0 <= c < len(ts)), key=lambda c: abs(ts[c] - t), default=None)
            dets = [to_detection(d) for d in rows[j]["dets"]] if j is not None and abs(ts[j] - t) < 0.05 else []
            hf = est.process(bgr, t, dets)
            if hf.ms:
                ms.append(hf.ms)
            bare = [d for d in dets if d.cls == "hand_bare"]
            n_bare += len(bare)
            n_skel += min(len(bare), len(hf.poses))
            hand_boxes = [d.aabb for d in dets if d.cls in HANDS]
            n_stray += sum(1 for p in hf.poses if not any(sum(b[0] <= x <= b[2] and b[1] <= y <= b[3] for x, y in p.landmarks) >= 11 for b in hand_boxes))
            timeline.append((t, {(c.obj, c.state): c.eta_s for c in hf.cues}))
        idx += 1
    est.close()
    return {"timeline": timeline, "n_bare": n_bare, "n_skel": n_skel, "ms": ms, "n_stray": n_stray}


def score(fx: dict, res: dict) -> dict:
    tl = res["timeline"]
    picks = [(e["t"], e["target"]) for e in fx["events"] if e["action"] == "remove_from"]
    out = {"picks": len(picks), "hit": 0, "leads": [], "false": 0, "onsets": 0,
           "held_on": [0, 0], "in_on": [0, 0]}
    for obj in OBJECTS:
        prev = False
        onsets, hold_starts = [], []
        prev_hold = False
        for t, cues in tl:
            r, h = (obj, "reaching") in cues, (obj, "holding") in cues
            if r and not prev:
                onsets.append(t)
            if h and not prev_hold:
                hold_starts.append(t)
            prev, prev_hold = r, h
        out["onsets"] += len(onsets)
        mine = [t for t, o in picks if o == obj]
        for T in mine:
            pre = [o for o in onsets if T - 3 <= o <= T + 0.3]
            if pre:
                out["hit"] += 1
                out["leads"].append(T - pre[0])
        for o in onsets:
            if not any(0 <= T - o <= 3 for T in mine) and not any(0 <= h - o <= 3 for h in hold_starts):
                out["false"] += 1
        # truly out of the box: remove -> next return of this jar
        ev = sorted((e["t"], e["action"]) for e in fx["events"] if e["target"] == obj
                    and e["action"] in ("remove_from", "place_into"))
        spans, start = [], None
        for t, a in ev:
            if a == "remove_from":
                start = t
            elif start is not None:
                spans.append((start, t))
                start = None
        for t, cues in tl:
            held = any(a <= t <= b for a, b in spans)
            k = "held_on" if held else "in_on"
            out[k][0] += (obj, "holding") in cues
            out[k][1] += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=("tune", "held_out", "all"), default="tune")
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    args = ap.parse_args()
    runtime = copy.deepcopy(load_runtime_config())
    for s in args.set:
        k, _, v = s.partition("=")
        set_path(runtime, k, v)
    tot = {"picks": 0, "hit": 0, "leads": [], "false": 0, "onsets": 0, "held_on": [0, 0], "in_on": [0, 0]}
    ms_all, bare, skel, stray = [], 0, 0, 0
    print(f"{'clip':26s} {'split':9s} {'skeleton':>8s} {'predicted':>9s} {'lead':>6s} {'false':>5s} "
          f"{'holding: out':>12s} {'in box':>7s}")
    for path in sorted(FIXTURES.glob("*.json")):
        fx = json.loads(path.read_text(encoding="utf-8"))
        if args.split != "all" and fx["split"] != args.split:
            continue
        res = run(fx, runtime, args.stride)
        s = score(fx, res)
        for k in ("picks", "hit", "false", "onsets"):
            tot[k] += s[k]
        tot["leads"] += s["leads"]
        for k in ("held_on", "in_on"):
            tot[k][0] += s[k][0]
            tot[k][1] += s[k][1]
        ms_all += res["ms"]
        bare += res["n_bare"]
        skel += res["n_skel"]
        stray += res["n_stray"]
        lead = f"{statistics.median(s['leads']):.2f}s" if s["leads"] else "-"
        print(f"{fx['clip_id']:26s} {fx['split']:9s} {res['n_skel'] / max(res['n_bare'], 1):8.0%} "
              f"{s['hit']:>4d}/{s['picks']:<4d} {lead:>6s} {s['false']:5d} "
              f"{s['held_on'][0] / max(s['held_on'][1], 1):12.0%} {s['in_on'][0] / max(s['in_on'][1], 1):7.0%}",
              flush=True)
    lead = f"{statistics.median(tot['leads']):.2f} s" if tot["leads"] else "-"
    print(f"\nskeleton on {skel / max(bare, 1):.0%} of bare hands | pickups predicted {tot['hit']}/{tot['picks']}, "
          f"median lead {lead} | false reach {tot['false']} of {tot['onsets']} onsets | holding "
          f"{tot['held_on'][0] / max(tot['held_on'][1], 1):.0%} while out, "
          f"{tot['in_on'][0] / max(tot['in_on'][1], 1):.0%} while in the box | MediaPipe "
          f"{statistics.median(ms_all) if ms_all else 0:.1f} ms/frame (p50) | skeletons off any detector hand: {stray}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
