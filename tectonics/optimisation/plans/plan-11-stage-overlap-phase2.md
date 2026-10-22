# Plan 11: reader-admission overlap, backlog item 10 phase 2

**Status:** WORKING NON-CANON. Phase-2 implementation and selected private integration are complete, with exact parity and one q46 ROOT-only comparison. The combined successor passes focused qualification; its own eligible ROOT and actual interval evidence remain later work.

**Owner:** Runner; bounded implementation/private-integration handoff complete.

**Completion boundary:** preserve the complete gate, receipt, memory, failure and independence contracts below. ROOT-only measurements do not establish interval/ALE performance or enable deferred phases 1/3.

## 1. Approved mechanism, order and scope

Phase 2 starts the reader alongside its own producer. The reader performs its independent, store-free initial admission while the producer runs, then waits before accessing the pending sealed store. For interval 1, this overlaps the reader's initial metrics with the producer's advance; at the root it overlaps the reader with the root producer's work.

The order is **Item 7 -> Item 21 / N5 -> Item 10 phase 2**. Preserve producer-only measurement reuse in [Plan 10](plan-10-measurement-reuse-n3.md) and the continuation boundary in Plan 29 (not included in this public snapshot). Readers still recompute independently; the producer's cache is not shared with them. Interval 2+ restores the spatial owner from sealed lineage without initial_metrics, so this admission saving applies once per lineage in the current route.

Phases 1 and 3 remain deferred. After Item 7 their projected saving was about 60 seconds each, insufficient to justify the extra launcher complexity and relaxed preflight. They need separate consideration after a phase-2 smoke demonstrates a measured net gain. Phase 2 does not start the next producer speculatively, move the deferred phases' producer/store checks, or authorise those phases automatically.

The implementation concerns process ordering and a launcher-written gate. It does not overlap a disk flush with template allocation and introduces no in-process thread-pool pipeline.

## 2. Required sequence and trust boundary

| Point | Required action |
| --- | --- |
| Start | Launcher starts the current producer and its reader under their guards, pinned composition and appropriate start gates. The reader receives the expected attempt/stage/interval, launcher identity and waiting-process binding needed by the gate protocol. |
| Before the gate | The reader completes serial `FRESH.admission` from its pinned composition, fresh budget and own artefact directory. Keep the existing source fence/capture and retained-scope discipline. No producer store, catalog, pending sealed view or producer output supplies the admission. |
| Wait | The admitted reader waits without opening the producer store. It checks cancellation, guard conditions, launcher PID/creation-time liveness and the bounded wait deadline. |
| Producer completion | The producer must exit and pass the existing guard, process-tree and receipt postchecks. `guard_postcheck` must report no failures. The launcher retains the RF.command-equivalent, store-free `producer_inputs` preflight before gate publication. |
| Publish | Launcher publishes the complete authenticated gate using the atomic protocol in section 3. |
| After the gate | Reader validates the gate, runs unchanged `producer_inputs` using the producer receipt SHA supplied by the gate, records that receipt pin, and rechecks its by-need memory start gate before `open_pending`. The pending view, change token, producer/root comparisons and independent verification follow the gate and retain their existing checks. |
| Finalise and adopt | Finalise validates the closed set of gate fields in the reader receipt and retains the equality check on `producer_receipt_sha256`. Adoption remains dependent on the normal successful independent reader and finalisation chain. |

**Admission is before the gate.** Producer-dependent validation and store access are after it. Deferring the admission until after the gate would remove the intended overlap. Moving admission earlier does not move `open_pending` or weaken its read-only seal, hash, reference-closure and identity checks.

The current selected worktree reader still opens its pending view before rebuilding admission; it is evidence of the existing boundary to change, not evidence that phase 2 has already landed. The design's original proposal is subordinate to the accepted review and later decisions.

## 3. Closed gate, publication and failure handling

The gate must bind all of the following, with no unknown or missing fields accepted:

