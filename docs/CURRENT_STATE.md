# Atlas: current development state

Source date: 15 September 2026. WORKING NON-CANON. This page is a public technical handover, not an accepted scientific model or a world dataset.

Local code supplement, 22 September 2026: [W01 Stage 7](../tectonics/docs/W01_REGIONAL_WORKFLOW.md)
now supplies the supported described-geology-to-regional-material workflow, with
retained initial thermal provenance, verified reuse and restoration.
[Stage 8](../tectonics/docs/W01_COMBINED_ACCEPTANCE.md) adds the focused combined
technical assessment, distinct from whole-W01 scientific acceptance, which remains
INCOMPLETE. Reopened S3C questions and the held R4.4 campaign are not passed by
these checks. The exact Tosi case-5b supplementary reference data and matched
comparison machinery are now integrated; this removes the source-data blocker,
not the held campaign's scientific acceptance requirements. See the
[bounded evidence](../tectonics/evidence/w01-bounded-validation.md).
The dated source handover and its scope below remain historical.

Local W03 supplement, 22 September 2026: [finite-plate thermal columns](../tectonics/docs/W03_THERMAL_COLUMNS.md)
add source-linked cooling ages, cell means, heat accounting and efficient direct
evaluation. [Thermal density and single-owner support](../tectonics/docs/W03_THERMAL_SUPPORT.md)
now add reference-column loads and total local displacement, using direct plate
integration with verified reuse. These two constant-property increments are
complete within their documented scopes. [Drained compaction and partial rebound](../tectonics/docs/W03_COMPACTION.md)
now add solid-conserving changing-area parcels, maximum-loading memory and finite
reservoir fluid accounts, with verified reuse/recovery. The [bounded W03 assembly](../tectonics/docs/W03_WORKFLOW.md)
now joins source-authenticated, stationary fixed-area sediment columns, initial
thermal reconciliation, booked finite reservoirs and exact restart continuation.
Its selected combined acceptance is distinct from general moving-stratigraphy,
empirical terrain realism or transient coupled pore-pressure/heat acceptance.

Local W04 supplement, 22 September 2026: [physical load construction](../tectonics/docs/W04_COLUMN_LOADS.md)
now uses finite fixed-reference columns, explicit replacement material and
separate thermal buoyancy, with compensated batched evaluation and verified reuse.
[Step 2 integration](../tectonics/docs/W04_WORKFLOW.md) now binds actual stationary
W01-W03 snapshots to explicit reservoir placement, separate external pressure and
the periodic uniform support solver, with exclusive thermal ownership and total-
reference surface changes. This is a one-way derived projection, not mesh/heat/
water feedback. [Step 3 finite 1D regions](../tectonics/docs/W04_FINITE_REGIONS.md)
now add explicit continuing-plate surroundings, physical free/clamped ends,
omitted-load error bounds and efficient analytic cell-load response.
[Step 4 variable rigidity](../tectonics/docs/W04_VARIABLE_RIGIDITY.md) now adds
fixed source-linked E/Te/nu profiles, the conservative Hermite weak operator,
explicit mesh-change gates and reused banded factors. Continuing variable-D
support requires exact declared exterior loads; evolving rigidity is unsupported.
[Combined W04 acceptance](../tectonics/docs/W04_COMBINED_ACCEPTANCE.md) now passes
the selected stationary planar 1D load-to-support workflow: 62 focused checks,
including six-route evolved-state accounts, reference changes and exact recovery.
This completes the scoped W04 sequence, not general terrain or field validation.
W05 [step 1 mechanism specification](../tectonics/docs/W05_REGIONAL_EXTENSION.md)
is now complete: prescribed dry listric extension, conservative material accounts,
single-owner support, independent references and a bounded acceptance design.
[Step 2 conservative motion](../tectonics/evidence/w05-motion.md) is implemented
and verified against independent quadrature: exact prescribed characteristic
transport, fixed footwall, tagged cohorts and finite-region exports. Kernel
integration is 99.04% faster than scalar quadrature; this is not full-generator
timing or coupled W05 acceptance. [Step 3 loads and support](../tectonics/evidence/w05-support.md)
now connects the motion to finite-column loads and continuous uniform flexure,
with true cell means and exterior/continuous-validity bounds. Sampled smooth
reference error at 125 m is about 1 mm; the prepared three-output load/support
sequence saves 24.84% including setup. [Step 4 recoverable workflow](../tectonics/evidence/w05-workflow.md)
now preserves complete outputs atomically, checks source-bound restart and avoids
repeating completed motion/flexure. Warm reopening saves 52.41% including setup
on the bounded case; compact snapshots use 39.97% less encoded payload than the
initial full-field layout. [Step 5 combined acceptance](../tectonics/docs/W05_COMBINED_ACCEPTANCE.md)
now passes the selected dry prescribed 1D workflow: 37 checks in 31.807 s,
full-crop smooth-reference support error 1.0164 mm at 125 m, identical final
32/64/128-partition surfaces, bounded domain sensitivity and exact recovery.
See [the measured evidence](../tectonics/evidence/w05-acceptance.md). This completes
the scoped numerical W05 sequence and separate analogue challenge plan, not
empirical terrain validation; analogue/support data remain to be independently bound.

