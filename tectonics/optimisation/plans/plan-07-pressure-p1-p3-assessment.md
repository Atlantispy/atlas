# Plan 07 — Pressure P1–P3 profiling and full-scale proof

**Item:** 07  
**Status:** WORKING NON-CANON. Plan amendments agreed in general463 and accepted with explicit additions in general465. P1–P3 is built and checked on the small case; full-scale proof and integration remain outstanding.  
**Owner:** Pressure. Geometry integrates binding/dispatch after the proof; Runner then pins the accepted integration.  
**Completion condition:** Obtain the authorised q02 profile and its fail-closed checks, refine and submit the exclusive full-scale proof request, complete the specified base/candidate comparisons and resource conditions, then deliver the evidence through the existing Geometry/Runner integration boundary. This plan grants no launch or implementation authority.

## 1. Actual change and current status

The primary backlog describes **P1 walls in parallel, preserving order and byte-identical results; P2 per-wall preparation reuse; P3 Fraction hoisting**. Its small-case profile attributes 94% of the stage to `moving_wall_integrals` and about 72% to Fraction overhead (MEASURED, shape only). These are the reported attributions, not a new nested percentage calculation. Remove the former stress-tensor, BEM, bounding-sphere, memoryview and vectorised-chunk explanations: they do not describe the assigned changes.

`PS/HANDOFF.md` §§1–2 records the old q02 waiter exiting under the usage hold without running the profile. The later consolidated queue snapshot lists q02 as **queued, not launched**. That later registry label supersedes the historical held label, while explicitly preserving the task pause/wind-down and proof prerequisites. Pressure must have the coordinator's release/resume and a queue that is not on hold before any launch. Do not infer permission from either this plan or the queued label, and do not start a replacement waiter automatically.

Path abbreviations:

- `T = C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10`.
- `PS = T/ps`.
- `R = T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1`.
- `A = C:/Users/LOCAL_USER/OneDrive/Documents/GitHub/atlas`.

The controlling sources are `PS/HANDOFF.md` §§1–2 and its fixed rules, `PS/proof-request-draft.md`, the actual profile/proof/comparator scripts, and the current consolidated plan and queue protocol under `A/.atlas-dev`. Existing implementation ownership is unchanged. N9 remains PAUSED BY USER; its possible later effect on P1 booking is a dependency, not authority to resume N9. Fresh full intervals and individual holds remain intact.

## 2. Retained candidate and measurement evidence

| Role | Retained source or artefact | Recorded SHA prefix |
| --- | --- | --- |
| Candidate | `PS/c/w6f5`, composed from `T/gg/workers6-r6` plus p2, p1 and p3; `TEST_COMPOSITION.json` | `0c2e9176` |
| Pressure wall module | `PS/runtime/integration_pressure_walls.py`, r5 | `61d2019e` |
| Transforms | p1_loop; p1_binding; p1_dispatch; p2_spatial; p3_coupling | `0928d1ad`; `0c8fe3be`; `ba949b37`; `b498c170`; `ba828fd9` |
| Profile harness | `PS/scripts/run_arms.py` | `51e98e01` |
| Proof harness | `PS/scripts/ab_pressure_r4.py` | `2e6aa2f5` |
| Comparator and null control | `PS/scripts/compare_ab_r2.py`; `PS/nullfields-ab2.json` | `7ac3a1df`; `30f86dad` |
| Existing request draft | `PS/proof-request-draft.md` | `3d2293df` |

These identify the retained proof route; they are not receipts for a new run. Refresh any changed source through the owner's existing process rather than silently repinning it. The handoff retains successful small-case contract, mutant, indexed-database and transient checks and a refuter outcome of HOLDS. Reuse adequate unchanged evidence within its recorded scope.

The Pressure section of `A/.atlas-dev/improvements-table.md` separates these observations:

| Evidence | Result | Scope and status |
| --- | --- | --- |
| P2+P3 serial | 108.3 → 70.8 s, approximately 0.65× baseline | MEASURED, small case, shared machine |
| P1 auto2 on top of P2+P3 | 108.3 → 45.9 s, approximately 0.42× the same original baseline | MEASURED, small case, shared machine; includes P2+P3 |
| Later r5 transport-gate sm7 | 56.1 s serial → 45.9 s parallel on the same build; backlog identifies auto1 | MEASURED, separate small-case run, shared machine; all arms equal |
| r5 sm7 memory | Peak 416 → 569 MiB; worker about 170 MiB real against 768 MiB booked | MEASURED resource observations, not a full-scale booking |

Do not merge the two 45.9 s results into one experiment or add overlapping savings. Declined/crashed walls were recomputed equal in the retained smokes; this does not establish a mechanism that reassigns work to surviving workers. No small-case ratio proves full-scale or whole-interval performance.

