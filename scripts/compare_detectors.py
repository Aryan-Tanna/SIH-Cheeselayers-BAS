#!/usr/bin/env python3
"""Compare two detector weights on the same test labels: mAP50, per-class
AP50, and the lid <-> same-colour module confusion counts (the reason for
the batch14 labels).

    python scripts/compare_detectors.py models/bootstrap_v5_best.pt runs/train/bootstrap_v6/weights/best.pt \\
        --data runs/yolo_dataset_v6/data_test_sessions.yaml runs/yolo_dataset_v6/data_test_s00.yaml

Both models are scored on the SAME yaml (same frames, same labels), CPU,
workers=0 (Windows, see CLAUDE.md gotchas). Prints a summary table.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

CONFUSIONS = [("red_lid", "red_module"), ("red_module", "red_lid"),
              ("yellow_lid", "yellow_module"), ("yellow_module", "yellow_lid")]


def evaluate(weights: Path, data: Path, out: Path) -> dict:
    import numpy as np

    if not hasattr(np, "trapz"):
        np.trapz = np.trapezoid  # ultralytics 8.3.28 + numpy 2
    from ultralytics import YOLO

    r = YOLO(str(weights), task="obb").val(data=str(data), imgsz=640, batch=1, workers=0, device="cpu",
                                          plots=True, verbose=False, project=str(out), name="v", exist_ok=True)
    # plots=True: ultralytics 8.3.28 fills the confusion matrix only when plotting
    names = r.names
    idx = {v: k for k, v in names.items()}
    per_class = {names[c]: float(r.box.ap50[i]) for i, c in enumerate(r.box.ap_class_index)}
    m = r.confusion_matrix.matrix  # rows = predicted, cols = true
    conf = {f"{t}->{p}": int(m[idx[p], idx[t]]) for t, p in CONFUSIONS}
    true_tot = {t: int(m[:, idx[t]].sum()) for t, _ in CONFUSIONS}
    return {"map50": float(r.box.map50), "map": float(r.box.map), "per_class": per_class,
            "confusion": conf, "true_tot": true_tot}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("old", type=Path)
    ap.add_argument("new", type=Path)
    ap.add_argument("--data", type=Path, nargs="+", required=True)
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="cmpdet_"))
    for data in args.data:
        a, b = evaluate(args.old, data, tmp), evaluate(args.new, data, tmp)
        print(f"\n=== {data.name}")
        print(f"{'':22s} {args.old.stem:>18s} {args.new.stem:>18s}   change")
        for k, label in (("map50", "mAP50"), ("map", "mAP50-95")):
            print(f"{label:22s} {a[k]:18.3f} {b[k]:18.3f}   {b[k] - a[k]:+.3f}")
        for c in sorted(set(a["per_class"]) | set(b["per_class"])):
            x, y = a["per_class"].get(c, float("nan")), b["per_class"].get(c, float("nan"))
            print(f"  AP50 {c:16s} {x:18.3f} {y:18.3f}   {y - x:+.3f}")
        print("  confusions (true -> predicted, count / true boxes of that class):")
        for k in a["confusion"]:
            t = k.split("->")[0]
            print(f"  {k:26s} {a['confusion'][k]:6d} / {a['true_tot'][t]:<4d}      "
                  f"{b['confusion'][k]:6d} / {b['true_tot'][t]:<4d}  {b['confusion'][k] - a['confusion'][k]:+d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
