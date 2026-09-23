# W01 bounded validation and acceptance reconciliation

22 September 2026. WORKING NON-CANON; local unreleased evidence.

## What is actually accepted

The supplied-geology / supported-motion / regional-material workflow passed its
71 assembled checks previously, in **54.571858800 s**. That includes numerical
oracles, conservation, scientific input meaning, cache isolation and recovery,
not merely import checks. Its declared planar-strip and axial-wedge limits remain.
It does not need a mature convection run before use.

The package source files are byte-identical to that run. Subsequent changes are
the acceptance wording in `verify.py` and its JSON case, the corresponding status
test, and the new measurement driver. Only the **three affected status tests**
were rerun: PASS. They overlap the original 71 and are not counted as 74 tests.

Whole-W01 generated geological realism is not accepted. R5-R9 contain additional
process and spherical-generation implementation, not merely missing tests of the
existing described-state workflow. R4.4 mature convection remains held/incomplete.

## New, reproducible short experiment

```text
python -I -B tectonics/tools/measure_w01_plate_shapes.py
```

NUMBA/OPENBLAS/OMP/MKL threads = 1. Windows, CPython 3.12.14, NumPy 2.4.6.
No download, fit, seed selection, retry at increased resolution, solver change or
tolerance change. Source hashes before/after matched; all reservations released.
The deadline is cooperative, 120 seconds per case, not an OS hard timeout.

Fixed seeds 41/42/43, 12 plates and 512 support cells reproduce the original
comparison's workload, adding the missing scale-labelled observations. The 12
largest published-area ranks are selected in advance: PA, AF, AN, NA, EU, AU,
SA, SO, NZ, IN, SU, PS. Candidate labels denote target area rank, not reconstructed
Earth identities. The PS morphology evaluation is explicitly labelled withheld
within PB2002; neither it nor the other shapes is used to tune this run.

Pinned full PB2002 dataset:
`b7c61ba3695535abea8bd2f78c67e8348aee2d4230b55276b367aba4c8ab3e7d`.
All eight original source identities were checked on load. This comparison uses
none of the restricted MS/ON/Peru geometry and does not override those restrictions.
The earlier source-review-only no-generation scope is historical: these new small
runs were expressly authorised as bounded validation, not a changed source policy.

| Fixed case | Elapsed seconds | Obtained result |
| --- | ---: | --- |
| 12 plates, seed 41, support 512 | 1.619072800 | 12 independent area/outline checks PASS |
| 12 plates, seed 42, support 512 | 1.661738100 | 12 independent area/outline checks PASS |
| 12 plates, seed 43, support 512 | 1.736311600 | 12 independent area/outline checks PASS |
| 52 plates, seed 41, support 1024 | 1.792304600 | Explicit small-plate resolution refusal; no generated result |

Total driver time: **7.116067000 s**, including reference preparation and source
inventory. This is validation elapsed time, **not a measured speedup**. Budget
peak estimate 96,041,175 bytes; not an operating-system RSS measurement.

All 36 measured outlines agree with both independent spherical area formulae and
the atlas patch sums. Largest discrepancy: **1.5543122344752192e-15 sr**;
largest planetary closure error: **1.7763568394002505e-15 sr**. The unchanged
registered numerical area bound is **2e-11 sr**. Area L1 calibration errors are
0.0082675543, 0.0091816139 and 0.0071094142, all below the existing 0.04 limit.

## Shape findings, not a fabricated realism score

Both reference and candidate boundaries were observed at 100, 250 and 500 km,
with the existing two sampling phases (0 and 0.5). There are 72 paired records per
scale: 12 area ranks x 3 candidate seeds x 2 phases, **not 72 independent Earth
observations**. All measured records, including poorly resolved candidate ranks,
are retained. No quality-based exclusion or new scientific pass threshold.

