# Plan 23 — WP12 authenticated sidecar reads

**Item ID:** 23  
**Retained owner:** Storage; backlog 14 / WP12 D1.  
**Status:** WORKING NON-CANON. Assessment complete: **UNBUILT/OFF** (see Disposition). No source, runtime or default change.
**Target completion condition:** Establish the code-quoted guard equivalence before implementation, then demonstrate exactness, resource accounting and the existing 5% net A/B gate on the selected live reader. Enable only if those conditions hold; otherwise retain an evidenced off/deferred disposition. This document authorises no build or run.

## Disposition — 23 October 2026

**Assessment complete; UNBUILT/OFF.** The retained profile and plain timings support a scoping estimate for the selected r4 reader. No new timing run, implementation, queue ticket or interval-data read was performed. This is a decision not to build the conditional option, not a measured performance failure.

The source review corrected the proposed reuse count. The named production route establishes **one mandatory sealed, cache-eligible reopen per successor store (N = 1)**: the independent fresh-process reader. Before the child's continuation calls `Workflow.open`, `start_next_interval` switches the store facade to its candidate. `SegmentView.cache_identity()` then returns `None`, disabling the native page-cache route to which WP12 would attach. The producer's pre-seal check uses the same ineligible path. Additional explicit sealed-reader executions are workload-dependent; a resume does not automatically add an eligible reopen. The earlier N = 2 estimate remains a sensitivity case, not the established production count.

The required `locked.check()` compares the opened handle with the current path on every read. At the profiled depth it entails seven file/ancestor `lstat` calls, a final path `stat`, and an `fstat`: **eight path-stat calls plus fstat**. Its estimated cost is 176 µs; the replaced SQLite/checksum/decode/digest/bookkeeping work is estimated at 250–404 µs per miss. Neither proposed sidecar cost nor its eventual production path depth was measured.

| IV1 sealed heat reopen | Value | Status |
|---|---|---|
| Base reopen, plain | 15.67 s | MEASURED mean of 15.895 / 15.445 s |
| Native misses served by `_bound_chunk` | 8,294 | MEASURED count |
| Net saving at N = 1, central (pessimistic / optimistic) | −3.1% (−9.8% / +5.1%) | ESTIMATE; gate ≥ 5% |
| Net saving at N = 2, central (sensitivity only) | +0.1% | ESTIMATE; second eligible read not established |
| Net saving with unlimited reopens, central | +3.3% | ESTIMATE |
| Added disk per IV1-sized interval | ≈158 MiB | ESTIMATE |

Positive percentages mean time saved; negative percentages mean more time. The model is `(M × (old miss cost − new miss cost) − open cost − build cost / N) / base reopen time`. The central inputs are 8,294 misses, 310 µs replaced, 241.4 µs added, 0.05 s per open and 1 s to build. The optimistic case uses the entire 404 µs profiled miss cost as plain time, lower added work and lower build/open costs. It marginally clears 5%; whole-run profile inflation was about 1.7×, but that does not establish inflation for each component. These scenarios are assumptions, not measured bounds or a proof that the gate is impossible. They do not justify implementing the option under the retained guard contract.

- **Declined variant.** Moving the parent-directory walk to open time weakens the per-read link/reparse refusal and remains rejected. Its central saving is about +3.2% at N = 1, or +6.4% in the N = 2 sensitivity case. The unchanged 256 MiB cap also limits eligible arrays; projected IV2 size is not a measurement.
- **Guard analysis.** The selected-source analysis records authentication of served bytes, cache-disabled verification, exact length, unused/swapped content, opened handles, caps and charges. It is not implemented guard equivalence: lazy authentication would defer unused-chunk corruption refusal from open to first use. That distinction, the required refuter, fault controls and A/B gate remain prerequisites for any future implementation; none was executed or waived by this no-build disposition.
- **Reconsideration.** Plan 30 owns the separate, post-assembly held-handle freshness design. WP12 may be reconsidered only after guard-equivalent freshness makes the repeated ancestor walk redundant, with a newly established eligible reuse count and net benefit. This outcome neither starts that work nor releases a run hold.

## Authority and current evidence

`T = C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10`. Storage's design/assessment root is `T/fidelity-integration-20261005/claude-review-steps1-7-20261015` (`S`). The controlling design is `S/fixes/backlog/wp12-design/DESIGN.md`, SHA-256 `99592b641eace6c425974e7345d4493b6810efc4ef63dc95cbcedbdceced9845`, especially §§0–6. Current order/owner status is in the repository `.atlas-dev/plan-status-20261016.md`, Storage row; q04 supersedes the older zero-read prediction.

This plan retains the conditional design requirements; the original design and review evidence are private. The filename retains the backlog's old “mapped reads” label. The approved successor uses **positioned reads into fresh immutable `bytes`, no mmap**.

