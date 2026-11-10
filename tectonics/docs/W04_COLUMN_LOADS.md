# W04 physical loads and support workflows

Implemented 22 September 2026.
This completes **load construction**, not W04 support/coupling acceptance or
empirical terrain realism. It does not change `PeriodicFlexure` or apply movement.

## Inputs and physical meaning

`LoadSupport` identifies the fixed horizontal footprints, frame, vertical datum,
finite column height, areas and geometry source. `LoadPhase` identifies each
disjoint rock, sediment-grain, pore-water, water or other inventory phase and its
explicit constant reference density/source. `ColumnLoadState` captures volumes,
replacement density and source/epoch identities in immutable byte-backed arrays.
Reference/current snapshots must share the exact support and phase catalogue.
Use a union catalogue with explicit zero volumes for absent phases, not an
intersection which silently discards material. Different density materials are
separate phases; no undocumented density change is inferred from thickness.

`geometry_source` and thermal coverage sources are caller attestations, not proof
that two polygons or depth intervals coincide. The later [bounded W04 workflow](#w04-source-bound-load-and-support-workflow)
binds its selected W01/W02/W03 geometry, inventory, history and support ownership.
`epoch_id` names the instant of each snapshot; reference/current may differ. No
time conversion or chronological interpolation is performed by this kernel.

Let A be area, V* the finite supported volume, V the sum of disjoint occupied
volumes, M their inventory mass, f the explicit replacement density and g positive
gravity. For each state, supported mass is `B = M + f (V* - V)`. The applied load is:

`q_material = g (B_current - B_reference) / A`, positive downwards, in Pa.

The implementation evaluates the equivalent contrast form:

`Delta B = sum[(rho_phase - f_current) Delta V_phase] + (V* - V_reference) Delta f`.

This avoids subtracting two large absolute loads. The second term is essential
when replacement density changes. A full support has no replacement material.
Negative volumes, overfilled supports, implicit remapping and unknown catalogues
are refused; volumes are never clipped to make them fit. One uniform replacement
density is prescribed per column. Represent distinct water/air regions explicitly
as phases; this is not a sea-level solver or an infinite background reservoir.

Compaction keeps grain mass unchanged. If pore water leaves and identical water
occupies the vacated volume, its two accounts cancel: compaction alone creates no
extra excess load. If negligible-density air replaces that water, the support
unloads. Fluid arriving elsewhere loads its destination only when that destination
is represented. This kernel neither locates an external reservoir nor proves its
supply. The [bounded workflow](#w04-source-bound-load-and-support-workflow) receives explicit finite-reservoir
placement; this kernel does not infer it.

## Thermal term and double-counting boundary

Optional thermal phases require `BoussinesqMaterial`, its **uncorrected reference
density**, zero extra composition anomaly, explicit fixed coverage, and valid
true volume-mean temperatures for both states. Because this EOS is linear,
volume means give the exact integral for the selected constant-property law:

`q_thermal = g sum[-rho0 alpha (T_current - T_reference) V_phase / A]`.

Cooling increases downward load; heating reduces it. Thermal phase volumes must
remain exactly fixed. Moving/changing thermal coverage is refused until a
conservative thermal mapping exists. All material temperature and small-anomaly
validity bounds remain active. The thermal account is a **diagnostic buoyancy
sheet**, not added/removed physical mass, pore fluid or W02 inventory.

The output of `column_load_change(reference,current,g)` has shape `(columns,4)`:

| Column | Quantity |
| --- | --- |
| 0 | Occupied inventory mass change / area, kg/m2 |
| 1 | Replacement mass change / area, kg/m2 |
| 2 | Thermal diagnostic buoyancy-sheet change, kg/m2 |
| 3 | Total prescribed downward pressure, Pa |

This is the **total change from the given reference**, not a displacement or a
load increment to repeatedly add to an already-loaded state. No precomputed W03
subsidence is accepted as another load input. The [bounded W03/W04 connection](#one-thermal-support-owner)
enforces one owner: it does not apply both local thermal isostasy and flexure to
the same thermal anomaly. Future deflection-created infill belongs to the restoring
term/feedback equation, not both that equation and this fixed-reference load.
There is no dynamic mantle traction, non-Boussinesq EOS or pressure-dependent
mineral phase equilibrium in this step.

## Efficiency and reuse

Inputs are captured/hashed once per immutable state, not once per column or
evaluation. The kernel vectorises across bounded column batches and uses
compensated accumulation across phases, retaining small loads between opposing
large ones. Scratch memory scales with batch size, not an extra full phase cube.
Positive-zero underflow and nonfinite intermediates fail closed; some extreme
representable end results are deliberately refused if their chosen intermediate
scales cannot be represented. This is not arbitrary-precision arithmetic.

`reuse.cached_column_load_change` uses the existing auto-admission, lossless
storage, execution/source identity, claims and cancellation machinery. Cheap work
bypasses persistence. Both snapshot identities, geometry, gravity, input bytes,
catalogue and current execution identity distinguish cached results. Changing
batch size changes workspace, not the numerical method or result identity.
No process pool is imposed on this millisecond-scale workload.

The constructors and kernel reserve transient workspace before allocation.
Caller-retained immutable snapshots need the caller's existing retained-state
allowance. Accounted workspace is not measured operating-system RSS. There are
explicit column/phase limits and cancellation checkpoints. Nothing uses a
platform-specific process/fork path; actual tests/timing here were on Windows.

## Research and existing software checked

- [Wickert (2016), gFlex v1.0](https://gmd.copernicus.org/articles/9/997/2016/gmd-9-997-2016.pdf):
  full-text section 2.1, equations 1-2 and infill discussion checked. Informed the
  distinction between imposed pressure and buoyancy/restoring infill. The finite
  material/replacement mass bookkeeping above is our explicit derived contract,
  not a claim that gFlex performs these Atlas source checks.
- [ASPECT 3.0 Boussinesq documentation](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/methods/approximate-equations/ba.html):
  approximation, incompressibility and near-linear-model sections checked.
  Informed the separation of thermal buoyancy from conserved reference mass.

These were paper/documentation reviews, not external software installation,
execution, code audits or cross-solver validation. No empirical data calibration
is claimed. See [focused evidence and measured timing](#obtained-evidence-22-september-2026).

## Assembled support routes

[W04 workflow](#w04-source-bound-load-and-support-workflow) owns actual stationary W01–W03 adapters and
exclusive thermal/support ownership. [Finite regions](#finite-region-support)
and [variable rigidity](#fixed-variable-rigidity) describe the distinct supported
boundary problems. Their combined qualification remains stationary planar 1D;
no full terrain or held R4.4 campaign is established by this load kernel.

## Obtained evidence, 22 September 2026

The finite fixed-reference load kernel passed 29 focused Windows tests:
nineteen load controls plus ten identity/reuse checks, 0.010/1.920 s. The initial
cache development pass is not counted twice. Selection:
test_w04_column_loads, test_w04_load_reuse and execution IdentityTests,
Python 3.12.14/NumPy 2.4.6. No Linux/full-suite/held run claim.

Independent synthetic SI witnesses check compaction with replacement-water
inventory/replacement −0.8/+0.8 kg/m² (zero force), air-background −1.6 Pa,
deposition replacing water +2.4 Pa/reversed erosion, finite-gap density +3.2 Pa,
and three metres cooled five kelvin +0.24 Pa without inventory change.
Fully occupied support ignores background changes. Independent absolute mass,
zero/reversal/additivity/subdivision and compensated large opposing loads pass.
Mismatch/shape/capacity/temperature/thermal-volume/double-count/underflow
refusals, immutability, source/runtime, cancellation/admission and real cache
invalidation remain. Review repaired intermediate underflow using checked
products/quotients with Decimal-backed regressions rather than false zeros.

[Raw load timings](../evidence/w04-load-timing.json) cover 65,536 columns/eight
phases, three alternating repeats after warm-up, identical immutable snapshots.
Independent scalar fsum 0.289386600023 s versus batch 0.008304700023 s saves
0.281081900001 s (97.130240300726%). Shared input construction is separately
0.027473299997 s; accounted workspace is 16,785,408 bytes, not RSS. Inventory/
replacement accounts match exactly; maximum thermal/pressure differences
2.84217e−14 kg/m²/3.63798e−12 Pa meet unchanged 2e−13 relative/2e−9 absolute
comparison. Each arm repeats its own output bitwise. Entry:
python -B tectonics/tools/benchmark_w04_loads.py --output NEW.json.

The [complete original report](https://github.com/Atlantispy/atlas/blob/1f1d78a6dd2ab3d1c533af9f9b5b79e769ce57fd/tectonics/evidence/w04-loads.md) retains exact module/source
identities, commands/static results and research pointers. This was a new
same-kernel scalar/batch comparison without cache/workers, not old production or
whole-generator gain. Thermal coverage is attested, not geometrically
authenticated; subsequent actual-source/reservoir/owner/support assembly has its
own acceptance, not supplied by this component result.

## W04 source-bound load and support workflow

This joins the supported stationary W01/W02/W03 column workflow to **uniform,
periodic, linear flexure**. It produces an immutable displacement/surface-change
projection; it does not deform the W03 material/thermal mesh or close a nonlinear
hydrology/erosion feedback loop. Subsequent [combined W04 acceptance](#combined-supported-workflow-acceptance)
passes the selected stationary 1D support workflow, not general terrain validation.

[Finite-region support](#finite-region-support) extends this bridge with explicit finite 1D
regions, exterior loads and physical free/clamped ends. The periodic contract
below remains the step-2 alternative; the finite route has its own continuum
equation and non-wrapping derivative checks. [Fixed variable rigidity](#fixed-variable-rigidity)
adds the separate variable-coefficient method and its accuracy limits.

### Connected data and required physical inputs

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

### Closed water, replacement and restoring force

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

### One thermal support owner

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

### Outputs and limitations

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
Step 3 supplies bounded non-periodic and domain-size treatment; [fixed variable rigidity](#fixed-variable-rigidity)
adds fixed variable rigidity. The later [assembled acceptance](#combined-supported-workflow-acceptance)
checks these alternatives without claiming broader terrain validation.

### Efficient use, caching and recovery

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

### Papers and software checked

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

### Combined supported-workflow acceptance

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

### Obtained workflow and combined evidence, 22 September 2026

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

<a id="finite-region-support"></a>

### Finite regions without invented plate edges

Implemented for the current **uniform-rigidity, stationary planar 1D** W01-W03
workflow. This is a linear support projection, not material evolution or
whole-world terrain acceptance. The periodic workflow above retains its explicitly
periodic centred-difference operator; this step does not change that equation.

#### Physical alternatives

- `continuous-plate`: the output region is a window into a continuing plate with
  the same prescribed D and K. Adjacent load cells and exterior half-lines are
  explicit. No motion or traction is forced to zero at the crop edges.
  Computational FFT padding is not an extra geological load region.
- `physical-edges`: the region really terminates at both source-defined ends.
  Each end is explicitly `clamped` (w=w'=0) or `free` (w''=w'''=0). Mixed
  free/clamped ends work. These homogeneous conditions describe changes from the
  chosen reference. Exterior plate loads are refused in this mode.

`FlexureBoundary1D(left, right, source_id)` records the actual assumption.
`W04SupportPolicy` takes `region_boundary` and `max_omitted_deflection_m` alongside
its unchanged material, ownership and validity requirements. A physical end must
not be chosen merely because source data stop there. Neither a coastline nor a
closed W02 transport boundary automatically defines a plate edge.

The 1D solution represents loading invariant along the transverse direction.
W03's finite reference width converts inventories into pressures; it is **not**
a finite-width 2D plate-edge treatment. Variable rigidity, spherical geometry,
arbitrary end forces, mixed continuous/physical ends and general 2D regions remain
outside this increment.

#### Explicit surrounding loads and uncertainty

`W04ExteriorLoads(state, left_pressure_pa, right_pressure_pa, *, far_left_pa,
far_right_pa, omitted_left_bound_pa, omitted_right_bound_pa, source_id)` binds one
exterior specification to the exact W03 state, time, grid, frame and datum.

Halo arrays contain total downward pressure in Pa on contiguous cells at the
source spacing. Left order is far-to-near; right is near-to-far. Empty arrays
explicitly mean no represented halo. Beyond each halo is a prescribed constant-
pressure half-line. These are total exterior loads, including any thermal,
geological, water or external components the source authorises; outside thermal
evolution is never inferred. Globally uniform cooling must be explicitly
continued outside to claim its uniform whole-line response. The closed W03
reservoir still closes on its own cells; it is not allocated outside again.

Supply reference exterior inputs through `PreparedW04Support(..., exterior=...)`
and current inputs through `.solve(..., exterior=...)`. Halos must have identical
geometry at both instants. Load changes are subtracted from that fixed reference;
previous displacement is never accumulated. Changed halo extent needs new
reference preparation, not a silent checkpoint repin.

Each omitted bound is an absolute pressure departure from the declared far-field
constant, valid everywhere beyond the represented halo. Reference/current bounds
add conservatively. Zero is an explicit exact-load assumption, not unknown data.
For nearest output-to-exterior distances dL,dR, define:

`S = QL exp(-dL/alpha) + QR exp(-dR/alpha)`.

Conservative error bounds are `S/(sqrt(2)*K)` for displacement, `S/(K*alpha)` for
slope, and `sqrt(2)*S/(K*alpha^2)` for curvature. The selected omitted-displacement
tolerance must pass. All three also augment the existing displacement, slope and
bending-strain checks. Padding unknown surroundings with zeros does not establish
that these bounds hold. Results retain the boundary source, full model grid,
crop, flexural length, both exterior IDs and conditional uncertainty assessment.

#### Equation and numerical choice

Solve the continuous uniform thin-plate equation `D w'''' + K w = q`, with
`K=(rho_compensation-rho_void)g`, positive-down w, and `alpha=(4D/K)^(1/4)`.

`G(r) = exp(-abs(r)/alpha) [cos(abs(r)/alpha)+sin(abs(r)/alpha)] / (2 K alpha)`.

Each cell is constant pressure over its full width, not a point impulse.
Analytical cell integration supplies exact weights for that representation.
Stable complex exponential/expm1 expressions preserve narrow-cell and far-tail
differences. Signed forebulges are retained. Zero-padded **linear** convolution
has enough padding for the complete source/kernel convolution, with no periodic
images. The whole coupled array is solved together. Output is point response at
centres/faces, including three analytic derivatives, not output-cell-mean
displacement. Unresolved subcell pressure still has a constant-cell assumption.

Constant far-halfline pressures are integrated analytically. Physical ends use
a four-coefficient homogeneous correction with bounded end-localised decaying
sine/cosine modes. Derivative rows are scaled by alpha powers. The scaled 4x4
condition number must be at most 1e8, and reconstructed endpoint residuals pass a
512-epsilon scaled arithmetic check. Ill-conditioned very short physical plates
refuse: this is a limitation of the numerical basis, not a singular physical
problem. No FD fallback silently changes the method.

The new continuum response and earlier periodic **discrete** biharmonic response
need not agree at finite resolution. Source subdivision and zero-load crop/domain
enlargement are independently tested. Physical-end changes deliberately change
the problem. Oscillating load responses need not converge monotonically with
distance. Validity checks sample analytic derivatives at every centre and face,
including exterior uncertainty; they do not certify unsampled subcell extrema,
independently validate thin-plate assumptions or calibrate elastic thickness.

#### Efficiency, provenance and recovery

Integrated kernel transforms and physical-end bases are prepared once. No dense
O(N-squared) matrix or growing history is kept. These short, globally coupled
kernels remain serial. Shared byte admission covers setup, retained coefficients,
full halo responses and compact interior output. A crop cannot retain its large
temporary halo buffer. Exterior hashing streams both payloads without making a
duplicate concatenation.

`cached_finite_flexure` uses the existing store, runtime/source checks and cheap-
work auto-bypass. Its identity is distinct from periodic flexure and includes
geometry, physical boundaries, materials and all load bytes, including far fields.
W04 additionally binds exterior sources and bounds. W03 restoration plus
reconstructed exterior inputs reproduces results and IDs. No old seal is repinned.
See [checks and timings](#finite-region-evidence).

#### Papers and software checked before selection

- [Wickert (2016), gFlex v1.0](https://gmd.copernicus.org/articles/9/997/2016/):
  full-text section 2.1, equations 1-4 and 7, Table 1 and section 2.3. Compared
  analytical superposition and finite differences; checked continuous, clamped,
  free and periodic meanings. This motivated exact cell integration for constant
  rigidity and explicit exterior treatment instead of a guessed clamp.
- [gFlex theory and numerics](https://gflex.readthedocs.io/en/latest/theory_and_numerics.html):
  independent reviewer checked governing equations, flexural length, SAS/SAS_NG,
  FD and FFT documentation. Atlas independently derives/tests positive-down
  pressure units; finite physical padding is not treated as exactly infinity.
- [SciPy FFT convolution documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.fftconvolve.html):
  checked full linear-convolution behaviour and size-dependent direct/FFT costs.
  Implementation uses existing NumPy FFTs; no dependency was installed.

Paper/documentation reviews only: no external gFlex execution or source-code
audit. Independent quadrature and closed-form controls provide numerical evidence,
not field calibration or full terrain realism acceptance.

<a id="finite-region-evidence"></a>

#### Obtained finite-region evidence, 22 September 2026

The uniform-D/K stationary planar 1D finite-region route passed 39 distinct
focused Windows tests: eleven independent finite controls, six real W03 regional
joins, thirteen retained periodic and nine shared identity checks. After final
finite/exterior fixes, all seventeen affected new-route tests passed in 11.494 s;
the unchanged 22 retained results were reused. Selection:
test_w04_finite_region, test_w04_regional_workflow, test_w04_workflow and
test_execution_reuse.IdentityTests, with declared scientific dependencies/one
thread. No Linux/full-suite/long-run evidence is inferred.

Independent Green quadrature, rectangular/forebulge response, direct cell sums,
half-lines, subdivision/crop enlargement/translation, omitted-strip bounds,
free/mixed/clamped ends and range/resource/cancellation/refusal/restart controls
check the stated continuum problem. Actual source/halo/thermal continuation,
closed-water/owner/epoch/datum and total-reference identities remain active.
Physical ends require declared boundaries; arbitrary tractions, short ill-conditioned
bases, variable rigidity, 2D/spherical support and subcell-extrema certification
were not qualified by this increment.

Review fixed a returned interior view retaining the full halo beyond its charged
lifetime: output now detaches while both buffers are admitted, with bounded
exterior hashing. Safe scaling also prevents q/(2K) silently vanishing at extreme
finite K; q=K=1e308 gives the independent 0.5 m half-line displacement.

[Raw finite timings](../evidence/w04-finite-timing.json) compare 2,048 cells/400 km,
twelve solves/repetition and three alternating pairs, signed synthetic loads.
Both use the same cell-integrated kernel, all centre/face displacements plus
three derivatives, validation/admission/immutable outputs. Direct superposition
0.101421499974 s versus prepared linear FFT 0.010749100009 s saves
0.090672399965 s (89.40155686%) per twelve solves; setup is separately
0.001285999897/0.001994500053 s and transform storage 524,352 bytes. Largest
displacement difference is 1.82146e−17 m; derivatives meet unchanged
5e−13 × per-component max response. The first harness tolerance-format error was
fixed to the same explicit inequality, without changing the gate. Entry:
python -B tectonics/tools/benchmark_w04_finite_region.py --output NEW.json.

The [complete original report](https://github.com/Atlantispy/atlas/blob/1f1d78a6dd2ab3d1c533af9f9b5b79e769ce57fd/tectonics/evidence/w04-finite-regions.md) retains exact
identities/static checks and reviewed gFlex/SciPy documentation. These are new
kernel algorithm measurements, not old-release/whole-generator gains, empirical
validation or external gFlex execution; W03 evolution/context and workers/cache
hits are outside timing.

<a id="fixed-variable-rigidity"></a>

### Fixed spatially variable rigidity

Implemented and optimised for the stationary, planar **1D** W01-W03 support
projection. This extends [finite-region support](#finite-region-support); it does not
change the existing fast uniform-rigidity routes. Subsequent [combined acceptance](#combined-supported-workflow-acceptance)
passes the selected stationary 1D support workflow, not general terrain validation.

#### Physical contract

`RigidityProfile1D` supplies source-linked E (Pa), effective elastic thickness Te
(m), and Poisson ratio nu for every ordered source/halo cell. Require E>0, Te>0,
and -1<nu<0.5. Rigidity is `D=E Te^3/[12(1-nu^2)]` in N m. E and Te are not
inferred from rock names, crustal thickness or the thermal-plate thickness.
Arrays are immutable snapshots; source, grid, frame, datum, epoch and explicit
exterior materials contribute to the profile identity.

Solve the conservative thin-plate/Winkler equation

`(D(x) w''(x))'' + K w(x) = q(x)`, `K=(rho_compensation-rho_void)g > 0`.

Displacement and pressure are positive down. D and q are piecewise constant in
the supplied cells; no averaging smears a stiffness jump. The weak form is
`integral(D w'' v'' + K w v) = integral(q v)`. It transmits displacement, slope,
bending moment and shear across an unloaded interface. Curvature itself may
jump. Multiplying the old uniform biharmonic stencil by local D is **not** this
equation and is not used.

The profile is fixed across the reference/current projection. The solver acts on
the change in load, so repeated calls give total displacement from that reference,
not accumulated increments. Time-dependent rigidity would require separate
reference/current absolute-load solutions; changing D is not supported here.
Local maximum strain uses each cell's own Te times absolute curvature / 2.

Boundary choices are explicit:

- `periodic`: identify displacement and slope at the seam. D may jump across it;
  the nonzero-mean load is retained because K is positive.
- Physical ends: homogeneous `free` or `clamped`, including mixed free/clamped
  ends, applied as natural weak conditions or constrained displacement/slope.
- Continuing plate: specify both far materials as `(E,Te,nu)` tuples and both
  exterior half-line pressures, with any represented halo cells in the profile.
  Exact constant-material decaying half-line solutions supply endpoint stiffness
  and forcing. The output crop is not a new plate edge.

For continuing support, **nonzero omitted-exterior pressure uncertainty is
refused**. The uniform Green-function tail bound is not valid through a variable-D
interior. Zero bounds declare exact prescribed exterior loads; they never mean
unknown data. Existing uniform support retains its previous uncertainty treatment.

This remains linear small-deflection, stationary 1D flexure with constant K.
Loading is invariant transverse to the transect; W03's inventory width does not
make it a finite-width 2D plate. No spherical geometry, yielding, viscoelasticity,
evolving rigidity, general end forces or feedback into W03 geometry/heat/water is
added. Effective elastic inputs still need source-specific scientific selection.

#### Numerical accuracy and output

C1 cubic Hermite finite elements preserve the correct weak equation. Exact
element stiffness, consistent foundation and cell-load integrals are assembled
in scaled `[w,h*theta]` degrees of freedom. A diagonal equilibration precedes
SPD banded Cholesky. No artificial stiffness, matrix jitter, dense fallback or
changed physics is used on failure. A componentwise scaled equation residual is
checked after every solve.

`VariableFlexureAccuracy` requires a source, relative tolerance and separate
absolute tolerances for displacement, slope and curvature. Starting subcells
respect the smallest prescribed flexural length. At least two meshes are solved;
subdivision doubles until every cell's point/maxima change, plus the estimated
numerical uncertainty of both meshes, passes its selected absolute tolerance plus
relative tolerance times that field's domain maximum.
The returned answer is the finer computed solution, not an extrapolation.
Default maximum refinements is six, bounded to eight and an explicit element
ceiling (default 65,536). Budget or convergence failure refuses the answer.

These are **mesh-change estimates, not rigorous continuum-error bounds**. Exact
element integration does not make the FE response exact, nor does a small backward
residual prove a small forward error for every extreme stiffness/mesh condition.
The independent controls include an exact two-material continuum solution and
uniform-rigidity analytical Green response; broad geological calibration remains
separate. An insufficient mesh ceiling is not repaired by loosening a tolerance.
When the ceiling is reached and a failing field's domain-maximum change did not
fall at the last refinement and lies above an earlier minimum, the refusal quotes
that minimum, its subdivisions and the change at the ceiling instead of saying
only that the tolerance was not reached. Round-off in the banded solve is the
usual cause (the scaled bending term grows as `h^-4`), and then a higher ceiling
is unlikely to help. The estimates do not establish that cause. An accidentally
small early estimate gives the same pattern. Two later levels can also agree
within the tolerance while round-off still moves each of them by more than that.
The mesh-change diagnostic offers the cause conditionally and never asserts it.
A failing field that is still falling at the ceiling keeps the plain refusal.

Before accepting a mesh pair, an additional numerical-precision check now
propagates scaled equation residuals and floating-point rounding estimates through
the retained Cholesky factors. Assembly estimates include the magnitudes of the
logarithmic stiffness scaling and the element contributions before cancellation.
A scalar stiffness error preserves its correlated element bending operator;
the local contraction's rounding and independent matrix assembly/equilibration
errors remain included. Right-hand-side formation and polynomial evaluation are
included separately.
The three output operators are the Bernstein controls for displacement, slope
and curvature. Their convex-hull property covers the whole represented element,
including maxima between samples. A deterministic, bounded Hager/Higham norm
estimate applies the LAPACK forward-error-estimation approach to those output
operators. No elastic-input perturbation is used as an error bound.

The acceptance allowance includes the mesh change and both numerical estimates.
An apparent mesh pass that cannot fit this allowance is refused explicitly for
numerical precision after the available levels have been tried. Tolerances and
physical equations are unchanged. This is an engineering **error estimate**, not
interval arithmetic or a rigorous upper bound: norm estimation can underestimate,
and elementary-function rounding is modelled rather than certified. It improves
the previous mesh-only gate without claiming a continuum-error certificate or
guaranteed digits for arbitrary ill-conditioned systems (R7, 2 October 2026).

The low-level immutable result has shape `(N,5,4)`:

| Row | Meaning |
| --- | --- |
| 0 / 1 / 2 | Left face / centre / right face: w, w', w'', w''' |
| 3 | FE-polynomial maxima in the source cell: abs(w), abs(slope), abs(curvature), strain |
| 4 | Mesh-change plus both numerical-error estimates for w, slope, curvature; accepted subdivisions |

True source/material faces remain one-sided. A centre falling on an artificial
internal FE face averages its two traces, making sampling reflection-consistent
without smoothing a material interface. Displacement/slope extrema include roots
inside each cubic, not merely centre/face samples. The third derivative is a
diagnostic FE derivative, **not** certified by the first-three-field mesh gate.
The bridge adds these combined estimates to its displacement, slope and strain
validity assessment; that remains a conditional engineering screen, not a proof
of all continuum subcell extrema or of realistic terrain.

#### Integration, reuse and bounded resources

Supply `rigidity=profile, accuracy=accuracy` to `PreparedW04Support` or
`project_w04_support`. The full profile grid, actual W01 source frame and W03
datum/epoch must match. Existing thermal ownership, physical load construction,
reference surfaces and exterior state binding still apply. E/Te/nu in the profile
are authoritative for bending; `policy.elastic` continues to supply K and gravity.

All elements remain in one coupled solve. Finite bandwidth is three; folding the
periodic ring keeps bandwidth at most five, so factorisation/storage are linear
in the number of internal elements. Factors for visited meshes are retained once
per prepared profile, not rebuilt per load or stored as a growing load history.
Coefficient-rounding estimates add one retained band, one element vector and two
small endpoint blocks. Numerical-precision estimation runs only for a mesh pair
that otherwise passes: it uses a fixed number of band solves and linear-sized vectors, without
a dense inverse. Estimates are reused only within the current load's solve.
Each new load still passes the same refinement gate; previous loads do not select
a different answer. Short kernels remain serial; this does not need worker startup.

`cached_variable_flexure` uses the existing cache, source/runtime identities,
single-flight and cheap-work bypass. The key includes exact pressure bytes,
profile, operator and accuracy, with SciPy/LAPACK execution identity. Cache and
fresh routes return identical response and convergence metadata. W03 restore plus
the same explicitly reconstructed profile/surface/exterior inputs reproduces IDs;
old source seals are not repinned. Profiles are not silently recovered from results.

Factor construction, retained ownership and response workspace use shared byte
admission, composing explicit per-call budgets. `close()` releases factors. Crops
are detached from halo buffers. Cancellation is checked between bounded mesh
operations, not by interrupting a native Cholesky call. Accounted bytes are not a
process RSS limit. See [focused checks and measured savings](#variable-rigidity-evidence).

#### Papers and software reviewed before selection

- [Wickert (2016), gFlex v1.0](https://gmd.copernicus.org/articles/9/997/2016/),
  full-text section 2.2, equation 9 and boundary discussion: selected the
  conservative variable-rigidity equation and explicit boundary meaning.
- [TU Delft, Euler-Bernoulli beam](https://interactivetextbooks.citg.tudelft.nl/computational-modelling/structural_linear/euler_bernouilli.html),
  weak/discrete form, equations 4.14-4.43: selected C1 Hermite interpolation and
  source-aligned material stiffness rather than differentiating noisy D arrays.
- [Wieckowski and Swiatkiewicz (2021), Materials 14, 460](https://mdpi-res.com/d_attachment/materials/materials-14-00460/article_deploy/materials-14-00460.pdf),
  independent review of section 2.1 and the section 6 opening: cross-checked the
  Winkler foundation and four-degree-of-freedom Hermite formulation.
- SciPy's [banded Cholesky](https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.cholesky_banded.html)
  and [factor reuse](https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.cho_solve_banded.html)
  documentation: selected compact SPD factorisation/repeated solves over dense
  matrices or a generic sparse solve per snapshot.
- LAPACK [DPBRFS](https://www.netlib.org/lapack/double/dpbrfs.f)
  and the deterministic sign/coordinate norm-estimation approach used by
  [DLACN2](https://www.netlib.org/lapack/explore-html/d6/d2d/group__lacn2.html):
  selected residual-plus-rounding forward-error estimates and explicit distinction
  between an estimated error and a rigorous bound. The implementation estimates
  the physical output operators rather than only the solution-vector norm.

These are paper/documentation reviews, not external gFlex execution, external
source-code audits or measured superiority to another terrain generator.

<a id="variable-rigidity-evidence"></a>

#### Obtained variable-rigidity evidence, 22 September 2026

The fixed source-linked rigidity route passed 41 distinct focused Windows
tests: eight variable-flexure (0.033 s), then five new workflow/six retained
finite/thirteen periodic/nine identity controls (33 tests, 39.012 s). Selected
test_w04_variable_flexure, test_w04_variable_workflow,
test_w04_regional_workflow, test_w04_workflow and execution IdentityTests used
Python 3.12.14/NumPy 2.4.6/SciPy 1.17.1, one thread.

Independent arbitrary-D equilibrium, two-material eight-coefficient continuum
solution/curvature jump, uniform Green refinement, periodic translation/mean,
reflection/exterior extension and same-D/different-Te strain check the conservative
Hermite route. Actual W03 boundary/halo/owner/source joins, total-reference output,
cache/restore parity, one-shot equivalence and lifetime/resource/refusal controls
pass. Continuing variable D requires exact declared exterior loads; omitted-pressure
uncertainty refuses. Mesh-change estimates and diagnostic third derivatives are
not continuum certificates; no evolving-D/2D/field-calibrated feedback is implied.

Review found slower curvature than displacement convergence. The default permits
six refinements within existing element/resource limits, replacing four; the
tight 1e−4 oracle explicitly permits seven, without widening accuracy gates.
Even-subdivision centre traces now average both internal FE traces to preserve
reflection, while genuine source/material interfaces stay one-sided. Far-load
nonzero-underflow checks, construction/factor overlap admission, composed budgets
and cancellation through fresh/cache/mesh paths were corrected.

[Raw factor-reuse timings](../evidence/w04-variable-timing.json) compare twelve
changing loads over 512 cells/400 km/three Te regions (1/2/4 km), three alternating
repetitions. Both include cold preparation, refinement/validation/diagnostics/
admission/output/close after the same native warm-up. Rebuild median
0.039662400028 s versus retained profile 0.020635399967 s saves 0.019027000060 s
(47.97238706%). Responses and mesh-gate metadata are bit-identical; accepted meshes
have 2–8 subcells/cell. Maximum factor capacity is 1,352,512 bytes/accounted peak
18,465,600, not RSS; all reservations release. Entry:
python -B tectonics/tools/benchmark_w04_variable_rigidity.py --output NEW.json.

The [complete original report](https://github.com/Atlantispy/atlas/blob/1f1d78a6dd2ab3d1c533af9f9b5b79e769ce57fd/tectonics/evidence/w04-variable-rigidity.md) retains exact
source identities, static checks and reviewed gFlex/Hermite/Winkler/SciPy source
extent. Unchanged uniform finite evidence was reused. No cache hits/workers/W03
evolution/context are timed; no old-release/whole-world speed or Linux/scientific/
empirical acceptance follows.
