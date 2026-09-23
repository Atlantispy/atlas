# W06 step 1: spreading, oceanic birth and inherited margin histories

22 September 2026. **WORKING NON-CANON; design complete, implementation pending.**
This selects the first W06 equations, data contracts, bounded case and acceptance
criteria. It does not claim a completed spreading solver or empirical validation.
W05's accepted prescribed mechanism and existing W01/R4.4 holds are unchanged.

## Selected model and scope

Start with Mode K: prescribed, piecewise-constant plate/ridge velocities in a
strike-invariant planar section. A supplied ridge-onset event creates new oceanic
crust between separating sides, drawing from named **finite** feedstocks. Its
formation time and cooling-start time travel with the material. One-dimensional
finite-plate cooling drives one water-loaded local-isostatic response. The initial
case starts after a ridge has been declared; it does not predict continental
breakup, melt production, force balance or fault initiation.

The first support choice is local compensation, not elastic flexure. It is a
long-wavelength thermal-subsidence baseline. W05's dry flexural output is not added
to it, and an empirical age-depth curve is not another displacement term. A later
flexural option must replace the support owner, use compatible mapped loads and
state its rigidity/edge/young-ridge validity; it is not enabled by this design.

Use constant-property vertical conduction as the controlled first thermal model,
matching W03. It is not the variable-property oceanic model evaluated by Richards
et al. Nor is conductive heat loss at a ridge a model of hydrothermal circulation.
Thermal parameters and initial axial depth below are synthetic inputs, not fitted
Earth or Diadem defaults. Numerical controls include age zero; do not interpret
the immediate axial region as resolved ridge morphology or measured heat flow.

## Motion, birth and finite inventories

Use metres, seconds, kilograms, kelvin and a named forward-running epoch. Import
of geological Ma-before-present requires an explicit epoch/sign conversion.
Let ridge position be r(t), velocity v_r, left/right plate velocities u_L/u_R,
and bookkeeping strike width W. Relative outward spreading speeds are

```text
c_L = v_r - u_L; c_R = u_R - v_r
dA_L/dt = W*c_L; dA_R/dt = W*c_R
x_s(t; tau) = r(tau) + integral(tau..t, u_s(t')) dt'
formation_age = t - tau; cooling_age = t - cooling_start
```

An active ridge requires both c_L and c_R strictly positive. A declared inactive
welded boundary may have u_L=u_R=v_r and no birth; other degenerate, convergent or
incompatible cases refuse until explicitly supported. Full spreading is
u_R-u_L, not either half rate. Split exactly at a change of velocity, ridge
activity or ownership. Integrate affine trajectories analytically, not with
Euler steps or interpolation across a boundary. At a semantic event use the
old interval's half-open end and the new interval's beginning, with no duplicate
birth. A change of frame applied to all velocities, bounds and positions must
leave relative rates and inventories unchanged.

A birth interval [tau0,tau1] defines an ordered strip on each side. Its formation
time is affine in x while its subsequent side velocity is spatially uniform.
Integrate exact strip/cell intersections for area, phase volume and birth-time
moments. Preserve the full affine birth-time distribution, not just its mean.
The ridge has zero measure: no arbitrary offset, minimum age or finite-width
zero-age cell. Track source, plate, ridge, event, phase and thermal-model IDs.
For old supplied material, unknown formation/cooling history stays unknown; do
not invent an initial age from present ridge distance or a typical speed.

For each phase j with fixed reference density rho_j and injected thickness H_j:

```text
dM_j/dt = rho_j * H_j * W * (c_L + c_R)
feed_remaining_j = feed_initial_j - cumulative_created_j
represented_j + cumulative_export_j = initial_represented_j + cumulative_created_j
```

Both equalities must close in the existing scale-aware floating-point account
policy. Reference mass is not changed by a diagnostic thermal density anomaly.
Crust and underlying mantle have separate inventories. The finite thermal plate
depth is not an additional thickness of material created as the cooling front
deepens. Crustal feed is already prepared hot solid: no claim of a solved melting,
latent-heat, differentiation or magmatic emplacement process. Mantle feed is
distinct; do not charge the same supplied material to both reservoirs.
Here formation time denotes accretion into the represented oceanic column;
it does not invent a mineral crystallisation age for the supplied feed. The
feed's reference enthalpy follows its mass and specific heat. The separate
birth-enthalpy cap below is a transfer allowance, not a contradictory assertion
that all initially available hot stock has that total energy.

