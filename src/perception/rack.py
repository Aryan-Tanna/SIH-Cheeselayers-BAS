"""Rack-space geometry from ArUco markers on the rig floor.

The rack frame is the plane the markers lie on (the tub floor), in
millimetres, seen from above: x right, y "down" (same handedness as the
image of a camera looking down, so no mirror), origin at the centre of
the reference marker (lowest ID in the layout), its edges on the axes.

Design decisions, stated because they decide behaviour:

* ANY visible marker is enough. Its 4 corners give the full
  image->floor homography once the layout (where each marker sits on the
  floor) is known. Measured on the 20 ArUco clips: >=1 marker in 99-100%
  of frames but all 4 in only 8-81% (hands and the open lid cover them),
  so waiting for all four would leave the rack unknown most of the time.
* With >=2 markers the fit is RANSAC over all corners, so one marker that
  was knocked out of place (or a misread) is outvoted instead of bending
  the whole frame. A fit whose reprojection error exceeds `max_reproj_px`
  is rejected, never used.
* IDs outside the configured list are ignored: the tub walls reflect the
  markers and produced a stray ID17 twice in the clips.
* Short gaps HOLD the last good pose (`hold_s`): the camera is fixed, so
  a pose from 0.5 s ago is still right, and a hand sweeping over the
  markers must not flip geometry to "none". Longer gaps report "none"
  and downstream falls back to image space -- degraded, never dead.
* Floor-plane only. The homography is exact for points ON the floor; a
  point above it (a module lifted 10 cm) lands displaced away from the
  camera by roughly height x tan(view angle). Fine for "which zone is
  this on the floor"; not a 3D position.
* The layout is calibrated FROM VIDEO (`calibrate_layout`), not measured
  by hand: equal-size flat squares of known side are fitted to all
  frames jointly. Anchoring on one small marker instead amplifies its
  corner noise across the tub -- tried, it produced fake 1.4-2x marker
  size mismatches -- so every iteration snaps each marker back to a rigid
  square of the known size.

Pure numpy + cv2; no runtime state except in RackTracker.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import numpy as np

Corners = np.ndarray  # (4, 2) float, ArUco corner order: TL, TR, BR, BL (clockwise)

ARUCO_DICTIONARIES = (
    "DICT_4X4_50", "DICT_4X4_100", "DICT_4X4_250", "DICT_4X4_1000",
    "DICT_5X5_50", "DICT_5X5_100", "DICT_5X5_250", "DICT_5X5_1000",
    "DICT_6X6_50", "DICT_6X6_100", "DICT_6X6_250", "DICT_6X6_1000",
    "DICT_7X7_50", "DICT_7X7_100", "DICT_7X7_250", "DICT_7X7_1000",
    "DICT_ARUCO_ORIGINAL",
    "DICT_APRILTAG_16h5", "DICT_APRILTAG_25h9", "DICT_APRILTAG_36h10", "DICT_APRILTAG_36h11",
)


# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class MarkerPose:
    """Where one marker sits on the rack floor: centre (mm) + rotation."""

    x_mm: float
    y_mm: float
    angle_deg: float


@dataclass(frozen=True)
class RackConfig:
    enabled: bool = True
    dictionary: str = "DICT_4X4_50"
    marker_size_mm: float = 49.0
    marker_ids: tuple[int, ...] = (1, 2, 3, 4)
    layout: dict[int, MarkerPose] = field(default_factory=dict)  # empty = not calibrated
    hold_s: float = 1.0
    max_reproj_px: float = 4.0
    ransac_px: float = 3.0

    def validate(self) -> list[str]:
        errs = []
        if self.dictionary not in ARUCO_DICTIONARIES:
            errs.append(f"unknown ArUco dictionary {self.dictionary!r}")
        if not self.marker_size_mm > 0:
            errs.append("marker size must be > 0 mm")
        if not self.marker_ids:
            errs.append("list at least one marker ID")
        if len(set(self.marker_ids)) != len(self.marker_ids):
            errs.append("marker IDs repeat")
        if any(i < 0 for i in self.marker_ids):
            errs.append("marker IDs must be >= 0")
        stray = sorted(set(self.layout) - set(self.marker_ids))
        if stray:
            errs.append(f"layout has markers not in marker_ids: {stray}")
        if self.hold_s < 0 or self.max_reproj_px <= 0:
            errs.append("hold_s must be >= 0 and max_reproj_px > 0")
        return errs

    @property
    def calibrated(self) -> bool:
        return bool(self.layout)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RackConfig":
        aru = d.get("aruco") or {}
        lay = d.get("layout") or {}
        return cls(
            enabled=bool(d.get("enabled", True)),
            dictionary=str(aru.get("dictionary", cls.dictionary)),
            marker_size_mm=float(aru.get("marker_size_mm", cls.marker_size_mm)),
            marker_ids=tuple(int(i) for i in aru.get("marker_ids", cls.marker_ids)),
            layout={int(k): MarkerPose(float(v["x_mm"]), float(v["y_mm"]), float(v["angle_deg"]))
                    for k, v in (lay.get("markers") or {}).items()},
            hold_s=float(d.get("hold_s", cls.hold_s)),
            max_reproj_px=float(d.get("max_reproj_px", cls.max_reproj_px)),
            ransac_px=float(d.get("ransac_px", cls.ransac_px)),
        )

    def to_dict(self, layout_note: str | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {
            "enabled": self.enabled,
            "aruco": {"dictionary": self.dictionary, "marker_size_mm": self.marker_size_mm,
                      "marker_ids": list(self.marker_ids)},
            "layout": {"note": layout_note, "markers": {
                i: {"x_mm": round(p.x_mm, 1), "y_mm": round(p.y_mm, 1), "angle_deg": round(p.angle_deg, 2)}
                for i, p in sorted(self.layout.items())}},
            "hold_s": self.hold_s,
            "max_reproj_px": self.max_reproj_px,
            "ransac_px": self.ransac_px,
        }
        if layout_note is None:
            del out["layout"]["note"]
        return out


DEFAULT_RACK_CONFIG_PATH = Path("configs/rack.yaml")

RACK_YAML_HEADER = """\
# configs/rack.yaml -- ArUco markers that define the rack (tub floor) frame.
#
# Edited by hand, or from the GUI ("Rack setup [K]"). Units: millimetres.
# marker_size_mm = black border edge to black border edge.
# layout = where each marker sits on the floor (centre + rotation), with
# the lowest-ID marker at the origin. It is CALIBRATED FROM VIDEO
# (GUI "Calibrate", or scripts/calibrate_rack.py) -- re-run that if the
# markers are re-taped, the size or IDs change. An empty layout means
# "not calibrated": the co-pilot then runs in image space (degraded).
"""


def load_rack_config(path: Path) -> RackConfig:
    import yaml

    if not path.exists():
        return RackConfig(enabled=False)
    return RackConfig.from_dict(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def save_rack_config(cfg: RackConfig, path: Path, layout_note: str | None = None) -> None:
    import yaml

    errs = cfg.validate()
    if errs:
        raise ValueError("; ".join(errs))
    body = yaml.safe_dump(cfg.to_dict(layout_note), sort_keys=False)
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(RACK_YAML_HEADER + "\n" + body, encoding="utf-8")
    tmp.replace(path)  # atomic: a crash mid-write never leaves half a config


# ----------------------------------------------------------------------
# Pure geometry
# ----------------------------------------------------------------------

def marker_corners_mm(pose: MarkerPose, size_mm: float) -> Corners:
    """Rack-frame corners of one marker, in ArUco corner order."""
    h = size_mm / 2.0
    local = np.array([[-h, -h], [h, -h], [h, h], [-h, h]], dtype=np.float64)
    a = math.radians(pose.angle_deg)
    rot = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    return local @ rot.T + np.array([pose.x_mm, pose.y_mm])


def apply_h(h: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Apply a 3x3 homography to (N, 2) points."""
    p = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
    q = np.hstack([p, np.ones((len(p), 1))]) @ np.asarray(h, dtype=np.float64).T
    return q[:, :2] / q[:, 2:3]


