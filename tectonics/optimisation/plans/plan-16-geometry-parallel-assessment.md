# Plan 16 — Geometry worker-cap and rolling-interface assessment

**Item ID:** 16  
**Retained owner:** Geometry / Runner; Storage receives the transform handoff and the coordinator retains queue and disposition ownership.  
**Status:** WORKING NON-CANON. Sampled six-worker proof, private implementation and source integration with Plans13–14 are qualified. The selected source and focused regression are included in this review-branch publication. q13 VOID-ENVIRONMENT and q21 INVALID LAUNCH ENVIRONMENT remain historical attempts; the separately authorised q53 successor passed. Production enablement, a new eligible ROOT and held interval work remain separate.
**Completion condition:** Obtain the required, separately authorised sampled IV2 w6 proof on the existing three-transform runtime; preserve all attempt provenance; then deliver the bounded result and integration handoff to the retained owners. No new geometry algorithm is proposed.

## 1. Scope, authority and sources

This is the assessment and handoff of `workers6 + workers6rolling + workers6clamp` on `T/gg/workers6-r6`. It does not implement a semaphore controller or grant implementation, preflight, queue, scientific-run or production-integration authority. Preserve source freezes, existing owners, all applicable individual/full-interval holds and N9 **PAUSED BY USER**. An approved plan is not a completed proof, integration, acceptance or publication.

Path aliases:

- `T` = `C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10`
- `R` = `T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1`
- `G` = `R/geometry-growth-r1`
- `P` = `T/.r44-env/Scripts/python.exe`
- `A` = `C:/Users/LOCAL_USER/OneDrive/Documents/GitHub/atlas`

Primary evidence at this revision:

| Source | Identity and relevance |
| --- | --- |
| `G/HANDOFF.md` §9 and §10a wind-down opening/items 2 and 5 | SHA-256 `7901b41693ff3d45d2ffb881861f0395150e9e50c94842228b7dc88c6871edb5`. Existing proof scope, owner-reported measurements, three-transform handoff and decision if VOID recurs. Its earlier “HELD; never started” entry predates the later q21 launch. |
| `G/transforms/workers_six.py` | SHA-256 `2296e269bd0b6a203c057e29a70f91a36619bef261d1e3c0eab18348c33a9d39`. Worker selection and complete audit in its docstring. |
| `G/transforms/workers_six_rolling_interfaces.py` | SHA-256 `c3fb0b5f23ee96ce95ad84d304fd727f29e9292b52cd1e74ba5f2fc6b155c34c`. Conditional ownership of the interface pass. |
| `G/transforms/workers_six_endpoint_clamp.py` | SHA-256 `82684257605e377cdc6a2b0b2e93c452b847cf9697783d2404421d14dbf406c4`. Deliberate endpoint cap. |
| `G/scripts/run_dj_rearm.sh` | SHA-256 `24f3eb16249f2a766348a1c0d34e5109c8fd73ff4ca6259fa1c186da00234759`. Actual launch, orphan audit, sampled inputs, retained attempts and merged proof. Plan 03 requires a reviewed successor for the identified launch/copy/orphan boundaries. |
| `G/scripts/summarise_dj.py` | SHA-256 `a58092566124fc83fcea9b8cca48ca4efd1b96a5f78707e8f00273ec66171bad`. Exact arm checks and mechanical VOID predicate. |
| `G/scripts/test_summarise_dj.py` | SHA-256 `2e2cbaf0cb3035925ac7c1d15fa60aec1cc48b38a06e2cb756810b5a703e2680`. HANDOFF records 144/144; this documentation edit does not rerun or independently reproduce that result. |
| `T/q/queue.json`, complete q13 and q21 records | SHA-256 `0992c52d69b18268cf26f56282b36ce2922cac6928813afbe2fb4af12702cec6`. Literal execution fields, scientific disposition notes and recorded resources. |
| `G/work/dj-rearm-r3-q21.log` | SHA-256 `9ebd68cdc3d1acdfdd22b50ff08529bac8cef388f3453cceb8cd77b3c5475566`. Earlier held waiter. |
| `G/work/dj-rearm-r3-q21b.log` | SHA-256 `3ba3da59468bb4db3bc3a3fffd2c4ed0f263aafd2589364e7804285674fc1e3f`. Later invalid launch. |
| `A/.atlas-dev/plan-status-20261016.md`, worker-cap row and acceptance boundaries | SHA-256 `be270e6898e0b1d5aa0c7d29065baf1d4df16ece34490f17d7c68a9d77d4339e`. Current retained ownership, distinct outcomes and no automatic retry. |
| `A/.atlas-dev/run-queue-protocol-20261016.md`, CPU, holds and memory amendments | SHA-256 `c0cf31fc54d4f302311037c2250c600c1ecd1429f5acf8940eac5dee9ac9a0b0`. Current queue rules; later amendments govern. |

