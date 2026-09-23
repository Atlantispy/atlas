# W05 step 3 — loads and continuous flexural support

Status: **PASS for this component integration**, WORKING NON-CANON.
Windows 11, Python 3.12.14, NumPy 2.4.6; one numerical thread.

## Implemented and reviewed

`extension_support.py` connects the step-2 characteristic motion to existing
W04 finite column-load construction and continuous, uniform elastic-plate support.
It does not impersonate the stationary W03 adapter or weaken its guards.
The dry restoring coefficient is **rho_m*g**, not (rho_m-rho_c)*g. There is no
second Airy correction, overlapping mantle load or repeated accumulation of w.

Stationary footwall and moving hanging wall are separate rock-volume phases.
The fixed initial footwall is partitioned in volume coordinates as support
capacity minus actual H0 volume, checked against the declared geometry at the
existing 1e-12 arithmetic scale. This avoids an artificial capacity excess from
separate rounded products. Moving H is never rescaled. Nonzero changes lost in
volume conversion are refused. A regression with Hc0=1e12 m demonstrates that a
small real moving load survives a large fixed baseline; that numerical stress
case is not a geological scenario or a supported planetary crust assumption.

Canonical surface, base and fault outputs use **true cell-mean displacement**.
New precomputed double-integrated Green weights and zero-padded linear FFT give
the exact mean response to the same cell-constant pressures as the retained W04
point solver. Face/centre w and derivatives are separately labelled. Mean output
is not interpolated centre output, and support never modifies the source material.
The mantle-volume diagnostic is -A*w for the declared hydrostatic reservoir,
not newly transported crust or a globally closed mantle-flow calculation.

The preparation binds source/runtime, initial reference, frame, datum, epoch,
policy and both operators. Foreign/nonuniform/unsupported motion is refused.
Reused kernels and bounded current outputs do not grow a timestep history.
Source changes, cancellation and budget/closed-owner failures remain visible.

## Bounded verification

Inputs are the [step-1 frozen support case](../cases/w05_support.json), bound to
the unchanged motion case. No tolerance was relaxed. Independent reference
`tests/w05_support_reference.py` imports no Atlas code: it uses nondimensional
adaptive quadrature of the continuum Green function with explicit load/front
splits, nested target-cell integration and bounded omitted Green tails.
Quadrature estimates are numerical uncertainty estimates, not rigorous interval
proofs; the largest estimate in this comparison was 1.353e-7 m (<0.01 m gate).

| Grid spacing | Cells | Largest sampled point-w error | Largest sampled mean-w error |
| --- | ---: | ---: | ---: |
| 500 m | 800 | 0.016208160 m | 0.016152466 m |
| 250 m | 1,600 | 0.004051992 m | 0.004045824 m |
| 125 m | 3,200 | 0.001012995 m | 0.001012273 m |

Each row compares **84 point probes and 9 cell means**, including the front,
shoulder/basin region and sampled displacement extremum. Smooth-load error is
distinct from exact-same-cell-load error and decreases approximately fourfold
per grid halving. This component evidence does not stand in for later combined
W05 acceptance or independent geological field validation.

- Exact same cell-load direct/FFT mean comparison, all 3,200 outputs:
  maximum difference **8.526512829121202e-14 m**.
- Enlarged-domain crop surface difference at 250 m:
  **6.59916565837193e-13 m**, below the frozen 0.01 m limit.
- At 125 m, synthetic mean surface range is -757.620578 to +181.804348 m;
  these are the model's outputs, not imposed terrain targets.
- Whole-domain omitted-load displacement bound: 2.3820846634539862e-8 m;
  slope/curvature bounds remain nonzero as well. Tail underflow cannot become an
  exact-zero claim. The moving front must stay inside the source window.
- Whole-domain continuous validity bounds at 125 m: |w| <=210.062996 m,
  |w'| <=0.007716859, bending strain <=0.001997166. These include both exterior
  uncertainty and bounds between sampled faces/centres using Green derivative
  norms, not just a search of output samples.
- **9 new production tests passed in 3.209 s**, including independent tiny-cell
  quadrature, hydrostatic limit, non-accumulation, stable loads, conservation of
  source state, and rejection/resource/identity cases.
- **3 reference-control tests passed in 0.037 s**; **18 affected motion/identity
  regressions passed in 6.680 s**. Static source wiring: 13 maps/41 paths PASS.
  Safety tests: 30 PASS, one Windows symlink skip, 31 reported in 0.106 s.
- No entire generator, full terrain, held R4.4 or multiday run was performed.

## Measured optimisation

[Raw samples, environment and source hashes](w05-support-timing.json): three
alternating repeats, identical loads/outputs and unchanged accuracy criteria.

| Comparison | Before | After | Saved |
| --- | ---: | ---: | ---: |
| 12 mean-field evaluations: direct convolution -> prepared linear FFT | 0.013806600 s | 0.001636400 s | 0.012170200 s (88.1477%) |
| Three load/support outputs: rebuild each time -> reuse prepared geometry | 0.501630000 s | 0.325147400 s | 0.176482600 s (35.1818%) |
| Same three-output sequence including one initial reusable preparation | 0.501630000 s | 0.377027400 s | 0.124602600 s (24.8395%) |

Direct convolution gets the same precomputed analytical weights as FFT; both
include input capture, budget admission and immutable outputs. The projection
comparison includes load snapshots, source checks, budgets and all mean/point
outputs. Common material generation is excluded from both; no whole-generator
speedup is claimed. The one preparation took 0.051880 s; retained point/mean
operator arrays total 1,179,728 bytes, with conservative resource admission above
that amount. These are new-method comparisons, not old-release benchmarks.

## Reproduction and references actually checked

With the existing scientific environment, one BLAS/Numba thread, and
`tectonics/src` plus `tectonics/tests` on PYTHONPATH:

```text
python -B -m unittest test_w05_support test_w05_support_reference
python -B -m unittest test_w05_extension test_execution_reuse.IdentityTests
python -B tectonics/tools/benchmark_w05_support.py --output tectonics/evidence/w05-support-timing.json
```

- [Wickert (2016), gFlex v1.0](https://gmd.copernicus.org/articles/9/997/2016/gmd-9-997-2016.pdf):
  full-text sections 2.1 and 2.3, equations 1/3/4 and boundary discussion checked.
  Informed uniform-plate Green superposition, mantle-minus-infill restoring
  density, and distinguishing a continuing plate from a physical break or clamp.
- [Landlab ListricKinematicExtender, example 5](https://landlab.csdms.io/tutorials/tectonics/listric_kinematic_extender.html):
  inspected the crust-thickness/load coupling and subtraction of the initial
  response. Atlas uses its own fixed-reference accounts and true cell means.
- Existing Atlas W04 column loads/finite flexure and W05 motion code were read
  and reused. gFlex and Landlab were not installed or executed; their published
  mathematics/documentation informed the implementation, not its acceptance.

Next remains step 4 (recoverable optimised workflow), then step 5 (combined
acceptance). This step already reuses prepared operators; it does not invent a
second durable-result cache ahead of the planned workflow layer.
