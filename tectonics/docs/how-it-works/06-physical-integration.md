# Connecting the physical processes: I01

[Guide contents](../HOW_TECTONICS_IS_MADE.md) · [Physical methods](02-tectonic-processes.md) · [Workflow and delivery](03-coupling-and-reliability.md)

Tectonic processes affect one another. Temperature changes rock strength; strength affects motion; motion changes thickness, heating and the forces driving the next interval. I01 investigates the physical rules needed to connect these effects without losing material, inventing heat or counting a force twice.

**I01's method choices, contracts and bounded feasibility are complete; the work remains WORKING NON-CANON.** I02 connects one real finite-strain column through shared state, coupled advancement, atomic state-and-exchange commits, one accepted clock, and saved-state continuation (section 8). I03 places one closed spherical network beside that history and moves it under supplied plate rotations, carrying its rock (sections 1 and 5). Its regional bridges return results only to the support and forcing for which they were calculated. Supplied plate splits, merges and ridge jumps commit with their interval, and explicitly supplied compatible junction paths can generate curved boundary ends. New rock that crosses from ridge to trench within one interval is supplied and consumed without inventing rock at the endpoint. These are joined prescribed-history mechanisms, not a physical motion/event producer. The sections below follow physical dependencies, not implementation dates. Source-bound controls and their successors are listed in [current evidence](../../../docs/CURRENT_EVIDENCE.md); completion and platform coverage live in [current status](../../../docs/CURRENT_STATE.md). The [integration architecture](../INTEGRATION_PLAN.md#4-architecture-one-evolving-physical-state) distinguishes this joined route from later physical-event work. The [experimental dynamics route](05-experimental-dynamics.md) remains separate.

The research links below come from the existing method records. They explain the chosen methods; this chapter adds no research campaign, numerical run or scientific acceptance.

## 1. Start from one declared physical state

The [physical contract](../I01_PHYSICAL_CONTRACT.md) identifies the world, time, geometry, material inventories, temperature, deformation history and physical assumptions. Each exchanged quantity also needs units, a reference level and the area or volume it represents. Matching array sizes is insufficient: two arrays may describe different rocks or thicknesses.

Plate identity and material identity remain separate. A rock parcel can change plate without losing its formation age, temperature or deformation history. Likewise, reheating ocean crust changes its thermal history without making it newly formed crust.

The intended accepted-time loop reserves finite material and heat transfers, checks the coupled result, then commits geometry and accounts together. Its design distinguishes supplied histories from generated evolution. A prescribed movement or event can test a transfer without demonstrating that Atlas predicts it.

### The first shared state: the finite-strain column

Before anything advances, Atlas records one declared starting state in a single
unchangeable [common-state record](../I02_COMMON_STATE.md). The first case is the
finite-strain column described in section 5: a closed strip of layered rock that
can widen, thin and heat. The record names the bounded case and scenario, the time
base, the strip's own frame and the surface that depths are measured from. It also
keeps the equations, rock and forcing parameters, numerical limits, and the source
and runtime that produced the starting values.

Two references matter. The mechanical reference fixes the unstretched layer
thicknesses, depths, pressures and densities; the thermal reference fixes the steady
temperature profile, heat capacity and heat sources. Both are kept exactly as
prepared, together with the inputs that reproduce them, so a later continuation can
rebuild its solvers instead of saving opaque solver objects. The changing state is
recorded separately: how far the strip has stretched, how far each rock parcel's
temperature departs from the steady profile, and how much plastic deformation it has
accumulated. Stretch and current geometry always refer back to the original shape;
a deformed strip never becomes a new starting shape.

Each quantity has one owner, a unit and the volume or area it describes. Rock
identity comes from the existing material records, with its origin and unknown
formation date preserved. Optional finite stores keep their own energy convention
and cannot duplicate rock that the column already owns. Physics this column does
not represent, such as elastic stress, melt, absolute elevation or a position on a
globe, is marked unknown rather than filled with zeros. The pieces are checked
against each other: heat capacity must equal density times specific heat times the
rock volume, for example. Mismatched time, units, support, references or ownership
are refused.

The record itself is not a calculation. It creates no rock and grants no permission:
the finite-admission check in section 7 still accepts only states produced by its own
evolution. Sixteen focused checks preserve the actual starting case, rebuild its
reference values exactly and deliberately try wrong inputs and caller mutations. They
pass after correcting an exposed array-descriptor alias and enforcing the existing
duration limit.

**Continuing from the record (implemented, awaiting review).** A continuation first
rebuilds the column's solvers from the recorded inputs and checks that they reproduce
every stored reference value exactly, not just a matching label. A changed runtime or
edited reference therefore stops the history instead of silently continuing it. It
then advances whole steps of the original timetable; a later piece never recalculates
its own step length or gains a fresh step budget. Each accepted piece produces a new
record that names its parent and the original starting record. It carries the
stretch, temperatures, plastic history, heat and work accounts, and step count
forward from exactly where the previous piece stopped. The unstretched reference, the
rules and the original rock records are shared unchanged; the rock records keep their
original date, and the current shape is always worked out from the original shape and
the accepted stretch. If a step is refused, the last accepted record is returned
unchanged with the reason. Splitting a history into uneven pieces is designed to give
exactly the same numbers as one uninterrupted run, and to agree within the existing
solver tolerance when a new session rebuilds the solvers. Review ran the focused
checks for this, and they passed. It also found that inspecting the prepared solver
handed out the solver's own working objects: changing the shape of one of their
arrays crashed the next piece or made it wrongly report that the rock-strength
calculation had failed, although no accepted record changed. The solver now keeps
private copies of its prepared column and heat-flow operators, and inspection hands
out a fresh copy each time, so editing that copy, or the objects originally supplied,
cannot affect later pieces. This protection recomputes nothing. The correction and its
mutation and continuation regressions have passed review and execution. Committing
exchanges, one accepted clock, and saving and reopening a record now exist as an
integrated workflow, described in section 8.

### The shared spherical network: one owner for every point of the sphere

The column above is one strip of rock. A planet also needs to know where its plates
are. The [spherical network](../I03_SPHERICAL_NETWORK.md) is that map, kept beside
the column in the same saved history. It divides the whole sphere into faces. Each
face belongs to exactly one plate, so every point has one owner and the faces
together cover the sphere once.

A boundary between two plates is stored once, as a line with a direction, a plate on
its left and a plate on its right. It also says what kind of boundary it is and the
one rule that kind needs: a ridge states what share of its opening each side
receives, and a trench states which side goes down. Nothing is assumed when a rule
is missing. Points where boundary lines end are junctions; Atlas works these out
from the lines rather than accepting them as given. Each plate carries one rotation
describing how far it has turned since a stated reference time, and each boundary
records where it came from: the declared starting condition or a named event.

