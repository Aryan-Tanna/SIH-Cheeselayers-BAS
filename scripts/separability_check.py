#!/usr/bin/env python3
"""Phase 1 script — written in phase 0, NOT run (frames/ is empty).

Decision point 1 (see CLAUDE.md "Decision points — STOP AND ASK"):
pulls 40 ambiguous frames into a contact sheet to answer, empirically,
before committing to the detector class list:

  - is `module_in_case` visually separable from `module_free`, or is
    the module too often occluded at the rim?
  - is `case_half_open` reliable, or should lid angle be derived
    geometrically instead of as its own class?

"Ambiguous" here means frames sampled near a state transition (a module
close to the container rim, a lid at an intermediate angle) rather than
a random sample — that is where a class boundary actually gets tested.
Selection is heuristic-only in phase 1 (based on extracted-frame
ordering/spacing near candidate transition points recorded in
manifest/clips.csv notes, once the human has annotated approximate
transition timestamps); it does not require a trained detector.
"""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

FRAMES_DIR = Path("frames")
MANIFEST_PATH = Path("manifest/clips.csv")
OUT_DIR = Path("manifest")
N_FRAMES = 40
GRID_COLS = 8


def pick_ambiguous_frames(frames_dir: Path, n: int, seed: int) -> list[Path]:
    """Phase 1 placeholder selection: every Nth frame from clips flagged
    with notes containing 'transition' or 'occluded' in clips.csv, falling
    back to a random sample if no such annotations exist yet. Replace
    with a geometry-driven selector (frames where a candidate module
    bbox overlaps the container bbox) once phase 2's detector exists.
    """
    all_frames = sorted(frames_dir.glob("*.jpg"))
    if not all_frames:
        return []

    flagged_stems: set[str] = set()
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                notes = row.get("notes", "").lower()
                if "transition" in notes or "occluded" in notes:
                    flagged_stems.add(row["clip_id"])

    candidates = [f for f in all_frames if any(f.stem.startswith(s) for s in flagged_stems)]
    if len(candidates) < n:
        candidates = all_frames

    rng = random.Random(seed)
    return rng.sample(candidates, min(n, len(candidates)))


def build_contact_sheet(frames: list[Path], out_path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    if not frames:
        return
    thumb_w, thumb_h = 160, 90
    rows = -(-len(frames) // GRID_COLS)
    sheet = Image.new("RGB", (thumb_w * GRID_COLS, thumb_h * rows + 16 * rows), "white")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()

    for i, frame_path in enumerate(frames):
        col, row = i % GRID_COLS, i // GRID_COLS
        with Image.open(frame_path) as img:
            thumb = img.resize((thumb_w, thumb_h))
        y = row * (thumb_h + 16)
        sheet.paste(thumb, (col * thumb_w, y + 16))
        draw.text((col * thumb_w + 2, y), frame_path.stem[-12:], fill="black", font=font)

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

    build_contact_sheet(frames, args.out)
    print(f"wrote {args.out} ({len(frames)} candidate-ambiguous frames)")
    print(
        "Review manually for: (1) module_in_case vs module_free separability "
        "at the container rim, (2) case_half_open reliability vs deriving "
        "lid angle geometrically. Report before committing to the detector "
        "class list."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
