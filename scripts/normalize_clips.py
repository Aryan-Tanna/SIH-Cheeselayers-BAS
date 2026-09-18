#!/usr/bin/env python3
"""Phase 1 script — written in phase 0, NOT run (clips/ is empty).

Normalizes every clip in clips/ into clips_norm/:
  - detect variable frame rate, transcode to CFR 30 (ffmpeg -vsync cfr -r 30 -an)
  - detect portrait orientation and rotate to landscape, recording the
    rotation applied (so downstream rack-space geometry can account for it)
  - strip audio
  - print a per-clip change table

Requires ffmpeg/ffprobe on PATH. No clip ID, filename, or timestamp may
appear anywhere under src/ (anti-overfitting rule) — this script writes
to manifest/, never to src/.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

CLIPS_DIR = Path("clips")
CLIPS_NORM_DIR = Path("clips_norm")
MANIFEST_DIR = Path("manifest")
TARGET_FPS = 30


@dataclass
class ClipChange:
    filename: str
    src_fps_mode: str  # "cfr" | "vfr"
    src_width: int
    src_height: int
    was_portrait: bool
    rotation_deg: int
    transcoded: bool
    error: str | None = None


def ffprobe_json(path: Path) -> dict:
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", "-show_format", str(path),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def detect_vfr(probe: dict) -> bool:
    """A clip is VFR if the declared average frame rate and the
    container's nominal r_frame_rate disagree beyond rounding, or if
    consecutive packet durations vary — ffprobe's avg_frame_rate vs
    r_frame_rate mismatch is a cheap, reliable-enough first signal."""
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    avg = video.get("avg_frame_rate", "0/0")
    r = video.get("r_frame_rate", "0/0")
    return avg != r


def detect_rotation(probe: dict) -> tuple[bool, int]:
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    width, height = video["width"], video["height"]
    tags = video.get("tags", {})
    side_data = video.get("side_data_list", [])
    rotate_tag = int(tags.get("rotate", 0))
    rotate_side = 0
    for sd in side_data:
        if sd.get("side_data_type") == "Display Matrix":
            rotate_side = int(round(sd.get("rotation", 0)))
    rotation = rotate_tag or (-rotate_side % 360)
    is_portrait = height > width
    return is_portrait, rotation


def normalize_one(src: Path, dest: Path) -> ClipChange:
    try:
        probe = ffprobe_json(src)
    except Exception as e:  # noqa: BLE001 - report, don't crash the batch
        return ClipChange(src.name, "unknown", 0, 0, False, 0, False, error=str(e))

    is_vfr = detect_vfr(probe)
    is_portrait, rotation = detect_rotation(probe)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")

    dest.parent.mkdir(parents=True, exist_ok=True)
    vf_filters = ["fps=" + str(TARGET_FPS)]
    if rotation:
        # ffmpeg's transpose: 1=90cw, 2=90ccw. We only need enough
        # granularity to land back in landscape; exact 90/-90 handling
        # is refined once real portrait clips are on hand.
        vf_filters.append("transpose=1" if rotation in (90, -270) else "transpose=2")

    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-vsync", "cfr", "-r", str(TARGET_FPS),
        "-vf", ",".join(vf_filters) if rotation else f"fps={TARGET_FPS}",
        "-an",
        str(dest),
    ]
    subprocess.run(cmd, capture_output=True, check=True)

    return ClipChange(
        filename=src.name,
        src_fps_mode="vfr" if is_vfr else "cfr",
        src_width=video["width"],
        src_height=video["height"],
        was_portrait=is_portrait,
        rotation_deg=rotation,
        transcoded=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips-dir", type=Path, default=CLIPS_DIR)
    ap.add_argument("--out-dir", type=Path, default=CLIPS_NORM_DIR)
    args = ap.parse_args()

    clips = sorted(args.clips_dir.glob("*.mp4"))
    if not clips:
        print(f"No clips found in {args.clips_dir}/ - nothing to normalize.")
        return 0

    changes = [normalize_one(c, args.out_dir / c.name) for c in clips]

    print(f"{'filename':<30} {'fps_mode':<8} {'src_wxh':<12} {'portrait':<9} {'rotation':<9} {'status'}")
    for c in changes:
        status = f"ERROR: {c.error}" if c.error else "ok"
        print(
            f"{c.filename:<30} {c.src_fps_mode:<8} {f'{c.src_width}x{c.src_height}':<12} "
            f"{str(c.was_portrait):<9} {c.rotation_deg:<9} {status}"
        )

    n_vfr = sum(1 for c in changes if c.src_fps_mode == "vfr")
    n_portrait = sum(1 for c in changes if c.was_portrait)
    n_errors = sum(1 for c in changes if c.error)
    print(f"\n{len(changes)} clips: {n_vfr} VFR, {n_portrait} portrait, {n_errors} errors")
    return 1 if n_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
