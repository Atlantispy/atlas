# Reconciling composed-r2 with remake: a file-by-file plan

Thread "Release, languages and landing plan" (T/rm), 16 Oct 2026, 17:19-17:45. This is a plan only and was produced read-only. Nothing was
edited in the repo or in R, nothing was run through the queue, and nothing was committed.

Sides:
- **S** is `R/composed-r2/src/atlas_tectonics`: 236 files, all LF.
- **remake** is `atlas/tectonics/src/atlas_tectonics` at 1a58e0b (pushed): 157 files.

The scripts and their JSON outputs are in `T/rm/reconcile/` (see §9). Every fact below was produced by those scripts (MEASURED) unless it
is labelled otherwise.

## 0. Answer in brief

1. **There are no real merge conflicts.** For all 21 modules that differ, S's file already contains every remake hunk, so **S's
   file is the base for every module**. For 16 of the 21, remake did not change the module since the shared ancestor. For the other 5,
   both sides changed it, and a three-way merge (base X, remake, S) that resolves toward S gives S byte for byte.
   - Those 5 are integration_driving, integration_feedback, integration_strength, integration_transfer and regional_execution3d.
   - `integration_driving.py` shows 4 textual conflicts, but they are adjacent insertions only. S also holds remake's
     `partition_motion_evaluation` change.
2. **Shared ancestor.** X = remake 30a79e6 (I03) plus the combined I04/I05 patch (`4ec2f359…`), rebuilt in scratch. remake equals X on
   141 of 157 files. S descends from X through four trees:
   - F0, Codex's fidelity source, which already carries most of the 5 Oct speed-ups;
   - H, the heat repair of 7 Oct;
   - RC1, composed-r1;
   - S, composed-r2.
3. **Landing is a copy plus additions, not a merge.** It replaces 21 modules and adds 79 that exist only in S. Of the 21, 9 are
   I04/I05 modules that are absent from I03.
4. **The real blocker is private helpers.** 22 of the S package modules import 30 modules from `composed-r2/helpers`. The import
   closure is **119 helpers and 47,886 lines**: about 75 `private_heat_*` modules, plus transfer, patch, store and table modules.
   - They bind identity by **absolute path**. `_SOURCES[str(Path(__file__).resolve())]` appears in many of them.
   - 5 of them hold literal `C:\Users\LOCAL_USER\...` paths.
   - Several pin the bytes of their sibling modules (`CORE_SHA256`, `ASSEMBLER_SHA`).
   - So units U3-U6 (§5) cannot land until the helpers are folded into the package. This is decision **R1**.
5. **A helper-free tranche exists.** U1 and U2 together are 35 modules (17 modified, 18 new). They import no helper and nothing from
   a later unit, so they can land first.
6. **Two current receipts are invalidated.**
   - `i02-workflow-timing-r12` binds all 157 package files, so all 21 modified modules hit it.
   - `i01-finite-admission-r12` binds constitutive, integration_ledger, resources and reuse.
   - None of the other 35 current records binds a changed file.
   - Both successors are small captures (the controls take under a second).
7. **New restore-time module.** S's `reuse.py` imports `exact_arithmetic` (reuse.py:587, a lazy import in `_runtime_record`). Restore
   is therefore expected to execute it. Add `src/atlas_tectonics/exact_arithmetic.py` to `RESTORATION`; this is the same failure
   mode as the reuse.py fix in 836a815. Confirm with `test_i02_persistence`.
8. **Not all of it is byte-identical.** The S line changed the expectations of some I03/I05 tests:
   - `test_i03_transfer`: refusal text "stored map row".
   - `test_i05_heat`: the omission fixture was re-authored.

   So U2 includes method changes from Codex's fidelity repairs. Persisted I03-I05 results made under remake are not guaranteed to
   reproduce.

## 1. Lineage

```
I03 30a79e6 --(combined I04/I05 patch 4ec2f359)--> X --(af5cfb5: 16 modules)--> remake 1a58e0b
                                                    \--> F0 (fidelity source) --> H (heat-repair 7 Oct) --> RC1 (composed-r1) --> S (composed-r2)
```

Pairwise counts (same / differ / only-left / only-right):
- X vs remake: 141 / 16 / 0 / 0
- F0 vs remake: 139 / 18 / 51 / 0
- H vs F0: 182 / 26 / 20 / 0
- RC1 vs H: 203 / 25 / 8 / 0
- S vs RC1: 218 / 18 / 0 / 0
- **S vs remake: 136 / 21 / 79 / 0**

