# S2 integration note: WP16 pre-advance captures, gzip-1 -> capture_store zstd-3 (exact bytes)

From "Small optimisations", 16 Oct 2026. DRAFT r5 (15:2x): it becomes final when the r5 delta re-check and q15 report.
For "Runner pipeline and final integration", who applies it. Measured design: Storage's WIRING_NOTE_STEPS8-9.md
(R/diagnostic-captures).

## What it does
The compact route's pre-advance step wrote the three operands (mesh, closed graph, bounds) as gzip level 1.
It now writes them as `atlas.diagnostic-capture.v1` files (exact bytes, Zstandard level 3, the pinned WP10 library)
through Storage's `capture_store.write_capture`. The logical identity is unchanged and codec-independent:
`raw_bytes`/`raw_sha256` (for the mesh, the view's `geometry_id`). `container_sha256` authenticates one file against
its own receipt and is never compared across runs. The ledger reads both forms: WP16 captures are fully verified
against `container_sha256` with the receipt's sizes bounding the reader; legacy gzip operands (r9 and earlier) stay
readable. Both then meet the same `raw_bytes`/`raw_sha256` check. No numbers change; only the capture container does.

## Change (r5; owner files unchanged since my base)
| File (owner path) | Base sha256 | Candidate sha256 | Diff |
|---|---|---|---|
| R/compact_restart_patch.py | 9d076c80 | **1a1088d9** | T/so/s2/r5/compact_restart_patch.diff (135 lines) |
| R/ledger_fresh_interval.py | cd89718b | **775bb0a4** | T/so/s2/r5/ledger_fresh_interval.diff (84 lines) |
| R/test_step8_coverage.py | fcd8cf6a | 59adb189 (unchanged since r4) | T/so/s2/owner/test_step8_coverage.diff (50 lines) |
| R/fresh_interval_driver.py, R/prepared_interval_driver.py | yours | + 2 lines each, applied by you | T/so/s2/r5/driver-lines.diff |
| new: test_wp16_preadvance.py | - | **fc8bc908** | 18 cases |
| new: test_s2_route_wiring.py | - | **50ea132c** | 4 cases (2 read your composed drivers) |

Full candidate files: T/so/s2/r5/*.py. The owner-layout coverage test is T/so/s2/owner/test_step8_coverage.py
(59adb189). test_wp16_preadvance.py takes SO_TMP for its temp folder (default: its own folder). r4 (e28331f2,
17162d30, 4bc22b32) is superseded; r4-to-r5 diffs are in T/so/s2/r5/.

- compact_restart_patch: `capture_operand`/`capture_operands` replace the gzip writer and `coverage.save_operands`
  for the compact route, with the same order and checks. Each file is published exclusively and atomically, the
  receipt is checked against the file, the mesh `raw_sha256` must equal `geometry_id`, and the parts are 64 KiB.
  There is no raw or gzip fallback, and a changed library refuses.
- **Run-start route check (r5, replaces r4's import-time find_spec):** `require_capture_route(store)`. For a compact
  store (`type(store) is CompactRestartStore`), it really imports `capture_store` and `storage_zstd_backend` (so under
  the selected runtime's Loader, each must be pinned) and loads the pinned library (`capture_backend()`, sha checked).
  It returns the library sha. Any other store returns None and imports nothing. A missing or unpinned module raises
  ImportError('WP16 pre-advance capture route incomplete: ...'); a missing or changed library raises.
  Importing compact_restart_patch no longer touches the capture route, so the legacy composition imports it as before.
- **Your two lines per driver (text in driver-lines.diff; I checked them only on local copies of your current shas):**
  - fresh_interval_driver.advance_first_interval (f328f314): first statements after the docstring, before
    `_seed_pinned()`: `from compact_restart_patch import require_capture_route` then `require_capture_route(store)`.
  - prepared_interval_driver.advance_prepared_interval (c4f5c4fb): right after the frozen-duration `_require(...)`,
    before `record.update(original_target=...)`: the same import, then `require_capture_route(workflow._store)`.
  - test_s2_route_wiring.DriverTests checks those placements on whichever drivers are first on sys.path. Today it
    FAILS 2 on your drivers and passes 2 on the patched copies.
- ledger_fresh_interval: `captured_bytes(path, container_sha256, raw_bytes, stored_bytes)`. Before it allocates
  anything, r5 requires:
  - int sizes with 0 <= raw_bytes <= 16 GiB and 0 < stored_bytes <= 16 GiB;
  - container_sha256 as 64 lowercase hex;
  - the file size equal to stored_bytes.

  Then: one preallocated buffer; `max_logical_bytes=raw_bytes, max_stored_bytes=stored_bytes`; overflow refused; a
  full verified stream required. A missing reader raises LedgerRefused. A damaged legacy gzip (EOFError, zlib.error)
  now raises LedgerRefused (exit 2, REFUSED), not exit 1 (FAIL).
- The legacy (non-compact) route is untouched and stays gzip.

## Composition (generation note needed: explicit repin)
1. Add `capture_store.py` (R/diagnostic-captures, 4664b205) to composed-r2/helpers and to composition.json's `files`.
   That manifest is the selected runtime's pin table (run_prepared_restart.py:424-431), so an unlisted capture_store
   refuses at run start, which is the intended early refusal. storage_zstd_backend.py (0e0ebf31) is already listed.
   The WP10 library is read from its permanent absolute path (`CAPTURE_LIBRARY` = R/compact-geometry-r1/native/
   wp10_zstd.dll, sha a40c24ad), not from the workspace. Its imports are stdlib, `atlas_tectonics.resources`
   and `storage_zstd_backend`. Also add it to your fixture copy lists and test roots wherever the helpers are copied.
2. Repin compact_restart_patch.py, ledger_fresh_interval.py and test_step8_coverage.py to the candidates above, and
   both drivers to your patched shas. compact_restart_patch and prepared_interval_driver are in RFI's FRESH_MODULES,
   and the advance driver has its own pin, so regenerate the profile.
3. Generation note: "S2/WP16 capture-digest generation: pre-advance operands zstd-3 exact-bytes captures with a
   run-start route check; CRP 9d076c80 -> 1a1088d9, LG cd89718b -> 775bb0a4, T8C fcd8cf6a -> 59adb189, drivers +
   require_capture_route; + capture_store 4664b205, test_wp16_preadvance fc8bc908, test_s2_route_wiring 50ea132c".
4. The ledger needs the composed helpers and the runtime source on sys.path wherever it reads WP16 captures. It
   refuses cleanly if they are missing.

## Decisions and flags
- (Yours or Michael's) `CAPTURE_MAX_BYTES = 16 GiB`, the run's existing logical ceiling, replaces capture_store's
  4 GiB default on this route, and the ledger reader uses the same ceiling. Reason: the gzip route had no ceiling, so
  4 GiB would stop a run at pre-advance once the streamed mesh outgrows it. Capture streams 64 KiB at a time, so this
  raises a size ceiling and adds no memory. No guard or memory limit is raised. If you prefer 4 GiB, change the one
  constant.
- (For Storage, P3-c) WP16's own export, replay and CLI readers keep the 4 GiB defaults (capture_adapters.MAX_BYTES,
  the CaptureReader default). A 4-16 GiB capture written by the run reads in the ledger but is refused by those tools,
  around interval 3 or 4 at about 4x growth per interval. Fix there: take an explicit limit or read it from the receipt.
- Accepted residual: the run-start check keys on the store type. A compact mesh on a legacy store is not checked at
  run start; if that ever happens, it refuses at capture (fail-closed, but after the advance).

## Proof
- Tests r5 (T/so/s2/r5-check/tests-r5.log; run_all_r5.sh, run_tests_r5.py; build in build-r5.log), 16 Oct 15:12.
  The loaded-file lines confirm which files ran.
  - base: 8 OK.
  - r5: 28 OK.
  - DriverTests: FAIL 2 on your drivers, OK 2 on the patched copies (as intended).
- Planted mutants r5 (make_mutants_r5.py; same log): 14/14 KILLED. why-errors.log shows each error-type kill fails for
  the mutated reason.
  - Route: find_spec only, every store checked, no library load, import-time capture, subclass accepted, error
    swallowed.
  - Ledger: each of the four bounds dropped, allocation first, each legacy exception uncaught, uppercase hex.
- r4 evidence still stands for the writer, which r5 does not change: rq2.log has 9/9 mutants fail closed and the
  control PASS against r9's operands (peak 1.91 GB). Smoke gain: median 1.22 s; disk 91.96 MB -> 79.55 MB.
- Refuter: first pass (a)-(e), all fixed in r4. The r4 delta found one P2 and P3-a/b/d; r5 fixes the P2 and P3-a/b/d,
  and P3-c is flagged above. r5 delta re-check: PENDING.
- Ruff F,E9,B,PLE, base against r5: no introduced findings.
- q15 timing (LNNL/NLLN x3, exact-bytes control vs r9): HELD (PAUSE), runs after the re-check. Storage's measurement
  for comparison: -1.0 to -1.26 s.

## Later-step impact
Each interval's pre-advance writes about 12.4 MB less (smoke fixture) and saves about 1.2 s. A compact run missing
its capture route now refuses before the advance instead of after it, so that interval's compute is not lost.
Restart and reopen read captures through the verified reader, and r9 receipts stay readable. Next-interval capacity:
no new memory, since capture reserves about 10 MB at its peak.