Local W06 supplement, 22 September 2026: [Step 1 spreading design](../tectonics/docs/W06_SPREADING.md)
remains frozen. [Step 2](../tectonics/docs/W06_BIRTH.md) supplies conservative
constant-velocity birth and finite material feeds. [Step 3](../tectonics/docs/W06_COOLING.md)
now adds full-age/phase cooling, single-owner wet support, finite heat/water accounts
and explicit boundary-exit exports. Inherited margins preserve actual source thermal
fields and use trajectory-wide water/deflection bounds. Thirty new focused checks
have passing evidence; nine shared identity checks also pass. Matched thermal output
saves 73.29% (0.3553722 to 0.0949111 s) against independent scalar integration;
prepared margin reuse saves 51.76%. The separate 4000-cell/four-output protected
ocean sequence takes 0.5856 s including setup. See [evidence](../tectonics/evidence/w06-cooling.md).
[Step 4 changing histories](../tectonics/docs/W06_HISTORIES.md) now handles
asymmetric rate switches, continuous ridge migration, stop/restart and explicit
plate reassignment, preserving birth ages and first-exit heat/water/ownership.
Twenty focused checks and nine shared identity checks have passing evidence.
Matched 256-cell reference timing is 0.646369 to 0.101052 s (84.37% less time);
setup-inclusive reuse across four 4000-cell outputs is 1.273474 to 0.658347 s
(48.30% less). [Evidence](../tectonics/evidence/w06-history.md) keeps these distinct
from whole-generator performance. [Step 5 recoverable workflow](../tectonics/docs/W06_WORKFLOW.md)
now provides atomic checkpoints and exact continuation for all three routes.
The selected combined profile passes 20 checks in 44.148 s, without source drift;
five separate ocean codec checks also have passing evidence. Completed thermal
evolution is not repeated during verified reuse. See [workflow evidence](../tectonics/evidence/w06-workflow.md)
for warm recovery, partial continuation and first-save overheads. The scoped W06
implementation sequence is complete; its independent observational challenge
remains separate. Next: the selected W07 mechanical backend.

