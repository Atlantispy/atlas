# W07 Step 3 — heterogeneous and thermal mechanics

23 September 2026. **WORKING NON-CANON; scoped Step 3 complete.**
Change ID: `ATLAS-W07-3-20260922` (work began 22 September).
The [Step 1 specification](W07_REGIONAL_MECHANICS.md) and
[case register](../cases/w07_mechanics.json) remain frozen. This supplements the
[Step 2 record](W07_REGIONAL_SOLVER.md); its historical reports are not rewritten.

## Implemented

- `regional_stokes.py`: explicit positive viscosity at normal-stress cell centres
  and shear-stress vertices. Full stress divergence, lifts, tractions, reactions
  and work use the corresponding coefficients. Variable-viscosity pressure-mass
  preconditioning preserves the gauge. Geometry/derivative maps survive numeric
  coefficient refills; factors are rebuilt when coefficients actually change.
- `regional_execution.py`: SI stress-site arrays, named sampling and source
  identity, safe coefficient updates, immutable published viscosity and results.
  Identical coefficients retain factors; identical definition retains the latest
  verified result. Changed provenance invalidates result reuse. Failed numeric
  refill leaves the public plan unusable until closed and rebuilt.
- `regional_rheology.py`: explicit Kelvin/depth/rate scales and retained Tosi
  temperature/depth/plastic laws and BF23 fixed-damage snapshots. Both temperature
  supports and, for BF23, both damage supports are supplied. Tensor components
  are collocated before calculating the invariant; edge reconstruction preserves
  affine fields. No viscosity clipping, arbitrary rate floor or damage evolution.
  At most 40 Picard iterations, log-viscosity change <=1e-8 **and current-law**
  momentum/divergence/gauge/work gates are required. Published stresses and
  reactions are recomputed with the current law; the preceding strict linear
  solve is separately identified, never relabelled as a current linear residual.
- `regional_transport.py`: constant-capacity/conductivity cell-mean heat transport,
  retained multidimensional MC reconstruction, SSP-RK2, conservative diffusion,
  open thermal boundaries, and uniform prescribed mesh translation. Flux uses
  physical minus mesh velocity. Material rectangles move at physical velocity,
  retain finite exterior stocks and sharp geometry, and use exact space-time
  intersections for gross inflow/outflow, including complete throughflow.
- `regional_thermomechanical.py`: a public interval joining start mechanics,
  heat/material transport and endpoint mechanics from the changed temperature.
  One detached initial temperature feeds both stages. The named linear
  cell-mean-to-stress-site reconstruction is explicit, not exact point sampling.
  Optional linear Boussinesq **total** gravity is added to explicitly separate
  other forces; the pressure reference is subtracted once. Inventory density is
  not inferred from buoyancy density. No W04 support is added automatically.

All new public interfaces are exported and their loaded functions/constants join
the existing source/runtime identity boundary. Inputs are shape-admitted before
copies. Budgets include caller reservations under 128 MiB; one native thread,
2–64 cells per axis, at most 256 heat substeps and 256 material rectangles.
Cancellation and failed-source checks preserve refusal/reuse behaviour.

### Explicit coupling support

The public interval is a first-order frozen-velocity operator split with SSP-RK2
heat substeps and an endpoint mechanical correction. Heat substeps are not
mechanical substeps. It keeps initial/final fields, not a growing field history.
Mechanical and sampled thermal loads are held in local rectangular coordinates;
world position is local position plus the recorded translating origin. The heat
adapter separately supports time/world-coordinate callbacks.

Material rectangles require uniform physical motion; nonuniform/deforming motion
is refused, not averaged. The complete rectangle list defines finite stock,
including exterior inflow; other space is explicitly vacuum. The interval uses
one thermal coefficient set and one supplied rheology profile, not an automatic
cohort-to-property mixture. BF23 is available as a frozen-damage mechanical
snapshot; the time-advancing bridge refuses it because it does not advect damage.
These interfaces do not claim geological input assembly/recovery (Step 5).

## Independent references and source correction

