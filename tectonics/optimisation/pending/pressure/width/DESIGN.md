# Pose/heat width fix: design r2 (Pressure speed and pose width, 16 Oct 2026, 17:2x). For review before any code.

Michael's approval: options (b) and (c), "as long as we don't lose significant accuracy". Option (a) is not used,
and MAX_INTEGER_BYTES (1 MiB) is not raised.

r2 applies the refuter's findings on r1 (r1 kept as DESIGN-r1.md, eb90a5e8; verdict in STATE.md 15:49):
- BLOCKER: (b-quat) broke the posed boundary's exact axis certificate. It now rounds a coaxial history as (w, s*k).
- SHOULD-FIX: both quanta now follow the step's ACTUAL error, not the policy target or the operator goal.
- NOTES: P's limits, the D:549 norms, types, the delta rule and binary64 crossings are addressed in place.

Paths:
- S = T/ps/c/full6/src/atlas_tectonics (unchanged; read only).
- Background: R/probes/step8/claude-20261015/heat-width/heat-magnitude-width-20261016.md.

Evidence, all on synthetic inputs (no state; small lane, 1 core; MEASURED):
- pose_round_probe_r3.py (5e7af4ad) -> probe-r3.json (a67c4a0d), probe-r3.log: PROBE CHECKS PASS.
  - It calls the runtime's unchanged _rotated_normal, _segment_quaternion, _qmul, CartesianCell.rotated and
    spatial_pressure._common_axis.
  - Production operator goal 1e-20. Four histories, n = 1 to 1,000:
    - coaxial at 3.17e-15, 5.5e-17 and 1e-19 rad/s;
    - alternating between two axes.
- check_round_mpmath_r3.py (f17927be) -> check-round-mpmath-r3.log: ENCLOSURE PASS on every row.
  - Review env, 400 digits, true pose composed step by step.
  - Checks:
    - the ray, at L0 and L24;
    - the swept current step, at 5 times;
    - the quaternion;
    - exact axis parallelism, in Fractions;
    - added shares under the proven bound;
    - SymPy rounding lemmas.

## 1. The budgets (where declared, values)

| path | per-step allowance (declared) | acceptance budget downstream | production value |
|---|---|---|---|
| Ray pose. W._pose_vector = sum of _rotated_normal steps. D posed support and _ray_box, E/W physical enclosure | Taylor target `t_L = max\|v\|/2^(32+2L)` per step (W:75, "algorithm policy"). Euclidean radius `3*tail + half*\|w x v\|_1`, with tail <= t_L. Radii ADD over steps (W:103, 106-116) | (i) _pose_binding: error <= ATTACHMENT_BAND_RAD (D:550). (ii) Volume leaves: hi-lo <= max_width_m3 = width/(2*max(1, carried)) (M:614/889, W:416). (iii) Sign/separation tests (D:706, 3774, 4365-4666), which have no budget | ATTACHMENT_BAND_RAD = 64*eps = 1.42e-14 (integration_sphere:69). width = max_geometry_volume_error_m3 = 32*R^3 (private_heat_original_joined_r8 mesh edit) |
| Quaternion pose. E._representative_pose (E:625/833, D:772 posed boundary, P:112 force pose) | goal = operator_goal/(8n) per segment (E:395) | 4*error <= operator_goal (E:406). E: operator_goal = pose_goal = min(1/2, 3*width/(32*nplanes*R^3)), "at most half the volume budget" (E:615-20). D:772 and P: max_operator_error. P: force/power error limits (P:197-201) | max_operator_error = 1e-20 (funding_transfer:189, continuation_r1:48) |
| Mesh deviation sum. M total_error (M:674/953) | n/a | total_error <= width (M:675/954). The stored field is only compared with the budget (no reader re-derives it; mesh_tables only stores it) | width = 32*R^3 |

