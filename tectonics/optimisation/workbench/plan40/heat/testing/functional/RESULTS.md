# Functional candidate tests — frozen status repair r6

All five assigned candidates have passing **bounded component checks**, with the qualifications below. No production helper, accepted public artefact or selected source was changed. No benchmark, worker, scientific run, JIT or installation was performed.

Authoritative frozen correctness result: `correctness-frozen-r5.json`, SHA256 `0a3a5bd606fad571f40d76dce5ac1491f1d4fe06ecde82c469d98fa2d0553960`.
Authoritative extended smoke result: `smoke-frozen-r5.json`, SHA256 `e0dd88d6ea2ada637b01d8ae4c9b1557ca5c05fd84c9d6d884cb1989eeb22579`. It contains the five correctness results and the new all-five sample-loop checks. Both have top-level PASS and exactly C1/C2/C12/C13/C14 all PASS, with explicit partial-component qualification. Failure or blocked status exits non-zero.
Frozen successor executable: `functional_tests.py`, SHA256 `50b834caa8c5bf01156909ec96f49afdeace2df9e8f3fff30ff5cef879c20147`. Predecessor bytes are preserved as `functional_tests_predecessor_r5.py`, SHA256 `0240b5fefff19022756eaf99c5c1a6e26b7757df6e2c018baceb7aa5b3f66838`.

Required review F3 found that a sample-loop failure, although still non-zero, was incorrectly relabelled BLOCKED after passing correctness. The successor changes exactly one predicate: BLOCKED classification now requires an actual BLOCKED candidate. `FAIL_SAMPLE_LOOP` and candidate FAIL survive. No numerical algorithm, workload, timing loop, guard or dependency changed.

Focused successor control `status_control_r6.py` (SHA256 `080a1f86c794e6d79752335c4cec06270c9ce2157eee5b39aa9fbee88a251793`) verifies the exact single-predicate byte delta, reuses pinned passing C1 correctness and injects a sample-loop exception through the actual successor entry. `status-control-r6.json` (SHA256 `2912bd3633d1e9a383d99bd09e8f383dd918ab07662d57fb7c3067c7414cd101`) reports PASS: observed overall `FAIL_SAMPLE_LOOP`, candidate FAIL and exit1. The deliberate failed record is `status-control-r6-failure.json` (SHA256 `582f318c67f5a66e39c9be7353564c176e0fb98aeadc63e5cf65f9ad48abb9e7`). A raising harness clock prevents accidental timing. Focused Ruff F821/F841/B905 passes.

`successor-evidence-r6.json` (SHA256 `03b33cb798483a44396cbe46defca41870a2a510af1c6fd76c681f21da5ff9f8`) combines the focused successor control with explicitly reused predecessor correctness and smoke evidence. Its top-level PASS and five scoped candidate PASS entries are evidence reuse after this status-only change, **not a new successor numerical or combined smoke run**. Both original result files and all earlier evidence remain intact. No whole numerical suite, timing, queue submission or worker was run for F3.
The prior correctness record remains `results-final-r2.json`, SHA256 `99a75bc26ffbc71416ce053c463f4157f7fed0590537b97d8ad5a7319d6e2e28`; unchanged source and fault evidence remains applicable. `smoke-r3.json`, `smoke-final-r3.json` and `smoke-final-r4.json` are superseded sampling-development observations. `injected-sample-failure-r3.json` is an intentional post-preflight corruption failure, not a candidate defect.
Earlier `results-r1.json`, `results-r2.json` and `results-final.json` are superseded development observations, not the final candidate record. `injected-failure-report.json` is an intentional failing harness control, not a failed candidate.

The script resolves 14 actual selected members from the pinned637-member map (`ce77c8f2922e0d8780e241ba9204e775388fa093935968eaee7c577606baaccc`). It uses real GMP2.3.2/GMP6.3.0, the selected exact-growth admission method, native selected WorkBudget/OwnedWorkspace and escaping-exception custody. Source extraction avoids importing an incoherent composed public folder. Source paths in the machine result are checkout-relative; `--repo` supplies the checkout. C2's optional private dependency is supplied through `--private-helpers`, never hard-coded in the script/results.

