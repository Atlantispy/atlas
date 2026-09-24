# W09 Step 1: water, erosion and source-to-sink design

23 September 2026. **WORKING NON-CANON. Design complete; implementation pending.**
The [frozen case register](../cases/w09_surface_processes_r1.json) binds this
design and independent numerical targets. No W09 solver or performance campaign
has run. Existing W01-W08 evidence, source identities and limits are unchanged.
This closes the initial C05 model choice, not its implementation acceptance.

## Implementation sequence

1. This model, interface, efficiency and reference-case selection.
2. Drainage and physical water: receivers, depression hierarchy, finite lakes,
   losses, spill/merge/split events and conservative geometry changes.
3. Material-aware bedrock/alluvium erosion and finite-supply hillslope transport.
4. Tagged sediment transport, deposition, stratigraphy, drained compaction and
   the explicit material/water/thermal/load consumer bridges below.
5. Joined bounded acceptance, source-bound reuse/restart and matched-error timing.

Each increment implements its applicable frozen controls before proceeding.
Independent geological profiles/stratigraphy and parameter calibration remain
the W10 challenge; exact arithmetic controls do not establish those observations.

## Selected physical model

Use SI: metres, seconds, kilograms, kelvin; planar x/y with z upward. Every
support has areas, connectivity, frame, datum, physical time and source identity.
Cell means and point values are distinct. Prescribed tectonic displacement,
effective dry-land runoff and lake precipitation are explicit inputs; do not
infer rainfall, erodibility or sediment supply from terrain appearance.

### Water: real storage, separate routing geometry

Select deterministic steepest-downhill single receivers on supplied connectors,
with stable cell-ID ties and explicit flat routing. Use Priority-Flood-derived
depression geometry and a nested spill hierarchy [S1-S4]. Artificial routing fill
never raises physical bed elevation or creates water. On non-lake reaches,
Q_i = r_i A_i + sum(Q_upstream), in m3/s. This is instantaneous routing, not a
channel-storage or flood-wave model. Lakes intercept inflow rather than passing
it through automatically; inundated cells have no fluvial incision in this route.

For a lake with physical bed z_i, store water volume, not just a flooded flag:

    V(h) = sum(A_i * max(h-z_i, 0))
    dV/dt = Qin + sum_wet(A_i * (p_i-e_i-f_i)) - Qout.

Runoff on dry land and direct precipitation on wet land have disjoint footprints.
Evaporation is atmospheric export; infiltration is transfer to a named finite
subsurface account. Supplied infiltration capacity is not a groundwater solver.
Select the ideal instantaneous sill outlet: V <= C=V(sill), Qout >= 0,
(C-V)*Qout=0. This is an explicit reduced outlet law, not a calibrated weir.
Closed boundaries have no invented ocean export.

Integrate to changes in forcing, wetted area, dry-out, spills, merging and
splitting. Fill connected children before merging; split at an exposed saddle
on drawdown and retain each child's physical water. Hierarchy metadata is not
additional stock. At zero storage, actual losses cannot exceed inflow: allocate
available water proportionally to simultaneous prescribed evaporation and
infiltration demands. No water and no input means zero actual losses. Large
geometry changes conservatively relocate old water before solving new levels;
unrepresented escape paths refuse rather than losing water.

### Rivers: separate rock and finite alluvium

Select a SPACE-family, cell-averaged erosion/settling closure [S5,S6]. Let H be
bulk alluvium thickness and Hstar a supplied positive roughness scale:

    omega_r = Kr * Q**m * S**n; omega_s = Ks * Q**m * S**n
    Er = max(omega_r-cr, 0) * exp(-H/Hstar)
    Es = max(omega_s-cs, 0) * (1-exp(-H/Hstar))
    Ds_k = ws_k * Qs_k / Q.