- attempt, stage and interval;
- producer `run.json` receipt SHA-256;
- guard receipt SHA-256, whose required status is STOPPED with producer exit confirmed;
- runner and sealed-record SHA-256s;
- the waiting process's exact PID and creation time;
- a launcher nonce.

Validate these bindings against the expected process/attempt and referenced records. Finalise checks the gate fields carried into the reader receipt as a closed set. A valid-looking hash alone does not establish the correct producer, waiter, stage or successful exit.

Write `gate.partial`, flush and fsync it, then rename it to `GATE` using the reviewed exclusive atomic Windows rename. A pre-existing destination refuses; `open('x')` followed by writes would expose a partial file and is not the protocol. After publication, no referenced file may be replaced again. Reads retain the required sharing-violation retries; a mutable stage record must not silently substitute for the pinned one.

Pass the launcher's PID and creation time on the waiter's arguments. If the launcher disappears or the maximum wait expires, the waiter fails before touching the store. Size the maximum wait to the expected advance plus a margin and record its basis. Preserve guard cancellation and exit confirmation. The guard has no general wall timeout, and launcher death/detachment does not establish that its guardian or workloads have exited.

An admitted-ahead reader failing for a non-data reason, such as launcher loss, cancellation or a free-floor trip, must not strand an otherwise valid sealed interval. The coordinator may choose a sequential fallback reader in a fresh output directory with the same complete checks. This is not automatic recovery or permission to bypass a failed gate, receipt, data or identity check. A fallback success does not erase the failed overlap attempt or its evidence.

## 4. Memory, process cohort and exactness

Retain the process-start memory check and **repeat the check after the gate, before `open_pending`**, recording both gate values and available memory. The current by-need rule supersedes the earlier blanket 10 GiB start rule and old TOTAL + 5 GiB queue threshold:

`start need = predicted peak × 1.2 + 1 GiB free floor + 1 GiB small-job allowance`

Use the largest successful matching-command peak, falling back to the booking when no measured command key exists. Failed runs never lower the prediction. Harness predictions must match the route, workers and inputs and include measured parent/worker contributions. Record prediction, basis, measured peak and any warning under the existing queue rules; a measured peak more than 20% above prediction is a warning. Do not inflate a booking to satisfy an obsolete fixed gate.

Book the concurrent workload's TOTAL from measured peaks. The phase-2 cohort is the current producer and its independent reader, plus their actual workers, guards and launcher. The old design's third workload was the next producer from deferred phase 3; do not include that behaviour as approved phase 2. Historical reader observations were about 0.45 GB tree RSS and 0.9 GB logical peak. These are scoped measurements, not universal bookings for a changed composition or workload.

The **12 GiB limit remains per guarded tree**, and the **1 GiB free-physical-memory floor remains system-wide**. Preserve the 16 GiB logical and 256 MiB scope limits and the named accounting contracts. Multiple logical ceilings cannot be treated as jointly available host RAM: the physical floor remains the operative joint guard, and a reader-induced floor trip can abort the producer's advance. No invented aggregate RSS equation or template-specific cap replaces these controls.

Record the advance's InterfaceParallelPolicy decisions, including `free_cores`, chosen workers and declines, with and without overlap. The load-sensitive ALE auto route can select fewer workers while a reader runs. Cite adequate exact source-bound evidence, or obtain the necessary authorised evidence, that this route is bit-identical across the relevant worker counts before accepting it. General support for workers or a different component's parity does not establish this claim.

The approved overlapping reader is **serial**. Parallel initial-metrics readiness elsewhere does not enable a parallel reader in this pipeline. Any later proposed parallel overlap needs a separately reviewed, fixed and recorded worker count and measured net benefit.

### Pre-existing retained-scope finding

Runner must assess the existing `live_producer_bytes` allowance in readers. The live R `new_retained_scope` function passes this allowance despite its comment saying the independent reader has a cold scope; the selected fresh/prepared reader sources call `RUN.new_retained_scope`. Determine the actual binding in the selected composition and report whether the effect is booking-only or affects independence. Do not infer either safety or an independence failure from the comment, or silently remove the allowance under this plan review. Carry its memory consequences into the measured overlap booking.

