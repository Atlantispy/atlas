# Finite-region three-dimensional mechanics

Status: WORKING NON-CANON. This is an implemented same-time mechanical solver
and finite-mode force connection, not a generated rift or evolved planet.

## Responsibility and inputs

`atlas_tectonics.regional_execution3d.PreparedRegionalStokes3D` solves an
axis-aligned finite Cartesian box. x and y are horizontal; z increases upward
from the bottom. All three velocity components are solved. The caller supplies
positive viscosity at volume quadrature points, body force, optional retained
symmetric deviatoric extra stress, and velocity or outward traction for every
component on all six faces. One shared nodal velocity trace avoids contradictory
edge/corner copies. Material, frame, datum, parent state, epoch and forcing
identities accompany the arrays. Public inputs and outputs use SI units.

The geometry, viscosity and boundary-condition pattern are fixed in a prepared
plan. Changing them requires a new plan; changing a force can reuse its matrix
and factor. The constitutive producer owns effective viscosity and retained
stress. This solver does not guess geological defaults or reset those histories.

## Equations and discretisation

With D = (grad(u) + grad(u)^T)/2 and supplied extra stress S:

```text
sigma = 2 eta D + S - p I
-div(sigma) = f,             div(u) = 0
outward traction = sigma n
```

The weak momentum equation is
`integral(2 eta D(u):D(v) - p div(v)) = integral(f.v) + integral(t.v) - integral(S:D(v))`.
This includes cross-component derivatives; three independent scalar Laplacians
would be wrong for spatially varying viscosity. Trilinear pressure (Q1) and
triquadratic velocity (Q2) use a regular hexahedral Taylor-Hood mesh, with three
Gauss points per direction. Incompressibility is imposed in the pressure test
space, not claimed to vanish pointwise at every quadrature point. A pressure
jump is not exactly representable by continuous Q1 and needs refinement evidence.

The matrix has velocity block A and divergence block B = -integral(q div(u)).
Prescribed velocities are eliminated without modifying the original equations
used to recover reactions. A volume-weighted pressure-mean constraint is added
only when a constant pressure is genuinely undetermined. Incompatible net
boundary flux is refused, not projected away. A numerical zero mean is not a
physical pressure datum; `physical_pressure_pa` is available only with an
explicit mean pressure or normal-traction conditions that determine it.
Unconstrained rigid translations/rotations are refused rather than hidden pins
being added.

## Solving and safe reuse

Length L, speed V and reference viscosity eta0 define internal units. Stress
scales as eta0 V/L, body force as eta0 V/L^2, integrated force as eta0 V L,
and power as eta0 V^2 L. These are full 3D forces/powers, not per-unit-strike values.
The normal path is GMRES with an incomplete velocity-block factor and a
viscosity-weighted pressure-mass diagonal. A separately selected sparse direct
method supplies small independent comparisons; a failed iterative solve never
silently switches to it. The fixed tolerances are linear relative residual
2e-9, mechanical-work residual 5e-9 and coupled-force residual 5e-8. GMRES asks
for relative tolerance 1e-11, absolute tolerance 1e-13 and at most 1,200 iterations.

Assembly reuses a sparse structure instead of retaining dense contributions
for every element. Memory is admitted before mesh/factor construction and actual
factor storage is checked afterwards. Admission is an accounting bound, not an
operating-system RSS guarantee. Cell counts 2-24 per direction are interface
limits, not a promise every such grid fits the selected memory budget.
Cancellation, loaded-source identity, single-owner use and closure are checked.
Only the latest immutable result and one finite-mode response are retained;
there is no growing history cache. Caller-retained snapshots remain caller storage.

## Force-driven connection

`solve_force_coupled` accepts one to twelve declared boundary displacement modes.
A mode in metres multiplied by its unknown rate in 1/s gives velocity. Its
conjugate force has units joules (a rotation mode gives torque); force times
rate gives watts. Solving each independent mode gives a regional resistance
matrix. The same regional matrix and factor serve the whole calculation.

The connection solves regional reaction plus explicitly separate exterior
resistance against supplied driving forces. More resistant material therefore
changes the resulting motion; regional speed is not just prescribed and then
reported as force-driven. The exterior contribution must not duplicate physics
inside the box. Reciprocal work, independent resisting modes and the final
force residual are checked. Regional reactions are forces applied to the region;
the equal-and-opposite force acts on the surrounding plates.

This is not yet the spherical plate-to-region mapper. Mapping actual plate modes
and forcing into many regions, returning their torques, and accepting one shared
world state belong to I04/I07/I09. Transport, nonlinear constitutive iteration,
surface motion, thermal history and physical boundary birth remain separate
connections, not implicitly supplied by a linear mechanical solve.

## What checks establish

The element tests independently check interpolation, derivatives, symmetry,
full-stress assembly, quadrature, interface loads, traction work and cancellation.
The prepared-solver tests use exact affine, genuinely 3D heterogeneous, hydrostatic,
mixed-traction and layered-shear solutions; retained extra stress; dimensional
rescaling; direct/iterative agreement; and a non-polynomial refinement case.
Force-driven controls change viscosity and driving force against an analytical
response. Refusal and reuse tests cover net flux, source changes, resources,
mutable inputs and pressure assumptions. These check implementation and bounded
resolution, not calibration against a geological event.

The separate Local Generator Engineering chat supplied independently derived
smooth-polynomial and layered pressure-jump cases. They are prospective continuum
checks, not published benchmark data or an executed cross-code comparison.
In particular, the pressure-jump case must not be required to fit continuous Q1
exactly. This delivery retains an exactly representable layered-shear control.

`tools/check_regional3d.py` records exact-field controls and cold/prepared/cache
timings with source bindings; refinement is checked in the focused tests.
Its matched outputs and admitted workload matter:
a small-grid reuse percentage is not a whole-planet runtime forecast. Old W07
and W10 receipts are not rebound or promoted by these new checks.

## Research and software checked

- [FEniCSx Stokes demonstration](https://docs.fenicsproject.org/dolfinx/main/python/demos/demo_stokes.html):
  Taylor-Hood spaces, pressure nullspace and block solution. Its pressure-sign
  convention is explicitly different; Atlas retains sigma = viscous - p I.
- [ASPECT numerical methods](https://aspect-documentation.readthedocs.io/en/latest/user/methods/numerical-methods.html):
  stable mixed elements, block preconditioning and resolving different length
  scales. Atlas has not acquired ASPECT's adaptive/distributed implementation.
- [PETSc DMStag example 4](https://petsc.org/release/src/dm/impls/stag/tutorials/ex4.c.html):
  an actual 3D variable-viscosity Stokes implementation, dimensional scaling and
  pressure-nullspace handling; not the finite-element backend used here.
- [Bleyer's consistent reactions](https://bleyerj.github.io/comet-fenicsx/tips/computing_reactions/computing_reactions.html):
  recover forces from the original weak residual. The example concerns elasticity;
  its virtual-work principle informs the reaction calculation, not a rock law.
- [SciPy sparse LU](https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.linalg.splu.html):
  factor reuse and sparse storage for the explicitly bounded direct comparison.

The implementation is original Atlas code. These sources explain method choices;
they are not claims that their software was installed or benchmarked locally.
