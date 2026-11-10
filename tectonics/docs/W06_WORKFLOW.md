# W06 spreading, histories and recoverable workflow

22 September 2026. Selected combined acceptance PASS.
The [frozen design](W06_SPREADING.md) and Steps [2](#oceanic-birth-and-spreading),
[3](W06_COOLING.md) and [4](#changing-motion-histories) retain their equations and tolerances.
This step adds an executable requested-output schedule and exact recovery, not
another physical law or an internal time-stepping approximation.

The Step-1 design is retained byte-for-byte as a frozen input to the W06 cases,
tests and benchmark drivers. Its "implementation pending" and "not yet claimed"
phrases describe the design capture; the implemented routes and bounded outcomes
are documented here and in Steps 2–4. They are not outstanding implementation
instructions or a claim of empirical validation.

## Supported routes and API

`PreparedW06Workflow(prepared, output_times_s, *, margin_policy=None, store=None,
budget=None, cancel=None)` accepts exactly one of:

- `PreparedSpreadingCooling`: constant prescribed spreading with phase-resolved
  cooling, finite material/heat/water accounts and one local support owner.
- `PreparedHistoryCooling`: the same thermal model driven by explicit changing
  motion, stop/restart and plate-ownership histories, retaining first-exit records.
- `PreparedMarginCooling`: the actual inherited W01 column/profile and its
  stationary conductive evolution, water account and reference-based support.

The third route requires `MarginWorkflowPolicy(materials, support,
initial_depth_m, area_m2, water_stock_m3, water_source_id, source_id)`; `materials`
is an immutable tuple of the exact source-linked `BoussinesqMaterial` objects.
The existing margin producer validates the whole profile, source materials,
references and trajectory-wide water/deflection bounds at preparation. It never
turns the inherited column into newborn ocean or invents a missing cooling age.

The routes are separate physical domains/scenarios. Running them through one API
does not merge footprints, invent a continental-oceanic transition or grant two
runs ownership of the same external reservoir. A changed source, policy or schedule
defines a NEW invocation, not a migration of an older result.

The workflow borrows the producer and optional `ArrayStore`; it closes neither.
Use `.run(through=index)` for an inclusive output index, `.run()` for completion,
`.load(index)` for a saved output and `.checkpoint_id(index)` for its exact key.
The returned `W06WorkflowCheckpoint` contains `checkpoint_id`, `output_index`
and `state`. State is the original typed ocean thermal state or
`MarginSupportResult`, with all its normal field/account/provenance interfaces.
Without a store, only the latest output remains recoverable in RAM.

The explicit schedule has one to 256 strictly increasing, representable endpoints,
possibly including the initial time. Requested outputs do not create geological
events or reset the cumulative accepted-interval count. The workflow retains only
its current output; callers retaining older returned results supply their own
memory allowance. Shared budgets include retained state, decode/reconstruction
scratch, immutable metadata and the store's existing codec/SQLite allowances.

## Save, interrupt and resume

Each requested output is a candidate until the existing `ArrayStore.put`
transaction publishes its entire array manifest and metadata. Live source and
cancellation checks run again at the commit boundary. A failed pre-commit
publication leaves the previous accepted output usable. A later restart recreates
the same prepared recipe, opens the same store and calls `.run()`.

On resume, the bounded schedule's manifests must form a contiguous prefix, with
matching invocation/execution, parent checkpoint and ocean state-parent/count
links. Only the newest needed payload is decoded. Earlier payloads are fully
checked when individually loaded; this is not an archive-wide corruption scan.
Corruption, a missing predecessor or an incompatible binding raises visibly and
is never treated as a cache miss that can be silently regenerated.

Checkpoint bytes alone are not a self-contained recipe: the caller must supply
the same source-bound preparation, runtime and schedule. There is no automatic
source repinning, pickle, installation or old-checkpoint migration.

## Lossless storage and avoided work

The existing chunk store deduplicates and compresses immutable arrays using its
selected Zstd/Blosc2 configuration. No second cache or compression implementation
is introduced. A no-store route remains available for one-off calculations.

Ocean snapshots store cell and centre thermal fields plus small heat/water
accounts; history snapshots additionally store per-first-exit enthalpy/water pairs.
They do not duplicate grid geometry, fractions, masks, birth strips or export
provenance already fixed by the prepared recipe and requested time. Recovery
reconstructs that inexpensive exact geometry, verifies the original motion and
thermal identities, and checks linear support/account/finite-stock relations.
It does not repeat the completed age/depth thermal integrator.

Margin snapshots store means, temperature changes and outward boundary heat.
Small temperature changes are retained separately: subtracting two rounded large
temperatures at restart is not equivalent. Source objects, reference temperatures,
layer masses and trajectory bounds come from the same validated inherited recipe;
support and water are reconstructed with the original arithmetic and IDs. No
completed image/spectral conduction solve runs during a warm load.

Savings compare setup-inclusive cold computation/publication, verified reopening
and partial continuation on matched outputs. First-time persistence can cost more
than no-store execution; that cost must be reported alongside recovery savings.
The existing Step 3/4 kernel speedups are not new persistent-cache measurements.

## Combined acceptance

The frozen three-grid, age/depth quadrature, partial-cell, domain, event,
64/128-partition, first-exit and finite-envelope checks are retained from the
unchanged numerical components. Their relevant source/case/test bindings are
checked before reuse. Current workflow verification targets only the new joins:
all three typed routes, exact interruption/restart and request identities,
future events, inherited source history, corruption/invalidation, retained limits,
bounded resources and absence of repeated thermal work.

`python -I -B tectonics/verify.py --w06` selects the new combined workflow tests,
shared live-source identity tests and profile/status contract. It has no broad
discovery fallback; empty, duplicated, skipped, failed or source-drifted work
cannot receive PASS. Focused ocean snapshot tests are a separate component gate.
Numerical component evidence is documented in [Step 3](W06_COOLING.md#retained-numerical-evidence)
and [Step 4](#history-numerical-evidence); these are not rerun for reassurance.

The selected profile passed all 20 checks in 44.148 s with no skips, failures,
errors or source drift: eight combined workflow checks, nine shared identity
checks and three acceptance-profile checks. Five focused ocean codec checks also
have passing evidence. See the [acceptance record](../evidence/w06-workflow-acceptance.json)
and [retained workflow measurements](#retained-workflow-measurements).

The existing empirical challenge remains separate: independently reconstructed
isochrons/motion, corrected basement depths and heat-flow observations must be
bound before an observational claim. Do not reuse fitted observations as held-out
validation. This workflow does not reopen R4.4 or authorise a large world run.

## Retained workflow measurements

The 22 September 2026 Windows/Python 3.12.14 measurement uses one numerical thread
and three rotating-order samples/mode, 4000-cell ocean cases / two actual margin
layers / four outputs. Each mode includes fresh context/preparation/workflow,
execution and closure; durable modes also store open/close/inventory. Process
launch, source hashing and exact equality work are outside the timer. Warm
means reopened SQLite connection, not OS cold cache.

| Route | No-store, s | First-save, s | Verified warm, s | Warm vs no-store | Partial, s |
| --- | ---: | ---: | ---: | --- | ---: |
| Constant ocean | 1.220668 | 1.683468 | 0.520681 | 0.699987 s/57.34% less | 0.919054 |
| Changing-history ocean | 0.981009 | 1.341096 | 0.396041 | 0.584968 s/59.63% less | 0.705706 |
| Inherited margin | 0.989721 | 1.099665 | 0.411937 | 0.577783 s/58.38% less | 0.602819 |

First publication adds 37.91%/36.71%/11.11%. Warm versus full compute+publish
saves 69.07%/70.47%/62.54%. Partial continuation starts with outputs 0–2 accepted,
restores 2 and computes/saves 3: prefix/seeding is excluded, so 45.41%/47.38%/45.18%
less time than full cold publication is shorter remaining work, not a faster
algorithm or cheaper interruption overall. No-store remains appropriate when
durability is unnecessary. These gains cannot be added to Step 3/4 kernel gains.

All 36 timed results exactly matched complete typed-state/array/account/provenance
signatures; 97 benchmark source bindings matched before/after. The
[original samples](../evidence/w06-workflow-timing.json) retain raw data and
conditions; no rerun selected better numbers.

| Route | Snapshots | Encoded payload, B | Database, B | Peak accounted, B |
| --- | ---: | ---: | ---: | ---: |
| Constant ocean | 4 | 485,901 | 548,864 | 48,195,696 |
| Changing history | 4 | 503,118 | 565,248 | 48,236,200 |
| Margin | 4 | 168 | 32,768 | 34,345,687 |

Reservations closed at zero under 128 MiB including 16 MiB caller allowance; this
is accounting, not an RSS cap. Existing Blosc2-backed Zstd level 1 / byte shuffle /
palettes were used, no dictionary/decoded cache or standalone zstandard package.
Ocean provenance/geometry reconstruct from bound recipes; margin separately
retains tiny temperature changes to prevent cancellation on restore.

## Retained recovery controls and limits

The [unchanged acceptance JSON](../evidence/w06-workflow-acceptance.json) retains
20/20 in 44.148151 s, no errors/failures/skips/source drift: eight workflow, nine
identity and three profile/status controls. Separate static symlink skipping
does not affect that strict profile. Coverage includes all three typed routes,
exact fresh-child continuation, unknown inherited history/nonzero epoch, future
event provenance, independent endpoint/first-exit checks, zero warm-load thermal
calls, finite stocks, precommit rollback/mid-evolution cancellation, corruption
including consistently rehashed foreign state, missing history and source/
schedule/policy refusal, bounded decode and 256-request/borrowed-owner limits.

Five ocean-codec controls have passing evidence; initial full five passed, then
only the affected budget/cancellation/history-corruption method was rerun after
fixing stricter child-budget propagation into ocean packing. Earlier numerical
evidence was reused only after 94 Step 3/4 source/case/test bindings matched,
excluding intentionally changed public exports/identity registry, with current
shared-identity controls covering registration. No three-grid/quadrature/partition
sweep was repeated or claimed as new.

This establishes PASS_SUPPORTED_W06_WORKFLOW, not a merged ocean-continent domain,
independently calibrated age/depth/heat-flow realism, Linux execution, power-cut
or arbitrary sync/network durability. Existing SQLite/filesystem guarantees remain;
R4.4 and scientific holds stay intact. All source/recipe/output-index/parent
bindings, corruption refusals and no-repin rules above remain unchanged.

## Existing software and research consulted

- [ASPECT 3.0.0 checkpoint/restart documentation](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/run-aspect/checkpoint-restart.html):
  full-state continuation and its warning about incompatible changed parameters
  inform exact source/recipe binding here. Atlas does not adopt permissive changes
  to an existing checkpoint's physical inputs. Documentation read; ASPECT not run.
- [SQLite atomic commit](https://www.sqlite.org/atomiccommit.html), introduction
  and recovery/testing discussion: publish all state together and test an
  interruption inside the transaction. Existing ArrayStore is reused; this does
  not claim a new filesystem power-loss test or remove hardware assumptions.
- [Official pyGPlates inherited thickness/subsidence example](https://www.gplates.org/docs/pygplates/sample-code/pygplates_reconstruct_crustal_thickness_and_tectonic_subsidence),
  selected Details: explicit inherited initial scalars and handling of inactive
  points inform the no-defaulted-history/no-discarded-inventory boundary.
  Documentation/example conventions, not an independent numerical oracle.

The TracTec and oceanic thermal papers already discussed in the frozen design
remain the physical background; no new physical law or fitted parameter is added
by this persistence step. External geodynamic packages were not installed/run.

<a id="oceanic-birth-and-spreading"></a>

## Oceanic birth and spreading

Status: **prescribed planar, constant-velocity implementation**.
This implements the material/motion part of the [frozen Step-1 design](W06_SPREADING.md).
See [retained numerical evidence](#birth-numerical-evidence); this is not combined W06
acceptance or empirical validation of generated terrain.

### Model and ownership

An initially empty ocean receives two continuous strips at a supplied ridge.
The ridge position is `r(t) = r0 + vr*t`; a parcel born at offset `tau` follows
`x(t;tau) = r0 + vr*tau + u*(t-tau)`. Each side has its own constant plate
velocity and plate ID. Positive half rates `vr-uL` and `uR-vr` are required.
The supported fixed-source-window family has `uL <= 0 <= uR`; the active ridge
must remain strictly inside that window. Inward trajectories, ridge exits and
time-varying schedules are refused, not silently discarded.

Each phase supplies a fixed reference thickness, reference density and finite
external stock in kg, with distinct phase/feed IDs. Newly created reference mass
is `(uR-uL)*elapsed*strike_width*thickness*density`. The frozen case contains
disjoint 0–7 km crust and 7–100 km mantle layers, not two overlapping full plates.
This prescribed accretion model does not predict mantle melting or breakup.

`PreparedRidgeSpreading.advance` computes a complete candidate from the original
event. It refuses the whole request if any phase feed is exhausted. An unchanged
endpoint returns the identical immutable state and does not debit stock again.
Candidate branches do not authorise spending a shared real reservoir twice:
committing shared feeds belongs to the later workflow transaction owner.

### Exact histories, projection and accounts

Two `BirthStrip` records retain full unclipped affine formation-time histories,
plate/ridge/event IDs and offsets from the explicit onset epoch. For this selected
hot-birth family only, cooling onset equals formation; inherited continental
histories are not represented by these strips and must not be reset to them.

The vectorised cell intersection returns `(side, cell, 3)` values:

- occupied width in metres;
- youngest material age in seconds;
- oldest material age in seconds.

Positive width is validity. Empty cells have zero placeholders, **not valid
zero-age material**. Ages are uniformly distributed within each occupied side-cell
intersection because the birth path is affine. Both sides are retained when a
cell straddles the ridge. `phase_thickness` is only a conservative cell mean;
downstream cooling must use the full age distribution, not cool its mean age.

The per-phase `accounts_kg` columns are created, remaining feed, represented,
left export, right export and material-balance residual. Exports are direct
boundary-crossing integrals, not leftover cell mass. Each phase and the summed
material ledger use the existing W02 roundoff policy. Finite feed debit is
checked separately. The stored residual follows W02's
`represented - created + left_export + right_export` sign convention.

Geometry is evaluated in onset-local coordinates to avoid subtracting rounded
large absolute positions. Unresolvable widths/clock increments and numerical
overflow refuse; no stock clipping, age clipping or tolerance relaxation is used.
The immutable state ID binds its payload and parent; prepared identity binds
the grid, motion, phases, epoch, strike width, source and execution identity.
The new module participates in shared source/live-callable protection.

### Efficiency and limits

Closed-form paths avoid internal advection time steps, scalar per-cell searches
and output-dependent birth bins. Each requested output is O(cells + phases);
the physical history remains two strips rather than growing with output count.
Immutable buffers are reused without an extra conversion copy. A prepared plan
can share an existing source-verifying `ExecutionContext`. Repeated endpoint
reuse is in memory, not a persistent cache claim.

Current caps are 65,536 cells, 16 distinct phases and 256 requested intervals.
WorkBudget leases, cancellation, foreign/closed-state checks and source checks
are retained. As with W02, callers must account for retained output states;
the prepared lease owns its initial state, not arbitrarily many caller snapshots.
The benchmark explicitly reserves caller output allowances. These are accounted
working bytes, not measured process RSS.

[Cooling and inherited margins](W06_COOLING.md), heat/water/support accounts,
[changing/stopped histories](#changing-motion-histories) and [durable recovery](W06_WORKFLOW.md)
have separate contracts; this birth component does not establish their acceptance. No
stationary W03/W04 assembled adapter is applied to these moving newborn strips.
No disk cache or parallel dispatch is added to this inexpensive vector kernel.

<a id="birth-numerical-evidence"></a>

### Retained birth numerical evidence

The 22 September 2026 Windows 11/Python 3.12.14/NumPy 2.4.6 run used one numerical
thread. At 20 Myr it created 800 km/m strike, 1.624e13 kg crust and 2.4552e14 kg mantle,
with zero ledger residual; remaining feed was 3.76e12/5.448e13 kg. A smaller 200 km
window independently accounted both boundary exports without changing common
interior history. Three 1000/500/250 m grids, 0/5/10/20 Myr and partial-cell outputs,
ridge-straddling/nonuniform cells, independent birth moments, finite/exact-feed
exhaustion, exports/domain enlargement and translated/moving frames were checked.

32/64/128 requested partitions retained bit-identical final geometry/accounts
and full strips, while parent/state identities recorded the actual sequence.
Zero/repeated endpoints, 256 limit, immutable views, cancellation/budget/closed/
foreign/live-source refusals passed. Eleven focused tests have passing evidence
across the original run and scoped corrections: first nine passed/two failed
test normalisation, then those two passed. The corrected assertions divide
each moment by its own occupied width and compare near-zero signed balance
against established mass-scale roundoff, not relative zero. Frozen 1e-7 m geometry,
1 s age and 128-epsilon W02 mass gates were unchanged. Nine shared identity checks
passed; the static suite's Windows symlink skip was a separate platform limit.

[Original timing and source record](../evidence/w06-birth-timing.json) retains
three alternating repetitions / four outputs / 4000 cells / two phases, imports excluded:

| Scope | Median | Interpretation |
| --- | ---: | --- |
| Independent scalar geometry | 0.017475400 s | Matched width/youngest/oldest fields |
| Vector geometry | 0.000484100 s | 97.23% less kernel time, not older-production/world gain |
| Prepared protected sequence | 0.459981000 s | Fresh context/outputs/thickness/accounts; no matching end-to-end baseline |
| Validated identical endpoint | 0.021219200 s | In-memory reuse, not persistent-cache gain |

Maximum matched width error 3.962e-11 m and age 0.0625 s over 20 Myr are numerical
reference differences, not geological accuracy. Accounted peak 8,680,576 B includes
6,721,664 B caller allowance and closes at zero; it is not measured RSS. Source
checks dominate this small protected workload and remain enforced. No Linux,
full-generator/Diadem/R4.4, thermal simulation or durable W06 cache was run by
this birth evidence. The research access limits below remain unchanged.

### Reproduction

With the existing NumPy/SciPy-compatible environment, run from the Atlas root:

```powershell
$env:PYTHONPATH='tectonics/src;tectonics/tests'
python -B -m unittest test_w06_spreading -v
python -B -m unittest test_execution_reuse.IdentityTests -v
python -B tectonics/tools/benchmark_w06_spreading.py --output w06-birth-timing.json
```

The fixture binds the unchanged Step-1 design by SHA-256. Changing that design
requires explicit review, not an automatic pin update. The scalar reference has
no production imports: it integrates the birth-time preimage of each cell and
uses two-point Gaussian integration for first/second formation-time moments.
The benchmark compares identical width/age fields at four outputs on 4,000 cells
using three alternating repetitions; setup-inclusive protected outputs and
same-state request validation are reported separately.

### Research/software checked for this implementation

- [Karlsen et al., TracTec author preprint](https://arxiv.org/html/1910.03351):
  selected birth/advection methods and limitations informed explicit continuous
  formation histories and the distinction between prescribed motion and predicted
  dynamics. The reference/production integrals here are independently derived 1D
  paths, not a claim to implement the full tracer model.
- [Official pyGPlates conjugate-isochron example](https://www.gplates.org/docs/pygplates/sample-code/pygplates_create_conjugate_isochrons_from_ridge):
  documentation/example code checked for conjugate birth geometry and separate
  plate identities. No pyGPlates runtime was installed or executed.
- Existing Atlas W02 material ledgers and W05 preparation/resource/source guards
  were inspected and reused where their contracts apply. No new dependency or
  external code copy was required.

<a id="changing-motion-histories"></a>

## Changing plate-motion histories

22 September 2026. This extends the frozen
[W06 design](W06_SPREADING.md), [birth geometry](#oceanic-birth-and-spreading) and
[cooling/support adapter](W06_COOLING.md). The Step 1 design bytes and numerical
gates are unchanged. Checks and measured performance are recorded in
[retained numerical evidence](#history-numerical-evidence).

### Events and material history

`RidgeHistoryEvent` supplies its offset from the named forward-running onset,
ridge position, left/right/ridge velocities, side plate IDs, activity, event ID
and source ID. Events start at offset zero, are strictly ordered and have unique
IDs. Between events, trajectories are affine. At an event, the new interval owns
the boundary while the preceding interval contributes its completed births only
once. An output request does not create a new physical cohort.

Ridge position must equal the position reached by the preceding motion. Arbitrary
ridge jumps and changed ridge identity refuse rather than create overlapping crust.
Asymmetric relative rates and continuous ridge migration are supported. The active
fixed-window route retains outward side velocities and positive relative spreading
on both sides, preventing exported material from silently re-entering. A stopped
welded boundary has all three velocities zero. It creates no material, but existing
crust continues to age and cool; subsequent supported restart adds new birth strips.

An explicit `PlateReassignment(side, from_plate_id, to_plate_id, source_id)` is
required for every changed side owner. Inherited birth event, source, original plate
and cooling onset remain unchanged. Current ownership is separate from origin.
No geometry or mass is added by reassignment; material already exported retains
its owner at first exit, not a later reassigned owner.

For a parcel born at time `tau` in a stage with ridge/side velocities `vr_i,u_i`:

```text
x(t;tau) = r(tau) + sum_k u_side,k * duration([tau,t] intersect stage_k)
dx/dtau = vr_i - u_i
formation_age = cooling_age = t - tau
```

The birth-time Jacobian depends on the birth stage, not the current rate. Each
semantic active interval therefore creates two affine strips with their complete
birth-time distributions. Intersect those strips with cells; do not infer old ages
from current ridge distance, average separate birth intervals before cooling, or
create tracer-age floors. Centres on the ridge are actual age samples, including
after spreading stops, not missing cells.

### First exits, heat and water

Each export record splits at both its birth stage and its exit-motion stage.
Solving the affine parcel path against the fixed boundary gives paired birth,
exit-time and exit-age endpoints. Endpoints are ordered by increasing birth time:
**exit age need not increase in that order**. A thermal mean uses the full range,
including the equal-age limit, weighted by exported width.

Exports retain original birth identities, the actual owner/event/source at first
exit and the named external destination. Heat, water and reference mass cross once.
After exit, further cooling or reassignment outside the region does not change
that regional export. The existing W06.3 thermal kernel, support owner, validity
limits, finite reservoirs and account tolerances are reused unchanged.

The frozen switch control changes rates after 10 Myr to ridge +5, left -15 and
right +35 mm/year. At 20 Myr the ridge is at +50 km, outer born edges are -350 and
+550 km, created width is 900 km and right export from the +/-500 km source window
is 50 km. Exported births span 0-2.5 Myr; their first-exit ages range from
18.571428571 to 17.5 Myr. The separate stop control creates only 400 km: at 20 Myr
the crust has ages 10-20 Myr, despite no motion since 10 Myr.

### Interfaces and efficiency

`PreparedSpreadingHistory(grid, events, phases, time_s=..., epoch_id=...,
width_m=..., source_id=..., context=..., budget=...)` has `.initial`,
`.advance(state, time_s=...)`, `.phase_thickness(...)` and explicit closure.
`HistorySpreadingState` retains exact strips, compact intersections, centre ages,
coverage, segmented exports and phase accounts. An intersection row is
`cell_index, strip_index, width_m, youngest_age_s, oldest_age_s`; its integer indices
are exactly represented in float64. Empty centres are marked invalid.

`PreparedHistoryCooling(history, parameters, budget=...)` projects that state into
the same cell/centre field and heat/water array layout documented for W06.3.
`HistoryThermalState.exports` contains `HistoryThermalExport(history,
destination_id, enthalpy_j, water_m3)` records. `history` is the exact first-exit
record, not an endpoint-only summary. The inherited continental margin adapter is
unchanged; plate reassignment is not permission to reset or recreate a continent.

Preparation validates and binds the event catalogue. Outputs integrate supplied
piecewise motion directly, without internal time stepping. Cell projection stores
only actual strip-cell intersections, then groups weighted thermal values by cell.
There is no dense events-by-cells tensor or copy of all earlier fields. Compatible
phase-age evaluations retain exact-key deduplication; no approximate age bins.
Source-validated prepared reuse and identical-endpoint reuse remain active.
Monotone outward motion proves that a side's younger material cannot have exited
if its oldest parcel is still inside the window. Such cases skip the quadratic
birth/exit-stage scan and its worst-case metadata reservation. Individual
non-crossing strips are skipped too. This admits the checked 256-event no-export
case within 128 MiB without weakening source or numerical checks.

Measured on the frozen switch: matched 256-cell output takes 0.101052 s instead
of 0.646369 s for independent scalar integration (84.37% less time). Reusing one
preparation across four 4000-cell outputs takes 0.658347 s instead of 1.273474 s
with fresh preparation each time (48.30% less, setup included). These are separate
three-repetition median comparisons, with no approximate physical shortcuts;
the [raw evidence](../evidence/w06-history-timing.json) retains raw timings,
numerical errors, source bindings and admission accounting.

The accepted-request ceiling remains 256; semantic events also have a finite 256
cap. Memory admission includes temporary escaped metadata used in identities, not
just numerical arrays. Complex histories may exhaust the supplied budget and are
refused without partial debits. Outputs are immutable candidate branches; durable
publication/recovery is Step 5. No disk cache, new dependency, worker pool or
unrequested large simulation is introduced here.

<a id="history-numerical-evidence"></a>

### Retained history numerical evidence

The 22 September 2026 Windows 11/Python 3.12.14/NumPy 2.4.6/SciPy 1.17.1 checks used
one numerical thread. The independent reference integrates each parcel's supplied
piecewise velocity and chronological first crossing, then uses separate adaptive
depth/age thermal integration. It imports no production geometry/thermal routines
and receives complete birth-age intervals rather than mean age.

Eight geometry methods have passing scoped evidence. The initial six-pass/two-
failure batch exposed test-fixture issues: a nearly symmetric linspace centre
really had 0.0625 s age, and a mocked export correctly triggered live-source
protection. Exactly symmetric geometry and a genuine bounded-admission fixture
corrected those two tests without changing production or acceptance. Nine shared
identity controls passed. Twelve assembled thermal/history methods then passed
with no subsequent production change; unchanged Step 3 suites were reused.

Coverage includes 900 km created / 850 km represented / 50 km right export, exact cell
intersections/centre ages, first-exit time/age/owner, reassignment/stopping/restart,
semantic-boundary samples and event ± 1 s, partial outputs, 64/128 partitions,
clipped/enlarged domains, constant-history reduction to Step 3, finite heat/water,
immutable/source/cancellation/budget guards. Restart retains the genuine missing
birth-age interval instead of resetting old crust or smoothing the discontinuity.
The 256-event no-export case fits 128 MiB by avoiding unneeded quadratic export work,
not by relaxing limits.

[Original raw timing](../evidence/w06-history-timing.json) retains the two separate
three-alternation comparisons above: matched 256-cell independent-reference output
and setup-inclusive four 4000-cell preparation reuse. An identical endpoint took
0.023533 s with current source checks. Prepared reuse gave exactly equal fields,
centre ages/accounts. Maximum matched phase mean error 2.05e-12 K, subsidence
6.75e-13 m, centre-age zero and normalised heat 4.24e-17; absolute cumulative
heat-field difference 0.046875 J/m2 and independent balance 9.35e-17 of birth heat
retain their distinct measures. Accounted peak 45,256,928 B includes 24 MiB caller
allowance, closes at zero and is not measured RSS. No tolerance changed, large
run or new external simulator execution is claimed.

### Papers and existing software actually checked

- [Karlsen et al., TracTec, selected full-text methods 2.1-2.2](https://arxiv.org/html/1910.03351):
  separate tracked age and changing current plate identity; prepare motion data
  outside the output loop. Its Euler stepping, ridge offsets, age floor and tracer
  deletion are not this conservative affine implementation.
- [Official pyGPlates conjugate-isochron example, Details and Advanced](https://www.gplates.org/docs/pygplates/sample-code/pygplates_create_conjugate_isochrons_from_ridge):
  explicit birth time, ridge geometry and conjugate side IDs. Missing IDs are
  rejected rather than replaced with example defaults; its geological time sign
  is not silently copied into this forward-running epoch.
- [Official pyGPlates topological-reconstruction primer](https://www.gplates.org/docs/pygplates/pygplates_primer.html#what-is-topological-reconstruction):
  per-interval ownership and motion. The design inference here is to retain origin
  separately, refuse missing coverage and preserve first-exit accounts instead of
  deactivating/discarding material or silently holding an uncovered point stationary.

The linked documentation/example code and selected paper sections were read;
TracTec and pyGPlates were not installed or executed. Piecewise characteristics and
their finite-volume accounts are derived directly from the frozen W06 equations.
