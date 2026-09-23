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


def summarize(labels_dir: Path, focus: set[str] | None = None) -> list[dict]:
    focus = focus or set()
    rows = []
    for txt in sorted(labels_dir.glob("*.txt")):
        lines = [l for l in txt.read_text(encoding="utf-8").splitlines() if l.strip()]
        confs = []
        classes_present = set()
        has_lid = False
        focus_confs = []
        for line in lines:
            parts = line.split()
            cls_id = int(parts[0])
            conf = float(parts[-1])
            confs.append(conf)
            classes_present.add(CLASS_ORDER[cls_id])
            if CLASS_ORDER[cls_id] in focus:
                focus_confs.append(conf)
            if cls_id in LID_CLASS_IDS:
                has_lid = True
        rows.append({
            "filename": txt.stem + ".jpg",
            "n_detections": len(lines),
            "min_conf": min(confs) if confs else 0.0,
            "mean_conf": sum(confs) / len(confs) if confs else 0.0,
            "has_lid_detection": has_lid,
            "classes": ",".join(sorted(classes_present)),
            "focus_classes": ",".join(sorted(classes_present & focus)),
            "focus_min_conf": min(focus_confs) if focus_confs else "",
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels-dir", type=Path, default=Path("runs/autolabel_predictions/labels"))
    ap.add_argument("--out", type=Path, default=Path("runs/autolabel_predictions/review_priority.csv"))
    ap.add_argument(
        "--focus-classes", default="",
        help="Comma-separated weak classes to review first, e.g. "
             "'yellow_module,yellow_lid,red_lid,case_closed'. Frames with a "
             "predicted box of these classes go to the top, ascending by the "
             "lowest confidence on a focus-class box.",
    )
    ap.add_argument("--manifest", type=Path, default=Path("manifest/clips.csv"))
    args = ap.parse_args()

    focus = {c.strip() for c in args.focus_classes.split(",") if c.strip()}
    unknown = focus - set(CLASS_ORDER)
    if unknown:
        raise SystemExit(f"unknown focus class(es): {sorted(unknown)}")
    rows = summarize(args.labels_dir, focus)
    # session_id tells the reviewer which pool a frame feeds: a train
    # session grows the model; a val session only sharpens the metric.
    with open(args.manifest, newline="", encoding="utf-8") as f:
        sessions = {r["clip_id"]: r["session_id"] for r in csv.DictReader(f)}
    for r in rows:
        r["session_id"] = sessions.get(r["filename"][:-4].rsplit("_", 1)[0], "")

    # Zero-detection frames first (likely blind spots), then ascending
    # min_conf within each group -- worst single box first, not just
    # worst average, since one bad box can hide inside a good average.
    # With --focus-classes, frames containing a focus class come first,
    # ascending by their weakest focus-class box.
    rows.sort(key=lambda r: (
        r["focus_min_conf"] == "",
        r["focus_min_conf"] if r["focus_min_conf"] != "" else 0.0,
        r["n_detections"] > 0, r["min_conf"],
    ))

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["filename", "session_id", "focus_classes", "focus_min_conf", "n_detections",
                                               "min_conf", "mean_conf", "has_lid_detection", "classes"])
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
