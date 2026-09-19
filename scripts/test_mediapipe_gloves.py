#!/usr/bin/env python3
"""Phase 1 script — written in phase 0, run in phase 1 against the
5-clip pilot corpus (needs the `vision` extra:
pip install -e .[vision]).

Decision point 2 (see CLAUDE.md "Decision points — STOP AND ASK"):
MediaPipe Hands is trained overwhelmingly on bare skin; white latex
gloves wash out the texture contrast the landmark model relies on.

Runs MediaPipe HandLandmarker over frames split gloved vs bare (from the
`gloves` column in manifest/clips.csv, once a human has corrected the
guessed values — see build_review_sheet.py; if that column still reads
"unimplemented", pass --gloved/--bare explicitly rather than guessing),
and reports detection rate and landmark jitter for each group. Below
85% gloved detection rate, the fallback is YOLO hand boxes + motion
coherence (src/kinematics/grasp.py already only needs a bbox + velocity,
not 21 landmarks, so the fallback does not touch the grasp/drift
definitions — only how the hand position feeding them is produced).

Uses the mediapipe.tasks Python API (HandLandmarker), not the classic
mediapipe.solutions.hands API this script originally targeted --
mediapipe removed mediapipe.solutions and its bundled model starting
partway through the 0.10.x series, and no version with both a bundled
model and a Windows/cp313 wheel exists. The Tasks API requires an
explicit local model file instead of one bundled in the pip wheel; see
models/README.md for exactly which file, its license, and how it was
obtained (downloaded once, vendored into the repo -- never fetched at
run time, per CLAUDE.md's offline requirement).

mediapipe/cv2 are imported lazily, inside functions that need them,
never at module level -- this script must not break `pip install -e .`
on a clean install with no [vision] extra, matching
src/perception/__init__.py's own rule.
"""

from __future__ import annotations

import argparse
import csv
import random
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

FRAMES_DIR = Path("frames")
MANIFEST_PATH = Path("manifest/clips.csv")
MODEL_PATH = Path("models/hand_landmarker.task")
N_FRAMES = 200


@dataclass
class GroupResult:
    label: str
    n_frames: int
    n_detected: int
    jitter_px: float  # mean frame-to-frame landmark displacement, detected frames only

    @property
    def detection_rate(self) -> float:
        return self.n_detected / self.n_frames if self.n_frames else 0.0


