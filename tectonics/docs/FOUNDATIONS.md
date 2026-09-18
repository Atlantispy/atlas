# Foundation case and numerical contract

**Current R2 extension (18 September 2026):** the original foundation contract
below is preserved. Version `0.1.0.dev22` additionally supports the plate-independent
precursor and bounded static W01 stage-5 sampler specified in
[plan revision 26](TECTONICS_PLAN.md#3cr2-initial-state) and
[`precursor_r2.json`](../cases/precursor_r2.json). This adds initial material-volume
accounting and temperature samples, not E04 time integration, a constitutive law,
a global disjoint dynamics mesh or accepted physical plate generation. R1's
strict/scoped gates and all original numerical cases remain unchanged. The R2
execution/indexing follow-up adds conservative candidate pruning and admitted
independent batches, not equations; its [separate execution case](../cases/precursor_r2_scaling.json)
preserves the original R2 numerical tolerances and whole-request inventories.


**ATLAS-TECTONICS-FOUNDATIONS-001, revision 1, 16 September 2026.**
Scope: first implementation under ATLAS-TECTONICS-PLAN-1 revision 3. The controlling
plan's original Markdown SHA256 is recorded in `../cases/foundations.json`. The
plan is an attached review artefact, not claimed to be published in this repository.

## Equations and boundaries

1. **E01/E02 kinematics.** Rigid rotations are unit quaternions, with right-handed
   geocentric XYZ coordinates. `a.then(b)` applies a then b. Instantaneous velocity
   is `omega cross r`, in m/s with omega in rad/s. It is not a finite chord velocity.
   Boundary diagnostics use x east / y north and right normal `(t_y,-t_x)`;
   relative velocity is right minus left. Positive normal motion means opening
   only under correct declared side geometry. No automatic geological interpretation.
2. **N01 source-free transport.** Constant-density solid-equivalent thickness H
   satisfies `dH/dt + d(uH)/dx = 0` on a fixed periodic uniform grid. H is a cell
   average; u[i] is the velocity on cell i's right face. A shared upwind flux
   `F[i]=u[i]*(H[i] if u[i]>=0 else H[i+1])` yields
   `H_new[i]=H[i]-dt/dx*(F[i]-F[i-1])`. Indices wrap. The positivity requirement is
   `dt/dx*(max(u[i],0)+max(-u[i-1],0)) <= 1` in every cell. This bound matters for
   divergent velocities and is stronger than merely checking max(abs(u))*dt/dx.
   The implementation uses an equivalent positive-weight form, without clipping.
   The conserved quantity is sum(H)*dx in m2 (solid volume per fixed unit width),
   not an integrated three-dimensional mass or the legacy integer mass account.
3. **E04 cooling.** `T=Ts+(Tm-Ts)*erf(z/(2*sqrt(kappa*t)))`, z positive downwards,
   SI seconds/metres/Kelvin and constant positive diffusivity. At t=0, the positive
   depth interior is Tm; the prescribed surface is Ts. The corner follows the
   surface boundary. No hidden minimum age. This evaluates an analytical profile,
   not a conduction timestepping solver. Scalar math.erf is a transparent reference
   within a batch, not a claim of a fully SIMD/vectorised special-function kernel.
4. **E12/E13 flexure.** `D*w'''' + K*w = q` with positive-down deflection w (m),
   load q (Pa), `D=Y*Te^3/[12*(1-nu^2)]` (N m) and `K=delta_rho*g` (Pa/m).
   Flat uniform thin elastic plate; small deflections; no in-plane stress; periodic
   boundaries. The discrete centred fourth difference has modal eigenvalue
   `(2*sin(pi*k/N)/dx)^4`. FFT divides each load mode by D times that eigenvalue
   plus K. This is **not** using continuous k^4 then calling it finite differences.
   The spatial scheme is second order for smooth fields. Uniform load gives w=q/K;
   a continuous sinusoid gives amplitude q0/(D*k^4+K), approached under refinement.
   Total deflection is returned, not an increment to add repeatedly to terrain.

All real inputs must be finite and supported by the stated sign/shape conventions.
Values outside finite binary64 intermediate range are refused rather than clamped.
Input Booleans, strings and complex arrays are rejected. Profiles contain source
labels, units in field names and no omitted-value defaults. Raw IEEE arithmetic is
not exact geology; conservation residuals and discretisation errors remain visible.

## Predetermined verification

The original case sheet set 1e-12 relative/absolute comparison tolerances for these
synthetic order-one quantities before the test suite was run. Those values do not
become universal geological or production tolerances. Smooth transport order must
lie between 0.8 and 1.2; smooth flexure order between 1.8 and 2.2 over three grids.
The grids are at most 128 cells in the present tests, below the case's 256-cell
fixture budget. That is a test scope, not a new hard-coded global Atlas limit.

Independent checks include hand-evaluated rotations, a scalar flux-divergence loop,
a tabulated error-function value, and a dense real-space flexure operator assembled
without FFT coefficients. Mutation/refusal cases cover negative thickness, invalid
properties, Courant violation, incompatible dimensions, nonfinite arithmetic,
readonly results and changed parameter/operator identity. Repeated short transport
steps are mathematical convergence fixtures, not a world or geological simulation.

The verification command inventories source/test/fixture bytes before and after,
records interpreter and NumPy versions, and fails if there are skips, errors or
source changes. This is local test evidence, not a tamper-proof attestation, a
historical restart seal, physical acceptance or a performance benchmark.

## Performance and memory scope

Use contiguous NumPy arrays and bounded caller-owned batches. Each public kernel
validates and detaches caller data; this first implementation favours clear ownership
rather than claiming zero-copy performance. Returned bytes-backed arrays cannot
be made writeable. Caller controls workload size; APIs do not independently enforce
a process RSS or wall-time budget. Verification uses no additional worker pool;
native library thread settings are recorded, with one thread selected for delivery
checks. No parallel/distributed scalability is claimed.

`PeriodicFlexure` retains N//2+1 coefficients. `setup_bytes` reports only those
coefficients, excluding Python metadata, inputs, FFT workspace and output copies.
Different loads reuse them; different material/grid definitions create different
operators. There is no process-global or persistent scientific result cache.

## Method references (not integrated packages)

- pyGPlates rotation/velocity convention reference:
  https://www.gplates.org/docs/pygplates/generated/pygplates.calculate_velocities
  Its finite-rotation/time API is not asserted identical to this instantaneous API.
- Wickert (2016), gFlex methods and physical scope:
  https://gmd.copernicus.org/articles/9/997/2016/
  This is an independent restricted Fourier-diagonalised difference solver, not
  copied gFlex code or a claim about an existing stable gFlex FFT feature.
- NumPy real FFT conventions:
  https://numpy.org/doc/2.3/reference/generated/numpy.fft.rfft.html
- Atlas Reports 01–04 / P01, P03, P06 and N01 in Plan 05 revision 3 supply the
  reviewed scientific context. No external solver, code, calibration data or
  database was imported to implement the formulas.


<a id="w02-regional"></a>

## W02 regional case: open/closed constant-density thickness transport

This section extends the existing case notes; it does not revise the preceding
periodic fixture or its acceptance thresholds. The executable case inventory is
`cases/regional_transport.json`. All values are synthetic, not Earth calibration.

For cell means H_i on uniform fixed width dx, solve dH/dt + d(uH)/dx = 0.
Face j is between cells j-1 and j; positive u and F point towards increasing x.
The Euler balance is Hnew_i = H_i + (dt/dx)(F_i - F_{i+1}). There are N+1 faces.

For first-order upwind, F_j selects the donor cell mean by the sign of u_j.
The compiled donor-weight evaluation avoids unnecessary cancellation while solving
that same finite-volume balance. Internal faces cancel in the domain account.
The incoming exterior state is consumed only on inflow; outflow comes from inside.
A closed boundary requires a supplied zero velocity. No outside state is guessed.

The higher-order profile uses limited piecewise-linear reconstruction. Interior
slopes are minmod(2*dL, (dL+dR)/2, 2*dR), where dL/dR are adjacent differences.
At an end, use a limited one-sided estimate from interior differences; cap its
magnitude by 2*H_end so reconstructed end values cannot become negative. A one-cell
grid has slope zero. At either boundary, a prescribed exterior quantity denotes
its physical FACE thickness, not a ghost cell centre. It is held fixed for one
submitted interval. Outgoing boundary flux uses the reconstructed interior face.

Time integration is SSP-RK2: H1 = H + dt*L(H), Hnew = (H + H1 + dt*L(H1))/2.
The implementation uses an equivalent difference-form average of two nonnegative
states to avoid halving the smallest subnormal value to zero or summing two large
positive values before halving. Return the corresponding average of the two face
flux arrays; it is not the flux at the final state. For frozen prescribed velocity,
require r*(max(u_right,0)+max(-u_left,0)) <= 1/2 for each cell (<=1 for upwind).
This is a sufficient positivity bound for the selected reconstruction/SSP scheme.
Intervals crossing a forcing discontinuity must be split by the caller. No automatic
substepping or claim of second-order accuracy for unresolved forcing is made.

Inventory V=dx*sum(H), in m² per unit width. Signed exchanges INTO the domain are
L=dt*mean(F_left) and R=-dt*mean(F_right). Check Vafter-Vbefore-L-R using accurate
summation, with a new-method roundoff allowance 128*eps*max(Vbefore,Vafter,in,out,tiny).
Do not alter a final cell to force closure. This is a floating-point volume account,
not the older fixed-quantum mass ledger and not an assumption of exactly zero drift.

Independent verification uses rational first-order fluxes, exact cell integrals
for a translated compact pulse, analytic uniform extensional decay, reflected
coordinates, sharp fronts and multiple refinements. The native/reference algorithms
have separate implementations; compilation is not the reference oracle. The default
is a compiled higher-accuracy profile; first-order is retained because lower error
per step and lower cost per step are different criteria. Boundary accuracy has an
explicit linear-profile reconstruction test, not only an interior periodic test.

Methods references, not copied implementations:
- [Clawpack conservation/advection](https://www.clawpack.org/riemann_book/html/Advection.html)
- [Clawpack boundary conventions](https://www.clawpack.org/bc.html)
- [Clawpack finite-volume solvers](https://www.clawpack.org/pyclaw/solvers.html)
- [Numba parallel-dependency requirements](https://numba.readthedocs.io/en/stable/user/parallel.html)

This delivered interval solver does not generate plate boundaries, carry material
cohorts, create crust, infer forces, construct vertical loads or accept a landscape.


<a id="w02-cohorts"></a>

## W02 cohort transport and formation histories

Executable contract: `cases/material_transport.json`. One shared prescribed face
velocity and a fixed regional grid are retained. Each cohort's partial thickness
H_k is nonnegative and satisfies

$$\partial_t H_k + \partial_x(u H_k)=0,\quad H=\sum_k H_k.$$

For each cohort separately, with x-positive flux and fixed cell width,

$$V_k^{n+1}-V_k^n = \Delta t(\bar F_{k,0}-\bar F_{k,N}) + r_k,$$

where r_k is the reported floating-point residual, NOT material to redistribute.
For SSP-RK2 the flux is the mean of the two stage fluxes. The regional 128-epsilon
roundoff rule is retained per cohort. Incoming/outgoing amounts are nonnegative;
left/right exchanges are signed into the domain. Native totals use the existing
exact nonnegative accumulator before rounding. Required fields remain binary64.

MC-limited MUSCL/SSP-RK2 remains the accuracy-first default with outgoing fraction
at most 1/2. Upwind's bound 1 is available only by explicit selection. Execution
or memory pressure never reduces order or changes the requested timestep. The
native row driver shares O(N) RK scratch and retains O(CN) candidate/flux outputs;
reference calculations use the independently implemented regional NumPy law.

Total thickness is derived, not separately evolved. Consequently fractions are
nonnegative and sum to one within rounding wherever H>0; in empty cells they are
undefined and accompanied by an occupancy mask. No normalisation alters conserved
partial thickness. Limiting is nonlinear: sum(limited H_k) does not generally equal
limiting(sum H_k). This model does not claim equivalence to a solver separately
advancing density/momentum, equal-volume immiscible fluids, or a VOF method.
Those couplings need consistent total/component transport in their own case.

A material class and origin share one catalogue record. Formation time is a cohort
attribute with an explicit epoch; age t-t_form is queried, not transported as an
average. None means unknown. Material with identical rock class but different
formation/origin is not merged. This increment does not retain complete temperature,
burial/exhumation paths or perform mineral-age inversion.

An instantaneous event applies a prescribed nonnegative partial-thickness amount
A_k at exactly the parent's time: H'_k=H_k+A_k for birth/add, H'_k=H_k-A_k for removal.
Overdraw refuses. Its residual checks V'_k-V_k-(signed transfer)=r_k. Birth requires
known formation time equal to event time; transfer of existing material preserves
its age. A named external reservoir makes the regional source/destination explicit,
without claiming that a planetary mantle reservoir has been solved. Time-varying
sources require explicitly split events or a later independently specified source
integrator; this is not an unanalysed operator-splitting model.

Every event binds its exact parent state and time. Repeating on that immutable
parent yields the same candidate; applying the event to its successor refuses.
Receipts retain event ID, source/destination, amount hash and before/after totals.
The current state stores only its last transition and lineage IDs. A historical
chain requires preserving those records, but decoding a snapshot never depends on
all previous manifests. Zero-inventory cohorts remain identified.

Tests include exact rational upwind fluxes, a one-cohort scalar equivalence check,
random independent-reference cases, smooth refinement, rare/sharp cohorts, zero and
unknown ages, cold backup restoration, stale identities, source/sink accounts,
immutable views, memory refusal, cancellation and independent scenario execution.
These are mathematical checks, not observational geological validation.


<a id="w02-completion"></a>

## W02 regional completion: conservative remap, ALE and ownership

The executable case is `cases/w02_completion.json`. The supported geometry is an
ordered 1D partition, not a closed spherical plate network. The initial material
history and prior numerical fixtures are retained. Input physical constants are
explicit; no new Earth or Diadem calibration is chosen.

### Conservative regridding at one time

For cohort k and donor cell i, reconstruct

\[
H_{ki}(x)=\bar H_{ki}+s_{ki}(x-x_{ci}).
\]

Slopes are nonuniform-grid, monotonised-central limited, with endpoint positivity
constraints. Endpoint cells use one-sided reconstruction; an exactly affine
profile remains exact where the positivity limiter does not activate. Each target
cell receives the integral over every intersecting donor interval:

\[
\bar H'_{kj}\,\Delta x'_j=
\sum_i\int_{I_i\cap I'_j}H_{ki}(x)\,dx.
\]

A sorted overlap sweep stores at most Ns+Nt-1 nonempty intersections: O(Ns+Nt)
geometry, not a dense Ns*Nt matrix. Local midpoint offsets reduce cancellation
from large absolute coordinates. Compiled integration uses one reused slope
vector and accurate positive accumulators. Formation ages/IDs are never averaged.
The same physical domain and frame are mandatory. Do not call cropping a remap.
Conservation of inventory does not restore high-frequency information lost by
coarsening; only suitably reversible mappings receive inverse tests.

### Moving control volumes

With edges x_j, physical velocities u_j and mesh velocities w_j, define

\[
Q_{ki}=\bar H_{ki}(x_{i+1}-x_i),\qquad
\dot Q_{ki}=F_{ki}-F_{k,i+1},\qquad F=(u-w)H_{face}.
\]

Edges move as x_new=x_old+dt*w during one explicitly frozen-face-forcing interval.
SSP-RK2 advances Q, not an average of thicknesses living on different geometries.
The predictor is evaluated on the initial geometry and the corrector on the
candidate geometry; their **mean face flux** is the integrated boundary account.
Constant H is preserved for a moving mesh through stationary uniform material
(the discrete geometric conservation check); u=w gives material-following cells,
so stretching lowers H while preserving Q.

Limited MUSCL uses an outgoing-Courant cap of 0.5 on both relevant stage widths.
First-order upwind is explicit and uses its own cap of 1. Mesh faces cannot cross;
nonzero motion that is unresolvable at the represented coordinate scale is refused.
`ale_timestep_limit` includes cell contraction even with zero relative flow. It
returns advice, never alters the requested duration. Known event times inside a
step are refused; boundary/forcing events require explicit step splitting.

For a block spanning faces a to b, the SAME interval-mean F gives
Q_after=Q_before+dt*F_a-dt*F_b, per cohort. Left/right neighbours cannot own separate
copies of one physical boundary flux. Totals are volume per transverse width in
m² under a common constant-density model, not a variable-density mass ledger.

### Topology and event semantics

A cut coordinate is stored once and defines both adjoining sides. Active blocks
cover the whole interval, with no repair by polygon clipping or material deletion.
Block, plate, mesh, material-origin and event identities are distinct. Plate lineage
is acyclic; retired block/boundary IDs cannot be rebound. A split or merge retains
its parent IDs and changes ownership, not material origin or formation time.

An instantaneous `move_partition` is explicitly reclassification: old/new ownership
intervals are overlaid and their per-cohort transferred inventory is reported.
It is not physical material motion. `advance_plate_state` instead moves physical
control volumes through ALE and requires cuts aligned with material mesh faces.
A missing alignment requires an explicit conservative regrid first.

Each event is bound to its model parent and a previously unused ID. Full earlier
receipts should be retained in the existing history store when needed; the live
state retains the last receipt plus used/retired IDs, not per-cell copies of an
ever-growing log. Snapshot restoration is self-contained, not a dependency on a
long chain of delta parents. Birth/removal amounts remain prescribed inputs; an
active ridge or subduction label does not generate physical rates or forces.

### Markers and supported claims

`MaterialMarkers1D` applies a declared corresponding-cell material map and tracks
sum(log(new_width/old_width)). Stable IDs, cohort association, epoch and time survive
mapping and persistence. It is not a mass-carrying particle representation and
cannot infer actual trajectories from arbitrary numerical mesh motion.

The 1D regional W02 contracts now have executable remap, motion, partition, event,
persistence and optimisation tests. General 2D/spherical networks, triple junctions,
force-derived events, variable density/momentum/energy, predictive magma/slab laws
and field-geological validation remain distinct scientific/geometry extensions.
W02 does not supply W04's load law or establish W05 landform realism.

Primary method context: [Fazio/LeVeque moving-mesh conservation](https://www.math.ntnu.no/conservation/1998/020.html),
[geometric conservation](https://epubs.siam.org/doi/10.1137/S1064827501384925), and
[GPlates deformation conventions](https://www.gplates.org/docs/user-manual/crustaldeformation/).
These are method references, not copied software or executed external benchmarks.


<a id="w01-coordinates"></a>

## W01 stage 1: coordinate, handedness and time contract

The independent fixture is `cases/w01_coordinates.json`. It does not change older
scientific fixtures or their tolerances. Binary64 is retained throughout.

### Coordinates and frame meaning

For geocentric latitude phi, east-positive longitude lambda, radial height h and
explicit radius R:

`r = (R+h) (cos(phi)cos(lambda), cos(phi)sin(lambda), sin(phi))`.

Inverse latitude uses `atan2(z,hypot(x,y))`; the radius uses nested `hypot`, not
naive squaring. Longitude is canonical in [-pi,pi), or [-180,180) when degrees are
explicitly requested. At the exact axis x=y=0, inverse longitude is zero. The centre
has no spherical coordinates. Near-pole points are not snapped using a tolerance.
At an exact pole, constructing a local frame requires an explicitly supplied
longitude as its meridian orientation; this does not make longitude physically
unique there. Geocentric spherical latitude is not ellipsoidal geodetic latitude.

ENU columns in parent Cartesian axes are
`E=(-sin(lambda),cos(lambda),0)`,
`N=(-cos(lambda)sin(phi),-sin(lambda)sin(phi),cos(phi))`, and
`U=(cos(lambda)cos(phi),sin(lambda)cos(phi),sin(phi))`.
The optional local-axis angle rotates X from E towards N and Y correspondingly.
For column-vector notation and local basis Q, positions obey
`x_local=Q^T (r-r_origin)`; vectors obey `v_local=Q^T v`.
The implementation stores rows in arrays and uses the corresponding transposes.
This is an affine 3D frame: dropping U is not lossless, local E is not arc length,
and no area-preserving projection is supplied.

For an explicitly moving origin/axes, the instantaneous relative velocity is
`v_local=Q^T [v-v_origin-omega cross (r-r_origin)]`.
The caller supplies origin velocity and angular velocity in the parent frame.
This is a coordinate transformation, not a plate-motion model or integration of Q.
Static vector component conversion does not add or remove these transport terms.

Legacy east/south/up axes are left-handed. Their polar-vector reflection is
`S=diag(1,-1,1)`. An axial vector instead transforms with `det(S)*S`; otherwise the
cross-product orientation would be wrong. No legacy data are edited automatically.

A nonzero radial height or local displacement wholly lost in origin arithmetic is
refused where detectable. Finite accepted coordinates still have ordinary binary64
roundoff; arbitrary sub-ULP detail cannot be recovered. For scale L, the case tests
coordinate errors using 64*machine_epsilon*L plus the stated relative allowance;
angular error is separately bounded. Large-origin round trips are NOT advertised
as bitwise identity. Masked/unknown values are refused, not filled with zeros.

### Time and units

`TimeAxis` defines `t_s=zero_time_s+sign*unit.seconds_per_unit*coordinate`, with sign
+1 for forward axes and -1 for before/look-back axes. Durations remain nonnegative
and use the positive scale regardless of orientation. Derivatives use sign/scale.
A geological formation age can therefore be explicitly converted to a timestamp
in W02's named epoch; it is not automatically a thermal age or a calendar date.

Different epochs require a declared `EpochOffset` satisfying
`t_target=t_source+offset_s`. Identical epoch labels cannot have a nonzero relative
offset. Direct axis conversion combines origins before rescaling so an avoidable
large absolute intermediate does not erase small local intervals. Unsupported
range, lost nonzero offsets and unresolvable positive advances are errors, not
zero timesteps. W02's historical epochs and time checks are unchanged.

The SI-second unit is explicit. A Julian year is an explicitly selected fixed
31,557,600 seconds (365.25 fixed days); a million Julian years multiplies that by
1,000,000. There is no unqualified year/month, UTC/TAI conversion, leap-second table,
or assumption that a fictional planet's orbital/rotation period equals Earth’s.

### References and verification limits

- ESA Navipedia, [ECEF/ENU transformations](https://gssc.esa.int/navipedia/index.php/Transformations_between_ECEF_and_ENU_coordinates), basis equations (3)–(6) and spherical-latitude note. No ellipsoid dataset or source code is imported.
- IAU, [Measuring the Universe](https://iauarchive.eso.org/public/themes/measuring/), fixed Julian-year definition. Used only for explicitly named unit constants.

The new tests use independent scalar formulas, exact cardinal bases, invariants,
round trips, source/constant-change refusal, budgets and cold-process restoration.
They verify conventions, not planetary polygon coverage, geological realism,
Windows compatibility or completion of the remaining W01 stages.


<a id="w01-geometry"></a>

## W01 stage 2: identified planar and spherical feature geometry


**Targeted correction, 17 September 2026:** finite-arc plane normals use
$(a+b)\times(b-a)=2(a\times b)$ and scale-safe normalisation. This avoids loss of
short-edge direction through cancellation of nearly equal endpoint products. The
nearest projected point must still lie on the finite minor arc; otherwise an
endpoint supplies the distance. No tolerance enlarges the physical arc. Independent
90-digit Decimal geometry of the stored endpoints checks the implementation at the
unchanged tolerance in `cases/w01_geometry.json`.

The public metric checks finite metres after unit conversion; zero-length imported
edges are rejected under the direct-construction rules; cancellation also applies
to empty results. `tests/test_w01_geometry_corrections.py` retains the original
review probes and adversarial extensions. Earlier acceptance constants and
historical evidence are unchanged.


This is a representation/geometry case, not geological validation. The executable
contract is `cases/w01_geometry.json`; earlier fixture values/tolerances are untouched.
The units and axes of stage 1 remain controlling. Supply a consistent identified
Cartesian plane (prefer the full stage-1 frame identity, not an ambiguous map label).
Spherical inputs are directions in a named planet-centred frame, with an explicit
radius. They are not latitude/longitude pairs or ellipsoidal geodesics. Use the
stage-1 spherical conversion with explicit angular units to create directions.

### Topology versus metric

Planar operations use GEOS through Shapely in double precision (`grid_size=0`).
Concavity and holes are retained; crossings, degenerate area and invalid holes are
refused. Polygon construction accepts a conventional repeated closing endpoint but
rejects other duplicate vertices. Traces retain direction. Intersections can have
area, length, a point contact, mixed components or be empty; contacts are not erased.
No `make_valid`, coordinate snapping, buffering-to-repair or tolerance-based deletion.
Geometry IDs preserve the declared coordinate representation and frame. Two shapes
with equal area or geometrically equivalent ring order need not have equal IDs.

For a spherical chart with unit centre c and tangent basis e,n, a unit direction p is
mapped to gnomonic coordinates

    x = (p dot e)/(p dot c),  y = (p dot n)/(p dot c).

All feature vertices must satisfy `p dot c >= min_cosine > 0`. `min_cosine` (default
0.001) is a declared conditioning envelope, not a physical planet parameter or a
permission to move a vertex. Great-circle arcs map to straight lines only for a
sphere. A chart therefore supports non-convex polygons/holes inside its open
hemisphere, including seam-crossing and polar regions. The selected interior is
the bounded polygon in this chart. Antipodal endpoints and the opposite spherical
complement are not inferred. Pair overlays require an admissible common chart;
existing charts and a validated joint-centre candidate are tried, otherwise the
caller must partition/rechart explicitly. This does not claim arbitrary whole-sphere
Boolean operations or a closed global plate-coverage validator.

Spherical area is NOT planar chart area. A signed triangle fan uses

    omega(c,a,b) = 2 atan2(det(c,a,b), 1+c dot a+a dot b+b dot c).

The determinant is evaluated as `c dot ((a-c) cross (b-c))` to reduce cancellation
for small patches; signed contributions are accurately summed, hole areas are
subtracted, and steradians are multiplied by R². Concave rings do not become their
convex hull. Distances use `2 atan2(norm(a-b), norm(a+b))` and finite-arc projection:
a nearest great-circle point is eligible only if it lies on the declared minor arc.
Otherwise the nearest endpoint is used. No chord or projected distance is reported
as a surface distance. Areas and distances are binary64 calculations with tested
error bounds, not exact-arithmetic predicates or physical precision guarantees.

Classification returns -1 (outside), +1 (interior) or 0 (boundary/uncertainty band).
Planar tolerance is explicitly selected, default zero. Spherical classification
uses a 64-machine-epsilon angular band by default to report roundoff-level ambiguity;
zero requests raw chart predicates. This band does not change stored coordinates,
expand area, repair a mesh or choose a plate owner. All candidates are retained by
the index for subsequent shared-boundary/sidedness work.

### Coverage, persistence and acceptance

Coverage reports preserve gap/outside/overlap geometry and contact intersections.
A complete result means no gap/outside set and no positive-area pair overlap in the
selected domain. Pair overlap areas are NOT summed as a union when more than two
regions overlap. Spherical audits operate inside the domain chart; cross-patch
ownership/junction construction belongs to stage 3. No label implies ridge/subduction
physics, layer order, a geological history or compatibility with spherical W02.

WKB restoration validates two-dimensional type codes, byte order, nested part and
coordinate counts, payload length and configured limits before native parsing.
Identifiers and full descriptors are checked after reconstruction. Static definition
bytes use existing ArrayStore snapshots; derived GEOS/search state is rebuilt. This
is not a security boundary against a process capable of changing code and records.

The independent fixtures use rational planar areas, scalar ray crossing, an octant's
pi/2 solid angle, the spherical rectangle solid angle
`4 atan(a*b/sqrt(1+a*a+b*b))`, finite equatorial arc distances, poles, seams and rotated
copies. Other checks cover holes, contacts, empty/multipart results, invalid input,
source changes, native settings, index-vs-exhaustive equality, cancellation, memory
admission, concurrent reads, corruption and fresh-process/cold backup restoration.
A GEOS-vs-GEOS index comparison checks pruning, not independent correctness of GEOS.

Primary method references:
- Shapely 2.1.2 STRtree: https://shapely.readthedocs.io/en/2.1.2/strtree.html
- Double-precision overlay semantics: https://shapely.readthedocs.io/en/2.1.2/reference/shapely.intersection.html
- Prepared geometry: https://shapely.readthedocs.io/en/2.1.2/reference/shapely.prepare.html
- Spherical gnomonic scope: https://proj.org/en/stable/operations/projections/gnom.html


<a id="w01-boundaries"></a>

## W01 stage 3: static shared-boundary case

`cases/w01_boundaries.json` defines scope and the existing geometry tolerances.
The occupied area of an oriented outer ring lies to its left (counter-clockwise);
for a hole, clockwise traversal also leaves the occupied surrounding polygon on
the left. Reorienting ring traversal does not move or simplify any geometry.
Shared source edges are noded and stored only once. A neighbour uses that same
segment with opposite direction; it is not an independently reconstructed boundary.
Domain-exterior sides are `None` / -1, not an automatically generated material.

For a directed planar edge a→b, t=(b-a)/|b-a| and the right unit normal is
n_R=(t_y,-t_x). For a spherical minor arc with unit endpoints a,b, use the stable
left plane normal n_L=unit((a+b)×(b-a)); at unit position r on the arc,
t=unit(n_L×r), n_R=-n_L. Positive opening is (v_R-v_L)·n_R. Tangential relative
motion is (v_R-v_L)·t. Reversing the edge swaps both sides and negates t/n_R,
preserving the physical opening and tangential measures. Region-relative flux
uses opposite incidence signs on the same edge; this graph does not itself
advance a 2D/spherical material field or infer a physical fault slip law.

At every graph vertex, sort outgoing half-edges counter-clockwise. The region to
the left of ray k must equal the region to the right of the next ray. This checks
local sector closure without epsilon-offset ownership guesses. Point-only contacts
are preserved separately: they do not create positive-length adjacency or flux.
An ordinary corner is not a predicted tectonic junction. Same-plate patch joins
are labelled seams and excluded from default interplate motion diagnostics.

Frames are evaluated at a specified fraction along a segment; spherical fractions
are arc-length fractions. There is no averaged tangent at a corner/junction.
Lengths/positions use the explicit sphere radius in metres. Spherical radial
relative velocity is reported, not dropped to manufacture a valid 1D forcing.

A spherical network is constructed in its declared coherent, conditioned domain
chart. It does not automatically stitch a global atlas. Distinct input charts must
convert without unresolved native coverage/side inconsistencies. No new epsilon,
snapping, sliver deletion or geometry repair is used to obtain a successful build.
Unresolved joins must be supplied coherently or remain refused. This is the same
sphere/minor-arc approximation as the stage-2 primitives, not an ellipsoid model.

Native noding and oriented rings follow the official Shapely methods linked in the
[optimisation reference](OPTIMISATION_REFERENCE.md#w01-stage3-delivery). Independent
checks use rational rectangles, concave/hole partitions, exact graph counts and
perimeter-normal cancellation, known great-circle lengths, co-rotation and side
reversal. Indexed/exhaustive/native comparisons test implementation consistency,
not a second independent proof of the underlying geometry engine. Conservation
here concerns geometric incidence; geological validation remains a later gate.


<a id="w01-stage3b"></a>

## W01 stage 3B: closed spherical atlas contract

### Definition and integration

`SphericalPatch(patch_id, region_id, plate_id, vertex_ids, chart, holes=())`
uses an explicitly supplied global registry of directions in one `SphericalFrame`.
Outer rings keep their interiors to the left (counter-clockwise in the chart);
holes use clockwise rings. A vertex ID has a single authoritative direction.
Magnitude is not altitude. Arbitrary input directions are normalised on capture;
already-unit binary64 directions within the same 16-epsilon restoration contract
retain their bytes instead of drifting after repeated normalisation.

Every face is a valid simple polygon (optionally holed) within its conditioned
open-hemisphere chart. These local restrictions do not bound a grouped global
region or plate: multiple faces supply large, disconnected, holed or whole-sphere
owners. All edges are minor great-circle arcs. No hidden longitude seam exists.

`stitch_spherical_networks(networks, vertices, vertex_bindings, region_bindings=...)`
is the stage-3 adapter. A binding supplies each local vertex's global ID in the
network's existing vertex order; regional names can explicitly map across patches.
The adapter uses the stage-3 atomic edge index to recover ordered face rings, checks
side declarations and compares projected copies against the canonical registry.
The fixed attachment allowance is 64 binary64 epsilons in radians. It is solely
an explicitly recorded round-off check, not a distance-based vertex merger or
permission to move poorly matching geometry. Every supplied source network ID and
binding participates in provenance. Sources are never edited.

### Coverage proof obligations

Finite tests do not prove arbitrary floating-point correctness. The construction
nevertheless has a stronger structural acceptance rule than sampling a few points:

1. Each face is injective within its chart and has a positive oriented interior.
2. Each global edge has exactly two opposite uses from distinct faces; there is
   no exterior face or unpaired seam on a complete sphere.
3. At every vertex, outgoing tangent rays are sorted geometrically. The left
   owner of each ray must be the right owner of the next ray, exactly once around
   the vertex, with no repeated face corner or ambiguous coincident rays.
4. Face adjacency is connected. The Euler check is
   `V - E + sum(1 - number_of_holes_in_face) = 2`.
5. An independent signed spherical-area fan sum closes to `4*pi` steradians within
   `2e-11 sr`. Areas are never rescaled to force closure.

In exact geometry, (1)–(3) give a local homeomorphism of a compact connected
surface onto the sphere. A connected covering of the simply connected sphere is
one sheet. This is why the local link check matters: opposite edge pairing or the
area total alone would not rule out pinches/folds/multiple coverings. Conditions
(4)–(5) supply additional independent consistency checks. In this implementation
near-degenerate/unsupported cases are refused within the declared binary64 range.

Metrics use canonical unit endpoints, not projected distances. For an edge,
`theta = 2*atan2(norm(a-b), norm(a+b))`, `length = radius*theta`, and the stable
left normal comes from `cross(a+b, b-a)`. A local point at arc fraction f and its
right normal use these same endpoints. Plate/region area sums include their
faces; perimeters count only edges whose actual owner changes, excluding internal
patch subdivisions. Units are metres and square metres with explicit radius.

### Identity, queries, restoration and limits

`geometry_id` binds the exact canonical registry, rings and owner assignments;
working charts are excluded. `atlas_id` additionally binds charts, numerical
ambiguity policy and source attachments. A different tessellation has a different
representation identity even when it describes the same physical geography.
Canonical shared-edge IDs exclude working charts. No prior execution/checkpoint
hash is reinterpreted as a global-atlas identity.

Queries use native chord-distance cap pruning followed by stage-2 spherical
classification. A cap smaller than a hemisphere containing a face's vertices is
geodesically convex and contains its full face, also when that face is concave or
holed. Conservative outward padding affects candidates only. The numerical
boundary band returns every neighbouring owner; it is not an ownership overlap or
an excuse to select one arbitrarily. A zero-band raw predicate that cannot establish
coverage refuses rather than guessing the nearest region.

The index is explicitly opened/closed and reusable for bounded batches. Threaded
reads are tested; closing while a reader is active is refused. Source/restored
arrays have immutable byte backing with fresh metadata views. Index state is
reconstructed, never saved as executable/object-graph data. Missing/corrupt objects
block restoration and remain distinct from an absent disposable snapshot.

This is a static geometric capability. Global transport, plate evolution,
material budgets, thermal evolution and predictive forces are not obtained by
joining maps. W01 stages 4–8 and relevant later scientific packages remain.

### Independent references and checks

Octant and cube symmetry, a plate larger than a hemisphere, a whole-sphere plate,
a filled local hole, disconnected owners, arbitrary rotations, vertex/edge reversal,
chart changes, conforming refinements and independent sign-based memberships are
checked. Invalid gaps, duplicate faces, nonconforming seams, wrong bindings,
misoriented rings and bad ranges are refused. Existing stage-3 networks are stitched
and independently restored in a fresh process. Old fixtures/tolerances are unchanged.

Primary method references (no new dependency or copied third-party source):
- [S2 geometry interface and explicit polygon boundary models](https://s2geometry.io/devguide/s2shapeindex)
- [CGAL manifoldness and orientation requirements](https://doc.cgal.org/5.6.3/Polygon_mesh_processing/index.html)
- [SciPy native spatial ball-query API](https://docs.scipy.org/doc/scipy/reference/generated/scipy.spatial.cKDTree.query_ball_point.html)

S2 and CGAL are conceptual references, not installed/recreated engines. No S2
semantics are claimed automatically: Atlas deliberately returns all boundary
owners rather than assigning semi-open ownership to exactly one polygon.


<a id="w01-stage3c"></a>

## W01 stage 3C: generated initial spherical partitions

Case: `cases/w01_planetary_generation.json`. This adds initial geometry only.
Given unit sites s_i and a unit query q, angular nearest-site ownership maximises
q dot s_i because arccos decreases on [-1,1]. An interplate arc therefore lies on
q dot (s_i-s_j)=0. A convex-hull facet through three sites has one outward unit
normal: the shared Voronoi junction. Primal edges join adjacent facets and give
shared dual edges. Ring order is recovered from incidence, not angle sorting.

One site owns the sphere. Two distinct sites divide it by the plane normal to
s_0-s_1 into hemispheres. Three sites define two antipodal junctions and three
finite-semicircle boundaries; hemisphere-safe triangle patches represent the
resulting lunes. No antipodal endpoint is treated as a unique minor arc.

For >=4 sites, the current method requires a nondegenerate three-dimensional
hull strictly surrounding the origin. Numerically ambiguous cofacets, omitted
sites, near duplicates, non-spanning sites or ill-conditioned derived triangles
are refused. Generated candidates retry the entire site set within max_attempts;
authored site coordinates never retry or receive Qhull joggling. These conditions
change the accepted placement prior, especially for small plate counts. They are
not a general-purpose solution for every possible authored Voronoi diagram.
Previously supported stage-3B authored atlases remain unchanged and available.

The raw seed mapping is SHAKE256 with a named domain, unsigned 128-bit seed and
candidate index. Two little-endian 64-bit words per site yield two top-53-bit
uniform values: z=2U-1 and longitude=2*pi*V. Latitude itself is not sampled uniformly.
No global RNG, worker ID, task ordering, patch limit or machine clock enters the
stream. Resolved sites, attempts, settings, method, generator-source and native
runtime identities remain in the self-contained atlas provenance. Trigonometric
and native geometry rounding are not guaranteed bit-identical across platforms.

The default working layout uses one local cell patch when adequately conditioned;
otherwise triangles are formed by an interior fan. Explicit all-triangle layout
uses the same canonical boundary vertices and arcs. The prepared partition ID
excludes chart/layout choices; the atlas representation ID does not. Geographical
areas, adjacency, physical edge identities and point ownership must agree within
unchanged geometry tolerances across these representations. Pure patch seams do
not enter plate perimeters or acquire independent physical ownership.

The normal independent stage-3B closure tests remain enabled: every shared edge
has two opposite uses, junction links close once, adjacency is connected, Euler
characteristic is two, and area sums to 4*pi within the original 2e-11 sr bound.
Direct dot-product ownership and analytical symmetry/lune cases independently
check the generated partition, including poles, seams and low-count cases. There
is no rescaling of areas, snapping of vertices or fallback to a raster partition.

Primary method references: [SciPy's spherical Voronoi algorithm](https://docs.scipy.org/doc/scipy-1.17.0/reference/generated/scipy.spatial.SphericalVoronoi.html),
[public convex-hull facets/neighbours/equations](https://docs.scipy.org/doc/scipy-1.17.0/reference/generated/scipy.spatial.ConvexHull.html),
and [CPython SHAKE byte-stream interface](https://docs.python.org/3.13/library/hashlib.html#shake-variable-length-digests).
These are algorithm/API references, not observational calibration or imported
tectonic data. A valid partition does not establish a physically plausible history.


<a id="w01-geological-description"></a>

## W01 stage 4 — geological case, not sampled/evolved fields

`cases/w01_geological_description.json` fixes the new initial-description contract.
All values in tests/examples are synthetic. Shared material reference properties
are not calibrated constitutive laws. Provenance records distinguish authored,
generated, observation, literature, synthetic and explicitly unknown declarations.

Column layers are ordered from a named local surface down to the declared
lithosphere base. Sediment is part of the crust; lithospheric mantle is not. For
bulk layer thickness d and porosity phi, (1-phi)d is solid-equivalent thickness;
component weights describe fractions of that SOLID volume. None porosity cannot
be treated as phi=0. W02 common-density volume transport is not silently promoted
to a variable-density mass/energy solver by supplying density metadata here.

Layer fractions must sum to one within the newly declared 1e-12 absolute tolerance;
values are not renormalised. The complete layer stack must match declared
lithosphere thickness within 1e-12 relative tolerance. Resolvable ordered edges,
finite quantities and correct referenced material types are mandatory. These are
input consistency checks, not error limits for later physical integrations.

Initial thermal data can be unknown, constant, tabulated (linear, no extrapolation)
or the existing half-space initial condition. Half-space cooling-start time is in
the named case epoch and independent of cohort formation. Both dates must not lie
in the future; table coverage must reach the assigned column base. No temperature
profile is evaluated during description construction. W03 evolution is not present.

All candidate matches are retained in a precedence receipt. Highest-first supplied
province precedence chooses one complete column only for a point already known to
be in the domain. This is NOT a conservative mixed-cell sampling rule. Stage 5
must integrate the actual sub-cell arrangement rather than assign a whole cell to
its centre-point winner. Geometric ownership boundaries are not geological contacts
unless that association is explicitly declared.

Fault dip is measured down from horizontal toward the named side of the directed
trace. Faults and weak zones have declared depth ranges; no offset, slip, displaced
layer stack, thermal source, weakness multiplication or generated tectonic force is
inferred. Point/depth evaluation belongs to the remaining sampler and mechanisms.

Whole cases save through ArrayStore with their complete topology and geometry.
The compressed canonical byte definition participates in exact identity. Restoration
must rebuild/validate native geometry and the typed records, preserve unknowns and
return the same complete descriptor without referring to the original database.


<a id="w01-earth-materials"></a>

## W01 stage 4B — reference-material interpretation and integration

This is a property library, not spatial sampling, heat evolution, an equation of
state or geological acceptance. The complete factual register is maintained beside
its implementation in `src/atlas_tectonics/earth_material_data.py`; every property
names its source/table and original quantity. `cases/w01_earth_materials.json`
registers independent source anchors and interpretation tests. The library includes
material classes as well as mineral endmembers; it does not claim every entry is
chemically pure or taken from one consistently measured specimen.

### Units, conditions and provenance

Density is kg/m3; specific heat is J/(kg K); conductivity is W/(m K); volumetric
radiogenic heat is W/m3; volumetric expansion is 1/K. Original g/cm3, J/g/K,
kJ/kg/K and microW/m3 are retained and converted once into SI. Printed decimal
midpoints and SI scales are converted with decimal arithmetic before binary64
storage, avoiding needless double rounding. Run-time numerical arrays remain
binary64; no exact-arithmetic per-cell object engine is introduced.

Reported ranges are original literature/population spreads, not confidence
intervals. Where a source prints a central value plus/minus a quoted spread, the
record retains that locator and the corresponding illustrative envelope; it is
not reinterpreted as a guaranteed minimum/maximum or a fitted probability law. Independent marginal ranges do not form a known joint distribution.
`midpoint_of_reported_range` is an explicit Atlas default selection; a reported
central value is not replaced by a midpoint. Precise and nominal room-temperature
references are distinguished in source/condition notes. No pressure-qualified
range is supplied by this reference set. Source citations and hashes identify
records, not signatures or permission to claim every measurement was repeated.

In particular, Lee et al. Table 1 gives most heat capacities at 0 C, with named
exceptions; those do not become 20 C heat capacities. Table 5 expansion values
are means over 20–400 C. Huotari/Kukkonen Table 3's selected linear values cover
20–100 C; the factor of three is an explicitly isotropic approximation, not an
anisotropic expansion tensor. A secant interval is NOT a material-law validity
interval and is not exported as an instantaneous derivative.

### Mixture definitions

For scalar constituent reference densities rho_i and declared volume fractions v_i:

- rho_mix = sum(v_i rho_i).
- Cv_mix = sum(v_i rho_i cp_i).
- cp_mix = Cv_mix / rho_mix, NOT sum(v_i cp_i).
- A_mix = sum(v_i A_i) only if every nonzero constituent has a known A_i.
- Mass fractions convert by v_i = (w_i/rho_i) / sum(w_j/rho_j).

Pore volume replaces part of a GRAIN mixture: solid bulk fractions are
(1-phi)*v_i and fluid fraction is phi. Bulk-rock reference density/conductivity
already have an unresolved specimen pore basis; adding pores to them is refused.
Names such as sandstone do not tell the sampler that its density is a grain value.
Zero ADDED porosity around a bulk reference does not certify that its original
specimen had no pores. It is an effective bulk profile, not a grain/pore inventory
for compaction; that distinction must survive sampling and W03 input selection.
Fractions are checked, never silently renormalised to conceal inconsistent input.
The tiny allowed input sum roundoff is distinct from a deliberate composition edit.

For the assumed scalar constituents with perfect thermal contact, conductivity
bounds are [1/sum(v_i/k_i), sum(v_i k_i)]. Explicit ideal series/parallel geometry
selects an endpoint. Geometric mixing exp(sum(v_i log(k_i))) is a named approximation,
not an accuracy improvement or a universal law for air-filled/cracked/anisotropic
rocks. Bounds describe arrangement uncertainty under these assumptions, not the
full uncertainty in the individual published scalar conductivities. Material
anisotropy, reactive/excess volumes and phase changes require other physical laws.

For explicit elemental assays, the named Rybach reference gives:

A [W/m3] = rho [kg/m3] * 1e-11 *
          (9.52 * U [ppm] + 2.56 * Th [ppm] + 3.48 * K [weight percent]).

The assay is not K2O abundance, a decay-history calculation or a spatial abundance
prediction. A zero assay must be explicit; absence is not zero. The two shale
source-rate references distinguish aluminous and iron-rich populations, not one
universal heat source for all shale.

### Existing-case binding

`definitions()` returns immutable `MaterialDefinition` and `GeologySource` records;
its source ID binds the library, profile and reference coordinate. The source
statement retains basis, selected values and per-property conditions. Incompatible
values are omitted with a reason. Do not silently promote these records to a hot
or high-pressure profile because they fit the same Python schema.

`resolve_geological_layer()` checks the exact case definitions/evidence against
the selected library, combines quantities for property calculations only, and
preserves separate W02 cohorts. It rejects unknown pores, a second pore correction
and a differently bound library. It does not select a spatial province or change
a layer's thickness: those remain stage 5 and later physical responsibilities.

The seven matrix recipes carry authored composition assumptions and do not infer
soil texture, compaction, burial or water saturation. Unusual materials and
unsupported reference conditions fail preflight rather than inheriting a vaguely
similar rock. Future data additions receive a new library identity/version.



## Plate-layout reference correction (18 September 2026)

The rank-conditioned target is f_i = A_i / sum(A_j) for the selected largest N
PB2002 Table-1 areas. This is a declared starting prior, not a universal law or a
physical generation mechanism. Graph cuts assign existing shared spherical faces;
all owners are checked as connected. Error in the discrete target match is bounded
both globally and per plate, separately from unchanged geometric closure tolerances.

A simple spherical ring uses signed solid-angle triangles for area, great-circle
arc lengths for perimeter, and geodesic turn angles. Compactness is
A*(4*pi-A)/P^2 (A in steradians, P in radians), not the planar 4*pi*A/P^2.
The Cocos outline is retained without smoothing; direction reversal changes only
the reported winding, not the measures. Gauss–Bonnet and an exact octant provide
independent mathematical checks. Hemisphere conditioning is explicit in this
standalone simple-outline diagnostic, not a new limit on global atlas coverage.

Prescribed Euler motion is v = omega cross (R*x). Opening uses
(v_right-v_left) dot n_right; PB2002 right-lateral slip has the opposite sign to
our along-trace (v_right-v_left) dot tangent. Across an arc with midpoint m and
angle theta, the exact integrated normal velocity in solid-angle/time is
2*sin(theta/2) * ((omega cross m) dot n). Summing the outgoing contributions
around a rigid plate gives zero. This accounts for curvature without approximating
a long arc by midpoint velocity times length. It does NOT infer the velocity,
subduction polarity, nonrigid strain or force balance.

The source-specific motion comparison allows 0.2 mm/a because endpoints are
printed to 0.001 degrees and rates to 0.1 mm/a. It does not change the 2e-12
geometric comparison level or prior physics tolerances. The printed Cocos area
is tested to its independent 0.00001 sr resolution. Neither test claims that the
source's observational accuracy equals its printed numerical precision.


## 3C-R1 reference-data verification contract

`cases/plate_reference_r1.json` registers source files, raw Git identities, expected
counts, conventions, numerical/source error bounds, observation scales and evidence
roles before further generator tuning. Runtime code is in
`plate_reference_dataset.py` and `plate_reference_acceptance.py`; explicit source
preparation is in `tools/prepare_plate_reference.py`.

The closed-polygon area is computed independently by Gauss-Bonnet
`A = (2*pi - sum(turning)) mod 4*pi` and signed spherical triangle solid angles.
This presumes a simple oriented ring; reversal selects the spherical complement,
not a silent repair. Arc length is `atan2(|a cross b|, a dot b)` on unit directions;
physical length uses the explicit reference radius. A constant-area sum by itself
is not proof of correct surface coverage: separate edge-incidence and neighbour
checks are required. Source data are checked, never snapped or reclassified.

Per-step relative velocity uses `(omega_right - omega_left) cross position`.
Opening is its right-normal component; Bird's right-lateral scalar has the
opposite sign to its along-trace component. Full source-step signs and original
classifications are retained. Published rounding allowances are distinct from
solver error and from poorly quantified geological-model uncertainty.

Pure numerical regression and complete external-source acceptance are different
runs. The 18 September offline repair completed a full-source run, but its strict
consistency status is `REFERENCE_DISCREPANCIES_REQUIRE_REVIEW`: five edge-incidence
discrepancies, one stored area-table mismatch and one open orogen remain visible.
All earlier numerical tolerances and the registered evidence split are unchanged.

The verified source loader retains all raw coordinates. Exact adjacent repetitions
are omitted only in a derived numerical view with retained original indices; this
removes zero-length spans, not physical boundary detail. The generic strict parser
still rejects degenerate/open polygons. An open evidence polygon cannot acquire
area by an inferred final edge: Peru remains explicitly unmeasured while other
records continue. Source-preserving import never establishes simple-ring validity,
non-overlapping ownership or permissible use as Atlas simulation geometry.

Both area formulae agree within the existing numerical bounds for all 52 measured
plates, and all 5,819 motion rows satisfy the existing per-record rounding bounds.
These checks verify computation and source interpretation, not geological realism.
None accepts a generated planet or claims present-day poles specify past history.


## 3C-R1 reviewed source-use contract (18 September 2026)

The original numerical/source protocol above is unchanged. The separately pinned
`cases/plate_reference_use_policy.json` is a **post-audit** policy bound to the exact
PB2002 dataset and original protocol; it is not retrospective preregistration or a
numerical waiver. `plate_reference_use.py` supplies the qualified observation route.

A successful scoped assessment is distinct from raw strict consistency (still exit
1) and from geological model acceptance (always false here). Exact finding
fingerprints restrict the policy to the reviewed five incidence discrepancies,
one ON source/table disagreement and one open Peru polygon. Additional failures,
changed coverage or unreviewed inputs require another decision, not silent reuse.

Ordinary MS simple-ring metrics are excluded at every scale/phase; the original
signed-ring and multiscale diagnostics remain visible even where outside a simple
polygon's range. Coincident subsurface boundaries are not collapsed. The three
missing source connectors are not filled. ON's published and outline-derived
areas retain distinct identities; Peru remains an open trace. A complete derived
deformation mask and unique two-owner planetary mesh are not supported uses.

Qualified populations retain original calibration/holdout roles. Shape comparison
requires matched physical observation scales and sampling phases, and all excluded
or unresolved records remain in reported expected counts. Areas use A/(4*pi),
not renormalisation after quality screening. Counts cannot authenticate arbitrary
caller-supplied candidate provenance; they make incomplete candidate populations
explicit. Source numerical checks are not independent physical validation.

The scope is 51 eligible ordinary plate shapes before scale limits, 43 conservative
surface-neighbour counts, 12 closed orogens, 52 separately labelled areas and all
5,819 original step records. This supports the finite R1 reference-use work, not
R2 or any new thermal/mechanical evolution. Sources and decisions are referenced
in the two maintained plan/optimisation documents and executable policy; no extra
general planning page is introduced.
