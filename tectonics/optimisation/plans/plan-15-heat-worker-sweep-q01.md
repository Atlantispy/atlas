# Plan 15: H4 heat worker sweep q01

**Item:** 15; backlog 9 / H4.  
**Status:** WORKING NON-CANON; q01 **HELD**, awaiting prerequisites and resource reconciliation. Discussion accepted with changes in general571, with the six-file correction in general572. Plan acceptance is not harness readiness, a run result or integration.  
**Owner:** Runner pipeline and final integration. The coordinator controls queue allocation, ticket/hold release and run authority; Storage must receive the later pin-change handoff.  
**Completion condition:** Complete the named seed/gate/refuter/smoke prerequisites; reconcile the CPU booking; obtain the required release and authorisation; execute the authentic six-arm W4 sweep; report its exact verdict and measured behaviour; and land a winning configuration only through the existing owner/integration process. A failed, reduced-worker or held run does not satisfy this condition.

## 1. Physical mechanism and retained schedule

This task measures **heat polygon-reconstruction worker counts** on the genuine W4 same-call control. It does not implement a new heat solver, partitioned finite-difference update or halo exchange.

The exact q01 schedule is **6, 8, 10, 12, 8, 6 workers**, in that order: six arms with repeated 8/6 counts to expose drift. There is no single-worker timing baseline in this schedule. Preserve the order and repetitions; do not replace them with a different scaling experiment.

`D/h4_heat_workers.py` starts one fresh process per arm. Its child loads the prepared layout's `private_heat_functionals_parallel_r1`, calls its public `configure(workers=N)`, and runs the unchanged same-call control. Both the legacy r12 and compact r13 advances reconstruct their faces under that setting. The control input is W4, **236 cells and 832 faces**, with the retained g13l1 layout and `D/g13-same-call-live1.json` reference. A retained reference PASS is not a completed q01 sweep.

## 2. Paths, current source and evidence

- `T = C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10`
- `R = T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1`
- `D = R/probes/step8/claude-20261015`
- `S = R/probes/step9/claude-20261016`
- `A = C:/Users/LOCAL_USER/OneDrive/Documents/GitHub/atlas`
- `P = T/.r44-env/Scripts/python.exe`

| Primary record | Scope |
| --- | --- |
| `T/q/queue.json`, ticket q01 | Actual schedule, W4 inputs, held status and recorded resources. A stored waiting PID is not proof of a live waiter. |
| `D/STATE-NOTE.md`, WIND-DOWN 19:15, opening constraints and item E | Latest retained q09/q01 prerequisites, exited waiters, fresh REQUEST and driver freeze. |
| Same STATE-NOTE, LIVE 14:15 and In flight | Per-arm gate basis and eventual configuration/report handoff. Historical running/queued wording is superseded by the later wind-down. |
| `A/.atlas-dev/run-queue-protocol-20261016.md`, CPU, review, small jobs, per-ticket holds and memory gates | Parent-core accounting, exclusive worker proofs, prediction provenance, overrun reporting and release rules. |
| `A/.atlas-dev/plan-status-20261016.md`, Heat and acceptance boundaries | H4 held, Runner ownership, no independent pressure-worker policy, unchanged limits and full-interval hold. |
| `D/h4_heat_workers.py` | Current harness, parity fields, recorded workers, output/gate ordering and three-outcome verdict. |
| `R/start_gate.py` | Actual decision/admission API and exact integer gate arithmetic. |
| `R/probes/step8/g13l1/control.json`, its named helper, and `D/g13-same-call-live1.json` | Loaded route, worker-process semantics and genuine control/reference. |

The **six files** covered by the owner's final q09/q01 refuter obligation are:

