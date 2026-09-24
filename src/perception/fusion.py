"""Per-frame detections -> debounced semantic step events.

Emits the four actions the container/module geometry can support today:

    open(container) / close(container)       from case_open vs case_closed
    remove_from(module, container)            module leaves the container
    place_into(module, container)             module comes back

Design decisions, stated because they decide test outcomes:

* PER-OBJECT state, never merged. Every role (container, module_a,
  module_b, ...) has its own debounce window. Two different objects
  moving close together in time -- test2.mp4 has one slab out while the
  other is being taken -- produce two distinct events. The only merging
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
* Containment is image-space for now: the module's box must lie MOSTLY
  inside the container's box (min_overlap), not merely have its centre
  inside -- in an oblique view a slab held in front of the box overlaps
  it in the image while being out (test1.mp4, 12-20 s). Rack-space
  geometry from ArUco (not built) replaces `ImageSpaceGeometry` behind
  the same interface.
* The container box persists while the container is not detected (it
  does not move; hands occlude it constantly).
* Known limit (measured on the tuning clips, 2026-09-24): from a
  top-down camera a module carried back and still hovering ABOVE the box
  reads as inside, so a return can register up to ~3 s early (train2,
  train3). A "hand must be off the module" rule was tried and reverted:
  swept over 0.15-1.0 hand-overlap thresholds it recovered nothing (best
  10/12 = same as without it) -- hand boxes cover modules resting in the
  box too. The fix is depth: rack-space geometry (ArUco) or the grasp
  signal from src/kinematics/grasp.py.

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

from src.perception.detector import Detection
from src.protocol.events import ActionEvent

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

    @classmethod
    def from_config(cls, runtime_cfg: dict[str, Any], timing: dict[str, Any]) -> "FusionConfig":
        p = runtime_cfg.get("perception") or {}
        return cls(
            k=int(timing.get("step_debounce_frames", 5)),
            n=int(timing.get("step_debounce_of_n", 8)),
            stale_s=float(p.get("stale_s", 1.5)),
            min_overlap=float(p.get("containment_min_overlap", 0.8)),
            min_conf={str(k): float(v) for k, v in (p.get("min_conf") or {}).items()},
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
        return cls(container, str(states["open"]), str(states["closed"]), modules)


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

    def _best(self, dets: list[Detection], classes: set[str]) -> Detection | None:
        ok = [d for d in dets if d.cls in classes and d.conf >= self.cfg.min_conf.get(d.cls, 0.0)]
        return max(ok, key=lambda d: d.conf) if ok else None

    def update(self, ts: float, dets: list[Detection]) -> list[ActionEvent]:
        b = self.binding
        events: list[ActionEvent] = []

        box = self._best(dets, {b.open_cls, b.closed_cls})
        if box is not None:
            self.container_box = box.aabb
            new = self.container.observe(ts, "open" if box.cls == b.open_cls else "closed")
            if new is not None:
                events.append(ActionEvent(ts=ts, action="open" if new == "open" else "close",
                                          target=b.container, confidence=box.conf))

        for role, cls_id in b.modules.items():
            det = self._best(dets, {cls_id})
            if det is None or self.container_box is None:
                continue  # no evidence: hold the confirmed state
            where = "in" if self.geometry.inside(det, self.container_box) else "out"
            new = self.modules[role].observe(ts, where)
            if new == "out":
                events.append(ActionEvent(ts=ts, action="remove_from", target=role,
                                          source=b.container, confidence=det.conf))
            elif new == "in":
                events.append(ActionEvent(ts=ts, action="place_into", target=role,
                                          dest=b.container, confidence=det.conf))
        return events

    def states(self) -> dict[str, str]:
        return {self.binding.container: self.container.state,
                **{r: v.state for r, v in self.modules.items()}}


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
