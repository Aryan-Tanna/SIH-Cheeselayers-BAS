#!/usr/bin/env python3
"""Next labelling batch aimed at the lid <-> same-colour module confusion.

v5 test confusion matrix (S01+S03 + test_s00): 25 true red_lid predicted
red_module, 15 the other way; yellow 9 / 12. In S05 video the cap held in
a hand also gets a second, low-confidence module box. This picks the
unlabelled frames (v5 pre-labels, runs/autolabel_predictions_v5) where
that confusion shows, by GEOMETRY of the predicted boxes, not only low
confidence:

  dup      two module boxes (or two lid boxes) of one colour: there is
           ONE jar per colour, so one box is the other part            +3
  cap_off  a lid box lying off every same-colour module box: the cap in
           a hand -- the state behind the early "lid closed" misses   +2
  lone_lid a lid box with no module of its colour in frame (often the
           jar itself called a lid)                                    +1.5
  unsure   lowest lid/module confidence in 0.25-0.5                   +1..+1.5

NOT used: lid/module overlap. From the top-down camera a cap on its jar
covers most of it -- in the human labels 49% of correct cap/jar pairs
have IoU >= 0.5 and 9% >= 0.9 -- so overlap cannot tell a confused box
from a closed jar.

Only TRAINING sessions (never S01/S03/S05 or the test_s00 clips: labelling
those would leak the test set into training), never frames already in the
v5 dataset. At most --per-clip frames per clip (neighbouring frames are
near-copies). Writes, in rank order: priority.csv (why each frame), a
Label Studio import JSON with v5's boxes pre-filled, and a contact sheet.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import yaml

CLASS_ORDER = ["case_open", "case_closed", "red_module", "yellow_module",
               "red_lid", "yellow_lid", "hand_gloved", "hand_bare"]
PAIRS = {"red": ("red_lid", "red_module"), "yellow": ("yellow_lid", "yellow_module")}
TEST_SESSIONS = {"S01", "S03", "S05"}


def aabb(v: list[float]) -> tuple[float, float, float, float]:
    xs, ys = v[0::2], v[1::2]
    return min(xs), min(ys), max(xs), max(ys)


def inter(a, b) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def area(a) -> float:
    return max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])


def score_frame(boxes: list[tuple[str, float, tuple]]) -> tuple[float, list[str]]:
    """boxes: (class, conf, aabb in normalised coords). Overlap fractions and
    IoU are invariant to scaling x and y separately, so normalised is fine."""
    score, why = 0.0, []
    for colour, (lid_c, mod_c) in PAIRS.items():
        lids = [b for b in boxes if b[0] == lid_c]
        mods = [b for b in boxes if b[0] == mod_c]
        if len(mods) > 1 or len(lids) > 1:
            score += 3
            why.append(f"dup:{colour}")
        if mods:
            for l in lids:
                if all(inter(l[2], m[2]) / max(area(l[2]), 1e-12) < 0.1 for m in mods):
                    score += 2
                    why.append(f"cap_off:{colour}")
                    break
        elif lids:
            score += 1.5
            why.append(f"lone_lid:{colour}")
        confs = [b[1] for b in lids + mods]
        if confs and min(confs) < 0.5:
            score += 1 + (0.5 - min(confs)) * 2
            why.append(f"unsure:{colour}:{min(confs):.2f}")
    return score, why


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred-dir", type=Path, default=Path("runs/autolabel_predictions_v5"))
    ap.add_argument("--manifest", type=Path, default=Path("manifest/clips.csv"))
    ap.add_argument("--test-clips", type=Path, default=Path("configs/training/split_v5_s00_test.yaml"))
    ap.add_argument("--dataset", type=Path, default=Path("runs/yolo_dataset_v5"),
                    help="frames already labelled (any split) are skipped")
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--per-clip", type=int, default=4)
    ap.add_argument("--out-dir", type=Path, default=Path("runs/label_batch14"))
    ap.add_argument("--sheet", type=int, default=24, help="frames on the contact sheet (0 = none)")
    args = ap.parse_args()

    session = {r["clip_id"]: r["session_id"] for r in csv.DictReader(open(args.manifest, encoding="utf-8"))}
    test_clips = set(yaml.safe_load(args.test_clips.read_text(encoding="utf-8"))["clips"])
    labelled = {p.stem for p in args.dataset.glob("images/*/*")}

    cands, skipped = [], Counter()
    for txt in sorted((args.pred_dir / "labels").glob("*.txt")):
        clip = txt.stem.rsplit("_", 1)[0]
        sess = session.get(clip, "?")
        if sess in TEST_SESSIONS or sess == "?" or clip in test_clips:
            skipped["test session / test clip / unknown"] += 1
            continue
        if txt.stem in labelled:
            skipped["already labelled"] += 1
            continue
        boxes = []
        for line in txt.read_text(encoding="utf-8").splitlines():
            p = line.split()
            if p:
                boxes.append((CLASS_ORDER[int(p[0])], float(p[-1]), aabb([float(v) for v in p[1:9]])))
        s, why = score_frame(boxes)
        if s > 0:
            cands.append((s, txt.stem, clip, sess, why))

    cands.sort(key=lambda c: (-c[0], c[1]))
    per_clip: Counter = Counter()
    picked = []
    for c in cands:
        if per_clip[c[2]] < args.per_clip:
            per_clip[c[2]] += 1
            picked.append(c)
        if len(picked) >= args.n:
            break

    args.out_dir.mkdir(parents=True, exist_ok=True)
    tiers = lambda i: 1 if i < args.n // 3 else 2 if i < 2 * args.n // 3 else 3  # noqa: E731
    with open(args.out_dir / "priority.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rank", "tier", "filename", "session_id", "score", "reasons"])
        for i, (s, stem, clip, sess, why) in enumerate(picked, 1):
            w.writerow([i, tiers(i - 1), f"{stem}.jpg", sess, f"{s:.2f}", " ".join(why)])

    ls = json.loads((args.pred_dir / "label_studio_predictions.json").read_text(encoding="utf-8"))
    by_name = {Path(t["data"]["image"]).name: t for t in ls}
    tasks = [by_name[f"{c[1]}.jpg"] for c in picked if f"{c[1]}.jpg" in by_name]
    (args.out_dir / "import.json").write_text(json.dumps(tasks, indent=1), encoding="utf-8")

    if args.sheet:
        make_sheet(picked[: args.sheet], args.pred_dir, args.out_dir / "top_sheet.jpg")

    reasons = Counter(r.split(":")[0] + ":" + r.split(":")[1] for c in picked for r in c[4])
    print(f"candidates {len(cands)}  picked {len(picked)} from {len(per_clip)} clips  skipped {dict(skipped)}")
    print(f"sessions: {dict(Counter(c[3] for c in picked))}")
    print("reasons in the batch: " + ", ".join(f"{k} {v}" for k, v in reasons.most_common()))
    print(f"-> {args.out_dir / 'priority.csv'}\n-> {args.out_dir / 'import.json'} ({len(tasks)} tasks)")
    return 0


def make_sheet(picked: list, pred_dir: Path, out: Path) -> None:
    import cv2
    import numpy as np

    col = {"red_lid": (200, 60, 255), "red_module": (40, 40, 255),
           "yellow_lid": (0, 150, 255), "yellow_module": (0, 230, 255)}
    tiles = []
    for i, (s, stem, clip, sess, why) in enumerate(picked, 1):
        img = cv2.imread(str(Path("frames") / f"{stem}.jpg"))
        if img is None:
            continue
        h, w = img.shape[:2]
        for line in (pred_dir / "labels" / f"{stem}.txt").read_text(encoding="utf-8").splitlines():
            p = line.split()
            cls = CLASS_ORDER[int(p[0])]
            if cls in col:
                pts = (np.array([float(v) for v in p[1:9]]).reshape(4, 2) * [w, h]).astype(np.int32)
                cv2.polylines(img, [pts], True, col[cls], 4)
                cv2.putText(img, f"{cls} {float(p[-1]):.2f}", tuple(int(v) for v in pts.min(0)),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.2, col[cls], 3)
        t = cv2.resize(img, (480, int(480 * h / w)))
        t = cv2.copyMakeBorder(t, 0, 270 - t.shape[0], 0, 0, cv2.BORDER_CONSTANT) if t.shape[0] < 270 else t[:270]
        cv2.putText(t, f"#{i} {stem}", (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
        cv2.putText(t, " ".join(why)[:70], (4, 262), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
        tiles.append(t)
    while len(tiles) % 4:
        tiles.append(np.zeros_like(tiles[0]))
    cv2.imwrite(str(out), np.vstack([np.hstack(tiles[r:r + 4]) for r in range(0, len(tiles), 4)]))


if __name__ == "__main__":
    raise SystemExit(main())
