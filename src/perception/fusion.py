"""Per-frame detections -> debounced semantic step events.

Emits the four actions the container/module geometry can support today:

    open(container) / close(container)       from case_open vs case_closed
    remove_from(module, container)            module leaves the container
    place_into(module, container)             module comes back

Design decisions, stated because they decide test outcomes:

* PER-OBJECT state, never merged. Every role (container, module_a,
  module_b, ...) has its own debounce window. Two different objects
  moving close together in time -- one module still out while the
  other is being taken (a held-out fixture clip) -- produce two distinct events. The only merging
  anywhere downstream is of spoken ALERT lines; step events never merge.
* k-of-n agreement per object (configs/defaults.yaml timing), counted
  over frames that carry EVIDENCE for that object. A frame where the
  object is not detected (occluded by a hand, container closed, detector
  miss) adds nothing: the last confirmed state holds. After `stale_s`
  without evidence the window is cleared, so votes from before an
  occlusion are never combined with votes after it.
* Initial states are the engine's: container closed, modules inside. So
  a clip that starts with the container already open still produces the
  "open" event once that is confirmed.
* Containment, image space (default, and the fallback whenever the rack
  is unknown): the module's box must lie MOSTLY inside the container's
  box (min_overlap), not merely have its centre inside -- in an oblique
  view a slab held in front of the box overlaps it in the image while
  being out (seen in a held-out fixture clip).
* Containment, rack space (`perception.geometry: auto`, used only while
  the ArUco rack pose is ok/held -- src/perception/rack.py): the module
  centre and the container's ROTATED box are mapped onto the rig floor
  in mm; inside = the point lies within the container footprint plus
  `rack_margin_mm`. What that fixes over image space: (1) the image test
  uses axis-aligned boxes, and a container sitting rotated in the tub has
  an AABB covering floor beside it -- a module set down next to it read
  as "in"; (2) the footprint is remembered in floor mm, so it survives a
  moved camera; (3) the CLOSED container's footprint is kept as the
  interior while it is open -- a case_open box includes the open lid
  flap, so a module put down on the open lid read as "in".
  Switching between the two geometries clears the vote windows (votes
  from different geometries are never combined); confirmed states stay.
* The container box persists while the container is not detected (it
  does not move; hands occlude it constantly).
* Known limit (measured on the tuning clips, 2026-09-24): from a
  top-down camera a module carried back and still hovering ABOVE the box
  reads as inside, so a return can register up to ~3 s early (train2,
  train3). A "hand must be off the module" rule was tried and reverted:
  swept over 0.15-1.0 hand-overlap thresholds it recovered nothing (best
  10/12 = same as without it) -- hand boxes cover modules resting in the
  box too. Rack space does NOT fix this: a floor homography carries no
  height, and a module hovering over the box maps onto the box's floor
  area. The fix needs a depth cue -- the grasp signal from
  src/kinematics/grasp.py (hand still holding it = not placed yet).

Operator presence: StateEvent("operator.hands_in_view", bool) on every
confirmed change, from its own k-of-n vote over "any hand class detected
in this frame" (perception.hands_k / hands_n; a detector missing a hand
for a frame or two must not read as "operator left"). Hand classes are
the profile's detector_classes_not_role_bound unless perception.hand_classes
says otherwise. Consumed by the engine's attended_while_open constraint.

Lid steps (open/close a module's lid, stow the lid) are NOT emitted yet:
stowing needs a rack-space stow zone that does not exist, and lid
open/close needs the lid-vs-body rule (src/kinematics/lid_state.py) fed
with tracked lid boxes -- next step. Until then, those steps are
confirmed by the operator ("Hey BAS, next step").
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np

from src.perception.detector import Detection
from src.protocol.events import ActionEvent, StateEvent

HANDS_IN_VIEW = "operator.hands_in_view"  # same key as src.protocol.engine.HANDS_IN_VIEW

Box = tuple[float, float, float, float]  # x0, y0, x1, y1


# ----------------------------------------------------------------------
# Debounce over categorical states
# ----------------------------------------------------------------------

class StateVote:
    """k-of-n agreement over categorical observations for one object."""

    def __init__(self, initial: str, k: int, n: int, stale_s: float) -> None:
        if not 1 <= k <= n:
            raise ValueError(f"need 1 <= k <= n, got k={k} n={n}")
        self.state = initial
        self.k, self.n, self.stale_s = k, n, stale_s
        self._window: deque[str] = deque(maxlen=n)
        self._last_ts: float | None = None

    def observe(self, ts: float, value: str) -> str | None:
        """Returns the NEW state on a confirmed transition, else None."""
        if self._last_ts is not None and ts - self._last_ts > self.stale_s:
            self._window.clear()
        self._last_ts = ts
        self._window.append(value)
        if value != self.state and sum(1 for v in self._window if v == value) >= self.k:
            self.state = value
            self._window.clear()
            return value
        return None

    def reset_window(self) -> None:
        """Forget pending votes, keep the confirmed state."""
        self._window.clear()
        self._last_ts = None


# ----------------------------------------------------------------------
# Geometry (image space now; rack space later, same interface)
# ----------------------------------------------------------------------

class Geometry(Protocol):
    def inside(self, obj: Detection, container: Box) -> bool: ...


def overlap_fraction(inner: Box, outer: Box) -> float:
    """Fraction of `inner`'s area that lies within `outer`."""
    ix0, iy0 = max(inner[0], outer[0]), max(inner[1], outer[1])
    ix1, iy1 = min(inner[2], outer[2]), min(inner[3], outer[3])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    area = max(1e-9, (inner[2] - inner[0]) * (inner[3] - inner[1]))
    return inter / area


