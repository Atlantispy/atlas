# S2 integration note r9: WP16 pre-advance captures, gzip-1 -> capture_store zstd-3 (exact bytes)

16 Oct 2026, 18:4x. FINAL for exactness. It supersedes INTEGRATION-r8.md, INTEGRATION-r7.md and INTEGRATION.md (r5), which
are kept as they were. One open choice remains: where the library path comes from (r9 or r10; see "Library path" below).
q15 timing does not change any of this.

This note is for the runner owner, who applies it. The measured design is Storage's WIRING_NOTE_STEPS8-9.md
(R/diagnostic-captures). It is N12 row S2, with conflicts C19 and C20 in T/so/assembly-manifest.md.

## What it does (unchanged since r5)
The compact route's pre-advance step wrote its three operands (mesh, closed graph, bounds) as gzip level 1. It now writes
them as `atlas.diagnostic-capture.v1` files: exact bytes, Zstandard level 3, through Storage's `capture_store.write_capture`
with the pinned WP10 library.

The logical identity is unchanged and does not depend on the codec: `raw_bytes`/`raw_sha256` (for the mesh, the view's
`geometry_id`). `container_sha256` authenticates one file against its own receipt and is never compared across runs. The
ledger reads both forms:
- WP16 captures are fully verified against `container_sha256`, and the receipt's sizes bound the reader.
- Legacy gzip operands (r9 and earlier) stay readable.

Both forms then meet the same `raw_bytes`/`raw_sha256` check. No numbers change; only the capture container does.

## Change (r9; your files unchanged since my base)
| File (owner path) | Base | Candidate | Diff |
|---|---|---|---|
| R/compact_restart_patch.py | 9d076c80 | **7afe82bf** | T/so/s2/r9-diffs/compact_restart_patch.diff (137 lines, 665446fd) |
| R/ledger_fresh_interval.py | cd89718b | **06040fd2** | T/so/s2/r9-diffs/ledger_fresh_interval.diff (165 lines, c2dfacdb) |
| R/test_step8_coverage.py | fcd8cf6a | **59adb189** (owner layout, unchanged since r4) | T/so/s2/owner/test_step8_coverage.diff (fe4d7548) |
| R/fresh_interval_driver.py (d7bba076), R/prepared_interval_driver.py (6fb4ab6d) | yours | 2 lines in each of three functions; you apply them | T/so/s2/r9/driver-lines.diff (1e2652b8, unchanged since r8) |
| new: test_wp16_preadvance.py | - | **25e9d8c6** | T/so/s2/r9 |
| new: test_s2_route_wiring.py | - | **d5f68374** | T/so/s2/r9 |
| R/test_ledger_fresh_interval.py | 69a4dda0 | unchanged; passes on r9 | - |

The full candidate files are in T/so/s2/r9/; r8 and earlier are superseded. T/so/s2/r9/test_step8_coverage.py (5c07cb3b,
CRLF) is the copy my runs used. It differs from the owner-layout 59adb189 only in the SO_R/SO_TMP environment roots, which
default to your layout. Please run the owner-layout file once from inside R after applying, since I do not write there.

### The driver lines (unchanged since r8)
Each of the three places gets the same two statements: `from compact_restart_patch import require_capture_route`, then
the call.
- **fresh_interval_driver.advance_first_interval** (d7bba076, hunk @@ -193): the first statements after the docstring,
  before `_seed_pinned()`. The call is `require_capture_route(store)`.
- **fresh_interval_driver.advance_successor_interval** (d7bba076, hunk @@ -256): the same, before `_seed_pinned()`.
- **prepared_interval_driver.advance_prepared_interval** (6fb4ab6d, hunk @@ -158): after the lineage-gate if/else,
  before `derivations = ...`. The call is `require_capture_route(workflow._store)`.

test_s2_route_wiring.DriverTests checks all three on whichever drivers are first on sys.path. If item 21 or item 10 moves
a driver again, re-run it (N12 C19/C20).

## What r9 changed since r8 (from the r7->r8 delta re-check)
The re-check found no P1. It closed NEW-1, NEW-3 and NEW-4, so r9 changes only wording and tests, and the reader's code is
identical to r8's. The r8->r9 delta (wording and tests) was not re-refuted.
- **P3-a (wording).** The legacy reader's docstring now says it accepts gzip.decompress's rules, plus two stricter zlib
  checks that gzip.decompress skips: the header CRC must match when present, and reserved header flags refuse. Writers
  set neither, so no real operand is affected.
