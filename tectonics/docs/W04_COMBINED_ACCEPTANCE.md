# W04 step 5: combined supported-workflow acceptance

22 September 2026. WORKING NON-CANON, local unreleased `remake` work.

**PASS_SUPPORTED_STATIONARY_PLANAR_1D_W04**: the planned load-to-support gate
passes for the implemented stationary, planar 1D W01-W03 workflow. This completes
the selected W04 sequence, not whole-world terrain, geological calibration or
acceptance of other stages. [Evidence](../evidence/w04-acceptance.md) and the
[source-bound machine record](../evidence/w04-acceptance.json) retain that scope.

## What was accepted

Physical finite-reference loads, one thermal owner, explicit closed-water
placement and additional external pressure connect to uniform or prescribed
variable-rigidity support. Results are total displacements and surface changes
from a fixed reference, never repeatedly accumulated deflections.

The new combined control uses actual source-authenticated W03 states: initial
columns, cooling plus prescribed drained compaction, then partial rebound and
further cooling. Expelled/reabsorbed water is booked once and explicitly placed;
a zero-total spatial redistribution and additional pressure are superposed.
Independent depth-cell thermal integration and inventory accounts check the
constructed load. Source grains and states remain unchanged by the projection.

That identical sequence is exercised through six alternatives: uniform/variable
rigidity, each with periodic, continuing-plate or mixed free/clamped boundaries.
The continuing case has two left halo cells, one right halo cell and explicit
constant-load/material half-lines. Different boundaries are different physical
problems, not outputs expected to match one another.

Reference-shifting checks establish interval additivity without accumulating prior
totals. W03 checkpoint restoration followed by rebound produces the same successor
state; rebuilt W04 plans and cache hits reproduce exact result bytes and IDs.
Variable-D strain limits are rechecked even on cache hits, using the cropped local
Te rather than the uniform policy placeholder, including the mesh-change margin.

## Reproducible bounded selection

From the repository root, with the existing declared dependencies and one
BLAS/OMP thread:

```text
python -I -B tectonics/verify.py --w04
```

This selects exactly eight reviewed groups, not the whole tectonics suite:

| Gate | Tests | Main evidence |
| --- | ---: | --- |
| Physical reference loads | 19 | Inventory, replacement, thermal basis, cancellation and range |
| Uniform periodic support | 10 | Independent discrete operator, sinusoid convergence and superposition |
| Uniform finite support | 11 | Analytical/quadrature controls, ends, subdivision, domain and uncertainty |
| Variable rigidity | 8 | Independent two-material solution, mesh refinement and sharp interfaces |
| Combined stationary workflow | 4 | Six-route evolving sequence, reference shift, restart/cache and strain guard |
| Verified load reuse | 1 | Reuse admission, persistent hit and invalidation |
| Source/geometry/ownership/validity guards | 6 | Wrong inputs, double support, overfill, source drift and exterior refusal |
| Acceptance status contract | 3 | No empty, skipped, failed, drifting or broadened pass |

Missing tests fail; no fallback discovers the full suite. The existing verifier
records all selected test IDs, before/after source hashes and runtime identity.
A pass requires nonempty successful execution, no skips and unchanged source.
The existing W01 selection and status meanings are preserved and separately tested.
This is explicit scoped numerical/engineering acceptance, not empirical validation.

## Physical and numerical limits retained

- Positive D fixed in time and positive constant restoring K; source-linked
  elastic thickness is not inferred from crustal or thermal-plate thickness.
- Small-deflection thin-plate support, invariant transverse loading, stationary
  reference geometry. No arbitrary plate motion, 2D/spherical region, yielding,
  viscoelasticity or changing rigidity is added.
- Uniform periodic support solves the existing discrete biharmonic equation.
  Finite uniform support uses the cell-integrated continuum solution; variable
  rigidity uses the conservative continuum weak form. Finite-resolution identity
  across these representations is not an acceptance condition.
- Continuing variable-D support requires exact declared outside loads; nonzero
  omitted-pressure uncertainty refuses. The uniform route retains its conditional
  exterior bounds. The omitted world is never assumed known merely to get a pass.
- Mesh-change estimates are not rigorous continuum-error certificates. Variable
  FE extrema and one-sided strain checks retain their stated scope; uniform finite
  validity remains sampled at centres/faces. Third FE derivatives are diagnostic.
- W03 remains a prescribed already-drained, fixed-property thermal/compaction
  model. Effective compaction traction and additional W04 pressure are distinct
  explicit inputs, not a solved coupled stress equilibrium. No shoreline, erosion,
  material/heat-mesh feedback or dynamic fault initiation is implied.

The synthetic sequence is an accounting/connection challenge, not calibrated
geology. Its initial longer cooling interval correctly triggered the existing
strain limit. The accepted case uses a shorter interval, with the same limits and
comparison tolerances. Details are retained in the evidence rather than hidden.

## Efficiency and researched basis

This step changes verification and documentation, **not the production solvers**.
Prepared contexts are shared within the synthetic sequence; core analytical
controls are cheap, and only missing cross-component joins were added. No full
terrain/R4.4 run, worker pool, new cache or benchmark campaign was necessary.
Existing source-checked optimisation evidence remains separate from acceptance
runtime; no new whole-generator speedup is claimed.

Before choosing the acceptance comparisons, reviewed [Wickert (2016), gFlex](https://gmd.copernicus.org/articles/9/997/2016/)
full-text load/infill and superposition discussion (section 2.1), limitations and
benchmarking (sections 2.4-2.5), and coupling (section 3.2). Also reviewed the
current [gFlex numerical-accuracy documentation](https://gflex.readthedocs.io/en/latest/accuracy.html)
on analytical/numerical comparisons and boundary/grid effects. These informed
matching the equation, load representation and boundary assumptions when judging
agreement. We do not import its empirical grid rules or sign conventions as Atlas
acceptance tolerances. No external package execution or field validation occurred.

Next is **W05: the first coupled regional-extension mechanism**, with its own
specification and reference comparison. That work has not been started by this
acceptance run, and passing W04 does not clear held R4.4 or unimplemented stages.
