# S1 integration note: WP17 completed-query counters per guard stage in run.json

From "Small optimisations", 16 Oct 2026. FINAL r4 (15:27): the r4 delta re-check PASSED with no P0-P2. It is for
"Runner pipeline and final integration", who applies it. The hook was agreed with Runner at 13:4x: observe from the
runner's save().

## What it does
`run.json` gains `completed_queries_by_stage` (schema `atlas.completed-queries-by-stage.v1`), with one row per guard
stage:
- `hits`, `misses`, `written` and `incomplete` as exact deltas of the live completed-query owner's own counters over
  that stage;
- `unflushed` as last read;
- `opens`, the number of `query_checkpoints` opens in the stage.

The record also carries `opened_with` (the counters at each open) and `status` (COMPLETE or INCOMPLETE).

A stage with no live owner has null counts, never 0. This is observation only:
- nothing wraps the owner, the guard or a query;
- the guard's phase names and order are unchanged;
- no number, store or result changes.

How it observes:
- `guard.phase()` sets `record['stage']` and then calls the runner's `save()`, so the wrapped `save()` sees each stage
  change after that stage's last query.
- `completed_queries()` reports open and close.
- `finish()` (in the runner's finally) observes once more, closes the last row and sets `status COMPLETE` before
  the final status; observation stops there. A run killed hard never reaches it: its run.json keeps the rows closed by
  its last save(), with no status and no in-progress row.

Failures:
- An instrumentation failure (any Exception) is recorded (`status INCOMPLETE`, `error`) and stops only this
  observation. It never fails the run, as with dev_stage_timing.
- r3: an interrupt (KeyboardInterrupt, SystemExit or any other BaseException) that lands inside an observation is
  recorded the same way, then re-raised unchanged. So a row it may have half-updated is never reported COMPLETE, and
  the run stops exactly as it would without S1.
- r4: both branches store `status INCOMPLETE` first, as a plain dict store with no call before it, and only then
  record the error. A second interrupt arriving while the first failure is recorded therefore still leaves the rows
  marked: no later save adds to them and finish() cannot call them COMPLETE.

## Change
| File (owner path) | Base sha256 | Candidate sha256 | Diff |
|---|---|---|---|
| R/run_fresh_interval.py | 8e825d29 | **066a7079** (r4) | T/so/s1/r4/run_fresh_interval.diff (209 lines) |
| new: test_s1_query_stages.py | - | **d93ed6b7** (r4) | 17 cases |

Apply the r4 files: T/so/s1/r4/run_fresh_interval.py and T/so/s1/r4/test_s1_query_stages.py. r3 (66a5000f, b1c3c051),
r2 and r1 are superseded. r4 changes only `_safely` and the class docstring (build_s1_r4.py; r3-to-r4.diff, 30 lines;
tests-r3-to-r4.diff, 44 lines). It fixes the r3 delta re-check's P3s: a second interrupt inside `_stop` could leave
no status, so a later save counted the row again (hits 14 against a true 7); and one 140-character docstring line.
r3 had fixed the r2 delta's P3s (an interrupt between two updates of a row; E302).

Base: R/run_fresh_interval.py is 8e825d29 (with item 7), which you confirmed at 14:5x. composed-r2/helpers still holds
the earlier composition (e3d5c342, 11:07), so compose from R. If R moves before you apply this, send me the sha and I
rebase: the seams are exact, and the builders refuse a seam they cannot find exactly once.

## Composition (generation note needed: explicit repin)
1. Repin run_fresh_interval.py 8e825d29 -> 066a7079 (or the rebased sha). Add test_s1_query_stages.py.
2. Generation note: "S1/WP17 query-stage generation: completed-query counters per guard stage in run.json
   (observation only); RFI 8e825d29 -> 066a7079; + test_s1_query_stages d93ed6b7".
3. run.json gains one top-level key. I grepped the 16 composed helpers that name run.json (launch, reopen, restart,
   publish and worker selection, plus their tests) for an exact key-set check and found none.

## Proof
- Tests, r4 (T/so/s1/r4/tests-r4.log; r4-tools/run_all_tests_r4.sh), 16 Oct 15:21:
  - the owner's test_run_fresh_interval (relocated only: 543e5608): base 41 OK, r4 41 OK. The loaded lines show
    base/ ran 8e825d29 and r4/ ran 066a7079.
  - the 17 S1 tests on r4: 17 OK.
- Planted mutants, r4 (same log; r4-tools/make_mutants_r4.py): 24/24 KILLED. That is r3's 22 plus m23 and m24 (the
  status store removed from each failure branch).
- Refuter (T/so/refute/s1):
  - r1: PASS, no P0-P2, five P3s, all fixed in r2.
  - r2 delta: PASS, no P0-P2; two P3s (interrupt windows) and E302, all fixed in r3.
  - r3 delta: PASS, no P0-P2; two P3s (double interrupt in `_stop`; a 140-character line), both fixed in r4.
  - r4 delta (delta-r4/delta-r4.log): PASS, no P0-P2; the double-interrupt probes now end INCOMPLETE with no
    duplicated row, at 5 interrupt points x 2 first failures. On 3.12.14 bytecode, both handlers reach the status
    store with no CALL, RESUME or backward jump. Only a Python-level tracer (settrace, coverage, pdb) could interrupt
    before it; production monitoring uses PY_START/PY_RETURN only.
  - Two P3s accepted, not fixed:
    - A second interrupt inside `_stop` leaves `status INCOMPLETE` but no `error` text. The rows are correct, and
      only the reason is missing.
    - Pre-existing: an Exception whose `__str__` itself raises escapes `_stop`, so that save() raises. The status
      is already INCOMPLETE, so later saves stop observing. If you want it contained, wrap `str(error)` in a
      fallback; I'll add it on request.
- Ruff F,E9,B,PLE, base against r4 (and the r4 tests): no introduced findings. E301-E305 (preview): none.
- No timing ticket. It is instrumentation: per save, one dict compare; per stage change, four getattr.

## Later-step impact
WP17 can then tell, per stage, how many completed queries hit, missed or were written, which locates the query work
in the 800 s admission (D1) without a profiler. Next-interval capacity: there is no new memory, apart from one small
row per stage in run.json.
