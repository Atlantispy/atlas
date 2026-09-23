# W03.2 thermal-density/support implementation and focused acceptance

22 September 2026. PASS within the stated homogeneous, constant-property,
first-order local-compensation scope. WORKING NON-CANON, local `remake` edits;
not committed or pushed. [Scientific contract and checked sources](../docs/W03_THERMAL_SUPPORT.md).

## Delivered

- The existing Boussinesq thermal-density law, not a competing equation of state.
- Explicit reference-column sheet anomaly, downward pressure and total downward
  displacement, with separate EOS/reference-column datums and fill density.
- One declared thermal-support owner; mechanical, flexural and empirical owners
  cannot also invoke this local-isostatic route. No elevation or mass-state mutation.
- Exact finite-plate column integration without depth sampling, stable mature-age
  differences, bounded arrays/chunks and range-aware final material scaling.
- Source-bound cooling histories, matching model/material selection, named epochs
  and depth datums, grouped evaluation and immutable reference-to-current outputs.
- Existing verified cache integration, including source/runtime/callable identity,
  full parameter provenance and cheap-call auto bypass. No new dependency or JIT.

The isostatic reference is the explicitly selected model at the chosen reference
time. It is not silently asserted equal to the original authored W01 field.
Thermal sheet anomaly is a Boussinesq load diagnostic, not an exact evolving mass
inventory. The caller selects a small-deflection envelope; its acceptance is not
an empirical calibration. Arbitrary external code remains responsible for not
ignoring the ownership record and double-applying support.

## Focused verification

Windows 11 build 26200; Python 3.12.14, NumPy 2.4.6, SciPy 1.17.1. Scientific
thread counts set to one. No corrected-source Linux execution is claimed.

With `tectonics/src;tectonics/tests` on `PYTHONPATH`:

```text
python -B -m unittest test_w03_plate_integrals test_w03_thermal_support test_w03_plate_cooling test_constitutive_r3.ThermochemicalTests test_execution_reuse.IdentityTests test_execution_reuse.CacheExecutionTests -q
```

Final production code: **76 passed in the 77-test combined run (6.448 s)**. One
new test fixture omitted the second thermal profile's required cooling-history
record, so failed before reaching the calculation. Only that fixture was fixed;
the exact affected test then passed in 0.003 s:

```text
python -B -m unittest test_w03_thermal_support.ThermalSupportWorkflowTests.test_distinct_epochs_collapsing_to_equal_ages_refuse -q
```

Thus all **77 selected checks pass across these retained runs**: 23 new and 54
affected existing tests. Unrelated tests were not repeated after a fixture-only
change. The numerical and integration coverage includes:

- Independent converged 1,000-mode integral reference, grid-partitioned true cell
  means, branch-switch continuity, young square-root and old finite-depth limits.
- SI scaling, mature adjacent-age differences, equal ages, reverse signs,
  isothermal plates, zero expansivity and range refusals.
- Existing Boussinesq consistency, uniform-cooling load/displacement, gravity and
  fill effects, separate EOS and isostatic references, and nonaccumulating totals.
- Generic depth repartition and compensated batch joins against `math.fsum`.
- Ownership, full analytic temperature interval, material/cooling consistency,
  internal-heating and explicit small-deflection refusals.
- Shapes, nonfinite/masked data, immutable results, cancellation and budget
  admission/release; source/history/epoch/datum and unknown-history handling.
- Real cache write/hit, cheap-call bypass, reference/policy changes and altered
  loaded-callable refusal. Existing identity/reuse tests remain passing.

During development, strict cache metadata comparison exposed a tuple/list JSON
representation mismatch. Canonicalising metadata before both persistence and
comparison fixed it without weakening the cache check. Independent bounded code
review then identified two false-zero edge cases: weighted temperature underflow
before later scaling, and distinct times collapsing to equal cooling ages against
an ancient start date. Both now refuse explicitly and have regression coverage.
The conservative leading-transient-underflow refusal of the mature integral is
also documented and tested. No physical minimum age or tolerance relaxation.

Required static checks: 13 selected source maps/41 required paths PASS; coding
safety tests 30 PASS, one expected Windows symlink skip, 0.106 s. No full suite,
multi-hour simulation, R4.4 campaign or historical checkpoint repin.

## Paired elapsed-time measurement

Reproduce from the repository root:

```text
python -B tectonics/tools/benchmark_w03_support.py
```

[Raw paired times, versions and source SHA-256 hashes](w03-support-timing.json).
2,048 columns, 256 true cell means per sampled column, one warm-up and three
alternating-order paired repetitions. The sampled control reuses its unchanged
reference temperatures; it is not charged for recomputing that reference.

| Same-model calculation | Median elapsed time |
| --- | ---: |
| Finite-plate cell means, then depth integration | 45.518000 ms |
| Direct whole-column integral | 0.934000 ms |
| Saved | **44.584000 ms / 97.948064%** |

Speed ratio: 48.734475x. Maximum absolute differences are `1.862645149230957e-9`
kg/m2, `1.4901161193847656e-8` Pa and `9.094947017729282e-13` m respectively.
Both routes pass the unchanged comparison (`rtol=2e-12`, `atol=1e-8`, with the
combined relative/absolute rule). The final source-bound measurement supersedes
the intermediate 45.285 -> 0.941 ms development measurement.

This measures removal of unnecessary depth sampling for **the same constant-
property model**, not a previous production W03 support stage, externally run
ASPECT/gFlex, whole-generator savings or an R4.4 forecast. Neither route marches
through geological timesteps; neither timed route uses disk cache. The primary
benefit is direct evaluation without a column-depth grid; no empirical accuracy
has been traded for the reduction. Applicability remains restricted by the model.

## Research and remaining work

Actually checked: Parsons & Sclater (1977), full-text equations 9-11/Figure 1;
Wickert's gFlex (2016), full-text section 2.1/equations 1-2; ASPECT's Boussinesq
documentation (3.0.0, corroborated by 2.5.0); existing Atlas constitutive,
thermochemical, flexure, plate-cooling and verified-reuse code. Their influence,
links and review extent are recorded in the contract above. External software was
not installed/executed and no upstream code was copied.

This closes W03 increment 2 in the documented scope. Still outstanding:
solid-conserving compaction/decompaction with changing area, reconciliation of
authored and selected thermal fields, and assembled W01/W02/W03 acceptance.
No deformable-surface, layered thermal-column, full-world realism or canon claim.
