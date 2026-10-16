# S2 integration note r7: WP16 pre-advance captures, gzip-1 -> capture_store zstd-3 (exact bytes)

16 Oct 2026, 17:3x. DRAFT r7. It supersedes INTEGRATION.md (the r5 draft, kept as it was).

This note becomes final when the r5->r7 delta re-check reports (T/so/refute/s2/delta-r7/review.txt). The q15 timing
run is HELD (light-work window); exactness does not depend on it.

For the runner owner, who applies it. Measured design: Storage's WIRING_NOTE_STEPS8-9.md (R/diagnostic-captures).
N12 row S2; conflicts C19/C20 in T/so/assembly-manifest.md.

## What it does (unchanged since r5)
The compact route's pre-advance step wrote the three operands (mesh, closed graph, bounds) as gzip level 1. It now
writes them as `atlas.diagnostic-capture.v1` files: exact bytes, Zstandard level 3, the pinned WP10 library, through
Storage's `capture_store.write_capture`.

The logical identity is unchanged and codec-independent: `raw_bytes`/`raw_sha256` (for the mesh, the view's
`geometry_id`). `container_sha256` authenticates one file against its own receipt and is never compared across runs.

The ledger reads both forms. WP16 captures are fully verified against `container_sha256`, with the receipt's sizes
bounding the reader. Legacy gzip operands (r9 and earlier) stay readable. Both then meet the same
`raw_bytes`/`raw_sha256` check. No numbers change; only the capture container does.

## Change (r7; your files unchanged since my base)
| File (owner path) | Base | Candidate | Diff |
|---|---|---|---|
| R/compact_restart_patch.py | 9d076c80 | **301845b1** | T/so/s2/r7-diffs/compact_restart_patch.diff (136 lines, f917abec) |
| R/ledger_fresh_interval.py | cd89718b | **f303d402** | T/so/s2/r7-diffs/ledger_fresh_interval.diff (148 lines, 3e122a43) |
| R/test_step8_coverage.py | fcd8cf6a | **59adb189** (owner layout, unchanged since r4) | T/so/s2/owner/test_step8_coverage.diff |
| R/fresh_interval_driver.py (f328f314), R/prepared_interval_driver.py (6fb4ab6d) | yours | + 2 lines each, applied by you | T/so/s2/r7/driver-lines.diff (f3cc3029) |
| new: test_wp16_preadvance.py | - | **2be4805f** | T/so/s2/r7 |
| new: test_s2_route_wiring.py | - | **50ea132c** (unchanged since r5) | T/so/s2/r7 |
| R/test_ledger_fresh_interval.py | 69a4dda0 | unchanged; passes on r7 | - |

Full candidate files are in T/so/s2/r7/.

T/so/s2/r7/test_step8_coverage.py (5c07cb3b, CRLF) is the copy my runs used. It differs from the owner-layout 59adb189
only in the SO_R/SO_TMP environment roots, which default to your layout. The owner-layout file can run only from
inside R, which I do not write to, so please run it once after applying.

r5 (1a1088d9, 775bb0a4, fc8bc908) is superseded.

### The two lines per driver (r7 placement)
I checked these only on local copies of your current SHAs (T/so/s2/r7-check/drivers, not for application).
- fresh_interval_driver.advance_first_interval (f328f314, hunk @@ -187), the same as r5. Insert as the first
  statements after the docstring, before `_seed_pinned()`:
  `from compact_restart_patch import require_capture_route`, then `require_capture_route(store)`.
- prepared_interval_driver.advance_prepared_interval (6fb4ab6d, hunk @@ -158). This changed in r7 because item 21
  moved the frozen-duration `_require` into both branches of an if/else. The same import and
  `require_capture_route(workflow._store)` now go after that if/else, whose ordinary branch ends in
  `record['lineage_gate'] = ...`, and before `derivations = ...`. The check therefore covers the migrated route and
  the ordinary one.
- test_s2_route_wiring.DriverTests checks both placements on whichever drivers are first on sys.path. Today it fails
  2 on your drivers and passes 2 on the patched copies. If item 7 or item 10 moves either driver, re-run it (N12
  C19/C20).

### What r6/r7 changed since r5 (the r5 delta findings)
- **P2 fixed.** require_capture_route looks `compact_restart_store` up in `sys.modules` and never imports it.
  - In r5, a legacy run (your driver tests have no compact_restart_store on their path) failed at run start.
  - In r5, a cold non-compact call imported about 940 modules.
  - Now every store gets the same result.
- **P3-a fixed.** captured_bytes now checks before it allocates the buffer:
  - the whole file must hash to the receipt's container pin;
  - the footer that pin covers must state the receipt's raw_bytes;
  - stored_bytes must be at least the format's minimum.
- **P3-c fixed (pre-existing).**
  - Both forms take plain file names only.
  - legacy_bytes decompresses member by member and never goes past the receipt's raw_bytes + 1. It requires each
    member's end (`eof`), and a `zlib.error` becomes LedgerRefused.
  - gzip_bytes, when present, must equal the file size.
- **r7 tests.**
  - Each malformed receipt must refuse at its own check, with the ledger's `open` unavailable, instead of being
    refused later by the hash pass.
  - legacy_bytes is now called directly with no gzip_bytes, so a missing gzip end is tested on its own.