Validate interval demand against stock before committing movement, birth or
publication. Insufficient stock refuses the whole requested transaction without
clipping, thinner invented crust or silent reduction of spreading. A caller can
explicitly end at an exactly supported exhaustion time. Export carries its phase
mass and history to an identified destination; leaving a regional crop is not
subduction or destruction. The output crop never defines the source ledger.

## Cooling, water and one subsidence owner

For new oceanic material only, the selected onset event binds cooling_start=tau.
The hot initial interior, fixed surface/base temperatures and constant volumetric
heat capacity C=k/kappa are the existing W03 finite-plate problem on 0<=z<=L:

```text
dT/da = kappa*d2T/dz2
T(z,0)=Tb for z>0; T(0,a)=Ts; T(L,a)=Tb
T = Ts + (Tb-Ts) * [z/L + sum(n>=1,
     2*sin(n*pi*z/L)*exp(-n*n*pi*pi*kappa*a/(L*L))/(n*pi))]
```

Use W03's equivalent young-age image solution and bounded mature series, not a
fixed truncated Fourier series near birth. The two disjoint thermal phases are
crust [0,Hc] and mantle [Hc,L], sharing k and C in this controlled case. Their
specific heats are C/rho_j, so the thermal and material definitions agree.
No internal heating, changing boundary temperature or reheating is implicit.

Relative to the hot, same-composition oceanic reference at birth:

```text
Sigma(a) = sum_j rho_j*alpha_j * integral(phase_j, Tb - T(z,a)) dz
q(a) = g*Sigma(a)
s(a) = Sigma(a)/(rho_compensation-rho_water)       # positive downwards
seafloor_depth = axial_reference_depth + s
```

This layered diagnostic buoyancy is not additional conserved mass. Ocean depth
is relative to a fixed supplied sea-level datum, not a solved global sea level.
Use one `column-isostasy` owner. Water filling the additional deflection is
already represented in the restoring density contrast: record its inventory but
do not add its weight again as an independent load.

Use an explicit finite external water reservoir with pressure/level maintained
as a supplied boundary condition. Book water volume W*integral(depth dx) over
represented ocean and its exports. Adding newly opened area consumes the axial
water column as well as subsequent infill. No water is invented in masked
continental/exterior cells. Refuse exhaustion or an exposed/dry column outside
this wet-only case rather than silently switching restoring density. This is a
bounded open-ocean boundary model, not a closed ocean's level/volume solution.

Integrate T, Sigma and cumulative heat across each cell's actual age distribution
and occupied width; evaluating them at mean age is generally wrong. For young
intervals touching a=0, transform a=y^2 or use equivalent stable analytic
primitives. The square-root endpoint then has finite integrated quantities.
Instantaneous heat flux at birth is singular: do not return a fabricated finite
value. Request cumulative or finite-interval heat instead. Split integrals at
birth/history/material boundaries; test partial cells and near-coincident ages.

Thermal energy uses the same C and reference Ts. Births bring C*(Tb-Ts)*L per
unit area, debited from the supplied feed enthalpy. Separately book basal heat
input, surface heat loss and exported enthalpy. Over a represented interval,
energy change equals birth plus basal input minus surface loss and net export.
Thermal reference shifts cannot create energy. W03 top/base cumulative heat
supports this account, but moving-domain fluxes still need a W06 adapter.

## Passive margins and changing histories

Keep oceanic creation separate from continental thinning. Import a margin's
source-bound material, thinning, thermal field/history and reference geometry;
a continental cell is not converted to new ocean merely because a ridge moved.
Breakup must be an explicit event with complete geometry and material-transfer
accounts, not a guessed crust-thickness cutoff. The first newborn-ocean fixture
tests only the supplied onset side of this transition.

