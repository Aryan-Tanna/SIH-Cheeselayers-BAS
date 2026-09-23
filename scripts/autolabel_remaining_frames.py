#!/usr/bin/env python3
"""Run the bootstrap YOLOv8-OBB detector on the frames nobody has
manually labelled yet, and write REVIEW-READY pre-labels -- not
accepted ground truth. Two output formats, same predictions:

  1. Plain YOLO OBB .txt per image (class_id x1 y1 x2 y2 x3 y3 x4 y4,
     normalized) -- for spot-checking without needing Label Studio.
  2. A Label Studio predictions-import JSON, so a human can load these
     as pre-filled boxes in the labelling UI and correct/reject them,
     the same review workflow already used for the 157 manual frames.

Default weights are bootstrap_v3 (196 train frames, real session
split; see CLAUDE.md for per-class val numbers -- yellow_lid and
case_closed are weak, hand_gloved is unmeasured). Treat its output
accordingly -- confidence numbers here are the model's own, not a
measure of correctness.

Rotation caveat: every one of the 860 training boxes had rotation ~= 0
(the labelled corpus turned out to be effectively axis-aligned in
practice). The center-to-corner math below has only been validated
against near-zero-rotation cases; if this model ever predicts a
meaningfully rotated box, that specific conversion path is unverified.
"""

from __future__ import annotations

import argparse
import json
import math
import uuid
from pathlib import Path

CLASS_ORDER = [
    "case_open", "case_closed", "red_module", "yellow_module",
    "red_lid", "yellow_lid", "hand_gloved", "hand_bare",
]


def _rotate_cw(dx: float, dy: float, theta_rad: float) -> tuple[float, float]:
    cos_t, sin_t = math.cos(theta_rad), math.sin(theta_rad)
    return (dx * cos_t - dy * sin_t, dx * sin_t + dy * cos_t)


def xywhr_to_ls_box(
    cx: float, cy: float, w: float, h: float, theta_rad: float,
    orig_w: int, orig_h: int,
) -> dict:
    """Ultralytics' OBB is parameterized as (center, size, angle),
    rotated about its own center. Label Studio's rectanglelabels OBB is
    parameterized as (top-left-before-rotation, size, angle), where
    that stored (x, y) is the corner's actual on-screen position --
    rotating a point about itself is a no-op, so the "top-left" corner
    never needs a separate before/after distinction (matches
    src/perception/obb_reduce.py's documented convention). Convert by
    finding where the local (-w/2, -h/2) corner lands after rotation.
    """
    tl_dx, tl_dy = _rotate_cw(-w / 2, -h / 2, theta_rad)
    x_px, y_px = cx + tl_dx, cy + tl_dy
    rotation_deg = math.degrees(theta_rad) % 360.0
    return {
        "x": x_px / orig_w * 100.0,
        "y": y_px / orig_h * 100.0,
        "width": w / orig_w * 100.0,
        "height": h / orig_h * 100.0,
        "rotation": rotation_deg,
    }


def xywhr_to_yolo_corners(
    cx: float, cy: float, w: float, h: float, theta_rad: float,
    orig_w: int, orig_h: int,
) -> tuple[float, ...]:
    corners_rel = ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))
    out = []
    for dx, dy in corners_rel:
        rx, ry = _rotate_cw(dx, dy, theta_rad)
        out.append((cx + rx) / orig_w)
        out.append((cy + ry) / orig_h)
    return tuple(out)


def already_labelled_filenames(labelled_dirs: list[Path]) -> set[str]:
    # Must cover val too, not just train: since the real session split,
    # labelled frames live in both, and excluding only train would
    # re-queue every held-out val frame for review.
    return {p.name for d in labelled_dirs for p in d.glob("*.jpg")}


