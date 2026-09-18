#!/usr/bin/env python3
"""Phase 1 script — written in phase 0, NOT run (clips_norm/ is empty).

Builds manifest/clips.csv and contact-sheet PNGs (6 evenly spaced
thumbnails per clip, clip_id + duration burned in, max 20 clips/sheet —
3 sheets for the ~60-clip batch 1 corpus) for the human review
checkpoint that gates everything downstream.

Columns are split three ways, exactly per CLAUDE.md:
  - derived  (ffprobe / pixel statistics — trustworthy, no _conf needed)
  - guessed  (prop_family, lid_type, gloves, camera_angle — each carries
    its own *_conf column with the real confidence value, not a blanket
    label). A column phase 1 has no honest way to guess prints
    "unimplemented" with conf 0.0, not "unknown" with conf 0.0 -- the
    two must not look the same in the CSV, since one means "we tried
    and got nothing" and the other means "we didn't try."
  - blank for the human (session_id, notes) — session_id is not
    visually derivable; two clips from different shoots can look
    identical, so it is never guessed.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

CLIPS_NORM_DIR = Path("clips_norm")
MANIFEST_DIR = Path("manifest")
MAX_CLIPS_PER_SHEET = 20
THUMBS_PER_CLIP = 6
STATS_FRAME_WIDTH = 640

DERIVED_COLUMNS = [
    "duration_s", "fps_mode", "orientation", "mean_brightness", "color_temp_k",
    "skin_pixel_fraction",
]
GUESSED_COLUMNS = ["prop_family", "lid_type", "gloves", "camera_angle"]
HUMAN_COLUMNS = ["session_id", "notes"]

UNIMPLEMENTED = "unimplemented"

# Standard YCbCr skin-tone threshold range (Chai & Ngan-style; no ML).
SKIN_Y_MIN = 80
SKIN_CB_RANGE = (77, 127)
SKIN_CR_RANGE = (133, 173)


@dataclass
class ClipRow:
    clip_id: str
    duration_s: float = 0.0
    fps_mode: str = "unknown"
    orientation: str = "unknown"
    mean_brightness: float = 0.0
    color_temp_k: float = 0
    skin_pixel_fraction: float = 0.0
    prop_family: str = UNIMPLEMENTED
    prop_family_conf: float = 0.0
    lid_type: str = UNIMPLEMENTED
    lid_type_conf: float = 0.0
    gloves: str = UNIMPLEMENTED
    gloves_conf: float = 0.0
    camera_angle: str = UNIMPLEMENTED
    camera_angle_conf: float = 0.0
    session_id: str = ""
    notes: str = ""

    def min_guess_confidence(self) -> float:
        return min(self.prop_family_conf, self.lid_type_conf, self.gloves_conf, self.camera_angle_conf)


def _mean_brightness(image) -> float:
    from PIL import ImageStat

    return ImageStat.Stat(image.convert("L")).mean[0]


def _srgb_to_linear(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _color_temperature_k(image) -> float:
    """McCamy's CCT approximation from mean sRGB -> linear RGB -> CIE
    XYZ (standard sRGB primaries) -> xy chromaticity -> McCamy's cubic
    fit. Assumes a single dominant illuminant and ignores scene
    reflectance/colour -- a rough lighting descriptor for a review
    sheet, not a colorimetrically exact measurement."""
    from PIL import ImageStat

    r, g, b = ImageStat.Stat(image).mean[:3]
    rl, gl, bl = _srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b)
    x_ = 0.4124564 * rl + 0.3575761 * gl + 0.1804375 * bl
    y_ = 0.2126729 * rl + 0.7151522 * gl + 0.0721750 * bl
    z_ = 0.0193339 * rl + 0.1191920 * gl + 0.9503041 * bl
    denom = x_ + y_ + z_
    if denom <= 0:
        return 0.0
    x = x_ / denom
    y = y_ / denom
    if (0.1858 - y) == 0:
        return 0.0
    n = (x - 0.3320) / (0.1858 - y)
    return 449 * n**3 + 3525 * n**2 + 6823.3 * n + 5520.33


def _skin_pixel_fraction(image) -> float:
    """Coarse YCbCr skin-tone thresholding, NOT localized to a detected
    hand bounding box -- phase 1 has no hand/pose detector available
    without either using MediaPipe (which would make a gloves GUESS
    circular with test_mediapipe_gloves.py's own MediaPipe detection-
    rate test, since that script uses the gloves column as its
    gloved/bare ground-truth split) or a fine-tuned detector this phase
    doesn't have. Exposed as a DERIVED diagnostic number, not turned
    into a gloved/bare guess -- see the "gloves" comment in derive_row()
    for why: measured against this project's own 5-clip phase-1 pilot
    corpus, this fraction does NOT separate gloved from bare hands
    (visually gloved Dataset1/2 measured 0.157/0.283; visually bare
    Dataset4/5 measured 0.628/0.162 -- Dataset5's bare hands measured
    LOWER skin fraction than either gloved clip). Left in as a real
    number a human reviewer can read, not a signal this script trusts
    enough to categorize on."""
    from PIL import ImageChops

    y, cb, cr = image.convert("YCbCr").split()
    y_mask = y.point(lambda p: 255 if p > SKIN_Y_MIN else 0)
    cb_mask = cb.point(lambda p: 255 if SKIN_CB_RANGE[0] <= p <= SKIN_CB_RANGE[1] else 0)
    cr_mask = cr.point(lambda p: 255 if SKIN_CR_RANGE[0] <= p <= SKIN_CR_RANGE[1] else 0)
    combined = ImageChops.multiply(ImageChops.multiply(y_mask, cb_mask), cr_mask)
    total = combined.width * combined.height
    return combined.histogram()[255] / total if total else 0.0


def _extract_representative_frame(clip_path: Path, duration_s: float, width: int = STATS_FRAME_WIDTH):
    """One frame from the middle of the clip, for pixel statistics.
    Returns None if ffmpeg produced nothing (e.g. duration is 0)."""
    from PIL import Image

    t = duration_s / 2
    cmd = [
        "ffmpeg", "-y", "-ss", str(t), "-i", str(clip_path),
        "-frames:v", "1", "-vf", f"scale={width}:-2",
        "-f", "image2pipe", "-vcodec", "mjpeg", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, check=True)
    if not result.stdout:
        return None
    return Image.open(BytesIO(result.stdout)).convert("RGB")


def derive_row(clip_path: Path) -> ClipRow:
    """ffprobe derivations (duration/fps_mode/orientation) plus real
    pixel-statistics derivations (mean_brightness, color_temp_k,
    skin_pixel_fraction -- all DERIVED, no threshold judgment applied).

    All four GUESSED columns are "unimplemented" here, including
    gloves: a skin-tone-fraction threshold was implemented and measured
    against this project's own 5-clip phase-1 pilot corpus (see
    _skin_pixel_fraction()'s docstring for the actual numbers), and it
    does not separate gloved from bare hands -- a visually bare-handed
    clip measured LOWER skin fraction than two visually gloved clips.
    Shipping a confident "true"/"false" off a threshold that measurably
    doesn't discriminate would be a fabricated guess wearing a
    plausible-looking confidence number, exactly what "unimplemented"
    exists to prevent. prop_family, lid_type, and camera_angle have no
    attempted phase-1 signal at all -- no object/shape classifier
    exists yet, that is explicitly phase 2.
    """
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries",
         "format=duration:stream=width,height,avg_frame_rate,r_frame_rate",
         "-of", "csv=p=0", str(clip_path)],
        capture_output=True, text=True, check=True,
    )
    lines = [l for l in probe.stdout.strip().splitlines() if l]
    duration = 0.0
    orientation = "unknown"
    fps_mode = "unknown"
    # ffprobe emits one CSV line per requested section (stream, then
    # format), never merged onto a single line -- the stream fields and
    # the duration are on DIFFERENT lines, not the head/tail of one.
    for line in lines:
        parts = line.split(",")
        if len(parts) == 4:
            try:
                width, height, avg_fr, r_fr = parts
                orientation = "portrait" if int(height) > int(width) else "landscape"
                fps_mode = "cfr" if avg_fr == r_fr else "vfr"
            except ValueError:
                pass
        elif len(parts) == 1:
            try:
                duration = float(parts[0])
            except ValueError:
                pass

    frame = _extract_representative_frame(clip_path, duration)
    if frame is not None:
        mean_brightness = round(_mean_brightness(frame), 1)
        color_temp_k = round(_color_temperature_k(frame))
        skin_pixel_fraction = round(_skin_pixel_fraction(frame), 4)
    else:
        mean_brightness = 0.0
        color_temp_k = 0
        skin_pixel_fraction = 0.0

    return ClipRow(
        clip_id=clip_path.stem,
        duration_s=round(duration, 1),
        fps_mode=fps_mode,
        orientation=orientation,
        mean_brightness=mean_brightness,
        color_temp_k=color_temp_k,
        skin_pixel_fraction=skin_pixel_fraction,
    )


def build_manifest(clips_dir: Path) -> list[ClipRow]:
    clips = sorted(clips_dir.glob("*.mp4"))
    return [derive_row(c) for c in clips]


def write_manifest_csv(rows: list[ClipRow], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = (
        ["clip_id"]
        + DERIVED_COLUMNS
        + [c for col in GUESSED_COLUMNS for c in (col, f"{col}_conf")]
        + HUMAN_COLUMNS
    )
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow({
                "clip_id": r.clip_id,
                "duration_s": r.duration_s,
                "fps_mode": r.fps_mode,
                "orientation": r.orientation,
                "mean_brightness": r.mean_brightness,
                "color_temp_k": r.color_temp_k,
                "skin_pixel_fraction": r.skin_pixel_fraction,
                "prop_family": r.prop_family, "prop_family_conf": r.prop_family_conf,
                "lid_type": r.lid_type, "lid_type_conf": r.lid_type_conf,
                "gloves": r.gloves, "gloves_conf": r.gloves_conf,
                "camera_angle": r.camera_angle, "camera_angle_conf": r.camera_angle_conf,
                "session_id": r.session_id,
                "notes": r.notes,
            })


def build_contact_sheet(clip_paths: list[Path], sheet_index: int, out_dir: Path) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    thumb_w, thumb_h = 160, 90
    rows_per_sheet = len(clip_paths)
    sheet = Image.new(
        "RGB", (thumb_w * THUMBS_PER_CLIP, thumb_h * rows_per_sheet + 20 * rows_per_sheet), "white"
    )
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()

    for row_i, clip_path in enumerate(clip_paths):
        y0 = row_i * (thumb_h + 20)
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(clip_path)],
            capture_output=True, text=True, check=True,
        )
        duration = float(probe.stdout.strip() or 0.0)
        for col_i in range(THUMBS_PER_CLIP):
            t = duration * (col_i + 0.5) / THUMBS_PER_CLIP
            cmd = [
                "ffmpeg", "-y", "-ss", str(t), "-i", str(clip_path),
                "-frames:v", "1", "-vf", f"scale={thumb_w}:{thumb_h}",
                "-f", "image2pipe", "-vcodec", "mjpeg", "-",
            ]
            result = subprocess.run(cmd, capture_output=True, check=True)
            from io import BytesIO
            thumb = Image.open(BytesIO(result.stdout))
            sheet.paste(thumb, (col_i * thumb_w, y0 + 20))
        draw.text((2, y0), f"{clip_path.stem}  {duration:.1f}s", fill="black", font=font)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"review_sheet_{sheet_index:02d}.png"
    sheet.save(out_path)
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips-dir", type=Path, default=CLIPS_NORM_DIR)
    ap.add_argument("--out-dir", type=Path, default=MANIFEST_DIR)
    ap.add_argument("--sort-by-confidence", action="store_true")
    args = ap.parse_args()

    clips = sorted(args.clips_dir.glob("*.mp4"))
    if not clips:
        print(f"No normalized clips found in {args.clips_dir}/ - nothing to review.")
        return 0

    rows = build_manifest(args.clips_dir)
    if args.sort_by_confidence:
        rows = sorted(rows, key=lambda r: r.min_guess_confidence())

    write_manifest_csv(rows, args.out_dir / "clips.csv")

    for i in range(0, len(clips), MAX_CLIPS_PER_SHEET):
        batch = clips[i : i + MAX_CLIPS_PER_SHEET]
        path = build_contact_sheet(batch, i // MAX_CLIPS_PER_SHEET, args.out_dir)
        print(f"wrote {path} ({len(batch)} clips)")

    unimplemented_cols = sorted({
        col for col in GUESSED_COLUMNS
        for r in rows
        if getattr(r, col) == UNIMPLEMENTED
    })

    print(f"\nderived columns : {DERIVED_COLUMNS}")
    print(f"guessed columns : {GUESSED_COLUMNS} (each with a _conf column)")
    if unimplemented_cols:
        print(
            f"UNIMPLEMENTED   : {unimplemented_cols} (no phase-1 signal -- see "
            f"derive_row()'s docstring for why each one; conf is 0.0, not a real guess)"
        )
    print(f"human columns   : {HUMAN_COLUMNS} (blank - fill in before scripts/split.py)")
    print(f"\n{len(rows)} clips written to {args.out_dir / 'clips.csv'}")
    print("STOP: a human must fill session_id and correct guessed columns before anything downstream.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