| Observation spacing | Mean candidate compactness | Mean reference compactness | Difference in means | Candidate/reference mean inward-turning difference |
| --- | ---: | ---: | ---: | ---: |
| 100 km | 0.469311 | 0.508238 | -7.6593% | -65.4202% |
| 250 km | 0.485231 | 0.552877 | -12.2353% | -31.1354% |
| 500 km | 0.512821 | 0.599832 | -14.5058% | +10.2419% |

Compactness is A(4*pi-A)/P^2; inward turning is the existing summed negative
spherical turning angle in radians. Raw records also retain per-plate boundary
lengths, second-moment eigenvalues and phase sensitivity.

These differences expose scale-dependent mismatch; they are **not percentage
accuracy**. Candidate areas use the documented largest-12 renormalisation
(factor 1.0736633528442074). Boundary segments reach roughly 1,753-2,175 km,
and 2-3 of the smallest candidate ranks are already flagged poorly resolved.
Sampling those arcs every 100 km cannot create missing 100 km geological detail.
This neither validates the low-resolution candidate nor proves that every higher
resolution candidate must fail. It supplies a concrete limitation of the tested
prior without hiding unresolved microplates or tuning against validation data.

## Evidence already available; do not repeat it as new work

`3cr1-complete-reference-checks.json` already checked **all 5,819 motion rows**,
including 766 within-model withheld rows. No motion issue exceeded the existing
source-derived component/speed/length rounding bounds. The maximum raw component
differences are 4.7744898507 and 1.9457507703 mm/a; those are not compared to the
old 12-row universal 0.2 mm/a excerpt allowance. The full report uses its declared
position/normal/pole rounding bounds and preserves unresolved source topology.

That is validation of prescribed Euler reconstruction against the source table,
not evidence for force-derived motion, historical evolution or geological realism.
Report SHA-256: `c02cee385b9e438cdb2bcfeb8a2eeac9d40c751ec155e0a9d3639b3db9ce69cd`.
Scoped-use restrictions remain in `3cr1-reference-use-assessment.json`.

Final new JSON SHA-256:
`972402d06fce4ce16e2d9103bed3f6f4ea9e32246e829183126bc8ba01fcbd3a`.
It retains input/source/runtime identities, all per-case and per-plate observations,
the explicit refusal and numerical checks. Raw capture location is retained in
the local workflow record rather than placing private paths in this public file.
An initial measurement-driver attempt used a nonexistent provenance attribute;
it was corrected to the atlas descriptor API before the successful results.

No R4.4 campaign, complete-world run, dependency installation or version bump.
No core numerical algorithm changed. The subsequent reference review is recorded
below; no long-time benchmark acceptance is claimed.

## Delegated reference review integrated

