# Pose/heat width fix: design (Pressure speed and pose width, 16 Oct 2026). For review before any code.

Michael's approval: options (b) and (c), "as long as we don't lose significant accuracy". Option (a) is not used,
and MAX_INTEGER_BYTES (1 MiB) is not raised.

Paths:
- S = T/ps/c/full6/src/atlas_tectonics (unchanged; read only).
- Background: R/probes/step8/claude-20261015/heat-width/heat-magnitude-width-20261016.md.

Evidence, all on synthetic inputs (pose_width_steps.py's plate rate and 1 Myr binary64 interval; no state; small lane, 1 core):
- pose_round_probe_r2.py calls the runtime's unchanged _rotated_normal, _segment_quaternion and _qmul (probe-r2.json, MEASURED).
- check_round_mpmath.py (review env, 400 digits, closed-form true pose; SymPy for the rounding lemma) gives
  ENCLOSURE PASS on all 21 cases, n = 1 to 1,000 (check-round-mpmath.log, MEASURED).

## 1. The budgets (where declared, values)

| path | per-step allowance (declared) | acceptance budget downstream | production value |
|---|---|---|---|
| Ray pose. W._pose_vector = sum of _rotated_normal steps. D posed support and _ray_box, E/W physical enclosure | Taylor target `t_L = max\|v\|/2^(32+2L)` per step (W:75, "algorithm policy"). Euclidean radius `3*tail + half*\|w x v\|_1`, with tail <= t_L. Radii ADD over steps (W:103, 106-116) | (i) _pose_binding: error <= ATTACHMENT_BAND_RAD (D:550). (ii) Volume leaves: hi-lo <= max_width_m3 = width/(2*max(1, carried)) (M:614/889, W:416). (iii) Sign/separation tests (D:706, 3774, 4365-4666), which have no budget | ATTACHMENT_BAND_RAD = 64*eps = 1.42e-14 (integration_sphere:69). width = max_geometry_volume_error_m3 = 32*R^3 (private_heat_original_joined_r8 mesh edit) |
| Quaternion pose. E._representative_pose (E:625/833, D:772 posed boundary, P:112 force pose) | goal = operator_goal/(8n) per segment (E:395) | 4*error <= operator_goal (E:406). E: operator_goal = pose_goal = min(1/2, 3*width/(32*nplanes*R^3)), "at most half the volume budget" (E:615-20). D:772 and P: max_operator_error | max_operator_error = 1e-20 (funding_transfer:189, continuation_r1:48). P: force/power error limits (P:200) |
| Mesh deviation sum. M total_error (M:674/953) | n/a | total_error <= width (M:675/954). The stored field is only compared with the budget (no reader re-derives it; mesh_tables only stores it) | width = 32*R^3 |

## 2. Insertion points and error propagation

### (b-ray): in W._pose_vector's step loop (W:113-116), after each step whose delta > 0

```
norm = max|v_in|;  v, delta = _rotated_normal(v, ...);  error += delta
if delta:  q = 2**(floor_log2(norm) - (32+2*level) - G_R);  v = round_to(v, q);  error = round_up(error + q, q)
```

- **Round to nearest (q dyadic).** Each component moves by at most q/2, so the 2-norm moves by at most
  (sqrt(3)/2)q <= q. The radius therefore still encloses the true pose: true rotations are orthogonal, so
  radii add, as the existing code already relies on.
- **round_up(e+q, q) adds [q, 2q)** and keeps the radius on the same short dyadic grid. Without this the
  radius itself widened (probe r1).
- **delta == 0 means an exact step**, either w x v = 0 or a zero-time current step, so it is left
  unrounded. This keeps the end pose of interval n equal to the start pose of interval n+1, as today.
- **inverse=True, every level, every caller** (D _ray_box, _constraint_pose, _fan/_source_planes,
  _boundary_leaf, W _pose_planes) get the rule through this single function. Their cache keys are
  unchanged, because the function stays deterministic.

### (b-quat): in E._representative_pose's loop (E:400-402)

```
q = 2**(floor_log2(goal) - G_Q), set once
Q = round_to(_qmul(s, Q), q)
e = round_up((1+delta)*e + delta + q, q)
```

- **Rounding.** On 4 components |r|_2 <= (sqrt(4)/2)q = q.
- **Bound on the product.** |s~Q~ - sQ| <= delta(1+e) + e, because |Q~| <= 1+e. The recurrence
  therefore holds with r added.
- **Unchanged.** The final check `error >= 1 or 4*error > operator_goal` and the return of 4*error stay
  as they are.

### (c): in M after the unchanged exact comparison (M:675, M:954; record fields at M:733, M:1016)

```
stored = 0 if total_error == 0 else min(round_up(total_error, 2**(floor_log2(total_error) - 64)), width)
```

- **Outward.** Since total_error <= width at this point, `stored >= total_error`.
- **Relative excess** is below 2^-64 (5.4e-20).
- **No pass/fail change at all.** The decision is still taken on the exact sum, and stored <= width, so a
  later "stored <= budget" check agrees with the build.
- **E, the exterior mesh**, has the same field (E:701/739, 909/954). The same rule is optional there, for
  Geometry to decide.

## 3. Precision (derived from the bar: <= 1% of the budget, cumulative over 1,000 intervals)

| path | proven added error / allowance | 1% needs | chosen | result | measured (probe r2, n <= 1,000) |
|---|---|---|---|---|---|
| ray | < 2q/(3t_L) <= (2/3)·2^-G_R per step; the ratio is the same summed over any n | G_R >= 7 | **G_R = 12** | **<= 0.016%** of the ray allowance; vs ATTACHMENT_BAND_RAD at L=24 after 1,000 steps: 4e-25/1.42e-14 = 3e-11 | 0.015% (L0) and 0.16-0.21% (L24) of the ACTUAL existing radius; widths 44-46 bits (L0) and 93-94 bits (L24), flat |
| quaternion | 4*added < 8nq·e^(operator_goal/8) <= operator_goal·2^-G_Q, independent of n | G_Q >= 7 | **G_Q = 10** | **<= 0.098%** of operator_goal | 0.066-0.097%; quaternion 66-76 bits, error 62-70 bits, flat |
| deviation sum | relative 2^-64 | any | **P = 64** | 5.4e-20 | (not probed; arithmetic) |

Pass/fail effect:
- **Quaternion check: cannot flip.** The existing 4*error <= operator_goal·(1/2)(1+eps). With rounding
  it is at most operator_goal·(1/2 + 1/1024)(1+eps), which is still below operator_goal.
- **Ray tests: flip only in a sliver.** A ray test changes outcome only if its margin lies within the
  added radius, at most 2^-11 of the step target:
  - **Band and sign tests:** such a flip refuses, it never gives a wrong pass.
  - **Leaf width tests (`met`, bisection):** an extra refinement level in the sliver costs time only.
    A refusal happens only at the max_leaves edge.
- **(c): nothing flips** (see section 2).

Guard bits cost about 1 bit per value each, so the extra margin (12 vs 7, 10 vs 7) is nearly free.

## 4. Projected widths (% of 8,388,608 bits). Without = the note's linear law; with = flat after one step (PROJECTED)

| field | IV1 measured | without: IV2 / IV3 / IV4 / IV5 | with (b)+(c): IV1 to IV5 |
|---|---:|---|---|
| heat exact_cell_storage_residual_j | 24.5% | 43-49 / 62-73 / 80-98 / **refuses** | ~5-7%, flat (heat ~ 53x metric width) |
| mesh per-element metric | 0.46% (38,455) | 0.8 / 1.2 / 1.5 / 1.9% | ~0.11% (~9.1k bits; root 8,128 at 53-bit rays, interpolated at 94-bit rays), flat |
| mesh deviation sum | 7.3% (614,116) | 14 / 21 / 28 / 35% | <= ~70 bits, flat |
| posed ray, L24 / quaternion | 1,345 / 834 bits | +1,291 / +833 bits per interval | 94 / ~70-76 bits, flat |

## 5. Identity impact

- **Every exact value downstream of a moving pose changes from IV1 on.** That covers the posed supports,
  mesh metric, ledgers, ids, and E/P poses, so this is an **identity successor**.
- **The three modules' source hashes change.** That alone refuses mixing with old stores, because the
  loaded-implementation and source checks stay untouched. No new record field is needed.
- **Physical outputs stored in binary64** (heat stocks, transport, state) should mostly be bit-identical.
  The pose moves by <= 2^-92 relative at L24, which crosses a binary64 rounding boundary only rarely.
- **One ticket after RESUME** (after q02 and the P1 proof): an IV1 replay on the successor against the
  current route. It reports the max change of every physical output field next to that field's
  certified bound, plus the new widths.

## 6. Interactions

- **Geometry D1/D2** (moving_interface/moving_face moments; byte-identical parity on the deep set and the
  IV1/IV2 surfaces):
  - moving_interface_moments calls D._ray_box (l.607/860/892), so its inputs change under (b).
  - The D1/D2 parity must therefore compare arms on the SAME base. Run it first on the current route,
    then compose the width successor after D1/D2 and G-PY.
  - D._rotation_boxes (moving_face l.211) composes its own history and is untouched.
- **G-PY** (Exact kernels q11 c5f2a123, composed after D2):
  - If it edits integration_wall_measures, the (b) transform anchors on G-PY's output sha.
  - round_to must keep the Fraction types that the exact_scale and shortcut type checks read
    (W:79, D:1876).
  - Narrower numbers mean the jets and kernels run on ~100-bit operands, not kbit ones: faster, and
    exact either way.
  - Exact kernels' D5 T1, a native `_rotated_normal` twin (T/ck/d5/DESIGN.md section 4):
    - My edit is in `_pose_vector`, which is text disjoint from T1. The two stack in either order.
    - T1 returns new Fractions, which round_to then consumes.
    - With (b), T1's operands become dyadics of at most (32+2L+12) bits, so T1's gain shrinks. Measure it both ways.
- **WP18:** serial-vs-parallel parity on one package is unaffected. Batch and decode sizes shrink, so
  WP18's and P1's booked envelopes become over-bookings and go on the match-real-cost re-measure.
- **Runner's width gate** (W(N+1) <= 50%, W(N+2) <= 100%) stays Runner's:
  - Its "IV1 rerun reproduces r9's widths exactly" baseline must be re-pinned to the successor's IV1
    replay. This is a declared change, not a defect.
  - The slope is then about 0, so the gate passes IV3 onward.
- **Not covered by this change.** Other routes compose the raw history themselves:
  - D._rotation_boxes (moving_face),
  - spatial_pressure._rotation_path,
  - interface_exclusion and rigid_intersection.

  Their outputs are projected to binary64, so they never reach the 1 MiB limit, but their cost grows
  linearly. They are a later profiling item.

## 7. Build plan (after review)

- **New-file source transforms in T/ps/width**, input-sha pinned and refusing on mismatch:
  - width_pose_round.py, covering (b-ray) and (b-quat);
  - width_deviation_bound.py, covering (c).
- **Unit tests:** the probe's cases through the transformed modules, plus check_round_mpmath.
- **Fail-closed mutants**, each of which the mpmath check or the tests must catch:
  - no radius added;
  - round_up replaced by round-nearest;
  - a quantum 2^4x too coarse;
  - rounding on delta == 0, which breaks the end(n) = start(n+1) equality;
  - (c) storing round-down.
- **One refuter on the design** (now), then Geometry's review and integration, then the replay ticket.

Later-step impact (PROJECTED):
- The width gate passes IV3 onward.
- Exact pose arithmetic gets cheaper: n narrow steps per call instead of widths growing ~1.3 kbit per
  interval.
- Downstream clip/volume/heat arithmetic runs on ~9 kbit metric numbers instead of 38 kbit + 30 kbit per
  interval.
- A later exact prefix cache (pose_k = f(pose_{k-1}, step_k, level) is deterministic) could make poses
  O(1) per interval.

Next-interval capacity (PROJECTED):
- Heat per-cell fields shrink from 2.05 Mbit (24.5%) to ~0.5 Mbit (~6%) and stay flat.
- The mesh deviation sum drops from 614 kbit to ~70 bits.
- Record bytes and the per-cell RAM of the widest heat fields fall about 4x at IV1, and more at later
  intervals.
