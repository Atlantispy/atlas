# Foundation case and numerical contract

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
