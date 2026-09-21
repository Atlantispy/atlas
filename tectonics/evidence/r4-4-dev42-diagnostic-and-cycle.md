# Dev42: reviewed diagnostic and fixed-cycle savings

21 September 2026. WORKING NON-CANON. R4.4 remains IN_PROGRESS.
Base: `49c6603fad2ed9a92f6f2a302037dd425f154c3c` (dev41, remake).

## Integration decision

Keep two small changes:

- Diagnostic snapshots use an accepted immutable stage-1 seed when present.
  Current temperature, composition, density, time and rheology are solved again.
  Diagnostics do not replace the seed or alter subsequent physical steps.
- Fixed GMG pre-smoothing skips the known-zero initial matrix-vector product.
  Its initial direction is copied into independent iterate storage. Degree-four
  pre/post smoothing, transfers, numerical coarse matrices and coarse solve are
  unchanged. No shared scratch, coefficient cache or new retained memory.

The zero-rate default and automatic GMG size/workload selection are unchanged.
Use the previously reviewed explicit `previous-stage1` profile to retain seeds.
At 128x128 the cycle avoids five sparse products: 45 -> 40 per application.
Changed source requires NEW runs; never rebind an existing checkpoint.

## Local measurements

Windows AMD64, Python 3.12.14, NumPy 2.4.6, SciPy 1.17.1, Numba 0.65.1.
One native numerical thread; serial workers; JIT warmed outside timing and no
new compiled signatures inside measured phases. Three alternating pairs per
comparison. No samples were dropped. Preparation and closure are included.

Each batch starts a NEW state, performs two coupled steps of 1e-7 s, then one
final diagnostic. GMG, Anderson, adaptive inner, four-use guarded preconditioner
reuse and previous-stage1 are enabled in both versions. The explicit established
profile uses a 400-iteration ceiling, linear rtol 1e-12, momentum 1e-9, viscosity
rtol 1e-8 and 1 GiB WorkBudget. No tolerance or cap changed between compared
variants. This is NOT the chat's separate 100-iteration experiment.

The developed input is the previously documented raw 16-grid field resampled to
128 using the dev41 probe, zero composition and NEW time zero. It is not an
evolved developed128 checkpoint or a historical continuation. Input NPZ SHA256:
`45cc6acf7d59370984b994f0ad2b8bf5c676c9be4ca105f583dc578b3cb3c26d`.

| Comparison and scope | Before median | After median | Seconds saved | Saved |
|---|---:|---:|---:|---:|
| Diagnostic only, initial Tosi-1 snapshot | 0.232408 | 0.169653 | 0.062755 | 27.002% |
| Diagnostic only, initial two-step batch + snapshot | 1.353112 | 1.266482 | 0.086630 | 6.402% |
| Diagnostic only, developed-input Tosi-2 snapshot | 7.841676 | 2.096511 | 5.745165 | 73.265% |
| Diagnostic only, developed two-step batch + snapshot | 27.916380 | 22.597693 | 5.318686 | 19.052% |
| Cycle added to seeded diagnostics, initial batch + snapshot | 1.267561 | 1.241046 | 0.026516 | 2.092% |
| Cycle added to seeded diagnostics, developed physical work excluding snapshot | 19.574532 | 18.755387 | 0.819145 | 4.185% |
| Cycle added to seeded diagnostics, developed batch + snapshot | 21.739724 | 20.834330 | 0.905394 | 4.165% |

Separate comparisons are incremental, not percentages to add together. One
snapshot every two steps is not the production sampling cadence; no campaign or
whole-generator saving is inferred. The small initial-cycle saving is noisy:
its snapshot subcomponent was 0.001426 s / 0.870% slower by medians. All three
developed total pairs improved. Diagnostic-only physical stepping was unchanged
code and measured 0.44% slower; the benefit is in the diagnostic solve.

Raw paired seconds (baseline then candidate, repetition order 0, 1, 2):

```text
Diagnostic / initial total:
  [1.353112400, 1.454226000, 1.336055200]
  [1.266482200, 1.251610300, 1.334306300]
Diagnostic / initial snapshot:
  [0.229055100, 0.247884900, 0.232407600]
  [0.169652900, 0.170171000, 0.168814300]
Diagnostic / developed total:
  [27.403691100, 28.103700800, 27.916379600]
  [21.688318100, 22.597693400, 23.032697600]
Diagnostic / developed snapshot:
  [7.841675800, 8.017100700, 7.739167300]
  [2.074241500, 2.422676500, 2.096511200]
Cycle / initial total:
  [1.267561400, 1.239521200, 1.294458000]
  [1.241045700, 1.220079900, 1.289977600]
Cycle / developed total:
  [21.739724100, 21.573551700, 22.287047800]
  [20.669253100, 20.979629400, 20.834330300]
```