The returned research was checked against [Tosi et al., equations 2, 4, 19-21,
Table 2 and section 5.4](https://d-nb.info/1153363070/34), and
[ASPECT 3.0.0 equation 1](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/methods/basic-equations/index.html).
The retained warm-upward sign is supported. An author-confirmed erratum was not
obtained. Case-5a scaled dissipation remains an inference, not permission to
silently relabel the printed data. Case-5b documents nine same-equation
contributors, not the ten required by the frozen comparison policy. The exact
supplementary rows remain unavailable: the publisher's linked supplement returned
HTTP 403 on this review. No plot digitisation or replacement dataset was used.

Six focused regression tests were added, covering three short checks:

1. A continuum constant-viscosity solution with C=Ra*A/(4*eta*pi^2),
   u=(-C*sin(pi*x)*cos(pi*y), C*cos(pi*x)*sin(pi*y)), and the independent
   pressure Ra*(y-y^2/2)-Ra*A*cos(pi*x)*cos(pi*y)/(2*pi). The actual Stokes
   solver at 8/16/32 cells has the correct upward-warm sign and second-order
   velocity, pressure, work and dissipation errors. Analytic work is A*C/4;
   dissipation is eta*C^2*pi^2=Ra*work. This is a mechanical oracle, not a
   steady thermal or nonlinear-rheology benchmark.
2. Exact-decimal conditional dissipation envelopes are
   [1.3238855, 1.3697145] and [9.0923, 9.5877]. In all ten columns, the raw-Phi
   interpretation contradicts the periodic heat/work bound. The inference and
   automatic-acceptance refusal are both retained.
3. Synthetic ten-cycle minima 1..10 and maxima 21..30 yield 5.5 and 25.5,
   rather than global extrema 1 and 30. Fewer cycles and a drifting signal
   cannot establish maturity. Existing cycle averaging was already correct.

The review found and fixed one genuine comparator gap: `compare_table` previously
did not enforce the named ten-contributor inventory, and an empty reference map
could satisfy an empty `all(...)`. Empty tables, missing/replaced contributors,
changed contributor counts and nonfinite numeric reference values now fail closed.
No diagnostic, physical tolerance, equation, iteration budget or solver was changed.
The case JSON records the reviewed interpretation and remaining reference gap;
its changed bytes and the analyser change are new run bindings, not a repin of
old simulations. No acceptance with nine codes is authorised by this review.

**36 focused tests PASS in 0.854 s** (3.234 s captured process time including
imports). This includes six new tests and affected existing case/policy checks,
not a full simulation. Test selection: `test_convection_r4_4.PublishedCaseTests`,
`test_convection_r4_4.QuadratureTests.test_constant_viscosity_buoyancy_solution_and_work_sign`,
and `test_convection_workflow_r4_4.AnalysisPolicyTests`. Same Python environment
and one-thread native-library settings as above.

Required static source-map check also PASS: 13 selected maps, 41 paths.
Static tests: 30 PASS, one environment-limited symlink skip, 0.109 s. An initial
static-test invocation from the wrong working directory failed to import the
repository tools; rerunning from the documented repository root passed. The
scientific 36-test run had no failures or skips. Diff check PASS.

Focused log SHA-256:
`82118521cc18c0102bb79ff8e0d222d0d9251141aef6c0bcaef509232f8f7d2f`.
Reviewed analyser SHA-256:
`b59921262e55d696de7c4238e067f55b77b2e6d7c67a5c9188b58d29f921dc72`.
Case JSON SHA-256:
`6440321315c80e796822a362e6c92265f8835dd8f75e0fe04406da3fee22965d`.
No R4.4 campaign, full-suite rerun, commit or push. R4.4 remains held/incomplete;
the supported W01 described-state workflow does not depend on those open claims.

## Reference-policy v2 corrections — 22 September 2026

This supersedes the previous entry's universal ten-code rule and unresolved
case-5a comparison mapping; it does not rewrite the original printed data or
promote R4.4 to accepted. The owner's follow-up requested the remaining issues
be sorted. No new mature Atlas output was used to choose this correction.

Case 5a now uses an explicit **derived project interpretation**, Phi/Ra, while
retaining the original printed labels and numbers. No author erratum or original
case-5a output has been obtained. [ASPECT 3.0.0's Tosi postprocessor](https://raw.githubusercontent.com/geodynamics/aspect/v3.0.0/benchmarks/tosi_et_al_2015_gcubed/tosi.cc)
integrates raw dissipation and work separately, then explicitly divides the former
by 100 in their work-balance comparison. This establishes the physical conversion,
not the authors' extrema-labelling intent. Together with the ten-column periodic
heat/work contradiction above and the steady Table 2 convention, it supports
the adopted interpretation without claiming documentary certainty.

The analyser also had a wiring omission: periodic dissipation was calculated but
neither channel's extrema reached the comparison. Both now appear in the periodic
report, and the already-scaled channel is compared without another division.
Missing/changed mappings and removed diagnostic rows fail closed. A successful
comparison records the derived interpretation and `author_confirmed: false`.

Case 5b's contributor inventory is now the nine documented same-equation codes,
following [section 5.4 and Figures 7-8](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1002/2015GC005807).
Cases 1-5a retain all ten named contributors. MC3D is not an allowed replacement.
Exact Tables S14-S23 remain missing: publisher automated download was denied;
institutional alternatives did not provide the supplement; ordinary browser
navigation reached the supplement URL but yielded no readable/exportable PDF.
These are retrieval limitations, not proof that the file is unavailable to users.
Its exact filename is `ggge20762-sup-0001-2015GC005807-SupInfo.pdf` (Supporting
Information S1). The owner has been asked to attach it if accessible. No invented
rows, plot digitisation or flat-table bypass; yield, mesh, regime and ten-cycle
aggregation must be matched after acquisition. That ingestion/comparison remains
incomplete, not just a completed feature awaiting a long run.

Five new focused tests plus affected existing checks: **46 PASS in 0.577 s**,
1.356 s tool-observed process wall time including imports. No failures or skips.
The selection was run once, with NUMBA/OPENBLAS/OMP/MKL thread counts set to 1:

```text
python -I -B -c "import sys,unittest; sys.path[:0]=[TECTONICS_SRC,TECTONICS_TESTS]; s=unittest.defaultTestLoader.loadTestsFromNames(['test_convection_r4_4.PublishedCaseTests','test_convection_workflow_r4_4.AnalysisPolicyTests','test_convection_workflow_r4_4.SuiteAcceptanceTests']); r=unittest.TextTestRunner(verbosity=2).run(s); sys.exit(not r.wasSuccessful())"
```

`TECTONICS_SRC` and `TECTONICS_TESTS` stand for the actual local checkout paths
used in that command, omitted here to keep public evidence free of private paths.
Python/runtime versions are unchanged from the earlier evidence. Static source-map
check PASS (13 maps/41 paths); static tests 30 PASS and one environment-limited
symlink skip in 0.109 s. `git diff --check` PASS. Existing source-bound runs were
not repinned; specification/analyser changes require new bindings for future work.
No solver changes, long simulation, broad regression rerun, commit or push.

## Supplied case-5b supplement integrated — 22 September 2026

This resolves the previous entry's missing-source and ingestion/comparison
obligation. The owner supplied the original 30-page Supporting Information S1,
`ggge20762-sup-0001-2015GC005807-SupInfo.pdf`, DOI
`10.1002/2015GC005807`. Source PDF SHA-256:
`817c1ebe44a5f9be45aa716416137e1f9a9d39c5840cac60e5540dba6ac09842`.
The PDF itself is not redistributed in this repository.

`tools/import_tosi_case5b.py` extracts Tables S14-S23 on pages 21-30 with
pdfplumber, independently cross-checking every numerical pair and printed dash
using pypdf. The introduction on page 4 and all ten table pages were rendered
and visually inspected. Import development exposed missing pair commas and
variable token spacing; these are handled without changing any number, and
failed extraction attempts produced no output. Result: **10 tables, 626
reported min/max pairs**, plus explicit nulls and original yield/mesh coordinates.
The factual data retains printed decimal strings, including trailing zeros.
Extracted JSON SHA-256:
`af24ea6d458f6c1898e7c747568741ff9b5dae30cf1c5fe5321e015e470ae010`.

The source's font convention matters: upright digits mean steady; italic digits
mean periodic. Equality of the two printed values is not a substitute. For
example, GAIA's refined 100x100 column at yield 3.8 is upright/steady despite
its unequal printed pair `(4.6298, 4.6383)`. The finest entries of eight other
same-equation codes are periodic there. These source disagreements remain
visible and are not pooled into a larger envelope. MC3D's S23 is retained but
excluded because it uses a different constitutive approximation; ELEFANT is
not fabricated.

The declared selection is each code's finest published column at the exact
yield, with no fallback when it is absent. Some yields or grid entries genuinely
were not reported; these become `SOURCE_ABSENT`, not zero, an inferred value or
a missing-file excuse. The selected regime must have published support.
This is a finest-published comparison, **not an exact-grid error estimate**.
The independent Atlas mesh, timestep and nonlinear studies remain required;
their finest representatives must also agree on the physical regime. Periodic
comparison and adequacy now both include the minimum and maximum Nu values
averaged over ten complete cycles, while retaining existing signal and field
checks. The 0.5% envelope margin and all physical tolerances remain unchanged.

The loader verifies the exact reference bytes and source identity before use;
the runner binds the data and comparator in its source record. Missing targets,
altered bytes or deleted source rows cannot silently pass or rebind old runs.
An independent code review found and fixed the isolated runner's sibling-helper
import path; a subprocess regression covers that seam. Runtime comparison uses
only the 25,270-byte JSON and the standard library, not PDF libraries or downloads.

Verification was proportionate, not a campaign:

- **57 focused tests PASS in 0.932 s**, including 11 new reference/identity/regime
  checks and the affected existing published-case, analysis and suite-policy tests.
- **Two four-step driver checks PASS in 17.519 s**: a resumed result equals the
  uninterrupted result, and a short case-5b trajectory reaches the new analyser
  without being mislabelled mature or accepted. These are 4x4-cell tests, not
  mature convection validation. Total focused test time: **18.451 s / 59 PASS**.
- Static source map PASS (13 maps / 41 paths). Mandatory static tests: 30 PASS,
  one environment-limited symlink skip, 0.112 s. Diff whitespace check PASS.

The four focused classes were `PublishedCaseTests` in `test_convection_r4_4` and
`AnalysisPolicyTests`, `Case5bReferenceTests`, `SuiteAcceptanceTests` in
`test_convection_workflow_r4_4`. The additional driver methods were
`test_fresh_process_resume_matches_uninterrupted` and
`test_case5b_short_trajectory_audit_does_not_claim_acceptance`.
Python 3.12.14; NumPy 2.4.6; SciPy 1.17.1; Numba 0.65.1. Test processes used `-B`,
explicit source/test paths and NUMBA/OPENBLAS/OMP/MKL thread counts of 1;
driver subprocesses also used `-I`. Each selected check ran once successfully.

Reference preflight now has **no unresolved reference-data requirement**, but
the empty campaign still correctly reports zero accepted cases and
`INCOMPLETE_R4_4`. No mature long run, solver change, tolerance relaxation,
old-source repin, commit or push. Whole-W01 scientific acceptance is not asserted.

## Windows numerical-export readiness — 22 September 2026

Independent local work while the source-supplied physical validation runs in the
chat. The Windows numerical environment has no Matplotlib; an optional-package
resolution attempt did not complete and was cancelled without installation.
No solver dependency, installed package or runtime binding was changed.

The existing visualisation command now supports an explicit numerical-only path:

```text
python -I -B tectonics/tools/visual_convection_r4_4.py --run RUN_DIRECTORY --output NEW_EXPORT_DIRECTORY --raw-only
```

This preserves the authenticated run/state/source metadata and exports the actual
endpoint fields and sampled diagnostic history in losslessly compressed NPZ.
It requires no plotting library. The default plot path is retained; if optional
plotting imports are unavailable it now refuses clearly before reading the run
or creating an empty output directory. The default path's six plot calls and
unmodified input arrays were checked with a mock plotting interface, not an
actual Matplotlib render.

Raw exports are labelled `RAW_DATA_ONLY` / `NOT_RENDERED`. Suite visual acceptance
now requires `RAW_DATA_AND_PLOTS` and all six expected images plus the raw data.
An otherwise source-bound inspection claiming PASS cannot promote raw-only data
to visual acceptance. Renderer changes invalidate old visual receipts normally;
no receipt or trajectory is silently repinned.

Four focused checks **PASS in 6.662 s** (7.468 s process wall time): the two
`VisualExportTests`,
`DriverRecoveryTests.test_raw_visual_export_without_plot_library_is_not_visual_acceptance`,
and `SuiteAcceptanceTests.test_absent_visual_inspection_never_passes`, all in
`test_convection_workflow_r4_4`. The integration check used a tiny four-step 4x4
fixture in fresh Windows processes, verified array shapes, final time, mean
temperature, state identity and released reservations, and tested the visual
refusal. It did not repeat the chat's scientific cases or establish realism.
Native thread counts were 1; the scientific runtime is unchanged from above.

Static map PASS (13 maps / 41 paths); mandatory static tests 30 PASS and one
environment-limited symlink skip in 0.109 s; diff whitespace PASS. Actual graphical
rendering remains untested here because its optional dependency is absent.
The supplied chat baseline's physical source and case bytes are unchanged.
Only the renderer, suite visual gate, affected tests and this evidence differ;
the pending chat result must still be reviewed against its own archive manifest.

## Actual Windows graphical rendering — 22 September 2026

The optional plotting dependency is now enabled in the existing scientific
environment: Matplotlib 3.11.2 and its plotting dependencies. All pre-existing
package versions were constrained during installation, and the actual Numba
execution identity was identical before and after installation. No solver,
physical configuration, tolerance or saved-run binding changed. A pip download
cache write stalled; selecting a task-local writable cache resolved it.

Five focused visual checks passed in **13.313 s** on Windows 11 / Python 3.12.14,
including a real headless Agg export of a new 4x4, four-step run. This produced
all six PNGs (temperature, viscosity, pressure, velocity, heat flux history and
temperature history), lossless raw arrays and source/state-bound metadata.
All images decoded successfully and matched their recorded hashes. Every array
in plotted and raw-only exports matched exactly; reservations returned to zero.
Generating images alone still does not pass visual or scientific acceptance.
Temperature, velocity and heat-flux figures were directly inspected: readable,
unclipped and consistent with their displayed axes and coarse sampled data.

The profile is the preceding four checks plus
`DriverRecoveryTests.test_graphical_export_matches_raw_arrays_and_remains_unaccepted`.
The new integration test skips explicitly without the optional visual dependency;
the recorded Windows run had **no skips**. Display metadata now correctly says
nearest-neighbour display of original cell arrays, not one screen pixel per cell.

Use the existing default command to generate plots, with a NEW output directory:

```text
python -I -B tectonics/tools/visual_convection_r4_4.py --run RUN_DIRECTORY --output NEW_PLOT_DIRECTORY
```

This is rendering/software verification, not a mature Tosi benchmark or a
terrain-realism claim. The latest exporter changes have not yet been executed
on Linux; no Linux environment is installed on the Windows host. The existing
chat's older physics snapshot must not be mistaken for this updated source.
The updated four-file source delta and portable five-check driver were supplied
to that existing chat for a separate Linux execution; the result is pending.
Static map PASS (13 maps / 41 paths), static tests 30 PASS / one Windows symlink
skip in 0.107 s, and whitespace check PASS.

## Physical-validation corrections — 22 September 2026

The two defects identified in the bounded chat review are corrected in local
source. This is implementation plus focused Windows verification, not acceptance
of all geology, nonlinear convection or generated terrain. The chat's original
result ZIP was unavailable locally; the controls below are independent
reconstructions, not an authenticated replay of that archive.

### Hydrostatic cooling

The constant-viscosity MINRES solution now receives a compatible MAC solenoidal
reconstruction when its velocity-relative divergence exceeds four binary64 eps.
This is an internal correction trigger, not an acceptance tolerance. Already
compatible flows avoid extra FFTs. Cross modes retain their solenoidal amplitude;
axis-only compressible modes are removed, and p_new = p_old - Dv preserves the
discrete momentum equation. No absolute velocity cutoff is used. The explicit
sparse-direct reference, variable-viscosity solver and every published-SI and
transport acceptance gate are unchanged. Final rounding still has to pass them.
The method uses bounded O(N) scratch inside the existing reservation.

The previously refused cooling control now completes: a 20 km by 10 km rectangle,
constant properties, fixed 1300/300 K bottom/top temperatures, and an initial
80 K sine perturbation on the linear profile. The independent oracle integrates
the continuum sine mode over each cell and decays it with diffusivity 1e-6 m2/s.
Duration is 5e12 simulated seconds, not wall-clock duration; four coupled steps
are used, plus an eight-step check at the finest grid.

| Grid | RMS temperature error (K) | Maximum error (K) |
| --- | ---: | ---: |
| 16 x 8 | 0.2171761204 | 0.3012319325 |
| 32 x 16 | 0.0546380835 | 0.0768978429 |
| 64 x 32 | 0.0136810565 | 0.0193246302 |

Observed spatial orders: 1.9908867 and 1.9977272. Doubling the step count changes
the final temperature by at most 2.27374e-13 K. All initial states are unchanged,
composition remains zero and reservations return to zero. In the initial focused
run these four controls took 1.616, 0.766, 0.858 and 1.336 s respectively; first
use includes preparation. These are bounded execution receipts, not speedup
measurements, and say nothing about mature R4.4 runtime.

New regressions also cover momentum/gauge preservation, nonseparable pressure
gradients, tiny genuine circulation, and continued refusal of tiny but genuinely
compressible velocity. Two older tests incorrectly demanded bit-exact *normal*
MINRES values: the unchanged raw Windows/SciPy solve itself produces two ULP of
rounding, and the correction leaves that vector bit-identical. Those tests now
compare the independent analytic value within two ULP and, where applicable,
momentum residual within four eps. Exact-subnormal-output tests, underflow
refusals and production acceptance thresholds remain unchanged.

### Cohort total-thickness consistency

`cohort-partial-thickness-regional-v2` jointly limits component slopes against
the scalar total slope at both SSP-RK2 stages. Nonnegative donor traces sum to
the scalar total trace within roundoff. Each component retains its own shared
conservative face flux; no updated fields, fractions or fluxes are normalised
afterwards. Single-cohort and upwind arithmetic are retained. The native and
independent reference paths use the same declared law; workspace admission now
accounts for simultaneous component stages. ALE/remap are separate and unchanged.
See the [full mathematical contract](../docs/FOUNDATIONS.md#w02-cohorts).

For the reconstructed 3 m interval, total thickness 4 m, two complementary
cohorts, speed 1 m/s, duration 0.5 s and Courant 0.4:

| Cells | Old final relative total-depth error | Corrected final error | Corrected largest transient error |
| --- | ---: | ---: | ---: |
| 24 | 2.9171800% | 2.22e-16 | 2.22e-16 |
| 96 | 1.4610497% | 3.33e-16 | 4.44e-16 |

Old largest transient error was 6.6366046% at both resolutions. Final individual
volumes remain 13 and 11 m3 for the specified 2 m width, within roundoff.
The 24-cell first-use observation was 3.969 s before / 5.554 s after, including
JIT compilation; the warm 96-cell observation was 7.303 / 7.843 ms. This is an
accuracy correction with a small measured warm cost, not a claimed speedup or a
statistically repeated benchmark.

Material tests: 86 PASS in 13.658 s, followed by two affected native-build/source
identity checks PASS in 6.345 s after including the new compiled helper in the
assembly identity. They cover both-stage traces, sparse/zero cohorts, variable
totals, reverse inflow, two/three-cohort constant totals, conservation, positivity,
smooth refinement, reference/native parity and v1/v2 restoration separation.

Source/context identities change normally. Old histories and evidence are not
silently repinned or promoted. Corrected-source Linux execution remains untested
locally; the earlier chat graphics check cannot establish it. No full campaign,
dependency change, commit or push is part of this correction.

### Focused verification record

Windows runtime and single-thread settings are unchanged from the preceding
section. With `tectonics/src` and `tectonics/tests` on `PYTHONPATH`:

```text
python -B -m unittest test_material_transport -q
python -B -m unittest test_stokes_review_r4_1.PublishedAccuracyTests test_hydrostatic_transport test_w01_workflow -q
```

The second command passed **42 tests in 50.102 s**, including coupled cooling,
pressure-dominated/tiny-flow regressions, preserved publication failures, linked
workflow restoration, source-change refusal and warm-cache kernel avoidance.
After tightening the two analytic-oracle assertions to actual ULP distance, those
two affected tests passed again in **0.396 s**. Earlier mechanics regression:
55 PASS in 7.129 s. A combined 136-test iteration found only the two pre-existing
normal-value exact-equality assumptions discussed above; the other 134 passed.
That complete set was not rerun after their focused correction.

Required source/tool checks: `python -B tools/check_coding_safety.py` PASS
(13 maps / 41 paths); `python -B -m unittest discover -s tests -p
test_coding_safety.py -q` ran 31 in 0.108 s, 30 PASS and one Windows symlink skip.
`git diff --check` PASS; only the pre-existing CURRENT_STATE line-ending advisory.
No acceptance tolerance, timestep ceiling or held simulation scope was changed.

## Fresh bounded physical acceptance rerun — 22 September 2026

After the numerical corrections, the owner authorised a fresh local rerun of the
three bounded physical controls, not the long R4.4 campaign. An explicit contract
was saved before execution; the existing source inventory and harness hashes
matched afterwards. Three modest resolutions per case and focused timestep
controls completed on Windows in **12.249925 s**, including first-use compilation,
case snapshot I/O, plots and final source verification, excluding imports/setup.
No production code, dependency, scientific tolerance or historical binding changed.

| Case | Limited acceptance | Quantitative witness |
| --- | --- | --- |
| Prescribed variable-viscosity steady mechanics | PASS WITHIN STATED SCOPE | Velocity/pressure error refinement ratios 4.005–4.164, inside the existing 3.7–4.5 gate; continuum-work error 0.970146% / 0.241899% / 0.060435%. |
| Hydrostatic finite-time cooling | PASS WITHIN STATED SCOPE | Three grids reach 5e12 s; finest maximum temperature error 0.01932463 K; timestep-halving difference 2.27374e-13 K. Velocity is exactly zero on these sampled grids, and maximum base-grid heat-ledger relative residual is 4.06e-17. |
| Nonnegative conservative material transport | PASS WITHIN STATED SCOPE | Final continuum volumes 13/11 m3 pass the original 1e-12 relative/absolute gate; maximum volume error 1.78e-15 m3. Constant total-thickness relative deviation at most 5.55e-16, including timestep control. |

Material **shape accuracy remains descriptive**, not a general sharp-front pass.
Mean per-cohort error decreases 0.164554 / 0.099247 / 0.059953 m at 24/48/96 cells
(observed orders 0.729/0.727); timestep control gives 0.058679 m. Maximum cellwise
errors at the discontinuities increase 1.049281 / 1.156699 / 1.248932 m. Domain-mean
convergence does not establish pointwise accuracy at a jump. No discontinuous-case
scientific shape bound exists in the retained contract, and the smooth-field
second-order threshold was not misapplied. Actual plots visibly retain interface
smearing; no altered data or hidden total-depth distortion is accepted.

The real-output plot was inspected: correct manufactured circulation sign,
cooling matching the analytic profile, broadening material fronts with flat total
thickness. Raw plotted arrays, per-grid metrics, heat ledgers, source manifest and
21 snapshots are retained locally. The existing lossless Zstandard store measured
299,008 bytes and restored final snapshot identities. Peak admitted reservation
was 75,992,824 bytes, not measured RSS; final reservation was zero. A harmless
font-cache permission warning did not prevent Matplotlib rendering.

This is independent analytic/numerical evidence on Windows, not empirical
geological validation or an authenticated replay of the unavailable chat ZIP.
Corrected-source Linux execution remains unverified. Whole-W01 generated
geological realism, mature R4.4 convection, terrain and world-scale claims are
not passed by these controls. Previously established unrelated evidence and holds
remain unchanged; no full-suite or long campaign was run.
