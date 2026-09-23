# W03 increment 1: finite-plate cooling and thermal-age columns

22 September 2026. Implemented locally, WORKING NON-CANON. This completes the
selected **constant-property thermal-column increment**, not all W03, empirical
Earth/Diadem calibration, evolved topography or mature R4.4 acceptance.

## Model and scientific basis

Solve `dT/dt = kappa d2T/dz2` on `0 <= z <= L`, positive depth downward, with
constant prescribed surface `Ts` and basal `Tb >= Ts`. Initially the interior is
at `Tb`; the surface point is `Ts`. Age zero is the explicit discontinuous ridge
initial condition, not a minimum-age approximation. Conductivity `k` and
diffusivity `kappa` imply the same constant volumetric heat capacity `C=k/kappa`.
All arguments use metres, seconds, kelvin, W/(m K) and J/m2. `Tb` is the actual
plate-base temperature, **not mantle potential temperature**.

References reviewed for this choice:

- [Parsons & Sclater (1977)](https://doi.org/10.1029/JB082i005p00803): the accessible
  abstract supports the young half-space limit and old-age finite-plate behaviour;
  full derivation was not accessible during this review.
- [Stein & Stein (1992)](https://www.nature.com/articles/359123a0): the accessible
  abstract describes joint depth/heat-flow calibration. No fitted Earth thickness,
  basal temperature, or age-depth curve is silently imported into Atlas.
- [Holdt, White & Richards (2025)](https://doi.org/10.1029/2024JB029890), equations
  2-4: one-dimensional constant-property cooling is a restricted model, distinct
  from their variable-property calibrated models. The reviewed equations and
  model distinctions support this formulation, not observational acceptance of
  our supplied parameters. [Author supplement](https://zenodo.org/records/14691107).
- [ASPECT v3.1.0 implementation](https://raw.githubusercontent.com/geodynamics/aspect/v3.1.0/source/initial_temperature/adiabatic.cc)
  corroborates the finite-plate eigenfunction solution. Its ten-term truncation
  does not provide arbitrary-young-age accuracy. GPL-2.0-or-later.
- [Geodynamic World Builder v1.0.0 implementation](https://raw.githubusercontent.com/GeodynamicWorldBuilder/WorldBuilder/v1.0.0/source/world_builder/features/oceanic_plate_models/temperature/plate_model.cc)
  includes horizontal conduction and a 100-term expansion, so it is not a
  like-for-like 1-D oracle. LGPL-2.0-or-later.

Atlas implements independently derived mathematics, **not copied upstream code**.
No new dependency was added. The scalar series, independent quadrature and small
finite-volume matrix in the tests are numerical oracles; we did not execute
ASPECT/GWB or claim their runtimes or calibration results as ours.

## Stable direct-age algorithm

With `x=z/L`, `Fo=kappa*t/L^2`, `theta=(T-Ts)/(Tb-Ts)`:

```text
theta = x + sum(n>=1) 2 sin(n*pi*x) exp(-n^2*pi^2*Fo)/(n*pi)
```

For `Fo > 1/16`, nine modes suffice: the omitted temperature tail is bounded by
`[2/(10*pi)] exp(-100*pi^2*Fo) / [1-exp(-21*pi^2*Fo)]`, below `2e-28` at the
switch. This is an accuracy-derived execution choice, not a fitted physical age.
For younger positive ages use the equivalent image solution:

```text
theta = erf(x/(2*sqrt(Fo)))
        + sum(m>=1) [erfc((2*m-x)/(2*sqrt(Fo)))
                     - erfc((2*m+x)/(2*sqrt(Fo)))]
```

Retaining image pairs `m=1,2` leaves a tail below `3e-45` in this branch. Endpoints
are imposed exactly. These are truncation bounds, not bounds on all floating-point
rounding. An isothermal plate is supported. Out-of-plate depths, negative/unknown
ages, mismatched epochs, masked data and unrepresentable scales are refused.

Cell means integrate these same solutions, rather than labelling centre samples
as volume averages. Mature modes use `sin(n*pi*mid)*sinc(n*width/2)`. Young cells
use the primitive `u*erfc(u)-exp(-u^2)/sqrt(pi)`. For scaled intervals <=0.01,
four-point Gauss evaluation avoids subtraction of near-equal primitives. Its
average-value remainder coefficient is `(4!)^4/[9*(8!)^3]`; the conservative
`|d^8 erfc/du^8| < 1e5` bound gives <6e-21 per term at this width. Direct `erf`
averages preserve small shallow-cell signals instead of subtracting from one.

There is no physical timestep restriction or accumulated time-stepping error in
this closed-form model. It does **not** replace the existing general conduction/
advection solver for arbitrary initial fields or changing boundary conditions.

## Independent heat accounts

`plate_cooling_heat` gives cumulative heat since cooling onset at top and base,
outward positive, in J/m2. Base heat is normally negative: the prescribed hot
reservoir supplies heat. Instantaneous surface flux at age zero diverges; this
API does not fabricate a finite flux. Its integrated heat is exactly zero there.

Normalised by `C*(Tb-Ts)*L`, mature-age cumulative heat is:

```text
Qtop  = Fo + 1/3 - (2/pi^2) sum(n>=1) exp(-n^2*pi^2*Fo)/n^2
Qbase =-Fo + 1/6 + (2/pi^2) sum(n>=1) (-1)^n exp(-n^2*pi^2*Fo)/n^2
```

Young ages use the integrated image solution, with `erfcx` avoiding unnecessary
underflow and cancellation. Terms at image argument >=12 are below the declared
absolute truncation precision. Top plus base heat is checked independently
against `C*integral(T_initial-T) dz`. Difference two cumulative accounts to obtain
interval heat. Like all cumulative ledgers, subtracting very large, near-equal
values at extremely old ages or tiny intervals can lose relative precision;
this is not a high-relative-accuracy short-interval flux API.

## Public workflow and provenance

- `PlateCoolingParameters(ThermalParameters(...), thickness_m, conductivity_w_m_k)`.
- `finite_plate_temperature(depth_m, age_s, parameters, cell_bottom_m=None, ...)`
  returns broadcast point values, or cell means with explicit lower cell depths.
- `plate_cooling_heat(age_s, parameters, ...)` returns `age_shape + (2,)`.
- `plate_cooling_columns(initial_state, models, depth_edges_m, time_s=..., epoch_id=...)`
  joins explicitly selected model parameters to existing `CoolingHistory` records.
  `models` maps existing thermal-profile IDs to the selected finite-plate models.
  The result retains parent state identity, epoch, evaluation time, history source
  IDs, model identities, depth edges, cooling ages, mean temperatures and heat.

Cooling age is `evaluation_time - cooling_start_time`, **never cohort formation
age**. Unknown histories refuse. This is a newly selected derived ridge-cooling
model; it neither overwrites initial W01 temperature descriptions nor asserts
that they equal its initial field. Later assembled W03 work must explicitly
reconcile initial fields and apply any thermal/material feedback.

Example of sampling a supplied model (not an Earth/Diadem default):

```python
from atlas_tectonics import finite_plate_temperature, plate_cooling_heat

# parameters, depths and ages are caller-supplied validated SI values.
points_k = finite_plate_temperature(depths_m, ages_s, parameters)
means_k = finite_plate_temperature(edges_m[:-1], ages_s, parameters,
                                  cell_bottom_m=edges_m[1:])
heat_j_m2 = plate_cooling_heat(ages_s, parameters)
```

## Execution, reuse and status

Age/depth factors are prepared separately for the common column-grid route.
Output and scratch are admitted under the existing `WorkBudget`; both axes are
batched without retaining a depth x age x mode tensor or growing trajectory.
Shared model profiles are grouped before evaluation, preserving individual ages.
No worker pool or JIT compilation is needed for these small direct calculations.

`reuse.cached_plate_temperature` supports points and means through existing
source/runtime-bound, byte-verified `ArrayStore` reuse, cancellation and auto
admission. It includes depths, cell bottoms, ages and full parameter provenance
in the invocation. Small calculations normally bypass disk. The new module is
in the callable identity inventory. Old checkpoints are not rebound or promoted.

See [tests and paired timings](../evidence/w03-thermal-columns.md). Source and
Windows execution are verified locally; this change has not been run on Linux.
No platform-specific numerical path was added, but that is not a Linux pass.

Thermal density and single ownership of vertical support are now implemented in
the separate [increment 2](W03_THERMAL_SUPPORT.md). Solid-conserving drained
compaction/rebound with changing area is supplied by [increment 3](W03_COMPACTION.md).
Assembled W01/W02/W03 acceptance remains. No density-driven buoyancy or age-depth subsidence is supplied by
increment 1 itself. This restricted conductive
model excludes variable material properties, internal/latent/adiabatic heating,
melt, hydrothermal circulation, moving plate thickness and horizontal conduction.
