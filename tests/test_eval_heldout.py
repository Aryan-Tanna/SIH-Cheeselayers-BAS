"""Tests for scripts/eval_heldout.py.

The point of this script is to replace a number nobody should trust
(mAP50 0.98 measured on train==val) with one people will quote. Its
geometry and matching therefore need to be correct against cases with
known answers, not merely plausible-looking.
"""

from __future__ import annotations

import math

import pytest

from scripts.eval_heldout import (
    average_precision,
    diagnose,
    manifest_constraints,
    match_frame,
    polygon_iou,
    score,
    stratified_sample,
    xywhr_to_corners,
)


def sq(x0: float, y0: float, x1: float, y1: float):
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))


class TestPolygonIou:
    def test_identical_boxes(self):
        a = sq(0, 0, 10, 10)
        assert polygon_iou(a, a) == pytest.approx(1.0)

    def test_disjoint_boxes(self):
        assert polygon_iou(sq(0, 0, 10, 10), sq(20, 20, 30, 30)) == 0.0

    def test_touching_edges_is_zero(self):
        assert polygon_iou(sq(0, 0, 10, 10), sq(10, 0, 20, 10)) == pytest.approx(0.0)

    def test_half_overlap(self):
        # intersection 50, union 150 -> 1/3
        assert polygon_iou(sq(0, 0, 10, 10), sq(5, 0, 15, 10)) == pytest.approx(1 / 3)

    def test_contained_box(self):
        # inner 25 inside outer 100 -> 25/100
        assert polygon_iou(sq(0, 0, 10, 10), sq(2.5, 2.5, 7.5, 7.5)) == pytest.approx(0.25)

    def test_is_symmetric(self):
        a, b = sq(0, 0, 10, 10), sq(3, 4, 20, 9)
        assert polygon_iou(a, b) == pytest.approx(polygon_iou(b, a))

    def test_opposite_windings_agree(self):
        """Label Studio and Ultralytics emit opposite corner windings;
        the clip must not depend on which one it is handed."""
        cw = sq(0, 0, 10, 10)
        ccw = tuple(reversed(cw))
        assert polygon_iou(cw, sq(5, 0, 15, 10)) == pytest.approx(
            polygon_iou(ccw, sq(5, 0, 15, 10))
        )

    def test_rotated_square_overlap(self):
        """A square rotated 45 deg about the shared center: the
        intersection is a regular octagon of known area."""
        s = 10.0
        axis = sq(-s / 2, -s / 2, s / 2, s / 2)
        diamond = xywhr_to_corners(0, 0, s, s, math.radians(45))
        inter = 2 * (math.sqrt(2) - 1) * s * s
        expected = inter / (2 * s * s - inter)
        assert polygon_iou(axis, diamond) == pytest.approx(expected, rel=1e-6)


class TestXywhrToCorners:
    def test_unrotated(self):
        got = xywhr_to_corners(10, 20, 4, 6, 0.0)
        assert set(got) == set(sq(8, 17, 12, 23))

    def test_rotation_preserves_area(self):
        from scripts.eval_heldout import _shoelace_area
        for deg in (0, 17, 45, 90, 180):
            c = xywhr_to_corners(5, 5, 4, 8, math.radians(deg))
            assert _shoelace_area(c) == pytest.approx(32.0)

    def test_90_degrees_swaps_extent(self):
        c = xywhr_to_corners(0, 0, 10, 2, math.radians(90))
        xs = [p[0] for p in c]
        ys = [p[1] for p in c]
        assert max(xs) - min(xs) == pytest.approx(2.0)
        assert max(ys) - min(ys) == pytest.approx(10.0)


