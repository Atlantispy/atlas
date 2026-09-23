# W04 step 2: source-bound load and support integration

22 September 2026. WORKING NON-CANON, local unreleased `remake` work.
This joins the supported stationary W01/W02/W03 column workflow to **uniform,
periodic, linear flexure**. It produces an immutable displacement/surface-change
projection; it does not deform the W03 material/thermal mesh or close a nonlinear
hydrology/erosion feedback loop. Subsequent [combined W04 acceptance](W04_COMBINED_ACCEPTANCE.md)
passes the selected stationary 1D support workflow, not general terrain validation.

[Step 3](W04_FINITE_REGIONS.md) extends this bridge with explicit finite 1D
regions, exterior loads and physical free/clamped ends. The periodic contract
below remains the step-2 alternative; the finite route has its own continuum
equation and non-wrapping derivative checks.

## Connected data and required physical inputs

`PreparedW04Support(reference, reference_surface, policy)` prepares one immutable
reference, source/runtime contexts, load catalogue and flexure operator. Its
`solve(current, current_surface)` method uses actual `W03ColumnState` snapshots:

- Source W01 sample cell IDs, footprint descriptors, frame, datum, section,
  transverse width, geological densities, cohorts and thermal history.
- The actual W02 cohort inventories retained inside W03, converted with their
  declared `area = spacing * reference_width`, without resampling or guessing
  ordered stratigraphy from a transported mixed cell.
- W03 grain/pore changes, finite reservoir stock, fixed thermal-plate binding,
  reference/current times and material/compaction identities.

The public `W04SurfaceInputs` requires the exact source cell IDs in order,
**reservoir water volume per cell**, **additional external downward pressure per
cell**, and an explicit input source. Each spatial reservoir allocation must be
nonnegative and sum to its own W03 snapshot's complete finite stock, within
128 binary64 eps relative summation tolerance. No renormalisation is performed.
Placement is not inferred from where water left the sediment; the same amount
may be moved to a different represented column. Off-domain/unknown placement is
not silently omitted. These arrays are physical boundary inputs, not hand-built
intermediate sediment/thermal loads.

External pressure excludes weight already represented as grains, pore water or
reservoir water. Supply explicit zero arrays if none is present. W03's prescribed
effective compaction traction is **not** silently interpreted as this total
external pressure: pore pressure, consolidation history and present external
loading are different quantities. The caller must supply the intended current
force independently and identify its source. This step is not a coupled traction
equilibrium calculation.

`W04SupportPolicy` requires the source, `periodic-repetition` assumption, exclusive
`flexure` thermal owner, air/vacuum density, finite headroom above the original
sediment column, elastic properties, and selected small-slope/bending-strain
limits. No Earth constants or empirical accuracy tolerances are invented.

## Closed water, replacement and restoring force

The finite support spans the original sediment base to the source top plus the
explicit headroom. Actual source grains, pore water and located reservoir water
are disjoint inventory phases. The rest is explicit lighter air/vacuum. Overfill
refuses; there is no clipping or invented water.

The step-1 load kernel gives the material/background load relative to the fixed
reference. In a closed pore-to-reservoir redistribution with conserved solids,
the total material force change is zero (up to arithmetic/source tolerances),
although its spatial distribution can bend the plate. Deeper fixed geological
inventories cancel in the reference difference; no duplicate deep rock inventory
is added merely to carry a thermal anomaly.

The restoring coefficient is explicitly
`K = (rho_compensation - rho_air_or_vacuum) * g`.
Compensation density/gravity must match the W03 source support parameters, but
the old **water-bath** restoring contrast must not be reused: that would introduce
deflection-created water from an implicit additional reservoir. Here finite
water volumes stay prescribed on the reference columns. A uniform sea-level
surface, shoreline migration or flow into new depressions requires later feedback
physics and is not simulated or claimed.

## One thermal support owner

W03's `thermal_diagnostics` computes a local-isostatic comparison but does not
apply displacement to its state. W04 explicitly excludes that displacement from
its combined result. It calculates only the source-bound pressure:

`q_T = rho0 * alpha * H * g * mean(T_reference - T_current)`.

The existing stable finite-plate integral evaluates the temperature change
directly, including its mature-age cancellation safeguards. The full effective
thermal plate is a fixed-coverage Boussinesq diagnostic, not another material
phase overlapping the sediment. W03's homogeneous constant-property thermal
approximation and validity checks remain; this does not introduce a mineral-
resolved thermal EOS. Thermal buoyancy never changes conserved inventory mass.

