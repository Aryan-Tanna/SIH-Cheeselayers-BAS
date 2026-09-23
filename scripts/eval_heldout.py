#!/usr/bin/env python3
"""Score a detector checkpoint against a genuinely held-out session.

Every mAP number this project has reported so far came from a
`runs/yolo_dataset/` whose val split was literally the same images as
train -- it measures memorization, not accuracy. This script exists to
replace that number with a real one, and it deliberately never reads
the training split: the frames it scores are selected by `session_id`
from `manifest/clips.csv`, and it hard-fails if the session you name is
one the model was trained on.

Two modes, run in this order:

  1. `--emit-tasks`   Select a stratified frame sample from the held-out
                      session and write a Label Studio import JSON for a
                      human to annotate. This is the ground truth; there
                      is no other source of it.

  2. `--ground-truth` Take the human's Label Studio export back, run the
                      checkpoint over exactly those frames, and report
                      per-class precision / recall / F1 / AP50, mAP50,
                      and a localization-free class-presence score.

On pre-labelling the ground truth
---------------------------------
`--prelabel` will seed the annotation tasks with the model's own
predictions, which is much faster to review than drawing from scratch.
It is OFF by default and should stay off for a validation set. The
failure mode is anchoring: this model's characteristic error is a box
that is loose by 10-25% rather than absent, and a reviewer correcting
pre-filled boxes tends to accept a box that looks approximately right.
That silently rewrites the ground truth toward the model and inflates
exactly the IoU-sensitive metrics this script exists to measure. Use
`--prelabel` for building TRAINING data (scripts/autolabel_remaining_
frames.py already does that job properly); draw validation boxes cold.

Metric conventions
------------------
- IoU is exact convex-polygon intersection-over-union (Sutherland-
  Hodgman clip + shoelace), not the probabilistic approximation
  Ultralytics uses internally for OBB NMS. Slower, exact, and it does
  not need to be fast here.
- Matching is greedy in descending confidence, one prediction to at
  most one ground-truth box, within the same class. Unmatched
  predictions are false positives; unmatched ground truth is a false
  negative.
- AP is all-point interpolation over the per-class PR curve (the
  COCO/Pascal-2010 convention), not the 11-point one.
- A class with zero ground-truth instances in the held-out session
  reports its false-positive count and nothing else -- precision and
  recall are undefined, and printing 0.0 for them would read as a
  measured failure rather than an absence of test data.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.convert_labels_to_yolo_obb import CLASS_ORDER, parse_task  # noqa: E402

CLASS_TO_ID = {name: i for i, name in enumerate(CLASS_ORDER)}

MANIFEST_PATH = Path("manifest/clips.csv")
FRAMES_DIR = Path("frames")
DEFAULT_WEIGHTS = Path("runs/train/bootstrap_v2/weights/best.pt")
DEFAULT_IOU = 0.5
DEFAULT_CONF = 0.25

Point = tuple[float, float]
Poly = tuple[Point, ...]


# --------------------------------------------------------------------------
# geometry
# --------------------------------------------------------------------------

def _shoelace_area(poly: Poly) -> float:
    n = len(poly)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def _clip_polygon(subject: Poly, clip: Poly) -> Poly:
    """Sutherland-Hodgman. Both polygons must be convex; an OBB always
    is. `clip` is walked edge by edge, keeping the half-plane on the
    interior side of each. Orientation-agnostic: the sign convention is
    taken from the clip polygon's own winding, so callers do not have to
    normalize corner order (Label Studio and Ultralytics emit opposite
    windings in practice)."""
    def winding(p: Poly) -> float:
        s = 0.0
        for i in range(len(p)):
            x1, y1 = p[i]
            x2, y2 = p[(i + 1) % len(p)]
            s += x1 * y2 - x2 * y1
        return s

    sign = 1.0 if winding(clip) >= 0 else -1.0

    def inside(pt: Point, a: Point, b: Point) -> bool:
        cross = (b[0] - a[0]) * (pt[1] - a[1]) - (b[1] - a[1]) * (pt[0] - a[0])
        return sign * cross >= 0

    def intersect(p1: Point, p2: Point, a: Point, b: Point) -> Point:
        x1, y1 = p1
        x2, y2 = p2
        x3, y3 = a
        x4, y4 = b
        den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if den == 0:
            return p2
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))

    output = list(subject)
    for i in range(len(clip)):
        a, b = clip[i], clip[(i + 1) % len(clip)]
        if not output:
            break
        cur, output = output, []
        for j in range(len(cur)):
            p1, p2 = cur[j - 1], cur[j]
            if inside(p2, a, b):
                if not inside(p1, a, b):
                    output.append(intersect(p1, p2, a, b))
                output.append(p2)
            elif inside(p1, a, b):
                output.append(intersect(p1, p2, a, b))
    return tuple(output)


def polygon_iou(a: Poly, b: Poly) -> float:
    inter = _shoelace_area(_clip_polygon(a, b))
    if inter <= 0:
        return 0.0
    union = _shoelace_area(a) + _shoelace_area(b) - inter
    return inter / union if union > 0 else 0.0


def _rotate_cw(dx: float, dy: float, theta: float) -> Point:
    c, s = math.cos(theta), math.sin(theta)
    return (dx * c - dy * s, dx * s + dy * c)


def xywhr_to_corners(cx: float, cy: float, w: float, h: float, theta: float) -> Poly:
    """Ultralytics OBB (center, size, angle-about-center) -> 4 corners in
    pixels. Matches scripts/autolabel_remaining_frames.py's convention."""
    rel = ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))
    return tuple((cx + dx, cy + dy) for dx, dy in (_rotate_cw(x, y, theta) for x, y in rel))