## 3. q02 profile and exclusive proof request

### q02

The retained profile route is arm `c2-spy`, mode `spy+seed`, on `frozen:R/composed-r2`, using the initial store at `R/s2/attempt-1/run-root/initial-measurements.sqlite`, pinned to `e337fc205071fc6754b47b18f1c990fbfaec2162ae55cc3a1210cdbc9872ce81`. The owner handoff supplies the launcher; do not substitute an unbound command or runtime.

The recorded q02 booking is **2.0 GiB, two cores**, with approximately **30 minutes PROJECTED**. The associated **4.4 GiB** start requirement is a calculation from that booking basis, subject to the prediction rules below. Its recorded evidence destination is `PS/p1` with `PS/p1.log`. The harness refuses an existing output directory; preserve any prior or partial evidence and resolve the next output location through the owner before execution.

`run_arms.py` must report CHECK PASS and exit successfully. It fails closed on absent arms, any non-zero arm exit, missing required bounds/geometry/partition identities, an invalid or missing workflow ID, identity disagreements, changed seeded stores or store sidecars. A py-spy trace alone is insufficient.

The `spy` route uses **100 Hz sampled stacks**, including subprocesses, and retains separately observed CPU/wall phase timings in its reports. Its tree-memory sampler runs once a second and excludes py-spy itself. `scripts/summarise_profiles.py pyspy p1/c2-spy/pyspy.txt` summarises sampled attribution; it does not produce exact microsecond stage timings. Preserve the measured timing and memory scope and the machine-load conditions.

After an authorised completion, Pressure reports actual tree peak against the booking, records the result through the existing `runq.py note q02` mechanism, and uses the observed stage timings to refine the proof request.

### Full-scale request and gate basis

Complete the existing `PS/proof-request-draft.md`, including TOTAL, duration and its no-duplicate registry check. Submit an **EXCLUSIVE REQUEST** to the coordinator, naming the runtime/composition, inputs, output locations, total resource basis and estimated duration. The coordinator supplies the ticket; there are no plan-created ticket JSON files.

The draft's **approximately 70 minutes and 3.5 GiB TOTAL are PROJECTED**, to be refined from q02 and adequate retained smoke evidence. **6.2 GiB** is the calculated start requirement on that booking basis, not a fixed live gate or a measured peak.

Under the dated queue amendment, predicted peak is the maximum retained measured peak for the matching command/input key, falling back to the booking where no matching history exists. Failed runs do not lower the prediction. Need is predicted peak × 1.2 plus the 1 GiB floor and 1 GiB small-job allowance. Preserve the actual prediction, basis, need and free memory recorded at launch; the 4.4/6.2 GiB examples do not override them.

The recorded queue warning compares measured peak with **prediction**, warning when it is exceeded by **more than 20%**. This is not an automatic booking-calibration rule. Report actual versus booked as required and route corrections through the coordinator. The request's **1.5× escalation concerns elapsed time**, not a RAM multiplier or automatic kill.

The proof requires q02's result, the coordinator's slot and a queue that is not on hold. Seed-zero, cleaned-environment, hash-randomisation and runtime-import rules remain those of the handoff; `-I` is reserved for helpers that do not import the runtime. Preserve source freeze, new-output refusal and historical evidence. No profile, proof, waiter or rerun is launched by this document.

## 4. Exact proof coverage and parity

The retained draft specifies two sequential proof processes and then the comparisons: one base serial arm on `test:T/gg/workers6-r6`, and six candidate arms on `test:PS/c/w6f5`:

1. `serial`.
2. `auto1`.
3. `auto2`.
4. `auto6`.
5. `auto6:-1=decline`.
6. `auto6:-2=crash`.

The planned outputs are `PS/fp/base`, `PS/fp/cand` and `PS/fp.log`, subject to the existing absence/reuse rules. Require the complete expected arm set, successful process exits, valid input/worker identities, and candidate **ARMS EQUAL**. That verdict compares the candidate arms' forcing ID, descriptor hash, arrays, integration leaves, driving ID and datum. A verdict over fewer arms does not prove the requested coverage.

Then require `compare_ab_r2` **NUMBERS EQUAL** or **IDENTITY-ONLY (D-b, null-field-controlled)** against the base. The comparator reads the first arm in each report, so its success does not replace the separate candidate-arm equality/coverage checks or excuse an earlier failed process.

For IDENTITY-ONLY, arrays/integration_leaves/datum and descriptor structure must be equal, and every differing descriptor field must be an identity matching the pinned null-control patterns. NUMBERS EQUAL retains the comparator's unchanged-output conditions. The retained null set derives from the docstring-only control; it is not permission for arbitrary boundary permutations, numerical differences or newly unexplained identity changes. An additional differing field yields DIFFER; any needed full-scale null-control run follows the established request route.

