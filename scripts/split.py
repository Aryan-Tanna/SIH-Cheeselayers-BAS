#!/usr/bin/env python3
"""Phase 1 script — written in phase 0, NOT run (manifest/clips.csv does
not exist until build_review_sheet.py has run and a human has filled in
session_id).

Splits manifest/clips.csv into train/val by session_id, never by frame
or by clip — a session appearing in both splits is a hard failure, not
a warning, since it is exactly the kind of leakage CLAUDE.md's
anti-overfitting rules exist to prevent. Supports holding out an entire
prop_family (e.g. validate generalization to `slab` while training only
on `jar`).
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

MANIFEST_PATH = Path("manifest/clips.csv")


class SplitError(RuntimeError):
    pass


def load_rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def split_by_session(
    rows: list[dict],
    val_fraction: float,
    seed: int,
    holdout_prop_family: str | None,
) -> tuple[list[dict], list[dict]]:
    for row in rows:
        if not row.get("session_id", "").strip():
            raise SplitError(
                f"clip '{row.get('clip_id')}' has no session_id - "
                f"run the review-sheet checkpoint first, not on partially reviewed data"
            )

    sessions = sorted({row["session_id"] for row in rows})
    rng = random.Random(seed)
    rng.shuffle(sessions)

    holdout_sessions: set[str] = set()
    if holdout_prop_family:
        holdout_sessions = {
            row["session_id"] for row in rows if row.get("prop_family") == holdout_prop_family
        }

    remaining = [s for s in sessions if s not in holdout_sessions]
    n_val = max(1, round(len(remaining) * val_fraction)) if remaining else 0
    val_sessions = set(remaining[:n_val]) | holdout_sessions
    train_sessions = set(remaining[n_val:])

    overlap = train_sessions & val_sessions
    if overlap:
        raise SplitError(f"session(s) {sorted(overlap)} landed in both splits - this is a bug, stop")

    train_rows = [r for r in rows if r["session_id"] in train_sessions]
    val_rows = [r for r in rows if r["session_id"] in val_sessions]

    train_only = {r["session_id"] for r in train_rows}
    val_only = {r["session_id"] for r in val_rows}
    if train_only & val_only:
        raise SplitError(f"session(s) {sorted(train_only & val_only)} appear in both splits - hard fail")

    return train_rows, val_rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    ap.add_argument("--val-fraction", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--holdout-prop-family", type=str, default=None)
    ap.add_argument("--out-dir", type=Path, default=Path("manifest"))
    args = ap.parse_args()

    if not args.manifest.exists():
        print(f"{args.manifest} does not exist yet - nothing to split.")
        return 0

    rows = load_rows(args.manifest)
    try:
        train_rows, val_rows = split_by_session(
            rows, args.val_fraction, args.seed, args.holdout_prop_family
        )
    except SplitError as e:
        print(f"SPLIT FAILED: {e}", file=sys.stderr)
        return 1

    for name, split_rows in (("train", train_rows), ("val", val_rows)):
        out_path = args.out_dir / f"{name}.csv"
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(split_rows)

    train_sessions = sorted({r["session_id"] for r in train_rows})
    val_sessions = sorted({r["session_id"] for r in val_rows})
    val_prop_families = sorted({r.get("prop_family", "") for r in val_rows})

    print(f"train: {len(train_rows)} clips across {len(train_sessions)} sessions")
    print(f"val:   {len(val_rows)} clips across {len(val_sessions)} sessions")
    print(f"val sessions: {val_sessions}")
    print(f"val prop families: {val_prop_families}")
    if args.holdout_prop_family:
        print(f"held out prop_family '{args.holdout_prop_family}' entirely into val")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
