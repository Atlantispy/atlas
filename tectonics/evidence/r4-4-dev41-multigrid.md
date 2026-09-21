# Dev41: strict publication refinement and selective velocity multigrid

2026-09-21. WORKING NON-CANON; R4.4/R4 IN_PROGRESS. AI-assisted implementation
reviewed locally. Code delivery, numerical checks and scientific acceptance are
separate. Base: remake commit `40e30e92d7856856b7aa3b4511d8d32b3790fcb8`.
No full campaign, physical acceptance, historical rebinding or remote push.

## What changed

1. A valid adaptive strict image can lose its residual margin when converted to
   and back from physical SI fields. Previously this always refused. Now only
   that representation failure asks the existing nonlinear loop for another
   strict solve of the actual returned vector. Both attempts are recorded;
   Anderson differences are cleared. The original iteration ceiling, residual
   target, nonlinear-law, divergence, gauge and work gates are unchanged.
   Invalid pre-publication images, failed GMRES and nonfinite values still refuse.
2. The velocity preconditioner can use a fixed linear geometric V-cycle with
   full coupled stress, Galerkin coarsening, degree-four Chebyshev pre/post
   smoothing and a small direct coarse solve. Normal wall velocity remains zero;
   tangential interpolation respects free-slip walls. Pressure approximation,
   physical equations and GMRES tolerances are unchanged. No nested variable
   inner tolerance, new package or silent solver fallback is used.
3. Geometry transfers are retained on the prepared plan. Numerical hierarchies
   rebuild on coefficient change unless the existing explicit request-local
   reuse policy admits a helper reuse. Current physical coefficients and pressure
   remain current; each helper is fixed during GMRES. Exact reuse also checks
   helper kind. Retained/transient admission is conservative, not a peak-RAM cap.
4. Default `auto` chooses GMG for isotropic square power-of-two supports >=128x128
   with Tosi-linear, or Tosi-plastic plus Anderson/adaptive-inner/guarded-reuse.
   Other cases retain ILU. This is a deterministic measured-workload heuristic,
   not a guarantee for every viscosity field, machine or larger mesh. `ilu` and
   `gmg` can be explicitly selected; unsupported explicit GMG refuses.
5. Policy and loaded helper functions are source-bound. New policy field and
   generic preconditioner-reuse method v2 change identities. Old checkpoints and
   older canonical policy records are not silently upgraded or rebound.

## Measured coupled timings

Windows, Python 3.12.14, NumPy 2.4.6, SciPy 1.17.1, Numba 0.65.1. One native
numerical thread; no concurrent numerical worker. Both candidates have the same
publication repair, original convergence limits, Anderson, adaptive inner and
four-use guarded reuse. Plan creation, advancement and close are timed; warm-up
compilation, input construction, archive writing and final field comparisons
are excluded. ILU/GMG order alternates. Every repetition starts a NEW input;
there is no rebinding of historical execution.

| Workload | Samples per method | ILU median | GMG median | Saved | Saved % |
| --- | ---: | ---: | ---: | ---: | ---: |
| Case 1 initial, 128x128, two steps | 3 | 2.060485 s | 1.377673 s | 0.682812 s | 33.138% |
| Case 2 developed input, 64x64, two steps | 3 | 5.060393 s | 4.853001 s | 0.207392 s | 4.098% |
| Case 2 developed input, 128x128, one step | 2 | 26.134182 s | 18.732475 s | 7.401708 s | 28.322% |

Ranges, not confidence intervals: case 1 128 ILU 2.033247–2.183173 s, GMG
1.334094–1.416143 s; case 2 64 ILU 4.977575–5.140371 s, GMG 4.809075–4.924622 s;
case 2 128 ILU 26.001997–26.266368 s, GMG 18.021319–19.443630 s. Two-sample
medians are the mean of the two observations; no statistical generalisation is
claimed. The earlier case-1 64 screening included first-use thermal compilation
in its first sample and overlapped thereafter; it is not a qualified speed claim.

Maximum temperature differences across each reported comparison were respectively
4.4408921e-16, 6.6613381e-16 and 2.2204461e-16 K; composition remained exactly zero.
Original per-stage strict and physical gates passed, and all work reservations
were released. GMG sometimes required MORE nonlinear iterations: case 2 128 used
144/149 per stage versus ILU 120/128, but remained faster overall. Iteration count
alone is therefore not the selection metric. This does not establish mature-run
trajectory equivalence, model accuracy or whole-generator savings.

