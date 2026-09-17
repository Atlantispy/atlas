# Atlas tectonics remake

**Branch: `remake`. WORKING NON-CANON. Mathematical verification, not accepted terrain.**
Vibe-coded with OpenAI ChatGPT/Codex under Michael's direction.

This isolated package follows the [tectonics plan](docs/TECTONICS_PLAN.md) and
[consolidated optimisation reference](docs/OPTIMISATION_REFERENCE.md). It imports
neither `engineering/work` nor `shared_generator`. Historical bindings, numerical
limits, checkpoints, `main` and the original Windows installation remain separate.

## W02 regional completion — remapping, moving boundaries and plate events

**17 September 2026.** W02's data/transport/event capabilities are now implemented
for the existing **1D regional, common-density, prescribed-kinematics model**.
This completes the outstanding regional remap/motion/ownership work; it is not
planetary topology, predictive tectonic forces or geological acceptance.

- `ColumnGrid1D` stores explicit nonuniform edges and an identified coordinate
  frame. `to_column_state` is an explicit inventory-preserving bridge from the
  previous uniform representation; older numerical APIs remain unchanged.
- `RemapPlan` uses a linear-size overlap sweep, reusable independently of material
  fields. `remap_materials` integrates limited linear reconstructions conservatively.
  Domain cropping or filling is refused; coarsening is not falsely reversible.
- `advect_ale` separates physical velocity **u** from mesh velocity **w** and evolves
  **thickness times cell width**, with relative flux **(u-w)H**. Compiled MC-MUSCL /
  SSP-RK2 remains normal. Closed moving faces require u=w, not u=0. Crossings,
  unsafe stages and known interior events are refused, never repaired by clipping.
- `PlateTopology1D` defines complete interval coverage, shared boundary sides and
  distinct plate/block/material IDs. Splits, merges, membership changes, boundary
  activation/deactivation and polarity changes retain parent and retired IDs.
- `advance_plate_state` moves aligned ownership/control-volume faces together;
  each shared flux reconciles neighbouring block/cohort inventories with opposite
  signs. Material birth/addition/removal reuses the existing prescribed transfers.
- `MaterialMarkers1D` supports an explicit material-following piecewise-affine map,
  accumulated log stretch and unchanged material identifiers. An arbitrary moving
  numerical mesh is not assumed to carry the material with it.
- Existing budgets, native executor, verified input/result identities, cache
  admission and Zstd/deduplicated snapshots are reused. State/marker snapshots
  restore without a chain of prior manifests. No new cache or scheduler is added.

Example with deliberately synthetic values, not Earth calibration:

```python
import numpy as np
from atlas_tectonics import (ColumnGrid1D, MaterialCohort, MaterialState,
    MaterialBoundary, remap_materials, advect_ale)

mesh = ColumnGrid1D(np.linspace(0, 1, 65), frame_id="synthetic-region")
state = MaterialState(mesh, (MaterialCohort("a", "rock", "origin", 0.),),
                      np.ones((1, 64)), time_s=0., epoch_id="example")
finer = ColumnGrid1D(np.linspace(0, 1, 129), frame_id="synthetic-region")
state = remap_materials(state, finer)
velocity = 0.1 * state.grid.edges_m
result = advect_ale(state, velocity, velocity, 0.5,
                    left=MaterialBoundary("closed"),
                    right=MaterialBoundary("closed"))
# The domain stretches by 5%; inventory is conserved and thickness falls.
# Save or consume result before reusing/releasing its owner's memory allowance.
```

**Verification:** all **488 tests (410 existing + 78 new)** passed without failures,
errors or skips in the tested Linux environment. Independent overlap/flux, geometric
conservation, refinement, event/history, cold restore, cache and concurrency cases
are in [the case](cases/w02_completion.json), [test evidence](evidence/w02-completion-tests.json)
and [measurements](evidence/w02-completion-measurements.json). Current reference and
native ALE outputs agree within unchanged tolerance, not necessarily bit-for-bit.

The plan and optimisation reference remain the two maintained authorities.
**Next physical work is W04 load construction**, with W03 thermal/compaction work
where needed, before a W05 coupled extension claim. Future 2D/spherical junctions,
variable-density mechanics and physical creation/recycling laws need their own
geometry and process extensions; no global or Windows sign-off is implied.