There is **no epsilon tolerance**. Preserve byte-identical pressure records and unchanged numerical/resource contracts. The separate bounded N9 design exception does not relax this P1–P3 proof.

## 5. Resource acceptance conditions (a)–(d)

Use the existing `fp/cand/report.json` and session fields. No new telemetry dataclass is required.

**(a) Transport and child accounting.** Report the full-scale gate's raw `input_bytes`, `decoded_bound` and actual `child_bytes`; worker real peak (`peak_child_rss`) beside booked peak (`peak_child_ledger`); and declined/recomputed walls per arm. Also retain free cores, workers asked/granted, adopted/declined/crashed walls and total/per-worker peaks. The production route passes `policy.child_bytes` to both the gate and the worker session. The dispatch constructor's 128 MiB default is not that route's allowance. The draft records a 512 MiB policy default, but report the actual selected value rather than inferring it from either default.

**(b) Real versus booked cost.** Report the decoded bound and raw-data relationship against the worker's retained copy and measured RSS. Preserve the existing match-real-cost obligation and report actual versus booked. A booking estimate is not measured memory, and neither is an operating-system cap.

**(c) Parent transient.** Retain the separate, **untimed** `--transient` memory pass in `ab_pressure_r4`. It observes `_shared_inputs` through local monitoring events without rebinding the implementation, stops at the gate before starting a worker, and records the traced peak and retained amount. Require `verify_boundary` to have run and passed with events live, at the gate and after release, with the monitoring tool released. Any missing check is TRANSIENT FAIL. Keep these memory results separate from timed arms. If the transient exceeds **256 MiB**, book it **before integration**; otherwise, the later match-real-cost repair obligation still applies. This is not permission to raise a scope cap or disregard an unbooked transient.

**(d) Reopening.** Preserve **no reopen change**. The draft's existing observation is zero reopens on six real walls; it is not a claim that the new full-scale proof has already run.

The proof harness samples total parent-plus-worker working set every 0.5 seconds. Retain that measurement scope, its per-worker figures and the separate queue observations. Existing 12 GiB tree-RSS, 1 GiB free-floor, 16 GiB logical, 256 MiB scope, 1 MiB integer and 256 accepted-step limits remain unchanged. Bookings, projections and sampled peaks do not redefine those contracts.

## 6. Failure disposition and owner handoff

Forced decline and crash are intentional proof arms and must demonstrate exact recomputation. An arbitrary crash is not automatically external or VOID-ENVIRONMENT. When a worker-count arm cannot obtain its required workers, use the established VOID-ENVIRONMENT disposition and submit a rerun REQUEST for that arm alone. There is **no automatic launch or rerun**. Preserve failures, partial outputs and source identities; a later comparator pass cannot erase them.

After the proof and resource conditions are satisfied, Pressure returns the complete evidence and outstanding dispositions. **Geometry integrates binding/dispatch; Runner pins after the proof.** Preserve the interaction with parallel admission in shared files and their owners. This plan neither edits those files nor admits the candidate to final assembly by itself. Plan 31 (not included in this public snapshot) and Plan 35 (not included in this public snapshot) retain their separate assembly and combined-measurement gates. Any remeasurement after N9 integration remains a coordinator dependency while N9 is paused.

## 7. Completion gates and provenance

- [ ] Authorised q02 completes with CHECK PASS, successful exit, all required identity/seed/sidecar checks, and reported timing scope and actual-versus-booked peak.
- [ ] The existing exclusive proof request is completed from valid evidence, including the registry check, source freeze, output locations, refined estimates and recorded prediction basis, and receives its separate execution slot.
- [ ] The base serial arm and all six specified candidate arms complete successfully; candidate ARMS EQUAL and the null-controlled base comparison pass with exact numerical contracts and no missing coverage.
- [ ] Conditions (a)–(d), transient integrity checks, worker-count/failure dispositions and actual-versus-booked obligations are satisfied before integration. An unresolved failure is a reported blocker, not completion.
- [ ] Pressure delivers the proof and resource evidence; Geometry and Runner complete their respective integration/pinning boundaries before later assembly or combined-performance acceptance is claimed.

The frozen Codex initial review (private evidence unavailable in this public snapshot) is unchanged. The post-reveal assessment and complete primary-source pins (private evidence unavailable in this public snapshot) record the corrections and their evidence. This revision implements general463 and Claude's explicit additions in general465. Plan acceptance is distinct from execution, proof, integration and scientific acceptance.
