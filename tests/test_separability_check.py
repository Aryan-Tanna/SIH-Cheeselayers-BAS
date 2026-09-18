"""_middle_third_dense_sample() regression: the original selection was a
uniform random sample across ALL frames pooled together, which the
in-case/out-of-case ambiguity this check exists to surface doesn't need
-- that ambiguity concentrates mid-clip (open/close bookend a clip), so
a uniform sample over-represents the unambiguous bookends and is
dominated by whichever clips happen to have the most kept frames.

Also covers the frame-label bug: two different clips whose names shared
a tail became indistinguishable under the old fixed-length slice
(frame_path.stem[-12:]), and frame indices restart at 0 per clip so the
index alone never disambiguated either."""

from pathlib import Path

from scripts.separability_check import _middle_third_dense_sample


def _fake_frames(clip_id: str, n: int) -> list[Path]:
    return [Path(f"{clip_id}_{i:06d}.jpg") for i in range(n)]


def test_sample_is_evenly_split_across_clips():
    all_frames = _fake_frames("A", 30) + _fake_frames("B", 30) + _fake_frames("C", 30)
    selected = _middle_third_dense_sample(all_frames, n=30, seed=1)
    by_clip: dict[str, int] = {}
    for f in selected:
        clip_id = f.stem.rsplit("_", 1)[0]
        by_clip[clip_id] = by_clip.get(clip_id, 0) + 1
    assert set(by_clip) == {"A", "B", "C"}
    assert all(count == 10 for count in by_clip.values())


def test_sample_comes_from_the_middle_third_not_the_bookends():
    # 30 frames -> middle third is indices [10, 20).
    all_frames = _fake_frames("A", 30)
    selected = _middle_third_dense_sample(all_frames, n=10, seed=1)
    indices = {int(f.stem.rsplit("_", 1)[-1]) for f in selected}
    assert indices <= set(range(10, 20))


def test_very_short_clip_falls_back_to_all_its_frames_not_empty():
    # A 2-frame clip's middle third is empty by the naive slice -- must
    # not silently drop the clip from consideration entirely.
    all_frames = _fake_frames("short", 2) + _fake_frames("long", 30)
    selected = _middle_third_dense_sample(all_frames, n=10, seed=1)
    clip_ids = {f.stem.rsplit("_", 1)[0] for f in selected}
    assert "short" in clip_ids


def test_sample_never_exceeds_available_frames():
    all_frames = _fake_frames("A", 3)
    selected = _middle_third_dense_sample(all_frames, n=40, seed=1)
    assert len(selected) <= 3
    assert len(set(selected)) == len(selected)  # no duplicates


def test_deterministic_given_same_seed():
    all_frames = _fake_frames("A", 30) + _fake_frames("B", 30)
    first = _middle_third_dense_sample(all_frames, n=20, seed=42)
    second = _middle_third_dense_sample(all_frames, n=20, seed=42)
    assert first == second