class TestMatching:
    def test_exact_match_is_tp(self):
        box = sq(0, 0, 10, 10)
        out = match_frame([{"class_id": 0, "conf": 0.9, "corners": box}],
                          [{"class_id": 0, "corners": box}], 0.5)
        assert out == [(0.9, True, 0)]

    def test_right_box_wrong_class_is_fp(self):
        box = sq(0, 0, 10, 10)
        out = match_frame([{"class_id": 1, "conf": 0.9, "corners": box}],
                          [{"class_id": 0, "corners": box}], 0.5)
        assert out == [(0.9, False, 1)]

    def test_below_iou_threshold_is_fp(self):
        out = match_frame([{"class_id": 0, "conf": 0.9, "corners": sq(0, 0, 10, 10)}],
                          [{"class_id": 0, "corners": sq(7, 0, 17, 10)}], 0.5)
        assert out == [(0.9, False, 0)]

    def test_duplicate_predictions_only_one_matches(self):
        """The model's observed failure mode: two boxes on one object.
        The second must be a false positive, not a second TP."""
        box = sq(0, 0, 10, 10)
        out = match_frame(
            [{"class_id": 0, "conf": 0.9, "corners": box},
             {"class_id": 0, "conf": 0.8, "corners": sq(1, 1, 11, 11)}],
            [{"class_id": 0, "corners": box}], 0.5)
        assert [t[1] for t in out] == [True, False]

    def test_higher_confidence_claims_the_box_first(self):
        gt = [{"class_id": 0, "corners": sq(0, 0, 10, 10)}]
        out = match_frame(
            [{"class_id": 0, "conf": 0.4, "corners": sq(0, 0, 10, 10)},
             {"class_id": 0, "conf": 0.95, "corners": sq(0, 0, 10, 10)}], gt, 0.5)
        assert out[0] == (0.95, True, 0)
        assert out[1][1] is False

    def test_unmatched_ground_truth_is_not_reported_as_prediction(self):
        assert match_frame([], [{"class_id": 0, "corners": sq(0, 0, 1, 1)}], 0.5) == []


class TestAveragePrecision:
    def test_perfect_detector(self):
        assert average_precision([(0.9, True), (0.8, True)], 2) == pytest.approx(1.0)

    def test_no_ground_truth_is_nan(self):
        assert math.isnan(average_precision([(0.9, False)], 0))

    def test_no_predictions_is_zero(self):
        assert average_precision([], 3) == 0.0

    def test_all_false_positives(self):
        assert average_precision([(0.9, False), (0.8, False)], 2) == 0.0

    def test_half_recall_perfect_precision(self):
        assert average_precision([(0.9, True)], 2) == pytest.approx(0.5)

    def test_ranking_matters(self):
        good = average_precision([(0.9, True), (0.5, False)], 1)
        bad = average_precision([(0.9, False), (0.5, True)], 1)
        assert good > bad


class TestScore:
    def test_class_with_no_ground_truth_reports_nan_not_zero(self):
        """red_lid/yellow_lid have no instances in a slab-prop session.
        Reporting 0.0 would read as 'the model failed', which is a
        different claim from 'this session cannot test it'."""
        box = sq(0, 0, 10, 10)
        r = score({"f.jpg": [{"class_id": 4, "conf": 0.9, "corners": box}]},
                  {"f.jpg": [{"class_id": 2, "corners": box}]}, 0.5)
        red_lid = r["per_class"]["red_lid"]
        assert red_lid["n_gt"] == 0
        assert red_lid["fp"] == 1
        assert math.isnan(red_lid["recall"])
        assert math.isnan(red_lid["ap50"])

    def test_map_excludes_classes_without_ground_truth(self):
        box = sq(0, 0, 10, 10)
        r = score({"f.jpg": [{"class_id": 2, "conf": 0.9, "corners": box}]},
                  {"f.jpg": [{"class_id": 2, "corners": box}]}, 0.5)
        assert r["n_classes_with_gt"] == 1
        assert r["map50"] == pytest.approx(1.0)

    def test_presence_ignores_localization(self):
        """A box in the right frame with the right class but useless
        overlap still counts for class-presence, and not for AP."""
        r = score({"f.jpg": [{"class_id": 2, "conf": 0.9, "corners": sq(90, 90, 100, 100)}]},
                  {"f.jpg": [{"class_id": 2, "corners": sq(0, 0, 10, 10)}]}, 0.5)
        assert r["per_class"]["red_module"]["tp"] == 0
        assert r["presence"]["tp"] == 1
        assert r["presence"]["fp"] == 0

    def test_presence_counts_duplicate_as_false_positive(self):
        box = sq(0, 0, 10, 10)
        r = score({"f.jpg": [{"class_id": 2, "conf": 0.9, "corners": box},
                             {"class_id": 2, "conf": 0.8, "corners": box}]},
                  {"f.jpg": [{"class_id": 2, "corners": box}]}, 0.5)
        assert r["presence"]["tp"] == 1
        assert r["presence"]["fp"] == 1

    def test_missing_prediction_entry_counts_as_false_negatives(self):
        r = score({}, {"f.jpg": [{"class_id": 2, "corners": sq(0, 0, 10, 10)}]}, 0.5)
        assert r["per_class"]["red_module"]["fn"] == 1
        assert r["presence"]["fn"] == 1


