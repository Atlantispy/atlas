# W03 increment 2: thermal density and one support owner

22 September 2026. Implemented locally on `remake`, WORKING NON-CANON. This
completes the selected homogeneous, constant-property thermal-density/local-support
increment. It is not complete W03, a deformable free surface, empirical calibration,
or an acceptance of generated Earth/Diadem terrain.

## Physical contract

Reuse the existing `BoussinesqMaterial` and thermal buoyancy law, with volumetric
expansivity `alpha`, reference density `rho0` and EOS reference temperature `T0`:

```text
rho(T) = rho0 * [1 - alpha * (T - T0)]
Sigma = integral_0^L [rho(T_current) - rho(T_reference)] dz
      = rho0 * alpha * integral_0^L (T_reference - T_current) dz
q_down = g * Sigma
s_down = Sigma / (rho_compensation - rho_fill)
```

Units are K, m, kg/m3, kg/m2, Pa and m respectively; gravity is positive in m/s2.
Cooling increases downward load and gives positive downward displacement; warming
reverses both. The same gravity in load and restoring force cancels from the
displacement. `Sigma` is a **buoyancy sheet anomaly**, not newly created or
conserved material mass. Boussinesq reference mass and heat capacity remain fixed;
this diagnostic must not overwrite W02's mass/solid-volume inventory.

The material's EOS reference `T0` is not the isostatic reference temperature field.
Both current and reference fields are explicit. Columns share fixed geometry,
material/composition, gravity and fill/restoring-density choices. Compensation
density must exceed fill density. The caller provides a named reference, depth
datum, provenance and small-deflection envelope `0 < max_relative_deflection < 1`.
Exceeding it refuses, not clamps. Passing a caller-chosen envelope is not evidence
that the parameters or local-isostasy assumption fit a real landscape.

This is first-order local compensation: no flexural rigidity, variable surface
replacement, shoreline crossings, dynamic pressure/topography, nonlinear moving
geometry or compressible mass evolution. The existing flexural/mechanical solvers
remain separate and unchanged. Layered materials and coupled geometry belong to
later assembled work, not this homogeneous plate adapter.

## Ownership and public interfaces

`ThermalSupportParameters` requires exactly one declared thermal owner:
`column-isostasy`, `mechanical-buoyancy`, `flexure`, or `empirical-age-depth`.
The local-response APIs refuse all but `column-isostasy`. This prevents duplicate
thermal support within this managed route; it cannot police arbitrary external
code which ignores the policy and sums unrelated outputs.

- `thermal_density(temperature_k, material, ...)` evaluates the existing thermal
  density law at reference composition, checking temperature and anomaly limits.
- `thermal_column_response(current_cell_means, reference_cell_means, edges_m,
  material, parameters, ...)` integrates supplied true cell means. The final axis
  is depth; edges start at zero and strictly increase downward. Generic cell means
  cannot certify unknown subcell extrema or arbitrary subcell composition.
- `plate_thermal_response(age_s, reference_age_s, plate, material, parameters, ...)`
  integrates the finite-plate model directly, without allocating a depth grid.
  Output final axis is `(buoyancy_sheet_kg_m2, downward_load_pa,
  downward_displacement_from_reference_m)`.
- `thermal_support_columns(initial_state, cooling_models, materials, parameters,
  time_s=..., reference_time_s=..., epoch_id=..., ...)` groups explicitly selected
  matching profile/model/material maps and applies the cached direct response.

Displacement is **total from the named reference**, never another increment to
add each time the API runs. The APIs return immutable diagnostics; they do not
mutate elevation, initial W01 temperatures or W02 material state. Callers wanting
an interval difference must select that interval's explicit reference.

The workflow retains parent-state identity, epoch/depth datum, both evaluation
times, cooling/reference ages, history source IDs and model/material/policy
identities. Cooling history is used, never cohort formation age; unknown histories
and mismatched epochs/datums refuse. The reference is the selected finite-plate
model at `reference_time_s`, **not a claim that it matches the authored W01 initial
temperature field**. Reconciling those fields belongs to assembled W03 acceptance.

For the plate route, material conductivity must match plate conductivity and
`rho0*Cp = k/kappa`. Internal heating must be zero. The entire analytic surface-to-
base temperature interval is checked against the material envelope using the
maximum principle, rather than accepting valid-looking means that hide an invalid
surface or base. No Earth/Diadem parameters are silently calibrated or supplied.