## W02 material cohorts and formation history (17 September 2026)

Accuracy remains the default: compiled MC-MUSCL/SSP-RK2, not automatic upwind
selection when a lower-order method is quicker. The new `advect_materials` API
transports each nonnegative cohort partial thickness under the same prescribed
face velocity. Total thickness is derived; material IDs and formation times are
metadata, not floating fields that can be interpolated or averaged away.

- `MaterialCohort`: stable material/origin/formation identity; unknown time is None.
- `MaterialState`: immutable compact cohort×cell thickness, forward-time epoch,
  parent identity and detached last-transition receipt. `ages_s()`,
  `total_thickness()` and `fractions()` derive views; empty fractions need the mask.
- `MaterialBoundary`: explicit incoming cohort composition and reservoir. Missing
  inflow refuses; closed-boundary velocities must be zero.
- `advect_materials`: per-cohort mean flux and before/after/in/out accounts,
  positive candidates, native default, independent reference, no renormalisation.
  `material_timestep_limit` advises a safe interval without changing the scheme.
- `register_cohorts`: explicit zero-inventory catalogue additions, no relabelling.
- `apply_material_event`: parent-bound birth/add/remove amounts at the exact current
  time. Birth sets the actual formation event; addition preserves prior age;
  removal keeps the cohort record even when its inventory becomes zero.
- `cached_material_transport` (in `reuse.py`) and `save_material_state` /
  `load_material_state` use the existing verified cache and deduplicated Zstd store.
- `KernelExecutor.material_transports` reuses bounded serial/thread/spawn execution
  for independent velocity scenarios, never adjacent tiles or sequential times.

Example (synthetic values, not geological calibration):

```python
import numpy as np
from atlas_tectonics import (RegionalGrid1D, MaterialCohort, MaterialState,
    MaterialBoundary, advect_materials)

cohorts = (MaterialCohort("old", "basalt", "source-A", -100.0),
           MaterialCohort("young", "basalt", "source-B", -10.0))
state = MaterialState(RegionalGrid1D(16, 16.0), cohorts,
    np.array([[1.0] * 16, [2.0] * 16]), time_s=0.0, epoch_id="synthetic-seconds")
inflow = MaterialBoundary("open", {"old": 1.0, "young": 2.0}, "west")
outflow = MaterialBoundary("open", None, "east")
result = advect_materials(state, np.ones(17), 0.2, left=inflow, right=outflow)
# result.state.ages_s() == (100.2, 10.2); histories were not blended.
```

Volume is m² per unit width under the common constant-density approximation,
not an unqualified mass ledger. Events prescribe transfers; they do not predict
magmatic productivity or subduction rates. No variable-density/momentum coupling,
continuous thermal/exhumation path, conservative remapping, moving grid or plate
ownership/split/merge logic is supplied. Those remain separately tested W02 work.
The last receipt and self-contained state are persisted; retaining every earlier
receipt is the caller's history policy, not an implicit growing in-memory list.

**Verification:** 410 tests passed (331 prior + 79 new), with no failures, errors
or skips on Linux. Smooth-cohort refinement approaches second-order convergence.
The native and reference measurements solve the same higher-order problem; their
measured partial-thickness outputs were identical. Windows is not verified.

