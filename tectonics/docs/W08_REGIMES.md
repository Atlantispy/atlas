# W08 Step 1: regional regimes and acceptance design

23 September 2026. **WORKING NON-CANON. Design complete; implementation pending.**
This selects physical and numerical contracts for W08, not a simulated landscape.
The companion [case register](../cases/w08_regimes.json) freezes this document's
identity and the first analytic fixtures before implementation. Existing W01-W07
cases, limits and evidence are unchanged. No W08 solver, benchmark or timing run
has been performed by this increment.

## Implementation sequence

W08 contains four different process families. Keep their acceptance independent;
use six increments rather than hide magmatism inside a final integration step.

1. This model/contract/reference design.
2. Finite-strain shortening, conservative material transport and a compatible
   load/support projection; prescribed underthrust/accretion geometry where supplied.
3. Transform and oblique histories: full horizontal motion, source-defined bends
   and stepovers, explicit local deformation and material exchanges.
4. Prescribed subduction with a computed wedge, interface/thermal transport,
   published reference comparison and conservative material retirement.
5. Finite-source magmatism: extraction, storage, intrusive/extrusive emplacement,
   heat, density and host-space accounting.
6. Joined regime transitions, complete source-bound restart/reuse, combined
   acceptance and matched-output performance evidence.

Step 2 starts with exact uniform shortening, not a new nonlinear regional solve.
Geological interpretations follow supplied scenario inputs; generic uplift is not
an alternative when the selected physical closure is unsupported.

## Prescribed inputs and computed outputs

| Route | Required supplied information | Computed result |
| --- | --- | --- |
| Shortening | Finite history, reference geometry, material properties; underthrust/fault geometry if used | Finite deformation, layer thicknesses, mass/heat transport, compatible loads and selected support |
| Transform/oblique | Both horizontal velocity components, moving boundaries, bend/stepover geometry, compatible regional strain/partition closure | Marker offsets, area change, local thickening/thinning and explicit exchanges |
| Subduction | Polarity, slab geometry/velocity, thermal state, coupling and rheology, trench/overriding history | Wedge velocity/pressure/temperature for the tested boundary-value problem; material flux accounts |
| Magmatism | Finite stocks, rates, compositions, thermodynamics, partitions and emplacement/host geometry | Reservoir evolution, mass/component/enthalpy balances, material volumes, deposited thickness and loads |

Positions alone do not choose subduction polarity. Plate convergence alone does
not select fault dip, strain localisation, magmatic productivity or eruption time.
These are explicit scenario closures until independently calibrated producers
supply them. A prescribed feature remains labelled prescribed after integration.

## Finite deformation and conservative geometry

Use metres, seconds, kilograms and kelvin internally. Plan view uses right-handed
Cartesian x/y and z up; vertical sections identify their azimuth, width and
out-of-plane assumption. Per-unit-strike quantities must be labelled kg/m, not kg.
Every product retains frame, datum, interval, material/cohort and source identity.

For a constant affine horizontal velocity segment, v(x) = L x + b, evolve

    [x(t+dt); 1] = exp(dt * [[L, b], [0, 0]]) [x(t); 1]
    Fdot = L F; J = det(F); A = J A0; H_i = H_i0 / J.

The last relation requires constant reference density, no material source/sink,
and column-compatible transport. With sources or density changes, reconstruct
H_i = M_i / (rho_i A) from the extensive account instead. Do not transport
thickness as a passive concentration. Distinguish conserved reference density
from a thermal buoyancy density used only in force/support calculations.

Use a small homogeneous matrix exponential (no inverse of potentially singular L)
or an equivalent proven closed form, prepared once per interval. Compose ordered
finite maps, splitting at actual history changes; do not add infinitesimal strains.
For diagnostics C = F^T F and E = (C-I)/2. A superposed rigid rotation leaves C
unchanged. A moving-coordinate velocity must include the frame motion correctly.

The first route uses non-overlapping material polygons or section intervals and
tagged layer inventories. Affine polygons retain exact straight edges. Integrate
physical overlap into receiving cells, carrying extensive component mass and
sensible/latent enthalpy, not centre-sampled thickness. Cache overlap geometry only
when the full source/target geometry is unchanged. Keep material beyond a finite
crop in named exports or retained exterior parcels; never renormalise it away.

### Shortening and structural response

For plane-strain shortening F = diag(lambda, 1), J = lambda and H = H0/lambda.
For example, 20% shortening of a 30 km incompressible column yields 37.5 km, not
36 km. This is geometric thickening, not a predicted surface elevation.

