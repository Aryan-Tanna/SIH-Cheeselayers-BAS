import math

from scripts.convert_labels_to_yolo_obb import obb_corners_normalized, parse_task


def test_zero_rotation_matches_naive_box():
    # x=10%, y=20%, w=40%, h=10% of a 1000x1000 image, no rotation.
    corners = obb_corners_normalized(10.0, 20.0, 40.0, 10.0, 0.0, 1000, 1000)
    assert corners[0] == (0.10, 0.20)  # top-left
    assert corners[1] == (0.50, 0.20)  # top-right
    assert corners[2] == (0.50, 0.30)  # bottom-right
    assert corners[3] == (0.10, 0.30)  # bottom-left


def test_90_degree_rotation_about_top_left_pivot():
    # Non-square box (matches obb_reduce.py's test fixture) so the
    # pivot bug can't hide behind symmetry. x=0,y=0,w=40%,h=20% of a
    # 100x100 image (so percent == pixels, easy to hand-check).
    corners = obb_corners_normalized(0.0, 0.0, 40.0, 20.0, 90.0, 100, 100)
    # Rotating (w,0)->(0,w) and (w,h)->(-h,w) etc, clockwise in image
    # coords -- same math already verified against hand computation in
    # test_perception_obb_reduce.py's 90-degree case.
    top_left, top_right, bottom_right, bottom_left = corners
    assert abs(top_left[0] - 0.0) < 1e-9 and abs(top_left[1] - 0.0) < 1e-9
    assert abs(top_right[0] - 0.0) < 1e-9 and abs(top_right[1] - 0.40) < 1e-9
    assert abs(bottom_right[0] - (-0.20)) < 1e-9 and abs(bottom_right[1] - 0.40) < 1e-9
    assert abs(bottom_left[0] - (-0.20)) < 1e-9 and abs(bottom_left[1] - 0.0) < 1e-9


def test_rectangular_image_percent_conversion_is_per_axis():
    # A non-square image: 10% of width != 10% of height in pixels, so
    # x/w must use original_width and y/h must use original_height,
    # never a single shared scale factor.
    corners = obb_corners_normalized(0.0, 0.0, 10.0, 10.0, 0.0, 2000, 1000)
    top_right = corners[1]
    bottom_left = corners[3]
    assert abs(top_right[0] - 0.10) < 1e-9  # 10% of width, normalized back to 0.10
    assert abs(bottom_left[1] - 0.10) < 1e-9  # 10% of height, normalized back to 0.10
    # In absolute pixels these would differ (200px vs 100px) -- the
    # normalized output being equal is exactly the point: each axis
    # divides by its own dimension.


def test_flag_linked_to_correct_region_by_shared_id():
    task = {
        "data": {"image": "/data/upload/1/abcd1234-frame.jpg"},
        "annotations": [{
            "result": [
                {
                    "id": "boxA", "type": "rectanglelabels",
                    "original_width": 100, "original_height": 100,
                    "value": {"x": 0.0, "y": 0.0, "width": 10.0, "height": 10.0,
                              "rotation": 0.0, "rectanglelabels": ["red_module"]},
                },
                {"id": "boxA", "type": "choices", "value": {"choices": ["occlusion"]}},
                {
                    "id": "boxB", "type": "rectanglelabels",
                    "original_width": 100, "original_height": 100,
                    "value": {"x": 50.0, "y": 50.0, "width": 10.0, "height": 10.0,
                              "rotation": 0.0, "rectanglelabels": ["hand_bare"]},
                },
            ],
        }],
    }
    filename, boxes = parse_task(task)
    assert filename == "frame.jpg"
    by_class = {b.class_id: b for b in boxes}
    from scripts.convert_labels_to_yolo_obb import CLASS_TO_ID
    assert by_class[CLASS_TO_ID["red_module"]].flags == ("occlusion",)
    assert by_class[CLASS_TO_ID["hand_bare"]].flags == ()


def test_unknown_class_raises():
    task = {
        "data": {"image": "/data/upload/1/x-frame2.jpg"},
        "annotations": [{
            "result": [{
                "id": "r1", "type": "rectanglelabels",
                "original_width": 100, "original_height": 100,
                "value": {"x": 0.0, "y": 0.0, "width": 10.0, "height": 10.0,
                          "rotation": 0.0, "rectanglelabels": ["not_a_real_class"]},
            }],
        }],
    }
    import pytest
    with pytest.raises(ValueError):
        parse_task(task)