ASPECT v3.0.0's SolCx manual gives `rho=sin(pi*x)*cos(pi*z)`, which the frozen
B06 specification retained. Its actual `solcx.h` material model uses
`rho=-sin(pi*z)*cos(pi*x)` (line 2938). With downward gravity these are different
forcing fields, not a pressure-gauge difference. Neither frozen file was repinned.
Both explicitly named variants are tested against independent continuum solutions.

`tests/w07_interface_reference.py` builds piecewise streamfunctions from eight
boundary/interface conditions: velocity and full normal/shear traction continuity.
It imports no Atlas production operator and copies no generated ASPECT solution.
The actual source variant needs one separated mode; the frozen-manual variant
uses a converged Fourier reference with its slowly converging pressure-force
antiderivative summed analytically. Layered shear uses exact dual-support series
compliance for the declared vertical interface, not a universal mixture rule.

| Selected finest reference | Velocity L2 error | Pressure L2 error |
| --- | ---: | ---: |
| ASPECT source, aligned 64x64 | 0.426761% | 0.031727% |
| ASPECT source, unaligned 63x63 | 0.156021% | 1.104766% |
| Frozen manual, aligned 64x64 | 0.210420% | 0.053395% |
| Frozen manual, unaligned 63x63 | 0.178590% | 1.674217% |

All decrease on the selected aligned 16/32/64 and unaligned 15/31/63 sequences,
passing <=2% velocity/<=5% pressure with viscosity contrast one million.
Layered 1000:1 cases at a=0.5 and 0.37 reach <=2.22e-16 maximum velocity error
at 64x64; largest pressure/shear errors are about 1.51e-11/1.33e-11.
The public all-velocity test fixes physical mean pressure separately at 10 Pa.
The additional core top-traction case is not substituted for that datum test.

High-contrast nonzero boundary lifts initially exposed cancellation: a tiny
assembled residual could coexist with physical momentum residual above 1e-9.
At most two bounded independent stress-defect corrections now reuse the same
factor under the existing 1200-iteration ceiling. No tolerance was relaxed.
Worst recorded core reference residuals: momentum 2.97e-10, divergence 2.28e-12,
gauge 6.45e-17, work 9.48e-11.

B07 spatial perturbation errors: **2.731081%, 1.112325%, 0.420528%**. Temporal
differences to the fixed same-grid 256-step reference decrease:
2.410817e-5, 5.679418e-6, 1.131397e-6. Affine moving-grid, oblique 2D heat,
positive-temperature/maximum-principle cases, heat/source/flux accounts and
material inventory/gross-throughflow checks pass their declared gates.
Nonlinear checks preserve original Tosi factor two/Frobenius conventions and
BF23 strength factors. Recorded current-law momentum <=5.114e-11 and work
<=7.15e-10; selected nonlinear cases converge in 2–3 iterations.

## Proportionate verification

Passing evidence is reused at its actual scope; these are not a newly repeated
whole-package suite or a whole-Diadem simulation.

| Checks | Passing evidence |
| --- | --- |
| Heterogeneous core | 7 new methods, 2.283 s; 9 retained methods passed on the same final core in the earlier combined run |
| Independent interface oracle | 3 initially passed; the corrected Fourier-pressure test passed separately in 0.127 s |
| Retained regional rheology | 8 methods, 6.840 s; final adapter pre-copy shape guard covered by the focused integration check below |
| Heat/material transport | 15 methods have passing evidence; numerical subset retained from 0.850 s run, affected admission/cancellation subset 3 PASS in 0.001 s |
| Public viscosity updates | 4 PASS in the initial 8-method integration run (3.835 s total); unrelated bridge failures did not affect them |
| Public thermal bridge | 5 methods have passing evidence; two initial integration cases passed in 3.576 s run, two corrected cases in 1.990 s; final capture/support checks 2 PASS in 1.019 s |
| Retained public/source identity | 12 public + 9 identity methods PASS in 5.284 s |
| Coding safety | 13 selected maps/41 paths PASS; 30 tests PASS and one Windows symlink skip, 0.107 s |
| Material reuse measurement | 18 assertions PASS, matched output fields and frozen gates |