Note on D:545-551 (refuter note 5): _pose_binding takes `|point - stored|_1 + tail`.
- tail is a Euclidean radius. Since |x|_2 <= |x|_1, this is a valid bound in the 2-norm reading.
- The rounding term this design adds is Euclidean, like tail.
- A 1-norm reading would need sqrt(3)*tail. That is a property of the existing code, not one introduced here.
- For Geometry: state the 2-norm reading in the docstring, or use sqrt(3)*tail.

## 2. Insertion points and error propagation

Shared helpers (exact; note 6):
- floor_log2 and ceil_log2 work on Fractions.
- Use `Q(2)**k`, because `2**negative` is a float.
- round_up(x, q) = -((-x)//q)*q.
- round(Fraction) is an int, and int*Fraction is a Fraction (0 gives Fraction(0)).
- Outputs stay tuples of Fractions, so the exact_scale (W:79) and D:1876 fast paths still fire.

### (b-ray): in W._pose_vector's step loop (W:113-116)

```
target = max|v_in| / Q(2**(32+2*level))           # the step's own Taylor target (W:75)
v, delta = _rotated_normal(v, w, a, b, level, arena);  error += delta
if delta:                                          # delta == 0: an exact step; nothing is rounded
    q = Q(2)**(floor_log2(min(delta, target)) - G_R)
    v = tuple(round(c/q)*q for c in v);  error = round_up(error + q, q)
```

- **Round to nearest (q dyadic).** Each component moves by at most q/2, so the 2-norm moves by at most
  (sqrt(3)/2)q <= q.
- **round_up(e+q, q) adds [q, 2q).** The radius therefore still encloses the true pose: true rotations are
  orthogonal, so radii add, as the existing code already relies on. It also keeps the radius on a short dyadic grid.
- **The quantum follows the actual error (SHOULD-FIX 2).** q <= 2^-G_R * min(delta, t_L):
  - a slow plate's very exact step is rounded finer;
  - a swept current step (delta includes half*|w x v|) is never rounded coarser than the policy target.
- **delta == 0 is an exact step (note 7):** either w x v = 0, or a zero-time step (t0 = t1 = 0, where x = 0 and
  the tail is 0).
  - The value is returned unchanged and left unrounded.
  - So end(n) through (w, d, d) equals start(n+1) through prior n plus (w', 0, 0).
  - MEASURED: true on all 16 rows at L0 and L24, and for the t0 = t1 = 0 test.
- **inverse=True, every level, every caller** (D _ray_box, _constraint_pose, _fan/_source_planes,
  _boundary_leaf, W _pose_planes) get the rule through this single function. Their cache keys are
  unchanged, because the function stays deterministic.

### (b-quat): in E._representative_pose (E:391-409)

```
rates = decoded angular velocities;  axis = first nonzero rate if EVERY nonzero rate is exactly parallel
        to it (all O._cross(w, axis) == 0), else None                 # once per call
for each segment:
    q_seg, delta = _segment_quaternion(...);  Q = _qmul(q_seg, Q);  e_exact = (1+delta)*e + delta
    if delta:            # delta == 0 only when h == 0: q_seg = (1,0,0,0) and the product is exact
        q = Q(2)**(floor_log2(delta) - G_Q)
        if axis is None:  Q = round each of the 4 components to q
        else:             j = argmax |axis_j|;  s = Q[1+j]/axis[j]   (Q[1:] == s*axis exactly; checked, else raise)
                          q_s = Q(2)**(floor_log2(q) - ceil_log2(|axis|_1))
                          Q = (round(Q[0]/q)*q, *(round(s/q_s)*q_s*k for k in axis))
        e = round_up(e_exact + q, q)
    else: e = e_exact
(unchanged) if e >= 1 or 4*e > operator_goal: raise;  return Q, 4*e
```

- **Why the axis branch (the BLOCKER).**
  - D:770-773 issues the posed-boundary rotation from this quaternion through CartesianCell.rotated, which
    is Q(q)/|q|^2 and exactly orthogonal.
  - DP:250 _KernelPose._axis and SP:46-60 _pose_axis then call SP:34-43 _common_axis.
  - _common_axis requires `row.k == k_i` and `column.k == k_i` EXACTLY.
  - That certificate drives invariant_wall and the axis paths (SP:208-209, 333-335, 381-414, 392, 567).
  - Without it, the pose takes the inexact-pose route, which is the known interval-two pressure block.
- **Why rounding w and s keeps it.**
  - Coaxial products stay exactly on the axis, because k x k = 0:
    (c1, s1 k)(c2, s2 k) = (c1 c2 - s1 s2 |k|^2, (c1 s2 + c2 s1) k).
  - For q = (w, s k), Q(q)/|q|^2 maps k to ((w^2 - s^2|k|^2) + 2 s^2|k|^2) k / (w^2 + s^2|k|^2) = k. The
    transpose does the same.
  - MEASURED: the axis is kept on all 12 coaxial rows (3 rates, n = 1 to 1,000), as on the unrounded route
    (n <= 6). The r1 componentwise rule on the same histories loses it on all 12 (the mutant).
- **Non-parallel histories lose nothing.** _common_axis returns None from the history alone (SP:37-38),
  before it reads the rotation.
- **Rounding.**
  - Coaxial: |dw| <= q/2 and |ds k|_2 <= (q_s/2)|k|_1 <= q/2, so the move is <= q/sqrt(2).
  - Componentwise: the move is <= (sqrt(4)/2)q = q.
- **Bound on the product.** |s~Q~ - sQ| <= delta(1+e) + e, because |Q~| <= 1+e. The recurrence therefore
  holds with the move added.
- **Rejected alternative: one summed-phase segment for a coaxial history.**
  - It composes exactly, but the phase grows with the history (~0.1 rad per interval at the representative
    rate, ~100 rad by IV1000), so the Taylor order and its widths grow.
  - It would also change the segment list the record carries.

### (c): in M after the unchanged exact comparison (M:675, M:954; record fields at M:733, M:1016)

```
stored = 0 if total_error == 0 else min(round_up(total_error, 2**(floor_log2(total_error) - 64)), width)
```

- **Outward.** Since total_error <= width at this point, `stored >= total_error`.
- **Relative excess** is below 2^-64 (5.4e-20).
- **No pass/fail change at all.** The decision is still taken on the exact sum, and stored <= width, so a
  later "stored <= budget" check agrees with the build. (The refuter's note 9: HOLDS.)
- **E, the exterior mesh**, has the same field (E:701/739, 909/954). The same rule is optional there, for
  Geometry to decide.

## 3. Precision, against the ACTUAL certified error (bar: <= 1%, cumulative over 1,000 intervals)

| path | proof | 1% needs | chosen | bound | measured (probe r3, n <= 1,000, four histories) |
|---|---|---|---|---|---|
| ray | each step adds a_i in [q_i, 2q_i), with q_i <= 2^-G_R*delta_i, so the radius is < (1+2^(1-G_R))*sum(delta_i): the existing radius of the same steps (taken on the rounded vectors, which moved <= 2^-(44+2L) relative; second order). Independent of rate, level and n | G_R >= 8 | **G_R = 12** | **< 0.049% of the actual radius**, and each move <= 2^-12 * t_L | end pose 0.010-0.033% at L0 and L24, including 5.5e-17 and 1e-19 rad/s (the r1 rule gave 1.39% and 839%); swept step <= 0.0004% |
| quaternion | by induction e_new <= (1+2^(1-G_Q))*e_old, where e_old is the existing recurrence on the same delta_i. Each delta_i <= goal, so the r1 bound against operator_goal also still holds | G_Q >= 8 | **G_Q = 12** | **< 0.049% of the actual certified error** (r1: ~2x at n=1; note 4's 0.104% is superseded) | 0.024-0.028% of the actual error; <= 0.0067% of operator_goal |
| deviation sum | relative 2^-64 | any | **P = 64** | 5.4e-20 | (not probed; arithmetic) |

Widths (MEASURED, flat in n):
- ray: L0 44-52 bits; L24 94-109 bits. The slow plates take more bits because their steps are more exact.
- swept step: 45-46 bits (L0) and 94 bits (L24).
- quaternion:
  - non-coaxial: 94 bits;
  - coaxial: 139-165 bits (s*k with a binary64 k);
  - error: 82-107 bits.
- The unrounded route grows by 1,022 bits per segment (quaternion at the production goal) and 1,345 bits
  per step (ray L24).

Tightness: the smallest bound/actual slack is 1.00025 (quaternion, 1e-19 rad/s, n = 1,000). The existing
coaxial bound is nearly exact there (its Taylor errors add coherently), and the added rounding term supplies
the margin. Rays: >= 7.6 at the end pose and 1.36 for the swept step.

Pass/fail effect:
- **Quaternion check: cannot flip.** The existing 4e <= (operator_goal/2)·e^(operator_goal/8). The new
  value is at most (1+2^-11) times that, which is still below operator_goal.
- **P (current_force_pose / rotated_background, refuter item 3).**
  - force_error and matrix_error are linear in pose._error (P:197-198), so their pose terms rise by < 0.049%.
  - The torque and power checks (P:200) flip only if the margin lies inside that, and only toward refusal.
  - P has no caller in full6 today.
- **D:772 posed boundary:** the same E check applies, and the axis certificate is kept (above).
- **Ray tests: flip only in a sliver.** A ray test changes outcome only if its margin lies within
  < 0.049% of the actual radius:
  - **Band (D:550) and sign/separation tests:** such a flip refuses, it never gives a wrong pass.
  - **Leaf width tests:** an extra refinement level costs time only. A refusal happens only at the
    max_leaves edge.
- **Exact-zero tests on posed vectors** flip only toward refusal. D's input-based coaxial proofs read the
  inputs, not the posed vectors, so they are unaffected.
- **(c): nothing flips.**

## 4. Projected widths (% of 8,388,608 bits). Without = the note's linear law; with = flat after one step (PROJECTED)

| field | IV1 measured | without: IV2 / IV3 / IV4 / IV5 | with (b)+(c): IV1 to IV5 |
|---|---:|---|---|
| heat exact_cell_storage_residual_j | 24.5% | 43-49 / 62-73 / 80-98 / **refuses** | ~5-7%, flat (heat ~ 53x metric width) |
| mesh per-element metric | 0.46% (38,455) | 0.8 / 1.2 / 1.5 / 1.9% | ~0.11-0.13% (~9-11k bits; root 8,128 at 53-bit rays, interpolated at 94-109-bit rays), flat |
| mesh deviation sum | 7.3% (614,116) | 14 / 21 / 28 / 35% | <= ~70 bits, flat |
| posed ray L24 / quaternion | 1,345 / 1,022 bits per step or segment (MEASURED, synthetic) | linear growth | 94-109 / 94-165 bits, flat (MEASURED, synthetic) |

## 5. Identity impact

- **Every exact value downstream of a moving pose changes from IV1 on.** That covers the posed supports,
  mesh metric, ledgers, ids, and E/P poses, so this is an **identity successor**.
- **The three modules' source hashes change.** That alone refuses mixing with old stores, because the
  loaded-implementation and source checks stay untouched. No new record field is needed.
- **Binary64 outputs (note 10).** Rounding moves a posed vector by <= 2^-(44+2L)·|v| per step:
  - Above binary64's 2^-53 at L <= 4: binary64 values projected from coarse-level poses can change by up to
    ~2^(9-2L) ulp (512 ulp at L0).
  - From L5 up, a change needs a rounding-boundary crossing (rare).
  - Every such change is < 2^-11 of that level's own certified radius.
  - So binary64 outputs fed by coarse-level poses should be expected to differ in their low bits.
- **One ticket after RESUME** (after q02 and the P1 proof): an IV1 replay on the successor against the
  current route. It reports the max change of every physical output field next to that field's
  certified bound, plus the new widths.
- **Heat ~5-7% stays PROJECTED** until that replay.

## 6. Interactions

- **Geometry D1/D2** (moving_interface/moving_face moments; byte-identical parity on the deep set and the
  IV1/IV2 surfaces):
  - moving_interface_moments calls D._ray_box (l.607/860/892), so its inputs change under (b).
  - The D1/D2 parity must therefore compare arms on the SAME base. Run it first on the current route,
    then compose the width successor after D1/D2 and G-PY.
  - D._rotation_boxes (moving_face l.211) composes its own history and is untouched.
- **G-PY** (Exact kernels q11 c5f2a123, composed after D2):
  - If it edits integration_wall_measures, the (b) transform anchors on G-PY's output sha.
  - The types stay Fractions in tuples (section 2).
  - The jets and kernels then run on ~100-bit operands, not kbit ones: faster, and exact either way.
  - Exact kernels' D5 T1, a native `_rotated_normal` twin (T/ck/d5/DESIGN.md section 4):
    - My edit is in `_pose_vector`, which is text disjoint from T1. The two stack in either order.
    - T1 returns new Fractions, which the rounding then consumes.
    - With (b), T1's operands become dyadics of ~44+2L to ~60+2L bits, so T1's gain shrinks. Measure it both ways.
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
  linearly. They are a later profiling item. The refuter found no missed (b-ray) callers (note 11).

## 7. Build plan (after review)

- **New-file source transforms in T/ps/width**, input-sha pinned and refusing on mismatch:
  - width_pose_round.py, covering (b-ray) and (b-quat);
  - width_deviation_bound.py, covering (c).
- **Unit tests:**
  - probe r3's cases through the transformed modules: widths, shares, the delta rule at t0 = t1 = 0, and
    end(n) == start(n+1);
  - check_round_mpmath_r3 on their output;
  - type checks: a Fraction in every component, tuple outputs;
  - the axis certificate through D.posed_boundary -> _KernelPose._axis and P._pose_axis, non-None for a
    coaxial boundary history at IV1 and at n = 1,000.
- **Fail-closed mutants**, each of which the mpmath check or the tests must catch:
  - no radius added;
  - round_up replaced by round-nearest;
  - a quantum 2^4x too coarse;
  - a quantum taken from t_L alone (the slow-plate rows exceed 1%);
  - rounding on delta == 0, which breaks end(n) = start(n+1) and the t0 = t1 = 0 test;
  - componentwise rounding on a coaxial history (axis lost; 12/12 in probe r3);
  - (c) storing round-down.
- **Sequence:** one refuter on the code, then Geometry's review and integration, then the replay ticket.

Later-step impact (PROJECTED):
- The width gate passes IV3 onward.
- Exact pose arithmetic gets cheaper: n narrow steps per call instead of widths growing ~1.0-1.3 kbit per
  interval.
- Downstream clip/volume/heat arithmetic runs on ~9-11 kbit metric numbers instead of 38 kbit + 30 kbit per
  interval.
- The coaxial axis certificate is preserved, so continued intervals keep the exact-axis pressure route.
- A later exact prefix cache (pose_k = f(pose_{k-1}, step_k, level) is deterministic) could make poses
  O(1) per interval.

Next-interval capacity (PROJECTED):
- Heat per-cell fields shrink from 2.05 Mbit (24.5%) to ~0.5 Mbit (~6%) and stay flat.
- The mesh deviation sum drops from 614 kbit to ~70 bits.
- Record bytes and the per-cell RAM of the widest heat fields fall about 4x at IV1, and more at later
  intervals.
