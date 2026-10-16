# S4 integration note: "retry the open later" in the RC1 rolling scheduler (backlog item 20)

From "Small optimisations", 16 Oct 2026, 13:43 (by Get-Date). For "Geometry speed and parallel workers" (file owner and integrator).

## What it fixes
A rolling pass whose FIRST worker session is refused by a machine/ledger gate (free cores, memory, budget, predicate
units at that moment) used to stop with 'session not opened' and stay serial for the whole pass. IV2 w6 lost 125 s
that way (PROJECTED gain: up to that much per affected pass; zero when the first open is admitted).

## Change (3 files; base = gg/workers6-r6 package as sent by Geometry)
| File | Base sha256 | Candidate sha256 | Diff |
|---|---|---|---|
| integration_parallel_rolling.py | 6daa2d3a… | c6c8a702… | T/so/s4/integration_parallel_rolling.diff (93 lines) |
| integration_parallel_selection.py | 7d4d4037… | a0d90167… | T/so/s4/integration_parallel_selection.diff (42 lines) |
| integration_component_volume_auto.py | fa0cbcaf… | 092dca7c… | T/so/s4/integration_component_volume_auto.diff (13 lines) |

Full candidate files: T/so/s4/*.py. (Full shas: `sha256sum T/so/s4/*.py`.)

- `Schedule` (rolling): `session()` may return the new sentinel `LATER`. The schedule then looks again at growing
  intervals of its own clock (DEFER 15 s doubling to DEFER_MAX 120 s), at most DEFERRALS = 24 deferrals; the 25th
  refusal stops with the old reason 'session not opened'. Between retries `advance()` returns before planning, so
  nothing is planned, offered, launched or held. A pass that ends while a deferral is pending now reports exactly
  as before: `stopped='session not opened'` (and `_Rolling.summary` puts the refusing gate's note in `detail`).
- `_Rolling._open` and `AutomaticEndpoints._open`: a `_machine()` refusal goes to the new `_Rolling._refused`, which
  returns `RB.LATER`, or `None` (stop at once, as before) for gates no later look can pass (`PERMANENT_GATES =
  {'psutil'}`). Repeated refusals by the same gate keep one (latest) note, so the 8-note report window keeps the
  pass's earlier notes. LATER is returned before any session, funding or worker count is created.
- Unchanged: a refused session or funding (`_open` returns None after the machine gates) still stops at once; a
  late session only changes which LATER requests are offered to workers, never the parent's order or what it adopts.

## Proof
- Tests: T/so/s4/test_s4_retry.py, 6 tests, all pass (T/so/s4/tests-r3.log; run with T/so/s4/run_tests.sh, which
  puts T/so/s4/pkg — your package with the 3 candidates overlaid — and composed-r2/helpers on sys.path):
  defer then open and launch, bounded retries with growing gaps, None still stops at once, no planning between
  retries, a pass ending mid-deferral reports 'session not opened', open answer shapes (LATER, note collapsing,
  psutil -> None) in both `_Rolling` and `AutomaticEndpoints`.
- Refuter (one, on this route): no P0/P1. Its four P3 notes are all fixed in these files (stop-text count,
  mid-deferral report, note crowding, permanent psutil gate / doc). Probe: T/so/refute/s4/probe.py.
- Ruff F,E9,B,PLE base vs candidate: no introduced findings.
- Cost: at most 25 probes per pass, each ~50 ms (psutil.cpu_percent(interval=0.05)) plus one plan, at least 15 s
  apart: <= ~1.75 s per pass, only in passes whose first open is refused.

## What the owner should do
1. Review the three diffs (you asked to review any geometry file change).
2. Integrate into your next package generation (new files; your parity controls cover results: the parent's
   order and numbers cannot change by construction).
3. Measure on your next IV2 w6-type run where the first open is gate-refused: report `reasons['session deferred']`,
   the open time, batches started and the pass wall time against the serial pass (the 125 s case).

Later-step impact: none on results or storage; only passes whose first open is refused change (they can go parallel late).
Next-interval capacity: no new memory or disk; nothing is held while deferred.