The frozen initial review (private evidence unavailable in this public snapshot) is unchanged. The post-reveal assessment and amendment checkpoint (private evidence unavailable in this public snapshot) retain the detailed source reconciliation. Current primary records govern execution; these identities record the reviewed evidence, not permission to run it or silently repin it.

## 2. Existing mechanism and deliberate limits

The three transforms form one handoff item:

1. **workers6:** permits policy workers 1..6. The single-contact planner retains `min(workers, 2)` because its exhaustive lookahead search and fixed dispatcher have a separate two-worker boundary. Existing physical-core, memory, booked-envelope and predicate-unit cuts remain unchanged. The existing rolling schedule uses workers+1 lanes, at most workers running and twice workers batches outstanding; this is not a 32-chunk batch guarantee.
2. **workers6rolling:** stacks after workers6. Rolling interface batches own the pass only when `workers > 2`, `batch_seconds is not None` and `minimum_job_seconds is None`. Otherwise the existing single-contact route remains. A per-contact floor cannot silently migrate to a route that does not apply it.
3. **workers6clamp:** clamps the automatic endpoint route to two after its machine gates. `ComponentParallelSession` remains 1..2; endpoint batching above that is separate deferred work. The superseded `workers_six_endpoints.py` must not be composed.

The single-contact and endpoint caps are deliberate design constraints, not evidence of a failed rolling proof or automatic VOID. Transform input pins and unique anchors remain binding. Execution selection changes neither equations nor record bytes and introduces no tolerance.

This replacement removes the unsupported 8 GiB swapping history; semaphore `RollingBatchClamp`, batch ≤32 and cache-eviction design; epsilon 1e-14 substitution for exact parity; 4.5 GiB ceiling; 256 MiB per-worker buffer cap; 250 ms sampler; automatic crash/chunk retry; invented q21c ticket; and the proposed `job_geometry_parallel.sh`, `geometry/rolling_batch_clamp.py`, `compare_geometry_outputs.py` and `q/tools/verify_child_env.py` paths. The Quickhull, Tanenbaum and Edelsbrunner citations did not establish this implementation and are removed. The recorded 4.5 GiB advice concerns q05's different next booking, not this route's RSS ceiling. Existing guards, including the actual 256 MiB scope caps, remain in force.

## 3. Three historical events and the preserved orphan

| Event | Retained execution record | Disposition |
| --- | --- | --- |
| q13 D-j rerun | Queue `status: failed`, exit 1, 1.14 GiB tree peak. The queue started after its 10-minute CPU wait with 5.6 free cores; the IV2 w6 session later recorded 3.01 free cores and selected two workers. | **VOID-ENVIRONMENT** for that worker-count proof; records/streams were identical and the other recorded checks passed. Keep both literal historical fields and the semantic disposition. |
| Earlier q21 waiter | `dj-rearm-r3-q21.log` ends at 18:46:17 on 16 October with “ticket q21 is held, not queued”, waiter exit 0. | The scientific arm never started in this event. This does not describe the later attempt. |
| Later q21 launch, outer log suffix q21b | Start 21:22:00, end 21:28:48, **status failed / exit 15**, 0.26 GiB tree peak. `date`, `seq` and `cp` were unavailable at actual wrapper lines 104, 119 and 124. | **INVALID LAUNCH ENVIRONMENT**. The copied input store was not created; only verified owned descendants were stopped. This is neither numerical failure nor a worker-count result. |

The queue ticket is q21; q21b is a log suffix; r3 is the harness generation. Do not invent a separate ticket from a suffix or relabel the current failed row as held.

The four exact paths checked during this replacement retain the recorded state: `G/evidence/workers-dj/iv2-w6-r3.log` exists at zero bytes; its matching `iv2-w6-r3.json` and `iv2-store-w6-r3` are absent; `G/evidence/workers-dj-merged-r3` is absent. The empty log is an unresolved attempt, not permission to rerun. The existing audit refuses a log/store without JSON and also enforces generation order, recognised names and non-overwrite checks. A later generation or fresh outer log cannot clear the orphan.

Plan 03 governs the prerequisites: explicit evidence-preserving coordinator ruling; reviewed successor behaviour that honours that ruling while still refusing other unruled orphans; actual utility execution and tiny synthetic-copy preflight in the exact child environment; and an explicit guard that refuses a failed actual input-store copy before parity starts. The current wrapper uses `set -u` and does not check `cp -r` before launching parity. A preflight alone does not repair that boundary.

Preserve old logs, attempt JSON, stores and partials byte-for-byte. Do not delete/move partials, fabricate a sentinel or scientific result, bypass the audit, or hide the original launch failure behind a successor. Record the disposition in the existing owner record outside the preserved attempt.

