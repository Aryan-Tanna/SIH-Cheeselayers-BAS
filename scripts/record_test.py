#!/usr/bin/env python3
"""Live check of capture -> recording + stream on this machine.

Captures from the configured source (default: camera 0) for a fixed
time through the production VideoSource and Recorder, while a receiver
on this same machine pulls the UDP stream, then reports what actually
happened -- measured, not assumed:

  capture fps, frames recorded / gap-filled / skipped / dropped,
  encoder (ffmpeg) CPU, decodable frames in the local segments,
  frames received over the stream, and a video-vs-log time check.

    python scripts/record_test.py                    # camera 0, 10 s
    python scripts/record_test.py --source 1 --seconds 20
    python scripts/record_test.py --source path/to/clip.mp4

The stream is sent to 127.0.0.1 on a free port (not the configured URL),
so this never sends video anywhere else. Recordings go to a temp
directory unless --keep is given. Prints a summary table at the end.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.runtime.capture import CaptureConfig, VideoSource  # noqa: E402
from src.runtime.config import load_runtime_config  # noqa: E402
from src.runtime.recorder import Recorder, RecorderConfig, find_ffmpeg  # noqa: E402


def _free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _count_frames(path: Path) -> int:
    import cv2

    cap = cv2.VideoCapture(str(path))
    n = 0
    while cap.read()[0]:
        n += 1
    cap.release()
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=None, help="camera index, file or URL (default: config)")
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--keep", action="store_true", help="write under recordings/ instead of a temp dir")
    args = ap.parse_args()

    cfg = load_runtime_config()
    cap_cfg = CaptureConfig.from_config(cfg)
    if args.source is not None:
        src = int(args.source) if args.source.isdigit() else args.source
        cap_cfg = dataclasses.replace(cap_cfg, source=src)
    exe = find_ffmpeg(RecorderConfig.from_config(cfg).ffmpeg)
    if exe is None:
        print("no ffmpeg available")
        return 1

    port = _free_udp_port()
    out_root = (REPO_ROOT / "recordings") if args.keep else Path(tempfile.mkdtemp(prefix="bas_rec_"))
    rec_cfg = dataclasses.replace(
        RecorderConfig.from_config(cfg), out_dir=str(out_root), stream_enabled=True,
        stream_url=f"udp://127.0.0.1:{port}?pkt_size=1316",
    )
    session_id = time.strftime("rectest_%Y%m%d_%H%M%S")

    # Receiver: a second ffmpeg that decodes the stream and counts frames.
    rx = subprocess.Popen(
        [exe, "-hide_banner", "-nostdin", "-loglevel", "info",
         "-i", f"udp://127.0.0.1:{port}?overrun_nonfatal=1&fifo_size=50000",
         "-f", "null", "-"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    time.sleep(0.5)  # let it bind before the first packet

    recorder = Recorder(rec_cfg, session_id, REPO_ROOT)
    recorder.start()
    source = VideoSource(cap_cfg, lambda f: recorder.submit(f.payload, f.ts_monotonic))
    print(f"capturing {cap_cfg.source!r} for {args.seconds:.0f} s -> {out_root / session_id}")
    source.start()

    # The encoder starts at the first frame (the camera may take seconds
    # to open), so wait for it to exist before measuring its CPU.
    t_start = time.perf_counter()
    enc_cpu, enc_proc = None, None
    try:
        import psutil
    except ImportError:
        psutil = None
    while psutil is not None and enc_proc is None and time.perf_counter() - t_start < 8.0:
        kids = [k for k in psutil.Process().children(recursive=True) if k.pid != rx.pid]
        enc_proc = kids[0] if kids else None
        time.sleep(0.1)
    if enc_proc is not None:
        enc_proc.cpu_percent(None)
    t_measure = time.perf_counter()
    time.sleep(max(1.0, args.seconds - (t_measure - t_start)))
    if enc_proc is not None:
        try:
            enc_cpu = enc_proc.cpu_percent(None)
        except Exception:  # noqa: BLE001 -- process may have exited
            enc_cpu = None
    measure_s = time.perf_counter() - t_measure

    source.stop()
    side = recorder.stop()
    time.sleep(1.0)
    rx.terminate()
    try:
        rx_err = rx.communicate(timeout=5)[1].decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        rx.kill()
        rx_err = rx.communicate()[1].decode("utf-8", "replace")
    rx_frames = 0
    for line in rx_err.replace("\r", "\n").splitlines():
        if line.startswith("frame="):
            try:
                rx_frames = int(line.split("=")[1].split()[0])
            except ValueError:
                pass

    segs = sorted((out_root / session_id).glob("seg_*.ts"))
    decoded = sum(_count_frames(s) for s in segs)
    st = recorder.stats
    video_s = st.frames_written / rec_cfg.fps

    print("\n" + "-" * 66)
    rows = [
        ("capture source", f"{cap_cfg.source!r}  {source.frame_size}"),
        ("capture fps (measured)", f"{source.stats.measured_fps:.1f}"),
        ("frames captured", source.stats.frames),
        ("video frames written", f"{st.frames_written}  ({video_s:.1f} s at {rec_cfg.fps:g} fps)"),
        ("  of which gap fills", st.frames_duplicated),
        ("  skipped (camera fps > video fps)", st.frames_skipped),
        ("  queue overflow (dropped)", st.frames_dropped_queue),
        ("decodable frames in segments", f"{decoded}  ({len(segs)} segment(s))"),
        ("frames received over stream", rx_frames),
        ("encoder CPU (% of one core)", "n/a" if enc_cpu is None else f"{enc_cpu:.0f}% over {measure_s:.1f} s"),
        ("recorder errors", side.error or "none"),
    ]
    for k, v in rows:
        print(f"{k:32s} {v}")
    print(f"sidecar: {json.dumps({k: getattr(side, k) for k in ('t0_monotonic', 't0_utc', 'fps', 'width', 'height')})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
