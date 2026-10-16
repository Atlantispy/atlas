# S8 integration note: readers record the live-producer child's accounting

From "Small optimisations", 16 Oct 2026, 13:52 (by clock). For "Runner pipeline and final integration" (owner and integrator).

## What it does
A reader scope from `RUN.new_retained_scope` carries the named live-producer child, so PRODUCER_PURPOSES charges
book there and not against the 256 MiB retained aggregate. The readers did not record that child, so a receipt could
not show what the producer held. This change records it. It is observation only: no charge, limit, order or result
changes, and the existing `retained_scope` schema and its validators stay byte-for-byte as they are.

## Change (2 files, rebased onto your current RF)
| File | Base sha256 | Candidate sha256 | Diff |
|---|---|---|---|
| reopen_prepared_restart.py | d93fe9c23698529aa370ad08e7b5cc5dee48fe1e602f62304a2c5ac7aed47586 | 5b7f13bf4ddcf2b0500071c69287d829cde216021a00b2ef95e600b9673b8f24 | T/so/s8/reopen_prepared_restart.diff (72 lines) |
| reopen_fresh_restart.py | c36ad987addaa014a46f3b03164d1f2fcd40252dfaa6696a3dba71a7aa1f3145 (your item 7 file) | f06f4fe046759a3d49108d2891a5a4be6b1fe5620eead44d572a355a376266fe | T/so/s8/r2/reopen_fresh_restart.diff (22 lines) |

Full candidate files: T/so/s8/r2/*.py. The earlier RF candidate (0fbfb890, on 59138100) is superseded. The same two
hunks apply to c36ad987 at an offset of 17 lines, with no other change.

- New in RO: `producer_accounting(scope)` (scope_id + producer_limit/bytes/peak/refusals + the two purpose maps,
  read from `scope.stats()`), `validate_producer_accounting(value, scope_id=)` (exact key set, non-negative ints,
  bytes <= peak <= limit, bounded maps, purposes sum to producer_bytes), and `validate_retained_producer(reopen, retained)`.
- Both readers write the sibling field `record['retained_producer'] = {before_close, after_close}` next to
  `retained_scope`, at the same two points.
- The validators call `RO.validate_retained_producer(reopen, retained)` after the retained checks. **The field is optional:**
  a receipt without it (all existing receipts) validates as before. When the field is present it must be complete, and
  `null` refuses. Its scope_id must equal the retained scope's.

## Proof
- Tests (T/so/s8/tests-r7.log, harness T/so/s8/run_all_tests_r2.sh, one process per module, and the loaded-file
  lines confirm the r2 files were used):
  - base: 13 + 14 OK;
  - candidate: 13 + 14 OK plus 4 new tests in T/so/s8/test_s8_producer.py (020dd9f6). The new tests cover the
    record shape, refusals (null, missing half, wrong scope_id, unreconciled sums), old receipts still validating,
    and the fresh-reader adoption wiring through your own `TF.ReaderReceiptAndAdoptionTests.validate`.
- Refuter (one, on this route): no P0–P2, four P3s. Two were acted on: null now refuses, and the wiring test is added.
  The probe and the refuter's notes are in T/so/refute/s8/.
- Ruff F,E9,B,PLE, base against candidate: no introduced findings.

## What the owner should do
1. Review the two diffs, then take the full files from T/so/s8/r2 into your next generation (generation note:
   "S8 observation-only field retained_producer; RO d93fe9c2 -> 5b7f13bf, RF c36ad987 -> f06f4fe0").
2. If RF moves again before you integrate, re-apply the 2-hunk diff yourself; it touches only the close block and
   the validator's retained loop.

Later-step impact: none on results, storage or timing. Receipts gain one small field (two dicts of at most 4096
purpose counters; in practice a handful), which future memory-booking decisions can read.
Next-interval capacity: no new memory or disk beyond that field.