| File | Current SHA-256 |
| --- | --- |
| `S/run_cell_keys.sh` | `ea47a4f29768056250dda32930cac500e0ee1a46df5fab4b3f57c5614c446961` |
| `S/check_cell_keys.py` | `f01c389f548e98963edbd986ba7e59f6bc411bf2c75571ffcdd4b1dc938be728` |
| `S/heat_control_on_frozen.py` | `eed6bf241a843537746ce8b643c83635489089d0959e2b112fa8983724461f76` |
| `D/h4_heat_workers.py` | `ac790b6150d59164b41f88c94a0d1096339e7f7f2634ad20c5efe132ee1973bf` |
| `S/test_cell_keys_fail_closed.py` | `3cd843e3779c35d7ef917f23b949129ae1de60b55859708b867abbe77b6310db` |
| `D/test_h4_fail_closed.py` | `b0ccbd085afd1d8fb222211d4fd43fcf4999e715461bc1dd03fb6c99d7683e45` |

`S/seed_zero_check.py` is a **separate preflight, not one of those six files**: `dcc5412307598d1e7377af12dc89e8170ed7dd92a3e4aa1be6695e5468f3b34e`. The shared gate source is `R/start_gate.py`, `16e448d60556acabc337c4ff7b39649d7ab8110aa5585ec6a82262e1838f6345`. These identities describe inspected current sources, not future corrected successors.

The [saved turn and evidence record](../discussions/atlas-plans-39-review-20261017/codex-plan-15-turn-02.md) contains additional source identities and scoped findings. The [initial independent review](reviews/codex/plan-15.md) remains frozen. Reopen current owner records at implementation time; neither review grants run authority.

## 3. Parity and actual worker acceptance

The comparison is D-b on the same layout and paths. Each control must PASS, with a nonempty matching array-identity dictionary and matching `result_id`, `metadata_sha256` and `metadata_bytes` for **both legacy and compact results** against the retained W4 reference. Missing or None identities fail; two None values are not evidence of equality. A worker-only change does not permit an invented identity translation or tolerance.

Every requested arm must be present and complete. Preserve recorded configuration, calls, fallbacks and input identity checks. The harness requires `total_calls == len(calls)` because the helper retains only its latest calls: truncated reporting is incomplete evidence. Hashes of the layout and reference must remain unchanged before/after the sweep; output destinations must be new and must not overwrite previous evidence.

For each reconstruction call, the expected count is the lesser of the requested count and `to_reconstruct` when the minimum-face threshold is met; otherwise it is zero. Fewer than two useful workers also means zero. Legitimately serial small calls are allowed. An expected parallel call must use its expected count without fallback. The real selector also respects active metering and ledger capacity: requesting N is not proof that N ran.

| Harness outcome | Meaning and use |
| --- | --- |
| **Exit 0 / PASS** | All requested arms and required fields/calls are complete and identical, configured counts match, required worker behaviour holds, and layout/reference identities remain unchanged. Eligible for the authorised timing comparison. |
| **Exit 1 / FAIL** | An arm is missing, stopped, failed, incomplete or non-identical; configuration/call reporting is wrong; or layout/reference identity changed. Preserve the failure and evidence. |
| **Exit 3 / WORKERS_REDUCED** | Every arm is identical, but an expected parallel count was reduced or fell back. This is not a valid timing for the requested count and must not be relabelled PASS. |

A child's exit zero alone is insufficient. No failed or reduced-worker result authorises a replacement run automatically.

## 4. Dynamic memory admission and output ordering

Current H4 still uses a fixed `START_GATE = 10*GIB`. The replacement is per-arm prediction through the shared gate, not another fixed 6.8 GiB check.

Runner supplies an explicit gate key and validates matching **route, worker count, inputs/source identity and completed PASS** evidence before calling `start_gate.decide(key, measured=peaks, booking=(fallback_bytes, fallback_basis))`, followed by `admit(decision, available_bytes)`. The core API does not discover H4 history or validate its semantics. Do not feed H4 summaries to the fresh-stage record reader as though they had that schema.

Use the maximum valid matching measured peak, accounting for the whole route and workers, with the queue policy's measured parent-plus-worker totals where applicable. Preserve provenance as source path/hash and positive integer bytes. When matching arm evidence is absent, use the documented ticket-prediction fallback; where no usable prediction exists, the declared booking is the fallback. Validate and label the basis. A failed/incomplete record cannot lower a prediction, and a differently scoped parent-only or six-worker observation does not establish twelve-worker TOTAL.

For predicted peak P in bytes, the shared rule is:

`gate_bytes = P + ceil(P / 5) + 2 * 2**30`

