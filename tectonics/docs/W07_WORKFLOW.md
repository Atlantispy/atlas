# W07 Step 5 — geological assembly and recoverable execution

23 September 2026. WORKING NON-CANON. Step 5 complete for the routes below;
assembled acceptance and matched recovery measurement PASS. The [Step 1 design](W07_REGIONAL_MECHANICS.md) and
[case register](../cases/w07_mechanics.json) are unchanged.

Subsequent 23 September dependency repair: surface projection and variable
flexure now load SciPy lazily. The [review-fix record](../../docs/REMAKE_REVIEW_FIXES.md#23-september-review-of-5ae74dc--reported-failures-resolved-locally)
supplies current focused evidence. The combined report, source-byte comparisons,
inventory and timings below describe the preceding Step 5 completion snapshot;
they have not been rebound to the later dependency-only source changes.

## Implemented connection

`bind_regional_geology` consumes the actual typed W01/W02 initial workflow, not
arrays with a geological-looking label. It preserves geological case, initial
sampling, original thermal profile, material cohorts, forcing, frame, epoch,
datum and source identities. Raw construction of the geological binding refuses.
Inward-positive source depth becomes upward-positive mechanical z explicitly.

Pure ordered horizontal layers supply point viscosity at cell centres and exact
vertical-series compliance over shear dual intervals. This is a stated series
law, not a universal harmonic mixture prescription. Exact layer intersections
preserve cohort volumes and reference masses separately from thermal buoyancy
density. Both original thermal point values and cell means remain available.
Unit/cohort identities remain separate even where their physical values agree.
The reference-constant law freezes source density, not a general equation of
state; the optional linear Boussinesq law uses source rho0, alpha and T0 for
buoyancy only. Source frame/vector/depth conventions remain in the binding.

`RegionalPhysicsOwnership` and `W07BoundaryMotion` name the owner of gravity,
thermal inputs, imposed motion and surface response. Full physical gravity is
supplied once; only the mechanical solver performs reference-pressure splitting.
Thermal buoyancy replaces the earlier gravitational field, rather than being
added to it. W04 displacement, water loads, extra heating and extra displacement
cannot be attached as duplicate contributions. Replacement boundary scenarios
require zero original S6 motion and their own matching source; uniform retained
S6 translation is a separate route. Out-of-plane motion is not silently dropped.

`PreparedW07Workflow` assembles three compatible routes:

- **Steady mechanics:** original layered geometry and inventories, source-bound
  gravity and explicit closed, translated or simple-shear boundary conditions.
  The homogeneous dry C01 law can additionally use the declared physical pressure.
- **Thermal evolution:** one homogeneous cohort on fixed, closed rectangular
  support; original heat capacity, conductivity and radiogenic production;
  source-labelled boundary data; SSPRK2 heat with first-order frozen-velocity
  coupling and a fresh mechanical endpoint. Viscosity is the explicitly selected
  constant geological law, valid only over its declared temperature interval.
  Optional linear Boussinesq buoyancy does not alter reference material mass.
- **Moving surface:** one homogeneous, isothermal, zero-heat-production material,
  actual Q2 geometry, mapped mechanics and conservative material inventory.
  A separately sourced zero-volume disturbance defines a new synthetic initial
  scenario, never a reconstruction of observed source topography.

Evolved W02 geometry without a compatible ordered-layer/thermal producer, evolved
W03 columns, W06 motion without a vector bridge, mixtures, lateral geology and
spherical sections refuse explicitly. Moving heterogeneous heat/material needs
the corresponding deformed-mesh transfer. These remain named integration
boundaries, not implicitly completed capabilities.

Closed thermal transport uses the discrete curl of a zero-boundary MAC
streamfunction to make the transferred face fluxes conservative. Its correction
must remain within the existing physically normalised mechanical divergence
allowance integrated across the domain. Larger corrections refuse. The original
mechanical field is unchanged; the heat receipt binds that field's identity,
transported velocity hashes and maximum correction. This resolves near-rest
round-off without clipping small physical velocities or relaxing solver gates.

## Recovery, storage and resource ownership

Schedules and cumulative partitions are immutable and source-bound. Requested
outputs are stored atomically in the existing `ArrayStore`. A compact catalogue
deduplicates identical arrays **before** payload copies, by exact dtype, shape
and bytes; no lossy compression or discarded physical fields are introduced.
Existing store compression policies, including zstd, remain selectable.

Recovery verifies the contiguous parent/source/schedule prefix, then decodes only
its newest physical state. It checks geometry, inventory, force, viscosity,
boundary and constitutive bindings, numerical gates and heat accounts without
rerunning completed mechanical solves. Closed heat accounts check source energy,
prescribed fluxes, stored energy and parent continuity. Corrupted or incompatible
records fail; the driver does not silently restart from scratch. Only the latest
output is retained in memory. Solver histories/Krylov vectors are not archived.
Thermal continuation reuses the accepted endpoint mechanics; surface continuation
seeds only its validated endpoint into the prepared solver. Initial-state, actual
force-array, dry-strength linear-origin and surface-history checks also apply on
restore, including when a corrupted record has internally consistent hashes.

One driving thread and one native thread, shared 128 MiB accounted admission,
256 cumulative accepted steps, cancellation and publication checks remain in
force. These are resource-accounting limits, not measured OS RSS. Redundant
docstrings were shortened and API detail retained in existing documentation,
rather than increasing the 2 MiB source-inventory limit. Final inventory is
2,096,516 bytes in 96 package files: 636 bytes of headroom. Executable ASTs of
`regional_checkpoint`, `regional_geology`, `surface_geometry`, `free_surface` and
`regional_strength` match HEAD after removing docstrings. Further source growth
must address the bounded representation explicitly; no physical fields were
removed. No numerical tolerance, grid or physical duration was changed to pass.

## Verification and measurements

### Snapshot codec contract

The codec preserves existing snapshot identities; it never repins sources or
evaluates mechanical, thermal or surface physics. The caller authenticates the
workflow, execution, policy, expected snapshot set, parents and physical state.
Hashes detect corruption, not an attacker replacing both records and hashes.
Returned data are detached and immutable. Codec reservations cover working and
output buffers until return; callers account for retained input/output data and
ArrayStore work separately. Resource figures are byte allowances, not RSS.
No history or process-global payload cache is retained. Array identity includes
shape, native float64 dtype and raw C-order bytes, preserving scalars, empty
arrays, signed zero and small fields. No fields are reconstructed from physics
or dropped. ArrayStore authenticates stored chunks; the codec checks schema,
bindings, hashes, finite values, bounded names/shapes/dtypes and exact coverage.
Mutable input arrays and metadata must remain unchanged until restore returns.
Internal consistency never substitutes for workflow/source/physical validation.

These expanded API notes were moved here from duplicate module docstrings during
Step 5 completion to preserve the existing 2 MiB source-inventory limit. No codec
validation, calculation, cap or output format changed.

### Combined evidence

The [current-source report](../evidence/w07-workflow.json) passes all **five**
assembled/reference/timing checks in **63.733 s**, on Windows 11, Python 3.12.14,
NumPy 2.4.6 and SciPy 1.17.1, with one native thread. Report SHA-256:
`11fd885f40da4765805a653f55d927bb344dc2964c204c38002669dcca45ceb3`.
Tests use declared synthetic controls passed through the real W01/W02 producer,
not Diadem terrain or calibration data. Eight codec, nine geological-binding and
all twelve workflow methods have passing evidence. Unchanged passing checks were
reused, not rerun. Nine shared execution-identity methods pass in 1.952 s; static
safety passes 13 maps/41 required paths, with 30 safety tests passing and one
Windows-specific skip.

The new heat reference solves the closed Neumann equation independently using
cosine-series **cell means**, starting from W01's linear temperature profile.
It includes radiogenic heating and Boussinesq endpoint mechanics, and verifies
unchanged reference mass and heat closure. At dimensionless diffusion time .02:

| Vertical cells / accepted steps | RMS temperature error / declared 100 K scale |
|---|---:|
| 16 / 16 | 0.0665189% |
| 32 / 64 | 0.0160034% |
| 64 / 256 | 0.00396383% |

Refinement ratios are **4.1566 and 4.0373**. This is a joined space/time refinement;
the separate spatial/time component checks remain in Step 3. No new claim of
fully implicit thermal-mechanical coupling is made.

Existing Step 4 evidence was checked against its actual source list: **93 of 98
recorded files are byte-identical**. `__init__.py` and `reuse.py` register the new
modules/exports; three Step 4 modules have only the docstring changes described
above. Their executable ASTs remain identical. The frozen design/case and reference
helpers are unchanged. The old report remains component evidence, not relabelled
with today's execution identity. The new workflow has its own source-bound report.

### Measured recovery

Three rotated-order repeats request the same final state of the 16 x 8 surface
case, with three scheduled outputs and 64 accepted steps. Timings include actual
W01/W02 source preparation, geological binding, W07 setup, checks, compute/store
work, complete final-field hashing and close. Imports/process startup are excluded.
All final fields and scientific identities match exactly. Warm recovery validates
the stored prefix but decodes only the requested latest output, not all three.

| Execution | Median seconds | Difference from fresh |
|---|---:|---:|
| Fresh, no persistence | 6.1484041 | baseline |
| First run with checkpoints | 6.7045900 | +0.5561859 s / +9.0460% |
| Reopen completed checkpoints | 2.6080241 | -3.5403800 s / -57.5821% |

Restore computes zero outputs; fresh/save compute three. Partial restart tests
also prove no completed mechanical solve is repeated. These are measured
same-workflow recovery savings, not a whole-generator first-run speedup. The raw
lossless store was held constant; zstd was not benchmarked or imposed. Exact
pre-copy deduplication reduced this final snapshot's array payload from 382,016
to 373,040 bytes (8,976 bytes, 2.35%); no physical fields were dropped. Every
measured owner returned to zero reserved bytes, with unchanged shared admission.

Reproduce only when inputs/code/dependencies change or new coverage is needed:
`python -B tectonics/tools/check_w07_workflow.py --report NEW.json`.
`--mode acceptance` and `--mode timing` separate the two jobs. Existing reports
cannot be overwritten; source changes fail the run rather than silently repin it.

Retained failures: one geology cancellation fixture used a callable rather than
the required Event; the affected test passed after correction. The first workflow
run stopped at source-inventory admission before physics. The next exposed a
tuple/list provenance representation mismatch; canonical JSON normalisation
fixed that comparison without weakening source equality. Passing surface coverage
was not repeated for this motion-only correction.
Final completion exposed near-rest transport divergence, a missing current-law
linear residual location, and a dry-strength tuple/list roundtrip comparison.
The initial workflow run passed 5/9 methods in 52.233 s; the affected/new run
passed 7/8 in 78.448 s, then the two remaining affected methods passed in 14.748 s.
The fixes above preserve original gates. The first assembled runner passed all
five checks; no grid/time/threshold retuning or repeated timing run was needed.

## Software and literature checked

These were documentation/method inspections, not executions of external software:

- [ASPECT 3.0 checkpoint/restart](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/run-aspect/checkpoint-restart.html):
  complete physical state and compatible configuration informed exact source,
  schedule and parent binding. Atlas does not copy its old-checkpoint deletion.
- [ASPECT material averaging](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/cookbooks/cookbooks/sinker-with-averaging/doc/sinker-with-averaging.html):
  warnings about blanket averaging informed the explicit pure-layer series law
  and refusal of unsupported mixtures rather than implicit smoothing.
- [ASPECT pressure splitting](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/methods/pressure-static-dyn.html):
  full physical gravity and solver-owned reference subtraction informed ownership.

No new paper-derived constitutive law was introduced. The existing solver,
transport, dry-strength and free-surface methods retain the research basis and
component validation recorded in Steps 2–4.

## Delivery

Local changes in Atlas `remake`; no commit, push, installation, R4.4 campaign or
whole-world generation. Completion handoff: `ATLAS-W07-5-20260923` to GEO
Coordination, Integration & QA. Sending is delivery, not downstream acceptance.
