#!/usr/bin/env python3
"""Phase 1 script — written in phase 0, NOT run (clips_norm/ is empty
until phase 1 normalize_clips.py has run against real clips).

Samples frames at 2.5 fps (configurable) from clips_norm/, drops
near-duplicates by dHash Hamming distance < 6, names output
{clip}_{frame:06d}.jpg. Expect ~40-60 kept per 45s clip — run_all-style
summary flags clips far outside that band (near-static or dedup
failure) for the phase-1 checkpoint #2 review.

session_id is deliberately NOT in the filename. It isn't known at this
point in the pipeline — it's filled in by hand on the review sheet
(build_review_sheet.py), which runs AFTER extraction — and it isn't
visually derivable, so it can't be guessed either (two clips from
different shoots can look identical). Any code that needs session_id
for a frame (e.g. enforcing scripts/split.py's train/val boundary at
frame level) extracts the clip_id from the filename and looks it up in
manifest/clips.csv — see resolve_session_id() below — the same join
scripts/split.py itself does against clip rows, just keyed down to
frames instead of clips.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

CLIPS_NORM_DIR = Path("clips_norm")
FRAMES_DIR = Path("frames")
MANIFEST_PATH = Path("manifest/clips.csv")
DEFAULT_SAMPLE_FPS = 2.5
DHASH_HAMMING_THRESHOLD = 6


def clip_id_from_frame_filename(frame_filename: str) -> str:
    """"{clip}_{frame:06d}.jpg" -> "{clip}" — the frame index is always
    the last underscore-delimited, zero-padded component."""
    stem = Path(frame_filename).stem
    return stem.rsplit("_", 1)[0]


def resolve_session_id(clip_id: str, manifest_path: Path = MANIFEST_PATH) -> str | None:
    """Look up session_id for a clip via manifest/clips.csv, the same
    table scripts/split.py reads. Returns None if the manifest doesn't
    exist yet or the clip has no session_id filled in — never guesses."""
    if not manifest_path.exists():
        return None
    with open(manifest_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("clip_id") == clip_id:
                return row.get("session_id") or None
    return None


def dhash(image_path: Path, hash_size: int = 8) -> int:
    from PIL import Image

    with Image.open(image_path) as img:
        img = img.convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
        pixels = list(img.getdata())

    bits = 0
    for row in range(hash_size):
        for col in range(hash_size):
            left = pixels[row * (hash_size + 1) + col]
            right = pixels[row * (hash_size + 1) + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


@dataclass
class ExtractResult:
    clip: str
    sampled: int
    kept: int
    duration_s: float


def extract_one(clip_path: Path, out_dir: Path, sample_fps: float) -> ExtractResult:
    clip_stem = clip_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        cmd = [
            "ffmpeg", "-y", "-i", str(clip_path),
            "-vf", f"fps={sample_fps}",
            str(tmp_path / "sample_%06d.jpg"),
        ]
        subprocess.run(cmd, capture_output=True, check=True)

        sampled_frames = sorted(tmp_path.glob("sample_*.jpg"))
        kept = 0
        last_hash: int | None = None
        for i, frame in enumerate(sampled_frames):
            h = dhash(frame)
            if last_hash is not None and hamming(h, last_hash) < DHASH_HAMMING_THRESHOLD:
                continue  # near-duplicate of the last KEPT frame - drop it
            last_hash = h
            dest = out_dir / f"{clip_stem}_{kept:06d}.jpg"
            dest.write_bytes(frame.read_bytes())
            kept += 1

    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(clip_path)],
        capture_output=True, text=True, check=True,
    )
    duration = float(probe.stdout.strip() or 0.0)

    return ExtractResult(clip=clip_path.name, sampled=len(sampled_frames), kept=kept, duration_s=duration)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips-dir", type=Path, default=CLIPS_NORM_DIR)
    ap.add_argument("--out-dir", type=Path, default=FRAMES_DIR)
    ap.add_argument("--fps", type=float, default=DEFAULT_SAMPLE_FPS)
    args = ap.parse_args()

    clips = sorted(args.clips_dir.glob("*.mp4"))
    if not clips:
        print(f"No normalized clips found in {args.clips_dir}/ - nothing to extract.")
        return 0

    results = [extract_one(c, args.out_dir, args.fps) for c in clips]

    print(f"{'clip':<30} {'duration_s':<11} {'sampled':<9} {'kept':<6} flag")
    for r in results:
        flag = ""
        if r.kept < 20:
            flag = "LOW - check for near-static clip"
        elif r.kept > 80:
            flag = "HIGH - check for dedup failure"
        print(f"{r.clip:<30} {r.duration_s:<11.1f} {r.sampled:<9} {r.kept:<6} {flag}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