Subsequent prescribed underthrusting requires identified hanging/footwall blocks,
fault/ductile-interface geometry, detachment depth, motion compatibility, incoming
and receiving material destinations, and non-overlap/host-space checks. Conserved
layer geometry and boundary work must be accounted before calling it a structural
model. Mesh-scale strain concentrations are not an accepted localisation law.

W04 presently supplies stationary, planar 1D support, not automatic moving-polygon
coupling. Step 2 must explicitly construct fixed-reference load columns from the
new material footprints, including replacement/exterior material. Test their
integrals independently before handing total loads to W04. One response owner:
do not add local Airy uplift to a flexural or mechanical response representing the
same buoyancy. The existing no-in-plane-stress flexure operator is not a model of
compressional buckling. Foreland response is conditional on this load/support
approximation, not a self-generated fold-and-thrust belt.

### Transform, pure shear and obliquity

Pure horizontal shear F = diag(exp(a), exp(-a)) and simple shear
F = [[1, gamma], [0, 1]] both have J=1: shape changes without automatic thickening.
Solid translation/rotation must preserve volume, thickness and strain invariants.
Area-changing oblique histories use their actual J, not total speed or accumulated
slip as a proxy for compression. The order of shear and shortening matters.

Prescribed bends/stepovers require compatible boundary segments, full vector
relative velocities and an explicit interior deformation/material-partition map.
Rigid pieces may slip on a named interface; gaps/overlaps need a physical creation,
transfer or accretion rule, not smoothing. Verify junction closure and fluxes at
each event. Existing vertical plane-strain mechanics must not silently discard
along-strike motion; the first transform route is horizontal kinematic transport.
An earthquake-cycle elastic displacement is not accumulated as geological plastic
deformation. Mechanically predicted localisation needs its own constitutive and
physical-length evidence.

## C03/C04: recycling and regime transitions

For each crust/mantle layer separately, integrate the moving-boundary flux

    q_out = integral_Gamma rho H (v_material - v_boundary).n_out ds.

Use the local section's declared width, signed normal and physical area measure.
Track incoming material, accreted material, eroded overriding material, slab/deep
storage and external exports in distinct nodes. An oceanic parcel crossing a
trench changes reservoir/ownership; it does not disappear from the account.
Birth similarly debits a supplied finite donor and records age, phase and heat.

Each dated history event includes a stable ID, old/new regime, continuous boundary
geometry or a separately explained jump, polarity/coupling/kinematics, material
destinations, transfer fractions and thermal provenance. Fractions are finite,
nonnegative and sum to one for each classified source flux. Trench migration uses
boundary-relative motion, not a second material velocity. Distinguish oceanic
subduction, continental entry, accretion/erosion, underthrusting and cessation.
Rollback/back-arc cases need explicit histories and their own tests; never infer
them just from an inward velocity. Cessation does not empty an existing reservoir.

Split intervals at source changes, interface crossings and stock exhaustion.
Compute competing demands simultaneously. Sequential min(stock, q*dt) per outlet
is rejected: it changes allocations with edge order. With prescribed rates, find
the first time a finite stock/component becomes infeasible. End the valid interval
there and refuse unsupported continuation; continued supply-limited operation
requires a declared allocation/thermodynamic policy. Exactly empty, instantaneous
pass-through reservoirs need a separate composition/enthalpy rule or refusal.

## Subduction: selected benchmark and required bridge

The first physical reference is van Keken et al. (2008): prescribed slab motion,
stationary overriding plate and mechanically driven wedge, followed by thermal
advection/diffusion. It is a local boundary-value problem. Do not start by evolving
a freely sinking slab or attempting a whole mantle history.

W07 already has open thermal boundaries and uniform translating-grid transport.
Its tagged rectangular materials still require uniform physical motion; the
body-fitted surface branch is homogeneous/isothermal with fixed horizontal mesh
geometry. Consequently, an oblique slab interface and deforming heterogeneous
heat/material transport are **new Step 4 bridges**, not existing W07 capabilities.

Use an interface-aligned mesh or rigorously conservative cut-interface treatment;
do not smear prescribed slab velocity into the wedge or across the stationary
plate. Retain one-sided velocity traces, correct coupling depth and heat-flux
continuity. Compare bounded candidates at the same continuum error before choosing
the final backend. The retained MAC and Q2 reference methods are starting points,
not evidence that either already supports the new interface.

Solve the stationary heat-advection/diffusion reference directly where appropriate,
with conservative fluxes and tested stabilisation. Do not integrate 50-100 Myr
merely to approach a steady benchmark. Use analytic corner flow first, then
computed isoviscous wedge flow, then temperature-dependent/diffusion-dislocation
rheologies. Independently verify interface temperature, wedge RMS temperature,
pressure/velocity, boundary flux/heat residuals and spatial convergence. A steady
residual alone is not thermal accuracy or valid heterogeneous material transport.

