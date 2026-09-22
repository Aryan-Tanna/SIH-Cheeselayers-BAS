#!/usr/bin/env python3
"""Turn runs/autolabel_predictions/labels/*.txt into a sorted review
queue. Reviewing all ~1900 auto-labelled frames at once isn't
practical -- this ranks them so the highest-value review time goes
first: zero-detection frames (likely model blind spots), then lowest
mean confidence, with lid-class presence called out separately since
red_lid/yellow_lid trained weakest (smallest objects, fewest examples).
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

CLASS_ORDER = [
    "case_open", "case_closed", "red_module", "yellow_module",
    "red_lid", "yellow_lid", "hand_gloved", "hand_bare",
]
LID_CLASS_IDS = {CLASS_ORDER.index("red_lid"), CLASS_ORDER.index("yellow_lid")}


def summarize(labels_dir: Path) -> list[dict]:
    rows = []
    for txt in sorted(labels_dir.glob("*.txt")):
        lines = [l for l in txt.read_text(encoding="utf-8").splitlines() if l.strip()]
        confs = []
        classes_present = set()
        has_lid = False
        for line in lines:
            parts = line.split()
            cls_id = int(parts[0])
            conf = float(parts[-1])
            confs.append(conf)
            classes_present.add(CLASS_ORDER[cls_id])
            if cls_id in LID_CLASS_IDS:
                has_lid = True
        rows.append({
            "filename": txt.stem + ".jpg",
            "n_detections": len(lines),
            "min_conf": min(confs) if confs else 0.0,
            "mean_conf": sum(confs) / len(confs) if confs else 0.0,
            "has_lid_detection": has_lid,
            "classes": ",".join(sorted(classes_present)),
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels-dir", type=Path, default=Path("runs/autolabel_predictions/labels"))
    ap.add_argument("--out", type=Path, default=Path("runs/autolabel_predictions/review_priority.csv"))
    args = ap.parse_args()

    rows = summarize(args.labels_dir)

    # Zero-detection frames first (likely blind spots), then ascending
    # min_conf within each group -- worst single box first, not just
    # worst average, since one bad box can hide inside a good average.
    rows.sort(key=lambda r: (r["n_detections"] > 0, r["min_conf"]))

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["filename", "n_detections", "min_conf", "mean_conf", "has_lid_detection", "classes"])
        writer.writeheader()
        writer.writerows(rows)

    zero_det = sum(1 for r in rows if r["n_detections"] == 0)
    lid_rows = [r for r in rows if r["has_lid_detection"]]
    lid_rows_sorted = sorted(lid_rows, key=lambda r: r["min_conf"])

    print(f"total frames         : {len(rows)}")
    print(f"zero-detection frames: {zero_det} (top of the queue)")
    print(f"frames with a lid detection: {len(lid_rows)}")
    print(f"lowest-confidence lid frames (review these specifically):")
    for r in lid_rows_sorted[:10]:
        print(f"  {r['min_conf']:.3f}  {r['filename']}")
    print(f"\nfull sorted queue -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
