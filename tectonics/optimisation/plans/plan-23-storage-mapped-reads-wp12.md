# Plan 23 — WP12 authenticated sidecar reads

**Item ID:** 23  
**Retained owner:** Storage; backlog 14 / WP12 D1.  
**Status:** WORKING NON-CANON. D1 accepted conditionally; successor wiring is design only, not built or integrated.  
**Target completion condition:** Establish the code-quoted guard equivalence before implementation, then demonstrate exactness, resource accounting and the existing 5% net A/B gate on the selected live reader. Enable only if those conditions hold; otherwise retain an evidenced off/deferred disposition. This document authorises no build or run.

## Authority and current evidence

`T = C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10`. Storage's design/assessment root is `T/fidelity-integration-20261005/claude-review-steps1-7-20261015` (`S`). The controlling design is `S/fixes/backlog/wp12-design/DESIGN.md`, SHA-256 `99592b641eace6c425974e7345d4493b6810efc4ef63dc95cbcedbdceced9845`, especially §§0–6. Current order/owner status is in the repository `.atlas-dev/plan-status-20261016.md`, Storage row; q04 supersedes the older zero-read prediction.

This plan applies the agreed Plan 23 corrections (private evidence unavailable in this public snapshot) and Codex response (private evidence unavailable in this public snapshot). The filename retains the backlog's old “mapped reads” label. The approved successor uses **positioned reads into fresh immutable `bytes`, no mmap**.

q04's retained profile recorded 8,294 native misses, 5,760 re-misses and 99.2% of misses in `int.bytes`; `_bound_chunk` accounted for 3.03 s cumulative in that profile. These identify an opportunity, not a measured successor saving. The earlier raw-sidecar component performs an eager whole-array authentication and maps each read; it is not the approved wiring. No claim of zero allocation, doubled whole-file RSS or generic EOF exception equivalence is used here.

## Guard equivalence — required before implementation

Storage must quote the actual selected code for `_chunk`, the authenticated `_native_binding` walk, `_verify_column_page` and the cache-disabled branch. The new section must establish:

1. The chunk ID comes from the authenticated index walk and is the same typed digest checked by `_chunk`: `sha256('atlas-typed-chunk-v1\0' + descriptor + '\0' + raw)`. Preserve the descriptor, dtype, shape, exact range and chunk identity.
2. Every served byte is checked before use against that ID. In particular, `ContentCache.offer_verified` returns before verification when disabled, so `_verify_column_page(key, page)` must be called explicitly before offering or borrowing the page. The immutable checked bytes are the bytes consumed.
3. Explain the eager pass's coverage of unused chunks, exact file length and trailing bytes. Retain cheap length checks at open; an unused corrupted chunk must refuse when later used. A swapped/present-but-wrong sidecar raises `ContractError`, never silently falls back.
4. Preserve the binding-named store/file identity, share-read lock, `locked.check()` per read, changed-file refusal, caps, and charge/borrow lifetimes. Authenticate the opened source; a pathname stat alone is insufficient.

The equivalence section and its required independent refuter are existing D1 conditions, not satisfied by this planning rewrite.

## Selected mechanism and integration boundary

Work follows L3 and uses the merged B17 rev4 + item14 reader. The design records `segment_store` a90ef8f3, `record_views` a6bbb81d, `content_cache` de7d3e45 and `raw_sidecar_store` e8ad994b as its input identifiers. These prefixes are navigation aids; the owner must use full selected-source pins at implementation. No invented `T/st` reader or test path is prescribed.

- In `record_views._cached_native_owner`'s miss branch, read the requested range from the locked sidecar handle under the store lock into new `bytes`, build `_NativeChunkPage`, verify explicitly, then offer/pin it.
- Add the design's `range_digest`/`read_bytes` route to the existing `RawSidecarStore`. It retains caps and lock checks and books scratch at the actual chunk size. Preserve the 8 KiB per-open-handle accounting and report actual versus booked use.
- Select `int.bytes` only; keep `MAX_ARRAYS` and the 256 MiB file cap. Missing/oversized sidecars or refused scratch admission decline visibly to `_bound_chunk`. Invalid authenticated content refuses instead.
- Attach one sidecar store to the sealed view using `cache_identity()`; retirement closes its handles consistently with outstanding ownership. Cover failure/cancellation cleanup through the actual lifetime contract.
- Build explicitly once after sealing, through the existing no-overwrite build/publish route (temporary file, fsync, no-replace rename). Take roots from the store or arguments. No implicit build during a read and no historical receipt rewrite.

L3 removes repeated verification on eligible cache hits; WP12 removes SQLite/decode work on eligible misses. Their effects overlap and must not be added arithmetically. The raised page-quota alternative is not adopted.

## Focused validation and completion

All validation below is prospective. Reuse unchanged q04/owner evidence; no full interval is launched to re-establish it. The owner uses the existing queue, seed-zero/runtime-source rules and unchanged memory/numerical limits.

- Compare every selected IV1 `int.bytes` chunk byte-for-byte with `_bound_chunk`, and retain equal reopen result identity and the five-field comparison. Check real read/decline counts rather than treating the design's projected counts as results.
- Exercise the existing M1–M8 obligations: used and initially unused byte flips, truncated/extended file, swapped sidecar, wrong offset, removed explicit verifier with cache disabled, over-cap decline, disabled/non-Windows fallback, and refused scratch reservation. Each must produce the specified refusal or visible safe decline.
- Obtain the one required refuter on the exact candidate's equivalence and accounting. Check scratch/handle retirement and actual versus booked RAM/disk, including failures.
- Run the authorised plain A/B with comparable source/input/cache conditions. The existing acceptance gate is **at least 5% net reopen saving, including sidecar build/open costs**. Record L3 and WP12 alone/together as required by the design; separate measured figures from projections.

Completion is a source-bound owner disposition, exactness/refuter evidence and the measured gate decision in existing Storage/composition records. A guard-equivalent design is not a built optimisation; a component result is not final N12 acceptance. Fresh full intervals remain held under the master plan.