W04 solves `D * discrete_biharmonic(w) + K*w = q_material + q_T + Delta p_external`
for the **total downward displacement from the chosen reference**. It never adds
W03's local-isostatic displacement, nor a previous W04 total. Re-evaluating the
same states/inputs gives the same result, not further subsidence.

## Outputs and limitations

`W04SupportResult.values` has one row per source cell:

| Column | Quantity |
| --- | --- |
| 0 | Occupied inventory pressure change, Pa |
| 1 | Air/vacuum replacement pressure change, Pa |
| 2 | Thermal diagnostic pressure change, Pa |
| 3 | Additional external pressure change, Pa |
| 4 | Total applied downward pressure change, Pa |
| 5 | Total downward flexural displacement from reference, m |
| 6 | Sediment-top change: bulk-thickness change minus displacement, m |
| 7 | Reservoir-top change, including water-thickness change, m |

Surface changes are positive upwards. Water-top change is undefined when either
reference or current cell is dry: `reservoir_surface_known` explicitly masks these
entries, their packed placeholder is zero, and the convenience property refuses
an unqualified read. This is not a coastline or water-level inference.

Results bind source/reference/current states, surface-input IDs, operator,
execution identity, epoch/datum and policy. All payloads are immutable; modifying
an array descriptor does not modify the stored state. W03 states remain unchanged.
Current states must share their source workflow, history, cohorts, fixed grid,
compaction catalogue/conditions and closed total fluid inventory with the reference.
Changed source/runtime identities refuse instead of silently rebinding snapshots.

Closed zero-velocity W03 transport does not imply periodic physical support.
The periodic assumption must be supplied explicitly. Each FFT spans the complete
domain and solves the existing centred-difference biharmonic operator, not a
continuous `k^4` spectral operator or independently tiled regions. Output slope,
bending strain and W03 fixed-plate deflection bounds must all pass. These guards
do not replace checking the thin-plate approximation against an intended use case.
Step 3 supplies bounded non-periodic and domain-size treatment; [step 4](W04_VARIABLE_RIGIDITY.md)
adds fixed variable rigidity. The later [assembled acceptance](W04_COMBINED_ACCEPTANCE.md)
checks these alternatives without claiming broader terrain validation.

## Efficient use, caching and recovery

```python
# All inputs below are explicit, source-bound model data.
with PreparedW04Support(reference, reference_surface, policy, budget=budget) as plan:
    for current, surface_inputs in supported_snapshots:
        result = plan.solve(current, surface_inputs, store=store)
        # Consume result; do not accumulate its total displacement.
```

`project_w04_support` is the equivalent one-shot convenience function. Reuse the
prepared object for multiple snapshots: geometry/reference conversion, source
context setup and immutable FFT coefficients are prepared once, while each
projection retains source checks, current inventory capture and validity gates.
Only the fixed reference is retained; there is no growing result/history list.
The caller owns the snapshots/results it deliberately keeps.

Material loads and flexure use the existing verified cache and auto-admission:
cheap work skips persistence; explicit persistence includes input and execution
identities. The homogeneous thermal integral is small and evaluated directly.
No worker pool is forced onto these short kernels. Budget reservations are
accounted workspace, not OS RSS, and are released on close/error/cancellation.

W04 is a derived projection rather than a new evolving material store. Existing
W03 save/restore preserves its actual inputs under unchanged source identity;
reconstruct the explicit surface inputs and prepared projection after restoration.
No old checkpoint is repinned, and no second history/cache system is introduced.
See [verification and timings](../evidence/w04-workflow.md).

## Papers and software checked

- [Wickert (2016), gFlex v1.0](https://gmd.copernicus.org/articles/9/997/2016/gmd-9-997-2016.pdf):
  full-text section 2.1, equations 1-2 and infill discussion; section 2.3 and its
  periodic-boundary discussion/Table 1. Used for load/restoring-force separation,
  explicit boundary assumptions and comparison expectations.
- [ASPECT 3.0 Boussinesq documentation](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/methods/approximate-equations/ba.html):
  approximation, incompressibility and constant-property density sections.
  Used to retain diagnostic thermal buoyancy separately from inventory mass.

These are paper/documentation reviews, not execution or source audits of either
external package. Local W01-W03, finite-plate integration and FFT support source
were reviewed directly. Independent analytical controls are not field calibration
or external cross-solver acceptance, and do not establish finished terrain realism.