def run(
    weights: Path, frames_dir: Path, labelled_dirs: list[Path],
    out_dir: Path, conf_threshold: float, local_files_prefix: str,
) -> dict:
    import numpy
    numpy.trapz = numpy.trapezoid  # see CLAUDE.md session-status gotchas
    from ultralytics import YOLO

    labelled = already_labelled_filenames(labelled_dirs)
    remaining = sorted(p for p in frames_dir.glob("*.jpg") if p.name not in labelled)

    out_labels_dir = out_dir / "labels"
    if out_labels_dir.exists():
        # Purge stale predictions from a prior run -- "remaining" shrinks
        # over time as reviewed frames get merged into the training set,
        # and a leftover .txt for a now-trained frame would wrongly keep
        # it in the review queue as if it still needed attention.
        for stale in out_labels_dir.glob("*.txt"):
            stale.unlink()
    out_labels_dir.mkdir(parents=True, exist_ok=True)

    model = YOLO(str(weights))

    ls_tasks = []
    zero_detection_images: list[str] = []
    class_counts: dict[str, int] = {c: 0 for c in CLASS_ORDER}
    conf_sum: dict[str, float] = {c: 0.0 for c in CLASS_ORDER}
    low_conf_images: list[tuple[str, float]] = []

    batch_size = 32
    for start in range(0, len(remaining), batch_size):
        batch = remaining[start : start + batch_size]
        results = model.predict([str(p) for p in batch], conf=conf_threshold, verbose=False)
        for path, res in zip(batch, results):
            orig_h, orig_w = res.orig_shape
            yolo_lines = []
            ls_result = []
            image_min_conf = 1.0
            n = 0 if res.obb is None else len(res.obb)
            for i in range(n):
                cx, cy, w, h, theta = res.obb.xywhr[i].tolist()
                cls_id = int(res.obb.cls[i].item())
                score = float(res.obb.conf[i].item())
                class_name = CLASS_ORDER[cls_id]

                yolo_corners = xywhr_to_yolo_corners(cx, cy, w, h, theta, orig_w, orig_h)
                coords = " ".join(f"{c:.6f}" for c in yolo_corners)
                yolo_lines.append(f"{cls_id} {coords} {score:.4f}")

                ls_box = xywhr_to_ls_box(cx, cy, w, h, theta, orig_w, orig_h)
                ls_result.append({
                    "id": uuid.uuid4().hex[:10],
                    "type": "rectanglelabels",
                    "from_name": "label",
                    "to_name": "image",
                    "original_width": orig_w,
                    "original_height": orig_h,
                    "value": {**ls_box, "rectanglelabels": [class_name]},
                    "score": score,
                })
                class_counts[class_name] += 1
                conf_sum[class_name] += score
                image_min_conf = min(image_min_conf, score)

            (out_labels_dir / (path.stem + ".txt")).write_text(
                "\n".join(yolo_lines) + ("\n" if yolo_lines else ""), encoding="utf-8"
            )

            if n == 0:
                zero_detection_images.append(path.name)
            else:
                low_conf_images.append((path.name, image_min_conf))

            ls_tasks.append({
                "data": {"image": f"/data/local-files/?d={local_files_prefix}{path.name}"},
                "predictions": [{
                    "model_version": weights.parent.parent.name,
                    "result": ls_result,
                }],
            })

    (out_dir / "label_studio_predictions.json").write_text(
        json.dumps(ls_tasks, indent=2), encoding="utf-8"
    )

    low_conf_images.sort(key=lambda t: t[1])

    return {
        "n_remaining": len(remaining),
        "n_zero_detection": len(zero_detection_images),
        "zero_detection_sample": zero_detection_images[:15],
        "class_counts": class_counts,
        "mean_conf": {
            c: (conf_sum[c] / class_counts[c] if class_counts[c] else 0.0) for c in CLASS_ORDER
        },
        "lowest_confidence_images": low_conf_images[:15],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", type=Path, default=Path("runs/train/bootstrap_v3/weights/best.pt"))
    ap.add_argument("--frames-dir", type=Path, default=Path("frames"))
    ap.add_argument(
        "--labelled-images-dirs", type=Path, nargs="+",
        default=[Path("runs/yolo_dataset/images/train"), Path("runs/yolo_dataset/images/val")],
    )
    ap.add_argument("--out-dir", type=Path, default=Path("runs/autolabel_predictions"))
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument(
        "--local-files-prefix", default="frames/",
        help="Path prefix for Label Studio's Local Files storage, relative to "
             "LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT (e.g. 'frames/' if that root "
             "is set to the repo directory). Must end with '/' if non-empty.",
    )
    args = ap.parse_args()

    summary = run(
        args.weights, args.frames_dir, args.labelled_images_dirs, args.out_dir,
        args.conf, args.local_files_prefix,
    )

    print(f"remaining frames processed : {summary['n_remaining']}")
    print(f"images with zero detections: {summary['n_zero_detection']}")
    if summary["zero_detection_sample"]:
        print(f"  sample: {summary['zero_detection_sample']}")
    print("class counts / mean confidence:")
    for c in CLASS_ORDER:
        print(f"  {c:14s} {summary['class_counts'][c]:5d}  conf={summary['mean_conf'][c]:.3f}")
    print("15 lowest-confidence images (priority review candidates):")
    for name, conf in summary["lowest_confidence_images"]:
        print(f"  {conf:.3f}  {name}")
    print(f"\nYOLO-format predictions -> {args.out_dir / 'labels'}")
    print(f"Label Studio import json -> {args.out_dir / 'label_studio_predictions.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
