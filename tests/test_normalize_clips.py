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

from scripts.normalize_clips import _parse_rate, detect_vfr

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
