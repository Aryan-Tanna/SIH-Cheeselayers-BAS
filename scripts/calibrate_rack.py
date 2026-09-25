#!/usr/bin/env python3
"""Calibrate the ArUco marker layout (where each marker sits on the rig
floor) from video, check it on clips it was NOT fitted on, and write
configs/rack.yaml.

    python scripts/calibrate_rack.py --clips clips_Aruco
    python scripts/calibrate_rack.py --clips clips_Aruco --no-write   # report only

Holdout: the layout is fitted on every other clip and scored on the rest
(pixel reprojection error + how often the rack is known), then refitted
on all clips for the config. A layout that only fits the clips it was
made from would show up as a gap between the two scores.

Prints a summary table on completion.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.perception.rack import (  # noqa: E402
    DEFAULT_RACK_CONFIG_PATH,
    RackConfig,
    RackTracker,
    calibrate_layout,
    detect_markers,
    fit_rack,
    load_rack_config,
    make_detector,
    save_rack_config,
)


def observe_clip(path: Path, detector, ids: tuple[int, ...], every: int) -> list[tuple[float, dict]]:
    import cv2

    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    out, k = [], 0
    while cap.grab():
        if k % every == 0:
            ok, img = cap.retrieve()
            if ok:
                out.append((k / fps, detect_markers(detector, img, ids)))
        k += 1
    cap.release()
    return out


def score(obs: list[tuple[float, dict]], cfg: RackConfig) -> dict:
    tr = RackTracker(RackConfig(**{**cfg.__dict__, "enabled": False}))  # no detector needed
    tr.cfg = cfg
    n = len(obs)
    counts = {"ok": 0, "held": 0, "none": 0}
    errs, gap, longest = [], 0.0, 0.0
    last_t = None
    for t, m in obs:
        pose = tr.update_markers(t, m)
        counts[pose.status] = counts.get(pose.status, 0) + 1
        if pose.status == "ok":
            if len(pose.fit.ids_used) >= 2:
                errs.append(pose.fit.reproj_px)
            gap = 0.0
        elif last_t is not None:
            gap += t - last_t
            longest = max(longest, gap)
        last_t = t
    return {"n": n, **{k: 100.0 * v / max(n, 1) for k, v in counts.items()},
            "reproj_px": float(np.median(errs)) if errs else float("nan"),
            "longest_gap_s": longest}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", type=Path, required=True, help="folder of .mp4 clips of ONE fixed rig")
    ap.add_argument("--config", type=Path, default=DEFAULT_RACK_CONFIG_PATH)
    ap.add_argument("--size-mm", type=float, default=None, help="override marker size")
    ap.add_argument("--dictionary", default=None)
    ap.add_argument("--ids", default=None, help="comma list, e.g. 1,2,3,4")
    ap.add_argument("--every", type=int, default=6, help="use every Nth frame (6 = 5 fps at 30 fps)")
    ap.add_argument("--cache", type=Path, default=Path("runs/rack_observations.json"))
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    base = load_rack_config(args.config) if args.config.exists() else RackConfig()
    cfg = RackConfig(
        enabled=True,
        dictionary=args.dictionary or base.dictionary,
        marker_size_mm=args.size_mm or base.marker_size_mm,
        marker_ids=tuple(int(i) for i in args.ids.split(",")) if args.ids else base.marker_ids,
        hold_s=base.hold_s, max_reproj_px=base.max_reproj_px, ransac_px=base.ransac_px,
    )
    errs = cfg.validate()
    if errs:
        print("config invalid: " + "; ".join(errs))
        return 1

    clips = sorted(args.clips.glob("*.mp4"), key=lambda p: (len(p.stem), p.stem))
    key = {"dictionary": cfg.dictionary, "ids": list(cfg.marker_ids), "every": args.every}
    cache = json.loads(args.cache.read_text()) if args.cache.exists() else {}
    if cache.get("key") != key:
        cache = {"key": key, "clips": {}}
    det = make_detector(cfg.dictionary)
    obs: dict[str, list[tuple[float, dict]]] = {}
    for c in clips:
        if c.stem not in cache["clips"]:
            print(f"detecting markers: {c.name}", flush=True)
            cache["clips"][c.stem] = [(t, {str(i): v.tolist() for i, v in m.items()})
                                      for t, m in observe_clip(c, det, cfg.marker_ids, args.every)]
        obs[c.stem] = [(t, {int(i): np.array(v) for i, v in m.items()}) for t, m in cache["clips"][c.stem]]
    args.cache.parent.mkdir(parents=True, exist_ok=True)
    args.cache.write_text(json.dumps(cache))

    names = list(obs)
    fit_set, hold_set = names[0::2], names[1::2]
    frames = lambda ns: [m for n in ns for _, m in obs[n]]  # noqa: E731
    res_half = calibrate_layout(frames(fit_set), cfg.marker_size_mm)
    cfg_half = RackConfig(**{**cfg.__dict__, "layout": res_half.layout})
    res_all = calibrate_layout(frames(names), cfg.marker_size_mm)
    cfg_all = RackConfig(**{**cfg.__dict__, "layout": res_all.layout})

    print(f"\n{'clip':28s}{'set':>6s}{'frames':>7s}{'ok%':>6s}{'held%':>7s}{'none%':>7s}"
          f"{'reproj px':>10s}{'gap s':>7s}")
    rows = []
    for n in names:
        s = score(obs[n], cfg_half)
        rows.append((n in hold_set, s))
        print(f"{n:28s}{'HOLD' if n in hold_set else 'fit':>6s}{s['n']:7d}{s['ok']:6.0f}{s['held']:7.0f}"
              f"{s['none']:7.0f}{s['reproj_px']:10.2f}{s['longest_gap_s']:7.1f}")
    for label, flag in (("fit clips", False), ("HELD-OUT clips", True)):
        ss = [s for h, s in rows if h == flag]
        print(f"{label:>34s}: rack known (ok+held) {np.mean([s['ok'] + s['held'] for s in ss]):5.1f}% | "
              f"median reproj {np.nanmedian([s['reproj_px'] for s in ss]):.2f} px | "
              f"longest gap {max(s['longest_gap_s'] for s in ss):.1f} s")

    print(f"\nlayout (all {len(names)} clips, {res_all.frames_used} frames with >=2 markers, "
          f"RMS {res_all.rms_reproj_px:.2f} px; half-fit RMS {res_half.rms_reproj_px:.2f} px):")
    for i, p in sorted(res_all.layout.items()):
        h = res_half.layout.get(i)
        d = math.hypot(p.x_mm - h.x_mm, p.y_mm - h.y_mm) if h else float("nan")
        print(f"  ID{i}: x={p.x_mm:8.1f} y={p.y_mm:8.1f} mm  angle={p.angle_deg:6.1f} deg"
              f"   (half-fit differs by {d:.1f} mm)")
    ids = sorted(res_all.layout)
    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            pa, pb = res_all.layout[ids[a]], res_all.layout[ids[b]]
            print(f"  ID{ids[a]}-ID{ids[b]}: {math.hypot(pa.x_mm - pb.x_mm, pa.y_mm - pb.y_mm):6.1f} mm", end="")
        print()
    if res_all.unplaced:
        print(f"  never seen with another marker (not placed): {res_all.unplaced}")

    if args.no_write:
        print("\n--no-write: config not changed")
    else:
        note = (f"calibrated by scripts/calibrate_rack.py from {args.clips} ({len(names)} clips, "
                f"RMS {res_all.rms_reproj_px:.2f} px)")
        save_rack_config(cfg_all, args.config, layout_note=note)
        print(f"\nwrote {args.config}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