Er, Es and Ds are solid-volume rates per plan area, m/s; S is nonnegative
physical channel-bed slope, not filled-routing slope. Kr/Ks units are
m**(1-3*m) * s**(m-1); cr/cs are erosion-rate thresholds, m/s, NOT watts.
The first exponent pair is m=0.5, n=1. No area-for-discharge substitution or
unconverted library default is allowed. Effective settling speeds ws are m/s;
they are process parameters, not automatically still-water grain speeds.
This is an effective landscape-cell model, not a resolved channel cross-section.
Parameters require scenario provenance and resolution/forcing validation.

Initial supported mixtures carry multiple provenance cohorts but one erosion
law and settling class per active sediment layer. Source-defined rock layers
can differ in density and erodibility; the first erodible-rock route is nonporous.
Size sorting/armouring is not silently
invented by assigning unrelated rates to mixed labels. All eroded material stays
in tracked sediment stocks/fluxes: no automatic discarded fines fraction.
Erosion consumes exposed layers in order, stopping at layer/exhaustion events.
For fixed porosity, dH/dt=(Ds-Es)/(1-phi); generally recover bulk geometry from
grain mass, density and explicit pore volume. Neither bedrock nor soil is an
infinite source. Zero Q gives no river erosion or division by Q.

### Transport and deposition

Select quasi-steady dilute channel transport, with real transient lake sediment.
For a frozen interval and cell area A, the first finite-volume channel stencil is

    Qs_out = (Qs_in + A*(Es+Er)) / (1 + A*ws/Q)
    deposited_solid_volume = dt*A*ws*Qs_out/Q.

This Atlas stencil is a first-order well-mixed-cell discretisation, not the exact
SPACE reach solution. It conserves the same removed, passed and deposited
quantities. Separate tagged channels use their material density to convert solid
volume to kg. A coupled local implicit solve must use the same integrated erosion
in bed changes and exported flux; a frozen-rate shortcut is only a reference
control. Refine geometry/time for accuracy even when the stencil is stable.
Changing porosity never creates grains. Track input, bed, suspended and exported
mass for every tag; formation age and deposition time are separate attributes.

Lake class mass M obeys dM/dt=Min_dot-(Qout/V + ws*Awater/V)*M when well mixed.
Use an exponential update for constant coefficients; otherwise split at events
and refine. This selected lake closure assumes dilute suspension and negligible
resuspension. Evaporation and infiltration export no grains in the initial
perfect-retention closure; grains remain tracked in suspension or bed. At drying, deposit
remaining suspended mass. Deposition changes bathymetry and may displace water;
book that water and any overflow in the same candidate interval. Initial dilute
validity bound is total suspended solid volume/water volume <= 0.01; crossing it
requires a different model, not smaller tolerances or hidden clipping. If water
loss reaches that bound before dry-out, refuse the dependent continuation there;
the terminal dry-bed rule is not permission to cross a dense-suspension interval.

### Hillslopes without universal smoothing

Select the Roering nonlinear flux for mobile, soil-mantled material [S7]:

    q_bulk = -D * grad(z) / (1-(abs(grad(z))/Sc)**2).

D is m2/s, Sc dimensionless, q_bulk m2/s per contour width. Convert with donor
solid fraction and grain density before transferring finite tagged mass.
Use shared face fluxes and donor availability; do not erode bare rock with a
soil diffusion law. Weathering supply must be separately supplied and debited
from rock if enabled. Soil-covered slopes at/above Sc need an explicit failure
law and currently refuse; never flatten a rock cliff to this soil threshold.
Linear diffusion is only the low-slope verification limit, not a universal
mountain treatment. Face fluxes near Sc require bounded nonlinear iteration and
accuracy refinement, not a denominator clamp that changes the law.

## Efficient numerical design

Follow [the existing optimisation reference](OPTIMISATION_REFERENCE.md); no new
scheduler or general cache layer. Preparation stores contiguous arrays, one
receiver order and area-weighted hypsometry. Bind reuse to geometry, areas,
connectivity, boundary/sill/tie policies and implementation identity. Forcing
changes reuse geometry but recompute fluxes; terrain changes rebuild the bounded
graph. Re-evaluate lake occupancy after drawdown. Do not cache an old full-lake
shortcut as immutable geometry.

