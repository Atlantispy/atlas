# W04 step 3 — finite-region implementation and bounded evidence

22 September 2026. WORKING NON-CANON, local unreleased `remake` work.
No commit/push, installation, checkpoint repin, full terrain or R4.4 run.

## Result and boundary

`finite_flexure.py` adds cell-integrated continuous 1D plate response, explicit
continuing-plate or physical clamped/free ends, analytic derivatives, prepared
linear FFT and a conditioned four-coefficient physical-end correction.
`W04ExteriorLoads` and the extended `PreparedW04Support` connect actual W03
reference/current states to explicit adjacent cells and far-halfline loads.
Reference/current omitted-load uncertainties are combined into conditional
displacement, slope and curvature bounds. Region-error and existing validity
limits refuse unsuitable inputs; no periodic derivatives are used on this route.

Source/frame/time/datum/order, exclusive thermal ownership, closed water accounts,
total-reference output, immutability, current runtime/source guards and existing
verified cache/recovery remain. Full halo outputs are compacted before returning
the interior. No new growing history or duplicate storage system was introduced.

Supported scope: stationary planar 1D, uniform D/K, small-deflection thin-plate
projection. Transverse loading is invariant, not a finite-width 2D plate. True
physical ends require an authored boundary choice. Variable rigidity, arbitrary
tractions, ill-conditioned short physical-plate bases, 2D/spherical geometry,
subcell-extrema certification and coupled material/water feedback remain outside
this increment. See the [complete contract and sources](../docs/W04_FINITE_REGIONS.md).

## Checks actually run

Windows 11, Python 3.12.14, NumPy 2.4.6; existing scientific environment,
one BLAS/OMP/Numba thread, `PYTHONPATH=tectonics/src;tectonics/tests`, Python `-B`.

39 distinct focused tests passed:

- 11 `test_w04_finite_region` controls: independent scalar Green quadrature,
  finite rectangular load, signed forebulge, direct cell sums versus FFT,
  uniform/unequal half-lines, source-cell subdivision, zero-load crop enlargement,
  coordinate translation, real omitted-strip response versus all three analytic
  error bounds, free and mixed ends, independent clamped closed form, numerical
  range, refusal, immutability and resource admission.
- 6 `test_w04_regional_workflow` controls: actual W03 connection, halo response,
  explicit exterior thermal continuation, total-reference identity, existing cache
  hits and exact restoration, conditional displacement/derivative gates, genuine
  free/clamped edges, source/time/halo mismatch refusal, cancellation and cleanup.
- 13 retained `test_w04_workflow` periodic integration controls plus 9
  `test_execution_reuse.IdentityTests`: 22 PASS in 20.624 s. This affected-route
  check preceded the final fixes confined to new exterior capture/finite response.

Independent initial numerical review ran 10 tests, PASS in 0.009 s. Initial six
regional integration tests passed in 11.289 s. Review then caught and fixed:

1. Returning a small view could retain the full halo response beyond its accounted
   lifetime. The interior is now detached within the enlarged reservation;
   exterior capture/hashing also accounts both buffers and avoids concatenation.
2. `q/(2*K)` could silently vanish when finite K exceeded half the float limit.
   Safe scaling and an independent q=K=1e308 half-line regression now preserve
   the expected 0.5 m boundary displacement.

After these corrections, `python -B -m unittest test_w04_finite_region
test_w04_regional_workflow -q` ran all 17 new-route controls: PASS in 11.494 s.
No unrelated full suite was rerun. Linux execution is not claimed.

`python -B tools/check_coding_safety.py`: PASS, 13 maps/41 paths.
`python -B -m unittest discover -s tests -p test_coding_safety.py -q`: 30 PASS,
one Windows symlink skip, 0.108 s. `git diff --check`: PASS (existing CRLF warning).

## Matched performance measurement

Reproduce with `python -B tectonics/tools/benchmark_w04_finite_region.py
--output tectonics/evidence/w04-finite-timing.json` from the repository root.

2,048 cells over 400 km, signed synthetic pressure, 12 solves per repetition,
three alternating direct/FFT repetitions after warm comparison. Both methods
reuse the same exact cell-integrated kernel and return all centre/face
displacements plus three derivatives. Direct baseline is ordinary linear
convolution, not deliberately repeated kernel construction. Input validation,
budget admission and immutable output are included. Setup is measured separately.

| Metric | Direct cell superposition | Prepared linear FFT |
| --- | ---: | ---: |
| Median, 12 solves | 0.101421499974 s | 0.010749100009 s |
| Per solve | 0.008451791665 s | 0.000895758334 s |
| Separate setup | 0.001285999897 s | 0.001994500053 s |

Saved **0.090672399965 s per 12 solves**, **89.40155686%**, **9.43535x** faster.
Per-solve saving is 0.007556033330 s. Prepared transform storage is 524,352 bytes.
Maximum displacement disagreement was 1.82146e-17 m; all derivatives passed the
predeclared per-component `5e-13 * max(abs(direct response))` bound. No tolerance
was weakened. The first benchmark attempt hit a NumPy assertion-format error
when given an array-valued tolerance; it was replaced by the same explicit
per-component inequality before final measurement.

This is a candidate-algorithm comparison for the **new finite-region kernel**, not
an old-release or whole-generator gain. No workers/cache hits/W03 evolution/source
checks/full terrain are included. The provisional pre-review timing was superseded
by the final code's raw [JSON](w04-finite-timing.json).

## Scientific sources checked

- [Wickert (2016), gFlex](https://gmd.copernicus.org/articles/9/997/2016/): full-text
  equations/analytical versus FD methods and physical/continuous boundary sections.
- [gFlex theory/numerics](https://gflex.readthedocs.io/en/latest/theory_and_numerics.html):
  independent review of the analytical, FD/FFT and flexural-length documentation.
- [SciPy convolution documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.fftconvolve.html):
  full linear convolution and direct/FFT performance behaviour.

Paper/docs only; no external gFlex execution/source audit or field calibration.
The exact positive-down normalisation is independently tested, not copied from
an ambiguous line-load/pressure convention. Numerical verification is not full
terrain realism or general assembled W04 acceptance.

## Final source identities

- `src/atlas_tectonics/finite_flexure.py`:
  `b29bae72b5e587c846a5735e100fd2a5d5ada07e38cffcd3cc7005c6cacaba66`
- `src/atlas_tectonics/w04_workflow.py`:
  `9b71a5136e610f9b4bd64353599fe45334530591893ee397ec3f3384fb163666`
- `src/atlas_tectonics/reuse.py`:
  `2714c234c9ed8c349412a08fae11def4840fd68efe829257f9c0f6fd0b8f69cc`
- `evidence/w04-finite-timing.json`:
  `c6c3840ea05a9f03a87552a848577dc59f6f4d65f005d8f60f44f972333acc64`

The new module participates in loaded-source identity. Old states/receipts are
not repinned. Next: step 4 variable rigidity, then general assembled acceptance.