def select_frames(
    frames_dir: Path,
    manifest_path: Path,
    n: int,
    seed: int,
    gloved_clip_ids: set[str] | None = None,
    bare_clip_ids: set[str] | None = None,
) -> dict[str, list[Path]]:
    """Splits frames into gloved/bare groups. Explicit gloved_clip_ids/
    bare_clip_ids (from --gloved/--bare) take priority over
    manifest/clips.csv's gloves column -- use them when that column
    still reads "unimplemented" (build_review_sheet.py has no phase-1
    signal for it). A clip that resolves to neither an explicit label
    nor a manifest value of exactly "true"/"false" contributes to
    NEITHER group. The original version of this function put anything
    not exactly "true" into "bare" -- that would have silently
    mislabelled every pilot clip as bare-handed today, since all five
    currently read "unimplemented"."""
    from extract_frames import clip_id_from_frame_filename

    gloves_by_clip: dict[str, str] = {}
    if manifest_path.exists():
        with open(manifest_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                gloves_by_clip[row["clip_id"]] = row.get("gloves", "unknown")

    gloved_clip_ids = gloved_clip_ids or set()
    bare_clip_ids = bare_clip_ids or set()

    all_frames = sorted(frames_dir.glob("*.jpg"))
    gloved, bare = [], []
    for frame in all_frames:
        clip_id = clip_id_from_frame_filename(frame.name)
        if clip_id in gloved_clip_ids:
            gloved.append(frame)
        elif clip_id in bare_clip_ids:
            bare.append(frame)
        else:
            gloves = gloves_by_clip.get(clip_id, "unknown")
            if gloves == "true":
                gloved.append(frame)
            elif gloves == "false":
                bare.append(frame)
            # anything else ("unknown"/"unimplemented"/...): excluded

    rng = random.Random(seed)
    half = n // 2
    # random.sample() returns a shuffled permutation even when the
    # sample size equals the population -- sort back to (clip_id,
    # frame_index) order so run_group()'s jitter calculation sees
    # genuinely adjacent frames, not an arbitrary pairing (see its
    # docstring for why that distinction matters).
    return {
        "gloved": sorted(rng.sample(gloved, min(half, len(gloved)))),
        "bare": sorted(rng.sample(bare, min(half, len(bare)))),
    }


def run_group(label: str, frames: list[Path], model_path: Path) -> GroupResult:
    """`frames` must be in (clip_id, frame_index) order -- see
    select_frames(). Jitter is reset at every clip boundary: frame
    filenames are `{clip_id}_{frame:06d}.jpg` with the index restarting
    at 0 per clip, so "adjacent" entries in an unsorted or cross-clip-
    concatenated list can be unrelated frames from different clips or
    footage minutes apart within the same clip. Measuring displacement
    between those pairs and calling it "landmark jitter" is not a
    temporal-stability signal at all -- it is close to the mean
    landmark distance between two random frames, which is why an
    earlier version of this function reported nearly identical jitter
    for the gloved and bare groups (137.21 vs 137.80 px) despite a
    53-point gap in detection rate: the metric wasn't measuring
    anything related to gloves."""
    import cv2
    import mediapipe as mp
    from mediapipe.tasks.python import vision
    from mediapipe.tasks.python.core.base_options import BaseOptions

    from extract_frames import clip_id_from_frame_filename

    options = vision.HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(model_path)),
        running_mode=vision.RunningMode.IMAGE,
        num_hands=2,
        min_hand_detection_confidence=0.5,
    )
    landmarker = vision.HandLandmarker.create_from_options(options)

    n_detected = 0
    prev_landmarks: list[tuple[float, float]] | None = None
    prev_clip_id: str | None = None
    displacements: list[float] = []

    for frame_path in frames:
        clip_id = clip_id_from_frame_filename(frame_path.name)
        if clip_id != prev_clip_id:
            prev_landmarks = None
            prev_clip_id = clip_id

        image = cv2.imread(str(frame_path))
        if image is None:
            continue
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = landmarker.detect(mp_image)
        if result.hand_landmarks:
            n_detected += 1
            lm = result.hand_landmarks[0]
            h, w = image.shape[:2]
            points = [(p.x * w, p.y * h) for p in lm]
            if prev_landmarks is not None and len(prev_landmarks) == len(points):
                disp = statistics.mean(
                    ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
                    for a, b in zip(points, prev_landmarks)
                )
                displacements.append(disp)
            prev_landmarks = points
        else:
            prev_landmarks = None

    landmarker.close()
    jitter = statistics.mean(displacements) if displacements else 0.0
    return GroupResult(label=label, n_frames=len(frames), n_detected=n_detected, jitter_px=jitter)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames-dir", type=Path, default=FRAMES_DIR)
    ap.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    ap.add_argument("--model", type=Path, default=MODEL_PATH)
    ap.add_argument("--n", type=int, default=N_FRAMES)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--gloved-threshold", type=float, default=0.85)
    ap.add_argument(
        "--gloved", type=str, default="",
        help="comma-separated clip_id list, overrides manifest.csv's gloves column "
             "(use when it still reads 'unimplemented')",
    )
    ap.add_argument(
        "--bare", type=str, default="",
        help="comma-separated clip_id list, overrides manifest.csv's gloves column",
    )
    args = ap.parse_args()

    if not args.model.exists():
        print(
            f"Model not found at {args.model} -- see models/README.md. "
            f"This must be a locally vendored file, never fetched here at run time."
        )
        return 1

    gloved_clip_ids = {c.strip() for c in args.gloved.split(",") if c.strip()}
    bare_clip_ids = {c.strip() for c in args.bare.split(",") if c.strip()}

    groups = select_frames(
        args.frames_dir, args.manifest, args.n, args.seed, gloved_clip_ids, bare_clip_ids
    )
    if not groups["gloved"] and not groups["bare"]:
        print(
            f"No frames found under {args.frames_dir}/, or none resolved to a "
            f"gloved/bare label (checked --gloved/--bare and {args.manifest}'s "
            f"gloves column) - nothing to test."
        )
        return 0

    results = [run_group(label, frames, args.model) for label, frames in groups.items() if frames]

    print(f"{'group':<8} {'n_frames':<9} {'detected':<9} {'rate':<7} jitter_px")
    for r in results:
        print(f"{r.label:<8} {r.n_frames:<9} {r.n_detected:<9} {r.detection_rate:<7.1%} {r.jitter_px:.2f}")

    gloved = next((r for r in results if r.label == "gloved"), None)
    if gloved is not None:
        if gloved.detection_rate < args.gloved_threshold:
            print(
                f"\nGloved detection rate {gloved.detection_rate:.1%} is below the "
                f"{args.gloved_threshold:.0%} threshold - fall back to YOLO hand boxes "
                f"+ motion coherence for gloved hands (see module docstring)."
            )
        else:
            print(f"\nGloved detection rate {gloved.detection_rate:.1%} clears the threshold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
