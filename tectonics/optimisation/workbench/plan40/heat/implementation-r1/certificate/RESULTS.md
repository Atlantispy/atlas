# Certificate implementation outcome

**Current actual-source result:** the later [exact-version comparison](../MEASUREMENTS.md) improves the rank-20 complete r3 attempt by 3.340% and solve by 4.800%; rank-4 solve regresses4.646% and its r3 attempt is effectively flat. C3 is retained as an unenabled source candidate with mixed performance. The prototype selection table below is earlier evidence, not the final implementation percentage.

WORKING NON-CANON. Implemented **C3 only**, as full additive Python certificate and compiled-dot source successors, plus the parallel caller's two corresponding source pins. Nothing selects this generation in production or starts a worker. C15-first readiness was conditional on savings; the actual measurements do not support it.

## Measured selection

Accepted run `364b539f-74df-4ee4-83ce-f4f1cb2370f8`, q76, payload `b793d9a0`; raw certificate measurement SHA-256 `e2266ec5bea52e373e2f5058357c57b6fd4456f96a2fbdf1cba29be1d3fd1d5d`. These are synthetic identity inputs, 320-bit arithmetic, four counterbalanced pairs. Values below are median **milliseconds per complete call**, dividing each sample by its recorded call count. Negative change is faster. `MEASUREMENT-DECISION.json` retains every normalised sample, pair-win count and accounted-memory comparison; no sample is removed.

| Candidate | Rank 4 baseline → candidate (change) | Rank 20 baseline → candidate (change) | Decision |
|---|---|---|---|
| C3 | 0.335163 → 0.311638 (−7.02%) | 6.222450 → 5.823300 (−6.41%) | Implement: 3/4 pair wins at each rank, no added retained state/accounted memory; small source change. |
| C4 | 0.300325 → 0.317837 (+5.83%) | 6.137250 → 5.993550 (−2.34%) | Retain reference: small/mixed result does not justify optional owner. |
| C5 | 0.313187 → 0.362350 (+15.70%) | 6.200400 → 5.179750 (−16.46%) | Retain reference for this batch: rank-20 benefit is real in all four pairs, but rank-4 regression and +1,933,312 accounted bytes at rank 20 do not establish a general selection policy. Do not invent a production rank threshold from two synthetic cases. |
| C11 append | 0.570562 → 0.914500 (+60.28%) | 23.458200 → 57.040400 (+143.16%) | Reject measured cache implementation. Mismatch also regresses 53.57%/149.23%; unavailable funding is +0.74%/+0.56%. |
| C15 | 0.331075 → 0.329875 (−0.36%) | 6.126750 → 7.279550 (+18.82%) | Retain reference. Two rank-20 candidate samples rise to 8.6003/8.7163 ms; they remain in the result. |
| C16 | 0.506162 → 0.492550 (−2.69%) | 6.876000 → 6.613700 (−3.81%) | Retain reference for this batch: only 2/4 and 3/4 paired wins, small absolute gain and a new attempt-lifetime owner. |
| C17 | 0.305275 → 0.590650 (+93.48%) | 6.112250 → 11.790900 (+92.91%) | Reject measured guarded implementation. |

C3's raw rank-20 candidate samples are 5.860300, 5.784400, 5.786300 and 6.324000 ms; corresponding baselines in chronological arm order are 6.215100, 6.043400, 6.294800 and 6.229800 ms. There is one losing pair, not universal acceleration. These short samples establish a bounded engineering choice, not a confidence interval, production zero frequency or whole-heat saving. Import/JIT is separate in the raw run. Those samples describe the prototype. The later complete-source comparison is recorded in [actual measurements](../MEASUREMENTS.md); the native bytes equal the measured transform. No independent gains are summed.

## Actual source and callers

`source/helpers/private_heat_certification_kernel_r1.py` is a complete selected-source successor. Its original dot implementation remains as `_c3_reference_dot`; the guarded `dot` carries the accepted C3 finite signed-zero logic and preserves ordered additions, checks and unsupported-context/type fallback. Its native neighbour pin names the actual successor bytes.

`source/helpers/private_heat_compiled_dot_r1.py` is byte-identical to the measured/tested C3 native transform: MPFR finite/zero/sign queries and exact signed-zero writes replace only eligible products; all original ordered additions, reviewed native-layout/version checks, compiled signatures and self-tests remain.

`source/helpers/private_heat_functionals_parallel_r1.py` changes only `_ASSEMBLY_CERT_SHA256` and `_ASSEMBLY_H3_SHA256`. Its original policy, live-token checks and worker control remain. A new composition/observer binding is still required before worker selection; this file is not an old-contract bypass.

| Successor | SHA-256 |
|---|---|
| Certificate r1 | `6ae1a0ab413dd36f4544a147aedc0f58e3347bf52501a7f205a25e9c09b62eeb` |
| Native dot r1 | `18317500e239fbd9c6359c0abe110969495bdd356f88d38b92b3c1f2510cd0d5` |
| Parallel caller r1 | `107f804186e316ef2805e013271c89438a75a14fee5b1a6d53d50507cd050a7d` |

`SOURCE-DELTA.json` records selected original public/private identities and successor hashes. Old sources/maps remain unchanged. Ordinary imports of complete selected certificate r3 and functional-bounds r2 resolve the same successor r1. These callers' algorithmic bytes remain unchanged. The test loader verifies unchanged dependencies against the selected public map; that is a public source-bound qualification, not authentication of private runtime/checkpoints.

## Focused verification