The detailed published cases and numerical comparison requirements are recorded
below. A matched published geometry/reference is necessary; ASPECT's illustrative
recreation is not itself a numerically confirmed independent reference result.

### Published subduction specification and remaining source binding

The author-hosted van Keken paper was read, including visual checks of equations,
Fig. 1 and Tables 1-3 (journal pages 188-194). Original contributed temperature
arrays were not acquired. The following transcription fixes the reference family;
it is not a claim that all benchmark-adapter details are already resolved.

- Domain 660 km wide by 600 km deep; source coordinates x right, y down. Atlas
  must explicitly transform y to its z-up convention, including velocity signs.
- Straight 45-degree slab, 5 cm/year; stationary overriding lid 50 km thick.
  rho=3300 kg/m3, cp=1250 J/(kg K), k=3 W/(m K); no body buoyancy or heat source.
  Steady incompressible Stokes and steady advective-diffusive heat equations.
- Surface/incoming mantle temperatures 273/1573 K. Left slab inflow is
  273 + 1300*erf(y/(2*sqrt(kappa*t50))), kappa=k/(rho*cp), t50=50 Myr.
  The overriding-plate right boundary has a linear geotherm; inflowing wedge
  material is 1573 K. Convert age and velocity with one labelled convention:
  this Atlas fixture uses 31,557,600 seconds/year. The paper does not specify
  that conversion, so this is an implementation convention, not a quoted constant.
- Cases 1a/1b use analytical corner-flow boundary data, with respectively
  prescribed flow/computed isoviscous flow. Case 1c replaces the far-field
  mechanical condition with zero traction. Cases 2a/2b use case 1c boundaries
  with diffusion/dislocation creep. Initial eta0=1e21 Pa s; eta_max=1e26 Pa s.
- With T in kelvin, R=8.3145 J/(mol K):
  eta_diff=1.32043e9*exp(335000/(R*T));
  eta_disl=28968.6*exp(540000/(3.5*R*T))*epsII^((1-3.5)/3.5).
  epsII=sqrt(0.5*sum_ij(D_ij^2)), D=sym(grad(v)); coefficients carry the
  corresponding SI units. Effective viscosity is the harmonic cap
  (1/eta + 1/eta_max)^(-1), not a hard minimum. At zero strain use its finite
  limiting value; do not silently add a different strain-rate regularisation.
  The initial benchmark variant has no optional wedge coupling ramp.

At points (6i km, 6j km), diagnostics are T(60 km,60 km),
sqrt(sum(i=1..36,T_ii^2)/36), and
sqrt(sum(i=10..21,j=10..i,T_ij^2)/78). **Convert each sampled temperature to the
paper's nominal Celsius convention (theta=T-273 for these specified boundaries)
before squaring**; RMS(K)-273 is not RMS(theta).
Bind the exact point interpolation/one-sided trace at interfaces as well.

| Published PGC row | Point, Celsius | Slab RMS, Celsius | Wedge RMS, Celsius |
| --- | ---: | ---: | ---: |
| 1a | 388.21 | 503.69 | 854.34 |
| 1b | 388.21 | 503.69 | 854.34 |
| 1c | 387.78 | 503.10 | 852.97 |
| 2a | 580.52 | 606.94 | 1002.85 |
| 2b | 582.65 | 604.51 | 998.71 |

These are named reference results, not tolerances or universal geological truth.
For a source-matched adapter, the initial engineering target is absolute error
at most 2 Celsius degrees in each diagnostic and at most 1 degree change between
the finest two of three admitted refinements; retain residual/flux checks as
separate gates. Targets are chosen here before running, not attributed to the
paper. Report errors as well as pass/fail; never retune physics to match a row.

Two source-adapter details must be resolved **before Step 4 benchmark execution**:
the paper references Batchelor (1967) without printing the 45-degree corner-flow
formula, and calls the thermal outflow condition "zero curvature" without an
explicit derivative/flux operator. Obtain an original reference implementation
or independently establish its intended weak/strong condition. Do not import a
90-degree formula or silently replace that boundary with zero diffusive flux.
Record the final operator, formula, units and source/derivation in a new adapter
binding before comparison. Until then source-exact published acceptance remains
BLOCKED_SOURCE_ADAPTER, though the numerical target and reference rows are frozen.

