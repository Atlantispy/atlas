# Item 10: stage overlap ("admit ahead"). Design for the coordinator's approval (16 Oct 2026)

Status: DESIGN ONLY, nothing built. It changes process order, so it needs the coordinator's approval before any code.

## What the smoke showed (s2, composed-r2, 16 Oct)

Every route (1) process spends about 1,000 s on store-free work before its first store access. That work is the same initial native admission in every process: startup, native admission, initial metrics, the spatial owner, and the workflow identity.

| process | store-free admission | store work |
|---|---|---|
| run A (root) | 838 s (sealed at 839 s) | create and seal the root, about 11 s |
| root reader | 958 s | open and verify, about 30 s |
| run B (stop-before-advance) | 1,002 s | reopen and compare, about 29 s |

The current order is strictly sequential: run A, reader, finalise, adopt (one launcher stage), then run B, reader, finalise, adopt (the next stage). Root plus interval 1 therefore pays about 4 × 1,000 s of admission one after another.

**Later intervals: UNVERIFIED (corrected 12:58).**
- Route (1) has only the root and interval 1. Interval 2 continues on the prepared successor route, generalised to an ordinary head (`design-route1-steps2-3.md`); that generalisation is not built yet.
- If that path re-derives the initial admission to open the head, as run B does for the root, each later interval pays about 2 × 1,000 s, and items 7 and 10 apply to every interval.
- If it restores the spatial owner from the stored lineage, items 7 and 10 apply once per lineage (4 processes).
- Decide this when the interval-2 path is designed. Restoring from the store is the cheaper choice.

