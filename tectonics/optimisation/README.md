# Atlas optimisation programme

Start with [current delivery and acceptance](../../docs/CURRENT_STATE.md#current-delivery-and-acceptance) for status, outstanding work and holds. This page supplies navigation and durable workflow contracts. Publication, component acceptance, installed delivery, runtime/default selection, scientific acceptance are separate outcomes.

The engineering aim is exact, certified interval generation in under five minutes on one Windows machine. That is a target, not measured combined performance. Changes preserve exact results or an explicitly approved field/identity translation; they do not widen tolerances or resource limits.

This page is the consolidated catalogue of the optimisation work in this published
branch: programme plans, compact work packages, candidate families and researched
techniques. Each list links to its existing owner for the actual contracts, evidence
and current status. The lists overlap: one method can appear in several programmes.
An idea listed here is not automatically implemented, enabled, measured or accepted.
The [current delivery and acceptance record](../../docs/CURRENT_STATE.md) owns the
status and holds; private or later work not represented there is outside this public
snapshot. Plan41 is included from the existing roadmap issue.
This is an index of documented optimisation work, not an exhaustive audit of
every performance-related implementation in Atlas.

[Plans](#plan-directory) · [Compact work packages](#compact-work-packages) ·
[Candidate families](#candidate-families) · [Scientific-software methods](#scientific-software-methods) ·
[Engineering techniques](#engineering-techniques) · [94-technique mapping](#94-technique-mapping)

## Layout

| Location | Purpose |
| --- | --- |
| [`composed-r2/`](composed-r2/) | Historical checkpoint package, helpers and composition pins. |
| [`drivers/`](drivers/) | Interval entry points, launch/reopen tools and tests; [continuation method](drivers/INTERVAL_CHAIN.md). |
| [`pending/`](pending/) | Retained candidates and predecessors; the name does not establish present selection. |
| [`workbench/`](workbench/) | Source constructors, component owner records, measurements and predecessor selections. |
| [`docs/COMPACT_EVERYWHERE_PLAN.md`](docs/COMPACT_EVERYWHERE_PLAN.md) | Compact storage/restart design, ownership, measurement and completion contracts. |
| [`docs/release/`](docs/release/) | [Check policy](docs/release/RELEASE-CHECKS.md), [fold](docs/release/FOLD.md), [languages](../../docs/CODING_SAFETY.md#7-conditional-compiled-kernel-development) and [landing expectations](../../docs/CODING_SAFETY.md#6-changed-expectations-and-landing-obligations). |
| [`CHANGELOG.md`](CHANGELOG.md) | Concise historical changes. |
| [`MANIFEST.json`](MANIFEST.json), [`SANITISED.md`](SANITISED.md) | Historical export origins and sanitisation record, not a live runtime manifest. |

MANIFEST's document rows inventory the historical export. They do not require retired status/index pages to remain in the current checkout. Their earlier prose remains in Git history; consolidation does not repin that historical manifest.

## Plan directory

These links identify subjects and existing owners. Read status in the current-state table and detailed contracts/evidence in the linked records. A plan number, folder revision or larger member count does not select a runtime.

| Plan | Public plan or owner record |
| --- | --- |
| 01 | [Runner test isolation](#plan-01--runner-test-isolation) |
| 02 | [By-need start gate](workbench/plan02/README.md); [prepared-construction v2](workbench/plan02/prepared-construction-v2-r3/README.md) |
| 03 | [q21 launch environment](#plan-03--child-launch-and-evidence-preservation) |
| 04 | [N9 comparison tools and width](workbench/plan04/README.md); [bounded-width method](workbench/plan04/BOUNDED-WIDTH.md) |
| 05 | [Heat correctness](workbench/plan05/README.md) |
| 06 | [D5 exact arithmetic](workbench/plan06/README.md) |
| 07 | [Pressure P1–P3](#plan-07--pressure-p1p3) |
| 08 | [Pressure P4](#plan-08--pressure-p4) |
| 09 | [Parallel initial admission](#plan-09--parallel-initial-admission) |
| 10 | [Initial measurement reuse](workbench/plans10-12/README.md) |
| 11 | [Reader-admission overlap](drivers/INTERVAL_CHAIN.md#serial-reader-admission-overlap) |
| 12 | [Heat timings/profile](workbench/plans10-12/README.md) |
| 13 | [H3 certification](workbench/plans13-14/README.md) |
| 14 | [Heat finish and closure markers](workbench/plans13-14/README.md) |
| 15 | [Heat-worker assessment](workbench/plan15/README.md) |
| 16 | [Geometry-worker assessment](workbench/plan16/README.md) |
| 17 | [Geometry stacked parity](workbench/plan17/README.md) |
| 18 | [Endpoint batching](workbench/plan18/README.md) |
| 19 | [Geometry candidates](workbench/plan19/README.md) |
| 20 | [Diagnostic captures](workbench/plan20/README.md); [measurement and folded-DLL contract](workbench/plan20/README.md) |
| 21 | [Lazy rows and sealed-mesh identity](workbench/plan21/README.md) |
| 22 | [Bounded page carry](workbench/plan22/README-r4.md); [corrected-reader selection](workbench/plan22/README-r4.md) |
| 23 | [Authenticated sidecar reads](#plan-23--authenticated-sidecar-reads-wp12) |
| 24 | [Segment summaries and buffer pools](#plan-24--segment-summaries-and-buffer-pools) |
| 25 | [Runtime arithmetic identity](#plan-25--runtime-arithmetic-identity-l4) |
| 26 | [Fold contract and historical parity](docs/release/FOLD.md); [prepared/fresh receiving](workbench/plan26/README.md) |
| 27–29 | N9 science, shared identity and live integration: [width](workbench/plan04/BOUNDED-WIDTH.md), [L4/C12/X1](#plan-25--runtime-arithmetic-identity-l4), [driver lineage](drivers/INTERVAL_CHAIN.md). Separate private plans are not supplied. |
| 30 | [B17/item14 and guarded reads](workbench/plan30/s1a/README.md) |
| 31 | [Query reporting](workbench/plan31/tier1/README.md), [final source/emitter](workbench/plan31/final/README.md), [explicit construction](workbench/plan31/final/README.md#explicit-construction-and-data-boundary) |
| 32–38 | Booking, query-store decision, reprofile, retests, dispositions, landing and intervals: [assembly](workbench/plan31/final/README.md#assembly-dependencies-and-unresolved-scope), [compact programme](docs/COMPACT_EVERYWHERE_PLAN.md), [expectations](../../docs/CODING_SAFETY.md#6-changed-expectations-and-landing-obligations), [driver](drivers/INTERVAL_CHAIN.md). Separate private plans are not supplied. |
| 39 | [Release policy source and qualification](workbench/plan39/README.md) |
| 40 | [Pressure arithmetic](workbench/plan40/pressure/FINDINGS.md) and [heat arithmetic](workbench/plan40/heat/FINDINGS.md), with their linked receiving routes |
| 41 | [Compact geometry between intervals](https://github.com/Atlantispy/atlas/issues/3#issuecomment-6439177800): planned after successful IV1/comparison and before a separately authorised longer campaign. |

## Plan 01 — runner test isolation

The [test-only successor](workbench/compact-geometry-r1/test_wp10_integration.py)
and [five-case checker](workbench/probes/step8/claude-20261015/plan01/plan01_fixture_check.py)
move candidate setup out of discovery and restore the changed module bindings,
parent `storage` attribute and `sys.path`, including failed setup and the explicit
`--fresh` route. Retained original-environment evidence was 5/5 fixture cases and
235 tests across 17 modules, with eight skips, no failures or errors, 263.896 s
and 0.40 GiB tree peak. It does not replace frozen `composed-r2` or establish
selected-runtime integration or scientific acceptance. The separate `ram_context` /
lazy `partition_v2` binding remains an applicability decision for the selected
composition.

## Plan 03 — child launch and evidence preservation

q21's r3 attempt was **invalid launch environment** after missing shell utilities
and a failed input copy, not a numerical verdict. The [r5 wrapper](workbench/geometry-growth-r1/scripts/run_dj_rearm_r5.sh)
confines the PATH correction to its child and refuses failed real copy before
parity. The [r6 successor](workbench/geometry-growth-r1/scripts/run_dj_rearm_r6.sh)
requires the specifically ruled empty r3 log and matching outer log, refuses changed
or additional orphans, and rechecks preservation before launch, merge and on copied
evidence. Its [synthetic regression](workbench/geometry-growth-r1/scripts/test_d08_preservation.py)
passed seven cases and detected five expected r5 bypasses. These are launch and
evidence checks, not scientific parity. [Plan16](workbench/plan16/README.md) records
the later q53 bounded worker/parity proof; that supersedes the old pending-retry
wording without changing q21's disposition or installing the wrapper in a runtime.

## Plan 07 — pressure P1–P3

P1 parallelises walls while preserving order and exact outputs; P2 reuses per-wall
preparation; P3 hoists Fraction work. [Pressure findings](workbench/plan40/pressure/FINDINGS.md#retained-measurements)
record q39 serial/worker/decline/crash comparisons, the q43 two-worker consumer
and later c2 shutdown-lifetime repair within their stated scopes. P2/P3 pressure
stage timing of 71.48 → 46.95 s and auto2 46.95 → 38.88 s (sampled tree RSS
407 → 820 MiB) are not whole-interval gains. Final coupled C4 and assembly remain
separate.

The original full-scale contract requires base serial and all six candidate arms:
serial, auto1, auto2, auto6, forced decline and forced crash. Require successful
exits and valid input/worker identities; candidate **ARMS EQUAL** covers forcing
ID, descriptor hash, arrays, integration leaves, driving ID and datum. Separately
compare base and candidate using NUMBERS EQUAL or the approved identity-only D-b
null control: arrays, leaves, datum and descriptor structure remain equal, and only
the controlled identity fields may differ. The comparator reads the first arm;
its pass cannot replace complete arm coverage. No epsilon is permitted.

Report gate input bytes, decoded bound and actual child allowance, worker real and
booked peaks, free cores, workers requested/granted, and adopted, declined, crashed
and recomputed walls. Use actual selected policy, not a constructor default. A
separate untimed transient pass verifies the live, gate and release boundaries and
tool release; book a transient above 256 MiB before integration. Preserve no reopen
change, existing numerical/resource limits and sampled-tree scope. Forced decline
and crash must recompute exactly; unavailable required workers are an environment
disposition, not a pass or automatic retry. Pressure hands accepted evidence to
Geometry for binding/dispatch and Runner for pinning. Any later proof uses the
current owner inputs, queue and holds; these requirements grant no launch. The
retained private handoff identifies `run_arms.py`, `ab_pressure_r4.py`,
`compare_ab_r2.py` and the approved null control; their historical pins and
outputs are not replacement authority for a new proof.

## Plan 08 — pressure P4

P4 is **implemented, tested and disabled**: q41 exact/null comparisons passed but
SMALL pressure-stage median rose from 57.12 to 123.025 s (+115.38%), without a
material RAM benefit. This did not measure the later lifetime-corrected shared
primitive or establish production adoption. [Pressure findings](workbench/plan40/pressure/FINDINGS.md#retained-measurements)
own the measurement and current source details; [Plan06](workbench/plan06/README.md)
owns the repaired shared primitives and D6 disposition.

The reference `_jet_mul` retains its three-component product: `a0*b0`,
`a1*b0 + a0*b1`, and `(a2*b0 + 2*(a1*b1)) + a0*b2`, with reference interval
operations, grouping and constant/zero/identity shortcuts.
Outward interval rounding uses `floor(lo*d)/d` and `ceil(hi*d)/d`, including
negative endpoints, at the original rounding points. Precision is request-derived
through a `ContextVar` (default 128) and reset in `finally`; `_RadialJet` expression
identity is distinct from coincident numerical values. Python mode does not require
gmpy2; explicitly requested unavailable native providers refuse, without silent
fallback after calculation failure.

Any reconsidered candidate retains reference-derived pre-reservation width checks,
provider and backend identity, exact outputs, ownership and lifetime accounting;
native objects do not escape in returned or persisted state. Preserve reference
reservation category and ordering, the distinct native and compact-integer ceilings,
and reference output types and shortcut identities. Policy A permits only the
specified earlier refusal, not later or absent refusal. Focused checks cover
shortcuts, signs/endpoints, rounding/context cleanup, provider, alias/pickle,
near-limit budgets, failure order and retained-native release. Use the approved
identity-only controls for explainable identity changes, and retain the independent
refuter and authorised measurements. A prior candidate's evidence is not acceptance
of a changed candidate or permission to rerun it.

## Plan 09 — parallel initial admission

ip9 recomputes the same 969 initial-metrics queries, preserving query order, the
parent's accuracy/witness and store checks, and serial fallback. The 969 chunks and
snapshots in the retained smoke are store records, not a partition of a planet.
The dated record reported ip9 READY and q19 queued but unlaunched; consult the
current owner before stating present queue status. The 40-query t9 worker fixture
and warm-store smoke do not prove fresh-store worker adoption.

The retained fresh-store proof uses the selected two-worker route. Require positive
`initial_parallel.stats.started` and `initial_parallel.adopted`, successful exit and
all job checks. These count started batches and adopted results; they do not prove
each worker adopted a particular share. The same-tree `compare_reports.py` result
must have `passed == true`, all checks true and no failures: both reports pass,
native/import roots and loaded digests agree, `metrics_only` is false, workflow and
non-empty preparation IDs agree, and every key in the non-empty identity union
matches. A comparator self-test is not this proof.

The Run-A `store_rekey.py` comparison requires its pinned reference and absent
sidecars, equal settings and chunk rows in put order, non-empty equal counts, one
execution identity per store, and validated snapshot bodies, keys and digests.
Re-derive snapshots under the approved reference execution identity and compare
them byte-for-byte in order; do not mask arbitrary differences or demand an
identical whole SQLite file. The selected native Python sources must match at
start and end; this scan does not cover every external helper. Preserve source
freeze, absent output and failure/partial evidence. The old booking was scheduling
data, not a live admission or RAM ceiling.

Geometry confirms the receiving-source boundary and reviews its code; Runner owns
integration, including the shared pressure/admission schema. READY, proof, source
integration and final assembly are distinct. Existing owner and queue conditions
govern any future execution; this catalogue authorises none. The retained private
owner handoff identifies the selected `ip9` manifest, `job_initpar_tree.sh`,
`compare_reports.py` and `store_rekey.py`; select and bind their actual current
versions rather than treating the old booking or filenames as a launch ticket.

## Plan 23 — authenticated sidecar reads (WP12)

**Storage: assessment complete; unbuilt/off.** Positioned reads into fresh immutable
bytes were considered for eligible `int.bytes` cache misses; mmap and a per-open
freshness shortcut were rejected. The selected reader established one eligible
sealed reopen per successor store, not two. The retained IV1 reopen averaged
15.67 s with 8,294 native misses; the estimated central net saving was −3.1%
(sensitivity −9.8% to +5.1%) and added disk about 158 MiB. These are scoping
estimates, not a measured sidecar result or a proved upper bound. The separate
[compact programme](docs/COMPACT_EVERYWHERE_PLAN.md) owns the WP12 design context.

Reconsider only if guard-equivalent freshness removes the repeated ancestor walk,
an eligible reuse count is established and a comparable authorised A/B shows at
least 5% net reopen saving **including build and open costs**. The selected handle
check currently runs on every read. A candidate must authenticate the exact typed
chunk and bytes consumed even with caching disabled; preserve file length,
changed/swapped-file refusal, opened-handle identity, locking, memory and disk
charges, and cancellation/retirement. Lazy authentication changes when unused
corruption is refused and needs explicit equivalence review. Exercise used and
unused corruption, truncation/extension, wrong offsets, disabled verification,
capacity/fallback and cleanup; preserve exact reader results and the required
independent refutation. Plan30's held-handle design is a separate matter; this
decision authorises no build, run or weakening of checks.

## Plan 24 — segment summaries and buffer pools

**Storage: assessment complete; both unbuilt.** The retained q04 profile did not
establish either build gate; it is not a measured failure. Its 26.458 s instrumented
reopen included 3.367 s ranged-read calls and 0.0808 s selected allocation/copy
operations; the plain reopen was 15.670 s. The attribution is incomplete and
these totals are neither measured savings nor complete cost bounds.

- **Segment summaries:** no content-predicate storage-pruning opportunity was
  demonstrated; an unexplained caller edge and missing per-read discard attribution
  prevent a zero-cost claim. Reconsider if an actual predicate consumer discards
  ranged reads costing at least 5% of its relevant read time. A justified footer
  belongs to the coordinated Step 12 format batch and must preserve exact typed
  values, authenticated content, compatibility and refusal semantics.
- **Buffer pools:** transient staging buffers exist, but removable allocation cost
  was not isolated and retained pages, SQLite-owned results and immutable copy-outs
  have different lifetimes. Reconsider when qualifying selected-reader evidence
  shows allocation/copy work around 5% of read time; a later ticketed comparison
  must include allocation and first-touch costs. Preserve owned copy-outs or sound
  leases, charge idle and active capacity, and handle admission, cancellation and
  release. Neither idea is selected for implementation by this assessment.

## Plan 25 — runtime arithmetic identity (L4)

**Kernels: approved, not started in this public plan.** A shared-file decision is
required before implementation. The affected seam is `reuse._runtime_record` in
the selected `reuse.py`, with `_loaded_binary` and `exact_arithmetic.runtime()`;
it is not a separate `_runtime_record.py`. Extend the existing label-keyed record
with trusted expected identities for the loaded `_decimal.pyd` and libmpdec
version, the actual loaded `python312.dll`, and `fractions.py`, `decimal.py` and
`_pydecimal.py` as used. Retain existing identity fields and fail closed for missing
or mismatched required files. Observed-at-launch bytes alone are not trusted pins;
the virtual-environment executable's sibling need not be the loaded DLL.

The existing coordinator decision covers labels, selected files, trusted pins,
check location and refusal wording. After that gate, the owner uses its selected
source-bound transform: C12 orders source-handles r2 → L4 → package reconciliation;
X1 combines H3, G-PY, N9 and L4, with L4 riding the first H3/G-PY generation if
timing requires. The final R1 fold still goes last; L4 precedes K1. Prove changed
binary and used source inputs and missing files refuse through the real record,
using disposable fixtures, and prove numerical values and existing checks remain
unchanged. Bind proof to the actual selected transform/runtime and retain old
receipts. FTZ/DAZ and rounding-word policy are outside this repair. This plan
grants no shared-source edit, run or fold authority.

## Compact work packages

WP0–WP25 are the [compact optimisation programme](docs/COMPACT_EVERYWHERE_PLAN.md#3-work-packages-execution-order-and-ownership), covering storage, memory, execution and exact arithmetic. Their status varies by package and receiving context; a name in this table is not a claim of completion or enablement. Use the programme and current-state links above for the actual disposition.

| Package | Purpose |
| --- | --- |
| WP0 | Census v2 |
| WP1 | Segment store |
| WP2 | Generic record codec and views |
| WP3 | Mesh v3 |
| WP4 | Partition v2 |
| WP5 | Record publication and restore |
| WP6 | Validation consumers |
| WP7 | Heat ledger |
| WP8 | Runner, reader and materialise |
| WP9 | Composition r2 |
| WP10 | Lossless compression layer |
| WP11 | Bounded content caches |
| WP12 | Authenticated positioned sidecar reads |
| WP13 | Interval file set and catalog |
| WP14 | Live in-memory working data during the advance |
| WP15 | Worker payloads |
| WP16 | Diagnostic captures |
| WP17 | Completed-query store |
| WP18 | Parallel scheduling and worker utilisation |
| WP19 | Checkpoint-only development timing |
| WP20 | One-shot exact certificates for zero-volume slivers |
| WP21 | Exact constraint simplification and chart merging |
| WP22 | Filtered exact predicates everywhere they apply |
| WP23 | Exact arithmetic efficiency, all lossless |
| WP24 | Compiled hot kernels |
| WP25 | Heat warm start and mixed-precision certified solves |

WP0 includes the historical census and later candidate measurements. WP12's
positioned-sidecar option was assessed **not built/off**; see
[Plan23](#plan-23--authenticated-sidecar-reads-wp12). The separate WP25 heat
warm-start proposal was evaluated and disabled; its
[disposition](../docs/OPTIMISATION_REFERENCE.md#wp25-heat-warm-start-disposition)
distinguishes that proposal from mixed-precision refinement already present in LOW.

## Candidate families

[PF01–PF26](../docs/OPTIMISATION_REFERENCE.md#candidate-register) are categories
to assess for a particular workload. Some related techniques already exist in
specific routes; others are deferred or untested. They are not 26 implemented
features, and selecting a family does not authorise a benchmark or change.

| Family | Technique |
| --- | --- |
| PF01 | Demand-driven evaluation, common subexpression elimination and dependency-aware incremental rebuilds |
| PF02 | Better graph ordering, spatial indexes, candidate pruning and active-domain algorithms |
| PF03 | Bounded source, geometry and final-result caches with concurrent-safe publication |
| PF04 | Reuse symbolic structure, numeric factors, transform plans and compiled expressions |
| PF05 | Compact material histories, deferred gridding and deduplicated immutable data |
| PF06 | Contiguous layout, vectorisation/SIMD, spatial ordering and cache blocking |
| PF07 | Buffer reuse, copy elimination, loop fusion and batched state mutations |
| PF08 | Compiled hot loops, specialised kernels and eligible JIT/AOT compilation |
| PF09 | Shared-memory threads / native parallel loops |
| PF10 | Persistent process pools, coarser task batches and bounded work queues |
| PF11 | Parallel scenarios, ensembles and independent diagnostics |
| PF12 | GPU batches, residency, coalesced access, kernel fusion and staged transfers |
| PF13 | MPI decomposition, work-weighted partitioning and repartitioning |
| PF14 | Nonblocking communication, preparation/compute overlap and bounded asynchronous I/O |
| PF15 | Locality, CPU affinity, NUMA placement and load balancing |
| PF16 | Sparse storage, active sets, memory maps and out-of-core streaming |
| PF17 | Chunk/shard/access layout, lossless compression and format-conversion avoidance |
| PF18 | Incremental checkpoints, bounded delta chains and independent output cadence |
| PF19 | Preconditioning, multigrid, scaling, warm starts and Krylov-space reuse |
| PF20 | Implicit, spectral, ADI and structured/specialised direct algorithms |
| PF21 | Adaptive timesteps, event-aligned integration, multirate subcycling and solver-work balancing |
| PF22 | Adaptive meshes, nonuniform layers, conservative remeshing and coarse/fine detail |
| PF23 | Mixed precision, iterative refinement and controlled approximate arithmetic |
| PF24 | Bounded lookup tables, low-rank compression, reduced-order or learned surrogates |
| PF25 | Reduced physical equations or dimension reduction |
| PF26 | Parallel-in-time / speculative future intervals |

## Scientific-software methods

The [O01–O17 research references](../docs/OPTIMISATION_REFERENCE.md#scientific-methods)
identify useful methods from other scientific software. They are precedents and
conditional ideas, not evidence that Atlas implements or adopts those projects.

| Reference | Method considered |
| --- | --- |
| O01 | GPlates/pyGPlates: bounded geometry and rotation reuse |
| O02 | GPlately: moving-point lifecycle rather than repeated full raster histories |
| O03 | Geodynamic World Builder: evaluate compact feature descriptions lazily |
| O04 | LaMEM: structured field layout and solver-aware data organisation |
| O05 | ASPECT: adaptive resolution and matrix-free geometric multigrid |
| O06 | Underworld: batch mutations, invalidate projections, compile equations once |
| O07 | pTatin3D: precondition the coupled system, not just its expensive block |
| O08 | gFlex: exploit linearity only where the operator permits it |
| O09 | pyBacktrack: separate local column calculations and cache thermal relationships |
| O10 | FastScape: ordered implicit updates on a valid receiver graph |
| O11 | Landlab: efficient routing plus bounded TVD advection |
| O12 | Badlands: controlled remeshing and compiled heavy kernels |
| O13 | goSPL: finite-volume partitioning with explicit boundary fluxes |
| O14 | PyLith: specialised fault constraints and nondimensionalisation |
| O15 | cutde: choose dense, blocked, matrix-free or approximate low-rank evaluation |
| O16 | MAGEMin: parallel point equilibrium and carefully bounded property tables |
| O17 | GDTchron: batch independent histories without losing inherited information |

## Engineering techniques

The [engineering-method reference](../docs/OPTIMISATION_REFERENCE.md#engineering-methods)
owns the explanation, application limits and evidence for these ideas. Their
selection and implementation differ by route; none is enabled by this list.

- Measure the whole operation before changing it.
- Persist expensive prepared artefacts.
- Create visual models only when first needed.
- Load optional visual resources on demand.
- Defer optional subsystem preparation.
- Reuse stable registry and resource-discovery results.
- Share equivalent immutable definitions.
- Replace repeated categorical objects with compact indices.
- Store volume in bounded chunks and compact uniform regions.
- Build fresh fields through one controlled batch path.
- Prune spatial candidates before exact geometry work.
- Use inverted indices for repeated applicability searches.
- Reuse valid matches and coalesce intermediate updates.
- Invalidate derived data through explicit change events.
- Evaluate affected networks without duplicate notifications.
- Schedule generation and I/O with explicit dependencies.
- Give state one owner and control ownership transitions.
- Parallelise genuinely independent scenarios or frozen-input batches.
- Budget worker pools, native threads and task granularity.
- Release temporary objects when their final consumer finishes.
- Keep caches only when their measured value exceeds their cost.
- Smooth writes while keeping accepted checkpoints coherent.
- Prepare only explicitly selected regions, with resumable tasks.
- Batch drawing and minimise repeated graphics submission.
- Prepare static visual geometry once per valid revision.
- Cull invisible drawing, not invisible physics.
- Maintain coarse context and fine detail in the viewer.
- Separate viewer-region caches from active compute data.
- Use hardware-specific render paths only behind a portable contract.
- Refresh the interface according to change, not simulation ticks.
- Aggregate only material parcels that remain scientifically equivalent.
- Adapt service quality without silently changing the science.
- Move selected bulk calculations behind a native interface.
- Cache parsing and indexing separately from evaluated results.
- Separate lookup hashing from cryptographic provenance.
- Bound asynchronous diagnostics and preserve indispensable evidence.
- Version random-stream and faster-maths changes explicitly.
- Use reversible dictionaries and explicit delta bases for future streaming.
- Eliminate copies only with proven ownership and lifetime.

## 94-technique mapping

The existing [94-technique comparison](docs/COMPACT_EVERYWHERE_PLAN.md#13-game-optimisation-benchmark-the-94-techniques-mapped-michael-15-oct)
groups overlapping ideas under the packages above and records exclusions. It is a
comparison against an external ideas list, not a claim that all 94 techniques are
individually implemented or appropriate. Lighting and rendering/GPU items are
excluded from that compact-generation assessment; reduced-accuracy simulation
levels of detail are rejected for that scope. The separately considered techniques
below are mapped to packages and remain subject to their actual dispositions.

| Technique | Related work packages |
| --- | --- |
| Induction-variable stepping (2) | WP23 |
| Partial evaluation / code generation (1) | WP23/WP24 |
| Expression templates / loop fusion (1, 2) | WP23 |
| Abstract data types swap (1) | WP23 |
| Loop interchange / tiling for locality (2) | WP18/WP11 |
| Consolidating invariant bounds checks (2) | WP23 |
| Reusing invariant guard results (2) | WP23 |
| Test reordering (2) | WP22 |
| Rematerialisation (2) | WP11 |
| Speculative execution (4) | WP18 |
| External sorting (1) | WP2/WP14 |
| Memory attribution profiling (11) | WP19 |
| Integer / fixed-point arithmetic (3) | WP23 |

Other mapped families include incremental algorithms, indices and shared work;
compact data structures and packed keys; octrees/KD trees/BVHs; memoisation;
fast paths; strength reduction; avoiding intermediate structures; loop-invariant
work and common-subexpression elimination; copy elision; memory layout and
narrow types; pools; SIMD; multithreading and segmentation; asynchronous/lazy
loading; persistent caches; deduplicated replication; dictionary compression;
embedded databases; and dead-store elimination. The full comparison describes
overlap and which low-level, network or game-specific items were left out.
Consolidation of repeated checks preserves the required correctness, identity,
resource and recovery contracts and the existing cancellation/guard cadence.

## Read source selections by their role

The [Plans19–20 selection](workbench/plans19-20/README.md) and [645-member combined snapshot](workbench/combined-runtime-r1/README.md) are historical composition stages, with their own maps and receiving evidence. Neither is a universal current-source pointer. Later constructors authenticate their actual predecessors and write additive successors; they do not rewrite those maps or renew their receipts.

Plan31's [final source/emitter record](workbench/plan31/final/README.md) distinguishes its public composition from the separate private final component. The [explicit construction route](workbench/plan31/final/README.md#explicit-construction-and-data-boundary) uses a closed authenticated external context; the older context-free r2 API retains its own selection. Construction membership and Release membership differ. Source construction, prepared restart, installed production and desktop delivery retain separate entry points and qualification contracts. Select by actual consumer, inputs and authority, never by highest revision.

Source exports reuse identical public files where import layout permits. Plan02 deliberately retains adjacent `start_gate.py` for preserved callers. Sanitised public bytes do not authenticate private runs. Private inputs, checkpoints, codecs, libraries, profiles, execution receipts and coordination records are excluded; this tree alone is not a runnable historical installation.

## Shared numerical and resource contracts

| Contract | Meaning |
| --- | --- |
| Numerical comparison | Exact field/number parity unless a specific approved identity translation or bounded N9 field exception applies; no blanket epsilon. |
| Tree RSS / free memory | Existing optimisation-run limits: 12 GiB across parent and children, at least 1 GiB free physical memory. Parent-only RSS is insufficient. |
| Logical accounting | 16 GiB total; applicable 256 MiB scope caps and paid lifetimes remain. This is not virtual-memory size. |
| Start admission | Existing [by-need gate](workbench/plan02/README.md): integer `P + ceil(P / 5) + 2 GiB`, qualifying matching-command observations and prescribed booking fallback; never clip predictions. The separate [Release sizing route](workbench/plan39/README.md#behaviour-and-integration) has its own contract. |
| Record integer limit | 1 MiB = 8,388,608 bits, distinct from D5's `2**27`-bit arithmetic ceiling. |
| Continuation width | Interval 1 uses `gate()`; N≥2 uses `gate_next()`. W(N+1) ≤50% and W(N+2) ≤100% of the record limit. No 25% gate or override; an old residual is not a successor guarantee. |
| Accepted steps | 256 is a ceiling, not a convergence target or permission for a truncated interval. |
| Runtime seed | Runtime-importing processes require `PYTHONHASHSEED=0` and fail closed unless `sys.flags.hash_randomization == 0`. `-I`/`-E` ignore that setting and are unsuitable for those children; isolated non-runtime helpers are separate. |

Preserve full loaded-source identities, immutable stores and refusal/cancellation semantics. Short hashes are references only. Higher RAM for measured speed is acceptable within actual memory/admission contracts; report both. Keep comparable source/configuration, timing, RAM/disk and observation scope. Do not sum overlapping gains, extrapolate samples to whole-run proof or turn missing observations into zero.

## Composition and delivery workflow

Follow the actual command-to-consumer route: entry, imports, implementation, fixtures, startup, ownership, cleanup and downstream readers. Inspect the changed route before expensive checks. Isolated imports, mocks, hashes or unexecuted branches do not establish readiness. Reuse adequate source-bound evidence while inputs, configuration and consumer scope remain valid. New comparison harnesses retain required independent refutation and planted failures before proof.

The retained programme order is Plan31 selected-source freeze → Plan26 final fold/parity and Plan31 build acceptance → Plan34 authorised reprofile → Plan35 applicable retests → separately authorised Plan38 outcomes → Plan36 final dispositions → Plan37 authorised landing. Plan32 follows comparable measurements, including later interval peaks. Plan39 is later/separate and does not gate Plans31/35/37/38. Dependencies release no run or landing holds.

A source-bound replay candidate and an accepted final freeze/fold differ. A candidate name is not acceptance; an approved test-only replay route can precede final component integration. R1 development/smoke and ticketed parity retain their explicitly selected input generations. The final X1 generation and mandatory last-stage R1 fold preserve the approved L4 timing fallback in [Plan25](#plan-25--runtime-arithmetic-identity-l4). C18's later rebase amendment remains in the [assembly manifest](workbench/plan31/final/README.md#assembly-dependencies-and-unresolved-scope), superseding its earlier no-rebase statement.

Composition requires justified dispositions and integration of selected work, not enabling every candidate. Preserve the [conditional reprofile list and structural/safety exclusions](workbench/plan31/final/README.md#assembly-dependencies-and-unresolved-scope), including 13A's not-built status; profile scoping is not an implemented cache. WP17 may remain off without making future counts a prerequisite for the first separately authorised run. The [compiler decisions](../../docs/CODING_SAFETY.md#7-conditional-compiled-kernel-development) retain distinct denominators: about 15% residual interface CPU for K1+K2, versus about 10% interval CPU plus 5% projected interval saving per speed-driven group; K4 has a separate capacity/packaging route.

Each plan reports its actual outcome, blocker or residual state under its authentic existing identity into the final evidence/disposition record. Coverage reporting is broader than execution dependencies and creates no cyclic prerequisite. Retain unresolved, held, unbuilt, excluded and cancelled states literally. Cancelled individual post-assembly checks are not passes and do not remove assembly/fold owners' necessary checks. [Landing expectations](../../docs/CODING_SAFETY.md#6-changed-expectations-and-landing-obligations) retain bound refusal, successor state-ID and explicit cell-mean-approximation obligations. Reconcile the actual package file by file before an authorised overlay: `composed-r2` and the main package differ in both directions.

## Plan publication authority

Private execution plans and bound owner evidence govern implementation, run clearance and scientific acceptance. Public plans are dated sanitised projections, not a second execution ledger. Their differing bytes are expected after redaction, explanation and dated result updates. Reopen relevant current authority on authorised implementation resume; a summary or old manifest row cannot override a later decision. A queue ticket grants no launch authority, and release of one hold does not release another.

Reconcile execution-contract or acceptance corrections against owner evidence before reflecting them publicly. Public-only link, spelling and privacy repairs remain publication changes. Later exports preserve those repairs and newer scoped results: compare exact source/destination versions before replacement. Source maps bind implementation bytes; public prose never substitutes for maps or private evidence. Keep current status in CURRENT_STATE and history in CHANGELOG; Git retains superseded prose. This page grants no run, repin, hold release, package overlay or publication permission.
