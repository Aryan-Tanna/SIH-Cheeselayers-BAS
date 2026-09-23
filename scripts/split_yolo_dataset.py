#!/usr/bin/env python3
"""Turn the flat pool convert_labels_to_yolo_obb.py writes (everything
into images/train + labels/train, no split) into a genuine train/val
split by session_id -- the piece that was missing for bootstrap_v1/v2,
where val had to be a copy of train because nothing was held out.

Moves (not copies) each frame+label pair into images/val + labels/val
if its clip's session_id is in --val-sessions. A frame whose clip has
no session_id in manifest/clips.csv is refused, not silently guessed --
same principle as everywhere else in this repo: an unset session_id
means "we don't know," not "assume train."
"""

from __future__ import annotations

import argparse
import csv
import shutil
from collections import Counter
from pathlib import Path

CLASS_ORDER = [
    "case_open", "case_closed", "red_module", "yellow_module",
    "red_lid", "yellow_lid", "hand_gloved", "hand_bare",
]


def clip_id_from_frame_filename(frame_filename: str) -> str:
    """Mirrors scripts/extract_frames.py's function of the same name --
    duplicated rather than imported to avoid a cross-script import path
    dependency; keep the two in sync if the naming convention changes."""
    stem = Path(frame_filename).stem
    return stem.rsplit("_", 1)[0]


def load_clip_sessions(manifest_path: Path) -> dict[str, str]:
    with open(manifest_path, newline="", encoding="utf-8") as f:
        return {row["clip_id"]: row["session_id"] for row in csv.DictReader(f)}


def class_counts_for(labels_dir: Path) -> Counter:
    counts: Counter = Counter()
    for txt in labels_dir.glob("*.txt"):
        for line in txt.read_text(encoding="utf-8").splitlines():
            if line.strip():
                counts[CLASS_ORDER[int(line.split()[0])]] += 1
    return counts


def split(
    dataset_dir: Path, manifest_path: Path, val_sessions: set[str],
    probe_clips: set[str] | None = None, probe_name: str = "probe",
) -> dict:
    """probe_clips: whole clips pulled out of TRAIN into images/<probe_name>
    as a separate, clearly-labelled eval set (e.g. gloved hands, whose only
    clips all share one session). Clip-level, never frame-level, so no
    near-duplicate frame of a probe clip is ever trained on -- but it is
    still the same session as train, so its metric overestimates and must
    never be merged into the headline val number."""
    probe_clips = probe_clips or set()
    images_train = dataset_dir / "images" / "train"
    labels_train = dataset_dir / "labels" / "train"
    images_val = dataset_dir / "images" / "val"
    labels_val = dataset_dir / "labels" / "val"

    # Start clean: val is rebuilt from train each run, never accumulates
    # stale entries from a previous split (same lesson as
    # autolabel_remaining_frames.py's stale-prediction bug).
    if images_val.exists():
        shutil.rmtree(images_val)
    if labels_val.exists():
        shutil.rmtree(labels_val)
    images_val.mkdir(parents=True)
    labels_val.mkdir(parents=True)

    images_probe = dataset_dir / "images" / probe_name
    labels_probe = dataset_dir / "labels" / probe_name
    for d in (images_probe, labels_probe):
        if d.exists():
            shutil.rmtree(d)
    if probe_clips:
        images_probe.mkdir(parents=True)
        labels_probe.mkdir(parents=True)

    clip_sessions = load_clip_sessions(manifest_path)
    bad_probe = sorted(c for c in probe_clips
                       if c not in clip_sessions or clip_sessions[c] in val_sessions)
    if bad_probe:
        raise SystemExit(
            f"refusing to split: probe clip(s) {bad_probe} are unknown to {manifest_path} "
            f"or already in a val session -- a probe must come out of train"
        )
    probe_moved = 0

    moved = 0
    kept = 0
    session_counts: Counter = Counter()
    unknown_clips: set[str] = set()

    for img_path in sorted(images_train.glob("*.jpg")):
        clip_id = clip_id_from_frame_filename(img_path.name)
        session_id = clip_sessions.get(clip_id)
        if session_id is None:
            unknown_clips.add(clip_id)
            continue
        label_path = labels_train / (img_path.stem + ".txt")

        if clip_id in probe_clips:
            shutil.move(str(img_path), str(images_probe / img_path.name))
            if label_path.exists():
                shutil.move(str(label_path), str(labels_probe / label_path.name))
            probe_moved += 1
        elif session_id in val_sessions:
            shutil.move(str(img_path), str(images_val / img_path.name))
            if label_path.exists():
                shutil.move(str(label_path), str(labels_val / label_path.name))
            session_counts[session_id] += 1
            moved += 1
        else:
            kept += 1

    if unknown_clips:
        raise SystemExit(
            f"refusing to split: {len(unknown_clips)} frame(s) belong to clip(s) "
            f"with no session_id in {manifest_path}: {sorted(unknown_clips)}"
        )

    return {
        "moved_to_val": moved,
        "kept_in_train": kept,
        "val_session_counts": dict(session_counts),
        "train_class_counts": dict(class_counts_for(labels_train)),
        "val_class_counts": dict(class_counts_for(labels_val)),
        "moved_to_probe": probe_moved,
        "probe_class_counts": dict(class_counts_for(labels_probe)) if probe_clips else {},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset-dir", type=Path, default=Path("runs/yolo_dataset"))
    ap.add_argument("--manifest", type=Path, default=Path("manifest/clips.csv"))
    ap.add_argument(
        "--val-sessions", required=True,
        help="Comma-separated session_id(s) to hold out as val, e.g. 'S01,S02'",
    )
    ap.add_argument(
        "--probe-config", type=Path, default=None,
        help="YAML with 'name' and 'clips' (e.g. configs/training/probe_gloved.yaml): "
             "whole train clips moved to images/<name> as a separate eval set.",
    )
    args = ap.parse_args()

    val_sessions = {s.strip() for s in args.val_sessions.split(",") if s.strip()}
    probe_clips: set[str] = set()
    probe_name = "probe"
    if args.probe_config is not None:
        import yaml
        pc = yaml.safe_load(args.probe_config.read_text(encoding="utf-8"))
        probe_clips, probe_name = set(pc["clips"]), pc["name"]
    summary = split(args.dataset_dir, args.manifest, val_sessions, probe_clips, probe_name)

    print(f"val sessions        : {sorted(val_sessions)}")
    print(f"frames moved to val : {summary['moved_to_val']}")
    print(f"frames kept in train: {summary['kept_in_train']}")
    print(f"val frames per session: {summary['val_session_counts']}")
    print("train class counts:")
    for c in CLASS_ORDER:
        print(f"  {c:14s} {summary['train_class_counts'].get(c, 0)}")
    print("val class counts:")
    for c in CLASS_ORDER:
        n = summary["val_class_counts"].get(c, 0)
        flag = "  <-- ZERO examples in val, metric for this class will be meaningless" if n == 0 else ""
        print(f"  {c:14s} {n}{flag}")
    if probe_clips:
        print(f"probe '{probe_name}': {len(probe_clips)} clips, {summary['moved_to_probe']} frames "
              f"(SAME session as train -- report separately, overestimates)")
        for c in CLASS_ORDER:
            print(f"  {c:14s} {summary['probe_class_counts'].get(c, 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
