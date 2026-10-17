# Plan 09: Parallel initial admission, ip9 and q19 proof

**Item:** 09 / N4 / backlog item 19  
**Status:** WORKING NON-CANON; ip9 READY accepted; q19 queued, not launched; proof and integration remain outstanding.  
**Retained owners:** Exact Kernels owns the item; Geometry owns and reviews the code; Runner integrates.  
**Plan decision:** Amendments agreed in general497-498, 17 October 2026. Plan acceptance, READY, proof, integration and final assembly are separate states.  
**Target completion condition:** Complete the authorised q19 proof on the selected ip9 tree using the existing two-worker route and fail-closed checks; report adoption and resource evidence; then hand the accepted result to the existing owners for integration, including the shared pressure/admission schema composition.

## 1. Purpose and current state

Item 19 performs an exact parallel reader recompute of the 969 initial-metrics queries, keeping the same queries, assembly order and numerical results. The retained implementation uses existing component-session workers to compute later queries in contiguous batches. Read-ahead starts at the first measurement-cache miss: the parent measures that query while workers take later positions. Passed positions and batches are skipped or retired. The parent retains its unchanged wrapper, reservations, accuracy/witness checks, diagnostics and measurement-store recording; an unavailable answer follows the serial call at its own position.

This is not a new physical partitioning algorithm. The smoke's 969 chunks and 969 snapshots describe store records, not mutually disjoint regions covering a planet. The source selection does not establish the removed draft's ip8 SQLite-WAL corruption, work-stealing or shared-store merge diagnosis.

**ip9 supersedes ip8 as the selected source.** The owner told Small that ip9 supersedes ip8 in N12; that message alone does not verify an assembly-manifest edit or final integration. The authoritative consolidated status records ip9 READY and q19 proof not run. No full-scale parallel speed result follows from READY or the retained small checks.

The earlier `ck/scripts` freeze was lifted: CK/STATE.md records q11 PASS at 18:26 and explicitly says `ck/scripts no longer frozen`, before t9, smoke-s4 and READY. The later q19 waiter was released and then exited on the 18:45 hold without running its proof. The consolidated record subsequently lists q19 as queued, not launched. Do not restore the earlier q06/q11 wait as a current unresolved freeze, infer a new q25 dependency, or infer launch authority from queue status. Preserve the current owner/coordinator release conditions and the selected-source freeze during any future proof.

This document authorises no launch, implementation, integration, hold release or publication. N9 remains PAUSED BY USER; fresh intervals and individual task/run holds remain binding.

## 2. Primary sources and selected build

Path aliases: `T = C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10`; `CK = T/ck`; `A = C:/Users/LOCAL_USER/OneDrive/Documents/GitHub/atlas`; `PY = T/.r44-env/Scripts/python.exe`.

| Source | Reviewed SHA256 prefix | Evidence |
| --- | --- | --- |
| `CK/HANDOFF.md`, section 2 | `1c0fe29c5da6` | Selected build, booking, exact command, proof acceptance and handoff. |
| `CK/STATE.md`, 18:26-18:45 entries | `922a77f5d63e` | Freeze lifted, t9/smoke, READY, release and later waiter exit; historical events remain distinct. |
| `A/.atlas-dev/plan-status-20261016.md` | `be270e6898e0` | Current admission status, ownership, queue snapshot and integration requirement. |
| `A/.atlas-dev/optimisation-backlog-20261016.md`, 12:55 changes | `414470799087` | Exact reader recomputation, query/order invariants and Geometry ownership. |
| `A/.atlas-dev/run-queue-protocol-20261016.md` | `c0cf31fc54d4` | Review before queue, CPU booking, resource prediction, overrun and preservation rules. |
| `CK/ip9/INITPAR_MANIFEST.json` | `f53a01e091b6` | Actual base, transform, module and changed-file input/output pins. |
| `CK/initpar/job_initpar_tree.sh` | `e681903bfa5f` | Pinned proof route and its actual checks. |
| `CK/initpar/compare_reports.py` | `ef50fd3f2813` | Same-tree report comparison; `checks`, `failed`, `passed`. |
| `CK/initpar/store_rekey.py` | `2ac4c47940ac` | Run-A store comparison and exact execution-identity re-derivation. |

The selected build is `CK/ip9/src`, based on `T/gg/final-f2` plus `CK/transforms/initpar_r1.py` (`3799958b`) and `CK/initpar/r2/integration_initial_parallel.py` (`5ffc7fb2`). The retained transform already includes the reviewed f2 inputs; the owner records that no new initpar transform r2 is required.

