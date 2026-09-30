# I02.1: the common physical state around the finite-strain column

**30 September 2026. WORKING NON-CANON. I02.1 and I02.2 (the package-owned solver
and its continuation, including the prepared-runner ownership correction, section 9)
are reviewed and accepted for their bounded scope. I02.3–I02.8 are now integrated
locally, described in [I02 workflow](I02_WORKFLOW.md); the current-state record
owns final verification and platform coverage.**
This is the first of the eight I02 steps in the [integration plan](INTEGRATION_PLAN.md#i02--common-state-exchange-transactions-and-accepted-time-controller).
It defines the shared state envelope and the initial-state contract of the first
physical route. It does not complete I02, run or continue physics, or establish a
connected world. [Current state](../../docs/CURRENT_STATE.md) owns progress.

## 1. What this step provides

[`integration_state.py`](../src/atlas_tectonics/integration_state.py) holds one
immutable, bounded, versioned **common-state envelope** for the declared initial
state of the first I02 route: the layered constant-drive
[finite-strain column](I01_FINITE_STRAIN.md). In that closed strip, temperature
changes strength and motion, deformation changes geometry and heating, and each
interval inherits those changes. The envelope records everything that later
continuation needs, without serialising prepared operators, functions or pickle.

The envelope itself performs no physics. Since I02.2b its `Continuation` connects it
to the package-owned core, which advances the column and issues successor envelopes
(section 9). Transfers, the store transaction, checkpoints, the accepted clock and
the command workflow are integrated through I02.3–I02.8 in
[I02 workflow](I02_WORKFLOW.md), which also adds the envelope's engine-owned
`restore`; remapping and a user interface belong to later stages. Nothing here
creates material or confers physical admission.

## 2. What an accepted state records

The [I01 contract](I01_PHYSICAL_CONTRACT.md#2-product-and-feedback-ownership) and
[section 4 of the plan](INTEGRATION_PLAN.md#4-architecture-one-evolving-physical-state)
set the required content. Each quantity has exactly one owner and one producer in
the module's `CATALOGUE`; `CommonState.declaration()` reports it with units, support,
status and whether this instance carries it.

| Group | Recorded content | Owner |
| --- | --- | --- |
| Identity | World and scenario labels, named epoch, caller-declared source and runtime SHA-256, SI unit declaration | `StateIdentity` |
| Time and schedule | History start (SI seconds in the epoch), elapsed time since the reference, accepted steps; fixed global schedule `step_s = duration_s/steps`; cumulative step ceiling of at most 256 | Global schedule |
| Lineage | `parent_state_id` and `initial_state_id` (both empty for an initial state), `state_id` | Envelope |
| Frame and support | Frame label, strip geometry convention, vertical reference, Gauss control volumes (layer, depth, width) and their `support_id` | Mechanical reference |
| Mechanical reference | Pinned preparation inputs and fingerprint, layer thicknesses, `h0`, overburden `P0`, mechanical density where the closure defines it, pore pressure exactly zero; `w0` is the drive width | Column preparation |
| Thermal reference | Pinned thermal inputs and fingerprint, steady geotherm, capacity `C0`, radiogenic source, thermal density, boundary temperatures, departure basis | Thermal preparation |
| Closure, parameters, policy | The six representation texts, production solver configuration, weakening law, drive, heat fractions, the numerical policy verbatim, stretch/temperature window and 5 K step guard | `ColumnSettings` |
| Column history | Stretch, thermal clock, displacement, log-strain path and quadrature, initial and current departure `theta`, initial and current raw plastic history `kappa`, 14 accounts, counters, extrema, per-point yield counts | `ColumnState` |
| Native payloads | W02 [`MaterialState`](../src/atlas_tectonics/materials.py) cohorts (required); W08 [`W08Inventory`](../src/atlas_tectonics/w08_inventory.py) exterior stocks (optional) | Their native owners |
| Unknown here | Elastic stress, melt fraction, absolute elevation, global position, lateral structure, external loads | Later stages named in the catalogue |

Scientific identity covers only these contents. Wall-clock time, host names and
resource peaks are operational records and never enter an identity.

## 3. Handing over the real column

Package code never imports a campaign tool or edits `sys.path`. The caller hands
over the retained preparation's own values; the focused test builds them from
`tools/check_i01_finite_strain.py` fixtures.

`ColumnReference(mechanical=..., thermal=...)` takes two mappings with exactly these
keys:

- `mechanical`: `key` (the preparation inputs `(layers, order, closure, gravity)`),
  `fingerprint`, `layer`, `depth_m`, `weight`, `reference_pa`, `density` (`None` for a
  supplied-pressure column) and `thickness_m`.
- `thermal`: `provider` (must be `COLUMN_THERMAL_BASIS`), `inputs` (`thicknesses`, `props`,
  `densities`, `boundaries`, `reference_temperature`), `fingerprint`,
  `mechanical_fingerprint`, `layer`, `depth_m`, `volume_m`, `reference_density_kg_m3`,
  `capacity`, `radiogenic`, `steady_k`, `boundary_temperature` and `thickness_m`.

`ColumnSettings(representation, law, drive, heat_fractions, policy, schedule)` takes
the case representation (six texts plus the two windows and the step guard), the
weakening-law and drive fields, the two heat fractions, the policy and
`{duration_s, steps}`.

```python
state = initial_state(
    identity=StateIdentity(world_id=..., scenario_id=..., epoch_id=..., source_id=...,
                           runtime_id=..., unit_system=UNIT_SYSTEM),
    start_time_s=..., frame_id=..., reference=reference, settings=settings,
    theta0_k=theta0, kappa0=kappa0, materials=cohorts, layer_cohorts=cohort_ids_in_layer_order,
    reservoirs=None, reservoir_basis=None)
```

Every argument except `budget` is required; `reservoirs=None` explicitly declares
that the closed strip has no attached finite stocks. Omitted or `None` required
data refuse. Zero is never supplied for a missing temperature or history.

## 4. What is checked and what is carried as declared

Checked exactly before acceptance:

- The pinned inputs reproduce the retained mechanical preparation fingerprint and
  the thermal-support fingerprint, which also binds the support bytes. A stale,
  stretched or foreign column cannot pose as the `lam = 1` reference.
- The support follows the retained supplied-support rules: whole layers of the pinned
  quadrature order, strictly increasing depths, positive widths summing to each
  layer thickness within the existing `8 (n + 3) u` round-off allowance, and points
  inside their layers. The thermal support must equal the mechanical quadrature.
- Mechanical density equals the pinned layer densities; the thermal inventory
  density equals it for lithostatic columns. Capacity equals `rho cp q0` and the
  radiogenic source equals `q0 A`, both by the preparation's own expressions, so
  scaled units or another support refuse. Thicknesses, boundary temperatures and
  the column total (the kernel's sequential sum) agree. Lithostatic overburden
  cannot decrease with depth. Supplied pore pressure is exactly zero.
- Only the retained representation, production solver configuration, frozen
  stretch/temperature ceilings, 5 K guard and a step ceiling of at most 256 are
  admitted; steps must fit that ceiling and duration must not exceed the retained
  `1e14 s` finite-strain horizon. Weakening, drive and heat-fraction values
  keep their retained domains. Initial temperatures `T_steady + theta0` lie inside
  the declared window.
- Material cohorts share the frame, epoch and history-start time, fill one strip
  cell of the reference width, and correspond one-to-one with the layers by
  material name and reference thickness. Attached reservoirs share the state time
  and their declared enthalpy basis.

Carried as declared and bound into the identity: the prepared overburden values,
the steady geotherm and the source/runtime digests. A later rebuild must reproduce
the first two bitwise; the focused test demonstrates that through the retained
preparation. Constitutive and thermal admission (law certification, the drag-only
window guarantee and the evolve kernel's refusals) stays with the producer. Declared
support is not empirical truth.

## 5. Ownership, units and bases

Units follow the spelling of the existing export ports in
[`workflow_ports.py`](../src/atlas_tectonics/workflow_ports.py). Strip extensive
quantities are per metre of strike: accounts in J/m, reference mass in kg/m and
volume in m². W08 stocks are whole kilograms and joules, so they cannot be added to
strip quantities without a declared strike length.

The column's thermal basis is a sensible-heat departure from the fixed steady
reference with constant per-material density and heat capacity. Its departure
enthalpy `w0 sum(C0 theta)` is signed: a cooler-than-reference column has negative
content. This basis is not interchangeable with the common-Gibbs provider or a W08
stock convention. The envelope never sums the two, and refuses a reservoir that
claims the column basis or a thermal support that names another provider.

Native material and reservoirs have disjoint ownership. Every native cohort owns
exactly one layer; a cohort cannot own two layers, and unowned or missing material
refuses. Reservoir rows may not reuse a cohort identity or carry W08 `crust` or
`mantle` kinds, which would be a second copy of lithospheric material. Receiver
provenance stays in the native payloads.

Reference mass `w0 sum(rho q0)` is invariant under affine stretch and the volume
`w0 h0` is conserved. Current geometry is derived from the original reference as
`w0 lam`, `h0/lam` and `z0/lam`; it is never stored as a new reference. A
supplied-pressure column has no mechanical density, so its reference mass is
unknown (`None`), not zero.

## 6. The initial state

The only state issued in I02.1 is the reference state: `lam = 1`, zero elapsed time
and zero accepted steps. Nothing has been booked since the reference, so the 14
cumulative accounts and the counters are exactly zero; running extrema are undefined
(`None`) because no stage has been observed. The initial departure `theta0` and
inherited history `kappa0` are explicit inputs, including nonzero and negative
departures where the declared window permits them. They stay separate from the
current fields that a continuation advances (section 9), and every successor shares
them unchanged. The history start is independent of elapsed time. The native cohort
formation times remain unknown where the scenario gives none.

## 7. Immutability, identity and resources

Proven immutable native arrays are borrowed through the existing
[`snapshot`](../src/atlas_tectonics/_validation.py) rule; every other array is
detached once, so later caller edits cannot change the envelope. Nested metadata is
held as canonical JSON bytes and returned only as fresh copies; array accessors
return fresh descriptors directly over immutable bytes, so editing a returned
array's shape/dtype or its `.base` descriptor cannot reach a retained descriptor.
The payload is still shared without copying. Envelopes are not pickled, `dataclasses.replace` cannot
build an unvalidated copy, and copying returns the same immutable object. Nonfinite,
Boolean, text, masked and wrongly shaped values refuse; signed quantities that
native code allows are preserved.

Identities follow the native pattern: SHA-256 of canonical JSON plus each array's
descriptor and exact binary64 bytes, including the sign of zero. `reference_id`,
`settings_id` (with separate closure, parameter and policy identities),
`column_state_id` and the native payload identities feed `state_id`. Successor states
can therefore share an unchanged reference and settings without rehashing them.

Construction reserves only transient capture workspace in the caller's
[`WorkBudget`](../src/atlas_tectonics/resources.py); this is not an RSS limit, and
retained payloads remain the caller's to account. Metadata is bounded at 512 KiB.
There is no fixed element limit beyond the retained route's own 64-layer,
128-point-order limit.

Adding this module changes the package execution identity: every package source file
participates in `ExecutionContext` source membership, so contexts created before the
addition refuse and new contexts receive a new identity. The loaded-code identity
module list and all existing receipts are unchanged; nothing was repinned. The
three registered whole-package receipts are now historical for the changed source
membership, not failures of their unchanged physical methods. Since repair batch R1
(30 September 2026) the loaded-code set is derived from the package source membership
rather than a fixed list, so new modules are bound automatically; this changed every
package execution identity without repinning any receipt.

## 8. Finite admission is not conferred

`CommonState.admission` is always `NOT_CONFERRED`, for successors as well as the
root. The [finite-admission tool](I01_FINITE_ADMISSION.md) issues states only from its
own retained evolution and, through I02.5, from an accepted ledger
commit that the package ledger re-reads and restores itself
([I02 workflow](I02_WORKFLOW.md#5-saving-reopening-and-continuing)). Passing the
envelope, or a `State` rebuilt from its values and preparation fingerprint, to that
tool is refused. Holding a fingerprint authorises nothing.

## 9. The package-owned solver (I02.2a) and its continuation (I02.2b)

**I02.2a: extraction reviewed.** The coupled
calculation this envelope describes now has one implementation inside the package.
It was moved from the six I01 tools without changing an equation, arithmetic order,
tolerance, type, refusal or deadline check. In dependency order:

| Package module | Owns |
| --- | --- |
| [`_integration_column`](../src/atlas_tectonics/_integration_column.py) | Creep laws, regularised friction, the scalar local solve and the prepared depth quadrature |
| [`_integration_weakening`](../src/atlas_tectonics/_integration_weakening.py) | The fingerprinted column preparation, the weakening law on raw plastic history and the vectorised stress/force response |
| [`_integration_heat`](../src/atlas_tectonics/_integration_heat.py) | The thermal support on the Gauss control volumes, exact modal (ETD2) conduction, the Arrhenius rebuild and once-only heat deposition |
| [`_integration_motion`](../src/atlas_tectonics/_integration_motion.py) | The drive and the force balance against disjoint drag and column resistance |
| [`_integration_thermomechanical`](../src/atlas_tectonics/_integration_thermomechanical.py) | One force-balanced stage with its heat taken from that same solved state |
| [`integration_evolution`](../src/atlas_tectonics/integration_evolution.py) | The finite-strain core and its `evolve` wrapper (split in I02.2b, below): current geometry from the original reference, the thermal clock and its single reused eigensystem, stage weights, refusals and the endpoint re-solved before commit |

The package modules import only the standard library, NumPy, SciPy and each other:
no campaign tool, `sys.path` edit, dynamic loading or copied code. The I01 tools
re-export these same objects, so a class checked with `type(x) is ...` in one tool is
the class used by every other tool and by the package. They keep their case loading,
campaigns, reports, CLI, timings, independent oracles and analytical controls, and
the tool-owned small-strain evolutions of the weakening, motion, heat and
thermomechanical controls. `evolve` keeps its signature and uninterrupted algorithm;
its default path still reuses one eigensystem and warm starts, while the rebuilt
operator and cold roots remain opt-in comparators.

The tools' source bindings now also bind the package files they execute, located
where they were actually imported from. Existing receipts are not rewritten: their
recorded tool bytes no longer match, so their drift checks now report them as stale
rather than current. Adding six package modules again changes the package source
membership and execution identity. New evidence, if needed, follows review.

Focused checks in [`test_i02_evolution.py`](../tests/test_i02_evolution.py) cover a
package-only process that prepares and evolves the real layered column with no tool
importable, exact object identity between tools and package, the absence of a second
implementation in the tools, strict type checks, extension, compression and rest,
reference and input immutability, complete signed accounts, operator reuse and
independent homogeneous oracles. The existing finite-strain checks now patch the
package module that actually runs. Review also completed package-owner bindings
in the three downstream admission/breakup tools. All 13 extraction checks pass
in 1.388 s; 206 methods pass across the eleven focused suites. Two old
source-freshness methods correctly fail because their receipts predate the move.
The nine affected campaign records are historical, not silently rebound. The
dependency-ordered campaign refresh remains due once I02.2b stabilises, before
current campaign acceptance. This review establishes ownership/execution parity,
not completion of the continuable workflow or a new speedup.

**I02.2b: one continuable core, connected to this envelope (implemented; ownership
correction awaiting review).** The same implementation is now split around one
immutable prepared `Runner` in
[`integration_evolution`](../src/atlas_tectonics/integration_evolution.py), and
`Continuation` in [`integration_state`](../src/atlas_tectonics/integration_state.py)
connects it to this envelope. In execution order:

1. **Prepare once.** `Continuation(state)` verifies the state (below), rebuilds the
   mechanical preparation from the pinned preparation inputs and the thermal support
   from the pinned thermal inputs, and compares every carried reference byte with the
   rebuild: support layers, depths and widths, overburden, mechanical and thermal
   density, heat capacity, radiogenic source, steady geotherm, thicknesses and
   boundary temperatures, as well as both fingerprints. Any difference refuses, so a
   changed runtime or an edited reference cannot continue a history. `prepare_run`
   then builds the runner with the frozen creep terms and the one reference
   eigensystem, in the production configuration the settings declare, and keeps
   private copies of the checked preparation, support and eigensystem (see
   "Prepared-runner ownership" below). Operators are never serialised, and no later
   piece rebuilds them.
2. **Begin a root.** For a declared initial state, `begin` balances the reference
   stage once and notes it once. Nothing is accepted yet.
3. **Advance whole scheduled steps.** `Continuation.advance(state, steps)` takes an
   integer from 1 to `state.remaining_steps`. The declared schedule's
   `dt = duration_s/steps` is used unchanged: a piece never chooses a new duration or
   budget. Booleans, non-integers, zero, negative and overrunning requests refuse, and
   a completed history cannot be extended by a new continuation. The 256-step
   ceiling, the `1e14 s` horizon, the declared windows and the 5 K guard remain those
   of the settings. `integration_evolution.advance` is the one step loop, moved
   unchanged from `evolve`. Each trial works on local candidate values, and only
   accepted steps reach the returned prefix. A stretch-window, temperature-window,
   temperature-step, constitutive or deadline refusal, including expiry after the final
   endpoint solve, returns the exact accepted prefix with the retained status and
   reason; when nothing was accepted, that is the input state itself. An exception
   leaves the input state and the continuation's warm data unchanged.
4. **Issue the successor.** A successor `CommonState` names its parent and root and
   shares the parent's reference, settings, native payloads and original
   `theta0`/`kappa0` bytes. It keeps the root's world, scenario, epoch, frame, history
   start and declared source and runtime identities; a continuation refuses states
   whose declarations differ, and rebinding after a source or runtime change belongs
   to I02.5. Its new column record carries stretch, thermal clock,
   displacement, log-strain path and quadrature, the global accepted-step index with
   elapsed time `accepted*step_s`, the 14 accounts, counters, extrema, per-point yield
   counts and the reference velocity and force. Identities bind these exactly, as for
   the root. `Advance.status` is `PIECE_COMPLETE` or `HISTORY_COMPLETE` for a
   completed request: finishing a piece is not finishing the history.
5. **Report.** `Continuation.report(state)` returns the retained `evolve` result of an
   accepted state through `finish`. Derived account identities are built on a copy and
   never carried; returned arrays and the final stage are copies.

`evolve` keeps its signature, defaults and output as a wrapper over exactly
`prepare_run`, `begin`, one `advance` of every step and `finish`. Its rebuilt-operator,
cold-root, conduction-off and geometry-off comparators remain `evolve` options; a
continuation uses only the production configuration. `resume` rebuilds a carried
prefix for a state that is not a continuation's own warm head.

**Diagnostic continuity decision.** Counters, extrema and yield counts cover booked
stages only: the reference balance once, then a predictor and an endpoint per accepted
step. A continuation keeps the balanced endpoint stage of its latest accepted state as
warm data, bound to that prefix and runner, and uses it only for that exact state
object. That warm path reproduces the uninterrupted run bitwise, including
evaluation and iteration counts. Any other state (a branch, or a state handed to a new
continuation) has its endpoint re-solved cold. The re-solve is operational work,
reported in `Advance.reconstruction_evaluations` and `reconstruction_iterations`,
and is never noted, booked or counted twice. Later warm guesses then start from that
cold solution, so subsequent evaluation and iteration counts can differ from the
uninterrupted run. Physical values must agree within the solver tolerances; the
prepared check uses the retained `1e-8` warm/cold parity allowance.

**Native payload decision.** The W02 cohorts and any W08 stocks are carried unchanged
with their own date, the history start, and the record labels their roles. The
material inventory is the unchanged reference inventory (partial thickness `h_k` at
`lam = 1`); the exterior stocks, to which the closed strip transfers nothing, are not
re-dated. Current geometry (`w0 lam`, `h0/lam`, `h_k/lam`, `z0/lam`) and temperature
are always derived from the original reference and the accepted stretch at the
state's time; nothing is written back. Re-dating unchanged stocks or committing a
transfer needs their native owners and belongs to I02.3.

**Integrity.** Every call checks the exact types, recomputes the state, column,
reference and settings identities from their records and arrays, and cross-checks
labels, joins, clock and lineage. A look-alike, a swapped part or an edit behind an
identity refuses, as does a state of another root, reference, settings or payload.
Introspection that rewrites a whole envelope and all its identities consistently is
not defended. Nothing confers finite admission.

**Prepared-runner ownership (review correction, awaiting review).** Review found that
the runner kept the preparation, thermal support and eigensystem it was given and
returned those same objects through `Continuation.runner`. Frozen dataclasses and
read-only arrays do not stop a caller changing an array's shape or dtype in place:
reshaping the public weight array made the next piece fail with a `TypeError`, and
reshaping the public eigenvalues produced a false `REFUSED_CONSTITUTIVE`. Accepted
states did not change, but the reusable solver did. `prepare_run` now captures the
checked objects once, straight after the existing checks, as private copies whose
arrays are new descriptors over the same immutable bytes. No payload is copied,
rehashed or factorised; only an array without compact immutable backing, which the
package's own preparations never produce, is copied once. Every piece reads only
these private copies. `Runner.base`, `thermal`, `modes`, `coeffs` and `rebuild` now
return a fresh copy of the same type on every access, so `evolve` and the tools still
accept them; inspection costs only new array descriptors and, for `rebuild`, a small
nested copy. Editing such a copy
(its shape, dtype, `.base` chain or nested rebuild data), or editing the objects
originally passed to `prepare_run` and `begin`, cannot reach a later piece. The
corrupting paths are removed rather than detected, so no new refusal was needed.
Because `runner.modes is runner.modes` is now false, the operator-reuse check instead
requires every inspection copy to share the owned eigensystem's memory. Private
fields, `object.__setattr__`, patched package functions and other deliberate
introspection are not defended.

**Consolidation.** The carrier now takes the stretch and temperature ceilings, the 5 K
guard ceiling, account names, representation texts and limits from
`integration_evolution`; closure names and the preparation fingerprint from
`_integration_weakening`; the 64-layer and 128-point limits from `_integration_column`;
and the width round-off rule from `_integration_heat`. The finite-strain tool
re-exports the same representation. The dependency runs from carrier to core only,
so `evolve` and the tools execute exactly the package modules they did before.
Remaining duplicates need files outside this assignment: the thermal-support
fingerprint is inline in `_integration_heat.prepare_thermal` (there is no owner
function to call), the 256-step ceiling is a literal in
`_integration_heat.policy_limits`, and `tools/check_i01_finite_admission.py` keeps
its own `1e14 s` horizon.

```python
from atlas_tectonics import integration_state as common

run = common.Continuation(state)         # rebuild once; verify every carried reference byte
first = run.advance(state, 3)            # three whole steps of the fixed schedule
rest = run.advance(first.state, first.state.remaining_steps)
result = run.report(rest.state)          # the retained evolve result of that accepted state
```

**Evidence limits.** These edits change `integration_evolution`, `integration_state` and
the finite-strain tool, and therefore the whole-package execution identity again. The
nine historical campaign records stay unrebound; the dependency-ordered evidence
refresh is still due after review. The ownership correction changes the bytes of
`integration_evolution` and `integration_state` again; nothing is rebound. No
campaign, timing or speedup is claimed.

## 10. Checks and remaining work

Focused checks, [`test_i02_common_state.py`](../tests/test_i02_common_state.py), use
order-8 layered and order-4 homogeneous fixtures and run no evolution:

```text
python -B -m unittest discover -s tectonics/tests -p test_i02_common_state.py -v
```

They check the real initial column's two references, units, support, nonzero thermal
and weakening history and native provenance; determinism and content binding;
retained negative enthalpy; refusals for wrong time, epoch, frame, units, support,
reference, provider and duplicated ownership; unknown optional fields; required-input
refusal; caller mutation and alias isolation; resource reservation; a bitwise rebuild
of the references through the retained preparation; and refused finite admission.
A drift guard compares the carried route constants with the retained tool; since
I02.2b it also asserts that they are the package owners' own objects, that the root's
identities recompute from its records and arrays, and that the root carries its
native payload date and role. Passing these checks establishes the carrier contract
only.

Codex review reproduced and corrected a public `.base` descriptor-alias bug and
added the retained duration ceiling. The corrected **16 tests pass in 0.083 s**
on the existing Windows test environment, with no skips. The mutation regression
covers all public reference/history arrays and confirms their immutable payload
is still shared. Static coding-safety and public-path checks also pass; the
coding-safety suite retains its existing Windows symlink-privilege skip. No
physical campaign or performance benchmark was needed for this carrier review.

The I02.2a extraction checks of section 9 passed at review. The same file now also
holds the I02.2b continuation checks. Before the ownership correction, review ran
them: 23 continuation tests pass in 2.503 s and 16 shared-state tests in 0.099 s, and
the affected finite-strain, finite-admission and breakup numerical checks passed,
with the then-stale receipt check still failing. That historical failure is now
resolved by fresh successor captures. The corrected ownership and continuation
checks passed within the final 30 September Git-normalised I01/I02 suite (758 tests):

```text
python -B -m unittest discover -s tectonics/tests -p test_i02_evolution.py -v
```

They use the same tiny cases: the order-8 layered column over eight steps of
`dt = 6.25e12 s` and the order-4 homogeneous layer. Pieces of 3 + 5 and 1 + 2 + 4 + 1
steps must reproduce one uninterrupted `evolve` bitwise inside one continuation. This
covers extension, compression and rest, a signed initial departure and inherited
history, temperature, history, geometry, clock, displacement, all 24 signed accounts,
conservation and every retained diagnostic. An independently prepared column must
agree at round-off. A cold rebuild in a new continuation must agree within the retained
`1e-8` parity while booking each stage once. A two-piece homogeneous continuation is
judged against the independent DOP853/Brent oracle, not only against the wrapper. The
retained original-algorithm checks remain. Instrumentation counts stage solves and
refuses any eigensystem, support or preparation rebuild, to show that pieces do not
rerun accepted steps. Other checks cover the whole-step schedule and its exhaustion,
exact prefixes after stretch-window and temperature-step refusals, expiry after the
final endpoint solve, immutable prior states and caller edits, look-alike, swapped,
edited and incompatible states, and rebuilt-reference mismatches of one overburden or
geotherm value. The package-only child process now also continues the route from a
common state. Receipt-freshness checks now pass against the renewed evidence;
they were not converted or skipped.

The ownership correction adds two checks and adapts one. Review's two reproductions
(reshaping the public weight array or eigenvalues), and shape, dtype and `.base`-chain
edits of every inspected preparation, support, eigensystem and creep-term array before
each piece, must leave both successor identities and the reported result bitwise equal
to an untouched session. In direct core use, the caller edits the preparation, support
and eigensystem it handed to `prepare_run`, the arrays it gave `begin`, the inspected
creep terms and, for the rebuilt-operator comparator, its original nested rebuild
mapping and a fresh inspection copy. The pieces must then match an unedited run
bitwise; the comparator, which factorises again at every step, must match at
round-off. The operator-reuse check now requires inspection copies to share the owned
eigensystem's memory rather than be the same object. Its refusal of any eigensystem,
support or preparation rebuild and its stage counts are unchanged.

The remaining I02 machinery is integrated: joint commits of state and finite
exchanges, one accepted clock, save/reopen/continue, the command workflow and
joined verification with measured overhead. The precision repair retains the
original constitutive tolerance and iteration ceiling; failed-step exceptions
also identify the last accepted checkpoint. Fresh finite-admission evidence is
captured. See [I02 workflow](I02_WORKFLOW.md) and the current-state record for
final acceptance; Linux execution remains a separate platform coverage gap.

## 11. Sources

Newly inspected for this contract: the repository's own finite-strain,
finite-admission, weakening, column, column-heat, thermomechanical and motion tools;
the `materials`, `mesh`, `regional`, `tectonic_history`, `timebase`, `_validation`,
`resources`, `reuse`, `storage`, `w08_inventory` and `workflow_ports` modules; and the
finite-strain, column-heat and weakening case records. `tectonic_history` provides
the dated-output and time conventions; the finite-strain route has no dated-history
payload in this step.

Reused I01 evidence: the physical basis and references recorded in the
[finite-strain](I01_FINITE_STRAIN.md) and [finite-admission](I01_FINITE_ADMISSION.md)
methods, which were not reread here. No new papers or external software were
consulted or run for this contract.

Inspected for I02.2a: the six moved tools (column, weakening, column-heat,
motion-coupling, thermomechanical-motion and finite-strain), their focused tests, the
retained finite-admission, column-admission and breakup-closure callers, and the
package `__init__`, `reuse` source inventory and this carrier. The move reuses the I01
methods and their recorded references unchanged; no paper or external software was
newly consulted or run.

Inspected for I02.2b: the package `integration_evolution`, `integration_state` and the
five `_integration_*` helper modules it calls; `_validation`, `materials` and
`timebase`; the finite-strain, thermomechanical-motion, column-heat, weakening and
finite-admission tools and the breakup-closure caller; the finite-strain and
column-heat case records; and the focused state, evolution and finite-strain tests.
The continuation reuses the I01 finite-strain and column-heat methods and their
recorded references unchanged. No paper or external software was newly consulted,
installed or run.

Inspected for the ownership correction: `integration_evolution` and
`integration_state`; the prepared types and helpers they hold (`PreparedColumn` and
`frozen` in `_integration_weakening`; `ThermalColumn`, `Propagator`, `valid_thermal`
and `same_support` in `_integration_heat`); the stage and motion owners; the
`_validation` immutable-view helpers; the finite-strain, thermomechanical-motion,
column-heat and weakening tool fixtures the checks use; and the focused evolution,
state and finite-strain tests. No paper, external documentation or software was
consulted, installed or run.