# --------------------------------------------------------------------------
# frame selection
# --------------------------------------------------------------------------

def clips_for_session(session_id: str, manifest_path: Path) -> list[str]:
    with open(manifest_path, newline="", encoding="utf-8") as f:
        return [r["clip_id"] for r in csv.DictReader(f)
                if (r.get("session_id") or "").strip() == session_id]


def assert_session_held_out(session_id: str, train_images_dir: Path, clip_ids: list[str]) -> None:
    """Refuse to report a validation number for frames the model may have
    trained on. If the training split isn't on disk we cannot prove the
    session is clean, so say that plainly rather than assuming it."""
    if not train_images_dir.exists():
        print(f"NOTE: {train_images_dir} not present -- cannot verify {session_id} was "
              f"excluded from training. Verify by hand before quoting these numbers.")
        return
    trained = {p.name for p in train_images_dir.glob("*.jpg")}
    leaked = sorted(n for n in trained
                    if n.rsplit("_", 1)[0] in set(clip_ids))
    if leaked:
        raise SystemExit(
            f"REFUSING TO SCORE: {len(leaked)} frame(s) from session {session_id} are in the "
            f"training split ({train_images_dir}), e.g. {leaked[:5]}. "
            "This session is not held out; any number produced here would be meaningless."
        )
    print(f"leakage check: OK -- 0 of {len(trained)} training frames belong to {session_id}")


