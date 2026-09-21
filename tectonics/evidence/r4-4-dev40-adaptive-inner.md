# Dev40 adaptive-inner review and bounded measurement

21 September 2026. WORKING NON-CANON; R4.4/R4 IN_PROGRESS. Local integration,
not a release, mature campaign, physical acceptance or historical-source rebind.
Developed with OpenAI ChatGPT and independently reviewed/corrected with Codex.

## Decision and review correction

Accept the opt-in policy, preserving Picard/zero-rate/default strict solving when
not requested. New runs can add `--adaptive-inner`; the measured combination also
used `--nonlinear-solver anderson --nonlinear-start previous-stage1
--preconditioner-max-uses 4`. Direct solves, non-unit relaxation, prescribed flow
and damage-dependent rheology cannot silently use this policy. Constant and
Tosi-linear laws bypass adaptive correction.

The return patch SHA256 was
`75e6ae783e13191feb85945d0242bc0cbdf9170d635f4d4edf71493f6d8aa243`.
All seven modified baseline files matched Git base
`7aacee7661a96ce35f78dfe61ec5228801ba44dc`; this is a scoped baseline check,
not an assertion about every file in the source archive. Reconciliation retained
the dev40 thermal, assessment and diagnostic-recovery corrections.

Review found one checkpoint gap: a reconstructed nonlinear state could carry a
well-formed inactive summary despite using Tosi-plastic rheology. The live solver
and run auditor already required activity; state restore now independently binds
activation to the problem's rheology and rejects the missing-certificate bypass.
An independent non-unit SI regression and adaptive endpoint-recovery check were
added. Strict final residuals are not allowed an extra roundoff tolerance.

## Focused verification

Windows, Python 3.12.14, NumPy 2.4.6, SciPy 1.17.1, Numba 0.65.1; native threads
limited to one, `python -I -B`, candidate source/tests/tools explicitly selected.
57 distinct focused tests passed across two selections, not a full-suite run:

- Adaptive policy/mechanics/coupling: 30 tests in 27.729 s; 29 initially passed.
  The new restore test expected the inner error text instead of the public wrapper.
  Its assertion was corrected to inspect the cause; production correctly rejected
  the malformed state on the first run.
- Follow-up: the corrected test, all 4 diagnostic-recovery tests, 2 retained reuse
  tests, 14 assessment tests and 7 schedule tests: 28 passed in 24.447 s.
  The repeated restore test is counted once in the 57-test total.

Commands: `python -I -B tectonics/tests/test_adaptive_inner_r4_4.py`, followed by
`unittest` selecting `test_adaptive_inner_r4_4.CouplingTests.test_saved_state_cannot_bypass_adaptive_certification`,
`test_convection_diagnostic_recovery_r4_4`,
`test_preconditioner_reuse_r4_4.ReuseTests.test_changed_helper_keeps_current_operator`,
`test_preconditioner_reuse_r4_4.ReuseTests.test_default_path_no_metadata`,
`test_convection_assessment_r4_4`, and `test_convection_schedule_r4_4`.
All 8 saved timing states and 8 independent endpoint results decoded with identical
recorded identities; work budgets were released. No full regression suite or
long-run acceptance campaign was repeated.

## Independent Windows dev40 timing

Same corrected source with policy disabled/enabled, same developed case-2 fixture
from step 901, 16x16, dt=1e-5. Fixture SHA256
`7284398ed3b3603683a89e31e639d135a7d9d9a372047ccd7b509450bc1d1062`.
This fixture is reused only as numerical input to fresh explicit dev40 states;
its historical source identity is not rebound or declared scientifically accepted.
Execution context: `7586441361a4b8b30ede4bed22f8be87558a5a2bd8453c41eda2cd39aafe74a3`.

One uncounted warm-up request per mode, then three paired repetitions with order
disabled/adaptive, adaptive/disabled, disabled/adaptive. Each uses a fresh prepared
plan, a separately timed first step, three timed prepared steps and a separately
timed cold endpoint solve. Only one numerical worker ran at a time. Source files
were unchanged during measurement; timings include source validation and stage
records, but not subsequent archive write/decode time.

| Repetition | Disabled mean step (s) | Adaptive mean step (s) |
| --- | ---: | ---: |
| 0 | 0.304870966667 | 0.282951166620 |
| 1 | 0.316855400063 | 0.283746133287 |
| 2 | 0.309460666690 | 0.283396966639 |
| Median | 0.309460666690 | 0.283396966639 |

Measured median reduction: **0.026063700051 s per step, 8.4223%**.
Observed ranges are separated, but three samples are not a confidence interval.
Across the 18 timed RK stage solves per mode, total linear iterations fell
6006 -> 3363 (44.006%); nonlinear iterations rose 312 -> 333. This is why reduced
linear work does not translate one-for-one into elapsed-time savings.

Matched endpoint temperature maximum difference was 3.46833672893e-13 K;
composition was byte-identical. The largest returned strict-linear residual/target
ratio across timed adaptive stages was 0.896172966498 (must be <=1).
These are agreement checks, not proof that the underlying physical model is correct.

Preparation, first-step and endpoint times (three repetitions, seconds):

| Mode | Preparation | First step | Cold endpoint |
| --- | --- | --- | --- |
| Disabled | .211398, .222720, .217673 | .617637, .605410, .661890 | .248389, .251345, .258263 |
| Adaptive | .245439, .221367, .224228 | .547261, .556236, .533269 | .216044, .206297, .213169 |

Raw JSON/NPZ evidence is retained in the engineering task's local
`adaptive-dev40-timings/`; the reviewed worker and original chat packet are in
`adaptive-return-20260921/`. These are evidence locations, not runtime dependencies.
No private absolute paths or physical fixtures are added to the public source tree.

## Returned Linux dev39 measurements (separate evidence)

Chat reported median prepared-step reductions of 16.28% (.208890 -> .174891 s)
and 12.36% (.241936 -> .212036 s) on two later developed fixtures. The earlier
fixture's 3.95% reduction had overlapping ranges; the bypassed linear control was
9.51% slower with overlapping ranges. Its environment was Linux/Python 3.13.5,
NumPy 2.3.5, SciPy 1.17.0, Numba 0.65.1. Those are not dev40 Windows measurements,
not additive gains, and not a whole-generator or high-resolution speed forecast.

## Local delivery confirmation

The 14 files in this increment were byte-matched to the tested candidate in the
actual `remake` checkout. Its fresh-process adaptive CLI/restart/audit regression
passed again in 12.520 s (one repeated test, not added to the 57 distinct count).
`git diff --check` and `python -I -B tools/check_coding_safety.py` passed; the latter
checked 13 selected maps and 41 required paths without importing Atlas.
The checkout has 43 total changed/new files including preceding dev40 repairs;
none were committed or pushed. Only this documentation addendum followed that
byte comparison; it is applied identically to both copies.