def fit_rigid_square(pts: np.ndarray, size_mm: float) -> MarkerPose:
    """Least-squares rigid placement (rotation + translation, NO scale) of
    a size_mm square onto 4 observed corners (Procrustes)."""
    pts = np.asarray(pts, dtype=np.float64)
    c = pts.mean(0)
    local = marker_corners_mm(MarkerPose(0.0, 0.0, 0.0), size_mm)
    q = pts - c
    num = float(np.sum(local[:, 0] * q[:, 1] - local[:, 1] * q[:, 0]))
    den = float(np.sum(local[:, 0] * q[:, 0] + local[:, 1] * q[:, 1]))
    return MarkerPose(float(c[0]), float(c[1]), math.degrees(math.atan2(num, den)))


def _wrap_deg(a: float) -> float:
    return (a + 180.0) % 360.0 - 180.0


def _rebase(layout: dict[int, MarkerPose], ref: int) -> dict[int, MarkerPose]:
    """Rigidly move the layout so the reference marker is at the origin, angle 0."""
    r = layout[ref]
    a = -math.radians(r.angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    out = {}
    for i, p in layout.items():
        dx, dy = p.x_mm - r.x_mm, p.y_mm - r.y_mm
        out[i] = MarkerPose(ca * dx - sa * dy, sa * dx + ca * dy, _wrap_deg(p.angle_deg - r.angle_deg))
    return out


@dataclass
class CalibrationResult:
    layout: dict[int, MarkerPose]
    frames_used: int
    rms_reproj_px: float  # corners reprojected with each frame's homography
    iterations: int
    unplaced: list[int]  # IDs seen but never together with another marker


def _frame_residuals(frames: list[dict[int, Corners]], layout: dict[int, MarkerPose],
                     size_mm: float) -> np.ndarray:
    """Pixel residuals of every frame's corners under its own best
    homography (rack -> image) for this layout. Frames with <2 layout
    markers carry no layout information and are skipped."""
    import cv2

    out = []
    for f in frames:
        ids = [i for i in f if i in layout]
        if len(ids) < 2:
            continue
        img = np.vstack([f[i] for i in ids])
        rack = np.vstack([marker_corners_mm(layout[i], size_mm) for i in ids])
        h, _ = cv2.findHomography(rack, img, 0)
        if h is None:
            out.append(np.full(img.size, 1e3))
            continue
        out.append((apply_h(h, rack) - img).ravel())
    return np.concatenate(out) if out else np.zeros(0)


def _refine_layout(frames: list[dict[int, Corners]], layout: dict[int, MarkerPose], size_mm: float,
                   ref: int, iterations: int = 30) -> dict[int, MarkerPose]:
    """Levenberg-Marquardt on the layout (x, y, angle of every marker but
    the reference), minimising PIXEL reprojection error over all frames --
    the error the camera actually makes, so tilted views are handled
    correctly. Numeric Jacobian: only 3 x (markers - 1) parameters."""
    others = [i for i in sorted(layout) if i != ref]
    if not others:
        return layout

    def unpack(v: np.ndarray) -> dict[int, MarkerPose]:
        lay = {ref: MarkerPose(0.0, 0.0, 0.0)}
        for k, i in enumerate(others):
            lay[i] = MarkerPose(float(v[3 * k]), float(v[3 * k + 1]), float(v[3 * k + 2]))
        return lay

    v = np.array([c for i in others for c in (layout[i].x_mm, layout[i].y_mm, layout[i].angle_deg)])
    r = _frame_residuals(frames, unpack(v), size_mm)
    cost, lam = float(r @ r), 1e-3
    steps = np.array([0.05, 0.05, 0.01] * len(others))  # mm, mm, deg
    for _ in range(iterations):
        jac = np.empty((r.size, v.size))
        for j in range(v.size):
            dv = v.copy()
            dv[j] += steps[j]
            jac[:, j] = (_frame_residuals(frames, unpack(dv), size_mm) - r) / steps[j]
        jtj, jtr = jac.T @ jac, jac.T @ r
        improved = False
        for _ in range(10):
            delta = np.linalg.solve(jtj + lam * np.diag(np.diag(jtj) + 1e-9), -jtr)
            r_new = _frame_residuals(frames, unpack(v + delta), size_mm)
            c_new = float(r_new @ r_new)
            if c_new < cost:
                v, r, lam, improved = v + delta, r_new, max(lam / 3, 1e-7), True
                done = c_new > cost * (1 - 1e-7)
                cost = c_new
                break
            lam *= 4
        if not improved or done:
            break
    return unpack(v)


def calibrate_layout(observations: Iterable[dict[int, Corners]], size_mm: float,
                     iterations: int = 20, tol_mm: float = 0.01) -> CalibrationResult:
    """Marker layout on the floor from many frames of a FIXED rig.

    observations: per frame, {marker id: (4,2) image corners}. Frames with
    fewer than 2 markers carry no layout information and are skipped.

    Alternates (a) per-frame homography image->floor fitted to ALL visible
    corners of the current layout, and (b) per-marker: map its observed
    corners to the floor in every frame, take the median, and snap to a
    rigid square of the KNOWN size. (b) is what removes the projective
    drift a free fit would have (see module docstring). That converges
    for an overhead camera but settles 8-22 mm off at 25-45 degrees of
    tilt (it averages in floor mm, where a tilted view's errors are
    lopsided), so it is only the starting point for _refine_layout, which
    minimises the pixel error directly.
    """
    import cv2

    frames = [{int(k): np.asarray(v, dtype=np.float64).reshape(4, 2) for k, v in f.items()}
              for f in observations]
    frames = [f for f in frames if len(f) >= 2]
    if not frames:
        raise ValueError("no frame shows 2 or more markers -- cannot calibrate a layout")
    seen = sorted({i for f in frames for i in f})
    ref = seen[0]

    # Init: weak perspective from the frame with the most markers (camera
    # roughly overhead): pixels -> mm by the observed marker size.
    best = max(frames, key=len)
    side_px = float(np.mean([np.linalg.norm(c[j] - c[(j + 1) % 4]) for c in best.values() for j in range(4)]))
    s = size_mm / side_px
    layout = {i: fit_rigid_square(c * s, size_mm) for i, c in best.items()}
    # Markers missing from that frame: place them through any frame shared
    # with an already-placed marker (single-marker homography, rough -- the
    # iterations refine it).
    for _ in range(len(seen)):
        for f in frames:
            known = [i for i in f if i in layout]
            if not known:
                continue
            h = cv2.getPerspectiveTransform(f[known[0]].astype(np.float32),
                                            marker_corners_mm(layout[known[0]], size_mm).astype(np.float32))
            for i, c in f.items():
                if i not in layout:
                    layout[i] = fit_rigid_square(apply_h(h, c), size_mm)
    layout = _rebase(layout, ref)

    it = 0
    for it in range(1, iterations + 1):
        mapped: dict[int, list[np.ndarray]] = {i: [] for i in layout}
        for f in frames:
            ids = [i for i in f if i in layout]
            if len(ids) < 2:
                continue
            src = np.vstack([f[i] for i in ids])
            dst = np.vstack([marker_corners_mm(layout[i], size_mm) for i in ids])
            h, _ = cv2.findHomography(src, dst, 0)
            if h is None:
                continue
            for i in ids:
                mapped[i].append(apply_h(h, f[i]))
        new = {i: fit_rigid_square(np.median(np.array(v), axis=0), size_mm)
               for i, v in mapped.items() if v}
        new = _rebase(new, ref)
        shift = max(math.hypot(new[i].x_mm - layout[i].x_mm, new[i].y_mm - layout[i].y_mm)
                    for i in new)
        layout = new
        if shift < tol_mm:
            break
    layout = _refine_layout(frames, layout, size_mm, ref)

    # Report: RMS reprojection error in pixels with the final layout.
    errs = []
    for f in frames:
        ids = [i for i in f if i in layout]
        img = np.vstack([f[i] for i in ids])
        rack = np.vstack([marker_corners_mm(layout[i], size_mm) for i in ids])
        h, _ = cv2.findHomography(rack, img, 0)
        if h is not None:
            errs.append(np.linalg.norm(apply_h(h, rack) - img, axis=1))
    rms = float(np.sqrt(np.mean(np.concatenate(errs) ** 2))) if errs else float("nan")
    return CalibrationResult(layout, len(frames), rms, it, sorted(set(seen) - set(layout)))


@dataclass(frozen=True)
class RackFit:
    img_to_rack: np.ndarray  # 3x3
    rack_to_img: np.ndarray  # 3x3
    ids_used: tuple[int, ...]
    reproj_px: float  # RMS over the inlier corners


def fit_rack(observed: dict[int, Corners], cfg: RackConfig) -> RackFit | None:
    """Image->rack homography from whatever layout markers are visible.
    None when no layout marker is visible or the fit is not trustworthy."""
    import cv2

    ids = sorted(i for i in observed if i in cfg.layout)
    if not ids:
        return None
    img = np.vstack([np.asarray(observed[i], dtype=np.float64).reshape(4, 2) for i in ids])
    rack = np.vstack([marker_corners_mm(cfg.layout[i], cfg.marker_size_mm) for i in ids])
    if len(ids) == 1:
        h = cv2.getPerspectiveTransform(rack.astype(np.float32), img.astype(np.float32)).astype(np.float64)
        inl = np.ones(4, dtype=bool)
    else:
        # rack -> image, so the RANSAC threshold is in pixels
        h, mask = cv2.findHomography(rack, img, cv2.RANSAC, cfg.ransac_px)
        if h is None:
            return None
        inl = mask.ravel().astype(bool)
        # keep only markers whose 4 corners all agree, refit on those
        per = inl.reshape(-1, 4).all(axis=1)
        if not per.any():
            return None
        keep = [i for i, ok in zip(ids, per) if ok]
        if len(keep) < len(ids):
            ids = keep
            img = np.vstack([np.asarray(observed[i], dtype=np.float64).reshape(4, 2) for i in ids])
            rack = np.vstack([marker_corners_mm(cfg.layout[i], cfg.marker_size_mm) for i in ids])
            if len(ids) == 1:
                h = cv2.getPerspectiveTransform(rack.astype(np.float32), img.astype(np.float32)).astype(np.float64)
            else:
                h, _ = cv2.findHomography(rack, img, 0)
        inl = np.ones(len(img), dtype=bool)
    if h is None or abs(np.linalg.det(h)) < 1e-12:
        return None
    err = float(np.sqrt(np.mean(np.sum((apply_h(h, rack) - img) ** 2, axis=1))))
    if len(ids) > 1 and err > cfg.max_reproj_px:
        return None
    return RackFit(np.linalg.inv(h), h, tuple(ids), err)


def to_rack(fit: RackFit, pts_px: np.ndarray) -> np.ndarray:
    return apply_h(fit.img_to_rack, pts_px)


def to_image(fit: RackFit, pts_mm: np.ndarray) -> np.ndarray:
    return apply_h(fit.rack_to_img, pts_mm)


# ----------------------------------------------------------------------
# Detection + runtime state
# ----------------------------------------------------------------------

def make_detector(dictionary: str) -> Any:
    import cv2

    params = cv2.aruco.DetectorParameters()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    return cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dictionary)), params)


