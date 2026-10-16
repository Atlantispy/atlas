# Width r2 (pose rounding and deviation bound): where it is integrated

What is rounded, and the proofs, are in `T/ps/width/DESIGN.md` r2 (f6e6dc64). That design is the
authority. This note covers only where the transforms enter the composition.

- **Files.** These follow the design:
  - W = `integration_wall_measures` (`_pose_vector`, b-ray);
  - E = `integration_exterior_mesh` (`_representative_pose`, b-quat);
  - M = `integration_differential_mesh` (stored `total_error`, c).
  - An earlier geometry note named `current_geometry_from_interval`. That is a function, not a module,
    and the name is withdrawn.
- **Bases.** Today W, E and M are d6b7d472, d338238e and ab0f31f8, the same in composed-r2/src and in
  the pressure tree. No geometry transform touches them:
  - the DG chain;
  - cpadopt, q2fast and jetsfast;
  - workers6, workers6rolling and workers6clamp;
  - WP18 r2;
  - D1 (moving_interface) and D2 (moving_face);
  - G-PY (moving_face).
  So every pin above is stable.
- **Order.** The width transforms go last in the geometry stage, after every byte-identical step:
  chain, cpadopt, q2fast, jetsfast, d1det, d2rot, G-PY, then widthround (b-ray + b-quat), then widthdev (c).
  - Reason: width is an identity successor, and D1/D2 and G-PY are proved by byte-identical parity on
    one base (design section 6). Composing width first would void that evidence.
  - Kernel twin T1 (native `_rotated_normal`) is text-disjoint from b-ray and stacks in either order. If it
    lands in W first, widthround's W input pin moves to T1's output, and its unit tests run again.
    Anchors are never fuzzy.
- **Registration.** `scripts/compose_test_runtime.py` registers `widthround` and `widthdev` by the design's
  transform files. Their shas are pinned when they are built, and each transform refuses an input sha it
  does not know.
- **(c) on E** (the design leaves it to geometry): apply the same rule to E's stored deviation field
  (E:701/739, 909/954), in widthdev. Two conditions:
  1. the design's note-9 check also holds there (the stored value is only compared with the budget, and
     no reader re-derives it);
  2. a unit test shows `stored >= total_error` and that pass/fail is unchanged.
  - Reason: the proof is the same, and applying it now avoids a second identity successor later.
  - If check 1 fails for E, E keeps the exact sum.
- **Acceptance at integration:**
  - the design's unit tests on the composed runtime;
  - then the one IV1 replay (design section 5) of the composed successor against the current route,
    reporting each physical field's maximum change beside its certified bound, and the new widths.
