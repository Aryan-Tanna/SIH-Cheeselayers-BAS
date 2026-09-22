#!/usr/bin/env python3
"""Label Studio full export -> YOLOv8-OBB training labels.

This is a training-data preparation script, distinct from
src/perception/obb_reduce.py (which reduces one OBB to a centroid +
radius for runtime kinematics). This one produces the 4-corner
normalized format Ultralytics' OBB trainer expects:

    class_id x1 y1 x2 y2 x3 y3 x4 y4   (all coords in [0, 1])

Pivot/rotation convention matches src/perception/obb_reduce.py exactly:
Label Studio's (x, y) is the box's top-left corner BEFORE rotation, and
rotation is clockwise in image coordinates (x right, y down). Corners
are rotated about that pivot, never computed as (x + w/2, y + h/2).

Per-region flags (occlusion / motion_blur / reflection_ambiguous) are
carried through as a sidecar quality report, not used to drop boxes --
LABELLING_GUIDANCE.md's own rule is that a flagged-but-boxed region is
still an accurate box of what's visible, so it's a legitimate (if
harder) training example, not a bad one.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

CLASS_ORDER = [
    "case_open",
    "case_closed",
    "red_module",
    "yellow_module",
    "red_lid",
    "yellow_lid",
    "hand_gloved",
    "hand_bare",
]
CLASS_TO_ID = {name: i for i, name in enumerate(CLASS_ORDER)}

_UPLOAD_PREFIX_RE = re.compile(r"^.*/([0-9a-f]{8}-)?")


@dataclass(frozen=True)
class ObbAnnotation:
    class_id: int
    corners: tuple[tuple[float, float], ...]  # 4 (x, y) pairs, normalized [0,1]
    flags: tuple[str, ...]


def _clean_filename(image_field: str) -> str:
    return _UPLOAD_PREFIX_RE.sub("", image_field)


def _rotate_cw(dx: float, dy: float, theta_rad: float) -> tuple[float, float]:
    cos_t, sin_t = math.cos(theta_rad), math.sin(theta_rad)
    return (dx * cos_t - dy * sin_t, dx * sin_t + dy * cos_t)


def obb_corners_normalized(
    x_pct: float, y_pct: float, w_pct: float, h_pct: float, rotation_deg: float,
    original_width: int, original_height: int,
) -> tuple[tuple[float, float], ...]:
    """Label Studio gives x/y/width/height as PERCENT of image size, with
    (x, y) the top-left pivot before rotation. Convert to absolute
    pixels first (percent -> px needs width/height separately per
    axis), rotate the 4 corners about that pivot, then normalize back
    to [0, 1] per axis for YOLO OBB's expected format."""
    x_px = x_pct / 100.0 * original_width
    y_px = y_pct / 100.0 * original_height
    w_px = w_pct / 100.0 * original_width
    h_px = h_pct / 100.0 * original_height

    theta = math.radians(rotation_deg)
    corners_rel = ((0.0, 0.0), (w_px, 0.0), (w_px, h_px), (0.0, h_px))
    corners_px = [
        (x_px + rx, y_px + ry)
        for rx, ry in (_rotate_cw(dx, dy, theta) for dx, dy in corners_rel)
    ]
    return tuple((cx / original_width, cy / original_height) for cx, cy in corners_px)


