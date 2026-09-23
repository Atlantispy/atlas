# W06 Step 4 evidence — changing motion histories

22 September 2026. WORKING NON-CANON. Step 4 implemented and checked.
[Model and API](../docs/W06_HISTORIES.md).
The frozen [Step 1 design](../docs/W06_SPREADING.md) remains unchanged at SHA256
`fc52728845d62bfd575a3d22e6a46796d3d36120b8ab1f65668379b38e0be285`.

## Numerical joins

The independent scalar reference integrates each parcel's piecewise velocity
history, then solves its first boundary crossing chronologically. It does not
import production geometry or thermal routines. Phase temperature and cumulative
heat use the retained independent adaptive depth/age reference. Full birth-age
intervals, not mean ages, reach both implementations.

Geometry: eight focused methods have passing evidence. The initial run had six
passes and two test-fixture failures in 15.677 s: an approximately symmetric
`linspace` centre was slightly off the ridge (giving a valid 0.0625 s age rather
than exact zero); a mocked production export function correctly triggered source
protection. The fixtures were corrected to an exactly symmetric grid and a genuine
bounded-admission check. Both affected methods then passed in 0.669 s. No production
change or scientific tolerance relaxation was needed after that run.

Coverage includes exact frozen-switch geometry (900 km created, 850 km represented,
50 km right export), full independent cell intersections and centre ages, mass
accounts, first-exit time/age/owner, stopping, semantic-boundary sampling, requested
output partition independence, partial cells and immutable projections. Feed,
cancellation, source/content, budget and 256 request/event guards are exercised.
The 256-event no-export case fits the 128 MiB admission budget after skipping
unneeded quadratic export work. This is admission accounting, not measured RSS.

Nine shared `test_execution_reuse.IdentityTests` passed in 1.736 s with both new
production modules registered. Existing W06.3 kernels were not changed; their
full suites were not repeated. A targeted constant-history reduction comparison
belongs to the new assembled checks.

Twelve assembled thermal-history tests passed in 42.364 s. They cover the frozen
switch and stop on three grids, full independent crop means/centres and accounts,
0/5/10/20 Myr and partial outputs, before/after reassignment, constant-history
reduction to Step 3, true pre-event ages, stopping/restarting at shared-face centres,
event boundaries +/-1 s, 64/128 output partitions, clipped/enlarged domains, finite
heat/water allowances, cancellation and foreign/live-source/resource guards.
The restart check preserves the genuine missing birth-age interval instead of
resetting older crust or averaging the discontinuity. No production changes were
made after these passing checks.

Final static safety check: PASS, 13 selected source maps and 41 required paths.
Its focused test suite: 30 passed and one environment-dependent Windows symlink
test skipped (31 total, 0.112 s). This is static wiring evidence, not additional
scientific simulation coverage.

## Measured performance

[Raw timing and source bindings](w06-history-timing.json): Windows 11, Python
3.12.14, NumPy 2.4.6, SciPy 1.17.1; numeric thread counts one. Three alternating
repetitions after accuracy checks; medians below. These compare separate scopes
and must not be added together or treated as whole-generator speedups.

| Comparison | Baseline | Implemented | Time saved | Reduction |
| --- | ---: | ---: | ---: | ---: |
| Matched 256-cell output against independent scalar history/thermal integration | 0.646369 s | 0.101052 s | 0.545317 s | 84.37% |
| Four 4000-cell outputs, fresh preparation per output versus one reused preparation; setup included | 1.273474 s | 0.658347 s | 0.615127 s | 48.30% |

An identical-endpoint request returns the same immutable state in median
0.023533 s with live source checks retained. Preparation reuse produced exactly
equal numerical fields, centre ages and accounts. Matched-reference maximum
phase-mean temperature error was 2.05e-12 K, mean subsidence error 6.75e-13 m,
centre-age error zero and normalised heat-account error 4.24e-17. Absolute
cumulative heat-field disagreement was 0.046875 J/m2; independent account
residual was 9.35e-17 relative to the birth heat. No tolerance was relaxed.

Peak accounted reservation was 45,256,928 bytes (43.16 MiB), including the
24 MiB caller allowance, under the 128 MiB admission budget. All reservations
were released; source hashes matched before/after. This is accounted memory,
not a process RSS measurement. The full source inventory is in the timing JSON.

## Research and reproduction

The [model document](../docs/W06_HISTORIES.md#papers-and-existing-software-actually-checked)
lists the selected TracTec paper sections and official pyGPlates documentation
actually inspected, and how they influenced implementation. External simulators
were not installed or executed.

From the Atlas root in the existing Python 3.12/NumPy/SciPy environment:

```powershell
$env:PYTHONPATH='tectonics/src;tectonics/tests'
$env:OPENBLAS_NUM_THREADS='1'
$env:OMP_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
$env:NUMBA_NUM_THREADS='1'
python -B -m unittest test_w06_history_geometry test_w06_history_cooling -v
python -B tectonics/tools/benchmark_w06_history.py --output W06_STEP4_BENCHMARK.json
python -B tools/check_coding_safety.py
python -B -m unittest discover -s tests -p test_coding_safety.py -v
```

Use `:` rather than `;` in PYTHONPATH on POSIX. Execution evidence here is Windows;
these commands document reproduction, not an additional completed combined run.