**Cause (found 12:39, `S/admission-800s-findings.md`).**
- 99.9% of the admission is the initial metrics.
- With D1 (RC1 items 11/15 off), the 969 initial component queries need 3.2× the leaves.
- Every process writes the identical 969 cached records under identical keys.
- So item 7 (a producer is handed run A's verified store) removes an estimated 700-740 s from run B, once per lineage. A later run(k) benefits only once such a route exists and is reviewed. Only readers must recompute.
- Coordinator (13:10): item 7 approved with 8 conditions; phase 2 approved after item 7 lands, with its conditions; phases 1/3 not approved yet (resubmit after phase 2's measured net gain). Review: atlas/.atlas-dev/review-item7-item10-20261016.md.

## The idea

A process's admission reads no store and writes only its own artifacts directory, so it can run before its gate opens.
- The launcher starts a process early.
- The process completes its admission, then waits at a gate before its first store access.
- The launcher opens the gate only after the predecessor step has passed exactly as it does today.

What stays exactly as it is:
- **Adoption.** Run B still touches the root only after adoption.
- **The reader's full independent recompute.**
- **Every check, receipt and stage record.**

What changes:
- **The order inside run B:** admission → gate → open catalog → `require_promoted_root` → reopen and compare → advance. Today the order is open catalog → promoted root → admission → ….
- **When the next process is started.**

### Phase 1 (what you asked): run B admits alongside the root reader
- Launcher (new pipeline mode, e.g. `--stages root,interval`): when run A's guarded run has passed its postcheck, start the root reader (as now) AND run B. Run B gets `--admit-ahead GATE`.
- Run B (runner): enter `FRESH.admission(...)` first.
  - That needs a small driver change: `reopen_root` and the interval path accept the already-entered admission instead of entering their own. The calls inside are unchanged.
  - Then wait at the gate: a 1 s loop that checks the cancel file and ticks the guard. It does not open any store, catalog or root file.
  - The gate opens when the launcher atomically writes `GATE` (exclusive create) with:
    - the root stage record's SHA-256 and status ADOPTED;
    - the adoption receipt hashes.
  - Run B re-reads those files and checks them before it continues.
  - After the gate, everything is today's code: open catalog, `require_promoted_root`, `ROOT_IDENTITY` comparison of the re-derived admission against run A's sealed root, then the advance.
- **Failure.** If the root reader, finalise or adopt fails, the launcher does not write the gate. It cancels run B through run B's own cancel file and waits for its PID to exit. Run B exits before touching the store, and nothing is adopted. That is the same outcome as today, because run B would never have started.
- **Wall saving:** about min(root reader, run B's store-free part) ≈ 950-1,000 s, once, at root plus interval 1. With item 7, run B's admission is about 60 s, so phase 1 then saves about 60 s once.

### Phase 2: each reader admits alongside its own run's advance
The reader's ~960 s admission does not need the sealed file either.
- The launcher starts reader(k) together with run(k).
- Reader(k) admits, then waits at a gate written only after run(k) has exited and passed its guard, process-tree and receipt postchecks. That is the point at which the reader starts today.
- Reader(k) then opens the pending sealed file and verifies everything independently, as now. It never sees anything of run(k) before that point.
- **Evidence that this is valid.** The reader's admission takes no input from the sealed file: `reopen_fresh_restart.py:513` calls `FRESH.admission(m, budget, artifacts, phase)`. It only compares its provenance and preparation IDs with the producer's root afterwards (lines 514-516).
- **Its pending view, change token and checks** are taken after the gate and held through verification, exactly as now. Only the admission moves ahead of `open_pending`.
- **Wall saving:** about 960 s per interval, while the advance lasts longer than the reader's admission. The current advance is about 1 h at IV1.

### Phase 3: keep the next process pre-admitted
Start run(k+1) when reader(k) starts, gated on interval k's adoption. Run(k+1)'s admission is then hidden behind reader(k)'s admission and verification.
- **Per-interval critical path:** run(k) post-gate (reopen about 30 s, then the advance) + reader(k) post-gate (verify about 30-60 s) + finalise and adopt (about 16 s). That is about 110 s plus the advance, against about 2,000 s plus the advance today.
- Admission stays visible only once per session, at the first interval.
- With item 7, run(k+1)'s admission is about 60 s, so phase 3 then hides about 60 s per interval. That is about 20% of a 5-minute interval.

## Costs and risks
- **Concurrency.** At most three processes are alive: run(k) advancing, reader(k) admitted and waiting, run(k+1) admitting. A waiting process holds about 0.6 GB and no CPU.
  - Memory at IV1: about 5.3 GB (r9's advance peak) + 2 × 0.6 GB ≈ 6.5 GB, within the 12 GiB guard.
  - The heavy lock declares the total.
  - Two admitting processes take two cores. That slows the advance's 6-12 worker passes a little, and it is measurable.
- **The 10 GiB start gate** is checked at each process start, as now, so it is checked with the other processes alive.
- **Determinism.** Each process's admission is the same deterministic computation as today, with PYTHONHASHSEED=0. The `ROOT_IDENTITY` comparison after the gate is unchanged and still catches any difference.
- **Interaction with item 7** (producer cache; run B reuses run A's certified measurements). REVISED 12:41, after the 800 s finding.
  - Item 7 is exact and close to free.
    - `integration_dual_geometry.cached_initial_component` already reuses a verified store losslessly. On a hit it re-checks each stored field's consistency with the request; it does not certify the geometry again (wording corrected 13:15, review condition 8).
    - The keys match across processes (969 of 969).
    - It cuts a producer's admission from about 800 s to an estimated 60-100 s (q08 measures it), and frees about 700 CPU-s that would otherwise compete with the advance's workers.
  - Readers must recompute everything, so item 7 cannot help them. Phase 2 hides their admission.
  - **Recommended order:**
    1. item 7;
    2. item 10 phase 2: the reader's about 930 s, or about 150-200 s if the geometry chat's parallel initial metrics lands;
    3. phases 1 and 3. After item 7 each hides about 60 s, but that is about 20% of a 5-minute interval, and they reuse phase 2's gate.
  - A reader admitting with parallel workers next to an advance competes for the 8 physical cores. Measure it through the queue.

## What I would build (after approval)
- **Runner** (`run_fresh_interval.py`): `--admit-ahead GATE`; the admission entered before the catalog; the gate wait (cancel, guard and stale-gate refusal).
- **Driver** (`fresh_interval_driver.py`): `reopen_root`, `create_root` and the interval path take an optional already-entered admission.
- **Reader** (`reopen_fresh_restart.py`): the same pattern for phase 2.
- **Launcher** (`launch_fresh_interval.py`): the pipeline mode. It starts processes early, writes gates only after the existing step passes, and cancels by cancel file and PID. The stage records stay the same, and each process gets `admitted_ahead`, `gate_wait_seconds` and the gate digest.
- **Tests:**
  - gate verification: wrong stage, wrong digest, stale gate, gate written before adoption;
  - cancel before the gate leaves the store untouched;
  - a reader failure means no gate and run B exits.
- **Then a smoke:** the root and interval stop-before-advance pipeline on the next composition. Compare against s2: identical root identities, receipts equal apart from the timing fields, and the wall time.
- **Later-step impact:** root plus interval 1 benefit for certain. Later intervals benefit only if the interval-2 path re-derives the initial admission (see "Later intervals: UNVERIFIED"). Where it applies, the saving does not grow or shrink with interval size, because it is the same initial admission.
- **Interval-3 line:** at IV3 the advance peak is larger, so check the summed peak (advance + 2 × 0.6 GB) against the 12 GiB guard and the declared heavy lock.
