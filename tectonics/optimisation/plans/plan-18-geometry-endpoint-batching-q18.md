# Plan 18 — Geometry endpoint batching: WP18 r2 and q18

**Status:** WORKING NON-CANON. Candidate built and unit-tested within the recorded scope; q18 is **HELD**, not proved, integrated or accepted for final assembly.  
**Retained owner:** Geometry, with Runner owning its compact-path integration and the Atlas coordinator owning queue release and the threshold decision.  
**Decision:** Replace the former draft under general612–620, including the coordinator's synthesis and assignment in general620.  
**Completion condition:** Close the existing source-bound review and smoke prerequisites, resolve the open wrapper-exit failure path and queue-generation mismatch, then obtain authorised five-arm endpoint parity and measured disposition. Report the IV1 threshold recommendation and resource evidence to the coordinator. Integration remains a separate owner action.

This document grants no implementation, refuter launch, test, smoke, scientific-run, queue-edit, manifest-edit or live-swap authority. N9 remains **PAUSED BY USER**; all individual and fresh full-interval holds remain. A queued row, a unit PASS or approval of this plan does not release a run. Preserve the agreed C1–C5 conditions, exact numerical contracts, immutable evidence and retained ownership.

## 1. Paths, evidence and selected scope

| Alias | Absolute path |
| --- | --- |
| W | C:/Users/LOCAL_USER/Documents/Codex/agentchattr/workspace |
| A | C:/Users/LOCAL_USER/OneDrive/Documents/GitHub/atlas |
| T | C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10 |
| G | T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1 |
| PY | T/.r44-env/Scripts/python.exe |
| BASH | C:/Program Files/Git/usr/bin/bash.exe |

Current authority is `A/.atlas-dev/plan-status-20261016.md`, the relevant WP18 decisions in `optimisation-backlog-20261016.md`, the current queue protocol and `G/HANDOFF.md` §10a item 6. The owner wind-down item supersedes older instructions to contact the same refuter: the remaining review calls for **one fresh refuter of the r1→r2 delta**. Source pins are listed in §8.

The selected work is WP18 part 1 **(a) endpoint clamp to the policy's reviewed general bounds, default 512 jobs / 4,096-request horizon, and (b) cross-support lookahead, approved at two endpoint workers**. Part (c), more endpoint workers, is later work. The endpoint session retains its 1..2-worker bound. The separate `EndpointBatchPass` opt-in prototype is unchanged.

“Hardest first” occurs in the original backlog item and design sketch, but the later reassessment in `G/WP18-PART1-DESIGN-NOTE.md` explicitly abandons it: the available labels did not predict cost, and work units were known only afterwards. It is not part of the selected implementation. The old sketch's proposed ALE and ahead-of-router `project_compact` changes are also superseded by the actual auto-only implementation.

The preserved [Codex initial assessment](reviews/codex/plan-18.md) and [Turn 2 source assessment](../discussions/atlas-plans-39-review-20261017/codex-plan-18-turn-02.md) record the review history. Initial assessments remain frozen; later decisions do not rewrite them.

## 2. Existing implementation and invariants

`G/transforms/wp18_endpoint_lookahead.py` modifies only `atlas_tectonics/integration_component_volume_auto.py`. Its reviewed input is the `workers6-r6` auto module, and compose name `wp18` produces the selected `T/gg/wp18-r2` runtime (`workers6-r6 + wp18`). `T/gg/wp18-r1` remains preserved for the delta review.

| Auto-module generation | SHA256 |
| --- | --- |
| workers6-r6 input | fa0cbcaf55eb0845e824fa8a2a8417dd1c0b1936c899a8b049d0ba88a1a1cdfe |
| Preserved wp18-r1 | ae1cd127f086b585a17b0f779e5c695c4036c11c8015ae0d709cb027c22d818d |
| Selected wp18-r2 | 643ce988d5d89d698db16e192f8d0e708fc4059ad7506ade2078cb640ee6983d |

These are **source-file hashes**, not package or simulation-result digests. The transform rejects already-applied input, unknown input unless explicitly using its unreviewed-input route, and non-unique anchors. This plan does not authorise that escape route or a repin.