[Scientific contract](docs/FOUNDATIONS.md#w02-cohorts),
[implementation and memory decisions](docs/OPTIMISATION_REFERENCE.md#w02-materials-delivery),
[test evidence](evidence/w02-material-tests.json) and
[bounded measurements](evidence/w02-material-measurements.json) describe the scope.
No old tests/tolerances or prior numerical kernels changed; no publication,
dependency installation, Windows integration or geological acceptance is implied.

## W02 regional transport increment (17 September 2026)

`advect_regional` now transports constant-density crustal thickness on a fixed
one-dimensional regional grid with **N cells and N+1 faces**. The existing periodic
API and its implementation remain unchanged. This is the open-boundary part of
W02, not completion of material cohorts, plate topology or crust production.

- Both ends explicitly select open or closed boundaries. Inflow requires supplied
  exterior face thickness; outflow uses the interior donor. Reversal requires new
  valid incoming data. A closed boundary rejects a nonzero supplied velocity.
- The normal backend is compiled Numba. The default numerical profile is limited
  **MUSCL/SSP-RK2**; `scheme="upwind"` selects the cheaper first-order scheme and
  `backend="reference"` independently checks either calculation. Numerical scheme
  selection is explicit: it is not a silent change to the old periodic method.
- The sufficient outgoing-fraction limits are 1/2 (MUSCL) and 1 (upwind), including
  both external faces. `transport_timestep_limit` advises a safe interval; the
  caller still chooses it. No clipping, automatic substeps or guessed inflow.
- Results include immutable thickness, interval-mean face flux, signed left/right
  exchange and nonnegative inflow/outflow totals. Inventory is **m² per unit width**,
  not kg. The RK2 boundary account uses its stage-averaged flux, not endpoint flux.
- `cached_regional_transport` and `KernelExecutor.regional_transports` reuse the
  existing cache, resource and worker infrastructure. Source, compiler, scheme,
  boundaries, interval and typed inputs participate in identity. Automatic cache
  admission still avoids persisting cheap steps. Whole independent cases can use
  explicit threads/spawn; auto currently retains serial compiled regional batches
  because outer threading was slower in the bounded end-to-end comparison.

```python
import numpy as np
from atlas_tectonics import (RegionalGrid1D, TransportBoundary,
                            advect_regional, transport_timestep_limit)

grid = RegionalGrid1D(cells=128, length_m=128.0)
left = TransportBoundary("open", exterior_thickness_m=2.0,
                         material_id="synthetic-external-reservoir")
right = TransportBoundary("open")
h = np.ones(grid.cells)                     # synthetic thickness, m
u = np.full(grid.cells + 1, 0.25)            # prescribed velocity, m/s
limit = transport_timestep_limit(u, grid, left=left, right=right)
step = advect_regional(h, u, grid, 0.5, left=left, right=right)
# step.balance_residual_m2 checks after - before - left_exchange - right_exchange.
```

All **331 checks passed** (280 prior + 51 new) on the tested Linux environment.
The new tests cover independent rational flux balances, inflow/outflow/reversal,
closed boundaries, variable-speed thinning, refinement and sharp fronts, compiled
versus independent reference, native/thread/spawn agreement, cancellation,
immutable restoration, cache identities, corruption and deduplicated payload reuse.
[Recorded tests](evidence/w02-regional-tests.json) and
[accuracy/cost measurements](evidence/w02-regional-measurements.json) retain their
actual scopes. Timings are noisy bounded synthetic comparisons, not world forecasts.
Windows, moving grids, geological validation and full evolving-world recovery remain
unverified. No source/dependency installation, publication or old-history migration
is part of this delivery. See [the existing scientific case notes](docs/FOUNDATIONS.md#w02-regional)
and [optimisation decisions](docs/OPTIMISATION_REFERENCE.md#w02-regional-delivery).

## Combined resource acceptance — item 12 (17 September 2026)

The normal optimised backends and storage profiles are retained. Executors, cache
wrappers and stores now share byte admission rather than each assuming its own
full allowance. `WorkBudget(max_bytes, parent=...)` supports related component
limits; a reservation charges shared ancestors once. Store cache/page-capacity
allowances stay reserved until close. Codec, decoding, staging, retained manifests
and pending results have separate lifetimes. Resource estimates remain distinct
from measured total process memory.

```python
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.execution import KernelExecutor
from atlas_tectonics.storage import ArrayStore, StoreLimits

# Example execution envelope, not an Earth parameter or owner hardware estimate.
run_budget = WorkBudget(256 * 1024**2)
# Pass budget=run_budget to the executor/store/standalone calls in the same run.
# Kernels keep pure numerical interfaces; no disk paths enter their equations.
```

Default-constructed stores and executors join the same process-local default
budget. An explicitly store-bound cache wrapper inherits that store's budget even
when automatic admission decides to recalculate. Distinct independently launched
programs are not collectively capped by this Python object. Caller-retained inputs,
outputs and operators must have explicit run reservations; shared immutable bytes
should be counted once by their owner, not once per view.

Pool capacity is coordinated across executors. Spawn workers have an explicit
96 MiB per-worker baseline allowance, held until shutdown in addition to their job
reservations; it is not a worker RSS limit. Cancelling a stream drains running calls
before release. Active store preparation cannot be closed underneath its writer.
Under shared memory pressure an executor refuses or drains pending work rather
than spinning because another component holds its remaining capacity.

**Obtained verification:** 280 tests passed (254 prior + 26 new), no failures, errors
or skips, on Linux/CPython 3.13.5. The combined drill additionally passed three
fresh-process profiles: serial/raw, automatic/balanced Zstd, and spawn/compact Zstd.
Each runs first use and five warm cycles combining native transport, cooling,
rotations, complete flexure domains, forced cache round trips, incremental branches
and an isolated backup. Output bytes agree between those profiles; original physical
fixtures and tolerances are unchanged. See the [acceptance record](evidence/combined-resource-acceptance.json)
and the [method/resource boundaries](docs/OPTIMISATION_REFERENCE.md#combined-acceptance).

```sh
# The usual complete regression checks (no telemetry dependency needed).
python -I -B tectonics/verify.py
# Complete regression + bounded process-tree resource/platform acceptance.
# psutil is the explicit acceptance extra; this command never installs anything.
python -I -B tectonics/verify.py --acceptance > item12-local.json
```

The latter command is also the local Windows acceptance route. **Windows remains
unverified until it actually passes there.** Missing dependencies, failed checks
and unsupported permissions/platform behaviour fail explicitly. No Windows pass,
power-loss guarantee or real-world tectonic validation is inferred from Linux or
from a spawn test. Item 1 remains skipped; no broad baseline/tuning programme ran.


## Current storage defaults (items 9–11)

The normal storage path now uses Zstd level 1 with byte shuffle and exact
categorical selection. No opt-in is needed; raw storage remains explicitly
selectable. Missing Blosc2 is an error, not a silent slower fallback. Blosc2 is
included in normal package requirements; no installer runs during computation.

`storage_profile("fast"|"balanced"|"compact")` supplies versioned starting profiles
with 16/64/256 KiB chunk suggestions. Existing stores keep their chunk size.
Packed 1/2/4/8-bit indices and run-length encoding preserve integer/Boolean data
exactly. Existing raw, uniform, palette8 and Zstd snapshots remain readable.

```python
# Snapshot IDs are supplied full scientific invocation identities (SHA-256).
from atlas_tectonics.storage import ArrayStore, StoreLimits, storage_profile
profile = storage_profile("balanced")
limits = StoreLimits(profile.chunk_bytes, max_array_bytes=16*1024**2,
                     max_store_bytes=64*1024**2, decoded_cache_bytes=1024**2)
with ArrayStore("existing-directory/fields.sqlite", limits, profile.compression) as store:
    store.put(parent_id, {"material": material, "temperature": temperature}, metadata)
    # Share the parent's unchanged data; replace only COMPLETE named chunks.
    store.put_incremental(child_id, parent_id,
                          {"temperature": {0: replacement_chunk}}, child_metadata)
```

Encoding and one-time round-trip checks now happen before the writer transaction,
using a bounded memory/disk spool. Dependency checks, batched insertion and final
publication remain transactional. Warm reads reuse verified chunks only inside a
stable database view, with invalidation for same/other-connection changes.

All **254 checks passed**. Repeated reads and unchanged snapshots were faster in
bounded measurements; first writes can be slower. Dictionaries and queued reads
did not justify automatic use in the tested cases. No codec tuning is a global
performance guarantee, and item 12 is not completed by this increment.

Read the [implementation, measurement and resource boundaries](docs/OPTIMISATION_REFERENCE.md#storage-profiles-delivery)
and [test record](evidence/storage-profiles-tests.json). Numerical kernels,
scientific tolerances and prior evidence remain unchanged. No publication,
Windows integration, physical simulation or dependency installation was performed.

## Current execution and reuse defaults (items 6–8)

The latest local delivery adds `KernelExecutor` for bounded independent cooling,
rotation and flexure batches, reusable `ExecutionContext`/`PreparedInput` identity
preparation, and automatic persistent-cache admission with same-request
coordination. The SciPy, Numba and matrix numerical defaults are unchanged.
Small jobs and matrix rotations remain serial when threading is not beneficial;
large eligible cooling/FFT batches use up to two threads under the automatic
profile. A persistent spawn-process path was tested and is not the default.

```python
from atlas_tectonics.execution import KernelExecutor
# requests yields (depth_array, age_array_or_scalar) pairs.
with KernelExecutor() as executor:
    for temperatures in executor.temperatures(requests, thermal_parameters):
        consume(temperatures)  # caller controls retained output memory
```

Cache wrappers now use automatic admission: they avoid caching cheap products and
learn measured compute/write/restore costs. `CachePolicy(mode="always")` explicitly
requests persistence; `mode="off"` disables store access. Supplying an immutable
`PreparedInput` lets repeated calls reuse its digest rather than rehash the payload.
Context reuse still compares exact current source bytes; it does not replace
verification with timestamps. Creator failure, wait cancellation, corruption and
source changes remain explicit errors. The existing transaction checks cancellation
and source state immediately before committing an admitted result.

See the [single maintained optimisation reference](docs/OPTIMISATION_REFERENCE.md#execution-reuse-delivery)
for policies, use boundaries and the measured decisions. The full verifier passed
**216 checks, with no failures/errors/skips**, including the original 169 and 47
new checks. [Test record](evidence/execution-reuse-tests.json) and
[measurements](evidence/execution-reuse-measurements.json) are scoped numerical and
execution evidence, not physical validation. `threadpoolctl>=3.6,<4` is now a normal
requirement. No dependencies were installed in this delivery; Windows/macOS and
other native builds were not run. No files have been pushed to origin.

## Implemented calculations

| Component | Capability | Boundary |
| --- | --- | --- |
| Rotations and boundary motion | Finite quaternions with reused immutable matrix application by default; ordered composition, inverse, bounded batches, streaming and scale-safe normalisation | No generated plates, force balance or geometric sidedness audit |
| Thickness transport | Conservative, positivity-preserving periodic 1D upwind update; compiled Numba update and exact positive-sum accounting by default; explicit NumPy/`math.fsum` reference | No open boundaries, material birth or subduction |
| Half-space cooling | Analytical temperature with explicit depth/age/parameters; SciPy array backend by default; explicit scalar reference | No evolving thermal PDE or calibrated material profile |
| Periodic flexure | Uniform 1D centred-difference operator solved with FFT; immutable setup reuse and scaled extreme-range arithmetic | Not continuous spectral k^4, variable rigidity, open edges or the cause of uplift |
| Parameter records | Immutable typed SI values and identities, without hidden Earth/Diadem defaults | No user customisation UI or new scientific calibration |

These do not complete W01-W04 or supply the W05 coupled extension experiment.
Physical validation and production integration remain outstanding.

## Memory and persistence increment (17 September 2026)

- Masked numerical inputs are refused before their missing-value information can
  be discarded. Shapes and projected array work are checked before bulk allocation.
- `WorkBudget` bounds estimated simultaneous kernel allocations, including shared
  reservations across threads. The default local envelope is 256 MiB; callers can
  supply a different explicit budget. This is **not a total process RSS cap**:
  caller-owned inputs, retained outputs and native allocator overhead remain separate.
- Transport reuses private donor/scratch arrays without mutating the input or
  changing the shared-face update. Accurate budget summations are retained.
- `backend="scipy"` is the default bulk error-function evaluation. It is numerically
  compared, not claimed bit-identical to `math.erf`. Missing dependencies cause an
  explicit error, never a silent backend substitution.
- Flexure restoration rebuilds its immutable coefficients from the typed definition.
  The method identity is versioned for range handling. Transport-result restoration
  also re-establishes immutable array backing; generic NumPy pickle is not a storage contract.
- `ArrayStore` provides typed, immutable array snapshots in a **local SQLite file**,
  with chunk deduplication, exact uniform encoding, optional integer palettes,
  optional Zstd via Blosc2, and byte/bit/no-shuffle choices. Compression uses one
  thread per call. Encoding records name codec/filter/version; raw storage is used
  when it is smaller. This is a declared encoding choice, not missing-dependency fallback.
- A repeated snapshot reuses unchanged chunks; one changed chunk stores one new
  payload. Each manifest references chunks directly, without long temporal delta
  chains. There is no automatic deletion or history migration.
- Reads validate stored and logical hashes, lengths, shape and dtype. Arrays restore
  with immutable byte backing. A bounded decoded-chunk LRU, direct chunk reads and
  streaming avoid requiring a complete decoded snapshot in RAM.
- SQLite transactions coordinate writers and publish complete snapshots. Conflicting
  results for one identity, corrupt records, missing chunks and exceeded limits are
  errors. `backup_to()` makes a consistent independent copy to a new file.
- `cached_temperature` and `cached_flexure` are optional wrappers outside the physics.
  Keys include typed input bytes, resolved parameters, selected backend, package
  source, loaded Python instructions and selected runtime binary identities.
  Profiles and input descriptors remain in the stored manifest, not just a filename.
  Source/instruction identity is rechecked before publication.

SHA-256 here detects corruption and supports identity; it is not a signature or a
security boundary against an attacker controlling the process or database. The
local directory must be owned/trusted. Binary runtime files are assumed immutable
for the lifetime of a process. This is not a recursively sealed historical runtime.

### Example: optional persistent cooling

Use an existing compatible environment; no command here installs dependencies.
The directory must already exist. Values below are **synthetic test values**, not
an Earth profile. The storage limits are example execution limits, not owner budgets.

```python
from pathlib import Path
import numpy as np
from atlas_tectonics.parameters import ThermalParameters
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore, StoreLimits, Compression
from atlas_tectonics.reuse import cached_temperature

limits = StoreLimits(chunk_bytes=32768, max_array_bytes=8*1024**2,
                     max_store_bytes=32*1024**2, decoded_cache_bytes=128*1024)
profile = ThermalParameters("synthetic", "example only", 300., 1300., 1.)
with ArrayStore(Path("existing-cache-directory") / "fields.sqlite", limits,
                Compression(codec="zstd", level=3, shuffle="byte")) as store:
    temperature = cached_temperature(np.linspace(0, 10, 4096), 1., profile,
        store=store, backend="scipy", budget=WorkBudget(32*1024**2))
```

The same call with `store=None` computes without persistent I/O. Imports use the
`tectonics/src` layout; use a declared environment or a separately prepared editable
installation. Normal requirements include NumPy, SciPy and `numba==0.65.1`.
Blosc2 remains the explicit `storage` extra. No package auto-installs.
Use `backend="reference"` explicitly for a diagnostic reference calculation.
Blosc2's level 0-9 scale is not the direct Zstd level scale.

### Memory/storage limits

Storage chunks are flat C-order pieces of a typed array, not physical boundaries.
Non-native byte order is losslessly normalised to little endian. Shapes, signed
zeros and categorical values are retained; masked/object/nonfinite arrays are
refused. A mask can be a separately identified boolean dataset only when its
scientific consumer actually supports that policy.

`max_array_bytes` limits individual writes and complete snapshot materialisation;
use `read_chunk()`/`iter_chunks()` for partial reads. `max_store_bytes` bounds
retained database pages/records; provision **up to another database-sized rollback
journal**, plus backups. SQLite cache and codec workspace are separate costs.
Input arrays must not be mutated during a store write. Returned data can outlive
an LRU entry, so caller-held arrays must still be counted in the application's RAM.

This is result persistence, not a demonstrated restart of an evolving world. No
Zstd dictionaries, global voxel engine, automatic GC, lossy history, GPU solver,
distributed mechanics or old R5 conversion is introduced.

## Optimised defaults (17 September 2026 follow-up)

Normal calls use the tested accelerated implementation: `advect_thickness` selects
Numba, while `half_space_temperature` and `cached_temperature` select SciPy.
The explicit reference routes remain for independent verification. Missing
dependencies cause an error, not silent fallback. The normal package requirements
include these backends; no setup command runs or installs packages automatically.
First-use compilation remains; compiler flags and numerical tolerances are unchanged.

The default-selection change passed 82 focused checks (53 explicit reference,
21 native and eight default/dependency checks) on Linux/Python 3.13.5.
The complete storage/reuse suite was not rerun for this follow-up; the cache-wrapper
default was checked structurally. Earlier full-suite records below remain historical.
No benchmark, simulation, Windows run or remote publication accompanied this change.

## Verification and evidence

```sh
# Existing NumPy environment: original 53 mathematical cases
python -I -B tectonics/verify.py --core
# Full suite, including compiled transport, with normal requirements and storage extra
python -I -B tectonics/verify.py
```

The verifier refuses local `.pyc` files: `-B` alone prevents writes, not reads.
It writes test details to stderr and a fresh versioned record to stdout. Missing
required dependencies block full verification rather than silently skipping it.

The 17 September delivery passed **93 tests (53 existing + 40 new), no failures,
errors or skips**, on Linux/CPython 3.13.5/NumPy 2.3.5, with SciPy 1.17.0,
Blosc2 4.3.3 and its Zstd 1.5.7. See
[evidence](https://github.com/Atlantispy/atlas/blob/0590774b9d59fa9e6c9cba8f5306a3e2b9f6bc40/tectonics/evidence/memory-storage-tests.json). Tests include independent numerical
references, masked/range regressions, allocation refusal, immutable restore,
fresh-process cache reuse, changed-input identities, Zstd/palette round trips,
concurrent writers, corruption/oversized decoding, rollback, and isolated backup.

[Bounded measurements](https://github.com/Atlantispy/atlas/blob/0590774b9d59fa9e6c9cba8f5306a3e2b9f6bc40/tectonics/evidence/memory-storage-measurements.json) compare synthetic
65,536-element kernels and a 1,179,648-byte three-field storage sample. They are not
world-scale forecasts or physical validation. Transport reduced tracked peak
allocations by about 22%, without a demonstrated timing improvement. The opt-in
cooling backend was faster in warmed comparisons; its results were not bit-identical.
Compression/deduplication gains depend on the field and must not be extrapolated.

Windows/macOS, Python 3.12, other dependency builds, power-loss behaviour on other
filesystems, large-world memory and geological realism were not verified here.
The [first delivery record](evidence/DELIVERY.md) remains historical and unchanged.

## Next development gate

Continue to W04 physical load construction using the regional W02 material, remap
and ownership state. Apply memory, ownership, cache and batching checks in each coding
increment, not a separate after-the-fact module audit. Keep the two consolidated
planning documents as the maintained references; do not create further roadmaps.


## Optimisations 4 and 5 — cooling and geometric batches

The optimised defaults remain enabled: SciPy cooling and compiled Numba transport.
Rotation now defaults to a reused immutable matrix (`backend="reference"` preserves
its earlier formula). Cooling computes age-dependent lengths before broadcasting,
then uses bounded sample batches. Flexure retains its verified FFT operator and
fast contiguous path, adding bounded independent-load grouping and lazy batch
consumption rather than an unproven backend replacement.

```python
# Ordinary calls use the selected optimisations without opt-in switches.
temperature = half_space_temperature(depth_m, age_s, parameters)
rotated = rotation.apply(points_m)
deflection = operator.solve(loads_pa)   # (..., grid.cells), independent leading cases

# These consume separate complete requests, not independent spatial solver tiles.
for rotated_batch in rotation.apply_batches(point_batches, budget=budget):
    consume(rotated_batch)
for deflection_batch in operator.solve_batches(load_batches, budget=budget):
    consume(deflection_batch)
```

`consume` represents the caller's chosen output handling, not a new Atlas function.
Discard processed batches to keep total output retention bounded. No disk write,
worker pool or background activity is started by these iteration APIs. The full
array-returning methods still require memory for the entire returned array.

[Decisions, limitations and obtained measurements](docs/OPTIMISATION_REFERENCE.md#delivered-optimisations-4-5)
are maintained in the existing reference. The new tests are included by
`python -I -B tectonics/verify.py`; no dependencies are installed by verification.
No other optimisation-list item or physical mechanism is implemented here.
