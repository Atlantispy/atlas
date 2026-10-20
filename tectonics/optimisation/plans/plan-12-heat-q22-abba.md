# Plan 12: q22 mirrored heat timings and profile

**Completed q22 and combined integration, 20 October 2026:** the released q22
successor completed all 11 authentic arms with PASS. The scoped comparison selected
lf3 (H1a/H1c, H2, L1 and the physical-order repair); H5a remains disabled.
The [combined Plans10–12 source snapshot](../workbench/plans10-12/README.md)
retains that selection and earlier enabled changes. Its private qualification
passed 27 orchestration tests, three native-entry cases and four heat cases.
The new combined profile needs its own eligible ROOT; original q22/q46/q47
evidence does not supply that identity. Full intervals, full-workflow cold
recovery and final combined timing remain later, held work. Section 9 records
the completed scope; the pre-execution note and sections 1–8 below are retained
as historical planning and source observations where superseded by it.

**Earlier integrated-successor checkpoint, 20 October 2026:** Plan05 supplied the actual r13
writer/verifier/launcher and consumer integration in
[workbench/plan05](../workbench/plan05/README.md). Its corrected native pair agrees
exactly under complete physical cell and face correspondence. Historical linkage
is NOT REPRODUCED after changed metadata; original q10 FAIL remains.

The prepared consumer validates the actual proof, complete metadata dispositions,
source bindings and original eleven-arm schedule, then refuses the absent
collective correctness acceptance. Separate q22 run authority is also absent:
**q22 was HELD and had not run at that checkpoint**. The old wrapper is preserved unchanged.
Implementation and integration ownership were transferred; there is no remaining
handback to a former owner. The older proposed-successor and ownership wording
below is historical where superseded here. The schedule, exactness, resource
guards and separate run-release obligations remain binding.

**Item ID:** 12  
**Retained owner:** Heat; the existing coordinator controls queue release and the improvements table.  
**Status:** WORKING NON-CANON. q22 benchmark/profile and owner/coordinator handoffs complete; selected lf3 integrated privately with focused checks PASS. Original q10 FAIL and the historical q22 hold remain preserved.

**Completion boundary:** the ten timing arms and separate profile arm establish their original component comparison only. New-profile ROOT, final combined timing, the held full-interval chain and full-workflow cold recovery remain later work.

`T` denotes the original `the-diadem-local-tasks-10` task root; `A` denotes the Atlas reference repository. Source paths below use those existing aliases. This plan grants no implementation, run, rerun, queue change, integration or publication authority. Preserve all individual and full-interval holds and N9's PAUSED BY USER state. Apply the agreed C1-C5 corrections throughout.

## 1. Current failure and the prerequisite that must change

q10 completed its five arms cleanly, but the H5a cross-arm comparison failed. The retained `T/hs/evidence/h1c-r4a/RESULT` contains **FAIL**. The current q22 wrapper, `T/hs/scripts/job_h1c_r4c_r2.sh`, reads that file and exits 4 unless it is PASS. It therefore correctly refuses the current evidence. An older owner subsection's not-run wording does not supersede the actual failure and current consolidated status.

[Plan 05](plan-05-q10-heat-correctness.md) preserves the unresolved correspondence and causality. Its 3,021 NUMERIC/OTHER metadata differences are not a count of proven physical per-cell solver regressions. A centroid-nearness crosswalk, clean execution or within-arm comparison cannot substitute for accepted complete exact correctness proof.

The original FAIL and original artefacts must remain intact even if later evidence resolves the issue. Record any accepted resolution as a **successor proof/disposition**. Consequently, the current wrapper cannot be used unchanged to admit that successor: it still checks the preserved FAIL. After correctness closure, Heat and the coordinator must bind the accepted successor through a **new reviewed job revision**, retaining the necessary source identities and focused positive/refusal checks. Preserve r2 as an immutable, correctly refusing reference. An owner message alone does not satisfy its on-disk gate. This plan does not authorise creating or running the successor revision.

## 2. Authentic arm schedule and what it can establish

The reviewed r2 job specifies the following order; each timing arm is a fresh process on the genuine W4 same-call control, with six reconstruction workers on each of its two heat calls.

| Zero-based arm | Mode | Layout | Recorded label |
| --- | --- | --- | --- |
| 0 | time | lw | base |
| 1 | time | ld3 | h12 |
| 2 | time | le3 | h12c |
| 3 | time | lf3 | h12cl1 |
| 4 | time | lh | h5a |
| 5 | time | lh | h5a |
| 6 | time | lf3 | h12cl1 |
| 7 | time | le3 | h12c |
| 8 | time | ld3 | h12 |
| 9 | time | lw | base |
| 10 | prof | lh | h5a |