| Candidate | Executed evidence | Remaining limit |
|---|---|---|
| C1 | Four actual GMP point fixtures: zero, mixed signs, large odd denominators and very small dyadics. All20 canonical outputs and complete original admission/operand/width traces agree;105→16 executed multiplies. Funded cache allocation precedes population; forced unfunded fallback restores reference arithmetic. Four cancellation positions, initial-budget refusal and one-byte-short vector-growth refusal agree. Native error custody remains charged while the error lives and releases after drop. | Fixed fixture cache bound, not arbitrary-input/RSS or complete reconstruction qualification. |
| C12 | Same four actual GMP input families;20 flux outputs agree,116→66 multiplies,51→39 divisions,48→36 additions. All original q/getter-reservation, rational-admission, logical operation and poll streams agree. Up to28 retained subresults are separately funded. The same cancellation/refusal/fallback/custody tests pass. | Selected flux method plus prototype seam, not a production imported successor or full physical-row certificate. |
| C2 | Unmodified public `_prepare` first retains its real source-fence refusal. Then the complete selected `_prepare` body runs with explicit component source-fence dependency injection and the actual, original-hash-matched private Decimal runtime checker. Baseline/reused preparation digests agree; conductivity, boundary partition and geometry changes rebuild; mutated cached output rebuilds. Cancelled hit preserves the owner; failed replacement preserves the old owner; closed borrow refuses and all charges release. One hit, five actual preparations. | This does **not** qualify public/private composed runtime imports. Same-face support/basis retention across refinement, full forward consumers and worker ownership remain unimplemented/untested. Metadata bound is for the bounded fixture. |
| C13 | Reuses the unchanged accepted numerical control/result identities: four accepted and seven refused polygons, without duplicating those tests. New selected prospective-plan tests give the same808 operations/full3,783,680-byte plan. Real native full admission, retained-result shrink, one-byte-short refusal, prospective cancellation and closed-owner refusal pass. | Full MOMENT runtime fence/r4 retention consumer and optional triangle-sum cache containers remain unqualified. No inventory reduction is proposed. |
| C14 | Actual selected ScreenedSupport with an explicit cache seam,27 observations across three target centres. Exact shell/full ranking, all diagnostics and original poll counts agree.243→81 observation enclosure calls; centre work stays fresh. Overflow/subnormal inputs preserve exact float hex enclosure representations. Changed coordinate/order/key uses reference screening; cancelled traversals and closed-owner refusal pass. Table is owned by a real native workspace beyond the screens and releases on close. | Full support resource wrapper, arbitrary-input table admission and actual worker-lifetime/replay remain unqualified. No cross-process reuse. |

GMP operand storage capacity matters. The first C12 trial found different q-reservation traces because the harness recreated equal-valued normal/moment GMP objects with different recycled capacities in each arm. Sharing the same immutable caller-owned fixture objects corrected the experiment; the q guards were not weakened. A missing selected L1 constant in the first polygon extractor was also corrected before the final complete pass. Both failed trial outputs remain in the task tool record; no failing observation was labelled PASS.

C2's public fence refused the sanitised private policy path. The accessible private Decimal source matches original hash `ded95d895acd84dc3d6e858054a7b21d5a58cb45c9f07790b676c2ad926a02b5`; its unchanged checker authenticates actual native policy `ef0f3b48ec1c992f2887f53b21c054d69439e58be2d3d445069162f29a51a0f0`. The component bridge checks the selected preparation/basis/exact-growth/GMP/budget source and invokes that checker. It is explicitly dependency injection, not a disguised replacement of the public fence. Without `--private-helpers`, C2 reports BLOCKED after exercising its actual public refusal; other candidates still run.

## Harness and resource observations

- Normal frozen invocation: exit0, five scoped PASS entries in `candidates`, detailed evidence in `results`.
- An injected candidate failure writes overall/candidate FAIL and exits1 (`injected-failure-report.json`). It never produces an overall PASS.
- `-O` and `-OO` refuse at the first non-removable guard before imports/source work. The guard stayed unchanged through the final edits.
- `--benchmark` without `--queue-go` refuses; no benchmark result is created. The flag records the caller's assertion of actual GO and does not grant authority.
- Focused Ruff F821/F841/B905: no findings.
- The final correctness process used one CPU, completed its in-process test/setup in0.1215627s and returned in about0.70s. Windows reported process peak working set38,404,096B. Maximum observed C1/C12 logical reservation4,840,576B; C2 peak2,567,104B. These are setup/workload bounds, **not** baseline/candidate timing or an RSS theorem. Harness trace/result storage is separate from production-workspace accounting.
- Stable arithmetic workload hash: `4dfae236b91f4c01ffd550f3018ebe393d26c9e386909edaa230fbf12edbaa95`. C2 and C14 have separate fixture hashes in the machine result. C1/C12 use deterministic synthetic coordinates, not a captured interval workload.

## Runnable entries and queue projection

From this directory, with `PYTHON` naming the already selected Atlas3.12.14 interpreter and `CHECKOUT` its absolute review checkout:

```text
PYTHON -B functional_tests.py --repo CHECKOUT --private-helpers PRIVATE_HELPERS --correctness --output NEW_RESULTS.json
```

`PRIVATE_HELPERS` is the existing selected-original private composed-r2 helpers directory, supplied on the command line. The root already has the authorised location. Each of C1,C2,C12,C13,C14 can be selected independently with repeated `--candidate` arguments. Omit `--correctness` for the same default mode. Output must not exist.