## 5. Performance claim and acceptance measurement

All phase-2 gains below are **PROJECTED**, not measured results of an implemented pipeline:

| Context from the accepted review | Scope |
| --- | --- |
| Approximately 929 s serial initial metrics, plus startup; about 950 s potentially hidden | s2-derived reader context beside an IV1 advance long enough to overlap it |
| Approximately 50-100 s extra advance time | Expected contention during that overlap; ALE worker selection can change too |
| Approximately 800-900 s net gain at IV1 | Review estimate only; requires a same-input end-to-end comparison |
| Approximately 838 s root producer admission | Historical root context; it cannot automatically hide a full 950 s reader admission |

Hidden admission is bounded by the producer work available to overlap. Do not multiply 930-950 seconds by two readers, add phase-1 savings to the same hidden work, or claim the benefit for every interval. A five-minute producer advance cannot hide a roughly 950-second reader admission. The critical path is approximately `max(producer work, reader admission) + remaining verification/finalisation`, with actual contention and overhead included in the measurement.

Compare sequential and phase-2 end-to-end wall totals on the same inputs, frozen sources and queue conditions. Report net difference alongside component timings, worker decisions/declines, measured process-tree peaks and failures. A faster admission or positive hidden-time estimate alone is not acceptance. Preserve baseline and candidate evidence even if the result shows no net gain.

The required phase-2 smoke/timing route needs its own reviewed queue request and run authority. Reuse adequate unchanged evidence for its prerequisites. An eventual worker-count comparison requires the queue's EXCLUSIVE conditions. The existing 1.5× elapsed-booking rule calls for escalation and a stop/continue recommendation; it is not an automatic kill or RAM multiplier. This plan launches no smoke, benchmark, scientific interval or queue ticket.

## 6. Source identity, refusal evidence and integration

Freeze the entire pipeline source manifest until all participants, reader exit checks and finalise have finished. The admitted reader lives through the producer's advance, so its source-verification window is longer. Preserve source/loaded-code checks throughout.

Exact numerical fields, required identities and the accepted adoption chain remain unchanged. Reader receipts gain gate fields and their hashes change; they cannot be required to equal old receipts apart from timing. Bind the actual successor source/profile/receipt identities under the existing composition rules, compare the required exact fields, and retain old receipts and pins untouched. No silent repin is allowed.

Carry the accepted focused refusal coverage before any real overlap run:

- partial or garbled gate; wrong attempt/stage/interval, receipt digest or waiter PID/creation time; stale or prematurely published gate;
- launcher loss or maximum-wait expiry, guard free-floor failure and cancellation while waiting, with the producer store untouched;
- Windows record-read/replacement races and sharing violations;
- missing or extra gate fields in the reader receipt, including finalise refusing incomplete bindings;
- sequential fallback preserving all checks and using a fresh output directory.

Use existing adequate source-bound checks where their assumptions remain valid. Changes or missing coverage require the relevant focused checks and required refutation under current queue rules, not an unrelated full suite. Failure evidence must remain visible and must not be converted into a successful scientific result.

Runner retains integration ownership. Item 21/N5 is published on the review branch, but the current status does not establish a live R/frozen-composition swap. Phase 2 and its required final-chain checks remain unfinished until evidenced. Plan 31: final assembly (not included in this public snapshot) and Plan 35: combined performance retests (not included in this public snapshot) are downstream boundaries, not authority to enable this route now.

Apply C1-C5: exact field/number parity with only explicitly approved identity translations and the bounded N9 exception; the real projected width gate and 1 MiB integer bound (8,388,608 bits), without a fixed 25% ceiling; measured/projected and built/integrated/accepted states distinguished; existing owners, authority and holds preserved; primary sources govern. Preserve the 256 accepted-step ceiling. N9 remains PAUSED BY USER; fresh full intervals and individual ticket holds remain in force. No numerical tolerance, source pin, environment or authority boundary changes here.