The developed field is the retained 16x16 step-901 comparison fixture, reintegrated
onto finer supports with the existing boundary-compatible temperature helper.
It is new numerical input, not evolved fine-grid evidence or historical restart.
dt=1e-7 for these short coupled trials. Frozen-system pressure alternatives remain
comparison-only: small gains in one setting did not justify a blanket replacement.

## Publication regression and verification

The previously refused case-2 128 endpoint now passes in 14.076966 s: 123 nonlinear
iterations, including one recorded conversion refinement. First attempt internal
residual 4.56533324e-11, returned 9.91757609e-11; unchanged target 7.62747947e-11.
Final returned residual 7.49305771e-11 passes that same target. This is successful
completion, not a speedup against the earlier failed solve.

Final focused selection: **34 tests passed in 26.346 s**. Coverage: eight GMG
tests (wall transfers, fixed linearity, separately assembled direct agreement,
independent NumPy residual, coefficient/geometry reuse, selection, admission,
cancellation, live source mutation, and fresh-process CLI/restart/changed-policy
refusal); three publication-refinement tests; adaptive mechanical tests; four
affected coupling tests; three guarded-reuse tests. The CLI check confirmed
uninterrupted and restarted states/arrays match exactly with explicit GMG.

Command from the local candidate root, with source/tests added to `sys.path`:

```python
names = [
    'test_velocity_multigrid_r4_4',
    'test_adaptive_publication_refinement_r4_4',
    'test_adaptive_inner_r4_4.MechanicalTests',
    'test_adaptive_inner_r4_4.CouplingTests.test_actual_stage_tolerances_survive_and_tampering_is_refused',
    'test_adaptive_inner_r4_4.CouplingTests.test_changed_policy_continuation_refused',
    'test_adaptive_inner_r4_4.CouplingTests.test_two_stages_and_endpoint_certified_with_seed_roundtrip',
    'test_adaptive_inner_r4_4.CouplingTests.test_second_stage_cancellation_preserves_input_and_seed',
    'test_preconditioner_reuse_r4_4.ReuseTests.test_changed_helper_keeps_current_operator',
    'test_preconditioner_reuse_r4_4.ReuseTests.test_age_rebuild',
    'test_preconditioner_reuse_r4_4.ReuseTests.test_no_cross_request_approximation',
]
unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromNames(names))
```

Independent static review caught a missing loaded-callable identity entry for the
new helper; it was fixed before final checks. The helper keeps SciPy optional at
module import so unrelated reference-only contexts retain their dependency
boundary; actual variable-mechanics preparation still requires SciPy.

Raw local evidence and reproducible driver are retained by Generator Engineering
under `stokes-preconditioner-compare/`: `coupled_trial.py`, `publication-fixed-128`,
`coupled-case1-128`, `coupled-case2-64`, `coupled-case2-128`. Each timing run records
source hashes, input hash, environment, method/order, timings and stage diagnostics.
Public repo does not receive private fixture data or local coordination records.
Timings used forced ILU/GMG branches before final automatic rule tightening; those
numerical branches are unchanged. Final focused checks cover the tightened rule.

## Algorithm sources and limits

- [Clevenger and Heister: AMG/GMG variable-viscosity Stokes comparison](https://arxiv.org/abs/1907.06696)
  informed the coupled velocity hierarchy and polynomial smoothing. Atlas's
  assembled MAC implementation is not their matrix-free finite-element solver.
- [Rudi, Stadler and Ghattas: weighted BFBT](https://arxiv.org/abs/1607.03936)
  informed the earlier pressure comparison, not a production pressure change.
- [PETSc GMRES/FGMRES distinction](https://petsc.org/release/manualpages/KSP/KSPFGMRES/)
  underlies keeping each preconditioner application fixed and linear.

No full test suite, mature R4.4 run, physical certification, source migration,
automatic remote publishing or full-world simulation was performed.

Delivery verification: all 12 selected files byte-matched the tested candidate;
`git diff --check` and `tools/check_coding_safety.py` passed (13 maps/41 paths).
The fresh-process GMG CLI/restart/policy-refusal test was repeated in the actual
GitHub checkout and passed in 13.016 s (repeat, not a 35th distinct test). Changes
are local on `remake`, uncommitted and unpushed, package version 0.1.0.dev41.
