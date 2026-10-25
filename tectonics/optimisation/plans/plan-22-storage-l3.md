# Plan 22 - bounded verified-page carry between read batches

**Status: WORKING NON-CANON. Implementation reviewed and source-integrated as an optional candidate. An earlier reader measured a 20.9% mean real interval-1 reopen gain; the newer port's qualification, retiming and final selection remain pending. L3 is UNCERTAIN / NOT ENABLED in the current selection. Issue #48 remains open.**

The [source overlay and receiving checks](../workbench/plan22/README.md) record the exact implementation revisions and their evidence. This plan defines the mechanism and acceptance contract. Publication does not replace the selected runtime, change an execution hold or qualify a real interval.

## Opportunity and limits of the evidence

The retained interval-1 sealed-heat count probe observed 65,995 cache lookups, 57,673 hits and 8,322 misses (8,294 native and 28 small-path misses). Of the hits, 57,424 crossed read batches: 31,814 small-path and 25,610 native. There were 7,183 outer batches on one segment, no outside-batch lookups in that probe, and equal result identity and five fields. A simulated 128-page LRU described access locality; it did not implement retention or prove its lifetime and memory bounds.

Multiplying 57,424 cross-batch hits by about 28.776 microseconds of profiled verifier cost gives 1.652 seconds, or about **6.25% of the 26.458-second profile**. This is an inflated profile-based opportunity estimate, not a measured L3 speed gain. It passed the 1% build-opportunity gate. The broader 5.242-second / 19.8% estimate includes lookup, scratch, key, pin and cursor work and is an upper estimate. Neither establishes an I/O-wait percentage.

The earlier plain reopen means, 46.127 seconds live, 17.419 seconds with B17 and 15.670 seconds with B17 plus item14, belong to those earlier improvements. They are not L3 results and are not added to its projected benefit.

## Mechanism and trust boundary

The existing reader books an optional `record-batch-page-borrows` registry and pins up to 128 verified immutable pages for one outer read batch. L3 keeps that registry for the next batch of the **same view and segment**:

1. Complete the outer batch and its closing freshness check before carrying anything. Trim oldest pages to the per-view bound, then carry or refuse at the process bound.
2. Keep optional carry available to the pressure reclaimer while `verified_read()` acquires its required entry reservation. Adopt the remaining registry only after entry succeeds; no page is served earlier. Entry refusal closes any remaining carry and propagates the error.
3. Keep per-access liveness, freshness, cancellation and the verified-read closing checks. Outside a batch, `_batch_pages` is absent and reads follow the ordinary verification route.
4. On an exception, including a closing-check exception, retain no reusable carry. Data retained by failed frames or tracebacks keeps its existing paid ownership until those references disappear.
5. Drop carry on close, failed entry, uncached fallback, trim, cap refusal or scope close. Under pressure, evict unpinned pages first; if insufficient, release idle carried registries and evict again. A busy view is skipped using a non-blocking lock; its active batch already owns its pins.

A carried hit deliberately avoids repeating the typed digest of the same immutable pinned object. It does not bypass the segment's freshness boundary. Keys are `(name, start)` within one segment, not a global cache keyed only by interval or offset.

`CompactRecord.close` and `CompactMesh.close` release their segment readers after checking outstanding borrows. The mesh port preserves the current streaming encoder used by capture writers. Repeated close keeps its existing behaviour. The touched-page tracker is a deduplicated set: an evicted or closed page removes itself, so scanning a long batch cannot leave an unbounded list of closed wrappers behind the 128-page registry.

## Memory contract

| Limit | Behaviour |
| --- | --- |
| Carried pages | At most 128 per view |
| Carried booked bytes per view | 10 MiB; trim oldest first |
| Carried booked bytes per process | 32 MiB; locked accounting, refuse/drop/count excess |
| Existing page-cache quota | 64 MiB; unchanged |
| Additional carry reservation | None; the existing registry and holders fund their lifetimes |

Booked carry is the registry charge plus each pinned holder's `charged_bytes`. That value includes its underlying allocation and holder overhead; do not describe a cache-hit share as only its carrier. The parent cache entry is not added again. Two views pinning one allocation can count it once per view, which makes admission conservative. Raw bytes and booked bytes are different measures.

The registry requests 266,240 bytes before its owner overhead. At 65,536 bytes per chunk, 128 pages are at most 8 MiB raw. These bounds do not raise the retained-scope cap, run budget or physical-memory guard. Keep active-batch wrappers bounded too; a carried-byte counter alone cannot prove that.

## Required checks and selection

The focused controls cover exact keys and values; per-view trim and process refusal; close with surviving references; entry/body/closing refusal; outside-batch reads; fallback; pressure reclamation; scope close; and the repaired wrapper-lifetime and repeated-close cases. Planted faults must fail their intended controls. Preserve unchanged-suite failures and skips explicitly rather than describing equal results as an all-pass suite.

The earlier **A/B ABBA** comparison on the interval-1 sealed heat store selected its tested reader: mean reopen time fell from 16.266 s to 12.864 s with exact result identity preserved. The gain's mechanism remains unproven. The newer reader requires its own combined qualification and retiming with authenticated source bindings and ordinary run admission. A request or result for an older candidate does not qualify a corrected successor.

Select L3 only when every condition holds:

- Both B samples beat both A samples, and the mean gain exceeds the larger within-arm range.
- Every sample has exact result identity and five fields, correct source binding and zero budget after close.
- B's page misses do not exceed A's; there are no new required refusals or carry refusals.
- B's peak RSS is no more than A's plus 48 MiB (the 32 MiB process cap plus 16 MiB).

If B is slower by more than the larger range, record a regression; otherwise retain **UNCERTAIN / NOT ENABLED** unless all selection conditions pass. Report raw timings, variability, misses, carried raw/booked peaks, pinned bytes, physical and process-tree peaks, trims, refusals and drops by reason. Reduced verification counts alone are not a net-benefit measurement. Neither the 1% opportunity gate nor WP12's separate 5% gate replaces this selection rule.

## Related storage work and completion

[Plan23](plan-23-storage-mapped-reads-wp12.md) remains UNBUILT/OFF. Its published assessment establishes one eligible sealed reopen and a central estimated net saving of -3.1%; the earlier N=2 / +0.1% figures are sensitivity cases. There are no WP12 C/D arms in this L3 comparison. Any later sidecar proposal must preserve typed-byte authentication, cache-disabled verification, unused/truncated/extended/wrong-file checks, bounded resources and the separate net-of-build/open gain criterion.

Plan30's B17/item14 inclusion remains open until the final assembly. A `record_views` successor legitimately changes that row: preserve and compare the other members and run the relevant receiving checks; never silently repin the original inclusion result. The original candidate and corrected private/public compositions have distinct identities and evidence.

Completion requires a measured L3 disposition, integration of that evidenced disposition into the final generation and verification of its consumers. Source publication alone completes none of those outstanding steps. Exact scientific values, retained-scope and run limits, restart identities and the 256 accepted-step ceiling remain unchanged.