For an inherited nonuniform continental thermal field, retain it and evolve an
appropriate conduction problem. A single reset cooling age or the hot-ocean
initial condition is not a replacement. The exact age-only kernel is reusable
only when the imported history actually matches that family. This is the
Step 3 integration boundary, including explicit refusal of unsupported profiles.

Step 4 must cover asymmetric rates, a continuously migrating ridge, stopped
spreading and source-visible plate reassignment. Retain existing birth/cooling
identities when ownership changes. A ridge jump across existing crust cannot
create a second overlapping strip: require explicit partition/reassignment and
coverage accounts, or refuse it. No planar result is relabelled spherical; no
subduction, collision or mantle-flow physics is added through event bookkeeping.

## Frozen design case for steps 2-5

These are declared challenge inputs, not measured calibration. Implement the
executable case from this contract before assessing output; do not tune it after
seeing results. Only the first symmetric case is the initial implementation.

| Input | Selected value |
| --- | --- |
| Time and frame | Forward t0=0, named synthetic planar epoch; year=31,557,600 s |
| Active ridge | r(0)=0, v_r=0; u_L=-0.02 and u_R=+0.02 m/year |
| Duration and outputs | 20 Myr; outputs 0, 5, 10, 20 Myr; extra partial-cell control at 5.00625 Myr |
| Source window; crop | [-500,500] km; [-150,150] km; only born ocean intersections are valid |
| Initial ocean | Empty at t0; outside the growing ocean is unrepresented exterior, not zero-age ocean |
| Width; grid study | W=1 m (bookkeeping, not a finite-width solution); dx=1000,500,250 m |
| Layers and density | Hc=7,000 m, L=100,000 m; rho_c=2,900, rho_m=rho_compensation=3,300 kg/m3 |
| Thermal constants | Ts=273.15 K, Tb=1573.15 K; kappa=1e-6 m2/s, k=3.3 W/(m K), C=3.3e6 J/(m3 K) |
| Expansion/reference | alpha_c=alpha_m=2e-5 /K; EOS reference Tb; g=9.81 m/s2 |
| Water/reference | rho_water=1,030 kg/m3; supplied axial depth 2,600 m; fixed sea-level datum |
| Finite feeds | Crust 2e13 kg; mantle 3e14 kg; associated birth enthalpy capped at 4e20 J |
| Other reservoirs | Basal heat-input allowance 2e19 J; external water 7e9 m3 |
| Physical envelope | abs(alpha_j*(T-Tb))<=0.05; abs(s)/L<=0.05; all supported columns remain wet |
| Partition study | 32,64,128 requested intervals on dx=500 m; semantic event times split explicitly |
| Domain controls | Enlarge to [-600,600] km; separately clip to [-100,100] km to test actual exports |
| Thermal controls | Exact zero age; young half-space limit; 100/200 Myr finite-plate column controls without a 200 Myr spreading run |
| Resource envelope | Existing 256 interval ceiling retained; selected workload admitted under 128 MiB explicit work budget |

At 20 Myr, exact newly formed width is 800,000 m; crust mass is 1.624e13 kg and
mantle mass 2.4552e14 kg per the selected W. Feed enthalpy is 3.432e20 J. The
small-deflection envelope bounds all represented water by 6.08e9 m3. Basal influx
is bounded by the steady flux k*(Tb-Ts)/L times the age-area integral, giving
1.083056832e19 J. Thus the declared finite stocks cover the case without clipping.
Maximum Boussinesq anomaly is 0.026, within the selected 0.05 envelope.

For the symmetric case, a=abs(x)/0.02 years on the born footprint and 0<=a<=t.
Area per age interval is 2*W*0.02 metres per year of age. In the narrow export
window at 20 Myr, represented width is 200 km and exported width 600 km:
represented/exported crust mass is 4.06e12/1.218e13 kg. Preserve both accounts.
Direct scalar evaluation of the stated layered thermal equations gives point
subsidence at ages 1,5,10,20 Myr of 218.116170, 508.646061, 729.091665 and
1038.028468 m respectively. These are mathematical controls, not observations,
cell means or executed generator outputs.

