# How Atlas tectonics is made

This guide explains the current methods, what their outputs mean, and the evidence
used to check them. It is written for an interested reader without specialist
geophysics or numerical-analysis training. Status: **WORKING NON-CANON**.

The dated results and outstanding findings live in
[the validation record](W10_VALIDATION.md). This guide explains the machinery;
it is not a second release certificate. References below point to the actual
implementation notes and tests, rather than a proposed future feature list.

## The central idea

Atlas does not paint a mountain range and then invent a geological explanation.
It starts with a description of rock, geometry, temperature and motion, and applies
explicit rules to them. Some motion is **prescribed**: the user supplies it. Other
motion is **solved**: the program calculates it from forces and material behaviour.
Those are different capabilities and should be labelled differently in the UI.

Think of the model as several linked scientific instruments, not one universal
simulation. A plate map, a cross-section through a rift and a regional flow solver
use different representations. They can exchange results only through a supported
connection that preserves the meaning and amount of the material being moved.

The main route is:

> Described geometry and materials → supported motion or force calculation →
> material and heat updates → mechanical response → inspectable, dated outputs.

Hydrology, erosion, geology and other modules own the further effects on their
systems. Existing shared thermal, load and material calculations remain available;
their location inside this package does not make all downstream science tectonics.

## What “we checked it” means

The new [W12 runnable assembly](W12_ASSEMBLY.md) checks the fourth question below:
can the instruments actually be used together? Its public example starts with
described geology, samples material columns, evolves their cooling/compaction,
and calculates the elastic response. It then saves the real fields through the
Atlas graph and lets a separate read-only operation inspect them. Other native
tectonics workflows can export their identified fields through the same storage
boundary without inventing a physical connection between incompatible models.

We compare this assembled answer with calling the existing calculations directly,
and compare an uninterrupted run with stopping, closing the store and resuming.
All fields and identities must agree. Cache restoration must still detect missing
physical data; “the cache says done” is not enough. This checks the wiring and
recovery, while the methods' existing mathematical and physical checks still
answer whether each instrument models the right thing.

There are four different questions, and a good answer to one cannot substitute
for an answer to another:

1. **Implementation:** does the program calculate the equations we intended?
   We use answers calculated independently, conservation accounts and deliberately
   invalid inputs. For example, rotating a rigid plate must not stretch it.
2. **Numerical accuracy:** is the approximation sufficiently resolved? We refine
   the grid and time intervals, and look at the error in the actual quantities of
   interest. A solver saying “converged” only means its algebraic work finished;
   it does not prove that the grid resolved the geology.
3. **Physical adequacy:** do the chosen equations and parameters reproduce
   independent laboratory or geological observations in the intended setting?
   Two programs can agree because both make the same simplifying assumption.
4. **Usable assembly:** do compatible inputs make it through a supported workflow,
   with correct units, resource limits, provenance, saving and recovery?

