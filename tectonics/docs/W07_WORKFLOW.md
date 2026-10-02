# W07 Step 5 — geological assembly and recoverable execution

Publication note, 26 September 2026: the linked W07 reports are now
explicitly redacted historical public copies. Only personal path components,
publication metadata and affected report-file digests changed; measurements
and original scientific source/runtime identities did not. The digests below
identify those public copies, not the original run artefacts. See the
[before/after trail](../evidence/public-path-redaction-r1.json).

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
The external surface pressure has no assumed value: the caller states
`external_pressure_pa`, zero gauge as an explicit `0.`, and an unstated pressure
is refused (R7 repair, 1 October 2026 candidate; before it, it silently became 0 Pa).

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
A restore regenerates that record from the stored mechanical field and requires
the stored record to equal it (R7 repair, 1 October 2026 candidate; see
[the heat-coupling record on restore](#recovery-storage-and-resource-ownership)).

## Recovery, storage and resource ownership

Schedules and cumulative partitions are immutable and source-bound. Every
computed output lands exactly on its requested time: the surface and heat
routes pass the output time as the declared interval end, and the restore checks
recompute the same partition (`timebase.interval_partition`). Full-mantissa
output times such as 0.011583828702548055 s over three steps were refused before
30 September 2026. The default of one step per output remains, but the surface
route now refuses any partition above its relaxation or surface Courant limit
and names the step count needed. Requested outputs are stored atomically in the existing `ArrayStore`. A compact catalogue
deduplicates identical arrays **before** payload copies, by exact dtype, shape
and bytes; no lossy compression or discarded physical fields are introduced.
Existing store compression policies, including zstd, remain selectable.

Recovery verifies the contiguous parent/source/schedule prefix, then decodes only
its newest record: the physical state, its endpoint mechanics and, for a thermal
output that evolved heat, the mechanics that carried the interval.
It checks geometry, inventory, force, viscosity,
boundary and constitutive bindings, numerical gates and heat accounts without
rerunning completed mechanical solves. Closed heat accounts check source energy,
prescribed fluxes, stored energy and parent continuity. Corrupted or incompatible
records fail; the driver does not silently restart from scratch. Only the latest
output is retained in memory. Solver histories/Krylov vectors are not archived.
Thermal continuation reuses the accepted endpoint mechanics; surface continuation
seeds only its validated endpoint into the prepared solver. Initial-state, actual
force-array, dry-strength linear-origin and surface-history checks also apply on
restore, including when a corrupted record has internally consistent hashes.

**Heat-coupling record on restore (R7 repair, 1 October 2026 candidate).** A heat
interval is carried by one mechanical field, its input mechanics: the solve at
the geological epoch for a first interval, the parent output's endpoint
mechanics for a later one. The heat receipt's coupling record names that field
(`mechanical_input_id`), the largest velocity correction and the hashes of the
two transported velocity arrays. The record is a function of the input mechanics
alone. Before the repair a restore could not see them: a first interval's input
solve was used and then discarded, and a later interval's input was known only
as an identity in its parent's metadata. Restore therefore checked the types of
the three fields and, for a later interval, the input identity against the
parent. A record rewritten with consistent hashes was accepted with a wrong
input identity at a first interval, and with wrong velocity hashes or an
inadmissible correction at any interval.

Every thermal checkpoint that evolved heat now stores its input mechanics as a
third snapshot, `coupling_mechanics`, beside `state` and `mechanics`. On restore
the workflow regenerates the coupling record from that snapshot, with the
function that produced the record, and requires the stored record to equal the
result exactly. The two are compared as the canonical bytes that enter the
output identifier, not as numbers. A correction that is exactly zero is recorded
as `0.0`; a record that states it as `-0.0` or as the integer `0` is an equal
number but other bytes, would restore as another output, and is refused. This
re-applies the admitted-correction limit. No mechanical solve is run. Two
further rules tie the snapshot to the run:

- A first interval has no parent record to name its input. Its stored input must
  pass the checks of a mechanical output at the geological epoch: the frozen
  numerical gates and execution identity, the epoch and time, the force source
  and force arrays of the source temperature, the plan definition, the
  stress-site viscosity and the physical boundary values.
- A later interval's record must name its parent's endpoint mechanics. That
  comparison existed; it now binds the snapshot that is actually stored.

A stored input on another velocity support than the heat grid, or whose
descriptor lacks the fields the regeneration reads, is refused. So is one whose
velocities are finite but overflow the regeneration: its correction is not a
number, which no stored record can equal. A coupling record that is not an
object is refused as an invalid binding; before the repair it raised an
unrelated error.

What this does not establish. The stored velocity and the stored diagnostics are
not recomputed, so they are trusted as stored, as a restored endpoint's are: a
stored input rewritten together with its record is caught only where a rule
above catches it. Only the newest record is decoded. Earlier records in the
prefix are still checked from their metadata alone. The exact comparison covers
the coupling record only. The receipt's other fields are still compared as
numbers, the heat account within its tolerances, so a record resealed with an
equal number in another encoding there (the step count `1` written as `1.0`) is
accepted and restores under another output identifier, as before the repair.

Costs and changes, accepted with the repair:

- Checkpoint content changes. An evolved thermal record without the snapshot is
  refused with a field-set mismatch, and so is a record at the geological epoch
  that carries one. Records written before the repair are recomputed in any
  case, because the package execution identity changed.
- Stores grow by up to one mechanics snapshot per evolved output. The store
  keeps each distinct array once, so a later interval's input, which is its
  parent's endpoint, adds no array payload; a first interval's epoch solve adds
  its own arrays. Each evolved record's manifest grows by about 10 KB when the
  input shares all its arrays with the endpoint (material at rest) and by about
  18 KB when it shares none.
- A restore decodes and hashes one more snapshot. The published outputs and
  their identifiers are unchanged by the stored input.
- The restore's own reservation keeps its rule: four times the record's distinct
  stored array bytes plus 64 KiB. It now has to cover a third decoded snapshot
  as well. In every case run for this candidate it still covered what a restore
  holds while it validates, which is the arrays read from the store and every
  decoded snapshot. The cases were square grids from 2 x 2 to 64 x 64 without
  gravity, at rest under gravity and with flow, and elongated grids from 64 x 2
  to 2 x 64 without flow, each on both schedules. The margin is smallest where
  nearly all stored fields coincide: 46,231 B on 64 x 64 without gravity and
  with a zero pressure datum. There four times the distinct bytes alone falls
  19,305 B short, and the 64 KiB term supplies the cover. A focused test holds
  the rule on the flow fixture.

Measured on the workflow test fixture, three outputs, raw lossless store, on
Windows/CPython 3.12.14 in the repair's scratch candidate against `8ee1041`.
These are exact byte counts and accounted allowances, not timings or RSS. "Flow"
is linear Boussinesq buoyancy under a laterally varying bottom heat flux, where
input and endpoint share no solved field; "epoch" and "first" are the schedules
(0, 0.01, 0.02) s and (0.01, 0.02, 0.03) s, with two and three evolved outputs.

| Case | Array payload, B | Manifests, B | Database file, B |
|---|---:|---:|---:|
| At rest, 16 x 16, epoch | 48,192 → 48,192 | 77,580 → 97,015 | 176,128 → 192,512 |
| At rest, 16 x 16, first | 48,192 → 48,192 | 78,535 → 107,688 | 176,128 → 204,800 |
| Flow, 16 x 16, epoch | 127,680 → 127,680 | 77,618 → 114,659 | 323,584 → 360,448 |
| Flow, 16 x 16, first | 127,680 → 163,280 | 78,551 → 134,122 | 327,680 → 438,272 |
| Flow, 64 x 64, epoch | 1,909,824 → 1,909,824 | 78,466 → 115,628 | 2,068,480 → 2,101,248 |
| Flow, 64 x 64, first | 1,909,824 → 2,445,008 | 79,465 → 135,228 | 2,068,480 → 2,666,496 |

The smallest shared budget that admits the store and the workflow, for the flow
cases with three outputs (each threshold is admitted exactly and refused one
byte lower):

| Grid, schedule | To run, B | To restore the last output, B |
|---|---:|---:|
| 4 x 4, epoch | 47,511,346 → 48,420,082 | 32,450,185 → 32,455,913 |
| 16 x 16, epoch | 52,264,391 → 53,174,031 | 36,211,183 → 36,282,383 |
| 64 x 64, epoch | 123,443,050 → 124,354,538 | 91,529,071 → 92,599,439 |

With flow, a run needs about 0.91 MB more at every grid size, which is the
store's staging allowance for the larger manifest and the additional arrays,
and a restore needs twice the added distinct array bytes more. At rest a run
needs about 0.08 MB more and a restore nothing more. On the largest regional
grid, 64 x 64, the run uses 124,354,538 B of the 134,217,728 B default. A
restore still needs less than the run that wrote the record in every measured
case, so no budget can publish a checkpoint that it cannot restore. Wall-clock
restore and storage time were not measured for this candidate.

Ten methods in their own class of the
[workflow tests](../tests/test_w07_workflow.py) hold this, nine on a flow case
and one on a case without gravity, where nothing moves and the correction is
exactly zero. Receipts are rewritten with consistent hashes at the first and at
a later interval: the input identity (a made-up one, and the record's own
endpoint), the velocity hashes (made up, exchanged, malformed), the correction
(inadmissible, the next representable number and, where it is exactly zero,
`-0.0` and the integer `0`) and the record itself replaced by a list or by
nothing. Records are also published with a substituted snapshot: none, an
unexpected one at the epoch, the endpoint in place of a first interval's input
with and without a matching record, the endpoint relabelled to the epoch, the
epoch input labelled with another time or with diagnostics that failed the
gates, another mechanics of the same run in place of a parent's endpoint, and an
input on another support, without diagnostics or with velocities that overflow
the regeneration. The remaining methods hold that an honest first-interval
restore equals the continuous run and solves nothing, that a run does not
continue from a resealed latest record, which snapshots a record stores, that a
restore is admitted by the smallest budget that admits the run and reserves for
itself exactly what its rule states, and that an interval's input is not kept
alive into the next interval. Seven of the ten fail without the repair; the
three that pass either way guard what the repair must not change (no solve on
restore, no budget that publishes what it cannot restore, and no more snapshots
alive during a solve than before). These were run in the repair's scratch
candidate on Windows/CPython 3.12.14 only.

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

**Interrupted dry-strength refill (R7 repair, 1 October 2026 candidate).** The
steady dry-strength route lends the workflow's own regional plan to the C01
Picard loop, which refills the plan's stress-site viscosity at every iteration.
A refill that is cancelled or fails between the start of its numeric part and
its acceptance leaves that plan
[invalid](W07_REGIONAL_SOLVER.md#resources-execution-and-reuse): it refuses
every further operation. Before the repair the workflow kept the dead plan, so
every later `run` on it was refused and the caller had to close the workflow and
prepare another one. The workflow now closes and drops such a plan as the
failure passes through it, which releases the plan's retained allowance. Its
next operation, `run` or `load`, first prepares a new plan from the same
geological binding, scales and pressure convention, through the one call that
also prepared the first plan. The new plan must carry the workflow's execution
identity: if the loaded source differs it is closed, the operation is refused
and a new workflow is needed. The regional plan's own rule is unchanged: nothing
is rolled back and an invalidated plan is never used again.

A failure that leaves the plan usable keeps it, for example a cancellation
before a refill starts or just after one was accepted. The Picard loop always
restarts from the creep viscosity, so coefficients left behind by an abandoned
iteration never enter a result. The other routes never refill coefficients and
are unaffected.

What this costs and changes:

- The new plan is a cold preparation and needs fresh admission of the plan's
  retained allowance. The dead plan is released first, so a retry reserves no
  more than an uninterrupted run; a focused test holds this at the smallest
  budget that admits the route. A new plan whose preparation is refused or
  cancelled is not adopted, and the next operation tries again.
- A `load` that follows an interrupted run also prepares the new plan, even
  when it then finds nothing to restore.
- The retried output, its identifiers and its stored checkpoint equal those of
  an uninterrupted workflow.

Ten methods in their own class of the
[workflow tests](../tests/test_w07_workflow.py) hold this. They interrupt a run
by a cancellation inside the factorisation, a cancellation after the solver core
took the new coefficients, a factorisation failure and an interruption that is
not an ordinary exception, and then compare the same workflow's retried, stored
and restored output with an uninterrupted workflow's. They also cover the
released reservation, a restore that needs the new plan before any solve, a
cancellation at every cancellation check of the new plan's preparation, a new
plan the budget refuses, a second interrupted refill on the new plan, the
smallest admitting budget, the kept plan after a failure that left it usable,
and a new plan refused under another execution identity or a changed source. The
plan refused under another identity is closed at once: the test reads its
returned allowance while the refusal is still being raised, not after the
garbage collector has released it. Cancellations and failures are injected
through cancel tokens and attributes of the one plan or workflow object; the
changed source is emulated as the existing source-drift tests do it. These were
run in the repair's scratch candidate on Windows/CPython 3.12.14 only. The
counts and timings recorded below are the 23 September record and are not
rewritten.

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
`b21b9b38b18a33f74bd8732a436d54baf449e93c3ac97c9a05e19c69255f460f`.
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
