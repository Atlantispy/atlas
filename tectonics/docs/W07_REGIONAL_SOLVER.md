# W07 regional solver and heterogeneous thermal mechanics

The linked reports are redacted historical public copies. Publication changed
personal paths and report digests, not the recorded measurements or scientific
source/runtime identities; the [redaction record](../evidence/public-path-redaction-r1.json)
retains the boundary.

Implementation and acceptance record, 22 September 2026.
Completion status: **STEP 2 COMPLETE; bounded numerical acceptance and reuse measured.**

The [Step 1 design](W07_REGIONAL_MECHANICS.md) remains frozen. This increment
implements its basic regional mechanics and independent method comparison. The
[Step 3 extension](#w07-step-3--heterogeneous-and-thermal-mechanics) covers
heterogeneous and thermal mechanics; moving-surface work remains separate.

[Steady solver](#equations-and-boundary-implementation) · [Heterogeneous and thermal mechanics](#w07-step-3--heterogeneous-and-thermal-mechanics)

## Equations and boundary implementation

The [numerical core](../src/atlas_tectonics/regional_stokes.py) uses constant
positive Newtonian viscosity in a two-dimensional rectangular, incompressible,
plane-strain Stokes model. Coordinates are x-right and z-up from the box bottom;
positive pressure is compressive. It keeps the full symmetric-stress weak form,
not a componentwise Laplacian applied to arbitrary boundary conditions.

Normal velocities occupy cell faces, pressure and normal strain occupy cells,
and shear strain occupies vertices. Tangential velocities at the physical walls
are explicit trace unknowns. Half-cell derivatives and boundary quadrature are
included in the energy, prescribed-value lifts and applied traction. Both the
momentum and continuity right-hand sides receive the prescribed-velocity lift.
No mass-conservation row is dropped to fix pressure.

Each of the four sides declares one condition for each Cartesian component:
`velocity` or physical outward `traction` (= stress tensor times outward normal).
Normal velocity plus tangential traction implements slip; two velocities implement
no slip/imposed motion; two tractions give a mechanically open boundary.
Corner traces must agree. Free-corner auxiliary trace relations reproduce affine
motion; they are not substitutes for physical rigid-mode constraints.

If all normal velocities are prescribed, their integrated outward flux must be
compatible with incompressibility, and the numerical pressure has a specified
mean gauge. A normal-traction boundary fixes pressure physically; adding or
subtracting a mean afterwards is forbidden. Unconstrained rigid translations and
rotation are a separate issue: either constrain their named means or refuse.
Incompatible force/torque is not repaired by drag or altered boundary loads.

Both compatibility conditions are judged in the solver's own discrete quadrature,
not as continuum integrals. This was true from the start but was not stated here
until 1 October 2026 (R7); the gates themselves are unchanged. When all four
normal velocities are prescribed, each face-centre normal value stands for the
mean normal velocity over its whole face. The net outward flux is the sum of
those values times their face lengths, and it must cancel to within 1e-12 of the
summed absolute face fluxes, or of 1 in the solver's scaled units if that is
larger. The two corner samples of a side carry no flux. When the velocity
conditions leave rigid motion free and its named means constrain it, the body
and traction loads must exert no net force or torque on those free modes, to
within 1e-11 of their summed absolute contributions (with the same floor of 1).
The sums use the solver's weights: each body-force sample times the volume its
face owns (half a cell on a boundary face), each normal traction times its whole
face, and each tangential traction by the trapezoid rule over the boundary
vertices. These are midpoint and trapezoid rules, so point samples of a smooth
field that is exactly compatible in the continuum miss both conditions by a
quadrature error that is second order in the grid spacing and far above either
tolerance. They are refused with "prescribed normal velocity has incompatible
net boundary flux" or "external force/torque is incompatible with unconstrained
rigid modes". A caller supplies face-mean normal velocities, and loads that
balance under these weights. The tolerances are not a margin to loosen: the
discrete continuity equations sum to exactly this net flux, so a remainder
leaves them without a solution, and a net load on a constrained rigid mode would
be taken up by the constraint as the drag ruled out above.

The independent returned-field checks scatter stresses directly, rather than
reuse the assembled matrix multiplication. They check momentum, cell divergence,
gauge, boundary traces, rigid constraints and mechanical work. Dirichlet reactions
and applied traction work are included. Trace reactions are discrete integrated
forces; boundary-corner reactions must not be silently represented as a smooth
continuum traction distribution.

## Public SI interface and source binding

The public [execution wrapper](../src/atlas_tectonics/regional_execution.py)
exports `PreparedRegionalStokes2D`, `RegionalMechanicsScales`,
`RegionalReferencePressure` and `RegionalMechanicalSnapshot`.

Preparation requires grid counts, physical width/height, viscosity, component
boundary types, positive length/velocity scales, frame, vertical datum and material
source. The first implementation supports 2–64 cells in each direction; this is
its bounded verified route, not a permanent product-resolution policy. It never
changes resolution automatically. Forces, boundary values, snapshot time/epoch
and their source labels are supplied for each solve.

Force arrays occupy **complete** staggered faces: `(nz,nx+1)` for horizontal force
and `(nz+1,nx)` for vertical force, including half-volume boundary faces. Boundary
normal values are `[first corner, face centres..., last corner]`; tangential values
are at boundary vertices. Corner normal samples have zero face measure and serve
trace compatibility. `coordinates('u'|'w'|'p')` returns the relevant axes;
`coordinates((side,component))` returns paired boundary point coordinates.
Callbacks may generate input arrays, but the public plan stores sampled bytes,
not mutable callbacks as scientific inputs.
These coordinates say where a value is attached, not that a point sample taken
there is admissible: a face-centre normal velocity is used as its face's mean,
and the [compatibility checks](#equations-and-boundary-implementation) use the
discrete weights given there.

The scales are L0 and U0; viscosity supplies stress eta U0/L0 and body-force
eta U0/L0². Conversions refuse nonfinite values and nonzero underflow. The wrapper
rechecks the equations after dimensional velocity/pressure publication and
round-trip conversion. Outputs contain full normal/shear strain, deviatoric and
total stress, out-of-plane stress, pressure, velocities and boundary reactions.
Each field's staggered support is recorded.

A velocity-only numerical example can retain a declared zero-mean gauge, but its
pressure is not labelled absolute physical pressure. Providing a physical domain-
mean pressure defines that offset without imposing another momentum condition.
For the optional uniform reference density,
`P_ref=top_pressure+rho_g*(height-z)`, the wrapper subtracts its gradient from the
body force and adds `P_ref*n` to traction before solving. It reconstructs full
pressure/stress afterwards. Reference pressure has its own source, and the
velocity-only route still requires a physical mean datum. Nothing is counted twice.

The existing `ExecutionContext` checks current source bytes, loaded methods,
constants and runtime. Both new production modules participate in that identity.
Grid/material/scales/pressure policy/boundary types bind a plan; actual load bytes,
boundary values and provenance bind a snapshot. A changed world frame is an error,
not a relabelled result. Step 5 owns geological workflow/checkpoint assembly.

## Resources, execution and reuse

The public plan uses a 128 MiB child `WorkBudget` joined to the caller's budget,
one owning thread and the existing process-wide native single-thread lease.
Retained preparation, input/result buffers and iterative scratch are charged
before work. Explicit small direct references also need the conservative
`64*N² + linear` fill allowance. Admission is not an operating-system RSS cap.
Caller-held outputs and imported native libraries still need headroom.

Topology, sparse operators and numerical preconditioning/factors remain prepared
while their geometry, material and condition types remain fixed. Pure RHS/value
changes reuse them. One latest identical invocation can return the same immutable
snapshot after source/input checks; there is no growing history or another disk
cache. Changed input/provenance invalidates that latest result. Exceptions,
cancellation and close release the relevant reservations; a failed final check
cannot leave a newly accepted cached result.

Stress-site coefficients can later be replaced on a prepared plan
([Step 3](#w07-step-3--heterogeneous-and-thermal-mechanics)). A replacement that is cancelled or
fails between the start of its numeric refill and its acceptance leaves the plan
invalid: the solver core may hold coefficients that the plan's definition does
not name. Nothing is rolled back and the state is never cleared. Every operation
except `close` then refuses with "regional plan invalidated by an interrupted
coefficient refill; close it and prepare a new plan" (R7 repair, integrated 2 October 2026; before it this refusal read as a closed, active or wrong-thread
plan). Closed, active and wrong-thread calls are tested first and keep that
older refusal, so a call made while a refill is still running is not reported as
interrupted. The read-only `usable` property is False once the plan is closed or
invalidated, and also from the start of a numeric refill until it is accepted;
it does not report whether some other operation is active. An exception from a
coefficient update does not identify the material the plan holds, because the
closing cancellation/source check can raise after the new material was accepted.
A caller reads `usable`: when it is True the descriptor and plan ID name the
material held. An owner that keeps one plan across coefficient changes must
close an unusable plan and prepare another. The
[evolving-input interface](EVOLVING_MECHANICS.md) does that itself; the Picard
routes take a caller-owned plan, and that caller receives the refusal until it
does. The
[W07 workflow](W07_WORKFLOW.md#recovery-storage-and-resource-ownership) lends
its own plan to the dry-strength Picard route and replaces it itself.

The iterative solver uses the current coupled equations with bounded restarted
GMRES, velocity-block incomplete LU and a pressure-mass Schur approximation.
The first full-saddle ILU trial failed on refinement; replacing that helper leaves
the physical matrix unchanged. It has no automatic direct fallback or
tolerance relaxation. Small direct solves are an explicitly selected reference,
not a concealed production path. Old closed-wall Stokes solvers remain untouched.

## Independent reference and acceptance

The [Q2/P1-discontinuous reference](../tools/w07_fe_reference.py) is an independent
small finite-element implementation, not an Atlas production backend. Its
quadrature, full strain energy, pressure space, lifts and traction loads do not
use the MAC matrix. It reports full fields at arbitrary independent quadrature
points. The weak pressure-moment continuity residual and pointwise divergence
approximation error remain distinct. It refuses unresolved rigid modes and
oversized direct systems. Its 8×8-element reference allowance is 41,792,064 bytes;
16×16 is refused under the 128 MiB limit.

The [bounded runner](../tools/check_w07_mechanics.py) compares MAC 4/8/16 with
FE 2/4/8 on common physical quadrature and records error, unknown counts and elapsed
time. Different raw grid sizes alone are not a speedup comparison. The independent
analytic oracle defines the loads; neither discrete solver manufactures its own
reference RHS. The retained smooth free-slip case keeps its old gates. The new
no-slip vortex also receives the frozen 16/32/64 convergence check. Hydrostatics,
affine extension/translation, rigid rotation and traction-driven Couette test
pressure, stress, work and boundary signs separately.

Three rotating-order samples compare cold versus prepared changing-RHS sequences,
and separately cold versus verified-identical reuse. Setup and cleanup are
included; requested outputs are matched. Case/source hashes bind the report, and
source drift or any failed gate remains visible. No long convection run is needed.

### Obtained evidence

The [initial combined report](../evidence/w07-regional-mechanics-check.json)
preserves 230 passing checks and two failed FE boundary-adapter invocations.
Those failures returned a zero-dimensional array where the reference's scalar
callback contract requires a real scalar; no numerical tolerance was involved.
The runner adapter is corrected separately; successful checks and timings are
retained without rerunning them. The [focused correction report](../evidence/w07-regional-mechanics-controls.json)
passes all eight assertions, resolving both failed invocations with unchanged
production, oracle, FE and case identities. Couette/hydrostatic-traction maximum
field errors are 2.645e-13/7.105e-14. The original report deliberately retains its
FAIL status; the supplement is labelled `PASS_FE_CONTROLS_ONLY`, not a new full
run. **Together with the owner checks below, the two reports close Step 2.**

Independent owner checks also pass: nine core methods in 0.303 s; twelve public
execution plus nine shared source-identity methods in 6.116 s; seven FE methods in
0.311 s, with its tightened 1e-12 true-residual regression in 0.246 s. Mandatory
static checks pass 13 maps/41 paths and 30 safety tests (one Windows symlink skip).
These are method counts; the runner's individual assertions are not extra unit
test methods.

The no-slip B02 native weighted relative errors at 64×64 are **0.157992% velocity**
and **0.0178405% pressure**, below the frozen 1% gates. Both converge by more than
3.2× per refinement through 16/32/64. Retained B01 square and rectangular controls
pass their unchanged second-order gates. Exact pressure/traction, extension,
translation and rigid-rotation controls separately check the full-stress result.

### Backend decision and measured reuse

Retain the full-stress MAC route for the next implementation step. It meets the
frozen numerical gates, preserves cellwise continuity and fits the existing
staggered thermal/transport interfaces. The independent FE reference is retained
as a comparator. The common-quadrature results show the FE method's higher-order
velocity benefit, not a universal MAC accuracy advantage:

| Method/grid | Solved unknowns | Velocity relative error | Pressure relative error | Setup + complete solve, seconds |
| --- | ---: | ---: | ---: | ---: |
| MAC 4×4 | 41 | 17.0955% | 9.97220% | 0.0087451 |
| MAC 8×8 | 177 | 5.34188% | 2.06199% | 0.0053808 |
| MAC 16×16 | 737 | 1.44736% | 0.415775% | 0.0068105 |
| Q2/P1-disc 2×2 | 31 | 16.1654% | 11.1235% | 0.0096679 |
| Q2/P1-disc 4×4 | 147 | 2.19336% | 2.82955% | 0.0254303 |
| Q2/P1-disc 8×8 | 643 | 0.276252% | 0.710451% | 0.0850874 |

All rows use the same independent analytic solution and 9,216 physical quadrature
points. Gauge-free pressure is explicitly mean-aligned on those points; normal
traction controls are not aligned. These reconstruction errors are distinct from
the native-grid refinement errors above. The FE full counts before eliminating
prescribed values are 63/211/771; the table consistently uses solved counts.
Costs are single-run observations, include method-specific load preparation as
recorded, and exclude common-grid evaluation. They do **not** establish a
cross-method speedup or a production FE performance limit. In this small smooth
comparison MAC 16×16 is both more accurate and cheaper than FE 4×4, while FE 8×8
resolves velocity more accurately than MAC 16×16. No resolution is silently chosen
from these results. No extra framework is adopted on this evidence.

The public API's **three-output 32×32 sequence** was timed in three rotating-order
samples. Native velocity/pressure errors are 0.630518%/0.0712547%; all numerical
gates pass and the compared published arrays are byte-identical.

| Matched workload | Cold median | Reuse median | Time saved | Saving |
| --- | ---: | ---: | ---: | ---: |
| Three changing loads; retain prepared solver | 0.7493145 s | 0.4133227 s | 0.3359918 s | **44.8399%** |
| Three identical requests; verify latest result | 0.7460721 s | 0.3466732 s | 0.3993989 s | **53.5336%** |

Preparation, input sampling, all three requests, immutable-output hashing and
cleanup are included; process/import startup is excluded. Raw samples and
first-minus-median differences remain in the report. These are measured regional
workflow savings, not whole-generator percentages. Peak reserved work was
82,657,280 bytes under 134,217,728; zero held bytes and zero refusals at completion.
The runtime was Windows 11, Python 3.12.14, NumPy 2.4.6, SciPy 1.17.1 and one native
numerical thread. Linux execution is not asserted by this Windows result.

### Reproduction and source identities

From the Atlas root with its existing scientific Python environment:

```sh
python -B tectonics/tools/check_w07_mechanics.py --report NEW-report.json
```

An existing report is never overwritten. Optional `--acceptance-only` and
`--timing-only` modes label their subset explicitly. This delivery's focused
correction used `--fe-controls-only --prior-report` with the original report;
it checks the exact prior failure set and unchanged non-runner identities before
running only the two affected controls. No successful numerical work was repeated.
The combined process took 9.473 s; the corrective process took 1.193 s. An earlier
report-open permission refusal happened before numerical work and created no
report; it was corrected through the reviewed execution permission mechanism.

- Initial report SHA-256: `3e366d93bceea4c4f40fdf07e64475c8fdb9d3d518cc07ba05a47a95d50adef7`.
- Corrective report SHA-256: `60a786aa224d1996220f58e1c1b7c6fe555ca18b1e32ebb9b8e43e6e1ad962ed`.
- Final runner SHA-256: `fc06d95a9e172ea6ef9462b5a142ced417f8e1b4d6c666ed40c81f6605223c91`.
- Production core SHA-256: `a9bfae5ff6f03da1d2f2e22d1cddf05665da330dbd0891ffd77a5b7054ae64b9`.
- Public wrapper SHA-256: `f3400f9434790a6a4c951fb7d8b5a4ae51d911b381dc649642d94b3a9a5ddf75`.

Both reports retain complete source inventories. The supplement binds the
original report and both runner versions; the correction changes only the
reference callback adapter and reporting/targeted-run route, not solver outputs,
equations, gates or grids. The frozen Step 1 document/case register are unchanged.
The later [Step 3 implementation](#w07-step-3--heterogeneous-and-thermal-mechanics) supplies
heterogeneous stress-site properties, sharp-interface checks, compatible
thermal/material transport and the selected nonlinear laws. This Step-2 result
does not independently qualify those extensions.

## Papers and software checked

- [May, Brown & Le Pourhiet (2014), pTatin3D, Section II](https://jedbrown.org/files/MayBrownLePourhiet-pTatin3d-2014.pdf):
  stable Q2/P1-discontinuous pairing, full-stress weak form and pressure treatment.
  Selected full text; independently implemented rectangular 2D comparator.
- [PETSc DMStag ex2 source](https://petsc.org/release/src/dm/impls/stag/tutorials/ex2.c.html):
  staggered geometry, explicit prescribed normal flow and manufactured controls.
  Its force-sign convention and toy preconditioner are not blindly transferred.
- [PETSc nullspace documentation](https://petsc.org/release/manualpages/Mat/MatNullSpaceCreate/):
  explicit pressure/rigid nullspaces, rather than an arbitrary dropped equation.
- [PETSc field-split/Schur documentation](https://petsc.org/release/manualpages/PC/PCFIELDSPLIT/):
  separate velocity/pressure preconditioning, full block factorisation and the
  pressure-block sign. The coupled operator and returned-field gates stay intact.
- SciPy [GMRES](https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.linalg.gmres.html)
  and [sparse LU](https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.linalg.splu.html)
  documentation: true-residual criterion, iteration callback/restart semantics and
  sparse factor reuse. Execution uses the installed SciPy 1.17.1, not a new install.
- The prior [Step 1 source review](W07_REGIONAL_MECHANICS.md#9-papers-and-existing-software-checked)
  supplies the LaMEM/ASPECT comparison and later surface/strength choices. These
  sections were not rerun as external software for Step 2.

No external geodynamic framework was installed or executed; no third-party
implementation was copied into the solver.

## W07 Step 3 — heterogeneous and thermal mechanics

23 September 2026. **scoped Step 3 complete.**
Change ID: `ATLAS-W07-3-20260922` (work began 22 September).
The [Step 1 specification](W07_REGIONAL_MECHANICS.md) and
[case register](../cases/w07_mechanics.json) remain frozen. This supplements the
[Step 2 record](#equations-and-boundary-implementation); its historical reports are not rewritten.

### Implemented

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
  Since the R7 repair (1 October 2026 candidate) the refusal says so: "regional
  plan invalidated by an interrupted coefficient refill; close it and prepare a
  new plan". Before, it read as a closed, active or wrong-thread plan. That older
  refusal is still tested first, so a call made while a refill is running is
  refused as active, not as interrupted. A read-only `usable` property is False
  once the plan is closed or invalidated, and while a numeric refill is running.
  An exception from a coefficient update does not say which material the plan
  holds: it can come before anything changed, from inside the numeric refill, or
  from the closing cancellation/source check after the new material was accepted.
  Callers read `usable`; when it is True the descriptor and plan ID name the
  material held. Nothing is rolled back, and the invalid state is not cleared.
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
  A prescribed face temperature shapes the limited advective normal slope only
  on inward relative faces; it must equal the inflow temperature there or the
  step is refused. On outward faces, the slope comes from the adjacent interior
  cell only when that inner face also carries fluid towards the boundary (or is
  stationary). This one-sided extrapolation preserves affine through-outflow.
  It falls back to a constant normal reconstruction at closed faces, where both
  normal faces export during a turn, or when extrapolation would be nonpositive.
  Thus a conducting wall cannot change the advective reconstruction on a closed
  or outward face. Its heat enters through the half-cell conductive flux.
  The existing `2*outgoing` timestep allowance covers the extra half-slope loss;
  shared interior fluxes, SSP-RK2 accounts and all acceptance tolerances remain
  unchanged. No temperature is clipped after an update. At zero conductivity
  the wall temperature does not widen the source-free maximum-principle bounds;
  at positive conductivity it remains a legitimate conductive bound. The
  focused regressions cover both extrema on every side, closed and turning
  outflow, zero/subnormal/tiny conductivity, affine outflow and heat closure.
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

#### Explicit coupling support

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

### Independent references and source correction

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

### Proportionate verification

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

**Repair note (R7, 1 October 2026 candidate).** The table and counts above are
the 23 September record and are not rewritten. The interrupted-refill repair
adds three methods in their own class of `test_w07_material_execution`: the
interrupted plan refuses `solve`, `coordinates` and `update_viscosity` with the
new text until it is closed, and afterwards as closed; a call made during a
healthy refill, from the driving thread and from another thread, is refused as
active while `usable` reads False, the refill then completes, and `usable` reads
True until that never-interrupted plan is closed and False afterwards; and one
exception type raised before, during and after the numeric refill leaves three
different states that only `usable` and the descriptor tell apart. The existing
`test_refill_failure_is_closed_to_scientific_reuse` is unchanged and still
passes. Run in the repair's scratch candidate on Windows/CPython 3.12.14 only.

Initial bridge failures were missing reader labels, scalar/zero-dimensional array
conversion, scalar hash handling, JSON infinity, and an exact-equality assertion
on accumulated floating-point origin. They were corrected without changing
numerical gates. A source-heated open-flow test was corrected to account for cold
inflow, not assume spatially uniform heating. Only affected tests were rerun.
Final review detached initial temperature once and admitted adapter supports
before copying; the targeted checks above cover these final changes.

### Measured reuse

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
Report SHA256: `05a345db8cc2dc8cac61c313e96dd855230bc2744abd6dcf01e6e27fbff97334`.
The first restricted report-open attempt failed before computation; one reviewed
escalated invocation completed. No historical report was overwritten.

### Papers and software actually checked

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
- For the R7 heat-boundary correction, the [Clawpack boundary documentation](https://www.clawpack.org/bc.html)
  and solver page above were consulted on 2 October 2026 for outflow extrapolation
  and reconstruction context. The conditional interior one-sided slope and its
  constant fallback described above are an Atlas derivation, not Clawpack's
  copied-cell ghost-boundary algorithm or a newly checked external benchmark.

No external framework was installed or executed; no generated third-party solver
source was copied. The later [Step 4 surface/strength response](W07_SURFACE_STRENGTH.md)
and [Step 5 assembled workflow](W07_WORKFLOW.md) have their own reduced-model
results. Physical localisation and whole-world acceptance are not established by
those bounded routes; R4.4 retains its hold.
