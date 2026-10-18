# Optimisation programme changelog (14-16 Oct 2026)

Status: WORKING NON-CANON. Results are labelled MEASURED or PROJECTED. "Built" means implemented and focused-tested,
with its proof run still pending. Nothing here is scientific acceptance.

Limits held throughout: 12 GiB RSS, 1 GiB free-memory floor, 16 GiB logical, 256 MiB caps, the 1 MiB integer limit and
the 256 accepted-step ceiling. No tolerance is relaxed.

## 18 Oct 2026, Plans 01 and 03 source publication

- Added the reviewed Plan 01 test-isolation successor and five-case fixture checker in the workbench; the frozen composed helper and its pin remain unchanged. Retained original-environment evidence: 235 tests OK, eight existing skips, plus 5/5 isolation checks.
- Added Plan 03 r5 wrapper/test successors, preserving prior versions and the unchanged summariser. Child-only PATH/preflight, bounded cleanup, copy refusal and the exact invalid-orphan exception are reviewed; the final two diagnostic/evidence cases pass. Earlier 179/40/7-case evidence is reused within its unchanged scope, not relabelled as a new full run.
- These are public review-snapshot sources. Local paths are sanitised with an original/public digest trail. No private receipts, logs or inputs are included. No live runtime installation, scientific acceptance, q21 retry or hold release is made.

## 17 Oct 2026, completion plans

- Added `plans/`: the finalised completion Plans 01-25 and `plans/INDEX.md` (directory, shared contracts,
  dependencies and status for all 39 plans). Plans 26-39 are still under correction and not included.
- Planning documents only: no source, test, run, hold, repin or acceptance change. Local user paths replaced with
  `LOCAL_USER`; links to unpublished reviews, discussions and local records do not resolve.

## 17 Oct 2026, item21 branch application

- Applied the item21 interval-N chain, start-gate wiring in the fresh-run, reopen and launch drivers, and S1
  query-stage changes to this branch. Working-copy checks matched seven Python driver/test files to
  `ac/r/chain-r3`; Git-normalised publication bytes require their own runtime binding.
  The retained source manifest is SHA-256 `8059c64914babe2fa7420561c1b16493338a69d71f4c7c8b7c8b53f9dea6e83b`,
  step `item21-r3-verdict-pin`. Branch-authored method notes are in `drivers/INTERVAL_CHAIN.md`.
- Reused the focused private evidence recorded in that manifest for the unchanged source bytes. This metadata
  update does not report a new test run, a live runtime swap, a runtime-manifest re-pin or scientific acceptance.
- The start gate's second route and final-composition pin remain pending. Finish-driver S1, geometry and S2
  capture-writer work are unchanged. All existing run holds and numerical/resource limits remain in force.

## 16 Oct 2026, evening

- Sealed interval-1 heat reopen 46.1 → 15.7 s (MEASURED): page and segment reuse merged into
  `composed-r2/helpers/segment_store.py`. Test failure set unchanged.
- Start-up measurement reuse 910.9 → 64.4 s (MEASURED under other machine load; indicative).
- Step 10 growth build checked on real intervals 1 and 2: structure identical to the reference, no violations; the
  only difference is 245 charts no longer started. Surface CPU: interval 1 893 → 454 s, interval 2 885 → 620 s
  (MEASURED, serial shards; not a worker-count result).
- Start gate sized by each run's predicted peak, replacing the fixed 10 GiB start requirement. Built; wiring staged.
- Pose and heat-number width: conditions 1-3 pass (pose change 0.010-0.033% of the certified radius, limit 1% over
  1,000 intervals). The interval-1 replay comparison tool was refuted and is being rewritten.
- Heat certification kernel H3 revision 3: cache names fixed so the identity guard checks the loaded implementation.
- Changed test expectations between remake and `composed-r2` (groups A-D) accepted; none widens a bound.
- Every process that imports the runtime now pins hash seed 0 and fails closed otherwise.
- Added `IN-PROGRESS.md`: part-implemented work, with what is left and each acceptance gate.

## Compact storage and restart (plan steps 1-10)

- One sealed file per interval:
  - catalog and cross-file references;
  - atomic publication with crash recovery;
  - an independent fresh-process reader before promotion;
  - no automatic adoption of a file sealed before a crash.
- Compact records with exact round-trips: graph, transport, state, certification, exchange, geometry, mesh v3,
  partition v2 and the heat ledger.
- Disk, MEASURED on real interval 1:
  - graph record 104.7 → 15.4 MB;
  - heat ledger about 357 → 167 MB;
  - support records 113.0 → 20.5 MB.
- Disk, MEASURED on interval 2: support records 553.9 → 88.8 MB.
- Whole-record copies removed from memory, and structures released after last use. Memory bookings now within
  1.0-1.15x of real use (were 3-18x). Real interval-1 data passes every cap that refused it before: builder,
  transport and stocks export, heat row export, mesh root header.
- Migration, runner and reader:
  - run A creates and seals the start;
  - an independent reader re-derives it;
  - run B reopens it in a fresh process.