Thus the timing sequence is `lw ld3 le3 lf3 lh lh lf3 le3 ld3 lw`, followed by `prof lh`: **11 total arms, ten timing samples and one separate profile**. The last arm uses worker cProfile instrumentation. Do not average it into the uninstrumented timing pairs.

| Layout transition | Conditional gain being assessed |
| --- | --- |
| lw -> ld3 | H1a r3 + H2 |
| ld3 -> le3 | H1c r3 |
| le3 -> lf3 | L1 r4 |
| lf3 -> lh | H5a |
| lw -> lh | Whole cumulative stack |

These are incremental comparisons along one cumulative composition chain. They do not test every permutation or establish a globally optimal H1c/L1/H5a ordering. Mirroring can mitigate steady order drift; it does not guarantee unbiased timings or cancellation of arbitrary host load. Report both observations for each layout, comparable timing measures, observed other load, order sensitivity and uncertainty. Keep whole-arm, legacy/compact and reconstruction timings distinguishable.

Enable only if the change gains under the existing acceptance rules; small exact gains count. Preserve negative, no-gain and noisy outcomes. There is no authorised fixed speedup hurdle, drift cutoff, temperature/frequency retry policy or claim of microsecond measurement precision. No automatic reruns follow from these outcomes.

The separate C14 composition order **H2 -> L1 -> H3** remains intact. This q22 plan creates no new dependency blocking [Plan 13 / q25](plan-13-heat-kernel-h3-q25.md).

## 3. Reviewed baseline, artefacts and the output discrepancy

Use the existing reviewed route as the baseline for the eventual successor job; do not invent another benchmark implementation.

| Role | Existing source or destination |
| --- | --- |
| Reviewed wrapper | `T/hs/scripts/job_h1c_r4c_r2.sh` (`12fa7955`) |
| Reviewed harness | `T/hs/scripts/ab_heat_r8.py` (`1146192b`); r5 prediction logic plus the seed rule, without the r6/r7 gate changes |
| Completion checker | `T/hs/scripts/check_arms.py` (`b8e7fe7f`) |
| Existing prerequisite | `T/hs/evidence/h1c-r4a/RESULT`, currently FAIL |
| Histories named by r2 | `T/hs/evidence/h12-r1/summary.json` and `T/hs/evidence/h1c-r4a/summary.json` |
| Actual r2 output | `T/hs/evidence/h1c-r4c` |
| Queue registry | q22 record in `T/q/queue.json` |

The wrapper refuses an existing output directory with exit 5; the harness also creates its output directory exclusively. Preserve existing evidence. The output includes `summary.json`, per-arm JSON and logs, worker profile files for arm 10, and `check-arms.txt`. A new combined synthetic result file is unnecessary. Source/helper identities, input/layout identities and actual observations remain part of the evidence.

**Metadata discrepancy:** q22's descriptive `what` field names `h1c-r4c`, agreeing with the wrapper and owner record, while its structured `outputs` field still names `T/hs/evidence/h1c-r1`. Use the wrapper's actual destination in this plan. The coordinator must reconcile the queue metadata with the reviewed successor route at any future release; this document edit changes neither the registry nor either evidence directory. If that future destination is already occupied, retain it and obtain a reviewed new destination rather than overwrite it.

The retained `dry-job-r4c-r2.log` reports DRY RESULT PASS for **11 dry cases**, including a schedule simulation, existing-output/prerequisite refusals and real interpreter-check positives/negatives. It is not a completed 11-arm scientific benchmark. Reuse that adequate unchanged evidence. The coordinator waived the refuter for the specific r8 revision that only added refusals; that waiver does not automatically cover the proposed successor proof gate. Changed admission behaviour requires its own applicable focused checks and review before release.

## 4. Booking, predictions and unchanged guards

The current q22 booking is **1.1 GiB, seven physical cores including the parent, quiet, exclusive, 36 minutes**. The wrapper's roughly 22-minute comment is an older projection. Neither figure is an observed completed q22 duration. The existing elapsed-time escalation rule remains a coordination rule, not a new automatic kill or retry threshold.

r8 retains r5's dynamic prediction behaviour before every arm:

1. Match the mode, layout, `used == [6, 6]` and W4 input against completed successful arm history, including earlier arms of this run. The historical missing-input default is limited to the harness's one established W4 control input. Proof-mode history is not a matching time/prof measurement merely because its layout matches.
2. Use the largest qualifying PASS/exit-0 peak without a stopped outcome. Where measured parent and per-worker peaks exist, take the greater of the recorded tree peak and `parent_peak + 6 * worker_peak`.
3. Without a matching measured arm, use `RUNQ_PRED_PEAK_GIB`, then the explicit `--pred-peak-gib` fallback when the preceding value is absent. Missing, non-positive or non-finite prediction refuses; an invalid supplied value is not permission to fall through to a lower guess.
4. Gate on `predicted_peak * 1.2 + 2 GiB`. With the initial 1.1 GiB fallback this is **3.32 GiB**, approximately 3.3 GiB. It is not a fixed threshold for all later arms: a later mirrored arm can use an earlier matching measurement.

Retain prediction basis, start gate, free memory, wait, tree/parent/worker peaks and load observations. Failed runs do not lower the queue prediction. Keep the reviewed harness's wait/refusal behaviour and the in-run **12 GiB tree-RSS / 1 GiB free-floor** guards. Preserve the wider 16 GiB logical, 256 MiB scope, 1 MiB integer (8,388,608-bit) and 256 accepted-step limits. This heat plan introduces no N9 numerical exception, new low-memory fallback or altered booking to satisfy a fixed gate.

## 5. Exact acceptance and environment checks

Retain **D-b**: every number and every other field byte-identical, with only approved digest-only identity differences. Digest classification alone does not approve a translation. There is no epsilon or checksum-within-tolerance comparison. The timing/profile control's within-arm checks do not replace the accepted q10 cross-arm correctness prerequisite.

The wrapper must obtain `check_arms.py` PASS with all of the following:

- Exactly 11 arms present.
- Every arm has status PASS and exit code 0.
- Zero leaks and no `stopped` field.
- `used == [6, 6]` and `fallback == [None, None]` for the two heat calls.

A bare harness exit 0 is insufficient: `run()` can stop on a gate or incomplete arm, write a partial summary and return. The wrapper's final checker, saved `check-arms.txt` and propagated failure exit are essential. Preserve the exact schedule, identities and mode distinction alongside these completion fields; the checker alone is not a substitute for them.

Each arm's per-arm result must show `ab.interpreter.hash_randomization == 0` and **`ab.interpreter.worker_probe_hash_randomization == 0`**. The owner note's shorter `worker_probe` wording is not the JSON field name. Runtime children use `-B -s -P`, a cleaned environment with `PYTHONHASHSEED=0`, and one BLAS/OpenMP thread. The prof route alone adds the approved `T/hs/workerprof` PYTHONPATH. Preserve the actual interpreter flags check, checked worker-launch source pattern and worker-style seed probe; an environment-variable check alone is insufficient. Do not substitute `-I` or `-E` for runtime-child flags.

## 6. Conditional release and ownership

After accepted Plan 05 closure, Heat supplies the successor proof binding and new reviewed job revision, its source identities, applicable gate/refusal evidence and readiness. The coordinator reconciles the output discrepancy and remaining conditions before any release. The existing interface is `runq.py hold-ticket q22 off --why "..."`, used only by the coordinator on Heat's accepted readiness. A global hold release does not clear this ticket hold. Heat then launches the explicitly reviewed and authorised `runq.py run q22 -- bash <successor-job>` route. No successor filename or ready-to-run command is invented here.

Heat reports the actual paired timings, profile, exactness checks, resources and scoped outcome. The coordinator retains ownership of the improvements table and enabled-build decision. Final assembly and fresh full intervals retain their separate authority and integration gates. Completion of this document is not benchmark completion or permission to continue paused work.

## 7. Completion conditions, not current claims

- [ ] Accepted Plan 05 successor correctness proof resolves the prerequisite while preserving q10's original FAIL and evidence.
- [ ] Heat/coordinator bind that proof in a new reviewed job revision, complete applicable focused gate checks, reconcile the queue destination, and obtain the required explicit release; existing holds remain until then.
- [ ] All 11 authentic arms complete with wrapper/checker PASS, exact interpreter fields, unchanged guards and retained source/input identities; the profile stays separate from the ten timing samples.
- [ ] Paired timing, load, order-sensitivity and resource evidence support an honest scoped gain/no-gain/uncertain disposition under the exact D-b contract, without automatic retry or invented thresholds.
- [ ] Heat delivers the evidence and the coordinator records the disposition and next action, preserving C14, q25's existing dependencies, N9's pause and all integration/full-interval boundaries.

## 8. Primary sources and decision record