- **P3-f (wording).** The require_capture_route docstring names the three entry points.
- **P3-c/d/e (tests and mutants).** Three new tests cover:
  - the size checks, in mid-loop and at the end, against a file that grows or shrinks while it is read;
  - the negatives that gzip.decompress also refuses (zlib format, space or tab padding, magic only, header only, padding
    only) and the two stricter checks;
  - one block held over many (a 24 MiB file peaks under 2.5 MiB).
  Seven new mutants (l24-l30) are each killed.
- Review-ID comments were removed from the new test files, for the public branch.

### Accepted residuals, booked here
- **P2: a legacy read can need about twice raw_bytes.** The decompressed chunk sits beside the output buffer, and the
  bytearray grows by reallocation. On a real r9 mesh (182 MiB raw) that is about 385 MiB of working set, transient, in
  the ledger and in restart reads of r9-era receipts only (new runs write WP16 captures). It is not a regression; r7 and
  earlier held the whole compressed file as well.
  - I did not take the refuter's alternative: cap decompressobj's max_length at 1 MiB. With a cap, zlib can consume all
    of its input while output is still pending (unconsumed_tail empty, eof False). The last block would then refuse a
    valid stream unless a drain loop were added, and the reallocation half of the 2x would remain anyway.
- **P3-b: a hostile many-member input is quadratic per block.** It is bounded by the receipt's raw_bytes and the file
  ceiling, and writers produce one member. Not worth the code.
- **NEW-2 (from r8): captured_bytes allocates raw_bytes once the pin and the footer agree.** It is bounded by
  CAPTURE_MAX_BYTES.