def detect_markers(detector: Any, image: np.ndarray, allowed: Iterable[int] | None = None) -> dict[int, Corners]:
    import cv2

    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = detector.detectMarkers(gray)
    if ids is None:
        return {}
    allow = None if allowed is None else set(allowed)
    return {int(i): c.reshape(4, 2).astype(np.float64) for c, i in zip(corners, ids.ravel())
            if allow is None or int(i) in allow}


def autodetect_dictionary(image: np.ndarray) -> list[tuple[str, list[int]]]:
    """Which dictionaries find markers in this image, most markers first.
    For the GUI: the operator does not need to know what was printed."""
    hits = []
    for name in ARUCO_DICTIONARIES:
        found = detect_markers(make_detector(name), image)
        if found:
            hits.append((name, sorted(found)))
    # Larger dictionaries contain the smaller ones' codes: prefer the
    # SMALLEST dictionary that finds the most markers (fewer confusable codes).
    hits.sort(key=lambda h: (-len(h[1]), ARUCO_DICTIONARIES.index(h[0])))
    return hits


@dataclass(frozen=True)
class RackPose:
    status: str  # "ok" | "held" | "none" | "uncalibrated" | "off"
    fit: RackFit | None
    markers_seen: tuple[int, ...]
    age_s: float  # time since the fit was measured (0 when ok)
    ts: float