History challenge for Step 4: after 10 Myr, set v_r=+0.005, u_L=-0.015 and
u_R=+0.035 m/year, keeping ridge position continuous. Relative rates are 0.020
and 0.030 m/year. At 20 Myr r=50 km and the oldest born edges are -350/+550 km;
total born width is 900 km and the base window exports 50 km on the right.
The pre-event strips keep their true ages, which a current-distance/current-rate
shortcut does not reproduce. A separate stop case sets all velocities to zero
at 10 Myr: no later birth, but age and cooling continue. Reject inconsistent
events; no arbitrary jump or reclassification is included in these cases.

## Independent acceptance and measurement plan

| Gate | Required result, not yet claimed |
| --- | --- |
| Geometry/history | Independent parcel paths and strip intersections; position <=1e-7 m error, age <=1 s error in this case; no gaps/overlaps, preserved full birth distributions and event lineage. |
| Material/source | Existing W02 scale-aware roundoff allowances, separately for crust/mantle and total; finite source debit equals creation; regional loss equals export. Test exhausted sources, zero area, partial cells and repeated requests. |
| Thermal/support | Independent adaptive integration of the scalar temperature reference over age and depth, split at discontinuities; mean T error <=1e-3 K, subsidence <=0.1 m, reference uncertainty <=1e-5 K/0.001 m. Test phases separately and together. |
| Heat/water | Close explicit moving-domain energy and water ledgers. Normalise thermal residual by max(birth enthalpy, initial represented enthalpy, sum absolute heat/advective exchanges); <=1e-8 relative, with exact zero-input control and independent quadrature uncertainty <=1e-10 on the same scale. No inventory clipping or double water loading. |
| Sampling/convergence | All occupied crop cells and centres at each requested output, true means compared with true means. Three grids; exact paths should be grid independent. Smooth sampled fields converge; no forced order at discontinuities. |
| Partitions/domain | 64/128 output partitions: surface difference <=0.01 m and age <=1 s; enlarged domain difference <=0.001 m on common crop. Clipped-domain inventories/exports must equal independent intersection results. |
| Scope/refusals | Relative velocities, epochs, positive density contrast, source stocks, thermal/envelope validity and unsupported ownership changes fail visibly. Unknown exterior is masked, not synthesised. |
| Workflow | Source-bound exact restart/cache parity, cancellation/atomic publication and budgets. Equivalent request partitions need physically equivalent histories, not necessarily identical checkpoint IDs. |

A scalar reference must not call the production strip integrator. Use separately
integrated birth trajectories, direct high-accuracy Fourier/image or boundary-value
temperature controls and independent age/depth quadrature. Reuse valid W03
component evidence; add tests for the new horizontal/history/source joins rather
than repeat the entire thermal or generator suite. Diagnostic age moments are
not sufficient to prove thermal means. A hypothetical temperature/depth plot is
not numerical or field acceptance.

Later empirical testing should bind independently reconstructed isochrons and
plate/ridge histories; thermal comparisons need independently corrected basement
depth and heat-flow observations. Do not fit the same depth profile for parameters
and then use it as an independent validation. Keep young hydrothermal, anomalous
crust, sediment loading and dynamic-topography effects explicit. No observational
dataset or universal empirical tolerance is supplied by this synthetic case.

## Existing interfaces and efficiency decisions

- Reuse W02 grids, phase inventory semantics, immutable identities and volume
  accounts. `MaterialCohort` stores one formation time and `CoolingHistory` one
  cooling onset: neither encodes a continuous birth strip. Keep W06 strip history
  authoritative; any W02 aggregate projection must retain that link and must not
  assert an invented instantaneous formation date. W02 event receipts are m2 per
  unit width; multiply by W and reference density for m3/kg. A reservoir ID alone
  is not a finite-stock account.
- Reuse `finite_plate_temperature`, `plate_cooling_heat` and the generic thermal
  response contracts. The whole-column `plate_thermal_response` assumes one
  material: the layered case requires phase-resolved integrals and one summed
  support response. `thermal_column_response` requires depth edges starting at
  zero: a phase-local translation must retain its physical coverage/provenance.
  Validate full endpoint temperatures and matched k/rho*cp, not just warm means.