def stratified_sample(clip_ids: list[str], frames_dir: Path, n: int, seed: int) -> list[Path]:
    """Even coverage per clip and even temporal coverage within each clip.
    A uniform random draw over the pooled frames would over-weight the
    longer clips and can leave a whole clip unrepresented, which is the
    opposite of what a validation sample is for."""
    by_clip = {cid: sorted(frames_dir.glob(f"{cid}_*.jpg")) for cid in clip_ids}
    by_clip = {k: v for k, v in by_clip.items() if v}
    if not by_clip:
        raise SystemExit(f"no frames found in {frames_dir} for clips {clip_ids}")

    rng = random.Random(seed)
    per_clip = max(1, n // len(by_clip))
    picked: list[Path] = []
    for cid in sorted(by_clip):
        frames = by_clip[cid]
        k = min(per_clip, len(frames))
        # even temporal strata, random position inside each stratum, so
        # repeated runs with different seeds don't all land on the same
        # canonical frames while coverage stays uniform.
        edges = [round(i * len(frames) / k) for i in range(k + 1)]
        for i in range(k):
            lo, hi = edges[i], max(edges[i] + 1, edges[i + 1])
            picked.append(frames[rng.randrange(lo, min(hi, len(frames)))])
    return sorted(set(picked))


# --------------------------------------------------------------------------
# inference
# --------------------------------------------------------------------------

def run_inference(weights: Path, frames: list[Path], conf: float
                  ) -> tuple[dict[str, list[dict]], dict[str, tuple[int, int]]]:
    import numpy
    numpy.trapz = numpy.trapezoid  # ultralytics 8.3.28 + numpy 2.x, see CLAUDE.md
    from ultralytics import YOLO

    model = YOLO(str(weights))
    out: dict[str, list[dict]] = {}
    shapes: dict[str, tuple[int, int]] = {}
    batch = 16
    for start in range(0, len(frames), batch):
        chunk = frames[start:start + batch]
        results = model.predict([str(p) for p in chunk], conf=conf, verbose=False)
        for path, res in zip(chunk, results):
            h, w = res.orig_shape
            dets = []
            n = 0 if res.obb is None else len(res.obb)
            for i in range(n):
                cx, cy, bw, bh, th = res.obb.xywhr[i].tolist()
                dets.append({
                    "class_id": int(res.obb.cls[i].item()),
                    "conf": float(res.obb.conf[i].item()),
                    "corners": xywhr_to_corners(cx, cy, bw, bh, th),
                })
            out[path.name] = dets
            shapes[path.name] = (w, h)
    return out, shapes


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------

def match_frame(preds: list[dict], gts: list[dict], iou_thr: float) -> list[tuple[float, bool, int]]:
    """Greedy one-to-one matching within a class. Returns (conf, is_tp,
    class_id) per prediction."""
    out = []
    claimed: set[int] = set()
    for p in sorted(preds, key=lambda d: -d["conf"]):
        best_iou, best_j = 0.0, -1
        for j, g in enumerate(gts):
            if j in claimed or g["class_id"] != p["class_id"]:
                continue
            iou = polygon_iou(p["corners"], g["corners"])
            if iou > best_iou:
                best_iou, best_j = iou, j
        if best_iou >= iou_thr and best_j >= 0:
            claimed.add(best_j)
            out.append((p["conf"], True, p["class_id"]))
        else:
            out.append((p["conf"], False, p["class_id"]))
    return out


def average_precision(records: list[tuple[float, bool]], n_gt: int) -> float:
    """All-point-interpolated AP over the PR curve."""
    if n_gt == 0:
        return float("nan")
    if not records:
        return 0.0
    records = sorted(records, key=lambda r: -r[0])
    tp = fp = 0
    precisions, recalls = [], []
    for _, is_tp in records:
        tp, fp = tp + int(is_tp), fp + int(not is_tp)
        precisions.append(tp / (tp + fp))
        recalls.append(tp / n_gt)
    # monotone-decreasing envelope, then integrate over recall steps
    for i in range(len(precisions) - 2, -1, -1):
        precisions[i] = max(precisions[i], precisions[i + 1])
    ap, prev_r = 0.0, 0.0
    for p, r in zip(precisions, recalls):
        ap += (r - prev_r) * p
        prev_r = r
    return ap


def score(predictions: dict[str, list[dict]], ground_truth: dict[str, list[dict]],
          iou_thr: float) -> dict:
    per_class_records: dict[int, list[tuple[float, bool]]] = defaultdict(list)
    n_gt: dict[int, int] = defaultdict(int)
    n_pred: dict[int, int] = defaultdict(int)
    tp: dict[int, int] = defaultdict(int)

    presence_tp = presence_fp = presence_fn = 0

    for name, gts in ground_truth.items():
        preds = predictions.get(name, [])
        for g in gts:
            n_gt[g["class_id"]] += 1
        for p in preds:
            n_pred[p["class_id"]] += 1
        for conf, is_tp, cid in match_frame(preds, gts, iou_thr):
            per_class_records[cid].append((conf, is_tp))
            if is_tp:
                tp[cid] += 1

        # localization-free view: per frame, compare the multiset of
        # classes present. Separates "found the right things in the
        # right frame" from "drew the box tightly enough".
        gc: dict[int, int] = defaultdict(int)
        pc: dict[int, int] = defaultdict(int)
        for g in gts:
            gc[g["class_id"]] += 1
        for p in preds:
            pc[p["class_id"]] += 1
        for cid in set(gc) | set(pc):
            hit = min(gc[cid], pc[cid])
            presence_tp += hit
            presence_fp += max(0, pc[cid] - gc[cid])
            presence_fn += max(0, gc[cid] - pc[cid])

    per_class = {}
    for cid, name in enumerate(CLASS_ORDER):
        g, p, t = n_gt[cid], n_pred[cid], tp[cid]
        per_class[name] = {
            "n_gt": g, "n_pred": p, "tp": t, "fp": p - t, "fn": g - t,
            "precision": (t / p) if p else float("nan"),
            "recall": (t / g) if g else float("nan"),
            "ap50": average_precision(per_class_records[cid], g),
        }
        pr, rc = per_class[name]["precision"], per_class[name]["recall"]
        per_class[name]["f1"] = (2 * pr * rc / (pr + rc)) if (pr == pr and rc == rc and pr + rc) else float("nan")

    aps = [v["ap50"] for v in per_class.values() if v["n_gt"] > 0]
    return {
        "per_class": per_class,
        "map50": sum(aps) / len(aps) if aps else float("nan"),
        "n_classes_with_gt": len(aps),
        "presence": {
            "tp": presence_tp, "fp": presence_fp, "fn": presence_fn,
            "precision": presence_tp / (presence_tp + presence_fp) if (presence_tp + presence_fp) else float("nan"),
            "recall": presence_tp / (presence_tp + presence_fn) if (presence_tp + presence_fn) else float("nan"),
        },
        "n_frames": len(ground_truth),
    }


# --------------------------------------------------------------------------
# ground-truth-free diagnostics
# --------------------------------------------------------------------------

def manifest_constraints(manifest_path: Path, clip_ids: list[str]) -> dict[str, set[str]]:
    """Per-clip facts that rule whole classes out, keyed by clip_id.

    Only literal, unambiguous values count: `gloves` must be exactly
    "false" (the same exact-match convention
    scripts/test_mediapipe_gloves.py relies on) and `lid_type` exactly
    "none". Any other value -- including blank, "unimplemented", or a
    stray capitalization -- yields no constraint at all. A wrong
    constraint here would manufacture false positives that aren't
    there, which is worse than measuring nothing.
    """
    out: dict[str, set[str]] = {}
    wanted = set(clip_ids)
    with open(manifest_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["clip_id"] not in wanted:
                continue
            forbidden: set[str] = set()
            if (row.get("gloves") or "").strip() == "false":
                forbidden.add("hand_gloved")
            if (row.get("lid_type") or "").strip() == "none":
                forbidden |= {"red_lid", "yellow_lid"}
            out[row["clip_id"]] = forbidden
    return out


RULED_OUT_CLASSES = ("hand_gloved", "red_lid", "yellow_lid")


def diagnose(predictions: dict[str, list[dict]],
             constraints: dict[str, set[str]],
             dup_iou: float) -> dict:
    """Checks that are decidable without any hand-annotation. These
    bound precision from one side; none of them can see a missed
    detection, so none of them says anything about recall."""
    impossible: dict[str, int] = defaultdict(int)
    impossible_frames: dict[str, set[str]] = defaultdict(set)
    n_ruled_out: dict[str, int] = defaultdict(int)
    total_boxes: dict[str, int] = defaultdict(int)
    conf_sum: dict[str, float] = defaultdict(float)
    contradiction_frames: list[str] = []
    duplicate_boxes = 0
    duplicate_frames: list[str] = []
    zero_frames: list[str] = []

    open_id, closed_id = CLASS_TO_ID["case_open"], CLASS_TO_ID["case_closed"]

    for name in sorted(predictions):
        dets = predictions[name]
        clip_id = name.rsplit("_", 1)[0]
        forbidden = constraints.get(clip_id, set())
        for cls in forbidden:
            n_ruled_out[cls] += 1

        if not dets:
            zero_frames.append(name)

        by_class: dict[int, list[dict]] = defaultdict(list)
        for d in dets:
            cname = CLASS_ORDER[d["class_id"]]
            total_boxes[cname] += 1
            conf_sum[cname] += d["conf"]
            by_class[d["class_id"]].append(d)
            if cname in forbidden:
                impossible[cname] += 1
                impossible_frames[cname].add(name)

        # One case per clip, in exactly one state. Both firing means at
        # least one is wrong, whichever one it is.
        if by_class.get(open_id) and by_class.get(closed_id):
            contradiction_frames.append(name)

        frame_dups = 0
        for boxes in by_class.values():
            for i in range(len(boxes)):
                for j in range(i + 1, len(boxes)):
                    if polygon_iou(boxes[i]["corners"], boxes[j]["corners"]) >= dup_iou:
                        frame_dups += 1
        if frame_dups:
            duplicate_boxes += frame_dups
            duplicate_frames.append(name)

    return {
        "n_frames": len(predictions),
        "ruled_out": {
            c: {
                "false_positive_boxes": impossible[c],
                "frames_where_ruled_out": n_ruled_out[c],
                "frames_with_fp": len(impossible_frames[c]),
            } for c in RULED_OUT_CLASSES
        },
        "total_boxes": dict(total_boxes),
        "mean_conf": {c: conf_sum[c] / total_boxes[c] for c in total_boxes},
        "contradiction_frames": len(contradiction_frames),
        "contradiction_sample": contradiction_frames[:8],
        "duplicate_boxes": duplicate_boxes,
        "duplicate_frames": len(duplicate_frames),
        "zero_detection_frames": len(zero_frames),
        "zero_detection_sample": zero_frames[:8],
    }


# --------------------------------------------------------------------------
# Label Studio task emission
# --------------------------------------------------------------------------

def emit_tasks(frames: list[Path], out_path: Path, local_files_prefix: str,
               prelabels: dict[str, list[dict]] | None,
               shapes: dict[str, tuple[int, int]] | None) -> None:
    tasks = []
    for p in frames:
        task: dict = {"data": {"image": f"/data/local-files/?d={local_files_prefix}{p.name}"}}
        if prelabels is not None:
            w, h = (shapes or {}).get(p.name, (0, 0))
            result = []
            for d in prelabels.get(p.name, []):
                xs = [c[0] for c in d["corners"]]
                ys = [c[1] for c in d["corners"]]
                result.append({
                    "type": "rectanglelabels", "from_name": "label", "to_name": "image",
                    "original_width": w, "original_height": h,
                    "value": {
                        "x": min(xs) / w * 100.0, "y": min(ys) / h * 100.0,
                        "width": (max(xs) - min(xs)) / w * 100.0,
                        "height": (max(ys) - min(ys)) / h * 100.0,
                        "rotation": 0.0,
                        "rectanglelabels": [CLASS_ORDER[d["class_id"]]],
                    },
                    "score": d["conf"],
                })
            task["predictions"] = [{"model_version": "prelabel", "result": result}]
        tasks.append(task)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(tasks, indent=2), encoding="utf-8")


def load_ground_truth(path: Path) -> dict[str, list[dict]]:
    """Label Studio export -> {filename: [{class_id, corners(px)}]}.
    Reuses convert_labels_to_yolo_obb.parse_task, so the unreviewed-vs-
    confirmed-empty distinction it enforces applies here too: a task
    nobody has annotated is skipped, never counted as a frame whose
    true answer is 'no objects'."""
    tasks = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, list[dict]] = {}
    skipped = 0
    for task in tasks:
        parsed = parse_task(task)
        if parsed is None:
            skipped += 1
            continue
        filename, boxes = parsed
        # parse_task normalizes to [0,1]; scale back to pixels so IoU is
        # computed in the same space as the predictions.
        res = task.get("annotations", [{}])[0].get("result", [])
        dims = next((( r["original_width"], r["original_height"]) for r in res
                     if "original_width" in r), None)
        if dims is None and boxes:
            raise SystemExit(f"{filename}: cannot determine image dimensions from export")
        w, h = dims or (1, 1)
        out[filename] = [{
            "class_id": b.class_id,
            "corners": tuple((x * w, y * h) for x, y in b.corners),
        } for b in boxes]
    if skipped:
        print(f"ground truth: skipped {skipped} unreviewed task(s) (no annotation submitted)")
    return out


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", default="S03", help="session_id to hold out and score")
    ap.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    ap.add_argument("--frames-dir", type=Path, default=FRAMES_DIR)
    ap.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    ap.add_argument("--train-images-dir", type=Path, default=Path("runs/yolo_dataset/images/train"))
    ap.add_argument("--out-dir", type=Path, default=Path("runs/eval_heldout"))
    ap.add_argument("--conf", type=float, default=DEFAULT_CONF)
    ap.add_argument("--iou", type=float, default=DEFAULT_IOU)
    ap.add_argument("--sample-n", type=int, default=63, help="frames to sample for annotation")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--local-files-prefix", default="frames/")

    ap.add_argument("--emit-tasks", action="store_true",
                    help="write a Label Studio import JSON for the sampled frames and stop")
    ap.add_argument("--prelabel", action="store_true",
                    help="seed emitted tasks with model predictions -- NOT for validation data, "
                         "see this script's docstring on anchoring")
    ap.add_argument("--ground-truth", type=Path,
                    help="Label Studio export to score the checkpoint against")
    ap.add_argument("--diagnose", action="store_true",
                    help="ground-truth-free checks over every frame in the session")
    ap.add_argument("--dup-iou", type=float, default=0.55,
                    help="IoU above which two same-class boxes count as a duplicate")
    args = ap.parse_args()

    clip_ids = clips_for_session(args.session, args.manifest)
    if not clip_ids:
        raise SystemExit(f"no clips with session_id={args.session} in {args.manifest}")
    print(f"session {args.session}: {len(clip_ids)} clips -- {', '.join(clip_ids)}")
    assert_session_held_out(args.session, args.train_images_dir, clip_ids)

    args.out_dir.mkdir(parents=True, exist_ok=True)

    if args.emit_tasks:
        frames = stratified_sample(clip_ids, args.frames_dir, args.sample_n, args.seed)
        prelabels = shapes = None
        if args.prelabel:
            print("WARNING: --prelabel on a validation set anchors the ground truth to the "
                  "model's own boxes. See the docstring.")
            prelabels, shapes = run_inference(args.weights, frames, args.conf)
        out = args.out_dir / f"{args.session}_annotation_tasks.json"
        emit_tasks(frames, out, args.local_files_prefix, prelabels, shapes)
        per_clip: dict[str, int] = defaultdict(int)
        for f in frames:
            per_clip[f.stem.rsplit("_", 1)[0]] += 1
        print(f"\n{len(frames)} frames sampled for annotation:")
        for cid in sorted(per_clip):
            print(f"  {cid:<24}{per_clip[cid]}")
        print(f"\nLabel Studio import -> {out}")
        print("Annotate these, export as JSON, then re-run with --ground-truth <export>.")
        return 0

    if args.diagnose:
        frames = sorted(f for cid in clip_ids for f in args.frames_dir.glob(f"{cid}_*.jpg"))
        if not frames:
            raise SystemExit(f"no frames for session {args.session} in {args.frames_dir}")
        print(f"\nrunning {args.weights.name} over all {len(frames)} frames (conf>={args.conf})...")
        preds, _ = run_inference(args.weights, frames, args.conf)
        d = diagnose(preds, manifest_constraints(args.manifest, clip_ids), args.dup_iou)
        n = d["n_frames"]

        print("\n--- ruled out by manifest (every such box is a false positive) ---")
        print(f"{'class':<16}{'frames ruled out':>18}{'FP boxes':>10}"
              f"{'frames w/ FP':>14}{'frame FP rate':>15}")
        for c in RULED_OUT_CLASSES:
            v = d["ruled_out"][c]
            k = v["frames_where_ruled_out"]
            rate = f"{v['frames_with_fp'] / k:.3f}" if k else "-"
            print(f"{c:<16}{k:>18}{v['false_positive_boxes']:>10}"
                  f"{v['frames_with_fp']:>14}{rate:>15}")

        print("\n--- detections (counts only, no ground truth) ---")
        print(f"{'class':<16}{'boxes':>8}{'mean conf':>11}{'boxes/frame':>13}")
        for c in CLASS_ORDER:
            if d["total_boxes"].get(c):
                print(f"{c:<16}{d['total_boxes'][c]:>8}{d['mean_conf'][c]:>11.3f}"
                      f"{d['total_boxes'][c] / n:>13.2f}")

        print("\n--- self-consistency ---")
        print(f"case_open AND case_closed in one frame  : {d['contradiction_frames']:>5}"
              f"  ({d['contradiction_frames'] / n:.1%} of frames)")
        if d["contradiction_sample"]:
            print(f"  sample: {d['contradiction_sample'][:4]}")
        print(f"duplicate same-class boxes (IoU>={args.dup_iou:.2f}) : {d['duplicate_boxes']:>5}"
              f"  across {d['duplicate_frames']} frames ({d['duplicate_frames'] / n:.1%})")
        print(f"frames with zero detections            : {d['zero_detection_frames']:>5}"
              f"  ({d['zero_detection_frames'] / n:.1%} of frames)")

        out = args.out_dir / f"{args.session}_diagnostics.json"
        out.write_text(json.dumps({"weights": str(args.weights), "conf": args.conf, **d},
                                  indent=2), encoding="utf-8")
        print(f"\ndiagnostics -> {out}")
        print("These bound precision only. Recall and localization need --ground-truth.")
        return 0

    if not args.ground_truth:
        ap.error("pass --emit-tasks to produce annotation tasks, --diagnose for "
                 "ground-truth-free checks, or --ground-truth to score")

    gt = load_ground_truth(args.ground_truth)
    frames = [args.frames_dir / n for n in sorted(gt)]
    missing = [f for f in frames if not f.exists()]
    if missing:
        raise SystemExit(f"{len(missing)} annotated frame(s) not in {args.frames_dir}, e.g. {missing[:3]}")

    stray = sorted({f.stem.rsplit("_", 1)[0] for f in frames} - set(clip_ids))
    if stray:
        raise SystemExit(f"ground truth contains frames from clips outside session {args.session}: {stray}")

    preds, _ = run_inference(args.weights, frames, args.conf)
    result = score(preds, gt, args.iou)

    print(f"\nweights   : {args.weights}")
    print(f"frames    : {result['n_frames']} annotated, conf>={args.conf}, IoU>={args.iou}")
    print(f"\n{'class':<16}{'n_gt':>6}{'n_pred':>8}{'TP':>5}{'FP':>5}{'FN':>5}"
          f"{'prec':>8}{'rec':>8}{'F1':>8}{'AP50':>8}")
    for name in CLASS_ORDER:
        c = result["per_class"][name]
        if c["n_gt"] == 0:
            note = f"no ground truth in {args.session}"
            print(f"{name:<16}{0:>6}{c['n_pred']:>8}{'-':>5}{c['n_pred']:>5}{'-':>5}"
                  f"{'-':>8}{'-':>8}{'-':>8}{'-':>8}  {note}")
            continue
        f = lambda v: f"{v:.3f}" if v == v else "-"  # noqa: E731
        print(f"{name:<16}{c['n_gt']:>6}{c['n_pred']:>8}{c['tp']:>5}{c['fp']:>5}{c['fn']:>5}"
              f"{f(c['precision']):>8}{f(c['recall']):>8}{f(c['f1']):>8}{f(c['ap50']):>8}")

    print(f"\nmAP50 (over {result['n_classes_with_gt']} classes with ground truth): "
          f"{result['map50']:.3f}")
    p = result["presence"]
    print(f"class-presence (localization-free): precision {p['precision']:.3f}  "
          f"recall {p['recall']:.3f}  (tp {p['tp']} fp {p['fp']} fn {p['fn']})")

    out = args.out_dir / f"{args.session}_metrics.json"
    out.write_text(json.dumps({
        "weights": str(args.weights), "session": args.session,
        "conf": args.conf, "iou": args.iou, **result,
    }, indent=2), encoding="utf-8")
    print(f"\nmetrics -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