The old endpoint-specific clamp was 32 jobs / 64 requests. The selected transform keeps the policy's already reviewed general `batch_jobs` and `horizon`; the inherited cache bound follows `2*horizon + 64` (8,256 entries at the default horizon). It retains the scheduler's `_weigh`/`_fits` capacity checks and `MAX_BATCH_INPUT`. Changing these scheduling bounds does not relax geometry, numerical or transport limits.

The parent still projects each routing row and adopts endpoint results in serial router order. Workers compute ahead. A future support contributes only its small component summary: logical cell id, whether it has a parent, constraint count and partition-path length. Non-compact reads use the existing prepaid routing decode envelope. Compact reads use a retained handle and charged `support_fields`; the temporary native support is dropped. **`project_compact` is never called ahead of its router position.** No ALE or Step 8 source change is part of this transform.

Preserve the complete r2 behaviour:

- Read ahead while a worker session is open **or** the schedule requests more offers to cut its first batch (`offered < _wanted`). “Session open only” would deadlock first-batch formation.
- With no session, stop renewed read-ahead once a lookahead reaches its horizon (`sated`); resume if a session opens. Below-threshold or estimate-free work must not eagerly read the whole pass twice.
- Estimate remaining work as jobs left in the current read plus unread supports times the observed jobs per support. This is a scheduling estimate, not a changed endpoint calculation.
- Bind an ahead-read support by its index and support id. A mismatch stops the schedule and leaves serial continuation; it must not adopt a mismatched worker result.
- Retain actual compact handles, not bare object ids; prune passed supports from the identities memo. Drop the support being read and held memo references on the relevant stop paths; close already offered work before partition close.
- Preserve request/adoption/checkpoint order, mandatory reservations, failure handling, capacity checks, and the declared lookahead support/handle peaks. A reservation shortage revoking the session, and one failure declining the rest of a 512-job batch, remain recorded efficiency limitations.

There is no SIMD/ray-packet implementation, floating-point clipping or new geometry tolerance here. Endpoint records must remain exact. Keep the existing 12 GiB tree-RSS, 1 GiB free floor, 16 GiB logical and applicable 256 MiB scope guards, projected-width gate, and 1 MiB integer bound (**8,388,608 bits**). A resource booking is not permission to raise an in-run guard.

## 3. Evidence already present and its limits

`G/scripts/test_wp18_lookahead.py` tests the controller against a fake schedule and fake compact handles/field owners. It checks request order, claims/checkpoint consumption, lookahead, mismatching support stops, no-prepare behaviour, first-batch demand, the no-session horizon limit, memo pruning, peaks and stop cleanup.

Both `G/work/wp18-unit-r3.log` and `wp18-unit-r4.log` end **ALL PASS**. Their complete diff adds one r4 line: the schedule-stop cleanup check corresponding to current test section 8b (labelled r2.1). The final owner handoff cites r3. Retain that provenance and the r4 addition; do not arbitrarily select a log or claim either log proves execution of today's exact source bytes without the source binding. The existing required review gate must bind the evidence to the selected generation. No unit rerun is required merely because the document changed.

The owner record also reports 17 q18 summary mutants within the earlier combined 32-case harness check. Reuse that evidence for its covered summary behaviour; it does not establish the separate arm-exit guarantee described in §5.

The earlier `G/evidence/wp18-smoke-r1` smoke compared serial and auto records on IV2 shard 0/10, but the CPU gate refused the session. It establishes that recorded serial equality only; it does not establish worker engagement or r2 acceptance. At this review, `G/evidence/wp18-smoke-r2` and `G/evidence/wp18-parity-r1` are absent. Recheck the exact intended destinations immediately before an authorised launch and never overwrite historical output.

**Still owed:** a test that the real partition closes with `borrow_count == 0` after a mismatch stop, requested by Runner. Real compact read-ahead V2 parity belongs to Runner's Step 8 integration. Fake-handle units and the non-compact endpoint harness do not close either obligation. S4 retry transforms stay out of q18's runtime so the WP18 result remains attributable; their later package proof is separate and follows q18 PASS under the owner sequence.

## 4. Authentic parity route

