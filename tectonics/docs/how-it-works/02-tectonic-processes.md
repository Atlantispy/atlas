# Tectonic processes: extension, spreading and regional deformation

[Guide contents](../HOW_TECTONICS_IS_MADE.md)

Atlas has several distinct ways of representing tectonic change. Some follow a
specified movement and calculate its consequences. Others solve the balance of
forces to calculate a velocity field. Combining them requires explicit agreement
about geometry, time, material and responsibility for each physical effect.

This chapter describes the implemented W05–W08 routes, including retained thermal
and geological helpers. Their location in the tectonics package does not transfer
scientific ownership: further geological, compaction and magmatic development
belongs to the corresponding modules; receiving modules apply tectonic outputs to
their own state. All outputs remain **WORKING NON-CANON**.

The linked numerical receipts describe their original source/runtime snapshots.
W01–W12 numerical receipts are outside the initial
[current-evidence register](../../../docs/CURRENT_EVIDENCE.md); they are not current
code acceptance. This guide-writing pass ran no simulations. Read
[current state](../../../docs/CURRENT_STATE.md) for present status; a historical
document's “next step” or “complete” wording does not override it.

## W05: extending a section along a curved fault

### Move the hanging wall and preserve its material

A listric fault curves towards horizontal at depth. W05 takes its trace, surface
dip in radians, detachment depth and initial crustal thickness in metres, together
with horizontal speed in m/s, density in kg/m³ and a transverse accounting width
in metres. The section is invariant along strike: that width converts section
areas into volumes without making the model three-dimensional.

Only the hanging wall—the material above the fault—moves. The footwall remains
stationary. The supplied exponential fault shape determines the initial division
between them. Under constant horizontal motion, the hanging-wall thickness at a
location is its original thickness at a point displaced backwards by the travelled
distance. Atlas integrates that profile across each grid cell. It therefore tracks
cell contents rather than treating a centre sample as the whole cell.

This analytical characteristic method avoids accumulating interpolation error
through repeated small steps. Its scope is deliberately narrow: the admitted
exponential profile, constant speed and spatially uniform cohort fractions.
Cohorts retain formation histories, and boundary exchanges remain signed section
areas in m²; multiplying once by width and density gives exchanged mass. The
separate MUSCL transport option remains a numerical comparison route. Uniform
dilation is also tested separately; it is not the physical motion of this fault.

