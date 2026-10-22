# Plan 03 — q21 child launch environment and preserved attempt

**Item ID:** 03  
**Retained owner:** Geometry / Runner; the coordinator retains queue ownership.  
**Status:** WORKING NON-CANON. Published r5 retained; r6 preservation-guard correction implemented and focused-tested as a workbench successor. q21 retry and scientific parity remain separate.
**Completion condition:** Preserve the invalid attempt, resolve its orphan disposition explicitly, prepare a bounded child-environment correction and copy-failure guard, and verify those boundaries before requesting a separately authorised successor proof.

## 1. Scope and authority

This plan concerns the actual `G/scripts/run_dj_rearm.sh` launch boundary. Correct PATH only for that child launch. Do not change global PATH, shared `runq.py`, the scientific algorithm, worker acceptance criteria or source identities merely to make a retry start.

The document grants no new implementation, preflight, queue or scientific-run authority. Preserve separately established authorisation, the retained owners, source freezes and all individual holds. An authorised successor proof requires the coordinator's explicit disposition and launch approval through the existing queue mechanism. N9 replay and fresh full-interval runs remain held.

Path aliases:

- `T` = `C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10`
- `R` = `T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1`
- `G` = `R/geometry-growth-r1`
- `P` = `T/.r44-env/Scripts/python.exe`

## 2. Primary evidence and factual disposition

| Source | Evidence and identity |
| --- | --- |
| `G/work/dj-rearm-r3-q21b.log` | Complete retained launch log. SHA-256 `3ba3da59468bb4db3bc3a3fffd2c4ed0f263aafd2589364e7804285674fc1e3f`. |
| `G/scripts/run_dj_rearm.sh` | Actual wrapper, including orphan audit and copy/launch boundary. SHA-256 `24f3eb16249f2a766348a1c0d34e5109c8fd73ff4ca6259fa1c186da00234759`. |
| Coordinator handoff (private evidence unavailable in this public snapshot), 21:32 and 21:59 checkpoints | Recorded environment diagnosis, verified-descendant stop, post-stop partial observations and explicit preservation ruling; lines 406–407 and 414. SHA-256 `e75652996f3f29e6c4b074f24bec561551c842c7b04a1ac49ccb8c411799ba15`. |
| Current consolidated status (private evidence unavailable in this public snapshot), q21 rows and worker-cap row | Retained Geometry / Runner ownership, distinct q13/q21 outcomes and prerequisites for any authorised retry. SHA-256 `be270e6898e0b1d5aa0c7d29065baf1d4df16ece34490f17d7c68a9d77d4339e`. |
| Current queue protocol (private evidence unavailable in this public snapshot) | Coordinator assignment, source-bound readiness, queue notes and current run controls. Later amendments govern over earlier resource formulas. |

**MEASURED / retained launch record:** q21 started at 21:22:00 and exited at 21:28:48 on 16 October 2026, with exit 15 and a 0.26-GiB process-tree RSS peak. These figures describe the failed launch attempt, not geometry performance, required future resource limits or a scientific result.

The log names the real wrapper and reports:

- `date: command not found` at line 104;
- `seq: command not found` at line 119;
- `cp: command not found` at line 124.

The coordinator records that Git Bash inherited a PATH lacking Git usr/bin, the input-store copy did not occur, and only verified runner descendants were stopped. Do not invent a `/bin/sh` diagnostic, a different wrapper, or an unsupported explanation involving Python's environment sanitisation.

The disposition is **INVALID LAUNCH ENVIRONMENT**. Keep it distinct from q13's **VOID-ENVIRONMENT** worker-count result. q21 establishes neither numerical failure nor scientific acceptance, and its low peak is not evidence for a lower booking of the intended workload.

**Recorded post-stop observations:** `G/evidence/workers-dj/iv2-w6-r3.log` was empty; `G/evidence/workers-dj/iv2-w6-r3.json` and `G/evidence/workers-dj/iv2-store-w6-r3` were absent. These are the checkpoint's observations, not claims of a fresh filesystem scan during this plan edit.

## 3. Evidence preservation and the orphan ruling

Keep the original attempt log, existing partials and associated attempt evidence byte-for-byte. Do not insert a sentinel or fabricated result JSON, delete or move partials, overwrite the old log, or manufacture a scientific verdict. Record any new disposition in the existing owner record or authorised queue note outside the preserved attempt.

Three identifiers have different roles:

| Identifier | Meaning |
| --- | --- |
| `q21` | Existing queue ticket. |
| `q21b` | Suffix of the outer launch log. |
| `r3` | Generation used by the geometry harness and its evidence filenames. |