## 4. Existing assessment route and resource admission

The recorded command shape is `run_dj_rearm.sh r3 iv2:6`. It is historical, **not a command ready to execute**. The coordinator must select the authorised ticket, reviewed successor source, generation and fresh output/log paths after Plan 03 is complete. Do not create q21c, edit ticket JSON directly or treat a queue entry as launch authority.

The wrapper uses runtime `test:T/gg/workers6-r6` and `parallel_parity.py`. Its IV2 inputs are `G/evidence/final-f2/iv2-supports.jsonl.gz`, `G/evidence/final-f1/iv2-partition.grid.json.gz` and `G/work/iv2-interval-only-r1.json.gz`, with the recorded stream width and **`--shard 0 --shards 20`**. The remaining proof is this sampled IV2 w6 rearm merged with retained IV1/IV2 controls and serial cross-checks. It is not a full-IV2 or whole-planet proof.

For an authorised successor, preserve the original attempt files under `G/evidence/workers-dj`. The wrapper adds generation-named JSON/log/store siblings there; the directory as a whole is not read-only. Use a new merged output name of the selected generation (`workers-dj-merged-<generation>`) and a new outer log name, both refusing existing paths. Preserve `sources.txt`, the corrected `r2view`, `superseded` attempts and `summary.txt` in the merged evidence. Fresh names do not waive the orphan ruling or other start checks.

The recorded q21 booking is **2.0 GiB TOTAL, 7 cores (six workers plus controller), exclusive, quiet, about 15 minutes**. Its outer queue admission recorded predicted peak 2.0 GiB from booking, memory need **4.4 GiB**, free RAM 11.4 GiB and free cores 7.2 at launch. The invalid launch's 0.26 GiB peak must not lower the intended scientific booking. Future admission follows the existing matching-command prediction rules, using successful matching peaks or the declared fallback and recording its basis.

The 4.4 GiB value comes from runq's rounded GiB calculation: predicted TOTAL ×1.2 + 1 GiB floor + 1 GiB allowance. The inspected wrapper does **not** call `SG.decide/admit`; do not describe an exact-byte SG gate as already wired or add that integration as an unassigned prerequisite. Queue admission, runtime resource cuts and in-run protection are distinct. Preserve the 12 GiB tree-RSS guard, 1 GiB free floor, 16 GiB logical and existing scope/integer/step limits. A worker-cap lift does not remove RSS protection.

Use the selected Git shell and Plan 03 child-local environment correction. Processes importing the runtime require `PYTHONHASHSEED=0`, the owner-recorded plain `-B` or `-s -P` route and fail-closed hash-randomisation checking; **no `-I` on runtime-importing children**. `-I` remains allowed for queue/psutil/JSON/summary helpers that do not import the runtime. Preserve existing numerical thread settings. A wrong seed can select SERIAL instead of proving the intended route.

Neither the queue's timed CPU wait nor the wrapper's bounded quiet attempts guarantees a quiet machine: both can proceed after their wait policy. Record actual load, free cores, runtime gate readings and workers used. Apply the queue's elapsed-time escalation rule rather than inventing a kill deadline. No automatic crash retry, chunk retry or quiet rerun is authorised.

## 5. Exact proof and mechanical outcomes

Use the selected reviewed `summarise_dj.py` contract, not a new comparator or tolerance. It judges all retained arms: IV2 serial/w2/w4/w6 and IV1 serial/w4/w6, with serial cross-checks and superseded attempts.

- Require exact record and stream digests against each set's same-runtime serial, no arm error, a nonmissing matching package digest, profile compatibility and the recorded route checks. The serial result must also match the corresponding r2 serial view; the IV1 encoding correction must retain the old runtime's package identity rather than fabricate comparable hashes.
- IV2 w2 must have a passing `interface-route` gate and the single-contact route selected.
- IV2 w4/w6 must have that gate present and refusing the single-contact route, with **interface-batch peak live workers > 2**. IV1 w4/w6 use the recognised interface/wall batch controllers. Record the actual peak: exceeding two does not establish six simultaneous workers.
- Every requested new arm must exist and be the selected generation's merged result. Retained arms and superseded attempts must also pass their applicable checks; superseded PASS/VOID results can be retained, but a genuine failed or unknown attempt cannot be hidden by a successful rerun.

**VOID is narrow.** For an arm requesting more than two workers, the concurrency-peak check must be its only failed check. Required sessions must be present; at least one must record gates. Each gated session's first trim to at most two must be CPU or memory, with its own reading proving it could not fit three workers although a suitable machine could:

- CPU: `free_cores < 4 <= physical_cores`; rounded readings that do not prove the strict bound fail closed.
- Memory: `available < 3 * per_worker + reserve <= physical_RAM`, with the actual r6 policy booking of **805306368 bytes per worker (768 MiB)** and **2147483648 bytes reserve (2 GiB)**. These classify the gate; they are not per-worker buffer limits or a replacement tree-RSS guard.