| Transformed source file | Reviewed input prefix | Output prefix |
| --- | --- | --- |
| `integration_dual_geometry.py` | `a48347c0` | `f9ebdd64` |
| `integration_differential_geometry.py` | `b4d95389` | `f0bce411` |
| `integration_parallel_binding.py` | `70db056a` | `4eb627dc` |
| `integration_parallel_results.py` | `f48cda05` | `73091fd3` |
| `integration_component_volume_parallel.py` | `fafc76fb` | `a4785573` |

These are transformed Python source identities. In particular, `73091fd3` is not a result-store hash and `a4785573` is not a coordinate-vector payload. Full pins remain in the manifest; preserve the historical manifest and receipts. Reopen the current owner and queue records before any later authorised run.

## 3. Retained verification and its limits

- **t9:** `CK/initpar/t9/report.json`, SHA256 `656e8a6e8c13b81613377c3be10af8c7fe301101d301949afc41df0e7fa9a371`; launcher `CK/initpar/run_t9.sh` (`5886704f`). The owner records all checks true, mutants refused and lifecycle checks true. The two-worker parallel fixture has 40 queries: five started batches, 39 adopted results and one serial query. Its tree peak was reported as 0.54 GiB. Do not confuse that tree measurement with a per-process report field or with q19's future peak.
- **smoke-s4:** the owner records PASS, 0.37 GiB tree peak, and 969 chunks plus 969 snapshots equal to Run A after the specified re-keying. The same-tree serial reference is `CK/initpar/smoke-s4/w0/report.json`, SHA256 `e8af70784dfb921e5105d383a0f0d48257f5b29b00bca16c07769f112a56c6f6`. This is a warm-store route: the pinned job requires worker launch/adoption to remain absent for cache hits. It is not the fresh-store parallel proof.
- **q19:** remains unrun. The existing fresh-store proof is necessary to establish actual worker execution/adoption on this route. The booking and any projected duration are not measured results. Do not infer a speedup against Run A's different native tree.

Reuse adequate unchanged t9, smoke and refuter evidence. The removed hostile concurrent-lock test has no established failure mechanism or authorised post-READY harness change here. Any material later code/harness delta follows the existing review-before-queue and focused failure-case requirements; the measured code must be the reviewed code.

## 4. Authentic proof checks

The pinned job uses the two-worker route (`proof 2`) on a fresh store. Its checks must all pass, with exit code 0; a missing required field, failed comparison, changed source or missing/zero worker count must not be relabelled as success.

### Worker execution and adoption

Read the actual w2 report fields: `initial_parallel.stats.started > 0` and `initial_parallel.adopted > 0`. The job writes `workers_started adopted: <started> <adopted>` to `workers_started.txt`. Preserve the existing accepted gate and evidence of the two-worker route.

These counters are not `workers_started=2` and `workers_adopted=2`. Adoption counts certified query results; the saved t9 example has five started batches and 39 adopted results. Do not demand that both workers each adopt a particular share, that all 969 queries are worker-adopted, or that positive aggregate counts independently prove simultaneous use of exactly two processes. Report actual route/counters and retained worker evidence, with the existing serial fallback and lifecycle semantics intact.

### Same-tree report comparison

`w2-vs-w0.json` is produced by `compare_reports.py` against the pinned smoke-s4 w0 report. Require its overall `passed == true`, with all checks true and no failures. The comparison verifies:

- both reports passed their own checks;
- native root, import roots and loaded module digests agree;
- both reports have `metrics_only == false`;
- workflow IDs and non-empty preparation IDs agree;
- identity mappings are non-empty and every key in their union is present and equal.

The comparison schema is `checks/failed/passed`. A top-level `identity: true` is a comparator self-test result, not the proof comparison output. Preserve that distinction when interpreting results.

### Store comparison against Run A

The reference store is pinned at SHA256 `e337fc205071fc6754b47b18f1c990fbfaec2162ae55cc3a1210cdbc9872ce81`. Require the `w2-store-compare.json` result's `passed == true`, not an invented `status: PASS` field.

The existing comparator verifies the reference pin, absent sidecars, equal settings and chunk rows in put order, non-empty equal counts and one execution identity per store. It verifies each candidate snapshot's canonical body, invocation/key and digest, then re-derives snapshots under the reference execution identity and compares them byte-for-byte in order. This is the approved identity translation. It does not require the entire candidate SQLite file already to have Run A's file hash, permit arbitrary masking, or excuse reordered records or numerical changes.