The following identities were read for this amendment; they pin the reviewed baseline, not a future successor. Current ownership and release authority must be reopened when actual work is assigned.

| Source | SHA-256 | Relevant evidence |
| --- | --- | --- |
| `T/hs/HANDOFF-20261016.md` | `0c0d7459c6263dcbefd3853586feb1a213dbe5e5f5952145b41cdf282cf21899` | Rules and complete q22 section; interpret historical status against actual FAIL/current status |
| `T/q/queue.json` | `0992c52d69b18268cf26f56282b36ce2922cac6928813afbe2fb4af12702cec6` | Complete q22 record at `/tickets/10`; held, booking and output discrepancy |
| `T/hs/scripts/job_h1c_r4c_r2.sh` | `12fa7955e8fd9926a7bd710ec785eb7e9040d9327ee94f0af411b7fe45f9fd56` | Exact schedule, prerequisite refusal, destination, final checker |
| `T/hs/scripts/ab_heat_r8.py` | `1146192b314bae1e174b7a246547885b2f5368f71cef2604969f684f29f42fbe` | Predictions, child/worker checks, recording and incomplete-run behaviour |
| `T/hs/scripts/check_arms.py` | `b8e7fe7f29ee50c49886b0dba125760678311381a17cf3c3e09a64be85587139` | Required arm count and completion fields |
| `T/hs/evidence/dry-job-r4c-r2.log` | `409c77ec0e5466016f691cbafabc90fdbadeb053cf1e94b1b18e4bb10cdc0552` | Eleven dry cases, not scientific arm measurements |
| `T/hs/evidence/h1c-r4a/RESULT` | `4f8e9e45f8a9e1843b81eaf3bdf52a6b778d415d23bf985774a9d34a43f69bd5` | Preserved FAIL |
| `A/.atlas-dev/plan-status-20261016.md` | `be270e6898e0b1d5aa0c7d29065baf1d4df16ece34490f17d7c68a9d77d4339e` | Current heat, queue, order and acceptance boundaries |
| `A/.atlas-dev/run-queue-protocol-20261016.md` | `c0cf31fc54d4f302311037c2250c600c1ecd1429f5acf8940eac5dee9ac9a0b0` | Per-ticket ownership and memory gates |
| `A/.atlas-dev/coordinator-handoff-20261016.md` | `e75652996f3f29e6c4b074f24bec561551c842c7b04a1ac49ccb8c411799ba15` | Programme exactness and enable-only-if-it-gains rule |
| `plans/plan-05-q10-heat-correctness.md` | `3a4e5daadb19c6a35170603670de2c9881579f7d9a60b2b670f68208a83eb74b` | Agreed preservation of original failure and successor disposition |

Discussion: Gemini's synthesis/directive in #general531 and Claude's acceptance/retained qualifications in #general532, after the independent initial positions and ordered turns. [Codex turn 2](../discussions/atlas-plans-39-review-20261017/codex-plan-12-turn-02.md) records the detailed primary-source assessment. The frozen initial review remains unchanged.

## 9. Completed component comparison and combined private integration

The authentic q22 successor completed all 11 arms with PASS: ten mirrored timing
samples and one separate profile. The observed run took 17 minutes 20 seconds,
with sampled queue tree peak 1.12 GiB. On its W4 supervised comparison, the
baseline-to-lf3 mean fell from 109.625 to 80.742 seconds (26.347% lower).
H5a was 6.067% slower than lf3 and is not selected; its retry disposition remains
with Plan35. These are component observations with original source/input/runtime
bindings, not whole-interval or new combined-profile measurements. The profile
arm is not averaged into the timing means.

The selected lf3 route is integrated with current compact heat consumers and all
earlier enabled changes. The combined composition contains 239 native and 390
helper files: 18 changed files and 611 preserved source files. Its focused
qualification passed 27 orchestration tests, three native-entry cases and four
heat cases. D5, P4 and H5a remain disabled. The original q10 failure, historical
NOT REPRODUCED observation and old receipts remain unchanged; the later scoped
correctness disposition does not establish general causality.

The new profile needs its own eligible ROOT; neither q22 nor the original-profile
q46 ROOT pair or q47 reuse smoke authenticates it. Plans31/38 retain final assembly,
the held full-interval chain and full-workflow cold recovery. Plans34/35 retain
final combined timing. C14's H2 -> L1 -> H3 order and Plan13's independent q25
boundary remain intact; H3 is not included by this integration. No whole-interval,
RAM, disk or Release/Debug gain, scientific acceptance or hold release is inferred.
