# Labelling guidance

Read this before labelling a single frame under `labels/`, and before
proposing a detector class list for a new prop family. The edge-case
rules in the second half matter more than the specific class list below
— a class list is a few hours of rework if it's wrong; inconsistent
annotation rules quietly poison every model trained on the corpus.

## The class list is an example, not a schema

The list in this section is what was decided for **this pilot corpus**
(5 clips, jar prop family, `configs/objects/profile_jar.yaml`), after
reviewing `manifest/separability_check.png` (40 candidate-ambiguous
frames, see `scripts/separability_check.py`). It is not a universal
constant. A different prop family, a different number of modules, or a
protocol with a different step sequence can legitimately need a
different class list — decide it the same way (below), don't copy this
one by default.

**Decided list**, `bas_specimen_v1` / jar:

```
case_open, case_closed, red_module, yellow_module, red_lid, yellow_lid, hand
```

**Method — apply this to any prop family, not just this one:**

A class should capture something a classifier can determine from
**appearance alone**, in a single frame, with no other context. If
answering the question requires knowing *where* something is relative
to something else, or requires interpolating a *continuum*, it is not a
classification problem — it is geometry, and belongs in
`src/kinematics/`, computed from bounding boxes, not asked of the
detector.

Two classes were rejected on exactly this basis, both confirmed against
real transition frames in this corpus (not assumed):

- **`module_in_case` / `module_free`** — rejected. A module's top
  surface photographs almost identically whether the module is inside
  the case or sitting upright just outside it (checked directly: both
  read as a flat circular top from directly overhead for a cylindrical
  jar). The actual distinguishing signal is **position**, not
  appearance: is the module's bbox centroid inside the case's bbox, in
  **rack-space coordinates** (not image space — a camera angle changes
  what "inside" looks like in pixels but not in rack space). Compute
  this from `red_module`/`yellow_module` and case detections directly;
  it needs no new class.
- **`case_half_open`** — rejected for the same reason a step's
  `condition` is never "roughly done": openness is continuous, and
  discretizing it into a classifier class throws away precision the
  geometry already has for free. Derive lid angle/travel from the
  lid's own bbox relative to the body/case bbox —
  `src/kinematics/lid_state.py` already does exactly this
  (`make_measurer()`, hinge-angle for `lid_type: hinged`, axial travel
  for `lid_type: screw`) with hysteresis, for module lids. It is the
  reason module lids (`red_lid`/`yellow_lid`) ARE their own detected
  class — the *box needs to be found*, even though its *state* is never
  classified — while the container's own hinge state is instead two
  direct whole-shape classes (`case_open`/`case_closed`): its lid is a
  large flap that changes the whole container's silhouette, not a small
  separate part like a screw cap, so appearance alone already separates
  open from closed and there is no continuum worth tracking for it.

When you propose a class list for a new prop family, re-run this
method: pull real candidate-ambiguous frames near actual state
transitions (`scripts/separability_check.py` — the sample must be dense
around transitions, not uniform random; see that script's docstring for
why), look at them, and ask of every candidate class: "could this be
answered from appearance alone, in one frame, or does it secretly need
position or a continuum?"

## Object profile schema

`configs/objects/*.yaml` binds protocol roles to these classes:

- `roles.<role>.class_id` — the role's own detected class (a module).
- `roles.<role>.lid_class_id` — present only when the role's lid is
  independently detected as its own bbox (state derived geometrically
  from it, per above). Omit entirely for a lidless role.
- `roles.container.state_class_ids.{open,closed}` — the container's own
  state as two direct classes, when (as here) its lid is a whole-shape
  appearance change rather than a small separately-tracked part. A prop
  family where the container's lid behaves more like a module lid
  (small, independently trackable) should use `lid_class_id` on it
  instead — this is a per-profile judgment call, not a fixed rule.
- `detector_classes_not_role_bound` — classes needed for kinematics but
  not bound to any protocol role (currently: `hand`).

## Annotation edge-case rules

These apply to every prop family, every class list. The failure mode
they all guard against is the same one this session already hit and
fixed twice elsewhere in this repo (a fabricated confident answer is
worse than an honest "can't tell"): **never label a box with more
precision than the frame actually supports.**

- **Module half-occluded by a hand.** Label the box as your best
  estimate of the module's **full extent**, including the occluded
  part, if you can confidently infer it from the visible portion and
  the object's known shape (e.g. a cylinder's visible curve implies the
  rest of the circle). If the occluded fraction is large enough that
  you're guessing rather than inferring — you cannot say within roughly
  one box-width where the far edge is — do not fabricate a box. Skip
  the frame for that instance and flag it as `occlusion` in the
  annotation tool's notes/attributes field, do not silently omit it
  (an omitted instance with no note looks identical to "this frame
  correctly has no module," which is a different fact).
- **Lid mid-rotation / mid-unscrew.** Label the lid's box exactly where
  it visually is at that instant — never round to "closed" or "open."
  This is the entire point of deriving state geometrically instead of
  classifying it: the label only needs to be accurate to *where the lid
  currently is*, not to *what state that counts as*. Getting the box
  right is enough; do not editorialize by placing it as if it were
  further open or closed than it visually is.
- **Motion-blurred frame.** If you cannot place an edge within roughly
  one box-width of confidence because of blur, skip the instance and
  flag it `motion_blur`, same as occlusion — do not average toward a
  guessed sharp edge. A detector trained on confidently-mislabelled
  blur is worse than one that simply saw fewer blurred examples.
- **General rule underlying all three:** a skipped, flagged instance
  costs one fewer training example. A confidently wrong box costs a
  false signal the model has no way to distinguish from a correct one,
  and that cost compounds across every frame labelled the same
  over-confident way. When in doubt, skip and flag; don't guess.
