#!/usr/bin/env python3
"""Image-space vs rack-space fusion on the SAME cached detections
(scripts/cache_rack_detections.py), per clip: where do the two
geometries disagree, and what does the container look like on the floor?

    python scripts/compare_geometry.py clips_Aruco/*.mp4 [--sheet]

No fixtures exist for these clips, so this is NOT an accuracy score:
it lists disagreements; --sheet writes a contact sheet of the frames at
each disagreement for a human to judge. Also measures, in floor mm, the
case_closed vs case_open footprints (does the open box include the lid
flap?) and where the container sits in each clip (zones.yaml).

Prints a summary table.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.cache_rack_detections import cache_path  # noqa: E402
from src.perception.detector import Detection, DetectorConfig  # noqa: E402
from src.perception.fusion import (  # noqa: E402
    FusionConfig,
    SceneFusion,
    binding_for,
    floor_polygon,
    polygon_area,
)
from src.perception.rack import RackTracker, load_rack_config  # noqa: E402
from src.protocol.loader import resolve  # noqa: E402
from src.runtime.config import load_runtime_config  # noqa: E402


def to_det(row: list) -> Detection:
    cls, conf, cx, cy, w, h, ang, corners = row
    return Detection(cls, conf, cx, cy, w, h, ang, tuple(tuple(p) for p in corners))


def run_clip(rows: list[dict], binding, fcfg: FusionConfig, rack_cfg) -> dict:
    img = SceneFusion(binding, replace(fcfg, geometry="image"))
    auto = SceneFusion(binding, replace(fcfg, geometry="auto"))
    tracker = RackTracker(replace(rack_cfg, enabled=False))
    tracker.cfg = rack_cfg
    ev_img, ev_auto, rack_frames = [], [], 0
    closed_polys, open_polys = [], []
    for r in rows:
        dets = [to_det(d) for d in r["dets"]]
        pose = tracker.update_markers(r["t"], {int(i): np.array(c) for i, c in r["markers"].items()})
        ev_img += [(round(r["t"], 1), e.action, e.target) for e in img.update(r["t"], dets)]
        ev_auto += [(round(r["t"], 1), e.action, e.target) for e in auto.update(r["t"], dets, pose)]
        rack_frames += auto.mode == "rack"
        if pose.fit is not None:
            for d in dets:
                if d.cls in (binding.closed_cls, binding.open_cls) and d.conf >= 0.5:
                    (closed_polys if d.cls == binding.closed_cls else open_polys).append(
                        floor_polygon(pose.fit, d.corners))
    return {"img": ev_img, "auto": ev_auto, "rack_pct": 100.0 * rack_frames / max(1, len(rows)),
            "closed": closed_polys, "open": open_polys}


def footprint_stats(polys: list[np.ndarray]) -> dict | None:
    if not polys:
        return None
    areas = [polygon_area(p) for p in polys]
    cents = np.array([p.mean(0) for p in polys])
    sides = []
    for p in polys:
        e = [float(np.linalg.norm(p[i] - p[(i + 1) % 4])) for i in range(4)]
        sides.append(sorted([(e[0] + e[2]) / 2, (e[1] + e[3]) / 2]))
    s = np.median(np.array(sides), 0)
    return {"n": len(polys), "area_cm2": float(np.median(areas)) / 100, "long_mm": float(s[1]),
            "short_mm": float(s[0]), "cx": float(np.median(cents[:, 0])), "cy": float(np.median(cents[:, 1])),
            "centre_spread_mm": float(np.median(np.linalg.norm(cents - np.median(cents, 0), axis=1)))}


def diff_events(a: list, b: list, tol: float = 1.0) -> list[str]:
    """Events in one list with no same (action, target) within tol s in the other."""
    out = []
    for name, x, y in (("image only", a, b), ("rack only", b, a)):
        for t, act, tgt in x:
            if not any(act == a2 and tgt == t2 and abs(t - s2) <= tol for s2, a2, t2 in y):
                out.append(f"{name}: {t:5.1f}s {act} {tgt}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="+", type=Path)
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--sheet", action="store_true", help="contact sheet of disagreement frames")
    args = ap.parse_args()

    rcfg = load_runtime_config()
    dcfg = DetectorConfig.from_config(rcfg)
    sess = rcfg.get("session") or {}
    resolved = resolve(REPO_ROOT / sess.get("protocol", "configs/protocols/bas_specimen_v1.json"),
                       object_profile=sess.get("object_profile"))
    binding = binding_for(resolved)
    fcfg = FusionConfig.from_config(rcfg, resolved.timing)
    rack_cfg = load_rack_config(REPO_ROOT / "configs" / "rack.yaml")

    print(f"{'clip':28s}{'rack%':>6s}{'img ev':>7s}{'rack ev':>8s}{'differ':>7s}"
          f"   closed LxW mm (n)     open LxW mm (n)   open/closed area")
    all_closed, disagreements = [], []
    for clip in args.clips:
        path = cache_path(clip, dcfg, args.stride)
        if not path.is_file():
            print(f"{clip.stem:28s}  no cache -- run scripts/cache_rack_detections.py first")
            continue
        rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l]
        res = run_clip(rows, binding, fcfg, rack_cfg)
        d = diff_events(res["img"], res["auto"])
        disagreements += [(clip, x) for x in d]
        c, o = footprint_stats(res["closed"]), footprint_stats(res["open"])
        if c:
            all_closed.append((clip.stem, c))
        cs = f"{c['long_mm']:4.0f}x{c['short_mm']:3.0f} ({c['n']:3d})" if c else f"{'-':>15s}"
        os_ = f"{o['long_mm']:4.0f}x{o['short_mm']:3.0f} ({o['n']:3d})" if o else f"{'-':>15s}"
        ratio = f"{o['area_cm2'] / c['area_cm2']:.2f}" if (c and o) else "-"
        print(f"{clip.stem:28s}{res['rack_pct']:6.0f}{len(res['img']):7d}{len(res['auto']):8d}{len(d):7d}"
              f"   {cs:>18s}   {os_:>18s}   {ratio:>6s}")

    print("\ndisagreements (event present under one geometry only, +-1 s):")
    for clip, x in disagreements:
        print(f"  {clip.stem:28s} {x}")
    if all_closed:
        cx = np.array([c["cx"] for _, c in all_closed])
        cy = np.array([c["cy"] for _, c in all_closed])
        print(f"\nclosed-container centre on the floor across {len(all_closed)} clips: "
              f"x {np.median(cx):.0f} mm (range {cx.min():.0f}..{cx.max():.0f}), "
              f"y {np.median(cy):.0f} mm (range {cy.min():.0f}..{cy.max():.0f})")

    if args.sheet and disagreements:
        import cv2

        tiles = []
        for clip, x in disagreements[:24]:
            t = float(x.split(":")[1].split("s")[0])
            cap = cv2.VideoCapture(str(clip))
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, im = cap.read()
            cap.release()
            if not ok:
                continue
            im = cv2.resize(im, (480, int(480 * im.shape[0] / im.shape[1])))
            im = cv2.copyMakeBorder(im, 0, max(0, 290 - im.shape[0]), 0, 0, cv2.BORDER_CONSTANT)[:290]
            cv2.putText(im, f"{clip.stem[:-6]} {x[:40]}", (4, 16), 0, 0.42, (0, 255, 255), 1, cv2.LINE_AA)
            tiles.append(im)
        while len(tiles) % 3:
            tiles.append(np.zeros_like(tiles[0]))
        sheet = np.vstack([np.hstack(tiles[i:i + 3]) for i in range(0, len(tiles), 3)])
        out = REPO_ROOT / "runs" / "geometry_disagreements.jpg"
        cv2.imwrite(str(out), sheet, [cv2.IMWRITE_JPEG_QUALITY, 85])
        print(f"\ncontact sheet -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