class TestManifestConstraints:
    HEADER = "clip_id,gloves,lid_type\n"

    def _csv(self, tmp_path, body):
        p = tmp_path / "clips.csv"
        p.write_text(self.HEADER + body, encoding="utf-8")
        return p

    def test_bare_hands_rule_out_gloved(self, tmp_path):
        p = self._csv(tmp_path, "A_glovebox,false,screw\n")
        assert manifest_constraints(p, ["A_glovebox"]) == {"A_glovebox": {"hand_gloved"}}

    def test_no_lid_rules_out_both_lid_classes(self, tmp_path):
        p = self._csv(tmp_path, "A_glovebox,true,none\n")
        assert manifest_constraints(p, ["A_glovebox"]) == {
            "A_glovebox": {"red_lid", "yellow_lid"}}

    def test_gloved_clip_rules_out_nothing_about_hands(self, tmp_path):
        p = self._csv(tmp_path, "A_glovebox,true,screw\n")
        assert manifest_constraints(p, ["A_glovebox"]) == {"A_glovebox": set()}

    @pytest.mark.parametrize("gloves", ["", "unimplemented", "False", "FALSE", "no", "0"])
    def test_only_literal_false_counts(self, tmp_path, gloves):
        """A wrong constraint invents false positives that aren't there.
        Anything but the exact literal must yield no constraint."""
        p = self._csv(tmp_path, f"A_glovebox,{gloves},screw\n")
        assert manifest_constraints(p, ["A_glovebox"]) == {"A_glovebox": set()}

    def test_other_sessions_clips_are_ignored(self, tmp_path):
        p = self._csv(tmp_path, "A_glovebox,false,none\nB_glovebox,false,none\n")
        assert set(manifest_constraints(p, ["A_glovebox"])) == {"A_glovebox"}


