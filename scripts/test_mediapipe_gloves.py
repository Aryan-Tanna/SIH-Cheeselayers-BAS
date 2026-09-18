#!/usr/bin/env python3
"""Phase 1 script — written in phase 0, NOT run (frames/ is empty, and
this needs the `vision` extra: pip install -e .[vision]).

Decision point 2 (see CLAUDE.md "Decision points — STOP AND ASK"):
MediaPipe Hands is trained overwhelmingly on bare skin; white latex
gloves wash out the texture contrast the landmark model relies on.

Runs MediaPipe Hands over 200 frames split gloved vs bare (from the
`gloves` column in manifest/clips.csv, once a human has corrected the
guessed values — see build_review_sheet.py), and reports detection rate
and landmark jitter for each group. Below 85% gloved detection rate, the
fallback is YOLO hand boxes + motion coherence (src/kinematics/grasp.py
already only needs a bbox + velocity, not 21 landmarks, so the fallback
does not touch the grasp/drift definitions — only how the hand position
feeding them is produced).

mediapipe is imported lazily, inside main(), never at module level —
this script must not break `pip install -e .` on a clean install with
no [vision] extra, matching src/perception/__init__.py's own rule.
"""

from __future__ import annotations

import argparse
import csv
import random
import statistics
from dataclasses import dataclass
from pathlib import Path

FRAMES_DIR = Path("frames")
MANIFEST_PATH = Path("manifest/clips.csv")
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


def select_frames(frames_dir: Path, manifest_path: Path, n: int, seed: int) -> dict[str, list[Path]]:
    gloves_by_clip: dict[str, str] = {}
    if manifest_path.exists():
        with open(manifest_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                gloves_by_clip[row["clip_id"]] = row.get("gloves", "unknown")

    from extract_frames import clip_id_from_frame_filename

    all_frames = sorted(frames_dir.glob("*.jpg"))
    gloved, bare = [], []
    for frame in all_frames:
        clip_id = clip_id_from_frame_filename(frame.name)
        gloves = gloves_by_clip.get(clip_id, "unknown")
        (gloved if gloves == "true" else bare).append(frame)

    rng = random.Random(seed)
    half = n // 2
    return {
        "gloved": rng.sample(gloved, min(half, len(gloved))),
        "bare": rng.sample(bare, min(half, len(bare))),
    }


def run_group(label: str, frames: list[Path]) -> GroupResult:
    import cv2
    import mediapipe as mp

    hands = mp.solutions.hands.Hands(static_image_mode=True, max_num_hands=2, min_detection_confidence=0.5)

    n_detected = 0
    prev_landmarks: list[tuple[float, float]] | None = None
    displacements: list[float] = []

    for frame_path in frames:
        image = cv2.imread(str(frame_path))
        if image is None:
            continue
        result = hands.process(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        if result.multi_hand_landmarks:
            n_detected += 1
            lm = result.multi_hand_landmarks[0]
            h, w = image.shape[:2]
            points = [(p.x * w, p.y * h) for p in lm.landmark]
            if prev_landmarks is not None and len(prev_landmarks) == len(points):
                disp = statistics.mean(
                    ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
                    for a, b in zip(points, prev_landmarks)
                )
                displacements.append(disp)
            prev_landmarks = points
        else:
            prev_landmarks = None

    hands.close()
    jitter = statistics.mean(displacements) if displacements else 0.0
    return GroupResult(label=label, n_frames=len(frames), n_detected=n_detected, jitter_px=jitter)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames-dir", type=Path, default=FRAMES_DIR)
    ap.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    ap.add_argument("--n", type=int, default=N_FRAMES)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--gloved-threshold", type=float, default=0.85)
    args = ap.parse_args()

    groups = select_frames(args.frames_dir, args.manifest, args.n, args.seed)
    if not groups["gloved"] and not groups["bare"]:
        print(f"No frames found under {args.frames_dir}/ - nothing to test.")
        return 0

    results = [run_group(label, frames) for label, frames in groups.items() if frames]

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
