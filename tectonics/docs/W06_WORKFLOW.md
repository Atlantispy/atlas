# W06 Step 5 — recoverable outputs and combined acceptance

22 September 2026. WORKING NON-CANON. Selected combined acceptance PASS.
The [frozen design](W06_SPREADING.md) and Steps [2](W06_BIRTH.md),
[3](W06_COOLING.md) and [4](W06_HISTORIES.md) retain their equations and tolerances.
This step adds an executable requested-output schedule and exact recovery, not
another physical law or an internal time-stepping approximation.

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
Numerical component evidence is documented in [Step 3](../evidence/w06-cooling.md)
and [Step 4](../evidence/w06-history.md); these are not rerun for reassurance.

The selected profile passed all 20 checks in 44.148 s with no skips, failures,
errors or source drift: eight combined workflow checks, nine shared identity
checks and three acceptance-profile checks. Five focused ocean codec checks also
have passing evidence. See the [acceptance record](../evidence/w06-workflow-acceptance.json)
and [measurement and implementation evidence](../evidence/w06-workflow.md).

The existing empirical challenge remains separate: independently reconstructed
isochrons/motion, corrected basement depths and heat-flow observations must be
bound before an observational claim. Do not reuse fitted observations as held-out
validation. This workflow does not reopen R4.4 or authorise a large world run.

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