A 64x64 full-domain grid has roughly 10.3x9.4 km cells, not the published fine
interface/boundary-layer representation. Establish interface-aligned/adaptive
representation and bounded admission before claiming convergence. This design
does not enlarge W07 mesh limits or assume the target fits the present backend.
The analytic shortening/transform work does not depend on that unresolved bridge.

## C06: finite-source magmatism

Select a reduced **prescribed-transfer** model: source solid, source melt,
well-mixed reservoirs, intrusive material, extrusive material and external exports.
This is a transparent conservation closure, not dynamic melt migration or an
eruption predictor. An equilibrium melt fraction can constrain a thermodynamic
state; it cannot supply extraction velocity, a rate or a pathway.

For each node i and chemical/material component k, store mass M_i, component mass
C_ik and enthalpy E_i, not only normalised fractions and temperature:

    dM_i/dt = sum(q_ji) - sum(q_ij)
    dC_ik/dt = sum(q_ji*c_jk) - sum(q_ij*c_ik)
    dE_i/dt = sum(q_ji*h_j) - sum(q_ij*h_i) + Q_i.

Transfers use the donor's evolving composition/enthalpy. Integrate balances
together for mixed recharge; an endpoint temperature times a total transferred
mass is generally wrong. Constant-rate, fixed-mass mixing admits an exact
exponential solution and is the first independent thermal oracle. More general
supported trajectories require positivity-preserving integration and convergence.

Initial thermodynamics are explicitly isobaric with supplied constant heat
capacities, latent heats and a declared phase rule:
h = cp*(T-T_ref) + L*f_liquid. Solid-to-melt conversion must pay its heat cost;
extraction does not melt the same material a second time. Phase fractions must
come from the supplied admissible thermodynamic state, not independent arbitrary
T/f choices. Track latent heat once during subsequent crystallisation/cooling.
Pressure-volume work, gravitational/mechanical energy and pressure-dependent EOS
need a responsible coupled component before a total-energy claim; this first
contract closes the declared thermal/enthalpy system.

The first phase-change control uses a single supplied melting temperature Tm:
below its solidus enthalpy f=0; between cp*(Tm-T_ref) and that value plus L,
T=Tm and f follows the enthalpy linearly; above it f=1. Use Tm=350 K for the
synthetic 400-to-300 K control, not as a rock property. Multicomponent melting
curves need their own supplied thermodynamic closure. The unequal-cp mixing
control is single-phase with no latent heat.

Use receiving density for volume V=M/rho; retain mass when density changes.
Nonnegative supplied spatial mass weights w_j, summing to one, give deposited
thickness dz_j = M_erupted*w_j/(rho_j*A_j). They prescribe a footprint, not a
predicted cone. Intrusion must specify underplating, host displacement or explicit
replacement with an outgoing host account; do not add material into full space.
Book each physical mass/load/heat contribution once across W03/W04/W07. A change
in density or placement changes the corresponding load/geometry source identity.

No universal intrusion/eruption ratio, productivity, residence time or edifice
aspect ratio is selected here. Scenario calibration and validity ranges travel
with those inputs. Optional caldera/hotspot models remain separate mechanisms.

## Frozen analytic cases and acceptance

The register contains synthetic values in SI, not geological calibration. Its
analytic expectations are independent of the future implementation.

- A01: 20% and 50% finite shortening; thickness/area/mass and interval invariance.
- A02: pure/simple shear, rigid translation/rotation and non-commuting histories.
- A03: boundary-relative flux, tangential zero flux and common-frame translation.
- A04: finite throughflow, competing outlets and exact exhaustion/cessation times.
- A05: continuous reservoir mixing, unequal heat capacities and latent heat.
- A06: density/volume, receiving-area deposition and explicit host replacement.
- A07: prescribed interface exchange and cross-regime restart, with all inventories
  and source identities retained; wrong/missing histories must refuse.

Binary64 exact-map/control comparisons use a declared nonzero physical scale and
at most 1e-10 normalised error. Extensive-account residuals use compensated sums
and at most 128*epsilon times the sum of absolute initial/final stocks and all
booked flux magnitudes (zero scale requires exact zero). Existing stricter consumer
gates still apply. This is not a universal geological observable tolerance.
Use 8/16/32 cells or parcels for overlap/refinement controls and 1/2/4 interval
partitions across the same events. Piecewise-affine constant-property exact cases
must be partition-invariant within the declared roundoff bound. Discontinuous
fronts use integral/position errors, not an asserted smooth convergence order.

Before their respective increments, define bounded physical challenges in addition
to analytic bookkeeping: shortening/foreland geometry and loads; bend/stepover
distributed strain; the published subduction thermal diagnostics; and calibrated
intrusive/extrusive thermal-volume cases. Analytic control success does not replace
these challenges. Any new reference fixture, geometry or tolerance receives a
new recorded identity before a candidate is run, never a retrospective repin.