q04's retained measurements recorded 8,294 native misses, 5,760 re-misses and 99.2% of misses in `int.bytes`; the both-profiler split used for this estimate attributes 3.3518 s to `_bound_chunk`. These identify an opportunity, not a measured successor saving. The earlier raw-sidecar component performs an eager whole-array authentication and maps each read; it is not the approved wiring. No claim of zero allocation, doubled whole-file RSS or generic EOF exception equivalence is used here.

## Guard equivalence — required before implementation

The selected-source analysis covers `_chunk`, the authenticated `_native_binding` walk, `_verify_column_page` and the cache-disabled branch. Any future implementation must establish:

1. The chunk ID comes from the authenticated index walk and is the same typed digest checked by `_chunk`: `sha256('atlas-typed-chunk-v1\0' + descriptor + '\0' + raw)`. Preserve the descriptor, dtype, shape, exact range and chunk identity.
2. Every served byte is checked before use against that ID. In particular, `ContentCache.offer_verified` returns before verification when disabled, so `_verify_column_page(key, page)` must be called explicitly before offering or borrowing the page. The immutable checked bytes are the bytes consumed.
3. Explain the eager pass's coverage of unused chunks, exact file length and trailing bytes. Retain cheap length checks at open; an unused corrupted chunk must refuse when later used. A swapped/present-but-wrong sidecar raises `ContractError`, never silently falls back.
4. Preserve the binding-named store/file identity, share-read lock, `locked.check()` per read, changed-file refusal, caps, and charge/borrow lifetimes. Authenticate the opened source; a pathname stat alone is insufficient.

The analysis is complete for the no-build assessment. Implemented equivalence and its required refuter remain prospective D1 conditions.

## Prospective mechanism and integration boundary

If reconsidered, work follows L3 and uses the merged B17 rev4 + item14 reader. The design records `segment_store` a90ef8f3, `record_views` a6bbb81d, `content_cache` de7d3e45 and `raw_sidecar_store` e8ad994b as its input identifiers. These prefixes are navigation aids; the owner must use full selected-source pins at implementation. No invented `T/st` reader or test path is prescribed.

- In `record_views._cached_native_owner`'s miss branch, read the requested range from the locked sidecar handle under the store lock into new `bytes`, build `_NativeChunkPage`, verify explicitly, then offer/pin it.
- Add the design's `range_digest`/`read_bytes` route to the existing `RawSidecarStore`. It retains caps and lock checks and books scratch at the actual chunk size. Preserve the 8 KiB per-open-handle accounting and report actual versus booked use.
- Select `int.bytes` only; keep `MAX_ARRAYS` and the 256 MiB file cap. Missing/oversized sidecars or refused scratch admission decline visibly to `_bound_chunk`. Invalid authenticated content refuses instead.
- Attach one sidecar store to the sealed view using `cache_identity()`; retirement closes its handles consistently with outstanding ownership. Cover failure/cancellation cleanup through the actual lifetime contract.
- Build explicitly once after sealing, through the existing no-overwrite build/publish route (temporary file, fsync, no-replace rename). Take roots from the store or arguments. No implicit build during a read and no historical receipt rewrite.

L3 removes repeated verification on eligible cache hits; WP12 removes SQLite/decode work on eligible misses. Their effects overlap and must not be added arithmetically. The raised page-quota alternative is not adopted.

## Focused validation and completion

The no-build assessment is complete. All implementation validation below is prospective and remains required if WP12 is reconsidered. Reuse unchanged q04/owner evidence; no full interval is launched to re-establish it. The owner uses the existing queue, seed-zero/runtime-source rules and unchanged memory/numerical limits.

- Compare every selected IV1 `int.bytes` chunk byte-for-byte with `_bound_chunk`, and retain equal reopen result identity and the five-field comparison. Check real read/decline counts rather than treating the design's projected counts as results.
- Exercise the existing M1–M8 obligations: used and initially unused byte flips, truncated/extended file, swapped sidecar, wrong offset, removed explicit verifier with cache disabled, over-cap decline, disabled/non-Windows fallback, and refused scratch reservation. Each must produce the specified refusal or visible safe decline.
- Obtain the one required refuter on the exact candidate's equivalence and accounting. Check scratch/handle retirement and actual versus booked RAM/disk, including failures.
- Run the authorised plain A/B with comparable source/input/cache conditions. The existing acceptance gate is **at least 5% net reopen saving, including sidecar build/open costs**. Record L3 and WP12 alone/together as required by the design; separate measured figures from projections.

The conditional plan closes with this evidenced UNBUILT/OFF disposition. Completion of a future implementation would additionally require source-bound exactness/refuter evidence and the measured gate decision. A guard-equivalent design is not a built optimisation; a component result is not final N12 acceptance. Fresh full intervals remain held under the master plan.
