# Connected regional material and heat evolution

**WORKING NON-CANON.** `regional_evolution3d.py` connects the actual
[three-dimensional mechanical solve](REGIONAL_MECHANICS_3D.md) to conservative
material/heat carriage, conduction and the next mechanical solve. It is a
fixed Cartesian Boussinesq branch, not completion of I01, I05, I07 or the planet.

## Physical state and one interval

`PreparedRegionalEvolution3D` takes the existing `BoussinesqMaterial`,
`RheologyProfile`, `DiffusiveScales`, mechanical scales, six mechanical boundary
patterns and explicit transport-correction allowances. Array order is x,y,z,
with z fastest; z increases upwards from the box bottom. All public quantities
are SI. Each immutable state holds component masses (kg), sensible enthalpy
`m cp T` (J), mass-weighted damage, accumulated scalar strain and optional
mass-weighted scalar histories. The latter are not elastic stress tensors.
Temperature is derived, not independently duplicated in the saved state.

The reference density, heat capacity and conductivity are constant in this
branch. Component proportions and temperature change the buoyancy anomaly;
they do not change reference mass. The registered local constitutive law uses
temperature, depth, solved three-dimensional strain rate and, where supported,
carried damage. Cell temperature/damage/composition are piecewise constant;
depth and strain are evaluated at the mechanical Gauss points. No new mixture
viscosity rule, mineral equation of state or experimental calibration is implied.

Constitutive depth is the distance down from the top of the box divided by
`depth_scale_m`: the top face is depth zero, and a Gauss-point depth beyond the
depth scale is refused. `vertical_datum` is recorded in the plan and in every
state but does not move that origin, so a box whose top is not the surface is
still evaluated as if it were; no top-depth input exists. The plan definition
records the convention as `depth`, as the two-dimensional regional route does.

One explicit requested interval performs:

1. Solve mechanics and its local rheology together at the starting state.
   The invariant is `sqrt(D:D/2)` with `D=sym(grad u)`, including all three axes.
   Fixed-point iteration must reach a maximum log-viscosity change of `1e-8`
   within 32 iterations, in addition to the retained force/work residual gates.
   Those gates are relative to their own operands (see
   [solving and safe reuse](REGIONAL_MECHANICS_3D.md#solving-and-safe-reuse)), so
   the mechanical scales chosen here change conditioning, not acceptance. Each
   Picard solve that would previously have returned zero or inaccurate velocity
   for small dimensionless loads is now either accurate or refused.
   Every such solve starts its fixed-point iteration from zero strain rate, that
   is from the law's zero-rate viscosity, and never from the rate left by an
   earlier solve on the same plan. The plan definition records this as
   `constitutive_start`. A published result is therefore a function of the
   state, the frozen driving and the plan definition alone
   ([heat and reuse](#heat-and-reuse) gives the reason and the cost).
2. Convert solved Q2 velocity to shared conservative transport-face streams.
3. Update the registered BF23 scalar memory by its exact frozen-coefficient
   material-point formula, and accumulate scalar strain. Apply the declared
   volume heating once to donor enthalpy. Optional viscous heating is `2 eta D:D`
   from the actual solve; elastic work and pressure work are not called heat.
4. Transfer component masses, enthalpy and scalar histories with the same donor
   volume fractions, debiting finite upstream boundary stocks and returning
   exports separately. Then solve heat conduction.
5. Solve endpoint mechanics using the new temperature, composition and damage.
   With the existing finite-mode force coupling, changed regional resistance
   changes the solved motion, not merely a diagnostic colour.

This is explicitly **first-order operator splitting**. Driving and thermal
boundary values are frozen over the requested interval. There is no hidden
subdivision, clipping, automatic material replenishment or elastic/fracture
state reset. Failure publishes no new state and leaves caller inputs/stocks
unchanged. Callers must carry the returned state **and** remaining stocks into
the next interval; exports belong to the receiving region/global ledger.

Tractions and pressures are dynamic, relative to removed reference hydrostatics.
This branch must not supply a pressure-dependent strength law with that dynamic
pressure as though it were total confinement. Imported elastic tensors, moving
surfaces and arbitrary new fields are not silently discarded or evolved.

## Conservative flow, without changing the driving

Continuous Q2/Q1 pressure/velocity elements conserve volume weakly, not exactly
in every transport cell. `regional_transport3d.py` integrates the actual Q2
normal velocity at 3x3 face Gauss points. It keeps both directions when a face
contains simultaneous inflow and outflow; taking just its net sign would lose
real exchange. Signed integration is exact for Q2, whereas positive/negative
stream integration is a stated quadrature approximation.

A prepared sparse cell-incidence solve supplies the minimum weighted interior
face-flux correction (`distance/area` weight). Every exterior velocity sample
is unchanged. A globally incompatible boundary flux is refused; an interior
correction cannot repair it. The tiny compatible mean residual is reported,
not erased by changing a boundary. Both absolute velocity correction and its
fraction of the original sampled speed must satisfy caller-declared limits.
The residual check includes an explicit original-flux machine-roundoff floor,
including when a field is projected towards zero. These are numerical method
controls, not scientific error bars or a cosmetic alteration of generated maps.

First-order donor-cell carriage uses an outgoing-volume CFL no greater than one.
This is robust and conservative but diffuses sharp interfaces. The current
connection does not claim a sharp-interface or fracture-resolving calculation.
On the coarse grids that fit the default memory budget (at most 6 cells per axis
for a cube; see [memory admission](REGIONAL_MECHANICS_3D.md#solving-and-safe-reuse)),
a sharp contrast spans only a few cells, and the checked fixture is 3x3x3. This
first-order numerical diffusion is then large relative to the features the grid can
represent and spreads a moving contrast over neighbouring cells. Such results are
not resolution-converged: there is no higher-order limiter, and an interval whose
outgoing CFL would exceed one is refused, not subdivided.
Each constituent has separate local face-transfer, domain and finite-exterior
inventory accounts; trace constituents are not scaled by bulk mass. All six
sides must declare stocks, including explicit empty stocks for no inflow.

## Heat and reuse

`regional_heat3d.py` uses cell-centred finite volumes and backward Euler.
Interior face conductance is `k A/d`. A fixed-temperature boundary is half a
cell from the nearest centre; a prescribed flux is positive **outwards**.
Each of the six faces is explicitly temperature or flux controlled.
Matrix residual and energy balance must meet fixed `1e-11` relative gates.
Signed/absolute joule error, individual boundary energies, exchange-scale error
and the storage-roundoff reference are reported separately. No latent heat,
adiabatic term, compressible work or phase transition is supplied by this branch.

Geometry/projection factors are prepared once. Heat retains one factor keyed
by duration and boundary kinds; changing only temperatures, fluxes or sources
reuses it. Mechanics retains one operator for exactly unchanged viscosity, plus
one endpoint result reusable as the next interval's start when state and driving
identities match. Changed viscosity rebuilds the operator; it is never reused
because a change merely looks small. Old factors are released before replacement.
The rebuild goes through `with_viscosity(..., release=True)`: the old plan is
closed first, then the new plan reuses only the viscosity-independent mesh tables,
divergence matrix, masks and patterns. The results are bitwise the same as
preparing afresh. `mechanics_method` selects `auto` (default), `gmres`,
`direct` or the
[matrix-free multigrid method](REGIONAL_MECHANICS_3D.md#matrix-free-multigrid-candidate-i072-solver-scaling),
and the choice is part of the plan identity. Under
[`auto`](REGIONAL_MECHANICS_3D.md#automatic-choice-between-gmres-and-multigrid-methodauto),
each prepared operator chooses multigrid or gmres from its own inputs, exactly as
a fresh plan with the same selection allowance would, so a viscosity drifting across the rule's range switches
method at that step. A change of method shares no preparation. The evolution
definition records the selection policy and which of the two methods fit its
mechanical allowance. This allowance is established after fixed preparation,
leaving room for the advance workspace. These admission choices stay pinned;
temporary pressure on a shared or parent budget can refuse work, but cannot
silently choose another solver. Every actual reservation still uses the live
budget. A reopened plan with a different admitted-method mask refuses the saved
state; different byte limits with the same mask remain compatible. Viscosity
changes can still switch methods under the recorded policy and admission mask.
Statistics count preparations by resolved method and method switches. Focused
regressions cover changed masks, compatible budgets and temporary contention
followed by recovery, without rerunning the numerical benchmark campaign.
Source/runtime identities, frame, parent, source and result hashes remain bound.
Admission uses the shared byte budget; it is not an operating-system memory cap.
Transport and multigrid reserve native SuperLU initial allocation, factor growth
and temporary work before execution, and check realised fill with the same model.
The corrected accounting can refuse a formerly admitted grid at the same budget;
it changes neither the equations nor the default 256 MiB limit. See the
[memory model](REGIONAL_MECHANICS_3D.md) for the bounded measurements and admission
examples. This is an allocation estimate, not an allocator or peak-RSS guarantee.

**Declared constitutive start (R7, 1 October 2026).** Every mechanical solve
starts its fixed-point iteration from zero strain rate. Until this repair it
started from the strain rate of whatever the plan had solved last: another
state, another driving, or the start of an advance that was refused afterwards.
That rate was not an argument, not part of the reuse key and not recorded. The
same state and driving therefore published different result ids and array bits
after a different call order and on a new plan continuing a saved state
(differences from round-off size up to a few parts in 1e9, inside the `1e-8`
log-viscosity tolerance), and near the 32-iteration ceiling the same interval
was accepted on one history and refused on another. With the declared start a
result depends only on its state, driving and plan definition. The reused
endpoint result is exactly what a fresh solve of the next interval's start
would publish, and a new plan given a saved state and its remaining stocks
reproduces the continuous run bit for bit under `auto`, `multigrid`, `gmres`
and `direct`. Under `auto` the method that prepares each intermediate operator
is fixed too, because the first operator always serves the zero-rate viscosity.
Nothing else solved earlier reaches a later result: the linear solvers start
from zero, the retained operator serves only exactly equal viscosity, and the
finite-mode response cache belongs to that one operator.

The accepted cost: a state whose viscosity depends on strain rate now pays the
full iteration count at both solves of every interval, where the endpoint and
the following start used to continue from a nearby rate. On the four-interval
3x3x3 buoyancy-driven yielding example used to scope the repair, the iterations
per interval went from 14 and 5 (then 5 and 5) to 14 and 14, and the operator
preparations from 34 to 70, under each of the four methods; its final arrays
moved by at most 6e-10 relative. In a matched scratch measurement on one Windows
machine that was otherwise idle (2 October 2026; a fresh process for each run,
three runs per tree, medians; not an evidence receipt) the whole example took
12.1 s before and 21.5 s after with `direct`, 12.3 s and 22.1 s with `gmres`,
15.3 s and 27.7 s with `multigrid`, and 12.3 s and 22.0 s with `auto`: about 1.8
times the run time for about twice the operator preparations. (The scoping run
of the prototype had recorded 12.6 s and 31.6 s in one unrepeated run.) On the
2x2x2 yielding test fixture a first interval takes 4 preparations where it took
3, and each following interval 2 where it took 1; four intervals took 3.9 s
before and 4.9 s after (4.2 s and 5.2 s with `multigrid`). Constant and
rate-independent viscosity is unchanged (about 2.8 s on both trees). An interval that reached the tolerance within 32
iterations only because of the leftover rate is now refused on every history;
the ceiling was not raised to compensate. No package module consumes this route
yet, so today the cost falls on tests and tools.

A declared warm start could win the speed back without the hidden input. The
caller would pass the parent interval's accepted mechanics, whose result id
would enter the reuse key and the constitutive records, in the way the
two-dimensional thermochemical route declares its `nonlinear_start` and records
its starting-guess ids. A restart would then need that snapshot as well as the
state and stocks. It is a design item for when a consumer needs it, and is not
implemented. R7's integration retains the deterministic zero start: adding a
saved starting guess is a separate state/continuation contract change, not a
reason to reintroduce an unrecorded cache dependency or raise the iteration
ceiling. The measured nonlinear cost above is retained explicitly.

## What the bounded checks establish

The transport tests cover all directions, exact signed Q2 integration, opposite
streams, unchanged boundary samples, local/global inventory accounts, exhausted
stock and CFL refusal. Heat tests use analytical linear fields on each axis,
independent prescribed energy increments, a discrete eigenmode, time refinement,
factor reuse, cancellation and resource refusal. Joined controls exercise actual
solved translation, heat-dependent force-driven motion, three-dimensional
yielding convention, carried healing/history, once-only viscous heat and repeated
cooling intervals. They also test immutable state/provenance and failed advances.

Controls added with the declared start (R7) run two yielding intervals under
`auto`, `multigrid`, `gmres` and `direct`. A new plan continuing from a state
and stocks rebuilt from their descriptors and arrays must publish the same
second interval as the continuous run, and the first interval solved again on a
plan that has just solved the second must equal its first solution: mechanics
and state ids, iteration records and arrays identical. An advance refused after
its start mechanics converged must leave the following advance unchanged, and a
force-driven yielding interval must be unchanged by another interval solved in
between. These establish independence from call history for the tested cases on
Windows/CPython 3.12.14, not for every platform or BLAS build. The tool below
still compares rebuilding with reuse on a constant-viscosity fixture, which
cannot see a starting-rate effect.

`tools/check_regional_evolution3d.py` runs the focused joined tests and compares
rebuilding with prepared reuse on the same small fixture using three interleaved
measurements. It binds the current package, all three new test files and this
method description; its new receipt is not a rewrite of old evidence. Windows
measurements are not Linux verification or a prediction of whole-world runtime.

Remaining integration is explicit: objective elastic/finite-strain tensor
history, physically supported separation, moving surfaces/ALE geometry, spherical
plate mapping, global transfers and accepted-time feedback. The fixed-box
connection does not replace those responsibilities or forget whole-planet scope.

## Research and existing software actually consulted

- [ASPECT discretisation documentation](https://aspect-documentation.readthedocs.io/en/stable/parameters/Discretization.html),
  especially its locally conservative option: continuous Taylor-Hood pressure
  does not provide cellwise volume conservation. No ASPECT run was performed.
- [Odsæter, Wheeler, Kvamsdal and Larson, conservative flux postprocessing](https://arxiv.org/html/1605.04076v2):
  weighted correction and fixed-boundary compatibility. Its examples concern
  Darcy flow; this velocity-to-transport application and its tests are Atlas's.
- [NIST FiPy finite-volume discretisation](https://pages.nist.gov/fipy/en/4.0/numerical/discret.html),
  equations (1), (3)–(5): transient control-volume balance, diffusive face
  conductance and volumetric sources. No FiPy dependency/comparison is claimed.
- [Becker and Fuchs (2023)](https://doi.org/10.1029/2023GC011179):
  the existing explicit scalar weakening/healing law is connected, not replaced.
- The already documented [Tosi et al. (2015)](https://doi.org/10.1002/2015GC005807)
  constitutive implementation is reused with its own strain-norm convention.
  This pass inspected that code; the publisher fetch was unavailable, so it is
  not claimed as a newly reread paper or a new benchmark reproduction.
- The declared constitutive start (R7, 1 October 2026) consulted no paper or
  external software. It applies the zero-rate start that the two-dimensional
  regional route (`regional_rheology.py`) already uses, and its checks are
  Atlas's own.
