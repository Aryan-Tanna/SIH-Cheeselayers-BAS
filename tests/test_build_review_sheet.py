"""Unit tests for the pure pixel-statistics functions in
build_review_sheet.py, against synthetic PIL images (no ffmpeg
dependency, unlike derive_row() itself -- those are exercised by
actually running the script against real clips, not in this hermetic
suite)."""

from PIL import Image

from scripts.build_review_sheet import (
    ClipRow,
    UNIMPLEMENTED,
    _color_temperature_k,
    _mean_brightness,
    _skin_pixel_fraction,
)


def _solid(rgb: tuple[int, int, int], size: tuple[int, int] = (32, 32)) -> Image.Image:
    return Image.new("RGB", size, rgb)


def test_mean_brightness_black_and_white():
    assert _mean_brightness(_solid((0, 0, 0))) == 0.0
    assert _mean_brightness(_solid((255, 255, 255))) == 255.0


def test_mean_brightness_mid_gray_is_roughly_half():
    b = _mean_brightness(_solid((128, 128, 128)))
    assert 120 < b < 135


def test_color_temperature_orders_warm_below_cool():
    # A reddish/warm image should compute a LOWER CCT than a bluish/cool
    # one -- this is the property the formula must have, regardless of
    # exact Kelvin values (which nobody hand-derives; see McCamy's
    # formula in _color_temperature_k's docstring for the source).
    warm = _color_temperature_k(_solid((255, 180, 120)))
    cool = _color_temperature_k(_solid((120, 180, 255)))
    assert warm < cool


def test_color_temperature_neutral_gray_is_finite_and_positive():
    ct = _color_temperature_k(_solid((128, 128, 128)))
    assert ct > 0


def test_skin_pixel_fraction_pure_skin_tone_is_high():
    # A canonical mid-tone skin RGB, well inside the YCbCr skin range.
    frac = _skin_pixel_fraction(_solid((220, 170, 140)))
    assert frac > 0.9


def test_skin_pixel_fraction_pure_blue_is_zero():
    frac = _skin_pixel_fraction(_solid((20, 20, 200)))
    assert frac == 0.0


def test_skin_pixel_fraction_pure_white_is_zero():
    # White gloves are near-achromatic -- exactly the false-positive
    # mode _skin_pixel_fraction()'s docstring documents as why this
    # number isn't turned into a gloves guess. A pure white swatch
    # should NOT register as skin.
    frac = _skin_pixel_fraction(_solid((255, 255, 255)))
    assert frac == 0.0


def test_unimplemented_guessed_columns_default_and_are_distinct_from_unknown():
    row = ClipRow(clip_id="x")
    assert row.gloves == UNIMPLEMENTED
    assert row.prop_family == UNIMPLEMENTED
    assert row.lid_type == UNIMPLEMENTED
    assert row.camera_angle == UNIMPLEMENTED
    assert UNIMPLEMENTED != "unknown"
