# Step 9 route comparison: fresh start vs D6 conversion (16 Oct 2026, ~03:20)

Paper and code reading only. Nothing was built or run.

- Decision: plan-order review section 7b, item 6, including its 04:15 amendment (RC1 is not output-identical to r7; the rehearsal produces a difference ledger), and item 7.
- Paths: R = resumability-r1, C = R/compact-geometry-r1, I = runtime-integration-r1/runtime-src/atlas_tectonics, H = heat-repair-20261007.
- Labels: **F** = read in code (file:line). **I** = inference.

## The two routes

1. **Fresh start (decision 6 default).** Rerun interval 1 on the Step 10 composition, from its original starting state, into a compact lineage:
   - root-only interval-0000;
   - interval-0001 holds the rerun endpoint;
   - interval 2 continues from interval-0001.

   The original r9 run stays untouched, and D6 becomes optional archival work (L1).
2. **D6 conversion.** Convert the original r9 interval-1 endpoint into a compact migration interval-0000, and continue interval 2 from the migrated root. Under the fallback, the rerun is only a test.

## Work per file

| File | (1) fresh start | (2) D6 conversion |
|---|---|---|
| run_prepared_restart.py | Add a fresh-start mode: funded preparation, `CollarWorkflow.create` into interval-0000, seal, reader, promote, `start_next_interval`, driver, seal. Accept an ordinary base: today it requires `MigratedWorkflowBase` (F: 634, 744, 893). | Exists. Tested on synthetic data only (35 tests; synthetic W4 passed, test-results/w4-runner-reader.json). |
| prepared_interval_driver.py | Start from an ordinary head as well as a migrated one. Today: "migrated head ... retained r9 physical case" (F: 1, 90-100). I: the advance loop is the same continuation code. | Exists (8 tests, stand-in modules). |
| reopen_prepared_restart.py | Accept an ordinary root and its successor. Today it accepts `migrated-root`/`successor` only (F: 239, 443, 746, 806, 873). The per-scalar re-derivation is unchanged. | Exists (14 + 10 tests). |
| Root metadata (new reviewed transform; I and RC1 unchanged) | **Shared blocker.** `compact_restart_store.put` refuses metadata over 64 KiB with "compact record references required" (F: compact_restart_store.py 337-339; test_step8_store.py 113). `Workflow.create` puts funding, exterior owner and collar plan in the root metadata (F: I 887-940). The r9 root metadata is about 0.33 MB (funding about 154 KB, exterior owner about 97 KB). Fix: move the descriptors into content-addressed records referenced from the root. | **Same blocker.** The migrated root carries `funding.descriptor()`, `owner.descriptor()`, `collar.descriptor()` and `native.record()` (F: workflow_transfer.py 671-683). I: W4 passed only because its descriptors are tiny. |
| Initial partition | `create` writes the partition arrays directly through `store.put` (F: I 932-937). `partition_workflow_transform` v2 only changes `_publish` (F: C 209-230). So a compact `create` seam is needed. I: small. | Not needed (`historical_partition_v2` converts). |
| launch_monitored_interval.py | Pins become the H fixture/funding source hashes and the composition. The r9 DB leaves the run path; the comparator reads it read-only. | Pins the original DB (F: 55-57, 599-601). Unchanged. |
| assemble_resumable.py | Needs a compact profile (`storage_format`; F: 1102-1113). | Same. |
| New comparator: difference ledger | **New.** Builds on `endpoint_array_records`/`canonical_records` (F: reopen 129-144, 197-205), `check_field_group` (F: materialise_endpoint 97-110), `private_heat_record_compare_r1` (F: H 320, 377; excludes identity fields) and the geometry chat's 7,181-query r7/RC1 matching. The hardest new part is tracing downstream heat and transport differences to query bounds (I). | Not needed. |
| materialise_endpoint / workflow_transfer / historical_admission / historical_compact_heat / initial_workload / plan_preparation | Off the run path; archival L1. | On the run path. Real-data hardening is still open (see risks). |

## Risks