remake has no module that S lacks.

## 2. The 21 modified modules

Key:
- **Kind:** *S-forward* means remake equals X, or remake's version lies on the S lineage. *Both* means both sides changed the module
  and S contains remake's hunks.
- **Lines:** S versus the base.
- **Unit:** see §5.

| Module | Kind | remake change since X | S change since base (where it entered) | Lines | Unit |
|---|---|---|---|---|---|
| constitutive | S-forward | none | `_cancel` (F0) | +1/-1 | U1 |
| regional_execution | S-forward | none | `_RetainedSnapshotBytes`, snapshot `__init__` (RC1 stage `native_transfer.retained_snapshot_source`) | +16/-1 | U1 |
| resources | S-forward | none | WorkBudget predicate-work primitives: `PredicateWorkLimitError`, `reserve_predicate_work`, `try_reserve`, `_BudgetLocks`, 27 added (H); +14 lines (RC1) | +387/-33 | U1 |
| reuse | S-forward | (remake == F0) | `exact_arithmetic.runtime()` joins the runtime record (H); `_SourceHandles` and `_capture_sources` (S stage `geometry:source_handles`; verify 45.3 -> 12.6 ms per G/HANDOFF §8) | +176/-4 | U1 |
| integration_bridges | S-forward | none | `RegionalResult` record/result_id, `_footprint_support`, `_regional_support` (F0) | +107/-14 | U2 |
| integration_driving (I04) | Both | `partition_motion_evaluation` diagnostic: belt-tangent local linearisation, omitted at rest | remake's change plus `radial_pressure` record, Forcing/Prepared/datum changes, `_power` (F0) | +176/-18 | U2 |
| integration_events | S-forward | none | `_rebuilt`, `_reexpression_bound` (F0) | +9/-4 | U2 |
| integration_family (I04) | S-forward | none | `_radial_column`, `family_moving`, `starting_physical_family` (F0) | +136/-15 | U2 |
| integration_ledger | S-forward | none | `inspect_material_snapshot`, moving restore (F0) | +36/-5 | U2 |
| integration_material (I05) | S-forward | none | patch columns, `patch_heat_exact`, moving declare/advance/restore; `_apply_rows` and `_rounded` removed (F0) | +549/-124 | U2 |
| integration_ports (I05) | S-forward | none | `material_trace_support` (F0) | +61/-0 | U2 |
| integration_properties (I05) | S-forward | none | `PatchStrengthColumn`, `_strength_rows` (F0) | +141/-34 | U2 |
| integration_sphere | S-forward | none | material build/restore, joined material (F0) | +46/-10 | U2 |
| integration_splits (I04) | S-forward | none | `applied` (F0) | +6/-1 | U2 |
| integration_strength (I05) | Both | `BeltTerm._coverage` | remake's change plus `_content`, `column_layers` (F0) | +17/-3 | U2 |
| integration_thermal (I05) | S-forward | none | patch contacts/heat, mechanical sources, `_radial_thermal`, `_volume_contract` (F0) | +561/-35 | U2 |
| integration_transfer | Both | `_advanced_junction`, `_moved`, `_transform_material_seams` | remake's change plus density/amount accuracy bounds, `_integer_triangles` (F0) | +405/-31 | U2 |
| regional_evolution3d | S-forward | none | source-stage endpoint, radial mechanics, donor stage (F0, H, RC1) | +485/-89 | U3 |
| regional_execution3d | Both | 1 line in `PreparedRegionalStokes3D.__init__` | remake's change plus hydrostatic request, pressure reference, traction binding (F0) | +321/-27 | U3 |
| regional_transport3d | S-forward | none | `_euler_inventory`, `_limited_slope`, `_specific_inventory` (F0) | +141/-36 | U3 |
| integration_feedback (I04) | Both | `_coupled_digest`, `_issued_coupled`, CoupledInterval/commit (the Codex P1 fix) | remake's change plus `RegionalFeedbackInterval`, `regional_interval` (F0) | +72/-9 | U4 |

How the inclusion was proved: `three.json` records, for each module, `merge_equals_S` (the clean merge equals S) or `S contains every
HEAD hunk` (resolving toward S equals S). For integration_driving the result is 4 conflicts with S ⊇ remake (rechecked in §9).

## 3. The 79 modules only S has