For the recorded **4.0 GiB declared booking**, this is **7,301,444,404 bytes**. The draft's float truncation was one byte lower. Do not assert equality to a rounded 6.8 GiB float or pass a hand-built two-field dictionary to `admit`; it must receive the actual decision with schema, basis and prediction. Record the decision, gate and available memory per arm. The booking is not a measured peak or an immutable arm requirement.

**Required ordering change:** current H4 creates OUTDIR before `_gate`, then records a refusal summary without starting a child. Initial admission must move before output-directory creation, with a below-gate/no-output check. That is future work, not current behaviour. Each later arm still requires its own admission before its child and arm outputs begin. If a later arm is refused, preserve completed arms and explicit refusal evidence; do not delete the sweep to force a global no-output condition. Reconcile the existing refusal-summary test with the new initial boundary.

The gate change needs the owner's delta review and below-gate refusal mutant, including the affected tests. Retain seed-zero admission and the in-run 12 GiB tree-RSS and 1 GiB free-floor guards. Admission does not raise logical, scope or numerical limits.

## 5. Resource record and unresolved CPU conflict

The actual held q01 entry records:

| Field | Recorded value |
| --- | --- |
| Memory booking | 4.0 GiB |
| Duration booking | 15 minutes |
| Physical cores | 7 |
| Quiet / timing / exclusive | true / true / true |
| Worker schedule | 6, 8, 10, 12, 8, 6 |
| State | HELD; Runner's checklist outstanding |

**CONFLICT to resolve before launch:** the queue protocol specifies physical cores as workers plus one, while this schedule requests up to twelve worker processes. Applying that rule literally implies up to thirteen, not seven. The inspected helper does not define the counts as half-core units or supply an exception. Runner and the coordinator must reconcile the request or establish an explicit applicable exception. This plan preserves the existing record; it neither silently rebooks thirteen nor changes the sweep or treats seven as proven sufficient.

Worker-count proofs/timings remain EXCLUSIVE and must account for parent capacity. The historical six-core smoke commands also need reconciliation with current admission and holds; they are not executable authority merely because they appear in the owner note. Record actual workers and quote `free_cores_at_start`, `cpu_note` where present, and `small_jobs_max` with timing results. A CPU-gate warning is not proof of a quiet run.

At the recorded fifteen-minute booking, the existing 1.5x rule requires escalation at **22.5 minutes**, with reason and stop/continue recommendation. It is not an automatic kill or a memory multiplier. The applicable coordinator-approved booking governs any later authorised successor.

## 6. Required owner sequence

These are pending owner actions. They retain the joint q09/q01 prerequisites in STATE-NOTE item E; no command is executed by this plan amendment.

1. **Seed rule.** Use `PYTHONHASHSEED=0`, bytecode suppression and a cleaned environment for every runtime-importing process, without `-I` or `-E`. Run `S/seed_zero_check.py` first with the same interpreter, flags and environment as the children. It checks flags and PYTHON environment variables; it is not a recorded five-test suite. `-I` on the queue wrapper does not authorise it on scientific children. Preserve the harness's single-thread numerical-library settings.
2. **Per-arm gate.** Implement the decision/provenance and output-order contract above, with affected checks, after the relevant owner/review clearance. Do not mark the current H4 as repaired.
3. **Final-code refutation.** Complete one refuter on the exact six files listed above, including the changed gate route and necessary planted failures. Reuse valid unchanged evidence and record affected successor identities; the measured code must be the reviewed code. Preserve the owner design calls that cell-ID contrast is reported rather than required, and the reference applies to g13l1 only.
4. **Both smokes and RealArm checks.** After applicable hold release and resource authorisation, run the exact owner routes into unused destinations. The cell-key smoke uses `S/run_cell_keys.sh` with the owner-recorded `R/L/sm9a` and g13l1 route: it deliberately expects **child exit 0 / script exit 1 INVALID** because a single arm is insufficient for comparison. The H4 smoke uses the prepared `R/probes/step8/g13l1`, `D/g13-same-call-live1.json`, the owner-recorded `R/L/sm1a` output and requested worker count **12**; require its genuine harness verdict, not an invented IPC test. Then run the three RealArm checks with `CK_REAL_ARM=R/L/sm9a/ck-g13l1`. Existing paths must be refused, not overwritten; any necessary successor output name must be recorded. The historical smoke allocation does not override the unresolved CPU conflict.
5. **Clean readiness return.** Send the owner-required `qNN CLEAN` with evidence path and smoke wall/peak. Retained results of 41 cell-key tests with three RealArm skips and 29 H4 tests do not close the outstanding smoke/refuter/gate work. Report the actual remaining gap if any; do not manufacture readiness.
6. **Fresh REQUEST and authorised sweep.** The later wind-down records exited waiters and requires a fresh REQUEST. Runner supplies the corrected scope/resources and evidence; the coordinator reconciles booking, clears the individual ticket through `hold-ticket q01 off` and any other applicable hold, and grants the necessary run authority. Global release alone leaves individual holds intact. Only then execute the unchanged six-arm schedule through the approved exclusive route, preserving source/input identities and fresh outputs.