class RackTracker:
    """Per-frame rack pose with a short hold. Not thread-safe: one caller
    (the perception thread); readers take `latest`, an immutable value."""

    def __init__(self, cfg: RackConfig) -> None:
        self.cfg = cfg
        self._det = make_detector(cfg.dictionary) if cfg.enabled else None
        self._last_fit: RackFit | None = None
        self._last_fit_ts = -math.inf
        self.latest = RackPose("off" if not cfg.enabled else "none", None, (), 0.0, 0.0)
        self.last_markers: dict[int, Corners] = {}

    def update(self, ts: float, image: np.ndarray) -> RackPose:
        if self._det is None:
            self.latest = RackPose("off", None, (), 0.0, ts)
            return self.latest
        seen = detect_markers(self._det, image, self.cfg.marker_ids)
        return self.update_markers(ts, seen)

    def update_markers(self, ts: float, seen: dict[int, Corners]) -> RackPose:
        self.last_markers = seen
        ids = tuple(sorted(seen))
        if not self.cfg.calibrated:
            self.latest = RackPose("uncalibrated", None, ids, 0.0, ts)
            return self.latest
        fit = fit_rack(seen, self.cfg) if seen else None
        if fit is not None:
            self._last_fit, self._last_fit_ts = fit, ts
            self.latest = RackPose("ok", fit, ids, 0.0, ts)
        elif self._last_fit is not None and ts - self._last_fit_ts <= self.cfg.hold_s:
            self.latest = RackPose("held", self._last_fit, ids, ts - self._last_fit_ts, ts)
        else:
            self.latest = RackPose("none", None, ids, 0.0, ts)
        return self.latest

    @property
    def geometry_status(self) -> str:
        """For the log: 'rack' (ok/held) or 'image' (fell back)."""
        return "rack" if self.latest.status in ("ok", "held") else "image"


