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
only when a constant pressure is genuinely undetermined; that test compares the
pressure leak with the divergence entries themselves, so a small open (traction)
box is never mistaken for a closed one. Incompatible net boundary flux is
refused, not projected away: the net flux must be below `2e-11` of the
integrated absolute normal boundary flux, `integral(|u.n|)` over the six faces,
plus the binary64 rounding bound of the computed sum. A numerical zero mean is not a
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
for relative tolerance 1e-11 of the right-hand side (absolute tolerance 0, so
SciPy's stopping target is purely relative) and at most 1,200 iterations.

Every gate is relative to its own operands, with no absolute floor, so the
caller's choice of L, V and eta0 cannot make a gate pass by shrinking the
numbers. (Scales still set conditioning: a badly chosen scale can make a solve
refuse, and the forward error of an accepted solve is its backward error times
the conditioning of the scaled system.) The right-hand side is normalised to unit
size before GMRES or the direct solve, so SciPy's internal 2-norms cannot
underflow or overflow. A forced problem whose right-hand side is zero or below
about 1e-281 after scaling is refused, as is nonzero forcing that underflows to
zero in assembly; an exactly unforced problem has the exact zero solution.

In a closed box the zero-mean pressure gauge is enforced exactly after every
solve (the gauge weights sum to one and `B_f^T 1 = 0`, so velocity is
unaffected); no gate would otherwise see a constant in pressure units. When the
velocity is below 1% of the magnitude the load implies (a load-dominated state,
such as full rho*g balanced by pressure), the solution is refined up to twice:
a relative stop on the whole right-hand side otherwise leaves the small driving
velocity inaccurate. If any gate still fails, up to two further working-precision
refinement steps are taken before refusing; fixed-precision refinement is a
standard way to recover componentwise backward stability for an accurate but
badly scaled solve (Skeel's 1980 analysis, cited from background knowledge and
not re-read for this change). A first GMRES solve that does not converge is
refused. A refinement correction that reaches the iteration limit is kept only if
it lowers the worst gate ratio: discarding such corrections refused well-scaled
problems (a buoyant inclusion at contrast 1e4) whose corrected solution passed
every gate. Refinement never changes a gate, and the published solution always
faces all of them. Three linear gates must then all pass:

- the combined relative residual `||K x - rhs||_inf/||rhs||_inf <= 2e-9`;
- the momentum block, row by row: `|r_i| <= 2e-9 (|A||u|)_i + 256 eps (|B^T||p| + |load|)_i`
  on the free rows. Pressure and load enter only at their round-off level
  because in a load-dominated state they cancel; at full weight they admitted
  velocity errors of 1e-5 when rho0 = 3300 drove a density anomaly of 0.01;
- the continuity block, row by row: `|B u + w lambda|_i` against
  `(|B|(|u| + 64 eps/2e-9 U*))_i + w_i |lambda|`, where `U*` is the momentum
  scale divided by the largest free-row sum of `|A|`, the velocity magnitude the
  momentum block implies. Only its round-off share enters: in a hydrostatic state u itself is
  round-off, while a larger share let an inflated pressure-balanced scale hide
  continuity error.

Rows are judged componentwise (Oettli-Prager form), each against its own
magnitudes, because normalising by the largest row let a weak layer's rows go
unchecked: a velocity error confined there was accepted at 2e-5 (viscosity
contrast 1e4) and 1e-4 (contrast 1e6). Rows below 1e-8 of the largest
magnitude are judged at that floor. Blockwise checks matter because one dominant
block can otherwise hide the other inside the combined norm.

A declared physical mean pressure is added to the pressure after solving, and
every gate and the work identity use the zero-mean solution: in a closed box the
datum cannot change velocity, whereas inside the right-hand side a 3 GPa datum
dominated every relative target and let GMRES move the velocity by 2.5e-7, and
inside the gate magnitudes it loosened them. Reactions are then recomputed with
the datum included.

The work identity is a consistency check between the published quadrature
fields and the assembled operators. In exact arithmetic its error equals the
momentum residual weighted by velocity, which the momentum gate already bounds,
so that exact term is subtracted. What remains must be `<= 5e-9` of the larger
side of the power balance (viscous, extra-stress and pressure power against
body, traction and constraint power), never of `max(1, ...)`. For rigid or
exactly balanced states, whose powers are all round-off, the only floor is 64
binary64 units on the magnitudes actually multiplied (`|A||u|`, `|B^T||p|`,
loads and reactions, and a shape-derivative bound for quadrature powers). A
forced solve whose powers underflow to zero or overflow is refused. The identity
detects a mis-scaled or mis-assembled symmetric strain rate (an injected scale
error of 2e-9 or a symmetric-part error of about 1e-7), but it cannot see an
error in the antisymmetric (spin) part of the gradient, in the velocity
interpolated to quadrature points, or in the scaling of the published pressure,
because those enter neither side of the balance it compares. Those outputs rely
on the exact-field and manufactured-solution tests instead.

Before 30 September 2026 (review finding s11-1) GMRES used an absolute tolerance
of 1e-13 and both gates were floored at 1. A problem posed in SI with unit scales
therefore returned velocities 2.6e-4 away from the direct answer, or exactly zero,
while reporting residuals near 1e-14. Intermediate candidates of this repair were
shown by adversarial verification to accept rigid fields with 225-8210% error at
badly chosen scales (combined residual only, with a work floor that absorbed the
residual), to let a datum or a hydrostatic load loosen the gates, to miss
weak-layer errors and to refuse well-scaled problems by discarding an unconverged
correction; the rules above close those cases. Scratch probes on the candidate
(Windows, CPython 3.12.14; not acceptance) found accepted velocity errors of at
most 3.5e-9 over a 430-case sweep of layered, inclusion and random viscosity
contrasts 1e3-1e6 with badly chosen reference viscosities, and 5.0e-9 over 192
lithosphere/asthenosphere solves with full rho*g, extra stress and four boundary
sets. Random-sign errors injected into momentum or continuity rows were accepted
only up to about 1e-10.

The gates bound backward error, not forward error. An adversarial residual that
fills each gate in the worst direction, with refinement disabled, was accepted
with velocity errors of 1.2e-8 in a uniform box and about 2e-9 times the
viscosity contrast in a layered one (1.85e-6 at contrast 1e4). A load-dominated
state has a floor of about eps times the ratio of the load-implied velocity to
the actual velocity, a property of solving the full pressure in binary64 that a
refined direct solve shares: it reaches 1e-8 only when rho0/delta-rho exceeds
about 1e7. Deliberately mis-scaled choices (for example L = 1e-3 m with
eta0 = 1e30) are refused, and GMRES alone refuses some strong-contrast cases
(layered contrast 1e6 at 4x4x4 did not converge) that the direct method solves.

Assembly reuses a sparse structure instead of retaining dense contributions
for every element. Memory is admitted before mesh/factor construction and actual
factor storage is checked afterwards. Admission is an accounting bound, not an
operating-system RSS guarantee. Cell counts 2-24 per direction are interface
limits, not a promise every such grid fits the selected memory budget.
In practice the assembly reservation alone is 8 MiB plus 420,000 bytes per cell
plus 3,000 bytes per velocity unknown (three per Q2 node) and per pressure node,
before the separate factor allowance. For cubes that is about 176 MiB at 7x7x7
and about 257 MiB at 8x8x8. The default GMRES route then reserves an
incomplete-factor allowance of 160 bytes per nonzero of the free velocity block
plus 1,024 bytes per free velocity unknown, so it grows as fewer velocity
components are prescribed. At 6x6x6 the factor allowance is about 85 MiB with all
faces velocity-prescribed, 131 MiB with free-slip faces and 151 MiB with only the
base velocity-prescribed (combined about 200, 246 and 265 MiB); at 7x7x7 even the
all-velocity case needs about 325 MiB. The default 256 MiB budget therefore
refuses every 7x7x7 cube and admits 6x6x6 only for velocity-dominated boundaries
(measured 29 September 2026; an earlier 28 September estimate of 7x7x7 counted
assembly only). The 24x24x24 interface limit would need about 6.9 GB (6.4 GiB)
for assembly alone. Larger grids need an explicitly larger budget and machine;
nothing is subdivided or coarsened automatically. The connected evolution
fixture is 3x3x3.
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

The adapter below now maps actual Euler plate modes into one declared region
and returns its torques. Assembling many regions and accepting one shared
world state still belong to I04/I07/I09. Transport, nonlinear constitutive iteration,
surface motion, thermal history and physical boundary birth remain separate
connections, not implicitly supplied by a linear mechanical solve.

### Planet-centred plate motion and returned torques

[`PreparedPlateBoundary3D`](../tools/regional_plate_coupling.py) connects existing
native `PrescribedPlateMotion` records to this solver. The caller supplies a
stationary, right-handed orthonormal local frame Q, a planet-centred origin r0
and one owner for each plate-controlled velocity node. With column-vector notation:

```text
r = r0 + Q x
u_local = Q^T (omega_global cross r)
torque_on_region = sum_owned_nodes r cross (Q reaction_local)
torque_on_plate = -torque_on_region
power_into_region = omega_global dot torque_on_region
```

All three components are retained, including the contribution from the actual
planet-centred origin. Plate ownership requires three prescribed velocity
components; partially constrained or interior nodes cannot masquerade as full
plate control. Unowned fixed supports have separate, explicit velocities. Their
reactions are not attributed to plates. Corner nodes have one owner, not one per
face. Tractions remain separate native inputs, not a second copy of plate drag.

Prescribed solves check plate order, global frame, epoch, time and native motion
provenance. Force-driven solves use all three Cartesian angular components for
each of one to four plates (the native twelve-mode limit), full supplied external
torques and an explicit exterior resistance matrix. No axis is silently locked
or discarded. The returned immutable exchange binds the mechanical snapshot,
mapping/source identity, angular rates, both torque signs and each plate's power.
The native conditioning, incompatible-flux and conservation refusals still apply;
a geometrically small or insufficiently resisted rotation can be inadmissible.

In a closed box without a declared mean pressure, the pressure is known only up
to a constant c, and c shifts the torque projected on each plate mode by
`-c` times that mode's net boundary flux. Totals and flux-free generalized forces
stay gauge-free and the native snapshot still publishes
`velocity_constraint_reaction_n` with `physical_pressure_defined=False`. The
adapter therefore refuses per-plate torques in that case unless every owned
plate mode is net-flux neutral (`1^T B m = 0`, tested with the closed-box flux
tolerance and recorded as `mode_net_flux_neutral`). Before 30 September 2026
(review s11-2) such torques were published as if the mean pressure were zero; in
the test box a 1000 Pa constant moves them by 39,000 and 18,000 N m. Declaring a
physical mean pressure, or traction faces, makes them physical.

The torque is the transpose of the same discrete velocity map acting on the
native nodal reactions. It therefore preserves virtual work without interpolating
stress onto another boundary or multiplying integrated nodal forces by area again.
Prepared displacement modes and the native factor/response are reused; no large
mechanical result is duplicated by the exchange wrapper. An explicit adapter
buffer allowance is separate from the native solver budget and is not an RSS cap.

This is an explicit flat-box embedding of instantaneous Euler velocities, **not
a curved spherical mesh, moving reference frame, automatic plate ownership,
regional time step or planetary assembly**. Domain curvature and evolution must
be handled by their owners before this becomes a world-scale calculation.

Focused tests independently check the cross-product mapping, multiple owners,
rotated axes and planet-scale offsets. An exactly representable twisting column
has nonzero strain: on a 2 by 3 by 4 m box with viscosity 2 Pa s and angular speed
0.5 rad/s, its plate torque is 1.625 N m and mechanical power 0.8125 W.
Both prescribing that rotation and solving for it from torque recover the same
analytical answer. Invalid ownership/frames/time, overflow, cancellation and source
drift are refused. Repeated torque solves retain one factor and reuse the response.
These are synthetic implementation controls, not geological calibration.

## What checks establish

The element tests independently check interpolation, derivatives, symmetry,
full-stress assembly, quadrature, interface loads, traction work and cancellation.
The prepared-solver tests use exact affine, genuinely 3D heterogeneous, hydrostatic,
mixed-traction and layered-shear solutions; retained extra stress; dimensional
rescaling; direct/iterative agreement; and a non-polynomial refinement case.
Scale controls solve one heterogeneous problem at load amplitudes 1 to 1e-14 and
one SI problem under length scales 1e-3 to 1e5 m: GMRES must match the direct
oracle to 1e-9 or be refused. A 5% net inflow into a closed box must be refused
with unit and physical scales alike, and a small traction box must not acquire a
pressure gauge. A scratch sweep of 64 scale combinations on two boundary types
found 28 accepted wrong answers before the change and none after; badly
conditioned choices (dimensionless viscosity 1e-9 with an open top) are refused.
Further controls cover rigid translation, rotation and boundary shear at badly
chosen scales (accurate to 1e-8 or refused), a 3 and 10 GPa pressure datum
(velocity unchanged to 1e-9, pressure shifted by the datum) and underflowing
forcing or power (refused, not published as zero). A rho0 = 3300 load driving a
0.01 density anomaly must give the anomaly's velocity to 1e-8 with either method
(baseline GMRES was 8.6e-6 away); a momentum-row error confined to a weak layer
(contrast 1e4) must be refused when refinement cannot repair it and repaired when
it can; a reference viscosity at the weak end of a 1e5-1e6 contrast must, with
the direct method at 4x4x4, be refined to an accurate solution rather than
refused; and a buoyant weak inclusion (contrast 1e4) whose GMRES correction
reaches the iteration limit must be accepted and match the direct solution to 1e-8.
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
- [pyGPlates velocity calculation](https://www.gplates.org/docs/pygplates/generated/pygplates.calculate_velocities):
  rotation-derived global velocities and explicit local-coordinate conversion
  informed the adapter. Atlas consumes instantaneous SI Euler rates, not a finite
  stage rotation or pyGPlates' geological-time unit convention. Bleyer's reaction
  example above also informed the work-preserving torque return.

The implementation is original Atlas code. These sources explain method choices;
they are not claims that their software was installed or benchmarked locally.