Use O(N) ordered accumulation/channel sweeps after preparation; generic
Priority-Flood preparation is O(N log N), not claimed linear for all inputs.
Use stable expm1/log1p near zero, bounded scalar implicit solves, and shared sparse
face operators for hillslopes. The fixed-receiver, bare-rock n=1 control uses a
downstream-to-upstream implicit stream-power sweep [S8,S9]; it is not an alternative
to the full finite-sediment model. Sediment feedback may require repeated sweeps;
no unconditional O(N) claim for the entire nonlinear coupled solve.

Keep accepted active state plus one candidate, immutable archived records and
existing ArrayStore checkpoint machinery. Reuse valid reference/control results.
Retain 128 MiB shared accounted work, one native thread and at most 256 cumulative
accepted subintervals. Reference meshes: 1D 8/16/32 cells, planar 4x4/8x8/16x16;
do not enlarge legacy native bounds. Start serial: these controls are tiny.
Later parallelism is for independent cases/regions with explicit boundaries.
No speed percentage is justified until matched-output/error measurements exist.

## Existing kernels and required consumer bridges

Reuse the actual contracts, not similarly named diagnostic fields:

| Existing Atlas component | W09 use and missing boundary |
| --- | --- |
| `materials.py`, `remapping.py` | Cohorts/events and conservative 1D overlap; inventories include per-width geometry, not automatically kg or 2D heat transport. |
| `compaction_columns.py`, `w03_workflow.py` | Grain volume, void ratio, stress memory, drained compaction and finite fluid exchange; ordered deposition/erosion insertion needs an adapter. Time labels drained equilibrium, not pressure diffusion. |
| `column_loads.py`, `w04_workflow.py` | Fixed-reference complete-column loads and stationary planar 1D support; current W03 adapter refuses moving columns/catalogue changes. |
| `w08_region.py`, `w08_inventory.py` | Finite component mass and signed enthalpy with origin labels; regional views are diagnostics, not material insertion or applied support. |
| `engineering/work/topography_r1/{kernels,transport}.py` | Retained finite-layer erosion, settling and heat/water transport are useful precedents; source-bound R31/native inputs and model-year units are not drop-in remake dependencies. |

Step 4 must implement a declared same-frame conservative placement from the
selected W08 parcels to the W09 support, including exterior stock. Preserve
formation labels while adding deposition intervals; carry signed enthalpy with
its reference and constitutive meaning. New sediment pore space draws water
from the finite shared account or remains explicitly unsaturated. The initial
drained saturated W03 bridge refuses insufficient supply; it must not fabricate
saturation or claim an unsaturated flow solver. Infiltration, compaction release,
lake storage, runoff and boundary supply share one water ledger.

Start feedback on a planar strip compatible with W04, with explicit strip width
and a complete fixed reference. General 2D support is not obtained by averaging
an arbitrary catchment to one line. Build one combined load from grains, pore
water, standing water, replacement medium and supported thermal effects. Choose
one structural response owner: W04 support OR compatible resolved mechanics;
do not also add W03 local support or W08's diagnostic load. W04 returns total
reference displacement: apply its change since last accepted state, not its full
value every interval. No duplicated thermal subsidence, magma heat or uplift.

At common physical times: place tectonic changes, evolve water/sediment, update
compaction and the chosen support, reconstruct geometry/routing, and test the
candidate. Iterate or reduce the macro interval for strong feedback; compare
refined and reversed split order. Any unsupported adapter or exhausted source
stops at its valid boundary. Commit material, heat, water, geometry, support and
consumed event IDs atomically. Recovery never repeats a booked transfer.

## Frozen acceptance and proportional verification

The register contains independently derived water/lake events, a discrete
stream-power control, shielding rates, finite-source exhaustion, a two-cell
tagged pulse, lake settling, nonlinear hillslope flux, sinusoidal diffusion and
porosity/load controls. Values are synthetic unit tests, not calibrated geology.
Distinguish exact discrete answers from continuum refinement targets.