- Do not force moving newborn crust through stationary, sediment-stack-specific
  `initialise_w03_columns` or `PreparedW04Support`. Do not disable W04's fixed
  thermal-coverage or reference guards. A new moving-history adapter is required.
- Use exact piecewise paths and ordered strip/cell sweeps: O(cells+intersections)
  per output after preparing the event history, not a dense cells-by-birth-times
  matrix. Split strips at physical events only; requested outputs do not create
  new physical cohorts. Merge only exactly equivalent adjacent history functions
  with shared provenance. Retain small source/exchange accounts and active state,
  not copies of every old field at every step.
- Batch independent age evaluations; integrate depth analytically where the
  existing kernel supports it. Use stable small-interval age integrals or bounded
  quadrature. This is a quality-preserving route, not age binning or an empirical
  lookup replacing physics. No universal timestep loop is needed for this family.
- Keep live work serial until a representative measure justifies bounded parallel
  output/parameter batches under the existing dispatcher. Do not parallelise shared
  reservoir debits. Reuse source-bound ArrayStore snapshots, Zstd and atomic
  publication; do not add another cache, compression system or unbounded history.
- After implementation, measure setup-inclusive cold/warm/restart and matched
  reference timings on the frozen case, with three local medians and numerical
  thread counts recorded. Report seconds and percentages including overhead;
  Step 1 makes no speedup or platform-execution claim.

## Papers and software actually checked

- [Karlsen et al., TracTec paper, author preprint](https://arxiv.org/html/1910.03351),
  methods 2.1-2.2 and limitations 3.3: historical ridge birth, plate-side identity
  and preprocessing separation inform this design. Its point-tracer seeding and
  deletion rules are not a conservative finite-mass prescription; we instead
  derive exact one-dimensional birth strips. Read selected full-text sections;
  TracTec was not executed or its implementation copied.
- [Richards et al. (2018), oceanic thermal structure](https://freddrichards.github.io/documents/papers/richards_etal_2018_jgr.pdf),
  introduction and modelling section 3: informs the distinction between a
  constant-property reference and more complete oceanic thermal physics, and the
  need for separate heat/depth evidence. No fitted parameters or solver code were
  imported. Selected full text read, not a reproduction of their calibration.
- [pyGPlates conjugate isochrons](https://www.gplates.org/docs/pygplates/sample-code/pygplates_create_conjugate_isochrons_from_ridge)
  and [crustal thickness/subsidence example](https://www.gplates.org/docs/pygplates/sample-code/pygplates_reconstruct_crustal_thickness_and_tectonic_subsidence):
  documentation/sample code checked for birth-time geometry, side IDs and time
  conventions. Reconstruction is not force balance or finite material closure.
- [GPlately 2.0 SeafloorGrid](https://gplates.github.io/gplately/v2.0.0/sphinx/html/generated/gplately.SeafloorGrid.html):
  API documentation checked for preparation/recovery structure and assumptions
  about initial ages and ridge symmetry. Do not transfer those defaults into an
  exact-age or asymmetric-spreading acceptance case. Neither package was run or
  added as a dependency; both remain relevant to a later spherical adapter.
- Existing Atlas W02 material events, W03 cooling/thermal integrals and W04 load
  contracts were inspected. Their restrictions above are integration requirements,
  not permission to weaken source, thermal or stationary-geometry guards.

## Completion and next increment

Step 1 provides the selected mechanism, equations, source/energy/water accounts,
history contracts, bounded synthetic case, independent criteria and efficiency
choices. It changes documentation only. Step 2 is conservative oceanic birth and
spreading with finite source debits and continuous history, before thermal/margin
coupling in Step 3, changing histories in Step 4 and combined workflow acceptance
in Step 5. No whole-world, held R4.4 or multi-day run is required by this design.

Step-1 checks: the required source-only checker passed 13 maps/41 paths; 30 safety
tests passed and one Windows symlink check was skipped (31 reported, 0.110 s).
Whitespace/diff and local design-link checks passed. Numerical figures above were
evaluated directly from the declared arithmetic/series, not from a new W06 runtime.
No generator regression, benchmark or external simulator was executed.
