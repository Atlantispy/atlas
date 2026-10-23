# Plan 24 — Segment summaries and buffer-pool scoping

**Item ID:** 24  
**Retained owner:** Storage; backlog 18, ideas 043 and 032.  
**Status:** WORKING NON-CANON. Assessment complete, reviewed 24 October 2026: **neither build gate is established; both mechanisms remain NOT BUILT**. No source, format, runtime or default change.
**Target completion condition:** Use the retained q04 evidence to give each technique an evidence-bound disposition, accounting for the current L3/WP12 reader. Identify only the missing observation or gated follow-up. Do not implement a new format or pool merely to complete this scoping item.

## Disposition — reviewed 24 October 2026

**Neither build gate is established; both mechanisms remain NOT BUILT.** This is a
scoping outcome from the retained post-B17 q04 sealed-reopen profile, not a measured
failure of either proposed optimisation. The reader files inspected in the selected
combined source generation match the measured reader. No new profile, simulation,
microbenchmark or interval-data read was performed. No L3 or WP12 saving is added.

| Retained q04 accounting | Seconds | Denominator | Share |
|---|---|---|---|
| Ranged-read calls | 3.367 | Whole profiled reopen: 26.458 s | 12.7% |
| Selected allocation/copy operations | 0.0808 | Whole profiled reopen: 26.458 s | 0.31% |
| Broader selected operations, including wrapper bookkeeping | 0.3901 | Whole profiled reopen: 26.458 s | 1.47% |
| Selected allocation/copy operations on the storage path | 0.0204 | Accounted storage path: 6.019 s | 0.34% |
| Broader selected operations on the storage path | 0.2283 | Accounted storage path: 6.019 s | 3.79% |

These are accounting totals from the instrumented profile. They are neither
measured savings nor complete allocation-cost bounds. The plain reopen took
15.670 s; whole-run profiling overhead does not establish each operation's
uninstrumented cost. The approximately 5% gates concern relevant read time, so
the whole-reopen percentages alone cannot decide them.

- **043 summaries: gate not demonstrated.** All 8,294 native page-miss calls have
  the expected immediate cache-reader caller. Source inspection supports canonical
  whole-record identity rendering, structural validation and authenticated column
  scans, with no demonstrated content-predicate storage pruning opportunity.
  The retained trace nevertheless has one unexplained value-reader caller edge
  and incomplete attribution through generator resumption. It contains no
  per-read discard measurement, so it does not establish exhaustive attribution
  or a measured zero discard cost. No summary footer is selected for the Step 12
  format batch. Reconsider if a real predicate-applying storage consumer shows
  discarded ranged reads reaching 5% of its read time.
- **032 pools: material benefit unresolved; not built.** Transient mutable staging
  buffers exist in the raw-reader and access helpers before their mandatory owned
  copy-outs. Reusing staging could retain the existing escape copy without adding
  one; the original claim that no poolable transient exists was incorrect.
  The 0.3901 s accounting omits some allocating wrappers and does not isolate
  constructors, backing allocation or first-touch cost. Reusing a stream's
  bytearray object does not prove reuse of its backing capacity. Retained pages,
  SQLite-owned blob results and immutable copy-outs remain distinct constraints.
  No material removable allocation cost or approximately 5% gate is established,
  so no pool trial is selected. Reconsider when the selected-build profile
  attributes sufficient removable cost to specific buffers, or a reader/format
  change creates a material new opportunity.

The missing observations are named above; no new run is requested. A later
candidate still requires authenticated exact values, unchanged refusal and
copy-out behaviour or sound leases, booked idle/active capacity, cancellation and
release, plus measured construction/read cost and any disk growth. All existing
run and scientific-acceptance holds remain.

## Authority and evidence

`T = C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10`; `S = T/fidelity-integration-20261005/claude-review-steps1-7-20261015`. The owner assessment is `S/fixes/backlog/item18-storage-assessment.md`, SHA-256 `be2e5987088760c324ad8c12bd7934e948e86db79440d760c451747017316de5`. The repository `.atlas-dev/plan-status-20261016.md` keeps backlog 18 conditional. The accepted correction list (private evidence unavailable in this public snapshot) replaces the earlier plan's invented timing, size and allocation cut-offs.

