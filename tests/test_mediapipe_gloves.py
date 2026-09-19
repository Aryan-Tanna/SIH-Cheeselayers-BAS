"""select_frames() regression tests. run_group() itself needs mediapipe,
cv2, and the vendored model file (models/hand_landmarker.task) to do
anything meaningful, so it's exercised by actually running the script
against real frames (see the phase-1 pilot report), not unit-tested
here -- matching this project's existing pattern of only unit-testing
the pure, dependency-free logic in phase-1 scripts (normalize_clips.py,
separability_check.py) and leaving ffmpeg/model-dependent code to a real
run.

Two real bugs were caught by actually running this script against the
pilot corpus, not by inspection:

1. The original select_frames() put every clip_id that wasn't EXACTLY
   "true" into "bare" -- since all 5 pilot clips' gloves column reads
   "unimplemented" (no phase-1 signal exists for it, see
   build_review_sheet.py), every clip would have silently landed in
   "bare". Fixed: only "true"/"false" land in a group; anything else is
   excluded from both, and --gloved/--bare accept explicit clip_id
   overrides for exactly this "unimplemented" situation.
2. random.sample() returns a shuffled permutation even when the sample
   size equals the population, so the frame list fed to run_group() was
   a random cross-clip shuffle. run_group()'s frame-to-frame "jitter"
   calculation assumed adjacent list entries were adjacent in time --
   under the shuffle they were often unrelated frames from different
   clips, and the two groups reported nearly identical jitter (137.21 vs
   137.80 px) despite a 53-point gap in detection rate, because the
   metric wasn't measuring anything related to gloves. Fixed:
   select_frames() sorts the sampled result back into (clip_id,
   frame_index) order, and run_group() resets its jitter tracking at
   every clip boundary."""

from pathlib import Path

from scripts.test_mediapipe_gloves import select_frames


def _touch_frames(tmp_path: Path, clip_id: str, n: int) -> None:
    for i in range(n):
        (tmp_path / f"{clip_id}_{i:06d}.jpg").write_bytes(b"")


def _write_manifest(path: Path, gloves_by_clip: dict[str, str]) -> None:
    lines = ["clip_id,gloves"]
    lines += [f"{clip_id},{gloves}" for clip_id, gloves in gloves_by_clip.items()]
    path.write_text("\n".join(lines), encoding="utf-8")


def test_unimplemented_clips_land_in_neither_group(tmp_path):
    _touch_frames(tmp_path, "ClipA", 5)
    manifest = tmp_path / "clips.csv"
    _write_manifest(manifest, {"ClipA": "unimplemented"})

    groups = select_frames(tmp_path, manifest, n=200, seed=1)

    assert groups["gloved"] == []
    assert groups["bare"] == []


def test_manifest_true_false_still_works(tmp_path):
    _touch_frames(tmp_path, "Gloved", 3)
    _touch_frames(tmp_path, "Bare", 3)
    manifest = tmp_path / "clips.csv"
    _write_manifest(manifest, {"Gloved": "true", "Bare": "false"})

    groups = select_frames(tmp_path, manifest, n=200, seed=1)

    assert len(groups["gloved"]) == 3
    assert len(groups["bare"]) == 3


def test_explicit_override_wins_over_manifest(tmp_path):
    _touch_frames(tmp_path, "ClipA", 3)
    manifest = tmp_path / "clips.csv"
    _write_manifest(manifest, {"ClipA": "false"})  # manifest says bare

    groups = select_frames(
        tmp_path, manifest, n=200, seed=1, gloved_clip_ids={"ClipA"}
    )

    assert len(groups["gloved"]) == 3
    assert groups["bare"] == []


def test_sampled_result_is_sorted_by_clip_and_frame_index(tmp_path):
    # 8 frames > the n=4 budget (half=2 per group), forcing an actual
    # random.sample() draw -- confirms the result is sorted afterward,
    # not left in sample()'s shuffled order.
    _touch_frames(tmp_path, "ClipA", 4)
    _touch_frames(tmp_path, "ClipB", 4)
    manifest = tmp_path / "clips.csv"
    _write_manifest(manifest, {})

    groups = select_frames(
        tmp_path, manifest, n=4, seed=7,
        gloved_clip_ids={"ClipA", "ClipB"},
    )

    names = [f.name for f in groups["gloved"]]
    assert names == sorted(names)
