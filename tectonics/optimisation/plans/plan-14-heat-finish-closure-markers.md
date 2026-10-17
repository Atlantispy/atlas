# Plan 14: Heat finish markers and closure ticks

**Item:** 14; Heat N6 / backlog 11.  
**Status:** WORKING NON-CANON. Discussion accepted with changes in general555, with the exception-type qualification in general556. This document records the agreed future work; it does not mark the driver build, integration or scientific proof complete.  
**Owners:** Runner is the sole writer of FD and the prepared driver. Heat supplies marker targets and owns Heat S1. The coordinator retains clearance, integration and run authority.  
**Completion condition:** Runner lands the agreed observation seam after clearance, with the existing ticks preserved, exact stage/code bindings and focused checks; returns the evidence to Heat and the coordinator; and records the remaining S1 integration/W4 and first-IV1 observation obligations separately.

## 1. Current state and distinct meanings

Three nearby references must remain distinct:

| Reference | Meaning and current status |
| --- | --- |
| Heat S1 | Closed-guard endpoint certificate reuse: `T/hs/s1/private_heat_closed_owned_r5.py` and finish kernel r11. Built, tested and accepted as **NOT REFUTED** in the owner/coordinator records; integration and W4 proof remain outstanding. |
| Small S1 | Query observations from `T/so/s1/r4`, part of N5 / the interval-N chain. These changes concern F (`run_fresh_interval.py`), not Heat's finish implementation. Published IN-PROGRESS records branch application; this does not establish a private live swap. |
| Runner M | This plan's finish/projection stage markers and closure ticks in FD (`fresh_interval_driver.py`). The seam is agreed but unbuilt. It observes the loaded Heat revision; it does not implement Heat S1. |

Heat's HANDOFF, the coordinator's 18:11 acceptance and published IN-PROGRESS record S1 as accepted/NOT REFUTED. The coordinator's accepted review records 266 fuzz cases with zero mismatches. The retained r2 suite has 30/30 passing cases, including stale theta/energy/face checks and budget release; the wrong V4/V5 variants fail those tests. These are existing results, not checks rerun for this plan. The older r1 26-case result is superseded for this purpose.

**Source conflict:** `plan-status-20261016.md` still says S1 'owes refutation/integration'. The coordinator must reconcile that row with the named acceptance records. Do not commission duplicate refutation from the stale row or present an unestablished lifetime defect as a new requirement. Integration and the missing W4 arm remain real obligations; an accepted refutation is not an integration or W4 result.

FD currently has six earlier heat stage pairs plus commit stages, and only the three existing R9 ticks. Both the private and published FD copies were verified at the same full SHA below. `test_fresh_interval_driver.py` remains deliberately red against that FD: the owner records **28 run, 7 failures**. This plan preserves that baseline rather than calling the marker build green.

## 2. Source paths and evidence

Path definitions:

- `T = C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10`
- `R = T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1`
- `D = R/probes/step8/claude-20261015`
- `A = C:/Users/LOCAL_USER/OneDrive/Documents/GitHub/atlas`
- `WT = A/.claude/worktrees/rv/tectonics/optimisation`

| Primary source | Relevant scope |
| --- | --- |
| `T/hs/HANDOFF-20261016.md`, N6/S1, M and S2/S4 sections | Accepted Heat S1, outstanding integration/W4, marker contract and conditional downstream work. |
| `D/STATE-NOTE.md`, WIND-DOWN 19:15, opening constraints and item C | Runner ownership, review-sync freeze, exact stage/tick contract, red tests and remaining implementation/checks. |
| `A/.atlas-dev/coordinator-handoff-20261016.md`, 18:11 acceptance and Heat finish speed | Accepted independent S1 review; M build still pending. |
| `WT/IN-PROGRESS.md`, Heat finish and interval-N sections | Published status; distinguish the applied query-observation chain from Heat S1 and live runtime integration. |
| `A/.atlas-dev/plan-status-20261016.md`, Heat and acceptance boundaries | Conflicting S1 summary row; q10 FAIL, integration order, unchanged limits and full-interval hold. |
| `R/fresh_interval_driver.py` and `WT/drivers/fresh_interval_driver.py` | Verified current FD copies; existing stage/tick/conditional-commit behaviour. |
| `R/test_fresh_interval_driver.py`, `R/test_prepared_interval_driver.py` | Existing expectations and prepared-route coverage; not files under `R/tests`. |
| `R/composed-r2/helpers/private_heat_finish_kernel_r10.py` and `private_heat_closed_owned_r4.py` | Actual loaded composition: FINISH imports Q=r4, whose `_guard` directly contains `certificate` and `admissible`. |
| `T/hs/tests/test_s1_closed_reuse_r2.py`, `T/hs/evidence/test-s1-r3-s1.log` | Current 30-case S1 proof and recorded result, separately from FD marker tests. |
| `T/hs/evidence/s1-changed-fields-r2.md` | Exact S1 changed-field boundary, superseding r1. |

