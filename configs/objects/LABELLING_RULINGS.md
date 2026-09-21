# Labelling rulings — quick reference

One-pager for annotators. For the *why* behind the class list and the
edge-case philosophy, see `LABELLING_GUIDANCE.md` in this folder — read
that once, keep this open while you label.

## Classes (order fixed, do not change)

```
1 case_open      5 red_lid
2 case_closed    6 yellow_lid
3 red_module     7 hand_gloved
4 yellow_module  8 hand_bare
```

## Format: OBB (rotated box), whole corpus

`canRotate="true"`. A straight object just has angle ≈ 0 — one format
for everything, no separate rules for tilted vs straight.

## Per-object rulings

**Modules (`red_module` / `yellow_module`)**
- Colour-based, covers both slab and cylinder prop shapes — no
  separate shape classes.
- Box full extent (including confidently-inferred hidden part), not
  just visible extent. Genuine guess ⇒ don't box, flag instead.

**Lids (`red_lid` / `yellow_lid`)** — cylinder module only, slab has none
- Box whenever the cap is **visible** — closed, open, or mid-rotation.
  Never skip for being "closed."
- Lid state is computed later from geometry — never classify it while
  labelling. Box where it visually is, don't round to open/closed.
- Attached: two overlapping boxes (body + lid). Detached: two separate
  non-overlapping boxes. Top-down cylinder view: near-identical overlap
  is correct, not a mistake.
- Label lids by their **own** colour, never by what they're sitting on.

**Case**
- `case_open` / `case_closed` — one whole-shape box, pick by whether the
  flap is up or down. Check every frame, don't autopilot.
- No separate lid box for the case (unlike modules).

**Hands**
- `hand_gloved` vs `hand_bare` per hand, independently — frames can mix
  a gloved hand with a bare forearm. Box hands (fingers visible), not
  bare forearms alone.

**Inside-the-case is not occlusion**
- Module fully visible inside an open case → box normally, no flag.
  "Inside" is computed later from centroid position, never annotated.
- Occlusion = your *view* is physically blocked. Not the same thing.

**ArUco markers** — not labelled, not in the class list, ignore them.

## Flags (metadata, not boxes)

| Flag | Meaning |
|---|---|
| `occlusion` | View physically blocked (hand, wall, another object) |
| `motion_blur` | Smeared; can't place an edge within ~1 box-width |
| `reflection_ambiguous` | Genuinely unsure real object vs. reflection in plastic |

- **Per-region**: box exists but is degraded → select the box, tick the
  flag.
- **Task-level**: object present but can't be boxed at all → tick the
  checkbox below the image, no box.
- Sure it's a reflection → don't box, don't flag, ignore it entirely.
  Only flag when genuinely unsure.

**Rule of thumb: box it if you can; flag only when something stops you
from boxing well; pick the flavour by whether a box exists.**

## When in doubt

Skip and flag. A confidently wrong box is worse than one fewer training
example.