The exact r3 attempt is ruled INVALID LAUNCH ENVIRONMENT. The r6 successor recognises only the preserved zero-byte `iv2-w6-r3.log` with SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` and the matching bound outer failure log; it refuses changed or additional orphans. It preserves the originals and carries their excluded provenance into the successor merge. See the r6 source for the complete size, timestamp, digest and absence checks. No fabricated scientific result or sentinel replaces the failed attempt.

Changing a log name or selecting attempt generation r4 does not waive those checks. The published r5 review found a preservation bypass: unexpected r3 JSON or a missing original log could skip the named check. The r6 correction requires that check before successor launch, before merge, and when validating copied excluded evidence. An actual retry still needs its separate ticket/launch disposition and valid runtime admission.

## 4. Child environment and bounded preflight

Prepare the smallest correction at the actual child launch boundary. Use the verified installed shell/tool locations and the selected launch configuration; do not assume a parent terminal's PATH proves what the queued child receives. Preserve the selected interpreter, seed, numerical thread settings and other existing environment constraints. Avoid global settings changes or a new general-purpose queue subsystem.

The preflight must execute the required utilities in that same child environment. For the currently reviewed wrapper the external shell utilities are:

```text
bash timeout date seq cp rm sleep mkdir basename sha256sum cut cmp cat
```

The explicitly selected Python interpreter and any additional dependencies of the selected launch/helper chain also need their applicable readiness evidence. Derive that scope from the actual chain rather than inventing a generic POSIX list. `shutil.which`, `command -v` or a string-prefix comparison alone does not establish successful execution or trusted path identity.

Use harmless bounded invocations and a tiny disposable synthetic directory copy. Verify the copied names and contents, observe return codes, and impose a proportionate finite timeout. Cover the demonstrated missing-utility cases. A requirement to finish within 500 ms is removed: desktop load is not a correctness test. Do not run the scientific wrapper or use a real input store merely to test PATH.

Record only relevant tool resolution and outcomes; a full environment dump is unnecessary. No helper path under `q/tools/` is prescribed or claimed to exist. The owner chooses the smallest source-bound preflight within the assigned launch scope and obtains any required review for changed harness behaviour.

## 5. Refuse a failed actual input-store copy

A successful preflight does not guarantee a later real copy succeeds. The original failed-launch wrapper uses `set -u` at line 22, invokes `cp -r` at line 124 without checking its status, then invokes `parallel_parity.py` at line 125. That predecessor can proceed after a failed copy; the retained r5 and r6 successors explicitly refuse it.

In the authorised successor wrapper revision, explicitly check the actual input-store copy result and refuse with a non-zero outcome before starting parity if copying fails. Preserve any new failed-attempt evidence under the applicable policy; never claim that refusal as scientific PASS. Do not replace this targeted check with an unreviewed blanket shell-policy change.

Verify this boundary in a disposable fixture: make the copy fail, use a parity-launch stand-in, and establish that the wrapper refuses and the stand-in is not called. Keep this separate from the positive synthetic-copy preflight. No simulation or real store is required. Preserve source pins, the existing before-copy/new-revision rules and required harness review/refutation; this plan does not implement or execute the check.

## 6. Successor request and completion conditions

Use the coordinator's existing REQUEST route after the necessary readiness work is authorised and complete:

```text
REQUEST: what | why (backlog item) | runtime/composition | inputs | outputs folder | TOTAL GiB (how known) | est. minutes
```

The coordinator determines the ticket and permitted disposition. Do not create a guessed `q21c` ticket, write ticket JSON directly, or treat an existing queued entry as launch authority. Any authorised successor uses fresh log/output names and preserves the original attempt. The successful preflight and copy-failure check establish launch readiness only; the actual six-worker proof, parity criteria and integration handoff remain separate.

- [x] Invalid-launch disposition and the explicit orphan ruling recorded with the original evidence preserved.
- [x] Selected child PATH correction prepared without global PATH or shared queue changes; required utilities and synthetic copy checked in the exact child environment.
- [x] Actual-copy failure refuses before parity, with the disposable failure case retained.
- [x] Successor source identities, applicable review/refutation and handling of the ruled orphan established without bypassing unrelated orphan checks.
- [x] Readiness and proposed fresh output locations returned to the coordinator for a separate ticket/disposition and launch decision.

The existing owner record must retain outcome, evidence pointers, unresolved issues and next action. No new sentinel, ledger or automatic retry loop is introduced. Physical exactness, input identities, worker-adoption criteria and all run guards remain unchanged. Plan 16's worker proof and any wider integration still require their own actual evidence and authority; this documentation revision completes neither.

## 7. Reviewed r5 successor

The [r5 wrapper](../workbench/geometry-growth-r1/scripts/run_dj_rearm_r5.sh) and [focused proof suite](../workbench/geometry-growth-r1/scripts/test_summarise_dj_r5.py) preserve the earlier published files. The wrapper confines PATH changes to its child, verifies required utilities and interpreter, bounds preflight and cleanup, refuses failed input copying before parity, and recognises only the exact ruled invalid-attempt orphan. Remaining scratch is reported for every failed probe. The proof checker treats inaccessible process identities as UNKNOWN, preventing a clean process-death result without alleging a survivor.

Retained original-environment evidence covers 179 earlier cases, 40 focused successor cases, seven bounded cleanup cases and the final two diagnostic/evidence corrections. These were separate source-bound runs with accepted reuse, not one fresh r5 full-suite run. The final two cases pass; no scientific parity or public-checkout execution is claimed. Original r5 wrapper/test SHA-256 values are `329b0b3c76b55e473cc525fa267077cc92c8474f0fab1e200f0844bd8ea7a571` and `2eb6dd0bdedfc525772e256e16272fa340ffcb2a3c11537c39cc675df27fa990`; the publication transformation is recorded in [SANITISED.md](../SANITISED.md).

The retained r5 review and readiness record predates the preservation finding in section 8. The source snapshot still requires excluded private runtime/input/evidence dependencies. Keep wrapper revision r5 distinct from proposed fresh attempt generation r4. No live wrapper installation, q21 retry, worker-count proof or hold release follows from publication; Plan 16 retains the separate ticket/launch and parity decision.

## 8. r6 preservation-guard correction

The [r6 wrapper](../workbench/geometry-growth-r1/scripts/run_dj_rearm_r6.sh) is a source successor to r5, whose bytes and historical digest trail remain unchanged. It moves the D08 validator into the parent shell and requires the exact preserved state before any generation-r4-or-later launch and before creating a merged folder. Excluded evidence is mandatory for those generations: the merge must copy both original logs, revalidate the originals, and verify the copied bytes before invoking the summary. An unexpected r3 JSON, missing log or altered bound evidence cannot silently disable that requirement. Other-orphan auditing and legacy r2/r3 behaviour remain unchanged.

The [focused regression](../workbench/geometry-growth-r1/scripts/test_d08_preservation.py) executes disposable copies of the full wrapper with synthetic logs/stores and interpreter/parity/summary stand-ins. It exercises launch refusal, changes during the run, copied-evidence refusal and the valid merge path without loading scientific inputs or the private runtime. On 19 October 2026, all seven r6 cases passed with no skips. The same suite against retained r5 detected exactly the five expected launch/merge bypasses; its valid-path and unrelated-orphan controls passed. This establishes detection of the actual defect, not a scientific verdict. Both runs used the small queue lane; observed combined process-tree peak was 0.09 GiB.

Commands run from the optimisation directory (through the small queue lane where applicable):

```text
python -B workbench/geometry-growth-r1/scripts/test_d08_preservation.py --wrapper workbench/geometry-growth-r1/scripts/run_dj_rearm_r6.sh -v
python -B workbench/geometry-growth-r1/scripts/test_d08_preservation.py --wrapper workbench/geometry-growth-r1/scripts/run_dj_rearm_r5.sh -v
bash -n workbench/geometry-growth-r1/scripts/run_dj_rearm_r6.sh
```

The r5 command intentionally exits 1 with those five failures; the r6 command exits 0. Shell syntax and focused Ruff checks passed. Repository-root checks also passed: `python -B tools/check_coding_safety.py`; `python -B -m unittest discover -s tests -p test_coding_safety.py -v` (31 run, one platform skip); `python -B tools/check_public_paths.py`; `python -B -m unittest discover -s tests -p test_public_paths.py -v` (14 run); and `python -B tools/check_current_evidence.py` (37 current records, 465 recorded digests matched). These checks are static or synthetic; the earlier scientific/test-isolation results were reused within their unchanged scope.

Tested r6 source SHA-256: `290240cee42ed20be23ae6114ddbd9f4e93bf061ec5e13031f4d4712ebc4bc1c`. Regression-source SHA-256: `f9b948680c36e7f3da0c6eafd0bfdb273d61c7c07f8ccece6d0eb979dff4d849`. The tests replace only fixture paths and the synthetic outer-log hash in disposable wrapper copies; preflight interpreter, parity and summary calls use explicit stand-ins. No historical source pin or receipt was rewritten.

This is a review-snapshot correction, not installation into the live wrapper. Plan 16 still owns any retry and actual worker/parity proof. No held run, source binding or frozen composition is changed.