Reproduction uses `.r44-env/Scripts/python.exe -B -m unittest` with `tectonics/src`
and `tectonics/tests` on PYTHONPATH. Named modules: `test_regional_heterogeneous_core`,
`test_w07_interface_reference`, `test_w07_regional_rheology`,
`test_w07_regional_transport`, `test_w07_material_execution`,
`test_w07_thermomechanical`, `test_regional_execution`, and
`test_execution_reuse.IdentityTests`. No Linux execution claim.

Initial bridge failures were missing reader labels, scalar/zero-dimensional array
conversion, scalar hash handling, JSON infinity, and an exact-equality assertion
on accumulated floating-point origin. They were corrected without changing
numerical gates. A source-heated open-flow test was corrected to account for cold
inflow, not assume spatially uniform heating. Only affected tests were rerun.
Final review detached initial temperature once and admitted adapter supports
before copying; the targeted checks above cover these final changes.

## Measured reuse

[Machine-readable timing](../evidence/w07-material-timing.json), produced by
[the bounded runner](../tools/benchmark_w07_materials.py), records three rotating
samples per mode. Workload: three complete 32x32 layered mechanical outputs,
including setup, source verification, sampling, solves, validation/hashing and
cleanup. One native thread; Windows 11, Python 3.12.14, NumPy 2.4.6, SciPy 1.17.1.

| Reuse mode | Fresh median | Reused median | Time saved |
| --- | ---: | ---: | ---: |
| Changed viscosity (1, 1.25, 1.5 factors) | 1.4813644 s | 1.5503307 s | **-0.0689663 s / -4.6556%** |
| Identical requests | 1.9776553 s | 1.0293819 s | **0.9482734 s / 47.9494%** |

Changed-coefficient reuse has **no demonstrated speedup** on this small case;
it still avoids geometry reconstruction but must rebuild numeric factors. Samples
vary substantially, so the small negative median is not evidence of a universal
regression. Identical requests match byte-for-byte; changed-coefficient outputs
match the roundoff criterion. Peak accounted memory 60,948,480 bytes (58.125 MiB),
zero final reservations or resource refusals. No whole-generator time claim.

The report binds exact execution source hashes and preserves all samples. It was
completed before the final bridge-only input snapshot and adapter shape-guard
changes. Those changes do not alter the benchmarked core/public mechanics,
sampling, solver or cache path; numerical evidence is reused, not silently rebound
to a byte-identical final package. No accepted timing samples were repeated.
Report SHA256: `12746ac9d5ccfada9f6bb2ec36d9cedbe12faef2f32f26c4628ab25e120ef72e`.
The first restricted report-open attempt failed before computation; one reviewed
escalated invocation completed. No historical report was overwritten.

## Papers and software actually checked

- [ASPECT 3.0 SolCx documentation](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/benchmarks/benchmarks/solcx/doc/solcx.html)
  and [actual benchmark source](https://raw.githubusercontent.com/geodynamics/aspect/v3.0.0/benchmarks/solcx/solcx.h):
  interface conditions, source/pressure conventions and the explicit forcing erratum above.
- [PETSc DMStag ex4 source](https://petsc.gitlab.io/petsc/release/src/dm/impls/stag/tutorials/ex4.c.html)
  and [ASPECT solver documentation](https://aspect-documentation.readthedocs.io/en/stable/user/methods/stokes-solver/solver.html):
  stress-site variable coefficients and velocity/pressure block preconditioning.
- [Tosi et al. 2015](https://www.ipgp.fr/~samuel/henriIPGP/Publications_files/Tosi_2015-1.pdf),
  equations 6–10, and [Becker & Fuchs 2023](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2023GC011179),
  section 2.2/equations 6–8: original retained constitutive factors and fixed-damage
  interpretation. Relevant paper methods were checked; this is not a new claim
  of running their global models.
- [Clawpack solver documentation](https://www.clawpack.org/pyclaw/solvers.html)
  and [ASPECT 3.0 ALE documentation](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/methods/freesurface/arbitrary-le-implementation.html):
  conservative reconstruction/time stepping and physical-versus-mesh velocity.

No external framework was installed or executed; no generated third-party solver
source was copied. **Next: Step 4 surface/strength response**, with real moving
surface geometry and separately justified pressure-sensitive strength/localisation.
R4.4 and whole-W07 acceptance remain in their existing state.
