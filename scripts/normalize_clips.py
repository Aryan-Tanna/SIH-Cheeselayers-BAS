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

Rotation decision, in priority order:
  1. manifest/rotation.csv's rotate_deg for this clip_id, but ONLY if
     that row's `confirmed` column is also filled in (this file is
     written fresh by THIS script every run, then re-read at the top of
     the next run -- the confirmed gate stops a freshly-computed
     "defaulted" guess from silently round-tripping back in as if a
     human had approved it on the very next run; see
     _read_rotation_overrides()). A human confirms by editing that file
     directly.
  2. A real rotation tag (EXIF `rotate` or Display Matrix side-data),
     normalized into {0,90,180,270}.
  3. A clip detected as portrait with no tag: DEFAULT to 90 clockwise,
     flagged "defaulted, verify" in the printed table -- this is a
     guess, not a detection, and must be visually confirmed in review.
  4. Landscape with no tag: 0, nothing to flag.

ffmpeg's own `-autorotate` (default on) can insert its own rotate filter
from the same tag/side-data BEFORE our filtergraph ever runs, which would
double-rotate a tagged clip if we then apply our own transpose on top of
what ffmpeg already did silently. We pass `-noautorotate` on the input
so our own decision above is the only rotation ever applied, and we
verify the actual output dimensions afterward as a second, independent
check (see _verify_output_dimensions()) in case that assumption is ever
wrong for some container/codec combination.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

CLIPS_DIR = Path("clips")
CLIPS_NORM_DIR = Path("clips_norm")
MANIFEST_DIR = Path("manifest")
ROTATION_MANIFEST_PATH = MANIFEST_DIR / "rotation.csv"
TARGET_FPS = 30
VALID_ROTATIONS = (0, 90, 180, 270)


@dataclass
class ClipChange:
    filename: str
    src_fps_mode: str  # "cfr" | "vfr"
    src_width: int
    src_height: int
    was_portrait: bool
    tag_rotation_deg: int  # raw detected tag/side-data value, 0 if none
    rotate_deg: int  # the value actually applied to the transcode
    rotation_source: str  # "override" | "tag" | "defaulted" | "none"
    transcoded: bool
    dim_warning: str | None = None
    error: str | None = None


def ffprobe_json(path: Path) -> dict:
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", "-show_format", str(path),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def _parse_rate(rate: str) -> float:
    num, _, den = rate.partition("/")
    den = den or "1"
    try:
        d = float(den)
        return float(num) / d if d else 0.0
    except ValueError:
        return 0.0


# Relative tolerance for "disagree beyond rounding." avg_frame_rate is
# computed from actual frame_count/duration and essentially never lands
# on an exact match to the declared nominal r_frame_rate even for
# genuinely CFR footage -- e.g. a real 30fps CFR clip measured at
# 30.0064 (observed on real pilot footage, all well under 0.1%) against
# a declared 30/1. A real VFR clip (frames genuinely dropped/duplicated)
# produces a much larger disagreement than encoder rounding noise -- see
# tests/test_normalize_clips.py for the measured margin.
_VFR_RELATIVE_TOLERANCE = 0.01


def detect_vfr(probe: dict) -> bool:
    """A clip is VFR if the declared average frame rate and the
    container's nominal r_frame_rate disagree beyond rounding, or if
    consecutive packet durations vary — ffprobe's avg_frame_rate vs
    r_frame_rate mismatch is a cheap, reliable-enough first signal.
    Exact equality is too strict: avg_frame_rate is a computed ratio
    (frame_count/duration) that almost never exactly equals the
    declared nominal rate even on genuinely CFR footage, so it needs a
    numeric tolerance, not string equality (see _VFR_RELATIVE_TOLERANCE)."""
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    avg = _parse_rate(video.get("avg_frame_rate", "0/0"))
    r = _parse_rate(video.get("r_frame_rate", "0/0"))
    if r == 0:
        return avg != 0
    return abs(avg - r) / r > _VFR_RELATIVE_TOLERANCE