The geometry is the closed spherical atlas of the
[foundations chapter](01-foundations.md#geological-geometry-and-shared-plate-boundaries),
checked by that atlas's own tests. A gap, an overlap, a face claimed twice, a
boundary line that stops part-way along an edge or a pinched face is refused. Atlas
does not close gaps, merge near-identical points or tidy a declaration to make it
valid. The lines that separate plates are also kept apart from the mesh used for
bookkeeping: an edge between two faces of the same plate is only a seam of that
mesh, and it can later be redrawn without touching a plate boundary.

Rock is recorded separately from plates. Each face holds one or more pieces, and
each piece belongs to a cohort: rock with one origin, one formation interval and
one reference to its history. A piece has four kinds of account, never merged: the
area it occupies, a reference mass and a volume for each declared rock phase, and
its heat content measured against a stated baseline, which can be negative. A plate
name never appears in a rock record, so regrouping faces into different plates
changes no rock. An account that was not declared is reported as unknown, not as
zero, and so is a formation date that was not given. The pieces of a face must fill
it: this is checked for every face when a world is declared, after every interval and
whenever a saved state is reopened. All the pieces together must always cover the
sphere once.

The totals are also kept as exact fractions, so "what is stored equals what was
declared plus what has since been supplied" can be checked exactly rather than
approximately. Every network, material record and state has an identity derived
from its complete contents. A saved history that includes a network binds that
identity into its own, and reopening rebuilds the network through the same checks
that created it; a record or array edited in the file no longer matches and is
refused.

[These checks](../../tests/test_i03_network.py) build small declared worlds of six
or eight pole-to-pole sectors, confirm their coverage and boundaries, and
deliberately try each kind of invalid declaration. They repeat the world about a
tilted axis, so that nothing depends on where the coordinate poles are, and confirm
that expressing it in rotated axes changes no area, neighbour or junction. Further
[checks through the saved history](../../tests/test_i03_ledger.py) reopen it in a
new process. They establish that the bookkeeping and geometry are consistent. They
do not show that any such plate layout is geologically plausible.

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

At each stage, driving work must equal drag dissipation plus column work. Exact linear examples and an independent [SciPy Brent root solver](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.brentq.html) check the nonlinear solution; evolving cases then test time and depth refinement. The [implementation](../../tools/check_i01_motion_coupling.py), [focused tests](../../tests/test_i01_motion_coupling.py) and [recorded control result](../../evidence/i01-motion-coupling-r3.json) make that reasoning inspectable. This is a regional force balance with supplied drive, not an assembled moving sphere.

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
These acceptance checks are relative to the problem's own magnitudes, so the
internal units chosen for a calculation cannot make an inaccurate or empty answer
pass; before 30 September 2026 a problem posed in SI units with unit scales could
return zero velocity while reporting a tiny residual. Each equation is judged
against its own terms, so a weak layer beside strong rock, or a small density
anomaly riding on the full weight of rock balanced by pressure, is checked at its
own scale. When a first answer falls short, the solver refines it and still
refuses if it cannot meet the same checks. A separate energy balance confirms
that the published stresses agree with the equations; it cannot see an error in
the rotational part of the flow or in the published pressure's scaling, which the
exact test solutions cover instead.

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

That stored matrix is what limited resolution. Each velocity unknown is coupled
to about 180 others, so the matrix and its approximate factor grew so quickly that
the default memory allowance refused every 7x7x7 box. Correctly counting the
factorisation library's working storage also refuses a 6x6x6 all-free-slip box
under 256 MiB (about 271 MiB required), while an all-velocity-prescribed box fits
(about 216 MiB). The allocation check no longer creates extra copies of both
factors merely to count them. These changes affect safe admission, not the
equations. A second solver avoids
the large assembled velocity matrix. It is integrated locally with the
automatic choice described below. It applies the same
equations directly from one shared table for
a standard box-shaped cell, without storing the big matrix. It speeds up the
iteration with a hierarchy of coarser versions of the same problem: first simpler
functions on the same cells, then larger cells. It finishes with the same checks,
tolerances and outputs as before. Viscosity is sampled at the same points on the
coarser levels, so strong and weak rock stay distinct there. When only the
viscosity changes, the box layout, boundary pattern and coarse-level connections
are reused rather than rebuilt. The
[method section](../REGIONAL_MECHANICS_3D.md#matrix-free-multigrid-candidate-i072-solver-scaling)
lists the papers and programs consulted
([May, Brown and Le Pourhiet](https://jedbrown.org/files/MayBrownLePourhiet-ScalableMatrixFreeMultigridPreconditionerFEHeterogeneousStokes-2015.pdf),
[Clevenger and Heister](https://arxiv.org/abs/1907.06696), ASPECT, PETSc and
MFEM) and what the scratch measurements found.

Which solver runs is now decided per prepared problem, unless the caller names
one. Before anything is reserved, Atlas works out how much memory each solver
would need, and measures how varied the viscosity is, the shape of the cells and
how many cells there are. The new solver runs whenever it fits the memory
allowance and the problem lies in the range where it has been shown to converge:
- viscosity varying by up to a factor of 100,000 in near-cubic cells, or up to
  1,000 in cells as flat as 4:1;
- at least 4 cells along every axis.

Outside that range, or when only the original solver fits, the original solver
runs. If neither fits, the problem is refused. The rule solves nothing to decide
and takes about a millisecond. Each result records which solver ran and why, and
a saved run can only be continued with the same selection policy and set of
admitted solvers. Evolution keeps those admission choices fixed: temporary
competition for shared memory refuses work rather than silently switching
solver. Changed viscosity can still change the choice under the recorded rule.

On 29 measured problems, the new solver was faster or about equal in 27 and
passed every check in all of them. Choosing it everywhere took about a quarter
of the original solver's time; an earlier, more cautious rule took about half.
That aggregate does not include the separate range-edge probes. Some small,
rough-viscosity cases lose more: one took 2.37 seconds instead of 0.97 seconds
(1.40 seconds, or 144%, longer). Easy problems solved many times over can also
be slower. Multigrid-first deliberately accepts these exceptions; it is not a
promise to choose the fastest solver for every workload.
Above the stated range each solver fails some cases the other solves, so the
original stays the choice there. The
[method section](../REGIONAL_MECHANICS_3D.md#automatic-choice-between-gmres-and-multigrid-methodauto)
gives the rule, its measurements and its limits.

[FEniCSx](https://docs.fenicsproject.org/dolfinx/main/python/demos/demo_stokes.html)
and [ASPECT](https://aspect-documentation.readthedocs.io/en/latest/user/methods/numerical-methods.html)
informed the mixed-element and block-solver choices. The actual
[PETSc 3D Stokes example](https://petsc.org/release/src/dm/impls/stag/tutorials/ex4.c.html)
was checked for variable-viscosity and pressure handling; the
[consistent-reaction example](https://bleyerj.github.io/comet-fenicsx/tips/computing_reactions/computing_reactions.html)
explains why forces should come from the original equations. These are method
references, not claims of an executed comparison against those programs.

The [plate connection](../REGIONAL_MECHANICS_3D.md#planet-centred-plate-motion-and-returned-torques)
now translates actual planet-centred plate rotations into movement at the edges
of this box. It keeps all three movement directions and uses the actual distance
from the planet's centre, not a convenient local lever arm. The rock's resistance
returns as a torque on each plate, with equal and opposite torque on the region.
The two sides exchange exactly the same mechanical work. Fixed supports and
unowned boundaries are kept separate, so their resistance is not wrongly charged
to a plate. The calculation can either use supplied rotations or solve rotations
from full driving torques and the region's calculated resistance.
In a closed box without a declared mean pressure, the pressure is known only up
to a constant, and that constant would shift each plate's torque unless its
boundary motion carries no net volume flux. Such per-plate torques are therefore
refused rather than published; totals remain available.

An analytical twisting column checks the rotation, returned torque and work
independently. The mapping is prepared once and reuses the existing solver's
matrix and motion response. [pyGPlates' velocity documentation](https://www.gplates.org/docs/pygplates/generated/pygplates.calculate_velocities)
informed the global/local distinction; the consistent-reaction example above
informed the torque calculation. Neither program was installed or benchmarked.

This is a same-time connection in a declared flat box, not a curved planetary
mesh. The material/heat connection below advances a solved region; joining many
evolving regions and plate motions into one world state remains separate work.

## 5. Advance heat, history and geometry together

### Move the plates of the shared network and carry their rock

Over each accepted interval, the [network of section 1](#the-shared-spherical-network-one-owner-for-every-point-of-the-sphere)
is moved by one supplied rotation per plate. In this mode the rotations, and what
ridges supply and trenches remove, are given to Atlas; calculating them from forces
is later work. A plate that does not move must be told so. Leaving a plate out is
refused, because unknown motion is not the same as no motion.

**Faces ride with their plate.** A face away from any plate boundary keeps its
shape, and its rock records are not touched at all: afterwards they are the same
bytes. Each plate keeps its corners in its own frame of reference, turned once to
place them on the sphere. A ridge keeps its corners the same way, in a frame of its
own. So a face that only rides keeps exactly the same numbers and the same measured
area, however far it travels. An earlier version re-rounded every corner each
interval, and over many intervals a narrow strip's area drifted from the rock it
held. Only what happens at the boundaries changes anything. Where a plate's face uses
a corner kept by another plate or by a ridge, the plate keeps its own copy of it, and
that copy may lie no further from the corner than 64 times the spacing of the stored
numbers; this is checked again whenever a state is saved or reopened. Two plates
moving apart more slowly than that each interval therefore still open a ridge once
their motion adds up, instead of leaving a gap that no account records.

**Each boundary moves by its declared rule.** A boundary between two plates that
turn together is locked and moves with them. A ridge moves with a blend of its two
plates' motions set by its declared share; with equal shares it travels at their
average. A trench moves with the plate that stays at the surface. A boundary where
plates only slide past each other moves with the plate it names as carrying it; the
other plate's cells beside it are sheared and their rock passed along between them,
never across the boundary. It is accepted only when the slip runs exactly along the
boundary's great circle; a boundary with any opening or closing must be declared a
ridge or a trench.

**New crust is made as new faces.** When a ridge opens, each plate keeps the edge it
had, and the strip between that old edge and the ridge's new position becomes new
faces of that plate. They hold a new cohort whose formation interval is exactly the
accepted interval, and whose mass, volume and heat are the declared amounts per
unit area from a named source. Older faces are never stretched to fill the space.
This is what keeps ages honest. In the staged test from the
[physical contract](../I01_PHYSICAL_CONTRACT.md), where the ridge and plate speeds
change part-way, crust born in the first stage reports a mean age of 4.0 million
years from its own record. Dividing its present distance from the ridge by the
present spreading rate would wrongly give 4.2.

**Consumed crust leaves through the trench.** The down-going plate's cells that
touch the trench are shortened to end at the trench's new position. The part that
has passed the trench is removed, with every cohort it held, and its mass, volume
and heat are booked to declared destinations in declared shares. A cell cannot give
more than it holds: a movement larger than the cells at the trench is refused, not
trimmed.

**Amounts move by measured overlap.** Wherever a cell changed shape, Atlas
intersects its old outline, carried with its plate, with the new cells and with the
strip the trench swept. The areas are measured on the sphere itself. Each account
is divided in proportion to those areas, and the parts add up to the original
exactly, so nothing is created, lost or counted twice. A cohort's dates and history
reference travel with each part unchanged, and no average age is ever formed. The
overlaps must add up to each cell's own area to about one part in a million million,
or the interval is refused. A cell roughly a kilometre across or less on an
Earth-sized sphere cannot always be measured that precisely, because its corners
are stored as rounded numbers. When a cell lies wholly inside another, Atlas decides
that exactly, without rounding, and moves its rock whole. So renaming a narrow strip,
merging it into its neighbouring cell or splitting it off again always balances. When a
redraw merges two very thin strips, their balance is held to the largest error that
rounding their measured areas could produce. That bound grows with a strip's length,
not its width. For strips a few metres wide it is about five parts in a thousand
million of the strip's area; for strips a fraction of a micrometre wide it reaches a
few per cent. The cell keeps an allowance of up to twice that, which governs every
later check of its rock against its area. A rename keeps the allowance unchanged, and
a later redraw replaces it rather than adding to it. When a trench cuts a very thin
cell, the interval can still be refused.
If a
source or destination is one of the saved history's
finite stores, the amount is taken from or added to that store in the same save,
and an empty store refuses the whole interval.

**Junctions must stay closed.** Where three or more boundaries meet, each boundary's
rule says where the meeting point should go. If they agree, it goes there. If one
straight boundary runs through the point and a third ends on it, the point slides
along the straight one, to where the third one's new position crosses it. The plate
carrying the straight boundary keeps its old corner as a new point on it, so its own
faces do not change. Three independently rotated, rigid boundary ends generally stop
meeting exactly. That does not by itself mean the plates must physically rearrange:
the boundary ends may need new segments as the junction advances. For an
outward-growing ridge junction, the supplied-history route now accepts an explicit
path for that meeting point and constructs the ends left behind it. The path is an
input because plate speeds alone do not uniquely choose future oblique ridge
directions. Atlas does not smooth the map until it looks plausible.

Curved ends are represented by short great-circle segments. A declared error bound
controls their spacing, while the actual analytic tangent controls velocity closure.
The supplied path must match the inherited tangent, and a conservative bound checks
that the meeting directions stay distinguishable throughout the interval, not just
at a few sampled times. An inconclusive bound refuses; it does not prove physical
instability. Accuracy must lie above coordinate roundoff and below the declared
90-degree representation cap. Neither changes the physical closure tolerance.

More stringent accuracy adds segments by repeated halving: one, two, four and so
on. A ceiling of three therefore allows at most two segments. Exact great-circle
ends stay sparse, but still split if one nearly antipodal segment would violate the
existing chart limits. The declared memory ceiling remains charged until geometry
and material transfer finish. The
[path-contract controls](../../tests/test_i03_path_contract.py) exercise these rules;
[moving-history controls](../../tests/test_i03_junction_paths.py) cover rotated
coordinates, refinement, saving and nonzero continuation.

Ordinary sampling vertices can also be passed without treating them as physical
collisions: along a carried transform line, by a carried ridge ending on that line,
and by a ridge ending on a trench line. A strict pass, an exact landing and several
passed vertices must leave the new strip and trench accounts on the updated chains.
These are the [vertex-traversal controls](../../tests/test_i03_vertex_traversal.py).
Passing a sampling vertex is not built where the vertex would subdivide a
same-interval ridge-to-trench triangle at the junction. Such a step is refused,
and the refusal says so rather than blaming the geometry; a pass outside the
triangle is admitted.
A material seam is different: its endpoint must follow its carried interior edge's
intersection with the trench. Unconstructed seam changes still refuse. A real
encounter with another junction needs an admitted reorganisation.

Some crust can be born at a ridge and swallowed by the adjacent trench before the
interval ends. Atlas now records both transfers from the actual swept geometry,
preserving the new crust's formation interval, source and heat even though it has
no surviving cell. The finite source and destination stocks commit together, or
neither changes. Restart checks cover that short-lived material as well as the
visible endpoint map.
At a ridge fraction of exactly zero or one, a side with no opening receives no new
rock. It may still lose old rock at the trench; no zero-area birth is manufactured.

**The mesh can be redrawn.** Cells may be merged or split between intervals, for
example to merge the narrow strips that many small openings leave behind. Rock is
transferred by the same measured overlaps. A redraw cannot move a plate boundary,
give a cell to another plate or change any formation date.
When a saved mesh is rebuilt, replay keeps every other field of the original motion,
including the supplied junction paths, events, returns, sources and destinations.
Replacing the mesh is not permission to reconstruct an older, shorter version of
the proposal. The combined path/mesh/event record and its identities must reproduce
before a reopened history can continue.

**The same memory limit follows the work.** Moving geometry, transferring rock and
restoring a saved step all charge the budget supplied by the caller. Reusing saved
overlaps saves calculation, but does not remove the memory needed to reconstruct
the state. Focused checks deliberately exhaust that budget and confirm that Atlas
refuses without publishing a partial result or leaking temporary reservations.

[The checks](../../tests/test_i03_transfer.py) use exact geometry: the area between
two meridians a known angle apart. A state that does not move, and a whole sphere
turned as one piece, transfer nothing and change no rock record. One plate turning
between fixed neighbours gains and loses exactly the predicted areas, and its
mass, volume and heat balance exactly. The same histories about a tilted axis give
the same accounts. Very slow boundaries, down to a ten-thousand-millionth of a
degree per interval, still balance at the precision the cells can be measured to,
and the strips a few metres wide that they leave ride on through later intervals.
A state holding a 55-metre strip, turned twenty times as one piece, keeps every
cell's rock equal to its area after every turn; the strip can then be renamed,
merged into its neighbour and split off again, with every account exact.
Cells at the poles only a kilometre and eleven metres tall are either moved with the
right balances or refused as unresolved, never moved wrongly. A square about a metre
across, far from the middle of a cell thousands of kilometres wide, is measured to
the precision the foundations already require of small areas. Each refusal above is
provoked deliberately. These checks show that the bookkeeping
follows the supplied motion; they say nothing about whether such motion would
arise physically. Two effects are approximate and recorded as limits in the
[method document](../I03_SPHERICAL_NETWORK.md#12-limits-and-what-remains): cells
along a trench exchange a small amount with their neighbours each interval, so the
mix of cohorts within those cells is not exact, and a cell holds its cohorts
uniformly rather than recording where in the cell each one lies. The same section
gives the [measured cost](../I03_SPHERICAL_NETWORK.md#11-measured-cost) of a step and
how it grows with the number of cells.

**Sources reused here.** This connection uses the existing W01 shared spherical
atlas and finite rotations, the [I01 transition contract](../I01_TRANSITIONS.md)
and I02's exact accounts and replay. The supplied path's exponential/logarithm
convention uses the previously consulted
[Modern Robotics section 3.2.3 transcript](https://modernrobotics.northwestern.edu/nu-gm-book-resource/3-2-3-exponential-coordinates-of-rotation-part-2-of-2/).
The curve-error and conditioning bounds are derived for Atlas's stated trace;
that source supplies no tectonic path-selection law. The later review repairs
reuse these sources and derivations, without a new literature or physical-validation
claim. The [specialist source list](../I03_SPHERICAL_NETWORK.md#14-sources) records
what was actually consulted.

### Hand part of the network to a regional model and take it back

A regional model, such as the three-dimensional solver of section 4, works on a box
or a slice, not on the whole sphere. A
[bridge](../I03_SPHERICAL_NETWORK.md#8-regional-bridges-i033) hands it a declared set
of whole cells of the network and takes its result back, without either side owning
the rock twice.

**Going out.** Each cell's rock records travel exactly as stored, with the cell's area
measured on the sphere: the area every amount is counted against.
- **Positions.** The region also receives the cells' corner positions in its own flat
  frame of east, north and up. That frame is an exact rotation of the sphere's
  coordinates, not a map projection, so a model that keeps all three directions loses
  nothing.
- **Fewer directions.** A map model that drops the vertical must declare how much
  shortening of lengths it accepts, because the curved surface falls away below a flat
  plane. It is also told how far its cells' flat areas depart from their true areas,
  and the largest share of the motion it drops by ignoring the vertical. A section model
  that drops one horizontal direction is accepted only where no motion runs across the
  section.
- **Motion.** The plates' turning speeds and the velocity at every corner travel as
  complete three-dimensional vectors. This port currently represents constant
  turning rates. It refuses every motion with supplied junction paths, including
  special cases with a constant spatial rate. The current port does not inspect
  those cases to admit exceptions or substitute a final rotation for a different
  forcing history. Omitting motion still permits material-only reading for a map
  or three-dimensional region; a section requires motion.
- **Forces and work** are not calculated here. They are passed as unknown, never as
  zero.

**Coming back.** The region's result replaces the rock in those cells only. Every
amount must come back exactly, with no rock appearing or disappearing. Each kind of
rock must come back in the same amounts too: a region may move rock between its cells,
but may not relabel it as rock of another age or origin. Anything a region exchanges
with the world outside must go through a named source or sink. Rock outside the region
keeps its exact bytes. Refused:
- a result for a state that has since moved on;
- two regions claiming one cell;
- a result that drops a direction its region kept.

A result is saved with the interval it belongs to: it travels with that interval's
motion and is applied at its end, only to cells the interval carried unchanged.
Its calculation must use the same plate motion and elapsed time as the committed
interval. Checking the starting state alone would let a result calculated for one
motion be used under another. For three-dimensional regions, maps and sections
alike, Atlas makes a fresh extract from the actual parent, motion and duration and
checks that its identity matches. This reapplies all admission rules, including
finite velocities and any omitted direction, rather than checking projection
metadata alone. Changed sources, sinks, mesh or events are part of a changed
forcing declaration too. Atlas also checks the cells' actual spatial support:
two equally full cells in different places are not interchangeable. A rigid ride
with the plate is allowed; a mesh change that relocates the cell is not. These
checks also run when the saved history is reopened, or the interval is refused.

[The checks](../../tests/test_i03_bridges.py):
- return a region unchanged and get back the very same state;
- move rock between two cells of different plates with every account exact;
- compare the velocities across four orientations of the frame;
- provoke each refusal, including attempts to alter what was handed out.

The limits on how much a map may distort were approved before their checks first
counted. A map model declares the distortion it accepts, and anything beyond it is
refused. Nothing here shows that a regional model's answer is right: a bridge only
checks that the bookkeeping is.

**The same case seen two ways.** The same history in tilted axes, and the same motion
on a coarse mesh, a finer one and a differently drawn one, give the same plate totals,
the same rock born and consumed, and the same amounts handed to each source and sink.
- **Ordinary motion.** Where the motion is not tiny against the cells, they agree to
  about one part in a hundred million million.
- **Very slow motion.** The new strips are only metres wide and are measured less
  precisely. The original comparison counted uncertainty in the remaining strips
  but missed the thin regions swept away by trenches. Those old checks remain
  visible as expected failures. A separately declared comparison now includes the
  actual swept regions and the density of their rock and heat. The retained
  comparison reported agreement in rotated axes and on both alternative meshes, using at most
  1.192% of its uncertainty bound. That newer comparison uses a turn of `0.0002°`
  per interval, twice the historical control's `0.0001°`, and checks that the swept
  regions really lie in the thin range. The reported bound uses the existing size
  rule: full for thin rings, capped in the transition range and zero beyond it.
  This does not loosen conservation or let a trench consume more than it swept.
  Where ordinary arithmetic cannot meet that strict area check, Atlas recalculates
  only the affected overlaps with exact geometric predicates and higher-precision
  area arithmetic.
  If an ordinary planar intersection wrongly contains only lines or points despite
  a significant overlap detected by its union, the same bounded exact method handles
  the original spherical polygons. Unresolved geometry still refuses. A conservative
  reach check and reuse of each donor's triangulation avoid unnecessary exact work;
  the [bounded timing comparison](../I03_SPHERICAL_NETWORK.md#11-measured-cost) is
  not a claim of whole-planet performance or final combined acceptance.

The way one kind of rock is spread within a plate depends on the mesh, and is not
compared. Where a trench consumes cells holding only one kind of rock, as here, the
amount of each kind is compared too. Where it consumes cells mixing rock of different
weight per area, only the consumed area can be compared.

### Change which plate owns which cells: supplied splits, merges and ridge jumps

Plates are not permanent. A plate can break in two, two plates can join, and a
spreading ridge can jump to a new position. In this mode such changes are supplied as
history, not calculated. Atlas commits them at the end of the interval that carries
them, together with that interval's motion, in one save, or not at all. The
[method](../I03_SPHERICAL_NETWORK.md#9-joint-geometry-commits-i034) describes the
records.

**A change of plate moves no rock.** Each change declares its time and takes effect
only at the end of the interval that ends then, never in the middle of one.
- **Split.** It names, cell by cell, which new plate each cell of the old one joins.
  The new boundary follows existing cell edges and ends on existing boundaries.
  Boundaries it meets are cut there, and the cut pieces get new names.
- **Merge.** Two plates that moved together and shared a boundary are joined, and
  that boundary retires.
- **Ridge jump.** The plate the ridge jumps into is split, and the slice left behind
  merges with the plate across the old ridge, whose boundary retires.

Every cell keeps its place and its rock records, so every amount is unchanged exactly. A merged plate continues
one of the two: for a ridge jump the plate across the old ridge, otherwise the larger. The other's cells are then
described in that plate's frame and measured again there. For a very thin strip that can change its measured area
by more than the usual one part in a million million, though no rock moves. Atlas admits such a change only within
the largest error that rounding can produce there, derived from the existing measurement bounds, and books the exact
change against that cell. A larger change would be a real displacement, and is refused.
Names of retired plates and boundaries stay reserved, and a plate cannot simply vanish
on its own.

**Several changes at once.**
- Changes that touch different plates in one interval give the same result in either
  order, and this is checked.
- Two changes that touch one plate must be proposed together.
- A later change is judged against the state after the earlier one is saved: once
  two plates have merged, a proposed split of one of them is refused.
- If the interval's demands on a finite store exceed it, the whole interval is
  refused, change included, rather than serving whichever came first.

[The checks](../../tests/test_i03_events.py):
- commit each kind of change, save it and reopen it in a new process;
- run a closed sphere through a ridge jump, with every source, sink and heat account
  matching exact geometry;
- provoke every refusal.

Generating such changes from the rock's own physics is later work (section 7). These
checks show only that supplied changes are committed consistently.

### Carry material and heat through the solved three-dimensional region

The [connected regional advance](../REGIONAL_EVOLUTION_3D.md) now uses the
calculated flow to move rock composition, heat and scalar material history.
All three move together: a parcel cannot leave its heat behind or arrive with
its earlier weakening forgotten. Material entering the box comes from a finite
declared supply, and material leaving it is returned as an explicit export.

Where a strength law depends on depth, depth is counted down from the top of
the box. The box is therefore treated as starting at the surface; the height
reference recorded with it is a label and does not shift that zero.

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

Rock that weakens as it deforms faster cannot be solved in one pass. Atlas
guesses the resistance, solves the flow, corrects the resistance from that flow
and repeats until the two agree, with at most 32 corrections. Every such
calculation now begins from the same declared starting point, rock at rest. It
used to begin from whatever the previous calculation on the same prepared
region had left behind, which was neither an input nor recorded. The same state
and driving therefore gave slightly different numbers and a different recorded
identity depending on what had been calculated before, and a run stopped and
continued from its saved state did not reproduce one that never stopped. Close
to the limit of 32 corrections, that leftover even decided whether an interval
was accepted. Since 1 October 2026 the answer depends only on the declared
state and driving, and a continued run matches the uninterrupted one exactly.
This costs time: where the rock changes slowly between intervals the
mechanical work roughly doubles, because each calculation repeats corrections
the leftover start used to skip, and an interval that only met the limit thanks
to that leftover is now refused. Rock whose resistance does not depend on how
fast it deforms is unaffected. A recorded, caller-supplied starting point could
win the speed back; it is not built. Focused checks repeat one yielding
interval after other work on the same region, and on a freshly prepared region
continuing from the saved state, with each of the four solver choices, and
require identical results. The
[method description](../REGIONAL_EVOLUTION_3D.md#heat-and-reuse) gives the counts.

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
[retained bounded record](../../evidence/regional-evolution3d-r1.json), now historical after the package
membership changed, measured that reuse separately from physical accuracy; it is not a whole-world speed forecast.

### Other supported thermal and moving-column connections

Deformation produces heat, conduction redistributes it, and temperature changes creep resistance. The [thermal cell](../I01_THERMAL.md) tests that feedback in a periodic material cell; the [column-heat model](../I01_COLUMN_HEAT.md) uses layered depth geometry with surface and basal temperatures. Their different spatial assumptions prevent simply stacking the two solvers.

Heat must be deposited in the same rock whose work produced it. A corrected column check rejects thermal cells representing 101 km of rock inside a declared 100 km column: an apparently closed energy balance alone had not exposed the extra heat capacity. [ASPECT's heating conventions](https://aspect-documentation.readthedocs.io/en/latest/parameters/Heating_20model.html) inform once-only dissipation accounting, while [Kassam and Trefethen](https://people.maths.ox.ac.uk/trefethen/publication/PDF/2005_111.pdf) support the exponential treatment of conduction.

The coupled column also compares actual reference densities, not just matching identity labels. Otherwise a denser thermal copy can change heat capacity and warming while its own energy account still closes. A preparation digest now checks derived capacities, conductances and reference temperatures before use, rejecting changed arrays carrying old identities. Deliberate property changes require a new preparation and compatible heat operator. Supplied-pressure analytical columns, which have no mechanical density, retain their separately declared thermal density. The [column-heat controls](../../evidence/i01-column-heat-r5.json) cover these guards without changing the supported physics or tolerances.

The [thermomechanical motion connection](../I01_THERMOMECHANICAL_MOTION.md) solves force, temperature and weakening at shared integration stages, including the final accepted state. External drag dissipation is recorded separately from column heating. Feedback-on/off comparisons and independent high-accuracy solutions distinguish physical response from integration error; the [current controls](../../evidence/i01-thermomechanical-motion-r4.json) retain those checks with the corrected thermal admission.

The [finite-strain control](../I01_FINITE_STRAIN.md) also lets a closed strip widen and thin while material carries its temperature and history. Thickness changes pressure, resistance and conduction; total rock mass and whole-strip heat capacity stay fixed. [ASPECT's finite-strain formulation](https://aspect-documentation.readthedocs.io/en/latest/user/cookbooks/cookbooks/finite_strain/doc/finite_strain.html) helps distinguish changing geometry from accumulated plastic memory. Its [tests](../../tests/test_i01_finite_strain.py) and [reviewed controls](../../evidence/i01-finite-strain-r5.json) check material transport, geometry scaling, independent solutions and refusal of unsupported steps. The strip has no lateral necking, mantle inflow or rupture.

These equations now have one owner. The finite-strain calculation and everything it
runs—rock-strength laws, weakening response, heat conduction and deposition, the
force balance and one combined step—moved unchanged into a reusable
[package solver](../../src/atlas_tectonics/integration_evolution.py) and its
supporting package modules. The earlier control tools call that same code rather than
keeping their own copies, so every existing check now exercises the one
implementation that later I02 steps will extend. Case files, campaigns, reports and
the independent comparison solutions stay with the tools. A separate check prepares
and runs the real layered column from the package alone, with no control tool
available. The physics, tolerances and refusals are unchanged; this change creates no
new physical result. The same solver is now split into starting a history, advancing
it by whole steps and reporting the result, so the original uninterrupted run and a
history continued in pieces from the shared record (section 1) use one step loop.
Shared transactions, the accepted clock and saving follow in section 8 as an integrated
[workflow](../I02_WORKFLOW.md); the continuation itself is described with the
[I02 steps](../I02_COMMON_STATE.md#9-the-package-owned-solver-i022a-and-its-continuation-i022b).

That closed strip holds its base at a fixed temperature, so nothing enters or leaves it. When a rift thins the lithosphere, the hot mantle beneath rises into the space. [ASPECT's continental-extension example](https://aspect-documentation.readthedocs.io/en/latest/user/cookbooks/cookbooks/continental_extension/doc/continental_extension.html) states that without such an upwelling layer its box cannot represent breakup. The [basal closure](../I01_BASAL_CLOSURE.md) therefore opens the bottom of the regional rifting box. Named asthenosphere enters through a fixed base 150 km down, below the 100 km lithosphere, at a prescribed, uniform upward speed. It brings its actual temperature and composition and no deformation history. Rock leaves through the sides at its own actual state, never reset to a boundary value. The top is a free surface: it rises and falls, but no rock crosses it.

This changes the accounts. Constant volume is not constant mass, because dense mantle replaces lighter crust leaving through the sides. Basal inflow equals side outflow only when the surface's net movement is zero. Heat carried by moving rock, heat conducted through each boundary and mechanical work are booked separately, so the pressure work of entering rock is not counted again as heat. The settings follow the example's parameter file and ASPECT's boundary documentation. [Brune et al.](https://www.earthbyte.org/Resources/Pdf/Brune_etal_2014_Rift_migration.pdf) supply the deeper domain, with asthenosphere below the lithosphere. Exact arithmetic and closed-form geometry check the balances, finite supplies, reversed flow and refusals. These are bookkeeping checks on supplied flows, not a solved flow field. The resolved rift (I07) must still test how the neck responds to this boundary and to its depth, and any melting of the rising mantle waits for a melt law. Transport through the strip and chain (I05) then uses the same inflow records.

The [reviewed controls](../../evidence/i01-basal-closure-r1.json) now connect the rock inventory to the box volume, insulating conditions to booked heat, and endpoint records to their source accounts. A shortening strip is refused if its lithosphere would cross the fixed base. For the work signs, a simple exact flow supplies boundary work, gravity work and internal dissipation independently; deliberately reversing signs or counting pressure work twice fails. This checks the boundary specification and accounts, not a simulated rift. I05/I07 must still connect the actual transported states and solved fluxes to one boundary configuration.

Neighbouring columns also exchange heat sideways. The [lateral-heat criterion](../I01_LATERAL_HEAT.md) asks how much temperature error ignoring those connections could accumulate. For a supplied whole-interval temperature contrast, it sums each contact's possible heat flow, divides by the cell's heat capacity and accumulates the result over time. It uses the conservative contact law described by [NIST FiPy](https://pages.nist.gov/fipy/en/stable/numerical/discret.html), with the mesh and monotonicity restrictions discussed by [Droniou](https://arxiv.org/html/1407.1567v1). The error inequality is derived in the Atlas method, not a published tectonic calibration. A two-cell exact solution and a small independent matrix solution check the calculation. Endpoint snapshots alone cannot supply the required bound. This selects the thermal criterion, while moving geometry and feedback from changed temperature into rock strength still need the later coupled implementation.

## 6. Produce melt, then account for extraction and delivery

The [common-provider connection](../I01_THERMO_PROVIDER_CONTRACT.md) identifies the ingredients, units, energy reference and conditions supported by a melt calculation. It carries actual mass and energy rather than just a percentage melted. An experimental connection now uses MAGEMin's corrected Green et al. (2025) igneous model. Its composition and phase-equilibrium calculations supply a single energy basis for melt and solid rock; the independent analytical controls below remain separate references.

Heating rock changes which minerals are stable and how much liquid can exist. Removing some liquid also removes its particular ingredients and heat, leaving chemically different rock behind. The connection calculates those heat accounts from the same chemical potentials used to determine equilibrium. This matters because copying the external software's raw heat fields would mix incompatible conventions. Nested temperature and pressure checks test each phase, including small ones, and reject unresolved changes of phase rather than smoothing through them. Exact two-component mixtures independently test the heat, entropy, volume, extraction and receiving calculations. Installed-model numerical tests and geological calibration remain distinct; see the [method and current results](../I01_THERMO_PROVIDER_CONTRACT.md#8-implemented-common-gibbs-connection).

Recovering temperature from energy or entropy now requires an explicit assumption that one continuous phase branch covers the requested interval. That declaration is bound to the provider, numerical controls, actual ingredients and amounts, pressure, temperature range and expected phases, with its supporting provenance. Both interval endpoints and every sampled intermediate state must retain those phases; matching endpoints alone cannot certify an unsampled interval. Receiving magma needs support for the combined composition. The [corrected native G25 controls](../../evidence/i01-gibbs-provider-r3.json) pass on their declared short branch. This protects a restricted calculation; it neither proves that no narrow transition lies between samples nor implements a moving freezing front.

The [melting control](../I01_MELTING.md) follows a dry mantle parcel through falling pressure. Melting consumes heat, which feeds back into the amount produced. It uses [Katz, Spiegelman and Langmuir's parameterisation](https://doi.org/10.1029/2002GC000433), with the existing method record explaining the ASPECT and pyMelt source comparisons. Exact limiting cases and a tighter independent integration check the thermal path. The result is retained melt mass, not a supply rate or transported magma.

Extraction changes composition. The [phase-partition control](../I01_PHASE_PARTITION.md), informed by [Keller and Katz](https://eprints.gla.ac.uk/195948/1/195948.pdf), tracks ingredients in solid and liquid separately. Otherwise, reusing the original composition after extraction can recreate melt that has already left.

Near complete melting, subtracting nearly all the liquid from the starting rock can lose the tiny remaining solid in numerical rounding. Atlas now calculates each ingredient's smaller phase amount directly and obtains the larger amount by subtraction. The physics and tolerances are unchanged. Independent known mixtures, extreme partition coefficients and heat/entropy recovery just inside both melting boundaries check the fix. The [Chemicals numerical notes](https://chemicals.readthedocs.io/chemicals.rachford_rice.html#numerical-notes) informed the stability review; its gas/liquid software was not used as a mantle model.

The new [composition-aware energy law](../I01_PHASE_ENERGY.md) now derives phase proportions and heat content together for an explicitly ideal mixture. Supplying energy lets it solve temperature and phase amounts, including melting at constant temperature. Removing liquid takes that liquid's ingredients and energy; the residue retains its changed composition. An analytical 10,000 kg source carries 5.8 GJ. Extracting 1,000 kg removes 0.9 GJ; cooling that extracted material releases the same heat to the surroundings. Thermodynamic derivative checks, signed energy references and latent-heat plateaux test more than conservation alone. Its basis includes the phase/energy treatment in [Keller and Katz, section 2.1.1 and Appendix A.2.2](https://eprints.gla.ac.uk/195948/1/195948.pdf), checked alongside the [R_DMC implementation](https://github.com/richard-katz/R_DMC/blob/master/src/R_DMC_Equilibrium.m).

The [pressure-change connection](../I01_PHASE_PRESSURE.md) then lets material move to a different pressure while retaining its ingredients and entropy. Melting uses sensible heat; freezing releases it. The code solves the new equilibrium directly rather than storing a long pressure-step history. It distinguishes the change in heat content (enthalpy) from mechanical work on the expanding or contracting material. An analytical half-molten parcel decompresses from 1 GPa and 1720 K to zero pressure and 1600 K; its molten fraction rises from 0.5 to 0.789283. Independent work integrals, a refined binary pressure integral and a receiver-connection check test those accounts. [Cantera's entropy/pressure equilibrium interface](https://cantera.org/stable/python/thermo.html), [pyMelt's mantle source](https://pymelt.readthedocs.io/en/latest/_modules/pyMelt/mantle_class.html) and [Keller-Katz's thermal equations](https://eprints.gla.ac.uk/195948/1/195948.pdf) were checked. The retained constant-volume law does not include single-phase thermal expansion.

The [compatible receiver](../I01_MAGMA_RECEIVER.md) now takes that extracted liquid into a finite body using exactly the same material law and pressure. Adding component masses and enthalpy determines how much crystallises or melts and the resulting temperature. Latent heat is already included, so it is not added a second time. Mixing can produce entropy and change volume: the method also checks the associated pressure-volume work. Independent pure and binary examples give exact reference answers. Parcels arriving together can share one equilibrium solve; the [receiver controls](../../evidence/i01-magma-receiver-r3.json) measure its matched performance. [Cantera's H/P mixing example](https://cantera.org/stable/examples/python/thermo/mixing.html) and the Keller-Katz component/energy equations informed the account structure, not the analytical material calibration.

The separate [delivery interface](../I01_DELIVERY.md) carries sensible and latent energy into W08 emplacement under its different, common-melting-temperature law. The new ideal-mixture receiver does not silently replace either that law or Katz's mantle parameterisation. See the [phase-energy controls](../../evidence/i01-phase-energy-r4.json) and [pressure-work controls](../../evidence/i01-phase-pressure-r3.json) for the underlying bounded law and solver improvements. Numerical transfer proposals do not provide persisted material identity or once-only delivery; those belong to the integration state/transaction layer.

The [selected focusing and cooling route](../I01_MELT_ROUTE.md) connects this material accounting to porous flow, matrix compaction and heat transport. Pressure gradients and buoyancy move liquid through the calculated permeability field. Cooling and crystallisation can reduce that permeability, redirecting or retaining liquid beneath colder rock. Thus a collecting region and its axial depth must follow the evolving material and temperature, rather than a universal depth looked up from spreading speed. Grain size, permeability, rheology, thermal boundaries and finite receiver capacity remain declared case inputs. The method uses the coupled equations in [ASPECT's melt-transport documentation](https://aspect-documentation.readthedocs.io/en/latest/user/methods/melt-transport.html); it does not adopt the simpler approximate-Darcy shortcut that omits matrix mass accommodation.

The first chemical approximation carries liquid without reaction with the host rock it passes through. Its ingredients and heat still travel with it; source melting and receiver crystallisation remain separately accounted operations. Mixing it with every traversed host and recalculating equilibrium would be reactive transport, a different model. Present common-Gibbs calculations support only admitted continuous phase branches: they refuse phase appearance or disappearance. Transporting existing liquid on such a branch therefore cannot yet demonstrate a moving freezing front, a generated thermal barrier or ocean-crust birth. I05 must connect evolving heat, phase and material state; I06 must connect actual extraction, ridge receivers and birth history.

The [implemented segregation control](../I01_MELT_SEGREGATION.md) solves a small
vertical column: pressure and buoyancy drive liquid between solid grains, while
the surrounding rock compacts or expands to accommodate it. It does not choose
an arbitrary extraction percentage. Known mathematical solutions, finer meshes,
reversed gravity and independent balance checks test the equations. The liquid's
speed relative to the rock is distinguished from the amount crossing a fixed or
moving receiver; confusing those would transfer the wrong mass. Truly dry cells
stay dry, and the phase-fraction conversion preserves very small positive liquid
fractions rather than silently discarding them. Reusing an unchanged pressure
operator speeds up new load solves without changing their results. These checks
support the method; connecting it to evolving chemistry, heat and receivers is
the later integration work, not something this column test already performs.

The [corrected G25 model's published calibration](https://hpxeosandthermocalc.org/2025/01/06/correction-to-the-holland-et-al-2018-and-tomlinson-holland-2021-models/) supports selecting its material model. Atlas's native checks establish interface behaviour within their tested scope. Neither establishes that all source, depleted-residue and receiver compositions, route coefficients or thermal fronts are physically validated. The selected route requires independently supported material properties and withheld phase, thermal and delivery observations for the claimed domain. Those physical acceptance conditions remain distinct from completing I01's model choice and bounded feasibility.

## 7. Admit a transition only when its physics and transfers are supported

The [local separation candidate](../I01_SEPARATION_LAW.md) distinguishes rock
becoming weaker from losing its bond. A weakened but still cohesive band remains
connected; an explicitly cohesionless failed band can still carry friction when
its sides touch. The small control tracks stored elastic stress and plastic
history together, so even a tiny positive drive at yield cannot be silently
discarded. Cooling, changing the mesh or inspecting today's temperature is not
proof that a broken bond has healed or its earlier history was valid.

Closed-form local solutions and focused tests check those distinctions and the
energy spent weakening the band. A final numerical guard refuses positive energy
that is too small to represent instead of reporting free breakage. The
[reviewed controls](../../evidence/i01-separation-law-r1.json) establish that local
calculation; the spatial rupture law, physical inputs and whole-section event
still require their separately specified checks. The method records its PyLith,
Fei–Choo and Aagaard research basis and exactly which sources were consulted.

The [new bond-history and spatial-strip method](../I01_SEPARATION_FEASIBILITY.md)
makes the missing history choice explicit. Once the declared material law has
broken a cohort's bond, an irreversible record travels with that material.
Recovering friction or strength, cooling, filtering history or changing cells
cannot silently weld it. Bonded and broken material sharing a cell retain their
separate identities; unresolved bridges stay unresolved. This follows the
distinction between residual contact and bonding discussed in the method's
[Fei–Choo comparison](https://arxiv.org/html/2003.04779v3) and
[PyLith interface documentation](https://pylith.readthedocs.io/en/stable/user/physics/faults/),
without implementing either external solver.

Its bounded mechanical problem resolves nonuniform plastic flow across a shear
strip at a fixed physical width. It reconstructs the fixed-length weakening
field from raw material history and accounts separately for elastic storage,
creep, cohesion breakdown, friction and overstress dissipation. Exact uniform
limits, spatial/time refinement, physical sensitivities and negative controls
now pass in the [bounded campaign](../../evidence/i01-separation-feasibility-r4.json).
The first run refused an overly large numerical creep timestep; halving that
step preserved the same physical inputs and acceptance limits. The strip retains
contact while losing a bond, so it is neither a free-surface lithosphere neck
nor a plate-splitting event. Conservative moving-history transport, the full
mixed-material geometry and whole-window mechanical handoff remain required.

The displacement reported here is imposed shear displacement, not normal opening of a rift. The fixed Helmholtz filter now reuses one Cholesky factor for its changing history inputs instead of decomposing the same matrix repeatedly. A matched [64-cell, 4,000-step measurement](../../evidence/i01-separation-performance-r1.json) fell from 0.4640 to 0.3708 seconds, about 20.1%, with identical event brackets and numerical differences no larger than 7.11e-15 in the compared fields. This is a saving for that control, not a whole-generator forecast; the physical law, refinement gates and event limits are unchanged.

The [transition contract](../I01_TRANSITIONS.md) covers separation, new sea floor, boundary migration, subduction initiation, collision and junction changes. A proposed event must be located in time, transfer finite inventories once, preserve history and resolve competing demands together. Root-finding limitations documented by [SUNDIALS](https://sundials.readthedocs.io/en/latest/cvode/Mathematics_link.html) inform checks for missed crossings; balance, replay and simultaneous-event controls check transfers.

Two junctions can each move consistently yet run into one another. The [contact helper](../I01_JUNCTION_EVENTS.md) now finds that meeting exactly for declared straight-line, constant-speed paths. Simply looking for distance to change sign cannot work: distance reaches zero and grows again. Independent algebraic controls check the meeting time, tiny near misses, moving frames and extreme numbers. The helper reports a candidate, not permission to invent a ridge, trench or fault. McKenzie-Morgan's stability definition (abstract inspected), Kleinrock-Morgan's stress-controlled reorganisation discussion and pyGPlates' shared-boundary representation informed that distinction. The selected physical reorganisation route below still needs its evolving-material and spherical-boundary integration.

After contact, the [outgoing ridge check](../I01_RIDGE_JUNCTION.md) asks whether a proposed new ridge can move consistently at both ends and actually grow in the direction allowed by plate ownership. Merely measuring a positive length can miss backwards growth. An exactly soluble four-plate example, moving-frame checks and deliberately incompatible candidates test this calculation. It is a small reused calculation, not another simulation. Gerya and Burov's oceanic-junction research and Koptev and colleagues' thermomechanical experiments reinforce why compatible movement is only part of the answer: creating the boundary also needs the rock's mechanical/thermal state and a supported propagation mechanism. The inaccessible Gerya-Burov steady-state formula has not been guessed or implemented.

The [decoupling control](../I01_DECOUPLING.md) asks whether replacing a deforming belt by a simpler boundary would change motion beyond a declared allowance throughout an interval. [Column admission](../I01_COLUMN_ADMISSION.md) supplies a conservative bound from the actual mixed-creep column, without replacing its rock laws. Failure means the bound cannot certify the switch. Passing establishes a conditional numerical error allowance; it does not establish physical rupture.

The [physical junction-reorganisation rule](../I01_JUNCTION_REORGANISATION.md) now chooses how to connect those prerequisites to the rock model: keep a small deforming region around the junction, allow competing directions to evolve, then simplify it to plate boundaries only when the physical interfaces and their motion support that change. Existing stress, heat and weakness stay with the rock. A ridge needs actual material supply; a trench needs an admitted sinking mechanism; an unresolved region need not become three neat lines immediately. Kleinrock and Phipps Morgan's local-stress analysis, Gerya and Burov's distinction between rifting and mature spreading, and Koptev and colleagues' three-dimensional experiments support this direction. ASPECT's actual 3D yield implementation fixes the proposed stress convention; it cannot silently reuse a 2D strength number. This is a selected method and coding sequence, not an implemented junction simulation. The completed contact/movement helpers remain useful without being rerun or mistaken for the full physical rule.

The [junction feasibility control](../I01_JUNCTION_FEASIBILITY.md) now exercises
that route through eight actual three-dimensional regional solves. Two plates
drive a small box containing intersecting regions of different viscosity.
Changing either the forcing direction or the material orientation changes the
solved motion. Rotating the whole problem, changing the global frame and
reordering plate identities preserve the corresponding physical answer; the
symmetric case acquires no artificial preferred direction. Independent force,
torque and power calculations check the returned plate reactions, following the
work principle in [Bleyer's consistent-reaction example](https://bleyerj.github.io/comet-fenicsx/tips/computing_reactions/computing_reactions.html).
The focused checks pass, but the result is instantaneous synthetic mechanics.
The existing feasible ridge candidate still explicitly lacks physical permission
to create a boundary. Real separation/initiation mechanisms, compatible finite
magma where needed, evolving history, joint timing/transfers and the full
mechanical handoff remain conditions for physical reorganisation.

The [finite-strain admission](../I01_FINITE_ADMISSION.md) now extends that reasoning to the widening, thinning, heating strip. It bounds resistance using the carried geometry and weakening history, then checks a future interval on the strip's actual cumulative clock. Only states issued by the retained evolution, or restored by the engine from a saved entry of it, can pass, so editing a state's clock in memory cannot recover time already used. Internally owned heat operators also prevent a changed calculation masquerading as the same evolution. Independent closed-form cases, genuine evolved endpoints, aggregate work/displacement and deliberate invalid-state tests check this connection. The mathematical bound covers intermediate stages conditionally; endpoint samples alone do not prove that. [The controls](../../evidence/i01-finite-admission-r8.json) retain non-admission for the strong layered column rather than loosen the tolerance. Goldberg's [floating-point analysis](https://docs.oracle.com/cd/E19957-01/806-3568/ncg_goldberg.html) and Python's [dataclass semantics](https://docs.python.org/3.12/library/dataclasses.html), inspected for the specialist method, inform numerical bounds and state ownership. Reusing a prepared bound saves repeated calculation. In the integrated route of section 8, a saved and reopened accepted state can also be admitted, but only through the engine's own restoration of that saved entry; holding its identity or fingerprint admits nothing. The saved file is trusted rather than authenticated: an entry written into it by other means that satisfies the engine's relations, even one recording later physics under an earlier clock, would be restored and admitted like a calculated one. Physical breakup remains a separate responsibility.

The [breakup control](../I01_BREAKUP_CLOSURE.md) examines whether a narrowing neck can reach zero thickness in finite time, rather than declaring breakup at an arbitrary thickness. For its precisely stated creep law and quadratic weakness, an exact continuum solution shows when this is possible. The discrete columns agree at the first thinning level; they do not resolve every later, much narrower neck. The [reviewed checks](../../evidence/i01-breakup-closure-r4.json) therefore establish analytical feasibility, not a generated split. They also show why weak resistance alone does not prove separation and why a finite set of gentle slopes cannot justify a law whose limiting neck becomes too steep. The method documents the Hutchinson-Neale and Audoly-Hutchinson necking sources and the Brune/ASPECT rifting comparisons; no new geological calibration is implied. The mixed-creep/plastic lithosphere still needs resolved neck mechanics before an event can be issued.

The [separation decision](../I01_SEPARATION_DECISION.md) defines the checks the future resolved model must report. Crust breaking apart, deeper mantle rock disconnecting, and a simpler boundary reproducing the same motion are different questions. It tracks actual material, including bridges that pass from crust into mantle and back, rather than declaring a split when a coloured cell disappears. Motion must remain close over a declared interval, not just its endpoints. An exact worked example shows why an apparently converging sequence of thinning measurements can still leave unbroken rock. Brune's rift-migration results and ASPECT's material-tracking example inform the distinction; the norm and refusal rules are Atlas design choices, not a new simulated breakup result.

For subduction, [the selected initiation method](../I01_INITIATION_DECISION.md) asks the regional model to calculate how bending, friction and flowing rock resist sinking, instead of supplying a convenient resistance number. It keeps stored elastic stress and plastic weakening as different histories. Water pressure is an explicit scenario input, not an invented drainage simulation. Weakening has a physical length, so smaller mesh cells do not automatically make the plate easier to break. The future test will remove the driving force without clamping the plate, and distinguish continued gravity-driven sinking from a short elastic rebound. Gurnis, Hall and Lavier's original force/convergence experiments and ASPECT's pressure, material-history and analytic load comparisons informed the specification. The research also exposed missing benchmark inputs: these must be fixed before testing, not selected to fit the answer. No new sinking simulation has passed yet.

An [independent analytical verification route](../I01_INITIATION_VERIFICATION.md)
now checks the missing numerical conventions without inventing the published
case's inputs. A resolved inclined viscous layer has independently derived
constant- and varying-viscosity solutions. Removing its driving traction permits
motion under gravity; clamping its velocity instead creates a resisting reaction.
The control distinguishes those outcomes, checks spatial refinement and matches
external work to independently calculated dissipation. A separate retained
elastic calculation shows why unloaded relaxation can dissipate stored energy
without proving gravity-driven sinking. Its sixteen controls and eight focused
tests pass. Following [ASPECT's verification/validation distinction](https://aspect-documentation.readthedocs.io/en/latest/user/benchmarks/index.html),
these are bounded equation and boundary checks, not a subduction event or
experimental validation. They allow I01's method/feasibility choice to proceed;
I07 still owes the declared resolved plate, history, exterior-sensitivity and
finite-window force-release experiment. Published reproduction remains an
optional independent comparison once its missing source definitions are resolved.

The paper's force curves now have a retained, reproducible extraction script and
raw readings. It reads the original drawn segments, keeps reading bands rather
than false single-value precision, and preserves the two plates' force signs.
The research owner's execution reproduced all 28 rounded bands; local review
checked the source figures and complete method, without reinstalling its parser.
These readings are comparison material, not new constitutive constants or a
substitute for the still-missing benchmark definitions and error allowances.

The [initiation comparison tool](../../tools/check_i01_initiation_inputs.py) now checks whether the required definitions have sources and have been reviewed. Unknowns remain unknown. Once those inputs and the comparison rules are ready, it can compare resistance against distance travelled, including peaks between the published sample points, and calculate the work done. The plan fixes the input and tolerance identities before the run; missing coverage, changed plans and incompatible units are refused. Its synthetic tests check the measuring tool, not whether subduction itself is realistic. Published reproduction and Atlas's separate force-release test remain distinct.

For that comparison, the preferred newer source is [Li and Gurnis (2023)](https://doi.org/10.1093/gji/ggac332), keeping the 2004 paper as supporting evidence. Its [archive](https://data.caltech.edu/records/haw6e-eck15) lets us inspect the calculation and use numerical histories instead of reading points from a graph. Inspection found missing case settings and a missing velocity row, so the data cannot yet be used as a completed benchmark. Most importantly, holding a plate still is not the same experiment as letting go of it: Atlas must still test whether sinking continues after the driving force is removed. This source review improves the test plan; it does not claim a new sinking result.

The [source reconstruction](../../cases/i01_li_gurnis_reconstruction_v1.json) now converts one 4 cm/year data row consistently and preserves its original measurements. This resolves the time units and sign of the force measured inside the plate, but that force is not automatically the work done at the model boundary. Reading the actual equations also exposed a temperature-scaling discrepancy and a missing basalt-density file. Eight small tests check the reconstruction without running subduction. We still need the original case settings and a reliable link between data rows and rock-behaviour models before claiming to reproduce the published experiment.

Reading the original benchmark more closely matters here: its older, 40-million-year right-hand plate sinks beneath the younger, 10-million-year left-hand plate. Its published material constants are now recorded, but a complete input recipe is still unavailable. The paper's basal-temperature descriptions disagree, and several boundary and weakening definitions remain missing. The research also recovered approximate graph readings; their line thickness describes how precisely we can read a figure, not how accurately a model represents nature. All 28 readings now have the reproducible extractor and coordinate calibration described above. They remain outside accepted comparisons because complete benchmark inputs, applicability and axis/systematic uncertainty allowances are unresolved. Nor can the paper's weakening-strain number simply be copied: its precise definition must first be related to Atlas's accumulated engineering plastic shear.

Generated breakup, complete melt-derived supply and crust birth, resolved initiation and evolving global geometry still require their later implementation and physical acceptance. The unresolved published benchmark remains separate from the new analytical verification route. The [reviewed transition evidence](../../evidence/i01-transitions-r2.json) supports bounded event machinery, not generated-world acceptance. Existing receipts and source-bound method documents retain their original meaning; explaining their connections does not renew or extend their evidence.

## 8. Accept, save and continue one evolving state

I02 also records the owner's [1% plate-velocity handoff limit](../I02_WORKFLOW.md#relative-plate-velocity-handoff-contract-eps_v).
Before a later stage replaces a detailed coupled calculation with a simpler one,
it must bound the largest velocity difference over the same region and time
window relative to an established reference speed. I06/I07 consume this policy
and I09 enforces it; I03 does not need it. The limit is not a claim that every
solver is accurate to 1%, and recording it does not implement the later handoff.

**The I02.3–I02.8 route is integrated locally; current verification and platform
coverage are recorded in [current status](../../../docs/CURRENT_STATE.md).** Sections 1–7 describe what is calculated
within an interval. This section follows one history of the finite-strain column of
section 5 through the loop that accepts, stores and continues it. The method detail,
its design choices and its checks are in the [I02 workflow method](../I02_WORKFLOW.md).

**Start from the declared record.** The starting record of section 1 becomes the first
entry, the root, of a ledger kept in Atlas's existing storage file. The unstretched
reference, the starting temperatures and plastic history, and the rock records are
stored there once. Finite stores attached to the record keep their starting amounts
there too; the ledger carries their current amounts from then on.

**Take one coupled step.** Each step is exactly the package calculation of section 5:
current geometry from the original shape, rock strength from temperature and history,
motion from the force balance, heat from that motion, then conduction. The step length
comes from the original timetable. Asking for "five more steps" or "continue until this
time" never recalculates it, and the step count keeps running towards the same 256-step
ceiling, whatever is asked.

**Check, then commit everything at once.** A step counts only if the existing checks
pass: stretch and temperatures stay inside their windows, no temperature changes by more
than the per-step guard, the rock-strength calculation succeeds and the time budget
holds. Accepted steps are saved at chosen points as one database transaction containing
the new temperatures and history, every heat and work account, any attached finite stores
and transfers between them, and the move of the "latest accepted" position. SQLite's
rollback journal makes that transaction all-or-nothing inside the one file. There is no
separate pointer to the latest entry: each entry can be followed only by one entry,
written in a slot reserved for it, so if two writers try to extend the same entry, the
first succeeds and the second is refused with nothing written. Transfers between declared
stores move stated amounts of each ingredient and of heat content, which may be negative,
exactly once. Nothing is created; a store cannot give more than it holds, an emptied
store cannot keep heat, and anything leaving or entering the represented stores is booked
against a named outside source or sink. Amounts are kept exactly; a stored amount is
rounded to the computer's number format once per save, and that rounding, which at a very
large store can be comparable to a small transfer, is reported rather than hidden (a
transfer too small to change the stored number is refused). The column itself exchanges
no rock. Only steps
the package has just calculated can be saved as new entries: a reloaded or hand-made
record, however well-formed, cannot be appended as new physics. Events are declared once,
with the history, and events this route cannot represent stop the history just before
them rather than being invented. Each transfer names the run of steps it was produced
for, and that run is saved in one entry together with its transfers or not at all: a
refused transfer, or a stop part-way through its run, leaves the history at the run's
start and says so. Otherwise a stop or an interruption still saves the steps already
accepted; a save that fails is tried once more, and the report of an interruption says
whether, and as which entry, the steps were saved.

**Checkpoint and continue.** Every saved entry is a checkpoint. Reopening rebuilds the
starting record through the same checks that created it, and refuses a different program
or runtime identity rather than quietly relabelling old results. Later entries are rebuilt
from their stored values, which must reproduce every recorded identity exactly, stay
inside the history's limits and obey the step's own relations (for example, the recorded
displacement must equal the change of width, and the work accounts must balance). Solvers
are rebuilt from the recorded inputs, never read back as opaque objects, and a new process
continues from the last entry without recalculating the earlier steps. Reopening
also exposed a numerical precision bug:
on very stiff rock branches, two neighbouring log-stress values could lie either
side of the answer but neither was accurate enough. Refining directly in stress
when that happens now meets the same tolerance, without changing the rock law or
loosening its checks. Tests repeat the previously failing saved histories and
compare their complete heat/work accounts with uninterrupted runs.
Each entry records a
fingerprint of the one before it, and every read first confirms that the chain from the
start to the latest entry is unchanged, checking it again whenever the file may have
changed, so an entry edited in the file without also editing every later one is refused.
The file itself is trusted: these checks show that its contents are consistent, not who
wrote them, so a consistent entry added to it by other means would be continued like a
calculated one. A process killed while saving leaves either the previous entry or the new
one, never a mixture; the checks deliberately kill writers in the middle of a save to show
this. The finite-admission check of section 7 issues a starting state from a reopened entry
only through this restoration, and only for the same retained evolution.

**Inspect the results.** A small command tool creates the declared case, advances it,
reports status, cancels a running advance while keeping every accepted step, saves a copy,
loads it into a new project and continues it. A request is checked completely before
anything starts, so a mistaken one changes nothing, and a stray or damaged cancellation
file can neither cancel nor stop a run. Inspection works on a read-only copy of the file:
it re-checks the chain of short descriptions, rebuilds and checks only the requested entry
and answers from it (for example, each rock parcel's temperature in kelvin at the accepted
time, with its source and runtime identity). It never re-runs physics or writes the
project. Loading a saved copy checks every entry, not only the latest, again for
consistency: a saved copy is trusted input.

**With a spherical network attached.** When the history carries the network of
section 1, each saved entry also holds the network's move for that run of steps
(section 5): the new cell outlines, the rock pieces, the measured overlaps and any
transfers to or from finite stores, in the same all-or-nothing transaction. Every
run of steps must then name its plate motion; a request without one saves nothing.
Reopening does not trust the stored result. It repeats the recorded motion to
rebuild the outlines, checks the stored overlaps against them, applies them to the
previous entry's rock again and requires every stored value and identity to match.
The stored overlaps are tested against conditions they must satisfy; they are not
measured a second time, which the method document records as a limit.
[These checks](../../tests/test_i03_clock.py) save a history after three intervals,
continue it in a new process and reach exactly the state of an uninterrupted run;
they also edit stored values, including in the latest entry, and confirm each edit
is refused.

**What the checks establish.** Splitting the history into several requests and save
points within one process gives exactly the same numbers and accounts as one uninterrupted
run. Continuing in a new process, including after a time budget stops a run, re-solves the
starting stage and agrees within the existing solver tolerance rather than bit for bit,
and the conservation identities close. Injected failures and killed writers never expose a
partial save, competing writers cannot both extend the history, and on Windows a program
polling the status while a run saves no longer makes the run fail. The 30 September
I02 checkpoint passed all 758 I01/I02 tests on Windows. R4 and the subsequent
checkpoint, recovery, resource and cache fixes are integrated with focused
regressions and fresh r6 admission/timing receipts. The final Git-normalised
check passed all three guards, including 759 I01/I02 tests in 164.449 s, with no
failures or skips. R7 and its follow-up corrections then passed 211 focused checks
and a fresh Git-normalised guard including 759 I01/I02 tests. The current r7 timing
comparison records warm bare evolution at 0.06976490 s and the stored workflow at
0.10974810 s (+0.03998320 s, or 57.31%) for this tiny column. That is a saving/recovery cost, not a physics speedup; the
[method](../I02_WORKFLOW.md#7-checks-coverage-and-measured-overhead) gives the measured
seconds. This reviewed, connected and restartable route completes I02 for its
declared case. Whole-planet integration and Linux platform coverage remain separate.
