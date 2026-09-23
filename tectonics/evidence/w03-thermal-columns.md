# W03.1 thermal-column implementation and focused acceptance

22 September 2026. PASS for the stated constant-property finite-plate column
model. WORKING NON-CANON. Local changes on `remake`, not committed or pushed.
[Contract, research and limitations](../docs/W03_THERMAL_COLUMNS.md).

## Implemented

- Explicit plate parameters with consistent conductivity/diffusivity/heat capacity.
- Stable point temperatures and cell means from zero to mature cooling age.
- Independently evaluated cumulative top/base heat, including the hot-base inflow.
- Source-bound history-to-column workflow, named epochs and preserved parent state.
  Unknown ages refuse; rock formation dates are never substituted for cooling age.
- Bounded vectorised batches, shared modal geometry and grouped model profiles.
- Existing auto-cache policy and source/runtime/callable invalidation; no silent
  historical rebind, relaxed gate, new package dependency or forced worker pool.

The new workflow produces a derived model rather than silently replacing the
predecessor initial temperature descriptions. General variable-property thermal
evolution, material coupling, density/support and compaction remain later work.

## Focused verification

Windows 11 build 26200; Python 3.12.14, NumPy 2.4.6, SciPy 1.17.1. Scientific
thread counts explicitly set to one. No Linux execution claimed for this change.

With `tectonics/src` and `tectonics/tests` on `PYTHONPATH`:

```text
python -B -m unittest test_w03_plate_cooling test_foundations.ThermalTests test_execution_reuse.IdentityTests test_execution_reuse.CacheExecutionTests -q
```

**50 passed in 6.014 s**: 12 new focused tests and 38 affected foundation/identity/
reuse tests. The new tests include:

- Independent 300-mode scalar reference on resolved positive ages; both algorithm
  branches and the switch; exact boundary, zero-age and mature limits.
- Half-space young-age limit and explicit separation from old half-space results.
- Independent quadrature of cell means; subnormal-width cells and a near-surface
  mean near `2.8209479177e-18` in the unit-temperature fixture.
- Heat against integrated temperature loss on 1/13/64-cell grids; independent
  positive-age flux integration and interval splitting.
- Independent dense finite-volume conduction on 16/32/64 cells: each successive
  max-error ratio >3.5, with one versus two exponential steps agreeing within
  `3e-14` normalised temperature. No multi-hour simulation.
- SI scaling and extreme representable scales; rejected unrepresentable depth
  ratios rather than silently treating them as the surface.
- General broadcast versus prepared column-grid route, immutable outputs,
  bounded admission, cancellation, verified cache hits and changed-executable
  invalidation; distinct point/cell/age/parameter cache records.
- Cooling provenance, explicit model selection, grouped distinct ages, unknown
  histories, wrong epochs and invalid depth grids.

A bounded independent code review caught two edge cases before final checks:
zero-contrast heat was incorrectly rejected by a positive-scale helper, and
`1-mean(erfc)` could erase very small shallow-cell temperatures. Both are fixed
and covered by the final tests. No other code was changed by the reviewer.

Repository static checks: `tools/check_coding_safety.py` PASS (13 selected maps,
41 required paths); 30 coding-safety tests passed, one Windows symlink test skipped,
0.111 s. `git diff --check` passed, with only the pre-existing CURRENT_STATE.md
line-ending advisory. No full test suite or R4.4 campaign was rerun.

## Paired timings and accuracy

Reproduce with `python -B tectonics/tools/benchmark_w03_cooling.py` from the repo
root. [Raw timings and source hashes](w03-cooling-timing.json) are retained.
Each comparison evaluates 1,024 ages x 256 depths/cells = **262,144 outputs**.
Three paired repetitions follow one warm-up. Medians, one native thread:

| Output | Vectorised 100-mode reference | Implemented direct-age route | Saved | Time reduction |
| --- | ---: | ---: | ---: | ---: |
| Point temperatures | 31.204800 ms | 8.972800 ms | 22.232000 ms | 71.2454% |
| Cell means | 35.854900 ms | 21.850300 ms | 14.004600 ms | 39.0591% |

Maximum normalised differences were `8.881784197001252e-16` for points and
`2.6756374893466273e-14` for cell means. For an illustrative 1,300 K contrast,
the latter is about `3.48e-11 K`, far below the physical modelling uncertainty.
The 100-mode reference is itself vectorised, not a deliberately slow scalar loop;
its age range `Fo=0.005..10` makes its truncation negligible. Zero/very young age
is checked separately, where arbitrary fixed term counts are not valid oracles.

The initial batched implementation gave approximately 36% less point time but
cell means were about 5.5% slower than their reference. Reusing modal age/depth
factors removed that repeated work; the final paired figures above supersede
those development measurements. There is no asserted disk-cache speedup for
these tiny calculations: default auto admission avoids that overhead.

These are same-equation algorithm comparisons, **not a speedup of a previous
implemented finite-plate stage** (there was none), not ASPECT/GWB timings, and
not whole-generator or R4.4 campaign forecasts. Neither timing route marches
through geological timesteps. Scientific applicability remains the constant-
property, fixed-thickness, fixed-boundary 1-D model documented in the contract.
