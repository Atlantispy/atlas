# The separate force-driven experiment

[Guide contents](../HOW_TECTONICS_IS_MADE.md) ·
[Prescribed regional processes](02-tectonic-processes.md)

The R3/R4 work asks a different question from the seeded world creator: can
temperature, composition and material behaviour drive a consistent flow, rather
than having plate motion supplied? It is a retained rectangular experiment, not
the current mechanism that generates an entire planet's plate network. Its
component implementations exist; the mature-convection R4.4 acceptance remains
held and incomplete. W08's subduction benchmark is a different experiment.

## 1. Specify how material resists deformation

**Inputs and outputs.** Temperature, depth and strain rate, plus an explicit
material-law choice, produce viscosity and strength diagnostics. The registered
laws use dimensionless temperature/depth and require named scales for SI values.
Room-temperature reference rock properties are not silently extrapolated into a
mantle-flow law.

The Tosi law family varies resistance with temperature/depth and, in selected
cases, deformation rate. The Becker–Fuchs subset adds strain-memory-dependent
weakening and thermal healing. A material-point update accumulates deformation
and removes memory by the declared healing law. The stored history is not clipped
when its effect on strength saturates. Its exact interval formula assumes fixed
rate and temperature over that interval, not arbitrary evolving conditions.

**Research and evidence.** These choices are recorded against
[Tosi et al. (2015)](https://doi.org/10.1002/2015GC005807) and
[Becker and Fuchs (2023)](https://doi.org/10.1029/2023GC011179).
The latter's full spherical experiment, continent model and time rescaling are
not reproduced. The source preserves each paper's strain-rate convention rather
than treating superficially similar yield formulae as interchangeable.
[Constitutive tests](../../tests/test_constitutive_r3.py) compare independent
scalar evaluations, limiting cases and memory updates. Read the
[exact selected-source contract](../../cases/physical_closure_r3.json) alongside
[the implementation](../../src/atlas_tectonics/constitutive.py).

## 2. Keep a physical smoothing length distinct from cell size

An optional one-dimensional nonlocal operator averages the strength-relevant
history over a declared physical length. Halving the grid spacing must not halve
that physical length. The finite-volume system is solved with a reusable banded
factor; raw history is retained separately so repeated inspection does not keep
diffusing it.

This is an explicitly Atlas-selected extension, not an equation attributed to
Becker and Fuchs. Constant-field, integral, positivity and modal-refinement checks
support the operator. They do not prove realistic, grid-independent shear-band
width in a coupled two- or three-dimensional model. See
[damage regularisation](../../src/atlas_tectonics/damage_regularisation.py) and
the [R3 verification entry point](../../tests/check_constitutive_r3.py).

## 3. Calculate velocity and pressure from forces

**Inputs and outputs.** A rectangular domain, viscosity, density anomaly, gravity
and boundary conditions produce velocity in m/s and pressure in Pa. Density
variation drives buoyancy, while the selected Boussinesq model otherwise uses
constant reference density for the represented conservation equations.

Pressure and velocities live on different parts of a staggered mesh. The solver
balances forces and enforces incompressibility, with an explicit pressure
reference. Constant-viscosity controls have their own prepared solver. With
variable viscosity, Atlas differentiates the full stress field; simply multiplying
an old constant-viscosity Laplacian by a new viscosity would omit terms.

Nonlinear iteration repeatedly solves for motion and recalculates viscosity from
that motion. Acceptance checks the updated material law and the actual returned
fields, not just convergence of an earlier linear approximation. An unsupported
or unconverged request fails rather than silently changing the law.

**Basis and checks.** The selected Tosi convection formulation is also documented
by [ASPECT's benchmark implementation](https://aspect-documentation.readthedocs.io/en/latest/user/benchmarks/benchmarks/tosi_et_al_2015_gcubed/doc/tosi_et_al_2015_gcubed.html),
a reference rather than an Atlas runtime dependency. Independent sparse operators,
manufactured fields, divergence, work balance and pressure-reference controls are
in [constant-Stokes tests](../../tests/test_stokes_r4_1.py) and
[variable-Stokes tests](../../tests/test_variable_stokes_r4_3.py). Code:
[stokes.py](../../src/atlas_tectonics/stokes.py) and
[variable_stokes.py](../../src/atlas_tectonics/variable_stokes.py).

## 4. Evolve heat and composition with that flow

The state holds cell-average temperature and one named constituent's volume
fraction, not automatically a plate ID. Heat diffuses, is carried by the flow and
receives an explicit source. Composition is transported conservatively. The
declared boundary conditions distinguish fixed face temperatures from insulating
walls and from boundary-cell averages.

Atlas alternates half a diffusion interval, a full transport interval and another
half diffusion interval. The diffusion/source step evaluates the discrete
constant-coefficient operator through transforms; transport uses limited
reconstruction and a two-stage time update. In the selected buoyancy-coupled mode,
mechanics is solved at both transport stages. Exact treatment of the discrete
diffusion part does not make the coupled continuous problem exact.

**Checks and limits.** [Thermochemical controls](../../tests/test_thermochemical_r4_2.py)
and [convergence tests](../../tests/test_thermochemical_convergence_r4_2.py) examine
transport bounds, heat/composition accounts, boundary conditions and independent
space/time refinement. Stage velocities are not relabelled as the accepted final
velocity. Evolving damage is not an available state variable in this two-field
coupling; a supported frozen-damage mechanical snapshot is a different capability.
Code and exact equation/splitting definitions:
[thermochemical.py](../../src/atlas_tectonics/thermochemical.py).

## 5. Challenge the mature result, not just a successful timestep

The benchmark machinery re-solves each sampled accepted endpoint and independently
derives heat-transfer rates, mean temperature, velocity summaries, viscosity
extrema and work/dissipation accounts. Dimensionless outputs are compared with
the specified published case. A Nusselt number measures heat transfer relative
to a conductive reference; it is not a temperature or an arbitrary score.

Steady and periodic regimes need different sampling. A short evolving transient
may have small solver residuals while still being far from its mature state.
Periodic comparisons require phase-compatible field data covering complete
cycles; scalar averages alone cannot establish agreement. Mesh, timestep and
nonlinear-solver sensitivity are separate questions.

The benchmark case definitions come from the
[Tosi community benchmark](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1002/2015gc005807).
Atlas's [diagnostic implementation](../../src/atlas_tectonics/convection_benchmark.py)
and [assessment tests](../../tests/test_convection_assessment_r4_4.py) check the
measurement machinery; they do not confer physical acceptance on a short run.
The recorded [dev40 assessment](../../evidence/r4-4-dev40-numerical-assessment.md)
still reports an unresolved domain-RMS comparison. Nothing in this guide authorises
another long run or describes this branch as completed planetary plate generation.

The publisher/author references and ASPECT documentation identify the method
basis; writing this chapter did not rerun their software or reproduce the full
papers. Atlas implementation details above are traced to its code and selected
case contracts. Use [current status](../../../docs/CURRENT_STATE.md) for what work
is authorised next, rather than old continuation notes inside research records.