`CHECK-RESULTS-r2.json`: PASS. Three complete solve/physical cases (rank 2/80 bits, 4/320 and 20/320) match the original in exact MPFR encodings, flags and check traces, including three cancellation points each. Four actual, normally imported r3 `_attempt` calls cover success/export/close, singular refusal, cancellation and entry admission refusal, comparing exact outcome, resource evidence and final release. No extraction or monkeypatch substitutes for the implementation or r3 caller; the accepted checker instruments comparisons and resolves unchanged source-bound dependencies.

Actual loader controls cover missing-native fallback, changed neighbour bytes refusing, and a stale loaded seal refusing. The missing-native case also completes a rank-4 Python solve/physical comparison. The three successor files and checker pass focused Ruff F821/F841/B905; the same checks on their predecessors are clean. Existing broad arithmetic controls are reused, not relabelled as new runs.

Reproduce with the existing Atlas environment, explicit checkout and accepted certificate-controls file:

```text
PYTHON -B check_successor.py --repo ABSOLUTE_CHECKOUT --controls ABSOLUTE_ACCEPTED_CERTIFICATE_CONTROLS --output NEW_RESULT_JSON
```

The checker refuses optimised Python and an existing output path, pins accepted control bytes, and uses one available CPU. Disposable loader fixtures are retained alongside the checker. The initial offline writer hit an indentation error before writing successor files; it was repaired before these checks. A checker-only unused-variable lint finding was repaired while retaining failure custody explicitly. Predecessor `CHECK-RESULTS.json` is retained privately; the r2 result additionally verifies the full Python fallback and includes the parallel successor binding.

Root owns shared composition, implementation review and publication. A new source-generation binding, strict import/receiver qualification and any separately authorised worker/recovery proof remain required before production selection. The source-construction and correctness-control stage ran no IV, worker or scientific work. The later controlled actual-source comparison completed under q80; no production route was enabled. AI-assisted implementation; original mathematical and resource contracts preserved.

## Actual-module measurement adapter

`measure_successor.py` SHA-256 `9d1be5f19a2d4b18917ec4b320de677df9c8d3523186c879a5fde9a8102ecf5e` is frozen for the parent's combined C3/C8/C13 request. `ACTUAL-MODULE-SMOKE.json` SHA-256 `0848acbf1131a96c178d44beaea8c3bdfbd14adcdfd7821c85c77bba9e958477` records PASS from one no-clock execution of the exact arm loop. The subsequent controlled benchmark completed and is retained in `ACTUAL-MEASUREMENTS-r1.json`; the earlier table remains prototype evidence.

Both arms import complete pinned r1 and native modules; the baseline pair is copied byte-for-byte to a new output-adjacent fixture so its genuine neighbour loader can resolve the selected native file. The full selected r3 caller is imported separately for each actual r1 module. No arithmetic or caller extraction/monkeypatch is used. The unchanged accepted source-bound dependency bootstrap is reused, including its extracted escaping-workspace support. Both native modules retain their own genuine cached loader routes and four compiled signatures; there is no per-arm monkeypatch or route replacement. Module import and native import/build/self-test are reported separately in benchmark mode.

The loop covers synthetic identity ranks 4 and 20 at 320 bits, four counterbalanced pairs, respectively four and one complete calls per sample. Its first scenario preserves the earlier solve/physical component boundary, including interval-plan construction, reservation, actual module calls and runtime guards, exact result encoding and release. Its second scenario calls the complete actual r3 `_attempt`, including export, returned owner and close. Inputs and source identity checks are outside clocks; successor runtime guards remain inside. Exact output digests match all 32 arm samples / 80 complete calls. Accounted peak bytes match both arms: solve/physical 2,170,880 and 21,110,784; r3/export 2,899,362 and 22,836,642. Each call verifies zero retained charge after close. Focused Ruff F821/F841/B905 passes.

```text
PYTHON -B measure_successor.py --repo ABSOLUTE_CHECKOUT --controls ABSOLUTE_ACCEPTED_CERTIFICATE_CONTROLS --smoke --output NEW_RESULT_JSON
PYTHON -B measure_successor.py --repo ABSOLUTE_CHECKOUT --controls ABSOLUTE_ACCEPTED_CERTIFICATE_CONTROLS --benchmark --output NEW_RESULT_JSON
```

The first form qualified the no-clock loop before the second form executed once under the exact q80 GO. Any future controlled repetition requires fresh admission. Mode defaults to smoke; neither smoke nor its result collects elapsed samples. The unchanged native source still uses its own internal import self-test clocks. Schema includes top-level `status`, `candidate: C3`, `script_sha256`, `mode`; complete samples are under `candidates.C3.benchmarks`, and import/build records under `imports`. An existing output or source-fixture directory refuses; optimised Python refuses before work; errors produce FAIL/nonzero. Projected bound is one core, under 700 MiB RSS and 180 seconds; these are caps for planning, not measured utilisation. Review applies to the completed implementation, not a separate testing gate. All production/worker/scientific holds remain.

## Explicit later receiving obligations

The genuine r3 `_attempt` controls and functional-bounds import/identity checks
are not complete `assess_weights` or bounds-entry qualification. The existing
certification inventory still pins the original r1. A later receiving generation
must provide an explicit successor inventory/source binding before those full
entry points can select C3; the old guard must not be bypassed or silently repinned.

The pin-only parallel successor still attests its original fourteen MPFR exports.
The C3 native implementation additionally uses `mpfr_zero_p`, `mpfr_number_p`,
`mpfr_signbit` and `mpfr_set_zero`. Any later worker observer/composition binding
must attest those four functions as well. No worker route is qualified by the
current pin edits. These are explicit limits of this accepted source-only batch,
not permission to enlarge it, modify held profiles or relabel old evidence.