## Efficiency, resources and recovery

- Prefer exact finite maps/event integration; prepare each segment once. Reuse
  W03's analytic thermal profiles where assumptions match, not for general flow.
- Conservative overlap is prepared geometry, not repeated point sampling. Preserve
  tagged extensive state and event segments; do not copy whole historical grids at
  each evaluation. Reuse existing immutable ArrayStore/checkpoint machinery.
- For subduction, compare matched-error direct steady thermal solves and reusable
  interface/operator setup. Temperature-dependent coefficients invalidate numerical
  factors; only unchanged geometry/sparsity can remain reusable in that case.
- Parallelise independent cases/regions only when cost justifies worker setup;
  ordered shared-material histories remain ordered. Charge parent and worker
  storage to the same budget; no parallelism to evade resource admission.
- Keep one native numerical thread, the 128 MiB accounted-work budget and the
  256 accepted-interval ceiling. Existing mesh/primitive bounds still apply;
  extending a solver's supported representation needs an explicit tested successor,
  not an enlarged constant. Accounted memory is not a measured RSS ceiling.
- The last source inventory has 2,097,129 bytes against the existing 2 MiB source
  capture cap (23 bytes headroom). **Before Step 2 adds production source**, make
  the smallest reviewed bounded source-inventory representation improvement,
  preserving complete code identity and old checkpoint refusal. Do not raise the
  cap, omit files, strip scientific history or repin old evidence as a shortcut.
- Future timing compares the same outputs at accepted error: cold preparation +
  execution + final materialisation, prepared reuse, first checkpoint write,
  verified restore and interrupted continuation separately. Three rotated repeats
  suffice initially; report median seconds and percentages, including slower paths.
  No W08 speed-up is claimed before those measurements.
- Step 6 must restore geometry, reference state, material/component/enthalpy
  stocks, exhausted sources, event cursor, physical owners and source/runtime
  bindings without replaying completed transfers. Atomic publication and corrupt,
  stale-source and mid-event restart refusal are required.

## Sources checked and design influence

No external software was installed or executed. Access descriptions distinguish
method review from execution and from complete-paper review.

- [GPlates/pyGPlates StrainRate documentation](https://www.gplates.org/docs/pygplates/generated/pygplates.StrainRate.html):
  method definitions read. Informed finite-deformation/objectivity checks and the
  separation of areal strain from shear. Its spherical metric is not copied into
  a Cartesian section.
- [Muller et al. (2018), GPlates: Building a Virtual Earth Through Deep Time](https://doi.org/10.1029/2018GC007584):
  indexed full-text Section 12 excerpts read, not the whole paper. Informed
  prescribed deforming-network history. Atlas additionally requires a material
  reservoir account for every disappearing point/cohort.
- [van Keken et al. (2008)](https://sites.ualberta.ca/~ccurrie1/papers/vanKekenEtAl_PEPI_2008.pdf):
  benchmark paper reviewed for the prescribed-slab/computed-wedge comparison;
  exact case definitions and reference extraction are described below.
- [ASPECT subduction cookbook source](https://raw.githubusercontent.com/geodynamics/aspect/main/cookbooks/vankeken_subduction/doc/vankeken_subduction.md):
  implementation description read. Informed interface-aligned geometry and explicit
  treatment of velocity discontinuities; its illustrative thermal run is not an
accepted benchmark oracle.
- [ASPECT melt transport methods](https://aspect-documentation.readthedocs.io/en/stable/user/methods/melt-transport.html):
  method section read; phase state, production and relative transport are distinct.
- [alphaMELTS manual](https://magmasource.caltech.edu/alphamelts/1/alphamelts_manual.pdf):
  output/extraction definitions, PDF pages 26 and 44-45 read. Melt mass/volume
  fractions and extraction controls do not define eruption rates.
- [Keller and Suckale (2019)](https://doi.org/10.1093/gji/ggz287):
  full-text conservation, thermal and closure sections read; informed separate
  phase/component/energy transfers and explicit empirical closures.
- [Spera and Bohrson (2002)](https://magma.geol.ucsb.edu/papers/2002_Gcubed_ref.pdf):
  author-hosted systems/mass/enthalpy sections read. Informed finite coupled
  reservoirs without pretending the conservation model supplies magma dynamics.

Existing Atlas W01/W02 material contracts, W03 thermal/compaction, W04 support,
W06 oceanic histories and W07 mechanical/thermal/surface route definitions were
checked for the named integration boundaries. No existing paper/case or accepted
reference was replaced by this design.
