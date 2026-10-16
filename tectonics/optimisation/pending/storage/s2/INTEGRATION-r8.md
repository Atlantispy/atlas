# S2 integration note r8: WP16 pre-advance captures, gzip-1 -> capture_store zstd-3 (exact bytes)

16 Oct 2026, 18:0x. DRAFT r8. It supersedes INTEGRATION-r7.md and INTEGRATION.md (r5), both kept as they were.

This note becomes final when the r7->r8 delta re-check reports (T/so/refute/s2/delta-r8/review.txt). The q15
timing run stays HELD until READY is sent; exactness does not depend on it.

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

## Change (r8; your files unchanged since my base)
| File (owner path) | Base | Candidate | Diff |
|---|---|---|---|
| R/compact_restart_patch.py | 9d076c80 | **301845b1** (unchanged since r6) | T/so/s2/r8-diffs/compact_restart_patch.diff (136 lines, f917abec) |
| R/ledger_fresh_interval.py | cd89718b | **7d8a0c91** | T/so/s2/r8-diffs/ledger_fresh_interval.diff (162 lines, 41c1e582) |
| R/test_step8_coverage.py | fcd8cf6a | **59adb189** (owner layout, unchanged since r4) | T/so/s2/owner/test_step8_coverage.diff |
| R/fresh_interval_driver.py (d7bba076), R/prepared_interval_driver.py (6fb4ab6d) | yours | + 2 lines in each of three functions, applied by you | T/so/s2/r8/driver-lines.diff (1e2652b8) |
| new: test_wp16_preadvance.py | - | **42d2576a** | T/so/s2/r8 |
| new: test_s2_route_wiring.py | - | **8e7b3daa** | T/so/s2/r8 |
| R/test_ledger_fresh_interval.py | 69a4dda0 | unchanged; passes on r8 | - |

Full candidate files are in T/so/s2/r8/. r7 (f303d402, 2be4805f, 50ea132c, f3cc3029) and r5 are superseded.

T/so/s2/r8/test_step8_coverage.py (5c07cb3b, CRLF) is the copy my runs used. It differs from the owner-layout 59adb189
only in the SO_R/SO_TMP environment roots, which default to your layout. The owner-layout file can run only from
inside R, which I do not write to, so please run it once after applying.

### The driver lines (r8 placement)
I checked these only on local copies of your current SHAs (T/so/s2/r8-check/drivers, not for application). Each
place gets the same two statements: `from compact_restart_patch import require_capture_route`, then the call.
- fresh_interval_driver.advance_first_interval (d7bba076, hunk @@ -193): first statements after the docstring,
  before `_seed_pinned()`; the call is `require_capture_route(store)`. Same place as r7, rebased from f328f314.
- fresh_interval_driver.advance_successor_interval (d7bba076, hunk @@ -256), **new in r8**: the same two lines,
  first after the docstring, before `_seed_pinned()`. Item 21 added this entry point for interval N >= 2; it reaches
  the same compact pre-advance capture through prepared_interval_driver, so without this line an N >= 2 run with a
  missing capture route would refuse only after its admission (minutes) instead of at run start.
- prepared_interval_driver.advance_prepared_interval (6fb4ab6d, hunk @@ -158), unchanged since r7: after the
  lineage-gate if/else (whose ordinary branch ends in `record['lineage_gate'] = ...`), before `derivations = ...`;
  the call is `require_capture_route(workflow._store)`.
- test_s2_route_wiring.DriverTests checks all three on whichever drivers are first on sys.path: FAIL 3 on your
  drivers, OK 3 on the patched copies, FAIL 1 (the successor) on the r7 placement. If item 21's remaining edits or
  item 10 move a driver again, re-run it (N12 C19/C20).

## What r8 changed since r7 (the r7 delta findings)
- **NEW-1 fixed.** legacy_bytes read the whole legacy file before decompressing, so a large file named by a legacy
  receipt allocated its own size first. It now streams the file 1 MiB at a time through the same member-by-member
  decompression. Unchanged: the output bound (receipt raw_bytes + 1), gzip.decompress's acceptance rules (zero
  padding only after a member), the file-size ceiling and every refusal message.
