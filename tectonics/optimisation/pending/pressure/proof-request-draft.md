# DRAFT: P1-P3 full-scale proof REQUEST (send only after RESUME; booking needs q02 and sm6)

REQUEST: P1-P3 full-scale worker-count proof (EXCLUSIVE). Backlog item 2.
- Candidate: T/ps/c/w6f5 (gg/workers6-r6 + p2 p1 p3; module r5 61d2019e).
- Base: test:T/gg/workers6-r6.
- Inputs: interval 1's real starting state through the fresh-driver admission; read-only.
- Outputs: T/ps/fp/{base,cand}, plus fp.log.
- TOTAL: <X> GiB (from sm6 per-worker peak scaled, plus the parent's full-scale peak from q02 or the s2 558 MiB WS).
- Estimate: <Y> min.

Command (one ticket, two processes in sequence, then the compares):
  cd T/ps && ab_pressure_r4.py --output-dir T/ps/fp/base --runtime test:T/gg/workers6-r6 --arms serial \
   && ab_pressure_r4.py --output-dir T/ps/fp/cand --runtime test:c/w6f5 --transient \
        --arms serial,auto1,auto2,auto6,auto6:-1=decline,auto6:-2=crash \
   ; compare_ab_r2.py fp/base fp/cand --null-fields nullfields-ab2.json

Coordinator conditions (16 Oct 15:10, r5 APPROVED), all reported from fp/cand/report.json:
(a) Full-scale raw input_bytes, decoded_bound and child_bytes from the transport gate value.
    - Production passes policy.child_bytes. InterfaceParallelPolicy defaults to 512 MiB (selection l.47).
    - Dispatch's 128 MiB is only BatchParallelSession's constructor default, which PressureWallSession always overrides.
    - Report the worker's real peak (session stats peak_child_rss) next to its booked peak (peak_child_ledger).
    - Report the declined and recomputed walls per arm.
    The margin is decided from these numbers.
(b) Real next to booked: the decoded bound (25x raw) against the worker's kept copy and its RSS. This goes on the
    match-real-cost list.
(c) The parent's unbooked transient, from the untimed --transient pass in ab_pressure_r4 2e6aa2f5 (r3 APPROVED ~15:22 with
    conditions, met in r4: verify_boundary run and PASSED with events live, at the gate and after release, all
    recorded; get_tool(3) is None recorded; memory only, reported apart from the timed arms). That pass runs
    tracemalloc on _shared_inputs only (sys.monitoring local events; nothing rebound, so the loaded-implementation
    check holds), ends at the gate's first instruction and starts no worker. It reports the traced peak and what is
    retained. If the transient is over 256 MiB, book it before integration; otherwise fix it in the same match-real-cost
    generation as (b).
(d) Reopen: no change (0 reopens on 6 real walls).

Checks (fail closed):
- cand: ARMS EQUAL across all 6 arms (forcing_id, arrays, leaves, driving_id).
- compare_ab_r2: IDENTITY-ONLY (D-b, null-field-controlled), or NUMBERS EQUAL.
  - nullfields-ab2.json holds the 11 identity fields moved by the small-case docstring-only control (ab2/base vs ab2/null).
  - Any other differing field gives DIFFER; we would then need a full-scale null run.
- The report records, per arm:
  - the gate decisions;
  - free_cores_at_start;
  - workers granted vs asked;
  - walls adopted, declined and crashed;
  - TOTAL and per-worker peaks.
- An arm that could not get its workers is VOID-ENVIRONMENT, not FAIL, and gets a rerun REQUEST for that arm alone.

Review-before-queue:
1. Refuter delta review r2->r4: HOLDS on correctness; gate finding fixed in r5 (refute/p1d). r5 delta: HOLDS.
2. Fail-closed checks:
   - mutants_p1r3 4/4; gate_p1r5 4/4;
   - contract_planes 6/6;
   - indexed_db 3/3;
   - compare_ab_r2 4/4;
   - transient_r4_check 9/9 (clean, unbound, again, fail-live, fail-gate, fail-after, traced, busy, no-build);
   - ab_pressure ARMS DIFFER exit 1.
3. Smoke of the exact harness: sm7 (small, c/w6f5, serial,auto1,decline,crash); sm6 on r4 exposed the gate defect;
   sm8 (r2) arms equal but its transient pass was refused by the loaded-implementation check; sm9 (r3): ARMS EQUAL, exit 0;
   transient (small) peak 25.6 MiB = 9.18x raw, retained 1.0x raw;
   sm10 (r4): ARMS EQUAL, 3 inventory checks passed, tool released, TRANSIENT MEASURED, exit 0.
4. Pinned:
   - c/w6f5 composition manifest;
   - module 61d2019e;
   - transforms p1_loop 0928d1ad, p1_binding 0c8fe3be, p1_dispatch ba949b37, p2_spatial b498c170, p3_coupling ba828fd9.
   New output folder fp; source frozen.
5. EXCLUSIVE, because this is a worker-count proof.
6. No duplicate in the registry: <check>.
7. Overrun: report at 1.5x.

Booking basis (PROJECTED until q02 and sm6 are in):
- Admission: s2 IV1 run-root, 840 s and peak WS 558 MiB (MEASURED). It runs once per process.
- Base pressure serial: about 560 s (r8: 966 s metrics+pressure minus 407 s metrics; old code).
- Candidate per-arm ratios from the small case (MEASURED, composed-r2):
  - P2+P3 serial: 0.65x;
  - auto2: 0.42x;
  - auto6: bounded by the largest wall (one wall was 42 of 64 s serial in the small case).
- Base process: about 23 min. Candidate process: about 37 min. Total booking: about 70 min.
- Peaks: parent ~0.7 GiB plus 6 workers x 0.2-0.4 GiB gives about 3.5 GiB TOTAL. Gate need: 3.5 x 1.2 + 2 = 6.2 GiB free.
