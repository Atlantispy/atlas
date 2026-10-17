# Plan 24 — Segment summaries and buffer-pool scoping

**Item ID:** 24  
**Retained owner:** Storage; backlog 18, ideas 043 and 032.  
**Status:** WORKING NON-CANON. Conditional scoping only; neither technique is established as built or tested/disabled.  
**Target completion condition:** Use the retained q04 evidence to give each technique an evidence-bound disposition, accounting for the current L3/WP12 reader. Identify only the missing observation or gated follow-up. Do not implement a new format or pool merely to complete this scoping item.

## Authority and evidence

`T = C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10`; `S = T/fidelity-integration-20261005/claude-review-steps1-7-20261015`. The owner assessment is `S/fixes/backlog/item18-storage-assessment.md`, SHA-256 `be2e5987088760c324ad8c12bd7934e948e86db79440d760c451747017316de5`. The repository `.atlas-dev/plan-status-20261016.md` keeps backlog 18 conditional. The [accepted correction list](reviews/claude/consolidated-23-39-for-codex.md) replaces the earlier plan's invented timing, size and allocation cut-offs.

The assessment's pre-B17 profile found payload allocation/copy work below its visible top costs and predicted little benefit. Those are historical observations and estimates; q04's post-B17 profile is the applicable successor evidence. Its non-zero opportunities for other Storage work do not establish a segment-summary or pool win. Reuse q04; no fresh IV1 run is assigned here.

## Separate the mechanisms

| Candidate | Work it could avoid | Existing overlap and boundary | Current disposition |
| --- | --- | --- | --- |
| 043 summaries | Reading ranges subsequently discarded by a consumer | Named/ranged readers already select data; geometric pruning sits above storage. B17's per-view directory already removes repeated named-lookup walks. | No format change now; revisit through the Step 12 format batch if the profile gate is met. |
| 032 buffer pools | Allocation, first-touch and copying of read/decode buffers | Decoded chunks escape as owned values. L3 caches eligible data; WP12 supplies fresh verified bytes on misses. These are distinct lifetimes, not proof that a pool is redundant. | Defer pending profile; a gated microbenchmark may establish whether further work is worthwhile. |

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
