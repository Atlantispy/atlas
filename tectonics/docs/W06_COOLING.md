# W06 Step 3 — ocean cooling and inherited passive margins

Status: **WORKING NON-CANON; scoped implementation and numerical checks pass**,
22 September 2026. The [Step 1 design](W06_SPREADING.md) remains frozen. This
increment extends [constant prescribed birth/spreading](W06_BIRTH.md); it does
not advance to Step 4 changing histories or Step 5 durable combined workflow.
See [checks and measured timings](../evidence/w06-cooling.md).

## Physical model and accounting

New oceanic material is born hot at its actual formation time. Its finite-plate
conduction problem retains fixed surface/base temperatures, constant conductivity
and volumetric heat capacity, no internal heating, and the declared finite depth.
Crust and mantle retain distinct reference densities, masses and thermal expansion
coefficients. They share conductivity and volumetric heat capacity in this model;
this is not a general heterogeneous thermal-layer solver.

Each cell uses the full continuous birth-age interval from Step 2, not cooling at
its mean age or distance from today's ridge. Phase temperature is integrated over
depth and age; centre values are separate point-age samples. Exactly zero age has
zero cumulative heat loss and no cooling anomaly: there is no artificial age floor.

Let `D_p = integral_p(T_b - T) dz`. The density sheet is
`sum(rho_p * alpha_p * D_p)` and downward subsidence is that sheet divided by
`rho_compensation - rho_water`. Water depth adds the declared axial depth. This
is the sole wet column-isostasy thermal owner; adding dry W05/W04 support to the
same anomaly would count it twice. Reference material masses do not change with
the Boussinesq density anomaly. Temperature/density/deflection validity is checked
on the oldest actual parcel as well as field means; a safe average cannot conceal
an invalid old column.

The regional heat account is
`resident enthalpy + left/right exported enthalpy + surface heat loss
- basal heat input - birth enthalpy = residual`.
Birth enthalpy uses the surface-temperature datum and is debited against a named
finite allowance. Basal heat has its own allowance. The relative closure gate
remains `1e-8`, with the tighter independent reference gate unchanged.

Exports retain heat and water **at boundary exit**, not after cooling outside the
represented region. For constant plate/ridge velocities, exit age is affine in
exit time; its interval can therefore be integrated directly. Constant ridge
migration is covered by this calculation. Changing velocity histories are not.
Heat exchanged before exit remains in the regional account. Explicit export
destinations, first/last exit offsets and first/last exit ages accompany each result.

Water draw includes resident and exported water volumes, including the water
needed above newly created axial-depth area. It is checked against a named finite
stock. These immutable states are candidate branches, not shared-reservoir commits;
durable transaction ownership belongs to the later workflow step.

## Inherited continental margins

`PreparedMarginCooling` accepts the actual W01 precursor or sampled initial state,
its named continental/transitional column, resolved piecewise-linear temperature
profile, source material definitions, reference geometry, source epoch and cooling
history. It evolves the supplied field from that epoch. Earlier cooling onset may
be unknown: no fictitious age is fitted, and the margin is never reset to newborn
oceanic temperature. A named thinning source is retained as provenance, not used
to invent a thinning solution. Resolved boundary temperatures must match the plate
model and the source column/layers must span the thermal depth.

The inherited temperature change, not absolute temperature relative to a newly
chosen hot profile, drives its sheet anomaly and displacement. Tiny changes are
retained separately from rounded absolute temperatures. Reference masses are
unchanged. The support owner and geometry/datum must match; water stock covers
the reference water volume as well as subsequent change.

Mixed hot/cold inherited profiles need not cool monotonically. An endpoint-only
water check would miss an earlier dry or overdrawn state. The heat-equation maximum
principle supplies conservative all-future temperature, displacement and water-depth
bounds. Requests are refused when these bounds cannot prove wetness, finite water
sufficiency and small deflection throughout the trajectory. This can conservatively
refuse a physically valid case; it does not assert that the case is impossible.

Unsupported profiles, unresolved body/field temperature offsets, porous/mixed source
layers and incompatible thermal properties are explicitly refused. This adapter
does not advect the continental column, manufacture missing rift history, or evolve
its source geometry. Those are not silently approximated by the ocean birth solver.

## API and ownership

The public package exports `OceanCoolingParameters`, `ThermalExport`,
`SpreadingThermalState`, `PreparedSpreadingCooling`, `spreading_thermal_means`,
`PreparedMarginCooling`, `MarginThermalResult` and `MarginSupportResult`.

