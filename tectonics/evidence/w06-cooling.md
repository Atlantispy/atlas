# W06 Step 3 evidence — cooling and inherited margins

Status: WORKING NON-CANON; PASS for the declared bounded increment, 22 September
2026. [Model/API](../docs/W06_COOLING.md); frozen [design](../docs/W06_SPREADING.md)
SHA256 `fc52728845d62bfd575a3d22e6a46796d3d36120b8ab1f65668379b38e0be285`.
No commit/push, full-W06, Linux-execution, R4.4 or empirical terrain claim.

## Focused verification

Thirty new focused checks have passing evidence, plus nine existing shared-source
identity checks. Existing checks were reused when a later change did not affect
their scope; no whole-generator regression was repeated.

| Area | Evidence |
| --- | --- |
| Thermal integrals | Six tests. Initial six-test run: five passed, one under-resolved independent quadrature failed (0.168 s). Adding geometric diffusion-scale reference cuts resolved its missed shallow tail; both affected reference tests passed in 0.194 s. Production kernel and frozen tolerances unchanged. |
| Assembled ocean | Twelve tests passed in 28.390 s. Independent depth-and-age integration, every occupied crop cell/centre on 1000/500/250 m grids, four main outputs and partial-cell output, clipped exports at actual exit age, constant ridge migration, 32/64/128 partition equality, finite stocks, oldest-column validity, cancellation, source and resource guards. |
| Inherited margin | Initial ten-test run: nine passed, one reference-rounding assertion failed (8.298 s). Its 3.41e-13 K difference exceeded an over-tight 3e-13 K test-only allowance; allowance corrected to 1e-11 K and that test passed (0.221 s). Added mixed-profile/nonzero-epoch/unknown-history and young-work-cap checks passed (0.674 / 0.320 s). Twelve tests covered. Frozen 1e-3 K acceptance threshold unchanged. |
| Shared protection | Nine IdentityTests passed in 1.592 s; source inventory and public imports include all three new production modules. |

Required static safety inspection: 13 selected maps / 41 paths PASS. Its dedicated
tests: 30 PASS and one expected Windows symlink skip (31 reported, 0.108 s).
Scoped tracked diff whitespace, new-file whitespace, JSON parsing and local links
in the two new documents PASS. These static checks do not claim general physics
coverage. The final edits after this check only record these results and clarify
one unit-description sentence; no numerical code changed.

The independent ocean reference imports no production thermal routine. It uses
scalar image/Fourier temperature, nested adaptive depth/age quadrature and separate
birth-time integration of resident/exported enthalpy. Exported parcels stop cooling
in the regional account at exit. A tightened quadrature control checks reference
resolution. The margin reference independently integrates the initial profile's
sine coefficients and evolved depth means. Tests include exact initial fields,
very young response, mature limits, heat closure, fixed geometry/source identities,
finite water and whole-trajectory validity.

The two initial numerical-reference issues above are retained, not concealed as
clean first runs. Neither required production-error masking or weakened scientific
acceptance gates. Short command-discovery mistakes (one wrong working directory
and one oversized document read) were corrected without changing code/results.

## Measurements

Windows, Python 3.12.14, NumPy 2.4.6, SciPy 1.17.1; numerical threads set to one.
Three repetitions per comparison; medians below. No process pool or weakened source
check. [Ocean raw measurements, accuracy and all package hashes](w06-cooling-timing.json).
[Margin reuse measurements and source binding](w06-margin-timing.json).

| Measured workload | Baseline | Implemented | Saved |
| --- | ---: | ---: | ---: |
| Matched 256-cell ocean output at 20 Myr: phase means, centres, coverage, support, heat/water accounts | 0.3553722 s, independent scalar quadrature | 0.0949111 s | 0.2604611 s / 73.2925% (3.7443x) |
| Three inherited-margin outputs, including source context/preparation | 0.6438855 s, prepare each output | 0.3106270 s, one prepared plan | 0.3332585 s / 51.7574% |
| Separate 4000-cell ocean sequence at 0/5/10/20 Myr, including fresh context/preparation/closure | Not measured | 0.5856365 s | No comparative saving claimed |
| Same-state source-validated ocean request | Not measured | 0.0223781 s | No comparative saving claimed |

The ocean comparison regenerates identical field/account subsets; neither side
looks up a saved result. The production side also computes birth/mass history and
validates identities. It excludes preparation only in the matched-output comparison;
the separate larger measurement includes setup. Do not extrapolate 73.29% to that
larger sequence or the whole generator. The margin comparison includes new execution
contexts and preparation, excludes imports/fixture creation/equality checks, and
produced identical IDs, means and heat for all nine compared outputs.

Maximum matched ocean errors: phase temperature `1.137e-12 K`, support
`4.406e-13 m`, heat-account error `1.194e-16` normalised, water account
`1.193e-7 m3`. Production heat closure residual `-1.869e-17` normalised. These
are numerical differences for the synthetic model, not physical prediction accuracy.
Accounted peak reservation `35,223,008 bytes`, final zero, within the 128 MiB
admission envelope (includes 16 MiB caller allowance); this is not measured RSS.

## Reproduction

From the Atlas root, using an environment with the recorded dependencies:

```powershell
$env:PYTHONPATH='tectonics/src;tectonics/tests'
$env:OPENBLAS_NUM_THREADS='1'
$env:OMP_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
$env:NUMBA_NUM_THREADS='1'
python -B -m unittest test_w06_thermal_integrals test_w06_spreading_cooling test_w06_margin_cooling -v
python -B tectonics/tools/benchmark_w06_cooling.py --output w06-cooling-timing.json
python -B tectonics/tools/benchmark_w06_margin.py
```

These are reproduction commands, not a claim that all component tests were rerun
together after the focused corrections. On POSIX use `:` in PYTHONPATH instead of
`;`. Current execution evidence is Windows only. The copied margin timing script
is byte-identical to the measured script; its only dependency on launch setup is
the documented PYTHONPATH. It does not install dependencies or modify production.

Research actually checked and access limits are listed in the
[model document](../docs/W06_COOLING.md#research-and-software-actually-checked).
Next authorised increment is changing motion/plate histories, not a large run.