They are grouped by the tree they entered in. `[changed@…]` marks a later edit.

- **F0 (51):**
  - integration_basal_inventory [H], belt_resolved, circular_moments, collar_geometry, current_force_pose;
  - differential_ale [H, RC1], differential_coupling [RC1], differential_geometry [H, RC1, S], differential_mesh [H, S],
    differential_pressure [H, RC1], differential_trace [H, RC1];
  - exterior_heat, exterior_mesh [H, RC1, S], exterior_state, interface_exclusion [H];
  - masked_native, masked_partition, mechanical_heat, mimetic_heat [H, RC1, S], mimetic_precision [H];
  - moving_face_moments [H, S], moving_interface_moments [H], native_faces, native_projection;
  - patch_contacts, patch_heat, poly_tiles, pressure_coupling [H], q2_directed [H, S];
  - radial_pressure, radial_strength, regional_driving, regional_evolution [H], regional_exchange, regional_inventory [H],
    regional_workflow [H, RC1, S];
  - rigid_intersection, spatial_ale [S], spatial_owner [H, RC1, S], spatial_pressure [H, RC1], spatial_reservoir [H, S],
    spatial_transport [H, S];
  - support, volume [RC1], volume_bounds [H, RC1], volume_overlap, wall_measures [RC1];
  - regional_collar3d [H, RC1, S], regional_conservative3d, regional_i01_creep, regional_radial_hydrostatic.
- **H (20):**
  - _mimetic_enclosure, _mimetic_newton_factor, exact_arithmetic;
  - integration_cone_zero, dual_geometry [S], dual_measures [S], exact_gmp [RC1], extremum_heat [RC1];
  - mimetic_limiter, mimetic_newton;
  - parallel_binding [RC1], parallel_dispatch [RC1], parallel_owner, parallel_profile, parallel_results [RC1, S],
    parallel_rolling [RC1], parallel_selection [RC1], parallel_worker;
  - routing_views [RC1], sphere_quadrature.
- **RC1 (8):**
  - integration_component_volume_auto, component_volume_batch, component_volume_parallel;
  - cone_intervals, endpoint_checkpoints [S], filtered_predicates, private_heat_cold [S];
  - regional_caloric.

Text scan of all 100 changed or new modules: no private path or user string. The only hits are two citation URLs, in
`_mimetic_enclosure.py:15` and `integration_mimetic_limiter.py:7`. Names to review at landing: `integration_private_heat_cold`
(U6) is "private" by name. The `parallel_*` modules call `require_strict_execution()`, so the composition refuses release mode
(RELEASE-CHECKS.md §1).

## 4. Helper dependency (the blocker)

Package modules that import helpers:
- component_volume_auto, differential_ale/coupling/geometry/mesh/pressure/trace;
- dual_geometry, dual_measures, exterior_mesh, mimetic_heat;
- parallel_dispatch, parallel_selection, private_heat_cold, regional_workflow, routing_views;
- spatial_ale/owner/reservoir/transport, regional_collar3d.

The direct targets are 30 helpers:
- `partition_*_patch`, `live_*_patch`, `spatial_*_patch`, `exterior_mesh_patch`, `pressure_indexed_patch`, `heat_cold_patch`,
  `publish_mesh_patch`, `exchange_record_patch`, `compact_restart_patch`;
- `continuation/geometry/funding/spatial/workflow_transfer`;
- `compact_contracts`, `interval_store_set`, `segment_store`, `mesh_tables`, `live_transport_result`;
- `private_heat_joined_consumer_r6`, `private_heat_restored_binding_r10`.

The closure of those 30 (`closure.json`) is 119 modules and 47,886 lines.

Why the helpers cannot simply be copied:
- **(a) Path-keyed identity.** Helpers register `_SOURCES[str(Path(__file__).resolve())]`, and heat result IDs bind those absolute
  paths. That is composed-r2's root rule: "launchers refuse to run from any other root". Moving the helpers changes every heat result
  ID, even when the numbers are D-b identical.
- **(b) Sibling byte pins.** Examples are private_heat_certification_kernel_r3:164, decimal_inventory_r1:86 and
  endpoint_inventory_r3:78. Any edit to a pinned sibling, including a renamed import, cascades through the chain of pins.