The retained proof wrapper is `G/scripts/run_wp18_parity.sh`; it selects `test:T/gg/wp18-r2`, drives `endpoint_parity.py`, then runs `wp18_parity_summary.py`. It takes a new evidence tag and an optional shard count. No optional shard count means the full support sets. The retained smoke call is `run_wp18_parity.sh wp18-smoke-r2 10`, selecting **shard 0/10 in every arm**, with the same wrapper and output layout.

| Order | Arm | Support input | Route and threshold | Required worker evidence |
| --- | --- | --- | --- | --- |
| 1 | iv2-serial | G/evidence/final-f2/iv2-supports.jsonl.gz | Serial reference | None |
| 2 | iv2-w2 | Same IV2 input | Auto, policy workers=2, default minimum_seconds=120 | started > 0; adopted > 0; refused = 0 |
| 3 | iv1-serial | G/work/iv1-supports.jsonl.gz | Serial reference | None |
| 4 | iv1-w2 | Same IV1 input | Auto, policy workers=2, default minimum_seconds=120 | Equality-only; legitimately serial is allowed |
| 5 | iv1-w2-min30 | Same IV1 input | Auto, policy workers=2, minimum_seconds=30 | started > 0; adopted > 0; refused = 0 |

The wrapper's stream-width arguments are retained exactly; they are not newly chosen tolerances:

| Input | Numerator | Denominator |
| --- | --- | --- |
| IV1 | 0x2f00cbfcd7c08aad8918ab19af | 0x4e3bbe22f900000000000000000000000000000000000 |
| IV2 | 0xef6aca6e197d9db2f69d62da0b | 0xc6ae51dc48000000000000000000000000000000000000 |

The support header supplies `max_volume_error_m3` and `max_leaves`; each decoded support id must match its header index. The route issues one shared predicate budget, opens the real automatic endpoint controller, prepares the selected tuple of non-compact supports, projects each row, binds its support, measures endpoints and reads the resulting record through the routing rows. It retains the normal close/finish sequence. Freeze the reviewed runtime, wrapper, helpers and input identities through the run.

Each emitted record-list entry contains the measure id, SHA256 of the canonical encoded measure record, and `met`, in router order. The report stores the ordered list and its SHA256. Each candidate arm must match its corresponding serial arm's positive record count and ordered-record hash, carry the same nonmissing package digest and no recorded error, and satisfy the engagement predicate where required. This is **ordered endpoint-record byte identity**, not a floating-point error norm. A positive `started` field counts endpoint work; it does not alone prove two children ran simultaneously.

The default IV1 auto arm must not be falsely rejected for staying serial. Conversely, serial fallback cannot substitute for the required IV2-w2 or IV1-w2-min30 engagement. The current summary returns **PROOF PASS / exit 0** or **PROOF FAIL / exit 1**. Describe its actual predicates: not every telemetry field it prints is validated against missing/None values. Source-bound readiness must cover the required fail-closed behaviour and provenance rather than infer it from the summary's docstring.

The wrapper exports `PYTHONHASHSEED=0`, `PYTHONDONTWRITEBYTECODE=1` and single-threaded OMP/OpenBLAS/MKL settings. Runtime-importing processes use `-B`, not `-I`, and `endpoint_parity.py` refuses active hash randomisation. Isolated `-I` remains for helpers that never import the runtime. Keep the inherited identity and guard checks; no patched runtime or serial mock may stand in for a worker arm.

## 5. Unresolved before READY: arm exits

**OPEN — source review, not an executed fault test.** In the pinned `run_wp18_parity.sh`, lines 43–46 run an endpoint arm, print its exit code and then inspect its log. The wrapper does not retain that arm status. Lines 53–56 return only the JSON summary's status. Consequently, a child that writes an otherwise acceptable report and then exits nonzero is not necessarily rejected by the wrapper. Record equality is not proof of a successful child exit.

Geometry must establish a source-bound failure path before READY: retain and propagate each nonzero arm exit, or provide primary evidence of an equivalent existing guarantee. Use a bounded known-fault fixture in which an arm has an otherwise acceptable report and a nonzero exit; the complete wrapper must fail. Existing missing-arm/error/record-difference mutants remain valid within their covered scope and do not substitute for this case. Missing outputs or failed children must not be relabelled as harmless resource refusal.