class TestDiagnose:
    C = {"A_glovebox": {"hand_gloved", "red_lid", "yellow_lid"}}

    def _det(self, cid, conf=0.9, box=None):
        return {"class_id": cid, "conf": conf, "corners": box or sq(0, 0, 10, 10)}

    def test_forbidden_class_counted_as_false_positive(self):
        d = diagnose({"A_glovebox_000001.jpg": [self._det(6)]}, self.C, 0.55)
        assert d["ruled_out"]["hand_gloved"]["false_positive_boxes"] == 1
        assert d["ruled_out"]["hand_gloved"]["frames_with_fp"] == 1
        assert d["ruled_out"]["hand_gloved"]["frames_where_ruled_out"] == 1

    def test_allowed_class_not_counted(self):
        d = diagnose({"A_glovebox_000001.jpg": [self._det(7)]}, self.C, 0.55)
        assert d["ruled_out"]["hand_gloved"]["false_positive_boxes"] == 0

    def test_two_fp_boxes_in_one_frame_count_boxes_and_frames_separately(self):
        d = diagnose({"A_glovebox_000001.jpg": [self._det(4), self._det(4)]}, self.C, 0.55)
        assert d["ruled_out"]["red_lid"]["false_positive_boxes"] == 2
        assert d["ruled_out"]["red_lid"]["frames_with_fp"] == 1

    def test_clip_without_constraint_is_not_ruled_out(self):
        d = diagnose({"Z_glovebox_000001.jpg": [self._det(6)]}, self.C, 0.55)
        assert d["ruled_out"]["hand_gloved"]["frames_where_ruled_out"] == 0
        assert d["ruled_out"]["hand_gloved"]["false_positive_boxes"] == 0

    def test_case_open_and_closed_together_is_a_contradiction(self):
        d = diagnose({"A_glovebox_000001.jpg": [self._det(0), self._det(1)]}, self.C, 0.55)
        assert d["contradiction_frames"] == 1

    def test_case_open_alone_is_not_a_contradiction(self):
        d = diagnose({"A_glovebox_000001.jpg": [self._det(0), self._det(0)]}, self.C, 0.55)
        assert d["contradiction_frames"] == 0

    def test_overlapping_same_class_boxes_are_duplicates(self):
        d = diagnose({"A_glovebox_000001.jpg": [self._det(2), self._det(2)]}, self.C, 0.55)
        assert d["duplicate_boxes"] == 1
        assert d["duplicate_frames"] == 1

    def test_separated_same_class_boxes_are_not_duplicates(self):
        """Two real modules of the same colour would be a legitimate
        double detection, not an NMS failure."""
        d = diagnose({"A_glovebox_000001.jpg": [
            self._det(2, box=sq(0, 0, 10, 10)),
            self._det(2, box=sq(50, 50, 60, 60))]}, self.C, 0.55)
        assert d["duplicate_boxes"] == 0

    def test_overlapping_different_class_boxes_are_not_duplicates(self):
        """A hand holding a module legitimately overlaps it."""
        d = diagnose({"A_glovebox_000001.jpg": [self._det(2), self._det(7)]}, self.C, 0.55)
        assert d["duplicate_boxes"] == 0

    def test_empty_frame_counted(self):
        d = diagnose({"A_glovebox_000001.jpg": []}, self.C, 0.55)
        assert d["zero_detection_frames"] == 1

    def test_mean_confidence(self):
        d = diagnose({"A_glovebox_000001.jpg": [
            self._det(2, conf=0.6, box=sq(0, 0, 10, 10)),
            self._det(2, conf=0.8, box=sq(50, 50, 60, 60))]}, self.C, 0.55)
        assert d["mean_conf"]["red_module"] == pytest.approx(0.7)
        assert d["total_boxes"]["red_module"] == 2


class TestStratifiedSample:
    def _frames(self, tmp_path, counts):
        for cid, n in counts.items():
            for i in range(n):
                (tmp_path / f"{cid}_{i:06d}.jpg").write_bytes(b"")
        return tmp_path

    def test_every_clip_is_represented(self, tmp_path):
        d = self._frames(tmp_path, {"A_glovebox": 80, "B_glovebox": 5, "C_glovebox": 40})
        got = stratified_sample(["A_glovebox", "B_glovebox", "C_glovebox"], d, 9, seed=0)
        clips = {p.stem.rsplit("_", 1)[0] for p in got}
        assert clips == {"A_glovebox", "B_glovebox", "C_glovebox"}

    def test_short_clip_is_not_oversampled(self, tmp_path):
        d = self._frames(tmp_path, {"A_glovebox": 50, "B_glovebox": 2})
        got = stratified_sample(["A_glovebox", "B_glovebox"], d, 20, seed=0)
        b = [p for p in got if p.stem.startswith("B_")]
        assert len(b) == 2  # cannot sample more frames than exist

    def test_no_duplicate_frames(self, tmp_path):
        d = self._frames(tmp_path, {"A_glovebox": 30, "B_glovebox": 30})
        got = stratified_sample(["A_glovebox", "B_glovebox"], d, 20, seed=3)
        assert len(got) == len(set(got))

    def test_covers_whole_clip_not_just_the_start(self, tmp_path):
        d = self._frames(tmp_path, {"A_glovebox": 100})
        got = stratified_sample(["A_glovebox"], d, 10, seed=1)
        idx = sorted(int(p.stem.rsplit("_", 1)[1]) for p in got)
        assert idx[0] < 20 and idx[-1] > 80

    def test_unknown_clip_raises(self, tmp_path):
        with pytest.raises(SystemExit):
            stratified_sample(["nope_glovebox"], tmp_path, 5, seed=0)