This follows the distinction between code and calculation verification described
in [NASA's verification guidance](https://www.grc.nasa.gov/WWW/wind/valid/tutorial/verassess.html).
An image is useful for spotting a reversed axis, missing region or implausible
pattern; it cannot replace a measured error or an independent physical comparison.

## 1. Place the world and keep its clocks straight

**Inputs:** positions, planet radius where needed, local coordinate frames,
length/angle units and a stated time convention.

**What happens:** spherical positions are converted to three-dimensional vectors;
regional cases use explicitly identified local frames. Finite rotations move a
rigid plate around an axis. Rotation order matters, just as turning a book over
and then sideways differs from performing those actions in the opposite order.
Geological ages are converted to a forward-running model clock rather than mixed
directly with elapsed seconds.

**Outputs:** transformed positions, relative motions and unambiguous time labels.

**How we check:** inverse rotations restore positions; distances and orientation
are preserved; poles and the longitude seam are tested; changing a common frame
must not change relative motion. These are exact mathematical requirements, not
properties fitted to a convenient map. See [W01 coordinates](FOUNDATIONS.md#w01-coordinates)
and `test_w01_coordinates.py` / `test_foundations.py`.

## 2. Describe plates and their shared boundaries

**Inputs:** supplied outlines or a seeded geometric layout, ownership labels and
boundary relationships.

**What happens:** regions share one boundary representation, so neighbouring
plates cannot quietly disagree about where their common edge lies. Geometry checks
detect gaps, overlap, bad orientation and ambiguous ownership. A generated initial
partition supplies candidate shapes; it is not evidence that mantle forces formed
those plates.

**Outputs:** plate/block regions, shared traces, junctions and ownership queries.

**How we check:** simple shapes have independently known area and perimeter;
reversing an edge must reverse its sidedness consistently; the complete spherical
surface must be accounted for. Tests include seams and poles. The PB2002 reference
is a separate Earth dataset, not Atlas output. See `test_w01_geometry.py`,
`test_w01_boundaries.py`, `test_w01_spherical_atlas.py` and
[the bounded W01 assessment](../evidence/w01-bounded-validation.md).

**Random new worlds:** [the candidate-layout route](NEW_WORLD_LAYOUT.md) now
varies plate sizes as well as geometry. A seed chooses explicit perturbations
of the exposed reference sizes, then connected cuts group a shared spherical
mosaic. Different sorted areas demonstrate changes that cannot be explained by
rotating or renaming the same map. The variation width is a disclosed engineering
assumption; crust and motion must subsequently be made physically compatible.
Insufficient resolution produces a recorded refusal, not erased small plates.

## 3. Put described geology onto a computational grid

**Inputs:** geological features, layers, material identities, known or unknown
formation dates, and initial thermal descriptions.

**What happens:** the model asks what occupies a point or a finite cell. A cell
crossing a boundary is not simply assigned the material at its centre: supported
sampling calculates the amounts of the intersecting materials. Temperature at a
point, temperature averaged over a cell and total heat are distinct outputs.

**Outputs:** initial material inventories, thermal fields and source-linked labels.
Unknown density cannot silently become an assumed mass, and a cooling age is not
automatically a rock's formation age.

**How we check:** analytic intersections and independently refined sampling must
give consistent inventories; different cell layouts must represent the same
described geology. Point samples must not be mistaken for cell averages. See
`test_w01_initial_sampling.py`, `test_w01_geological_description.py` and
[the regional workflow](W01_REGIONAL_WORKFLOW.md).

## 4. Turn plate motion into regional forcing

**Inputs:** full plate velocities or rotations, the regional section's orientation,
and explicit rules for movement outside that section.

**What happens:** velocities are resolved into the components relevant to the
regional representation. A cross-section cannot silently discard sideways motion
and still claim to represent the original three-dimensional movement. Unsupported
components require explicit treatment or refusal.

**Outputs:** compatible boundary velocities and accounted motion used by the
regional calculation.

**How we check:** rigid/common motion, rotated frames, signs, side reversal and
out-of-section components have dedicated controls in `test_w01_regional_forcing.py`.
This verifies conversion of supplied motion; it does not discover plate speeds.

## 5. Move material without creating or losing it

**Inputs:** labelled material amounts, cell sizes, velocities and explicit
inflow/outflow conditions.

**What happens:** a finite-volume method records the amount crossing every shared
cell face. What leaves one cell enters its neighbour, unless it is explicitly
exported. Higher-order reconstruction reduces artificial smearing, while slope
limits prevent negative amounts. Several materials must be treated consistently:
their reconstructed amounts must add to the reconstructed total.

Changing the grid is a different operation from moving rock. Conservative remapping
integrates the old representation over the new cells. Moving-grid transport uses
the rock's velocity **relative to the moving cell faces**, and updates amount as
thickness multiplied by cell width.

**Outputs:** material distributions, boundary transfers, cohort ages and residual
accounts. A cohort is simply a labelled group of material sharing an origin/history.

**How we check:** known translations, affine fields, sharp fronts, positivity,
individual inventories, total thickness, grid refinement and native/reference
agreement. The comprehensive review found that individual conservation alone
missed a mixed-material remapping error. Joint reconstruction now corrects it,
with passing remap/moving-grid regressions and source-bound integration evidence
in the dated validation record. See `test_w02_completion.py` and
`materials.py` / `remapping.py` / `_mesh_native.py`.

The consistency requirement is also central to
[Plewa and Müller, Consistent Multi-fluid Advection](https://arxiv.org/abs/astro-ph/9807241).
Atlas's correction constrains reconstruction; it must not repair completed cell
inventories by arbitrary renormalisation or claim to copy that paper's exact scheme.

## 6. Calculate cooling, temperature and heat

**Inputs:** initial thermal state or cooling history, time, thickness, conductivity,
heat capacity and thermal boundary conditions.

**What happens:** thermal diffusion carries heat from hotter to colder material.
For the constant-property plate model, a mathematical series directly evaluates
the cooling solution. General supported regional cases solve the heat equation,
including transport by the current velocity. Integrating a profile over a cell
gives its mean temperature or heat content; a single centre sample is not enough.

**Outputs:** temperature profiles/fields, stored heat and boundary heat transfers.
Kelvin is used for absolute temperature; a temperature difference of 1 K equals
a difference of 1 degree Celsius.

**How we check:** initial and boundary limits, independent finite-volume solutions,
depth/time refinement and heat balance. Mature ocean heat flow is also compared
with 50 independent published age bins. The baseline passes the stated dispersion
screen but is below the observed median in all 50 bins, by about 8.78 mW/m² on
average. That is a systematic discrepancy, not evidence of an unbiased Earth
prediction. See [thermal columns](W03_THERMAL_COLUMNS.md),
[W10 observations](W10_VALIDATION.md#independent-observational-challenge), and
`test_w03_plate_cooling.py` / `test_w06_thermal_integrals.py`.

## 7. Convert cooling and compaction into material/load changes

**Inputs:** temperature-dependent density parameters, reference columns, solid
grain amounts, pore fluid, effective stress and compaction history.

**What happens:** cooling changes the modelled density and hence the supported
load. Compaction closes pore space without destroying the solid grains. Expelled
water enters a named reservoir; reopening pores requires an actual fluid supply.
Maximum past loading matters because unloading does not normally undo all
compaction. The current drained update is an equilibrium response, not a prediction
of how quickly water escapes through the rock.

**Outputs:** bulk thickness, porosity, grain/fluid accounts, thermal load and
reference-relative support diagnostics.

**How we check:** fixed solid volume/mass, zero-change cases, load–unload paths,
finite fluid supply and changing-area accounts. These tests verify the chosen law;
geological use still requires appropriate material parameters. See
[thermal support](W03_THERMAL_SUPPORT.md), [compaction](W03_COMPACTION.md), and
[their supported assembly](W03_WORKFLOW.md).

## 8. Bend and support the lithosphere

**Inputs:** physical loads, replacement material, gravity, elastic properties,
effective elastic thickness and boundary conditions.

**What happens:** a load depresses the lithosphere and the surrounding material
provides restoring support. Elastic bending spreads that response sideways. A
thicker elastic plate resists bending much more strongly. Atlas has distinct
periodic, finite-ended and continuing-region treatments; the edge choice changes
the physical question, not merely the plotting window.

When stiffness changes, the current equilibrium under its absolute load is
compared with the original equilibrium. Solving only the change in load would
incorrectly predict no response to a stiffness change under an unchanged load.

**Outputs:** displacement, slope and curvature relative to a specified reference.
One owner supplies each displacement contribution: thermal support cannot be
added twice through two different adapters.

**How we check:** sinusoidal/analytic loads, independent quadrature, superposition,
mesh refinement, exterior-load sensitivity and two-equilibrium controls. See
[finite regions](W04_FINITE_REGIONS.md), [variable rigidity](W04_VARIABLE_RIGIDITY.md),
[evolving inputs](EVOLVING_MECHANICS.md), and `test_evolving_flexure.py`.

Uniform finite-region validity is currently checked at cell faces and centres.
That sampling is not a proof that the largest slope or curvature between samples
is safe. A near-limit application needs an extremum bound or a demonstrated
refinement margin. The variable-rigidity and extension routes have their own
stronger validity treatments; one route's guarantee must not be borrowed by another.

## 9. Stretch crust and create oceanic material

**Inputs:** a prescribed extension geometry/rate or spreading-ridge history,
initial material and finite source supplies.

**What happens:** extension spreads existing material out and generally thins it.
The listric-fault route follows a supplied curved fault geometry. Spreading instead
creates labelled oceanic material from an explicitly accounted source; each strip
retains its birth time and cools for its actual age. Ridge migration and rate changes
split histories at their actual events, rather than smearing them across a long step.

**Outputs:** changing thickness, cohort positions, birth/exit histories, temperature,
heat accounts and supported elevation changes.

**How we check:** independent characteristic trajectories, known thinning factors,
material/heat/water balance, refinement, first-exit bookkeeping and exact restart.
A supplied fault shape passing these checks is not evidence of predicted fault
initiation. See [W05](W05_REGIONAL_EXTENSION.md), [W06](W06_SPREADING.md) and
[changing spreading histories](W06_HISTORIES.md).

## 10. Solve slow regional deformation

**Inputs:** geometry, viscosity/strength, density/body forces, boundary velocities
or tractions, and an explicit pressure reference.

**What happens:** on the represented geological timescales, the regional solver
balances stress and forces while enforcing the selected mass-conservation law.
Viscosity measures resistance to slow deformation; the constitutive law says how
that resistance changes with temperature, pressure and strain rate. Nonlinear
cases repeatedly update stress and material behaviour until both agree.

**Outputs:** velocity, physical pressure, stress/strain-rate diagnostics, boundary
reactions and numerical residuals. They are not earthquake waveforms.

**How we check:** manufactured flows with independently known force fields,
hydrostatic and rigid-motion limits, sharp material interfaces, mesh refinement,
pressure/reference invariance and alternate discretisations. See
[regional solver](W07_REGIONAL_SOLVER.md),
[heterogeneous/thermal mechanics](W07_HETEROGENEOUS_THERMAL.md), and
`test_regional_stokes_core.py` / `test_w07_regional_rheology.py`.

## 11. Let the surface and temperature feed back

**Inputs:** a current physical surface, mechanical solution, thermal state and
explicit time intervals.

**What happens:** the free-surface route moves the top boundary with the rock and
re-solves mechanics on its changed shape. Thermal–mechanical intervals use flow to
transport heat and evaluate updated material behaviour. The frequency with which
mechanics and temperature communicate matters: more heat substeps alone do not
necessarily resolve their feedback. Temperature-dependent coupling is available
through the lower-level interval API; the assembled geological W07 workflow
currently uses its explicitly selected constant-viscosity route. Testing the
former does not silently give the latter a new nonlinear capability.

**Outputs:** evolving surface shape, temperature, material state and endpoint
mechanics, each tied to its time and source.

**How we check:** independent free-surface relaxation, volume balance, spatial/time
refinement and active-coupling controls. A stationary conduction example cannot
certify moving, temperature-sensitive coupling. The current findings are in the
validation record. See [surface/strength](W07_SURFACE_STRENGTH.md) and
[W07 workflow](W07_WORKFLOW.md).

## 12. Shorten, slide and underthrust

**Inputs:** prescribed deformation, fault/section geometry, labelled materials
and explicit receiving/exterior regions.

**What happens:** shortening compresses a horizontal footprint and thickens its
conserved material. Transform motion slides regions past one another; supported
oblique motion also retains extension/shortening components. Ramp-flat underthrusting
moves material along a supplied dipping then flatter interface, keeping the sides
and stationary host occupancy consistent throughout the motion.

**Outputs:** changed geometry, material inventories, explicit exports and, where
supplied, separate boundary work and gravitational-energy changes.

**How we check:** analytic deformation maps, determinant/area changes, rotated
frames, side reversal, exact finite accounts and checks along the whole path—not
only two non-overlapping endpoints. See [shortening](W08_SHORTENING.md),
[transform motion](W08_TRANSFORM.md), [underthrusting](UNDERTHRUST.md).

## 13. Model a prescribed slab and its mantle wedge

**Inputs:** a supplied subduction geometry and slab speed, thermal conditions,
material laws and a declared mesh.

**What happens:** the slab movement is imposed; the mantle wedge's slow flow and
temperature are calculated. Hot moving mantle and the cold, strong region beneath
the lid create narrow gradients. Resolving those gradients matters more than
merely adding cells uniformly. Thermal transport must use a compatible velocity
field, otherwise a transfer between numerical representations can create an error.

**Outputs:** wedge velocity, pressure, temperature and fixed benchmark observables;
material retirement is accounted separately.

**How we check:** published benchmark quantities under matched boundary/material
assumptions, nonlinear residuals, conservative velocity transfer and grid-refinement
sequences. Retained five-case campaigns are labelled historical, not silently
rebranded as new runs. Agreement verifies this numerical experiment; it does not
independently validate every natural subduction zone. See
[subduction](W08_SUBDUCTION.md) and `test_w08_subduction_acceptance.py`.

## 14. Account for finite magma and changing regimes

**Inputs:** finite source/reservoir stocks, supplied phase/thermal laws, explicit
transfer rates, emplacement choices and dated regime changes.

**What happens:** melting must be paid for with heat; transfers must remove actual
material from the source. Mixing and emplacement preserve component and enthalpy
accounts. A depleted source stops supplying material instead of becoming negative.
The joined workflow prevents a saved transfer being paid or applied a second time.

**Outputs:** finite material/heat transfers, reservoir and emplacement inventories,
and compatible diagnostic regional loads/views.

**How we check:** independent calorimetric controls, exact exhaustion cases,
component/enthalpy balance, ownership and restart. This is accounting for supplied
processes, not spontaneous volcano placement. Further geological/magmatic expansion
belongs with its owner. See [magmatism](W08_MAGMATISM.md) and
[joined workflow](W08_JOINED.md).

## 15. Save, reuse and recover without changing the science

**Inputs:** a complete scientific request, source/runtime identity and finite
resource limits.

**What happens:** prepared calculations reuse unchanged geometry or matrix work.
Exact result reuse requires the same relevant request. Saved arrays are compressed
losslessly and published atomically: a half-written result must not masquerade as
a completed state. Changing source or physical inputs invalidates the applicable
reuse rather than silently accepting an old result.

The latest performance pass reduces the cost of these safeguards without skipping
them: each source file is still read, but repeated filesystem queries are combined;
the geological connection keeps one suitable verifier rather than rebuilding it;
and checkpoint writing avoids an unnecessary temporary array copy. The measured
workflow savings and exact comparison scope are in the
[W11 record](OPTIMISATION_REFERENCE.md#w11-module-wide-linked-workflow-pass--24-september-2026).

**Outputs:** dated snapshots, complete result arrays, provenance, resource/timing
records and restartable supported histories.

**How we check:** byte-for-byte cold/reused agreement, fresh-process recovery,
corruption refusal, cancellations around publication, changed-source refusal and
combined resource drills. Accounted numerical memory and total process memory are
reported separately. Small-grid speedups are not planet-wide runtime forecasts.
See [histories](TECTONIC_HISTORIES.md) and
[performance methods](OPTIMISATION_REFERENCE.md).

## Reading an output without being misled

The package also retains downstream W09 components: routing geometry identifies
receivers and connected depressions; finite-water calculations fill, spill and
split lakes; river erosion consumes identified rock/alluvium; hillslope transport
moves finite tagged soil across neighbouring faces on a one-dimensional strip.
Mass and signed enthalpy stay accounted. These components have analytic/refinement
and recovery checks, but are not a joined erosion–deposition–tectonic feedback model.
They remain with their downstream owners; the comprehensive regression includes
them without turning their further development into tectonics work. See
[surface-process boundaries](W09_SURFACE_PROCESSES.md) and [erosion](W09_EROSION.md).

- **Position/displacement:** check frame, metres versus kilometres, sign and the
  named reference surface. Total displacement is not the increment for one step.
- **Temperature/heat:** temperature is an intensive value; heat/enthalpy is an
  amount tied to material and a declared reference. They are not interchangeable.
- **Pressure/stress:** check physical versus shifted/dynamic pressure and the
  pressure datum before interpreting strength or forces.
- **Thickness/material:** check whether the result is a point value, cell mean,
  volume or mass. Volume becomes mass only through an explicit density law.
- **Age/time:** distinguish formation age, cooling age and elapsed model time.
- **Rendered map:** colours must come from the named arrays and legend, not an
  illustrative terrain image. An attractive map is not evidence of validation.
- **Status:** computed, numerically checked, physically supported and released
  are different states. Missing observations or failed checks stay visible.

## The experimental generated-dynamics route

There is also a retained experimental route for coupled heat, composition and
force-driven flow, with temperature-dependent viscosity, yielding and explicit
material-point memory. Its linear solvers, time integration, error checks and
recovery have tests. Those checks do not establish that a short transient has
reached the mature convection regime required by the published benchmark.

This matters because a geometrically valid plate map and a successfully solved
regional flow field are not yet a verified mechanism for generating an entire
planet's plates. The R4.4 long-convection acceptance remains held/incomplete.
Nothing in this guide treats its unrun mature-regime comparison as passed, or
uses a small demonstration as a replacement for it. Supported prescribed-motion
workflows remain separately usable and testable.

## Further reading and reproducibility

Each method section links its design/implementation record; those records contain
the specialised papers, software comparisons, supported parameters and commands.
The [validation record](W10_VALIDATION.md) gives the measured results of this pass,
remaining scientific questions, and the distinction between reused and new evidence.
The [tectonics README](../README.md) remains the entry point for running the package.

Primary methods and existing software consulted for this review include
[pyGPlates velocity conventions](https://www.gplates.org/docs/pygplates/generated/pygplates.calculate_velocities),
[Clawpack's conservation/advection explanation](https://www.clawpack.org/riemann_book/html/Advection.html),
[Parsons and Sclater's plate-cooling paper](https://topex.ucsd.edu/geodynamics/parsons_sclater77.pdf),
[Fowler and Yang on compaction](https://people.maths.ox.ac.uk/fowler/papers/2002.1.pdf),
[gFlex](https://gmd.copernicus.org/articles/9/997/2016/),
[Landlab's prescribed listric extension](https://landlab.csdms.io/tutorials/tectonics/listric_kinematic_extender.html),
[PETSc's staggered Stokes example](https://petsc.org/release/src/dm/impls/stag/tutorials/ex2.c.html),
[ASPECT's moving-mesh formulation](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/methods/freesurface/arbitrary-le-implementation.html),
and [FEniCS-SZ's subduction benchmarks](https://cianwilson.github.io/fenics-sz/notebooks/03_sz_problems/3.4b_sz_benchmark.html).
These were consulted as scientific/method references, not executed as new
cross-code comparisons. The dedicated W10 record gives the actual observation
dataset and attribution. Atlas's joint-material limiter and coupling diagnostic
are its own implementations, not claims to reproduce an external package exactly.