This is part of the **already required review and exact-harness smoke**, not a new reviewer chain or permission to run now. Any wrapper repair changes its source identity: preserve the current evidence, record the successor hash with the owner, and have the authorised smoke load the reviewed successor. The hash in §8 identifies the currently reviewed, still unresolved version; it is not an acceptance pin for a future fix. Do not mark this issue closed from a documentation change.

## 6. Queue state, resources and authorised continuation

The read q18 row is **HELD**, position 5, owned by “Geometry speed and parallel workers”. It books **2.5 GiB, 22 estimated minutes, three physical cores (two workers plus controller)** with `quiet=true`, `exclusive=true`, `timing=true`. Its hold reason records r2 memory fixes, delta re-review and smoke, with release on READY.

The row's description still names `gg/wp18-r1`, whereas the pinned wrapper loads `gg/wp18-r2`; its dedicated runtime/input fields are empty. **The coordinator must reconcile the reviewed runtime/input generation and booking before release.** Do not silently rebook, repin or release it. The stored waiting PID 9516 is stale launch metadata: `G/work/wp18-parity-q18.log` ends “ticket q18 is held, not queued”. Preserve it and use a new, non-overwriting log for any authorised relaunch.

The remaining sequence, when implementation/run work is authorised, is:

1. Geometry obtains the one fresh delta refutation of the selected auto-module generation against preserved r1, with relevant callers/tests and the r2 lifetime/guard changes. Include the open wrapper-exit requirement in the source-bound readiness work. Do not contact the old refuter as a substitute for the current owner instruction.
2. Complete the exact small-lane smoke using `run_wp18_parity.sh wp18-smoke-r2 10`, or an explicitly recorded new tag if that destination has since been used. Preserve the script/arguments/observers/layout, seed checks, arm exits, output refusal and source pins. Use the existing `runq.py small` route with a grounded resource request; no fabricated `small --ticket` command.
3. Geometry reports **READY** with the exact runtime/harness/input generation, refuter/fault/smoke evidence, output destination and measured booking basis. The coordinator resolves the r1/r2 row mismatch and controls per-ticket release.
4. Only after release, use the retained command shape below with a new log and the reviewed harness generation. A process started earlier or a previous waiter PID is not a release signal.

```text
"$PY" -B -I "$T/q/runq.py" run q18 -- "$BASH" "$G/scripts/run_wp18_parity.sh" wp18-parity-r1
```

The wrapper refuses an existing evidence directory; endpoint reports also refuse an existing output file. Preserve these guards and the protocol's short-path/output/input checks. No old partial attempt is deleted, moved or reused by this plan.

Queue admission predicts from the largest matching successful peak and falls back to the booking. The fallback calculation here is `2.5 * 1.2 + 2 = 5.0 GiB` free memory; it is not a fixed replacement for prediction and not an in-run RSS cap. Use measured parent and endpoint-child peaks to ground future bookings, preserving route/worker/input context. A failed run must not lower a prediction.

The wrapper's local CPU quiet wait is bounded at approximately two minutes, after which the gate still decides and the summary still requires engagement for the two proof arms. Keep exclusive/timing conditions and report the queue's free physical cores, CPU note, free-memory/admission evidence and concurrent-small-job count with timings. Lack of quiet does not turn a failed engagement check into PASS.

**22 minutes is an estimate, not a timeout.** The queue protocol's 1.5× elapsed escalation requires a report to the coordinator with the reason and stop/continue recommendation; it is not automatic cancellation. There is no invented 600-second deadline, raised memory guard or new endpoint-worker policy.

## 7. Result, decision and completion criteria

After the authorised proof, Geometry returns the full arm verdicts and evidence path to the coordinator, including successful child exits, ordered-record identity, actual worker engagement, gate decisions, parent peak, sampled endpoint-child count/largest/total RSS, session memory observations and queue process-tree context. Sampling figures must be labelled as sampled, and must not be presented as a continuous hard upper bound.