Local W07 supplement, 22 September 2026: the frozen [Step 1 design](../tectonics/docs/W07_REGIONAL_MECHANICS.md)
now has a [Step 2 regional mechanical implementation](../tectonics/docs/W07_REGIONAL_SOLVER.md).
It supplies constant-Newtonian full stress, imposed velocity/traction boundaries,
physical-pressure references, reactions, and source-bound SI results. The small
independent Q2/P1-discontinuous comparison supports retaining MAC for the next
increment. Native 64×64 reference errors are 0.157992% velocity/0.0178405% pressure;
refinement and retained smooth controls pass unchanged gates. Setup-inclusive
three-output 32×32 measurements save 44.8399% for prepared changing-load reuse and
53.5336% for verified identical requests; published arrays match exactly.
The implementation record preserves and resolves benchmark-adapter failures
without replacing successful evidence. Local 23 September increment:
[Step 3](../tectonics/docs/W07_HETEROGENEOUS_THERMAL.md) now implements explicit
heterogeneous properties, sharp-interface checks, retained nonlinear laws and
open/translated-grid thermal/material intervals with endpoint mechanics.
The SolCx manual/source discrepancy is recorded; both variants pass without
repinning the frozen case. Identical-request reuse saves 47.95% (0.94827 s);
changed coefficients show no measured gain.
[Step 4](../tectonics/docs/W07_SURFACE_STRENGTH.md) now implements dry
pressure-sensitive strength and body-fitted Q2/physical-P1 free-surface evolution.
Ten bounded relaxation trajectories pass; finest amplitude error 0.003688%, with
mesh/time convergence and conserved volume. Finest runs take 2.55–2.63 s;
identical-state reuse saves 54.64% (0.4548072 s) on three complete outputs.
[Step 5](../tectonics/docs/W07_WORKFLOW.md) now supplies geological assembly,
single-owner force/heat/motion, atomic complete snapshots and verified recovery.
All five assembled checks pass, alongside the codec/geology/workflow tests;
finest joined heat-reference RMS error is 0.003964% of the declared 100 K scale.
Reopening the same final state takes 2.608 s versus 6.148 s fresh (57.58% saved);
first-save overhead is 0.556 s / 9.05%. Selected W07 Steps 1–5 are complete for
their documented routes. The [case register](../tectonics/cases/w07_mechanics.json),
unsupported geological bridges and held R4.4 are not silently reclassified.
Local W08 supplement, 23 September 2026: [Step 1 regime design](../tectonics/docs/W08_REGIMES.md)
and its [frozen case register](../tectonics/cases/w08_regimes.json) now specify
finite shortening, full-vector transform/oblique motion, prescribed-slab/computed-
wedge subduction and finite-source magmatism. They separate physical owners,
material/enthalpy accounts, required bridges and analytic/published acceptance.
[Step 2 implementation](../tectonics/docs/W08_SHORTENING.md) now supplies exact
distributed finite shortening, conservative cohort/enthalpy projection and dry
fixed-base load/support, with 21 focused checks passing. Three matched complete
outputs take 1.0531178 s with repeated preparation versus 0.5586197 s with reuse:
46.96% less time, including setup and verification. The bounded full-source digest
inventory replaces retained source text; execution identity v4 refuses old
checkpoints. [Final evidence](../tectonics/evidence/w08-shortening-r2.json) records
the source-bound numerical reference and timing. Supplied underthrust scenarios
retain their separate structural closure requirement.
[Step 3](../tectonics/docs/W08_TRANSFORM.md) now connects exact full-vector affine
motion, compatible distributed bend/stepover networks and named straight-fault
slip to conserved material/enthalpy and explicit region/exterior exchange. All 66
new focused checks have passing evidence; nine shared identity checks also pass.
The bounded smooth-bend reference meets its frozen finest-grid 0.02 Jacobian RMS
gate (0.01804426). Matched three-output preparation reuse saves 0.7768963 s / 51.59%;
identical-result reuse saves 0.9936889 s / 64.26%, with setup and source checks
included. See [source-bound evidence](../tectonics/evidence/w08-transform.json).
[Step 4](../tectonics/docs/W08_SUBDUCTION.md) now implements prescribed-slab/computed-
wedge mechanics, direct steady heat, conservative thermal velocity transfer and
finite material retirement. Its original-source and numerical comparison gates
remain explicit: Step4 is IN_PROGRESS, not retrospectively accepted by its unit
checks. Plotting remains deferred.

## Product and scale definition (revision 2 review draft)

[ATLAS-PRODUCT-SCALE-1, revision 2](PRODUCT_AND_SCALE_CONTRACT.md) incorporates the
owner's clarification: Atlas is intended to become **world-agnostic**; the Diadem
is its primary development case, not its required setting. Eventual scope includes
potential **whole-planet generation**. These are product directions, not capabilities
established by the public code.

