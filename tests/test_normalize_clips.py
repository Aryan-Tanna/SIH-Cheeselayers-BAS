"""detect_vfr() regression: the original implementation compared
avg_frame_rate to r_frame_rate by exact string equality, which flagged
every genuinely-CFR clip in the phase-1 pilot corpus as VFR (4 of 5
real clips) -- avg_frame_rate is a computed ratio (frame_count/duration)
that essentially never lands on an exact match to the declared nominal
rate, even with no real frame-rate variation. These are the ACTUAL
avg_frame_rate/r_frame_rate fraction strings ffprobe reported for the
five pilot clips (clips/Dataset1..5_glovebox.mp4), not hand-picked
numbers -- Dataset1/2/3/5 were false positives under the old exact-match
check; direct inter-frame timestamp measurement on Dataset1 confirmed
its deltas cluster at 0.033333s/0.033334s (30fps) with only
encoder-rounding jitter, not genuine variability."""

import csv

from scripts.normalize_clips import (
    ClipChange,
    _parse_rate,
    _read_rotation_overrides,
    _transpose_filters,
    _write_rotation_manifest,
    decide_rotation,
    detect_vfr,
)

PILOT_CLIP_RATES = {
    "Dataset1": ("13230000/440983", "30/1"),
    "Dataset2": ("14310000/476899", "30/1"),
    "Dataset3": ("15555000/518479", "30/1"),
    "Dataset4": ("90000/3013", "90000/3013"),
    "Dataset5": ("6690000/222991", "30/1"),
}


def _probe(avg: str, r: str) -> dict:
    return {"streams": [{"codec_type": "video", "avg_frame_rate": avg, "r_frame_rate": r}]}


def test_parse_rate_handles_fraction_strings():
    assert _parse_rate("30/1") == 30.0
    assert _parse_rate("90000/3013") == 90000 / 3013


def test_parse_rate_handles_zero_denominator_safely():
    assert _parse_rate("0/0") == 0.0


def test_all_five_pilot_clips_are_genuinely_cfr_not_vfr():
    for clip_id, (avg, r) in PILOT_CLIP_RATES.items():
        assert detect_vfr(_probe(avg, r)) is False, f"{clip_id} misdetected as VFR"


def test_exact_match_is_not_vfr():
    assert detect_vfr(_probe("30/1", "30/1")) is False


def test_genuinely_different_rate_is_vfr():
    # 24fps average against a declared 30fps nominal -- 20% off, far
    # beyond encoder-rounding noise (all pilot clips were under 0.03%).
    assert detect_vfr(_probe("24/1", "30/1")) is True


def test_zero_r_frame_rate_does_not_crash():
    assert detect_vfr(_probe("30/1", "0/0")) is True
    assert detect_vfr(_probe("0/0", "0/0")) is False


def test_decide_rotation_override_wins_over_everything():
    assert decide_rotation("Dataset3", is_portrait=False, tag_rotation_deg=90, overrides={"Dataset3": 270}) == (
        270, "override",
    )


def test_decide_rotation_tag_wins_over_default():
    assert decide_rotation("clip", is_portrait=True, tag_rotation_deg=180, overrides={}) == (180, "tag")


def test_decide_rotation_portrait_no_tag_defaults_to_90_clockwise_and_flags():
    # Dataset3_glovebox.mp4: is_portrait=True, no rotation tag detected
    # (confirmed via real ffprobe output) -- this is the exact real
    # scenario that produced the un-rotated pilot bug.
    assert decide_rotation("Dataset3", is_portrait=True, tag_rotation_deg=0, overrides={}) == (90, "defaulted")


def test_decide_rotation_landscape_no_tag_is_zero_not_defaulted():
    assert decide_rotation("clip", is_portrait=False, tag_rotation_deg=0, overrides={}) == (0, "none")


def test_transpose_filters_cover_all_four_rotations():
    assert _transpose_filters(0) == []
    assert _transpose_filters(90) == ["transpose=1"]
    assert _transpose_filters(180) == ["hflip", "vflip"]
    assert _transpose_filters(270) == ["transpose=2"]


def _change(filename: str, rotate_deg: int, source: str) -> ClipChange:
    return ClipChange(
        filename=filename, src_fps_mode="cfr", src_width=478, src_height=850,
        was_portrait=True, tag_rotation_deg=0, rotate_deg=rotate_deg,
        rotation_source=source, transcoded=True,
    )


def test_unconfirmed_default_does_not_round_trip_as_an_override(tmp_path):
    # Regression: an earlier version wrote every clip's freshly-decided
    # rotate_deg back to the manifest with nothing distinguishing "the
    # script guessed this" from "a human approved this," so a SECOND run
    # with zero human review read its own unconfirmed "defaulted" guess
    # back in as if it were a confirmed override -- silently losing the
    # "defaulted, verify" signal after exactly one run, for every clip,
    # even ones that were never portrait/ambiguous at all.
    path = tmp_path / "rotation.csv"
    _write_rotation_manifest([_change("Dataset3_glovebox.mp4", 90, "defaulted")], path)
    assert _read_rotation_overrides(path) == {}


def test_confirmed_default_does_round_trip_as_an_override(tmp_path):
    path = tmp_path / "rotation.csv"
    _write_rotation_manifest([_change("Dataset3_glovebox.mp4", 90, "defaulted")], path)
    rows = list(csv.DictReader(open(path, newline="", encoding="utf-8")))
    rows[0]["confirmed"] = "yes"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["clip_id", "rotate_deg", "source", "confirmed"])
        writer.writeheader()
        writer.writerows(rows)

    assert _read_rotation_overrides(path) == {"Dataset3_glovebox": 90}


def test_override_source_is_written_back_as_confirmed_so_it_persists(tmp_path):
    # Once a clip is sourced from a confirmed override, that confirmation
    # must survive being written back out, or a human's correction would
    # only take effect for exactly one run.
    path = tmp_path / "rotation.csv"
    _write_rotation_manifest([_change("Dataset3_glovebox.mp4", 270, "override")], path)
    assert _read_rotation_overrides(path) == {"Dataset3_glovebox": 270}