Report the **IV1 w2-min30 threshold line** with its serial and default-threshold comparisons; the coordinator owns the corresponding backlog decision. Enable only if the route gains time under comparable conditions and the required correctness gates pass; otherwise retain its measured disabled disposition. The design-note figures **IV2 402→217 seconds and IV1 91→57 seconds are PROJECTED**, not q18 measurements or whole-interval speed-ups. There is no approved 15% WP18 acceptance hurdle. Preserve exact parity even if a timing result favours the candidate.

A passing endpoint proof and a favourable timing disposition do not themselves integrate `composed-f1`, accept the real compact route, release full intervals or complete final assembly. Send required owner handoffs and retain the Runner mismatch-stop obligation and separate compact V2 proof. S4 is outside this proof generation. There is no blanket authority to launch Plans 31/35 from this document.

- [ ] Source-bound fresh delta review and relevant evidence binding completed; the arm-exit gap is demonstrably closed on the reviewed wrapper generation before READY.
- [ ] Exact small-lane smoke and required fail-closed evidence recorded on that generation, with new outputs, pinned inputs and a grounded booking.
- [ ] Geometry READY recorded; the coordinator reconciles the queue generation and explicitly releases the held ticket before launch.
- [ ] Authorised full five-arm proof returns successful child exits and PROOF PASS with exact ordered endpoint records and the correct arm-specific engagement requirements; peaks, gates and comparable timings are retained.
- [ ] Geometry sends the measured disposition and IV1 threshold recommendation to the coordinator, with outstanding Runner/Step 8 and later integration obligations explicit. Final admission/integration status is recorded only by the relevant owners after their remaining gates.

## 8. Source identities retained for this plan

Pins identify the sources examined; they confer no launch or acceptance authority. Reconcile changed inputs through the owning workflow. Do not silently repin. Runtime auto-file identities are listed in §2; the frozen initial assessment is separate from live owner evidence.

| Source | SHA256 |
| --- | --- |
| A/.atlas-dev/plan-status-20261016.md | be270e6898e0b1d5aa0c7d29065baf1d4df16ece34490f17d7c68a9d77d4339e |
| A/.atlas-dev/optimisation-backlog-20261016.md | 414470799087a745e79ded44fc53ff747f14ee5a3f773de039c0aa6b01658189 |
| A/.atlas-dev/run-queue-protocol-20261016.md | c0cf31fc54d4f302311037c2250c600c1ecd1429f5acf8940eac5dee9ac9a0b0 |
| G/HANDOFF.md | 7901b41693ff3d45d2ffb881861f0395150e9e50c94842228b7dc88c6871edb5 |
| G/WP18-PART1-DESIGN-NOTE.md | 5040e564d312e8e851ee49b9a0faad38d8abc5651c39567d57c862589df9bf3c |
| G/transforms/wp18_endpoint_lookahead.py | 82db03052076680c97d3fd6856f4003d0b425b6447efc44054c547b30fd38e6c |
| G/scripts/run_wp18_parity.sh — unresolved arm-exit path | cb7cc706f0dc6c383169d078e80e9184790ef3d6bb06eb8a57ba9f15f398ab09 |
| G/scripts/endpoint_parity.py | 31df8d8c9104414385b87b1b3261afa9eacb76b1d1bf2cf2ee3adad5f953cb7d |
| G/scripts/wp18_parity_summary.py | f78d3640217beb97cbed0a7782b710b554a52544413dc77fa9817f23ed33a9e2 |
| G/scripts/test_wp18_lookahead.py | ada0592a7a168078d07d8871117ee7b462f75eff541887939176d8e4cb169620 |
| G/work/wp18-unit-r3.log | f8a3ef1ada99cecdc5c2b9009ce1a5e35fcd645fe10d2dfac819bff632e693ec |
| G/work/wp18-unit-r4.log | 084c8b2faf71c51d68e3c09957565ecb14a0c54a5e0bd957c39b7276b510a756 |
| G/work/wp18-parity-q18.log | 286f85727aade9bd350abf1973837f2838295b9d4f2e5ae24ca3524e97a28883 |
| T/q/queue.json — q18 at /tickets/18 | 0992c52d69b18268cf26f56282b36ce2922cac6928813afbe2fb4af12702cec6 |
| W/plans/reviews/codex/plan-18.md — frozen initial assessment | 97433bc746f6bc7ac28ade25635104765e38962082ef22954b7bdf83fa440115 |