**(1) Fresh start**
- New code on the run path: the runner mode, driver and reader generalisation, the compact `create` seam and the ledger. Mitigations:
  - reuse the interval-2 continuation driver and reader;
  - Step 10 already requires RC1 against RC1 plus transforms, with exact parity;
  - a synthetic W4-style fresh-start run and a stop-before-advance smoke on the real start come before any real run.
- One real compute run on a shared machine. r9 itself committed its endpoint but then failed the 1 GiB free floor (F: r9 receipt; process-tree peak 9.05 GB).
- The ledger may find a difference it cannot attribute. That fails the rehearsal by design and would block interval 2 until resolved. This is the intended outcome, not a defect of the route.
- Execution identity: result and plan IDs differ by construction (F: historical_admission 769-784). The ledger matches queries and values by stable content keys, not IDs.

**(2) D6 conversion**
- The preserved Step 9 fixture crashed with 0xC0000005 after 127.833 s (F: CLAUDE_FULL_PLAN_HANDOFF, "Step 9" paragraph). It is undiagnosed.
- Real-data conversion has never run, and its time is unknown (it reads 308.4 MB).
- I: the heat-ledger part is the same ledger whose unsealed restore took 2,402 s in Step 8.
- The graph pack builder limit is no longer a blocker: Step 8 fits the authentic graph at 83.1% of the unchanged 256 MiB builder.
- **Mixed lineage.** Interval 2 would run on RC1 from an r7-produced endpoint. The 445 r7/RC1 query differences at that endpoint are never put in a ledger, so an interval-2 anomaly cannot be separated from the r7→RC1 change.
- Migration-only paths stay in the run path and in every later reader: `register_legacy_lookup` (F: r4 285) and `migrate_heat_history` (F: historical_compact_heat 43), both of which require interval 0.

## How exactness is proven

**(1) Fresh start**
- The difference ledger, as amended:
  - every difference is attributed to a named approved RC1 change (cube-witness stopping; item 15 padded containment if kept; item 11 is OFF unless a measured gain);
  - both bounds are certified, meet the requested width and overlap;
  - downstream heat and transport differences are quantified and traced;
  - anything unattributed fails.
- The start state (rerun sequence-0 arrays against r9's sequence-0 records) goes through the same ledger.
- Transform exactness is separate (Step 10): RC1 against RC1 plus transforms, on the same runtime and input, with exact parity.
- The independent fresh-process reader re-derives every scalar on the sealed interval-0000 and interval-0001.
- Promotion waits for the reader (Step 9(a)).

**(2) D6 conversion**
- Byte-exact conversion checks:
  - whole-DB SHA pin (F: historical_admission 290-292, 662-664);
  - per-record sha256 and byte count against the original (F: materialise_endpoint 338-342);
  - partition header and stats, mesh identity and heat chunk hashes.
- The reader re-checks manifests and indexes (F: workflow_transfer 372).
- This proves the r7 records were stored losslessly. It says nothing about RC1 against r7, and interval 2 runs on RC1 regardless.

## Wall time

| | (1) fresh start | (2) D6 conversion |
|---|---|---|
| Machine time before interval 2 | Rerun to endpoint about 64-92 min (r8 3,815.75 s PASS with 4,241.4 s total; r9 5,493.6 s). Reader about 7-8 min (r8 416.9 s, r9 447.6 s). Ledger in minutes. **About 1.2-1.7 h.** The compact composition may move this; Step 8's forecast will say how far. | Conversion not measured (I: about 10-45 min, judged from Step 8's heat-ledger restores of 2,402 s unsealed and 322.9 s sealed). Reader about 7-8 min. **Plus the rerun's 1.2-1.7 h if it is still run as a test.** |
| Build | Fresh-start mode, generalisation, `create` seam and ledger (I: about two working sessions). Plus the shared root-reference transform (I: about half a session). | Crash diagnosis (unknown), real-data hardening and the shared root-reference transform. If the rerun test is on the compact build, all of (1)'s fresh-start code as well. |

## Interval store and catalog