def parse_task(task: dict) -> tuple[str, list[ObbAnnotation]] | None:
    image_field = task.get("data", {}).get("image", "")
    if not image_field:
        return None
    filename = _clean_filename(image_field)

    annotations = task.get("annotations", [])
    if not annotations:
        # No human has submitted this task yet (e.g. it's still just a
        # pre-label prediction from a partial-review export) -- this is
        # NOT the same as "reviewed and confirmed zero objects", which
        # is a real annotations[0] entry with an empty result list.
        # Conflating the two would silently teach the model "nothing is
        # here" for frames nobody has actually looked at yet.
        return None

    results = annotations[0].get("result", [])
    flags_by_region_id: dict[str, list[str]] = {}
    boxes: list[tuple[str, dict]] = []
    for res in results:
        region_id = res.get("id")
        if res.get("type") == "rectanglelabels":
            boxes.append((region_id, res))
        elif res.get("type") == "choices":
            choices = res.get("value", {}).get("choices", [])
            flags_by_region_id.setdefault(region_id, []).extend(choices)

    parsed: list[ObbAnnotation] = []
    unknown_classes: list[str] = []
    for region_id, res in boxes:
        value = res["value"]
        labels = value.get("rectanglelabels", [])
        if not labels:
            continue
        class_name = labels[0]
        if class_name not in CLASS_TO_ID:
            unknown_classes.append(class_name)
            continue
        corners = obb_corners_normalized(
            value["x"], value["y"], value["width"], value["height"],
            value.get("rotation", 0.0),
            res["original_width"], res["original_height"],
        )
        parsed.append(ObbAnnotation(
            class_id=CLASS_TO_ID[class_name],
            corners=corners,
            flags=tuple(flags_by_region_id.get(region_id, [])),
        ))
    if unknown_classes:
        raise ValueError(f"{filename}: unknown class(es) {unknown_classes}, not in CLASS_ORDER")
    return filename, parsed


def convert(
    json_paths: list[Path], frames_dir: Path, out_images_dir: Path, out_labels_dir: Path,
) -> dict:
    out_images_dir.mkdir(parents=True, exist_ok=True)
    out_labels_dir.mkdir(parents=True, exist_ok=True)

    seen_filenames: dict[str, Path] = {}
    class_counts: Counter[str] = Counter()
    flagged_box_count = 0
    total_box_count = 0
    n_images = 0

    for jp in json_paths:
        tasks = json.loads(jp.read_text(encoding="utf-8"))
        for task in tasks:
            parsed = parse_task(task)
            if parsed is None:
                continue
            filename, boxes = parsed

            if filename in seen_filenames:
                raise ValueError(
                    f"duplicate filename '{filename}' in both {seen_filenames[filename]} and {jp} "
                    "-- refusing to silently overwrite one annotator's labels with another's"
                )
            seen_filenames[filename] = jp

            src_image = frames_dir / filename
            if not src_image.exists():
                raise FileNotFoundError(f"{filename} referenced in {jp} not found in {frames_dir}")

            shutil.copy2(src_image, out_images_dir / filename)

            label_path = out_labels_dir / (Path(filename).stem + ".txt")
            lines = []
            for box in boxes:
                total_box_count += 1
                class_counts[CLASS_ORDER[box.class_id]] += 1
                if box.flags:
                    flagged_box_count += 1
                coords = " ".join(f"{c:.6f}" for pt in box.corners for c in pt)
                lines.append(f"{box.class_id} {coords}")
            label_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
            n_images += 1

    return {
        "n_images": n_images,
        "n_boxes": total_box_count,
        "class_counts": dict(class_counts),
        "flagged_box_count": flagged_box_count,
        "source_files": [str(p) for p in json_paths],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", nargs="+", type=Path, required=True, help="Label Studio full-export JSON files")
    ap.add_argument("--frames-dir", type=Path, default=Path("frames"))
    ap.add_argument("--out-images", type=Path, default=Path("runs/yolo_dataset/images/train"))
    ap.add_argument("--out-labels", type=Path, default=Path("runs/yolo_dataset/labels/train"))
    args = ap.parse_args()

    summary = convert(args.json, args.frames_dir, args.out_images, args.out_labels)

    print(f"images written : {summary['n_images']}")
    print(f"boxes written  : {summary['n_boxes']}")
    print(f"flagged boxes  : {summary['flagged_box_count']} (kept in training data, not dropped)")
    print("class counts   :")
    for name in CLASS_ORDER:
        print(f"  {name:14s} {summary['class_counts'].get(name, 0)}")
    print(f"images  -> {args.out_images}")
    print(f"labels  -> {args.out_labels}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
