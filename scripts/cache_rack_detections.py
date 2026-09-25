#!/usr/bin/env python3
"""Detector + ArUco markers for every processed frame of some clips,
cached as JSONL under runs/detections_rack/ -- the input for
scripts/compare_geometry.py (image-space vs rack-space fusion on the SAME
detections, no re-inference while tuning).

    python scripts/cache_rack_detections.py clips_Aruco/*.mp4 --stride 3

--stride 3 = 10 of every 30 frames, roughly the live detector rate
(same default as scripts/replay_clip.py). Prints a summary table.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.perception.detector import Detector, DetectorConfig  # noqa: E402
from src.perception.rack import detect_markers, load_rack_config, make_detector  # noqa: E402
from src.runtime.config import load_runtime_config  # noqa: E402

CACHE = REPO_ROOT / "runs" / "detections_rack"


def cache_path(clip: Path, cfg: DetectorConfig, stride: int) -> Path:
    return CACHE / f"{clip.stem}__{Path(cfg.weights).stem}_i{cfg.imgsz}_c{cfg.conf:g}_s{stride}.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="+", type=Path)
    ap.add_argument("--stride", type=int, default=3)
    args = ap.parse_args()

    import cv2

    dcfg = DetectorConfig.from_config(load_runtime_config())
    rack = load_rack_config(REPO_ROOT / "configs" / "rack.yaml")
    aru = make_detector(rack.dictionary)
    det = None
    CACHE.mkdir(parents=True, exist_ok=True)
    print(f"{'clip':30s}{'frames':>7s}{'ms/frame':>9s}  status")
    for clip in args.clips:
        out = cache_path(clip, dcfg, args.stride)
        if out.is_file():
            print(f"{clip.stem:30s}{'':>7s}{'':>9s}  cached")
            continue
        if det is None:
            det = Detector(dcfg, REPO_ROOT)
        cap = cv2.VideoCapture(str(clip))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        rows, idx, t0 = [], 0, time.perf_counter()
        while cap.grab():
            if idx % args.stride == 0:
                ok, img = cap.retrieve()
                if ok:
                    ds = det.detect(img)
                    mk = detect_markers(aru, img, rack.marker_ids)
                    rows.append({
                        "t": idx / fps,
                        "dets": [[d.cls, round(d.conf, 3), round(d.cx, 1), round(d.cy, 1), round(d.w, 1),
                                  round(d.h, 1), round(d.angle_deg, 1),
                                  [[round(v, 1) for v in p] for p in d.corners]] for d in ds],
                        "markers": {str(i): [[round(v, 2) for v in p] for p in c.tolist()] for i, c in mk.items()},
                    })
            idx += 1
        cap.release()
        out.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        ms = 1000 * (time.perf_counter() - t0) / max(1, len(rows))
        print(f"{clip.stem:30s}{len(rows):7d}{ms:9.0f}  written", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
