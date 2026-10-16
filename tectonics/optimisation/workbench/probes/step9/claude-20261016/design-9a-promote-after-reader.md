# Step 9(a) design: catalog promotion waits for the independent reader (16 Oct 2026, ~04:15)

Paper design; nothing is built yet. Decision: plan-order review §7b item 5. It goes alongside route (1) build step 2.
Paths: R = resumability-r1, C = R/compact-geometry-r1.

## Why

The mandatory independent fresh-process reader currently runs after the catalog has already moved to the new interval. This happens because `CompactRestartStore.seal_and_promote` seals and promotes in one call, and the launcher only then starts the reader. As a result, a defect that only the reader can see would already be accepted state when it is found:

- a pack or codec defect;
- a chunk whose id and content were swapped between rows (gap G8, the R2 refuter's #3);
- anything outside bounded_preseal's scope (gaps G4/G7).

Recovery would then need a catalog rollback.

**Protects:** nothing the reader would refuse ever becomes accepted state; a failed reader leaves the catalog untouched.

**Costs:** no extra compute, since the reader is mandatory anyway. Wall time is unchanged. Memory is covered under option B below.

## What exists (read in code)

- `UnlistedCandidate.seal(head)` (C/interval_store_set.py, 783) and `IntervalStoreSet.promote(sealed, expected_catalog_digest)` (500) are already separate. `promote` checks four things: the same store-set object, a fresh catalog digest, the next interval, and an unchanged immutable file token. It then publishes the catalog atomically.
- The facade joins the two calls (R/compact_restart_store.py, `seal_and_promote`).
- A new candidate file is created with `O_CREAT | O_EXCL` (interval_store_set 571). An unlisted file left at the next interval path therefore blocks `begin_interval`. It is never overwritten and never adopted.

## Protocol (recommended: option B)

1. **Runner (run_prepared_restart).**
   - Steps: publish, then bounded_preseal (successor) or the root put (interval 0), then `sealed = store.seal(head_key)`. This is a new facade method that does not promote.
   - It records `sealed_awaiting_reader`: interval, file name, logical seal, sha256 of the sealed file, expected catalog digest and head SegmentRef. Then it saves and exits, releasing all of its memory.
2. **Launcher (launch_monitored_interval).** Under the same guard, it starts the independent reader on the pending sealed file:
   - read-only and immutable;
   - against the old catalog head plus this pending interval;
   - with the same per-scalar re-derivation as today.
   The reader's verdict binds the sealed file's sha256 and logical seal.
3. **PASS.** The launcher calls `adopt_and_promote(file, logical seal, file sha256, expected catalog digest)`:
   - it re-verifies the immutable token and the seal digest;
   - it promotes atomically (`publish_catalog`);
   - it records `promoted_after_reader` with the verdict digest.
4. **FAIL, reader crash or timeout.** There is no promotion and the catalog is untouched. The record says `sealed_rejected` with the reader's first-raised cause (the harness's `exception_chain` rule). The sealed file stays unlisted. The next `begin_interval` refuses because the file exists. Only an explicit decision removes or keeps it.
5. **Runner crash between seal and its record.** The file is unlisted and there is no record. Recovery is never automatic:
   - the explicit tool `adopt-after-reader` runs the reader on the file;
   - on PASS it adopts and promotes as in step 3.

**Option A**, the runner keeping its in-process `SealedCandidate` and promoting itself after a reader subprocess, needs no new storage primitive. Its cost is that the runner's process tree stays alive beside the reader's (about 0.5-1 GB) under one guard. **Option B is recommended:**

- the runner's memory is gone before the reader starts;
- one code path serves both the normal case and crash recovery.

## Needed from the storage owner (interval_store_set is WP10's)

1. **Pending-interval read view.** Open a catalog read-only with one named, sealed, unlisted next-interval file as its head. It verifies:
   - the immutable token;
   - the logical seal, recomputed;
   - parent seal = the catalog head;
   - references limited to listed intervals.
   The reader's facade (`CompactRestartStore`) takes it as its resolver.
2. **`adopt_and_promote`.** Turn that verified pending file into a `SealedCandidate` owned by a fresh store set, with the same checks as `promote` plus the seal recomputation, and promote it.
3. **Refusals (tests):**
   - an adopt with a stale catalog digest;
   - a changed file (token or sha256);
   - a wrong interval;
   - a parent seal differing from the head;
   - foreign references;
   - two adopts racing (the second sees a stale digest).

## Changes in my files

- **R/compact_restart_store.py:** `seal(head_key)`. `seal_and_promote` is kept for fixtures and synthetic runs only.
- **R/run_prepared_restart.py:**
  - seal, record, exit;
  - `record['record_identities']` stays as today;
  - failure records carry first_raised.
- **R/launch_monitored_interval.py:** reader on the pending file, then `adopt_and_promote` on PASS; guard and postcheck around both.
- **R/reopen_prepared_restart.py:** accept the pending view as its resolver; verdict binds the file sha256 and logical seal.
- **Tests:** promote-after-pass; reject-on-fail (catalog unchanged); crash between seal and record (`begin_interval` refuses; explicit adopt after reader); tamper after the reader (adopt refuses); stale digest.

## Exactness

There is no tolerance and no new acceptance rule: the reader is the existing mandatory reader. Promotion is gated on its PASS, bound to the exact sealed bytes. The catalog still changes only through the existing atomic `publish_catalog`.

## Later-step impact

- Step 11 and the real interval runs (interval-1 rerun, interval 2, interval 3) use this protocol.
- Route (1) step 5 (the synthetic fresh-start run) is its first end-to-end exercise.
- G8 needs no storage accumulator: the reader catches a swapped chunk before promotion. The WP10 accumulator stays optional defence in depth at Step 12.

## Interval 3

No capacity or time figure changes. The runner and the reader no longer overlap in memory, so interval 3's peak is the larger of the two, not their sum.