For binary64 accounts require |residual| <= 128*epsilon*sum(abs(stocks and
booked transfers)); a zero scale requires exact zero. Existing stricter consumer
gates still apply. Never erase a material deficit by clipping or renormalising.
Analytic/discrete controls use 1e-10 relative plus 1e-12 in the stated SI output
unit. Continuum controls use 16/32/64 interval partitions and 8/16/32 spatial
cells, final relative L2 error <=1%, with errors decreasing by at least 1.5 per
refinement until below the analytic tolerance. Separate spatial and temporal
error and compare cell means to cell-mean references. Profile error is normalised
by the evolving perturbation, not a large constant elevation offset.

Joined gate: closed/open tagged-pulse conservation; dry and still-water limits;
receiver/saddle changes; grain/heat/porosity accounts; unique support ownership;
dt/dt2/dt4 coupling changes with final normalised difference <=1e-3 and reduction
>=1.5 unless already at analytic tolerance. Freeze the specific joined fixture,
normalising scales and geological parameter sources before its candidate run.
Include invalid geometry/units, depleted stock, wrong owners, cancellation and
checkpoint/restart identity. Exact frozen material and metadata bytes must agree
for pure cache/restart reuse. A cheap control failure blocks dependent work.

Timing belongs to each implemented increment: three rotated matched runs when
useful, cold setup and prepared execution separated; report seconds and percent
at unchanged physical accuracy. No full world, long campaign or plotting is
needed to complete this design. References below were read, not installed/run.

## Research and software checked

- **S1** [Barnes et al. (2014), Priority-Flood](https://richard.science/sci/2014_depressions.pdf),
  algorithm sections 3.2-3.3 and complexity section 4: deterministic depression preparation.
- **S2** [Barnes et al. (2021), Fill-Spill-Merge](https://esurf.copernicus.org/articles/9/105/2021/),
  sections 2.1, 3.1-3.3 and 4.3: hierarchy and lake-volume geometry; equilibrium
  snapshot is not transient hydraulics. Atlas adds the explicit event balance above.
- **S3** [Landlab LakeMapperBarnes](https://landlab.readthedocs.io/en/latest/generated/api/landlab.components.lake_fill.lake_fill_barnes.html),
  class/parameters and depth/volume properties: geometric fill is not water supply.
- **S4** [Landlab FlowAccumulator](https://landlab.readthedocs.io/en/latest/tutorials/flow_direction_and_accumulation/the_FlowAccumulator.html),
  initialisation/director/depression sections: routing and runoff accumulation.
- **S5** [Shobe, Tucker and Barnhart (2017), SPACE 1.0](https://gmd.copernicus.org/articles/10/4577/2017/gmd-10-4577-2017.pdf),
  sections 3.5, 4.1-4.4 and 5: cover, finite alluvium and erosion/deposition balance.
- **S6** [Landlab SpaceLargeScaleEroder](https://landlab.readthedocs.io/en/latest/generated/api/landlab.components.space.space_large_scale_eroder.html)
  and its linked source: conservative large-step design, input/porosity/settling
  interfaces and single-receiver restriction. Atlas uses explicitly SI thresholds
  and the declared sharp-threshold variant, not copied defaults/smoothed behaviour.
- **S7** [Roering, Kirchner and Dietrich (1999)](https://seismo.berkeley.edu/~kirchner/reprints/1999_29_Roering_nonlinear.pdf),
  equation 8 and its soil-mantled validity discussion: nonlinear hillslope transport.
- **S8** [FastScapeLib documentation](https://fastscape.org/fastscapelib-fortran/),
  governing model, API and algorithm references: prepared ordered implicit work.
- **S9** [Yuan et al. (2019)](https://agupubs.onlinelibrary.wiley.com/doi/10.1029/2018JF004867),
  section 2.2 and limitations: ordered implicit deposition; its untracked cover
  and grain-size limitations favour the explicit Atlas stocks selected here.

Badlands/goSPL remain references in the parent plan, not newly inspected or
executed comparators in this increment. No third-party implementation was copied.
