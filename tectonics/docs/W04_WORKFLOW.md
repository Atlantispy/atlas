# W04 step 2: source-bound load and support integration

22 September 2026. local unreleased `remake` work.
This joins the supported stationary W01/W02/W03 column workflow to **uniform,
periodic, linear flexure**. It produces an immutable displacement/surface-change
projection; it does not deform the W03 material/thermal mesh or close a nonlinear
hydrology/erosion feedback loop. Subsequent [combined W04 acceptance](#combined-supported-workflow-acceptance)
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
adds fixed variable rigidity. The later [assembled acceptance](#combined-supported-workflow-acceptance)
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
See [verification and timings](#obtained-workflow-and-combined-evidence-22-september-2026).

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

## Combined supported-workflow acceptance

The 22 September 2026 gate is **PASS_SUPPORTED_STATIONARY_PLANAR_1D_W04** for
the selected stationary planar 1D W01–W03 route. The original
[machine result](../evidence/w04-acceptance.json) and
[obtained evidence](#obtained-workflow-and-combined-evidence-22-september-2026) retain their source scope;
this does not accept whole-world terrain, geological calibration or other stages.

`python -I -B tectonics/verify.py --w04`, with declared scientific dependencies
and one BLAS/OMP thread, selects eight reviewed groups: physical reference loads
(19 tests), uniform periodic support (10), uniform finite support (11), variable
rigidity (8), combined workflow (4), verified load reuse (1), source/geometry/
ownership/validity guards (6), and status contract (3). Missing, empty, failed,
skipped or drifting selections cannot pass; no full-suite fallback is used.

The combined control uses authenticated W03 initial columns, cooling and prescribed
drained compaction, then partial rebound and more cooling. Expelled/reabsorbed
water is booked and placed once; zero-total redistribution and additional pressure
are explicit. Independent depth-cell thermal integration and inventory accounts
check the load, without changing source grains/states. The same sequence covers
uniform/variable rigidity under periodic, continuing and mixed free/clamped ends.
The continuing case has two left/one right halo cells and explicit constant-load/
material half-lines. Different boundaries define different physical problems.

Reference shifts establish interval additivity without accumulating prior totals;
W03 restore/rebound and rebuilt/cached W04 projections retain exact bytes/IDs.
Variable-D strain checks apply on cache hits using cropped local Te, including
the mesh-change margin. Rigidity stays positive and fixed, with positive constant
restoring K; elastic thickness is not inferred from thermal/crustal thickness.
No moving plate, 2D/spherical support, yielding, viscoelasticity or evolving D is
qualified. Periodic discrete, uniform finite continuum and variable weak-form
representations need no finite-resolution identity across different equations.
Continuing variable D requires declared exterior loads and refuses omitted-pressure
uncertainty; uniform exterior bounds remain conditional. Mesh-change estimates
are not rigorous continuum-error certificates; variable FE one-sided strain/
extrema, sampled uniform finite validity and diagnostic third derivatives retain
their separate scope. Prescribed drained W03 traction is distinct from W04
external pressure; shoreline, erosion and mesh/heat feedback remain absent.

The first longer-cooling fixture correctly refused on strain. Only its cooling
interval was shortened; original limits/tolerances were unchanged. This step
added qualification, not production-solver optimisation, and claimed no solver/
whole-generator speedup or empirical validation. The
[original assessment](https://github.com/Atlantispy/atlas/blob/1f1d78a6dd2ab3d1c533af9f9b5b79e769ce57fd/tectonics/docs/W04_COMBINED_ACCEPTANCE.md)
retains exact gate descriptions and consulted gFlex sections (Wickert 2016,
2.1, 2.4–2.5, 3.2; numerical-accuracy documentation). Those informed matching
equations, loads and boundaries, without importing external grid rules, signs
or tolerances. Neither gFlex nor a field comparison was run.

## Obtained workflow and combined evidence, 22 September 2026

The original periodic bridge passed **43 distinct focused tests**: thirteen workflow
and thirty load/identity/affected-W03 controls, 13.737/5.348 s. A targeted cleanup
rerun was already among those thirteen, not a 44th check. Actual source joins,
closed-water zero force, sinusoidal response/translation, independently integrated
thermal pressure, compaction/reservoir redistribution, uniform pressure, shifted
reference, masks/immutability/validity/source refusals and exact restored result
IDs were assessed. Failed context-manager entry initially retained resources;
cleanup was hardened. Its test then correctly encountered changed-callable refusal
during close rather than the guessed entry message; release passed without
weakening the source guard.

The [workflow timing record](../evidence/w04-workflow-timing.json) compares four
actual W03 snapshots over 128 columns on a 100 km × 1 km synthetic profile, three
alternating repetitions after warm comparison. Both include W04 setup/close and
exclude the same 4.137581199990 s source/surface-input preparation. Separate
one-shot preparations took median 3.123138900031 s; shared preparation
1.681624000077 s, saving 1.441514899954 s (46.155965075384%), with bit-identical
outputs/provenance. Source/load/thermal/FFT/mask/validity work remains; no cache
hits, workers or skipped snapshots create this gain. Entry:
`python -B tectonics/tools/benchmark_w04_workflow.py --output NEW.json`.
This is same-implementation reuse, not an old shipped stage or whole-generator gain.

The later explicit `python -I -B tectonics/verify.py --w04` passed **62 tests in
51.7190680000931 s**, no failures/errors/skips, with identical before/after source
inventory. Gate counts were 19 load, ten periodic, eleven finite, eight variable,
four assembled, one reuse, six validity/source and three status. An independent
review added cache-hit strain coverage using cropped local Te/mesh-change margin,
distinct from the placeholder policy Te; it found an evidence gap, not a bad
solver. Three new W04 and three retained W01 profile tests passed separately.

The first combined run correctly refused its uniform mixed-edge snapshot:
strain 0.012010364704435138 exceeded unchanged 0.01, while slope 0.015213242362989914
was below 0.1. Fixture cooling intervals changed 1e6/2e6 → 1e5/2e5 s, preserving
compaction stresses, spatial loads, physical limits and assertion tolerances.
This is prescribed drained accounting, not calibrated consolidation time. No
production solver module changed in that acceptance step. Earlier variable-factor
timing (47.97238706% setup reuse) remained bound to unchanged code and was reused,
not rerun or added to an end-to-end percentage.

The [full workflow report](https://github.com/Atlantispy/atlas/blob/1f1d78a6dd2ab3d1c533af9f9b5b79e769ce57fd/tectonics/evidence/w04-workflow.md)
and [combined report](https://github.com/Atlantispy/atlas/blob/1f1d78a6dd2ab3d1c533af9f9b5b79e769ce57fd/tectonics/evidence/w04-acceptance.md)
retain exact selected tests, module/verifier/case/result identities, static checks
and reviewed-source extent. Windows/Python 3.12.14/NumPy 2.4.6/SciPy 1.17.1 with
one native thread was used. No Linux, full suite, full terrain, R4.4, publication,
external gFlex, empirical or whole-world acceptance is supplied by these results.
The machine result remains the original observation; no checkpoint was repinned.
