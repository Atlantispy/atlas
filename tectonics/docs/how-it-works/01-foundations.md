# Foundations: geometry, material, heat and support

[Back to the guide](../HOW_TECTONICS_IS_MADE.md)

W01–W04 establish where rock is, what material it contains, how prescribed motion
moves that material, and how cooling, compaction and loading affect a supported
column. They provide several connected, bounded methods rather than one unrestricted
planet simulation. All remain **WORKING NON-CANON**.

The test links below describe executable checks. Linked numerical receipts are
**recorded evidence for their stated source/runtime snapshots**, not current-code
acceptance. These W01–W04 records are outside the initial
[current-evidence register](../../../docs/CURRENT_EVIDENCE.md); their omission does
not imply acceptance. No numerical tests or simulations were rerun for this guide.

## W01: describe space, geology and prescribed motion

### Coordinates, rotations and geological time

Inputs identify a spherical planet or local Cartesian frame, positions in metres,
angular units and a named time origin. Atlas converts spherical latitude/longitude
to three-dimensional vectors and supplies local east–north–up axes. On a moving
frame it subtracts both the origin's velocity and the velocity caused by rotating
axes. A static change of vector components alone would miss those effects.

Finite rotations move rigid geometry around an axis. Their order matters: rotating
an object sideways and then turning it over generally differs from reversing those
actions. The resulting positions should retain distances and acquire no strain.
Geological ages running backwards from a reference are explicitly converted to a
forward clock in seconds. Formation time, cooling onset and elapsed duration stay
distinct; “year” requires a specified unit.

One shared interval rule serves every later stepped route: a fixed partition's
last substep ends exactly at the declared end, and a caller's declared output
time is published as it is. Recomputing `start+(end−start)` can miss the end by
one rounding unit, which previously made W07, W08 and W09 refuse their own
results for ordinary computed event times.

