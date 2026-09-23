# W05 step 2 — conservative motion and thinning

Status: **PASS for the specified motion component**, WORKING NON-CANON.
Windows 11, Python 3.12.14, NumPy 2.4.6, SciPy 1.17.1; one numerical thread.
The coupled support and recovery steps retain their existing place in the plan.

## Implementation

`src/atlas_tectonics/extension.py` implements source-bound fixed-grid listric
motion, stationary footwall, immutable W02 cohorts and independently integrated
finite-region export receipts. Public classes are exported by `atlas_tectonics`;
the extension module participates in live/source execution identity checks.
The production characteristic path solves the declared constant-speed profile
directly. It does not numerically diffuse the moving edge or require timesteps.

Inputs/gates: [frozen case](../cases/w05_motion.json), copied from the step-1
contract without relaxing thresholds. Reference: `tests/w05_reference.py`,
independent point-profile/boundary quadrature plus parcel-map/dilation controls.

## Results

- 800 / 1,600 / 3,200 cells (500 / 250 / 125 m): maximum crop H error
  **3.637978807091713e-12 m** on each grid; finest relative L1
  **8.616154932020543e-17**. Global integral error <=5.4569682106375694e-12 m.
- Two tagged cohorts, fractions 0.25/0.75: zero left inflow; right exchanges
  -2,499,999.999900741 and -7,499,999.999702223 m2. Largest cohort inventory
  residual 2.3096799850463867e-7 m2, within unchanged W02 roundoff bounds.
- Direct versus 64-/128-output continuation: final material and exchanges
  bit-identical. Larger domain: **0 m** difference on the common surface crop.
- Existing MUSCL diagnostic: **24.584781512074883 m** edge error, FAIL against
  10 m. Retained as evidence; not passed off as the accepted production route.
- 9 focused production tests, 2 independent-reference tests and 9 existing
  execution-identity tests passed in targeted invocations. Covers positivity,
  nonuniform/tiny cells, zero motion, complete export, immutable histories,
  clocks/underflow, cancellation/budgets, source changes, MUSCL cache miss/hit
  parity and separate native ALE dilution. One initial cache test fixture
  under-budgeted SQLite's existing resident reservation; correcting the fixture
  to include those pages passed without changing production budget safeguards.
- Static wiring: 13 maps / 41 paths PASS. Coding-safety tests: 30 PASS, one
  Windows symlink skip (31 reported, 0.107 s). No whole-generator run.

## Measured optimisation

[Raw timing and source identities](w05-motion-timing.json), three alternating
repeats on the 3,200-cell, two-cohort case. Medians:

| Matched-accuracy comparison | Before | After | Saved |
| --- | ---: | ---: | ---: |
| Cell-integral kernel: independent adaptive quadrature -> stable vectorised analytical integration | 0.015387400 s | 0.000147200 s | 0.015240200 s (99.0434%) |
| Prepared three-output sequence: Python -> native inventory/total reductions, same characteristic method | 0.295834300 s | 0.270354000 s | 0.025480300 s (8.6130%) |

The first comparison is to the independent scalar integration implementation,
not an older shipped generator. The second includes source checks, budgets,
cohort histories, exports and geometry outputs, but excludes preparation and
first-ever JIT compilation. Warm-process preparation: reference 0.127891100 s;
native 0.210932000 s. Including that setup, this one sequence is 0.423725400 s
reference versus 0.481286000 s native; use `backend='reference'` for a short
one-off and amortise the native option over repeated sequences. Setup is an
observed single preparation, not a robust cold-start benchmark.

The diagnostic MUSCL run took 8.176098 s, but fails the accuracy gate. It is
deliberately excluded from matched-quality speedup percentages. No global
generator, coupled-support, Linux runtime or geological field-validation claim
is inferred from these bounded measurements.

## Reproduction and sources checked

With the existing scientific environment and numerical thread variables set to 1:

```text
PYTHONPATH=tectonics/src;tectonics/tests
python -B -m unittest test_w05_extension test_w05_reference test_execution_reuse.IdentityTests
python -B tectonics/tools/benchmark_w05_motion.py --output tectonics/evidence/w05-motion-timing.json
```

The PYTHONPATH separator above is Windows syntax; use `:` on Linux. No OS-specific
implementation APIs were added. Existing source material consulted:

- [Landlab ListricKinematicExtender tutorial](https://landlab.csdms.io/tutorials/tectonics/listric_kinematic_extender.html):
  reopened its theory and translated-thickness definition.
- [Clawpack / LeVeque, Riemann-book advection](https://www.clawpack.org/riemann_book/html/Advection.html):
  conservation and exact constant-speed characteristic solution.
- Atlas W02 transport, material histories, cache and accounting implementation:
  inspected and reused, not replaced or weakened.

Landlab/Clawpack documentation was reviewed, not executed. No new paper is claimed
read for step 2; the step-1 paper review remains in the mechanism specification.
