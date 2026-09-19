# Atlas optimisation reference

<a id="3cr4-3-execution"></a>

## Current: R4.3 variable stress, nonlinear iteration and source-safe continuation

**Version `0.1.0.dev30`, maintained plan revision 34. R4 remains IN_PROGRESS.**
The scientific contract is in [the maintained plan](TECTONICS_PLAN.md#3cr4-3-variable-mechanics)
and [`variable_stokes_r4_3.json`](../cases/variable_stokes_r4_3.json). R4.4 full
convection benchmarks and combined acceptance remain outstanding.

### Numerical work that is reused, and work that must not be reused stale

The full saddle operator is applied with native array stress/gradient/divergence
stencils. Sparse derivative topology is assembled once. The velocity block needed
for the ILU preconditioner is assembled natively from those derivatives and the
current centre/vertex viscosities. A bounded restarted GMRES solves the full
system using a block-triangular approximate inverse. The velocity inverse is
SuperLU ILU; the pressure approximation is the projected local `-2*eta_cell`
inverse Schur action, with the mean-pressure/gauge pair handled separately.

This preconditioner is nonsymmetric, so the normal route is GMRES, **not MINRES**.
It is approximate and contrast-sensitive; it is not R4.1's exact separable
constant-coefficient inverse. No dense inverse or whole saddle matrix is built on
the normal route. The explicitly selected small direct reference independently
assembles the saddle matrix and uses sparse LU; no automatic fallback is allowed.
The direct reference may be faster for small cases and is not a realistic large-
problem memory forecast. Advanced multigrid or universally mesh-independent
iteration counts are not claimed by this increment.

Default restart is 60 with at most 20 restart cycles. ILU drop tolerance `1e-4`
and fill factor 12 are numerical policy, not changes to viscosity. Increasing
fill can alter solver cost, not the accepted physical equations. The full true
residual is checked separately from the preconditioned residual. Failure in
factorisation or iteration is explicit. SciPy's fill policy does not cap total
native process memory. The public WorkBudget remains estimated admission with
required external/interpreter headroom, not an OS RSS limiter.

At most one numerical factor is retained, keyed by the exact normalised centre
and vertex viscosity bytes. Unchanged coefficients reuse it; changed coefficients
rebuild it while the sparse derivatives remain. Each complete nonlinear request
starts from its declared zero-rate control; it does not depend on hidden history
from the previous request. Picard iterations reuse their previous vector as the
next *linear* initial guess, but do not reuse a stale matrix as the physical
operator. Fixed-coefficient repeated requests preserve exact result identities.
Actual source/numerical-policy changes still intentionally change identities.

### Ownership, admission, cancellation and numerical integrity

Prepared plans are driven and closed by one thread. Global mechanics is not split
into independent plates or uncoupled grid tiles. Native-thread leases reuse the
existing implementation; no new pool or persistence subsystem is introduced.
Admission covers sparse derivatives, conservative overlapping factor lifetimes,
normalised inputs, a bounded GMRES basis, lagged/new material arrays, tensor
reconstruction, result copies and diagnostic scratch. Results retain immutable
bytes with private shapes. Returned results kept by callers need separate headroom.

Cancellation is checked before/after factorisation and during iterative calls;
native factorisation is allowed to return before its temporary memory is released.
Failures publish no result, and close releases the retained factor, derivatives
and source context. Factor construction counters are diagnostic state, not
scientific constants. No unsupported conditional change to equations, precision,
viscosity limits or material inventories follows a resource refusal.

For coupled work, existing thermal transforms and fused transport remain the
normal route. Each RK stage invokes the prepared nonlinear mechanics with new
current fields and checks true convergence. Both-stage and whole-step limits,
energy/material accounting and complete interval publication remain mandatory.
There is no extra heating channel. The `mechanical_mode='variable-r4.3'` switch
prevents legacy constant-only descriptors being reinterpreted silently. Supplying
an unused constant/nonlinear solver policy to the opposite mode is refused.

### Stable code identity and lossless restart

The new fresh-process nonlinear restart test exposed a provenance defect in
Python's default marshal encoding: format >=3 records object-reference state,
so retaining a returned constant tuple could change a code digest without changing
code or source. Execution schema `atlas.kernel-execution.v3` explicitly encodes
normalised acyclic code with marshal **format 2**, still within the exact pinned
Python runtime. Code objects are not decoded from untrusted input; cross-Python
code compatibility is not claimed. Source bytes, callable objects/instructions,
defaults, scientific constants and native binaries remain independently checked.
Tests still detect actual method/source changes. The initial failed regression
is retained; an old success receipt is not regenerated or relabelled.

The existing lossless Zstd/ArrayStore stores complete prescribed/rheological
mechanical inputs and outputs, and complete evolving thermal/composition states.
Both nonlinear stage IDs and true diagnostics survive restoration. Identical
repeated writes deduplicate. Same-source/policy continuation works after reopening
and in a fresh process. Historical R4.2 states remain exactly decodable; changing
source still refuses automatic continued calculation. No parent delta chain,
lossy field or whole-trajectory retention claim is introduced.

### Registered bounded measurements and actual-code visual checks

From a complete checkout in the declared installed environment:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python -I -B tectonics/verify.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python -I -B tectonics/tests/check_variable_stokes_r4_3.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python -I -B tectonics/tools/visual_variable_stokes_r4_3.py --output NEW_DIRECTORY
```

These are finite R4.3 component cases, not the skipped general benchmark programme
or full published convection. Setup, first and repeated complete-call costs,
iteration counts, native factor reuse/rebuild and memory admissions are separated.
No isolated cold-process timing or universal speedup is inferred. The declared
synthetic fields are fixed; failures are not discarded through a favourable seed.
Independent continuous-variable-coefficient, scalar nonlinear and coupled ODE
controls check accuracy separately from time. The optional plots use actual
registered numerical output and explicit labels; no renderer invents physics.

Routine stderr transcripts remain local. Structured evidence includes failures,
counts and source hashes. Earlier tests, source cases and historical evidence are
retained. Every implementation/review response carries a copy-ready Git changelog.
No reference reacquisition, dependency installation, R4.4 or R5 work is implied.

## Historical revision 33 and earlier execution contracts


<a id="3cr4-2-review-execution"></a>

## Current: R4.2 numerical conditioning and insulated-work reduction

**Version `0.1.0.dev29`, plan revision 33. R4 remains IN_PROGRESS.**
The [scientific review](TECTONICS_PLAN.md#3cr4-2-review) describes the unchanged
physical equations and new publication guard. No temperature clipping, source
renormalisation, mesh change, lowered order or tolerance relaxation is introduced.

The thermal cache still holds just one interval. In addition to rates and the
existing exp/phi coefficients, short-interval change coefficients and weighted
source factors/masks are prepared once and reused. Source-dependent mode products
still run per call; no field is cached under an incomplete identity. The original
128-byte/cell retained admission covers these linear-size arrays. No dense matrix/exponential is constructed. An observed midrange offset
under insulation uses two native field reductions; it is not a new material input.
The short-interval increment form avoids adding a round-trip error to the whole
field. Long-interval absolute evaluation avoids cancellation of a nearly fully
decayed field. The source-product fallback now includes nonzero subnormal
intermediate factors; its normal route remains native bulk arithmetic.

Under insulated walls the time-average field is unused and integrated boundary
heat is exactly zero. Each thermal half-step therefore performs one rather than
two two-dimensional inverse transforms. Fixed-temperature walls retain both,
including the independent signed boundary-heat account. No globally coupled solve
or successive physical interval is incorrectly parallelised.

The finite review observer compares old/new COMPLETE steps at 64/256-square fixed
and insulated prescribed-flow cases, plus 128-square coupled flow. It records
preparation, first calls and five reused calls, output comparisons and budget
reservations. The benchmark script can explicitly select the old checkout with
`--root`; its own hash is recorded separately from the target source inventory.
No baseline input, old test or previous evidence is regenerated. Timings are not
correctness gates or whole-world forecasts; native/library process caches and
machine conditions affect them. Inspect positive and negative timing results.

New state records carry the clock/conditioning publication contract. Older state
metadata is retained on decode, and source identity prevents silently claiming
that old endpoints can continue under the new implementation. The real original
snapshot restoration and new same-source restart checks are separate experiments.
No new cache, scheduler or persistence subsystem is added.

Run from the complete checkout in its documented environment:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -I -B tectonics/verify.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -I -B tectonics/tests/check_thermochemical_review_r4_2.py
```

New tests, source-bound measurements and actual-code plots accompany the review.
Historical reports remain at their existing paths. R4.3 variable/yielding
mechanics and R4.4 benchmark/combined acceptance have not started.

## Historical revision 32: initial R4.2 execution


<a id="3cr4-2-execution"></a>

## Current: R4.2 thermal/composition execution, version 0.1.0.dev28 / revision 32

R4.2 is delivered only for its [registered constant-property rectangular/binary
scope](TECTONICS_PLAN.md#3cr4-2-thermochemical). **R4 remains IN_PROGRESS; continue
with R4.3, then R4.4.** The old R4.1 next-step sentences below are historical.

### Native transport and a prepared discrete thermal exponential

The default combines fused Numba MC face reconstruction and Euler accumulation
with SciPy's native orthonormal sine/cosine transforms. `fastmath=False`, binary64
and disabled disk JIT caching remain explicit. One x/z face transfer is computed
once for temperature and composition, not independently by adjacent cells. The
NumPy slope-array formulation is an explicit same-equation verification/comparison
route, not a lower-order fallback. Buffers and `dt*u/h` transfers avoid unnecessary
physical-flux intermediates. A Neumaier reduction gives deterministic inventory
accounting without parallel reduction reassociation.

The thermal solve reuses O(N) discrete rates and one timestep coefficient entry;
changing dt replaces that entry rather than accumulating an unbounded cache.
The fixed source transform is reused in both thermal half steps. A stationary
boundary lift handles fixed face temperatures. `phi1` and `phi2` are evaluated
with series/expm1 near zero, not subtractive cancellation. Source weighting occurs
before a potentially overflowing source impulse, with an exponent fallback for
rare products; large attenuated modes have a log-tail path. This is not a lossy
history codec or an approximation to a different physical equation.

No dense global thermal matrix/exponential is formed in the normal route. Its
native transform work is O(N log N), retained arrays/scratch O(N); the independent
dense exponential is confined to small tests. Avoiding an explicit diffusion
CFL removes a stability bottleneck, not the requirement to refine time and space.
Variable conductivity, irregular geometry or other boundary conditions need an
explicitly verified operator rather than silently reusing this diagonalisation.

### Existing mechanics, execution and resource ownership

Constant-viscosity mechanics is prepared lazily and reused. Its source-verified
matrix-free solver is called at BOTH transport RK stages. These globally coupled
solves and successive physical timesteps are not independent jobs. No new thread
pool or scheduler is created. Native inner threads are bounded by the existing
lease; the driver is single-thread-owned and concurrent driving is refused.

One verified `ExecutionContext` covers Python/source/loaded numerical methods,
Numba/LLVM and the actual SciPy FFT/LAPACK/SuperLU binaries used together. The
new native transport module participates in that inventory. Source inclusion
changes identity intentionally, never an old evidence binding. Preparation is
shared; verification occurs around the full step, not per face/cell in hot loops.
SciPy/Numba are not imported into the old NumPy-only reference route by preparation
side effects; constructing a new thermochemical plan requires its declared engines.

`WorkBudget` admits preparation (including source context), accepted-state/source
capture, RK candidates, shared-face transfers, transform scratch, both stage
solutions, diagnostic arrays and final immutable publication. The nested existing
Stokes solver has its own admission. Failure/cancellation closes active call scopes
before memory is released, and publishes no endpoint. Completed results retained by
callers and interpreter/native allocator baselines still need headroom: this is
not a process-RSS cap. No budget failure changes order, precision, mesh or model.

Immutable bytes-backed state/step arrays have private shape metadata. Mutable
caller arrays are captured; returned views cannot become writable. Shared state and
compact problem definitions replace per-cell rich objects. There is no implicit
pruning of required material history; this binary pilot does not migrate the
existing cohort/history systems in the first place.

### Persistence, identity and finite evidence

The existing lossless Zstd/Blosc2 store remains the only persistent engine. Each
endpoint contains current T/C, problem, frame/epoch, source/policy, time/index and
last-step records. This supports exact same-source continuation without replaying
a parent delta chain. Future source/velocity input remains explicit. A decoded
historical record is not relabelled as meeting a newer method's acceptance.
Routine logs stay local; source-bound structured results include real failures.

Commands, from a clean complete checkout in the documented environment:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -I -B tectonics/verify.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -I -B tectonics/tests/check_thermochemical_r4_2.py
python -I -B tectonics/tools/visual_thermochemical_r4_2.py --output /path/to/new/r4-2-visuals
```

The finite comparison records native-versus-NumPy transport for complete
64/256-square prescribed-flow steps, plus actual two-stage coupled 128-square
steps. Setup, first calls and all reused-call repetitions are separated. Source
hashes are checked before/after. Different backend/runtime identities remain
distinct even when numerical arrays agree. These are sequential same-host
measurements, not isolated cold-process or whole-planet predictions. No universal
speedup, RSS bound, complete Tosi benchmark, Windows/macOS run or R4 completion is
claimed. `evidence/3cr4-2-tests.json` and `evidence/3cr4-2-measurements.json` are new
obtained records; earlier test sources/cases/reference bytes/evidence are retained.

## Historical R4.1 execution and review


<a id="3cr4-1-execution"></a>

## Historical: R4.1 mechanical execution — R4 remains IN PROGRESS

**Version `0.1.0.dev27`, plan revision 31.** This increment implements only the
constant-viscosity, uniform rectangular, closed free-slip mechanical component.
The authoritative [continuation table](TECTONICS_PLAN.md#3cr4-progress) keeps heat/
composition evolution, variable viscosity/yielding and full R4 benchmarks open.
Optimisation is part of each increment, not a reason to call the wider stage done.

### Review correction: numerical accuracy after SI publication

The original force snapshot is now normalised once, before applying any arbitrary
reference force scale. Velocity/pressure conversions use physical force, length
and viscosity factors in mantissa/exponent form. A normal, representable scalar factor uses one bulk multiplication;
only extreme factors require array decomposition. Native binary64 `frexp/ldexp`
work avoids intermediate scale underflow/overflow. Density-to-face interpolation
also evaluates the endpoint mean and gravity at a shared exponent rather than
rounding a tiny mean before multiplying. This is not higher-precision
physics, a lossier approximation or a new solver.

The private solve vector is reused for reconstructed published fields before the
single independent ghost-stencil/work pass. There is no second solve, second
full diagnostic pass, matrix construction or per-cell Python arithmetic. The
existing 768-byte/unknown solve admission includes these temporary conversion
buffers. FFT preconditioner reuse, coupled MINRES, direct-reference selection,
native-thread limits, cancellation and source identity remain in place.

`publication_contract=atlas.stokes-published-si-gates.v1` distinguishes current
checks from historical snapshots. The old `force_normalisation` is retained as
a descriptive reference quantity, not used to rescale the solved physics;
`force_amplitude_n_m3` records the actual original SI normalisation. Source changes
create new scientific identities. No old snapshot or test evidence is repinned.

`tests/check_stokes_publication_r4_1.py` performs the registered range/publication probes and
bounded 64/256-grid complete-call timings, including preparation, first and five
reused calls. An explicit `--root` may select the original code in a separate
process; the observer script hash is recorded separately. This is not a broad
benchmark or proof of universal speedup. The original favourable three-iteration
special-case preconditioner is unchanged. See the
[scientific review](TECTONICS_PLAN.md#3cr4-1-publication-review).

### Obtained review evidence

All 1,854 tests pass, including 38 new publication/scaling/physical-control tests.
The complete 256-by-256 reused-call median changed from 0.068989 s to 0.072163 s
in the bounded sequential comparison (about 4.6% more elapsed time). Three
MINRES iterations remained sufficient in that specific geometry. The 64-by-64
comparison was faster after correction, but these timings are not a universal
speedup claim. The extra SI-output adequacy check is retained rather than
sacrificing accuracy for the smaller timing. All repetitions and setup costs
are in [the review record](../evidence/3cr4-1-review-measurements.json).
The two ordinary workloads have exactly matching old/new force, velocity and
pressure arrays; divergence diagnostics and source-bound result identities
are intentionally updated. A genuine dev26 snapshot also restores unchanged,
without retroactively claiming the new publication guarantee.

### Matrix-free ordinary path and a separate small direct reference

`PreparedStokes2D` captures one named grid, R3 constant law, explicit SI scales,
pressure gauge and solve policy. Physical constant viscosity is divided out with
corresponding pressure/force scales; the RHS is normalised by its maximum absolute
force. Exact-zero force has an exact-zero result. Scientific precision, grid,
physical model and tolerances are never reduced after admission or convergence
failure. All physical outputs remain binary64 SI arrays.

MINRES applies the symmetric augmented MAC operator using native array stencils.
The velocity preconditioner is an exact **discrete** separable inverse in this
specific geometry: DST-I on wall-normal interior nodes, DCT-II on wall-tangential
cell centres, retained spectral eigenvalues, inverse transforms. Pressure's
mean-zero Schur block is identity after constant-viscosity scaling; its constant
mode is paired with the gauge multiplier. Full residual checks remain necessary
in finite precision. This is not a preconditioner claim for variable coefficients,
irregular supports, non-free-slip boundaries or a 3D spherical shell.

The explicit `method='direct'` route assembles the operator from independent
Kronecker/face-incidence stencils and retains SuperLU factors. It is a small
verification route, not automatically selected on failed MINRES. No dense inverse
is formed. Later thermal/nonlinear work must distinguish reusable symbolic geometry
from numeric factors that become invalid when coefficients change.

### Resource bounds, native threads and cancellation

Preparation reserves existing source/context storage and O(N) spectral/operator
metadata. The direct route additionally reserves `64*N_unknowns^2` bytes as a
conservative dense-fill factor/work allowance before sparse assembly, rather than
assuming favourable fill. This intentionally limits the direct control under a
finite budget. The normal matrix-free path needs only linear retained/workspace
admission; transform complexity is O(N log N). Independent task-level parallelism
is not used to split a globally coupled stress solution into separate plates.

The existing WorkBudget admits captured forces, RHS, MINRES vectors, FFT scratch,
independent residuals and immutable publication before allocation. FFT workers are
explicitly one. The existing coordinated native-thread lease also limits linked
BLAS work to one, without a second executor/control subsystem. A plan has one
driving thread and one active solve; another thread may signal cancellation through
an event, not concurrently mutate/close its native state. Native calls complete
before resource release; cancelled calls leave the retained plan reusable.

Current policy bounds unknowns, direct-reference size and iterations. They are
explicit request limits, not permanent metre/planet product ceilings. A budget is
an admission estimate, **not a process RSS cap**; caller-retained outputs, interpreter
and native allocators still require headroom. Nonfinite or unrepresentable SI
conversions and unsuitable spectral condition estimates fail explicitly.

### Source identity, persistence and independent gates

Existing `ExecutionContext` checks current source bytes, loaded callables and
constants before/after each complete solve, not inside every Krylov iteration.
The new modules and selected native FFT/SuperLU binaries participate in the runtime
record; this is still not a recursively sealed system-library deployment. Reused
context identifiers avoid redundant whole-context validation inside publication.
Changes in grid, scales, law, boundary or numerical policy alter the prepared
identity; changes in forcing/provenance/epoch/time alter the result identity.

MINRES `info=0` alone is insufficient. Independent ghost-stencil momentum, all-cell
divergence (without gauge correction), gauge multiplier/mean pressure and discrete
mechanical work must pass the separately registered limits. The sparse direct
reference and continuous manufactured cases test more than one matrix assembly.
The two linear solvers may differ at round-off and are NOT claimed bit-identical.
Repeated same-route outputs are deterministic in the tested environment.

The sole persistence path remains lossless Zstd/Blosc2 ArrayStore with verified
chunks and deduplication. A snapshot includes the full steady problem and actual
u/w/p/divergence/forcing arrays, not mutable factors. Cold restoration does not
re-run a solver or replace old source identities. Evolving-state recovery remains
an explicit future R4 requirement, not inferred from restoring a steady snapshot.

### Reproducible bounded evidence and next work

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python -I -B tectonics/verify.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python -I -B tectonics/tests/check_stokes_r4_1.py
python -I -B tectonics/tools/visual_stokes_r4_1.py --output /new/visual/directory
```

The first command is the regression suite, not a world run. The second compares
16/24-cell-per-axis direct and iterative cases, plus 64/128/256 iterative cases,
with three reused calls and separate preparation/first calls. Input construction
is outside timing. It records every repeat, actual iteration counts, native thread
environment, admitted memory, numerical agreement and exact restored-array identity.
No speed ratio is generalised to nonlinear or whole-planet workloads; native direct
factorisation can be faster at small sizes while its memory scaling is worse.
New evidence goes into distinct `3cr4-1-*.json` files, never historical repins.

The visual tool labels supplied temperature separately from solved velocity and
pressure. Raw staggered arrays remain authoritative; centred arrows are rendering
interpolation. Visual review is recorded after inspection, not automatically green
because PNG files exist. This component establishes no thermal trajectory, Tosi
convection solution, pressure-dependent rheology, coupled localisation or geological
acceptance. **Continue with R4.2; do not mark R4 complete or jump to R5.**

## Historical revision 29 — retained R3 numerical hardening

<a id="3cr3-stress-arithmetic"></a>

## Current: R3 stress arithmetic hardening — 19 September 2026

**Version `0.1.0.dev25`, plan revision 29.** This is a local numerical correction,
not a new physical closure. The former evaluation squared the strain invariant
before multiplying by viscosity, causing avoidable underflow; `2*eta` and the
invariant itself could also overflow before a representable final product.

The normal path remains native binary64 array work. `frexp` splits viscosity,
each strain component and the largest tensor magnitude into binary significands
and integer exponents. `ldexp` applies the combined exponent only after bounded
significand multiplication. Heating uses a power-of-two-normalised square sum,
with both off-diagonal entries retained, before the final conversion. There are
no logarithmic approximations, dense inverses, extended-precision hot paths,
per-point Python loops or arbitrary epsilon rates. Decimal appears only in the
independent test oracle. True final overflow or a non-zero output rounded to zero
is refused; representable subnormals remain supported.

The helper no longer calls `strain_rate_invariant` just to repeat capture,
normalisation and validation, or computes a square root only to square it again.
Symmetry and trace checks share normalised input. Read-only broadcast views,
in-place stress buffers and existing immutable publication are retained. The
unchanged WorkBudget subsystem admits capture, mantissas/exponents, scratch,
outputs and immutable copies before allocation; it is not a process-RSS cap.

Run `python -I -B tectonics/tests/check_stress_hardening_r3.py` for the bounded
current-source probe. Optional `--baseline <prior tectonics directory>` compares
the untouched previous source in an isolated process. The 8,192/65,536-point
full-call timings include validation, capture and output publication. The first
call and five repeats are recorded; inputs are constructed outside timing and
no universal speedup is claimed. New structured records preserve the old failing
probe separately from corrected results. No historical evidence is overwritten.

Accuracy/optimisation reviews include repair of verified in-stage defects under
the owner's standing instruction, followed by tests, meaningful visual QA and
a response changelog. That convention does not permit later-stage development,
new dependencies, source repinning, numerical downgrades or automatic Git writes.


<a id="3cr3-execution"></a>

## R3 local-law implementation (original delivery) — 19 September 2026

**Version `0.1.0.dev24`, plan revision 28.** The science and exact source locations
are in [the maintained plan](TECTONICS_PLAN.md#3cr3-physical-closure) and
[`physical_closure_r3.json`](../cases/physical_closure_r3.json). This increment
implements local viscosity/yield/memory, force/heat accounting and a 1D physical-
length operator, not the R4 thermal/Stokes solver. R1 and R2 are not repeated.

### Native work and measured scheduling

`evaluate_rheology` uses binary64 native array operations and bounded buffered
iteration (32,768 points by default), supporting strided/broadcast arrays without
point-by-parameter object graphs. Analytical zero-rate and zero-healing limits
avoid arbitrary epsilon rates. The memory update uses `expm1` for small intervals.
An explicit range/refusal is preferred to numerical zero, an altered law or a
hidden viscosity clamp. Registered parameter profiles remain immutable.

`PreparedRheology` captures mutable input once into compact immutable bytes,
reuses those bytes for calculation/hashing, and shares the existing verified
source context. An optional explicit `ExecutionPolicy` connects to the existing
bounded `KernelExecutor`; no new worker pool implementation exists. Only independent
local evaluations are batched, not successive physical timesteps. Ordered output
assembly preserves the same arrays and result identity for serial and threads.

**The normal path is native bulk serial.** The finite local-law workloads did not
establish a repeatable thread speed advantage once source checks, capture and
output publication were included. Optional auto/thread policies remain available
for owner-measured workloads; there is no automatic whole-solver speed claim or
reason to impose threading on small ufunc batches. R2's separate measured point
threshold and cell defaults are unchanged. The new measurement driver records
first calls, setup, each repeat and both modes, not just a favourable timing.

The 1D regularisation operator factors an SPD banded matrix once and reuses the
factor in O(n) solves. It does not form a dense inverse. An independent flux
residual, positivity, integral and modal/refinement tests constrain its numerical
behaviour. This does not certify coupled localisation or a 2D/3D solver.

### Memory, cancellation and persistence

The existing `WorkBudget` admits the source context, full input capture, held
batch outputs, final assembly, per-job native scratch, banded factor and store
operations. Admission estimates are not process-RSS limits; caller-retained
completed outputs and allocator/interpreter baselines need additional headroom.
Excess requests fail rather than changing precision, law, history or resolution.
The complete request's count bound applies before jobs are submitted. A failed
or cancelled worker aborts siblings and drains active native work before releasing
reservations; a failed request does not poison the pool. Closing a live plan or
its executor from the wrong driving thread is refused without discarding its
live reservation. No unbounded task queue is added.

New loaded modules participate in the existing callable/source inventory. The
SciPy LAPACK binary is recorded for the banded solver alongside existing SciPy
runtime identities. Profile, named scales, source/runtime and method identity
bind the output; worker count/order does not. Interpreter link portability and
source/data/compiled-extension link protections retain the cleanup contract.

`LawResult` holds complete local inputs, outputs, exact profile/scales and original
source identity. Memory-step records include before/after damage and interval.
`save_law_result`/`load_law_result` use the existing lossless Zstd/Blosc2 `ArrayStore`,
verified chunks and deduplication. Restore validates recorded definitions and
result identity without rerunning the model or rebinding historical bytes to the
current context. No new storage system or lossy history is introduced. Hashes
identify the record; they do not authenticate an outside producer's claims.

### Bounded evidence and visual inspection

From a clean checkout in the separately documented environment:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python -I -B tectonics/verify.py > fresh-r3-tests.json
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python -I -B tectonics/tests/check_constitutive_r3.py > fresh-r3-measurements.json
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python -I -B tectonics/tools/visual_r3.py --output r3-visuals
```

The output directory must be new. The visual tool publishes its five figures,
raw curve arrays and a manifest atomically. A successful render remains
`RENDERED_AWAITING_VISUAL_REVIEW`; inspection must be recorded separately. These
are material responses and an authored fixed-length test, not invented mountains
or evolved plate boundaries. The local references are independent scalar/decimal,
analytic and dense-matrix checks, not cross-code full-convection acceptance.
Linux evidence does not establish Windows/macOS, global scale or physical validity.

Every delivery response includes a **copy-ready commit title and changelog**,
covering actual changes, tests, provenance and important limits. Keep structured
JSON evidence; routine new unittest logs remain local. Preserve old evidence,
include exact before/after hashes, and distinguish a complete package from its
review patch. The owner applies/commits/pushes manually. The selected code
licence is AGPL-3.0-only; third-party terms remain separate.

<a id="cleanup-execution"></a>

## Historical: portability and review cleanup — 19 September 2026

**Package `0.1.0.dev23`, maintained plan revision 27.** No equations, scientific
cases, R1 source-use policy, measured R2 execution thresholds or physical scope
change. R2 is delivered within its registered envelope; R3 remains unstarted.

### Interpreter identity without weakening source checks

The Python executable path is resolved strictly before hashing its regular-file
target. This supports linked and copied virtual-environment launchers. Only the
interpreter receives that treatment, including the built-in `math` fallback.
Source files, reference data and binary extensions keep their existing symlink
refusals. Broken/cyclic interpreter links and non-files fail explicitly. Hashes
identify binary content rather than absolute installation paths; the existing
process-lifetime immutability assumption for loaded binaries is unchanged.
This is runtime provenance, not a defence against arbitrary hostile process edits.
See [environment setup](../README.md#environment) for the independent tectonics
venv; the older source-only bootstrap is not its dependency environment.

### Delivery and evidence policy

A delivery must state its branch/base commit, full-snapshot versus update-only
kind, exact added/modified/deleted paths, old/new SHA-256s and suggested logical
review groups. A complete snapshot is not an instruction to replace a repository
folder. Merge only reviewed changes and preserve newer local edits. Each manifest
has an explicit apply root; tests, review patches and visual artefacts are separate.
Michael retains manual application, commit and push ownership.

Routine unittest stderr logs remain local, ignored artefacts; retain concise JSON
with actual commands, environment, source hashes, counts, failures and limitations.
Preserve unique failure diagnostics when needed and explain exceptions to the log
policy. Already tracked historical logs/JSON/reference originals are not deleted,
rewritten or rebound by this cleanup. No benchmark is rerun just to refresh a date.

### Visual QA is part of every meaningful stage

Use actual source-bound code output, not image-generation illustrations. Record
case, seed, units, source/runtime identity, sampling and rendering choices. Check
labels and joins against source records, including unknown masks and formation
versus cooling time. Flat global maps need proper seam clipping; globes need both
polar views as well as equatorial orientations. Inspect slivers, discontinuities,
coverage and suspicious patterns. Human observations and automated numerical
checks are separate evidence; neither alone establishes physical adequacy.
An unchanged runtime-only stage may reuse the same case for a bounded visual
regression. If nothing meaningful can be visualised, record why rather than
invent an output. Store a small machine-readable visual record; keep routine PNGs
outside versioned scientific source. The renderer and its tests remain reproducible.

The previous chat age graphic and boundary-symbol legend are superseded by the
source-derived visual tool. Cohort dates are read from sampled units; no hand-coded
age table is used. PB2002 `-` is labelled non-subducting, not transform. Raw
polylines are display-only; no malformed outline is repaired or granted approval.


<a id="3cr2-scaling-execution"></a>

## Current: R2 scheduling/indexing follow-up (18 September 2026)

**Version `0.1.0.dev22`, maintained plan revision 26.** This is an engineering
extension of R2 only. Scientific scope and numerical acceptance are unchanged;
R1 sources/evidence are preserved and R3 is not started. The earlier dated R2
execution section remains as the historical account of revision 25.

### Conservative indexing, exact final predicates

`_spherical_candidates.py` prepares a hemispherical cap `(c,r)` per unique area
footprint. A normalised vertex-mean centre generally gives a local cap; the
existing conditioned chart centre is a conservative fallback when the local cap
would not be hemispherical. Geodesic convexity means that a cap below a hemisphere
containing all vertices contains their minor arcs and areal hull. Holes only
subtract area. The cap lies in the unit-sphere Cartesian ball centred at `c` with
radius `2*sin(r/2)`. Outward bounds use a declared binary64 arithmetic guard of
512 epsilon; this is not a modified physical/area acceptance tolerance.

A Shapely STRtree indexes the two most informative Cartesian bounding coordinates.
The omitted coordinate and angular cap-distance predicates reject additional false
positives. Potential intersections then use the unchanged native spherical overlay.
No approximate nearest-neighbour query, sampling-phase trick, snapping, longitude
box or positive-area cutoff is used. Polar and date-line cases are tested. The
index also prunes spherical province candidates during ordinary cell sampling.

The complete cell-overlap check groups identical footprint IDs and sorts their
depth intervals. Each group is checked for positive-depth self-overlap; pairs of
candidate groups use a two-pointer depth sweep before at most one exact footprint
intersection. Caps and bounds are prepared once per distinct footprint, not once
per possible cell pair. Queries retain one bounded candidate row rather than an
all-pairs matrix. Sparse cases improve substantially; dense overlapping enclosures
can still require quadratic work and are subject to the explicit work limit.
Prepared area indices remain reserved until close, with concurrent-reader guards.

### Existing scheduler integration and measured automatic selection

`PrecursorExecutionPolicy` selects the normal route without changing equations:

| Request | Normal automatic route |
|---|---|
| Indexed point request, at least 262,144 points | Existing bounded thread executor; 32,768-point tasks. |
| Smaller or unindexed point request | Existing grouped/native serial implementation; no pool created. |
| Cell request | Serial by default: the measured 512-cell cases were slower with threads. |
| Explicit threaded cell comparison or owner-selected threshold | The same bounded executor, default 64-cell tasks; identical scientific outputs. |

The existing `ExecutionPolicy` defaults remain two workers (or fewer if only one
CPU is available), at most four queued/in-flight tasks, and one inner native
thread. Explicit one-worker policies remain serial. A prepared native index is
shared in-process, not pickled to spawned workers; requesting that unsupported
process mode is refused. A pool is created lazily on the driving thread and
reused. The executor must be driven/closed from that same thread; small independent
serial readers still share the immutable prepared state. No second scheduler or
unbounded worker queue was introduced.

The prior-evaluation native batch default is 32,768 rather than 4,096 points.
This changes scheduling/scratch, not per-point mode summation or numerical order;
user-specified batch limits are honoured. GeometryIndex scratch also clamps its
batch to actual query length rather than charging a full policy batch for one
point. Both changes are covered by equality/refusal tests.

### Admission, global limits, cancellation and identity

Before submission, the full immutable request is captured and an aggregate
reservation covers retained chunk outputs, merge arrays and final immutable
bytes. Each existing executor task holds its full parent admission until result
validation finishes. Detached child WorkBudgets account for nested allocations
inside that already held envelope, avoiding double charging the shared budget.
This private admitted-call adapter is not a bypass for unbounded arbitrary jobs.
Prepared geometry and source contexts remain admitted independently. Complex jobs
that exceed their declared allowance fail; they never coarsen, reduce precision
or change model. Interpreter/native allocator baselines and completed results
retained by the caller still require headroom; admission is not an RSS cap.

The global ledger counts geometry hits, sparse associations and overlay/sampling
work across all batches. Complete cell-frame/support/unique-ID/overlap validation
occurs once before workers; batching never implies permission to sum overlapping
queries. Original errors and the explicit non-additive opt-in remain. Ordered
assembly shifts sparse offsets and phase-to-row references without re-summing a
physical cell in a different order. Shared thermal means remain call-local and
bounded. Worker failures/cancellation abort siblings and drain native work before
reservations are released; the pool can be reused after the failed request.

Execution configuration, worker order and diagnostics do not enter the scientific
sample identity. The sampling method is versioned `atlas.precursor-sampling.v2`;
actual source/runtime and loaded methods are checked before/after each full call.
The source inventory now includes the index and execution adapter. Only the
executor's enumerated process-wide resource lease counters/handles are excluded
from scientific constant checks, not methods, numerical constants or source bytes.
Stale-source/loaded-executor mutation tests and cleanup tests cover this separation.

The existing ArrayStore remains the only persistence path: lossless Zstd/Blosc2,
verified chunks, deduplication and self-contained precursor/sample definitions.
Serial/thread outputs deduplicate to the same current sample; all restored arrays
are exact. This does not rebind or overwrite historical checkpoints/evidence.

### Focused reproducible evidence

From a clean complete checkout in the already declared environment:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python -I -B tectonics/verify.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python -I -B tectonics/tests/check_precursor_scaling.py
```

The latter is the finite registered comparison, not the skipped general baseline
programme. It records source identities before/after, all setup/first/reused complete
call timings, serial-versus-thread numerical identity, resource admissions, exact
restoration/deduplication, and the negative threaded-cell performance result.
Index construction is included in complete overlap-validation timing. Input
construction is separate. Imported libraries/process caches are shared across
sequential cases; setup is not an isolated cold-process startup comparison.
Timing is not a test gate and is not extrapolated to all meshes or machines.
No R1 reacquisition, full-world simulation, dependency installation, Windows
acceptance, physical validation or R3 implementation occurs in this increment.

## Historical revision 25 execution delivery

<a id="3cr2-initial-execution"></a>

## 3C-R2 — precursor execution, identities and storage (18 September 2026)

**Current delivery: `0.1.0.dev21`, plan revision 25.** The bounded static precursor
and necessary initial sampling are delivered; R3 is not started. The scientific
contract and unsupported spherical/global/volumetric cases are in
[the maintained plan](TECTONICS_PLAN.md#3cr2-initial-state) and
[`precursor_r2.json`](../cases/precursor_r2.json). Older dated R1 status below is
historical; R1 inputs, numerical gates, source-use policy and evidence are unchanged.

### Normal execution path, not an opt-in optimisation

`PreparedPrecursor` shares one immutable case/state, compact unit/cohort/material
catalogues and existing native geometry indexes. Indexed sparse point hits are
grouped once; native array unions, grouped depth searches and vector arithmetic
replace a Python object/set per point. Only actual province/weak-zone associations
are returned in compact CSR arrays. Cell queries prune area candidates, then use
unsnapped exact geometry intersections and precedence subtraction; the index
never decides material ownership or stands in for a conservative average.

Constant-depth breaks are split explicitly. A bounded cache of up to 1,024
initial-profile interval means avoids repeated integration within one cell call;
its key includes profile, top, bottom and spherical radius, with a fixed shared
case time. There is no stale cross-state thermal cache. Streaming compensated
sums accumulate volume/temperature/error per actual unit portion. Sparse records
grow only after bounded capacity admission; no dense cell-by-every-material or
point-by-every-mode cube is formed. Outputs use private immutable bytes and fresh
shape/dtype views, not a mutable read-only parent array. A changed result-view
shape cannot change the next view or another reader's metadata.

The default remains binary64 with no fast-math, no precision/coarsening fallback,
no altered history and no sampled centre replacing an integral. Planar spectral
prior integrals use polygon boundary Fourier integrals (including holes) and a
separable vertical factor. Long-wavelength cancellation uses factored/sinc-style
expressions and fixed summation order. Spherical Cartesian-prior cell integration
is explicitly unavailable instead of being replaced by a lower-quality route.

### Resource ownership and bounded interruption

The existing `WorkBudget` accounts for active shared state, both native indexes,
compact maps and an execution-context allowance before setup. That allowance
covers the existing context's bounded source snapshot, the concurrent comparison
copy and callable metadata. It remains reserved until plan close; source
invalidation during close cannot leak its reservation. Per-call capture,
geometry candidates, fragments, sparse records, native work and immutable-output
construction have joined allowances, finite row/work/vertex limits and cooperative
cancellation. Readers can share a prepared plan; close refuses while a read is
active. Interacting timesteps or mechanical plate solves are not parallelised by
this static API. No new scheduler, worker pool or unbounded cache was introduced.

Budget figures are admission estimates, **not process-RSS limits**. Returned
`InitialSamples` and caller input/state references are caller-owned: retaining
many completed outputs requires aggregate caller/execution admission using their
reported `nbytes`. Interpreter/native allocator baselines and other retained
outputs require headroom. Cancellation is cooperative at bounded work points;
it does not interrupt a GEOS/native call halfway through memory ownership.

### Identity and self-contained persistence

The state identity includes the original case, actual material-library dependency,
origin classifications, separate cooling dates, volume bases, body/field records
and explicit precedence. Priors include stream version/name/seed, physical scales,
amplitude convention, origin and domain/frame. The prepared identity also covers
numerical limits and the existing verified `ExecutionContext`; the new modules
are included in its callable/source inventory. Every prepared use verifies the
source/runtime contract, rather than trusting mutable input digests or mtimes.
No historical source bindings or expected answers are rewritten.

`save_precursor_state`/`load_precursor_state` use one existing `ArrayStore`
transaction. `save_initial_samples`/`load_initial_samples` additionally retain the
actual query support geometries, sample arrays, their complete descriptor and
the precursor/library decoding dependencies in a **single result snapshot**.
Restore verifies canonical definitions and every array, and neither reacquires
sources nor resamples stored outputs. Original sources/unknowns/history survive.
The existing lossless Zstd/Blosc2, verified chunks, compact categoricals and
deduplication remain the storage implementation. Small raw chunks are its explicit
size choice, not a compression-error fallback. No lossy histories, temporal delta
chains, dictionary dependencies or Numba disk cache are introduced.

### Obtained bounded checks and reproducible commands

Run from the repository root in the existing declared environment:

```sh
# Entire software regression: source-bound result, not physical validation.
python -I -B tectonics/verify.py > 3cr2-tests.json
# Only the declared small R2 measurement/invariant case, with finite repeats.
python -I -B tectonics/tests/check_precursor_r2.py > 3cr2-sampling-evidence.json
# Offline authored example using the sourced material catalogue; no file writes.
python -I -B tectonics/tools/prepare_precursor_example.py > initial-example.json
# Explicit optional NEW store; existing destinations are refused.
python -I -B tectonics/tools/prepare_precursor_example.py --save-store initial-example.db
```

The example is not an equilibrium, mantle law or calibrated Earth starting
condition. Its temperatures, lateral columns and formation/cooling dates are
explicit authored inputs. The source catalogue supplies reference material data;
unknown hot properties, stress/damage and intrinsic aggregate porosity remain
visible. The optional store contains one complete result snapshot; obtain its
state through `load_initial_samples(store, report['sample_id']).state`.

The focused execution card uses **672 points**, three cold complete calls, three
prepared complete calls, and **1/4/16-cell** inventories. Its exhaustive per-point
oracle checks exactly the same geometry/material/thermal quantities, but is not
timed as a fully equivalent alternative execution backend. Cold/prepared timings
both include normal context verification, capture, sampling, immutable output and
hash creation; cold includes preparation/close. State-construction and storage/
restoration costs are reported separately. All point temperatures, unit/province
codes and retained province matches agreed; the three mesh sizes had zero
reported material/coverage residual in this exactly integrable fixture. Every
saved numeric array restored exactly, with zero residual budget reservation.

On the obtained Linux run, complete cold calls were approximately **0.290, 0.063
and 0.065 s**, and prepared calls **0.019–0.025 s**; these are small-case costs,
not a universal speedup or proof of planetary capacity. The combined check's
peak **accounted** reservation was 22,231,138 bytes including storage work, not
measured peak RSS. Exact values, source hashes and runtime are in
[`3cr2-sampling-evidence.json`](../evidence/3cr2-sampling-evidence.json).
[`3cr2-tests.json`](../evidence/3cr2-tests.json) and its log record the actual
complete regression. A Linux/CPython 3.13 execution does not establish Windows,
other runtimes or general physical adequacy. The broad baseline programme remains
unperformed, as instructed.

---

### Retained R1 reference-use delivery

<a id="3cr1-reference-tools"></a>

## 3C-R1 — audited source uses, unchanged strict checks (18 September 2026)

**The bounded reference-use review is complete; R2 is not started.** This closes
the source-use decision left open by the offline tooling repair, not the failed
strict consistency gate and not the later tectonic-realism gates. The complete
package still contains all baseline files and the eight unmodified PB2002 originals
under `reference_data/pb2002`. No additional acquisition or dependency is needed.

```sh
# Raw source consistency: currently exit 1, including all unresolved findings.
python -I -B tectonics/tools/prepare_plate_reference.py --verify-only > 3cr1-strict.json
# Exact reviewed source uses: exit 0 only within the registered finite policy.
python -I -B tectonics/tools/prepare_plate_reference.py --verify-only --assess-use > 3cr1-use.json
```

Exit 2 still means an input/prerequisite failure. No network access occurs with
`--verify-only`. A scoped exit 0 must never replace the strict result in reporting.
The policy, dataset, original protocol and actual strict report have distinct
identities. Unknown source findings or failed numerical checks refuse scoped use.

### Source investigation and restrictions

The [versioned source-use case](../cases/plate_reference_use_policy.json) gives
primary-source locators and how each was accessed. Bird's **Table 1** confirms
ON=0.00802 sr; our transcription is not the cause of its outline disagreement.
The outline gives approximately 0.0079998317443 sr under both existing area
formulations. Neither value is changed. Table calibration and outline diagnostics
remain distinct, and ON cannot be used to claim table/outline equivalence.

Bird's **paragraphs 44 and 65** explain the subsurface Molucca representation;
paragraph 65 gives SU/MS\BH, consistent with the archived BH-side owner. Paragraph
44's different PS reference is documented rather than used to reassign owners.
Two coincident spans and the MS retraced branch remain original evidence.
MS is excluded from ordinary simple-ring morphology at all scales/phases. In
particular, a source-preserving diagnostic at one scale produces compactness above
one; it remains visible in the raw report, not clipped or selected away by phase.
Individual source boundary/step kinematics remain labelled source observations,
not independent dynamics validation or unique surface edges.

Three polygon-only connectors (approximately 163.51, 259.76 and 2.22 m) have no
corresponding original boundary step. Their cause is not established. All five
incidence-affected edges fail the two-owner surface-edge interface; near points
are not snapped. Surface-neighbour statistics conservatively exclude the nine
touching owners `AF, AU, BH, IN, MS, NB, SB, SO, SU`. Unaffected original records
remain available, but the source is not accepted as a globally consistent mesh.

Peru's 49-point deformation trace is open by approximately 8.70 km. The publication
and pinned format documentation specify polygon outlines; no explicit exception
was found that justifies fabricating closure. Record 11 cannot supply polygon
metrics. Original `in_orogen` flags are retained as source values, never recomputed
from an incomplete 12-outline mask. A complete derived mask is refused.

### Prepared use plan, resources and evidence identities

`plate_reference_use.prepare_reference_use()` loads the checksum-verified originals,
runs the unchanged complete report and admits **16 MiB additional** preparation
workspace through the existing parent WorkBudget, alongside the report's existing
reservation. This estimate is not an operating-system RSS limit. Returned data
and indexes are explicitly caller-owned. A frozen shared report tree backs record
indexes without copying its numerical/metadata payload for each query. All exact
boundary-edge keys are built once, so subsequent membership/refusal is a set
lookup, not a repeated full boundary walk. No general cache or scheduler is added.

`observations()` selects every eligible reference in the named original split;
it does not accept arbitrary record masks. Shape observations require a named
100/250/500 km physical scale and phase (0 or 0.5). Area data require the explicit
`published_table` or `source_outline` basis and use physical `4*pi` normalisation,
not the sum of surviving/tuned records. `compare()` requires the same candidate
scale/phase, a run/candidate identity, total population and unresolved count.
Raw generic diagnostic primitives remain unchanged; qualification is a separate
interface, and callers must not describe unqualified primitives as approved uses.

The selection uses bounded native arrays and a 256 KiB metadata envelope; candidate
and empirical-distribution work join the same budget. Cancellation/refusal releases
all work reservations. Missing scientific information is never inferred by a memory
fallback. No fast-maths, lowered precision, source repin or old tolerance change.
Concurrent reads share immutable prepared setup. Returned reports are detached.

The complete qualified comparison identity binds policy, source, strict report,
reference split/scale/phase, area basis, exclusions and actual comparison values.
The existing ArrayStore lossless Zstd/deduplication/backup path stores the **unchanged
strict report**; receipts name the separate policy and assessment. Cold assessment
rechecks source/policy identities; it never trusts an obsolete cached exemption.

### Coverage and scope acceptance

- 52 table areas and 52 native area-formula checks remain labelled diagnostics or
  exposed calibration. ON table/outline equivalence is unavailable (51 eligible).
- 51 plates are eligible for ordinary morphology before observation-scale limits.
  MS remains present as raw evidence, not removed from planetary accounting.
- 43 plates support the conservative surface-neighbour-count population.
- 12 of 13 orogens support closed-polygon diagnostics; no complete derived mask.
- All 229 boundary segments and 5,819 motion rows remain source records, not a
  unique two-owner surface network. Duplicate spatial traces are not collapsed.

The ten predeclared morphology holdouts are unchanged. Scale-unresolved cases
(for example Manus at 250/500 km) remain in expected counts and are reported, not
assigned a misleading zero. Within-model holdouts are correlated evidence, not
an independent second Earth. Historical/external-model challenges remain at R9.
No combined realism score or automatic generated-world approval is produced.

The [scoped assessment](../evidence/3cr1-reference-use-assessment.json),
[coverage](../evidence/3cr1-reference-use-coverage.json) and
[regression](../evidence/3cr1-reference-use-tests.json) record this decision.
The [strict report](../evidence/3cr1-complete-reference-checks.json) and prior repair
tests are preserved byte-for-byte. New tests cover policy identity, unknown findings,
MS/ON/Peru restrictions, all five exact edges, preserved holdouts, candidate counts,
phase/scale compatibility, immutable/concurrent reads, budgets/cancellation and
fresh-process offline/storage restoration. No R2, W03, generator change or publishing.

The full regression passed **1,298 tests** (1,254 retained plus 44 new), with zero
failures/errors/skips and 93 unchanged verification-input hashes. All old tests,
source data, numerical kernels and historical evidence remain byte-identical.
For either phase, whole-inventory compactness coverage is 51/52 at 100 km, 49/52
at 250 km and 45/52 at 500 km: MS is excluded and all other absences are explicitly
scale-unresolved. These are reporting populations, not candidate scores.

### What the implementation checks

- Original DIG segment titles, directions, explicit closure and source locators;
  fixed-width step columns, left/right ownership, signed Euler poles, class and
  deformation flags. Unknown seafloor ages remain unknown.
- Spherical area through independent Gauss-Bonnet and solid-angle formulations;
  great-circle perimeter without a planar projection or hemisphere-only shortcut.
  Oriented complements are explicit; clockwise rings are not silently reversed.
- Shape at 100, 250 and 500 km observation scales, using equal-arc sampling and two
  sampling phases. Coarse samples of small plates are labelled unresolved. Extra
  collinear vertices cannot improve the measurements. Boundary moment eigenvalues
  are a boundary-shape diagnostic, not falsely labelled an area inertia tensor.
- Exact source-decimal shared-edge incidence, adjacency, junction owner sets,
  full step-to-boundary sequence alignment, per-class lengths and margin context.
  Orogens remain overlapping deformation overlays, not additional rigid plates.
- Per-step opening, right-lateral velocity, speed and length with separate numerical
  and source-rounding bounds. Observed SUB classifications are not manufactured
  from convergent velocity; rounding bounds are not geological confidence intervals.

### Data use is declared before further generator tuning

All 52 areas are already-exposed calibration. Cocos morphology and the first 12
AF-AN motion steps remain marked previously exposed. New morphology for
`KE, MA, MN, NB, NI, PS, SB, SS, TO, WL` is reserved; all boundary segments touching
those plates share the held-out designation. Orogen shapes are reserved from
layout tuning. Numerical verification of these records is not use for fitting.

This is a **within-PB2002 spatial/observable holdout**, not an independent second
Earth. Boundary neighbours and common reconstruction assumptions remain correlated.
A separate reconstruction/model and temporal histories have NOT been acquired by
this increment. The protocol keeps those gates unavailable; a current Euler pole
cannot fabricate a historical plate-shape series.

Evaluation records require an explicit purpose, split, candidate identity and run
ID. An area-calibrated result cannot be rebranded as held-out area validation. Each
metric is reported independently, with observation scale and unresolved-object
counts. No single realism score, invented scientific threshold or automatic
scientific pass is supplied. Realism acceptance remains at the later registered
process/population gates.

### Optimisation and ownership

The code uses compact immutable coordinate payloads, shared catalogues, native
NumPy geometry, finite parser limits, scoped memory admission and uniform-arc
sampling. It does not allocate all-pairs point/edge matrices. Parsed references
can be retained by their caller; data are never cached by a mutable array's object
identity. The optional report persistence uses the existing exact ArrayStore and
its compression/deduplication/backup semantics. No new runtime or cache framework
is introduced. Caller-retained references and native overhead remain outside the
per-call budget estimate.

Unit verification and full-source verification are deliberately separate. The
new regression tests cover malformed sources, known areas, oriented complements,
source signs, vertex-density/rotation/seam invariance, explicit holdouts, corrupted
records, bounded memory and failed acquisition cleanup. The original numerical
and generator implementations remain unchanged. No W03/R2 work is authorised or
implemented here.

Sources and conventions: [Bird (2003)](https://doi.org/10.1029/2001GC000252),
[original format documentation](https://github.com/fraxen/tectonicplates/blob/339b0c56563c118307b1f4542703047f5f698fae/original/README.md),
[Table-2 fields](https://github.com/fraxen/tectonicplates/blob/339b0c56563c118307b1f4542703047f5f698fae/original/PB2002_steps_desc.txt),
and [data licence](https://github.com/fraxen/tectonicplates/blob/339b0c56563c118307b1f4542703047f5f698fae/LICENSE.md).

<a id="plate-formation-execution-plan"></a>

## Execution plan for the causal plate-formation correction (18 September 2026)

**Planning-only; no measured gains or new backend selection are claimed.** Stages
3C-R1–R9 and their scientific gates are in the
[maintained tectonics plan](TECTONICS_PLAN.md#plate-formation-implementation-plan).
This section makes their execution requirements explicit, rather than adding a
second scientific roadmap or postponing optimisation until after implementation.

The code-revision and subsequent literature documents were prepared from different
document baselines. This version retains BOTH the implemented PB2002-conditioned
candidate/evidence section and the 15-study causal review below, then gives the
new plan precedence. Old measurements remain observations of their exact source,
not tests rerun during this planning update. No historical test record is edited.

### Stage-specific implementation contracts

| Technique | Where and how used | Correctness/measurement gate |
| --- | --- | --- |
| Native arrays and compact records | R2–R9: shared material/law catalogues and stable IDs; contiguous numerical fields. Batch property evaluation and traversal; avoid Python objects per solver cell or complete per-cohort thermal grids without a physical need. | Explicit array layout/units, independently verified property laws, safe capture and publication, stable material history and masks. Unknown is not zero. |
| Linear-size geometry and sparse connectivity | R1/R7/R8: reuse spherical atlas, conservative bounds and native spatial trees; store each physical edge once and separate output patches from solver partitions. | Indexed queries reproduce exhaustive results, with ambiguous memberships retained. No chart-count or vertex-count dependence of physical metrics. |
| Native structured Stokes and thermal calculations | R4–R6: compile assembly/transport/property kernels; use sparse direct reference at small size and block-preconditioned iterative solves where justified. Investigate geometric/algebraic multigrid for the actual operator. | Compare total cost at matched velocity, pressure, divergence, thermal and integrated-account error. Test pressure null spaces, sharp viscosity contrasts and nonlinear convergence. No unapproved external-package integration or whole-application language rewrite. |
| Reusable setup | R4–R6: reuse mesh connectivity, sparsity, geometric factors and compatible preconditioners; reuse numerical factors only for the same matrix. | Separate pattern identity from numeric operator identity. Changed damage, composition, temperature, dt or boundary terms invalidate the relevant numeric setup. A reused preconditioner still needs residual/iteration checks. |
| Warm starts | R4–R6: previous accepted velocity/pressure and damage state initialise new nonlinear iterations. | Enforce current residual and error criteria. Detect changed solution branch or stagnation; do not accept a previous solution merely because it is nearby. |
| Shared allocation admission | All: existing WorkBudget across state, candidate, nonlinear workspaces, operators, extraction, workers, staging, codec and retained output. Preflight size before materialising. | Coupled peak, cancellation, failed admission and last-reader lifetime tests. Counts are not an RSS cap. Include native/preconditioner/JIT headroom using measured process-tree memory. |
| In-memory versus persistent reuse | R1/R2/R8: prepare immutable reference data, profiles and derived mesh plans once. Keep expensive repeatable results eligible for existing admission; evolving states are primarily checkpoints, not assumed cache hits. | Exact dependencies include case/law/reference versions, initial fields, boundary/forcing history, numerical policy and runtime. No timestamp-only invalidation. Selected calibration and diagnostic settings participate where they change the product. |
| Parallel execution | R1/R5/R9: independent cases/ensembles through existing bounded executor. R4/R6: native parallelism or genuine coupled domain decomposition only after numerical verification. | Do not run adjacent plates or successive times independently. Coordinate inner/outer threads, partition faces, reductions and global pressure coupling. Compare cold transfer/setup plus warm full-call time, not isolated kernel timing. |
| Adaptive space and time | R4–R7: focus support on thermal boundary layers, damage/shear zones and selected slab/ridge structure; split accepted steps at physical/topological events. | Check convergence and regularisation length; resolution must not create the shear-band width or erase small plates. Mesh/frame rotation tests detect preferred numerical directions. Never silently lower order/precision or relax physical error targets under pressure. |
| Conservative transfer | R2/R4/R6/R7: extend W02's separation of extensive inventory and intensive fields to chosen multidimensional thermal/compositional transport. Advect damage with its explicit production/healing equation. | Shared flux once, correct units/densities, source/destination accounts, no heat or material change from remap alone. Damage is not falsely conserved in the presence of its physical source/sink. |
| Incremental boundary work | R7: reuse unaffected topology/metrics where actual dependency changes are local; rebuild when a long-range operator or reorganisation invalidates them. | Coarse bounds never omit relevant contacts. Small field changes can cross a classification threshold: compare incremental with full extraction and retain threshold uncertainty/hysteresis definition. |
| Lossless storage and deduplication | R1–R9: current Zstd, shuffling, compact categories, immutable chunks and direct manifests. Save required composition/damage/thermal/history fields, not just pretty outlines. Active solvers use normal arrays. | Exact round trip, independent backup/cold continuation, corrupt-chunk refusal, restored ownership. Deduplication of changing fields is not promised; shared data are not independent backups. Dictionaries/delta chains only with a measured use case and explicit decode dependencies. |
| Lazy output | R1/R5/R9: plots and optional derived diagnostics on demand, generated from actual stored numerical data. Keep required conservation, acceptance and restart records. | Display resolution cannot create a scientific claim. Release caller-retained arrays; no indefinite in-memory history or drawing one pixel per simulation element. |
| Determinism and identity | All: stable seeded independent streams, fixed law/solver/source IDs and documented reduction order/equivalence. Keep observed geometry and reference files immutable. | Same inputs under the declared reproducibility policy; result origins statistical/kinematic/dynamic remain distinguishable. No automatic switches between physical models. |
| GPU/distributed/other precision | Conditional only after R4/R6 reveal an eligible workload. Native CPU is the initial route; existing geometry charts do not imply a distributed volume solver. | Include device transfers, supported double precision, solver/codec workspace and numerical agreement. Mixed precision, fast-math, surrogates or physical simplifications are new reviewed numerical/model policies, never automatic speed settings. |

### Model extraction is itself an accuracy-sensitive calculation

For a proposed plate interior p, fit the Euler vector to independently solved
surface velocities using area weights:

\[
\widehat{\boldsymbol\omega}_p=
\arg\min_{\boldsymbol\omega}\sum_{i\in p}A_i
\left\|\mathbf v_i-\boldsymbol\omega\times\mathbf r_i\right\|^2.
\]

Report residuals, condition/rank, fitted support, reference frame and excluded
boundary/deformation bands. This is a diagnostic adapted from the PF-C12 research
direction, not a claim that fitting poles validates forces. Prescribed Euler
velocities are suitable unit fixtures only. Thresholds, smoothing length and
minimum resolved region are scientific configuration, not hidden cleanup settings.
The shared atlas remains downstream of the continuum/kinematic scientific state;
it cannot erase significant non-rigid deformation just to complete a polygon map.

### Minimum combined checks in every delivered increment

A new calculation needs: independent reference/invariants; accepted uncertainty
and convergence criterion; unsupported-input refusal; memory/ownership and
cancellation checks; updated identities; cache-fresh agreement where eligible;
restart dependencies; and focused cost/peak-memory evidence for its actual work.
R9 composes these contracts and tests resource pressure, but does not introduce
basic cache or ownership design for the first time. Existing unchanged evidence
is reused rather than repeated as an unrelated broad audit. Scientific realism is
never scored by counting tests, source lines or implemented optimisation names.

No percentage speed/memory improvement is forecast here. Global process resolution
must resolve the selected physics; a later 1 m visual/terrain export is not a 1 m
whole-mantle calculation. Conversely, a coarse calculation cannot claim resolved
microplates or kilometre-scale transforms merely because the display is detailed.

### Primary-method connections

Preserve PF-C01–PF-C15 below. The implementation's required source extraction
focuses on [Tosi et al. 2015](https://doi.org/10.1002/2015GC005807) for the nonlinear
reference suite, [Fuchs & Becker 2022](https://doi.org/10.1029/2022GL099574) and
[Becker & Fuchs 2023](https://doi.org/10.1029/2023GC011179) for the candidate
memory-rheology experiments, [Gouiza & Naliboff 2021](https://doi.org/10.1038/s41467-021-24945-5)
for inherited-structure tests, [Langemeyer et al. 2021](https://doi.org/10.1038/s43247-021-00139-1)
for the limits of ridge/transform/global interpretations, and
[Guerrero et al. 2025](https://doi.org/10.1038/s41598-025-14903-2) for independent
surface-rigidity diagnostics. Web-readable methods were re-examined for this plan;
supplementary inputs/tables not yet extracted remain an R1/R3 task, not silently
transcribed benchmark data. No software installation or numerical run occurred.


<a id="plate-formation-evidence-20260918"></a>

## Plate formation and shape: scientific correction to stage 3C (18 September 2026)

**Status: literature-informed design and acceptance correction, not a replacement
solver or an obtained scientific pass.** The unweighted nearest-site generator is
implemented and geometrically checked. Its original completion statement does not
establish an Earth-like initial plate population. It remains a geometry fixture or
an explicitly chosen statistical initial condition; the scientific selection of a
normal Earth-like generation recipe is reopened. No generator default or numerical
code is changed by this documentation update. W03 implementation remains paused.

The 18 September diagnostic progress package supplied a comparison against an
approximate published count/area relation. It did not finish individual observed
outline comparisons. This literature pass adds causal requirements; it does not
upgrade that comparison into a completed validation dataset.

### Evidence and what it does, and does not, justify

The sources below distinguish observational constraints, process experiments,
kinematic theory and numerical verification. None supplies an exact universal
formula for the shape of a plate. Findings from idealised experiments are not
universal parameter values for Atlas. Access extent is recorded deliberately;
abstract-level findings cannot authorise copying an unseen constitutive law.

| ID / primary work | Finding relevant to Atlas | Modelling consequence and limitation | Content examined |
| --- | --- | --- | --- |
| PF-C01: [Mallard et al. (2016), *Subduction controls the distribution and fragmentation of Earth's tectonic plates*](https://doi.org/10.1038/nature17992) | Spherical convection experiments connect large-plate organisation to slab spacing and smaller fragments to trench-bending stresses. | Test size populations jointly with subduction geometry and the spatial location of small plates. A fitted size histogram is not a fragmentation model. | Publisher abstract, extended-data descriptions and reference trail; not the complete main methods. |
| PF-C02: [Bercovici & Ricard (2014), *Plate tectonics, damage and inheritance*](https://doi.org/10.1038/nature13072) | A proposed damage/healing mechanism produces persistent weak zones whose accumulation helps establish plate boundaries. | Preserve inherited weakness and test its reactivation. This is one mechanistic theory, not a uniquely established law or permission to insert arbitrary noise. | Publisher abstract and editorial description; not the complete constitutive derivation. |
| PF-C03: [Fuchs & Becker (2022), *On the Role of Rheological Memory for Convection-Driven Plate Reorganizations*](https://doi.org/10.1029/2022GL099574) | Their global oceanic-only models preferentially reuse damaged zones and alter reorganisation behaviour. | Distinguish active boundaries from advected inactive weakness. The paper's reduced convective vigour and absence of continents limit direct calibration to Earth. | Accessible methods, results, discussion and data-availability sections. |
| PF-C04: [Becker & Fuchs (2023), *Generation of Evolving Plate Boundaries and Toroidal Flow From Visco-Plastic Damage-Rheology Mantle Convection and Continents*](https://doi.org/10.1029/2023GC011179) | Damage and continental rafts affect multiscale tectonics; undulating divergent margins can evolve into overlapping ridges and microplates. | Do not treat continental structure and weakness as decorations assigned after a final shape. Damaged and undamaged rheologies are alternative experiments, not claims that one parameterisation is settled. | Publisher abstract and accessible discussion/conclusions; complete numerical setup still needs extraction before reproduction. |
| PF-C05: [Gouiza & Naliboff (2021), *Rheological inheritance controls the formation of segmented rifted margins in cratonic lithosphere*](https://doi.org/10.1038/s41467-021-24945-5) | Labrador-constrained thermo-mechanical models connect inherited lithospheric structure to rift segmentation and breakup differences. | Generate or supply initial material/thermal structure before modelling rift localisation. Their specific region and parameter cases are not universal rifting defaults. | Full accessible article including methods and uncertainty discussion. |
| PF-C06: [Gerya (2010), *Dynamical Instability Produces Transform Faults at Mid-Ocean Ridges*](https://doi.org/10.1126/science.1191349) | Numerical models produce transform development from asymmetric plate growth and weakening rather than requiring every offset to pre-exist. | Ridge offsets need process/history and motion compatibility; inherited faults are not the sole permissible origin. | Publisher abstract and accessible article page; supplement not reproduced. |
| PF-C07: [Langemeyer, Lowman & Tackley (2021), *Global mantle convection models produce transform offsets along divergent plate boundaries*](https://doi.org/10.1038/s43247-021-00139-1) | Viscoplastic spherical convection develops segmented divergent boundaries distinct from continuous convergent margins. | Evaluate morphology separately by boundary regime. Their passive-spreading examples show that a deep plume need not sit beneath every ridge; their convergent downwellings are not realistic one-sided subduction. | Full accessible results, equations and methods. |
| PF-C08: [Crameri et al. (2012), *A free plate surface and weak oceanic crust produce single-sided subduction on Earth*](https://doi.org/10.1029/2011GL050046) | Modelled free-surface behaviour and weak crust influence subduction asymmetry and trench curvature. | Convergence or a curved outline alone does not select polarity or establish a correct slab model. | Publisher abstract and accessible article introduction. |
| PF-C09: [McKenzie & Morgan (1969), *Evolution of Triple Junctions*](https://doi.org/10.1038/224125a0) | Kinematic compatibility distinguishes junctions that can maintain their configuration during plate motion from those that cannot. | Require closure of relative velocities and compatibility of junction motion with the incident boundaries. Do not force every junction to 120 degrees. | Publisher abstract; classification tables not transcribed. |
| PF-C10: [Morra et al. (2013), *Organization of the tectonic plates in the last 200 Myr*](https://doi.org/10.1016/j.epsl.2013.04.020) | Reconstructed small and large plate populations have different statistical behaviour, with large-plate organisation changing through time. | Validate ensembles and different histories, not one fixed count or one modern histogram; treat reconstruction uncertainty separately. | Publisher abstract/highlights and authors' related preprint abstract; not numerical tables. |
| PF-C11: [van Heck & Tackley (2008), *Planforms of self-consistently generated plates in 3D spherical geometry*](https://doi.org/10.1029/2008GL035190) | Changing rheology in a dynamic spherical model produces materially different tectonic regimes and geometries. | A convection calculation is not automatically Earth-like. Check parameter sensitivity, resolution and rotational invariance rather than equating physics code with realism. | Accessible full article, including assumptions and discussion. |
| PF-C12: [Guerrero et al. (2025), *A rapid tectonic plate reorganization event driven by changes at subduction locations in a mantle convection model*](https://doi.org/10.1038/s41598-025-14903-2) | Evolving model plates are assessed using fitted Euler vectors; reorganisation is connected to changed subduction locations. | Measure agreement of a derived intraplate velocity field with rigid rotation. Agreement is tautological if velocities were assigned from those same poles. | Full accessible article, including plate identification and kinematic diagnostics. |
| PF-C13: [Moulin & Jonsson (2025), *Persisting influence of continental inheritance on early oceanic spreading*](https://doi.org/10.1038/s41598-025-93942-1) | Observations in a plume-assisted setting support inherited influence extending into early spreading. | Do not reset inherited structure automatically at continental breakup. The reported setting does not justify a universal plume requirement. | Accessible abstract, results/discussion and observational methods. |
| PF-C14: [Tosi et al. (2015), *A community benchmark for viscoplastic thermal convection in a 2-D square box*](https://doi.org/10.1002/2015GC005807) | Independent codes compare nonlinear thermal-convection regimes and resolution behaviour. | Reproduce an applicable numerical benchmark before using a new rheology to support causal claims. Passing a 2-D test is not spherical or geological acceptance. | Accessible benchmark methods/results; reference numbers are not copied into a new fixture here. |
| PF-C15: [Hasterok et al. (2022), *New maps of global geological provinces and tectonic plates*](https://doi.org/10.1016/j.earscirev.2022.104069) | Geological provinces, plate models and deformation zones use multiple observational constraints. | Separate geological provinces from rigid-plate identities and accommodate distributed deformation. It is an observational map compilation, not a formation simulator. | Authors' institutional-repository abstract; datasets not downloaded or numerically compared here. |

### Required scientific state before a shape can be called process-informed

A replacement must jointly specify (or explicitly derive) the thermal and
mechanical background, continental versus oceanic structure, supported inherited
weak zones, boundary regimes, relative motion and history. The existing stage-4
schema and material catalogue are useful inputs; room-condition mineral values
are not a creep/yield law. Missing stress, slab or damage information must remain
missing, not be manufactured by adding an unlabeled random field.

For a mature initial world, choose a declared starting epoch. It need not simulate
planet formation from a magma ocean. A candidate can be an evidence-constrained
statistical initial state, a replayed kinematic history, or a state generated by
validated dynamics. These are different scientific claims, not interchangeable
backends. State the mode in the recipe and its provenance.

The intended causal loop is:

**initial thermo-compositional structure and inherited weakness -> applied or
computed forcing -> localised deformation and boundary motion -> material and
weakness history -> changed forcing and subsequent geometry.**

Plate regions are the relatively coherent moving interiors of that network, not
independently drawn polygons later decorated with arbitrary boundary labels.
This is an Atlas modelling requirement inferred from PF-C01--PF-C13, not a claim
that this whole loop is implemented.

### Minimum mathematical and numerical contracts

For a declared rigid kinematic plate p, use the existing relation

\[
\mathbf v_p(\mathbf r)=\boldsymbol\omega_p\times\mathbf r.
\]

At the same boundary location, relative velocity is

\[
\Delta\mathbf v=(\boldsymbol\omega_R-\boldsymbol\omega_L)\times\mathbf r,
\quad v_n=\Delta\mathbf v\cdot\mathbf n,\quad
v_t=\Delta\mathbf v\cdot\mathbf t,
\]

where n points from the declared left owner to the right owner. Keep convergence,
divergence and tangential motion separate; zero-speed classification needs a
physical uncertainty band, not a tolerance borrowed from geometric predicates.
Negative opening does not choose which plate subducts. A sharp boundary also does
not stand in for every diffuse deforming zone.

At a junction, relative velocities formed at one location obey
v_AB + v_BC + v_CA = 0. A junction velocity must additionally satisfy the normal
motion constraints of all incident boundary segments. Algebraic closure alone
is not a dynamical stability test; incompatible or transient junctions require
an explicit evolution/reorganisation treatment.

For a dynamical claim, use the selected momentum/continuity/thermal formulation
and an explicitly sourced constitutive law. As an illustrative *model family*,
not a newly selected Atlas closure, incompressible Stokes flow satisfies

\[
-\nabla p+\nabla\cdot(2\eta\dot{\boldsymbol\epsilon})
+\rho'\mathbf g=0,\qquad \nabla\cdot\mathbf v=0.
\]

Here p is the dynamic-pressure convention and rho-prime is the buoyancy density
relative to the declared reference, rather than a second mass ledger. Energy advection/diffusion and heating close the temperature field.
The actual pressure convention, viscosity/strength law, regularisation, boundary
conditions, internal heating and basal forcing must be fixed in the case. No
abstract-level paper citation supplies missing constants or numerical settings.

Damage memory, when used, needs an advected state plus separately specified
production and healing terms. A static spatial-noise texture is not equivalent.
Choose either a calibrated reduced damage law or a particular microphysical
formulation; do not combine unrelated papers' laws or coefficients silently.

Rigid-plate diagnostics should fit omega to independently calculated/supplied
interior velocities and measure the residual, together with strain localisation.
A perfect fit to v=omega cross r assigned by construction only checks plumbing.

### Validation required before promoting a replacement

1. **Geometry:** retain whole-sphere coverage, shared-edge and junction invariants,
   patch-layout independence, pole/seam checks and the existing error thresholds.
2. **Observed morphology:** compare individual outlines at declared angular/physical
   resolution; area distributions, shape compactness, elongation, boundary turning
   and adjacency must not depend on arbitrary vertex density. Count uncertainty in
   small plates and diffuse regions. PB2002 is a reference, not a unique definition
   of Earth's plate inventory or a prescribed target for every synthetic world.
3. **Process-conditioned morphology:** compare divergent segmentation, convergent
   curvature, inherited rift orientations and small-plate locations near active
   margins separately. Globally scattered fragments with the right histogram do
   not pass this test.
4. **Kinematics and history:** check interior coherence, boundary motion components,
   admissible junction evolution, material birth/retirement accounts and persistence
   of inherited features. Use explicit time/epoch and thermal history.
5. **Numerics:** quantify resolution/time-step and regularisation dependence,
   invariance under rigid rotation, sensitivity to initial conditions, and effects
   of numerical remeshing. Artificial cracks following the grid do not pass.
6. **Independence:** separate calibration cases/parameters from withheld test cases.
   Keep unsuccessful candidates and the reasons for rejection. Do not tune on a
   single observed map and call the same-map fit independent validation.

The immediately usable references are the existing diagnostic code plus the
paper requirements above. Individual PB2002/Hasterok polygon comparison and a
reproduced physical-formation benchmark remain open; this update reports no new
measurements or passing scientific thresholds.

### Optimisation without changing the scientific question

Retain the existing shared spherical graph, compact material IDs, native batches,
bounded spatial indexes, memory budgets, lossless storage and verified identities.
Refine geometric or mechanical support where the selected process needs it, with
explicit convergence and cross-region exchange. A smaller *validated* physical
model is legitimate; merely labelling a coarse calculation accurate is not.

Preserve sparse inherited features and share immutable reference definitions.
Cache an operator only when its geometry, rheology, constraints and discretisation
match; evolving damage invalidates affected setup. Parallelise independent cases
or legitimate domain-decomposition work, not mechanically interacting plates as
isolated jobs. Use analytic kinematics where that is the claimed model. Never use
faster damage healing, reduced strength, noise, or skipped small plates as
undocumented performance switches.

**Decision:** do not promote weighted Voronoi, arbitrary agglomeration or decorative
edge perturbations as the scientific fix merely because they look irregular. They
remain possible empirical candidates only with explicit assumptions and the
relevant observed tests. Causal generation requires a verified process model; it
cannot be obtained by renaming a statistical prior.

This research update changes only the two maintained documents. No new numerical
implementation, runtime dependency, full-world simulation or W03 implementation
is delivered. The existing generator code and its historical test records are
unchanged; stage-3C scientific acceptance remains open.

<a id="plate-layout-science-correction"></a>

## Stage 3C scientific correction — 18 September 2026

**Stage 3C was complete as a shared-geometry generator, NOT as an Earth-like
plate-layout model. Its scientific acceptance is reopened.** The old nearest-site
API remains a reproducible mathematical fixture and authored Voronoi route; its
unchanged numerical meaning must not be relabelled geological evidence.

This corrective increment adds `PlateLayoutSettings` / `generate_plate_layout`:
a **candidate**, not a newly certified default. A fine shared spherical subdivision
is grouped by connected geodesic cuts using the published PB2002 rank/area spectrum.
This permits unequal, connected, concave owners without independently drawing and
repairing their borders. The candidate records calibration, unresolved shape and
motion gates, reference identity and generating resolution with every result.
`require_geological_layout_acceptance` explicitly refuses a scientific acceptance
claim that the supplied evidence does not establish. It is not a bypassable
user-metadata flag. No code claims a validated Earth-like production route exists.

The prior is intentionally conditional: for N<52, the largest N published areas
are renormalised; omitted small plates are not individually reconstructed. This
is a modelling choice, NOT a measurement of another planet or an invariant
historical Earth distribution. Plate count above 52 requires another declared
prior. Original geometry-fixture support for other counts is unchanged. A global
L1 area check AND per-plate relative check reject insufficient resolution; the
algorithm never conceals a lost microplate inside a small global average error.
Coarse support can fail these checks. There is no automatic memory-driven loss of
accuracy and no claim that a successful coarse prior resolves detailed boundaries.

### Evidence and what it does not prove

* **Calibration:** all 52 area values from Bird (2003), Table 1, retained at their
  printed precision. Their slight sum discrepancy from 4*pi is tabulation rounding.
* **Independent outline challenge:** the complete Cocos plate ring, 157 edges plus
  the repeated closure point. Spherical area agrees with the separately printed
  Table 1 area. This tests genuine concavity, perimeter and turning; it is one
  withheld small-plate outline, NOT the entire Earth's morphology distribution.
* **Independent motion sample:** the original signed AF/AN Euler poles and 12
  original boundary steps reproduce the published opening/right-lateral values
  within their rounded source precision. The sign convention is explicit.
* **Generated motion diagnostic:** supplied angular velocities produce boundary
  motion with an analytic great-circle integral for each rigid plate's closed
  area-rate account. This is rigid kinematic consistency, not force balance,
  subduction polarity or an evolved plate history.

`plate_outline_cycles` ignores same-plate patch seams; simple-ring diagnostics
refuse pinched ownership cycles rather than choose an arbitrary continuation.
The separate simple-outline metric requires a conditioned hemisphere; global
area/perimeter/adjacency diagnostics still operate on the complete atlas.
Perimeter and nonzero turning are invariant to adding points on an existing arc.
A finer GENERATING subdivision changes the prior; it is not mere display zoom.

### Execution and storage

Three native sparse shortest-path solves per cut, compact dual adjacency and
bounded connectedness checks replace dense feature-pair comparisons. Geometry
construction reuses the audited native generator and global coverage checks.
Candidates, queries and stored state use existing budgets/immutable geometry and
ArrayStore. There is no new scheduler or general cache. Parent support geometry
is charged while the derived atlas is built. Native library allocations remain
estimated, not a process RSS guarantee. Source and reference definitions participate
in the existing ExecutionContext. The old physics, storage formats, data library,
authored geometry routes and numerical defaults are retained.

### Obtained evidence for this corrective increment

[Full regression](../evidence/plate-layout-tests.json): **1,134 passing tests**, all
1,091 earlier tests plus 43 new checks, zero failures/errors/skips. All prior test
sources, physical fixtures and tolerances are byte-for-byte unchanged. Checks
include exact octant/Gauss–Bonnet identities, complete source-outline area,
source motion signs/units, area resolution refusal, connectedness, sphere coverage,
immutable queries, source mutation, stage-4 geological attachment, and cold/backup
restoration. Source inventory: 84 files, unchanged during the final run.

[Three preselected seeds](../evidence/plate-layout-comparisons.json), 12 plates and
512 support cells: median rank-area L1 mismatch against the DECLARED largest-12
calibration prior is 0.32368058 for the Voronoi fixture and 0.00784261 for the candidate.
This is a calibration improvement, NOT a percentage improvement in geological
realism. Each configuration was timed once per seed, not a robust speed benchmark.
The new finer construction is slower and retains more geometry; those costs are
reported without a claim of end-to-end improvement. A coarse 52-plate request is
explicitly refused when small plates cannot meet the relative area bound.

The source Cocos outline area is 0.072230194879 sr,
consistent with the separately printed 0.07223 sr. The largest difference in the
12-step AF/AN comparison is 0.06247472 mm/a, within
its source-specific 0.2 mm/a rounding allowance. These calculations do not validate
arbitrarily generated motion or the complete population of plate outlines.

Actual geometry diagrams: [old fixture](../evidence/plate-layout-voronoi.png),
[connected candidate](../evidence/plate-layout-candidate.png), and
[area calibration](../evidence/plate-layout-area-spectrum.png). These are plots of
model data, not an artist's impression or a finished globe viewer.

Tested on Linux / CPython 3.13.5 with the existing declared dependencies. Windows,
full plate-morphology acceptance, physical histories and world-scale performance
are unverified. No installation, origin publication, prior-store migration or
W03 implementation occurred.

### Remaining scientific work

The connected candidate is more flexible and better area-calibrated than the old
one-site/one-plate fixture. **It must not be promoted merely because it looks more
irregular.** Scale-matched multi-plate outline and boundary-type/kinematic evidence,
including deformation-zone treatment and reference-model variability, is still
needed before a validated Earth-like default can be claimed. This increment
records that open gate rather than changing the definition of “complete”.
No W03 work or general optimisation pass is performed. The old dated delivery
summaries below remain historical; this section controls the present status.

Sources: [Bird 2003](https://doi.org/10.1029/2001GC000252),
[original digital documentation](https://github.com/fraxen/tectonicplates/blob/master/original/README.md),
[curator and data licence](https://nordpil.com/resources/tectonic-plates-gis-data/index.html),
[time-dependent hierarchy study](https://arxiv.org/abs/1011.2752), and
[alternative finite-area statistical model](https://arxiv.org/abs/cond-mat/0202320).
PB2002 numerical data are credited to Peter Bird; curated conversion to Hugo
Ahlenius/Nordpil and GeoJSON preparation to csterling, under the Open Data Commons
Attribution Licence 1.0. No third-party implementation is copied. Source selectors
and blob identities are embedded in `plate_reference.py`.

<a id="w01-stage4b-delivery"></a>

## W01 stage 4B — reference materials, conditions and mixtures (17 September 2026)

This increment populates the stage-4 descriptions with a bounded offline reference
library: **67 profiles**, **7 declared matrix recipes**, and **11 source/method
records**. It is not W03 thermal evolution, W07 material mechanics or a validated
planetary composition model. It builds on the stage-4 delivery; the copy-ready
package is cumulative from `ecac085fb64b7bd862580f996c61d5bf7c9088e2`.

| Concern | Implemented decision and scope |
| --- | --- |
| Breadth | 39 named bulk-rock profiles across main igneous, metamorphic, sedimentary and ultramafic families; 25 mineral/endmember profiles; fresh water, seawater and ice. This is not every mineral, metamorphic facies or arbitrary composition. |
| Evidence | Property-level source and table/section, original unit, printed range, selection meaning and temperature reference. Literature ranges are not calibrated distributions or matched specimens. No paper text/images or third-party implementation is bundled. |
| Scientific eligibility | `missing`, `require`, `unresolved` and condition-specific coverage. 44 profiles have rho/cp/k together at nominal 293.15 K; others retain useful partial/different-temperature data. No pressure law or instantaneous expansion law is inferred. |
| Expansion | 30 interval secants retained separately. Ordinary scalar-alpha export refuses to mislabel them. No density-temperature model is supplied merely by possessing a mean expansion value. |
| Mixtures | Explicit mass/volume fractions, additive density/heat inventory, named pore fluid, grain/bulk distinction. Conductivity bounds are default; geometry-dependent estimates require explicit selection. Unknown radiogenic input is never zero. |
| Radiogenic inputs | Two sourced shale-population values and an explicit natural-present-day U/Th/K conversion. No universal heat-production property for each rock name, isotope history or assumed zero mantle heating. |
| Existing geology | Normal stage-4 material/source records plus exact layer-binding verification. Conflicting properties or changed library versions are refused instead of overwritten. Cohort origin/formation metadata remain independent. |
| Memory/layout | One immutable bounded catalogue per process; compact numeric table and known-value mask, integer map codes, bounded native gather. Source strings/objects are not copied per cell. Owner accounts retained table/catalogue; admission covers conversion/gather/restore work. |
| Computation | Convert reference units and compile a table once; reuse it for many native gathers. Small scalar mixture calculations use accurate sums. No new compiler, worker pool, GPU or scientific-library dependency is justified for metadata. |
| Identity | Raw data are source bytes, included in existing source checks. Loaded library routines and data/unit constants participate in the existing ExecutionContext. Complete manifests and prepared-table identities include data interpretation and conditions. |
| Persistence | Canonical library JSON is a chunked byte dataset through existing Zstd/deduplication. Actual sources/data restore with the library, not just an installed-version dependency. Corruption, malformed records, oversized inventories and wrong bindings refuse. No external fetch during generation. |
| Reuse | Repeated library lookup shares the immutable catalogue; prepared tables are caller-owned, no global unbounded table cache. Repeated snapshots deduplicate exact payload. A new data revision gets a new identity, not repinned old records. |
| Default accuracy | Unsupported scalar conductivity is returned as bounds, not a fabricated point. Same-temperature eligibility is checked, not assumed. A partial reference remains partial even when convenient extrapolation would let a downstream solver run. |

**Obtained checks:** all **1,091 tests (1,005 prior + 86 new)** pass on the recorded
Linux environment without failures/errors/skips. New cases check independent
source anchors and exact-rational synthetic mixture expectations, ranges/unit
conversion, secant/temperature refusal, porous/bulk separation, explicit assay
units, table masks, immutable serialisation, bounded/cancelled/concurrent gathers,
source/default changes, case binding, saved libraries/cases and cold independent
restoration. All earlier tests/fixtures/tolerances remain unchanged. No broad
performance pass, simulator run, dependency installation or Windows test is implied.

The [coverage record](../evidence/w01-earth-materials-coverage.json) reports actual
payload/table/store sizes and the complete capability/missing-field map; they are
not a whole-run RAM estimate or a claimed physical error bound. The method is
native table gathering by construction; no unmeasured speed-up percentage is claimed.
See [tests](../evidence/w01-earth-materials-tests.json) and
[reference equations/source interpretation](FOUNDATIONS.md#w01-earth-materials).

**Next:** W01 stage 5 sampling uses these definitions and must preserve their
basis/condition flags. W03's temperature/compaction laws and W04's load conversion
remain separate; no supported hot-rock law is silently added by a room-condition
constant. No new general plan is created, and W03 remains paused.


<a id="w01-stage4-delivery"></a>

## W01 stage 4 — compact geological descriptions (17 September 2026)

This delivery supplies typed input descriptions and their validation, not numerical
sampling/evolution. The stage-3C ZIP is its immediate source baseline; the copy-ready
update remains cumulative from remote `ecac085fb64b7bd862580f996c61d5bf7c9088e2`.
Accuracy-first numerical defaults and all previous physical kernels are unchanged.

| Concern | Selected implementation and completion boundary |
| --- | --- |
| Representation | Immutable, slotted records containing SI scalars/tuples; shared material, cohort and thermal catalogues. Constant bulk layer stacks vary laterally through explicit provinces. No per-cell Python object engine. |
| Plate/geology separation | Geological provinces may select plates, regions, or independent geometric pieces. A continental/oceanic classification is never inferred from a plate label or random seed. |
| Units and uncertainty | Positive finite dimensions and appropriate property ranges; solid-volume fractions distinguished from mass/bulk fractions; formation separate from cooling age. Unknown values carry reasons and survive persistence. |
| Precedence | Caller supplies a complete highest-first province order and one explicit whole-domain background. Candidate resolution uses prepared ranks, O(k log k) for k matches, not an O(P) scan of all P provinces. All matches remain in the selection receipt. |
| Overlapping structures | Faults coexist. Weak zones coexist or use a named explicit override order; no automatic factor multiplication or duplicate deformation contribution. Corridor width is an exact distance specification, not a new polygonal buffer. |
| Geometry reuse | Immutable stage-2 objects, regional networks and global atlases are referenced, not regenerated. Regional containment uses existing native predicates; out-of-domain supplied geometries are refused rather than repaired. A corridor's line must lie in-domain; its predicate is evaluated only for in-domain queries at stage 5. |
| Memory | Preflight counts catalogues, nested layers/components, strings, profile samples and geometry bytes. Shared WorkBudget charges construction/restore/save workspace; caller owns retained case/geometry objects. Explicit byte/record limits, not arbitrary unlimited metadata. |
| Persistence/compression | ONE ArrayStore snapshot includes all geometry and topology dependencies. Canonical description bytes are a chunked numeric byte dataset, so profile/description text benefits from current Zstd profiles. Geometry aliases use one payload; descriptors refer by identity. |
| Identity and reuse | Complete case ID includes topology, properties, thermal history, evidence, depth/epoch frame and precedence. Catalogue order is canonical; physical layer/profile/precedence order is retained. Source/instruction context includes both new modules. A definition identity is not scientific acceptance or a hostile-runtime signature. |
| Concurrency | Immutable descriptions support concurrent reads. Existing store transactions, cancellation and shared budgets handle writes. No new pool, cache, native solver or GPU path for small declarative records. |
| Restoration | Validate canonical definition, inventories, shapes/dtypes and byte limits; rebuild and verify geometry/topology; reconstruct typed records and compare full identity. Missing or corrupt data is not a cache miss or permission to reroll the planet. |
| Numerical choices | No new evolution approximation. New fraction/stack consistency thresholds are explicit in the case fixture; previous numerical/geometric tolerances are unchanged. No renormalisation, smoothing, snapping or hidden lower accuracy. |

### Supported scope and outstanding work

A stage-4 case can retain unresolved facts; it reports them and never fills them.
A successful description check means internal structural consistency, not that its
rock properties/thermal assumptions were measured or physically calibrated. Source
links/checksums are declared provenance, not fetched/authenticated evidence.

Tabulated profiles specify linear interpolation with no extrapolation. Half-space
initialisation records explicit cooling-start time/parameters, independent of cohort
formation. Stage 5 must evaluate those profiles at actual locations, honour layer
arrangement, calculate mixed-cell quantities and check spatially varying property
validity. W03 thermal evolution, heat sources, compaction and mechanical response
are NOT executed here; W03 remains paused.

Initial layer thickness is constant within an assigned column profile; multiple
provinces describe lateral changes. Arbitrary dipping layer-interface functions and
volumetric fault meshes are not silently approximated by these scalar records.
Dip/depth fault metadata and weakness modifiers are explicit declarations, not slip,
force balance or a calibrated failure law. No full W01 completion claim is made.

### Verification

The complete regression run passed **1,005 tests** (915 existing + 90 new), with
no failures, errors or skips. Linux/CPython 3.13.5, NumPy 2.3.5, SciPy 1.17.0,
Numba 0.65.1 and Shapely 2.1.2 were already installed; no dependencies were added.
Windows execution and physical calibration remain unverified.

The [test record](../evidence/w01-stage4-tests.json) and new
`test_w01_geological_description.py` cover complete/missing catalogues, explicit
units and unknowns, layer/porosity/mixture consistency, independent formation/cooling
times, frame/coverage refusal, generated-planet attachment, deterministic precedence,
immutable ownership, source-context changes, compression/deduplication, cancellation,
failed writes, corruption, fresh-process and independent-backup restoration.
Tests also assert that constructing a description does not call the thermal solver,
transport, or point-membership sampler. All prior fixtures/tests remain unchanged.
No speed percentage or global geological acceptance is claimed for metadata work.

Primary implementation references: the existing Atlas stage-2/3/3B/3C/W02 contracts;
[Python dataclasses](https://docs.python.org/3.13/library/dataclasses.html) for frozen
record semantics, and [Shapely geometry immutability](https://shapely.readthedocs.io/en/2.1.2/release/2.x.html)
for shared native geometry. Plain frozen dataclasses alone do not freeze arbitrary
contained arrays; these records prohibit mutable nested payloads and reuse existing
bytes-backed geometric objects.

<a id="w01-stage3c-delivery"></a>

## W01 stage 3C — automatic conforming initial partitions (17 September 2026)

**Implemented and tested on Linux.** Seeded geometry uses a declared unweighted
spherical Voronoi prior. Native generation constructs its shared vertex/edge
registry first, derives charts afterwards and independently validates the atlas;
no manual stitch, repaired polygon soup or desired mountain outline is involved.
The authored-site preparation API never changes inputs to find an easier result.

### Adopted execution choices

| Decision | Selected implementation and boundary |
| --- | --- |
| Global geometry algorithm | One native Qhull calculation for >=4 sites, followed by sparse incidence traversal. No dense pairwise distance matrix, repeated polygon intersection, or angle-sorted dual rings. Explicit 1/2/3-site constructions avoid pretending a degenerate 3D hull is well-defined. |
| Shared topology | Each junction is created once from a canonical site triple, and shared arcs come from primal-edge incidence. Derived local faces refer to that registry. Full stage-3B manifold/coverage checks remain on. |
| Prepared reuse | `PlanetaryPartitionPlan` holds immutable sites, vertices and ring definitions. Repeated patch construction does not rebuild the hull. Existing atlas indexes handle repeated spatial queries; no new general cache or search framework. |
| Working patch default | Retain conditioned cells when possible; fan only when needed. All-triangle layout is explicitly available for numerical/layout checks. This changes representation cost, not physical plate geometry or precision. |
| Reproducibility | Named deterministic seed-to-direction mapping; sorted IDs and adjacency traversal. Candidate failures are bounded and counted. No global RNG, time, worker count or scheduling-dependent draws. Exact cross-backend equality is not asserted. |
| Resources and cancellation | Bounds precede RNG/native allocation; one serial native hull per candidate and finite native-memory allowances. Cancellation is checked between phases/loops; a running native hull is not forcibly terminated. Budget/cancellation/audit failures are not permission to reroll. |
| Persistence | Existing Zstd/deduplicated atlas snapshots retain resolved sites, source/runtime identity and full canonical geometry. Corruption is not repaired by regenerating another world. Cold restoration validates topology without a parent-chain dependency. |
| Parallelism | A single closed partition is globally coordinated. No per-plate pool is added; independent calls are concurrency-tested against shared budgets. Larger workloads may justify a measured scheduler decision later, not thread count for its own sake. |
| Accuracy | Binary64 native geometry; no QJ, snapping, fast-maths, lossy coordinates, relaxed prior tolerances or raster substitution. The prior is not an Earth plate-size or force model. |

Near-duplicate sites, non-spanning >=4-site hulls and unresolved cofacets are rejected.
For generated data the full candidate is redrawn within the explicit limit, with
the accepted attempt and reasons retained; this conditioning is a declared prior.
Authored diagrams with these conditions fail explicitly rather than being modified.
A supported whole-planet layout is not a claim that arbitrary input is repairable.

The two layout modes share an intrinsic `partition_id` and physical interplate
edge IDs. Extra triangles are same-owner seams, excluded from plate adjacency
and perimeters. `repatch_planetary_partition()` uses saved sites, not a new seed
or an untracked stochastic draw. Repeated in-process layouts should use the
prepared plan instead of reconstructing it from an atlas.

### Obtained verification and bounded costs

[Fresh regression evidence](../evidence/w01-stage3c-tests.json): **915 passes,
847 preceding checks plus 68 new checks**, no failures/errors/skips. All prior
test sources, fixtures and tolerances are unchanged. The new suite checks direct
nearest-site predictions, analytical whole-sphere/hemisphere/lune and symmetric
areas, coverage/junction invariants, patch changes, native/reference geometry
comparison, deterministic order, invalid inputs, failure/cancellation, shared
budgets, immutable metadata and compressed/fresh-process/backup restoration.

[Focused measurements](../evidence/w01-stage3c-measurements.json), five warmed
observations per operation, one native-library thread. Full generation includes
the seeded candidate and complete atlas validation, not merely the hull:

| Plates | Generate and validate | Prepare shared topology | Auto layout from plan | Triangle layout from plan | Patches auto / triangles |
| --- | --- | --- | --- | --- | --- |
| 12 | 28.49 ms | 2.14 ms | 26.80 ms | 108.50 ms | 12 / 60 |
| 64 | 155.35 ms | 10.35 ms | 144.50 ms | 669.35 ms | 64 / 372 |
| 128 | 303.66 ms | 20.90 ms | 308.79 ms | 1396.29 ms | 128 / 756 |

The first 12-plate generation took 245.86 ms including lazy
native setup inside the call; this is separate from the warmed observations.
The maximum measured auto/fan area difference was below 5e-16 sr. Query ownership
also matched an independent site-dot-product calculation. Different layouts have
different amounts of representation work; these timings are not a speed-up against
an earlier planet generator (there was none), or a whole-world physics forecast.
The script is `tests/measure_w01_planetary_generation.py`. It does not revive the
skipped broad baseline item. Accounted memory and retained estimates are not RSS;
caller-owned plans, returned atlas data and indexes must retain owner reservations.

No additional dependencies were installed or added: the existing SciPy native
hull/tree, NumPy and Shapely/GEOS stack is reused. Runtime identity now includes
the Qhull extension. Existing physical kernels and storage formats are untouched.
Copy-ready delivery is on the stage-3B source over remote `ecac085f…`; nothing is
pushed. Windows and physical validity remain unverified. **Next: W01 stage 4;
stages 4–8 remain open and W03 remains paused.**

<a id="w01-stage3b-delivery"></a>

## W01 stage 3B — closed planetary patch geometry (17 September 2026)

**Implemented and mathematically checked on Linux:** a closed, conforming static
spherical atlas, using the existing stage-2 primitives and stage-3 side conventions.
The global geometry no longer needs to fit a single hemisphere chart. Local faces
still use conditioned charts. Every source seam uses explicit shared vertices and
matching subdivisions, rather than automatic nearest-neighbour welding.

### Execution and representation decisions

- `SphericalAtlas` holds one canonical coordinate per global vertex and one shared
  edge with two opposite owners. Vertex links, connectedness, Euler characteristic
  and independent area sums validate closure without an all-faces intersection
  matrix. Perimeter and adjacency ignore same-owner patch cuts. Region/plate IDs
  are independent of patch IDs, including owners spanning more than a hemisphere.
- Existing stage-3 networks attach through `stitch_spherical_networks()` and explicit
  local-to-global vertex bindings. Each attachment is checked against the supplied
  canonical geometry; a fixed 64-epsilon angular round-off allowance and observed
  errors are recorded. Larger disagreement is refused. No source files or shapes
  are silently modified. Repeated attachment preserves already-unit coordinates
  rather than normalising them repeatedly and drifting their byte identities.
- Areas and edge frames use canonical spherical directions. Working-chart changes
  leave the geometry identity and edge metrics unchanged. A changed mesh/patch
  subdivision is a changed representation identity, not new physical geology.
- Point membership uses reusable **radius-bucketed spherical caps and native SciPy
  cKDTree queries**. Tight cap centres are chosen only when all face vertices lie
  in the resulting convex hemisphere cap. Otherwise the declared chart cap is
  retained. Native vector operations prune candidates; existing spherical polygon
  predicates decide final membership. Approximate tree search is not enabled.
- A preliminary cap implementation used overly broad common-chart centres and
  per-candidate Python arithmetic. It was replaced before delivery by tighter
  per-face bounds and batched chord comparisons. Candidate pruning must improve
  total query work, not merely make the reported candidate count smaller.
- Queries return all boundary owners, deduplicating repeated hits from patches of
  one owner. No 'first plate wins' or nearest-owner fallback is supplied. Index
  construction and active queries obey the existing shared memory admission.
  A retained index holds its reservation until closed; atlas payloads and returned
  arrays remain owner-side costs. Native-memory allowances are not an RSS cap.
- Source, material and geometry identities remain separate. The existing execution
  context now includes this module and the SciPy spatial native binary. Contexts
  retain their documented process-lifetime/runtime assumptions, not a security seal.
- Existing `ArrayStore` saves the canonical numeric registry with the complete
  static definition. Identical registries deduplicate across chart-only changes.
  Native indexes rebuild on restore and are never pickled as trusted structures.
  No new cache, scheduler, codec, automatic history cleanup or dependency is added.

### Checks and measured behaviour

[The fresh verification record](../evidence/w01-stage3b-tests.json) reports
**847 passing checks: all 756 previous tests and 91 new tests**, no failures,
errors or skips. It records 67 source/test/case hashes before and after execution.
Previous fixture/test sources and their tolerances are unchanged. New coverage
includes closed octant/cube/random triangulated spheres; large, holed, disconnected
and whole-sphere owners; chart/rotation/refinement invariance; invalid seams/folds;
short arcs; frame reversal; input immutability; budget/cancellation/concurrency;
explicit stage-3 bindings; corrupted objects; backup and fresh-process restoration.

The additional rotated-seam check found a coordinate re-normalisation drift during
development. It was corrected and three successive restitch/rebuild tests now keep
the canonical coordinate and shared-edge bytes stable. This did not require changing
old angular tolerances or widening the source-attachment band.

[Focused measurements](../evidence/w01-stage3b-measurements.json) compare the same
ownership query on **216 spherical patches and 2,048 query directions**, five
paired alternating-order warmed repetitions, without other test runs in progress:

| Quantity | Obtained result |
| --- | --- |
| Exhaustive feature/query pairs | 442,368 |
| Accepted cap candidates | 3,847 (99.1% fewer) |
| Median exhaustive query | 153.00 ms |
| Median indexed query | 27.18 ms (82.2% less time) |
| Full atlas construction, one observation | 396.81 ms |
| First index setup, including native spatial import, one observation | 212.15 ms |

All reported owner pairs matched exactly. The retained atlas estimate was
984,910 bytes, not a measured process peak.
Construction/import costs are not hidden inside warmed speed claims. Results do
not establish whole-world generation throughput, material-physics performance or
Windows compatibility. The repeatable focused script is
`python -B tectonics/tests/measure_w01_spherical_atlas.py`; it runs only the named
synthetic geometry workload, not a new general benchmark programme.

**Completion boundary:** stage 3B supplies static closed spherical geometry for
explicit conforming patch meshes, not automatic repair/tessellation of unrelated
polygon inputs. General evolving spherical W02 transport, generated plate motion,
forces and geology remain separate. W01 stages **4–8** are still outstanding.
W03 is not implemented by this increment. The two existing maintained documents
remain the authorities; this delivery is copy-ready, not remotely published.

References and the structural acceptance reasoning are in the existing
[scientific notes](FOUNDATIONS.md#w01-stage3b). S2/CGAL were method references only.

<a id="w01-stage3-delivery"></a>

## W01 stage 3 — static shared boundaries (17 September 2026)

This delivery builds on the **corrected** stage-2 source, not the unrelated W03
attempt. It implements the supported static geometry/side/junction responsibilities;
W01 stages 4–8, generated forcing, moving spherical topology and physical/geological
acceptance remain separate. No numerical transport/thermal kernel is changed.

### Implementation and accuracy

`BoundaryRegion` pairs an immutable areal geometry with separate region and plate
identities. `build_boundary_network` requires complete nonoverlapping coverage in
one identified plane or a declared spherical domain chart. An STRtree prunes
candidate region/segment comparisons; native predicates still check each relevant
case. Source rings are consistently oriented (CCW shells, CW holes), then native
noding splits shared linework at intersections and vertices. Each atomic segment
receives at most one occupied owner on each side using original directed segments.
There are **no epsilon-offset sampling probes, snapping, precision grids, silent
repairs, dropped overlaps or tolerance-based gap closure**.

The graph stores vertices, edges, left/right region indices and two compressed-row
incidence tables: vertex→outgoing rays and region→directed edge uses. Each interior
edge appears once, referenced with opposite signs. A junction's left sector must
match the next CCW ray's right sector. Point-only contacts and same-plate patch
seams are explicit, not promoted to interplate adjacency. Content IDs preserve the
current inputs and derived connectivity; they do not replace persistent geological
identifiers in W02 or a future boundary history.

`frames()` uses native array batches for tangent/right-normal/metric calculations.
A spherical normal uses the corrected stable sum/difference plane normal; true
arc fractions and lengths use the radius. `motion()` consumes named plate velocity
vectors, with region geometry deciding the side assignment. Results use the same
conventions as `boundary_motion`; no material/slab velocity is inferred. Radial
relative velocity is exposed for spherical diagnostics, not discarded as a valid
one-dimensional reduction. `validate_trace()` uses the retained native edge tree
and checks all overlapping pieces and their directed owners.

### Execution, memory and reuse decisions

- Reuse native Shapely/GEOS noding and indexing already required by stage 2.
  No alternative geometry framework, dependency installation or new worker pool.
- Source-side/ring preparation occurs once per network. Shared input metadata is
  hashed once, then its digest is reused in edge/node IDs instead of repeatedly
  hashing a region-sized header for every edge. Region incidence avoids scanning
  the full network once per region; velocity ownership groups are built in one pass.
- Compact immutable byte-backed arrays provide private returned descriptors.
  Traces/frames are queried in bounded batches, and required output/arrangement
  envelopes are admitted before bulk allocation. No full edge×query matrix is kept.
- WorkBudget reservations cover build/query estimates. Network/geometry ownership
  persists beyond each call: the caller must account `retained_bytes_estimate`
  and genuinely shared source geometry once. GEOS and STRtree overhead is an
  allowance, not a hard cap or measured whole-process RSS.
- Native read queries are reusable and tested concurrently. Indexes rebuild after
  serialization/storage; no mutable prepared object is accepted by trust in pickle
  flags. Save/load uses the existing ArrayStore, lossless Zstd and chunk deduplication.
  One snapshot contains all input WKB definitions; no long manifest dependency chain.
- Updating geometry or plate labels creates a new identified network. Existing
  execution contexts include the new module and refuse changed source/methods.
  Cancellation is checked at safe boundaries, not claimed to kill a running GEOS call.

### Spherical support and numerical refusal

The topology chart is dimensionless and orientation-preserving on its supported
hemisphere. Adjacent regions may use distinct compatible charts only when exact
conversion to the **declared domain chart** passes coverage and source-side tests.
Reprojection may expose a numerical sliver even for intended coincident source
arcs. Such input is refused rather than joined by tolerance or repair; use a
coherent common definition. The tests preserve a refusal case and a successful
compatible-chart case. A planet-spanning atlas without a supported common chart
requires a separate explicit seam/stitching extension. This release does not
claim that extension, global coverage, moving junctions or spherical W02 transport.

### Obtained evidence

The fresh [test record](../evidence/w01-stage3-tests.json) and
[log](../evidence/w01-stage3-tests.log) record the complete current suite. The new
84 cases cover independent rational partitions/perimeter integrals, holes, T/four-way
junctions, point contacts, trace reversal, short arcs, polar/seam frames, co-rotation,
compatible/inexact recharting, invalid coverage, allocation/cancellation, identity,
concurrent reads, source changes, corruption and fresh-process/backup restoration.
All prior test sources/cases and geometric tolerances remain unchanged.

[Focused measurements](../evidence/w01-stage3-measurements.json) use 96 rectangular
regions, 212 unique edges and 172 interplate edges. Five paired warmed comparisons
of the same velocity diagnostics gave median 17.112 ms through individual diagnostic
calls and 2.537 ms through the new batch interface, with identical compared output
bytes. Single-observation network preparation took 62.514 ms. Candidate checks
and retained/tracked memory scopes are recorded; these are not world forecasts,
hardware-independent improvements or an audit of all future geometry sizes.
No timing threshold is embedded in tests. Windows and geological validation are
unverified; no publication or edits on the owner's PC occur here.

Primary method references (no external code copied):
- [Native noding](https://shapely.readthedocs.io/en/2.1.2/reference/shapely.node.html).
- [Occupied ring orientation](https://shapely.readthedocs.io/en/2.1.2/reference/shapely.orient_polygons.html).
- [Directed shared paths](https://shapely.readthedocs.io/en/2.1.2/reference/shapely.shared_paths.html).
- [Spherical gnomonic scope](https://proj.org/en/stable/operations/projections/gnom.html).


<a id="w01-stage2-corrections"></a>

## W01 stage 2 — targeted correctness corrections, 17 September 2026

The four double-check findings are corrected in `0.1.0.dev13`, without another
architecture/optimisation pass. The three changed implementation files are
`_geometry_native.py`, `geometry.py` and `spherical_geometry.py`.

| Finding | Correction and regression boundary |
| --- | --- |
| Short-arc distance and missed matches | Compute `(a+b) × (b-a)` instead of subtracting nearly equal products in `a × b`; scale the normal before taking its norm. Preserve exact finite-arc membership testing and the endpoint fallback, not an infinite-great-circle approximation or enlarged corridor. Tests use 90-digit independent products of captured endpoints, multiple orientations, short lengths, offsets and reversal. |
| Constructor/import mismatch | Apply shared coordinate-sequence checks after native parsing, including individual multiline/polygon/collection parts. Duplicate adjacent vertices are rejected, not removed; a legitimate ring closure and equal endpoints belonging to distinct components remain valid. |
| Infinite output distance | Apply the region-interior zero convention before converting radians to metres, then reject unrepresentable outputs before publication. Representable extreme-radius results remain supported. |
| Empty-query cancellation | Check cancellation before allocation and at the empty-result return, including invalid tokens and cancellation raised during the call. Reserved work is released on refusal. |

The metric stays compiled with `fastmath=False`, no parallel reductions and no
points-by-edges scratch matrix. Validation changes do not alter the WKB schema or
valid definition IDs; existing source/execution identities prevent silently
reusing results of the old numerical implementation. Invalid definitions formerly
admitted by the importer now refuse restoration. No historical snapshot is rewritten.

The previously failing probes are retained as permanent tests, alongside endpoint,
near-miss, serialisation, storage/index and cleanup checks. Original fixtures and
previous test sources remain unchanged. See [fresh full tests](../evidence/w01-stage2-corrections-tests.json)
and [the correction record](../evidence/w01-stage2-corrections.json). These are
correctness checks, not new performance measurements or geological acceptance.
Windows remains unverified. W01 stage 3 and W03 are not part of this delivery.

Method references: [S2 stable cross-product explanation and implementation](https://s2sphere.sidewalklabs.com/en/latest/_modules/s2sphere/sphere.html#robust_cross_prod)
and [Shapely's documented limits on WKB validity checking](https://shapely.readthedocs.io/en/2.1.2/reference/shapely.from_wkb.html).
The algebraic identity is used directly; no external implementation is imported.

<a id="w01-stage2-delivery"></a>

## W01 stage 2 — geometry, predicates and spatial queries

**17 September 2026.** Native double-precision Shapely/GEOS is the normal planar
backend; spherical geometry uses its topology inside conditioned gnomonic charts,
with separately calculated spherical metrics. No runtime choice lowers precision,
repairs an invalid feature or treats geographic degrees as Cartesian metres.
See [the scientific scope](FOUNDATIONS.md#w01-geometry). W01 stages 3–8 remain.

| Concern | Implemented decision and boundary |
| --- | --- |
| Native calculations | Shapely 2.1+ vectorised native predicates/overlays; compiled finite-arc distance loops with `fastmath=False`, `cache=False`, no parallel reductions. Reference-only package use does not eagerly require Numba. |
| Setup reuse | Immutable WKB-backed geometry prepares its native predicate structure once. Indexes share feature definitions and build native STRtrees once. Equal-identity overlays reuse the verified definition where mathematically appropriate. |
| Candidate pruning | Index multipart components separately without creating new geological IDs. Per-chart spherical boxes are conservative broad phases; final predicates/arc-distance bands retain all candidates. Stable sorted output never assumes a nearest/first-hit owner. Hole validation also uses an index rather than rebuilding all prior holes. |
| Memory | Bound query chunks and match count before native calls, including candidate/result tables. No points-by-edges distance matrix. The index holds an estimated native/setup allowance until close; caller-held geometry/results remain owner costs. Native GEOS/JIT allocator memory is not a promised RSS cap. |
| Overlay size | Account for a conservative intersection envelope and refuse excessive pairs before allocation. Provably disjoint bounding boxes avoid that quadratic envelope. No downsampling to fit the budget. |
| Spherical representation | One conditioned open-hemisphere chart per patch; cross-seam and polar support. Indexed queries may group several charts. Global patch seam/coverage construction is deferred to the explicit topology stages, not silently replaced by flat geometry. |
| Storage and identity | Existing Zstd/deduplicated ArrayStore holds bounded WKB definitions plus frame/chart metadata. Restore rebuilds geometry, verifies its descriptor/ID and recreates derived setup. No new disk cache, pickle store or state migration. |
| Dependency verification | Geometry modules join the fixed callable inventory; native metric source/flags join the selected Numba identity. Shapely extension and bundled GEOS binaries join runtime identity. System/non-wheel GEOS remains explicitly unsealed where those binaries are not discoverable. |
| Parallelism | Independent immutable queries may share an index. Tests exercise concurrent reads; close refuses active readers. No extra worker hierarchy, GPU path, eager prefetch or automatic parallelisation of coupled topology is added. |
| Cancellation/failure | Check at bounded query boundaries and before publishing results. Invalid masks, frames, shapes and native failures are explicit. Geometry is never mutated by a rejected query/overlay. |

**Focused evidence:** `tests/measure_w01_geometry.py` compares exhaustive feature
queries with the reusable index on 200 separated rectangles and 2,000 sample points,
with five alternating-order warmed repetitions and separately recorded setup.
The result includes candidate counts and exact hit equality; it is not a forecast
for overlapping global plates. Native/internal allocations are not fully captured
by Python allocation tracking. Spherical metric checks measure finite arcs against
independent equatorial expectations, recording first compilation separately.
[Measurements](../evidence/w01-stage2-measurements.json) and
[full regression record](../evidence/w01-stage2-tests.json) report actual outcomes.

**Not adopted:** dense all-pairs cell/feature tables, maximum compression in hot
loops, persistent predicate-result caches for these cheap queries, a separate geometry
scheduler, automatic coordinate snapping/repair, low-precision GPU predicates, or
an unvalidated full-sphere rewrite. The existing optimized numerical backends and
W02 contracts remain unchanged. Shapely is a declared dependency already present in
the development environment; no installation or publication was performed.

<a id="w01-stage1-delivery"></a>

## W01 stage 1 — coordinate/time conventions, 17 September 2026

**Scope:** coordinate representation and explicit time/units only; not a complete
W01 geological sampler or W01-to-W02 forcing adapter. The branch baseline is
`ecac085fb64b7bd862580f996c61d5bf7c9088e2`. This is a local copy-ready delivery.
Physical/numerical accuracy remains ahead of speed; no untested lower precision,
fast-maths, implicit unit guesses or silent reference-frame substitutions occur.

| Concern | Implemented decision |
| --- | --- |
| Bulk geometry | NumPy native ufunc/matrix batches, normally 65,536 points; input capture, output and bounded scratch use the existing shared WorkBudget. Invalid shapes are refused before bulk conversion. |
| Reusable setup | Each local frame retains one immutable 3x3 basis (72 numerical bytes, excluding metadata/origin). Its identity covers radius, parent frame, origin, local name and orientation. Restore reconstructs derived setup. |
| Copies/lifetime | Existing read-array borrowing for proven immutable backing; detached mutable capture; compact immutable outputs. Direct local-to-local transforms compose their small operators rather than produce a full intermediate XYZ field. |
| Persistence | Existing ArrayStore supports coordinate products/metadata; no bespoke coordinate cache. Frames/time axes supply content identities, not complete scientific-result identities. Complete invocation records must still include inputs and execution identity. |
| Verification | Fixed execution-dependency inventory now includes coordinates/timebase and immutable named unit records, preventing stale loaded-code/unit reuse. Old caches are not repinned. |
| Time efficiency | Direct axis conversion combines origins before scaling and avoids a huge intermediate absolute timestamp. This preserves small local intervals where possible; lost positive steps or wholly lost offsets are refused. |
| Parallelism | Conversions are independent only for independent batches and immutable frames. They require no new pool. Existing matrix/native controls remain; no automatic process/GPU backend is introduced. |
| Resource meaning | Per-call reservation covers estimated input/candidate/publication arrays and batch scratch, not total RSS or caller-retained results. Large outputs need explicit budgets or caller-supplied chunking; smaller scratch does not remove output memory. |

Numerical reference: the ESA ENU basis, specialised to a sphere, and independent
scalar trigonometry/cardinal-frame cases. Fixed Julian units use the explicitly
named IAU definition, not an implicit civil or planetary year. See
[scientific case notes](FOUNDATIONS.md#w01-coordinates) for equations and sources.
Coordinate roundoff is a representation error separate from geological uncertainty.
The local frame is an affine three-dimensional chord frame, not a flat surface map;
no surface-area, polygon or force-derived-motion claim follows from passing it.

[Obtained verification](../evidence/w01-stage1-tests.json) records the full suite.
New checks include poles/seams, tiny/large values, input/mask/budget refusal, polar
and axial legacy reflection, moving-frame velocity terms, time/epoch consistency,
immutable restoration, shared-thread execution and existing store/context reuse.
No new performance benchmark or universal speed/RAM percentage is claimed. No
Windows or geological validation is inferred. Stages 2–8 of W01 remain outstanding.


<a id="w02-completion-delivery"></a>

## W02 regional completion — remap, motion, topology and history

**17 September 2026. Implemented and mathematically verified on Linux, not physically
accepted.** The remaining regional W02 capabilities use nonuniform columns,
conservative overlap remapping, moving control-volume transport, stable material
markers and explicit 1D ownership/events. Existing fixed-grid and periodic APIs,
prior fixtures, tolerances, compression formats and recorded evidence are preserved.
No new dependencies, separate scheduler/cache, publication or Windows integration.

### Selected methods and accuracy

- `ColumnGrid1D` has immutable explicit edges, a named frame and separate mesh ID.
  Its widths must be positive and numerically resolvable. The uniform-grid bridge
  preserves represented inventory and records any required mean-thickness adjustment.
- `RemapPlan` uses a sorted linear-size overlap sweep and limited linear donor
  integration; coefficients are immutable/reusable for the identical two meshes.
  The material field and its history remain separate invocation inputs. Same-grid
  identity remaps reuse the state; coarsening is not claimed reversible.
- `advect_ale` solves the conservative moving-volume equation with relative flux
  `(u-w)*H`, evolving `H*width` through MC-MUSCL/SSP-RK2. Initial/final geometry and
  interval-mean fluxes enter admission and accounts. No face crossing, missing
  inward composition, silent time shortening or unresolvable coordinate motion.
- `PlateTopology1D` stores shared cuts once and distinguishes plate, block, material
  and mesh identities. Splits/merges, membership and activation/regime events bind
  an exact parent, retain retired IDs and refuse replay. An ownership-only change
  records reassigned inventory without moving geology. Advancing cuts uses the same
  flux on both sides and reconciles block/cohort accounts.
- `MaterialMarkers1D` maps declared material-following cells and accumulates log
  stretch; it does not infer arbitrary material motion from mesh motion and is not
  an extensive-inventory representation.
- Numba is normal; independent reference and lower-order remap/transport choices
  are explicit. Runtime, cache admission and memory pressure never reduce order.
  All new native functions disable fast-math, parallel reductions and disk JIT cache.

### Memory and reuse

Sparse overlap geometry uses O(Ns+Nt) storage, avoiding a dense interpolation matrix.
Slope and stage vectors are reused across cohorts. Cohort outputs/fluxes still scale
with C*N; an arbitrary world is not sparse merely because IDs use a compact table.
Formation times remain once-per-cohort metadata. All accepted arrays/meshes have
immutable backing; restored models validate state, topology and geometry identities.

Existing WorkBudget/KernelExecutor/ArrayStore/ExecutionContext paths are reused.
Remap and ALE cache keys include source material/history, exact geometry, forcing,
boundaries, time, scheme and implementation. Known in-interval events are checked
before a hit. Independent cases may use threads/spawn; successive states and the
adjoining blocks of one model are never independent numerical jobs.

Saved model/marker state uses the existing Zstd, deduplication and direct-manifest
format. No automatic deletion or temporal delta chain is introduced. A cold backup
was restored after removing the original database and continued to the same model
identity. Complete earlier receipts are still a caller-owned history retention
requirement, not automatically rebuilt from the last receipt.

### Obtained measurements, not planetary forecasts

[Recorded measurements](../evidence/w02-completion-measurements.json) compare the
same selected higher-order models on synthetic arrays, one native inner thread.
Five alternating-order warm comparisons; native import/compilation is separate.

| Case | Independent reference | Compiled default | Recorded agreement |
| --- | ---: | ---: | --- |
| Remap: 2 cohorts, 8,192 source / 12,288 target cells | 172.888 ms | 2.457 ms | Zero maximum thickness difference in this case |
| ALE: 2 cohorts, 8,192 cells | 75.360 ms | 1.415 ms | 4.44e-16 m maximum difference |

First compiled setup/use took 2.435 s for remapping and
3.010 s for ALE. Reusing a remap plan reduced a separate warmed
comparison from 2.306 to
2.127 ms; the difference is small and no
hardware-independent gain is assigned. The retained plan occupies 589,808
bytes, **excluded** from the reused-call tracked allocation of
425,516 bytes. A reference call including its separate
setup tracked 3,388,541 bytes, so these are not identical
retention conditions and are not a universal RAM reduction percentage.

ALE tracked call allocations were 861,258 bytes native
and 1,710,876 bytes reference. Tracemalloc does not
include every native/JIT/process allocation. Preserve owner reservations for retained
states, plans and workers; stated work budgets are not process RSS caps.

Four independent cases with 8 cohorts x 32,768 cells took
75.339 ms serial and 45.085 ms under two-worker
auto execution (three paired repetitions). Outputs had identical state identities.
Peak accounted reservation was 100,958,208
bytes serial and 201,916,416 bytes threaded;
all reservations returned to zero. This is throughput of independent cases, not
parallel splitting of one physically coupled domain.

### Verification and completion boundary

[All 488 checks](../evidence/w02-completion-tests.json) passed: 410 prior + 78 new,
zero failures/errors/skips. The new suite includes independent Fraction overlaps,
linear reconstruction, smooth refinement, geometric-conservation and Lagrangian
limits, per-block/cohort transfers, event replay/lineage, nonuniform source/sink,
markers, changed cache inputs/source, corruption, budget/cancellation, cold restore
and serial/thread/spawn equivalence. Existing fixtures and tolerances are unchanged.

This closes the remaining W02 **regional implementation**, not global 2D/spherical
junctions, force-derived motion, variable-density/thermal mechanics, predictive
production/subduction or field-geological acceptance. Those require their named
geometry/process extensions. W04's physical-load connection is next; no additional
general optimisation audit or extra roadmap is required. Windows remains untested.


<a id="w02-materials-delivery"></a>

## W02 material cohorts — delivery and accuracy-first policy, 17 September 2026

This extends the delivered regional kernel; it is not a new physical-solver
framework or a claim that all W02/W05 work is complete. The user has explicitly
selected **accuracy before speed**: MC-MUSCL/SSP-RK2 with binary64 and strict native
arithmetic remains normal. Upwind and the independent reference require explicit
selection. Automatic worker/cache choices may reduce cost but never order,
precision, stage count, conservation checks or the physical model.

### Representation and numerical choices

- A `MaterialCohort` stores one stable cohort ID, material class, origin and optional
  formation time. `MaterialState` has one immutable C-order C×N matrix of partial
  thicknesses, an explicit forward-time epoch, and parent/last-transition receipts.
  Same material class with different origins or formation times stays separate.
- Each cohort solves dH_k/dt + d(u H_k)/dx = 0 using the SAME prescribed face field.
  Total thickness and fractions are derived when requested, not independently
  advanced or renormalised. Empty-column fractions need the returned occupancy mask.
  This is NOT a density/momentum-coupled multifluid scheme. A nonlinear limiter does
  not commute with summation, so transporting a separately summed scalar H need not
  produce the same bits. One-cohort outputs agree with the preceding scalar kernel.
- The compiled multi-row driver reuses two stage vectors across cohorts. Candidate
  thickness/mean flux cost O(CN); RK scratch costs O(N), not O(CN) per intermediate.
  Exact nonnegative accumulators are reused for cohort/column volume totals. No
  full slope arrays, per-cell Python material objects, fast-math or parallel sums.
- State views have fresh array descriptors backed by immutable compact bytes.
  Creation/restoration reserves known capture work separately from live stencil
  scratch, so the same allocation is not charged twice. `material_work_bytes()`
  provides the composite estimate; retained caller states remain owner costs.
  This is bounded dense regional cohort storage, NOT a sparse planet-wide solution
  for an unlimited number of cohorts. Budgets refuse excessive C×N state; numerical
  histories are never merged or binned merely to fit memory.
- Formation ages are derived per cohort. No full age field is rewritten each step.
  None is unknown, not zero. Registration adds zero inventory; retired rows retain
  their definitions. Birth requires a known time equal to the event time. Addition
  of existing material keeps its formation history. Removal refuses overdraw.
- Events require the exact parent state and time, with named external reservoirs,
  transfer-amount identity and before/after account. A retry on the same immutable
  parent is deterministic; applying it to the successor refuses. Full historical
  trajectories require retaining their separate receipts/snapshots: the current
  state keeps its last transition, not an unbounded embedded event chain.

### Reuse, persistence and execution

`cached_material_transport` uses existing admission, verified execution contexts,
prepared velocities, same-key coordination and transactional ArrayStore publication.
Keys include cohort composition/history, epoch, state/lineage, both external maps,
velocities, time interval, scheme and source/runtime identity. Restored numerical
accounts are checked against their parent fields and interval-mean boundary flux.
Missing composition cannot be hidden by a hit. Scalar scheme identities are unchanged;
new source membership deliberately changes current invocation identities, never
repins old cached records.

`save_material_state` / `load_material_state` use the existing typed Zstd/deduplicated
store and retain the complete cohort catalogue, formation times and last receipt.
Time-only changes reuse payload chunks but have different state/manifest identities.
A backup restores without the original database or parent snapshots; a parent ID
is lineage, not a hidden decoder dependency. No snapshots are deleted or migrated.

`KernelExecutor.material_transports` processes independent face-velocity scenarios
for one immutable parent. Auto retains native serial execution for small cases and
uses the established parallel-size threshold for larger native batches. Every job
contains the whole coupled region and all its cohorts. Explicit threads/spawn
produce checked immutable results. Successive times are never independent jobs;
no new scheduler or worker-level physics is introduced.

### Checks and measured scope

The new tests supplement every preceding check and leave their fixtures and
thresholds unchanged. They include independent rational face balances, scalar-row
comparisons, both numerical schemes, increasing/decreasing velocity, refinement,
sharp fronts, zero/unknown ages, source/sink accounts, metadata collisions, overflow,
immutability, cold restore, cache invalidation, cancellation and executor budgets.
The final [test record](../evidence/w02-material-tests.json) and
[bounded comparisons](../evidence/w02-material-measurements.json) record actual counts,
versions, first-call cost and measurements. Windows and physical/geological validity
remain unverified; no full world run or publication is performed.

The comparison uses four cohorts × 65,536 cells, the SAME MUSCL equation and
binary64 precision on native/reference paths, and five warmed alternating-order
calls. Tracked allocations exclude some native/JIT memory; resource reservations
are estimates, not total RSS. A separate smooth translation check uses 64/128/256
cells and an explicitly synthetic profile. This is an enabling-method comparison,
not the skipped general benchmark programme or a forecast for the whole generator.

### Obtained bounded evidence

The final suite passed **410 tests (331 prior + 79 new)**, with no failures,
errors or skips. On four cohorts × 65,536 cells, native/reference median warmed
calls were 8.16/27.02 ms with zero measured difference in partial-thickness values.
Tracked peak allocations were 8,922,927/11,607,368 bytes; these exclude some native
and JIT memory. First native use, including compilation, was 6.05 s. Four independent
same-parent scenarios took 52.74 ms serially versus 28.91 ms in automatic mode in
this environment. These figures are workload-specific, not world forecasts.

The smooth translation mean absolute errors at 64/128/256 cells were
0.004397/0.001229/0.0003281 m. A time-only snapshot change preserved all formation
metadata and reused the original 32 payload chunks without adding another chunk.
Exact test definitions, source hashes and raw measurements remain in the linked
machine-readable evidence rather than an additional report.

Primary scientific background: the conservation equation and scalar discretisation
are retained from [the regional case](FOUNDATIONS.md#w02-regional). Multi-component
sum constraints are a known issue discussed by [Plewa & Mueller](https://arxiv.org/abs/astro-ph/9807241).
Atlas's present prescribed-velocity, partial-thickness model does NOT implement or
claim that paper's coupled-hydrodynamic CMA method: it avoids a separate total field
and tests each conserved component directly. Further density/force coupling needs
its own consistent interface, not a reuse claim based solely on this comparison.


<a id="w02-regional-delivery"></a>

## W02 regional transport — implementation and decisions, 17 September 2026

Local continuation of item 12; no remote publication. The reviewed code source
baseline exactly matched the item-12 receipt. [331 passing checks](../evidence/w02-regional-tests.json)
include 51 new regional cases. Existing periodic/cooling/flexure algorithms,
fixtures, tolerances, storage formats and historical evidence are unchanged.
This does not complete all W02 or validate physical mountain formation.

### Selected method and execution

The new regional default is compiled MC-limited MUSCL with SSP-RK2, frozen face
forcing per interval, and a sufficient combined outgoing-fraction limit 1/2.
First-order upwind (limit 1) and independent NumPy/Python implementations remain
explicit numerical alternatives. Slopes at the ends use limited one-sided interior
information; inflow uses an explicit exterior FACE value. Numerical reconstruction
is limited for positivity; negative candidate cells are refused, never clipped.
One face flux per stage supports both neighbouring cells. Returned flux is the
RK2 interval mean. Native totals reuse the existing exact nonnegative accumulator;
binary64 local updates still have a reported, checked roundoff residual.

| Concern | Implemented decision |
| --- | --- |
| Representation | N binary64 means and N+1 face velocities; two boundary records, not per-cell objects or a padded ghost grid. |
| Temporaries | Local reconstruction; first-order donor loop; only required candidate/flux and the two RK-stage work arrays. No full arrays of every outflow coefficient or slope. |
| Admission | Shape and shared `WorkBudget` before bulk copies; candidate/codec publication lifetime kept by existing layers. Work estimate is not a total RSS cap. |
| Reuse | Typed inputs, complete boundary records, grid/frame, duration, scheme and selected compiler/runtime. Prepared immutable inputs use the existing snapshot/digest path. |
| Persistence | Existing auto admission, single-flight/OS claims, Zstd/dedup store and publication checks; a versioned packed layout avoids a new arbitrary-object serialiser. No I/O inside equations. |
| Parallel work | Existing executor handles whole independent queries in ordered bounded streams. Serial auto was retained for regional batches after the tested outer-thread path was slower. Explicit threads and spawn passed exact-output tests. A single physical domain is never treated as unrelated tiles. |
| Correctness | Rational flux oracle, variable-velocity thinning, one-cell/two-sided cases, reversal, closed/no-flow/zero-time, sharp fronts, refinement, reflected coordinates, budget/cancellation, native code mutation and fresh-process cached reuse. |
| Native identity | Actual Python definitions/JIT options and Numba/LLVM library identity now participate for this backend. Generated assembly hashes remain observed evidence, not authentication of a hostile process. |

### Accuracy versus cost, not a blanket speed claim

The [measurement record](../evidence/w02-regional-measurements.json) uses a compact
sin^4 pulse with exact translated cell averages. Speed is 1 m/s, duration 0.1 s,
unit interval; these are synthetic values. Upwind used nominal Courant 0.8,
MUSCL 0.4, so the cheaper method received its larger admissible step.

| Cells | Upwind mean absolute error (m) | MUSCL mean absolute error (m) |
| ---: | ---: | ---: |
| 64 | 0.0061062 | 0.0034967 |
| 128 | 0.0031250 | 0.0009711 |
| 256 | 0.0015788 | 0.0002552 |
| 512 | 0.0007932 | 0.0000654 |
| 1024 | 0.0003976 | 0.0000165 |

Neither numerical scheme is uniformly fastest. At the preselected coarse L1 target
0.002 m, upwind at 256 cells took 2.72 ms versus MUSCL at 128 cells taking 4.79 ms
in the recorded three-run medians. MUSCL is the higher-accuracy regional default,
not a claim that it wins that coarse target. At finer grids its reduced smoothing
and smaller required cell count can justify the extra stages. Exact shifts at unit
Courant particularly favour first-order upwind; no universal superiority is claimed.
The physical case must choose its accuracy profile rather than using timing to
change its conservation law. Both selected schemes execute compiled by default.

For the SAME MUSCL scheme at 262,144 cells, five alternating warmed comparisons
recorded 106.92 ms reference versus 35.18 ms native (67.1% less median time), with
23,338,303 versus 8,394,850 tracked peak bytes (64.0% lower). The timing spread is
large (native 12.96–48.70 ms); these are not repeatable machine-independent ratios.
The compared outputs matched bit-for-bit. Tracemalloc excludes some native and
JIT memory; the first new native call took 10.41 s including compilation.
Four independent large batches took median 210.64 ms serial versus 254.90 ms with
outer threads under the former automatic policy. The delivered auto policy uses
serial for these regional jobs. This does not prove threads lose at every size.
The measurement record retains the exact source identities used at measurement
time. The subsequent changes selected serial automatic regional scheduling and
hardened packed-result restoration/added native-build reporting; the measured
native stencil is unchanged. The final regression receipt identifies the delivered
code separately. Re-running the measurement script now reports the selected serial
automatic path, not the rejected former threaded automatic path.
No new GPU, intra-domain worker system, persistent JIT cache or general scheduler
was introduced. The single-domain native stencil remains serial; distributed or
parallel spatial transport is not claimed by this increment.

### Scope and continuation

The execution card is `cases/regional_transport.json`; equations and boundary
meaning are in [the existing foundation case notes](FOUNDATIONS.md#w02-regional).
`tests/measure_regional_transport.py` reproduces the bounded comparisons without
installing dependencies. No arbitrary Earth parameters are baked into the kernel.
Material mixtures/cohorts, internal production/recycling, moving boundaries,
plate topology, physical loading and geological validation remain later work.
Windows remains unverified. Update these existing documents; do not create another
optimisation roadmap for the next physical increment.


<a id="combined-acceptance"></a>

## Combined resource/platform acceptance — item 12, 17 September 2026

**Current outcome: implemented and Linux-accepted within the bounded synthetic
profiles; local Windows acceptance is outstanding.** This closes the available
platform's combined engineering work, not every future performance candidate or
any geological acceptance gate. Items 2–11 remain implemented; item 1 was explicitly
skipped. Changes are delivered locally on top of the items 9–11 package, not pushed
to origin. The existing tests/records remain historical; this section adds no
competing general plan.

### Findings corrected in the combined path

1. **Independent limits did not compose.** A local executor and a store could each
   admit their complete budget at once. A parent-aware `WorkBudget` now reserves
   distinct ancestors atomically once. Default stores and executors share the
   existing process-local envelope; explicit budgets let a case select another
   finite envelope without altering physics. Per-executor limits remain in force.
2. **Retained and inter-stage allocations had missing lifetimes.** Store capacities
   for decoded chunks, verified metadata and SQLite pages are reserved until close.
   Read/codec work, write staging and live streaming manifests have separate
   reservations. Cached numerical results remain accounted while being checked,
   compressed and committed after the kernel's scratch scope ends. A wrapper with
   a store inherits the store's run budget even when cache admission bypasses I/O.
3. **Shared pressure could cause a scheduling loop.** Admission now drains already
   pending work when it can help, otherwise refuses without copying. A failed pool
   creation releases its reservations/slots. An initially cancelled stream does
   not leave the executor permanently marked active. Reservations for running
   calls are held until they finish; native kernels are not killed by cancellation.
4. **Concurrent pools could each assume exclusive CPU use.** Pool capacity is
   claimed across executors. Existing native-thread controls remain. Spawn baseline
   allowances are held until shutdown; no new automatic preference for process
   execution is introduced. It stays an explicit alternative for matched tests.
5. **Preparation and close could overlap.** A store with active preparation refuses
   close until the owner cancels/joins that work, rather than releasing memory while
   a producer still uses the connection. Transaction/corruption semantics remain.

### Exactly what the shared envelope means

- `WorkBudget` remains admission for estimated allocations/capacities, **not an RSS
  limit**. Maxima are immutable. Accounting categories and high-water records are
  bounded and detached. Related budgets charge common ancestors once; reservations
  for different simultaneous allocations remain additive.
- `ArrayStore(..., budget=run_budget)` reserves decoded-cache capacity, a 1,024-byte
  per-entry verified-cache allowance, a 16 KiB connection-metadata allowance and a
  configurable SQLite page-cache allowance (default 2 MiB). The page-cache setting
  is an SQLite suggestion, not enforcement of all SQLite allocations.
- `codec_workspace_bytes` defaults to an 8 MiB **allowance**. It is included in read
  and write admission, not passed off as a native codec heap cap. Actual process
  memory and headroom must still be measured for the selected compression/build.
- Write-work estimates now include simultaneously retained Python dependency maps,
  sets and manifests. They scale with the submitted reference count instead of
  always charging the maximum permitted count. Limits are checked before encoding.
- An executor charges a complete in-flight job once to its shared parent and uses
  an internal job-local check inside the worker. This prevents charging the same
  worker workspace twice. A pool using spawn also reserves a configurable 96 MiB
  baseline allowance per worker; job transfer/scratch is additional.
- Caller-owned input arrays, retained returned outputs, prepared inputs, execution
  contexts and operator coefficients need owner-side reservations when retained
  outside a call. Returned plain arrays do not magically transfer a reservation to
  an arbitrary caller. Count genuinely shared backing once. The drill explicitly
  reserves caller state and output consumption while workers and storage overlap.
- `resource_requirements()` reports storage capacities: one database and rollback
  journal per physical database, one spool per concurrent writer, and each backup
  separately. Connections to the same database do not create extra database files,
  but each has its own caches/spool. Free-space checking is not filesystem locking;
  other applications can consume that space. No automatic deletion is performed.
- `peak_prepared_bytes` records the largest logical spool prepared. Visible-file
  telemetry can miss unnamed temporary files and brief journals, so it is not
  presented as a complete filesystem peak. On-process library/JIT allocations are
  captured by external memory sampling subject to its documented blind spots.

### Obtained checks and bounded combinations

The [verification record](../evidence/combined-resource-acceptance.json) records
**280 passing checks: all 254 previous checks plus 26 new combined-resource cases**,
with no failures/errors/skips. New challenges cover sibling/parent budgets, failed
admission, cancellation, active preparations, concurrent encoder/executor work,
retained state, duplicate/cached results, corruption, isolated restoration, spawn
allowances and overlapping CPU pools. Original mathematical tolerances, fixtures,
compression formats and provenance checks are not relaxed.

`verify.py --acceptance` runs the complete regression suite and then three fresh
processes, each using 262,144-sample fields, first use and five warm repetitions:

| Selected combination | Accounted byte envelope | Integrated responsibilities |
| --- | --- | --- |
| Serial + raw | 96 MiB | Numerical reference agreement, full persistence path and backup |
| Auto + balanced Zstd | 96 MiB | Threaded independent batches, compression, caches, deduplication and incremental branches |
| Spawn + compact Zstd | 384 MiB | Explicit process transfer/restoration, worker lifetime and the same storage/identity checks |

All three combinations produced identical output-byte digests for the compared
optimised calculations, kept their accounting within their configured envelope and
released every reservation after consumption/close. The native transport was also
compared with its reference fields, fluxes and totals. Rotation versus the separate
formula uses the existing numerical tolerance, not a new claim of bitwise equality.

**Measurement semantics.** A separate parent samples the whole child process tree,
including spawned workers and native-library memory. RSS sums can overcount shared
pages; USS and PSS are reported independently when available. Polling may miss
brief peaks. A 1 GiB sampled-RSS watchdog and a 90-second per-profile timeout bound
the drill, but neither is an OS memory guarantee. Missing telemetry is not a zero
value or a pass. First-use import/JIT/pool costs remain separate from five warm
cycles. This is the focused combined acceptance requested in item 12, not the
skipped item-1 broad baseline or a geological simulation.

The JSON holds measured values for this machine rather than hardcoding performance
thresholds into unit tests. It includes source hashes, actual platform/runtime,
component accounting, process-tree memory, disk capacity and blind spots. The
resource figures include the Numba compiler's process residency; do not interpret
an accounted array envelope as the entire Python application's memory.

### Platform decision and continuation

The delivered run is **Linux, CPython 3.13.5, NumPy 2.3.5, SciPy 1.17.0, Numba
0.65.1, Blosc2 4.3.3, threadpoolctl 3.6.0 and psutil 7.2.2**. The cross-platform
runner can be invoked locally using `python -I -B tectonics/verify.py --acceptance`.
It creates only its own temporary test data and the redirected evidence output;
it performs no installation, publication or Windows workspace integration.
`psutil` is an optional **acceptance telemetry** dependency, not a slower/default
numerical backend. Existing optimised computation remains the normal path.

**Windows is pending, not passed by simulation or inference.** A local run must
exercise the actual libraries, spawn, file locks, permissions and filesystem.
A failed Windows test is a blocked platform claim, not permission to skip it or
weaken a tolerance. Linux acceptance is sufficient to continue bounded development
there; it is not authority to claim the whole tectonic module or universal scale
complete. Later physical packages inherit these shared-budget and acceptance
requirements rather than requiring another general optimisation audit.

Primary implementation references (no new external software audit):
[CPython executor/cancellation semantics](https://docs.python.org/3.13/library/concurrent.futures.html),
[spawn and Windows requirements](https://docs.python.org/3.13/library/multiprocessing.html),
[SQLite page-cache semantics](https://www.sqlite.org/pragma.html#pragma_cache_size),
and [psutil process-memory APIs](https://psutil.readthedocs.io/en/latest/).


## Optimised-default policy — 17 September 2026

Accuracy takes priority: preserve the selected highest-accuracy supported scheme.
Optimise its execution; never select a less accurate equation/discretisation or
precision merely because it is faster. Use the tested optimised implementation
as the normal default for supported
workloads. Reference implementations remain explicitly selectable for verification
and diagnosis; users should not have to opt into an already accepted acceleration.
Do not silently enable approximate physics, unsafe arithmetic or an untested
backend in the name of this policy.

In the delivered optimisation 2/3 follow-up, `advect_thickness` now defaults to
`backend="numba"`; `half_space_temperature` and `cached_temperature` default to
`backend="scipy"`. Normal package requirements include the tested Numba pin and
SciPy range. Explicit `backend="reference"` remains available. Missing required
optimised dependencies raise an error rather than silently falling back; no
automatic dependency installation occurs. Historical restored result labels retain
their recorded backend. First-use compilation and the existing precision,
conservation, memory and source-validation requirements remain unchanged.

Default verification includes native transport checks. The existing reference
suite explicitly selects its original backend, so it remains an independent
comparison rather than comparing the accelerated calculation with itself.
This changes selection and packaging, not the transport equation or compiler flags.
No new benchmark or performance claim accompanies this change.


**ATLAS-OPTIMISATION-REFERENCE | Revision 4 | 17 September 2026**
**Historical consolidation of scientific-software methods, engineering patterns, language guidance and performance/storage notes.**

This is the single maintained optimisation reference for [the tectonics plan, revision 7](TECTONICS_PLAN.md). It distinguishes documented methods, proposed Atlas applications and delivered behaviour. The original catalogue remains a set of method studies. The delivery sections record implemented items 2–11 and bounded measurements, not physical acceptance; the broad item-1 programme was not run. Atlas remains WORKING NON-CANON, vibe-coded with OpenAI ChatGPT/Codex under Michael’s direction.

**Start with the selected physical calculation, not the whole catalogue.** Apply the relevant execution and storage contracts, choose only useful method candidates, then compare them at the predeclared numerical/physical error. Continue the selected tectonic stage rather than implementing every candidate method first.

**Navigation:** [Current baseline](#current-baseline) · [Process placement](#process-placement) · [Execution](#execution-contract) · [Caches](#cache-contract) · [Storage](#storage-contract) · [3D geology](#volumetric-storage) · [Language](#native-boundary) · [PF candidates](#candidate-register) · [Tests](#performance-tests) · [Execution card](#execution-card) · [Scientific software](#scientific-methods) · [Engineering methods](#engineering-methods) · [Adoption](#method-adoption) · [Sources and consolidation](#sources)

<a id="current-baseline"></a>

## 1. Scope, status and reading rules

The live documentation branch was checked at `612d53eba495202101a8e638578f47fb37752649`. Its numerical foundation remains `11317165b7e2aeab7201a1fe3e3f646cb640d51e`: arrays/batches, rotations, periodic thickness transport, analytical cooling and reusable uniform periodic discrete flexure. See the [pinned module scope][url-001]. No coupled extensional landscape, global mechanics, voxel engine or measured acceleration is implied.

The dated pre-studies reviewed scientific software and engineering methods on 15–16 September 2026. This consolidation performs no new external software audit. A developer claim stays a developer claim. Version, access and preprint limitations are retained in the source notes. Broad implementation descriptions are leads for inspection, not recovered algorithms.

| Change class | What changes | Required evidence |
| --- | --- | --- |
| E — execution | Layout, reuse, batching or scheduling without intended mathematical change. | Established result/identity policy, complete invalidation and safe ownership. |
| N — numerical | Discretisation, precision, iteration, remapping, random draw mapping or evaluation order. | Error/convergence, events and conservation under an explicit numerical identity. |
| M — model reduction | Physical laws, state variables or degrees of freedom. | Separate physical justification and acceptance; not “same physics, faster”. |
| S — scale/representation | Mesh, partitioning, material representation or resolution hierarchy. | Correct boundary exchange, state transfer, conservation and workload evidence. |

A proposal can span classes. Renderer culling, reduced display refresh, deleted records, raised limits and omitted checks do not automatically preserve the scientific problem. Hash-table keys are not cryptographic source identities. Prescribed-time queries may be independent; evolving time steps are not. Exact historical accounts and source checks stay protected.

## 2. Execution, caching, storage and language contracts

<a id="storage-profiles-delivery"></a>

### 2.0d Delivered local increment: checklist items 9, 10 and 11

**17 September 2026.** Based on the local items 6–8 delivery, not a newly pulled
origin. These storage changes are implemented and tested; none is a new tectonic
mechanism or a whole-world performance claim. Item 1 stays skipped and item 12's
combined resource/platform acceptance is still outstanding. Code remains vibe-coded
with ChatGPT/Codex under Michael's direction. No publication was attempted.

**9 — compression and chunk profiles.** Normal `ArrayStore` construction now uses
Zstd, Blosc level 1, byte shuffle and exact categorical selection. Blosc2 is a
normal package requirement. `Compression(codec="raw", palette=False)` remains an
explicit reference/no-compression path; missing Zstd support never causes fallback.
An encoded chunk can still choose raw bytes when that exact representation is
smaller. This is a documented per-chunk selection, not a backend-failure fallback.

`storage_profile()` supplies named, versioned starting configurations:

| Profile | Suggested independent chunk | Compression | Intended trade-off |
| --- | --- | --- | --- |
| `fast-v1` | 16 KiB | Zstd level 1, byte shuffle | Fine read/update granularity; more metadata and calls. Not universally the fastest full scan. |
| `balanced-v1` | 64 KiB | Zstd level 1, byte shuffle | Normal starting profile; low encode cost and bounded decoded blocks. |
| `compact-v1` | 256 KiB | Zstd level 3, byte shuffle | Lower payload/object overhead in the tested data; larger partial-read and update amplification. |

A caller still supplies total store, array and cache limits. Opening an existing
store does not change its chunk size or recompress historical objects. Profiles
are recommendations from bounded synthetic cases, not a claim of optimality for
every machine or future geological field. Higher levels were not automatically
better: level 6 and bit shuffle did not consistently beat level 3/byte here.

The tuning record covers 30 level/filter/chunk configurations, with uniform,
categorical, layered, smooth, noisy and signed-zero fields. It also compares
Blosc's embedded per-frame dictionary request on small repeated records and
smooth/noisy fields. Dictionaries did not show a useful size/time win in these
cases; **dictionary use is not enabled by any normal profile**. Explicit
`Compression(use_dict=True)` remains available for a justified future comparison.
Every frame stays independently decodable; no external trained dictionary or
shared dictionary store was added. Small frames may cause Blosc to omit training.

**10 — compact categoricals and reference-based snapshots.** Eligible integer and
Boolean data can use 1/2/4/8-bit palette indices or typed run-length records. Packed
indices retain sign/range exactly, use checked lengths and indices, and reject
nonzero padding. Floating fields retain exact bytes, including signed zero; there
is no quantisation. The old raw, uniform, palette8 and Zstd formats remain readable.
Older programs do not understand the new codec labels and must refuse them; this
is backward reading support, not a promise of forward-reader compatibility.

`store.reference(parent, name)` returns a small checked descriptor, not an array
copy. `put_incremental(child, parent, replacements, metadata)` changes specified
**complete chunks** and directly shares all other parent chunk identities. It
never accepts a dirty flag as proof that a supplied field is unchanged. Shape and
datatype changes require an ordinary new array submission. Each resulting manifest
references its payloads directly; it does not require a chain of parent manifests
for decoding. Geological provenance still belongs in the supplied metadata.

The first use of a cold reference verifies every required chunk. Repeated use can
reuse a bounded attestation for the same stable database version. The reference
record is not a security capability: its path, parent, name and descriptor digest
are rechecked, including before commit. Source corruption, deleted dependencies,
changed manifests and incompatible chunk layouts are errors, not missing-cache hits.

**11 — preparation, transactions and loading.** Encoding and exact encode/decode
verification take place before `BEGIN IMMEDIATE`. A byte-bounded spool retains
small preparations in memory and spills larger ones to the trusted local folder.
One encoder per store instance limits scratch; separate connections may prepare
concurrently. The final transaction rechecks dependencies and concurrent duplicate
chunks, inserts rows in bounded batches, validates cancellation/source state and
publishes one complete manifest. It never publishes partially encoded candidates.

New execution limits are `staging_memory_bytes` (256 KiB), `max_staging_bytes`
(256 MiB), `verified_cache_entries` (2,048) and `insert_batch_bytes` (256 KiB).
These are overridable execution limits, not physics. Spool and insertion targets
can transiently hold one additional chunk. Preparation reserves an explicit
`WorkBudget` envelope; the cache wrapper forwards its budget and cancellation.
Caller inputs, retained decoded arrays and native codec overhead remain outside
a process-wide RSS guarantee. Plan for staging storage **in addition to** database,
rollback journal and independent backups. No automatic history deletion is added.

Read operations pin a SQLite read view before reusing validated data. Source
manifest hashes are always checked. SQLite `data_version` detects another
connection's commits; `total_changes` detects direct writes on the same connection.
Changed settings or either version invalidate the relevant attestation/cache.
A verified decoded hit avoids repeated payload reads and hashing while the view
remains valid. `get()` parses the manifest once; streaming releases its read
transaction between chunks instead of holding a reader lock across user work.
This relies on trusted SQLite-managed access, not hostile raw-file mutation or
protection against an attacker replacing both data and checksums. Reopening the
store starts cold and checks on-disk payloads again.

A focused one-worker queued-read comparison was slower than serial reads for the
tested local store. No new automatic prefetch, asynchronous writer, compression
pool or WAL migration is introduced. Existing execution parallelism is unchanged.
This is an explicit evaluated non-adoption, not an unimplemented default.

**Obtained evidence.** All **254 tests** passed (216 retained + 38 new), with no
failures, errors or skips. Two old format-specific fixtures now explicitly request
raw/legacy-palette encoding, retaining their former assertions rather than testing
the new default accidentally. New tests cover independent packed/RLE decoding,
malformed data, defaults and missing codecs, cold and hot reference validation,
changed/deleted dependencies, concurrent creators, unlocked encoding, bounded
staging and spills, cancellation/rollback, immutable reads and backup restoration.
No numerical equations, compiler settings, physical fixtures or tolerances changed.

Five paired/order-balanced whole-store comparisons used 2,621,440 bytes of synthetic
arrays, 64 KiB chunks, Zstd level 3/byte with palettes on both implementations and
a 4 MiB decoded-cache allowance. The previous implementation is the items 6–8
source identified in the measurement record. First-write measurement includes
validation, encoding, publication and trace instrumentation. The transaction
interval starts at the traced BEGIN and ends on return, including wait/commit cost;
it is not pure compression time or a guarantee of filesystem power-loss durability.

| Operation | Previous | Current | Calculated difference |
| --- | ---: | ---: | ---: |
| Whole first write, identical level-3/byte settings | 32.751 ms | 36.546 ms | -11.6% less time |
| First decoding (filesystem cache not flushed) | 6.808 ms | 4.252 ms | 37.5% less time |
| Warm complete read | 4.006 ms | 0.709 ms | 82.3% less time |
| Write-transaction interval | 32.599 ms | 20.120 ms | 38.3% less time |
| Unchanged snapshot: full submission versus direct references | 5.501 ms | 2.098 ms | 61.9% less time |

Negative "less time" means a slowdown: the new first-write path can cost more due
to staging and one-time round-trip attestation. That trade-off buys shorter writer
occupancy, safely reusable verifications and faster repeated reads/branches; it is
not claimed as a universal first-write speed-up. The default level-1 profile was
selected from the separate encode/decode sweep, not from this fixed-level-3 table.

In the raw categorical comparison the complete database changed from
1,286,144 to 1,187,840 bytes.
With Zstd enabled both databases occupied 917,504 bytes;
new categorical representations do not guarantee another reduction when Zstd
already encodes those fields well. Re-saving an unchanged snapshot added no payloads;
replacing one chunk added one new payload. A reference still has O(chunk-count)
metadata/verification bookkeeping: this is not a constant-time world snapshot.

[Test results](../evidence/storage-profiles-tests.json) ·
[compression/dictionary sweep](../evidence/storage-tuning.json) ·
[whole-store comparisons](../evidence/storage-comparisons.json).
The repeatable script is `tests/measure_storage_profiles.py`, with explicit
`--mode tune|compare`, `--baseline` and `--out` arguments. Measurements use warmed
imports on Linux/CPython 3.13.5, NumPy 2.3.5, Blosc2 4.3.3 / Zstd 1.5.7 and SQLite
from that Python build. No dependency was installed, no filesystem cache was
forcibly cleared, and no Windows or large-world test is implied.

Method references checked for this increment: [Blosc compression API](https://blosc.org/python-blosc2/reference/autofiles/low_level/blosc2.compress2.html),
[Blosc compression/filter/dictionary parameters](https://blosc.org/python-blosc2/reference/storage.html)
and [SQLite isolation](https://www.sqlite.org/isolation.html). These inform the
implementation; the obtained evidence above is Atlas's own bounded testing.

<a id="copy-transport-increment"></a>

### 2.0 Delivered local increment: checklist items 2 and 3

**17 September 2026 — prepared against `remake` commit
`0590774b9d59fa9e6c9cba8f5306a3e2b9f6bc40`; not published by this task.**
The scope is redundant-copy/private-buffer reduction and transport optimisation.
The broad baseline project (item 1) and checklist items 4–12 were not undertaken.
Focused correctness tests and paired kernel measurements are part of verifying
these two changes, not a world simulation or a new general benchmark framework.

**Ownership and copies.** Numerical kernels borrow only aligned, C-contiguous
native binary64 arrays whose base chain ends in immutable `bytes`. Read-only
flags alone, mutable owners, memory maps and subclasses are insufficient. Every
borrow has private shape/dtype metadata and is still checked for finite values,
shape and sign. Other inputs are detached. Cache wrappers capture one immutable
input snapshot for both hashing and calculation; kernels do not copy it again.
Publishing a small slice compacts it rather than retaining a larger parent buffer.
`frozen()` may reuse an already compact immutable payload; new mutable results
still receive immutable backing. No shared global scratch pool was introduced.
Cooling reuses its private final arithmetic buffer; flexure multiplies its private
FFT spectrum in place and releases it before publication. Their equations and
selected backends are unchanged. Conservative allocation admission stays enabled;
it is not a process RSS cap.

**Transport.** `advect_thickness(..., backend="numba")` explicitly selects an
native path, now the default under the optimised-default policy.
`backend="reference"` remains explicitly available for NumPy/math.fsum verification. The native path combines the field update, face flux and totals in a
compiled loop after a separate Courant-admission pass. It preserves the reference's
multiplication and addition order, signs, periodic boundary and refusal behaviour.
It does not add open boundaries, new physics, automatic substepping or clipping.

The native totals use an original exact nonnegative binary64 superaccumulator:
represent each value in units of 2^-1074, accumulate into 34 unsigned 64-bit limbs,
then round once to binary64 nearest/ties-to-even before the unchanged multiplication
by cell spacing. The 2,176-bit capacity exceeds the less-than-2,161 bits needed for
any finite positive binary64 value summed over a signed-64-bit-addressable array.
It is not a signed general-purpose `fsum` replacement or the historical mass ledger.
Tests compare both `math.fsum` and independently summed exact Python Fractions,
including ties, subnormals, wide exponents and overflow. Fast-math, reassociation,
parallel reductions and disk JIT caching are disabled. Results record the selected
backend and numerical-method name; the verifier records compiler versions and a
hash of generated assembly. This is evidence, not a runtime security seal.

**Dependency and use (original 2/3 delivery).** The former optional `transport` extra selected `numba==0.65.1`; the optimised-default follow-up makes it a normal requirement.
No dependency was installed during this task. The default backend does not import
Numba; explicitly requesting it without the supported dependency fails, never
silently substitutes another algorithm. First native use imports/compiles; reuse
within the process amortises that cost. JIT/compiler resident memory is additional
to the kernel's array budget. No persistent transport-result wrapper or additional
cache framework is supplied.

```python
result = advect_thickness(h, u, grid, duration_s, backend="numba", budget=budget)
```

**Obtained evidence.** [131 passing checks](../evidence/copy-transport-tests.json)
include all 93 existing cases, 17 new copy/dependency checks and 21 native checks
(including the nine existing transport cases rerun through the native backend).
Original fixtures and test tolerances are unchanged. Checks include alias mutation,
private metadata, cache-miss snapshot sharing, fresh-process reuse, failure/budget
release, immutable restoration, strict compiler flags and exact comparison of
100 varied transport fields plus 200 Fraction-verified accumulator cases.

[Focused measurements](../evidence/copy-transport-measurements.json) used five
rotated-order warmed repetitions on Linux/CPython 3.13.5/NumPy 2.3.5, Numba 0.65.1
and llvmlite 0.47.0. At 65,536 cells, transport went from 5.498 ms to 0.713 ms;
at 262,144 cells, from 25.682 ms to 3.292 ms: approximately 87% less elapsed time
on those synthetic calls. The fresh first call, including import and compilation,
was 1.944 s. These are not whole-generator forecasts or hardware-independent gains.
At 262,144 cooling samples with the SAME SciPy backend and immutable input,
tracked allocation fell from 10,750,946 to 6,556,944 bytes (39.0%). Tracemalloc
excludes some native/JIT/library allocations; no native or total-RSS memory-saving
percentage is claimed. Buffer borrowing also avoids an input-sized payload copy;
validation scans remain. No speed threshold is embedded in unit tests.

Reproduce the correctness checks in an explicitly prepared environment:

```text
python -I -B tectonics/verify.py             # 110 checks; existing fast/storage extras
python -I -B tectonics/verify.py --native    # 131 checks; additionally transport extra
```

The optional focused measurement script is
`tests/measure_copy_transport.py --baseline PATH_TO_UNMODIFIED_TECTONICS`.
It validates the relevant baseline files against the pinned Git blob identities,
and includes validation/publication costs. It does not measure cache tuning,
compression settings or an entire end-to-end pipeline.

Windows/macOS, Python 3.12, other compiler builds and real geological behaviour
remain unverified. Source changes naturally invalidate prior result-cache keys;
old records are not edited, deleted or repinned. The task creates a local patch,
not a push to origin. Continue to update this reference rather than creating a
separate optimisation report.

Method references: [Numba execution and fast-math semantics](https://numba.readthedocs.io/en/stable/user/performance-tips.html)
and [Python accurate summation](https://docs.python.org/3.13/library/math.html#math.fsum).
The accumulator implementation is newly written, not copied from an external package or solver.

<a id="process-placement"></a>

### 2.1 Per-calculation placement

This is a candidate placement map. “Batch” means a finite group of independent items with fixed inputs, not an instruction to launch one job per cell. A case's execution card in [the execution card section](#execution-card) selects its actual backend and limits. No worker count or hardware default is approved here.

| Process / equations | Candidate parallel unit and backend | Reuse and mandatory dependency boundary |
| --- | --- | --- |
| **P01 / E01–E02: rotations and boundary motion** | Batch points for one known rotation/time; vectorised CPU first. Independent prescribed-time queries may run concurrently. | Cache rotations/shared geometry by full input, time and frame identity. Evolving accepted states are not independent historical queries. |
| **P02 / E03: birth, age, recycling** | Batch age/location updates across stable material IDs. Process independent scenarios separately. | Each creation/removal event has one owner and one ledger transaction. Topology and material transfers must reconcile before commit. |
| **P03 / E04: initial conditions/cooling profiles** | Batch independent point/column queries; threads only for suitable native kernels, otherwise bounded process batches. | Reuse immutable feature geometry and exact profile evaluations. Feature precedence and boundary classification remain deterministic. |
| **P04 / E05–E09: mechanics and coupled heat** | Native threaded sparse/structured solves; MPI domain decomposition only for a verified distributed formulation. | Pressure/velocity and coupled thermal fields require global or iterative interface coordination. Do not solve arbitrary tiles as independent mechanics. |
| **P05 / E10–E11: material transport/projection** | Disjoint particle batches from a frozen velocity field; private deposition buffers or an explicitly race-safe reduction. | Locate/migrate particles, combine contributions, then make the projection visible. Shared mesh writes are not independent. |
| **P06 / E12–E13: flexure** | Independent load scenarios; one global linear solve or transform per coupled domain. Vectorised/native kernels first. | Reuse a factorisation only for the same operator. A global load response cannot be produced by unrelated tile solves without valid boundary treatment. |
| **P07 / E14–E15: compaction/subsidence** | Independent columns when lateral coupling is absent; reuse operator/profile setup within a batch. | Column calculations may be independent; their shared flexural or water-load response is not. Preserve solid inventories and reference states. |
| **P08 / E16–E17: kinematic extension** | Compiled/vectorised transport over disjoint output cells from an immutable prior step; halo exchange if partitioned. | Honour stencil/Courant conditions and boundary fluxes. The next interval depends on the accepted current state. |
| **P09 / E18: routing/accumulation** | Build routing with a chosen algorithm; parallelise independent components or dependency-ready graph levels when justified. | Upstream contributions precede downstream accumulation. Real lake storage, spill events and globally changed receivers require coordinated updates. |
| **P10 / E19–E21: incision/diffusion** | Receiver-first incision ordering; independent eligible branches. Batch ADI line solves within each directional sweep. | Receiver values precede donors for the selected implicit incision; ADI directions and coupling stages retain their order. |
| **P11 / E22–E23: sediment and remapping** | Local face calculations and disjoint remap blocks; MPI exchanges later. | One oriented flux per shared face, used with opposite signs. Reconcile migrations, boundary export and remap budgets before publication. |
| **P12 / E24–E25: elastic faults** | Fixed-geometry observation/source blocks; GPU only for a sufficiently large eligible workload. | Track traction/slip conventions and near-field error. Exact blocked evaluation and approximate low-rank compression have different acceptance tests. |
| **P13 / E26: equilibrium/property maps** | Independent pressure–temperature–composition cases; batch by appropriate workload. | Database and phase rules are fixed. A warm start must not silently select the wrong equilibrium; surrogate tables need withheld-state checks. |
| **P14 / E27: thermal-history diagnostics** | Independent grains/histories, read once and batched; stable output ordering. | Preserve birth, sediment inheritance, grain parameters and complete thermal history. Do not distribute a single sequential history as unrelated time slices. |
| **P15 / E28: combined surface update** | Independent local arithmetic only after its movement/load/erosion inputs are ready. | One owner per physical contribution; deterministic reconciliation and a single accepted-state publication. |

These mappings are engineering proposals grounded in the F/O method studies, not claims that each package implements all the listed backends. Whole-scenario ensembles usually offer a different opportunity from making one scenario finish sooner; measure **throughput** and **single-case latency** separately. [R01](TECTONICS_PLAN.md#research-basis) / [R02](#scientific-methods) / [R03](TECTONICS_PLAN.md#research-basis) / [R04](TECTONICS_PLAN.md#research-basis)

<a id="execution-contract"></a>

### 2.2 Execution and failure

**Choose the parallel layer, do not multiply all of them.** Prefer bounded scenario or independent-column work first, then native kernel parallelism where appropriate. A resource owner admits work using CPU slots, total host memory, device memory and I/O capacity. Existing Atlas scheduling should be reused where compatible rather than creating another universal scheduler.

| Decision | Required rule for the selected case |
| --- | --- |
| **Threads or processes** | Threads are candidates for I/O or kernels proven to release the interpreter lock and be thread-safe. Processes are candidates for substantial Python-bound or isolated independent tasks. Record interpreter/build, process start method, serialisation and child initialisation. Never assume a fork-only design works on Windows. |
| **Persistent workers and task size** | Initialise verified read-only data once per worker where allowed. Bound both item count and bytes in flight. Select batch size from setup, serialisation, memory and cancellation costs. Keep tiny jobs serial when that wins. |
| **Nested threading** | Set and record outer workers and inner BLAS/OpenMP/native thread budgets. Admit the maximum concurrent combination, including helper/compression/I/O pools; do not let each layer assume exclusive use of every core. |
| **Shared memory** | Share immutable numerical buffers, not mutable arbitrary object graphs. Define owner, shape, dtype, lifetime and cleanup. A read-only view does not freeze other aliases. Use disjoint writes or private buffers plus a reviewed reduction. |
| **Ready-work scheduling** | Submit only tasks whose inputs are complete. The coordinator resolves dependencies; pool workers do not wait on jobs submitted to the same saturated pool. Do not enqueue the entire world in advance. |
| **GPU eligibility** | Compare a compiled/vectorised CPU baseline with end-to-end device execution, including compilation, allocation, transfers, synchronisation and receipts. Keep eligible state resident across compatible kernels. Pin device/backend/precision; do not silently use lower precision or change backend after failure. |
| **MPI / distributed domains** | First verify the serial spatial operator. Define partition/halo ownership, collective ordering and global budgets. Exchange current boundary data and measure communication; shared drainage and pressure constraints survive partitioning. |
| **Overlap** | Overlap independent preparation, nonblocking communication or writing only with immutable input/output snapshots and bounded buffers. Consume an exchange only after completion. Asynchronous syntax alone is not evidence of useful overlap. |
| **Load balance and locality** | Weight jobs by layers, active particles, expected solver iterations and transfer work, not cell count alone. Study placement, CPU affinity/NUMA and repartitioning only if measured locality or imbalance warrants their complexity. |
| **Cancellation and retry** | Stop new admission; request cooperative cancellation at safe boundaries; retain the last accepted state. A timeout does not imply a running kernel has stopped. Quarantine late results by attempt/generation ID; retries cannot double-apply material transfers or publish a partial step. |

Runtime basis: CPython documents process-serialisation/import requirements, nested-pool deadlocks and the distinction between cancelling queued and running work. NumPy documents both native operations that can use threads and hazards from shared mutable arrays; underlying BLAS may have its own thread pool. These constraints inform the proposals above without selecting a dependency version. [[PS01][url-002]; [PS02][url-003]; [PS03][url-004]]

**Deterministic work identity:** assign random streams to stable scientific identifiers—world/case, material or feature ID, process, and declared event—not to whichever worker or batch receives them. Record the generator and draw/counter policy. Rescheduling or changing worker count must not change an intended fixed stochastic scenario. A new mesh may change scientific sampling; distinguish that from an execution-only partition change. NumPy's parallel-stream mechanisms are references, not automatic guarantees of task-order invariance. [[PS04][url-005]]

**Equality policy:** maintain exact discrete identities and any selected integer accounts. For floating calculations, predeclare reproducibility within a pinned execution and bounded equivalence across allowed backends/reduction orders. Reordering must not silently change event selection, accepted branches or physical budgets. If a change crosses an event threshold, investigate it; an average field norm alone is not sufficient. Exceptions to bitwise equality belong to a reviewed new numerical identity, never a weakened historical hash check.

**Two illustrative cost checks, not forecasts:** for fixed total work, ideal strong scaling has $S(p) \leq 1/[f_s+(1-f_s)/p]$, where $f_s$ is the serial fraction and $p$ the worker count. For a fixed expensive setup, reuse becomes worthwhile only when $T_{\mathrm{setup}}+nT_{\mathrm{reuse}}<nT_{\mathrm{fresh}}$, counting verification and transfer in the relevant terms. Real contention, memory bandwidth, communication and changed workload can invalidate a simple estimate. NVIDIA's guide treats transfer costs and strong/weak scaling explicitly; GPU selection here remains hardware-neutral until a case requires it. [[PS05][url-006]]

<a id="cache-contract"></a>

### 2.3 Cache identities and lifetime

**A cache is not scientific authority.** Reuse existing identity/verification mechanisms. Distinguish **R: read-only source/metadata reuse**, **G: immutable geometry**, **L: linear/numerical setup**, **J: compiled kernels**, **V: derived fields**, **S: complete scientific results**, and **H: authoritative history dependencies**. H is listed to prevent it being treated as a disposable cache.

| Object and class | Identity required for reuse | Lifetime, invalidation and explicit boundary |
| --- | --- | --- |
| **Decoded source/feature data — R** | Exact bytes, schema, units, feature precedence and parser identity. | Reuse within a verified immutable snapshot. Modified contents or membership invalidate; timestamps alone do not authenticate scientific bytes. |
| **Rotations, shared boundaries, spatial indexes — G** | Geometry/rotation inputs, time/interval, frame/radius, side conventions, query options and algorithm. | Bounded per-process or safely shared immutable cache. Motion, topology, geometry or query-policy changes invalidate affected entries. |
| **Mesh metrics and sparsity — G/L** | Mesh geometry/topology, space/DOF layout, partition where relevant and boundary-type structure. | A moved mesh may retain connectivity but not metric coefficients. Sparsity-pattern reuse is not numeric-matrix reuse. |
| **Factors and exact response operators — L** | The entire numerical operator: coefficients, boundaries, mesh, timestep where present, constraints, precision and implementation. | Reuse for a changed load/RHS only if the operator is unchanged. A changed RHS still creates a new scientific result identity. |
| **Preconditioners / previous solutions — L** | Original setup identity plus current operator and explicit lag/warm-start policy. | Reuse across changed coefficients is a numerical strategy, not an exact result hit. Check the current true residual and solution; rebuild on predefined criteria. |
| **Compiled kernels / FFT plans — J** | Expression, compiler/build flags, ABI, architecture/backend, dtype and required layout/shape. | Reuse compilation when only eligible runtime parameters change; those parameters still alter the scientific invocation. Hash an executable artifact where relevant. |
| **Particle projections / derived fields — V** | Particle/field state, weights, support, interpolation/conservation method and boundaries. | Invalidate on every relevant mutation, including aliases. Batch mutations and reconstruct once per requested complete state; no partially updated view escapes. |
| **Routing and accumulated forcing — V** | Physical/routing surface, masks, outlets, receiver/depression policy, runoff/storage and interval. | Reuse geometry separately from forcing-derived values. Changed drainage may affect distant downstream cells; no blanket tile-local invalidation. |
| **Complete stage or scenario products — S** | Canonical inputs, full transitive dependencies, equations/closure, numerical policy, state, time, seeds and relevant runtime/backend. | Bound cache by bytes/cost. Authenticate data and completeness before reuse. Local or cross-run reuse cannot silently repin a historical result. |
| **Property/surrogate tables — V/S** | Database, parameters/composition basis, sampled domain, construction method, interpolation/error envelope and version. | Approximations require N/M validation. Out-of-range or phase-boundary queries fall back only to an explicitly authorised method, otherwise refuse. |
| **History frames / checkpoints — H** | Immutable logical and stored identities, codec, parent/manifest references and complete restart dependencies. | Protect while referenced. No eviction, automatic garbage collection, recompression or migration is authorised by this plan. |

**Concurrent cache rules:** finite byte budgets for each process and shared store; independent accounting for duplicated process-local entries; immutable or detached returned objects; one creator per key where useful; verified temporary publication before an atomic/coherent visibility change; leases/locks with failure recovery; pin entries while in use. Differing results under one exact identity are an error, not “last writer wins”. A missing disposable entry can trigger recomputation; corruption must be reported and quarantined or refused, not disguised as an ordinary miss. Missing H data blocks restart.

**What invalidation must do:** source, parameter, mesh, boundary, time, seed, precision, code, partition and database changes each have a tested path to the correct affected products. Nonlocal operators may require wider invalidation. A changed scenario cannot inherit a valid-looking output merely because filenames match. Dependency signatures must cover every consumed input, not only those convenient to hash.

**Source verification is not removed to make caching faster.** Separate trusted immutable snapshots and invocation-local reuse from externally mutable paths. Stream and batch verified reads where the established contract permits it; retain raw-byte checks at required boundaries. Incremental hash structures are candidates only with an explicit immutable write/commit protocol. No mtime-only substitute or silent weakening of the existing Atlas checks is allowed.

PETSc explicitly permits preconditioner reuse when matrix values change but warns that iteration counts can increase. Hence a cached factorisation of an unchanged operator, a lagged preconditioner and a cached final answer receive three different acceptance rules. [[PS06][url-007]]

<a id="storage-contract"></a>

### 2.4 Memory, storage and recovery

**Budget peak simultaneous ownership, not just one array.** The execution card accounts for accepted state, candidate state, shared read-only data, per-worker scratch/native libraries, solver setup, caches, transfer buffers, queued outputs and publication/recovery staging. Record host and device memory separately. Sum private memory and shared physical allocation carefully; do not multiply-count mapped shared pages or use that ambiguity to omit genuine costs. Compare the model with actual whole-process/system peaks in a later authorised run.

| Design area | Proposed method and testable requirement |
| --- | --- |
| **Field layout and IDs** | Use compact numeric buffers and stable-ID lookup tables where appropriate; compare structure-of-arrays and array-of-structures for actual access patterns. Spatial reordering must not change geological identity or numerical tie rules. Do not squeeze the fixed-quantum ledger into an inadequate dtype. |
| **Temporary buffers** | Preallocate bounded scratch, use output buffers and fuse compatible passes to avoid repeated full-state copying. Track aliases/lifetimes. Copy-on-write must keep rejected trials from altering accepted state. Fusion or vectorisation changing reduction order gets N review. |
| **Sparse / active representations** | Store only active fields, supports or material histories where semantics permit it. Missing, masked, unknown and physical zero remain distinct. Spatial culling must agree with exhaustive reference queries at boundaries. |
| **Out-of-core execution** | Consider memory maps or streamed blocks when data exceeds RAM. Select access order to limit paging/read amplification; global solvers still need their declared global coupling. Out-of-core is a resource strategy, not proof of speed. |
| **Chunks and compression** | Choose computational blocks, storage chunks and shards separately using actual reads/writes. Benchmark lossless codecs/levels and decoded working sets. Large compression/thread pools share the overall resource budget. No universal chunk size is prescribed. |
| **Output sampling** | Generate requested layers/regions/times; defer pure review exports and detail products when unnecessary. Do not omit mandatory scientific receipts or material history needed by a claimed diagnostic. A lower history sampling rate is a scientific/numerical choice when it loses relevant information. |
| **Asynchronous I/O** | Write only frozen accepted-generation data through bounded queues. Do not let the next state overwrite a writer's buffer. Use one owner per physical chunk/shard or proven synchronisation, and publish the bundle only when all required parts validate. |
| **Checkpoint cadence** | Separate recovery checkpoints from scientific output and accepted-step receipts. Choose cadence from measured write/verify cost, permitted lost work, storage and restore requirements—not a universal every-step or every-N-years rule. |
| **Incremental storage** | Consider immutable deduplicated blocks, dirty-chunk writes or bounded delta chains only for a new reviewed storage path. Include parent closure and compaction/recovery cost; a delta without all parents is not restorable. Do not alter old R5 files. |

The Zarr performance guide documents chunk-shape, memory-layout and concurrency trade-offs. It is a reference for these design decisions, not a requirement to migrate every field to Zarr or rely on a particular store's atomicity. [[PS07][url-008]]

**Storage acceptance:** verify restart after the original test state is unavailable; test missing parents, truncated/corrupt chunks, disk-full and interrupted publication. Record the point at which a generation is coherent and the separately tested durability guarantee of the filesystem/storage backend. Renaming a manifest is not by itself proof of power-loss durability across all files. Preserve a previous complete generation until the replacement passes its publication contract.

Lossless compression is the default candidate for scientific/restart state. Lossy compression, quantised fields or reduced-precision history require an explicit new error/physical-validity decision; none may be slipped in as “just storage”. Recovery stores remain dependencies, not expendable performance caches.

<a id="volumetric-storage"></a>

### 2.5 Volumetric geology without a per-voxel object engine

#### Evidence and representation

- Numerical domain, storage working set and display range are separate Atlas
  responsibilities; displaying a region does not define its physical boundary.
- Tommaso Checchi's Bedrock format note describes local block palettes and packed
  per-block indices. The protocol note is historical, not a claim that every
  current Java/Bedrock detail is identical.
  [Developer palette note][url-010]
- His client-cache note describes content-addressed reuse of unchanged blobs.
  Network reuse is distinct from reducing a physics solver's computational work.
  [Developer cache note][url-011]
- OpenVDB gives a more directly relevant continuous-volume reference: individual
  voxels, uniform tiles and background values, with active/inactive states.
  [OpenVDB overview][url-012]
  This is an additional method-study reference, not a selected dependency.

#### Candidate representation

| Concern | Proposed adaptation | Required scientific boundary |
| --- | --- | --- |
| Large 3D material regions | Spatial chunks, material-ID palettes, uniform tiles or layer descriptions; allocate detail only where it varies | The same material may have nonuniform temperature, stress or porosity. Constant material ID is not a constant physical state. |
| Continuous physical fields | Separate contiguous arrays or sparse/implicit field representations where justified | Do not quantise temperature/stress to a tiny palette merely to improve compression. Any approximation needs an error policy. |
| RAM residency | Load required chunks/fields, with an explicit byte budget and bounded I/O prefetch | Storage residency is not permission to ignore physical influence from outside the loaded region. |
| Changed regions | Dirty flags, dependency-aware invalidation and immutable chunk identities | A changed region may affect distant drainage, heat or mechanically coupled fields; do not invalidate by viewer distance alone. |
| Uniform regions | Losslessly represent exactly identical values once | Near-uniform replacement is lossy. Unknown, empty, absent, unloaded and uniform are different states. |
| Material history | Stable material/origin IDs separate from chunk and computational-node IDs | Remapping/deformation cannot move fixed voxel IDs and assume material conservation follows. |
| Resolution | Coarse planetary/regional support plus optional fine volumetric domains/output | Output voxels are not necessarily solver cells. Scientific 3D fields, voxel storage and block rendering are independent choices. |
| Parallel chunks | Batch independent storage/encoding, bounded workers, owned writes | Coupled solvers need consistent face fluxes/halo exchange and often global solves; chunks are not automatically independent mechanics. |
| Recovery | Reuse existing verified immutable objects and publish a consistent manifest | Unchanged bytes do not make a missing dependency safe to discard; no duplicate generic cache/recovery framework. |

#### Storage arithmetic, not a benchmark

For a 32 cubed chunk there are 32,768 locations. Sixteen categorical material types
need 4 bits per index in an ideal bit-packed representation: 16,384 bytes (16 KiB),
plus palette and metadata. One binary64 scalar at those locations uses 262,144
bytes (256 KiB). Eight such fields use 2,097,152 bytes (2 MiB), before working copies,
solver state or history. Uniform fields can compress well; continuously varying
fields may not. These are raw storage calculations, not measured Atlas
memory or proposed final chunk dimensions.

The 3D count grows with depth as well as area. A hypothetical 1 km cubed domain at
1 m spacing contains 1 billion voxels. One binary64 field alone takes 8 billion
bytes (8 GB decimal). Do not extrapolate a game's visible block count into a
planet-wide simultaneous thermomechanical workload.



#### Representation acceptance

Compare candidate chunks/palettes, layer columns and sparse tiles on uniform,
layered, faulted and highly heterogeneous synthetic geology. Include smooth and
sharp continuous fields. Record total resident and persistent bytes, indexing,
encoding/decoding, random access, halo reads, write amplification and actual
solver time. Match physical accuracy and conservation, not just displayed detail.

Require exact round trips for lossless data, explicit unknown/missing handling,
finite memory budget, restart after source changes, conservative material remap,
and cross-chunk results matching a monolithic reference under the declared policy.
Only then choose chunk dimensions, codec or sparse hierarchy. The current small
1D reference kernels are intentionally storage-agnostic, not the permanent world
representation and not an obstacle to 3D development.

<a id="native-boundary"></a>

### 2.6 Language and native-call boundary

**Revision 4 design recommendation:** retain Python for case definitions, orchestration, validation and reviewable scientific logic. Use appropriate native-backed numerical routines for bulk work. Evaluate a narrowly compiled kernel when a measured path justifies it; C++ is a candidate, not a whole-project rewrite decision. Numba or an existing scientific routine may answer a narrower need. Do not accumulate multiple native languages and accelerators without a maintained use case. This is implementation guidance, not permission to install or migrate anything.

NumPy numerical arrays and many operations already use compiled implementations. Many native operations release the interpreter lock, but that does not mean every operation is internally parallel or that shared writes are safe. The high-level language alone does not predict the performance of the complete calculation. [LS01][url-013] · [LS02][url-003]

**Observed starting point, not a completed performance study.** At remake commit `11317165b7e2aeab7201a1fe3e3f646cb640d51e`, the foundation already has NumPy fields and batched operations. The earlier implementation record reports 53 mathematical tests; that evidence is not a benchmark or a completion claim for W01–W04. This revision does not rerun those tests or reopen old numerical policy.

| Existing path | Candidate study | Preserve before judging speed |
| --- | --- | --- |
| `thermal.py`: Python iteration around `math.erf` | Compare an eligible bulk native error function; SciPy supplies an array `erf` as one candidate. | Broadcasting, zero age, surface/depth limits, finite-range handling and independently bounded error. No silent dependency installation. |
| `transport.py`: multiple array passes | Compare a fused native loop and reusable private scratch with the same upwind formulation. | Outgoing Courant-sum refusal, positivity, shared-face fluxes and material-budget diagnostics. Reduction-order changes receive N review. |
| `flexure.py`: native FFT plus reusable coefficients | Measure setup, batched application, copies and workspace before proposing a different backend. | The current discrete centred-difference eigenvalues; continuous spectral k^4 is a different numerical operator. Material/grid changes invalidate setup. |
| `_validation.py`: detached inputs and byte-backed immutable results | Evaluate allocation only after proving equivalent ownership and lifetime protection. | A read-only view cannot prevent another alias from mutating its backing buffer. Accepted state must survive failed and cancelled attempts unchanged. |

Source basis: [language assessment](#native-boundary), with pinned source links. These are observed implementation choices, not established bottlenecks. The proposed error-function route is documented at [LS03][url-014].

#### Native interface requirements, not a general backend framework

Use whole arrays or substantial batches across the boundary, never a Python/native call per cell. Before implementation, complete the execution card with dtype, shape, stride/contiguity, alignment and byte-order expectations; allocation and conversion policy; input lifetime and output ownership; and supported platform/build identities. Reject unsupported buffers or make an explicit, measured conversion. Do not let a convenience binding silently cast precision or allocate an unreported copy. pybind11 provides such interfaces, but copy avoidance depends on compatibility and lifetime. [LS05][url-015]

A native calculation must not modify the accepted input. Hold its backing owner alive while work runs; release the interpreter lock only around code that does not touch Python-managed objects. Use one output owner and controlled joins. Count native threads together with outer workers. Translate errors deterministically, quarantine incomplete results and record authorised fallback rather than silently switching backend after failure.

No default fast-math, unsafe reassociation or reduced precision is selected. Record compiler, optimisation flags, target architecture, numerical-library and binary identity where they affect results. Numba's documentation demonstrates that fast-math can change floating-point behaviour. [LS04][url-016]

**Selection gate:** compare the existing reference, the best appropriate array/routine baseline and the narrow candidate at the same equation, workload and declared error. Include import/JIT/build setup, dispatch, copies, temporary/native memory, transfers, verification and small-case regressions. A portable development and test path is part of the decision. At most one new compilation route should be selected for the first justified kernel; broad C++/Rust/GPU migration remains unselected.

## 3. Candidate decisions, evidence and one execution card

<a id="candidate-register"></a>

### 3.1 PF01–PF26: choose, do not enable indiscriminately

**PF01–PF26 are planning checklist IDs, not new Atlas modules or implemented switches.** Assess relevance when a kernel or its workload is selected; do not implement every row. [the candidate register section](#candidate-register) and O01–O17 retain the detailed software-method background. All entries currently have status **CANDIDATE — NOT MEASURED**.

| ID / class | Family to assess | First relevant work; rejection or escalation condition |
| --- | --- | --- |
| **PF01 E/S** | Demand-driven evaluation, common subexpression elimination and dependency-aware incremental rebuilds. | W01 onwards; dependencies and nonlocal effects must be complete. Do not eliminate required evidence. |
| **PF02 E/N** | Better graph ordering, spatial indexes, candidate pruning and active-domain algorithms. | W01/W02/W09; compare with exhaustive queries and actual closed-basin semantics. |
| **PF03 E** | Bounded source, geometry and final-result caches with concurrent-safe publication. | W01 onwards; reject stale reuse or lookup/verification overhead exceeding benefit. |
| **PF04 E/N** | Reuse symbolic structure, numeric factors, transform plans and compiled expressions. | W03/W04/W07; distinguish unchanged operators from changed coefficients. |
| **PF05 E/S** | Compact material histories, deferred gridding and deduplicated immutable data. | W02 onwards; preserve event/lifecycle closure and diagnostic history. |
| **PF06 E/N** | Contiguous layout, vectorisation/SIMD, spatial ordering and cache blocking. | Relevant kernel; measure bandwidth and any changed floating reduction/tie behaviour. |
| **PF07 E/N** | Buffer reuse, copy elimination, loop fusion and batched state mutations. | W02 onwards; alias, rejected-trial and lazy-invalidation tests required. |
| **PF08 E/N** | Compiled hot loops, specialised kernels and eligible JIT/AOT compilation. | Only a measured hot path; include compile/startup cost and compiler identities. |
| **PF09 E/N** | Shared-memory threads / native parallel loops. | Independent numerical batches; use safe mutation and explicit inner-thread budgets. |
| **PF10 E** | Persistent process pools, coarser task batches and bounded work queues. | Independent CPU-bound work; serialisation/startup may make serial execution preferable. |
| **PF11 E/N** | Parallel scenarios, ensembles and independent diagnostics. | W10 or declared independent cases; separate throughput from latency and fix stable random streams. |
| **PF12 E/N/S** | GPU batches, residency, coalesced access, kernel fusion and staged transfers. | Large eligible arrays/kernels; require CPU comparison and real device-memory/transfer accounting. |
| **PF13 E/N/S** | MPI decomposition, work-weighted partitioning and repartitioning. | W11 after a verified serial spatial operator; halo, global budget and iteration tests required. |
| **PF14 E/N** | Nonblocking communication, preparation/compute overlap and bounded asynchronous I/O. | A measured idle/transfer cost; preserve immutable state and completion barriers. |
| **PF15 E/N** | Locality, CPU affinity, NUMA placement and load balancing. | Measured memory/locality or workload imbalance; no machine-specific tuning presented as portable default. |
| **PF16 E/S** | Sparse storage, active sets, memory maps and out-of-core streaming. | W02/W07/W09/W11; validate active/unknown semantics and include paging costs. |
| **PF17 E/N** | Chunk/shard/access layout, lossless compression and format-conversion avoidance. | First large fields/history; include encode/decode/metadata cost and writer ownership. |
| **PF18 E/S** | Incremental checkpoints, bounded delta chains and independent output cadence. | Restart-capable cases; exact dependency closure and isolated recovery required. |
| **PF19 N** | Preconditioning, multigrid, scaling, warm starts and Krylov-space reuse. | W07 or relevant linear solve; use current residuals, null spaces and rebuild/branch-sensitivity tests. |
| **PF20 N** | Implicit, spectral, ADI and structured/specialised direct algorithms. | W03/W04/W09; only for compatible equations/boundaries, with temporal accuracy tests. |
| **PF21 N/S** | Adaptive timesteps, event-aligned integration, multirate subcycling and solver-work balancing. | A verified time-dependent kernel; preserve coupled flux intervals and event accuracy. |
| **PF22 N/S** | Adaptive meshes, nonuniform layers, conservative remeshing and coarse/fine detail. | Accepted operator and error measure; do not refine merely to improve appearance. |
| **PF23 N** | Mixed precision, iterative refinement and controlled approximate arithmetic. | Measured precision/bandwidth bottleneck; exact ledgers stay exact and event decisions must remain valid. |
| **PF24 N/M** | Bounded lookup tables, low-rank compression, reduced-order or learned surrogates. | Conditional specialist; withheld-state error, conservation, applicability and explicit rejection outside validity. |
| **PF25 M** | Reduced physical equations or dimension reduction. | Scientific case design, not a speed patch; requires separate physical justification and identity. |
| **PF26 N/S** | Parallel-in-time / speculative future intervals. | Deferred, not a 1.0 default: adaptive events and path-dependent histories need a separately proven algorithm. Independent prescribed-time geometry queries do not establish this. |

Assess energy, monetary cost or interactive response when they become actual user requirements; no cloud spend or service is selected here. Automated tuning is a bounded, reproducible future experiment, not permission for an unbounded parameter search. Tune on a calibration workload and test a withheld workload; never tune physical tolerances just to improve speed.

<a id="performance-tests"></a>

### 3.2 Measurement and PT01–PT14

**No benchmark is performed by this revision.** Each later study states its scientific question, unchanged/changed equation and E/N/M/S class, baseline and candidate identities, numerical/physical error criteria, workload, permitted resources and stop conditions before execution.

Use a small correctness fixture, a meaningful medium case and a bounded stress case where appropriate. Compare the same physical problem and output obligations. For numerical alternatives, compare at matched error rather than equal cell count or nominal timestep. Record dry/no-op work, changing topology, high layer count, difficult coefficients, cache pressure and repeated updates when relevant; a warm best case alone is insufficient.

| Measurement | Required interpretation |
| --- | --- |
| **Timing** | End-to-end wall time plus non-overlapping critical-path intervals; separate component CPU/device work. Overlapped worker times cannot be summed into elapsed time. Include source verification, pool/compile setup, rejected trials, transfers, checks and publication. |
| **Cold/warm state** | Distinguish application-cache state, new/existing process, compiled-kernel cache, solver setup and OS filesystem cache. Do not claim cold disk merely because the application cache was cleared. No destructive cache flushing is implied. |
| **Repetition** | Predeclare a repeat count appropriate to cost/noise; use at least five paired or order-balanced repetitions when affordable, otherwise report the smaller sample and limited confidence. Report median, spread and outliers rather than only the fastest run. |
| **Parallel scaling** | Strong scaling: fixed problem versus worker count. Weak scaling: fixed work per worker with growing problem, explicitly not the same speed comparison. Report efficiency, peak memory, imbalance, synchronisation and useful physical work completed. |
| **Memory/storage** | Peak whole-run host/device memory, cache and queue peaks, scratch/staging/recovery bytes and persistent output. Count native allocations and spawned workers. Report any sampling blind spots. |
| **Accuracy** | Field/observable errors, conservation residuals, convergence, event choices, accepted/rejected intervals and unchanged identities. A lower residual alone is not the physical acceptance result. |
| **Profiling** | Sample or instrument to locate setup, allocation, I/O, communication and kernel costs; separate profiling runs from uninstrumented timing if overhead is material. PETSc's event/stage profiling is one documented reference, not a selected Atlas dependency. |

[[PS08][url-017]; [R02](#scientific-methods), O01–O17]

**Acceptance decision:** retain a candidate only if it passes its scientific/numerical and recovery contracts and provides the predeclared useful improvement—time, memory, throughput or feasible scale—without an unacceptable regression elsewhere. No universal speedup percentage is invented. An optimisation with no demonstrated benefit is deferred/rejected rather than enabled because it sounds modern. Record tested interactions between accepted optimisations; their individual speed ratios are not multiplicative forecasts.

The following **PT01–PT14** tests supplement T01–T16. They test execution and storage, not replace physical validation. All are planned, not run.

| ID | Required challenge and expected invariant |
| --- | --- |
| **PT01** | Compare serial, threaded, process and eligible device paths under the declared equality policy, including discrete events and material accounts. |
| **PT02** | Change worker count, task order, chunk assignment and retry timing: scientific IDs and fixed-scenario random draws remain stable. |
| **PT03** | Mutate each cache input independently—source bytes/membership, frame/time, parameters, mesh, boundary, seed, precision, code/database—and verify the correct transitive invalidation. |
| **PT04** | Concurrent same-key requests, creator crash, corrupt/truncated entries and conflicting results: no partial/stale hit or silent overwrite. |
| **PT05** | Shared-array alias mutations, lazy-field invalidation and rejected trials: accepted state and any cached immutable view remain unchanged. |
| **PT06** | Saturated queues, nested thread pools, memory pressure and oversized batches: admission remains finite and no deadlock or hidden oversubscription is accepted. |
| **PT07** | Partition a river/material path and a mechanically coupled region: conserve shared-face fluxes and reproduce the reviewed solution within the specified policy. |
| **PT08** | Reuse factors only for unchanged operators; challenge lagged preconditioners, warm starts and changed coefficients with fresh solutions/current residuals. |
| **PT09** | Interrupt, timeout or kill a worker during a candidate/commit/write: retain the previous complete generation, reject late results and avoid duplicate transfers. |
| **PT10** | Restore checkpoints/deltas after removing access to original test directories; missing history parents or corruption must not appear as a valid restart. |
| **PT11** | Vary chunks, lossless codecs, write order and streaming block sizes: preserve required logical values/identities and bound total working memory. |
| **PT12** | Change precision, surrogates, mesh and timestep only under N/M/S review: assess withheld states, near-event thresholds, sharp contacts and phase boundaries. |
| **PT13** | Change compiler/backend/library/thread/start-method identity: refuse incompatible cached results and document fresh execution; record any authorised fallback explicitly. |
| **PT14** | Evaluate accepted optimisation combinations on cold/warm and small/meaningful/stress workloads: reject hidden setup, verification, communication or recovery regressions. |

<a id="execution-card"></a>

### 3.3 Inline execution card

**Each selected calculation gets one compact execution card, not a new framework.** The field groups below are an inline planning template, not runnable configuration or a separate document to maintain. Fields that determine the next experiment must be resolved before that experiment; unrelated future hardware details do not block a small mathematical reference.

| Field group | Required decisions |
| --- | --- |
| **Scope and identity** | Case/kernel, W/P/E/O IDs, physical/closure and numerical identity, baseline, equality policy, input/output requirements and status. |
| **Dependency and ownership** | Read/write sets, immutable snapshots, single-writer/flux/commit owners, sequential barriers and retry/event rules. |
| **Execution** | Candidate and selected CPU/thread/process/GPU/MPI mode, fixed start method where used, outer/inner budgets, grain size, queue-byte limit, partition and cancellation behaviour. |
| **Reuse** | Cache/setup objects, canonical dependencies, lifetime, byte budget, storage tier, mutation invalidation, sharing/publication and corruption rules. |
| **Resources and output** | Host/device peaks, scratch/persistent/staging/recovery budgets, chunk/codec policy, transfer ownership, output and checkpoint cadence. |
| **Evidence** | PF candidates assessed, applicable PT/T tests, workload/repetitions/cold-warm definition, error/benefit criteria, logs/measurements and accepted/rejected/deferred decision. |

**Worked candidate: rotations (W01/P01).** Read fixed point coordinates and one rotation/frame; write a separate output array. Start with a vectorised CPU batch versus an independently checked small reference. Cache a rotation only under its complete inputs/time/frame; cache no per-point result unless repeated demand justifies it. No inner/outer nested parallelism by default. PT01–PT05/PT13 and T01–T02 apply. Batch size, thread budget and benefit remain to be measured; GPU is deferred unless the workload justifies it.

**Worked candidate: uniform flexure (W04/P06).** Compare the analytic sinusoidal reference with a selected compatible sparse or spectral solve. Reuse the same operator for independent load vectors; changed stiffness, density, mesh or boundary invalidates numeric setup. Treat the domain solve as coupled, not independent tiles. Allocate operator/factor/transform buffers once within a finite envelope. PT01/PT03/PT05/PT08/PT14 and T07 apply. This planning example is partly realised by the restricted first foundation; no performance result or broader flexure capability is established.

**Worked candidate: extension/material transport (W02/W05/P08).** Freeze the accepted field, evaluate disjoint output regions with valid halo data, accumulate consistent face transfers and reconcile the candidate before a single commit. Use separate candidate/scratch buffers and refuse alias writes into accepted state. Reuse only unchanged geometry, not old state-dependent fluxes. PT01–PT03/PT05–PT07/PT09 and T03/T14/T15 apply. Sequential physical intervals remain sequential unless a separately validated algorithm replaces them.

Keep this record with the selected case and its evidence. Missing fields affecting that case must be resolved before its run; unrelated future hardware choices do not block a small reference. The [plan](TECTONICS_PLAN.md#numerical-and-computational-design) owns W00–W12 placement. No additional general execution-card guide or policy file is needed.

<a id="scientific-methods"></a>

## 4. Scientific-software methods O01–O17

These retained cards are the method-specific part of former Report 02, consolidated here. F01–F17 still identify the scientific software families, O01–O17 their optimisation studies, and E/P IDs the earlier equation/process map. Their sources and qualifications are preserved. They are alternatives or conditional references, not seventeen dependencies to integrate. Cross-cutting policy now lives above, rather than being repeated for each software review.

<a id="O01"></a>

### O01 — GPlates/pyGPlates: bounded geometry and rotation reuse

**Observed method.** RotationModel and TopologicalModel reuse reconstruction trees and resolved time snapshots; the documented topology cache supports least-recently-used eviction and can otherwise be unlimited. Recreating the model object repeatedly discards useful reuse. [SC-S02][url-018]

**Proposed Atlas adaptation — E.** Cache the result of a pure geometry/rotation stage using a key containing input-content identities, world geometry, reference frame, time interval, algorithm version and every topology/strain option. Set a byte budget, not only an entry count: a complicated snapshot can be much larger than another. Reuse decoded immutable geometry inside a verified invocation, while retaining required raw-source checks across invocations.

**Cost hypothesis.** Savings exist only if queries repeat and cache lookup/authentication cost is smaller than reconstruction. An LRU lookup can be approximately constant-time; geometry construction has its own nontrivial cost. Do not extrapolate cache-hit speed to cold runs.

**Proposed measurement and refusal tests.** Compare identical cold/warm query sequences; record decode count, geometry-build count, verification time and peak cache bytes. Mutate rotations, anchor frame, strain policy, input membership and producer code independently. Each relevant change must invalidate the result. Freeze outputs or return detached copies so callers cannot poison shared cached geometry.

<a id="O02"></a>

### O02 — GPlately: moving-point lifecycle rather than repeated full raster histories

**Observed method.** Seafloor ages are tracked on points created at ridges and reconstructed through time; gridding is a separate stage. Initial age guesses and surviving seed artefacts are explicitly documented. [SC-S04][url-019]

**Proposed Atlas adaptation — E/S.** Keep compact arrays of identity, birth time, location and host domain. Introduce points from declared spreading events; retire subducted points into a transfer ledger. Rasterise only requested outputs. Batch points by valid plate/time interval, and amortise topology queries rather than reconstructing independently for every property field.

**Cost hypothesis.** Work follows the number of active points and boundary queries instead of storing a dense raster at every historical time. This is not automatically smaller: oversampling ridges or never retiring material can make the point set expensive. Spatial queries, redistribution and final gridding remain part of the cost.

**Proposed test.** Use a small analytic spreading history, then changing ridge speed and a subduction boundary. Compare age/mass inventories before and after rasterisation; measure point growth and interpolation error. Unknown birth ages must not be replaced with a nearest-ridge estimate unless that approximation is selected and labelled. This approach changes representation and therefore cannot silently reuse existing Atlas checkpoint identities.

<a id="O03"></a>

### O03 — Geodynamic World Builder: evaluate compact feature descriptions lazily

**Observed method.** GWB returns physical properties at requested positions from a structured description of geological features; it does not require the feature description itself to be a dense output raster. [SC-S06][url-020] [SC-S07][url-021]

**Proposed Atlas adaptation — E/S; query pruning is a proposal, not a claimed GWB benchmark.** Separate a versioned geological description from its sampler. Batch point requests, identify candidate features with bounding volumes, and cache reusable geometric primitives. Keep feature precedence deterministic. Compute temperature/composition at solver quadrature or sample points rather than materialising every possible resolution in advance.

**Cost hypothesis.** A naive query tests every feature at every point. Pruning may reduce the candidate count, but complex overlaps can defeat it; building an index is worthwhile only after enough queries. A final dense export still incurs its own full output cost.

**Proposed test.** Compare against an exhaustive sampler on overlapping and boundary-touching features, poles/seams where relevant, and points exactly on interfaces. Verify that changing sample density does not move the authored feature. Record candidate counts, index build cost, sampling cost and memory. Never let a missed bounding-box candidate become an apparently valid default material.

<a id="O04"></a>

### O04 — LaMEM: structured field layout and solver-aware data organisation

**Observed method.** LaMEM uses staggered finite differences, marker-in-cell material representation and PETSc solvers. [SC-S08][url-022] [SC-S09][url-023]

**Proposed Atlas adaptation — E/N/S.** For a selected continuum experiment, store field values in contiguous arrays and keep material identity/history separate from pressure/velocity unknowns. Stagger velocities and pressure only when that discretisation is justified; rearranging dictionaries into arrays is an execution change, while changing the discretisation is not. Reuse fixed sparsity patterns and geometry, not stale coefficients.

**Cost hypothesis.** Contiguous storage reduces per-object overhead and supports compiled/vectorised kernels. It does not cure an ill-conditioned nonlinear solve. Parallel throughput also depends on halo traffic, marker migration and load balance, not just core count.

**Proposed test.** First test array versus reference updates for a tiny fixed state with the same law. For a new staggered solver, separately test incompressibility, pressure modes, boundary conditions and viscosity contrasts. Account for field arrays, marker arrays, preconditioners and temporary buffers in total peak memory. Do not silently replace Atlas’s fixed-quantum material ledger with floating-point arrays: retain an explicit accounting contract or introduce a separately reviewed numerical successor.

<a id="O05"></a>

### O05 — ASPECT: adaptive resolution and matrix-free geometric multigrid

**Observed method.** ASPECT’s solver research compares algebraic and matrix-free geometric multigrid on adaptive meshes with variable viscosity. Material averaging and constitutive conventions affect the represented problem. [SC-S10][url-024] [SC-S11][url-025] [SC-S12][url-026]

**Proposed Atlas adaptation — N/S.** Only after choosing a continuum formulation, refine around measured numerical error or unresolved physical gradients. Use a mesh hierarchy to remove errors at different wavelengths; consider matrix-free action for expensive high-order operators. Preserve a coarse solve and an effective preconditioner. “No matrix” does not mean “no solver infrastructure”.

**Cost hypothesis.** Fewer active degrees of freedom can reduce work versus uniformly fine resolution. Ideal multigrid scaling assumes effective smoothing, transfer operators and coarse correction; coefficient jumps, adaptive interfaces and nonlinearities can destroy that assumption. No unconditional O(N) runtime is claimed.

**Proposed test.** Compare uniform refinement against adaptive refinement at matched error in displacement, stress and budget—not equal cell count. Report setup plus solve time, iteration counts, true residuals, total memory and mesh-transfer error. Include a high-viscosity-contrast case. Refinement thresholds, viscosity averaging and regularisation must remain recipe-visible, because improving iteration counts by smoothing away a physical discontinuity is a model change.

<a id="O06"></a>

### O06 — Underworld: batch mutations, invalidate projections, compile equations once

**Observed methods.** UW3 tracks particle changes and lazily rebuilds mesh projections, batches synchronisation after grouped updates, and separates runtime constants from compiled symbolic expressions. [SC-S14][url-027] [SC-S15][url-028]

**Proposed Atlas adaptation — E first, N/S later.** Introduce narrow transaction-like update boundaries around arrays or derived geometry so all dependent products become stale once. Rebuild each required projection at most once per state. A future compiled kernel should bind the expression and compiler separately from runtime parameter values; changing a value must still change scientific invocation identity even when recompilation is unnecessary.

**Cost hypothesis.** Useful when many writes trigger the same expensive projection or code generation. Batching offers little benefit when each write genuinely changes a separately consumed state. Symbolic/JIT startup can dominate tiny workloads, and expression growth can make compilation expensive.

**Proposed test.** Instrument invalidation/projection/compile counts and verify results after every supported mutation path. Test a changed parameter without changed expression, and a changed expression with identical parameters. Detect hidden in-place writes. A weighted particle projection must pass its own conservation requirements; caching it does not make it conservative. Building an entire symbolic geodynamics framework is not the recommendation for this step.

<a id="O07"></a>

### O07 — pTatin3D: precondition the coupled system, not just its expensive block

**Observed method.** The cited Stokes method combines matrix-free operators, geometric multigrid, hybrid coarse operators and suitable iterative methods. Its material-point representation is distinct from its mixed finite-element unknowns. [SC-S16][url-029]

**Proposed Atlas adaptation — N/S.** If a pressure–velocity solver becomes necessary, use the block structure. For the system in the historical modelling study, the pressure Schur complement involves $BA^{-1}B^T$. Approximate its action with a justified pressure preconditioner while solving the viscous block effectively. Explicitly handle null spaces and scaling.

**Cost hypothesis.** Reducing iterations may dominate lower-level kernel improvements. Conversely, an expensive preconditioner can cost more to build than it saves on a small case. Matrix-free evaluation trades stored coefficients for repeated operator work; the useful choice depends on reuse and hardware bandwidth.

**Proposed test.** On one chosen formulation, compare total setup/solve cost and accuracy across refinement and coefficient contrast, including nearly incompressible behaviour. Report iteration growth and coarse-grid cost. Refuse the claim that a successful scalar multigrid test establishes the coupled solver. Because the source repository was only partly accessible, a complete implementation transfer requires additional source inspection; this report does not claim that work has been done. [SC-S17][url-030]

<a id="O08"></a>

### O08 — gFlex: exploit linearity only where the operator permits it

**Observed foundation.** gFlex’s analytical superposition relies on a linear, constant-property response; its finite-difference route addresses more general rigidity. Sharp coefficient changes require special care. [SC-S18][url-031] [SC-S20][url-032]

**Derived candidate — E/N.** For uniform $D$ and compatible periodic boundaries, Fourier transformation gives

$$\widehat w(\mathbf k)=\frac{\widehat q(\mathbf k)}{D|\mathbf k|^4+\Delta\rho g}.$$

An FFT application costs roughly O(N log N) rather than a naive O(N²) all-to-all convolution. Padding for an approximation to an infinite domain must be tested; a periodic answer is not an infinite-plate answer. The development documentation’s FFT mention is not treated as a reproduced stable implementation. [SC-S19][url-033]

**Alternative candidate — E.** When a sparse operator is unchanged, reuse its factorisation or preconditioner for new load vectors. Invalidate on rigidity, density contrast, grid, boundaries or algorithm changes—not merely load changes.

**Proposed test.** Use sinusoidal loads, load superposition, symmetry and domain enlargement. Compare spectral and independent finite-difference answers under identical conditions. Test changed elastic thickness and edge constraints. Separate load construction from solution time. Never substitute one constant-rigidity spectral operator for spatially varying stiffness just to obtain a faster run.

<a id="O09"></a>

### O09 — pyBacktrack: separate local column calculations and cache thermal relationships

**Observed foundation.** Subsidence, decompaction and optional sea-level/dynamic-topography contributions are separable parts of the documented reconstruction. Newer workflow features do not change that distinction. [SC-S21][url-034] [SC-S22][url-035] [SC-S23][url-036]

**Proposed Atlas adaptation — E/M.** For a chosen reduced model, batch independent columns and reuse lithology-specific integrals or age-depth evaluations. Cache by full material/thermal parameters and age convention, not by a rounded age alone. Keep observed, generated and reconstructed column information separately labelled.

**Cost hypothesis.** Independent column work is often parallelisable without spatial communication; gridding and shared loads are not necessarily independent. A table lookup can be cheaper than repeated nonlinear decompaction, but interpolation becomes a numerical approximation. Thermal subsidence from a reduced age law is not the same calculation as a three-dimensional evolving thermal solver.

**Proposed test.** Check solid-volume conservation under decompaction, monotonicity where the selected law requires it, zero-thickness layers and very young/old ages. Measure error over a range withheld from table construction. Keep sea-level change, basement motion and sediment displacement distinct to avoid double counting. The September 2026 1.5 paper remains a preprint; its new claims should receive a separate evidence label. [SC-S24][url-037]

<a id="O10"></a>

### O10 — FastScape: ordered implicit updates on a valid receiver graph

**Observed foundation.** The C++ documentation specifies an implicit, first-order SPL update; the Fortran and threshold formulations have additional features and conditions. [SC-S26][url-038] [SC-S27][url-039] [SC-S28][url-040]

**Derived candidate — N.** For single-receiver, detachment-limited erosion with slope exponent $n=1$, fixed nonnegative $K,A$, distance $\ell_i$ and uplift $U_i$:

$$h_i^{new}=\frac{h_i^{old}+\Delta t\,U_i+\alpha_i h_{r(i)}^{new}}{1+\alpha_i},
\qquad \alpha_i=\frac{\Delta t K_iA_i^m}{\ell_i}.$$

Given a valid acyclic receiver graph and boundary values, process receivers before donors. The graph sweep is O(N); graph construction, changing drainage and nonlinear solving are separate costs. This equation does not cover sediment feedback, multiple receivers or general $n$ unchanged.

**Proposed test.** Compare analytic steady profiles and a transient feature at successively smaller timesteps. Track accuracy as well as stability. Exercise zero runoff, outlets, pits and changing receivers. Report graph-build, sweep and nonlinear-iteration costs independently. Reusing a graph after the terrain changes is invalid unless its connectivity is re-established.

**Atlas condition.** This is potentially a different erosion law from Atlas’s material-aware route. It needs a new scientific identity and conservation/physical acceptance—not an overwrite labelled “optimisation”.

<a id="O11"></a>

### O11 — Landlab: efficient routing plus bounded TVD advection

**Observed methods.** Priority-Flood combines a priority queue with ordinary queue processing in suitable depressions; complexity depends on elevation representation and implementation. Landlab exposes depression fill/breach and flow-metric choices. Its listric example uses TVD advection for hanging-wall movement. [SC-S29][url-041] [SC-S30][url-042] [SC-S31][url-043]

**Proposed Atlas adaptation — E/N.** Learn the heap/FIFO algorithm as a way to order work, but keep its routing surface distinct from physical topography. Fuse compatible accumulation steps only when their inputs and semantics match. For material transport, use contiguous conservative fields and a limiter appropriate to the equation, rather than repeatedly copying layered Python structures.

**Cost hypothesis.** Floating-height heap flooding has an O(N log N) worst-case form; specialised integer queues can differ. Claiming all Priority-Flood is linear would be wrong. A TVD advection step still obeys its time-step restrictions and can incur numerical diffusion.

**Proposed test.** Include genuine closed lakes, flats, boundary runoff and tie cases. Confirm that a chosen breach cannot silently become an incision of the actual terrain. Advect a constant field, a smooth wave and a sharp tagged contact; measure phase error, bounds and material budgets. Any epsilon slope, fill depth or limiter belongs in the numerical recipe.

<a id="O12"></a>

### O12 — Badlands: controlled remeshing and compiled heavy kernels

**Observed method.** The methods paper describes triangular/Voronoi calculations, efficient node ordering, remeshing under deformation and a Python interface with compiled heavy functions. Current repository scope is broader than the original paper. [SC-S32][url-044] [SC-S33][url-045]

**Proposed Atlas adaptation — E/N/S.** Keep readable orchestration, but isolate deterministic numerical loops with explicit array inputs. Remesh only when measured quality or transfer error requires it, then remap conserved quantities conservatively and re-establish affected topology. Tag stratigraphic/material identity independently of node identity.

**Cost hypothesis.** Reusing geometry until necessary can avoid repeated mesh construction. Waiting too long can worsen the physical operator, while remeshing too often can accumulate transfer error. Compiling a hot loop does not eliminate I/O, topology reconstruction or history costs.

**Proposed test.** Apply a known horizontal deformation and verify total material before/after remeshing. Transport labelled sediment through erosion, transit and deposition, including outside-domain flux. Compare field errors and strata across remeshing thresholds. Profile meshes, kernels, Python marshaling and export separately. Do not adopt a fuzzy or empirical marine process as a computationally cheaper equivalent to an unrelated physical law.

<a id="O13"></a>

### O13 — goSPL: finite-volume partitioning with explicit boundary fluxes

**Observed method.** goSPL describes unstructured planar/spherical meshes, geometric face data, finite-volume operators and DMPlex redistribution. Recent coupled extensions have a separate preprint status. [SC-S34][url-046] [SC-S35][url-047] [SC-S37][url-048]

**Proposed Atlas adaptation — S/E.** Partition a validated mesh and assign a single consistent flux to each shared face. Keep ghost data and ownership explicit, and exchange boundary contributions before downstream accumulation. Partition for measured work, not merely equal cell counts; active routing, material layers and nonlinear iterations can be uneven.

**Cost hypothesis.** Distribution can reduce per-process memory and parallelise local operators. Global routing, repartitioning and reductions can dominate at scale. A model with adequate local kernels may still have poor communication scaling. There is no claim that adding MPI to the current 256-cell domain is useful.

**Proposed test.** Compare a serial closed-domain budget with multiple partitions, including a river and material pulse crossing a cut. Test partition boundaries at difficult features, not only uniform regions. Check restart with an explicitly versioned partition map. Approximate global reductions must follow a declared numerical policy; an exact hash comparison across differently ordered floating reductions is not automatically meaningful.

<a id="O14"></a>

### O14 — PyLith: specialised fault constraints and nondimensionalisation

**Observed methods.** The historical PyLith methods paper uses Lagrange multipliers for slip constraints and a specialised preconditioner. Current documentation separates formulations and requires prescribed slip. [SC-S38][url-049] [SC-S39][url-050] [SC-S40][url-051]

**Proposed Atlas adaptation — N.** When a fault-mechanics problem is selected, scale displacement, stress, length and time consistently before solving. Separate bulk and interface unknowns so a preconditioner addresses the actual coupled structure. Reuse mesh/topology components when they are truly unchanged.

**Cost hypothesis.** Better scaling and block preconditioning may reduce iterations more than kernel-level acceleration. The benefit is conditional on a compatible finite-element formulation and a problem large enough to justify setup. A full fault-interface solver is not a small patch to a raster displacement field.

**Proposed test.** Compare nondimensional and dimensional formulations after conversion; include a simple prescribed-slip analytic case and a material-contrast case. Check traction balance, constraint residual and conditioning-sensitive parameter ranges. Report setup and iterations, not only solve time. Never import a dynamic rupture capability from an older publication into a claim about the current documented release.

<a id="O15"></a>

### O15 — cutde: choose dense, blocked, matrix-free or approximate low-rank evaluation

**Observed methods.** The technical README distinguishes full matrix construction, direct matrix-free action, block evaluation and adaptive cross approximation (ACA), warning that matrix-free can be slower and ACA may not reach its requested tolerance. [SC-S41][url-052]

**Proposed Atlas adaptation — E/N.** For fixed elastic geometry, compare the number of planned right-hand sides with storage cost. A dense response matrix can amortise construction for many repeated slip vectors. Direct matrix-free evaluation stores much less but recomputes interactions; blocked exact evaluation limits working memory. Approximate far-field compression is a separate numerical method, not exact reuse.

**Derived cost comparison.** With $N_o$ observation points and $N_s$ triangles, direct all-pairs work and dense storage scale with $N_oN_s$ (times component counts). An approximation $G\approx UV^T$ of rank $r$ has storage proportional to $r(N_o+N_s)$ for an eligible block, but its validity is geometry- and tolerance-dependent.

**Proposed test.** Compare exact small matrices, matrix-free results and compressed blocks on independent slip vectors. Check near-fault behaviour separately from far-field error. Include build, host-device transfer, warmup and repeated-application costs. Pin backend, precision and geometry. The analytical foundation is elastic dislocation theory, not long-term tectonic deformation. [SC-S42][url-053]

<a id="O16"></a>

### O16 — MAGEMin: parallel point equilibrium and carefully bounded property tables

**Observed method.** MAGEMin’s point-wise equilibrium calculations combine global composition discretisation/linear programming with partitioning and local minimisation. Independent pressure–temperature–composition points are a natural parallel workload. [SC-S43][url-054] [SC-S44][url-055]

**Proposed Atlas adaptation — E/N/M.** For selected material laws, batch independent points and inspect whether a verified property table can cover the actual state range. Refine near phase changes and preserve phase identities; do not interpolate phase labels as numbers. Reuse a table only with the same thermodynamic database, composition basis and numerical policy.

**Cost hypothesis.** Precomputation can reduce repeated expensive minimisations, but table dimension grows rapidly with variable composition. Near phase boundaries, a smooth interpolant can be fast and wrong. Warm starts need safeguards against locking onto a previous metastable/local solution.

**Proposed test.** Withhold state points, test phase-boundary neighbourhoods and compare conserved components, density, melt fraction and relevant derivatives. Test multiple minimiser starts. Separate table-build cost from runtime savings and report storage. Data from Earth-compatible thermodynamic models are not automatically validated over every hypothetical composition. This method is deferred until Atlas can provide the physical state that makes the calculation meaningful.

<a id="O17"></a>

### O17 — GDTchron: batch independent histories without losing inherited information

**Observed method.** The methods paper uses vectorisation, sparse calculations and single-node parallel processing; it identifies unresolved inherited-history issues for newly created particles and deposited sediment. Some repository examples require large data not shipped with the small demonstrations. [SC-S45][url-056] [SC-S46][url-057]

**Proposed Atlas adaptation — E/N.** Extract validated time–temperature histories once, batch independent grains/histories and write results in a stable identity order. Reuse time-grid operators only under matching diffusion parameters, time steps and boundary assumptions. Keep missing history explicit. Do not replace a sediment grain’s source history with its new host’s history for convenience.

**Cost hypothesis.** Batching reduces scheduler/startup overhead and sparse one-dimensional diffusion operators reduce storage. Repeated identical diffusion matrices may permit reuse, but temperature-dependent diffusivity changes coefficients. A tiny batch may run faster serially.

**Proposed test.** Check simple isothermal/cooling paths, particle identity through restart, mixed grain sizes and withheld histories. Compare serial/batched results under the numerical policy. Record extraction, interpolation, calculation and I/O separately. Apparent cooling ages should carry uncertainty in kinetics and grain properties, not be treated as an exact unique reconstruction of a tectonic history.


### Scientific evidence qualifications

Underworld2 and Underworld3 are different implementations; FastScape Python, Fortran and C++ variants do not share an interchangeable capability inventory. The gFlex FFT discussion in the pre-study is a derived candidate, not verification of a stable gFlex FFT feature; Atlas’s separate foundation does implement its stated *discrete* periodic FFT-diagonalised operator. The pTatin3D repository listing was incomplete, so its transfer assessment rests mainly on the identified methods paper. PyLith’s reviewed current prescribed-slip scope must not acquire spontaneous-rupture capability from an older paper. The pyBacktrack and goSPL 2026 extensions were under-review preprints in the original study. GDTchron is a limited diagnostic, not a general tectonic model. No new release or runtime compatibility claim is made by consolidation.

### Scientific source records

**[SC-S02][url-018] — pyGPlates: TopologicalModel.** Official API documentation; original review 2026-09-15. Time-snapshot cache, anchor frame and least-recently-used eviction.

**[SC-S04][url-019] — GPlately: SeafloorGrid.** Official methods/API documentation; original review 2026-09-15. Documentation labelled 2.0.0; initial-age heuristic and surviving-seed artefacts explicitly described.

**[SC-S06][url-020] — Fraters et al. (2019): The Geodynamic World Builder.** Peer-reviewed methods paper; original review 2026-09-15. Initial conditions, not time evolution; Cartesian and spherical geometry.

**[SC-S07][url-021] — Geodynamic World Builder official repository.** Official repository; original review 2026-09-15. Structured feature inputs and point-query architecture.

**[SC-S08][url-022] — LaMEM official repository.** Official repository; original review 2026-09-15. Marker-in-cell, staggered finite differences, PETSc and rheology; no runtime reproduced.

**[SC-S09][url-023] — LaMEM: Quick start.** Official development documentation; original review 2026-09-15. Documentation generated August 2026; development page, not a pinned tested build.

**[SC-S10][url-024] — ASPECT: Basic equations.** Official scientific documentation; original review 2026-09-15. Stable documentation labelled 3.0.0; equation families and approximations.

**[SC-S11][url-025] — ASPECT: Material model.** Official scientific documentation; original review 2026-09-15. Creep, yielding and explicit warning about rheological parameter conventions.

**[SC-S12][url-026] — Clevenger and Heister (2019): Algebraic versus matrix-free geometric multigrid for variable-viscosity Stokes.** Author research preprint; original review 2026-09-15. Primary author account; abstract/metadata reviewed, not all performance tables.

**[SC-S14][url-027] — Moresi (2026): Particles in Underworld3.** Developer technical note; original review 2026-09-15. Dated 3 June 2026; projection, lazy invalidation and batching.

**[SC-S15][url-028] — Moresi et al. (2026): How Underworld3 turns SymPy into C.** Developer technical note; original review 2026-09-15. Dated 1 April 2026; generated Jacobians and runtime constants.

**[SC-S16][url-029] — May, Brown and Le Pourhiet (2015): Matrix-free multigrid for heterogeneous Stokes flow.** Institutional record of peer-reviewed methods paper; original review 2026-09-15. Q2–P1-discontinuous/material-point method and hybrid multigrid; full paper/code not audited.

**[SC-S17][url-030] — pTatin3D official source location.** Official repository landing page; original review 2026-09-15. Landing page resolves; directory rendering was incomplete. No claim of a complete source audit or current build verification.

**[SC-S18][url-031] — Wickert (2016): Open-source modular solutions for flexural isostasy, gFlex v1.0.** Peer-reviewed methods paper; original review 2026-09-15. Analytical and finite-difference methods; boundaries and variable rigidity.

**[SC-S19][url-033] — gFlex: Theory and numerics.** Official development documentation; original review 2026-09-15. Indexed page labelled 2.0.0b2 includes FFT; direct page retrieval failed. FFT is treated here as a derived candidate, not a verified stable build capability.

**[SC-S20][url-032] — Hindle and Besson (2023): Corrected flexure finite differences with abrupt coefficient changes.** Peer-reviewed methods paper; original review 2026-09-15. Independent warning about discretising variable rigidity and interfaces.

**[SC-S21][url-034] — pyBacktrack official repository.** Official repository; original review 2026-09-15. Backtracking versus forward generation; explicit Earth input dependencies.

**[SC-S22][url-035] — Müller et al. (2018): PyBacktrack 1.0.** Peer-reviewed methods paper; original review 2026-09-15. Decompaction, subsidence, sea level and dynamic topography.

**[SC-S23][url-036] — EarthByte (8 May 2026): PyBacktrack 1.5 release.** Official release announcement; original review 2026-09-15. Release claims, not a reproduced installation.

**[SC-S24][url-037] — Müller et al. (2026): PyBacktrack 1.5.** Research preprint under discussion; original review 2026-09-15. Posted 4 September 2026; not treated as completed peer review.

**[SC-S26][url-038] — FastScapeLib-Fortran documentation.** Official scientific documentation; original review 2026-09-15. SPL/transport/diffusion equation; O(N) claim is formulation-specific.

**[SC-S27][url-039] — Fastscapelib C++: Eroders.** Official API/scientific documentation; original review 2026-09-15. First-order implicit SPL and nonlinear Newton treatment; not all Fortran features inferred.

**[SC-S28][url-040] — Braun (2023): Implicit algorithm for threshold stream-power incision.** Peer-reviewed methods paper; original review 2026-09-15. Accuracy and nonlinear convergence caveats; thresholds change the problem.

**[SC-S29][url-041] — Landlab: ListricKinematicExtender tutorial.** Official scientific tutorial; original review 2026-09-15. Revised June 2023; prescribed geometry, TVD advection and separate flexure.

**[SC-S30][url-042] — Landlab: PriorityFloodFlowRouter tutorial.** Official tutorial; original review 2026-09-15. Fill/breach, routing metric and epsilon choices are semantic settings.

**[SC-S31][url-043] — Barnes, Lehman and Mulla: Priority-Flood.** Author research manuscript; original review 2026-09-15. Heap/FIFO algorithm and conditional integer/floating complexity.

**[SC-S32][url-044] — Salles, Ding and Brocard (2018): pyBadlands.** Peer-reviewed methods paper; original review 2026-09-15. TIN/Voronoi finite volume; deformation/remeshing; empirical process laws.

**[SC-S33][url-045] — Badlands official repository.** Official repository; original review 2026-09-15. Current scope and mixed licence files; do not infer every historical implementation detail remains unchanged.

**[SC-S34][url-046] — goSPL: UnstMesh, v2026.6.30.** Versioned official API documentation; original review 2026-09-15. Planar/spherical finite-volume mesh, DMPlex and geometry data.

**[SC-S35][url-047] — goSPL stable manual.** Official documentation; original review 2026-09-15. Landing page labelled v2026.7.14 at retrieval.

**[SC-S37][url-048] — Salles (2026): Coupled hydrology, weathering and surface processes in goSPL.** Research preprint under discussion; original review 2026-09-15. Posted 22 July 2026; extensions are not treated as independently validated Atlas capabilities.

**[SC-S38][url-049] — PyLith: Current overview.** Official documentation; original review 2026-09-15. Current overview describes prescribed fault slip; the fetched latest page labels itself 5.0.0dev. Do not infer current spontaneous rupture from the older paper.

**[SC-S39][url-050] — PyLith: Governing elasticity equations.** Official scientific documentation; original review 2026-09-15. Static/quasistatic/dynamic formulations and rheologies.

**[SC-S40][url-051] — Aagaard, Knepley and Williams (2013): Fault slip by domain decomposition.** Author research manuscript; original review 2026-09-15. Historical fault-interface/preconditioner formulation; not a claim of current spontaneous rupture support.

**[SC-S41][url-052] — cutde official repository and technical README.** Official repository; original review 2026-09-15. Dense, matrix-free, block and ACA routes; memory/speed trade-offs and maintenance statement.

**[SC-S42][url-053] — Nikkhoo and Walter (2015): Triangular dislocation, an analytical artefact-free solution.** Peer-reviewed methods paper; original review 2026-09-15. Homogeneous elastic full-space/half-space; artefact-free does not remove physical discontinuities.

**[SC-S43][url-054] — Riel et al. (2022): MAGEMin.** Peer-reviewed methods paper; original review 2026-09-15. Linear programming, partitioning Gibbs energy and local minimisation; database dependence.

**[SC-S44][url-055] — MAGEMin official repository.** Official repository; original review 2026-09-15. Parallel equilibrium engine and source entry point.

**[SC-S45][url-056] — Vasey et al. (2026): GDTchron.** Peer-reviewed methods paper; original review 2026-09-15. Published 1 April 2026; simple He kinetics, spherical grains, inherited-history and single-node limitations.

**[SC-S46][url-057] — GDTchron official repository.** Official repository; original review 2026-09-15. 0.1.2 release shown; distinguishes runnable examples from large-data-dependent demonstrations.

<a id="engineering-methods"></a>

## 5. Engineering methods and their accuracy boundaries

These 39 retained methods are an engineering reference, not a prerequisite list
or a claim that every method is implemented. The current delivery sections,
source and named evidence govern adoption. Each card preserves its Atlas use,
ownership/accuracy boundary and verification requirements. The source-project
catalogue has been removed; its history remains in Git, not another active plan.

Caching avoids repeated work; lazy preparation avoids work not yet requested.
Both require measured setup/first-use/reuse cost and complete dependencies.
"Design now" means preserve the necessary contract, not build speculative systems.
The general baseline programme remains explicitly skipped; only finite comparisons
needed for an authorised increment are permitted.

**Delivered where relevant:** bulk native operations, immutable definitions and
compact categoricals, bounded work admission, conservative feature indexing,
independent-batch scheduling, verified reuse, lossless chunk storage and exact
restoration. Consult the current R2 and earlier delivery sections for exact scope.
**Conditional:** volumetric hierarchy, new operator reuse and parcel aggregation
require their own numerical/workload evidence. **Deferred:** viewer, network and
hardware-specific rendering work is not a tectonic-solver prerequisite.


<a id="method-01"></a>

### Measure the whole operation before changing it

**Atlas application.** Instrument source verification, preparation, kernel work, communication, rejected trials, output and retained memory separately. Give batch work stable operation IDs so sampled hot paths can be tied to their scientific purpose.

**Boundary.** Use instrumentation suitable for the actual Python/native runtime. Instrumentation itself has a cost; sampling frequency and debug checks must be recorded.

**Check.** Compare instrumented and uninstrumented bounded runs; distinguish total CPU work from wall time and queue waiting. Locate a repeatable bottleneck before adding another cache or worker pool.


<a id="method-02"></a>

### Persist expensive prepared artefacts

**Atlas application.** Persist verified derived geometry, feature indices or reusable operator data when restoration is cheaper than reconstruction. Bind input content, algorithm, schema, numerical settings and relevant runtime identity. Handle uncacheable items by recomputing them, not omitting them.

**Boundary.** Treat cached records as bounded data, not executable object graphs. Corruption may trigger reconstruction only for genuinely derived products with available authenticated inputs. An authority or historical checkpoint is not a disposable cache.

**Check.** Measure build, write, validation and restore separately. Test source/parameter changes, malformed or oversized records, interrupted writes and exact agreement with the uncached path.


<a id="method-03"></a>

### Create visual models only when first needed

**Atlas application.** In a future Atlas viewer, hold a small renderer factory per feature type and construct meshes/material pipelines on demand. Prewarm likely first views only when latency evidence justifies it.

**Boundary.** This is lazy initialisation, not culling, simulation suspension or dynamic geological loading. A hidden consumer that requests every model defeats the saving. Concurrent first-use calls need single-owner construction and explicit failure handling.

**Check.** Count models built at launch, first view and repeated view; measure first-use latency and retained RAM/VRAM. Exercise concurrent requests, resource reload and a renderer whose construction fails.


<a id="method-04"></a>

### Load optional visual resources on demand

**Atlas application.** Keep the asset catalogue separate from materialised visual models and optional derived datasets. Resolve only requested assets, retain dependencies while in use, and evict rebuildable products under a finite budget.

**Boundary.** Lazy scientific data are eligible only when the active solver still receives every required value and boundary input. Viewer asset absence must not become missing physics. Resource generations and references need consistent invalidation.

**Check.** Compare peak/resident memory, first-use stalls and revisits. Reload an asset while referenced, request it concurrently and reject missing required dependencies rather than silently substituting a valid-looking result.


<a id="method-05"></a>

### Defer optional subsystem preparation

**Atlas application.** Load optional exporters, viewer preparation and specialist diagnostics only when their operation is selected. Keep a small capability description available without importing all expensive implementations.

**Boundary.** Defer preparation, never a required conversion or validation. First use may become slower and failures occur later; make that explicit. Avoid a complex general plug-in framework merely to postpone one import.

**Additional application.** Keep optional online checks explicitly opt-in. Missing required dependencies must produce a diagnostic; never silently remove inputs or alter the requested capability to make loading succeed.

**Check.** Compare cold launch, first invocation and subsequent calls. Confirm skipped capabilities are truly unused and that each capability fails clearly when its dependency is absent.


<a id="method-06"></a>

### Reuse stable registry and resource-discovery results

**Atlas application.** Create a deterministic index of the exact material/law/feature inventory needed by a case. Reuse parsing and lookup structures within an authenticated invocation; consider a persisted index only with complete membership and content identities.

**Boundary.** Directory discovery, decoded metadata and scientific authority are distinct. File timestamps or a directory name alone do not authenticate unchanged inputs. A registry cache must not hide a newly added or removed dependency.

**Check.** Compare indexed and exhaustive resolution. Test added/removed files, reordered declarations, changed content and duplicate identifiers; include validation and index-build cost.


<a id="method-07"></a>

### Share equivalent immutable definitions

**Atlas application.** Intern material-law descriptions, immutable composition classes and repeated geometric metadata. Keep per-cell temperature, stress and history separate. Use canonical content identity rather than object addresses to establish persistent equivalence.

**Boundary.** Shared mutable data let one edit corrupt many cells. Interning itself consumes lookup memory and CPU. Equal rock labels do not mean equal physical state or identical historical evidence.

**Check.** Measure allocation count, unique definitions and total retained bytes. Test mutation refusal, parameter changes and reference release; retain the method only when sharing exceeds its indexing cost.


<a id="method-08"></a>

### Replace repeated categorical objects with compact indices

**Atlas application.** Use chunk-local material palettes and compact integer indices for categorical fields. Decode batches into solver-friendly arrays where necessary. Reserve explicit encodings for unknown, absent and real empty material.

**Boundary.** Bit-packing material IDs is not a licence to quantise temperature, stress or conserved mass. Many unique states can make palettes costly; switching representations needs a versioned lossless conversion.

**Check.** Round-trip single-material, mixed, high-cardinality and unknown-containing chunks. Include decoding and updates in the cost comparison, not disk bytes alone; check canonical identity across palette reorderings.


<a id="method-09"></a>

### Store volume in bounded chunks and compact uniform regions

**Atlas application.** Combine compact geological layers/features with detailed volumetric chunks where required. Load selected fields and ranges, using exactly uniform regions without allocating every voxel. Keep the numerical mesh and storage hierarchy independent.

**Boundary.** A storage chunk is not a physical boundary. Unknown and uniform background are different. Fine continuous gradients may defeat uniform compression; approximation needs separate error approval.

**Check.** Compare layer, dense-chunk and sparse encodings for uniform, faulted and continuously varying test fields. Verify material budgets, coordinates, boundary samples, decoded identity and peak active working set.


<a id="method-10"></a>

### Build fresh fields through one controlled batch path

**Atlas application.** Allocate a candidate field once, evaluate geological features in batches, assemble metadata once and validate the complete candidate before making it visible. Separate construction of new state from arbitrary editing of accepted state.

**Boundary.** Construction shortcuts are valid only under proven preconditions. They must not omit accounting, source checks or events that other components depend on. Related optimisations do not imply independent multiplicative speed-ups.

**Check.** Compare batch construction against a transparent per-item reference, including mixed materials and failed sampling. Interrupt construction and verify no partial accepted field escapes.


<a id="method-11"></a>

### Prune spatial candidates before exact geometry work

**Atlas application.** Index fault traces, slab bodies and geological features; query conservative bounds before exact intersection or property evaluation. Batch nearby samples and reuse a valid index until geometry changes.

**Boundary.** Broad-phase pruning must have no false negatives. A missed candidate cannot become an apparently valid default material. A planar box strategy requires adaptation for spherical seams and moving/deforming features.

**Additional application.** Order pure rejection predicates by cost; a cheap rejection must be proven conservative. Range, corner and interval queries can share the same content-identified search structures.

**Check.** Compare with exhaustive geometry checks on touching boundaries, narrow intersections, degeneracy and coordinate seams. Measure candidates per query, rebuild time, exact-check time and index memory.


<a id="method-12"></a>

### Use inverted indices for repeated applicability searches

**Atlas application.** Build material-to-law, feature-to-region and changed-parameter-to-dependent-product indices. Apply the full validity rule to the reduced candidate set; preserve a deterministic precedence for overlapping rules.

**Boundary.** An index identifies candidates, not scientific suitability. Unknown/custom rule types require an exhaustive fallback. If build cost dominates a small workload, scanning may be better.

**Check.** Compare selections and ordering with exhaustive evaluation, including overlapping and unmatched inputs. Measure index build plus all lookups and test content/membership changes.


<a id="method-13"></a>

### Reuse valid matches and coalesce intermediate updates

**Atlas application.** Reuse the last applicable material/constitutive selection while its full input signature remains valid. Group related parameter edits before recomputing derived tables or geometry that no consumer needs in intermediate form.

**Boundary.** Never omit an intermediate physical state that another coupled process consumes. Matching only a material name is insufficient when pressure, temperature or history changes validity.

**Check.** Test repeated identical input, rapid rule changes and a match becoming invalid mid-batch. Compare final results and every required notification with the uncoalesced reference.


<a id="method-14"></a>

### Invalidate derived data through explicit change events

**Atlas application.** Assign each accepted state a revision and mark affected derived geometry/projections stale once per coherent change. Rebuild only when requested. Propagate parameter and topology changes through known dependency relationships.

**Boundary.** The event system must cover in-place writes, boundary edits and shared-array mutations. Continuously evolving physics cannot sleep merely because no user edited it. Counter overflow and object reuse need defined behaviour.

**Additional application.** Compact dispatch/subscription structures are worth considering only after profiling. Propagate invalidation only when dependent output changes, while retaining every required consumer notification.

**Check.** Mutate each permitted input independently and ensure exactly the necessary derived data are invalidated. Test repeated batched edits, no-op changes and a consumer requesting state during an unfinished update.


<a id="method-15"></a>

### Evaluate affected networks without duplicate notifications

**Atlas application.** For a defined dependency or routing operator, gather affected nodes, avoid duplicate work and publish a coherent result after the required propagation. Reuse ordered queues only when graph, event and numerical semantics match.

**Boundary.** A generic graph propagation rule is not thermal diffusion, stress equilibrium or transient water physics. A changed notification/order rule may change numerical outcomes; it needs an explicit equivalence policy.

**Check.** Exercise cycles, ties, simultaneous sources, boundary changes and serial versus parallel ordering. Check physical or graph invariants, recomputation count and total convergence work.


<a id="method-16"></a>

### Schedule generation and I/O with explicit dependencies

**Atlas application.** Use finite queues and persistent workers for dependency-ready tasks. Distinguish I/O preparation, immutable numerical inputs, candidate calculation and commit. Prioritise work needed to finish an accepted regional result, not unlimited speculative loading.

**Boundary.** Parallel chunk generation does not establish independent tectonic chunks. Include nested native-library threads in the core budget. Same-seed generation is not sufficient evidence of schedule-independent science.

**Check.** Compare one and several workers under shuffled completion order; stress cancellation, queue pressure, missing dependencies and worker failure. Measure setup, waiting, work and peak combined memory.


<a id="method-17"></a>

### Give state one owner and control ownership transitions

**Atlas application.** Give a worker exclusive ownership of its candidate writes; share immutable inputs. Reconcile boundary fluxes and particle migration through explicit transfers, then publish one accepted revision. Perform repartitioning at defined safe boundaries.

**Boundary.** Ownership is a correctness rule, not evidence of physical independence. Neighbour regions may need iterative/global coordination. Deadlocks can arise if dependency and lock order are implicit.

**Check.** Test overlapping requests, migration during repartition, competing commits, abandoned workers and deterministic restart. Verify one owner per conserved transfer and no lost/double material.


<a id="method-18"></a>

### Parallelise genuinely independent scenarios or frozen-input batches

**Atlas application.** Parallelise independent world scenarios, parameter-study members or particle queries against a frozen field. Batch enough work to justify scheduling and collect outputs by stable identity rather than completion order.

**Boundary.** Interacting plates are not independent scenarios. Particle deposition into shared cells requires safe reduction. Per-item Python tasks may cost more than their calculation; exceptions must not leave a partly committed state.

**Check.** Compare serial/batched results, random-stream identity, allocations and throughput across batch sizes. Test an exception within one batch and confirm other results cannot falsely complete its scenario.


<a id="method-19"></a>

### Budget worker pools, native threads and task granularity

**Atlas application.** Select an outer-worker budget jointly with BLAS/FFT/OpenMP thread counts, reserve memory per admitted task and reuse workers. Choose task size from measured overhead versus work rather than one task per voxel.

**Boundary.** Higher priority or more threads cannot create hardware capacity. Busy waiting, nested pools and too-small batches can undermine responsiveness and efficiency. A fixed limit for one machine is not a universal setting.

**Check.** Sweep bounded worker/thread/batch combinations on the same workload and error target. Record wall time, CPU time, memory, queue delays and cancellation latency.


<a id="method-20"></a>

### Release temporary objects when their final consumer finishes

**Atlas application.** Track when temporary decoded geometry, candidates, futures and output buffers have no remaining consumers; release them then. Make lifetime ownership explicit around task failure and branch completion.

**Boundary.** Do not free live boundary data, a shared accepted state or a history object that another control still references. Garbage collection cannot recover objects deliberately kept in global dictionaries.

**Check.** Repeat many small load/compute/release cycles, including failures. Check retained objects and process memory after steady state; confirm shared references remain valid until their true final release.


<a id="method-21"></a>

### Keep caches only when their measured value exceeds their cost

**Atlas application.** Budget each cache by retained bytes and reuse value, not entry count alone. Separate small reusable metadata from large derived fields. Consider recomputing cheap values, eviction, and bounded warm sets.

**Boundary.** Eviction can create repeated rebuilds and latency spikes. It must never delete required history/authority data. A hash or deserialisation pass may cost more than the computation it protects.

**Check.** Measure hits, misses, bytes, rebuild time and first-use latency under realistic revisit patterns. Compare no-cache, bounded-cache and prewarmed configurations with the same result requirements.


<a id="method-22"></a>

### Smooth writes while keeping accepted checkpoints coherent

**Atlas application.** Write immutable output chunks through a bounded I/O queue. Publish a manifest naming one coherent state only after every required chunk is durable and verified. Report saving separately from completed recovery readiness.

**Boundary.** Asynchronous completion order must not mix physical times. A responsive interface is not proof of a durable checkpoint. Backpressure must limit memory while storage is slow or full.

**Check.** Interrupt each write/publication boundary, exhaust disk space and inject a failed chunk. Recovery must find the old complete state or the new complete state, not a convincing partial mixture.


<a id="method-23"></a>

### Prepare only explicitly selected regions, with resumable tasks

**Atlas application.** Prepare a declared geological region or output request in finite batches, preserving dependencies and resumable progress. Cache only useful intermediate results; keep speculative work behind required calculations.

**Boundary.** Pregeneration shifts when work happens; it does not automatically reduce total cost. Requested regions still need relevant external boundary information. Cancellation must not be reported as successful full coverage.

**Check.** Pause, resume and cancel at several stages. Compare results with uninterrupted execution, track unnecessary work and verify progress counts complete verified units rather than merely scheduled tasks.


<a id="method-24"></a>

### Batch drawing and minimise repeated graphics submission

**Atlas application.** Group compatible chunk meshes, diagnostic lines and overlays into batches; retain prepared buffers across frames. Keep updates granular so a small geological change need not regenerate the whole displayed world.

**Boundary.** Viewer throughput does not accelerate the tectonic solver. Batching by material can still require correct transparency, ordering and picking. Related renderer versions are not interchangeable designs.

**Check.** Measure draw/submission counts, CPU/GPU frame time, upload bytes and visible latency on fixed views. Verify clipping, transparency and selection after local updates.


<a id="method-25"></a>

### Prepare static visual geometry once per valid revision

**Atlas application.** Cache geological cross-section meshes, unchanged fault surfaces and repeated symbols by scientific/display revision. Isolate animated time interpolation and genuinely moving geometry from static components.

**Boundary.** Prepared geometry is a derived viewer product, not the scientific state. A changed clipping plane, selected time, material appearance or input geometry may invalidate it even if the camera is unchanged.

**Check.** Compare static and dynamic reference drawings; change time, clipping and geometry independently. Count rebuilds and verify that inactive visual references release their memory.


<a id="method-26"></a>

### Cull invisible drawing, not invisible physics

**Atlas application.** Use conservative view/occlusion tests for opaque rock interiors and off-screen overlays. Keep volumetric scientific data intact and allow cutaways to reveal it without regeneration of the physical model.

**Boundary.** Visibility is not physical influence. Never drop a mechanical, thermal or water contribution because its chunk is hidden. Transparency, cross-sections and delayed asynchronous visibility answers complicate correct culling.

**Check.** Compare against an unculled reference view while moving cameras and cut planes; test transparent materials, sudden reveals and picking. Measure culled draws without changing scientific outputs.


<a id="method-27"></a>

### Maintain coarse context and fine detail in the viewer

**Atlas application.** Derive several display levels from one identified state; request finer visual geometry where needed and retain coarse context elsewhere. Keep seams, surface position and important topology explicit across levels.

**Boundary.** Visual LOD is not solver refinement or finer evidence. Coarse meshes may hide narrow rivers/faults; selection must recover the underlying object rather than invent a new identity.

**Check.** Test seams, silhouette/topology loss, cutaways, rapid movement and revision changes. Report storage, build cost and display error separately from scientific resolution.


<a id="method-28"></a>

### Separate viewer-region caches from active compute data

**Atlas application.** Serve immutable identified region products on request, with bounded queues, cancellation and revision notifications. The viewer may retain data no longer in the solver working set, provided its displayed revision is clear.

**Boundary.** A cached view is not a current scientific authority. Stale geometry and fields must not be combined silently. Network work is irrelevant to a purely local numerical kernel unless measurement shows otherwise.

**Check.** Test reordered/duplicate responses, missed invalidations, reconnects, slow consumers and partial datasets. Verify revision coherence and byte budgets before measuring throughput.


<a id="method-29"></a>

### Use hardware-specific render paths only behind a portable contract

**Atlas application.** Keep a portable viewer baseline and isolate eligible hardware-specific drawing kernels behind the same visual-data interface. Profile submission, transfer and device memory before committing to a specialist path.

**Boundary.** Device support, precision, driver behaviour and memory capacity become dependencies. No result here justifies translating a renderer speed claim into a mantle or terrain-solver estimate.

**Check.** Compare images, picking and clipping against the portable path across supported devices. Include initial compilation, uploads, transitions and unsupported-device fallback.


<a id="method-30"></a>

### Refresh the interface according to change, not simulation ticks

**Atlas application.** Render charts, overlays and panels when their inputs change or a display deadline requires it. Allow an idle/minimised viewer to reduce graphics load while authorised compute continues according to its separate policy.

**Boundary.** Display refresh, physical timestep and wall-clock task scheduling are different clocks. Throttling an interface must not silently pause a promised run or hide stale progress.

**Check.** Test minimisation, wakeup, updates during long calculations and cancellation. Measure graphics/CPU load and responsiveness without altering accepted numerical steps.


<a id="method-31"></a>

### Aggregate only material parcels that remain scientifically equivalent

**Atlas application.** Investigate grouping parcels with compatible properties into weighted records, preserving extensive totals and the histories required by later diagnostics. Split them again only through an explicitly defined reconstruction or retained distribution.

**Boundary.** Equal rock names do not imply equal ages, temperatures or strain histories. A mean can erase a distribution needed for cooling ages or reactions. Lossy aggregation is a numerical/model change, not exact deduplication.

**Check.** Check mass/composition budgets, distribution-sensitive diagnostics and reversible regrouping where claimed. Compare with unaggregated withheld histories before accepting a bounded approximation.


<a id="method-32"></a>

### Adapt service quality without silently changing the science

**Atlas application.** Under load, lower preview refresh, defer optional exports or limit concurrent scenarios. Any change to physical resolution, timestep policy or active processes must be explicit, identified and checked against the numerical/physical contract.

**Boundary.** Off-screen is not inactive geology. Skipping a physical update to meet a deadline changes the calculation. Adaptive policy cannot retrospectively redefine a failed accuracy or resource threshold.

**Check.** Inject slow storage and heavy queues; verify priorities and cancellation. Confirm scientific settings remain unchanged unless an explicit new scenario/policy is selected and recorded.


<a id="method-33"></a>

### Move selected bulk calculations behind a native interface

**Atlas application.** Keep readable orchestration and independently checked mathematical references. Pass whole arrays to an eligible native CPU or device operation. Evaluate one maintained compilation route, not an entire application rewrite.

**Boundary.** A native implementation does not imply a fixed Atlas speed multiplier. GPU FP64 support, transfers, numerical libraries, failure handling and binary identity matter. Rendering performance is not evidence for mechanical-kernel speed.

**Check.** Compare complete cold/warm cost, output/error and conservation with the current kernel; cover dtype/stride/alias errors, extremes, cancellation and reproducible packaging.


<a id="method-34"></a>

### Cache parsing and indexing separately from evaluated results

**Atlas application.** Identify the source manifest, parser/schema, symbol table and archive membership when preparing a reusable representation. Give evaluated scientific results their own state/parameter identity. Publish an asynchronous index only once complete.

**Boundary.** Same text or file path does not mean same semantics. Cached external metadata allowed to be stale is not an authority for scientific inputs. Archive indexing must retain decoder bounds.

**Check.** Change symbols, parser, parameters and archive membership independently; cancel a scan then complete an older task; no stale generation can replace the newer index.


<a id="method-35"></a>

### Separate lookup hashing from cryptographic provenance

**Atlas application.** Choose explicit compact spatial keys and a suitable index, measuring build, update and query costs. Retain full-key equality on collisions. Hash-table iteration must not become a scientific tie-break rule.

**Boundary.** A quick table hash is not a content identity, signature or replacement for source SHA verification. Spatial candidate pruning must remain conservative before exact geometry checks.

**Check.** Adversarial/colliding keys, reordered insertions, negative coordinates, boundary queries and exhaustive-search equivalence; confirm provenance algorithms remain unchanged.


<a id="method-36"></a>

### Bound asynchronous diagnostics and preserve indispensable evidence

**Atlas application.** Use bounded queues with separate policies for optional progress noise, errors and required scientific receipts. Define backpressure, shutdown flush, disk-full behaviour and task-generation identity. Keep authoritative records outside disposable retention classes.

**Boundary.** Responsive UI is not durable completion. Do not drop required errors, failed-case evidence or checkpoint parents. Forced garbage collection is not a substitute for releasing live buffers.

**Check.** Slow/full storage, saturated queues, cancellation, crash and out-of-order completion; reconcile required record IDs and demonstrate bounded total retained bytes.


<a id="method-37"></a>

### Version random-stream and faster-maths changes explicitly

**Atlas application.** Assign randomness to stable scientific identities and explicit event/draw counters, not worker completion. A changed generator, vectorised draw mapping, precision or math library acquires a reviewed numerical identity.

**Boundary.** The same seed across different algorithms does not promise the same world. Approximate arithmetic, reassociation or unreviewed transcendental routines may alter thresholds or conservation.

**Check.** Fixed vectors, worker/batch reordering, restart/retry, declared statistical properties and near-event thresholds. Separate a newly approved stochastic scenario from an execution-only optimisation.


<a id="method-38"></a>

### Use reversible dictionaries and explicit delta bases for future streaming

**Atlas application.** Separate control, viewer and authoritative data requirements. Bind schema, dictionary and delta-base identities; cap encoded and decoded sizes; retain a full-snapshot/resynchronisation path.

**Boundary.** Traffic reduction may consume CPU and memory. TTL caches, dropped visual frames or unordered channels do not authenticate scientific state. This is not a numerical-kernel priority.

**Check.** Exact decode round trips, stale base/dictionary, missing/reordered/duplicated messages, corrupted payloads, bounded decompression and interruption recovery.


<a id="method-39"></a>

### Eliminate copies only with proven ownership and lifetime

**Atlas application.** Distinguish immutable definitions, borrowed read-only inputs, private scratch and published outputs. Reuse compatible allocations or transfer ownership only where aliases and asynchronous lifetime are controlled.

**Boundary.** Current Atlas input copies and byte-backed outputs enforce real guarantees. A read-only NumPy view does not freeze its backing owner. Neither material labels nor allocation addresses prove equivalent history.

**Check.** Mutate caller aliases during/after work, reuse scratch while a writer reads it, reject a candidate and race two tasks; accepted state and cached immutable views must not change.


<a id="method-adoption"></a>

## 6. Adoption, measurement and non-goals

Use the existing PF candidate register and T/PT acceptance families; no second
execution framework or testing taxonomy is introduced. A useful optimisation
must preserve its named scientific problem or be explicitly classified as a
numerical/model change. The code path selected by default must be the tested one.

Keep dependency discovery, parsing, evaluated results and display products as
separate reuse layers. Share full immutable state in-process where appropriate;
passing one item per worker or copying a whole world per job is not a useful
parallelisation. Count retained outputs, queues, native threads and I/O together.

Optional viewer notifications, display quality and network transport may use
separate budgets, reversible dictionaries or revision-tagged caches. They must
not govern physical timesteps, drop required evidence, accelerate material ageing,
or delete required state. A transport-size ceiling is an explicit refusal, not
permission to truncate a scientific record. Hardware-specific paths and changed
random/math routines require their own supported-platform and accuracy evidence.


<a id="sources"></a>

## 7. Sources, consolidation and maintenance

### What is superseded

| Previous separate item | Maintained location |
| --- | --- |
| Plan revision 4 Sections 7.5–7.15 and separate execution-card policy/template | Sections 2–3 here; plan revision 5 keeps the high-level obligation. |
| Report 02 optimisation methods | Section 4, with O01–O17 and scientific source caveats retained. |
| Earlier engineering-method studies | Section 5 retains the 39 methods, their accuracy boundaries and required checks without a source-project catalogue. |
| Prior screening and language assessment | Methods in Sections 5–6; language contract in Section 2.6. No separate maintained screening page. |
| Report 03’s later language supplement | Section 2.6; its original scientific feasibility study remains historical research. |
| Repository PERFORMANCE_DESIGN.md and VOXEL_STORAGE.md | Sections 2.2–2.6 and 5; removed as competing current pages, preserved in Git history. |
| Separate source-register and review-guide documents | Sources and review questions in these two maintained documents. |

Earlier attachments are not erased. They are superseded where this table says so. The original scientific capability and equation cross-reference studies remain dated research evidence, not extra active plans. Existing case specifications and obtained test reports remain with their code. Do not rewrite historical test results or delete numerical predecessors while tidying documentation.

### Review questions

Challenge the relevant equation/semantics, complete dependency set, ownership and boundaries; whether a proposed speed-up actually changes the model; whether the benchmark compares equal work and error; and whether failure, restart and stale results remain controlled. A review finding should identify the ID, failure mechanism and smallest test/correction. Agreement among reviewers or shared software assumptions is not independent physical evidence.

### Runtime and language source records

**[PS01][url-002] — CPython 3.13: concurrent.futures.** Official runtime documentation. Threads/processes, serialisation/import constraints, pool deadlocks and cancellation semantics. No Python version installed or tested by this revision. Checked 16 September 2026.

**[PS02][url-003] — NumPy: Thread Safety.** Official runtime documentation. Native operations and interpreter-lock behaviour, immutable/shared-array safety; dynamic manual, not a version selection. Checked 16 September 2026.

**[PS03][url-004] — NumPy: Global Configuration Options.** Official runtime documentation. Underlying BLAS may introduce its own threads; informs explicit outer/inner thread budgeting. Checked 16 September 2026.

**[PS04][url-005] — NumPy: Parallel random number generation.** Official algorithm documentation. SeedSequence, stable identity-based streams and counter-based alternatives; Atlas task-invariance rules are proposed separately. Checked 16 September 2026.

**[PS05][url-006] — NVIDIA: CUDA C++ Best Practices Guide.** Official developer documentation. Transfer/residency, profiling and strong/weak scaling principles. No GPU, CUDA dependency or speedup selected. Checked 16 September 2026.

**[PS06][url-007] — PETSc: KSPSetReusePreconditioner.** Official solver API documentation. Lagged preconditioner reuse can increase iterations; not equivalent to caching unchanged numeric factors or a final answer. Checked 16 September 2026.

**[PS07][url-008] — Zarr-Python: Optimizing performance.** Official storage documentation. Chunk/shard/memory-layout and concurrency trade-offs. No format migration or universal atomicity assumed. Checked 16 September 2026.

**[PS08][url-017] — PETSc: Profiling.** Official developer documentation. Event/stage profiling and parallel measurements as a reference; no dependency or benchmark executed. Checked 16 September 2026.

#### Language records

- [LS01][url-013] — NumPy: numerical arrays and compiled operations. Official documentation refreshed 16 September 2026; no package version or installation selected.
- [LS02][url-003] — NumPy: thread safety and native operations. Official documentation refreshed 16 September 2026; no package version or installation selected.
- [LS03][url-014] — SciPy: array error function. Official documentation refreshed 16 September 2026; no package version or installation selected.
- [LS04][url-016] — Numba: compilation, loops and fast-math trade-offs. Official documentation refreshed 16 September 2026; no package version or installation selected.
- [LS05][url-015] — pybind11: buffer/NumPy interfaces and conversion. Official documentation refreshed 16 September 2026; no package version or installation selected.


**Consolidation boundary:** source content, links and document layout were checked; no dependency installation, source-code audit, simulation, scientific test, benchmark, numerical change or historical rebind was performed. Source access limitations and unmeasured candidate status are retained.


[url-001]: https://github.com/Atlantispy/atlas/blob/11317165b7e2aeab7201a1fe3e3f646cb640d51e/tectonics/README.md
[url-002]: https://docs.python.org/3.13/library/concurrent.futures.html
[url-003]: https://numpy.org/doc/stable/reference/thread_safety.html
[url-004]: https://numpy.org/doc/stable/reference/global_state.html
[url-005]: https://numpy.org/doc/stable/reference/random/parallel.html
[url-006]: https://docs.nvidia.com/cuda/cuda-c-best-practices-guide/
[url-007]: https://petsc.org/release/manualpages/KSP/KSPSetReusePreconditioner/
[url-008]: https://zarr.readthedocs.io/en/stable/user-guide/performance/
[url-010]: https://gist.github.com/Tomcc/a96af509e275b1af483b25c543cfbf37
[url-011]: https://gist.github.com/Tomcc/4be79d3eafcd158c5059abd4ab2e8d35
[url-012]: https://www.openvdb.org/documentation/doxygen/overview.html
[url-013]: https://numpy.org/doc/stable/user/whatisnumpy.html
[url-014]: https://docs.scipy.org/doc/scipy/reference/generated/scipy.special.erf.html
[url-015]: https://pybind11.readthedocs.io/en/stable/advanced/pycpp/numpy.html
[url-016]: https://numba.readthedocs.io/en/stable/user/performance-tips.html
[url-017]: https://petsc.org/release/manual/profiling/
[url-018]: https://www.gplates.org/docs/pygplates/generated/pygplates.topologicalmodel
[url-019]: https://gplates.github.io/gplately/latest/sphinx/html/generated/gplately.SeafloorGrid.html
[url-020]: https://se.copernicus.org/articles/10/1785/2019/
[url-021]: https://github.com/GeodynamicWorldBuilder/WorldBuilder
[url-022]: https://github.com/UniMainzGeo/LaMEM
[url-023]: https://unimainzgeo.github.io/LaMEM/dev/man/Quickstart/
[url-024]: https://aspect-documentation.readthedocs.io/en/stable/user/methods/basic-equations/index.html
[url-025]: https://aspect-documentation.readthedocs.io/en/stable/parameters/Material_20model.html
[url-026]: https://arxiv.org/abs/1907.06696
[url-027]: https://www.underworldcode.org/particles-in-underworld3/
[url-028]: https://www.underworldcode.org/how-underworld3-turns-sympy-into-c/
[url-029]: https://www.research-collection.ethz.ch/handle/20.500.11850/690333
[url-030]: https://bitbucket.org/ptatin/ptatin3d
[url-031]: https://gmd.copernicus.org/articles/9/997/2016/
[url-032]: https://se.copernicus.org/articles/14/197/2023/
[url-033]: https://gflex.readthedocs.io/en/latest/theory_and_numerics.html
[url-034]: https://github.com/EarthByte/pyBacktrack
[url-035]: https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2017GC007313
[url-036]: https://www.earthbyte.org/11247-2/
[url-037]: https://egusphere.copernicus.org/preprints/2026/egusphere-2026-3680/
[url-038]: https://fastscape.org/fastscapelib-fortran/
[url-039]: https://fastscapelib.readthedocs.io/en/latest/api_cpp/eroder.html
[url-040]: https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2023JF007140
[url-041]: https://landlab.csdms.io/tutorials/tectonics/listric_kinematic_extender.html
[url-042]: https://landlab.csdms.io/tutorials/flow_direction_and_accumulation/the_Flow_Director_Accumulator_PriorityFlood.html
[url-043]: https://arxiv.org/abs/1511.04463
[url-044]: https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0195557
[url-045]: https://github.com/badlands-model/badlands
[url-046]: https://gospl.readthedocs.io/en/v2026.6.30/api_ref/mesh_ref.html
[url-047]: https://gospl.readthedocs.io/en/stable/
[url-048]: https://egusphere.copernicus.org/preprints/2026/egusphere-2026-4124/
[url-049]: https://pylith.readthedocs.io/en/latest/index.html
[url-050]: https://pylith.readthedocs.io/en/stable/user/governingeqns/elasticity/index.html
[url-051]: https://arxiv.org/abs/1308.5846
[url-052]: https://github.com/cutde-org/cutde
[url-053]: https://academic.oup.com/gji/article/201/2/1119/572006
[url-054]: https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2022GC010427
[url-055]: https://github.com/ComputationalThermodynamics/MAGEMin
[url-056]: https://gchron.copernicus.org/articles/8/209/2026/
[url-057]: https://github.com/dyvasey/gdtchron


<a id="delivered-optimisations-4-5"></a>

## Delivered items 4 and 5 — cooling and rotation/flexure batches

**17 September 2026.** Applied to the previously delivered optimised-defaults
items 2/3 package, based on `remake` commit
`0590774b9d59fa9e6c9cba8f5306a3e2b9f6bc40`. Package version `0.1.0.dev4`.
This is a local delivery, not a remote publication. Item 1's general performance
baseline and items 6–12 remain outside this increment. Existing physical laws,
acceptance tolerances, transport implementation, compression/store format and
source/invalidation safeguards are unchanged.

### Item 4 — cooling: selected profile and bounded broadcast evaluation

**Selected normal profile: SciPy bulk `erf`, no automatic fallback.** The reference
`math.erf` path remains explicitly available for verification. Both dependencies
and defaults were established in the preceding delivery; no new package is added.
The same formula now constructs diffusion lengths once per supplied age **before
broadcasting**. It does not repeatedly calculate an age's square root for every
depth. Remaining arithmetic is evaluated in C-order batches, normally **8,192
samples**, with bounded iterator buffers and immutable output. `batch_elements`
changes only work granularity; it never changes the physical resolution or time.
A huge batch hint is capped by actual output size. Full output still needs memory;
array admission estimates include inputs, length data, buffers and publication.
The cached wrapper uses the kernel's estimate and retains complete source checks.

Scope tested: scalar and vector inputs; scalar age, varying age and crossed
age/depth broadcasts; zero-age/surface limits; equal temperatures; strided,
Fortran-layout and non-native-endian inputs; extreme ranges; masked/invalid input
refusal; missing SciPy; allocation failures; and repeat/cache/reopen behaviour.
Changing the tested execution batch sizes preserved bits within each backend.
SciPy versus the scalar reference remains numerically equivalent, **not promised
bit-identical**. No approximate error function, new time integration or thermal
PDE is introduced.

Fresh-process first-call measurements include SciPy's lazy import: median
**103.9 ms**, followed by **1.34 ms** for the next 65,536-sample
call. These are three process starts, not OS-cold-disk measurements. The optimised
backend remains the default even when a one-off tiny call would not amortise its
initialisation. There is no hidden switch back to the reference.

### Item 5 — rotation and flexure batch decisions

| Calculation | Decision implemented | Limits and interpretation |
| --- | --- | --- |
| Rotation | Construct an immutable 3×3 matrix per normalised quaternion and reuse it; matrix application is the default, normally in batches of at most 65,536 vectors. | 72 retained matrix data bytes, excluding Python metadata. `backend="reference"` keeps the prior cross-product formula. Matrix arithmetic changes rounding/order; existing tolerances, independent Rodrigues checks and rigid-motion invariants apply. No universal bitwise equivalence. |
| Flexure | Retain NumPy FFT and the existing discrete centred-difference operator. Fitting load groups take the earlier contiguous fast path. Default grouping targets at most 8 MiB of real load payload per transform group, but always at least one complete domain. | A group holds independent loads, not independent spatial tiles. An oversized individual domain is refused by its work budget rather than cut into invalid mechanics. Retained operator/coefficients and their physical/numerical identity remain unchanged. |
| Explicit group sizing | `batch_vectors`, `batch_loads` and `batch_elements` allow a case to declare execution granularity. | Positive integer controls, documented defaults, no automatic machine tuning or worker pool. Different layouts/backends remain subject to the declared equality policy. |
| Streaming independent requests | `Rotation.apply_batches(...)` and `PeriodicFlexure.solve_batches(...)` lazily yield complete immutable result batches. | No prefetch; memory reservations are released before each yield. Caller-held results still count towards application RAM. Later requests are captured when consumed; this is not one atomic snapshot of all future input. Stopping early stops further calls, not a partly completed physical timestep. |

Forced small flexure groups did **not** show a consistent speed advantage over
already-batched calls. They remain a memory/granularity control, not the default
for fitting loads. The existing FFT backend is retained, not rewritten or replaced
with continuous spectral k^4. Rotation restoration reconstructs its immutable
matrix; it does not trust pickled mutable derived arrays.

### Obtained focused results and adoption boundary

Five alternating-order warmed comparisons, one native library thread, Linux /
CPython 3.13.5 / NumPy 2.3.5 / SciPy 1.17.0. Preparation and fresh-process costs
are separate. No worker-pool, compression or complete-generator benchmark ran.

| Synthetic workload | Previous default | Current default | Interpretation |
| --- | --- | --- | --- |
| Cooling: 262,144 samples, fixed age | 6.663 ms | 4.701 ms | 29.4% less elapsed time; same SciPy backend, observed bit equality. |
| Cooling tracked peak allocation | 6,556,880 bytes | 4,197,209 bytes | 36.0% less; not whole-process RSS or a claim about all native allocations. |
| Rotation: 262,144 three-dimensional points | 14.615 ms | 2.726 ms | 81.3% less elapsed time; operator setup excluded and measured separately. |
| Rotation tracked peak allocation | 27,267,792 bytes | 12,584,857 bytes | 53.8% less; input arrays already existed. |
| Flexure: already-batched loads | Existing FFT | Same FFT with grouping | No material default speedup claimed; retaining the fitting fast path avoids unjustified new overhead. Streaming is a distinct memory-lifetime facility. |

All recorded default cooling and flexure outputs matched the prior defaults
bit-for-bit on these samples. The largest rotation difference in the 262,144-point
sample was 1.33e-15 in the synthetic coordinate
units, within the unchanged test envelope. New source identities prevent old
persistent results from being mistaken for this implementation. Matrix/reference
selection must be recorded by future rotation-result consumers; no rotation-result
persistent wrapper is introduced here.

The small/scalar and varying-age cooling comparisons do not establish a speedup
in every workload: for example, the 65,536-varying-age sample took slightly longer
in this run while allocating less. The selected profile favours bounded working
memory and sustained batch execution; measured improvements are not summed or
extrapolated to a world run. BLAS backend and thread count can change performance
and last-bit rounding. Windows/macOS, other builds, large worlds and physical
realism are not newly verified.

[Full test record](../evidence/kernel-batch-tests.json) and
[measurements including samples and first use](../evidence/kernel-batch-measurements.json)
are obtained evidence, not additional planning documents. Reproduce the bounded
measurement with `tests/measure_kernel_batches.py --baseline PATH_TO_PREVIOUS_TECTONICS`;
it verifies the relevant prior-delivery source hashes. The new regression cases
live in `tests/test_kernel_batches.py`; existing tests and fixture tolerances remain
unchanged. The usual full verifier includes them.

Primary method references: [NumPy matmul](https://numpy.org/doc/stable/reference/generated/numpy.matmul.html)
for native matrix batches and output buffers, and [SciPy erf](https://docs.scipy.org/doc/scipy/reference/generated/scipy.special.erf.html)
for the exact selected public array-function interface. Runtime versions above,
not the moving documentation version, identify the tested environment. These
sources are method/API references, not evidence of an Atlas performance gain.


<a id="execution-reuse-delivery"></a>

## Delivered optimisation items 6–8 — 17 September 2026

**Scope:** continue the delivered 4/5 tree, with its optimised numerical defaults.
No new physics, changed test tolerances, global performance-baseline programme,
GPU solver, distributed spatial solve, old-cache migration or remote publication.
Source and evidence are delivered for Michael to apply to `remake` locally.

### 6. Bounded independent-batch execution

`execution.KernelExecutor` is a caller-owned context with lazy ordered streams for
cooling queries, rotations and independent flexure load scenarios. It reserves
estimated capture/work/transfer/output bytes before admission, limits queued jobs,
reuses its worker pool, and drains running native work before releasing reservations.
Returned arrays have immutable bytes backing, including after process transport.
Neither task order nor storage chunks redefine physical coupling. A flexure row
always spans its whole domain. Iterating another physical timestep is not made
parallel by this API.

**Default policy:** `mode="auto"`, up to two available CPU workers, one inner native
thread, four in-flight jobs and a 256 MiB estimated array-work envelope. Small jobs
remain serial; independent SciPy cooling/FFT batches at least 262,144 elements may
use threads. Matrix rotations stay serial under auto because forced threading
regressed the larger comparison. These are named execution settings, not Earth
parameters, universal optima, or a process-RSS cap. Retained caller outputs, process
interpreters/native libraries and non-Atlas allocations remain outside this budget.

Explicit threads and persistent **spawn** processes remain comparison/override
paths. Processes lost on the tested workloads, so are not the default. No
per-cell futures or GPU choice is added. `threadpoolctl>=3.6,<4` is a declared
requirement; its existing installed version was used, not installed by this task.
Thread-limit leases have one driving Python thread and reject conflicting limits.
Because native thread control is backend-sensitive, explicit threaded matrix runs
are restricted to the tested OpenBLAS/pthreads arrangement; other arrangements must
select serial or spawn explicitly. Auto does not rely on threaded BLAS rotations.

Close an iterator on early termination (or exit its executor context). Cancellation
stops new admission and discards unconsumed results, but cannot instantly interrupt
a running native operation. Independent outputs already consumed remain outputs;
this is not an atomic evolving-world step or a replacement runtime graph.

### 7. Reusable verification and prepared immutable inputs

`reuse.ExecutionContext` computes source/code/runtime identities once, then checks
**complete exact source bytes and membership**, loaded function/code/default and
callable-alias identity, and relevant module constants before reuse/publication.
It does not trust mtimes. Repeated source reads remain; repeated SHA hashing,
code normalisation and marshalling are avoided. Changed source or callable state
refuses the context and requires a new explicit context/controller. No historical
identity is overwritten. Inventory size is bounded.

`PreparedInput` captures a compact immutable f64 payload and its typed digest once.
Each array access returns private shape/dtype metadata; only proven immutable
payloads can reuse their digest. Mutable arrays are captured/hashes recomputed,
never cached by object address. Prepared payload lifetime/RAM remains the caller's
responsibility, and its creation is admitted against a WorkBudget.

The execution/invocation schema is versioned to v2. Old entries remain stored but
are not repinned into the new schema. Runtime binaries keep the prior explicit
process-lifetime immutability assumption; this is not a hostile-process sandbox or
recursively authenticated installation. Hashes/contexts are not geological proof.

### 8. Admission, same-request coordination and safe publication

`cached_temperature` and `cached_flexure` now default to **automatic admission**,
not unconditional persistence. Small results bypass unnecessary identity/store
work. For eligible size bands the first call measures a direct calculation;
subsequent calls pay for persistence only when recorded compute cost and expected
reuse justify it. Current defaults: 256 KiB–64 MiB candidate result range, 10 ms
minimum observed compute, and three expected reuses. Cost/profile records are
bounded to 128 per controller; they choose execution only and never authenticate
inputs. Actual restoration/write costs feed back into later decisions. A newly
opened controller learns again; it does not treat another machine's timing as fact.

`CachePolicy(mode="always")` explicitly requests verified persistence, including
for correctness tests or known expensive repeated products. `mode="off"` avoids
store access. Native numerical backends do not change with these policies. A
provided ExecutionContext is still checked on bypass. No existing persisted
history is deleted, and a corrupt entry that is read remains an error, not a miss.

Admitted identical requests share one in-process computation, bounded to 32 active
keys and 128 waiters. Futures hold private result descriptors; returned descriptors
cannot change another caller's result shape. Failure is propagated, completed
entries are released, retries may become new owners, and a cancelled waiter does
not cancel the owner. Recursive same-key requests and saturated bounds fail rather
than deadlock or enqueue unlimited work.

Separate local processes coordinate using crash-released OS locks on 16 fixed
stripes per store and recheck the database after acquisition. This avoids stale
lease takeover and unlimited per-key lock files; colliding stripes may serialise
extra work. Windows locking is implemented but not verified in this environment.
Trusted local paths only. Direct ArrayStore writers still use existing SQLite
transactions; callers bypassing these wrappers do not inherit compute suppression.

`ArrayStore.put` has an optional final publication check inside its existing
transaction. The reuse wrapper rechecks source/cancellation immediately before
commit; failures roll back candidate rows. Cancellation after publication begins
cannot revoke a completed atomic snapshot. No schema, codec or deduplication
algorithm change is introduced here.

### Focused measurements and decisions

Five alternating-order warmed comparisons, 8 independent jobs per batch, two
outer workers and one inner native thread. Linux/CPython 3.13.5, NumPy 2.3.5,
SciPy 1.17.0 and threadpoolctl 3.6.0. Full samples, first-use costs, source hashes
and mode statistics are in the evidence, not inferred from unrelated application performance.

| Workload | Serial batch | Selected automatic path | Observed change |
| --- | ---: | ---: | --- |
| Cooling: 8 independent jobs × 262,144 samples | 35.433 ms | 22.361 ms | 36.9% less elapsed time |
| Flexure: 8 independent jobs × 262,144 samples | 33.578 ms | 21.244 ms | 36.7% less elapsed time |

Rotation auto retained the serial matrix path. Spawn process execution was slower
for all three larger workloads and is not selected automatically. Serial and
threaded answers, and the tested process answers, were bit-identical in these
comparisons; this does not establish universal cross-platform equality.

A repeated context verification took **0.866 ms** versus
**1.910 ms** for the previous fresh identity function (about
**54.6% lower**). Fresh creation of the new, stronger context
is costlier than the previous function; reuse amortises it. Timings compare stated
operations, not a universal cache speedup. PreparedInput also avoids repeated
payload hashing, but verification and restore costs do not disappear.

Forced persistent restoration of the tested cooling fields was slower than direct
SciPy calculation. Auto therefore recalculates these cheap fields, while preserving
setup reuse and all numerical checks. This closes admission for current workloads
without pretending a cache hit is invariably faster. Thresholds remain adjustable
execution policy and should be recalibrated for a materially different workload.

**216 tests passed (169 prior + 47 new), zero failures/errors/skips.** Persistence
regressions now explicitly select `mode="always"`; they still test their original
correctness invariants rather than bypassing them through auto admission. No old
tolerances or fixtures were weakened. New cases cover lazy/bounded admission,
private results, cancellation, worker failure, nested streams, spawn restoration,
thread-limit ownership, source/default/alias changes, prepared identities, cache
policy, same-key contention, creator failure/retry, waiter cancellation/timeout,
corruption, transactional cancellation and OS-lock recovery after process death.

[Full test evidence](../evidence/execution-reuse-tests.json) and
[focused measurements](../evidence/execution-reuse-measurements.json) are obtained
records; older evidence remains unchanged. Reproduce with the usual `verify.py`,
and `tests/measure_execution_reuse.py --baseline PATH_TO_ITEMS_4_5_TECTONICS`.
No scientific world simulation or package installation was performed. Windows,
macOS, other native builds, power-loss recovery and full-world resource behaviour
remain unverified. Checklist items 9–12 and unbuilt physical mechanisms are not
silently marked complete by this increment.

Method references: [CPython concurrent futures](https://docs.python.org/3.13/library/concurrent.futures.html),
[NumPy thread safety](https://numpy.org/doc/stable/reference/thread_safety.html),
[threadpoolctl and its backend/thread limitations](https://github.com/joblib/threadpoolctl),
and [OS file locking](https://docs.python.org/3.13/library/fcntl.html).
They support API semantics, not the obtained Atlas measurements.
