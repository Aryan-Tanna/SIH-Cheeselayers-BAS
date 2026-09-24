#!/usr/bin/env python3
"""How does the configured detector do on these clips? Measured per clip:

  inference time (mean / p95, CPU), and for every class: the share of
  processed frames with at least one detection, and its mean confidence.

Plus an annotated contact sheet per clip (12 frames, boxes drawn), so a
human can see WHAT is being missed, not just how often.

    python scripts/detector_report.py test_clips/*.mp4
    python scripts/detector_report.py clip.mp4 --stride 1 --weights models/other.pt

"Share of frames with a detection" is NOT recall -- there are no labels
for these clips, and an object may genuinely be absent or hidden. Read it
alongside the contact sheet. Prints a summary table on completion.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.perception.detector import Detector, DetectorConfig  # noqa: E402
from src.runtime.config import load_runtime_config  # noqa: E402

COLOURS = {  # BGR
    "case_open": (255, 255, 255), "case_closed": (180, 180, 180),
    "red_module": (60, 60, 255), "yellow_module": (0, 220, 255),
    "red_lid": (180, 0, 255), "yellow_lid": (0, 140, 255),
    "hand_bare": (0, 200, 0), "hand_gloved": (255, 200, 0),
}


def annotate(img, dets):
    import cv2
    import numpy as np

    out = img.copy()
    for d in dets:
        c = COLOURS.get(d.cls, (255, 0, 255))
        pts = np.array(d.corners, dtype=np.int32).reshape(-1, 1, 2)
        cv2.polylines(out, [pts], True, c, 4)
        x, y = int(min(p[0] for p in d.corners)), int(min(p[1] for p in d.corners))
        cv2.putText(out, f"{d.cls} {d.conf:.2f}", (x, max(30, y - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, c, 3)
    return out


def main() -> int:
    import cv2
    import numpy as np

    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="+", type=Path)
    ap.add_argument("--stride", type=int, default=2, help="process every Nth frame")
    ap.add_argument("--weights", default=None)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "runs" / "detector_report")
    args = ap.parse_args()

    cfg = DetectorConfig.from_config(load_runtime_config())
    if args.weights:
        cfg = DetectorConfig(weights=args.weights, conf=cfg.conf, iou=cfg.iou, imgsz=cfg.imgsz)
    det = Detector(cfg, REPO_ROOT)
    classes = sorted(det.names.values())
    args.out.mkdir(parents=True, exist_ok=True)
    print(f"weights {det.weights_path.name}  conf>={cfg.conf}  imgsz {cfg.imgsz}  stride {args.stride}")

    rows = []
    for clip in args.clips:
        cap = cv2.VideoCapture(str(clip))
        n_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        sheet_at = set(np.linspace(0, max(0, n_total - 1), 12).astype(int).tolist())
        seen = {c: 0 for c in classes}
        confs = {c: [] for c in classes}
        times, tiles, processed, idx = [], [], 0, 0
        det.detect(np.zeros((64, 64, 3), np.uint8))  # warm-up, not timed
        while True:
            ok, img = cap.read()
            if not ok:
                break
            want_tile = idx in sheet_at
            if idx % args.stride == 0 or want_tile:
                dets = det.detect(img)
                if idx % args.stride == 0:
                    times.append(det.last_inference_ms)
                    processed += 1
                    for c in {d.cls for d in dets}:
                        seen[c] += 1
                    for d in dets:
                        confs[d.cls].append(d.conf)
                if want_tile:
                    t = cv2.resize(annotate(img, dets), (640, 360))
                    cv2.putText(t, f"{clip.stem} {idx / 30:.1f}s", (8, 28),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
                    tiles.append(t)
            idx += 1
        cap.release()
        while len(tiles) < 12:
            tiles.append(np.zeros((360, 640, 3), np.uint8))
        grid = np.vstack([np.hstack(tiles[r * 4:(r + 1) * 4]) for r in range(3)])
        cv2.imwrite(str(args.out / f"{clip.stem}_detections.jpg"), grid, [cv2.IMWRITE_JPEG_QUALITY, 80])
        p95 = sorted(times)[int(0.95 * (len(times) - 1))] if times else 0.0
        rows.append((clip.stem, processed, statistics.mean(times) if times else 0.0, p95,
                     {c: (100.0 * seen[c] / max(1, processed),
                          statistics.mean(confs[c]) if confs[c] else 0.0) for c in classes}))
        print(f"  {clip.stem}: {processed} frames processed")

    print("\n" + "-" * 110)
    short = {c: c.replace("_module", "").replace("case_", "case:").replace("hand_", "hand:") for c in classes}
    print(f"{'clip':10s} {'frames':>6s} {'ms mean':>8s} {'ms p95':>7s}  " + " ".join(f"{short[c]:>13s}" for c in classes))
    for name, n, mean_ms, p95, per in rows:
        cells = " ".join(f"{per[c][0]:5.0f}% @{per[c][1]:.2f}" if per[c][0] else f"{'-':>13s}" for c in classes)
        print(f"{name:10s} {n:6d} {mean_ms:8.1f} {p95:7.1f}  {cells}")
    print("cells: % of processed frames with >=1 detection of the class @ mean confidence")
    print(f"sheets: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