- Checkpoint build `composed-r2` frozen-tested to the start of interval 1, every number bit-identical to the reference.

## Speed (MEASURED unless marked)

- Mesh and storage:
  - real interval-1 mesh packing 1,219.5 s → 13.8 s;
  - mesh finish over 24 min 53 s → 26 ms (the mesh is kept in memory);
  - heat-ledger full re-check 40 min → 5 min 23 s;
  - fresh heat-ledger reopen 188-213 s → 71-75 s;
  - record reopen −52%;
  - heat save write loop 5.8 → 0.9 s;
  - transport identity 3.99 s → 0.3 ms per call.
- Heat-ledger reopen page layer: page misses −22.6%, verified chunk resolves −18.2%, byte-identical. Built.
- Geometry:
  - exact rotation reuse and a faster number type: interval-1 interfaces 777 → 511 CPU-s;
  - all geometry changes together: interval 1 714 → 396 CPU-s;
  - filtered predicates: −10.6% on the hard interval-2 cases;
  - interval-2 endpoints: 24 queries that never settled now all settle, in 401 CPU-s;
  - interval-2 interfaces: about 221 queries that never finished (at least 21.6 serial hours) now all settle
    (PROJECTED 1.9-2.1 h on 4 workers).
- Parallel workers:
  - worker cap 2 → 6, with rolling batches;
  - interval-2 interfaces 946 → 569 s on 4 workers;
  - interval-1 geometry 546 → 305-310 s;
  - byte-identical at every worker count.
- Start-up metrics 407 → 285 s per process, with code files locked against change during the run.
- Pressure stage, small case: −35% serial, −58% with walls in parallel. Built; the full-scale proof is pending.
- Pressure transport gate: 56.1 → 45.9 s (−18%) on the small case; worker memory 170 MiB real against 768 MiB booked.

## Growth control (results unchanged)

- Unreferenced support constraints are no longer stored.
- Pieces proved empty no longer seed the next interval's charts.
- Interval 2, MEASURED:
  - constraints 598,337 → 76,135;
  - supports 5,801 → 3,502;
  - pieces 31,769 → 23,585.
- Not adopted, because they change results: merging charts that carry material, and re-basing carried constraints.

## Exactness and safety

- Exact zero-area certificates for the stalled interval-2 queries.
- A difference ledger that traces every bound difference between reruns.
- A per-interval width gate on the largest exact numbers. It only refuses.
- Fail-closed proof harnesses with planted mutants.
- A heavy-run queue with job-object memory tracking and predicted-peak start gates.

## Tested and switched off (measured outcome kept)

| Item | Outcome |
|---|---|
| Record compression | Real-data gain −0.02% to −0.54%; existing encoding kept. |
| Compact worker data | 1-8% of worker memory, and slower dispatch. |
| Heat warm starts | No gain. |
| Crash-proof query store | Passes 12 hard kills; stays off until fresh-run counts show it pays. |
| Cross-query cache, decoded-support cache, spatial index, packed keys | 0-0.3% each. |

All of these are re-tested on the combined build before the fresh interval runs.

## Built, proof pending, or in progress

Superseded on 16 Oct by `IN-PROGRESS.md`, which lists the current state of each item.

- Built, with the proof run pending:
  - heat reconstruction: accounting fast path, fused dot, inline growth and prepare reuse (about 11 s per interval);
  - compiled exact kernels: heat sum of products (numba with MPFR) and a geometry jet number type (gmpy2);
  - admission: reuse of start-up measurements (PROJECTED about 740 s once per lineage) and parallel start-up
    recompute (PROJECTED to about 1/6 of 800-930 s);
  - endpoint batching (interval-2 endpoints PROJECTED 402 → 217 s).
- In progress:
  - geometry arithmetic D1-D5;
  - the runner for interval 2 and later;
  - lazy per-field rows;
  - heat finish and commit speed-ups.
- Measurement note: one heat proof arm took 119 s without the `setprofile` observer and 1,173 s with it, with
  identical outputs. Walls measured under `setprofile` overstate cost.

## Decisions

- Heat-number width: the composed pose is rounded to a bounded dyadic inside the declared pose error budget, and the
  mesh deviation sum is stored as an outward-rounded bound. The added error must be proven to stay ≤ 1% of the budget
  over 1,000 intervals. Conditions 1-3 pass; the interval-1 replay is pending. It lands before the fresh runs.
- Release mode: check policy D1-D6 plus the seal/promote boundary are approved. Scientific checks and resource guards
  stay on in every build. Not being built yet.
- Compiled code:
  - finish the two built kernels;
  - re-measure once after the other speed work;
  - then use Cython (with libmpdec and gmpy2's C API) for exact jets and rationals, and keep numba for the heat
    kernel;
  - install a compiler only if the re-measure shows at least 15% left to gain;
  - pin the interpreter's decimal and arithmetic binaries in the execution identity.

## Before landing on remake

- Proof runs.
- Final assembly of every enabled change, with its checks.
- File-by-file reconciliation with the current package.
- Reader chapters and method docs.
- New receipts.
- Fresh full runs of each interval.