## 7. Primary evidence and remaining completion conditions

Path aliases: `A = C:/Users/LOCAL_USER/OneDrive/Documents/GitHub/atlas`; `WT = A/.claude/worktrees/rv/tectonics/optimisation`; `T = C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10`; `R = T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1`.

| Source | Governing evidence |
| --- | --- |
| `A/.atlas-dev/review-item7-item10-20261016.md`, complete Item 10 section and coordinator decisions | Phase-2 conditions, gate protocol, refusal cases, projected net benefit, deferred phases and Runner order |
| `R/probes/step8/claude-20261015/item10-stage-overlap-design.md` | Original DESIGN ONLY proposal and s2 observations; accepted review/later decisions supersede its under-specified gate, old timing claims and unverified later-interval branch |
| `A/.atlas-dev/run-queue-protocol-20261016.md`, current by-need and review-before-queue sections | Prediction-based gates, measured concurrent booking, source-frozen comparisons and required queue checks |
| `A/.atlas-dev/plan-status-20261016.md`; `coordinator-handoff-20261016.md`, section 4 | Current status, once-per-lineage route, ordering, owners and unchanged acceptance boundaries |
| `WT/drivers/reopen_fresh_restart.py` | Existing producer preflight, receipt and pending-store/admission boundary; not proof of implemented phase 2 |
| `R/run_prepared_restart.py`, `new_retained_scope` | Existing allowance/comment discrepancy for Runner's selected-composition assessment |

Exact review-time source hashes and read scope are retained in Codex's Plan 11 discussion record (private evidence unavailable in this public snapshot). Frozen initial assessments remain unchanged.

The checklist below retains the original final-chain acceptance requirements.
Section 8 records the completed implementation and bounded ROOT evidence; the new
combined profile and actual intervals retain their separate evidence obligations.

- [ ] Runner identifies the selected phase-2 implementation/composition and demonstrates admission-before-gate with complete producer checks and store access after it, without enabling phases 1/3.
- [ ] Gate publication, liveness, receipt/finalise bindings, refusal handling and coordinator-decided fallback have adequate source-bound evidence and all required focused checks.
- [ ] Same-input, source-frozen, authorised measurement reports net end-to-end benefit and worker decisions, with exact ALE worker-count evidence; projections are not substituted for results.
- [ ] Concurrent TOTAL and both memory-gate observations are grounded in the applicable measurements, guards remain effective, and Runner has assessed the retained-scope finding and its implications.
- [ ] Final integration has its own correct successor identities and required evidence, with historical records preserved and the owner record retaining remaining dependencies and holds.

## 8. Completed implementation, private integration and scoped ROOT result

The q46 original-profile ROOT pair passed exact parity. Wall time fell from
1,701.781 to 1,172.375 seconds, a 31.11% reduction, while sampled arm-tree RAM
rose 74.23%. This is one ROOT-only pair under the selected serial comparison
scope. It is not interval/ALE evidence, a repeated-run estimate or a
whole-programme performance claim. The earlier failed native-entry attempt and
its evidence remain preserved.

The [combined Plans10–12 source snapshot](../workbench/plans10-12/README.md)
retains the overlap implementation, producer reuse and earlier enabled changes
with selected lf3 heat. Its private qualification passed 27 orchestration tests,
three native-entry cases and four heat cases. H5a, D5 and P4 stay disabled.
The q46 ROOT pair and q47 reuse smoke belong to the original profile; their
receipts cannot be reused to authenticate the new combined profile's ROOT.

The new profile needs its own eligible ROOT. Actual interval proof, final
assembly and full-workflow cold recovery remain later work under Plans31/38;
final combined timing belongs to Plans34/35. Phases 1/3 remain deferred and all
scientific and individual holds remain. Focused integration is complete without
claiming full-interval execution, scientific acceptance or general net savings.
