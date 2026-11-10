# Atlas optimisation reference

This reference owns execution, numerical cost, source and runtime identity, caches, storage and measurement contracts. [Current state](../../docs/CURRENT_STATE.md) owns delivery, outstanding work and holds. The scientific-fidelity repair remains paused, and R4.4 and full-interval scientific work retain their holds. Component checks, source integration, publication, enabled defaults, platform qualification and scientific acceptance are separate outcomes.

Start with the selected calculation and its consumers. Choose useful methods, then compare complete work at the required accuracy. Retained measurements describe their original sources and environments; they do not authenticate today's runtime or permit a checkpoint rebind. No scientific test, benchmark, installation or runtime change accompanies this consolidation. Git history retains obsolete delivery prose.

The [reader guide](HOW_TECTONICS_IS_MADE.md) and [foundation contracts](FOUNDATIONS.md) own the scientific explanation. [Package commands](../README.md#commands), [verification](../README.md#verification-and-evidence), [environment](../../docs/TECTONICS_ENVIRONMENT.md) and [development procedures](../../docs/CODING_SAFETY.md) own the existing operational routes. Commands are explicit actions, not documentation setup requirements.

[Execution](#execution-contract) · [Identity](#source-and-runtime-identity) · [Caches](#cache-contract) · [Representation](#immutable-fields-and-geometry) · [Numerical cost](#numerical-cost-and-reusable-operators) · [Storage](#storage-contract) · [Measurements](#retained-measurements-and-limits) · [Eligibility](#scientific-eligibility-and-method-provenance) · [Candidates](#candidate-register) · [Scientific software](#scientific-methods) · [Engineering](#engineering-methods) · [Sources](#sources)

<a id="current-baseline"></a>

## Scope and change classes

The retained foundation identities are `11317165b7e2aeab7201a1fe3e3f646cb640d51e` (numerical foundation) and `612d53eba495202101a8e638578f47fb37752649` (documentation-branch observation), not current-checkout claims. See the [pinned original scope][url-001]. The 15–16 September studies did not install or reproduce the cited packages; their access and preprint caveats remain in the source records.

| Change class | Meaning | Required basis |
| --- | --- | --- |
| E — execution | Layout, reuse, batching or scheduling without intended mathematical change. | Result/equality policy, complete invalidation and safe ownership. |
| N — numerical | Discretisation, precision, iteration, remapping, draw mapping or evaluation order. | Error/convergence, events and conservation under explicit numerical identity. |
| M — model reduction | Physical laws, state variables or degrees of freedom. | Separate physical justification and acceptance. |
| S — scale/representation | Mesh, partitioning, material representation or resolution hierarchy. | Boundary exchange, state transfer, conservation and workload evidence. |

A proposal may span classes. Renderer culling, record deletion, raised limits and omitted checks do not automatically preserve the scientific question. Accuracy takes priority: optimise the selected supported method without reducing precision, order, inventories, physical laws or acceptance limits. Reference routes remain explicit; missing required native dependencies refuse instead of silently falling back. Named opt-in starts, Anderson and adaptive inner accuracy retain their controls.

## Execution and resources


<a id="process-placement"></a>

### Place work at the dependency boundary

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

### Scheduling, equality and failure

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


<a id="combined-acceptance"></a>

### Shared admission and simultaneous ownership

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

#### Accounted capacities

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


<a id="execution-reuse-delivery"></a>

### Independent batches and native-thread ownership

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

**R7 repair (1 October 2026): the lease owner is a thread object, and an ended
owner's lease is recovered.** The owner of the native-thread lease, and each
executor's driving thread, used to be recorded as a thread identifier. The system
hands an ended thread's identifier to a later thread, which then passed as the
owner: it could drive the ended thread's executor and share its lease. A thread
that ended with an executor still open also left the lease, the native-thread limit
and the pool's CPU slots held for the rest of the process: every other thread's
executor was refused, the open executor could not be closed, and garbage
collection of it returned neither the lease nor the slots. Now the owner is the
`Thread` object itself. While the owner is alive the rules are unchanged: other
threads are refused, and only the driving thread drives or closes its executor.
Once the owner has ended, any thread may close an executor it left open, which
returns that executor's pool, CPU slots and share; such an executor is never driven
again. If several threads close it at once, one closes it and the others wait for
that close, so nothing is returned twice.
The next thread to take a lease, by entering an executor or through a solver
plan, also reclaims the lease itself: the
thread counts that applied before the ended thread's lease are restored, its shares
and CPU slots are dropped, and a new lease starts for that thread. An
executor whose lease was reclaimed refuses further use, and closing it returns
nothing a second time and does not disturb the new lease. Nothing happens at the
moment the owner ends: the limit stays applied until one of those two events.
A reclaim leaves the ended thread's idle workers, and any reservation held by a
stream it left suspended, in place until its executor is closed or collected.

Four cases keep the earlier refusal instead of guessing. Only shares held by
executors are reclaimed, because only its driving thread can use an executor. A
share taken directly for a plan's lifetime, as the evolving flexure support does,
may still be in use from another thread after the thread that took it has ended, so
other threads stay refused until that plan is closed, which any thread may do. A thread
that Python's `threading` module did not start is represented by a placeholder
keyed by its identifier, which CPython 3.12 never reports as ended: such an owner
is identified no better than before and its lease is not reclaimed. Any owner
that the interpreter does not definitely report as ended is treated the same way.
A thread that ends in the middle of a stream can leave jobs running in its pool.
They cannot be interrupted, and until they are done they occupy the CPU slots that
pool claimed and run under the ended thread's limit. Its lease is therefore not
reclaimed while a job it submitted is unfinished: other threads stay refused,
instead of being admitted beside those jobs with the slot count reset, and are
accepted once the jobs are done or that executor has been closed, which waits for
them. Each pool job is registered with its lease for this purpose.
And an executor left open by a thread that is still alive remains that thread's
to close. No admission formula, limit or default changes, and no timing is
recorded for the extra ownership checks or the per-job registration.

Close an iterator on early termination (or exit its executor context). Cancellation
stops new admission and discards unconsumed results, but cannot instantly interrupt
a running native operation. Independent outputs already consumed remain outputs;
this is not an atomic evolving-world step or a replacement runtime graph.


<a id="3cr2-scaling-execution"></a>

### Request-owned precursor dispatch

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
process mode is refused. Each threaded request creates, drives and closes its own
executor on the calling thread, inside the plan's dispatch lock. Small independent
serial readers still share the immutable prepared state. No second scheduler or
unbounded worker queue was introduced.

**R7 repair (1 October 2026): the executor belongs to the request, not the plan.**
Before this repair the first threaded request created a pool lazily and the plan
kept it until close. That tied the plan, the process-wide native-thread limit and
the pool's CPU slots to whichever thread made that request: other threads were
refused, and the plan could not be closed once that thread had gone. Now the
executor ends with the request. An idle plan holds no worker pool, CPU slot or
native-thread limit and may be closed from any thread; a close is refused only
while a call is active. Threaded requests on one plan take turns under the dispatch
lock. They are serialised, not run in parallel, and this adds no wider
thread-safety guarantee. A request still waiting for its turn is not yet active:
a close made then succeeds, and the waiting request is refused because the plan
is closed. The native-thread limit is set when a threaded request
starts its jobs and restored when they end, so it changes once per threaded request
instead of once per plan; a compatible lease already held by the calling thread is
shared for the request and left in place. While another live thread holds a
native-thread lease, or the calling thread holds one with a different inner-thread
count, the request raises the executor's existing `TectonicsError` before any job
is submitted, releases its reservation and leaves the plan usable. So does a
request whose pool would exceed the CPU slots left by executor pools the calling
thread already holds. A threaded
request is therefore refused, not queued, while a threaded request on another plan
is running on a different thread. The refusal arrives after input capture and, for
cells, after whole-request validation. The accepted cost is that the worker pool is
rebuilt, and the native-thread limit set and restored, for every threaded request;
no timing of that cost is recorded here.
`execution_statistics()` describes one dispatch only, as its contract already
said: `peak_inflight` and `accounted_executor_peak_bytes` are no longer maxima over
the plan's lifetime. It is the last dispatch that was recorded, which is not always
the last request. A serial request writes the record when it is routed; a threaded
request writes it only once all its jobs have completed. A threaded request that
fails, is cancelled or is refused therefore leaves the earlier record in place, as
it did before this repair. The local-law plan differs: its record also describes a
threaded evaluation that failed or was cancelled
([R3 execution notes](#3cr3-execution)). Scientific outputs are unchanged. The
package identity, and with it every plan and sample identity, changes as it does
for any source edit.

The prior-evaluation native batch default is 32,768 rather than 4,096 points.
This changes scheduling/scratch, not per-point mode summation or numerical order;
user-specified batch limits are honoured. GeometryIndex scratch also clamps its
batch to actual query length rather than charging a full policy batch for one
point. Both changes are covered by equality/refusal tests.


### Full-request admission, ordering and cancellation

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
reservations are released; the plan can be reused after the failed request, whose
executor is closed with it (R7, 1 October 2026).

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

## Source and runtime identity

The bounded combined-start benchmark has an independent historical source boundary: [`source_audit`](../tools/benchmark_combined_start_r4_4.py) requires detached base `49c6603fad2ed9a92f6f2a302037dd425f154c3c`, exact source membership and exact runner/case/project/reference bytes, including this document. Later reference edits do not qualify that benchmark or authorise repinning it. Its synthetic harness tests verify those refusals.


### Exact live verification and prepared input

`reuse.ExecutionContext` computes source/code/runtime identities once, then checks
**complete exact source bytes and membership**, loaded function/code/default and
callable-alias identity, and relevant module constants before reuse/publication.
It does not trust mtimes. Repeated source reads remain; repeated SHA hashing,
code normalisation and marshalling are avoided. Changed source or callable state
refuses the context and requires a new explicit context/controller. No historical
identity is overwritten. Inventory size is bounded.

The R1 dtype correction also captures loaded NumPy dtype constants recursively:
byte order, item size/alignment, ordered fields and their offsets/titles, subarray
base/shape and metadata. Dtype equality/hash and `.str` alone are insufficient.
Metadata is re-read on each verification; plain scalars/bytes, lists/tuples,
mappings, NumPy scalars and nested dtypes are supported. Cycles and other opaque
metadata refuse rather than receive a type-only identity. This intentionally
changes execution identities; existing caches/checkpoints are not rebound.
The focused `IdentityTests` in `test_execution_reuse.py` cover actual checkpoint
dtype replacement, fresh/existing identities, structured layouts and nested
metadata mutation. See NumPy's [dtype](https://numpy.org/doc/stable/reference/generated/numpy.dtype.html)
and [structured-array](https://numpy.org/doc/stable/user/basics.rec.html) documentation.

`PreparedInput` captures a compact immutable f64 payload and its typed digest once.
Each array access returns private shape/dtype metadata; only proven immutable
payloads can reuse their digest. Mutable arrays are captured/hashes recomputed,
never cached by object address. Prepared payload lifetime/RAM remains the caller's
responsibility, and its creation is admitted against a WorkBudget.

The original prepared-input delivery used execution/invocation schema v2; the stable-code correction below uses v3. Old entries remain stored but
are not repinned into the new schema. Runtime binaries keep the prior explicit
process-lifetime immutability assumption; this is not a hostile-process sandbox or
recursively authenticated installation. Hashes/contexts are not geological proof.

**Repair note (R7, 1 October 2026; not accepted): each loaded binary is hashed once
per process.** The runtime record's binary digests were kept in a 16-entry
least-recently-used cache. On the pinned Windows environment the reference record
names 11 distinct files, the SciPy record 17 and the Numba record 19, so the last
two never fitted: every new context of those backends evicted and re-read its own
files, 15 files (19,382,272 bytes) per SciPy context and 18 files
(126,458,160 bytes) per Numba context, and each W12 publication opens one of each.
The cache is now unbounded. Its keys are the fixed paths of the runtime record
(about 20), so it does not grow with use, and a repeated record or a second
context of the same backend hashes no file
([`LoadedBinaryReuseTests`](../tests/test_runtime_portability.py)). The record's
content is unchanged; only the repeated reading is removed. One behaviour changes
with it: a binary replaced on disk while the process runs is no longer noticed by
a later SciPy or Numba context, as the assumption above already said. Before the
repair such a context re-read most of its files (15 of SciPy's 17, 18 of Numba's
19) and took the identity of a replacement among those, although the process was
still running the binary it had loaded. The figures are
file and byte counts from a reproducer run in the scratch candidate on
Windows/CPython 3.12.14; no time saving was measured.


<a id="3cr4-4-source-verification-execution"></a>

### Streaming callable verification

Identity preparation still uses `_callable_inventory` to capture ordered tokens,
constant bytes and loaded-code signatures. Repeated verification now scans live
module and class dictionaries against held expected bindings instead of building
new sorted member lists, a signature dictionary that is discarded, and a complete
replacement token tuple. A no-defaults (`None`) path avoids needless recursive
normalisation. Every mutable default and native option is still normalised each
time; registered constants are still canonically encoded and compared each time.
No acceptance cache, source mtime shortcut, delayed check or skipped nested check
is introduced. `_source_bytes`, `_runtime_record` and the normaliser are unchanged.

Each verification consumes a PRIVATE shallow copy of the expected-key table.
It neither changes the retained baseline nor shares scratch across concurrent
readers. Consuming every key detects missing entries and duplicate qualified
names, not just a coincidentally equal count. Ambiguous names present at capture
use the original full comparison, not a weaker fast path. The new comparison
helper is checked before entering it as well as through the live inventory.
Function/code identity uses held objects, so object-id recycling is not relied on.

The additional retained Python lookup table shares existing token objects. Its
memory is context/interpreter overhead, not an extra numerical array or a claim
that WorkBudget bounds total RSS. Timing and allocation probes are separate:
profiling/tracemalloc results must not be reported as unprofiled timestep timing.
Current-byte source reads, method/default/constant/native-option checks and all
original entry/exit checks continue. Arbitrary concurrent source mutation and
hostile in-process modification are not made atomic or sandboxed by this change.

The new test catalogue compares success/refusal with the retained full-inventory
oracle, including live code, methods/descriptors, nested mutable defaults and
constants, JIT options, same-size/same-time file edits, aliases, duplicate names,
new/removed source and lifecycle/recovery controls. Preconditioning, compiled
mechanics, nonlinear starts and their numerical acceptance gates are unchanged.


### Module membership and constants

The 30 September candidate intentionally broadens identity; this paragraph is not a present acceptance claim. `ExecutionContext` now binds the loaded
code of every package module in the source membership (137 modules; the seven
numba kernels whenever importable, skipped for other backends when their optional
runtime is missing or broken) instead of a fixed 112-name list, fixing review
finding s01-1. Upper-case module data is bound too: dicts, lists, sets, mapping
proxies, numpy scalars (exact value) and arrays (dtype, shape, digest), compiled
patterns, functions held in such tables (by code digest and defaults), and numpy
function defaults, which were previously reduced to their type. This
intentionally changes every package execution identity; no receipt was repinned.


### Stable code encoding

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


<a id="cleanup-execution"></a>

### Interpreter portability and its unsealed boundary

The Python executable path is resolved strictly before hashing its regular-file
target. This supports linked and copied virtual-environment launchers. Only the
interpreter path receives that treatment, including the built-in `math` fallback.
Source files, reference data and binary extensions keep their existing symlink
refusals. Broken/cyclic interpreter links and non-files fail explicitly. Hashes
identify binary content rather than absolute installation paths; the existing
process-lifetime immutability assumption for loaded binaries is unchanged.
This is runtime provenance, not a defence against arbitrary hostile process edits.
See [environment setup](../README.md#environment) for the independent tectonics
venv; the older source-only bootstrap is not its dependency environment.

**Correction (R7, 1 October 2026): the hashed file need not contain the
interpreter.** The paragraph above reads as if the interpreter's own bytes entered
the runtime identity. On Windows they do not. In the pinned environment
`sys.executable` is the virtual environment's `python.exe`, a 277,808-byte copied
launcher. It is a regular file, so resolving it changes nothing, and it is the
file that is hashed. The process itself runs the base `python.exe` (107,312
bytes), which is only a stub that loads `python312.dll` (6,985,520 bytes, the
module at `sys.dllhandle`); that DLL holds the interpreter and its built-in
modules. Neither of those two files is hashed. Built-in `math` has no file of its
own, so the record's `math` entry repeats the launcher's hash and adds nothing.
On Windows the interpreter's identity therefore rests on the recorded
`sys.version` string (version, build date and compiler): two builds that report
the same string, or an edited DLL, share one runtime identity. Extension modules
(NumPy, SciPy, Numba, Shapely and its bundled GEOS libraries) are still hashed as
files. What is hashed did not change in R7: hashing the DLL would change the
Windows runtime identity and is left as a separate decision. Only
Windows/CPython 3.12.14 was examined; the same gap applies wherever the
interpreter lives in a shared library and not in the resolved executable.

## Cache identities and lifetime

<a id="cache-contract"></a>

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


### Admission, concurrent creators and publication

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
lease takeover and unlimited per-key lock files; colliding stripes originally
serialised unrelated work (see the R4 corrections below). Windows locking is
implemented but was not verified in this original (Linux) environment; the R4
tests run it on Windows.
Trusted local paths only. Direct ArrayStore writers still use existing SQLite
transactions; callers bypassing these wrappers do not inherit compute suppression.

`ArrayStore.put` has an optional final publication check inside its existing
transaction. The reuse wrapper rechecks source/cancellation immediately before
commit; failures roll back candidate rows. Cancellation after publication begins
cannot revoke a completed atomic snapshot. No schema, codec or deduplication
algorithm change is introduced here.

**R4 corrections (30 September 2026 candidate; not a new measurement).**
- *A cancellation stays its caller's own.* A waiter used to re-raise the owner's
  `CancelledError` although its own event was unset, discarding a completed result.
  A waiter whose event is unset now registers again, within its original deadline:
  it becomes the owner and computes with its own cancellation, or waits for a newer
  owner. A retry never waits again on the finished future of an owner it has
  already seen cancelled (an owner resolves its future before it removes its entry).
  After three such retries it reports that other callers cancelled
  (`TectonicsError`), never a cancellation of its own. One deadline covers a caller's
  waiting: for an identical in-process flight and, if it takes over, for the process
  claim. A creator's *failure* is still shared with waiters, as before.
- *Stripe collisions no longer fail.* The claim is still held across computation for
  cross-process suppression of identical work, and the 16 lock files are unchanged.
  The holder now writes its cache identity after the one locked byte (outside the
  locked region, so it stays readable on Windows). A request that finds its stripe
  held by a different identity proceeds without the claim — its lookup and
  publication are rechecked and idempotent — instead of timing out after
  `wait_timeout`, which previously failed about one in sixteen unrelated requests
  behind a computation longer than 30 s. A request for the identity the holder is
  computing still waits. The trade-off: while an unrelated identity holds the stripe,
  requests for one identity in several processes each compute (a duplicate; the
  publication stays idempotent), where they previously queued behind the unrelated
  work. A stale or partly written record only decides whether to wait. Per-key lock
  files and byte-range locks were not adopted: the first grows without bound, and the
  second would need untested POSIX lock semantics.
  On Windows, creating the first lock byte now participates in that same bounded
  retry loop: a rival can initialise and lock it between the size check and write.
  This transient contention no longer escapes as a raw `PermissionError`; timeout,
  cancellation and handle cleanup remain in force.
- *Store boundary.* Opening compares the database's `sqlite_schema` rows exactly
  with the store's three tables and their two automatic indexes (every storage
  revision created the same statements; SQLite records them without `IF NOT
  EXISTS`, as checked on the pinned SQLite 3.53.1), inside the write lock and before
  any statement touches a table. Views, triggers, generated columns, defaults,
  checks and extra indexes refuse. SQLite parses a file's whole schema at the first
  statement, before any comparison: an 8 MB view measured about 700 MiB of memory.
  Opening therefore first sets `SQLITE_LIMIT_SQL_LENGTH` to 4,096 bytes (every store
  statement and schema row is under 200) and a
  [progress handler](https://www.sqlite.org/c3ref/progress_handler.html) that stops
  the open sequence after 200 ticks of 1,000 virtual-machine operations (genuine
  opens of new, small and 8.7 MB stores took no tick; 20,000 schema rows exceed it
  and refuse in about 0.2 s). SQLite's [security guidance](https://sqlite.org/security.html)
  (§1.1–1.2) lists that handler; its `integrity_check` and `cell_size_check` are not
  adopted, because every manifest and chunk is already hashed, typed and
  length-checked before use and a whole-file check at each open would scan the full
  store. Opening an existing store ends with `ROLLBACK`, so it writes nothing and
  succeeds beside a reader. Known limits: a WAL-mode file is converted by
  `journal_mode=DELETE` before the comparison (the project loader works on a copy),
  and table root pages are not compared (record hashes still decide integrity).
  `put` refuses a snapshot whose total exceeds `max_array_bytes`, the limit `get`
  applies to a full read; streaming reads still check each array only. Manifest and
  chunk rows of the wrong SQLite type refuse. SQLite errors while opening, reading or
  publishing become `StoreError`, and lock contention, bounded-work refusal and file
  access failures (read-only, full, I/O) are named instead of being reported as
  corruption.

### WP11 certified-fact cache feasibility

**Evaluated feasibility; NOT BUILT OR WIRED.** This is the 16 October 2026 scoped decision, not authority to reopen work. Cross-query keys repeat often, but the projected endpoint saving is small, interface saving zero, and exact record preservation makes hooks invasive. Every cache saving below is an unmeasured upper bound, not an achieved speed-up. Storage would own the cache/quota; geometry would own the hook at the existing per-query reuse site.

Historical source locators use G=geometry-growth-r1; RC1=composed-r1/runtime-src/atlas_tectonics, W6=T/gg/workers6-r6/atlas_tectonics, DG=integration_differential_geometry.py. These private composition names/line numbers identify the inspected source, not a runnable public source selection. The retained [key-census script](../optimisation/workbench/geometry-growth-r1/scripts/wp11_key_census.py) processes JSON without importing runtime or executing geometry; original evidence identifiers remain below.

#### Candidate facts and exact operands

One query is support/logical-component/endpoint, with t=0 or duration_s (RC1 DG:4893), and one arena-owned _ComponentRayCache (RC1:4981/W6:5509). Leaf predicate order is RC1:4395–4449/W6:4773–4827.

| Predicate | Exact operands and reusable portion | Existing query reuse / source |
| --- | --- | --- |
| A: _common_ray_cone_zero_volume, cell=None | Ordered name/sign literals, their exact constraint bytes, a=b=t, level; cell-independent. Cell variant at clipped root is cell-dependent. | Decline-only 64-bit level mask; successes recompute per leaf. RC1 DG:4011,4037,4429–4436,4513–4515 / W6:4389,4810. |
| B: _corotating_plane_pair_zero_volume | Literal/constraint prefix has no time or level; cell enters only final voxel projection. | Impossibility bit1; possible families repeat prefix. RC1:3847–3910,3900,4411 / W6:4225. |
| C: _coaxial_edge_pair_zero_volume | Impossibility uses literals/constraints only; later ray-box work depends on a,b,level and cell. | Impossibility bit2. RC1:3913–3991,3934–3965,3968,3980,4416 / W6:4291. |
| D: integration_cone_zero.certificate | Cell vertices/axes, literals/constraints,t; root-only. | No cross-query root repeats. cone_zero:154, RC1 DG:4406–4408. |
| E: integration_cone_zero.plane_certificate | Per-literal cell vertices,constraint,sign,t; certificate includes literal name. | Root-only, no root repeats. cone_zero:94–151,142–143; DG:4444–4446. |
| F: _clipped_voxel_edge_zero_volume | Cell,literals,constraints,t,level; clipped root only. | No cross-query repeats. RC1 DG:4225,4518. |

Names must remain in keys even where name-free census counts match, because certificates carry literals/triangle_literals (RC1 DG:3902–3905,4131–4167). Literal/list order and sorted integer-set iteration are fixed. Byte-identical complete operands give the same result/certificate at the declared method/precision.

A completed None is a mathematical decline. Budget exhaustion, cancellation and QueryCap/time limits are exceptions, never cacheable declines; store only normal None/certificate returns. Level sets pose target norm/2^(32+2×level) (RC1:1025/W6:1143), so A and post-impossibility C keys need it. B prefix/C impossibility need neither time nor level. prior means constraint rotation history (prior_rotations plus snapshot offsets), not previous-query state; it is an operand through exact constraint bytes (RC1:3994–4008).

A hit must preserve more than its boolean/certificate:

- Replay original ordered work charges (B:128 per equal-rotation pair; C:64+32×n; A:128+64×paths plus later work; RC1 DG:3886–3887,3955,4050–4210). work_units enters records (RC1:5080/W6:5621).
- Re-retain ray boxes produced by A/C in original order: _ray_box affects later pose hits/work counts and per-query cache state. The cache retains at most 256 entries/2 MiB with reservations (RC1:492–506). W6 WP23 per-arena rotation memo caps 4,096 entries (W6:1051,1171–1205) and replays charges on hits, but arena.keep reservations still differ.
- Set declined_cone_levels/impossible_pair_families exactly as a miss would, since these gate later calls.
- Resolve admission semantics explicitly: miss operand workspace can refuse where a hit succeeds. WP23 accepted charge replay only; WP11 must declare that policy or re-admit original peak bytes. No silent equivalence claim.

A complete fact key needs exact ordered literal/constraint bytes, exact rational a/b, relevant level and variant/cell operands; predicate and callee source identities (_rigid_plane_path,_ray_box,_pose_vector,_rotation_boxes), replay format, certificate/verifier schemas, runtime package digest, Python/gmpy2 versions, PYTHONHASHSEED=0 and process_epoch. See inspected composed-r2/helpers/certified_fact_cache.py:14–49. Per-process epoch means one private cache per worker, not a shared serial hit rate.

#### Capacity and cost model

Inspected content_cache.py charges backing+OWNER_BYTES=4,096, and carrier 4,096+512+4×len(epoch)+32: **8,864–8,992 B fixed per fact** for a 32–64-character epoch, plus one CACHE_CONTROL_BYTES=2,048. A 32-byte SHA256 key is covered by the index charge; every hit still invokes the verifier (:752). Backing must include replay, not just CertifiedFact(bool,certificate).

| Fact | Estimated backing | Charged total |
| --- | --- | --- |
| B prefix: ordered inward/alpha/beta outcomes plus charges | 0.3–1 KB | 9.2–9.9 KB |
| A decline plus charges/replayed boxes | 1–8 KB | 10–17 KB |
| A success certificate plus replay | 2–10 KB | 11–19 KB |

Ray boxes book at least 1,024+128×values bytes each (RC1 DG:500–501). The 64 MiB facts quota sits inside the single 256 MiB retained scope (compact_contracts.py:28–30): capacity is 7,557 zero-backing facts, roughly 6,800 at 1 KB or 3,900 at 8 KB. IV2 serial needs 2,306 B plus 2,564–2,991 A key/level facts, about 4.9–5.3k facts / **47–90 MiB**, at or above quota. One owned packed allocation per literal family could remove much fixed overhead; it was not implemented or measured. These are charged estimates, not process RSS.

The pure-JSON census ran once at one core with PYTHONHASHSEED=0, 14:42:23–14:43:08; peak 0.07 GiB. Canonical keys reduce rationals; enumeration matches replay_queries.py:172–176. Original output identifier: evidence/wp11-census-r1/census.json. Query-level repeats are an upper bound on callable/level hits: a later query can hit only levels already visited. All 27,004 IV2 final-f2 endpoint rows joined and were met; 7,075 of 7,181 IV1 support IDs differ between final-f2 and requested work inputs, so **IV1 CPU weights were not used as matched evidence**.

| Query-level key | IV2 total/distinct (repeat fraction) | Six-private-cache IV2 proxy | IV1 total/distinct (repeat fraction) | Same-support repeats IV2/IV1 |
| --- | --- | --- | --- | --- |
| A literal/constraint/t | 27,004/2,564 (90.5%) | 13,912 (51.5%) | 7,181/635 (91.2%); private proxy4,125 | 0/0 |
| B-prefix/C-impossibility | 27,004/2,306 (91.5%) | 15,297 (56.6%) | 7,181/503 (93.0%); private proxy4,629 | 258/72 |
| D/E/F cell root | 27,004/27,004 (0%) | 0 | 7,181/7,181 (0%) | 0 |
| E per-literal cell subtest | 237,002/33,002 (86.1%) | 165,269 | 52,748/17,326 (67.2%) | 60,362/16,530 |
| Constraint pose/t, level-free | 237,002/2,228 (99.1%) | 224,213 | 52,748/1,412 (97.3%) | 4,284/1,077 |
| Snapshot nested constraint/offset | 167,927/966 (99.4%) | 162,454 | 29,314/510 (98.3%) | 4,817/838 |
| Ray direction/omega/history/t | 348,580/397 (99.9%) | 346,248 | 61,254/240 (99.6%) | 3,359/629 |

IV1 six-cache cone/prefix proxies are 57.4–64.5%. IV2 A groups cap at 50 queries (1,272 groups of 9–16; 299 of 17–64). Repeat-query CPU was 380.8 s for A keys / 388.8 s for B keys out of 433.7 CPU-s. There were 30,573 leaves for 27,004 queries; within-query reuse could remove at most 3,569 leaf calls.

The only endpoint profile, evidence/profile-iv2-rc1-858-r1.prof, is one unusually deep RC1 query: support 858, end, 11 literals, 1,391 leaves, 60.3 s. B cumulative 9.63 s/16.0% over 1,390 calls (6.93ms/call); A 0.669 s/1.1% over 32 (20.9ms/call); C 0.002 s/0.003% over 1,390; D 0.108 s/0.18% once; E 0.008 s once; F 0.022 s once. Multiplying removable B 28,267 and A 28,009 calls by those means predicts 196+585=781 CPU-s, exceeding the entire 388.8 repeat-query CPU: **deep-query per-call costs do not transfer to typical ~16ms queries**.

The strict ceiling is 388.8 CPU-s, implausibly assuming all repeat-query work disappears. A share-based projection assumes the deep query is representative: (16.0+1.1+0.003)%×388.8=**at most66.5 CPU-s**,15.3% of the endpoint pass. Six private caches retain about56.6–62% of relevant repeats, yielding38–41 CPU-s or about6–7s wall at six workers. The rough15 CPU-s IV1 estimate uses a different 97.2 CPU-s support build and is not a matched projection.

**Interface benefit is zero:** A–F have no interface-profile calls; interfaces dominate geometry (deep IV2 final-f1 interfaces 2,134 s). Interface _common_plane_factor,zero_area,intersect_world_line each account about 0.1% (factor 0.43 s of 742 s in wp22-profile/cand-deep-s0.prof). Existing face/corner caches are cell/face-dependent: moving-interface factors key(name,edge,section), voxel sections include fixed face, corners key face corner; moving-face predicates are per face. interface_exclusion:336 explicitly adds no persistent decoded-path cache; rigid intersection has none.

A partial q14 interface-only profile (evidence/wp23r-prof-r1; 5/49 interfaces, 249.4 s) had zero A–F calls and shares rotation_boxes 9.1%, constraint_pose 4.4%, pose_vector 3.9%, ray_box 2.2%. Its final merged figures were unavailable in the note; blanks are not results and interface profiling cannot supply endpoint shares. Pose work is a better candidate, not an authorised build: 397 distinct ray poses serve 348,580 query uses; it is 23–38% of the deep endpoint and 9–11% of interface profiles after WP23. A process-level memo would need the same charge replay.

**Disposition: do not build WP11 now.** High repeat rate does not override small unmeasured payoff, memory pressure or slower complete elapsed time. Revisit only after an explicitly authorised endpoint-pass profile demonstrates A+B at least 5% of measured endpoint time; if warranted, B's cell/time/level-independent prefix is first, then A declines with ray-box replay. D–F are excluded because their root keys have zero repeats. No profile, build, interval run or cache activation is triggered by this record.


## Immutable fields and geometry


<a id="copy-transport-increment"></a>

### Capture, borrowing and publication

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


<a id="w01-stage1-delivery"></a>

### Coordinate and clock batches


Coordinates use NumPy batches normally 65,536 points and a retained immutable 3×3 basis (72 numerical bytes, excluding origin/metadata). Direct local transforms compose small operators rather than materialise full intermediate XYZ arrays. Direct clock conversion combines origins before scaling to protect small intervals; lost positive steps/offsets refuse. Capture and publication follow the shared immutable-buffer contract. [Coordinate/time science](FOUNDATIONS.md#w01-coordinates) owns frames, units, moving-frame velocities, chord interpretation and uncertainty.


<a id="w01-stage2-delivery"></a>

### Prepared predicates and conservative candidates


Native Shapely/GEOS uses WKB-backed immutable definitions, prepared predicates and STRtrees built once. Index multipart components without new geological IDs. Bound query chunks, matches and conservative overlay envelopes before native calls; provably disjoint boxes avoid a quadratic allowance. No points×edges distance matrix, snapping, precision grid, downsampling, repair, nearest/first-owner fallback or cached cheap-predicate result is adopted. Native arc loops retain fastmath=False, cache=False and no parallel reduction.

Per-chart spherical boxes are broad phase only. Final exact predicates retain every boundary owner and conditioned-chart/metric meaning stays in [geometry science](FOUNDATIONS.md#w01-geometry). Index owners retain allowances until close and refuse active-reader close; native calls are cooperatively cancellable at bounded boundaries. Shapely extensions/bundled GEOS enter runtime identity; undiscoverable system GEOS remains unsealed. Restore rebuilds derived native setup from verified definitions.


<a id="w01-stage2-corrections"></a>

### Range-safe arc/import corrections


Stable short-arc normals use (a+b)×(b−a), scaled before norm, without enlarging physical corridors; finite-arc membership still precedes endpoint fallback. Independent 90-digit captured-endpoint products cover short lengths, offsets, orientation and reversal. Native loops retain strict arithmetic and bounded scratch.

Import checks every individual sequence/component after native parsing: adjacent duplicates refuse, legitimate closure/equal endpoints in separate components remain valid. Interior zero distance is applied before conversion to metres; unrepresentable outputs refuse while representable extreme radii remain supported. Empty queries also check cancellation before allocation/return. These corrections do not change valid WKB definitions or existing geometric tolerances; formerly admitted invalid definitions may now refuse restore. [Geometry science](FOUNDATIONS.md#w01-geometry) owns predicate definitions; [correction evidence](../evidence/w01-stage2-corrections.json) retains the original probes.


<a id="w01-stage3-delivery"></a>

### Shared boundary representation


Native noding/indexing builds source-side/ring preparation once. A shared region-header digest is reused in edge/node IDs; CSR vertex→ray and region→directed-edge incidence avoid one network scan per region, and velocity groups build in one pass. Frames/traces run bounded batches without full edge×query storage. [Static-boundary science](FOUNDATIONS.md#w01-stage3) owns occupied sides, junction sectors, shared physical edges and spherical metrics.

Inputs and compact outputs share immutable backing with private descriptors. Count genuinely shared geometry once plus retained network estimate; GEOS/STRtree allowance is not RSS. Immutable indexes support concurrent reads and rebuild from saved WKB, never trusted pickle. New geometry/labels create new network identities. Native GEOS calls finish before cancellation releases ownership.


<a id="w01-stage3b-delivery"></a>

### Spherical atlas indexes and canonical geometry


Atlas membership reuses radius-bucketed spherical caps/cKDTree and batched chord comparisons. A tighter vertex-derived cap is used only when its convex-hemisphere proof applies; otherwise retain the declared chart cap. Exact final predicates return all owners and deduplicate same-plate patches. The discarded broad-cap/per-candidate Python prototype demonstrated that candidate count alone is insufficient; complete query cost must improve.

Canonical vertices/shared arcs avoid all-face intersection matrices. Explicit stitching checks declared bindings with a fixed 64-epsilon angular round-off allowance and records actual error; larger disagreement refuses. Preserve already-unit coordinates instead of repeatedly renormalising and drifting byte identities. Chart changes preserve physical geometry; same-owner patches do not create perimeter/adjacency. [Atlas science](FOUNDATIONS.md#w01-stage3b) owns coverage/manifold/Euler and area contracts.

Retained indexes hold allowances until close; atlas/results are caller costs. Saved numeric registry and static definition deduplicate across chart-only changes; native indexes rebuild on restore. Runtime provenance includes the spatial native binary. No new cache, scheduler, codec or history cleanup is selected.


<a id="w01-stage3c-delivery"></a>

### Generated partition setup and repatching


One Qhull calculation for >=4 sites feeds sparse incidence traversal: canonical site triples create junctions once and primal edges define shared arcs. Explicit 1/2/3-site constructions handle degeneracy without a fictitious hull. No dense pair matrix, repeated polygon intersection or angle-sorted dual rings is required. PlanetaryPartitionPlan retains immutable sites, vertices and rings so layout changes do not rebuild the hull.

Auto retains conditioned cells, fanning only where needed; all-triangle mode changes representation cost, not physical geometry. Repatch from saved sites, not a new draw. Named seed mapping, sorted IDs/traversal and finite whole-candidate retries are declared prior semantics; authored near-duplicate/non-spanning/unresolved-cofacet inputs refuse without QJ/joggling. Bounds precede native allocation and cancellation occurs between phases, not inside a running hull. Budget/audit failures never trigger a favourable reroll.

A partition is globally coordinated, not a per-plate worker pool. Existing immutable/indexed geometry and lossless snapshots retain resolved sites/source/runtime. [Partition science](FOUNDATIONS.md) owns nearest-site/coverage/layout invariants and the distinction from a geological formation model.


<a id="w01-stage4-delivery"></a>

### Compact geological descriptions


Frozen slotted SI records share material/cohort/thermal catalogues and existing immutable geometry instead of per-cell Python objects. Highest-first prepared province ranks resolve k matches in O(k log k), not a scan of all P provinces; retain every match. Preflight bounds nested records, strings, profile samples and geometry. Immutable readers need no new metadata worker pool or compiler.

Canonical catalogue order preserves physical layer/profile/precedence order. A complete snapshot shares aliases once and contains WKB/topology dependencies plus canonical description bytes. Cases bind topology, properties, thermal history, evidence, depth/epoch and precedence. Corruption/missing dependencies refuse rather than reroll. [Foundations](FOUNDATIONS.md) own units, uncertainty, mixtures, province/plate distinctions, fault/weak-zone precedence, interpolation and scientific eligibility.


<a id="w01-stage4b-delivery"></a>

### Reference material tables


One immutable bounded process catalogue and caller-owned compact numeric tables/known-value masks serve native integer gathers; source strings/objects are not copied per cell. Convert units and compile once. Accurate scalar mixture sums need no compiler/pool/GPU. No unbounded global prepared-table cache or generation-time external fetch is introduced.

The bounded library has 67 profiles, seven recipes and 11 source/method records (39 bulk rocks, 25 minerals/endmembers, water/seawater/ice); canonical library JSON travels through the existing chunked lossless store with actual sources and interpretation/condition identities. [Material science](FOUNDATIONS.md#w01-earth-materials) owns coverage, basis, ranges, missing fields, 44 nominal-293.15-K rho/cp/k combinations, 30 expansion secants, conductivity bounds and radiogenic eligibility. Version/binding conflicts refuse rather than overwrite.


<a id="3cr2-initial-execution"></a>

### Initial sampling and bounded profile reuse


PreparedPrecursor shares immutable case/catalogues and indexes. Grouped native point hits, unions/depth searches and CSR associations avoid per-point objects and point×mode/cell×material cubes. Exact cell overlay/precedence subtraction decides ownership. Constant-depth breaks split explicitly; compensated sums accumulate actual portions. A call-local cache of 1,024 interval means keys profile/top/bottom/radius at fixed case time, never a cross-state thermal cache. Polygon-boundary Fourier integrals include holes and separable depth factors; factored/sinc long-wave forms retain summation order. Unsupported spherical Cartesian-prior integration refuses, never substitutes cell-centre sampling. [Sampling science](W01_INITIAL_SAMPLING.md) owns formulas/support meaning.

Retain context/maps/index allowances until close; join capture/fragments/sparse/native/publication admission, finite row/work/vertex bounds and active-reader close guards. Source invalidation at close must release reservations. Caller samples/state/geometry need aggregate nbytes accounting plus external native/interpreter headroom. State IDs bind case/library/origins/cooling/volume/precedence/prior stream/scales/frame; prepared IDs add limits/context. One result snapshot contains actual support/arrays/descriptor and precursor/library decoding dependencies, so restore neither reacquires nor resamples. Sampling-v2 worker order/configuration stays outside scientific identity; changed source refuses.


<a id="w02-materials-delivery"></a>

<a id="w02-completion-delivery"></a>

### Regional material layout and remap geometry


A C×N immutable partial-thickness matrix plus compact cohort metadata replaces per-cell objects. Candidate/flux output costs O(CN); two reused stage vectors and slopes cost O(N). Keep formation data once per cohort, never merge distinct origin/time histories to fit RAM. Unknown age and empty occupancy stay explicit. Nonlinear limiting does not commute with summing cohorts, so total/fractions are derived, not independently evolved. This is bounded dense regional state, not unlimited sparse planetary storage or coupled-density CMA.

RemapPlan uses a sorted O(Ns+Nt) overlap sweep and immutable coefficients for exactly two identified meshes, not dense interpolation. Same-grid identity may reuse state; coarsening is irreversible. Retained plans/states remain owner costs. Keys include history/material, exact mesh, forcing/boundary/time/scheme/source; known interval events are checked before a hit. Direct lossless manifests retain cohort formation/last receipt; parent IDs are lineage, not decoder dependencies. Full history requires separate receipts. [W02 science](FOUNDATIONS.md#w02-regional) owns MC-MUSCL/SSP-RK2, ALE, cohort/event/marker/topology equations. Only independent whole-region scenarios may use threads/spawn.

## Numerical cost and reusable operators


### Native periodic transport and exact totals

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


<a id="w02-regional-delivery"></a>

### Regional transport cost choices

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

[Regional equations and boundary meaning](FOUNDATIONS.md#w02-regional) own the scientific contract.


<a id="delivered-optimisations-4-5"></a>

### Cooling, rotation and flexure batches

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


### Local-law batching and fixed-length factors

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


<a id="3cr3-stress-arithmetic"></a>

### Range-safe stress arithmetic

This is a range correction, not a new physical closure. The former evaluation squared the strain invariant
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


<a id="3cr3-execution"></a>

### Local-law resource lifetime and request workers

The existing `WorkBudget` admits the source context, full input capture, held
batch outputs, final assembly, per-job native scratch, banded factor and store
operations. Admission estimates are not process-RSS limits; caller-retained
completed outputs and allocator/interpreter baselines need additional headroom.
Excess requests fail rather than changing precision, law, history or resolution.
The complete request's count bound applies before jobs are submitted. A failed
or cancelled worker aborts siblings and drains active native work before releasing
reservations; a failed request leaves the plan usable, and its executor is closed
with it. Closing a plan while an evaluation is active is refused without discarding
its live reservation. No unbounded task queue is added.

**R7 repair (1 October 2026): the executor belongs to the evaluation, not the plan.**
Before this repair the first threaded `evaluate` created an executor lazily and the
plan kept it until close. That tied the plan, the process-wide native-thread limit
and the pool's CPU slots to whichever thread made that call: other threads were
refused, and the plan could not be closed once that thread had gone. A first
threaded call that was itself refused, for example while another thread held the
native-thread lease, left an executor that had never started, and every later
threaded call on that plan was refused as well. Now each threaded evaluation
creates, drives and closes its own executor on the calling thread. An idle plan
holds no worker pool, CPU slot or native-thread limit and may be closed from any
thread; a close is refused only while an evaluation is active. Any thread may make
a threaded evaluation, one at a time: an overlapping call on the same plan is
refused, as before, not queued, and this adds no wider thread-safety guarantee.
While another live thread holds a native-thread lease, or the calling thread holds one
with a different inner-thread count, the evaluation raises the executor's existing
`TectonicsError` before any job is submitted, releases its reservation and leaves
the plan usable. So does an evaluation whose pool would exceed the CPU slots left
by executor pools the calling thread already holds.
The accepted cost is that the worker pool is rebuilt, and the
native-thread limit set and restored, for every threaded evaluation; no timing of
that cost is recorded here. The normal serial route creates no executor and is
unaffected. `execution_statistics` is `None` until the first threaded evaluation
and then describes the last one only, including one that failed or was cancelled
after its executor started: its job counts and executor peak are no longer totals
over the plan's lifetime, and its shared-budget entry is read when the property is
read. In a run of `check_constitutive_r3.py` made after this repair, the
thread-mode "reused" calls are repeat calls on one prepared plan, each building and
closing its own executor; the timings recorded for this section were taken while
the plan kept one pool across those calls, and are not rewritten and were not
re-measured here. Scientific outputs are unchanged. The package identity, and with
it every plan and result identity, changes as it does for any source edit.

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


<a id="3cr4-1-execution"></a>

### Constant-viscosity matrix-free mechanics


PreparedStokes2D fixes grid/law/scales/gauge/policy. Matrix-free MINRES uses retained DST-I/DCT-II spectra as an exact discrete separable velocity inverse only for the uniform constant-viscosity rectangular free-slip problem. Explicit small direct LU independently assembles Kronecker/incidence stencils; failed MINRES never falls back. [R4 science](TECTONICS_PLAN.md) owns collocation, equations, pressure/force scaling and independent acceptance.

Normal retained/scratch memory is O(N), transform work O(N log N); direct preparation additionally reserves 64×N_unknowns² bytes for conservative fill/work. Existing solve allowance is 768 bytes/unknown including conversion buffers. FFT workers/linked BLAS lease are one. One driving thread owns solve/close while another may signal cancellation; native work finishes before release and cancelled calls leave plans usable. Unknown/direct-size/iteration bounds are request limits, not product scale caps. Caller outputs/native/interpreter memory need separate headroom.

### SI publication arithmetic and independent gates

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


<a id="3cr4-3-execution"></a>

### Changing-coefficient operators and factors


Native stress/gradient/divergence actions retain sparse derivative topology; current centre/vertex viscosity fills the ILU velocity block. Bounded restarted GMRES uses a nonsymmetric block-triangular inverse and projected local -2×eta_cell inverse Schur action, mean/gauge separate; MINRES is unsuitable. No dense inverse/whole saddle matrix is normal. Explicit independent small direct LU may win small cases while scaling worse in RAM. [R4.3 science](TECTONICS_PLAN.md) owns stress-support collocation, law/merit/true-residual and coupled account gates.

General policy: restart 60, at most 20 cycles, drop 1e-4, fill 12. Historical R4.4 explicitly uses fill 17 and 400 Picard iterations as a cost allowance, not relaxed accuracy. Exact factor hits key normalised centre/vertex viscosity bytes; changed values rebuild numeric ILU and at most one factor remains. Cold nonlinear requests have no previous-request history; previous Picard vectors may seed subsequent linear solves. Current physical operators are never replaced by lagged factors.

One thread drives/closes plans; admit derivative/factor-overlap/GMRES-basis/current+lagged material/result/diagnostic lifetimes together. Cancellation waits for native factorisation; failure publishes no result, close releases factor/derivatives/context. mechanical_mode='variable-r4.3' separates modes and unused opposite-mode policies refuse. Resource failure changes no model, precision, timestep or mesh.


<a id="3cr4-4-native-execution"></a>

### Compiled stress action

The compiled path fuses the existing variable-stress saddle
operator into `_mechanics_native.stress_saddle`. Only prepared GMRES selects this
path; the separately selected direct reference and the NumPy operator/residual
expressions are unchanged. It uses the existing pinned Numba dependency with
`fastmath=False`, `cache=False`, no parallel loops and no parallel reduction.
Each call allocates three local stress arrays and a fresh binary64 result vector.
There is no persistent shared scratch and no returned-buffer alias: SciPy may keep
or mutate old matvec outputs. Input vector and current centre/vertex viscosities
are read-only by contract. Existing conservative per-solve scratch admission is
retained, not raised. Compiler/interpreter memory still requires external headroom.

A tiny declared signature is compiled during prepared-mechanics construction.
First-process compilation and preparation must be recorded separately from warm
accepted-step measurements. Disabled JIT or failed compilation is refused, not
silently routed through a different algorithm. Cancellation is checked around
preparation and each existing operator callback; native compilation/application
may finish before a pending cancellation is observed. No hard wall-time limit is
claimed. The general single-driving-thread prepared-plan rule remains unchanged.

ExecutionContext's existing `numba` route records the selected Numba/LLVM binary
runtime and the new native callable/options; all existing per-operation checks
remain. No source inventory caching optimisation or skipped verification is part
of this task. Exact unchanged-viscosity factor reuse, changed-viscosity rebuild,
GMRES policy, true residual checks and cold independent nonlinear requests remain
as before. Performance acceptance uses process-isolated dev32/dev33 comparisons
of identical explicit physical inputs and solver policies. Whole accepted steps
and developed endpoint solves are measured separately from bare operator calls.
Neither a microbenchmark speedup nor a short probe is a full campaign forecast.


<a id="3cr4-4-sparse-template-execution"></a>

### Fixed sparse structure

Prepared GMRES mechanics owns an immutable geometry-only CSC template for the velocity
block. Preparation constructs fixed CSC indices/indptr plus ordered contribution tables. At
each new viscosity field, the compiled fill routine reads the current centre/vertex viscosity
and writes a fresh numerical data vector; the resulting CSC matrix uses the fixed structure.
No viscosity value or factor is retained by the template. Existing exact coefficient-keyed ILU
reuse remains unchanged: changed viscosity still rebuilds the factor.

The explicit direct reference does not allocate/use the template and keeps the predecessor
SciPy sparse expression. This preserves an independent construction route. Source/native
identity includes the new fill callable/options. Template tables are read-only, and factor
construction cannot mutate them. Numerical data/results are fresh per request.

The retained template is admitted at `768 * nx * nz + 8` bytes; a conservative transient
build allowance is separately reserved while constructing it. If actual retained bytes exceed
the bound, preparation refuses. This is WorkBudget admission, not total-process RSS. The
extra one-time preparation cost is measured separately from warm per-step timings.

The first prototype, which precomputed algebraically equivalent coefficient products, was
rejected after round-off differences amplified in the nonlinear yielding trajectory. The
retained implementation preserves dev35 operation association. Tests cover exact sparse-value
reproduction, fresh/no-alias data, immutable viscosity-independent tables, factor rebuilds on
changed viscosity, direct-route independence, budget refusal/release and source-callable
invalidation.


<a id="3cr4-4-intra-step-guess-execution"></a>

### Explicit intra-step starting data

General coupling and the
R4.4 driver retain cold `zero-rate` defaults. New runs can explicitly select
`--nonlinear-start rk-stage0`; that value enters the frozen run configuration and
coupling plan identity. Resumption refuses resupplied/changed starting policy.
The trajectory auditor checks the new per-stage links and agrees with each saved
state's policy/ledger; it does not infer policy from low iteration counts.

`NonlinearStokesGuess` owns immutable binary64 SI u/w/p bytes, a canonical bound
descriptor and its own content identity. It is constructed from a current typed
mechanical solution, or restored from its own complete saved descriptor/arrays.
No recursive trajectory or previous solution is needed to decode it. It is NOT
an accepted answer for another force/temperature. Solve input validation requires
matching current plan/source, box, scales, rheology and epoch, and a nonfuture
seed time. Normalisation uses the NEW force scale; current-zero forcing starts
at zero. The current constitutive law is evaluated afresh from the seed velocity.
Changed coefficients still rebuild the exact-key numerical factor. Every existing
source and convergence check remains active. No automatic cold retry follows a warm failure; unsupported BF warm-start use refuses.

During a coupled step the stage-0 solution and its three-field guess are local
variables. Their extra live memory and publication copies are conservatively
admitted in the existing parent WorkBudget; the original memory ceiling is not
raised. No starting-field reference is retained on the prepared plan across steps,
including failed/cancelled calls. Caller-retained results or exception tracebacks
need their own headroom. The retained mechanics contains only the existing one numerical
factor, NOT a hidden last-velocity guess. Standalone caller-retained guesses need
caller headroom, like retained solutions. Memory refusal remains MemoryLimitError,
not an error reclassified as invalid physics. Compiler/interpreter/native allocator
memory is still external headroom, not covered by a claim of OS RSS limiting.

The accepted physical fields and stage identities fully determine future steps.
A fresh process reconstructs stage 0 cold and then stage 1 from that stage-0 result;
there is no extra numerical history to serialise into the two-field checkpoint.
The final diagnostic endpoint remains independently cold-solved. Neither an RK
stage nor a previous endpoint is relabelled as the next solved flow.

Performance comparisons alternate cold/warm order across repeated serial runs,
keep exact inputs/precision/tolerances/fill/timestep fixed, and report preparation
and first calls separately from retained-plan operations. Compare actual complete
steps as well as iteration counts, and include a pristine dev33 cold baseline so
new validation/provenance overhead is not concealed by same-version comparisons.
Do not multiply this speedup by old measured gains to forecast an unrun campaign.


<a id="3cr4-4-cross-step-start-execution"></a>

### Checkpoint-owned cross-step seeds

The opt-in `previous-stage1` mode extends the existing typed `NonlinearStokesGuess`
and storage path, not a new scheduler or persistence engine. The accepted state owns
one immutable u/w/p seed from its solved second stage. `state.next_initial_guess`
is read-only; `state.array_names` includes the three `next_guess_*` arrays only on
v2 cross-step endpoints. Stage-0 data and full stage results do not accumulate across
steps. The old v1 numerical fields and default semantics remain supported.

The core step admits an additional `1024*cells + 524288` bytes while capturing the
second full result, immutable seed and successor state. State capture adds
`128*cells + 262144` bytes. Existing save/decode admission uses the expanded `nbytes`;
all arrays/metadata share the existing snapshot transaction and checksum machinery.
Caller-retained outputs need separate headroom. Admitted memory is not a process-RSS
cap; Python/compiler/native/database/exception objects still need external headroom.
The benchmark WorkBudget is not increased to accommodate starting data.

The input guess is read only from the explicit accepted state. Both new physical
operators use current viscosity, and the existing exact-byte factor reuse/rebuild
rule is unchanged. Failed/cancelled steps neither publish partial starting data nor
silently cold-retry. Mechanical diagnostics do not alter future starting data.

The runner stores the policy in its immutable configuration and captures input/output
seed provenance for EVERY accepted step. The auditor checks previous-state and
previous-stage links through the complete ledger and checks all stored seed arrays
through the typed state decoder, including off-cadence saved endpoints. A complete
saved v2 state is sufficient for exact next-step reconstruction without its parents.
The first state remains an unseeded v1 initialisation; subsequent cross steps require
complete v2 data. Source/runtime/start/algorithm changes remain explicit refusals.


<a id="3cr4-4-anderson-execution"></a>

### Request-local Anderson

The opt-in `AndersonPolicy` is forwarded to the coupled plan's existing owned
mechanical plan. Both transport stages and independent cold endpoint diagnostics
use that plan, without duplicating retained ILU memory. The existing compiled
operator, fixed sparse structure and current-coefficient factor rebuilds remain
unchanged. Picard's branch and default metadata remain unchanged when acceleration
is not selected. Default starting mode remains `zero-rate`; `rk-stage0` is still a
separate explicit intra-step starting policy.

Each accelerated solve admits additional history/mixing scratch before allocation:
`8 * unknowns * (8 * (depth + 1) + 32) + 262144` bytes. At default depth five this
is 640 bytes per unknown plus 262144 bytes. It conservatively covers bounded image
and error histories, difference matrices, proposal vectors, least-squares scratch
and additional law/diagnostic work. The reservation releases on success, cancellation,
linear failure or rejected requests. Retained caller results, interpreter, compiler,
LAPACK/native allocator and database memory need external headroom; WorkBudget is
not an OS RSS cap. No runner budget is raised to accommodate this feature.

No nonlinear history is cached across requests. Mixed vectors, errors and output
buffers have private ownership. Failed proposals may keep the already-computed
Picard image, but no failed physical linear solve is retried with changed tolerances,
direct mechanics, a different timestep or a cold fallback. Native calls and SVD
remain cooperatively cancellable at their existing boundaries, not hard interruptible.

The new source module, policies, helper functions and actual least-squares callable
alias enter the existing live callable/source inventory. Verification frequency is
not reduced. Algorithm controls and safeguard counts are saved in mechanical/stage
provenance; standalone records retain per-iteration decisions. The runner, auditor
and renderer use the same declared option. Resume uses frozen policies and refuses
resupplied algorithm options; receipt/configuration/source identities remain mandatory.

New invocations opt in with `--nonlinear-solver anderson`; adding
`--nonlinear-start rk-stage0` also enables the existing intra-step guess. No old
trajectory is rebound to dev37. The dev37 selection uses the dev36 Sparse Structure patch base; original receipt/Git identities distinguish it from the separately named Sparse Layout build.


The Type-II full-vector/SVD policy uses default depth 5, singular-value cutoff 1e-10, coefficient L1 bound 10 and warmup 2. Current-merit safeguards choose acceleration or the ordinary Picard image; final acceptance still evaluates a fresh current-law Picard image. These are explicit algorithm controls, never weakened physics gates.


<a id="3cr4-4-preconditioner-reuse-execution"></a>

### Guarded approximate-factor reuse

The guarded four-use option is integrated through the existing owned
mechanics plan. Reuse never means stale equations: only the approximate velocity
ILU may lag; physical operator and pressure approximation remain current. The
factor-origin hash is never relabelled with the new viscosity. Exact-coefficient
cache hits remain allowed across calls; approximate reuse state does not.

An active Tosi-plastic request admits `64*cells + 262144 + 2048*max_picard_iterations`
additional bytes for coefficient copies, guard scratch and bounded decision records.
The existing retained factor budget and 1 GiB runner default remain unchanged.
Strain-independent cases allocate no request history. Python/compiler/native, database,
exception traceback and caller-retained result memory require separate headroom;
WorkBudget is not a hard RSS limit. Cancellation is cooperative at existing boundaries.

The numerical linear body, current-law residual checks and independent sparse-direct
route remain unchanged. A rebuild failure or GMRES failure propagates without retry.
Each request records origin hashes and deterministic guards; actual cache-hit/build
counts remain outside result identity. All request references clear in `finally`.
Source verification includes the policy/helper module and is not skipped or cached.
The analyser checks policy agreement in all recorded stages and saved state records.


Guarded reuse is Tosi-plastic only, at most four uses; rebuild when the log-viscosity change exceeds log(2) or prior iterations exceed max(40, 1.5×origin iterations). The first solve is current; operator/pressure are fixed inside each GMRES solve. Unsupported policy combinations refuse. No cross-request approximate history or retry follows failure.

### Strict final certification with adaptive intermediate accuracy


Opt-in AdaptiveInnerPolicy/--adaptive-inner bounds intermediate Tosi-plastic defect
correction, bypassing constant/Tosi-linear laws. Direct solves, non-unit relaxation,
prescribed flow and damage-dependent rheology cannot silently use it. Default
Picard/zero-rate/strict solving remains when unselected. Final current-system SI
certification, current-law nonlinear and conservation gates stay strict; entering
the strict phase clears Anderson history. Save policy and actual stage tolerances.

State restore independently binds adaptive activation to problem rheology: a
well-formed inactive summary cannot bypass a Tosi-plastic certificate. Live solver
and auditor checks alone were insufficient at the restore boundary. Non-unit SI
and endpoint-recovery regressions cover this repair. Old source bindings refuse;
final residuals receive no extra roundoff tolerance. The narrowly allowed dev41
SI representation refinement is described in the GMG/publication subsection.


### Selective GMG and strict SI publication refinement

A fixed linear geometric velocity V-cycle uses coupled stress, Galerkin coarsening,
degree-four Chebyshev pre/post smoothing and a small direct coarse solve. Transfers
retain zero normal wall velocity/free-slip tangential interpolation. Pressure,
physical equations and GMRES tolerances stay unchanged; no nested variable inner
tolerance or silent fallback is selected. Geometry transfers live on the prepared
plan; numerical hierarchies rebuild on changed coefficients unless explicit
request-local guarded reuse admits a helper. Exact hits also check helper kind;
the current physical operator/pressure remain current and each helper stays fixed
through GMRES. Retained/transient admission is conservative, not an RSS cap.

The recorded dev41 auto rule selects GMG for isotropic square power-of-two supports
>=128×128 with Tosi-linear, or Tosi-plastic plus Anderson/adaptive-inner/guarded-reuse.
Other cases retain ILU. Explicit ilu/gmg choices remain, unsupported GMG refuses.
This measured-workload heuristic is not a universal best-method guarantee. Policy,
loaded helpers and reuse method v2 enter source identity; old canonical policy or
checkpoint records are not silently upgraded. SciPy remains optional at helper
module import for reference-only contexts, while variable-mechanics preparation
requires it. A missing loaded-helper inventory entry was corrected before final
focused checks.

Only a valid adaptive strict image that loses residual margin on conversion to
and back from SI asks the existing nonlinear loop for another strict solve of the
actual returned vector. Record both attempts and clear Anderson differences.
Pre-publication invalidity, failed GMRES or nonfinite values still refuse. The
same iteration ceiling, strict residual, law, divergence, gauge and work limits
apply; the correction is neither an extra roundoff tolerance nor a general retry.

Sources actually consulted: [Clevenger/Heister](https://arxiv.org/abs/1907.06696)
for variable-viscosity hierarchy/polynomial smoothing (Atlas is assembled MAC,
not their matrix-free finite elements), [Rudi/Stadler/Ghattas](https://arxiv.org/abs/1607.03936)
for comparison-only weighted-BFBT pressure work, and [PETSc GMRES/FGMRES](https://petsc.org/release/manualpages/KSP/KSPFGMRES/)
for a fixed linear preconditioner. No new source was consulted in this consolidation.


<a id="3cr4-2-execution"></a>

<a id="3cr4-2-review-execution"></a>

### Thermal transforms and range conditioning

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

The thermal cache holds just one interval. In addition to rates and the
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


### Shared mechanics for coupled transport

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

### WP25 heat warm-start disposition

**EVALUATED — DISABLED; NO HELPER BUILT OR WIRED.** The 16 October 2026 assessment covers heat warm starts/mixed-precision certified solves under unchanged certified records, helper-only changes and first use from interval 2. It does not reopen work, compose anything into Step 10 or qualify a new numerical identity.

The inspected private_heat_forward_kernel_r13 (r12/r13 issuer kernel) runs LOW.solve, certified polygon reconstruction/precision ladder, HIGH.solve_rounded and FINISH.finish with both values. LOW/private_heat_decimal_sparse_core_r1 already uses mixed-precision refinement: binary64 SuperLU start converted to Decimal80, up to eight Decimal80 HALF_EVEN residual corrections with that factor, first iterate meeting largest-residual target accepted. HIGH/r2 uses partial-pivot MPFR512 LU and exact rational→Decimal80 conversion under the same first-acceptable-iterate rule.

That first acceptable vector is not a unique canonical solution. A prior-interval start or lower-precision HIGH factor changes the accepted Decimal80 vector; its temperature/energy/face-flux strings feed FINISH and change certified ledger values. refinements/residual_history are not themselves certified (r9 IV1 scan found neither); the incompatibility concerns accepted values, not optional diagnostic metadata. Changed geometry/conductance makes a new matrix every interval, so factors cannot carry across intervals.

A genuine W4 owner/transport/mesh probe (236 cells, 832 faces; layout g13l0; read-only hook on both solve returns) passes the same-call control. [Retained probe](../optimisation/workbench/probes/step8/claude-20261015/wp25_iteration_counts.py); original result identifiers wp25-iteration-counts-w4.json and wp25-control-w4.json are not bundled runtime evidence here.

| Solve | Corrections after start | Complete solve | Factor | L+U nonzeros |
| --- | ---: | ---: | ---: | ---: |
| LOW: binary64 LU+Decimal80 | 1 | 0.011s | SuperLU included | 11,368 |
| HIGH: MPFR512 LU | 0 | 0.96s | 0.71s | 37,157 |

Warm start can at most remove LOW's single millisecond-scale correction; HIGH accepts its first solve and warm start cannot remove its factorisation. The r9 real IV1 phase record heat-original-connected-20261013-r9.json covers 2357.8→5493.6 s (~3,136 s): LOW-predictor 133 s (~4%, including geometry preparation and exact E/C ledger), certified polygon reconstruction ~2,330 s (~74%), conservative finish 288 s, native projection 279 s. These phase figures identify where time went; no RAM bound or new whole-interval speed result is inferred.

An identity-preserving faster route would have to reproduce the reference iterate exactly, rigorously enclose MPFR512 rounding, prove each Decimal80 rounding and fall back to reference otherwise. The proposed C+dtL M-matrix structure may support a cheap inverse bound, but this remains a new certified route with new source identity and review, not a built variant or proven speed gain.

An **identity-changing later option**, requiring the owner's separate decision, is to define LOW/HIGH output as the correctly rounded solution with rigorous enclosure, then admit faster factorisations. Reconsider only if HIGH factor cost grows materially at IV2/IV3 (about 16× IV1 cells by IV3 was the projected scale). The old record proposed persisting/re-measuring factor diagnostics at IV2; it did not do so and this consolidation does not authorise it. The largest observed cost was polygon reconstruction, outside WP25: exact-input certified-fact reuse or the WP24 compile gate were possible separately owned candidates, not adopted changes. WP11's distinct feasibility decision above remains NOT BUILT.


## Memory, storage and recovery

<a id="storage-contract"></a>

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


<a id="storage-profiles-delivery"></a>

### Lossless profiles, references and transactional loading

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


<a id="3cr4-4-execution"></a>

### Accepted schedules, publication and audit

The existing thermal transforms, fused conservative transport, bounded restarted
GMRES, one coefficient-keyed ILU factor, source identity, thread leases, WorkBudget
and ArrayStore are reused. The physical equations and convergence gates are unchanged.
The stress operator avoids per-matvec padding allocations and its weighted sparse
velocity matrix is assembled by exact row scaling of the fixed derivatives. New R4.4
runs explicitly use ILU fill factor 17; the general R4.3 policy default stays 12.
Sampling re-solves the final physical endpoint using the coupled plan's same owned
prepared mechanics object; it does **not** retain or reuse a stale RK-stage flow.
This removes the formerly redundant second retained factor. Independent case processes
may run concurrently with a declared native-thread budget. A single globally coupled
mechanical system is never split into unrelated local solves.

`run_convection_r4_4.py` has an explicit finite overall schedule and bounded
per-invocation segments. No long run is dependent on an unsaved conversational
claim. Source files, driver bytes, case specification, runtime, material, grid,
forcing, step size and solver policies are bound to the run configuration. The
default 400 Picard-iteration allowance is an explicitly different **cost limit**,
not a tolerance relaxation. A failed Courant or nonlinear gate stops that run;
the driver does not silently change the timestep, law, mesh or numerical route.

Each complete accepted step records input time, dt, state identity, original
heat/material/Courant balances and both mechanical stages' identities, convergence
diagnostics and iteration counts. Full fields are saved at declared checkpoints;
scalar samples have a separate fixed cadence. Fixed-step continuation includes
the future schedule, not just a two-field snapshot. Increasing a completed run's
maximum step count or modifying its schedule is not an implicit resume operation.
A new schedule requires an explicitly separate, scientifically justified run.

The existing transactional state store commits first. Complete JSON receipts are
flushed and exclusively hard-linked into place with a parent-receipt hash. Existing
outputs are not overwritten. Unreceipted orphan states are not silently promoted.
A single exclusive run claim prevents concurrent writers. A hard-kill claim remains
for deliberate investigation; the program does not guess whether another process
is dead and remove its ownership record. Cooperative SIGINT/SIGTERM/time bounds
save only the last fully accepted state, then close plans and storage normally.
These are cooperative bounds, not hard interruption of a native factorisation.

Same-source fresh-process and relocated-source/store-copy continuations must have
exact final state identities and field arrays matching an uninterrupted run.
Changing actual source, specification or schedule is refused. The new mid-second-RK
cancellation test verifies that recovery does not advance time or preserve a
partially accepted temperature, and that the next uncancelled step is exactly
reproducible. The broader old resource drill is retained but is not renamed as a
full long-run R4.4 campaign test.

The auditor refuses live runs, missing or reordered receipt/step chains, changed
case/source identities, sample/state/clock disagreement and changed source/receipts
during the audit. It reopens and decodes each referenced stored checkpoint. Its
recent-field retention has an explicit 1 GiB array envelope; it does not retain
the entire spin-up in RAM. Periodic checks require real field cadence as well as
scalar cadence, and report insufficient coverage rather than interpolating an
underresolved trajectory into a false pass.


### Bounded R4.4 run and campaign protocol


Use the substantive [bounded R4.4 operations](../README.md#bounded-r44-studies) for run/resume, trajectory audit, visual output and study-axis/campaign manifests, including incomplete/refusal exits. These commands require their existing authority and do not lift held R4.4 work.

### Typed numerical snapshots

The existing lossless Zstd/Blosc2 store remains the only persistent engine. Each
endpoint contains current T/C, problem, frame/epoch, source/policy, time/index and
last-step records. This supports exact same-source continuation without replaying
a parent delta chain. Future source/velocity input remains explicit. A decoded
historical record is not relabelled as meeting a newer method's acceptance.
Routine logs stay local; source-bound structured results include real failures.

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


### Analysis preflight and bounded retained diagnostics

Use campaign `--preflight` before expensive archive reads or extending a proposed
benchmark schedule. It reports known source/control/reference and maturity-schedule
blockers without reading arrays or solving physics. It is not authentication or
acceptance. Actual acceptance still reads and verifies the original evidence.
The existing within-invocation scalar-analysis cache remains; periodic comparisons
retain only three bounded final-cycle sidecars (64 MiB per run). This bounds sidecar storage, not process RSS, and does not duplicate the archive. Repeated runs may require reanalysis
when their sidecars are no longer held; this deliberately bounds additional memory.

The frozen-field resolution probe separates mechanical resolution, surface sampling
and inherited temperature error. Its first mesh can include compilation, so its
mesh timings must not be presented as comparative speed gains. Short evolved runs
likewise do not establish mature accuracy. Numerical values, elapsed times and
retained evidence identifiers are in
[dev40 evidence](#adaptive-accuracy-and-assessment-limits).

One shared-workflow candidate remains unimplemented: separate reviewed physics
dependency identities from assessment/report identities while retaining complete
provenance. Current package-wide source hashing deliberately invalidates reuse
even after assessment-only edits. Any separation needs an explicit dependency
closure and recovery tests; ignoring hashes or silently migrating existing runs
is not an acceptable shortcut. No percentage saving is inferred for this candidate.


<a id="volumetric-storage"></a>

### Volumetric representation

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
finite memory budget, and restart under the declared source/runtime identity.
Changed sources must refuse old checkpoint reuse unless a separately admitted
successor defines and verifies the migration. Require conservative material remap
and cross-chunk results matching a monolithic reference under the declared policy.
Only then choose chunk dimensions, codec or sparse hierarchy. The current small
1D reference kernels are intentionally storage-agnostic, not the permanent world
representation and not an obstacle to 3D development.

## Retained measurements and limits

These are bounded historical observations under the exact source, platform, cache state and instrumentation described. They do not qualify a later source/runtime. WorkBudget is estimated admission; tracemalloc and sampled process memory have the stated blind spots. Preserve elapsed time, RAM and negative results together. Ratios across separate workloads/versions must not be added or multiplied into a forecast. Historical test counts identify their recorded campaign; passing them is not physical acceptance.


<a id="w11-module-wide-linked-workflow-pass--24-september-2026"></a>

### Linked module-wide W11 study

The historical pass assesses every existing tectonics family and its implemented
connections, including retained cross-module producers/consumers. It changes four
production files, not physical equations, meshes, numerical tolerances or the
256-step ceiling. The pre-change source copy matched commit
`8f6ba86724d775d5c840b79e47f4d68620b4e3ea` and all 124 package-source file hashes.
Old W10/W11 receipts remain historical after the earlier remap correction; none
was repinned or treated as a current passing campaign.

#### Implemented improvements

1. **Cheaper exact source verification, throughout the package.** Every source
   byte and current file membership is still read on every check. Two fresh
   non-following file-stat calls replace four overlapping metadata queries;
   relative names use already-parsed path components. Opened-file identity is
   now also compared with the pre-open entry. Same-size/same-mtime mutations,
   growth, replacement and links still refuse. No cached timestamp acceptance.
2. **Reuse at the actual W01/W02 → geology → W07 connection.** Steady, thermal
   and surface workflows retain a correctly backend-matched geological execution
   context instead of rebuilding it at every boundary. They still verify the
   complete geological payload and live source/callable identities on every use.
   The separate reference-backend context has an explicit 4 MiB reservation;
   closure and constructor failure release resources. Standalone calls retain
   fresh verification. There is no reuse of a different backend's identity.
3. **Remove a checkpoint-write copy.** Contiguous arrays use a flat view before
   the existing bounded chunk capture; noncontiguous arrays keep their prior
   bounded path. Detached immutable bytes, endianness, compression, chunk IDs,
   corruption checks and transaction publication are unchanged.

The pass also fixed a **measurement reporter bug**: unittest can report a skipped
subtest without starting a separate test. That previously turned the Windows
symlink-permission skip into a KeyError. Skips now remain explicit, parent rows
disclose skipped subtests, and class-fixture errors/subtest errors are recorded
correctly. This does not relax the zero-skip acceptance rules in W10 or old W11.

#### Coverage and decisions

| Existing family/link assessed | Decision/evidence in this pass |
| --- | --- |
| Coordinates, rotations, clocks, topology, spherical boundaries and spatial indices | Retain existing immutable/indexed/batched algorithms; foundation guards and actual construction dependencies covered. |
| W01 described geology, point/cell/spherical sampling and material inventories | Inspect existing batched lookups, bounded thermal reuse and shared footprints; source verification is the measured common bottleneck. No geometry shortcut. |
| W01 motion → regional forcing → W02 initial material | Time the real linked construction and compare complete outputs, including face/owner/velocity fields. |
| W02 transport, nonuniform remap, moving grid, markers, topology and restoration | Time nonzero two-step continuation; check combined regrid/motion/birth/split/merge/restore and cache invalidation. Retain the corrected joint reconstruction and conservative native methods. |
| W03 cooling → density/load → compaction/rebound | Time initialisation and three changed steps; compare all state, material and compaction arrays/accounts. Retain grouped thermal work and prepared backends. |
| W03 → W04 periodic/finite/exterior/variable-rigidity support | Time changed/identical projections; check cache/source/halo/factor ownership. Retain FFT, analytic finite response and banded factors. |
| W05 listric motion → load → support → history | Time complete three-output 3,200-cell sequence; material, exchange and support fields agree. |
| W06 birth/history/inherited margins → cooling → water/support accounts | Time all three routes, four outputs, including 4,000-cell ocean cases; scientific fields and declared export/thermal metadata agree. |
| W07 mechanics, heterogeneous/nonlinear material laws, thermal/material intervals, dry strength and free surface | Review solver/factor/current-law/coupling contracts; implement and test geological verifier ownership. Three assembled routes and recovery pass. No new solver or constitutive approximation. |
| W08 shortening, transform/oblique, bends/stepovers and straight-fault slip | Retain exact/ordered motion and finite projection algorithms. Exercise the supported joined affine route; do not pretend it includes the separate non-affine/fault-slip routes. |
| W08 prescribed slab/wedge, thermal projection and material retirement | Review factor/projection lifetime and accepted refinement choices; retain the time-first operator policy. Material retirement exercised in the joined workflow; expensive coupled campaign not repeated. |
| W08 finite melting/transfer/emplacement → joined regimes and cessation | Inspect the three component contracts; measure the five-interval joined workflow, including inventories, regional fields, footprints and deformation. |
| Underthrust → host/receivers; evolving W03/W04 and regional inputs | Measure all three supported adapters; keep complete interfaces, explicit force/load owners and analytic mechanical controls. |
| Dated histories, all supported save/restore links | Shared storage optimisation applies without schema changes; recovery validates the accepted prefix without replaying completed physics. Relevant W01/W03/W07 recovery and corruption checks covered. |
| Retained W09 drainage/water/erosion/hillslope boundary | Inspect existing contracts; two changed-bed/finite-stock guards pass. Missing deposition and full consumer bridges remain with their individual modules, not invented here. |
| Shared caching, immutable ownership, compression, scheduling and resource control | Retain exact invalidation, same-request coordination and lossless deduplication; measure contiguous writes and current automatic parallel choices. |

This extends PF01–PF26 consideration across the implemented workflows: PF01/03
benefit from verification/preparation reuse, PF06/07/17 from the storage change,
and PF09–11 retain measured independent-work policies. Existing indexing, factors,
compiled kernels, history deduplication and bounded queues remain appropriate.
No measured case justified a new GPU/MPI backend, asynchronous write queue,
out-of-core solver, altered timestep, mixed precision, surrogate, reduced physics
or parallel-in-time path. Existing nonuniform/remap support is retained; new
adaptive/spherical stress meshes and distributed flux operators still require
their own numerical development, not an execution-only optimisation label.

#### Matched measurements

Windows 11, Python 3.12.14, NumPy 2.4.6, SciPy 1.17.1; same existing environment,
no installation. Three alternating baseline/candidate pairs per workflow, five
for storage. Timed regions include the stated setup, checks, complete result
construction and owner closure; imports/untimed fixture work are excluded.
These are separate workloads, **not additive or multiplicative savings**.

| Complete timed workload | Before s | After s | Saved s | Saved time |
| --- | ---: | ---: | ---: | ---: |
| W01 → W02 initialisation | 1.237829 | 0.928682 | 0.309147 | 24.97% |
| W02 moving setup + continuation | 1.155571 | 0.900521 | 0.255051 | 22.07% |
| W03 initialisation | 0.741306 | 0.528854 | 0.212451 | 28.66% |
| W03 three changes, fresh preparation | 3.450840 | 2.737592 | 0.713248 | 20.67% |
| W03 three changes, shared preparation | 1.661145 | 1.091263 | 0.569881 | 34.31% |
| W04 three changes, fresh preparation | 2.678668 | 1.941961 | 0.736707 | 27.50% |
| W04 three changes, shared preparation | 1.539129 | 1.072666 | 0.466463 | 30.31% |
| W04 three identical requests, shared preparation | 1.467902 | 0.997590 | 0.470311 | 32.04% |
| W05 three complete outputs | 1.307060 | 0.970070 | 0.336989 | 25.78% |
| W06 constant spreading | 1.149944 | 0.850411 | 0.299533 | 26.05% |
| W06 changing history | 1.089366 | 0.769171 | 0.320195 | 29.39% |
| W06 inherited margin | 1.170287 | 0.776990 | 0.393298 | 33.61% |
| W08 five joined intervals | 0.970932 | 0.705046 | 0.265885 | 27.38% |
| Underthrust three outputs | 0.501860 | 0.401237 | 0.100624 | 20.05% |
| Evolving regional mechanics | 0.722093 | 0.500733 | 0.221360 | 30.66% |
| Evolving elastic support | 3.299592 | 2.387790 | 0.911802 | 27.63% |
| W07 steady: additional caller-context optimisation | 2.841434 | 1.901576 | 0.939858 | 33.08% |
| W07 thermal: additional caller-context optimisation | 3.615335 | 2.270506 | 1.344829 | 37.20% |
| W07 surface: additional caller-context optimisation | 3.327096 | 2.157326 | 1.169770 | 35.16% |
| 10 MiB contiguous checkpoint, raw profile | 0.042769 | 0.035934 | 0.006835 | 15.98% |
| 10 MiB contiguous checkpoint, default Zstd | 0.043690 | 0.040015 | 0.003675 | 8.41% |

[Early evidence](../evidence/w11-module-wide-early.json): 2,154 saved arrays,
complete scientific metadata and within-version result identities agree. Across
source revisions, only explicitly identified execution-derived IDs are mapped;
physical/material/owner IDs are retained. An omitted intermediate W02 parent ID
was corrected in the comparator against saved outputs, without repeating timings.
[Later summary](../evidence/w11-module-wide-late.json): all 48 timed sequences
agree on declared complete scientific arrays and explicit physical metadata;
this is not a full metadata/execution-ID equality claim. Large raw signatures
remain in the hash-bound local receipt. [W07 evidence](../evidence/w11-module-wide-w07.json)
instead compares the exact archived previous caller with the new caller, both
using the same current scientific dependencies: **all IDs, descriptors and array
bytes agree without filtering**. Thus its percentages isolate the caller-context
change, not the combined source-reader gain. The extra retained context is 4 MiB
of explicit accounting, not measured RSS; all owners close without reservations.

[Storage/execution evidence](../evidence/w11-module-wide-storage.json): every
paired SQLite chunk row and restored byte agrees. Encoded size is unchanged.
Strided controls use the unchanged path and show no attributable saving. Existing
automatic execution, not a new improvement, still saves 20.30% for cooling and
28.09% for flexure at 262,144 elements; rotations remain faster serial. Keep the
existing threshold rather than retuning it from small/noisy cases on one host.


### W11 scope, reporter failure and reproduction

278 distinct checks pass after the reporting repair; three environmental skips
remain explicit (source-link privilege, storage-link privilege and the existing
root tooling skip). Groups: shared guards **142 pass/1 skip**, storage/execution
**76 pass/1 skip**, W07/geology/retained W09 **30 pass**, static safety **30 pass/1
skip**, plus 13 source maps/41 paths. The shared first run had 139 passes and the
reporter error in 67.442 s; only that affected method and three new reporter tests
were rerun (3 pass/1 privilege skip, 0.311 s). The initial reporter regression
also caught the missing parent-subtest status and was corrected. Both failed
receipts remain local evidence; successful physics was not replayed. No full
3,565-test suite, Linux pass or multi-hour campaign is claimed by this pass.

Reproducible runners live in `tectonics/tools/`: `check_w11_guards.py`,
`benchmark_w11_early.py`, `benchmark_w11_late.py` with `w11_late_profile.py`,
`benchmark_w11_w07.py`, and `benchmark_w11_storage.py`. Use `--help`, the same
declared environment, new output destinations and a separate baseline source
checkout. `--baseline`/`--current`/`--baseline-source` name the directory containing
`atlas_tectonics`; the storage runner instead takes the baseline `storage.py`.
The W07 runner requires its recorded old caller and current compatible fixture.
Portable path/report guards were packaged after measurement, not called a new
simulation. The older `check_w11.py` deliberately still refuses stale W10/source
bindings; it is not silently redirected to claim a new physical acceptance.

Methods/software consulted: [PETSc profiling](https://petsc.org/release/manual/profiling/)
for application/setup costs, [Python 3.12 file status](https://docs.python.org/3.12/library/os.html#os.lstat)
and [regular-file mode checks](https://docs.python.org/3.12/library/stat.html#stat.S_ISREG),
plus [NumPy reshape](https://numpy.org/doc/stable/reference/generated/numpy.reshape.html)
and [flat iteration](https://numpy.org/doc/stable/reference/generated/numpy.ndarray.flat.html).
No new physical method or new physical-paper claim was introduced. Delivery and continuation are owned by [current state](../../docs/CURRENT_STATE.md); held R4.4 boundaries remain unchanged. This closes this implemented-workflow optimisation pass,
not every conceivable future optimisation or a planetary-scale forecast.


### Regional prepared-owner scale study

This is the retained scoped decision for the supported regional
mechanical route, not a replacement for the historical PF/PT planning definitions
below. No production equation, backend, tolerance, timestep or checkpoint identity
changes. W10's bounded evidence is retained; its unresolved physical claims remain.

Result: [bounded W11 assessment](../evidence/w11-assessment-r1.json)
`PASS_BOUNDED_W11`. Fourteen selected execution safeguards pass in 9.596 s,
with zero skips; the receipt including source/evidence checks takes 10.666212 s.
The [recorded scale study](../evidence/w11-scale-r2.json) retains all 90 computed
outputs' checks and exact within-case parity across five pairs at each size.

| Regional grid | Fresh-owner median, three outputs | Prepared median, three outputs | Saved seconds | Saved time |
| --- | ---: | ---: | ---: | ---: |
| 8x8 | 0.9259151 | 0.6446081 | 0.2813070 | 30.3815% |
| 16x16 | 0.8890599 | 0.7019060 | 0.1871539 | 21.0508% |
| 24x24 | 0.9969288 | 0.7118593 | 0.2850695 | 28.5948% |

All observed cold/prepared ranges are disjoint. The prepared execution path is
retained. These quantify **existing** reuse at the selected sizes, not a new
additional speed multiplier. Small-case costs include substantial fixed overhead;
the non-monotonic cold medians are not fitted into a planetary scaling law.
Whole study time is 25.417801 s before writing and 25.430221 s including writing
(the latter is the retained command completion output). Scientific imports take
0.711901 s. Peak numerical accounting is 37,693,684 bytes; observed Windows
process-lifetime peak RSS is 123,183,104 bytes. Final reservations are zero.
The detailed scale receipt is 433,500 bytes; no scratch/history store is created.
Four scale-harness tests pass in 0.104 s, three assessment-guard tests in 0.845 s.
Required static checks pass (13 maps/41 paths; 31 safety tests, one existing
environmental skip, 0.114 s). No new Linux run or whole-world claim is made.

`tools/check_w11_scale.py` measures existing preparation reuse at 8x8, 16x16 and
24x24 grids. Each trial computes three genuinely changed viscosity/boundary
requests, not three cached answers. Five alternating cold/prepared pairs per size
compare complete wrapper/mechanics IDs, descriptors, diagnostics and every field.
All numerical gates remain active. An independent affine-shear solution checks
velocity and stress at every size. This provides scale transfer for this exact
steady synthetic problem, not arbitrary heterogeneous geological histories.

The execution card is embedded in the scale receipt. It declares one native thread,
128 MiB shared numerical accounting, a 120-second cooperative deadline, bounded
evidence storage, no scratch/checkpoint stores and no processes/device work.
Whole-process RSS is measured separately: Python and native libraries are not
magically included in the 128 MiB numerical reservation. Cold means fresh owner
per output in the same process; it does not mean cold OS disk/library caches.
Construction, deferred setup, live verification, solves, oracle checks, complete
hashes and close are in the timed trials. Imports, fixture construction, inventory
checks and report writing are reported separately. Medians and raw ranges are
retained; these ratios must not be multiplied into older claimed savings.

The first study completed its solves but failed to save its detailed receipt due
to the shell's destination permissions. `evidence/w11-scale-r1.json` preserves the
failure and surviving stdout summaries; it is NOT full passing evidence. The
runner now claims its exclusive output writer before scientific work. Existing
reports refuse, incomplete output remains visibly incomplete, and one justified
repeat supplies `evidence/w11-scale-r2.json`. No numerical retry/tolerance change.

`tools/check_w11.py --report evidence/w11-assessment-NEW.json` authenticates that
scale receipt, reuses W10's unchanged recorded files and exact production
membership, and runs 14 explicitly selected execution/storage safeguards. Added
W11-only source files receive a separate current inventory; old evidence is never
repinned. Run both tools from the repository root with the `tectonics/` prefix
on tool and evidence paths. No automatic benchmark replay or whole suite occurs.


### W11 candidate decisions and check coverage

#### Scoped PF decisions

| PF family | Decision and reason |
| --- | --- |
| PF01, PF03 | Retain bounded verified preparation/result reuse; changed outputs are measured separately from identical hits. |
| PF02 | Existing indexing retained; no new pruning without a measured bottleneck and exhaustive reference. |
| PF04, PF19 | Measure existing prepared structures and valid factor reuse; changed coefficients still receive current solves/residual gates. Held R4.4 algorithms excluded. |
| PF05, PF17, PF18 | Existing lossless, deduplicated recovery retained; applicable Step 4 evidence reused, not a new storage-speed claim. |
| PF06, PF07 | Existing array layout and immutable ownership retained; no speculative fusion or copy removal. |
| PF08 | Existing compiled/library kernels retained; no new hot-loop implementation justified by this study. |
| PF09-PF11 | Existing bounded independent-work machinery retained; coupled regional solves are not independent spatial tiles. No new parallel speed claim. |
| PF12, PF13 | GPU/MPI deferred: no device-transfer comparison or distributed flux/operator proof. |
| PF14, PF15 | Overlap, affinity and NUMA tuning deferred: no identified idle/transfer/locality bottleneck. |
| PF16 | Finite sparse-solver admission retained; out-of-core regional solving not established. |
| PF20, PF21 | Existing numerical methods and interval semantics retained; no equation/timestep shortcut. |
| PF22 | Fixed-grid scale experiment only; adaptive/coarse-fine transfer deferred pending its own conservative operator/accuracy case. |
| PF23-PF25 | Mixed precision, surrogates and reduced physics deferred: no separate error/applicability case. |
| PF26 | Parallel-in-time remains deferred; prescribed steady requests do not establish sequential-history parallelism. |

These are evaluated scoped choices across all 26 families, not 26 new features
or a claim that every possible optimisation has been exhausted.

#### Scoped PT coverage

The exact methods in `tools/check_w11.py` cover selected threaded kernel parity
(PT01), source/parameter/backend invalidation (PT03/PT13), four-thread same-key
coalescing (PT04), detached immutable inputs/outputs (PT05), queue/shared-memory
pressure (PT06), changed-versus-fresh solves and valid factor retention (PT08),
injected cancellation/write failures (PT09), corrupt/missing history and backup
independence after removal of a temporary source database (PT10), and named
lossless encoding/chunk profiles (PT11). The new scale experiment supplies PT14
for its declared workload. No individual PT family is claimed universally closed.

This selection does not cover every worker/order/random-stream permutation (PT02),
distributed coupled-region flux exchange (PT07), or a new numerical/precision/mesh
scheme (PT12). It also omits actual killed-worker/late-result races, the full
compiler/library/start-method matrix, exhaustive cache-input mutations, lagged
preconditioners, and all possible compression/write orders. Those are not silently
accepted because a nearby test passed. No relevant new backend is enabled here.

#### Methods consulted

[PETSc profiling documentation](https://petsc.org/release/manual/profiling/)
informs the separate setup/solve stages and inclusion of application-level costs;
verbose tracing is not enabled during the timed trials. PETSc is not installed.
[SciPy's SuperLU interface](https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.linalg.splu.html)
documents the factor object and subsequent solve calls; actual operator ownership
and invalidation are checked in Atlas. Documentation is methodological, not proof
of compatibility with a different library version. The recorded run uses the
existing pinned local environment, not the online documentation's latest release.


### Broader source-identity coverage cost

Measured on Windows (CPython 3.12.14; four alternating fresh-process runs; medians; SciPy): first context 0.310→0.505 s (+0.195 s, mostly added one-time imports including Numba); further contexts 0.120→0.137 s (+14%); verify 0.0203→0.0221 s; bound callables 5,542→6,253. Single reference runs: 0.301→0.494 s cold, 0.106→0.120 s warm; Numba 0.505→0.581 s cold, 0.191→0.207 s warm. These measured increases accompany broader identity coverage; no receipt was repinned.


<a id="obtained-dev33-verification-and-matched-measurements"></a>

### Compiled action: dev32→dev33

The final frozen source passes **2,244 tests (26 new)**, with zero failures,
errors or skips and `PASS_BOUNDED_CURRENT_PLATFORM`. The 171-file executable/
case/test/tool inventory is unchanged before and after the run. Separate matched
comparisons use five repetitions per workload, identical explicit inputs, one
native thread and serial version-isolated processes. Across all seven workloads, the compared saved
field/operator arrays are bit-for-bit equal on the exercised runtime, including
the developed transient nonlinear fixture. This is not a universal bit-identity
claim across other platforms or every admitted input.

| Workload | dev32 seconds | dev33 seconds | Speedup | Less time |
|---|---:|---:|---:|---:|
| Initial case 1, 16×16 timestep | 0.077054 | 0.072601 | 1.061× | 5.8% |
| Initial case 1, 64×64 timestep | 0.234096 | 0.227106 | 1.031× | 3.0% |
| Initial case 1, 128×128 timestep | 1.281421 | 1.255447 | 1.021× | 2.0% |
| Developed case 2, 16×16 endpoint solve | 0.772995 | 0.628282 | 1.230× | 18.7% |
| Developed case 2, 16×16 timestep | 1.572853 | 1.211589 | 1.298× | 23.0% |

These are prepared-operation medians, not startup-inclusive campaign timings.
Ranges and preparation/first-call costs are retained in
`../evidence/3cr4-4-dev33-measurements.json`. Small initial-grid gains have overlapping
repeat ranges; their median differences are not treated as established universal
speedups. Compilation costs are paid during preparation and no disk JIT cache is
used. Larger bare-operator gains must not be substituted for complete-step gains.
An extra SciPy column-vector check found an interface error after an initial
2,242-test pass; the callback now normalises `(N,)`/`(N,1)` inputs to its declared
length, and two new tests cover column/matrix use and incorrect length. The earlier
pass is superseded. The independent NumPy residual checks remain unchanged.


<a id="obtained-dev34-verification-and-measured-limits"></a>

### Intra-step seeds: dev33/dev34

The frozen executable source passed **2,291 tests, including 47 new tests**,
with zero failures/errors/skips and `PASS_BOUNDED_CURRENT_PLATFORM`. All
173 source/case/test/tool hashes were unchanged during verification.
Five serial unprofiled repetitions per route compare exact physical inputs and
unchanged precision/timestep/ILU/convergence gates. Pristine dev33 and dev34 cold
fields agree bit-for-bit across all five measured workloads; explicit-start
results are close, **not** relabelled as bit-identical to cold results.

| Workload | dev33 cold, s | dev34 cold, s | dev34 explicit start, s | Same-source speedup |
|---|---:|---:|---:|---:|
| Developed case 2, 16×16 timestep | 1.153824 | 1.186607 | 0.978180 | 1.213× |
| Initial case 2, 16×16 timestep | 0.170884 | 0.157192 | 0.133826 | 1.175× |
| Initial case 1, 16×16 timestep | 0.069182 | 0.068943 | 0.070019 | 0.985× |
| Initial case 1, 64×64 timestep | 0.228984 | 0.223949 | 0.215555 | 1.039× |
| Initial case 1, 128×128 timestep | 1.234523 | 1.225195 | 1.177197 | 1.041× |

For developed case 2, stage 1 fell from 76 to 55 Picard iterations while stage 0
remained cold with 75. The complete prepared timestep is 17.6% cheaper within
dev34 and 15.2% cheaper than the matched dev33 cold baseline on this host. Initial
case 2 falls from 11 to 6 stage-1 Picard iterations. Case-1 Picard counts remain
1/1, although the supplied linear guess reduces some GMRES work. Repeat ranges are retained
for each route; small single-host differences are not universal speedups or
whole-campaign forecasts. Preparation, first-call and independent cold
endpoint timings are in `../evidence/3cr4-4-dev34-measurements.json`.

Independent scalar-root, full coupled ODE/time-refinement, failure/cancellation,
source/policy refusal and self-contained saved-input tests passed. All 26 Tosi
input configurations passed matched two-step 4×4 checks under both modes. A
separate developed 16×16 transient passed 20 steps per mode; maximum final
warm/cold temperature difference was 1.815e-12 K. These are numerical/short-path
checks, not mature published convection or a guarantee of a unique nonlinear root.
A real 128×128 four-step run matched two fresh-process two-step segments exactly
after source relocation and store copying. Actual run maximum admitted memory
was 719,543,976 bytes under the retained 1 GiB budget; all closures released their
reservations, and both changed-source and changed-start-policy continuation were
refused. WorkBudget is not an OS total-RSS limiter.

One one-step feasibility pilot preceded the new comparison specification; its
comparison gates were fixed before formal tests/measurements and never loosened.
The initial descriptor list/tuple mismatch and memory-exception reclassification
were corrected before final evidence. R4.4 remains IN_PROGRESS; this completes
only the separately selected explicit-start optimisation, retained as opt-in.


<a id="obtained-dev35-evidence"></a>

### Streaming verification: dev34/dev35

The final frozen source passed **2,342 tests (51 new), zero failures/errors/skips**,
with all **175** executable/case/test/tool hashes unchanged and
`PASS_BOUNDED_CURRENT_PLATFORM`. The retained full-inventory method independently
checks success/refusal equivalence. Same-length/same-mtime file changes, nested
mutable defaults, methods/descriptors, JIT options, added/deleted aliases and
qualified-name collisions remain detected.

Seven unprofiled batches of 20 checks per backend measured verification time
reductions of **26.6% (reference), 28.2% (SciPy) and 29.9% (Numba)**. The separate
call profile retains six verification calls and six source-byte reads per coupled
timestep in both cold and opt-in warm modes; no check is removed.

Five unprofiled repetitions per version and mode compare complete prepared steps:

| Workload, opt-in rk-stage0 | dev34 median, s | dev35 median, s | Less time | Repetition ranges overlap? |
|---|---:|---:|---:|---|
| Initial case 1 16×16 | 0.067993 | 0.054048 | 20.5% | No |
| Developed case 2 16×16 | 0.960354 | 0.976468 | -1.7% | Yes |
| Initial case 2 16×16 | 0.136271 | 0.123985 | 9.0% | No |
| Initial case 1 64×64 | 0.222662 | 0.204905 | 8.0% | No |
| Initial case 1 128×128 | 1.210126 | 1.201074 | 0.7% | Yes |

Negative reduction means slower. Developed nonlinear and 128×128 measurements
have overlapping ranges and do not establish a dependable complete-step gain;
cold medians there were 3.0% and 2.7% slower respectively. Small initial cases
show the clearest benefit. Preparation/first calls, all raw ranges and endpoint
times are retained separately. These are not whole-campaign forecasts.

All 11 compared physical arrays are byte-identical to dev34 in each of ten
workload/mode pairs; iteration counts are unchanged. An actual warm 128×128
four-step CLI/store run equals two fresh-process two-step segments after source
relocation and store copying. A separate dev34 run gives identical temperature
and composition bytes. Changed-source continuation is refused in both directions;
changed starting policy is refused and the original partial store is unchanged.
Peak admitted numerical memory remains **719,543,976 bytes**, with zero retained
reservations, under the existing 1 GiB budget. Each retained expected-binding table
has measured shallow size **51,968 bytes**, sharing captured tokens, plus one
private shallow copy while checking. Python/JIT/database/native allocator headroom
is separate; none of these observations is a total-process RSS cap.

See `../evidence/3cr4-4-dev35-tests.json` and
`../evidence/3cr4-4-dev35-measurements.json` for the source-bound results. Matching
arrays and passing component/workflow tests do not complete mature convection,
mesh/time/nonlinear adequacy, outstanding references or R4.4 campaign acceptance.


### Sparse-template performance and rejected arithmetic

Isolated assembly improves by approximately **14.6x (16x16)** and **4.70x (64x64) and 5.34x (128x128)** on
the exercised host. Developed case-2 prepared timesteps improve about **3.6% cold / 7.5%
`rk-stage0`**, with exact physical arrays and identical iteration histories. Initial 64/128
whole-step ranges overlap and do not establish a general speedup. No source checks, solver
tolerances, timestep controls or nonlinear policies are weakened.

Final regression, actual-run recovery/resource evidence and package hashes are bound to the
frozen dev36 source. The item is an execution optimisation only; R4.4 physical acceptance
remains separately gated.


### Diagnostic reuse and GMG zero-start shortcut


Keep accepted stage1 seed consumption for diagnostic solves and omit fixed-GMG's
known-zero initial matvec. Current T/C/density/time/rheology is solved anew;
diagnostics never replace the seed or affect future physical steps. Copied initial
directions own independent storage; degree-four recurrence/transfers/coarse matrices
and solve stay unchanged. At 128² this removes five sparse products 45→40 per cycle,
without shared scratch, new coefficient cache or retained memory. Default zero-rate/
auto-GMG selection stays. New source means new runs, never checkpoint rebind.

Local Windows AMD64/Python 3.12.14, NumPy 2.4.6, SciPy 1.17.1, Numba 0.65.1, one native thread,
serial workers: three alternating pairs, no discarded samples, warmed JIT outside
phases, prepare+close inside. Both arms enable GMG/Anderson/adaptive/four-use reuse/
previous-stage1 with 400 iterations, linear 1e-12, momentum 1e-9, viscosity 1e-8,1 GiB budget.
Each fresh initial/developed-derived128² input advances twice at dt=1e-7 then samples
once; this cadence is not production. The developed input is resampled 16-grid
raw temperature, zero composition, new time zero, not a historical fine-grid restart.

| Incremental comparison | Before median, s | After median, s | Saved |
| --- | ---: | ---: | --- |
| Seed diagnostic, initial Tosi1 snapshot | .232408 | .169653 | .062755 s/27.002% |
| Seed diagnostic, initial two-step+snapshot | 1.353112 | 1.266482 | .086630 s/6.402% |
| Seed diagnostic, developed Tosi2 snapshot | 7.841676 | 2.096511 | 5.745165 s/73.265% |
| Seed diagnostic, developed two-step+snapshot | 27.916380 | 22.597693 | 5.318686 s/19.052% |
| Cycle added, seeded initial batch+snapshot | 1.267561 | 1.241046 | .026516 s/2.092% |
| Cycle added, developed physical work excluding snapshot | 19.574532 | 18.755387 | .819145 s/4.185% |
| Cycle added, developed total | 21.739724 | 20.834330 | .905394 s/4.165% |

Incremental percentages are not additive/campaign forecasts. Initial cycle saving
is noisy: snapshot median regresses .001426 s/.870%; diagnostic-only stepping uses
unchanged code and regresses 0.44%. All three developed totals improved. Total-pair
ranges: diagnostic initial 1.3360552–1.4542260→1.2516103–1.3343063; diagnostic
developed 27.4036911–28.1037008→21.6883181–23.0326976; cycle initial 1.2395212–1.2944580→
1.2200799–1.2899776; cycle developed 21.5735517–22.2870478→20.6692531–20.9796294 s.

Physical state/seed/transport bytes agree; cycle diagnostic bytes also agree.
Seeded/cold diagnostics meet existing tolerances (developed max velocity 2.755e-10m/s).
Snapshot nonlinear 133→35, linear 1878→492; strict returned residuals 7.47514e-11 and
6.18753e-11 remain below unchanged 7.62727e-11. Same-source descriptors repeat,
reservations release; no OS memory cap is inferred. Recorded checks: 17 diagnostic,
10 GMG component/integration plus changed cross-step sampling regression, including
current forcing/seeds, cancel/source/plan, zero/nonzero fixed linearity, ownership,
direct comparison and actual CLI restart. Evidence-only bypass-certificate and
summary-reader metadata-key mistakes were corrected; failed records are retained,
not counted as speed data or hidden by repeated physics. Final version-label bump
changes source identity but not measured algorithm. Retained local benchmark driver:
[benchmark_solver_candidates_r4_4.py](../tools/benchmark_solver_candidates_r4_4.py),
serial isolated source copies, three alternating pairs and explicit raw fixture;
JIT/archive writing outside timing. It cannot reconstruct a historical checkpoint.

**Rejected symbolic Galerkin assembly:** worker-returned completed native comparison
(60 exact dev41 files, three pairs) improves hierarchy rebuild .026342→.022079 s/16.18%,
but regresses initial coupled 128 2.350936→2.895038 s/23.14% and developed
46.008231→50.179245 s/9.07%. Symbolic plan already survives 68 hierarchy builds;
preparation .069167 s cannot explain away 4.171014 s total regression. Do not integrate
that implementation. These results were not independently repeated locally;
reported diagnostic refusal in both arms is not physical acceptance and the packet
was not retrieved, audited or byte-verified. This rejects this candidate, not all
symbolic reuse. The minimal cycle change was locally reconstructed/reviewed/tested
from the visible proposal when its attachment was unavailable; the diagnostic
packet was retrieved and its two-line change reviewed. No broad suite/full R4.4
campaign, default change or scientific acceptance follows.

### Adaptive accuracy and assessment limits


The dev40 bounded Windows assessment used CPython 3.12.14, NumPy 2.4.6, SciPy 1.17.1,
Numba 0.65.1 and one native thread. These are new declared states from archived
temperature, not rebound historical continuations or a reproduction of Linux bits.
Probes precede final version/assessment edits; their original bindings are not
relabelled as final-source continuation. Input/trajectory archives remain local.

A boundary-compatible sin(z)/cos(x) interpolant matches original cell integrals,
then integrates onto 32/64/128 supports without creating resolved physical detail.
Mechanics/nearest-row diagnostic are otherwise unchanged; meshes are not separately
equilibrated. Quantities below are the registered nondimensional diagnostics.

| Mesh | Domain RMS velocity | Surface RMS | Max surface velocity |
| --- | ---: | ---: | ---: |
| 32 | 253.877702466415 | 2.007485658625 | 2.796617283948 |
| 64 | 251.185847863429 | 1.908572931401 | 2.659875304052 |
| 128 | 250.520551324295 | 1.884126374052 | 2.626114481682 |

Finer-grid velocities enter reference bounds, supporting a spatial-error explanation,
but inherited fine-grid bottom flux remains outside reference: no coupled acceptance.
Quadratic surface reconstruction alone changes 32-grid RMS to 1.996201428832,
insufficient. Elapsed 1.6703752/0.2889686/0.5529345 s includes encountered setup/JIT,
not matched performance.

The original zero normal slope at wall-adjacent temperature cells has linear-face
error h/2=0.015625 at 32 cells. Reflected-wall, wall-capped MC reconstruction is exact
for that linear profile without changing bounds. At new nondimensional time 0.001:

| Configuration | Domain RMS | Surface RMS | Bottom Nu |
| --- | ---: | ---: | ---: |
| Original 32, dt=1e-5 | 253.877881052771 | 2.007485426773 | 3.393288746740 |
| Corrected 32, dt=1e-5 | 250.669522765962 | 2.002951728230 | 3.286175683576 |
| Corrected 32, dt=5e-6 | 250.670105874154 | 2.002948305996 | 3.286182587133 |
| Corrected 32, dt=2.5e-6 | 250.670303053183 | 2.002947474114 | 3.286183091125 |
| Corrected 64, dt=5e-6 | 247.115670042032 | 1.904862181837 | 3.395080906712 |

Largest ten-diagnostic full→quarter timestep change 0.0003112803%, half→quarter
0.0000786607%; these short transients do not establish mature adequacy. Corrected 64
domain RMS remains below reference lower bound. Original/corrected 32 dt1e-5
probes stopped cooperatively at 180 s with 924/903 accepted steps; finer-dt probes
completed 200/400 steps in 43.2806704/83.5704772 s; corrected64 completed 200 in 66.2303171 s.
Independent probes overlapped, so these are not matched speed comparisons.

A rejected static stress-support-temperature reconstruction gives domain RMS
251.708631771189/250.546940610935/250.357651884173 and surface RMS
2.005969425524/1.908178033332/1.884027789365 at 32/64/128. Domain mesh spread falls 59.76%,
surface spread only 1.15%; spread is not absolute error. Evidence is insufficient
to replace the general nonlinear constitutive route; production is unchanged.

Recorded checks: 47 distinct boundary/diffusion/transport/conservation/ODE cases,
four analytic frozen-field/surface cases plus quadrature controls; final combined
selection 71 numerical/workflow tests. Initial wrong SuiteAcceptanceTests module
name produced 65 passes plus loader error; correct class 6/6 passed. A later affected
45-test selection overlaps those 71, not additional distinct coverage. Static safety
checked 13 maps/41 paths and 30 cases with one Windows symlink skip. No mature campaign,
full regression, complete visual acceptance or measured solver speed gain.

[Tosi 2015](https://www.ipgp.fr/~samuel/henriIPGP/Publications_files/Tosi_2015-1.pdf)
reference ranges are not confidence intervals. Case 5a Table 2 extrema omit /Ra
while equations 20–21 distinguish raw dissipation/dissipation÷Ra; whether extrema
use Ra=100 remains unresolved. Case 5b needs minimum and maximum surface Nu averaged
over ten cycles, or steady-state surface Nu, not just mean peaks. Supplement
Tables S14–S23 were inaccessible (HTTP 403); targets stay null, not inferred from
transition ranges. Existing thresholds remain. SciPy 1.18's FFT backend change
motivates the retained <1.18 compatibility bound while binary checks remain; no
new environment install/change follows from this record.

### Adaptive-inner Windows and returned Linux measurements

Independent corrected-dev40 Windows comparison: developed case 2 step 901 16×16 input,
dt1e-5, one native worker, policy disabled/enabled with the same source and existing
Anderson/previous-stage1/four-use reuse combination. One uncounted warm-up per mode,
then three alternating pairs; each fresh plan times first step separately, then
three prepared steps and a separate cold endpoint. Validation/stage records are
inside timing, archive write/decode outside. This is fresh input, not historical
source rebinding.

| Pair | Disabled mean step, s | Adaptive mean step, s |
| --- | ---: | ---: |
| 0 | 0.304870966667 | 0.282951166620 |
| 1 | 0.316855400063 | 0.283746133287 |
| 2 | 0.309460666690 | 0.283396966639 |
| Median | 0.309460666690 | 0.283396966639 |

Median saving 0.026063700051 s/8.4223%, separated observed ranges but three samples
are not confidence intervals. Across 18 timed stage solves per mode linear iterations
6006→3363 (44.006% fewer), nonlinear 312→333: iteration saving is not elapsed saving.
Temperature max difference 3.46833672893e-13 K, composition byte-identical; maximum
strict-linear residual/target 0.896172966498<=1. All 8 saved timing states and 8 endpoint
results decoded with original identities; reservations released, not measured RSS.

| Mode | Preparation samples, s | First-step samples, s | Cold endpoint samples, s |
| --- | --- | --- | --- |
| Disabled | .211398, .222720, .217673 | .617637, .605410, .661890 | .248389, .251345, .258263 |
| Adaptive | .245439, .221367, .224228 | .547261, .556236, .533269 | .216044, .206297, .213169 |

Recorded 57 distinct focused tests, not full suite:30 adaptive/mechanics/coupling
and 28 follow-up with one repeated restore case counted once. The first restore
assertion expected an inner message rather than public wrapper; corrected to inspect
cause, with production refusal already correct. Independent non-unit SI, activation
restore and endpoint recovery controls remain. One later fresh-process CLI/restart/
audit repetition took 12.520 s and is not another distinct test. Raw local records:
adaptive-dev40-timings/ and adaptive-return-20260921/, not public runtime dependencies.

Separate returned Linux dev39 reports (Python 3.13.5, NumPy 2.3.5, SciPy 1.17.0, Numba 0.65.1)
measured .208890→.174891 s (16.28%) and .241936→.212036 s (12.36%) on later developed
fixtures. Earlier 3.95% gain and bypassed-linear 9.51% regression had overlapping
ranges. These are reported worker evidence, distinct from local Windows results,
not additive or high-resolution/whole-generator forecasts.

### Selective multigrid measurement and publication repair

Windows CPython 3.12.14, NumPy 2.4.6, SciPy 1.17.1, Numba 0.65.1, one native thread and no
concurrent worker. Both arms include the same SI publication repair and unchanged
limits, Anderson/adaptive/four-use reuse. Alternate ILU/GMG, each from new input;
plan creation/advance/close timed, compilation/fixtures/archive/comparison excluded.
Developed input is a boundary-compatible reintegration of the retained 16-grid
step 901 field, not evolved fine-grid evidence. dt1e-7; no old checkpoint rebind.

| Coupled workload | Samples/arm | ILU median, s (range) | GMG median, s (range) | Saved |
| --- | ---: | --- | --- | --- |
| Case 1 initial 128², two steps | 3 | 2.060485 (2.033247–2.183173) | 1.377673 (1.334094–1.416143) | .682812 s/33.138% |
| Case 2 developed 64², two steps | 3 | 5.060393 (4.977575–5.140371) | 4.853001 (4.809075–4.924622) | .207392 s/4.098% |
| Case 2 developed 128², one step | 2 | 26.134182 (26.001997–26.266368) | 18.732475 (18.021319–19.443630) | 7.401708 s/28.322% |

Two-sample medians are means of two values, not confidence intervals. Earlier case 1
64 screening mixed first-use thermal compilation and later overlapping ranges;
no qualified gain there. Temperature max differences are 4.4408921e-16/6.6613381e-16/
2.2204461e-16 K respectively, composition exactly zero, strict/physical gates passed,
reservations released. Case 2 128 GMG had more nonlinear iterations 144/149 versus
ILU 120/128 yet lower time; iteration count alone does not select the method.
Frozen-system pressure alternatives remain comparison-only: small local gains did
not justify replacing production pressure.

The formerly refused 128 endpoint completes in 14.076966 s with 123 nonlinear iterations
including one recorded conversion refinement: internal 4.56533324e-11, first returned
9.91757609e-11, unchanged target 7.62747947e-11; final returned 7.49305771e-11 passes.
This repairs successful completion, not a speed gain against failure. Final 34 focused
tests cover GMG transfers/fixed linearity/direct and NumPy-residual agreement,
coefficient/geometry reuse, selection/admission/cancel/source, publication and actual
CLI/restart/policy refusal. A checkout repetition 13.016 s is not a 35th distinct test.
Raw local records/driver are stokes-preconditioner-compare/{coupled_trial.py,
publication-fixed-128, coupled-case1-128, coupled-case2-64, coupled-case2-128}; forced-arm
timings preceded tightened auto selection, while final checks cover that selection.
No complete suite, mature trajectory, physical acceptance or RSS gain was measured.

### Combined warm-start profile measurement

The exact-base [combined-start harness](../tools/benchmark_combined_start_r4_4.py)
compares zero-rate versus previous-stage1 at the exact detached dev41 base specified under source identity.
Both use GMG, Anderson, adaptive inner, four-use reuse, ILU fill 17, linear rtol 1e-12,
momentum 1e-9, viscosity rtol 1e-8, Picard ceiling 400. This supports that explicit new-run
profile only for tested 128² Tosi 2 inputs, not default changes/all rheologies/meshes.
The 16² control saved 9.095 ms in one pair, insufficient small-workload promotion.

Each sample starts unseeded and times capture, prepare, two accepted steps at dt=1e-7,
seed capture and close. Actual-path JIT/fixtures/check/export/checkpoint I/O/standalone
endpoints are excluded: not full-run timings. Three alternating pairs:

| Input | Cold samples, s | Warm samples, s | Median cold→warm, s | Saved |
| --- | --- | --- | --- | --- |
| Analytic128² | 2.505858400,2.330446000,2.514332000 | 1.963621100,2.030245800,1.936269700 | 2.505858400→1.963621100 | .542237300 s/21.638785% |
| Developed-derived128² | 39.632789300,33.755287200,35.089515200 | 21.466978400,19.262625100,20.052830500 | 35.089515200→20.052830500 | 15.036684700 s/42.852358% |

Every pair favours warm starts; three-pair medians are not confidence intervals or
additive GMG/adaptive savings. Developed temperature comes from 16-grid from_900.npz,
reintegrated by temperature_on_grid onto 128 with zero composition and new time zero.
It is not an evolved 128-grid trajectory, mature convection, historical restart or terrain
acceptance; private fixture/full records are not included publicly.

Existing velocity/transport tolerances, 1e-9 K coupled bound and exact composition pass;
max temperature difference 4.440892098500626e-16 K and developed velocity 3.135910142670895e-10m/s.
Same-mode state IDs repeat. Nonlinear stage counts cold [144,149,143,132]=568 versus
warm [144,63,50,91]=348; linear cold [2082,2111,2075,1872]=8140 versus
warm [2082,718,608,1145]=4553. Max returned momentum 7.87226617227077e-10 under 1e-9,
divergence 8.029132914089132e-13, heat-relative 3.4888853336570515e-19, composition residual 0.

A separate 16² saved/restored first state recreated plan and matched uninterrupted
state/arrays for both modes. Every trial checks seed chain/typed decoding/zero
remaining reservations. Existing 8² fresh-process combined CLI evidence was reused,
not rerun. Warm starts add 395,264 raw seed bytes (386 KiB) per 128² endpoint plus metadata,
without recursive history; both use 1 GiB WorkBudget, not RSS cap.

Windows 11 AMD64, Python 3.12.14, NumPy 2.4.6, SciPy 1.17.1, Numba 0.65.1, llvmlite 0.47.0,
threadpoolctl 3.7.0, one native thread/exclusive numerical worker. Exact detached
source bytes/membership matched before/after. The local bounded driver reused reviewed
harness functions for one 16-grid restart check then three pairs/input; it did not run
the longer all-in-one repeated CLI/128-grid restart sequence. Focused harness tests
retain canonical-LF synthetic fixtures and source refusals. Reproduction requires
its exact detached base, compatible installed dependencies, new output and explicit
exclusive-host confirmation/repeat 3; the guard intentionally refuses newer source.
No source/checkpoint pin is altered to make it pass. Original tooling-only packet
could not execute numerical work; these later local measurements supersede that
execution limitation, not its preserved evidence or broader acceptance gates.


### Baseline mechanics and SI review

Core WorkBudget admissions remain estimates, **not an OS RSS cap**. The runner's
Python receipt ledger, JSON serialisation, interpreter/native runtime, diagnostic
plotting and retained caller outputs require separate headroom. The default
500-step receipt cadence bounds pending ledger growth; large explicitly selected
cadences require correspondingly more memory. ArrayStore's declared 2 GiB store
limit is not a limit on the whole run directory: receipts, evidence and plots are
additional disk use. Finite schedule limits are not a universal machine-capacity
guarantee. Do not describe zero remaining core reservations as zero process memory.

A sampled Linux process RSS/high-water measurement is current-host evidence only.
Dev31 profiling found six exact source/callable verifications per ordinary timestep;
they dominate some small simple workloads but were only about 2.6% of the developed
16x16 nonlinear step and 0.45% of the 128x128 initial step. Those checks are therefore
left unchanged in dev32. The dominant costs were mechanics: roughly 93% linear-solve/
factor work in the developed nonlinear sample and 99% at 128x128. Matched measurements
on this Linux runtime show the prepared case-1 step median changing from about 0.0813,
0.1090, 0.3577 and 11.6406 seconds at 16/32/64/128 in dev31 to about 0.0726, 0.0967,
0.2365 and 1.2645 seconds with the retained dev32 policy/kernels. The developed case-2
16x16 endpoint solve changed from about 0.9944 to 0.7770 seconds with identical velocity
array hash and the same 75-Picard/2508-linear-iteration history. These measurements are
matched-workload evidence, not universal speed guarantees or whole-planet forecasts.
Source verification is not replaced with timestamps, stale caches or skipped checks.

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


### Initial sampling

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


### Spherical partition generation

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


### Shared atlas queries

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


### Shared boundary batching

[Focused measurements](../evidence/w01-stage3-measurements.json) use 96 rectangular
regions, 212 unique edges and 172 interplate edges. Five paired warmed comparisons
of the same velocity diagnostics gave median 17.112 ms through individual diagnostic
calls and 2.537 ms through the new batch interface, with identical compared output
bytes. Single-observation network preparation took 62.514 ms. Candidate checks
and retained/tracked memory scopes are recorded; these are not world forecasts,
hardware-independent improvements or an audit of all future geometry sizes.
No timing threshold is embedded in tests. Windows and geological validation are
unverified; no publication or edits on the owner's PC occur here.


### Geometry query controls

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


### Reference-material verification and bounded scope

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


### Regional transport accuracy/cost and negative scheduling result

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


### Cohort native/reference comparison

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


### Remap and ALE comparisons

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


### Buffer and periodic transport comparison

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


### Cooling, rotation and flexure comparison

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


### Execution, context verification and cache admission

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
These original measurements do not establish Windows/macOS, other native builds, power-loss recovery, full-world resources or later unbuilt physical mechanisms.

Method references: [CPython concurrent futures](https://docs.python.org/3.13/library/concurrent.futures.html),
[NumPy thread safety](https://numpy.org/doc/stable/reference/thread_safety.html),
[threadpoolctl and its backend/thread limitations](https://github.com/joblib/threadpoolctl),
and [OS file locking](https://docs.python.org/3.13/library/fcntl.html).
They support API semantics, not the obtained Atlas measurements.


### Whole-store preparation and format comparison

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


### Combined resource/platform drill

#### Obtained checks and bounded combinations

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

#### Platform decision and continuation

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


### Later endpoint lookahead and geometry/capture selections

The [Plan18 method record](../optimisation/workbench/plan18/README.md) covers four
changes:
- one or two endpoint workers compute across supports, under the scheduler's
  configurable defaults of 512 jobs and 4,096 requests;
- the compact route keeps plain support headers;
- retained ownership carriers are booked at a measured 2,112 B;
- a retained-handle diagnostic is added.

The reader chapter explains
[endpoint lookahead](how-it-works/06-physical-integration.md#look-ahead-across-supports-to-keep-endpoint-workers-busy)
and [header retention](how-it-works/06-physical-integration.md#retain-only-plain-support-headers-on-the-compact-route).

The 1.65× interval-2 endpoint result comes from a detached endpoint-loop replay
on captured supports. It is not a run of the integrated successor or of a whole
interval. The integrated route's evidence is its closure proofs and focused
tests. Larger-interval capacity under that predecessor's 256 MiB retained cap
remains open; later combined-source selection has its own paid carrier/support
allowance and is not bounded by this predecessor-only forecast. The
[endpoint owner](../optimisation/workbench/plan18/README.md) distinguishes those
routes. No new research or scientific acceptance is claimed.

The [Plans19–20 source selection](../optimisation/README.md#plans19-20-source-selection)
combines two accepted geometry changes and the accepted S2 r9 capture helpers,
preserving later heat/worker choices. The reader chapter explains
[bounded geometry refinement](how-it-works/06-physical-integration.md#refine-only-the-geometric-bounds-that-need-it)
and [exact diagnostic operands](how-it-works/06-physical-integration.md#save-diagnostic-operands-without-changing-their-logical-identity).
Component results and memory trade-offs are recorded in the linked method records.
The public selection has new source identities; historical private results do not
authenticate a new combined runtime. Release/Plan26 binding and main-package
landing remain separate. No new research or scientific acceptance is claimed.

## Scientific eligibility and method provenance

Execution optimisation cannot change the evidence population or scientific question. The [source-use contract](FOUNDATIONS.md#3c-r1-reviewed-source-use-contract-18-september-2026) and [versioned policy](../cases/plate_reference_use_policy.json) own PB2002 strict/scoped uses, scales/phases, original incidence defects, observation populations and held-out splits. Strict failure remains failure; scoped exit 0 never replaces it. Use the existing [offline commands](../README.md#offline-plate-reference-assessment) for actual work. No source acquisition occurred in this consolidation.


<a id="3cr1-reference-tools"></a>

### Prepared reference use, resources and identity


prepare_reference_use() checksum-loads originals and runs the unchanged strict report, admitting 16 MiB additional workspace alongside its report reservation; returned data/indexes remain caller-owned. A frozen shared report tree backs indexes without per-query payload copies, exact boundary keys build once, and selection/candidate distribution work uses bounded native arrays plus a 256 KiB metadata envelope. Concurrent reads share immutable setup; cancellation/refusal releases work, returned reports detach.

Qualified identity binds policy/source/strict report, reference split/scale/phase, area basis, exclusions and actual values. Persist the unchanged strict report through existing lossless ArrayStore; separate receipts name policy/assessment and cold reuse rechecks both. No timestamp/mutable-array-address cache or source exemption is introduced. [Foundations](FOUNDATIONS.md#3c-r1-reviewed-source-use-contract-18-september-2026) and [policy](../cases/plate_reference_use_policy.json) own scientific eligibility and source restrictions. [Assessment](../evidence/3cr1-reference-use-assessment.json), [coverage](../evidence/3cr1-reference-use-coverage.json) and [tests](../evidence/3cr1-reference-use-tests.json) retain original results; the raw [strict report](../evidence/3cr1-complete-reference-checks.json) is not replaced by scoped success.

### Purpose correction and exposure boundary


The registered split remains binding: development pairs with calibration, withheld with validation, source-verification with itself. The R7 correction rejects development/validation as well as withheld/calibration; permitted records and protocol identity are unchanged. measure_w01_plate_shapes.py now derives purpose from split: eleven ranked outlines were development, PS withheld. A recorded JSON tally found 263 development/calibration and 250 withheld/validation pairs, no invalid pair; the old tool output was not committed and [bounded-validation prose](W01_REGIONAL_WORKFLOW.md#bounded-shape-validation-and-limits) remains historical.

All 52 published areas are exposed calibration; Cocos and the first 12 AF–AN motion rows were previously exposed. The ten morphology holdouts and their touching boundary segments, separate scale/phase unresolved counts and orogen tuning restrictions belong to the [source-use contract](FOUNDATIONS.md#3c-r1-reviewed-source-use-contract-18-september-2026). A within-model holdout is correlated evidence, not an independent second Earth or a realism score.


<a id="plate-layout-science-correction"></a>

### Statistical layout eligibility and observed limits


The PB2002-conditioned connected candidate is area-calibrated, not a certified Earth-like default or causal formation model. For N<52 the largest-N published areas are renormalised; N>52 requires another declared prior. Global L1 and per-plate relative area checks refuse unresolved small plates; finer generating support changes the prior, not display zoom. Three sparse shortest-path solves per cut, compact dual adjacency and bounded connectedness reuse existing native generator, shared coverage and ownership budgets. Parent support geometry stays admitted while building derived atlas. No new scheduler/cache or hidden accuracy fallback.

[Plate-layout tests](../evidence/plate-layout-tests.json) record 1,134 passes (1,091 prior+43), zero failures/errors/skips, 84 unchanged verification files. [Comparisons](../evidence/plate-layout-comparisons.json) use three preselected seeds, 12 plates, 512 support cells: median rank-area L1 error is 0.32368058 for Voronoi and 0.00784261 for the candidate against the declared largest-12 prior. This is calibration improvement, not geological realism. Each case was timed once per seed; finer construction is slower and retains more geometry, without robust speed claims. Coarse 52-plate requests refuse if relative bounds fail.

The Cocos ring has 157 edges plus closure; area 0.072230194879 sr agrees with printed 0.07223 sr. The largest AF/AN 12-step difference is 0.06247472 mm/a within its source-specific 0.2 mm/a rounding allowance. Cocos/motion samples are previously exposed development evidence; R7 corrected older held-out labels in writers, while original comparison receipts retain historical labels/digests. Those probes verify source signs/geometry, not arbitrary generated motion or the complete morphology population. Outline metrics refuse pinches and unsupported conditioned hemispheres rather than choose arbitrary continuations; global area/perimeter/adjacency and same-owner seam exclusion retain their definitions in [Foundations](FOUNDATIONS.md).

Actual model-data plots: [Voronoi](../evidence/plate-layout-voronoi.png), [candidate](../evidence/plate-layout-candidate.png), [area prior](../evidence/plate-layout-area-spectrum.png). Recorded platform Linux/CPython 3.13.5; Windows, full morphology, physical histories and world-scale performance remain unverified. PB2002 numerical provenance is Peter Bird; curated conversion Hugo Ahlenius/Nordpil, GeoJSON preparation csterling, ODC Attribution 1.0. Original source/blob selectors remain in plate_reference.py; no third-party implementation was copied.


<a id="plate-formation-evidence-20260918"></a>

### Causal plate-formation primary records

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


<a id="plate-formation-execution-plan"></a>

### Cost-aware causal model design


Native arrays/shared catalogues, bounded indexes and sparse connectivity, prepared topology/factors, exact dependency identities and lossless checkpoints remain the execution basis. Nonlocal stress/flexure and changed damage/temperature/composition/boundaries may invalidate wider work than the edited region. A preconditioner/warm guess still needs current residual/branch controls. Adaptive support, event-aligned stepping, conservative transfers, distributed coupling and alternative precision are numerical/model developments, not automatic performance switches; [candidate families](#candidate-register) state their boundaries. Required science and R1–R9 sequence remain in the [tectonics plan](TECTONICS_PLAN.md).

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

Extraction itself consumes numerical accuracy: threshold/smoothing length/minimum resolved region belong to scientific configuration. Incremental extraction must agree with full extraction at contacts and threshold crossings, preserving uncertainty/hysteresis. One accepted contribution/face/event owner and coherent checkpoint are required. Whole-process/native/JIT memory and complete time-to-required-accuracy matter alongside admitted arrays. No percentage gain, metre-scale mantle claim or automatic GPU/distributed selection follows from this planning guidance.

## Candidate selection and measurement
<a id="candidate-register"></a>

### Potential follow-up improvements — deferred, 24 September 2026

**User instruction: record these only; do not implement or benchmark them now.**
Status: **CANDIDATE — NOT EXPERIMENTALLY ASSESSED IN THE MODULE-WIDE W11 PASS**.
Resume only on an explicit follow-up request. The completed pass covered the
implemented workflows; it was not an exhaustive comparison of every possible
algorithm. Most families below already appear in PF01–PF26. These are more
specific follow-up experiments, not newly discovered omissions or claimed novel
research, and none has an Atlas speedup estimate or demonstrated benefit yet.

| Potential experiment | What to investigate later | Existing work and conditions to preserve |
| --- | --- | --- |
| **Cross-stage execution fusion and shared intermediates** (PF01/07) | Plan compatible producer/consumer chains together so common geometry, thermal or material intermediates are computed once and unnecessary materialisation/copying is avoided. Start with a real linked route, not isolated kernel timings. | Prepared contexts and local copy elimination already exist. This would assess a broader cross-stage plan. Preserve immutable ownership, required diagnostics, provenance, cancellation and checkpoint boundaries; fusion may reduce useful parallelism. [Dask graph optimisation](https://docs.dask.org/en/latest/optimize.html) supplies the execution-pattern reference, not a requirement to adopt Dask. |
| **Field-/region-aware incremental recomputation** (PF01/02) | Track which physical fields and spatial supports actually changed and recompute only proven affected consumers, rather than invalidating an entire compatible workflow result. | This goes beyond existing result/geometry caches and incremental storage. Nonlocal stress, flexure, connectivity and threshold changes must propagate globally where required; dirty flags alone are not evidence of unchanged data. First compare with full recomputation. |
| **Persistent recycled Krylov subspaces** (PF19) | Carry a bounded useful search subspace between compatible changing linear systems, rather than retaining only an initial guess or factor. Assess GCRO-DR-style recycling against current warm starts and preconditioners. | Krylov reuse was already a candidate family, not a newly assessed W11 implementation. Check current-operator residuals, pressure null spaces, topology/coefficient changes, memory and restart/reset rules. [PETSc/HPDDM](https://petsc.org/main/manualpages/KSP/KSPHPDDM/) documents GCRO-DR and its research references. |
| **Outer coupled-workflow acceleration** (PF19 extension) | Where a genuine iterative thermal/mechanical/material coupling exists, assess interface quasi-Newton history to reduce whole coupling iterations, including transfer and verification costs. | Atlas already has Type-II velocity Anderson acceleration and log-viscosity Anderson; do not propose those again as missing. The candidate is a distinct outer interface, only if profiling and the actual coupling equations justify it. Preserve physical bounds and current convergence checks; do not invent a feedback loop for speed. [preCICE acceleration](https://precice.org/configuration-acceleration) describes IQN-ILS/Anderson and IQN-IMVJ. |
| **Multirate, event-aligned integration** (PF21) | Evolve demonstrably slow and fast processes at different appropriate internal rates while synchronising exchanges and geological events. | Already listed/deferred, not a tested W11 gain. This is numerical-method development, not simply skipping stages. Preserve coupled heat/material/force accounting, event timing and temporal error; no raised step ceiling or relaxed tolerance. [SUNDIALS ARKODE](https://sundials.readthedocs.io/en/latest/arkode/Mathematics_link.html) supplies the multirate-method reference. |
| **Partial assembly for currently assembled regional operators** (PF16/19/20 extension) | Compare retained element/quadrature data and on-demand operator action against assembling/storing the full regional operator, including the cost of an effective preconditioner. | Atlas already has matrix-free Stokes/Schur actions; this is not a proposal to add matrix-free solving everywhere. Applicability depends on element type/order and the actual regional route. Lower RAM is not a win if elapsed time worsens. [MFEM partial assembly](https://mfem.org/performance/) explains the representation and preconditioning trade-off; its tensor-product approach is not a drop-in fit for every Atlas mesh. |

When requested, assess the first two against linked-workflow profiles before
commissioning new solver work. Acceptance is lower elapsed time at unchanged
required output quality, with explicit accounting for preparation, transfer,
verification and recovery. No new dependency, backend or production policy is
authorised by this list.

### 3.1 PF01–PF26: choose, do not enable indiscriminately

**PF01–PF26 are planning checklist IDs, not new Atlas modules or implemented switches.** Assess relevance when a kernel or its workload is selected; do not implement every row. [the candidate register section](#candidate-register) and O01–O17 retain the detailed software-method background. These are candidate families; implementation and measurement status is case-specific, including the retained W11 decisions above. Listing a family does not enable it.

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

This catalogue itself performs no benchmark. Each later study states its scientific question, unchanged/changed equation and E/N/M/S class, baseline and candidate identities, numerical/physical error criteria, workload, permitted resources and stop conditions before execution.

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

The following **PT01–PT14** tests supplement T01–T16. They test execution and storage, not replace physical validation. These are challenge families, not universal completion claims; the retained W11 selection states which were exercised and omitted.

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

## Language and native-call boundary

<a id="native-boundary"></a>

**Language selection:** retain Python for case definitions, orchestration, validation and reviewable scientific logic. Use appropriate native-backed numerical routines for bulk work. Evaluate a narrowly compiled kernel when a measured path justifies it; C++ is a candidate, not a whole-project rewrite decision. Numba or an existing scientific routine may answer a narrower need. Do not accumulate multiple native languages and accelerators without a maintained use case. This is implementation guidance, not permission to install or migrate anything.

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

## Scientific-software methods O01–O17


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

## Engineering methods and their accuracy boundaries
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

## Adoption and non-goals
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

## Sources and maintenance

Update the subject that owns the mechanism. Keep current status in [CURRENT_STATE.md](../../docs/CURRENT_STATE.md), scientific explanation in its specialist contract and operational examples in existing operational homes. Retain unique equations, assumptions, limitations and measurements here until a substantive owner exists; a pointer alone is not a replacement. Git history keeps superseded prose, without another archive, revision stack or duplicate ledger. Original receipts retain historical digest detail; active source guards and exact benchmark boundaries remain mandatory.

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
