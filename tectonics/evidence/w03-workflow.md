# W03 bounded assembly acceptance

22 September 2026. WORKING NON-CANON. Local `remake`, uncommitted/unpushed.
Selected stationary fixed-area W01/W02/W03 assembly: **PASS**. Not general
moving-stratigraphy, empirical geology/terrain calibration, R4.4 or whole-world
acceptance. [Implementation/physical scope](../docs/W03_WORKFLOW.md).

## Implemented joins and corrections

- Actual W01 source/sample/workflow identities, ordered top sediment parcels and
  each W02 cohort/cell are checked together. Full planar reference-area conversion
  is retained. Transported/mixed source columns and multiple pore-water origins
  refuse; there is no inferred stratigraphy or averaged maximum loading.
- Authored/selected initial thermal boundaries, cell means, cooling history,
  diffusivity, epoch/datum and **authored lithosphere versus finite-plate depth**
  must agree within the explicit mean/boundary tolerance where applicable.
- A finite water stock is updated alongside real W02 clock/removal/addition
  receipts. Both signs of a mixed exchange survive in one immutable last-step
  record. Grain reference masses do not change with thermal buoyancy density.
- Source workflow dependencies are saved through existing deduplicated storage;
  restart rechecks the thermal assertion against the restored source, not just a
  saved error scalar. Current compaction peak history and water stock continue
  exactly. Source/runtime changes still refuse automatic reuse/rebinding.
- Fixed-reference thermal diagnostics are not repeated elevation increments.
  Net heat is independently integrated rather than derived by subtracting large
  opposing boundary totals. Unresolved boundary-heat increments refuse.
- Correct backend-specific preparation is shared by `evolve_w03_columns`; all
  intermediate loads and the existing live source checks remain in place.

## Focused verification

Windows 11 build 26200, Python 3.12.14, NumPy 2.4.6, existing scientific environment;
BLAS/OpenMP/Numba thread limits set to one. No installation, R4.4 rerun or full suite.

```text
python -B -m unittest test_w03_workflow test_w03_compaction_columns
  test_w03_thermal_support test_execution_reuse.IdentityTests
  test_execution_reuse.CacheExecutionTests -q
63 tests PASS in 31.735 s
```

Nine new assembly tests, plus affected compaction/support/cache/identity checks.
The assembled synthetic control uses four columns of 2 m2, with 40 m sediment
at porosity 0.4 over 60 m at porosity 0.25: per-column solid equivalent thicknesses
24 and 45 m, pore equivalent 31 m. Total pore water is 248 m3; with a 100 m3
reservoir, all load/unload/reload states close to 348 m3. Source grains are unchanged.
Time labels are 1e12 s apart; drainage is prescribed complete, not dynamically
proven by that interval. The separate compaction increment already supplies the
independent continuous-column refinement oracle; it was not re-run as a new study.

Cooling at nonzero age closes cell-integrated heat against rho*Cp and buoyancy
against rho*alpha and the selected restoration contrast. Repeated support queries
do not change state. Loading/unloading retains irreversible residual compaction
and peak stress. Mixed signed exchanges retain all three W02 receipts. Insufficient
stock, wrong thermal model/datum/depth, moving or mixed source geology, distinct
water origins, invalid clocks, resource exhaustion and cancellation refuse.
Restored and uninterrupted successors are bit-identical, including forced verified
cache continuation. The preferred prepared sequence equals individual updates.

Static coding-safety review: 13 maps / 41 required paths PASS. Its unittest module:
31 run, 30 PASS, one existing Windows symlink skip, 0.109 s. `git diff --check` PASS;
only the existing CURRENT_STATE line-ending advisory. This turn executed Windows,
not Linux; the new code uses the existing portable NumPy/SciPy/storage interfaces.

During implementation, import/backend binding and typed-record JSON restoration
errors were corrected before the final passing run. No tolerance was weakened.

## Measured efficiency

`python -B tectonics/tools/benchmark_w03_workflow.py`

Same six sequential load/unload steps, 256 columns, 128 parcels/column:
**196,608 parcel updates**, three alternating-order repetitions after one untimed
equivalence run per route. Both include their execution-context preparation and
closure; shared W01/W03 initialisation is outside timing. No cache hits, workers,
skipped intermediate loads or relaxed verification create the gain.

| Route | Median elapsed |
|---|---:|
| Separate execution setup for every complete step | 3.261035100 s |
| Automatic shared setup for the complete sequence | 2.181135000 s |
| Saved | **1.079900100 s / 33.115255%** |

Speedup **1.495109x**. Final complete-state SHA is identical between both routes.
This is an assembled stationary-sequence optimisation, **not** a whole-generator,
whole-planet or external-software speedup. Earlier component gains are not added
to this percentage. [Raw measurements and exact source hashes](w03-workflow-timing.json).

## Research/software coverage and remaining limits

For this join, inspected ASPECT's primary Boussinesq documentation (equations and
mass/buoyancy distinction) and pyBacktrack's ordered stratigraphic/decompaction
source interface. The earlier Fowler & Yang full-text compaction review remains
the history/drained-limit basis. Exact links, coverage and influence are in the
[implementation document](../docs/W03_WORKFLOW.md#papers-and-software-checked).
No upstream software was copied, installed, executed or performance-compared.

General lateral history-preserving remapping, multiple-fluid provenance allocation,
evolved thermal properties/deformed thermal mesh, advected pore-water heat and
transient pore pressure remain outside this reduced assembly. Restricted physical
validity and synthetic acceptance do not establish calibrated Diadem terrain.