### Source identity throughout the proof

Require `sources-start.sha256 == sources-end.sha256`. The actual job captures the selected native tree's Python files at start and end. Preserve its fail-closed comparison and the separately pinned module, manifest, scripts and evidence. Do not describe this tree scan as a scan of every external helper. Source changes invalidate the proof; no silent repinning is permitted.

## 5. Scheduling and resource reporting

The retained q19 booking is **12 minutes, 1.1 GiB and three physical cores**, with **quiet plus EXCLUSIVE**. The selected route uses two workers plus the parent. These are scheduling requirements, not a 1.1 GiB in-run ceiling or a 720-second automatic timeout. Preserve the implementation's worker limit and the actual in-run guards.

If elapsed time passes **18 minutes (1.5 times booking)**, report to the coordinator promptly with the reason and a stop/continue recommendation. It is not an automatic kill or numerical FAIL. Report measured tree peak against the 1.1 GiB booking; a booking miss is evidence for resource accounting, not permission to change guards.

Use the current queue's by-need prediction: the maximum successful matching-command peak, with booking fallback if no matching successful evidence exists. The start requirement is predicted peak times 1.2 plus 2 GiB. Failed runs never lower a prediction. Retain recorded prediction/basis, memory and CPU admission decisions; quote free cores at start with timing. A warning above prediction by more than 20% is distinct from the booking comparison. Do not silently reuse a differently scoped t9 peak as q19's command history.

Keep the existing 12 GiB tree-RSS, 1 GiB free floor, 16 GiB logical, 256 MiB scope, 1 MiB integer and 256 accepted-step limits. Exact numerical parity, approved identity translations and the separately bounded N9 design exception retain their existing scopes. There is no fixed 25% width ceiling or new scientific tolerance in this plan.

## 6. Gated execution and handoff

The following is the existing owner command for a later authorised launch, **not an instruction to launch during plan review**. From `T/ck`, with `PY` set to the pinned interpreter above:

```bash
"$PY" -B ../q/runq.py run q19 -- \
  bash initpar/job_initpar_tree.sh p9 proof 2 \
  "C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/ck/initpar/smoke-s4/w0/report.json" \
  > q19.log 2>&1
```

Before that launch, the owner/coordinator must confirm the applicable release, current registry/dependencies, unchanged reviewed inputs and adequate evidence. Preserve the script's cleaned environment and seed checks and the pinned interpreter; do not alter the environment or bypass its guards. The exact proof job defaults to ip9; an alternative native tree is a different input and must not be silently substituted.

`CK/initpar/proof-p9` must not exist. Preserve/rename the old q19.log before redirecting new output, as the handoff requires. Do not overwrite historical logs or delete an existing proof directory to force readiness; an unexpected existing result needs owner disposition. The real output is `CK/initpar/proof-p9/`; no invented ticket JSON filename is part of this plan.

On completion, report PASS/FAIL, actual adoption count and worker evidence, report/store verdicts, start/end source equality, elapsed time and measured peak versus booking through the existing coordinator/queue record. Retain failures and partials. A failed or unavailable required proof does not authorise an automatic rerun.

Runner integration follows the accepted proof and Geometry/code-owner review. Resolve the combined pressure/admission schema composition in the shared files and establish the integration identities under the existing owner process. Coordinate N12 inclusion with its manifest owner; neither READY nor a passing standalone proof establishes final assembly or publication.

## 7. Completion conditions

- [ ] Current coordinator release and dependencies are satisfied for the exact reviewed ip9/q19 route, with new output and preserved historical evidence.
- [ ] The proof exits 0 and records the authentic positive started/adopted counters and required two-worker-route evidence.
- [ ] Every same-tree report and Run-A store check passes under the existing identity-translation rules, and native sources start == end.
- [ ] Actual elapsed time, adoption and measured tree peak versus booking, including any overrun or gate caveat, are reported through the existing owner/coordinator process.
- [ ] Runner and Geometry complete the required integration handoff and shared pressure/admission composition; any assembly disposition is explicitly recorded as a separate state.

Related work: [Plan 07: pressure proof](plan-07-pressure-p1-p3-assessment.md), [Plan 02: by-need start gate](plan-02-start-gate.md), and [Codex's Plan 09 source assessment](../discussions/atlas-plans-39-review-20261017/codex-plan-09-turn-02.md). Frozen independent reviews remain unchanged.