def detect_rotation(probe: dict) -> tuple[bool, int]:
    """Returns (is_portrait, tag_rotation_deg). tag_rotation_deg is 0
    when no EXIF rotate tag and no Display Matrix side-data are present
    -- that is NOT the same thing as "confirmed no rotation needed": a
    portrait clip with tag_rotation_deg == 0 still needs decide_rotation()
    to apply the defaulting rule."""
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
    return is_portrait, rotation % 360


def _read_rotation_overrides(path: Path) -> dict[str, int]:
    """Human-CONFIRMED per-clip rotate_deg values from a PRIOR run's
    manifest/rotation.csv. This script overwrites that file fresh every
    run, so it must distinguish "a human reviewed and confirmed this
    value" from "this script itself wrote this value last run" -- a row
    is only honored as an override if its `confirmed` column is
    non-blank. Without that distinction, EVERY clip's freshly-decided
    value (including an untouched "defaulted" guess) would round-trip
    back in as if a human had approved it on the very next run, silently
    turning "defaulted, verify" into "override" with nobody ever having
    reviewed anything. Blank rotate_deg or blank confirmed are both
    ignored -- same "blank means not yet reviewed" convention as every
    other human-editable column in this project (session_id, notes)."""
    overrides: dict[str, int] = {}
    if not path.exists():
        return overrides
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if not (row.get("confirmed") or "").strip():
                continue
            raw = (row.get("rotate_deg") or "").strip()
            if not raw:
                continue
            try:
                deg = int(raw)
            except ValueError:
                continue
            if deg in VALID_ROTATIONS:
                overrides[row["clip_id"]] = deg
    return overrides


def decide_rotation(
    clip_id: str, is_portrait: bool, tag_rotation_deg: int, overrides: dict[str, int]
) -> tuple[int, str]:
    """Returns (rotate_deg, source). Priority: human override > a real
    rotation tag > (portrait, no tag: default 90 clockwise, needs
    verification) > 0 (landscape, nothing to do)."""
    if clip_id in overrides:
        return overrides[clip_id], "override"
    if tag_rotation_deg in (90, 180, 270):
        return tag_rotation_deg, "tag"
    if is_portrait:
        return 90, "defaulted"
    return 0, "none"


def _transpose_filters(rotate_deg: int) -> list[str]:
    if rotate_deg == 90:
        return ["transpose=1"]  # 90 clockwise
    if rotate_deg == 270:
        return ["transpose=2"]  # 90 counter-clockwise
    if rotate_deg == 180:
        return ["hflip", "vflip"]
    return []


def _verify_output_dimensions(dest: Path, src_width: int, src_height: int, rotate_deg: int) -> str | None:
    """After transcode, confirm the OUTPUT dimensions actually match
    what rotate_deg should have produced. Catches ffmpeg auto-rotating
    despite -noautorotate (or any other silent mismatch between our
    rotation decision and what actually landed in clips_norm/) rather
    than trusting the ffmpeg command we issued reflects the pixels we
    got. Returns None if the dimensions match."""
    probe = ffprobe_json(dest)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    out_w, out_h = video["width"], video["height"]
    if rotate_deg in (90, 270):
        expected_w, expected_h = src_height, src_width
    else:
        expected_w, expected_h = src_width, src_height
    if (out_w, out_h) != (expected_w, expected_h):
        return (
            f"UNEXPECTED OUTPUT DIMS {out_w}x{out_h} (expected {expected_w}x{expected_h} "
            f"for rotate_deg={rotate_deg}) - possible ffmpeg auto-rotate interaction, verify manually"
        )
    return None