## Library path (decision for you or the coordinator)
In r9, `CAPTURE_LIBRARY` in compact_restart_patch.py and ledger_fresh_interval.py is the library's permanent absolute
path, R/compact-geometry-r1/native/wp10_zstd.dll (sha a40c24ad). That works in every layout on this machine. Every
composition copies these modules into a helpers folder that has no native/ folder: composed-r2, composed-checks/hc-*,
T/ps/c/*, step10/a3, rm/fold/tr.

r10 (T/so/s2/r10, build_s2_r10.py) is the same candidate with the path taken from the module's own folder
(`Path(__file__).resolve().parent/'compact-geometry-r1'/'native'/'wp10_zstd.dll'`). That way no machine path is in the
source.
- r10 SHAs: CRP b9228231, LG c2b54841, test_wp16 113a56be. It adds one assertion that the path is module-relative.
- Proof: T/so/s2/r10-check/tests-r10.log. base 8 OK; r10 37 OK; DriverTests 3/3/1 as expected; 39/39 mutants KILLED
  (r9's 37 plus l31/l32, the path taken from the working folder); your driver tests base == r10 (below).
- But in a composed layout r10 refuses at run start (FileNotFoundError from require_capture_route) unless the composition
  also carries compact-geometry-r1/native/wp10_zstd.dll beside the helpers.

**Recommendation: land r9.** It is an existing file, and the public-branch sync scrubs machine paths in existing files.
Take r10 only if every composition will also carry the library.

## Composition (generation note needed: explicit repin)
1. Add `capture_store.py` (R/diagnostic-captures, 4664b205) to the composed helpers and to composition.json's `files`.
   That manifest is the selected runtime's pin table, so an unlisted capture_store refuses at run start (the intended
   early refusal). storage_zstd_backend.py (0e0ebf31) is already listed. Also add capture_store wherever the helpers are
   copied: fixture copy lists and test roots.
2. Repin compact_restart_patch.py, ledger_fresh_interval.py and test_step8_coverage.py to the candidates above. Repin both
   drivers to your patched SHAs. compact_restart_patch and prepared_interval_driver are in RFI's FRESH_MODULES, and the
   advance driver has its own pin, so regenerate the profile.
3. Generation note: "S2/WP16 capture-digest generation: pre-advance operands as zstd-3 exact-bytes captures with a run-start
   route check; CRP 9d076c80 -> 7afe82bf, LG cd89718b -> 06040fd2, T8C fcd8cf6a -> 59adb189, drivers +
   require_capture_route (fresh: first and successor entry points; prepared: after the lineage-gate if/else);
   + capture_store 4664b205, test_wp16_preadvance 25e9d8c6, test_s2_route_wiring d5f68374". If r10 is chosen, use its
   three SHAs instead.
4. Wherever the ledger reads WP16 captures, it needs the composed helpers and the runtime source on sys.path. It refuses
   cleanly if they are missing.

## Decisions and flags (unchanged since r5)
- **CAPTURE_MAX_BYTES (yours or Michael's).** On this route it is 16 GiB, the run's existing logical ceiling, and the
  ledger reader uses the same value. This replaces capture_store's 4 GiB default, which would stop a run at pre-advance
  once the streamed mesh outgrows it (the gzip route had no ceiling). Capture streams 64 KiB at a time, so this adds no
  memory, and no guard or memory limit is raised.
- **For Storage (P3-c of r5).** WP16's export, replay and CLI readers keep the 4 GiB defaults. A 4-16 GiB capture
  therefore reads in the ledger but is refused by those tools, from about interval 3 or 4 at the observed growth.
- **Optional (P3-b of r5), your call.** The stop-before-advance smokes never reach the route check. To refuse at the true
  run start, add `capture_store` and `storage_zstd_backend` to run_prepared_restart.COMPACT_MODULES, and to the fresh
  runner's FRESH_MODULES and its profile check.
- **Accepted residual.** The run-start check keys on the store type. A compact mesh on a legacy store refuses at capture
  instead, after the advance (still fail-closed).

## Proof
- **Tests r9** (T/so/s2/r9-check/tests-r9.log; run_all_r9.sh through the small lane, seed 0, fail-closed flag check),
  16 Oct 18:26.
  - base: 8 OK.
  - r9: 37 OK.
  - DriverTests: FAIL 3 on your drivers, OK 3 on the patched copies, and FAIL 1 (the successor) on the r7 placement.
  - Planted mutants: 37/37 KILLED (r8's 30 plus l24-l30).
- **Your own driver tests, all classes** (r9-check/drivers-r9b.log, drivers_r9b.py bcc307fe, 18:30).
  - At 18:19 your test_fresh_interval_driver.py changed to 60fba3c7, and run_all_r9's pin refused it (as designed).
    drivers_r9b re-pins it. It also lets your deliberate unseeded scenario reach the driver's own refusal.
  - prepared: base 17 OK, r9 17 OK.
  - fresh: base and r9 both run 28 and fail the same 7 (item 11 and 11m wiring tests). Your test file is ahead of FD
    d7bba076, and these are not S2's.
- **Writer evidence.** The r4 writer mutants (9/9 fail closed) still stand. q15 harness smokes, seed flag 0, the control
  passing (each arm's raw sha/bytes equals the r9 receipt, and the first N arm decodes to the exact r9 bytes):
  - r2 = r9, `-B -s -P`, cleaned env: L 2.28 s, N 1.19 s.
  - r3 = r10: L 2.32 s, N 1.19 s.
  - disk 91.96 MB -> 79.55 MB; peak RSS 0.80 GiB.
  These are smokes, not timing evidence.
- **Ruff** (F, E9, B, PLE; check only): the r8, r9 and r10 modules and tests are clean, and so are the new scripts.
- **Refuter.** All rounds through r7->r8 are closed or booked (above). The r8->r9 delta (wording and tests) was not
  re-refuted.
- **q15 timing** (LNNL/NLLN x3, exact-bytes control against r9) is HELD until READY. Storage measured -1.0 to -1.26 s.

## Later-step impact
Each interval's pre-advance writes about 12.4 MB less (on the smoke fixture) and saves about 1.1-1.2 s. A compact run
missing its capture route now refuses before the admission, in interval 1 and in every successor interval, instead of
after it. Restart and reopen read captures through the verified reader. r9 receipts stay readable at about twice their
raw_bytes, transient, during the read.

Next-interval capacity: no new memory in the run. Capture reserves about 10 MB at its peak. Legacy (r9-era) reads hold one
1 MiB block plus about twice the operand's raw_bytes while reading.
