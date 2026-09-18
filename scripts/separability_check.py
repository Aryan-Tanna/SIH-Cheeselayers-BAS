#!/usr/bin/env python3
"""Phase 1 script — written in phase 0, NOT run (frames/ is empty).

Decision point 1 (see CLAUDE.md "Decision points — STOP AND ASK"):
pulls candidate-ambiguous frames into a contact sheet to answer,
empirically, before committing to the detector class list:

  - is `module_in_case` visually separable from `module_free`, or is
    the module too often occluded at the rim?
  - is `case_half_open` reliable, or should lid angle be derived
    geometrically instead of as its own class?

"Ambiguous" here means frames sampled near a state transition (a module
close to the container rim, a lid at an intermediate angle) rather than
a random sample — that is where a class boundary actually gets tested.

Selection strategy, in priority order:
  1. Frames from clips flagged with 'transition' or 'occluded' in
     manifest/clips.csv's notes column, once a human has annotated
     approximate transition timestamps there. Highest-signal option,
     but requires that annotation pass to have happened.
  2. Otherwise: dense sampling from the MIDDLE THIRD of each clip's kept-
     frame sequence, evenly split across clips. In-case/out-of-case
     ambiguity happens while a module is being handled -- concentrated
     mid-clip (open/close bookend a clip), not spread uniformly across
     it -- so a uniform random sample over- represents the
     unambiguous open/close bookends and under-represents exactly the
     frames this check exists to examine. Kept-frame index is used as a
     cheap proxy for elapsed clip time (sampling is constant-fps before
     dedup, so index order tracks time even though dedup drops frames
     unevenly).

  A hand-region/case-region bbox-overlap proxy was considered and
  rejected for phase 1: the only hand-region signal available without a
  trained detector is whole-frame skin-tone thresholding, and that is
  independently measured (see build_review_sheet.py's
  _skin_pixel_fraction() docstring) to false-positive on this corpus's
  wood-grain table background and white gloves -- not reliable enough to
  trust for frame selection either, on the same corpus where it already
  failed for the gloves column. Revisit once a real hand/object detector
  exists.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from collections import defaultdict
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from extract_frames import clip_id_from_frame_filename  # noqa: E402

FRAMES_DIR = Path("frames")
MANIFEST_PATH = Path("manifest/clips.csv")
OUT_DIR = Path("manifest")
N_FRAMES = 40
GRID_COLS = 8


def _flagged_clip_ids(manifest_path: Path) -> set[str]:
    flagged: set[str] = set()
    if not manifest_path.exists():
        return flagged
    with open(manifest_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            notes = row.get("notes", "").lower()
            if "transition" in notes or "occluded" in notes:
                flagged.add(row["clip_id"])
    return flagged


def _middle_third_dense_sample(all_frames: list[Path], n: int, seed: int) -> list[Path]:
    """Evenly split the frame budget across clips, sampling from each
    clip's own middle third (by kept-frame index) rather than pooling
    every clip's frames and sampling uniformly at random -- a uniform
    pool sample is dominated by whichever clips happen to have the most
    kept frames and, within a clip, doesn't preferentially hit the
    handling-heavy middle of the clip at all."""
    by_clip: dict[str, list[Path]] = defaultdict(list)
    for f in all_frames:
        by_clip[clip_id_from_frame_filename(f.name)].append(f)
    for frames in by_clip.values():
        frames.sort()

    clip_ids = sorted(by_clip)
    if not clip_ids:
        return []
    per_clip = max(1, n // len(clip_ids))

    rng = random.Random(seed)
    selected: list[Path] = []
    for clip_id in clip_ids:
        frames = by_clip[clip_id]
        lo, hi = len(frames) // 3, -(-2 * len(frames) // 3)
        middle = frames[lo:hi] or frames  # very short clips: fall back to all of it
        k = min(per_clip, len(middle))
        selected.extend(rng.sample(middle, k))

    # Top up to n, if under budget, from any middle-third frames not
    # already picked (short clips leave slack the longer ones can fill).
    if len(selected) < n:
        chosen = set(selected)
        remaining = []
        for clip_id in clip_ids:
            frames = by_clip[clip_id]
            lo, hi = len(frames) // 3, -(-2 * len(frames) // 3)
            remaining.extend(f for f in (frames[lo:hi] or frames) if f not in chosen)
        top_up = rng.sample(remaining, min(n - len(selected), len(remaining)))
        selected.extend(top_up)

    return selected[:n]


def pick_ambiguous_frames(frames_dir: Path, n: int, seed: int) -> list[Path]:
    all_frames = sorted(frames_dir.glob("*.jpg"))
    if not all_frames:
        return []

    flagged_ids = _flagged_clip_ids(MANIFEST_PATH)
    candidates = [f for f in all_frames if clip_id_from_frame_filename(f.name) in flagged_ids]
    if len(candidates) >= n:
        rng = random.Random(seed)
        return rng.sample(candidates, n)

    return _middle_third_dense_sample(all_frames, n, seed)


def build_contact_sheet(frames: list[Path], out_path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    if not frames:
        return
    thumb_w, thumb_h = 160, 90
    font = ImageFont.load_default()

    # Two-line label (full clip_id, then frame index) so a frame is
    # always traceable back to its source clip regardless of clip_id
    # length or how many clips are in the corpus. The original bug
    # (frame_path.stem[-12:]) sliced a fixed number of TRAILING
    # characters -- for any clip_id longer than the frame-index suffix
    # it silently dropped the clip identity, and two different clips
    # whose names happened to share that tail became indistinguishable
    # (and frame indices restart at 0 per clip, so the index alone
    # doesn't disambiguate either). Line height is measured, not
    # assumed, so this holds for any font/corpus, not just this one.
    probe_bbox = ImageDraw.Draw(Image.new("RGB", (1, 1))).textbbox((0, 0), "Ag", font=font)
    line_h = probe_bbox[3] - probe_bbox[1]
    label_h = 2 * line_h + 6

    rows = -(-len(frames) // GRID_COLS)
    sheet = Image.new("RGB", (thumb_w * GRID_COLS, (thumb_h + label_h) * rows), "white")
    draw = ImageDraw.Draw(sheet)

    for i, frame_path in enumerate(frames):
        col, row = i % GRID_COLS, i // GRID_COLS
        clip_id = clip_id_from_frame_filename(frame_path.name)
        frame_idx = frame_path.stem.rsplit("_", 1)[-1]
        with Image.open(frame_path) as img:
            thumb = img.resize((thumb_w, thumb_h))
        y = row * (thumb_h + label_h)
        sheet.paste(thumb, (col * thumb_w, y + label_h))
        draw.text((col * thumb_w + 2, y), clip_id, fill="black", font=font)
        draw.text((col * thumb_w + 2, y + line_h + 2), f"#{frame_idx}", fill="black", font=font)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames-dir", type=Path, default=FRAMES_DIR)
    ap.add_argument("--n", type=int, default=N_FRAMES)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--out", type=Path, default=OUT_DIR / "separability_check.png")
    args = ap.parse_args()

    frames = pick_ambiguous_frames(args.frames_dir, args.n, args.seed)
    if not frames:
        print(f"No frames found in {args.frames_dir}/ - nothing to check.")
        return 0

    flagged_ids = _flagged_clip_ids(MANIFEST_PATH)
    strategy = "annotated transition/occluded notes" if flagged_ids else "dense middle-third-per-clip sample"

    build_contact_sheet(frames, args.out)
    print(f"wrote {args.out} ({len(frames)} candidate-ambiguous frames, selection: {strategy})")
    print(
        "Review manually for: (1) module_in_case vs module_free separability "
        "at the container rim, (2) case_half_open reliability vs deriving "
        "lid angle geometrically. Report before committing to the detector "
        "class list."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