## Direct integral and bounded execution

For the fixed-thickness finite plate, let `Fo=kappa*t/L^2` and let `d(Fo)` be its
normalised mean temperature deficit from the hot initial interior:

```text
d(Fo) = 1/2 - sum(n odd >= 1) 4 exp(-n^2*pi^2*Fo)/(n^2*pi^2)
mean(T_reference - T_current) = (Tb-Ts) * [d(Fo_current)-d(Fo_reference)]
```

Young ages use analytically integrated image terms; mature ages use odd modes
through 9. At the `Fo=1/16` switch the first omitted odd mode is 11, giving a tail
below `1.4e-35`. At young ages five alternating mean-erfc intervals implement the
same whole-column integral used by the established point/cell-mean solution.
Tests compare independent long-series and integrated-cell references, both sides
of the switch, the young square-root limit and finite old-plate limit.

For two mature ages, integrate their difference directly using `expm1`; do not
subtract two nearly equal old limiting temperatures. Compute the physical age
difference before Fourier scaling. Equal ages and isothermal plates return exact
zero. Young/mixed-age differences use absolute truncation accuracy, subject to
floating-point rounding, not arbitrarily high relative precision for tiny
increments. Unequal mature ages
whose leading transient has already underflowed refuse rather than inventing
zero; a very large subsequent multiplier cannot recover that lost transient.

The workflow also refuses distinct evaluation times that collapse to equal
binary64 cooling ages after subtraction of an ancient start date. The generic
cell route refuses nonzero weighted temperature contributions rounded to zero
before material scaling. These are explicit numerical limits, not physical
minimum ages, smoothing or relaxed acceptance tolerances.

Direct integration removes all depth sampling from the plate-support route.
The generic cell route uses bounded buffered traversal and compensated joins;
material factors are applied without subtracting rounded absolute densities.
Inputs/output/scratch use existing `WorkBudget` admission, cancellation and
immutable arrays. Profiles sharing identical models/materials are grouped.

`reuse.cached_plate_thermal_response` uses existing verified `ArrayStore` reuse.
The key includes ages, reference ages, full plate/material/support provenance and
output layout; source/runtime/loaded-callable identities cover both new modules.
JSON metadata is canonicalised before storing/comparing, including tuple fields.
Auto admission bypasses disk for cheap calls; no new cache framework, worker pool,
dependency or historical checkpoint repin is introduced.

## Papers and software actually checked

- **Parsons & Sclater (1977)**, *An analysis of the variation of ocean floor
  bathymetry and heat flow with age*: [full text](https://topex.ucsd.edu/geodynamics/parsons_sclater77.pdf),
  equations 9-11 and Figure 1, pp. 805-806. Unlike the abstract-only access during
  increment 1, this review reached the column/isostatic derivation. It supports
  first-order compensated plate cooling, square-root young-age behaviour and
  old-age saturation. Their elevation above the old asymptote and our downward
  displacement from an explicitly chosen reference have different datums/signs.
- **Wickert (2016), gFlex v1.0**, *Open-source modular solutions for flexural
  isostasy*: [full-text section 2.1, equations 1-2](https://gmd.copernicus.org/articles/9/997/2016/).
  The restoring term `(rho_m-rho_fill)*g*w` supplies the local zero-rigidity limit
  and the distinction between load and displacement. Paper/method review only:
  gFlex was not installed, executed or source-audited for this increment.
- **ASPECT Boussinesq documentation**, [version 3.0.0](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/methods/approximate-equations/ba.html)
  (also checked against 2.5.0 by the research reviewer): density varies in the
  buoyancy term while the reference mass-continuity approximation remains
  incompressible. Documentation review, not a new ASPECT execution or source audit.
- **Existing Atlas software**: reviewed/reused `constitutive.py`'s
  `BoussinesqMaterial`/`boussinesq_response`, the same law in `thermochemical.py`,
  `flexure.py`'s restoring-force convention, finite-plate cooling and verified
  reuse. These remain the internal constitutive/execution foundation rather than
  introducing a competing density law or adding thermal support twice.

The mathematics is independently implemented; no upstream software code was
copied. External-package runtimes are not claimed. See
[focused checks and paired timings](../evidence/w03-thermal-support.md).

Solid-conserving drained compaction/rebound with changing column area is now
implemented in [increment 3](W03_COMPACTION.md). Next: assembled W01/W02/W03
acceptance. No long R4.4 or whole-world run was performed.
