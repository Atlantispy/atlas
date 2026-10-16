# S4 "retry the open later" (backlog 20) — code-owner review, 16 Oct 2026

Reviewed: T/so/s4 (INTEGRATION.md 13:43), the three diffs on gg/workers6-r6:
rolling 6daa2d3a → c6c8a702, selection 7d4d4037 → a0d90167, auto fa0cbcaf → 092dca7c;
test_s4_retry.py (9bb588f6), tests-r3.log (6/6 pass). Small optimisations' refuter: no P0/P1, its P3s fixed.

## Verdict: ACCEPT (no P0–P2)

## Checked and fine
- **Before any batch only.** `LATER` is returned by `_open` before a session, funding or worker count exists.
  - `_machine()` runs first. On refusal it sets `_Rolling.workers = 0`.
  - `schedule.workers` is set only after a real open, so it is unchanged.
- **Nothing is planned between retries.** `advance()` returns before `_again` or a plan while `session is None and clock < _retry`.
  - `_again` was cleared before the plan that tried the open, so the first advance after the retry time plans again.
- **The lookahead stays bounded while deferred.**
  - `reached()` pops `ahead` and retires `live` independently of `advance()`.
  - `hungry()` is unchanged: `stopped` is None, so the router keeps offering within the horizon and a round of work, exactly as before any first open.
  - A deferred pass therefore holds no more than one that has not yet opened.
- **The report matches the old shape.**
  - If the pass ends mid-deferral, `close()` records `stopped='session not opened'` with the refusal count.
  - `_retry` is ignored once a session exists.
- **Bounded cost.** At most 24 deferrals at 15 s doubling to 120 s (about 45 min). Each costs one `cpu_percent(0.05)` probe and one plan.
- **Gates.**
  - `psutil` is permanent: it stops at once.
  - cpu, memory, budget and predicate units are momentary hints; nothing is reserved.
  - Budget or predicate units can stay short for a whole pass. That costs at most 25 cheap looks (efficiency only).
- **Records and order.** A late session is an ordinary first session opened later in the pass. The parent's order and what it adopts are unchanged by construction, the same as a pass whose first batch becomes worth starting late.
- **Evidence the case is real.** In `evidence/wp18-smoke-r1`, the IV2 auto arm's first open was refused by the cpu gate after 2 plans, and the pass stayed serial (55.8 s). The IV2 w6 run lost 125 s the same way.

## Interplay with WP18 r2 (same auto module)
- WP18 r2 reads supports ahead with no session open only while the schedule's plan asks for more (`offered < _wanted`).
- During a deferral that is at most the last plan's request, so a deferral never makes the endpoint lookahead read the whole pass.
- S4's auto hunk (`_open`) is disjoint from every WP18 anchor.

## P3 (cosmetic, not fixed)
- A pass that opens late but launches nothing reports `reason='session deferred'` (its last note) with `stopped` None.

## Integration
- **Transforms.** Generated mechanically from base → candidate hunks; each reproduces the candidate byte for byte (`make_s4_transforms.py`, in my scratch):
  - `transforms/s4_retry_rolling.py`
  - `transforms/s4_retry_selection.py`
  - `transforms/s4_retry_endpoints.py`
- **Compose names:** s4roll, s4sel and s4auto. s4auto goes after wp18.
- **Not inside q18's WP18 proof runtime** (gg/wp18-r2), so that proof stays attributable. S4 goes into the next package generation and the Step 10 candidate. The parity controls there cover results.
- **Measurement owed** (Small optimisations' item 3), on the next IV2 w6-type run whose first open is gate-refused:
  - `reasons['session deferred']`;
  - the open time;
  - batches started;
  - the pass wall time against the serial pass (the 125 s case).
