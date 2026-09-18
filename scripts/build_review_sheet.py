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
    label)
  - blank for the human (session_id, notes) — session_id is not
    visually derivable; two clips from different shoots can look
    identical, so it is never guessed.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

CLIPS_NORM_DIR = Path("clips_norm")
MANIFEST_DIR = Path("manifest")
MAX_CLIPS_PER_SHEET = 20
THUMBS_PER_CLIP = 6

DERIVED_COLUMNS = ["duration_s", "fps_mode", "orientation", "lighting"]
GUESSED_COLUMNS = ["prop_family", "lid_type", "gloves", "camera_angle"]
HUMAN_COLUMNS = ["session_id", "notes"]


@dataclass
class ClipRow:
    clip_id: str
    duration_s: float = 0.0
    fps_mode: str = "unknown"
    orientation: str = "unknown"
    lighting: str = "unknown"
    prop_family: str = "unknown"
    prop_family_conf: float = 0.0
    lid_type: str = "unknown"
    lid_type_conf: float = 0.0
    gloves: str = "unknown"
    gloves_conf: float = 0.0
    camera_angle: str = "unknown"
    camera_angle_conf: float = 0.0
    session_id: str = ""
    notes: str = ""

    def min_guess_confidence(self) -> float:
        return min(self.prop_family_conf, self.lid_type_conf, self.gloves_conf, self.camera_angle_conf)


def derive_row(clip_path: Path) -> ClipRow:
    """ffprobe-only derivations. Guessed columns (prop_family, lid_type,
    gloves, camera_angle) require the actual detector/classifier from
    phase 2 and are left at confidence 0.0 / "unknown" here — this
    function is what phase 1 has without a model yet. Swap in a real
    classifier call once one exists; the CSV shape does not change.
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

    return ClipRow(
        clip_id=clip_path.stem,
        duration_s=round(duration, 1),
        fps_mode=fps_mode,
        orientation=orientation,
        lighting="unknown",  # pixel-statistics estimate — TODO phase 2
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
                "lighting": r.lighting,
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

    print(f"\nderived columns : {DERIVED_COLUMNS}")
    print(f"guessed columns : {GUESSED_COLUMNS} (each with a _conf column)")
    print(f"human columns   : {HUMAN_COLUMNS} (blank - fill in before scripts/split.py)")
    print(f"\n{len(rows)} clips written to {args.out_dir / 'clips.csv'}")
    print("STOP: a human must fill session_id and correct guessed columns before anything downstream.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
