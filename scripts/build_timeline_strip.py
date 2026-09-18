#!/usr/bin/env python3
"""Phase 1 script — written in phase 0, NOT run.

For ONE clip nominated by the human as a fixture source (about 10 of
60, not all): a PNG with frames every 2s, timestamp burned into each,
4 per row — and a harness/fixtures/{clip_id}.skeleton.json with
protocol_id set and an empty expected_events array for the human to
hand-fill by watching the real clip. Violation timestamps are
hand-written, never derived — sampling can't reliably capture
hesitation, smooth trajectories, or anything between samples.

Usage: python scripts/build_timeline_strip.py CLIP_ID
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

CLIPS_NORM_DIR = Path("clips_norm")
FIXTURES_DIR = Path("harness/fixtures")
MANIFEST_DIR = Path("manifest")
STRIP_INTERVAL_S = 2.0
COLS = 4


def build_strip(clip_path: Path, out_path: Path) -> int:
    from PIL import Image, ImageDraw, ImageFont
    from io import BytesIO

    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(clip_path)],
        capture_output=True, text=True, check=True,
    )
    duration = float(probe.stdout.strip() or 0.0)
    timestamps = [t for t in _frange(0.0, duration, STRIP_INTERVAL_S)]

    thumb_w, thumb_h = 240, 135
    rows = -(-len(timestamps) // COLS)  # ceil
    sheet = Image.new("RGB", (thumb_w * COLS, thumb_h * rows), "black")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()

    for i, t in enumerate(timestamps):
        cmd = [
            "ffmpeg", "-y", "-ss", str(t), "-i", str(clip_path),
            "-frames:v", "1", "-vf", f"scale={thumb_w}:{thumb_h}",
            "-f", "image2pipe", "-vcodec", "mjpeg", "-",
        ]
        result = subprocess.run(cmd, capture_output=True, check=True)
        thumb = Image.open(BytesIO(result.stdout))
        col, row = i % COLS, i // COLS
        sheet.paste(thumb, (col * thumb_w, row * thumb_h))
        draw.text((col * thumb_w + 4, row * thumb_h + 4), f"t={t:.1f}s", fill="yellow", font=font)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return len(timestamps)


def _frange(start: float, stop: float, step: float):
    t = start
    while t < stop:
        yield t
        t += step


def write_skeleton_fixture(clip_id: str, protocol_id: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    skeleton = {
        "clip_id": clip_id,
        "protocol_id": protocol_id,
        "expected_events": [],
        "expected_alerts": 0,
        "partial": True,
    }
    out_path.write_text(json.dumps(skeleton, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip_id")
    ap.add_argument("--clips-dir", type=Path, default=CLIPS_NORM_DIR)
    ap.add_argument("--protocol-id", default="bas_specimen_v1")
    ap.add_argument("--out-dir", type=Path, default=MANIFEST_DIR)
    args = ap.parse_args()

    clip_path = args.clips_dir / f"{args.clip_id}.mp4"
    if not clip_path.exists():
        print(f"{clip_path} not found - nothing to build.")
        return 1

    strip_path = args.out_dir / f"{args.clip_id}_timeline.png"
    n_frames = build_strip(clip_path, strip_path)

    skeleton_path = FIXTURES_DIR / f"{args.clip_id}.skeleton.json"
    write_skeleton_fixture(args.clip_id, args.protocol_id, skeleton_path)

    print(f"wrote {strip_path} ({n_frames} frames @ {STRIP_INTERVAL_S}s intervals)")
    print(f"wrote {skeleton_path} - fill expected_events by hand, then rename to drop .skeleton")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
