# Connecting the physical processes: I01

[Guide contents](../HOW_TECTONICS_IS_MADE.md) · [Physical methods](02-tectonic-processes.md) · [Workflow and delivery](03-coupling-and-reliability.md)

Tectonic processes affect one another. Temperature changes rock strength; strength affects motion; motion changes thickness, heating and the forces driving the next interval. I01 investigates the physical rules needed to connect these effects without losing material, inventing heat or counting a force twice.

**I01 remains open and WORKING NON-CANON.** Its reviewed implementations are bounded controls, not a connected whole-world engine. W01–W12 name the existing component responsibilities; I01–I12 are the separate integration increments, with I02–I12 still unstarted. The sections below follow physical dependencies, not implementation dates. In the coupled controls, related quantities are updated together at declared integration stages. The eventual assembled loop must also check that its interacting processes agree at the accepted interval endpoint. See the [integration architecture](../INTEGRATION_PLAN.md#4-architecture-one-evolving-physical-state) and [current status](../../../docs/CURRENT_STATE.md). The [experimental dynamics route](05-experimental-dynamics.md) remains separate.

The research links below come from the existing method records. They explain the chosen methods; this chapter adds no research campaign, numerical run or scientific acceptance.

## 1. Start from one declared physical state

The [physical contract](../I01_PHYSICAL_CONTRACT.md) identifies the world, time, geometry, material inventories, temperature, deformation history and physical assumptions. Each exchanged quantity also needs units, a reference level and the area or volume it represents. Matching array sizes is insufficient: two arrays may describe different rocks or thicknesses.

Plate identity and material identity remain separate. A rock parcel can change plate without losing its formation age, temperature or deformation history. Likewise, reheating ocean crust changes its thermal history without making it newly formed crust.

The intended accepted-time loop reserves finite material and heat transfers, checks the coupled result, then commits geometry and accounts together. Its design distinguishes supplied histories from generated evolution. A prescribed movement or event can test a transfer without demonstrating that Atlas predicts it.

## 2. Calculate support and gravitational driving from the columns

In the [columns-to-GPE control](../I01_GPE.md), layer thickness, density and temperature determine both dry surface support and gravitational potential energy: effectively, how high the column's weight sits. Differences between neighbouring columns produce sideways traction, which feeds the spherical torque calculation. Thermal buoyancy changes support while reference material mass remains intact.

The common depth and pressure reference matters. A different arbitrary reference for every column would corrupt the force comparison. Nor may Atlas add a separate ridge-push force where the same gravitational contribution is already included. The method draws on [Ghosh, Holt and Flesch](https://ceas.iisc.ac.in/~aghosh/Ghosh_gji09.pdf) for integrated column pressure and [Clennett et al.](https://adamfholt.github.io/documents/papers/clennett_et_al_scirep2023.pdf) for reduced gravitational traction; forward motion is Atlas's extension. Analytical columns, reference shifts and known spherical torques check this connection.

Water introduces another feedback. The [water–flexure control](../I01_WATER_FLEXURE.md) repeatedly redistributes one finite water volume and bends the supporting crust until shoreline, depth and deflection agree. [Wickert's gFlex paper](https://gmd.copernicus.org/articles/9/997/2016/) and [software theory](https://gflex.readthedocs.io/en/latest/theory_and_numerics.html) inform the elastic response and boundary assumptions. Independent flat-plate and wave solutions check volume, mean subsidence and bending.

The [water-loaded driving connection](../I01_WATER_GPE.md) now uses that same
loaded bed and water inventory to calculate sideways gravitational forces. It
adds the water's weight once and does not float the already-bent bed again.
When rock carries some load sideways by bending, the vertical stress is not
simply the weight above it: the depth of the load-carrying layer also matters.
The connection therefore needs a declared shear-transfer depth for nonuniform
finite-rigidity cases. No water, no rigidity and exactly uniform loading are
separate structural limits; a numerically small bending effect is not silently
treated as absent.

The [single-core producer](../I01_ELASTIC_CORE.md) supplies this missing depth
from one declared load-bearing rock layer. Its thickness and elastic properties
set bending stiffness; its position sets the midpoint at which it transfers load
sideways. Moving the same layer deeper therefore changes the driving force even
though its stiffness is unchanged. That is a physical change, unlike moving an
arbitrary height reference. Atlas does not guess this layer from a temperature
profile or an effective elastic thickness alone.

[Kelly's plate-theory derivation](https://pkel015.connect.amazon.auckland.ac.nz/SolidMechanicsBooks/Part_II/06_PlateTheory/06_PlateTheory_Complete.pdf)
provides the assumed smooth shear profile; Wickert/gFlex supplies the retained
linear plate framework. [Independent pressure and Fourier controls](../../evidence/i01-elastic-core-r1.json)
check that integrating that profile gives the same force correction, with the
right signs and reference behaviour. The selected branch is one homogeneous
core in a flat-reference, constant-stiffness model. Curved-plate coupling and
weak/broken boundaries still need I04/I08 assembly and admission.

The pressure-balance reasoning uses the Ghosh and Clennett papers above, with
the flexural extension derived explicitly in Atlas. A known wave-shaped plate
solution and an independent integration through the pressure profile check the
result. Shifting or deepening the common reference must preserve the force,
without erasing a real pressure difference. Tests also reject negative water,
double loading and a second isostatic correction. The [reviewed controls](../../evidence/i01-water-gpe-r1.json)
cover this periodic planar connection, not yet spherical torque or weak/broken
plate-boundary assembly.

## 3. Calculate resistance and where deformation concentrates

The [column law](../I01_COLUMN.md) calculates how each material creeps or yields, then integrates resistance through depth. Simultaneous creep mechanisms share stress and contribute different deformation rates. The [pressure/temperature control](../I01_STRENGTH.md) also recalculates frictional strength as deformation changes pressure: confinement strengthens the frictional response, while pore pressure reduces effective confinement.

These choices use explicit stress conventions and material laws informed by [ASPECT's continental-extension example](https://aspect-documentation.readthedocs.io/en/latest/user/cookbooks/cookbooks/continental_extension/doc/continental_extension.html). Independent conversions and analytical stress solutions check that laboratory coefficients have not acquired the wrong units or numerical factors. Example parameters are not universal planetary defaults.

The [weakening adapter](../I01_WEAKENING.md) carries accumulated plastic deformation and uses it to reduce cohesion and friction. A uniform column cannot locate a rift. The separate [two-dimensional localisation probe](../I01_FAULT2D.md) tests how deformation concentrates using a declared physical length, informed by [Duretz et al.'s regularisation study](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2022GC010675). Refining the grid should resolve that length rather than make a fault arbitrarily narrower. Spatial and timestep refinement, orientation controls and force/work balance support this numerical claim; they do not establish calibrated faults or rupture.

## 4. Solve motion against the calculated resistance

Rock can store part of its deformation elastically, like a very stiff spring.
Resetting its stress at every step would lose that stored force and energy. The
[elastic-memory choice](../I01_ELASTIC_MEMORY.md) therefore retains stress for
the future rift. Mechanical work can either change stored energy or become heat;
these are separate accounts, and releasing stored energy can produce heat even
without further loading. [ASPECT's viscoelastic source](https://github.com/geodynamics/aspect/blob/main/source/material_model/viscoelastic.cc)
shows how geological models carry old stress, while
[Schrank et al. (2017)](https://doi.org/10.1093/gji/ggx297) explain why a common
rotation rule can give misleading results under large shear. Atlas selects the
logarithmic-objective direction, but first implements an exact control restricted
to stretching along common axes plus rigid rotation. General shear is refused.
Independent high-precision integrals, stress relaxation, rotation, subdivision
and heat/work checks test this [local update](../../tools/check_i01_elastic_memory.py).
Prepared coefficients are reusable without dropping the initial stress.
The [receipt](../../evidence/i01-elastic-memory-r1.json) is for that control, not
elasticity already coupled into the existing motion/heat columns below. Their
viscoplastic accounts stay unchanged; the future elastic solver must include
stored-energy change in its internal-work account.

The [motion connection](../I01_MOTION_COUPLING.md) balances external driving force against drag and the actual layered column's resistance. Speed is an output. As plastic history weakens the column, the same force can drive faster extension. The drag represents a separate process, so its resistance must not duplicate deformation already resolved inside the column.

At each stage, driving work must equal drag dissipation plus column work. Exact linear examples and an independent [SciPy Brent root solver](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.brentq.html) check the nonlinear solution; evolving cases then test time and depth refinement. The [implementation](../../tools/check_i01_motion_coupling.py), [focused tests](../../tests/test_i01_motion_coupling.py) and [recorded control result](../../evidence/i01-motion-coupling-r1.json) make that reasoning inspectable. This is a regional force balance with supplied drive, not an assembled moving sphere.

### Solve a three-dimensional region and return its resistance

The new [finite-region solver](../REGIONAL_MECHANICS_3D.md) lets rock move in both
horizontal directions and vertically. Each part of the box has its supplied
viscosity, and the equations balance pressure, internal stress, body forces and
forces at the boundaries. This is important around competing faults or junctions:
a vertical slice alone cannot let two horizontal directions compete.

Velocity and pressure are solved together. The method uses smooth quadratic
velocity fields and linear pressure fields within small connected boxes, known
as Taylor-Hood elements. The full stress connects the movement directions; it
does not treat them as three unrelated flow problems. A pressure reference is
kept distinct from actual confinement, and prescribed flow that would accumulate
incompressible rock inside a closed box is rejected.

The connection can also calculate how fast declared boundary motions should be.
It measures the region's resistance to each independent motion, then balances
that resistance and separately declared exterior drag against the driving force.
Changing viscosity therefore changes the calculated speed. The boundary reactions
come from the same equations as the flow, so force and mechanical work can be
checked without inventing a second resistance estimate.

Exact shearing, stretching, gravity-pressure and layered-material examples test
the equations. A genuinely three-dimensional example varies viscosity across
the box, and a smooth non-polynomial example checks refinement. Stored extra
stress can be supplied without being erased; its work is recorded separately
from viscous heating. That interface does not itself update elastic history.
The solver prepares its sparse matrix once, reuses factors for changed loads,
and keeps only one latest result and one motion-response cache.

[FEniCSx](https://docs.fenicsproject.org/dolfinx/main/python/demos/demo_stokes.html)
and [ASPECT](https://aspect-documentation.readthedocs.io/en/latest/user/methods/numerical-methods.html)
informed the mixed-element and block-solver choices. The actual
[PETSc 3D Stokes example](https://petsc.org/release/src/dm/impls/stag/tutorials/ex4.c.html)
was checked for variable-viscosity and pressure handling; the
[consistent-reaction example](https://bleyerj.github.io/comet-fenicsx/tips/computing_reactions/computing_reactions.html)
explains why forces should come from the original equations. These are method
references, not claims of an executed comparison against those programs.

This supplies mechanical flow and finite-mode force feedback. The material/heat
connection below now advances that solved region. Evolving its surface and
connecting its reactions to the moving sphere remain separate connections;
this is not yet a generated rupture or junction reorganisation.

## 5. Advance heat, history and geometry together

### Carry material and heat through the solved three-dimensional region

The [connected regional advance](../REGIONAL_EVOLUTION_3D.md) now uses the
calculated flow to move rock composition, heat and scalar material history.
All three move together: a parcel cannot leave its heat behind or arrive with
its earlier weakening forgotten. Material entering the box comes from a finite
declared supply, and material leaving it is returned as an explicit export.

There is a numerical distinction worth making. A flow can satisfy the mechanical
equations without balancing the tiny inflow and outflow of every individual
transport cell exactly. Atlas therefore constructs shared cell-face flows with
a bounded, reported correction inside the box. The exterior driving is unchanged;
an incompatible exterior flow is rejected. This follows the issue explained by
[ASPECT](https://aspect-documentation.readthedocs.io/en/stable/parameters/Discretization.html)
and the conservative correction idea of
[Odsæter and colleagues](https://arxiv.org/html/1605.04076v2). Opposite streams
through one face are retained rather than cancelled before moving the material.

Heat then conducts between neighbouring cells and through the declared boundary
conditions. The finite-volume balance follows the formulation explained by
[NIST FiPy](https://pages.nist.gov/fipy/en/4.0/numerical/discret.html): heat leaving
one internal cell enters its neighbour. Each external heat exchange is counted
separately. Atlas applies its existing temperature/weakening laws, then solves
the mechanics again. A joined check demonstrates that heating lowers resistance
and increases force-driven motion: the changed temperature affects the next
calculation, not just the map's colours.

Known translations in every direction test carriage; exact heating and cooling
examples test heat accounts; a yielding example checks the three-dimensional
strain convention; repeated smaller intervals test time accuracy. The connection
is deliberately first-order and fixed-box: it does not yet move the surface or
carry an objectively rotated elastic tensor. Reference mass density stays fixed
while temperature/composition change buoyancy, as required by this selected
Boussinesq approximation. Sharp interfaces are numerically spread by donor-cell
transport, so this is not claimed as a resolved fracture calculation.

Prepared geometry, unchanged mechanical operators and heat factors are reused
without retaining every previous interval. The
[new bounded record](../../evidence/regional-evolution3d-r1.json) measures that
reuse separately from physical accuracy; it is not a whole-world speed forecast.

### Other supported thermal and moving-column connections

Deformation produces heat, conduction redistributes it, and temperature changes creep resistance. The [thermal cell](../I01_THERMAL.md) tests that feedback in a periodic material cell; the [column-heat model](../I01_COLUMN_HEAT.md) uses layered depth geometry with surface and basal temperatures. Their different spatial assumptions prevent simply stacking the two solvers.

Heat must be deposited in the same rock whose work produced it. A corrected column check rejects thermal cells representing 101 km of rock inside a declared 100 km column: an apparently closed energy balance alone had not exposed the extra heat capacity. [ASPECT's heating conventions](https://aspect-documentation.readthedocs.io/en/latest/parameters/Heating_20model.html) inform once-only dissipation accounting, while [Kassam and Trefethen](https://people.maths.ox.ac.uk/trefethen/publication/PDF/2005_111.pdf) support the exponential treatment of conduction.

The [thermomechanical motion connection](../I01_THERMOMECHANICAL_MOTION.md) solves force, temperature and weakening at shared integration stages, including the final accepted state. External drag dissipation is recorded separately from column heating. Feedback-on/off comparisons and independent high-accuracy solutions distinguish physical response from integration error.

The [finite-strain control](../I01_FINITE_STRAIN.md) also lets a closed strip widen and thin while material carries its temperature and history. Thickness changes pressure, resistance and conduction; total rock mass and whole-strip heat capacity stay fixed. [ASPECT's finite-strain formulation](https://aspect-documentation.readthedocs.io/en/latest/user/cookbooks/cookbooks/finite_strain/doc/finite_strain.html) helps distinguish changing geometry from accumulated plastic memory. Its [tests](../../tests/test_i01_finite_strain.py) and [reviewed controls](../../evidence/i01-finite-strain-r2.json) check material transport, geometry scaling, independent solutions and refusal of unsupported steps. The strip has no lateral necking, mantle inflow or rupture.

That closed strip holds its base at a fixed temperature, so nothing enters or leaves it. When a rift thins the lithosphere, the hot mantle beneath rises into the space. [ASPECT's continental-extension example](https://aspect-documentation.readthedocs.io/en/latest/user/cookbooks/cookbooks/continental_extension/doc/continental_extension.html) states that without such an upwelling layer its box cannot represent breakup. The [basal closure](../I01_BASAL_CLOSURE.md) therefore opens the bottom of the regional rifting box. Named asthenosphere enters through a fixed base 150 km down, below the 100 km lithosphere, at a prescribed, uniform upward speed. It brings its actual temperature and composition and no deformation history. Rock leaves through the sides at its own actual state, never reset to a boundary value. The top is a free surface: it rises and falls, but no rock crosses it.

This changes the accounts. Constant volume is not constant mass, because dense mantle replaces lighter crust leaving through the sides. Basal inflow equals side outflow only when the surface's net movement is zero. Heat carried by moving rock, heat conducted through each boundary and mechanical work are booked separately, so the pressure work of entering rock is not counted again as heat. The settings follow the example's parameter file and ASPECT's boundary documentation. [Brune et al.](https://www.earthbyte.org/Resources/Pdf/Brune_etal_2014_Rift_migration.pdf) supply the deeper domain, with asthenosphere below the lithosphere. Exact arithmetic and closed-form geometry check the balances, finite supplies, reversed flow and refusals. These are bookkeeping checks on supplied flows, not a solved flow field. The resolved rift (I07) must still test how the neck responds to this boundary and to its depth, and any melting of the rising mantle waits for a melt law. Transport through the strip and chain (I05) then uses the same inflow records.

The [reviewed controls](../../evidence/i01-basal-closure-r1.json) now connect the rock inventory to the box volume, insulating conditions to booked heat, and endpoint records to their source accounts. A shortening strip is refused if its lithosphere would cross the fixed base. For the work signs, a simple exact flow supplies boundary work, gravity work and internal dissipation independently; deliberately reversing signs or counting pressure work twice fails. This checks the boundary specification and accounts, not a simulated rift. I05/I07 must still connect the actual transported states and solved fluxes to one boundary configuration.

Neighbouring columns also exchange heat sideways. The [lateral-heat criterion](../I01_LATERAL_HEAT.md) asks how much temperature error ignoring those connections could accumulate. For a supplied whole-interval temperature contrast, it sums each contact's possible heat flow, divides by the cell's heat capacity and accumulates the result over time. It uses the conservative contact law described by [NIST FiPy](https://pages.nist.gov/fipy/en/stable/numerical/discret.html), with the mesh and monotonicity restrictions discussed by [Droniou](https://arxiv.org/html/1407.1567v1). The error inequality is derived in the Atlas method, not a published tectonic calibration. A two-cell exact solution and a small independent matrix solution check the calculation. Endpoint snapshots alone cannot supply the required bound. This selects the thermal criterion, while moving geometry and feedback from changed temperature into rock strength still need the later coupled implementation.

## 6. Produce melt, then account for extraction and delivery

The [common-provider connection contract](../I01_THERMO_PROVIDER_CONTRACT.md) defines what a future calibrated model must pass between these steps. It must identify the ingredients, units, energy reference and conditions where its predictions are supported, and carry the actual mass and energy rather than just a percentage melted. It also distinguishes an empty inventory, an uncertain solution and a model used outside its supported conditions. Existing analytical checks are reused; this is an interface design, not a new melting model. Cantera's explicit mass/molar properties and alphaMELTS's total-energy and gram-based outputs informed the unit boundary.

The [melting control](../I01_MELTING.md) follows a dry mantle parcel through falling pressure. Melting consumes heat, which feeds back into the amount produced. It uses [Katz, Spiegelman and Langmuir's parameterisation](https://doi.org/10.1029/2002GC000433), with the existing method record explaining the ASPECT and pyMelt source comparisons. Exact limiting cases and a tighter independent integration check the thermal path. The result is retained melt mass, not a supply rate or transported magma.

Extraction changes composition. The [phase-partition control](../I01_PHASE_PARTITION.md), informed by [Keller and Katz](https://eprints.gla.ac.uk/195948/1/195948.pdf), tracks ingredients in solid and liquid separately. Otherwise, reusing the original composition after extraction can recreate melt that has already left.

Near complete melting, subtracting nearly all the liquid from the starting rock can lose the tiny remaining solid in numerical rounding. Atlas now calculates each ingredient's smaller phase amount directly and obtains the larger amount by subtraction. The physics and tolerances are unchanged. Independent known mixtures, extreme partition coefficients and heat/entropy recovery just inside both melting boundaries check the fix. The [Chemicals numerical notes](https://chemicals.readthedocs.io/chemicals.rachford_rice.html#numerical-notes) informed the stability review; its gas/liquid software was not used as a mantle model.

The new [composition-aware energy law](../I01_PHASE_ENERGY.md) now derives phase proportions and heat content together for an explicitly ideal mixture. Supplying energy lets it solve temperature and phase amounts, including melting at constant temperature. Removing liquid takes that liquid's ingredients and energy; the residue retains its changed composition. An analytical 10,000 kg source carries 5.8 GJ. Extracting 1,000 kg removes 0.9 GJ; cooling that extracted material releases the same heat to the surroundings. Thermodynamic derivative checks, signed energy references and latent-heat plateaux test more than conservation alone. Its basis includes the phase/energy treatment in [Keller and Katz, section 2.1.1 and Appendix A.2.2](https://eprints.gla.ac.uk/195948/1/195948.pdf), checked alongside the [R_DMC implementation](https://github.com/richard-katz/R_DMC/blob/master/src/R_DMC_Equilibrium.m).

The [pressure-change connection](../I01_PHASE_PRESSURE.md) then lets material move to a different pressure while retaining its ingredients and entropy. Melting uses sensible heat; freezing releases it. The code solves the new equilibrium directly rather than storing a long pressure-step history. It distinguishes the change in heat content (enthalpy) from mechanical work on the expanding or contracting material. An analytical half-molten parcel decompresses from 1 GPa and 1720 K to zero pressure and 1600 K; its molten fraction rises from 0.5 to 0.789283. Independent work integrals, a refined binary pressure integral and a receiver-connection check test those accounts. [Cantera's entropy/pressure equilibrium interface](https://cantera.org/stable/python/thermo.html), [pyMelt's mantle source](https://pymelt.readthedocs.io/en/latest/_modules/pyMelt/mantle_class.html) and [Keller-Katz's thermal equations](https://eprints.gla.ac.uk/195948/1/195948.pdf) were checked. The retained constant-volume law does not include single-phase thermal expansion.

The [compatible receiver](../I01_MAGMA_RECEIVER.md) now takes that extracted liquid into a finite body using exactly the same material law and pressure. Adding component masses and enthalpy determines how much crystallises or melts and the resulting temperature. Latent heat is already included, so it is not added a second time. Mixing can produce entropy and change volume: the method also checks the associated pressure-volume work. Independent pure and binary examples give exact reference answers. Parcels arriving together can share one equilibrium solve; the [receiver controls](../../evidence/i01-magma-receiver-r2.json) measure its matched performance. [Cantera's H/P mixing example](https://cantera.org/stable/examples/python/thermo/mixing.html) and the Keller-Katz component/energy equations informed the account structure, not the analytical material calibration.

The separate [delivery interface](../I01_DELIVERY.md) carries sensible and latent energy into W08 emplacement under its different, common-melting-temperature law. The new ideal-mixture receiver does not silently replace either that law or Katz's mantle parameterisation. Calibrated material properties, chosen pressure/flow histories and native thermal/geometry embedding still need connecting. Extraction amount, permeability and focusing remain open physical choices. See the [phase-energy controls](../../evidence/i01-phase-energy-r3.json) and [pressure-work controls](../../evidence/i01-phase-pressure-r2.json) for the underlying bounded law and solver improvements. Numerical transfer proposals do not provide persisted material identity or once-only delivery; those belong to the integration state/transaction layer.

## 7. Admit a transition only when its physics and transfers are supported

The [transition contract](../I01_TRANSITIONS.md) covers separation, new sea floor, boundary migration, subduction initiation, collision and junction changes. A proposed event must be located in time, transfer finite inventories once, preserve history and resolve competing demands together. Root-finding limitations documented by [SUNDIALS](https://sundials.readthedocs.io/en/latest/cvode/Mathematics_link.html) inform checks for missed crossings; balance, replay and simultaneous-event controls check transfers.

Two junctions can each move consistently yet run into one another. The [contact helper](../I01_JUNCTION_EVENTS.md) now finds that meeting exactly for declared straight-line, constant-speed paths. Simply looking for distance to change sign cannot work: distance reaches zero and grows again. Independent algebraic controls check the meeting time, tiny near misses, moving frames and extreme numbers. The helper reports a candidate, not permission to invent a ridge, trench or fault. McKenzie-Morgan's stability definition (abstract inspected), Kleinrock-Morgan's stress-controlled reorganisation discussion and pyGPlates' shared-boundary representation informed that distinction. The full physical reorganisation rule and connection to moving spherical boundaries remain open.

After contact, the [outgoing ridge check](../I01_RIDGE_JUNCTION.md) asks whether a proposed new ridge can move consistently at both ends and actually grow in the direction allowed by plate ownership. Merely measuring a positive length can miss backwards growth. An exactly soluble four-plate example, moving-frame checks and deliberately incompatible candidates test this calculation. It is a small reused calculation, not another simulation. Gerya and Burov's oceanic-junction research and Koptev and colleagues' thermomechanical experiments reinforce why compatible movement is only part of the answer: creating the boundary also needs the rock's mechanical/thermal state and a supported propagation mechanism. The inaccessible Gerya-Burov steady-state formula has not been guessed or implemented.

The [decoupling control](../I01_DECOUPLING.md) asks whether replacing a deforming belt by a simpler boundary would change motion beyond a declared allowance throughout an interval. [Column admission](../I01_COLUMN_ADMISSION.md) supplies a conservative bound from the actual mixed-creep column, without replacing its rock laws. Failure means the bound cannot certify the switch. Passing establishes a conditional numerical error allowance; it does not establish physical rupture.

The [physical junction-reorganisation rule](../I01_JUNCTION_REORGANISATION.md) now chooses how to connect those prerequisites to the rock model: keep a small deforming region around the junction, allow competing directions to evolve, then simplify it to plate boundaries only when the physical interfaces and their motion support that change. Existing stress, heat and weakness stay with the rock. A ridge needs actual material supply; a trench needs an admitted sinking mechanism; an unresolved region need not become three neat lines immediately. Kleinrock and Phipps Morgan's local-stress analysis, Gerya and Burov's distinction between rifting and mature spreading, and Koptev and colleagues' three-dimensional experiments support this direction. ASPECT's actual 3D yield implementation fixes the proposed stress convention; it cannot silently reuse a 2D strength number. This is a selected method and coding sequence, not an implemented junction simulation. The completed contact/movement helpers remain useful without being rerun or mistaken for the full physical rule.

The [finite-strain admission](../I01_FINITE_ADMISSION.md) now extends that reasoning to the widening, thinning, heating strip. It bounds resistance using the carried geometry and weakening history, then checks a future interval on the strip's actual cumulative clock. Only states issued by the retained evolution can pass: editing the clock cannot recover time already used. Internally owned heat operators also prevent a changed calculation masquerading as the same evolution. Independent closed-form cases, genuine evolved endpoints, aggregate work/displacement and deliberate invalid-state tests check this connection. The mathematical bound covers intermediate stages conditionally; endpoint samples alone do not prove that. [The controls](../../evidence/i01-finite-admission-r1.json) retain non-admission for the strong layered column rather than loosen the tolerance. Goldberg's [floating-point analysis](https://docs.oracle.com/cd/E19957-01/806-3568/ncg_goldberg.html) and Python's [dataclass semantics](https://docs.python.org/3.12/library/dataclasses.html), inspected for the specialist method, inform numerical bounds and state ownership. Reusing a prepared bound saves repeated calculation; persisted continuation and physical breakup remain separate responsibilities.

The [breakup control](../I01_BREAKUP_CLOSURE.md) examines whether a narrowing neck can reach zero thickness in finite time, rather than declaring breakup at an arbitrary thickness. For its precisely stated creep law and quadratic weakness, an exact continuum solution shows when this is possible. The discrete columns agree at the first thinning level; they do not resolve every later, much narrower neck. The [reviewed checks](../../evidence/i01-breakup-closure-r1.json) therefore establish analytical feasibility, not a generated split. They also show why weak resistance alone does not prove separation and why a finite set of gentle slopes cannot justify a law whose limiting neck becomes too steep. The method documents the Hutchinson-Neale and Audoly-Hutchinson necking sources and the Brune/ASPECT rifting comparisons; no new geological calibration is implied. The mixed-creep/plastic lithosphere still needs resolved neck mechanics before an event can be issued.

The [separation decision](../I01_SEPARATION_DECISION.md) defines the checks the future resolved model must report. Crust breaking apart, deeper mantle rock disconnecting, and a simpler boundary reproducing the same motion are different questions. It tracks actual material, including bridges that pass from crust into mantle and back, rather than declaring a split when a coloured cell disappears. Motion must remain close over a declared interval, not just its endpoints. An exact worked example shows why an apparently converging sequence of thinning measurements can still leave unbroken rock. Brune's rift-migration results and ASPECT's material-tracking example inform the distinction; the norm and refusal rules are Atlas design choices, not a new simulated breakup result.

For subduction, [the selected initiation method](../I01_INITIATION_DECISION.md) asks the regional model to calculate how bending, friction and flowing rock resist sinking, instead of supplying a convenient resistance number. It keeps stored elastic stress and plastic weakening as different histories. Water pressure is an explicit scenario input, not an invented drainage simulation. Weakening has a physical length, so smaller mesh cells do not automatically make the plate easier to break. The future test will remove the driving force without clamping the plate, and distinguish continued gravity-driven sinking from a short elastic rebound. Gurnis, Hall and Lavier's original force/convergence experiments and ASPECT's pressure, material-history and analytic load comparisons informed the specification. The research also exposed missing benchmark inputs: these must be fixed before testing, not selected to fit the answer. No new sinking simulation has passed yet.

The [initiation comparison tool](../../tools/check_i01_initiation_inputs.py) now checks whether the required definitions have sources and have been reviewed. Unknowns remain unknown. Once those inputs and the comparison rules are ready, it can compare resistance against distance travelled, including peaks between the published sample points, and calculate the work done. The plan fixes the input and tolerance identities before the run; missing coverage, changed plans and incompatible units are refused. Its synthetic tests check the measuring tool, not whether subduction itself is realistic. Published reproduction and Atlas's separate force-release test remain distinct.

Reading the original benchmark more closely matters here: its older, 40-million-year right-hand plate sinks beneath the younger, 10-million-year left-hand plate. Its published material constants are now recorded, but a complete input recipe is still unavailable. The paper's basal-temperature descriptions disagree, and several boundary and weakening definitions remain missing. The research also recovered approximate graph readings; their line thickness describes how precisely we can read a figure, not how accurately a model represents nature. All 28 readings are preserved, but the original extraction did not retain the script or coordinate calibration needed to reproduce them, so they remain outside accepted comparisons. Nor can the paper's weakening-strain number simply be copied: its precise definition must first be related to Atlas's accumulated engineering plastic shear.

Generated breakup, compatible melt supply, the remaining initiation benchmark inputs and the evolving global geometry still require closure. The [reviewed transition evidence](../../evidence/i01-transitions-r2.json) supports bounded event machinery, not generated-world acceptance. Existing receipts and source-bound method documents retain their original meaning; explaining their connections does not renew or extend their evidence.