The assessment's pre-B17 profile found payload allocation/copy work below its visible top costs and predicted little benefit. Those are historical observations and estimates; q04's post-B17 profile is the applicable successor evidence. Its non-zero opportunities for other Storage work do not establish a segment-summary or pool win. Reuse q04; no fresh IV1 run is assigned here.

## Separate the mechanisms

| Candidate | Work it could avoid | Existing overlap and boundary | Current disposition |
| --- | --- | --- | --- |
| 043 summaries | Reading ranges subsequently discarded by a consumer | Named/ranged readers already select data; geometric pruning sits above storage. B17's per-view directory already removes repeated named-lookup walks. | No format change now; revisit through the Step 12 format batch if the profile gate is met. |
| 032 buffer pools | Allocation, first-touch and copying of read/decode buffers | Decoded chunks escape as owned values. L3 targets eligible retained data; WP12 remains unbuilt/off. These are distinct lifetimes, not proof that a pool is redundant. | Not built: removable allocation cost is unresolved; reconsider only with qualifying evidence. |

WP12 activity does not automatically exclude a pool. Conversely, neither a cache label nor allocator activity establishes a benefit. Identify the actual buffers, ownership and copies in the selected reader before proposing reuse.

## 043: summaries gate and format boundary

The owner gate is ranged reads followed by discard accounting for **at least 5% of read time** on the relevant q04 evidence. Whole-array restoration cannot gain from chunk pruning; the assessment's expected share is about 0%, not a new measurement. Record missing caller/discard attribution explicitly rather than inferring it from call counts alone.

A summary footer changes persisted metadata and identities. A1 preserves those identities within the present generation, so any justified design belongs to the **Step 12 format batch**, alongside its coordinated format changes. This plan selects no 32-byte float footer or alternative representation.

Before a later format proposal is adopted, specify the actual typed values and exactness, authenticated summary/content binding, version compatibility and reader refusal rules. Approximate metadata must not silently decide an exact exclusion. Include construction/read cost, disk growth and the consumers that can actually skip data; no unsupported 5-second or percentage-of-file-size acceptance threshold is introduced.

## 032: pool gate and ownership boundary

From q04, compare the self time of buffer creation, joins and copies with decompression and hashing on the read path. The existing trigger is allocation/copy work reaching **about 5% of read time**. Only then does the assessment call for a ticketed microbenchmark of decompression into a reused booked buffer versus fresh allocation, using IV1-sized chunks.

A candidate must preserve copy-out semantics or an explicitly sound lease contract: a caller retaining a decoded chunk must never see bytes overwritten by a later read. Account for idle capacity as well as active scratch, admission/refusal, cancellation and release. The owner assessment requires byte-identical results and no escaped mutable pool storage. Neither a non-zero allocation count nor a synthetic allocator result alone justifies integration.

## Bounded procedure and completion

1. Bind the applicable q04 profile, reader source/configuration and workload. Reuse its retained measurements; identify how L3/WP12 change the relevant path without adding overlapping savings.
2. Extract only the missing ranged-read/discard and allocation/copy observations. Report each gate as met, not met, or unresolved with the exact missing evidence. A below-gate or absent result is not a completed implementation test.
3. If a gate is met, return the bounded follow-up to the existing owner/coordinator: summaries to Step 12, pools to the authorised queued microbenchmark. Keep existing run holds and resource controls. This document issues no ticket or fresh scientific run.
4. Record the disposition and evidence pointers in the existing Storage and final-composition records. Any later built candidate needs its own exactness, lifetime, identity and measured-cost evidence before selection.

Scoping is complete when both ideas have a justified current disposition and any unresolved evidence is named. “Deferred/not built”, “measured below gate”, “candidate built” and “tested/disabled” remain different states. No storage-format or pool implementation, automatic peer review or final N12 acceptance is claimed by this rewrite.
