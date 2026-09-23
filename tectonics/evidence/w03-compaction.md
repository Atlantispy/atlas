# W03.3 compaction: focused checks and measured batching

22 September 2026. WORKING NON-CANON. Local `remake` edits, not committed/pushed.
PASS for the selected saturated, already-drained, fixed-grain parcel model.
[Equations, APIs, actual research coverage and limitations](../docs/W03_COMPACTION.md).
Not empirical sediment calibration, transient consolidation or whole-W03 acceptance.

## Implementation and numerical evidence

History-dependent natural-log loading/rebound law; explicit past maximum loading;
solid-coordinate effective pressure; changing-area grain conservation; finite
pooled fluid reservoir checks; source-bound W01 authored-sediment import with true
grain/fluid conventions; immutable state and existing-store save/restore; grouped
and batched evaluation plus source/runtime/callable-bound cache reuse.

Final Windows run, scientific thread counts set to one, with `tectonics/src` and
`tectonics/tests` on `PYTHONPATH`:

```text
python -B -m unittest test_w03_compaction_law test_w03_compaction_columns test_w03_thermal_support test_execution_reuse.IdentityTests test_execution_reuse.CacheExecutionTests -q
```

**64 PASS in 6.560 s**: 21 new focused tests and 43 affected support/identity/reuse
checks. No full suite or long physical run. Windows 11 build 26200, Python 3.12.14,
NumPy 2.4.6. Linux execution is not claimed.

Static source maps PASS (13 maps/41 required paths); coding-safety tests 30 PASS,
one expected Windows symlink skip, 0.110 s. `git diff --check` PASS with only the
pre-existing CURRENT_STATE line-ending advisory.

Controls cover loading/unloading/reloading, irreversible/reversible/zero-slope
limits, independent Decimal small-increment arithmetic, immutable aliases,
bounded cancellation and admission, grain and fluid accounts, changing area,
mixture cohort identity, peak-history persistence and bit-identical continuation,
wrong epochs/history/basis/fluid/porosity refusals, cache hits, modified histories/
parameters/callables and the shared-reservoir stock limit.

Continuous independent self-weight oracle: 100 m3 grains, density 2650 kg/m3,
fluid density 1000 kg/m3, gravity 10 m/s2, initial void ratio 0.8, top effective
traction zero, stress offset 100000 Pa, slopes 0.1/0.02 (synthetic, not fitted).
Prescribed area 1 -> 0.5 -> 1 m2 gives continuum thicknesses
**180 -> 348.0489533306557 -> 175.21958133226227 m**. Grain mass remains 265000 kg;
partial rebound does not restore all original pore space. The increased loaded
height reflects the reduced area, not a claim that compaction creates solid volume.

| Midpoint parcels | Loading thickness error against exact continuous integral |
| --- | ---: |
| 16 | 0.04154216824 m |
| 32 | 0.01227892620 m |
| 64 | 0.00326733370 m |
| 128 | 0.00083225477 m |

Refinement ratios are 3.3832, 3.7581 and 3.9259: the coarse 16-parcel sample is not
yet in the asymptotic second-order range. The final test uses 32/64/128, preserving
its original 3.5-4.1 ratio gate rather than loosening it. 128 parcels give 0.83 mm
error in this synthetic case; this is numerical error, not real-world accuracy.

During review, fixed three issues before final checks: malformed auxiliary shapes
could be copied before admission; metadata admission did not count every grain
component/text field; scalar reservoir stock could be duplicated across columns.
The final implementation preflights shapes, admits metadata sizes, and checks one
pooled reservoir total. An initial save/restore test fixture also omitted required
store limits; the fixture was corrected. No production tolerance was relaxed.

## Paired performance

`python -B tectonics/tools/benchmark_w03_compaction.py`, one warm-up then three
alternating-order pairs, **1,024 columns x 64 parcels = 65,536 updates**.
[Raw times and source SHA-256 bindings](w03-compaction-timing.json).

| Same guarded constitutive calculation | Median time |
| --- | ---: |
| Separate per-column calls (already vectorised within each column) | 81.860500 ms |
| One bounded batch of independent columns | 2.343700 ms |
| Saved | **79.516800 ms / 97.136959%** |

Results were **bit-identical**, including maximum-stress history. Speed ratio
34.927893x. This measures batching/call-overhead reduction for the same new law,
not a previous production implementation, a full compaction workflow, pyBacktrack
timing, a whole-generator gain or a prediction for R4.4. No disk-cache/JIT/worker
pool is used in these timed paths. Cache auto-bypass avoids overhead for cheap work.
Grain buffers are shared across state transitions; no growing history arrays.

## Research and remaining scope

Checked Fowler & Yang (2002) full-text constitutive/history sections; Müller et al.
(2018) full-text decompaction method; pyBacktrack well/lithology source; existing
Atlas inventory, resource and store/reuse code. Original Athy full text was not
accessible. No upstream code copied, software installed or external runtime tested.

Compaction increment complete in the stated drained scope. Assembled W01/W02/W03
acceptance remains: compatible thermal fields, explicit vertically ordered
material/history exchange and external reservoir/support accounts. No automatic
remapping of maximum-load history, authored-field overwrite, empirical parameter
selection, old checkpoint repin or whole-world/R4.4 simulation.