- **P3-b (optional; your call).** The stop-before-advance smokes return before calling the driver, so they never reach
  the route check. A real run still checks before the advance, but only after its runner work. To refuse at the true
  run start:
  - add `capture_store` and `storage_zstd_backend` to run_prepared_restart.COMPACT_MODULES;
  - in the fresh runner, add them to FRESH_MODULES and its profile check.

## Composition (generation note needed: explicit repin)
1. Add `capture_store.py` (R/diagnostic-captures, 4664b205) to composed helpers and to composition.json's `files`.
   - That manifest is the selected runtime's pin table, so an unlisted capture_store refuses at run start (the
     intended early refusal). storage_zstd_backend.py (0e0ebf31) is already listed.
   - The WP10 library is read from its permanent path (`CAPTURE_LIBRARY` = R/compact-geometry-r1/native/wp10_zstd.dll,
     sha a40c24ad), not from the workspace.
   - Also add capture_store to your fixture copy lists and test roots wherever the helpers are copied.
2. Repin compact_restart_patch.py, ledger_fresh_interval.py and test_step8_coverage.py to the candidates above, and
   both drivers to your patched SHAs. compact_restart_patch and prepared_interval_driver are in RFI's FRESH_MODULES,
   and the advance driver has its own pin, so regenerate the profile.
3. Generation note: "S2/WP16 capture-digest generation: pre-advance operands as zstd-3 exact-bytes captures with a
   run-start route check; CRP 9d076c80 -> 301845b1, LG cd89718b -> f303d402, T8C fcd8cf6a -> 59adb189, drivers +
   require_capture_route (prepared: after the lineage-gate if/else); + capture_store 4664b205, test_wp16_preadvance
   2be4805f, test_s2_route_wiring 50ea132c".
4. The ledger needs the composed helpers and the runtime source on sys.path wherever it reads WP16 captures. It refuses
   cleanly if they are missing.

## Decisions and flags (unchanged since r5)
- **CAPTURE_MAX_BYTES (yours or Michael's).** `CAPTURE_MAX_BYTES = 16 GiB` replaces capture_store's 4 GiB default on
  this route; 16 GiB is the run's existing logical ceiling, and the ledger reader uses the same value.
  - The gzip route had no ceiling, so 4 GiB would stop a run at pre-advance once the streamed mesh outgrows it.
  - Capture streams 64 KiB at a time, so this adds no memory. No guard or memory limit is raised.
  - If you prefer 4 GiB, change the one constant.
- **For Storage, P3-c.** WP16's export, replay and CLI readers keep the 4 GiB defaults. A 4-16 GiB capture therefore
  reads in the ledger but is refused by those tools, from about interval 3 or 4 at the observed growth. The fix
  belongs there: take an explicit limit, or read it from the receipt.
- **Accepted residual.** The run-start check keys on the store type. A compact mesh on a legacy store is not checked at
  run start; it refuses at capture instead (fail-closed, but after the advance).

## Proof
- **Tests r7** (T/so/s2/r7-check/tests-r7.log; run_all_r7.sh; build in build-r7.log), 16 Oct 15:45. The loaded-file
  lines confirm which files ran.
  - base: 8 OK.
  - r7: 31 OK.
  - DriverTests: FAIL 2 on your drivers, OK 2 on the patched copies (as intended).
- **Planted mutants r7** (make_mutants_r7.py): 25/25 KILLED. These are r5's 14 rebased, plus c7 and l9-l18 for the r6
  changes. r6's four survivors (l3, l4, l8, l6) are now killed.
- **Your own driver tests, all classes** (r7-check/drv/drivers_r7.py):
  - base equals r7: fresh 18 OK, prepared 16 OK, including OrdinaryHeadScenarios;
  - the r5 control shows the P2 (fresh 7 errors, prepared 8 failures).
- **Writer evidence** (r4, still standing; r5-r7 did not change the writer):
  - 9/9 mutants fail closed (rq2.log);
  - the control PASSES against r9's operands (peak 1.91 GB);
  - smoke gain: median 1.22 s; disk 91.96 MB -> 79.55 MB.
- **Ruff** (F, E9, B, PLE; check only): the r6/r7 modules and the r7 test are clean, and so is the base.
- **Refuter.**
  - First pass (a)-(e): all fixed in r4.
  - r4 delta: P2 + P3-a/b/d, fixed in r5.
  - r5 delta: P2 + P3-a/b/c. r6 fixes P2, P3-a and P3-c; P3-b is the optional item above.
  - r5->r7 delta re-check: PENDING.
- **q15 timing** (LNNL/NLLN x3; exact-bytes control vs r9): HELD. Storage's measurement for comparison: -1.0 to -1.26 s.

## Later-step impact
Each interval's pre-advance writes about 12.4 MB less (smoke fixture) and saves about 1.2 s. A compact run missing its
capture route now refuses before the advance instead of after it, so that interval's compute is not lost. Restart and
reopen read captures through the verified reader, and r9 receipts stay readable.

Next-interval capacity: no new memory; capture reserves about 10 MB at its peak.