- **NEW-3 tested.** `_container_pinned` keeps the footer when it spans the last two 1 MiB read blocks (the code was
  already right; now a test holds it, at sizes 1 MiB + k for k around the footer's 81 bytes).
- **NEW-4 rebased.** Driver lines cut on d7bba076 and the successor entry point added (above).
- **NEW-2 (accepted residual).** captured_bytes allocates the receipt's raw_bytes once the whole file hashes to the
  receipt's container pin and the footer under that pin states the same raw_bytes. The receipt is pinned by the
  run's own ledger, and raw_bytes is at most CAPTURE_MAX_BYTES. Growing the buffer instead would add a transient
  copy of up to the largest operand (about 190 MB at r9) for no protection the pin does not already give.
- **P3-b (optional; your call), unchanged since r5.** The stop-before-advance smokes return before calling the
  driver, so they never reach the route check. A real run still checks before the advance, but only after its
  runner work. To refuse at the true run start:
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
   run-start route check; CRP 9d076c80 -> 301845b1, LG cd89718b -> 7d8a0c91, T8C fcd8cf6a -> 59adb189, drivers +
   require_capture_route (fresh: first and successor entry points; prepared: after the lineage-gate if/else);
   + capture_store 4664b205, test_wp16_preadvance 42d2576a, test_s2_route_wiring 8e7b3daa".
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
- **Tests r8** (T/so/s2/r8-check/tests-r8.log; run_all_r8.sh through the small lane; build in build-r8.log),
  16 Oct 18:00. The loaded-file lines confirm which files ran.
  - base: 8 OK.
  - r8: 34 OK.
  - DriverTests: FAIL 3 on your drivers, OK 3 on the patched copies, FAIL 1 (successor) on the r7 placement.
- **Planted mutants r8** (make_mutants_r8.py): 31/31 KILLED. These are r7's 25 (l6 and l12 re-cut for the streaming
  reader), l19-l23 for the r8 reader and footer tail, and m00 = r7's whole-file reader under the r8 tests.
- **Your own driver tests, all classes** (r8-check/drv/drivers_r8.py, on test_fresh ace18923 and test_prepared
  cb3f0aac): base equals r8, fresh 26 OK, prepared 17 OK.
- **Writer evidence** (r4, still standing; r5-r8 did not change the writer):
  - 9/9 mutants fail closed (rq2.log);
  - the control PASSES against r9's operands (peak 1.91 GB);
  - smoke gain: median 1.22 s; disk 91.96 MB -> 79.55 MB.
- **Ruff** (F, E9, B, PLE; check only): r7 and r8 modules and tests clean; the r8 build and check scripts clean.
- **Refuter.**
  - First pass (a)-(e): all fixed in r4.
  - r4 delta: P2 + P3-a/b/d, fixed in r5.
  - r5 delta: P2 + P3-a/b/c; r6 fixed P2, P3-a and P3-c; P3-b is the optional item above.
  - r5->r7 delta: P2/P3-a/P3-c closed; NEW-1/3/4 handled in r8, NEW-2 accepted (above).
  - r7->r8 delta re-check: PENDING.
- **q15 timing** (LNNL/NLLN x3; exact-bytes control vs r9): HELD until READY. Storage's measurement for comparison:
  -1.0 to -1.26 s.

## Later-step impact
Each interval's pre-advance writes about 12.4 MB less (smoke fixture) and saves about 1.2 s. A compact run missing its
capture route now refuses before the admission, in interval 1 and in every successor interval, instead of after it.
Restart and reopen read captures through the verified reader, and r9 receipts stay readable at a fixed ~1 MiB read
cost however large the legacy file is.

Next-interval capacity: no new memory; capture reserves about 10 MB at its peak; legacy reads hold one 1 MiB block
plus the receipt-bounded output.