No stale PID proves a waiter is running. Use the existing completion return; do not install polling or duplicate listeners.

## 7. Measurements and integration

Report reconstruction seconds per call, legacy/compact advance times and end-to-end control/arm wall time alongside configured, expected and actual workers, fallback reasons, worker/tree peaks, gate decisions, machine load and hook state. Preserve all arms and repeated counts. Do not sum overlapping phase times or infer a full-interval gain from this control.

The existing `parallel_efficiency` diagnostic is:

`worker_compute_seconds / (used_workers * call_seconds)`

It remains a diagnostic, not an acceptance threshold or a T(1) scaling curve. Selection uses valid measured end-to-end behaviour under the agreed conditions. There is no 60% hurdle, automatic clamp to four, promise of speedup or obligation to change configuration if no arm wins. Preserve exact outputs and existing admission policy; introduce no independent pressure-worker policy.

If a valid arm wins with identical arrays, IDs and metadata, the retained owner direction is one `configure(workers=N)` in `R/fresh_interval_driver.py` plus `PARALLEL.report()` in `run.json`. **Tell Storage first about the pin change.** Runner retains the write; the review-sync driver freeze and integration checks still apply. A sweep PASS is not itself a live swap, completed final assembly or scientific acceptance of fresh full intervals.

Return the measured result, verdict, source identities, evidence path, proposed configuration or no-change disposition, and next action to the coordinator/Storage through the existing owner workflow. Preserve historical results and pins; use explicit successors where required.

## 8. Completion conditions and authority

- [ ] Seed/environment and per-arm gate changes are implemented on identified reviewed successors, including initial no-output refusal, later-arm evidence preservation, and unchanged in-run guards.
- [ ] The exact six-file refuter obligation, both smoke routes and three RealArm checks are complete with their correct expected outcomes and retained evidence; Runner has sent clean readiness or the real blocker.
- [ ] The seven-core/twelve-worker conflict is resolved by Runner/coordinator, the fresh REQUEST is handled, applicable ticket/holds are released, and the exclusive run is explicitly authorised.
- [ ] All six scheduled arms are complete with exit 0 / PASS, exact reference parity, valid workers, complete reporting and frozen inputs; measured timing/resource results and uncertainty are recorded. FAIL and WORKERS_REDUCED remain separate unsuccessful outcomes.
- [ ] The owner records the winning configuration or no-change disposition, returns the result, and completes any authorised configuration/report integration with Storage's pin handoff and required checks. Until then, integration remains INCOMPLETE.

There is **no new Plan 14 dependency**. Preserve Runner ownership, N9 **PAUSED BY USER**, all individual and full-interval holds, the actual q10 failure and other unrelated task states. Common C1-C5 boundaries remain: primary-source status, measured versus projected claims, exact numerical parity with only already approved identity translations and the bounded N9 exception, no invented tolerance or width policy, and no authority inferred from a plan. Keep 12 GiB tree-RSS, 1 GiB free floor, 16 GiB logical, 256 MiB scope, 1 MiB integer and the 256 accepted-step ceiling. This document authorises no source edit, run, queue change, repin, live swap or publication.