Resolution is **configurable by coverage, purpose, process and finite budget**,
including **1 m or finer where feasible**. Larger areas generally favour a coarser
base under a fixed budget, with finer regions where needed. The existing 100 m
Diadem authority and 10 m local workflows are implementation examples, not universal
or permanent delivery targets. Core/world/run-profile separation, multiresolution
behaviour and planetary geometry require explicit future implementation and tests.

The Diadem interface remains 18,600 × 22,000 cells. The current native common-domain
limit remains 256 cells, with 256 accepted intervals including predecessors; the
climate transect limit remains 32 cells. Documentation has not enlarged them.
The [planning record](contracts/product-scale-v1.json) records revision 2 intentions,
observations and unresolved run profiles separately; it is not runtime configuration.

This remains recommendation 1 only: no production bridge, model implementation,
world run, benchmark, numerical change, runtime installation or Windows integration
was performed. Actual resolutions, masks/regions, physical horizons and budgets
remain to be selected for the next scoped case.

## Latest route

The wider generator programme has implementations through [generator upgrade R31](../engineering/work/generator_upgrade_r31/). The latest bounded native experiment is [native terrain R5](../engineering/work/native_terrain_r5/), building on R1–R4, [runtime R12](../engineering/work/generator_runtime_r12/) and other generator/model predecessors. It is only one part of the generator.

Recent changes:

- Native R2 addressed numerical representation and continuation limits in a saved synthetic example.
- R3 reduced repeated state copying and expanded history construction, retaining immutable compressed records.
- R4 selected interval prediction and versioned history commitments. Mapping reuse did not provide a reliable gain. Parallel trial workers were not selected because short-workload startup overhead outweighed the useful warm-worker result. Active state and accepted receipts matched in the bounded comparison; requested/rejected/refinement history changed, so full historical-body or long-run trajectory identity must not be inferred.
- R5 shares identical immutable Zstandard history frames across independent run controls. In three matched already-loaded branch-creation comparisons, time fell from 3.696854 to 0.680990 seconds and added disk from 7,996,951 to 879,786 bytes. Ordinary interval timing was essentially unchanged (observed 0.60% slower including load/proposal). This is a branch-creation/storage improvement, not another solver speedup or a whole-world timing forecast.
- A separately authorised local cleanup consolidated 828 old closed-history copies with exact recovery retained. It did not change physics or authorise further simulation. Do not repeat it from this source export.

Existing local R5 tests established bounded storage/session behaviour and a relocated portable checkpoint restart in the original environment. They do not prove that this public export runs in a different environment. No new generator tests or simulations were run merely to prepare this repository.

## Boundaries

- Physical mountain realism remains unaccepted. Earlier inconclusive or failed morphology/Landlab experiments are not positive validation of the native route.
- No full Diadem or whole-year run is authorised by this handover. The existing 256 accepted-step ceiling, physical assumptions, numerical policy and acceptance tolerances have not been relaxed.
- Successive speed measurements have different scopes and must not be added together.
- Shared history stores are dependencies, not disposable caches. The local controls, stores, private authority inputs and provenance records are deliberately absent here. A control copied without its source/store/runtime dependencies is not a restartable delivery.
- Local user-directory names and a private project identifier are sanitised in the public copy. Historical execution hashes therefore cannot automatically authenticate these bytes. Never silently repin historical runs.

## Practical next work

For a new authorised coding request, inspect the relevant current module and its retained imports, make a separate change, then run only the relevant tests in a compatible environment. Record untested assumptions plainly. A portability change must preserve source-binding, integrity and numerical checks rather than bypassing them.

This repository is a public point-in-time source handover. It does not mount or automatically synchronise the original Windows workspace. A GitHub change is not a local integration until it has actually been reviewed and applied there.

## Independent public development (separate from historical execution)

The [public development package](INDEPENDENT_DEVELOPMENT.md) provides an offline
editable source environment, new public execution identities, a synthetic integer
fixture and focused tests of the actual R12 runtime and selected native numerical
components. See its [obtained evidence](INDEPENDENT_DEVELOPMENT_EVIDENCE.md).
This does not supply the excluded recursive scientific seal, native R5 codec,
Windows runtime, private inputs or saved checkpoints. All original physical,
numerical and source-identity boundaries above remain in force.