def edit_config(old: RackConfig, dictionary: str, marker_size_mm: float,
                marker_ids: tuple[int, ...]) -> tuple[RackConfig, str]:
    """A config edit (GUI) WITHOUT re-calibrating. Returns (new config, note).

    * Size changed: the layout was measured in marker widths, so every
      position scales by new/old size -- correcting the size fixes the mm.
    * IDs changed: layout entries for IDs no longer listed are dropped.
    * Dictionary changed: different physical markers, so the layout means
      nothing any more -- dropped; calibrate again.
    """
    note = []
    layout = dict(old.layout)
    if dictionary != old.dictionary and layout:
        layout = {}
        note.append("ArUco type changed: layout cleared -- calibrate")
    if layout and marker_size_mm != old.marker_size_mm and old.marker_size_mm > 0:
        k = marker_size_mm / old.marker_size_mm
        layout = {i: MarkerPose(p.x_mm * k, p.y_mm * k, p.angle_deg) for i, p in layout.items()}
        note.append(f"layout scaled x{k:.3f} for the new marker size")
    dropped = sorted(set(layout) - set(marker_ids))
    if dropped:
        layout = {i: p for i, p in layout.items() if i in marker_ids}
        note.append(f"layout entries dropped for IDs {dropped}")
    missing = sorted(set(marker_ids) - set(layout))
    if layout and missing:
        note.append(f"IDs {missing} not in the layout yet -- calibrate to place them")
    new = RackConfig(enabled=True, dictionary=dictionary, marker_size_mm=marker_size_mm,
                     marker_ids=tuple(marker_ids), layout=layout, hold_s=old.hold_s,
                     max_reproj_px=old.max_reproj_px, ransac_px=old.ransac_px)
    return new, "; ".join(note)


def parse_ids(text: str) -> tuple[int, ...]:
    """'1, 2,3 4' -> (1, 2, 3, 4). Raises ValueError with a readable message."""
    parts = [p for p in text.replace(",", " ").split() if p]
    if not parts:
        raise ValueError("enter at least one marker ID, e.g. 1,2,3,4")
    try:
        ids = tuple(int(p) for p in parts)
    except ValueError:
        raise ValueError(f"marker IDs must be whole numbers, got {text!r}") from None
    if len(set(ids)) != len(ids):
        raise ValueError("marker IDs repeat")
    return ids
