# W07 Step 2 — regional steady mechanical solver

WORKING NON-CANON. Implementation and acceptance record, 22 September 2026.
Completion status: **STEP 2 COMPLETE; bounded numerical acceptance and reuse measured.**

The [Step 1 design](W07_REGIONAL_MECHANICS.md) remains frozen. This increment
implements its basic regional mechanics and independent method comparison, not
the heterogeneous, thermal or moving-surface extensions assigned to later steps.

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

- Initial report SHA-256: `cf7530f46e44c4e9df3d6f67ff25b885e13e023165d9a42e8cf0e0d66248a00c`.
- Corrective report SHA-256: `c06858c723dd4c0386ab8f8e88cd3d0d8885e0a4f2d5ce71038a313329268787`.
- Final runner SHA-256: `fc06d95a9e172ea6ef9462b5a142ced417f8e1b4d6c666ed40c81f6605223c91`.
- Production core SHA-256: `a9bfae5ff6f03da1d2f2e22d1cddf05665da330dbd0891ffd77a5b7054ae64b9`.
- Public wrapper SHA-256: `f3400f9434790a6a4c951fb7d8b5a4ae51d911b381dc649642d94b3a9a5ddf75`.

Both reports retain complete source inventories. The supplement binds the
original report and both runner versions; the correction changes only the
reference callback adapter and reporting/targeted-run route, not solver outputs,
equations, gates or grids. The frozen Step 1 document/case register are unchanged.
Next: Step 3 heterogeneous stress-site properties and sharp-interface checks,
then compatible thermal/material transport and the selected nonlinear laws.

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
