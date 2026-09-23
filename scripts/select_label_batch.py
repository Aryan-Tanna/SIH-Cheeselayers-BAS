#!/usr/bin/env python3
"""Pick the next labelling batch from autolabel pre-labels, aimed at the
classes that are weak, and write a Label Studio import JSON for just
those frames.

Two pools, never mixed:
  train pool  (--train-sessions, e.g. S00) -> frames that grow training
  val pool    (--val-sessions,  e.g. S01..S03) -> frames that make the
              held-out metric trustworthy (more val instances of rare
              classes); they do NOT improve the model.

Within each pool, for each target class, frames are taken in ASCENDING
order of the model's lowest confidence on a box of that class (the
frames the model is least sure about first), at most --per-clip frames
per clip per class so one clip can't fill the quota with near-identical
frames.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

CLASS_ORDER = [
    "case_open", "case_closed", "red_module", "yellow_module",
    "red_lid", "yellow_lid", "hand_gloved", "hand_bare",
]


def clip_id_from_frame_filename(frame_filename: str) -> str:
    return Path(frame_filename).stem.rsplit("_", 1)[0]


def per_class_min_conf(labels_dir: Path) -> dict[str, dict[str, float]]:
    """frame filename -> {class: lowest conf of that class's boxes}"""
    out: dict[str, dict[str, float]] = {}
    for txt in labels_dir.glob("*.txt"):
        confs: dict[str, float] = {}
        for line in txt.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if not parts:
                continue
            cls = CLASS_ORDER[int(parts[0])]
            confs[cls] = min(confs.get(cls, 1.0), float(parts[-1]))
        out[txt.stem + ".jpg"] = confs
    return out


def select(confs: dict[str, dict[str, float]], sessions_by_clip: dict[str, str],
           sessions: set[str], quotas: dict[str, int], per_clip: int,
           taken: set[str]) -> list[dict]:
    picked: list[dict] = []
    for cls, quota in quotas.items():
        cands = sorted(
            (c[cls], f) for f, c in confs.items()
            if cls in c and sessions_by_clip.get(clip_id_from_frame_filename(f)) in sessions
        )
        per_clip_count: Counter = Counter()
        n = 0
        for conf, f in cands:
            if n >= quota:
                break
            clip = clip_id_from_frame_filename(f)
            if f in taken or per_clip_count[clip] >= per_clip:
                continue
            taken.add(f)
            per_clip_count[clip] += 1
            n += 1
            picked.append({"filename": f, "target_class": cls, "target_conf": round(conf, 3),
                           "session_id": sessions_by_clip[clip],
                           "all_classes": ",".join(sorted(confs[f]))})
    return picked


def parse_quotas(spec: str) -> dict[str, int]:
    q = {}
    for item in spec.split(","):
        cls, n = item.split("=")
        if cls not in CLASS_ORDER:
            raise SystemExit(f"unknown class '{cls}'")
        q[cls] = int(n)
    return q


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred-dir", type=Path, default=Path("runs/autolabel_predictions_v4"))
    ap.add_argument("--manifest", type=Path, default=Path("manifest/clips.csv"))
    ap.add_argument("--train-sessions", default="S00")
    ap.add_argument("--val-sessions", default="S01,S02,S03")
    ap.add_argument("--train-quotas", default="yellow_module=20,yellow_lid=20,red_lid=20,case_closed=20")
    ap.add_argument("--val-quotas", default="case_closed=15,yellow_lid=15,yellow_module=10,red_lid=10")
    ap.add_argument("--per-clip", type=int, default=3)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()

    with open(args.manifest, newline="", encoding="utf-8") as f:
        sessions_by_clip = {r["clip_id"]: r["session_id"] for r in csv.DictReader(f)}
    confs = per_class_min_conf(args.pred_dir / "labels")
    taken: set[str] = set()
    rows = []
    for pool, sess, quotas in [("train", args.train_sessions, args.train_quotas),
                               ("val", args.val_sessions, args.val_quotas)]:
        for r in select(confs, sessions_by_clip, set(sess.split(",")),
                        parse_quotas(quotas), args.per_clip, taken):
            rows.append({"pool": pool, **r})

    # Output in review_priority.csv order: ascending min_conf over ALL the
    # frame's boxes, per pool -- Label Studio shows tasks in import order,
    # so the least-certain frames come up first.
    with open(args.pred_dir / "review_priority.csv", newline="", encoding="utf-8") as f:
        prio = {r["filename"]: r for r in csv.DictReader(f)}
    for r in rows:
        pr = prio[r["filename"]]
        r.update(n_detections=pr["n_detections"], min_conf=pr["min_conf"],
                 mean_conf=pr["mean_conf"], has_lid_detection=pr["has_lid_detection"])
    rows.sort(key=lambda r: (r["pool"] != "train", float(r["min_conf"])))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    with open(args.out_dir / "review_priority.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    tasks = json.loads((args.pred_dir / "label_studio_predictions.json").read_text(encoding="utf-8"))
    by_name = {Path(t["data"]["image"]).name: t for t in tasks}
    for pool in ("train", "val"):
        sub = [by_name[r["filename"]] for r in rows if r["pool"] == pool]
        (args.out_dir / f"import_{pool}.json").write_text(json.dumps(sub), encoding="utf-8")

    print(f"{'pool':6s}{'target_class':15s}{'frames':>7s}{'clips':>7s}{'conf lo':>9s}{'conf hi':>9s}")
    groups = defaultdict(list)
    for r in rows:
        groups[(r["pool"], r["target_class"])].append(r)
    for (pool, cls), g in groups.items():
        cf = [r["target_conf"] for r in g]
        clips = {clip_id_from_frame_filename(r["filename"]) for r in g}
        print(f"{pool:6s}{cls:15s}{len(g):7d}{len(clips):7d}{min(cf):9.3f}{max(cf):9.3f}")
    for pool in ("train", "val"):
        n = sum(r["pool"] == pool for r in rows)
        print(f"{pool} total: {n} frames -> {args.out_dir / f'import_{pool}.json'}")
    print(f"sessions: {dict(Counter(r['session_id'] for r in rows))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