- **(c) Literal user paths** in decimal_inventory_r1:38, geometry_inventory_r1:35, interval_inventory_r4:32,
  low_solver_kernel_r2:37 and low_solver_kernel_r5:58. `historical_admission.py:37` holds `HISTORICAL_RELATIVE` (a relative
  fidelity path).
- **(d) Compose-time code.** Many `*_patch` helpers carry the string-replacement transforms that produced the outputs, as well as
  runtime functions. Only the runtime part belongs in a landed package.

## 5. Merge order

The order follows the import layers (`layers.py`). Every import cycle lands inside one unit. No unit imports a later unit; this was
checked by script (`units.json`).

| Unit | Contents | Lines | Helpers needed | Notes |
|---|---|---|---|---|
| U0 | Preconditions: decision R1; add `exact_arithmetic.py` to `RESTORATION` in `tectonics/tools/check_i01_finite_admission.py`; bring the S-line tests (§6) | – | – | No package change |
| U1 | 4 modified (constitutive, regional_execution, resources, reuse) and 12 new numeric/infrastructure leaves (exact_arithmetic, _mimetic_*, filtered_predicates, cone_intervals, mimetic_newton, sphere_quadrature, volume, parallel_owner/rolling, regional_caloric/conservative3d) | 6,332 | 0 | Invalidates both current receipts |
| U2 | Cycle 1: the I03/I04/I05 core. 13 modified and 6 new (patch_contacts, patch_heat, radial_pressure, support, volume_overlap, mimetic_limiter) | 20,889 | 0 | Method changes (§0 item 8); I03/I05 tests change |
| U3 | Cycle 2: regional 3-D and spatial. 3 modified and 22 new | 16,614 | 9 | Needs R1 |
| U4 | integration_feedback and 8 new (q2_directed, dual_measures, mechanical_heat …) | 3,415 | 1 | Needs R1 |
| U5 | Cycle 3: differential, parallel, component-volume, moving-face. 29 new | 24,836 | 15 | Needs R1 |
| U6 | integration_regional_workflow, integration_private_heat_cold | 2,134 | 14 | Needs R1; rename private_heat_cold |

With per-unit checks, U1 and U2 can land before R1 is settled:
- the import check;
- `test_i02_persistence`;
- `check_i01_finite_admission`;
- the S-line tests for the unit.

U3-U6 then land after the helpers are folded in.

## 6. Outside the package

These are counted against H's source tree (`heat-repair-20261007/source`), which is where S's tests live.

- **tectonics/tools:** 3 files differ and H has 4 more.
  - `check_i01_finite_admission.py` merges cleanly. H's only change is the r6/r4 upstream pins, which remake already has.
    **Keep remake's file** and add exact_arithmetic (U0).
  - The other two differing files are magemin_g25.jl and magemin_g25.py.
- **tectonics/cases:** `i01_closure_matrix_v1.json` was changed only by remake (the r12 pin), so keep remake's.
  `i03_controls_v3.json` was changed only by H, so take H's. It is an I03 controls case; its receipt status needs checking at U2.
- **tectonics/tests:** 15 differ and H has 254 more. All 15 are either H-forward or H ⊇ remake (test_i04_feedback); none
  conflicts. Two of them change expected behaviour (§0 item 8). The composition-level tests (`R/resumability-r1/test_*.py`, about
  60) cover the RC1/S stages and need sorting into production and harness.
- **tectonics/docs:** 11 differ and H has 4 more, including I03_SPHERICAL_NETWORK, I04_CAUSAL_START, I04_I05_PORTS,
  I05_MOVING_STATE and INTEGRATION_PLAN. Update them in AGENTS.md dependency order, with each unit.
- **Environment:** gmpy2 is installed in `.r44-env` but appears in neither remake's nor H's pinned requirements, so
  `exact_arithmetic` stays on its Python route in a clean install. To enable it, the requirements change and the current
  `environment-install` receipt needs a successor (decision R4).

## 7. What each merge invalidates

**Current receipts.** These are the only two. Each needs a successor captured in dependency order; old receipts are never edited.

| Receipt | Bound files changed | Hit by | Successor and order |
|---|---|---|---|
| `i01-finite-admission-r12` | constitutive, integration_ledger, resources, reuse; also the tool, if RESTORATION grows | U0, U1, U2 | **r13 first**. Re-pin `cases/i01_closure_matrix_v1.json` and update docs/CURRENT_EVIDENCE.md (the only two places naming r12). Its upstream receipts (finite-strain r6, column-admission r4 and the others) bind no changed file, so they stay. |
| `i02-workflow-timing-r12` | all 21; the successor also inventories the 79 new modules (whole-package binding) | U1-U6 | **r13 after finite-admission r13.** Five strict repetitions; samples are about 0.07 s each. Or reclassify it as historical if no new timing claim is wanted (decision R3). |