`PreparedSpreadingCooling(spreading, parameters, budget=..., cancel=...)` reuses,
but does not own, the live `PreparedSpreading` plan/context. Use `.initial`, then
`.advance(state, time_s=...)`. Closing its parent invalidates the adapter. Requesting
the same endpoint validates source/state and returns the same immutable object,
without another debit. Returned-state retention remains the caller's resource duty.

For `P` phases, ocean `cell_values` and `centre_values` have `P+5` columns:
phase temperatures (K), density sheet (kg/m2), subsidence (m), water depth (m),
cumulative outward top heat (J/m2), cumulative outward base heat (J/m2).
Cell values are means over the occupied ocean portion; `ocean_fraction` supplies
its coverage. `centre_valid` identifies valid samples. Zero placeholders in empty
cells are not physical zero-kelvin values.

`heat_accounts_j` contains birth, birth remaining, basal input, basal remaining,
surface loss, resident enthalpy, left export, right export, residual, and normalised
residual. The last entry is **dimensionless**, despite the array's
unit suffix. `water_accounts_m3` contains draw, remaining, resident, left export,
right export and residual. Outward basal heat in field outputs is negative for
basal input; the account's basal-input channel is positive.

The margin API evaluates true depth-cell means and cumulative outward boundary
heat at a named time/epoch. `.support(...)` additionally returns inherited-relative
load/displacement, reference/current water, remaining stock and
`trajectory_depth_bounds_m`. Results retain their actual source objects and IDs.
No persistent result cache or restart interface is claimed in this step.

## Efficiency without changing the model

- Ocean age queries are batched and exactly deduplicated. Young ages use bounded
  image integrals and adaptive quadrature in square-root age; phase diffusion-scale
  cuts resolve very thin boundary layers. Mature ages use exponential interval
  antiderivatives with stable `expm1` arithmetic. Zero-area states bypass the kernel.
- Prepared margins reuse profile coefficients. Young evolution uses analytic image
  primitives; mature evolution uses decaying sine coefficients with explicit tails.
  There is no internal time-step history or cell-by-age-by-depth storage tensor.
- The existing source/context, cancellation, finite-stock and hierarchical byte
  budget protections remain active. Ocean execution retains the 256 request-interval
  ceiling. Margin limits include 4096 profile knots, 65536 cells, 256 modes, 16 images
  and 1,000,000 young image interactions. Failure to resolve within a cap refuses
  the request instead of weakening accuracy. Admission is not measured process RSS.
- Process parallelism and persistent caching are not added to these subsecond
  cases. Source-validated prepared reuse already removes worthwhile repeated work.

The [recorded benchmark](../evidence/w06-cooling-timing.json) compares identical
256-cell field/centre/account outputs with independent scalar quadrature: 0.3553722
to 0.0949111 seconds, saving 0.2604611 seconds / 73.29%. It is not a comparison to
an older production cooling adapter, which did not exist. Separately, the protected
4000-cell, four-output sequence including setup takes 0.5856365 seconds. Prepared
margin reuse reduces three-output elapsed time from 0.6438855 to 0.3106270 seconds
(51.76%). None is a whole-generator speed claim.

## Research and software actually checked

- [Richards et al. (2018), selected full-text modelling and heat/depth sections](https://freddrichards.github.io/documents/papers/richards_etal_2018_jgr.pdf):
  finite-plate cooling, water-loaded subsidence and the distinction between this
  constant-property control and more elaborate Earth-calibrated thermal models.
  No Earth calibration or paper implementation was imported/executed.
- [Official pyGPlates crustal-thickness/subsidence example](https://www.gplates.org/docs/pygplates/sample-code/pygplates_reconstruct_crustal_thickness_and_tectonic_subsidence):
  documentation and example code inspected for inherited scalar histories. Example
  defaults are not physical initial conditions and deactivated points do not replace
  this package's export account. pyGPlates was not executed.
- [MIT/Strang Fourier heat-equation derivation, selected pp. 12-13](https://math.mit.edu/~gs/cse/websections/cse41.pdf):
  steady-plus-transient sine evolution and the danger of unresolved young-time
  truncation. Production switches representation and bounds tails instead.
- [SciPy complementary-error-function documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.special.erfc.html):
  the image-solution primitive. Existing NumPy/SciPy dependencies were used, not
  upgraded; no new solver dependency. Atlas W02 accounts, W03 conduction/support
  and W06 birth code were read and reused through their guarded interfaces.

This is a physically based, independently numerically checked reduced model for
the stated regime. It is not empirical validation of a particular margin, realistic
whole-planet terrain, variable-history acceptance or completion of all W06.