@dataclass(frozen=True)
class ImageSpaceGeometry:
    min_overlap: float = 0.8

    def inside(self, obj: Detection, container: Box) -> bool:
        return overlap_fraction(obj.aabb, container) >= self.min_overlap


def floor_polygon(fit: Any, corners: Any) -> np.ndarray:
    """A detection's rotated-box corners (pixels) -> floor polygon (mm)."""
    from src.perception.rack import to_rack

    return to_rack(fit, np.asarray(corners, dtype=np.float64).reshape(-1, 2))


def signed_distance_mm(poly: np.ndarray, pt: np.ndarray) -> float:
    """> 0 inside the polygon, < 0 outside (distance to its edge, mm)."""
    import cv2

    return float(cv2.pointPolygonTest(poly.astype(np.float32).reshape(-1, 1, 2),
                                      (float(pt[0]), float(pt[1])), True))


def polygon_area(poly: np.ndarray) -> float:
    x, y = poly[:, 0], poly[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def covered_fraction(inner: np.ndarray, outer: np.ndarray) -> float:
    """Fraction of `inner` polygon's area inside convex `outer` (mm)."""
    import cv2

    area = polygon_area(inner)
    if area <= 0:
        return 0.0
    inter, _ = cv2.intersectConvexConvex(inner.astype(np.float32), outer.astype(np.float32))
    return float(inter) / area


# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class FusionConfig:
    k: int = 5
    n: int = 8
    stale_s: float = 1.5
    min_overlap: float = 0.8
    min_conf: dict[str, float] = field(default_factory=dict)  # per class; default: detector conf
    geometry: str = "image"  # "image" | "auto" (rack space while the rack pose is known)
    rack_margin_mm: float = 15.0  # module centre may lie this far outside the footprint
    # While open, the last CLOSED footprint is the interior -- as long as
    # the open box still covers this fraction of it (else the container
    # moved: use the open box).
    closed_footprint_min_cover: float = 0.7
    hands_k: int = 8  # "hands gone" / "hands back" needs k of the last n frames
    hands_n: int = 10
    hand_min_conf: float = 0.0  # on top of detector.conf

    @classmethod
    def from_config(cls, runtime_cfg: dict[str, Any], timing: dict[str, Any]) -> "FusionConfig":
        p = runtime_cfg.get("perception") or {}
        geometry = str(p.get("geometry", "image"))
        if geometry not in ("image", "auto"):
            raise ValueError(f"perception.geometry must be 'image' or 'auto', got {geometry!r}")
        return cls(
            k=int(timing.get("step_debounce_frames", 5)),
            n=int(timing.get("step_debounce_of_n", 8)),
            stale_s=float(p.get("stale_s", 1.5)),
            min_overlap=float(p.get("containment_min_overlap", 0.8)),
            min_conf={str(k): float(v) for k, v in (p.get("min_conf") or {}).items()},
            geometry=geometry,
            rack_margin_mm=float(p.get("rack_margin_mm", 15.0)),
            closed_footprint_min_cover=float(p.get("closed_footprint_min_cover", 0.7)),
            hands_k=int(p.get("hands_k", 8)),
            hands_n=int(p.get("hands_n", 10)),
            hand_min_conf=float(p.get("hand_min_conf", 0.0)),
        )


# ----------------------------------------------------------------------
# Fusion
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class RoleBinding:
    container: str
    open_cls: str
    closed_cls: str
    modules: dict[str, str]  # role -> detector class
    hand_classes: frozenset[str] = frozenset()  # empty = presence not tracked

    @classmethod
    def from_profile(cls, profile: dict[str, Any], container_roles: set[str],
                     module_roles: set[str]) -> "RoleBinding":
        roles = profile.get("roles") or {}
        (container,) = sorted(container_roles) or ("container",)
        states = (roles.get(container) or {}).get("state_class_ids") or {}
        if "open" not in states or "closed" not in states:
            raise ValueError(f"profile role {container!r} needs state_class_ids open/closed")
        modules = {}
        for role in sorted(module_roles):
            cls_id = (roles.get(role) or {}).get("class_id")
            if not cls_id:
                raise ValueError(f"profile role {role!r} has no class_id")
            modules[role] = str(cls_id)
        hands = frozenset(str(c) for c in (profile.get("detector_classes_not_role_bound") or []))
        return cls(container, str(states["open"]), str(states["closed"]), modules, hands)


class SceneFusion:
    """Feed every processed frame's detections; get back ActionEvents."""

    def __init__(self, binding: RoleBinding, cfg: FusionConfig,
                 geometry: Geometry | None = None) -> None:
        self.binding = binding
        self.cfg = cfg
        self.geometry = geometry or ImageSpaceGeometry(cfg.min_overlap)
        self.container_box: Box | None = None
        self.container = StateVote("closed", cfg.k, cfg.n, cfg.stale_s)
        self.modules = {role: StateVote("in", cfg.k, cfg.n, cfg.stale_s)
                        for role in binding.modules}
        # rack space (floor mm): footprints of the last closed / open box
        self.closed_floor: np.ndarray | None = None
        self.open_floor: np.ndarray | None = None
        self.mode = "image"  # geometry used for the last update
        self.hands = StateVote("present", cfg.hands_k, cfg.hands_n, cfg.stale_s)

    def _best(self, dets: list[Detection], classes: set[str]) -> Detection | None:
        ok = [d for d in dets if d.cls in classes and d.conf >= self.cfg.min_conf.get(d.cls, 0.0)]
        return max(ok, key=lambda d: d.conf) if ok else None

    def interior_floor(self) -> np.ndarray | None:
        """Container interior on the floor (mm): the closed footprint while
        the open box still covers it, else the open box."""
        closed, opened = self.closed_floor, self.open_floor
        if self.container.state == "closed" or opened is None:
            return closed if closed is not None else opened
        if closed is not None and covered_fraction(closed, opened) >= self.cfg.closed_footprint_min_cover:
            return closed
        return opened

    def update(self, ts: float, dets: list[Detection], rack_pose: Any = None) -> list[ActionEvent | StateEvent]:
        """rack_pose: src.perception.rack.RackPose of the SAME frame, or None.
        Used only with geometry 'auto' and a known pose (ok / held)."""
        b = self.binding
        events: list[ActionEvent | StateEvent] = []
        if b.hand_classes:
            seen = any(d.cls in b.hand_classes and d.conf >= self.cfg.hand_min_conf for d in dets)
            new_h = self.hands.observe(ts, "present" if seen else "absent")
            if new_h is not None:
                events.append(StateEvent(ts=ts, key=HANDS_IN_VIEW, value=new_h == "present"))
        fit = None
        if (self.cfg.geometry == "auto" and rack_pose is not None
                and rack_pose.status in ("ok", "held") and rack_pose.fit is not None):
            fit = rack_pose.fit

        box = self._best(dets, {b.open_cls, b.closed_cls})
        if box is not None:
            self.container_box = box.aabb
            if fit is not None:
                poly = floor_polygon(fit, box.corners)
                if box.cls == b.closed_cls:
                    self.closed_floor = poly
                else:
                    self.open_floor = poly
            new = self.container.observe(ts, "open" if box.cls == b.open_cls else "closed")
            if new is not None:
                events.append(ActionEvent(ts=ts, action="open" if new == "open" else "close",
                                          target=b.container, confidence=box.conf))

        interior = self.interior_floor() if fit is not None else None
        # The geometry actually used decides the mode (rack needs a footprint).
        mode = "rack" if interior is not None else "image"
        if mode != self.mode:
            for vote in self.modules.values():
                vote.reset_window()
            self.mode = mode
        for role, cls_id in b.modules.items():
            det = self._best(dets, {cls_id})
            if det is None:
                continue  # no evidence: hold the confirmed state
            if interior is not None:
                pt = floor_polygon(fit, [(det.cx, det.cy)])[0]
                inside = signed_distance_mm(interior, pt) >= -self.cfg.rack_margin_mm
            elif self.container_box is not None:
                inside = self.geometry.inside(det, self.container_box)
            else:
                continue
            where = "in" if inside else "out"
            new = self.modules[role].observe(ts, where)
            if new == "out":
                events.append(ActionEvent(ts=ts, action="remove_from", target=role,
                                          source=b.container, confidence=det.conf))
            elif new == "in":
                events.append(ActionEvent(ts=ts, action="place_into", target=role,
                                          dest=b.container, confidence=det.conf))
        return events

    def states(self) -> dict[str, str]:
        out = {self.binding.container: self.container.state,
               **{r: v.state for r, v in self.modules.items()}}
        if self.binding.hand_classes:
            out["hands"] = self.hands.state
        return out


def binding_for(resolved: Any) -> RoleBinding:
    """Container and module roles as the protocol uses them (sources/dests
    of remove_from/place_into are containers; their targets are modules),
    bound to detector classes through the resolved object profile."""
    containers: set[str] = set()
    modules: set[str] = set()
    for sid in resolved.parsed.order:
        node = resolved.parsed.nodes[sid]
        if node.action in ("remove_from", "place_into"):
            modules.add(node.target.split(".", 1)[0])
            if node.source:
                containers.add(node.source)
            if node.dest:
                containers.add(node.dest)
    return RoleBinding.from_profile(resolved.parsed.object_profile or {}, containers, modules)


def with_hand_classes(binding: RoleBinding, runtime_cfg: dict[str, Any]) -> RoleBinding:
    """perception.hand_classes (config) overrides the profile's list."""
    from dataclasses import replace

    override = (runtime_cfg.get("perception") or {}).get("hand_classes")
    return binding if override is None else replace(binding, hand_classes=frozenset(map(str, override)))