Verified identities used for this amendment:

- Both FD copies: `d7bba0769fd8a1523818f09b0e11a552acacd463f4037a809909411af82ea030`.
- Fresh-driver tests: `60fba3c7ca0e81d3f58aa15b74756806da5f5dcf2b741d9a2aa5c97f1f4de412`.
- Prepared-driver tests: `cb3f0aac8248236e241a1b36e23b8c9e037589e4f0d2cdd1404cfcd3b7c2b5ae`.
- Heat S1 closed r5: `6da4964cad7a2553cce40ef53fd2a42f6c6f12bd605a92685b59652f7e74c079`; finish r11: `e5a2409fb87695dc0151c7b256f27bea2e550d0fdaf5a66a44b516dde53f3e15`.
- S1 tests r2: `69c3ac8f478496eeb258b958730cc86499c7af9c23b6a575fc9b705a1fd9db6a`.

The [saved Codex turn and evidence record](../discussions/atlas-plans-39-review-20261017/codex-plan-14-turn-02.md) contains the full supporting hashes and scoped inspection results. The [initial independent review](reviews/codex/plan-14.md) remains frozen; its duplicate-refutation assumption is explicitly withdrawn in the later record. These are provenance pointers, not substitutes for current owner authority when implementation resumes.

## 3. Closure and tick contract

Resolve the seam before admission through the loaded `m.J.I.F.FINISH.Q._guard`. Do not hard-code a separately imported candidate r5 module. The current composed-r2 r4 and candidate r5 both contain the two direct nested code objects.

`_closure(fn, name)` inspects direct entries of `fn.__code__.co_consts`, selects `types.CodeType` entries with the requested `co_name`, and returns the **unique matching code object**. It **raises on 0 or 2+ matches**. The owner records do not fix exception classes, so this plan does not prescribe them. Exact code identity is required, not just a matching function name. Do not execute the guard or closures to discover their code.

Retain observer r1 and its existing list of `(probe, tick_name)` pairs. For either nested closure, the probe is `types.SimpleNamespace(__code__=code)`, using the resolved code object. Ordinary probes remain their actual function objects. The observer reads `fn.__code__`; no dictionary interface or observer replacement is required. M must not add global `setprofile`/`settrace` instrumentation.

The list contains **six ticks in this order**, consisting of three retained R9 ticks followed by three new Heat ticks:

| Tick | Probe through the loaded module `m` |
| --- | --- |
| `component_volume_queries` | `m.G.component_volume_bounds` |
| `heat_faces` | `m.J.I.F.FUNCTIONS._face` |
| `heat_faces_collected` | `m.J.I.F.FUNCTIONS.PARALLEL.completed` |
| `metric_identity_calls` | `m.J.I.INDEXED.metric_identity` |
| `closed_guard_certificates` | SimpleNamespace carrying `_closure(m.J.I.F.FINISH.Q._guard, 'certificate')` as `__code__` |
| `closed_guard_admissible_tests` | SimpleNamespace carrying `_closure(m.J.I.F.FINISH.Q._guard, 'admissible')` as `__code__` |

## 4. Stage registration and interpretation

Register these **eleven heat stage pairs**, in this order:

| Stage name | Function through `m` |
| --- | --- |
| `actual-differential-geometry` | `m.G.enclose_differential_ale` |
| `actual-composed-heat-forward` | `m.J.forward` |
| `heat-low-predictor` | `m.J.I.F.LOW.solve` |
| `heat-certified-polygon-reconstruction` | `m.J.I.F.FUNCTIONS.reconstruct` |
| `heat-conservative-finish` | `m.J.I.F.FINISH.finish` |
| `heat-finish-correction` | `m.J.I.F.FINISH.C.correct` |
| `heat-finish-closed-guard` | `m.J.I.F.FINISH.Q.closed_guard` |
| `heat-finish-issue` | `m.J.I.F.FINISH.I.issue` |
| `heat-native-projection` | `m.J.I.N.project` |
| `heat-projection-decode` | `m.J.I.N.R.verified_private` |
| `heat-projection-exact` | `m.J.I.N.R.calculate` |

Keep the existing commit stages after them: `heat-result-packaging`, `heat-checkpoint-save`, optional `heat-checkpoint-r3-checks`, `heat-exterior-finish`, and `endpoint-store-publish`.

There are **16 registered pairs when the R3 checkpoint hook is present, 15 without it**. Preserve the existing condition that `Workflow._r3_after_heat_checkpoint` is callable and the corresponding no-R3 test; do not manufacture that hook. The eleven-pair heat prefix remains unchanged in either case. `heat-projection-exact` resolves r3 through r4's alias in the recorded composition.

This registry includes nested calls; it is not a new sequential solver algorithm or proof that every registered stage executed. `closed_guard` is called only on the closed path. Record the actual stages and ticks, retaining `record['observed_stages']`. The owner interprets certificate/admissible counts as follows:

| Loaded guard | Full theta=1 | Bisection | Bisection remaining at zero |
| --- | --- | --- | --- |
| r4 | 4 / 1 | 70 / 67 | 70 / 67 |
| r5 | 2 / 1 | 67 / 67 | 66 / 67 |

Read these with the actual route and revision. Do not infer IV1's unrecorded path from fixture counts, sum overlapping phase timings, or claim zero instrumentation overhead. Heat's estimated savings remain projections until the relevant authorised measurement.

## 5. Numerical boundary and remaining S1 work

**M changes run-record counters and phase seconds only.** It must retain D-b byte-identical sealed outputs and must not change the Heat algorithm, observer contract or acceptance limits.

Heat S1 has a separate, accepted changed-field contract. Exact guard values, energy/face contents and certificate values remain equal; nested certificate dictionaries may be shared rather than copied. Source bindings and identities incorporating them change with r5/r11. Unsealed diagnostics, operation counts, some resource amounts and cancellation-poll counts can change with skipped work. Do not assert byte identity for all metadata. In particular, **forward-result compact admission is expected unchanged**, despite lower amounts in the closed stage.

Integrate r5/r11 after H5a through the forward successor carrying H5a r14, paying the C15 pin cascade once. The owner specifies a future same-call D-b layout with r5/r11 contents under the r4/r10 names, allowing the approved digest-only identity translation. Preserve the outstanding W4 proof requirement and the actual unresolved H5a/q10 **FAIL**; earlier 'not run' wording does not supersede that failure. This plan neither rewrites the failure nor releases a proof run.

The accepted S1 tests/refutation are retained evidence. Wrong copies in `T/hs/rf-s1/var_V0..V8` must never enter a production import path. Any newly identified defect needs its own concrete evidence and scoped owner action; marker mutants are not a second certificate-reuse refutation.

## 6. Owner implementation and focused verification

After the coordinator clears driver edits following review-branch sync, Runner:

1. Implements FD `_closure`, `_finish_stages`, `_projection_stages` and expanded `_ticks` in **`R/fresh_interval_driver.py`**, resolving bindings before admission. Preserves the existing commit-stage behaviour and observer interface.
2. Makes the ordinary branch of `R/prepared_interval_driver.py` consume FD `_stages` / `_ticks`, updating the corresponding prepared-driver tests. Heat supplies targets but does not edit either driver.
3. Completes `HeatMarkerSourceTests` against the actual pinned composed-r2 module paths, including loaded FINISH.Q and exact nested code identities. Retains six ticks, ordered eleven-stage heat prefix and both conditional commit layouts.
4. Runs the focused fresh/prepared tests, affected regressions and required source checks under the existing seed-0 and queue rules. The tests are directly in R. Preserve the recorded 28-run/7-fail baseline and before-copy; a future green result must identify the implemented successor. Required FD mutants cover dropped/reordered stages, accepting zero or multiple matching closures, and binding a tick to the wrong code object. They must be applied and caught; an unexecuted or unapplied mutant is not evidence. Complete the owner's required Ruff check for the actual code change.
5. Returns the landed result, source identities and check evidence directly to Heat and the coordinator, identifying any remaining blocker and next action. Do not create a polling loop or treat a saved plan as the landing return.

No code or tests are run by this document amendment. Existing adequate S1 evidence is reused. The current freeze remains in force until actual coordinator clearance; a published copy or room consensus does not itself clear it.

## 7. Completion conditions and downstream boundaries

- [ ] Runner has cleared ownership/freeze prerequisites and landed the marker seam with unique code-object resolution before admission, preserving the existing observer interface.
- [ ] Six ordered ticks and the exact eleven-stage heat prefix are bound correctly; the total is 16 with the R3 hook and 15 without it, with prepared-route and actual-source coverage.
- [ ] Focused fresh/prepared tests, affected regressions and required source checks pass on the identified successor; all stipulated FD mutants are applied and caught, with the historical red baseline preserved.
- [ ] Marker-only sealed-output parity is evidenced under the existing rules; the separate accepted S1 review, outstanding integration/W4 obligation and conflicting summary row remain explicitly accounted for. Runner has returned the landing evidence to Heat and the coordinator.
- [ ] The first separately authorised fresh IV1 record supplies actual marker/tick observations, or remains explicitly **INCOMPLETE / held**. Heat S2 proceeds only if those observations show worthwhile bisection; S4 uses the commit markers. Neither downstream implementation is authorised merely by this plan.

There is no new dependency on Plan 15's worker sweep: q01 retains its own readiness prerequisites. Preserve N9 **PAUSED BY USER**, all individual and full-interval holds, existing owners and unchanged numerical/resource limits. Preserve the 12 GiB tree-RSS, 1 GiB free floor, 16 GiB logical, 256 MiB scope, 1 MiB integer and 256 accepted-step boundaries. Exact numerical parity remains the default, with only already approved identity translations and the bounded N9 exception; this observation task introduces no tolerance or width-policy change. No live swap, repin, queue change, new run or publication follows from accepting this plan.