def normalize_one(src: Path, dest: Path, overrides: dict[str, int]) -> ClipChange:
    try:
        probe = ffprobe_json(src)
    except Exception as e:  # noqa: BLE001 - report, don't crash the batch
        return ClipChange(src.name, "unknown", 0, 0, False, 0, 0, "none", False, error=str(e))

    is_vfr = detect_vfr(probe)
    is_portrait, tag_rotation_deg = detect_rotation(probe)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    src_width, src_height = video["width"], video["height"]

    rotate_deg, rotation_source = decide_rotation(src.stem, is_portrait, tag_rotation_deg, overrides)

    dest.parent.mkdir(parents=True, exist_ok=True)
    vf_filters = [f"fps={TARGET_FPS}"] + _transpose_filters(rotate_deg)

    cmd = [
        "ffmpeg", "-y", "-noautorotate", "-i", str(src),
        "-vsync", "cfr", "-r", str(TARGET_FPS),
        "-vf", ",".join(vf_filters),
        "-an",
        str(dest),
    ]
    subprocess.run(cmd, capture_output=True, check=True)

    dim_warning = _verify_output_dimensions(dest, src_width, src_height, rotate_deg)

    return ClipChange(
        filename=src.name,
        src_fps_mode="vfr" if is_vfr else "cfr",
        src_width=src_width,
        src_height=src_height,
        was_portrait=is_portrait,
        tag_rotation_deg=tag_rotation_deg,
        rotate_deg=rotate_deg,
        rotation_source=rotation_source,
        transcoded=True,
        dim_warning=dim_warning,
    )


def _write_rotation_manifest(changes: list[ClipChange], path: Path) -> None:
    """`confirmed` is only carried forward for rows THIS run actually
    sourced from a confirmed override -- see _read_rotation_overrides()'s
    docstring for why a freshly-computed "defaulted" or "tag" value must
    NOT be written back as confirmed. A human confirms a row by editing
    this file directly (fill in the `confirmed` column, e.g. "yes")."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["clip_id", "rotate_deg", "source", "confirmed"])
        writer.writeheader()
        for c in changes:
            if c.error:
                continue
            writer.writerow({
                "clip_id": Path(c.filename).stem,
                "rotate_deg": c.rotate_deg,
                "source": c.rotation_source,
                "confirmed": "yes" if c.rotation_source == "override" else "",
            })


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips-dir", type=Path, default=CLIPS_DIR)
    ap.add_argument("--out-dir", type=Path, default=CLIPS_NORM_DIR)
    ap.add_argument("--rotation-manifest", type=Path, default=ROTATION_MANIFEST_PATH)
    args = ap.parse_args()

    clips = sorted(args.clips_dir.glob("*.mp4"))
    if not clips:
        print(f"No clips found in {args.clips_dir}/ - nothing to normalize.")
        return 0

    overrides = _read_rotation_overrides(args.rotation_manifest)
    changes = [normalize_one(c, args.out_dir / c.name, overrides) for c in clips]
    _write_rotation_manifest(changes, args.rotation_manifest)

    print(
        f"{'filename':<30} {'fps_mode':<8} {'src_wxh':<12} {'portrait':<9} "
        f"{'rotate_deg':<10} {'source':<10} status"
    )
    for c in changes:
        status = f"ERROR: {c.error}" if c.error else "ok"
        if c.dim_warning:
            status = c.dim_warning
        note = "defaulted, verify" if c.rotation_source == "defaulted" else c.rotation_source
        print(
            f"{c.filename:<30} {c.src_fps_mode:<8} {f'{c.src_width}x{c.src_height}':<12} "
            f"{str(c.was_portrait):<9} {c.rotate_deg:<10} {note:<10} {status}"
        )

    n_vfr = sum(1 for c in changes if c.src_fps_mode == "vfr")
    n_portrait = sum(1 for c in changes if c.was_portrait)
    n_defaulted = sum(1 for c in changes if c.rotation_source == "defaulted")
    n_warnings = sum(1 for c in changes if c.dim_warning)
    n_errors = sum(1 for c in changes if c.error)
    print(
        f"\n{len(changes)} clips: {n_vfr} VFR, {n_portrait} portrait, "
        f"{n_defaulted} rotation defaulted (verify in review), "
        f"{n_warnings} dimension warnings, {n_errors} errors"
    )
    print(f"rotation manifest written to {args.rotation_manifest} - edit rotate_deg there to override on next run")
    return 1 if n_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