**(1) Fresh start**
- Nothing requires interval 0 to be a migration (F):
  - `create_migration` only checks the path and an absent catalog (interval_store_set 300-307);
  - `begin_interval(None)` needs only the parent to equal the head (478-497);
  - `seal` needs only a segment-root head, and science admission is caller-owned (785-796);
  - catalog interval 0 just has no parent (interval_catalog 115-117).
- A root-only interval-0000 followed by an advanced interval-0001 is already tested (test_step8_store.py 118).
- Needs: root metadata of 64 KiB or less, using references (shared); a new workflow_id lineage; promotion after the reader for both files.
- Disk: interval-0000 holds about 24 MB of root arrays. Interval-0001 is of IV1 size.

**(2) D6 conversion**
- Needs: a migration interval-0000 with legacy lookup and history migration, and the same 64 KiB fix.

## Recommendation

**Route (1), fresh start: the default holds.** It is more new code, but not materially more work or risk:

- The biggest real-data blocker, root metadata over 64 KiB, is shared.
- Route (2) has its own unresolved real-data risks: an undiagnosed native crash and a conversion that has never run.
- Under the fallback, a rerun "as a test" on the compact build still needs (1)'s fresh-start code. So (2) saves no code; it only adds D6 hardening on top.
- With RC1 differing from r7, only (1) ledgers interval 1's differences before interval 2. It also gives one RC1 lineage from interval 0.

**Build order after your go** (no real run without it):
1. The root-reference transform, tested at real descriptor sizes from r9's receipt values.
2. The compact `create` seam, the root-only interval-0000 and the reader for ordinary roots.
3. The fresh-start runner mode and the driver generalisation.
4. The ledger comparator.
5. A synthetic fresh-start run with the fresh reader, then a stop-before-advance smoke on the real start.

Throughout, a bounded read of the D6 crash logs (no rerun), in case it lies in a shared native path.

**Later-step impact.**
- (1) gives Steps 10-11 and the final recomposition a single lineage with no migration-only readers.
- (2) would keep the legacy lookup and history migration supported through interval 3.

**Interval-3 impact.** The route choice changes no capacity or time figure. (1)'s measured rerun time and peak become the IV1 baseline for the IV3 forecast.

## Decision (coordinator, 16 Oct 2026, ~03:30)

**Route (1), fresh start, APPROVED.** It comes with build order 1-5 above and a bounded read of the D6 crash logs (no rerun).

- The D6 files leave the run path and become L1 archival.
- Priorities:
  - Step 8 completion items come first whenever their inputs are ready: R1a, S1, R2 rev2, then the capacity retry.
  - Route (1) is built in the gaps.
  - The 9(a) design goes alongside build step 2.
- No real run (interval-1 rerun or interval 2) without the coordinator's go. Build step 5 is allowed when ready, because it does not advance: a synthetic fresh-start run with the reader, then a stop-before-advance smoke on the real start.
- R2 refuter #3 becomes gap G8, closed by 9(a). The (id, stored_sha) accumulator goes into S1 only if trivial; otherwise it is WP10 defence in depth at Step 12.
- Heavy runs (expected above 2 GiB real) take the cooperative lock `fidelity-integration-20261005/heavy-run.lock.json` first: exclusive create, a stale lock replaced only when its PID is dead, and the lock deleted at the end of the run.

**Michael's rule (relayed by the coordinator, 16 Oct ~03:15).** Interval 1 is NOT rerun until the size and speed improvements are in.

- The rerun runs only on the single Step 10 composition.
- That composition must contain every approved pre-interval-2 change:
  - growth (a) and (b);
  - WP20 certificates for the 24 stalls;
  - WP22, and WP18 batching and hardest-first;
  - the R1 batch and R1a;
  - S1;
  - R2 rev2;
  - the WP23 items ranked by profile.
- Building and testing route (1) code is allowed now, including the synthetic fresh-start run and the stop-before-advance smoke on the real start. Nothing that recomputes interval 1 is allowed before then.
- The 1.2-1.7 h figure comes from old-code runs. It is an upper reference, not a forecast.