A positive trimmed count must then run normally (`selected`, no worker error). Zero must be refused by that last gate alone with the recorded session-not-opened reason. A gate-less companion session is permitted only for the summariser's recognised below-threshold design reason without error. Budget/predicate trims, missing sessions, binding/funding/worker errors and other failed checks remain FAIL. The deliberate endpoint cap alone is never a VOID justification.

| Outcome | Meaning and next action |
| --- | --- |
| Summary 0 — PASSED | All required current checks pass; enables the owner handoff subject to existing integration authority. |
| Summary 1 — FAILED | A genuine failed/missing check or unacceptable superseded attempt; preserve evidence and return the specific failure. |
| Summary 3 — VOID-ENVIRONMENT | No genuine failure, but a current arm meets the mechanical VOID predicate. Neither PASS nor proof completion; return to coordinator for disposition. |
| Wrapper 2 — refused start | Existing output, invalid generation/specification or unresolved attempt/start condition. No scientific result. |
| Observed launch exit 15 | Historical q21 invalid-launch stop. Preserve separately; not a summariser verdict. |

Unexpected errors also fail closed; these named codes are not a claim that every possible launch failure must produce 0–3. Reuse the adequate unchanged 144/144 owner-recorded summariser evidence. Plan 03's changed launch/copy/orphan boundaries require their own stipulated focused checks; no duplicate scientific audit or new algorithm is required merely by this document.

## 6. Owner handoff, dependencies and pending completion

After the required authorised PASS, Geometry sends Storage all three transforms as one item, their reviewed identities, actual proof evidence and the audit list in `workers_six.py`'s docstring. Geometry returns the worker-cap result to Runner: its owned clamp (`interface_worker_selection` and the tree guard, in Runner's files) **may lift** after the PASS and the applicable integration decision. Runner owns that change and retains RSS/free-floor protection. The coordinator receives the registry update with the actual result and remaining dependencies.

If the successor remains VOID, the coordinator decides whether the existing w4 result suffices for a w4 handoff or another separately authorised quiet run is needed. HANDOFF reports sampled IV2 w4 **569 seconds versus 946 seconds serial**, byte-identical. These are retained owner measurements for that scope; they neither prove the w6 result nor predict whole-interval/additive gains. Do not invent missing timing-load metadata or replace the requested w6 proof without the coordinator's decision.

The blanket claim that q21 gates all of Plans 31/35 is removed. The owner identifies q23/jets-r2 as the stated N12 dependency. Preserve whatever reviewed worker transform and Runner changes the selected enabled composition actually needs; removing a false blanket dependency does not waive integration checks.

C1–C5 apply: exact numerical parity with only explicitly approved identity translations and the bounded N9 exception; the 1 MiB integer bound and projected-width gate without an invented fixed 25% ceiling; evidence-backed figures and honest status; no new authority; and current primary mechanisms/owners. N9 remains paused, and the 256 accepted-step value remains a ceiling rather than a demand to run that many steps.

- [x] Plan 03 readiness, preserved-orphan disposition, reviewed successor identity and coordinator-approved ticket/generation/output/log scope are established before any launch.
- [x] The separately authorised sampled assessment records the exact inputs, runtime/package identities, admission basis, actual resources and worker counts while preserving historical attempts.
- [x] The merged proof meets all exact arm, route, serial and superseded-attempt checks; any FAIL, refusal or VOID returns its literal outcome without automatic retry.
- [x] Geometry delivers the three-transform/hash/evidence/docstring-audit handoff to Storage, returns the result to Runner and supplies the coordinator's registry update under the agreed disposition.
- [x] The existing owner record states the outcome, remaining integration decisions, source/evidence pointers and next action; no scientific or production completion is claimed from this documentation revision.


## Implementation checkpoint - 21 October 2026

The separately cleared q53 sampled assessment passed the original exact merged
proof and the stronger actual-session/peak-six criterion. IV2 shard 0/20 elapsed
time was 421.73 s versus retained serial 946.57 s; guarded invocation sampled
1.34 GiB. q13 VOID and q21 invalid-launch history remain preserved.

The [Plan16 source successor](../workbench/plan16/README.md) integrates five
helper changes with the selected Plans13-14 closure, retaining all native bytes.
It authenticates actual parent RSS/logical peaks, records and forwards the
four/six worker ceiling, and preserves existing serial/recovery/source guards.
New source/profile identities and a new eligible ROOT are required. Native-entry
preflight passed separately. This publication supplies the integrated source,
retained results and portable focused regression. It does not establish a full
interval, production default switch or final assembly acceptance. Git history
records commit and push state.