## Quality and verification

All paired physical state, retained seed and transport arrays were byte-identical.
The cycle also preserved every compared diagnostic array byte-for-byte. Seeded
versus cold diagnostics differed only within existing regression tolerances;
developed maximum velocity difference was 2.755e-10 m/s. Original strict solver
certificates passed for each accepted result. Repeated same-source descriptors
were identical and all WorkBudget reservations were released.

The developed snapshot fell from 133 to 35 nonlinear iterations and from 1,878
to 492 linear iterations. Returned strict residuals were 7.47514e-11 (cold) and
6.18753e-11 (seeded), both below the unchanged target 7.62727e-11.

Focused local checks: 17 diagnostic tests, 10 multigrid integration/component
tests, and the changed cross-step sampling regression. Coverage includes current
forcing, immutable seeds, sampling cadence, cancellation, source/plan refusal,
resource cleanup, no-seed and constant paths, exact zero/nonzero smoothing,
fixed linearity, owned outputs, direct comparison, and actual GMG CLI restart.
The initial linear benchmark driver incorrectly assumed that bypassed adaptive
inner had a certificate; this evidence-only check was corrected to inspect its
active flag. The failed record is retained, not used as timing evidence. No
solver change or relaxation was required. A summary-reader metadata-key mistake
was also corrected without rerunning numerical work.

The two implementation files measured and delivered have SHA256:

```text
_velocity_multigrid.py
bf8e70012c10c2963b73e34c8514f269758464c034de9876921fd82353a01868
thermochemical_execution.py
fb30c7761781f6c7a489c5141ffc0c3ee9961796a93b8a8df19340ee5afe855e
```

Timing copies were dev41 plus the stated changes. The final dev42 version-label
bump changes source identity but not numerical algorithms; final focused checks
run on that delivery. Complete local records include source/input hashes,
environment, policies, descriptors, certificates and comparison arrays.

Reproduce with `tools/benchmark_solver_candidates_r4_4.py` in serial isolated
source copies, alternating order for three repetitions. For example:

```text
python -I -B tools/benchmark_solver_candidates_r4_4.py --source ATLAS_COPY --output NEW_OUTPUT --case tosi-1 --label initial
python -I -B tools/benchmark_solver_candidates_r4_4.py --source ATLAS_COPY --output NEW_OUTPUT --fixture DECLARED_RAW_FIELDS.npz --label developed
```

The second command needs the documented input; it does not reconstruct or rebind
a historical checkpoint. The driver records exact supplied bytes. Its warm-up
and archive writing are outside timings. Run the accompanying comparison tool on
the named three-pair folders; do not run numerical workers concurrently.

## Rejected Galerkin assembly candidate

The assembly chat's later completed native report supersedes its earlier
synthetic-only prototype. It reported 60 exact dev41 executable files and three
alternating pairs: hierarchy rebuild 0.026342 -> 0.022079 s (16.18% faster), but
initial coupled128 2.350936 -> 2.895038 s (23.14% slower), and developed-derived
coupled128 46.008231 -> 50.179245 s (9.07% slower). Its symbolic plan already
survived all 68 hierarchy builds in the developed step. Preparation was only
0.069167 s, much less than the 4.171014 s total regression. Merely amortising
that one-off preparation therefore does not establish a long-run benefit.

Do not integrate this implementation. Those are the worker's returned results,
not independently repeated local measurements; its reported extra diagnostic
refusal in both variants is not physical acceptance. Its packet was not retrieved
because completed browser pages could not be refreshed under the UI safety check.
No claim of a local Galerkin patch audit or universal rejection of symbolic reuse.

The cycle packet had the same attachment limitation. The locally reviewed minimal
change was reconstructed from its complete visible proposal and independently
tested/benchmarked above, not represented as a byte-verified downloaded patch.
The diagnostic packet was retrieved and its two-line implementation reviewed.

No full R4.4 campaign, broad repository suite, commit or push was performed.