[Landlab's listric tutorial](https://landlab.csdms.io/tutorials/tectonics/listric_kinematic_extender.html)
provides the relevant geometric precedent. Atlas's motion is prescribed, so it
cannot determine fault initiation or the stress needed to move it. The
[implementation](../../src/atlas_tectonics/extension.py) and
[motion tests](../../tests/test_w05_extension.py) check independent profile
integrals, stationary footwall, cohort balance, tiny partial cells and equivalent
output partitions. These establish transport correctness for the selected family.

### Convert thinning into one supported surface

Removing crustal thickness changes both the unflexed surface and the weight
supported below it. W05 constructs a pressure change `q = density × gravity ×
thickness change`, in pascals. Its elastic support solves `D w'''' + K w = q`:
flexural rigidity `D`, in N m, spreads the response sideways, while foundation
stiffness `K`, in Pa/m, represents the hydrostatic restoring response. Downward
deflection `w` is measured in metres. Effective elastic thickness is a separate
input from total crustal thickness.

Surface change is thickness change minus deflection. The base and fault move by
the same support displacement, while material remains accounted in its original
reference coordinates. This prevents rebound from creating fictitious rock. Every
output is compared with one fixed initial state; repeatedly adding a total
deflection would count the same response again.

The prepared support operator uses integrated Green-function weights: the response
to each load interval is added to its neighbours. Zero-padded FFT convolution
accelerates the same linear sum. Separate weights return true cell means;
interpolated point deflections would not be equivalent. The continuing elastic
layer, small-slope assumptions and exterior-load bounds follow the declared
closure, informed by [Wickert's gFlex methods](https://gmd.copernicus.org/articles/9/997/2016/).

[Support code](../../src/atlas_tectonics/extension_support.py),
[independent reference tests](../../tests/test_w05_support_reference.py) and the
[combined receipt](../../evidence/w05-acceptance.md) distinguish exact same-load
FFT/direct agreement from refinement against a smooth continuum load. They also
check hydrostatic limits, domain enlargement, and displacement, slope and bending
strain between samples. The recorded millimetre-scale numerical error is not
millimetre-scale geological accuracy. The model remains dry, isothermal and without
erosion, yielding, fault feedback or an independently calibrated analogue case.

### Save requested extension outputs

The [W05 workflow](../../src/atlas_tectonics/extension_workflow.py) joins motion and
support on an explicit output schedule. It binds the initial reference, plans,
schedule and source/runtime identities. Each completed output is published in one
storage transaction; failure leaves the previous completed state available.

[Workflow tests](../../tests/test_w05_workflow.py) and the
[recorded checks](../../evidence/w05-workflow.md) cover exact reopen/continuation,
interrupted publication, corruption, incompatible schedules and zero solver calls
for a completed saved result. They establish recoverability and faithful reuse,
not physical realism. The workflow keeps its latest state rather than duplicating
every previous grid in memory. Requested output limits remain explicit.

## W06: create oceanic material and preserve its age

### Birth and spreading

W06 starts with a declared ridge position and velocity, separate left/right plate
velocities, phase thicknesses, reference densities and finite source stocks in kg.
For the constant-motion route, a parcel born at time `τ` lies at the ridge's
position at `τ`, plus its plate velocity multiplied by the time since birth.
Two continuous birth strips retain that relationship on either side.

Intersecting a strip with a cell supplies occupied width in metres and its youngest
and oldest ages in seconds. Empty space has no valid material age. A ridge-crossing
cell retains both sides separately. Created mass equals newly opened area times
phase thickness and density; represented material and left/right exports must
account for that creation. Exhausting any phase feed refuses the candidate.

This is more informative than assigning age from distance to today's ridge:
distance works only for particular motion histories. It also distinguishes oceanic
birth from moving pre-existing continental material. The route prescribes
accretion; it does not calculate breakup or the melting process that supplies it.

See [birth implementation](../../src/atlas_tectonics/spreading.py),
[birth tests](../../tests/test_w06_spreading.py) and
[birth evidence](../../evidence/w06-birth.md). Independent trajectory/intersection
checks, finite-stock tests and boundary-crossing integrals establish the selected
geometry and mass account. Outward-motion and ridge-inside-window restrictions
prevent unsupported re-entry or disappearance at the regional boundary.

### Cool the actual age distribution

Hot newborn material cools through a finite-depth plate with fixed top/base
temperatures, conductivity in W/(m K) and volumetric heat capacity in J/(m³ K).
Crust and mantle phases can have different density and thermal expansion, but this
route shares thermal conductivity and volumetric capacity across them. It has no
internal heating. Fourier and young-time image representations of the conduction
solution support depth-and-age integrals with controlled truncation.

Cooling a cell at its mean age would give the wrong mean temperature and heat
loss, especially near the ridge. Atlas integrates across the full birth-age
interval and each phase depth. It keeps point samples separate and gives exactly
newborn material zero accumulated cooling without inventing an age floor.

The integrated temperature deficit creates a density sheet in kg/m². Dividing
this by compensation density minus water density gives downward thermal subsidence
in metres. This is one water-loaded local support calculation; another support
response cannot be added for the same thermal anomaly. Reference material mass
stays fixed under the small thermal-density approximation.

Enthalpy in joules is balanced between birth, resident material, boundary exports,
surface heat loss and basal input. Exports carry heat and associated water volume
at their first exit, not after hypothetical cooling outside the region. Named heat
and water allowances are finite. [Richards et al.](https://freddrichards.github.io/documents/papers/richards_etal_2018_jgr.pdf)
provide the plate-cooling and water-loaded-depth context, including why constant
properties do not reproduce their more elaborate calibrated Earth model.

The [cooling code](../../src/atlas_tectonics/spreading_cooling.py),
[integral kernels](../../src/atlas_tectonics/spreading_integrals.py),
[tests](../../tests/test_w06_spreading_cooling.py) and
[receipt](../../evidence/w06-cooling.md) check independent depth/age quadrature,
partial cells, three grids, heat/water closure and equivalent time partitions.
Validity is checked for the oldest parcel as well as the cell mean.

### Inherited margins and changing histories

An inherited continental margin instead starts from its actual supplied thermal
profile and geological column. It evolves that profile from the stated epoch;
unknown earlier cooling onset remains unknown. Its change from that initial
profile drives support, rather than a reset to newborn oceanic temperature.
Conservative bounds over the trajectory check wetness, water availability and
small deflection. A bound can refuse a valid case when it cannot certify the
requested envelope. [Margin tests](../../tests/test_w06_margin_cooling.py) inspect
these distinctions and source/property incompatibilities.

[Staged spreading histories](../../src/atlas_tectonics/spreading_history.py)
support asymmetric rate changes, continuous ridge migration, stopping/restarting
and explicit ownership reassignment. Events split the physical history at their
dates; asking for another output does not create another birth event. Stopping
creates no rock, but existing rock continues ageing and cooling. Reassignment
changes current ownership while preserving formation source and original plate.

First-exit calculations split at both birth and exit-motion stages. This matters
because parcels born later need not have greater exit age. The
[history cooling tests](../../tests/test_w06_history_cooling.py) check those
distributions, event boundaries, stopped-age gaps and exports frozen at departure;
[recorded evidence](../../evidence/w06-history.md) retains their snapshot.

The [W06 workflow](../../src/atlas_tectonics/w06_workflow.py) supports constant
spreading, staged spreading and inherited-margin cooling as separate scenarios.
It validates a contiguous saved output sequence and restores the newest required
payload. [Workflow tests](../../tests/test_w06_workflow.py) and the
[workflow receipt](../../evidence/w06-workflow-acceptance.json) check all three
routes and recovery without repeated thermal calculation. A shared interface
does not merge their footprints or grant duplicate access to a finite reservoir.

## W07: calculate slow regional deformation

### Balance forces, incompressibility and boundary conditions

The rectangular regional solver treats long-term rock deformation as extremely
slow viscous flow. It balances body forces against pressure and viscous stress,
while requiring the selected incompressible volume balance. Inputs include box
dimensions in metres, viscosity in Pa s, body force in N/m³, boundary velocity in
m/s or traction in Pa, and an explicit pressure convention. Outputs include
velocity, pressure, strain rate in s⁻¹, stress and boundary reactions.

The MAC discretisation places normal velocities on cell faces, pressure and normal
strain at centres, and shear strain at vertices. This arrangement connects the
flow through each cell face directly to its volume balance. The full symmetric
stress expression handles shear and mixed boundaries; it is more than independently
smoothing two velocity components. Each boundary component declares velocity or
outward traction. [PETSc's staggered Stokes example](https://petsc.org/release/src/dm/impls/stag/tutorials/ex2.c.html)
is a reference for this layout and manufactured checks, not Atlas's solver runtime.

Prescribed normal velocities must have compatible total flux. If they leave
pressure undetermined by an additive constant, a mean convention fixes that
numerical freedom. Physical pressure needed by strength laws requires a physical
datum. A traction boundary may already fix pressure, so subtracting a new mean
would change the problem. Rigid translation and rotation freedoms are checked
separately.

[Core code](../../src/atlas_tectonics/regional_stokes.py),
[SI execution](../../src/atlas_tectonics/regional_execution.py) and
[core tests](../../tests/test_regional_stokes_core.py) inspect momentum, divergence,
reactions and mechanical work from returned fields. Manufactured flows, hydrostatic
balance, Couette shear, rigid rotation and mesh refinement isolate different
failure modes. An independent finite-element comparator follows the Q2/P1 approach
described by [May, Brown and Le Pourhiet](https://jedbrown.org/files/MayBrownLePourhiet-pTatin3d-2014.pdf).
The [solver evidence record](../W07_REGIONAL_SOLVER.md) preserves both an initial
reference-adapter failure and its focused correction. Neither establishes
earthquake dynamics or unrestricted regional geology.

### Let material resistance vary

Heterogeneous viscosity is sampled where normal and shear stresses are evaluated.
That placement matters near sharp material boundaries. Temperature, depth and
strain-dependent laws then make mechanics nonlinear: the predicted flow changes
viscosity, which changes the flow. Atlas repeats the solve and material update until
both the viscosity change and force/volume/work residuals satisfy their gates.
A small residual for yesterday's viscosity is insufficient.

[Regional rheology](../../src/atlas_tectonics/regional_rheology.py) retains explicit
Kelvin, depth and strain-rate scales, the constitutive conventions of
[Tosi et al.](https://www.ipgp.fr/~samuel/henriIPGP/Publications_files/Tosi_2015-1.pdf),
and the separately supplied fixed-damage law. A fixed damage field is a snapshot,
not damage evolution. Tensor components are reconstructed together before taking
their strain-rate magnitude; averaging final viscosities is not interchangeable.

The separate dry strength route sets yield strength from cohesion and physical
pressure/friction, then limits viscous stress through the corresponding effective
viscosity. Exact zero strain uses creep viscosity. Unsupported tension, pore
pressure or viscosity ranges cause refusal; clipping is not used to manufacture
a result.

[Rheology tests](../../tests/test_w07_regional_rheology.py),
[strength tests](../../tests/test_w07_regional_strength.py) and
[interface references](../../tests/test_w07_interface_reference.py) check analytic
shear, factors and units, pressure-datum behaviour, current-law residuals and sharp
viscosity contrasts. The [method record](../W07_HETEROGENEOUS_THERMAL.md) explicitly
separates two conflicting SolCx forcing descriptions. Agreement with one must not
be claimed as testing the other. Perfect yielding supplies no physical shear-band
width or proof of mesh-independent localisation.

### Exchange heat and motion at explicit intervals

[Regional transport](../../src/atlas_tectonics/regional_transport.py) moves
cell-mean heat using conservative face fluxes, slope-limited reconstruction and
two-stage SSP-RK2 stepping, together with conduction. Physical velocity minus mesh
velocity governs transport relative to a translating grid. Material rectangles
use exact space-time intersections to retain gross incoming and outgoing stocks,
including material passing completely through the region.
Where a side prescribes a face temperature, fluid entering through that side must
be declared at the same temperature; a differing pair is refused, not blended.
On a closed or outward face, the wall temperature affects only conduction.
Ordinary outflow extrapolates from adjacent interior cell means, preserving
affine transport. Closed or turning flow uses a constant normal state, as does
an extrapolation that would be nonpositive. This prevents an unused cold wall
from creating artificial heating through the advective reconstruction. Tests
cover both extrema on all four sides down to subnormal conductivity and retain
the exact affine moving-grid check; conservative flux accounts and timestep
limits are unchanged.

The [thermal–mechanical bridge](../../src/atlas_tectonics/regional_thermomechanical.py)
solves start mechanics, advances heat using that frozen velocity, and solves endpoint
mechanics with the changed temperature. This is first-order splitting of feedback,
even though the heat substeps use a second-order method. More heat substeps do not
automatically provide more frequent mechanical feedback.

Optional thermal buoyancy supplies one total gravitational force; the pressure
reference is removed only by the mechanical solver. Inventory density remains
separate. [Interval tests](../../tests/test_w07_thermomechanical.py) and the
[active-coupling receipt](../../evidence/w07-active-coupling-r3.json) distinguish
temperature-sensitive response from stationary conduction and test translated
coordinates, balances and refinement. Rectangle transport currently requires
uniform physical motion; the bridge refuses evolving fixed-damage rheology because
it lacks compatible damage transport.

### Move a real surface and assemble compatible geology

[Free-surface evolution](../../src/atlas_tectonics/free_surface.py) moves the top
mesh boundary with the material. Its height satisfies `h_t = w − u h_x`: vertical
motion changes height, while horizontal motion carries an existing slope. Curved
Q2 elements represent geometry and velocity; discontinuous physical P1 represents
pressure. Mesh motion extends smoothly downwards while fixing the bottom.

This follows the physical/mesh distinction in
[ASPECT's ALE description](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/methods/freesurface/arbitrary-le-implementation.html).
Atlas advances surface and material inventory together, checks element orientation
and independently integrates face fluxes. Weak finite-element incompressibility
does not mean zero divergence at every point. [Surface tests](../../tests/test_w07_free_surface.py)
and [relaxation evidence](../../evidence/w07-surface.json) compare a small sinusoidal
surface with an independently derived finite-depth decay rate and refine space
and time. The supported surface route remains homogeneous and isothermal;
moving heterogeneous thermal fields require another compatible transfer.

Because the surface step is explicit, a step that is long compared with the
fastest relaxation time would make topography grow instead of relax, while every
conservation check still passes. Each step is therefore limited: the fastest
relaxation rate of a layer of thickness H on a rigid base is
0.160698 ρgH/η, and the product of that rate and the step length must not exceed
a declared limit (default 0.1). At the default the time error after one decay
e-folding is about 0.2%, against the route's 1% amplitude tolerance, and the
extra fast modes of very wide elements still decay. On a sloped surface the
flow along it also carries relief sideways, which this explicit method amplifies
unless each step moves the surface less than about a tenth of a node spacing, so
that is limited too. A refused request names the number of steps it needs;
nothing is subdivided silently. Outputs land exactly on
the requested times.

The [geological W07 workflow](../../src/atlas_tectonics/w07_workflow.py) binds actual
W01/W02 inputs, ordered layers, reference masses and named physical owners. Its
three assembled routes are steady mechanics, homogeneous closed-box thermal
evolution with explicitly constant viscosity, and homogeneous moving surface.
Lower-level nonlinear thermal capability does not silently extend that assembled
thermal route. [Workflow tests](../../tests/test_w07_workflow.py) and
[evidence](../../evidence/w07-workflow.json) cover those joins and exact recovery.
Unsupported mixtures, spherical sections and incompatible evolved columns remain
integration gaps.

When the thermal route carries heat across an interval, it records which
mechanical solution carried the heat, how far that solution's velocity had to be
corrected so that heat is conserved, and the hashes of the corrected velocity.
Each saved thermal output that evolved heat also keeps the mechanical solution
that carried it. When a saved output is read back, the workflow rebuilds the
record from that stored solution and refuses the output unless the rebuilt record
equals the saved one. Nothing is solved again. For the first interval, which has
no earlier saved output to name its solution, the stored solution must also be
the one for the starting geological state. Before this repair (R7, 1 October 2026
candidate) a saved output whose hashes had been made consistent could carry a
wrong record unnoticed. The stored velocity itself is not recomputed, so it is
trusted as saved, as every restored field is. The cost is a larger saved output,
by up to one mechanical solution each; an output saved without it is refused. The
[method record](../W07_WORKFLOW.md#recovery-storage-and-resource-ownership) gives
the exact sizes.

The steady route's optional dry strength law repeats its solve, changing the
viscosity inside the workflow's prepared solver each time. If such a change is
cancelled or fails part-way, the solver refuses all further work rather than run
with half-changed coefficients. The workflow does not keep a solver in that
state. It closes it, and the next request first prepares a new one from the same
geological inputs, so the same workflow can be asked again and returns what an
uninterrupted run returns. A new solver prepared from different source code is
refused. The [method record](../W07_WORKFLOW.md#recovery-storage-and-resource-ownership)
states the cost, which is one fresh preparation.

## W08: shortening, sliding, subduction and finite magma

### Shortening and transform deformation

[Distributed shortening](../../src/atlas_tectonics/shortening.py) takes prescribed
velocity gradients in s⁻¹, translation in m/s and dated intervals. Exact finite
maps compress each parcel's horizontal footprint. Its conserved volume divided by
new area gives thickness: 30 km becomes 37.5 km after 20% shortening. Sparse interval
intersections produce cell views and named exterior inventories without deleting
cropped material. Optional specific enthalpy in J/kg remains explicitly unknown
when absent. The [support bridge](../../src/atlas_tectonics/shortening_support.py)
turns changed column weight into one W04/W05 flexural response; it does not model
compressional buckling. [Shortening tests](../../tests/test_w08_shortening.py) and
[evidence](../../evidence/w08-shortening-r2.json) check finite maps, volume, heat,
exterior stocks and independent support.

Transform and oblique motion retain both horizontal components. Three implemented
choices have different meanings: [affine motion](../../src/atlas_tectonics/transform.py)
uses a matrix exponential for constant velocity gradients; a
[deformation network](../../src/atlas_tectonics/deformation_network.py) moves shared
triangle vertices along prescribed paths; [straight-fault slip](../../src/atlas_tectonics/fault_slip.py)
allows distinct tangential translations on the two sides. Pure shear or rigid spin
does not automatically thicken material. Network orientation is checked throughout
an interval, because acceptable endpoints can conceal an inverted intermediate
triangle. Straight-fault opening needs a different creation/deformation closure.

Exact polygon intersections allocate conserved parcels to receiving regions and
their exterior. Endpoint exchange accounts describe origin and destination, not
every intermediate crossing. [Transform tests](../../tests/test_w08_transform.py)
and [receipt](../../evidence/w08-transform.json) check shear, rotation, frame changes,
finite maps and accounts. [SciPy's matrix exponential](https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.expm.html)
is an actual numerical dependency; GPlates comparisons in the method record are
references, not an executed Atlas dependency.

### Slide material through a ramp and flat

The [underthrust route](../../src/atlas_tectonics/underthrust.py) takes a supplied
descending interface, block identities, motion, section width and non-overlapping
material parcels. It maps `(x,z)` to `(x+s, z+h(x+s)−h(x))`, where `h` is interface
height and `s` horizontal slip. Coordinates measured relative to the interface
turn this into translation. Splitting at interface bends creates exact affine
pieces that preserve area and the side on which material lies.

This vertical-shear closure preserves vertical thickness, not all possible bed
lengths or bed-normal thicknesses. It cannot select a fold or fault geometry from
stress. [Plotek et al.'s comparison](https://ri.conicet.gov.ar/handle/11336/135525)
places alternative kinematic closures alongside an analogue experiment; that
comparison motivates making the selected closure explicit, not assuming universal
validity. Stationary host material must be declared: continuous swept-path checks
detect collisions that clear endpoints miss. Named receiver polygons and an
explicit exterior retain volume, mass and signed enthalpy.

Supplied boundary work in joules and gravitational potential-energy change remain
separate. Their difference is not automatically converted into heat. The
[underthrust tests](../../tests/test_underthrust.py),
[method/source discussion](../UNDERTHRUST.md) and
[receipt](../../evidence/underthrust-r1.json) cover exact maps, side preservation,
path occupancy and finite accounts. This is a structural motion model, not a
self-consistent collision dynamics calculation.

### Calculate a prescribed slab's surrounding flow

The [subduction engine](../../src/atlas_tectonics/subduction.py) represents a supplied
slab, overriding lid and mantle wedge. Slab velocity and geometry are imposed;
wedge velocity and pressure are calculated, except in the analytical corner-flow
case, which prescribes the velocity and therefore publishes no pressure (it
previously published a fabricated field of zeros). Interface-aligned triangular meshes
keep those regions distinct. Quadratic P2 velocity and linear P1 pressure form a
Taylor–Hood finite-element pair; temperature uses continuous P2 interpolation.
The published fields are m/s, Pa and K, with explicit conversion from internal
kilometre/slab-speed units and downward depth to Atlas's upward coordinate.

The five reference cases distinguish analytical corner flow, calculated constant-
viscosity flow and temperature/strain-dependent creep. They derive from
[van Keken et al.'s 2008 benchmark](https://www.sciencedirect.com/science/article/pii/S0031920108000848).
They are local steady experiments, not freely sinking slabs or a global mantle.

High viscosity contrasts make the pressure/velocity equations difficult to solve.
Atlas uses a weighted BFBT preconditioner: an auxiliary sequence of simpler block
solves makes the original coupled solve tractable. The method follows
[Rudi, Stadler and Ghattas](https://arxiv.org/html/1607.03936v2), with an explicitly
documented positive-weight adaptation for Atlas's triangular elements. Independent
original-equation residuals remain the acceptance criterion; a preconditioner
does not replace the physical equations. [Linear tests](../../tests/test_w08_subduction_linear.py)
check that boundary, pressure and residual contract.

### Transfer velocity consistently and stabilise heat transport

The steady heat equation balances advection by moving rock and diffusion through
it. Weak incompressibility in the mechanical solution is insufficient for every
thermal test. Atlas constructs a separate locally divergence-free transport
velocity from the curl of a cubic streamfunction, preserving boundary-normal
transport. The mechanical field remains available separately. This prevents an
inconsistent transfer from heating a constant-temperature field or making the
result depend on Celsius versus Kelvin representation.

SUPG—streamline upwind/Petrov–Galerkin stabilisation—adds a residual-based term
along the flow direction to control oscillatory advection errors. Atlas includes
the quadratic diffusive Laplacian in that residual; omitting it would change the
method's consistency. [Brooks and Hughes](https://www.sciencedirect.com/science/article/pii/0045782582900718)
describe the original weighted-residual approach. SUPG is not a general guarantee
that temperature remains
within physical bounds. Conservative boundary terms retain heat carried out by
flow. Natural outflow sets diffusive normal flux to zero, not total heat flux.

The [source resolution](../W08_SUBDUCTION.md#source-resolution-and-step-4-closure)
derives that condition independently, supported by the weak-form explanation in
[Wilson and van Keken](https://link.springer.com/article/10.1186/s40645-023-00588-6).
Equivalence with every original 2008 contributor's code remains **NOT_VERIFIED**.
[Transfer tests](../../tests/test_w08_subduction_transport.py) check normal flux,
constant-temperature preservation and temperature-reference invariance; the
[subduction tests](../../tests/test_w08_subduction.py) inspect the joined operator.

### Converge rheology and resolve the mesh

Diffusion creep depends strongly on temperature; dislocation creep additionally
depends on strain rate. Atlas evaluates the specified laws in logarithmic arithmetic
with their declared harmonic viscosity cap. Coupled iterations recompute mechanics,
temperature and viscosity. Safeguarded Anderson acceleration combines recent
log-viscosity updates to approach the same fixed point faster; a worsening proposal
returns to its retained Picard update. The finite bound remains 200 maps, with
temperature change no greater than 10⁻⁴ K and log-viscosity residual no greater
than 10⁻⁷. [SCS's algorithm documentation](https://www.cvxgrp.org/scs/algorithm/acceleration.html)
informed that acceleration; SCS is not an Atlas dependency.

A converged iteration can still solve an inadequately resolved spatial problem.
The historical comparison therefore used 6/3/1.5 km base-spacing sequences and
fixed point, slab and wedge temperature diagnostics. Fine-reference disagreement
had to stay within 2 °C and the finest refinement change within 1 °C.

The diffusion-creep route required one-pass solution-guided refinement. Its
[indicator](../../src/atlas_tectonics/subduction_refinement.py) combines velocity-
gradient jumps and log-viscosity gradients across the whole wedge, marks a fixed
fraction of indicator weight, and inserts interior points without changing the
interface partition. [ASPECT's refinement documentation](https://aspect-documentation.readthedocs.io/en/latest/parameters/Mesh_20refinement.html)
provides the velocity/viscosity-indicator context; Atlas's one-pass triangle rule
is its own implementation. Remote flow error can affect local temperature, so refinement
is not confined to the diagnostic box. It is not a certified error bound or an
automatic route for every case.

[Refinement tests](../../tests/test_w08_subduction_refinement.py),
[acceptance tests](../../tests/test_w08_subduction_acceptance.py) and the
[closure receipt](../../evidence/w08-subduction-acceptance.json) bind the retained
five-case comparisons, including the adapted diffusion-creep case. These are
historical snapshot results, separate from the held, incomplete R4.4 campaign.
They establish neither present-code acceptance nor empirical validity for every
natural subduction zone.

### Retire finite material and account for magma

[Subduction retirement](../../src/atlas_tectonics/subduction_materials.py) is
separate from wedge diagnostics. It withdraws finite cohort mass using density,
thickness, section width and velocity relative to the boundary. Explicit fractions
credit accretion, deep storage or exports simultaneously. Components and signed
enthalpy travel with the mass. [Retirement tests](../../tests/test_w08_subduction_materials.py)
check exact exhaustion and destination-order independence. No unspecified donor
replenishes a depleted slab stock.

The retained magma helpers accept finite stocks, component properties, transfer
rates in kg/s, heat in W or J and receiving density in kg/m³. The
[thermal helper](../../src/atlas_tectonics/magmatic_thermodynamics.py) inverts enthalpy
to temperature and phase fraction using the supplied common melting temperature,
heat capacities and latent heats. Added energy can melt material at constant
temperature; already-liquid extraction must not pay latent heat again. Empty
stock has no invented temperature.

[Transfer](../../src/atlas_tectonics/magmatic_transfer.py) evolves well-mixed
reservoir components and enthalpy together. Fixed-mass linear cases use an augmented
matrix exponential; changing-mass mixtures use
[SciPy DOP853](https://docs.scipy.org/doc/scipy/reference/generated/scipy.integrate.DOP853.html)
with admitted nonnegative transfer maps and extensive-account checks. DOP853 itself
does not guarantee positivity. Singular mixed recharge/depletion endpoints remain
unsupported. [Keller and Suckale](https://academic.oup.com/gji/article/219/1/185/5523132)
provide the distinction between transported energy and phase-reaction energy;
Atlas is not reproducing their full multiphase continuum model.

When a thermal law is supplied, each stock declared as a melt or solid source must
match its phase under that law, at the start and in every published remainder. A
stock with no latent heat has a temperature but no melt fraction, so it is compared
with the melting temperature instead: melt above it, solid below it. A stock exactly
at that temperature is refused as ambiguous. This comparison checks only the label
declared for a transfer. Heat-paid melting and the separate
[delivery interface](../I01_DELIVERY.md) still refuse a stock with no latent heat at
every temperature.

[Emplacement](../../src/atlas_tectonics/magmatic_emplacement.py) assigns intrusion
or extrusion and accounts for finite displaced/replaced host material. Net load
depends on incoming minus outgoing mass per area. It does not independently run a
thermal or structural response. [Thermodynamic tests](../../tests/test_w08_magmatic_thermodynamics.py),
[transfer tests](../../tests/test_w08_magmatic_transfer.py) and
[recorded controls](../W08_MAGMATISM.md) use calorimetry, analytic mixing, competing
outlets, exact depletion and component/enthalpy closure. They check supplied
processes rather than predicting volcano locations or melt-source chemistry.

### Join regimes and exchange evolving mechanical inputs

The [W08 workflow](../../src/atlas_tectonics/w08_workflow.py) serialises dated
shortening, affine transform/oblique motion, retirement, magma transfer and
cessation. Each node owns its mass and enthalpy once. Events require continuous
geometry, polarity and source declarations. A completed interval ends exactly at
its supplied end time, even when start plus duration rounds one unit short. Cessation advances the clock without
emptying reservoirs. Exact supported exhaustion is committed before unspecified
continuation stops. Saved transfers cannot be spent again on restart.

Its [regional view](../../src/atlas_tectonics/w08_region.py) allocates stocks to
disjoint parcels and reports thickness, volume, advected enthalpy and pressure
load change. A stock and its spatial view are the same material. Non-affine fault
networks, steady wedge diagnostics, explicit host replacement and heat-paid melting
remain separate component operations rather than arbitrary joined transient
histories. [Workflow tests](../../tests/test_w08_workflow.py) and the
[joined receipt](../../evidence/w08-joined.json) test regime transitions, conserved
stocks, interruption before/after commit and recovery without repeated transfers.

The later [evolving-mechanics interface](../../src/atlas_tectonics/evolving_mechanics.py)
accepts coincident material, force, boundary and surface-pressure inputs. Their
time, frame, sampling and physical owners must agree. Changed viscosity rebuilds
coefficients; changed force can reuse compatible geometry. It produces a
quasi-static snapshot, not an invented path between supplied states.
[Tests](../../tests/test_evolving_mechanics.py) check hydrostatics, shear, time/frame
refusals and duplicate force ownership. The related
[evolving-support record](../EVOLVING_MECHANICS.md) explains why changing rigidity
requires separate absolute reference/current equilibria. Preserving these exchange
boundaries makes the individual methods useful together without claiming a fully
coupled planet.

A viscosity change can be interrupted: cancelled, or failed, while the solver's
coefficients are being replaced. A half-replaced operator would pair new
coefficients with the previous material's name. The regional plan therefore
refuses all further work once a change was interrupted, says that this is the
reason, and reports it through a `usable` flag; it does not try to undo the
change. The interface does not keep such an operator. It closes it and prepares a
new one from the next request's own material, which gives the same result as an
uninterrupted change at the cost of one fresh preparation. A cancellation can
also arrive just after a change was accepted, so the error alone does not show
which material the operator holds. After any failed change the interface
therefore stops trusting its own record of that. Before the next request is
solved it reads back from the operator which material is in place, and changes
the coefficients if the request needs another one, so a request is never solved
with whatever happened to be left behind. A replacement operator must come from
the same source code as the first one; otherwise the request is refused. The
evolving-mechanics tests cancel a change at every point where cancellation is
checked, and a [history test](../../tests/test_tectonic_history.py) resumes a dated
sequence after such a cancellation. The [method record](../EVOLVING_MECHANICS.md)
lists what the repair costs.
