#!/usr/bin/env python3
"""Pick the frames to label for the next detector (v5) from new clips,
aimed at where the CURRENT detector is wrong, and export them ready for
the labelling pipeline.

    python scripts/select_v5_frames.py

For each clip in PLAN it:
  1. normalizes exactly like scripts/normalize_clips.py (CFR 30, no
     scaling), so frame numbers match what extract_frames.py / Label
     Studio name them: {clip_id}_{frame:06d}.jpg
  2. knows the true scene state at every frame from the hand-written
     timeline in harness/clip_fixtures/<clip>.json (container open?
     each module in / out?)
  3. scores each candidate frame (every 3rd frame, detector cache from
     scripts/replay_clip.py) by how wrong the current detector is there:
       - container truly open, no confident case_open      (+3)
       - container truly closed, no confident case_closed  (+2)
       - a module truly out of the box, not detected        (+2)
       - red/yellow_lid detected on a lidless slab profile  (+2, false positive)
       - low mean confidence                                (+1)
  4. takes the top-scoring frames per clip, forcing coverage of every
     scene state (closed / open / each module out / both out) and a few
     easy frames, never two frames closer than MIN_GAP_S or near-identical
     (dHash), and exports the JPGs + a CSV saying WHY each was picked.

Every selected frame is TRAIN material. The val/test split is by SESSION
(scripts/split.py rule): frames from these clips must never be used to
judge v5 -- record new clips for that (see the printed summary).
Prints a summary table on completion.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.replay_clip import detections_for  # noqa: E402
from src.perception.detector import DetectorConfig  # noqa: E402
from src.runtime.config import load_runtime_config  # noqa: E402

# clip file stem -> (proposed clip_id, session_id, frames to pick, profile note)
PLAN = {
    "test1": ("Dataset75_desk", "S05", 40, "slab"),
    "test2": ("Dataset76_desk", "S05", 40, "slab"),
    "train1": ("Dataset72_glovebox", "S04", 15, "mixed"),
    "train2": ("Dataset73_glovebox", "S04", 15, "mixed"),
    "train3": ("Dataset74_glovebox", "S04", 15, "mixed"),
}
CLIPS = REPO_ROOT / "test_clips"
OUT = REPO_ROOT / "runs" / "label_batch_v5"
FPS = 30
STRIDE = 3
MIN_GAP_S = 0.6
DHASH_MIN = 8
CONF = 0.5  # "confident" detection for scoring


@dataclass
class Cand:
    frame: int
    t: float
    state: str
    score: int
    reasons: list[str]
    mean_conf: float


def truth_timeline(fixture: dict) -> list[tuple[float, str, str]]:
    """(t, step, kind) from the fixture's step_complete events, sorted."""
    ev = [(e["t"], e["step"]) for e in fixture["expected_events"] if e["type"] == "step_complete"]
    return sorted(ev)


def state_at(t: float, timeline: list[tuple[float, str]], starts_open: bool) -> dict[str, str]:
    st = {"container": "open" if starts_open else "closed", "module_a": "in", "module_b": "in"}
    for te, step in timeline:
        if te > t:
            break
        if step == "open_container":
            st["container"] = "open"
        elif step == "close_container":
            st["container"] = "closed"
        elif step.startswith("remove_"):
            st["module_" + step[-1]] = "out"
        elif step.startswith("return_"):
            st["module_" + step[-1]] = "in"
    return st


def label(st: dict[str, str]) -> str:
    if st["container"] == "closed":
        return "closed"
    outs = [m for m in ("module_a", "module_b") if st[m] == "out"]
    return {0: "open_both_in", 1: f"open_{outs[0][-1]}_out" if outs else "", 2: "open_both_out"}[len(outs)]


def dhash(img) -> int:
    import cv2

    g = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (9, 8), interpolation=cv2.INTER_AREA)
    bits = (g[:, 1:] > g[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def normalize(src: Path, dest: Path) -> None:
    # same command as scripts/normalize_clips.py (landscape clips: no transpose)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-noautorotate", "-i", str(src),
                    "-vsync", "cfr", "-r", str(FPS), "-vf", f"fps={FPS}", "-an", str(dest)],
                   check=True)