Unaffected:
- `optimisation-20261005` is already historical.
- The 57 superseded and 29 historical records are not checked.
- No other current record binds a changed file.

**Execution identity.** The runtime record and source digest change with every unit:
- U1 adds `exact_arithmetic` and changes `_SourceHandles`.
- Reuse-cache and measurement-cache entries, and the item-7 pins, regenerate. They are not reused across the change, by design.

**composed-r2's private evidence.** This covers the interval stores, checkpoints, Step 8 runs and `runq` ticket results bound to
composed-r2. All of it binds the absolute helper paths and composed-r2's root. After R1 it does not transfer to the landed package
without an authenticated migration, and composed-r2's manifest says no migration is granted. The landed package therefore starts
from fresh runs, or migration is a separate decision (R2). composed-r2 itself stays intact as the reference.

**Tests.** `test_i02_persistence` (restore inventory) and the S-line I03/I05 expectation changes land together with U2, not
separately.

## 8. Decisions (batched, with recommendations)

- **R1. Helper fold-in.** Recommended: the helper closure moves into the package as a private subpackage, U3 to U6, one unit at a
  time.
  - Runtime parts only; the compose-time transforms are dropped.
  - Path-keyed `_SOURCES` becomes package-relative.
  - User paths are removed.
  - Sibling pins are re-derived bottom-up in one pass.
  - Success test: the D-b check is the numbers and fields of a composed-r2 replay; only the result IDs change.
  - The alternative, landing helpers byte-for-byte at the same relative layout, still breaks (a) and (c) and gives no gain.
- **R2. composed-r2 run evidence.** Recommended: no migration. The first landed interval run is a fresh baseline, and the
  composed-r2 results stay as private reference.
- **R3. I02 timing.** Recommended: capture successor r13 rather than reclassify. It is cheap, and it keeps a current timing claim
  across the whole package.
- **R4. gmpy2.** Recommended: keep it out of the pinned requirements for U1 (Python route, D-b). Decide together with LANGUAGES.md
  L2/L3 (gmpy2 C API).
- **R5. Commit shape.** Recommended: one commit per unit on a landing branch. Capture both successors once, after the last unit that
  lands, and push to remake only when check_before_commit passes at that point. Intermediate commits fail the register by design.

Later-step impact:
- U1 and U2 do not change Step 8-19 runs, which use composed-r2.
- U3-U6 retarget future runs at the landed package once R1 is done.

Next-interval capacity: the landing changes no guards or limits.

## 9. Reproduction

The scripts are in `T/rm/reconcile/`. Run them with `.r44-env/Scripts/python.exe -I`.

1. **Rebuild X in scratch.** `git archive 30a79e6 README.md tectonics | tar -x`, then `git apply` the combined patch
   (`.atlas-dev/claude-i04b-strength-feedback-20261004-combined.patch`, sha `4ec2f359…`). Never apply it in REAL.
2. **Run the analysis scripts:**
   - `trees.py`: per-file sha256 (LF-normalised) for S, RC1, H, F0 and remake c856236/30a79e6/1a58e0b, written to `trees.json`;
   - `three.py`: lineage kind, numstat, changed top-level functions and trial merges, written to `three.json`;
   - `scan.py`: private paths and non-package imports;
   - `closure.py`: helper closure, written to `closure.json`;
   - `layers.py`: import layers and cycles, written to `layers.json` and then `units.json`.
3. **Recheck the five both-changed modules with CR stripped:** `git merge-file -p --theirs remake X S` equals S for all five
   (rechecked 17:35).
   - `--theirs` alone could hide a dropped remake hunk, so integration_driving was also checked line by line.
   - Of the 33 lines remake added since X, 32 appear verbatim in S.
   - The 33rd is `partition_motion_evaluation=partition_evaluation)`. In S it ends in a comma rather than `)` because S passes a
     further argument after it.
   - The remake-side names (`PARTITION_LOCAL`, `with_tangent=True`, `_coupled_digest`, `_issued_coupled`, `_coverage`,
     `_advanced_junction`, `_transform_material_seams`) are all present in S.