[Coordinate](../../src/atlas_tectonics/coordinates.py),
[rotation](../../src/atlas_tectonics/kinematics.py) and
[time](../../src/atlas_tectonics/timebase.py) code produces transformed positions,
velocities and timestamps. [Tests](../../tests/test_w01_coordinates.py) check
independent scalar formulae, poles, longitude seams, inverse transforms and moving
frames. These establish conventions, not the accuracy of a planet's supplied data.
The sphere is not an ellipsoid, and flattening local coordinates loses information.
The shared basis is [ESA's ENU transformation](https://gssc.esa.int/navipedia/index.php/Transformations_between_ECEF_and_ENU_coordinates)
and [pyGPlates' rotation/velocity conventions](https://www.gplates.org/docs/pygplates/generated/pygplates.calculate_velocities);
pyGPlates is a reference here, not an Atlas dependency.

### Geological geometry and shared plate boundaries

An outline answers “which points belong here?”; topology additionally records which
regions share an edge and which side each occupies. Atlas stores a shared edge
once, so neighbours cannot independently move their common boundary. Reversing its
direction reverses the side convention consistently. Point contacts do not create
a length across which material can flow.

Planar intersections use Shapely/GEOS in double precision, preserving holes and
concave outlines. Spherical features use bounded local charts with great-circle
edges, then calculate actual surface areas in m² and arc lengths in metres.
Several patches can form one large or disconnected plate. A complete spherical
atlas checks opposite edge pairing, junction order, connectivity, Euler's relation
and an area sum of `4π` steradians. No area rescaling repairs a failed closure.

[Geometry](../../src/atlas_tectonics/geometry.py),
[spherical geometry](../../src/atlas_tectonics/spherical_geometry.py),
[boundaries](../../src/atlas_tectonics/boundaries.py) and
[atlas](../../src/atlas_tectonics/spherical_atlas.py) code supply ownership and
adjacency queries. [Geometry tests](../../tests/test_w01_geometry.py),
[boundary tests](../../tests/test_w01_boundaries.py) and
[sphere tests](../../tests/test_w01_spherical_atlas.py) compare rational areas,
octants, known arc lengths, rotated copies and invalid joins. Ambiguous or
ill-conditioned geometry can be refused. Fast point queries use GEOS's prepared
search structures, which GEOS builds lazily and not thread-safely; Atlas keeps
them private to each geometry or index and serialises their use, so concurrent
queries can no longer crash the process. A child-process storm test of cold
concurrent first use checks this. A valid map establishes neither fault
physics nor plate history. [Shapely's intersection contract](https://shapely.readthedocs.io/en/2.1.2/reference/shapely.intersection.html)
documents the actual planar dependency.

### Generated partitions, geological descriptions and reference materials

The initial spherical partition method assigns surface directions to their nearest
supplied or seeded site. Convex-hull relationships construct shared junctions and
edges; low plate counts have explicit geometric cases. Resolved sites and seed
provenance are retained. This supplies candidate ownership, not forces that formed
the plates. Later new-world layout adapters make additional size/shape choices.

Geological descriptions then attach ordered sediment, crust and mantle layers,
material fractions, porosity, initial thermal profiles, faults and weak zones to
explicit features. A plate boundary is not automatically a geological contact.
Fault dip and depth describe geometry; they do not generate slip. Unknown porosity
cannot become zero, and a room-temperature rock reference cannot become a calibrated
hot-mantle law. The reference library distinguishes grain density from porous bulk
rock and preserves original measurement conditions. Mixture density is weighted by
volume; specific heat requires mass weighting. Conductivity also depends on arrangement.

See [partition code](../../src/atlas_tectonics/planetary_generation.py),
[geological cases](../../src/atlas_tectonics/geological_case.py),
[material library](../../src/atlas_tectonics/material_library.py) and its
[property-level source register](../../src/atlas_tectonics/earth_material_data.py).
[Partition](../../tests/test_w01_planetary_generation.py),
[description](../../tests/test_w01_geological_description.py) and
[material tests](../../tests/test_w01_material_library.py) check ownership,
layer/fraction consistency and units, rather than geological plausibility.
[SciPy's spherical Voronoi explanation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.spatial.SphericalVoronoi.html)
provides algorithm context; [BurnMan's composite documentation](https://burnman.readthedocs.io/en/latest/materials_05_composite.html)
is a reference for explicit mixture definitions, not bundled thermodynamic software.

### Sampling points and finite cells

The sampler takes the described geology plus query positions or cell footprints.
A point returns membership, layer and temperature where known. A cell receives
the actual intersections with provinces and layers. A cell containing two rocks
therefore retains both amounts instead of inheriting its centre's rock label.
Outputs distinguish bulk, grain and pore volumes in m³, reference mass in kg when
density is available, and volume-mean temperature in K. A mean temperature is not
an inventory of heat.

Spherical cells use shell volumes, not surface area multiplied by depth. Thermal
tables are integrated across their segments without extrapolation, and validity
checks cover a fragment's temperature range rather than just a plausible average.
Unknowns remain identified or cause a requested calculation to refuse.

[Sampling code](../../src/atlas_tectonics/precursor_sampling.py), the
[method](../W01_INITIAL_SAMPLING.md) and
[tests](../../tests/test_w01_initial_sampling.py) cover analytical intersections,
refinement, mixed cells and preserved source descriptions. Constant-depth layers
and declared body bands are supported; arbitrary three-dimensional interfaces are
not. The shared conceptual basis for description and sampling is
[Geodynamic World Builder's feature precedence](https://gwb.readthedocs.io/en/latest/user_manual/concepts/painting_in_the_world.html)
and [Kritsikis et al.'s conservative spherical interpolation](https://gmd.copernicus.org/articles/10/425/2017/).
Neither external method validates Atlas's particular geology or shell reduction.

### Converting full motion into regional forcing

A regional cross-section needs velocities at its cell faces in m/s. Atlas first
resolves supplied plate and reference-frame motion into along-section, sideways
and vertical components. Solver-ready planar input requires compatible relative
translation along the section; supported spherical input requires relative rotation
about its great-circle pole. Sideways or vertical flow cannot simply disappear
because a two-dimensional drawing omits it.

The [forcing adapter](../../src/atlas_tectonics/regional_forcing.py) checks the
whole section for ownership and discontinuities, including narrow regions between
grid faces. Distinct velocities meeting internally require a contact/flux law and
are refused here. Motion is explicitly frozen at the starting instant for the
submitted interval; this is not exact finite-time rotation of evolving boundaries.
Inflow needs a supplied exterior composition.

[Forcing tests](../../tests/test_w01_regional_forcing.py) exercise common motion,
rotated frames, hidden interfaces and incompatible flow. They establish faithful
conversion of a supported prescription, not the discovery of plate speeds.
[Method details](../W01_MOTION_FORCING.md) retain the units and restrictions; the
rotation basis is the pyGPlates reference above.

### Initialising and checking the connected regional workflow

[The workflow](../../src/atlas_tectonics/regional_workflow.py) connects sampling,
forcing and W02 transport. It divides each actual phase volume by the declared
reference width and cell length to obtain an equivalent thickness in metres.
Multiplying back recovers volume. On a sphere this quantity is not raw radial
layer thickness; only the documented hemisphere-wedge support is implemented.

Initial thermal descriptions, material origins and dates survive transport, but
they remain initial data until a thermal model evolves them. Restoring a saved
workflow checks those bindings and the original forcing interval rather than
inventing further motion. [Workflow tests](../../tests/test_w01_workflow.py) and
[combined acceptance tests](../../tests/test_w01_acceptance.py) cover inventory
closure, seam-crossing axial motion, refusal, reuse and restoration. The
[recorded W01 assessment](../../evidence/w01-stage8-acceptance.md) separates a
supported technical workflow from incomplete whole-W01 geological realism.
[Bounded shape evidence](../../evidence/w01-bounded-validation.md) likewise does
not accept independently generated dynamics. The sampling and kinematic references
above are the shared scientific basis for this connection.

## W02: preserve material while changing its location and representation

### Cohorts, transport and open boundaries

A cohort is material sharing a named origin and formation history. Two quantities
of the same rock formed at different times remain different cohorts. Age is
evaluation time minus known formation time, in the named epoch; it is not an
averaged field transported across mixed cells.

Given nonnegative partial thicknesses, cell widths, face velocities and an interval,
[material transport](../../src/atlas_tectonics/materials.py) records what crosses
each face. Neighbours use the same transfer with opposite signs. The default MUSCL
method reconstructs limited linear profiles inside cells; its two-stage time update
reduces smearing while preserving nonnegative amounts under the timestep restriction.
All cohort profiles are constrained together so their sum follows the total-thickness
profile. Conserving each cohort alone would not guarantee that consistency.

An open boundary uses explicitly supplied composition on inflow and interior
material on outflow. A closed fixed boundary requires zero normal velocity.
Receipts account separately for each cohort: change equals incoming minus outgoing
volume, plus reported rounding residual. Inventories are m² per unit transverse
width, becoming m³ after multiplication by the declared width; this is not a
variable-density mass solver.

[Transport tests](../../tests/test_material_transport.py) use rational fluxes,
translated pulses, sharp fronts and refinement. [Clawpack's conservation derivation](https://www.clawpack.org/riemann_book/html/Advection.html)
and [Plewa and Müller's consistency requirement](https://arxiv.org/abs/astro-ph/9807241)
provide method context. Atlas constrains reconstruction; it does not copy that
paper's scheme or renormalise completed inventories to conceal error.

### Regridding and moving cells

Regridding changes how the same instant is represented. [Conservative remapping](../../src/atlas_tectonics/remapping.py)
integrates each old reconstructed profile over its overlap with each new cell.
The frame and physical domain must match: cropping away material is not a remap.
Coarsening preserves amounts but can lose detail irreversibly.

Moving-cell transport is different. It uses material velocity relative to the cell
faces and advances thickness multiplied by current cell width. If faces follow
the material, a stretching cell becomes thinner while retaining its volume.
Moving a grid through stationary uniform material must not manufacture variation.
Face crossings, unresolved motion and intervals containing unsplit events refuse.

[Remap and moving-volume tests](../../tests/test_w02_completion.py) check affine
profiles, constant totals across mixed cohorts, geometry conservation, relative
inflow and reference/native agreement. The [W02 completion record](../../evidence/w02-completion-measurements.json)
belongs to its recorded snapshot. [Fazio and LeVeque's moving-mesh work](https://www.math.ntnu.no/conservation/1998/020.html)
is a primary method reference, not an external solver executed by these tests.

### Birth, removal, plate ownership and markers

An explicit material event adds or removes an amount at the parent's time and
records a named source or destination. Removal cannot overdraw. Birth requires a
formation time equal to the event time; transfer of existing rock retains its age.
A “ridge” or “subduction” label alone creates neither a rate nor a reservoir.

[Topology operations](../../src/atlas_tectonics/topology.py) split, merge or
reclassify plate/block ownership without changing material origin. Reclassifying
a boundary records the inventory changing owner; physically moving it uses the
moving-volume method. [Markers](../../src/atlas_tectonics/markers.py) retain labels
and accumulated stretch under a declared material map, but carry no mass and do
not infer trajectories from arbitrary grid motion.

The [integrated tests](../../tests/test_w02_completion.py) combine regrid, motion,
birth, split, merge and restoration, checking per-cohort balances and replay
refusal. Their conservation basis is shared with the preceding W02 methods.
General spherical transport, force-derived topology changes and complete burial
or thermal histories are outside this one-dimensional material contract.

## W03: temperature, thermal support and compaction

### Cooling columns and heat accounts

Inputs supply cooling onset, plate thickness in metres, surface/base temperatures
in K, diffusivity in m²/s and conductivity in W/(m K). The
[half-space helper](../../src/atlas_tectonics/thermal.py) represents cooling into
an unbounded hot interior. [Finite-plate cooling](../../src/atlas_tectonics/plate_cooling.py)
instead retains a prescribed hot base: young behaviour approaches the half-space
limit; old behaviour approaches a steady profile.

Atlas evaluates the analytical solution at the requested age, using equivalent
young- and mature-age formulae to avoid poorly converging sums. It integrates
depth intervals for true mean temperatures and calculates cumulative outward heat
at the surface and base in J/m². Basal heat may be negative because the hot
reservoir supplies energy. No finite instantaneous surface flux is invented at
the discontinuous age-zero state.

[Cooling tests](../../tests/test_w03_plate_cooling.py) compare independent series,
quadrature, finite-volume conduction and heat balance. [Recorded evidence](../../evidence/w03-thermal-columns.md)
supports the stated implementation snapshot. [Parsons and Sclater (1977)](https://topex.ucsd.edu/geodynamics/parsons_sclater77.pdf)
is the primary cooling-model basis. The present column model excludes variable
properties, internal/latent heating, hydrothermal circulation and moving thickness;
its supplied parameters are not automatically Earth calibration.

### Turning cooling into a support diagnostic

Cooling increases density under the selected linear thermal-expansion law. The
[support helper](../../src/atlas_tectonics/thermal_support.py) integrates the
current/reference density difference through a column, giving a buoyancy-sheet
anomaly in kg/m². Multiplication by gravity gives downward pressure in Pa;
division by the compensation-minus-fill density gives local downward displacement
in metres.

This Boussinesq anomaly affects buoyancy while reference material inventory stays
fixed. It is not newly created mass. Displacement is total from the named reference,
not another increment to add on every call. An ownership policy prevents this
managed route from applying thermal support both locally and through flexure.

[Tests](../../tests/test_w03_thermal_support.py) check signs, dimensions, unchanged
fields, gravity cancellation in local support and independent thermal integrals.
[Evidence](../../evidence/w03-thermal-support.md) retains its snapshot scope.
The basis combines Parsons and Sclater with [ASPECT's Boussinesq explanation](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/methods/approximate-equations/ba.html).
This diagnostic does not solve dynamic topography, shoreline migration or a
compressible mass balance.

### Drained compaction and rebound

Compaction closes pore space while preserving solid grains. Inputs include grain
volumes in m³, grain/fluid densities in kg/m³, column area in m², effective stress
in Pa and maximum previous loading. Atlas uses a supplied shifted-log stress law
with separate compression and rebound slopes. Unloading retains the maximum-load
memory, so it need not restore the original pore space.

[Compaction](../../src/atlas_tectonics/compaction.py) and
[column geometry](../../src/atlas_tectonics/compaction_columns.py) return thickness,
porosity and fluid exchanges. Changing area changes thickness and self-weight
stress without changing grain volume. Expelled fluid enters a named reservoir;
rebound needs sufficient pooled fluid supply. One midpoint stress represents each
parcel, so thick parcels require refinement.

[Law tests](../../tests/test_w03_compaction_law.py) and
[column tests](../../tests/test_w03_compaction_columns.py) check load–unload cycles,
grain conservation, area changes, finite water stock and convergence towards an
independent continuous solution. [Recorded evidence](../../evidence/w03-compaction.md)
is snapshot-specific. [Fowler and Yang (2002)](https://people.maths.ox.ac.uk/fowler/papers/2002.1.pdf)
informs the history distinction; Atlas's selected law is its own approximation.
The response assumes saturated, hydrostatic, already-drained pores. It predicts
neither drainage time nor trapped excess pressure.

### Assembling thermal and material histories

[The W03 workflow](../../src/atlas_tectonics/w03_workflow.py) accepts a genuine
W01/W02 root with stationary planar support and an explicitly ordered sediment
column. It verifies each cell's grain/pore inventory and reconciles the initial
thermal description with the chosen cooling model on the declared depth cells.
Transported mixtures cannot supply missing layer order or peak-loading history.

Each later prescribed load updates compaction, books signed water events once,
updates the finite reservoir and returns thermal diagnostics. This assembled
route fixes area and ordering even though the lower-level compaction helper can
handle area changes. Temperature-dependent compaction, lateral remixing and heat
carried by pore water remain excluded.

[Workflow checks](../../tests/test_w03_workflow.py) challenge independent accounts,
incompatible thermal/source inputs, insufficient water, unloading history and
restored continuation. The [recorded assessment](../../evidence/w03-workflow.md)
applies to stationary columns, not a general evolving basin. Its research basis
is the cooling, buoyancy and compaction work above; the connection introduces no
new constitutive law.

## W04: convert physical loads into bending and surface change

### Inventory, replacement and thermal loads

The [load kernel](../../src/atlas_tectonics/column_loads.py) compares current and
reference volumes on the same finite support. Each disjoint rock, grain, pore-water
or reservoir-water phase has an explicit density. Unoccupied volume contains the
declared replacement material. The mass difference per area, multiplied by gravity,
is downward pressure in Pa. Changing replacement density matters as well as changing
occupied volume.

If expelled pore water is replaced by identical water, their weight changes cancel.
Replacement by air unloads the column. Optional thermal pressure uses fixed coverage
and actual volume-mean temperatures; the buoyancy anomaly remains separate from
conserved mass. [Load tests](../../tests/test_w04_column_loads.py) check these
cancellations, density changes, units and overfill refusals; [evidence](../../evidence/w04-loads.md)
records the snapshot. The shared research basis for all W04 subsections is
[Wickert's gFlex paper](https://gmd.copernicus.org/articles/9/997/2016/), especially
the distinction between imposed load, restoring material and boundary conditions.
Atlas does not call gFlex or claim its validation results.

### Uniform periodic flexure

Inputs include pressure, gravity, density contrast, Young's modulus in Pa,
effective elastic thickness in metres and Poisson's ratio. Together the elastic
inputs determine rigidity in N m. Greater elastic thickness strongly increases
bending resistance; it is not interchangeable with crustal or thermal thickness.

[Periodic flexure](../../src/atlas_tectonics/flexure.py) solves bending plus local
restoring support on a repeating one-dimensional domain. An FFT separates the
discrete equation into independently solvable wave components. It solves the
centred-difference biharmonic operator, not the continuous spectral equation.
The whole coupled domain is required; separate spatial tiles would change the
answer. Output is downward displacement in metres.

[Periodic workflow tests](../../tests/test_w04_workflow.py) check independently
constructed discrete operators, sinusoidal loads, refinement and superposition.
[Recorded workflow evidence](../../evidence/w04-workflow.md) does not make a
regional crop physically periodic. Repetition must be an explicit assumption.

### Continuing plates and physical ends

An output-window edge need not be a plate edge. [Finite-region flexure](../../src/atlas_tectonics/finite_flexure.py)
offers a continuing uniform plate with explicit surrounding loads, or actual
free/clamped ends. A clamp fixes displacement and slope; a free end carries no
end moment or shear. A coastline alone supplies neither condition.

The continuing solution integrates an analytical response over each constant-load
cell and combines those responses by linear convolution. Nearby exterior cells and
constant far-field loads are supplied explicitly. Bounds on omitted exterior
pressure produce conditional uncertainty bounds on displacement and derivatives.
Physical ends instead add a homogeneous correction satisfying the endpoint rules.

[Tests](../../tests/test_w04_finite_region.py) compare independent quadrature,
analytical controls, source subdivision, endpoint conditions and exterior changes.
[Evidence](../../evidence/w04-finite-regions.md) is tied to the recorded method.
Uniform-route validity samples centres and faces; it does not certify every
between-sample extremum. This remains a planar transect with loading invariant in
the transverse direction, not a finite-width two-dimensional plate.

### Spatially variable and time-changing rigidity

[Variable flexure](../../src/atlas_tectonics/variable_flexure.py) solves
`(D(x) w''(x))'' + K w = q`. Differentiating bending moment is essential at a
stiffness jump; multiplying a uniform stencil by local rigidity gives a different
equation. Cubic Hermite finite elements join displacement and slope continuously
while allowing curvature to change across material boundaries. This interpolation
has a [TU Delft derivation](https://interactivetextbooks.citg.tudelft.nl/computational-modelling/structural_linear/euler_bernouilli.html).

At least two meshes are compared, with further refinement until displacement,
slope and curvature changes meet declared tolerances. Polynomial extrema and local
elastic thickness contribute to strain checks. These are mesh-change estimates,
not rigorous bounds on the exact solution. Continuing variable-rigidity cases
currently require exact declared exterior loads; the uniform uncertainty bound
cannot be borrowed.

The separate [evolving adapter](../../src/atlas_tectonics/evolving_flexure.py)
also accepts prescribed rigidity at different times. It requires an absolute
reference load and subtracts two equilibria: current load/current rigidity minus
reference load/reference rigidity. Unchanged load can therefore produce movement
when stiffness changes. It does not derive stiffness evolution or viscoelasticity.
[Variable](../../tests/test_w04_variable_flexure.py) and
[evolving tests](../../tests/test_evolving_flexure.py) check two-material analytical
solutions, refinement and unchanged-load/changing-rigidity controls. See the
[variable evidence](../../evidence/w04-variable-rigidity.md) and
[evolving method/check record](../EVOLVING_MECHANICS.md).

### Connected support, outputs and acceptance limits

[W04 assembly](../../src/atlas_tectonics/w04_workflow.py) obtains actual W03 grain,
pore and thermal state, plus explicit placement of its finite reservoir water and
additional pressure. Reservoir placement must account for the full stock; it is
not inferred from where water left the sediment. Effective compaction stress and
external total pressure are different inputs.

W04 owns the thermal displacement, so W03's local-support comparison is excluded.
Results distinguish material, replacement, thermal and external pressure, downward
deflection, and upward-positive sediment/water-top changes. A water-top change is
unknown when either compared cell is dry. None of these alone supplies absolute
elevation, sea level or shoreline feedback.

[Combined tests](../../tests/test_w04_acceptance.py) exercise uniform/variable
rigidity with periodic, continuing and free/clamped boundaries, independent load
accounts, reference shifts, restored continuation and reuse. The
[recorded W04 acceptance](../../evidence/w04-acceptance.md) is explicitly for the
supported stationary planar 1D workflow and its snapshot. Small-deflection limits,
source checks and conservation do not establish realistic mountains or calibrated
basins.

Geometry, material records, thermal integrals, storage and execution helpers can
serve other Atlas modules. Their reuse does not transfer ownership of erosion,
surface-water flow, soils or climate into tectonics. The receiving module owns
applying a support result to its geometry and must preserve its units, reference,
unknowns and single ownership of each physical effect.