def main() -> int:
    import cv2

    dcfg = DetectorConfig.from_config(load_runtime_config())
    (OUT / "images").mkdir(parents=True, exist_ok=True)
    rows, summary, sheet = [], [], []
    tmp = Path(tempfile.mkdtemp(prefix="v5norm_"))
    for stem, (clip_id, session, quota, prof) in PLAN.items():
        fixture = json.loads((REPO_ROOT / "harness/clip_fixtures" / f"{stem}.json").read_text(encoding="utf-8"))
        timeline = truth_timeline(fixture)
        starts_open = any(s == "open_container" and t < 1.0 for t, s in timeline)
        frames = detections_for(CLIPS / f"{stem}.mp4", dcfg, STRIDE, {})
        cands = []
        for fr in frames:
            t = fr["t"]
            st = state_at(t, timeline, starts_open)
            dets = fr["dets"]
            best = {}
            for d in dets:
                best[d[0]] = max(best.get(d[0], 0.0), d[1])
            score, why = 0, []
            if st["container"] == "open" and best.get("case_open", 0) < CONF:
                score += 3; why.append("open box missed")
            if st["container"] == "closed" and best.get("case_closed", 0) < CONF:
                score += 2; why.append("closed box missed")
            for m, cls in (("module_a", "red_module"), ("module_b", "yellow_module")):
                if st["container"] == "open" and st[m] == "out" and best.get(cls, 0) < CONF:
                    score += 2; why.append(f"{cls} out but missed")
            if prof == "slab" and (best.get("red_lid", 0) > 0 or best.get("yellow_lid", 0) > 0):
                score += 2; why.append("lid on a slab (false positive)")
            confs = [d[1] for d in dets]
            mc = sum(confs) / len(confs) if confs else 0.0
            if dets and mc < 0.5:
                score += 1; why.append("low confidence")
            cands.append(Cand(int(round(t * FPS)), t, label(st), score, why, mc))

        norm = tmp / f"{clip_id}.mp4"
        normalize(CLIPS / f"{stem}.mp4", norm)
        cap = cv2.VideoCapture(str(norm))
        picked, hashes = [], []

        def try_pick(c: Cand) -> bool:
            if len(picked) >= quota or any(abs(c.t - p.t) < MIN_GAP_S for p in picked):
                return False
            cap.set(cv2.CAP_PROP_POS_FRAMES, c.frame)
            ok, img = cap.read()
            if not ok:
                return False
            h = dhash(img)
            if any(bin(h ^ o).count("1") < DHASH_MIN for o in hashes):
                return False
            picked.append(c)
            hashes.append(h)
            cv2.imwrite(str(OUT / "images" / f"{clip_id}_{c.frame:06d}.jpg"), img,
                        [cv2.IMWRITE_JPEG_QUALITY, 95])
            if len(picked) <= 8:
                sheet.append((cv2.resize(img, (320, 180)), f"{clip_id} {c.frame}"))
            return True

        # 1. coverage: 2 frames of every scene state, trying candidates
        #    hardest-first and, among equals, from the MIDDLE of the state's
        #    time span (its edges sit next to frames of other states and
        #    are the ones the spacing rule rejects)
        by_state: dict[str, list[Cand]] = {}
        for c in cands:
            by_state.setdefault(c.state, []).append(c)
        for cs in by_state.values():
            mid = (cs[0].t + cs[-1].t) / 2
            got = 0
            for c in sorted(cs, key=lambda c: (-c.score, abs(c.t - mid))):
                if got >= 2:
                    break
                got += try_pick(c)
        # 2. a few easy frames spread over the clip (the model must keep
        #    getting those right too)
        easy = [c for c in cands if c.score == 0]
        for c in easy[:: max(1, len(easy) // 3)][:3]:
            try_pick(c)
        # 3. fill with the hardest remaining
        for c in sorted(cands, key=lambda c: (-c.score, c.mean_conf)):
            if len(picked) >= quota:
                break
            try_pick(c)
        cap.release()
        picked.sort(key=lambda c: c.frame)
        for c in picked:
            rows.append({"image": f"{clip_id}_{c.frame:06d}.jpg", "clip_file": f"{stem}.mp4",
                         "clip_id": clip_id, "session_id": session, "frame": c.frame,
                         "t_s": f"{c.t:.2f}", "scene_state": c.state, "priority": c.score,
                         "why": "; ".join(c.reasons) or "coverage / easy example",
                         "split": "train"})
        states = {}
        for c in picked:
            states[c.state] = states.get(c.state, 0) + 1
        summary.append((stem, clip_id, session, len(picked), sum(1 for c in picked if c.score >= 2), states))

    with open(OUT / "frames_to_label.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with open(OUT / "manifest_rows_to_add.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["clip_file", "clip_id", "session_id", "setup"])
        for stem, (clip_id, session, _, prof) in PLAN.items():
            w.writerow([f"{stem}.mp4", clip_id, session,
                        "Parth desk, oblique front view, red+yellow slabs" if prof == "slab"
                        else "Aryan tub, top-down, red jar (screw cap) + yellow slab"])

    import numpy as np
    tiles = [cv2.putText(t.copy(), lab, (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1)
             for t, lab in sheet[:40]]
    while len(tiles) % 8:
        tiles.append(np.zeros((180, 320, 3), np.uint8))
    rows_img = [np.hstack(tiles[i:i + 8]) for i in range(0, len(tiles), 8)]
    if rows_img:
        cv2.imwrite(str(OUT / "preview.jpg"), np.vstack(rows_img))

    print(f"{'clip':7s} {'clip_id':20s} {'session':7s} {'frames':>6s} {'hard':>5s}  states covered")
    for stem, cid, ses, n, hard, states in summary:
        print(f"{stem:7s} {cid:20s} {ses:7s} {n:6d} {hard:5d}  "
              + ", ".join(f"{k}:{v}" for k, v in sorted(states.items())))
    print(f"total {len(rows)} frames -> {OUT / 'images'}")
    print(f"list: {OUT / 'frames_to_label.csv'}   manifest rows: {OUT / 'manifest_rows_to_add.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