All five have executable bounded **component** arms. Smoke executes the exact counterbalanced sample loop with no harness clock calls and no timing fields:

```text
PYTHON -B functional_tests.py --repo CHECKOUT --private-helpers PRIVATE_HELPERS --candidate C1 --candidate C2 --candidate C12 --candidate C13 --candidate C14 --smoke --samples 2 --output NEW_SMOKE.json
```

After actual queue GO and required prequeue review, the exact all-five measurement entry is:

```text
PYTHON -B functional_tests.py --repo CHECKOUT --private-helpers PRIVATE_HELPERS --candidate C1 --candidate C2 --candidate C12 --candidate C13 --candidate C14 --benchmark --queue-go --samples 3 --output NEW_BENCHMARK.json
```

Each candidate can also be selected separately. Missing private dependencies explicitly refuse C2 sampling; they are not silently replaced. `--samples` specifies one to three **blocks**, each ABBA or BAAB, alternating between blocks. Three blocks produce six raw samples per arm per candidate:60 full arm invocations. Numerical preflight equality and every sample digest comparison occur outside the timed window. `sample_preflight` stores baseline/candidate result digests, workload hashes and per-call work; `benchmark_samples` stores each raw arm sample, elapsed seconds, phase costs, work and owner charges. `smoke_samples` has the same work/results without timing fields. Context-construction time is separate. No timed calls were made in this task.

| ID | Full arm workload, including setup and retirement | Explicit sampling limit |
|---|---|---|
| C1 | Four fixed point cases plus one forced-unfunded reference fallback; real budget, arena, optional memo, original guard trace and teardown for every call. | Instrumented extracted method, no complete reconstruction. Setup included in total, not separately clocked. |
| C12 | Four fixed flux cases plus one forced-unfunded reference fallback; all original guards and cache ownership. Workload hash also includes shared normal, moments and conductivity. | Same limits as C1. |
| C2 | Fresh generation with six requests: identical input, changed conductivity, boundary partition and geometry; another six requests with cache funding deliberately disabled. Baseline12 preparations; candidate10 preparations plus2 hits, including6 reference fallback calls. Input/output snapshots, component source fence, replacement retirement and final close are included. | Same-face support/basis retention across refinement is still untested. DI is not whole-runtime or worker qualification. Cache-disabled mode is a deterministic fallback fixture, not evidence of a real allocation refusal. |
| C13 | Two complete prospective plans and numerical calls, full original admission, retained-result shrink/borrow/close; candidate uses normal/edge/symmetric-triangle reuse for one call and reference fallback for the other. Both keep808 planned operations,3,783,680B full plan and144,356B retained result. Candidate separately funds65,536B for retained locals in this small quadrilateral fixture. | Actual Fraction helper; optional triangle-sum cache is deliberately absent and its custody remains untested. Full MOMENT fence/r4 consumer and arbitrary-input funding remain unqualified. No plan reduction. |
| C14 | One27-observation owner generation, three fresh face centres/rankings, then changed-coordinate reference fallback, then release. Baseline324 observation enclosures, candidate162 including fallback; both12 centre enclosures and4 fresh rankings. | Serial selected ScreenedSupport component, no worker/generation transfer or full wrapper qualification. |

C2/C13/C14 phase times (benchmark mode only) distinguish fixture/generation setup, plans/admission where relevant, compute/borrows, fallback and retirement. C1/C12 retain detailed instrumentation in both arms, including per-call digest creation already present in the tested component; comparison against the cross-arm expected digest remains outside timing. These are instrumented component measurements, not production face timings or a full-heat gain estimate. Source checks and cache metadata costs are intentionally included.

The final smoke ran40 arm samples (two blocks/all five candidates),224 component calls plus preflight, with all expected digests matching. A replacement harness clock raised on any call; smoke passed with no timing fields. Six invalid polygons additionally compare the newly extracted Fraction subset's exact refusal type/message. Post-preflight output corruption was detected by the sample comparison, written as overall/candidate FAIL, and exited1; a console-status defect found during this fault check was fixed to use the authoritative candidate status. Focused Ruff found no F821/F841/B905 findings before the final digest/console-only changes.

The final smoke process used one CPU and reported peak working set36,229,120B. The execution tool returned in about1.05s; this is a harness-duration bound, not an arm measurement. Project the complete three-block measurement under10s, one CPU and128MiB process headroom; configured maximum logical test budget remains256MiB. Queue/supervisor limits remain authoritative. No queue ticket, worker launch or controlled timing was requested or executed here.

Code is frozen at the SHA above for the root's mandatory prequeue review. Root owns staging/publication, any queued measurement and all final integration claims. H5a remains disabled; scientific and full-interval holds remain unchanged.
