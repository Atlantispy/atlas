# Fresh interval chains, independent readers and adoption

**WORKING NON-CANON.** This is the durable contract for fresh ROOT construction,
continuation, independent reading, comparison, admission and atomic promotion.
[Current state](../../../docs/CURRENT_STATE.md) owns delivery and holds. The
[combined Plans10–12 source selection](../workbench/plans10-12/README.md) publishes
selected source, not a runnable private profile or an eligible ROOT. No run,
queue ticket, source repin, legacy migration or default activation is authorised
by this document. N9 remains PAUSED BY USER; fresh full intervals, scientific
and individual ticket holds and the 256 accepted-step ceiling remain intact.

The retained driver docstrings describe actual entry points. Source integration,
focused qualification, an adopted interval, final assembly, whole-workflow cold
recovery, scientific acceptance and canon remain different outcomes. In particular,
old design-only statements about unbuilt work do not override later scoped
implementation evidence, and a component PASS does not qualify a final runtime.

[Fresh ROOT](#fresh-root-and-legacy-migration) · [Promotion](#independent-reader-before-atomic-promotion) ·
[Lineage](#approved-lineage-and-release-b13-protection) · [Comparisons](#causal-quantity-and-field-specific-comparison) ·
[Widths](#width-gates-and-continuation-stop) · [Resources](#start-gate-by-need) ·
[Reader overlap](#serial-reader-admission-overlap) · [Accounting](#reader-live-producer-accounting) ·
[Evidence](#retained-evidence-and-completion-boundaries)

## Fresh ROOT and legacy migration

A fresh route reconstructs fixture/admission from its declared composition; it
does not load a stored start and call it fresh. The original r9 route constructs
radial differential fixture (q1-p0 pressure, material quadrature), initial partition
(max_components=4096), metrics/bounds/mesh and spatial owner, then checks initial
pressure/force. Those are deterministic functions of fixture and composition.

- **Run A, interval 0:** Workflow.create constructs ROOT on CompactRestartStore,
  using root-metadata byte segments, then seals without promotion, records
  sealed_awaiting_reader and exits. The historical ROOT contained about 24 MB of
  arrays plus 337 KB descriptor fields; this is not a changed-profile capacity bound.
- **Independent root reader:** rebuilds fixture/admission and opens ROOT with
  CollarWorkflow.open, comparing every root field/definition and funding-derived
  initial state, plus the existing per-scalar re-derivation. It uses a pending view
  and must pass before promotion.
- **Run B, interval 1:** recomputes admission under the same composition, opens the
  promoted ROOT instead of creating it, and uses native equality checks to prove
  reconstructed admission matches. It begins the next candidate, advances once,
  runs bounded_preseal, seals, records and exits. The independent reader and
  finalise/adopt chain follow; the difference ledger must pass before interval 2.
- **N >= 2:** uses the same open-then-advance pattern from the approved adopted
  N−1 head. Item 7's seed remains from ROOT. Stop-before-advance smoke is interval 1
  only, never an adopted continuation parent.

The fresh reader/runner are separate from the migrated prepared-restart route.
Keep legacy migration/D6 archival behaviour and migrated checks unchanged. The
ordinary prepared-driver branch requires CollarWorkflow with no _migration,
matching budget/query-checkpoint ownership, and refuses InitialWorkloadState or
ambiguous base/lineage combinations. It uses the parent's own checked advance
duration. Fresh continuation keeps the joined r8 module that interval 1 used;
switching to the migrated r6 module changes lineage identity without justification.
The shared observer/thread-limit context has one owner, not duplicated wrappers.

Compact stores publish ordinary successor partitions in v2 through the reviewed
'migrated or compact store' selection. ROOT's interval-0 partition retains legacy
arrays and restore dispatches explicitly on compact_partition. ArrayStore and
migrated outputs remain unchanged by that selection. Source-output pin changes
belong to a reviewed new composition, never an edit to old evidence. The original
fresh route depended on the WP17 storage companion and pending/adopt primitives;
a public document does not supply those missing private prerequisites.

Recomputation is an explicit cost of separate invocations: Run B repeats fixture,
partition, metrics and initial pressure/force admission once at interval 1. Its
original estimate was minutes rather than hours, not a measured current duration.
N >= 2 restores spatial owner from approved sealed lineage without initial_metrics;
this initial-metrics saving is once per lineage. Other reader admission, source,
identity and memory checks remain required at ROOT and every interval.

## Independent reader before atomic promotion

The catalog must not move to a candidate that its independent fresh-process reader
would refuse. A codec/pack defect, swapped chunk identity/content or defect outside
bounded_preseal must be found while the candidate is still unlisted, preserving
the old catalog without rollback. The reader is already mandatory; delaying
promotion adds no extra verification computation, but scheduling/resource overhead
must be measured rather than presumed zero.

1. The producer publishes its candidate, performs bounded_preseal (or ROOT put),
   calls seal(head_key), records interval/file/logical seal/file hash/expected
   catalog digest/head SegmentRef, and exits. Record identities and first_raised
   failure cause remain intact. seal_and_promote is for fixtures/synthetic runs,
   not this acceptance route.
2. The independent reader opens the old read-only catalog plus exactly one named,
   sealed, unlisted next-interval head through a pending resolver. It verifies
   immutable token, recomputed logical seal, parent seal equal to catalog head,
   and references confined to listed intervals. It re-derives the same required
   scalars and binds its verdict to exact sealed-file bytes and logical seal.
3. Only PASS plus the ordinary finalisation chain allows adopt_and_promote. A fresh
   store-set owner rechecks token/hash/seal, expected catalog digest, next interval,
   parent and reference closure, then uses atomic publish_catalog. The adoption
   record binds the reader verdict. A second racing adopt sees stale digest and
   refuses; foreign owner/reference, wrong interval or tampering after reader PASS
   also refuses.
4. Reader FAIL/crash/timeout leaves catalog untouched and records sealed_rejected
   with the first-raised cause. The unlisted file remains. Exclusive candidate
   creation means the next begin_interval refuses rather than overwrite/adopt it.
   Keeping/removing failed data requires an explicit decision.
5. A crash between seal and recording likewise leaves an unlisted file without
   automatic recovery. An explicitly authorised adopt-after-reader tool must run
   the same independent reader and promotion checks; an orphan is never silently
   promoted.

The reader catches swapped chunks before promotion without requiring a new storage accumulator; the separately proposed WP10 accumulator remains optional defence in depth, not a substitute for the independent reader.

The selected separate-process route releases producer memory before pending-store
verification. Keeping a SealedCandidate in the producer while spawning the reader
was rejected as the normal route because roughly 0.5–1 GB of producer memory
would remain alongside it. Peak for the sequential verification phase is the larger
of those processes, not their sum. The later admission-overlap route below permits
only the reader's independent store-free setup to overlap live production; it does
not weaken the producer-exit boundary before pending-store access.

## Approved lineage and Release B13 protection

For interval N >= 2, run_fresh_interval.sealed_lineage re-reads approved records
for intervals 0..N−1 before admitting continuation. The explicit
parent-adopted-sha256 argument authenticates adopted(N−1); it is never guessed
from a directory. The gate has no fallback. Its original cost model is 4N small
JSON records plus a catalog hash, with additional review approvals where present.

| Binding | Required agreement |
| --- | --- |
| Each interval k | runner, sealed, verdict and adopted schemas/interval/mode/entry; sealed and verdict bind the runner record; verdict PASS; adoption binds verdict and runner. |
| Every continued link k >= 1 | A passed independent width gate of the matching version; review-adopted approval where applicable. A stopped link cannot become a parent. |
| Root and parent chain | Same workflow and ROOT runner; previous head equals parent head, previous/advanced interval counts k−1/k; sealed expected_catalog_digest equals adopted(k−1).catalog_digest. For k >= 2, parent runner/adoption pins agree with the actual predecessor. |
| Catalog before open | File hash equals adopted(N−1).catalog_sha256. |
| Catalog after open | Logical digest equals adopted digest, head equals sealed predecessor entry and runner head, workflow ID equals ROOT. |
| Live opened workflow | workflow/root/head keys equal lineage, head is successor, sequence and inspected interval count equal N−1; check before physical advance. |
| Reader | Re-run the same producer lineage gate from runner(N)'s parent pin; its complete recorded lineage must equal the fresh result. Sharing this validator avoids divergent reader/producer interpretations. |

At N=2 the ROOT anchor follows interval-1 producer receipt to its run record under
the current profile route; Run A seed capture must match its receipt, verdict and
adoption. At N>=3 all earlier links also equal runner(N−1)'s recorded lineage.
A profile repin between interval 1 and 2 therefore fails closed; repin must precede
interval 1 or have a separately designed lineage route.

The lineage record (atlas.fresh-interval-lineage.v1) contains interval, workflow,
root/head keys, catalog digest/hash and per-link runner/verdict/adoption record
pins/file hashes. N>=2 runner records add lineage and parent pins. N=1 retains
its old paths/labels/record shape; reader refuses N>=2-only fields at N=1.
Readers/adoption map arbitrary interval to mode rather than indexing an
interval-0/1-only list. Launcher accepts only the explicit approved parent stage,
with the matching passed width gate, including review-adopted stages only under
the separate rule below. N>=2 stage/run/reopen names retain zero-padded interval
labels. Older records are rechecked on the next interval's lineage gate, not
retroactively rewritten at adoption.

**Review-adopted parent:** approval itself belongs inside hash-pinned lineage.
Adoption pins review_approval; the immediate parent adoption uses the explicit
argument, earlier ones use the successor runner's parent-adoption pin. Re-read
approval and repeat existing reader checks: sealed file hash, verdict hash,
approver, cause checker-defect and diagnosis-file hash. Only then may runner/sealed
records carry REVIEW_STATUS; otherwise ordinary sealed status is mandatory.
Record approval and diagnosis pins per link. A label or unpinned review note is
insufficient.

**Release B13:** compact seal/adopt is not assumed to establish a source/identity
boundary. Recheck all record and opened-catalog bindings explicitly, including
file hash before open and digest/head/workflow after open. This compensating
lineage protection is mandatory; it does not claim to repair the independent
Release-mode gap or qualify a packaged release.

## Causal quantity and field-specific comparison

The historical interval-1 ledger need not require global byte equality with r9.
It must attribute every changed physical quantity to a named approved change,
certify every differing query's bounds/width/overlap, quantify downstream heat and
transport changes, and fail on any unattributed value. Approved identity
translations are explicit mappings proved by the reader; never learn them from
changed numerical content or mask arbitrary fields.

The retained [ledger implementation](../composed-r2/helpers/ledger_fresh_interval.py)
is narrower than a general N9 comparator: its only approved change is
cube-witness-stopping. It is store-free and lists endpoint array identities;
value-level quantification is a distinct guarded reader step. Do not claim that
its digest comparison already read/quantified stored arrays.

| Comparison layer | Required causal evidence |
| --- | --- |
| Identity | Record execution/source/plan/result IDs and permitted storage-representation differences; these differ by construction and are not numerical failure alone. This does not waive physical fields. |
| Start | Resolve ROOT metadata references to logical descriptors and compare every physical leaf with r9 completed_endpoint.root_metadata. No approved change alters the start. |
| Heat inputs | Bind all three raw preadvance captures: bounds, closed_graph and mesh. Match cells by cell_id and start/end endpoint, never run ID; r9 held 6,260 cells, 1,014 face intervals and 140 finite exchanges. Mesh must agree; graph/face/exchange changes need an approved causal path. |
| Query attribution | full_cell is capture cell_id; endpoint start/end maps to start_/end_volume_bounds_m3. exact=[lower,upper,positive witness] in m³. Every rerun queried bound equals approved Step10 replay exactly; every r9 bound equals all-off r7 replay exactly. That r7 replay matches all 7,181 queries. A differing endpoint must appear in the approved difference set, be met/certified, satisfy requested width and overlap. |
| Endpoint arrays | Compare non-empty inventory by group/name/hash: collar, native, exterior, source_audit, full_collar, spatial_audit. Identical physical inputs require identical endpoint arrays. For changed arrays, a separately guarded read reports differing-element count, maximum absolute/relative difference, sign changes and nonfinite values, traced to attributed inputs. |
| Widths | Compare every exact-field census against the independently recorded reader tables and list every difference for explanation; a valid projection is not a substitute for the actual field scan. |

In the historical interval-1 replay, requested width is exactly 32,000 m³ from
max_volume_error_m3; certification is status met, upper−lower within that width,
and upper=0 or witness>0. This is the declared fixture criterion, not a universal
new tolerance. The retained ledger bounds input records at 64 MiB and verifies
raw capture length/hash before decode. Identical-input same-call re-proofs establish
method parity, not a new license for changed inputs. FAIL blocks interval 2.

N9 has its own [bounded width/field contract](../workbench/plan04/BOUNDED-WIDTH.md)
and authentic-reader tool selection. Only its specifically approved pose/header
changes may use their field-specific exact/outward bounds. Preserve units,
quantity type, original radii/enclosures and exact fields. Exact rational values
have no generic binary64 ULP tolerance; unchanged heat fields retain exact/bit
comparison where required. Do not import N9 exceptions into unrelated pressure,
heat or scheduling comparisons. Full coupled C4, actual successor reader/width
tables and pressure/heat propagation remain separate unproved scope.

## Width gates and continuation stop

Every compact integer is limited to **1 MiB / 8,388,608 bits**. The independent
reader scans authentic canonical record streams by kind/root field, recording
count, maximum numerator/denominator widths and trajectory count without parsing
huge integers. A field missing at ROOT uses W0=0, the conservative larger projection.
For an approved changed input the census can differ from r9, but must be explained.

After interval N, the approved linear rule is:

- W(N+1)=2W(N)−W(N−1) <= 50% of the integer limit;
- W(N+2)=3W(N)−2W(N−1) <= 100% of the limit.

There is no override or fixed 25% ceiling. A failed continuation gate still allows
the independently accepted completed interval N to be adopted and reported
GATE_STOP, but it is never a parent for N+1. The historical status label retains
its interval-2 wording at every N for record compatibility. The old watch
projection W1≈24–25%, W2≈43–49%, W3≈62–73%, W4≈80–98% would stop before IV3:
measured W2 would need to be about 37% or less to keep next width <=50%. These were
projections, not authentic successor tables or permission to run width options.

## Start gate by need

start_gate.py replaces a blanket 10 GiB launch requirement and the obsolete
TOTAL+5 GiB queue threshold. The launcher derives need from successful matching
command/stage measurements, or explicit booking if none exists:

**start need = predicted peak×1.2 + 1 GiB free floor + 1 GiB small-job allowance.**

Use the largest successful matching-command peak; failed runs cannot lower it.
Match route/workers/inputs and include parent/worker contributions. Record basis,
prediction, observed peak and warning; >20% excess peak is a warning. The encoded
gate travels last in guarded producer/reader commands and each child re-admits
against its own available memory. Launch without a gate refuses. Reader repeats
its gate after producer release/authenticated handoff, before open_pending, recording
both observations. Do not inflate booking to pass a superseded fixed rule.

The **12 GiB RSS ceiling is per guarded tree**, **1 GiB free-physical floor is
system-wide**, and **16 GiB logical / 256 MiB retained scope** are separate controls.
Concurrent logical ceilings are not jointly available RAM; a reader-induced free
floor trip can abort production. Book actual producer+reader+workers+guards+launcher
from measured peaks, not an invented aggregate RSS equation. The old reader's
~0.45 GB tree RSS/~0.9 GB logical observations are not universal changed-profile
bookings. The 1.5× elapsed-booking rule requires escalation/stop-continue judgement,
not automatic kill or a RAM multiplier. Guard has no general hard wall timeout;
launcher death/detachment does not prove guardian/workload exit.

## S1: completed queries per guard stage

F.QueryStages observes exact completed-query counter deltas (hits, misses,written,
incomplete), owner opens and last unflushed count for every owner open in a guard
stage. No live owner means null counts, never invented zeros. It wraps neither
owner nor guard/query; phase names/order stay unchanged. This observation does not
change physical results, admission or execution order.

## Reader live-producer accounting

A reader's RUN.new_retained_scope contains a named live-producer child: the four
PRODUCER_PURPOSES charge there rather than against the 256 MiB retained aggregate.
The selected scope still carries a parent-charged 2 GiB allowance. This is accounting,
not producer data or an independence breach inferred from a misleading cold-scope
comment; do not silently remove it. Measure its contribution to concurrent booking.

S8 records that child beside retained_scope as optional retained_producer with
before_close and after_close snapshots at the same two lifecycle points. Existing
retained_scope schema/validators stay unchanged. Older receipts without the sibling
field remain valid; when present it must be complete and null refuses.

producer_accounting/validate_producer_accounting require an exact field set:
scope_id, producer_limit_bytes, producer_bytes, producer_peak_bytes,
producer_refusals and producer_purpose_bytes/producer_purpose_peak_bytes maps.
Scalars are nonnegative integers and bytes<=peak<=limit; each map has at most 4,096
string keys of length 1..256 with nonnegative integer counts. Purpose bytes sum to
producer_bytes; scope_id matches the retained before_close scope. Both reader
validators invoke validate_retained_producer after existing retained checks.

This is observation only: no charge, limit, order, result, store schema or timing
policy changes. The receipt adds two small bounded dictionaries; maps normally
have a handful of purposes. Original S8 evidence retained 13+14 base tests and the
same candidate tests plus 4 new shape/refusal/old-receipt/fresh-adoption wiring tests;
null refusal and wiring coverage corrected two review findings. Ruff comparison
introduced no findings. These are historical focused results, not a rerun here.

## Serial reader admission overlap

Phase 2 starts the current producer and its **independent serial reader** together.
Reader FRESH.admission uses its own pinned sources, fresh budget/artifact directory
and source fence/capture, with no producer catalog/store/output as input. Admission
happens before waiting. Only producer-dependent validation and pending-store access
happen after the gate. Item 7 producer reuse -> Item 21/N5 continuation -> phase 2 is
the retained order. Reader recomputation remains independent of producer cache.
The implementation is process ordering, not flush/template overlap or a new
in-process thread-pool pipeline.

| Boundary | Required action |
| --- | --- |
| Before handoff | Reader waits store-free, checking cancellation/guard state, launcher PID+creation-time liveness and a bounded deadline based on expected advance plus margin. |
| Producer release | Successful producer exit, clean STOPPED guard, empty owned process tree, frozen receipt/runner/seal and guard_postcheck with no failures. Retain RF.command-equivalent store-free producer_inputs preflight. |
| Publish | Exclusive Windows gate.partial write/flush/fsync then reviewed atomic rename to GATE. Existing destination refuses; exposing a partially written open('x') file is insufficient. Required sharing-violation retries remain. Referenced files cannot be replaced afterwards. |
| Authenticate | Closed exact fields bind attempt/stage/interval/profile, producer/guard/runner/seal pins, exact waiter PID+creation time, launcher identity and nonce. Reader validates expected process/attempt and referenced records, records receipt pin, reruns unchanged producer_inputs and memory start gate, then opens pending sealed store. |
| Finalise/adopt | Reader receipt has complete closed gate bindings and matching producer_receipt_sha256. Independent numerical verification, finalise and atomic adoption remain mandatory; admission/gate alone cannot adopt. |

Freeze the whole pipeline source manifest through every participant exit and
finalisation; the admitted-ahead reader lengthens its source verification window.
Retain live source/loaded-code checks. New gate fields change reader-receipt hashes;
compare required exact fields and approved identity translations rather than demand
old whole-receipt equality or repin historical bytes.

A once-only sequential fallback is available only by specific approval for proven
non-data overlap failure (for example launcher loss, cancellation or free-floor
trip) with complete producer/failed-reader exit evidence. Use a new sibling reader
directory and pinned approval, repeat every independent/source/receipt/store check,
and preserve failed overlap evidence. Data, identity, source and uncertain-cleanup
failures refuse recovery. Never start the next producer speculatively.

The first comparable arms fix ALE serial at interval 1 and ordinary successor
intervals, separately from retained pressure auto. Record InterfaceParallelPolicy
free_cores/workers/declines with/without overlap; load-sensitive auto may choose
fewer workers beside a reader. A future parallel-ALE/reader claim needs its actual
source-bound bit-parity and independently authorised worker comparison, not parity
from another component. Parallel initial-metrics readiness does not enable a
parallel overlapping reader.

Phases 1/3 stay deferred; their post-Item 7 projections were about 60 s each and need
separate consideration/authority, never automatic activation after phase 2. Early
IV1 projections (~929 s serial metrics/~950 s with startup hidden, 50–100 s contention,
800–900 s net; ROOT producer ~838 s) were estimates. Hidden admission is bounded by
producer work; do not add two readers or phase 1 saving to the same overlap.
Critical path is approximately max(producer work,reader admission)+remaining
verification/finalisation including contention/overhead. No interval-wide gain is
established by ROOT-only evidence.

Measure both complete producer/reader/finalise/adopt cohorts under comparable inputs,
frozen code/cache/queue conditions and one observation method. Report wall totals,
components, actual worker decisions, failures and sampled RAM/disk peaks together,
including observer overhead/blind spots. A faster component is not net acceptance.
Any new smoke/timing route needs its existing reviewed queue request and authority;
worker comparisons need required EXCLUSIVE conditions. Focused challenges include
partial/garbled/stale/premature gate, wrong process/attempt/receipt, launcher loss,
wait expiry/cancel/free-floor refusal before store access, Windows replacement/race
handling, missing/extra finalise fields and fresh-directory fallback. Reuse adequate
unchanged evidence; do not run an unrelated suite or turn this list into new authority.

## Retained evidence and completion boundaries

The selected private phase 2 implementation/integration is complete within its
recorded scope. The q46 original-profile ROOT pair passed exact parity:
1,701.781→1,172.375 s wall (31.11% less), sampled arm-tree RAM +74.23%. It is one
ROOT-only pair, not interval/ALE, repeated-run or whole-programme gain. Earlier
failed native-entry evidence remains preserved. The separate q47 producer-only
reuse smoke recorded 969 hits/0 misses; it ran no reader and stopped before advance,
so it is not an adopted parent or reader qualification.

Combined selected lf3 heat retains H1a/H1c, H2, L1 and physical-order repair; H5a, D5, P4
stay disabled. Focused qualification recorded 27 orchestration tests, 3 native-entry
cases and 4 heat cases. q46/q47 bind the original profile, never the new combined
profile's ROOT. The combined profile requires its own eligible ROOT. Heat seam
save/restore is not full-workflow cold recovery. Actual interval proof, final
assembly and full cold recovery remain Plans31/38; final combined timing remains
Plans34/35. These retained contracts consulted no new external physical paper or
benchmark in this scheduling consolidation.

The [Plans10–12 source map](../workbench/plans10-12/SOURCE-MAP.json) identifies 239
native and 390 helper members and declares public_runtime_compatibility=false.
Its selected source members include fresh runner/reader/launcher, prepared driver,
reader-overlap gate and the retained store-free ledger; it does not bind this
Markdown or the consolidated design notes. Old receipts/source maps remain
unaltered. Use the [current delivery summary](../../../docs/CURRENT_STATE.md) and
existing plan/source owners for changed selection, approval and remaining work.
