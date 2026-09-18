# Addendum — Protocol defaults and inheritance

Append this to `CLAUDE.md`. It supersedes anything earlier in that file
that conflicts with it.

## Separation of concerns — the core design rule

The engine implements constraint **types**. A protocol selects which apply
and in which direction. Nothing is universal except physical impossibility.

Specifically: `one_module_at_a_time` is NOT a law of the system. It is a
default that a protocol may disable. A combination or mixing procedure
legitimately requires both modules open at once, which `bas_specimen_v1`
forbids. Both are valid experiments. If a rule cannot be expressed as data,
that is a design bug.

## Defaults posture — fail-safe

`configs/defaults.yaml` is inherited by every protocol. When an experiment
definition is silent on a safety question, apply the **cautious**
interpretation, not the permissive one.

Defaults are split into three tiers:

1. **Hard ordering** — physical impossibility. Engine-enforced. No protocol
   or flag can disable it.
2. **Non-overridable defaults** — `no_loose_objects`,
   `container_empty_before_close`. A protocol may ADD permitted zones but
   never remove the constraint. A floating object is a hazard regardless of
   what the experiment is trying to achieve. If a protocol sets
   `disabled: true` on one of these, emit a warning and keep it enabled.
3. **Overridable defaults** — everything else. Replaced by a protocol
   constraint of the same `id`, or toggled via `strict_mode`.

**The loader MUST print the resolved constraint set at startup**, marking
each entry `[default]` or `[protocol]`. An author who has never opened
`defaults.yaml` must still be able to see what is being enforced. Silent
defaults are how someone ends up debugging violations they never wrote.

## Groups are not atomic — read this twice

A `group` is a **naming and constraint-attachment device, not an atomicity
guarantee**. Steps inside a group MAY interleave with steps outside it
unless a `concurrency` setting or a `mutual_exclusion` constraint forbids it.

All ordering comes from `after` dependencies on individual step or group ids.
Group membership alone implies nothing about ordering.

This matters because a user may legitimately want:
`remove_b -> remove_a -> return_a -> return_b`
with both modules out simultaneously. If groups were atomic, that intent
would be inexpressible without flattening the protocol. It must be
expressible by disabling `one_module_at_a_time` and writing per-step `after`
dependencies.

## Conditional steps are skipped, not missed

When a step's `condition` evaluates false (e.g. `target.has_lid` on a prop
with no lid), the step is **skipped silently**. It is NOT a violation, NOT
logged as missed, and NOT spoken. This is what lets one protocol run on
jar props, slab props, and mixed props with only a profile swap.

The mixed-prop case — one module lidded, one not — is the strongest single
demonstration that conditional execution is real rather than decorative.
Make sure it works and put it in the demo.

## Roles, not colours

Protocols refer to `container`, `module_a`, `module_b`. The object profile
YAML binds those to YOLO classes, `has_lid`, `lid_type`, and thresholds.
**A protocol that names a colour or a shape is a bug.** Reject it in the
validator.

## The primitive set is fixed in this phase

`grasp`, `release`, `open`, `close`, `place_into`, `remove_from`,
`move_to_zone`, `dwell`.

A genuinely new kind of physical action — pour, stir, weigh, swab — requires
a new primitive **in code**. That is the honest boundary of the "no code
change" claim and must be stated on the limits slide rather than hidden:

| User's new intent | What it needs |
|---|---|
| Different order, same actions | Protocol JSON. No code. |
| Different constraints (concurrency allowed or required) | Protocol JSON. No code. |
| Different objects, same action types | Profile YAML + detector fine-tune. No code. |
| A genuinely new action | New primitive. **Code.** |

## Validator requirements

`scripts/validate_protocol.py` must check and report with **line numbers**:

- every `after` reference resolves to a real step or group id
- no dependency cycles
- every `target`, `source`, `dest` resolves to a declared role
- every role in `roles` is bound in the object profile
- every `zone` is declared and is in the `rack` frame (reject `image` frame
  zones — they break the moment the rig tilts)
- no colour or shape names appear in the protocol
- every constraint has a `basis` field (a constraint nobody can justify to a
  judge should not exist)
- `disabled: true` is not applied to a non-overridable default
- the protocol is reachable: `close_container` is satisfiable from the
  initial state

Run the validator in CI and on every hot reload. A malformed protocol must
fail loudly at load, never silently mid-run.