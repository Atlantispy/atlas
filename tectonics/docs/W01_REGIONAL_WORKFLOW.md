<a id="stage-7-workflow"></a>

# W01 sampling, motion and regional material workflow

Implemented 22 September 2026.
This connects the supported S5/S6/W02 route, not whole-W01 scientific acceptance.
The subsequent [Stage-8 assessment](#stage-8-combined-acceptance) checks this
assembled route. Reopened S3C acceptance, unrestricted spherical dynamics and
R4.4 remain separate. No long simulation was run to implement this bridge.

The sections also describe the [initial sampler](#initial-condition-sampling),
[prescribed-motion forcing](#prescribed-motion-to-regional-forcing) and the
[plate-independent R2 substrate](#3cr2-initial-state). Each retains its own
support and acceptance limits.

## Public workflow

`PreparedRegionalWorkflow(initial, definition, section, reduction, grid, support)`
takes an `InitialConditionState`, the existing S6 motion records, a uniform
`RegionalGrid1D` and an explicit `RegionalColumnSupport`. It builds the cell
footprints, obtains S5 intersection inventories, constructs W02 material cohorts,
and prepares source-bound face velocities. Callers do not assemble numerical
inventory arrays. Sources, material definitions, formation times, cooling history,
unknown masks and the original geological description remain accessible through
`state.initial_samples.state`.

```python
with PreparedRegionalWorkflow(initial, motion, section, reduction, grid, support,
                              budget=budget) as plan:
    start = plan.initialise()
    end = plan.advance(start, left=left_boundary, right=right_boundary)
    save_regional_workflow(end, store, budget=budget)

restored = load_regional_workflow(store, end.workflow_id, budget=budget)
with PreparedRegionalWorkflow.from_state(restored, budget=budget) as plan:
    # Only if some of the ORIGINAL frozen forcing interval remains:
    continued = plan.advance(restored, left=left_boundary, right=right_boundary)
```

An omitted duration advances to the original S6 endpoint. A supplied positive
duration can cover a prefix. The unchanged W02 adviser determines substeps;
the default remains MUSCL/Numba, with no numerical fallback or interval extension.
Boundary reservoirs/composition must be explicit, including all required inflow.
Each accepted step retains its parent, cohort exchanges and numerical receipt.
`initialise()` always returns the original root, not the latest advanced state.

Run the complete authored example, from the repository root:

```text
python -I -B tectonics/tools/run_w01_workflow.py
python -I -B tectonics/tools/run_w01_workflow.py --benchmark --output s7-timing.json
```

The example uses two explicitly synthetic rocks, three geological strips and
32 solver cells. It verifies a 24 m3 initial inventory and evolves 0.025 seconds.
It installs/downloads nothing; `--output` refuses to overwrite existing evidence.

## Meaning of the conserved quantity

For cohort k and numerical cell i:

`q[k,i] = sum(actual S5 phase intersection volumes[k,i]) / (ds * reference_width)`.

Hence `sum(q * ds * reference_width)` is the retained volume. Stable grouping
with compensated summation preserves small mixed-fragment contributions. There
is no re-normalisation of authored fractions or implicit density/porosity law.
W02 calls q "partial thickness"; in the spherical route it is an equivalent
inventory per reference area, **not raw radial thickness**. W02 exchange receipts
are per unit reference width (m2); multiply by the declared width for m3.

Planar support is a straight strip centred on the declared section, of explicit
reference width and initial depth band. Its complete footprint must lie inside
the regional topology. Every intersecting owner must have compatible full
relative-motion coefficients, not merely the same projected speed at a centre.
S6's continuous-section discontinuity checks are still mandatory.

Spherical support is a complete north- or south-hemisphere longitude wedge about
the section's declared pole, bounded by great-circle meridians and the equator.
Axial relative Euler rotation preserves that transverse support. Surface area is
`R * ds`; shell volume is `ds/R * (r_outer^3-r_inner^3)/3`. S5 uses stable shell
arithmetic, not surface area times depth. For R=10 m, depths 0–2 m, width=10 m,
q=122/75 m, not 2 m. The two hemispheres are separate supported queries, not a
general finite-latitude strip or a two-dimensional spherical mechanics model.
Changed/unsupported owner motion anywhere inside a wedge is refused.

Explicit pore phases require `PoreFluidCohort(unit_id, cohort, source)` mappings.
Different units can share an explicitly identical fluid history or retain
different origins. No fluid age/origin is invented from a material name. Bulk
reference materials keep their declared intrinsic-pore uncertainty; this bridge
does not claim to resolve unknown true solid volume, heat or in-situ mass.

## Initial temperature is not evolved temperature

Initial profiles, source conditions, volume-weighted temperatures and validity/
known masks survive every step and restore. Their label remains **initial epoch,
not evolved heat or temperature**. No temperature advection, thermal density,
compaction, relative fluid motion or new W03 physics is implemented here. Carried
formation/cooling provenance must not be interpreted as a current thermal field.

## Reuse, restoration and bounds

One preparation is reused across consecutive steps or independent scenario
branches. Initial samples/forcing are shared immutable objects; history is a
linked sequence, not repeatedly copied into each new state. Persistent transport
reuse uses the existing `ArrayStore` and `CachePolicy`; no extra scheduler/cache
service, compression format or worker pool is added. Dependent time steps remain
sequential. Parallel workers would add overhead to the bounded example.

Snapshots save dependencies before their workflow nodes. Restoration checks
source/runtime, whole-footprint geometry and S5 plan binding, initial inventory,
every parent/time/velocity/policy binding and cohort balance receipt. It does not
re-sample geology or re-evolve the material. Existing integrity checks are not
proof against a hostile Python runtime or a substitute for scientific validation.
The new modules join the live-callable execution identity inventory. Changed
source requires a new run; historical runs are never automatically rebound.

The wrapper accepts at most 4,096 cells, 4,096 cohorts and 256 cumulative steps,
subject also to existing geometry/sampling, byte-budget and numerical limits.
These are finite engineering bounds, not a tested capacity claim. Plans admit
retained descriptions, topology, samples, velocities and execution state;
advances admit their candidate history. Returned snapshots transfer ownership to
the caller. `WorkBudget` is an allocation-admission estimate, not an RSS ceiling.
Cancellation is checked through preparation, aggregation and each substep.
Unrepresentable clocks/metrics, exhausted budgets, changed bindings, unsupported
interfaces, incomplete inflow and off-section movement are refusals, not silently
repaired outputs. A failed advance publishes no partial workflow result.

## Method references

The official [Geodynamic World Builder painting model](https://gwb.readthedocs.io/en/latest/user_manual/concepts/painting_in_the_world.html)
and [2D section documentation](https://gwb.readthedocs.io/en/latest/user_manual/basic_starter_tutorial/18_2D_models.html)
(manual 1.2.0-pre, accessed 22 September 2026) support separating source geometry,
feature precedence and numerical queries. Their point-query model is not proof
of conservative cell integration.
[ASPECT particle properties](https://aspect-documentation.readthedocs.io/en/latest/parameters/Particles.html)
(3.2.0-pre) distinguish initial composition/position/generation time from evolving
properties. [Kritsikis et al. (2017), sections 2, 3.4 and 4.3](https://gmd.copernicus.org/articles/10/425/2017/)
support intersection-based conservative spherical remapping and reuse of fixed
geometry. The shell-volume reduction above is derived for this restricted
workflow; that paper does not validate its physics. No external code/dependency
was copied or added.

Focused verification and measured timings are recorded in
[Stage-7 evidence](#obtained-stage-7-and-8-evidence-22-september-2026).

## Stage 8 combined acceptance

The 22 September 2026 assembled assessment is **PASS_SUPPORTED_WORKFLOW**, while
`whole_W01_status = INCOMPLETE` and `whole_W01_complete = false`. A successful exit
reports technical qualification of supplied geology and supported motion, not
generated geological realism. Reproduce its bounded selection with
`python -I -B tectonics/verify.py --w01`; `verify.py:W01_GATES` owns the selections
and `cases/w01_acceptance.json` the assumptions. The emitted record retains every
test, elapsed time, source hashes before/after and runtime. Failed, skipped,
empty or drifting selections cannot pass; no unrelated convection campaign runs.

The gates cover rigid/rotation/frame/epoch/pole/seam representation; shared and
reversed traces; initial thermal limits; actual mixed-cell volumes, refinement,
unknown masks and whole-fragment validity; continuous sections and complete
footprints; original frozen intervals, per-cohort conservation and exterior
accounts; and material identity independent of plate identity. A nonzero axial
transport case crosses 180 degrees and restores complete shell/reference-volume,
source, thermal and history records. Nonuniform MUSCL native/reference fields and
accounts meet unchanged material tolerances; the independent upwind witness does
not replace the default.

Cache invalidation covers changed boundary/interval/metric/geology/code. A fresh
process restores and continues; interruption after a cached substep preserves the
accepted checkpoint, without pretending a pure cache entry is an accepted state.
Assembly found preparation leases ending while their outputs remained live: staged
reservations now persist until prepared ownership takes over and release on
failure/cancellation. Handover briefly admits both scopes conservatively without
lifetime double charging. Restore enforces the existing 4,096-cell bound before
geometry allocation. `WorkBudget` remains admission accounting, not an RSS cap.

No physical kernel, material policy, tolerance, transport default or 256-step
ceiling changed. Source changes received new identities; old runs were not
rebound. All 5,819 PB2002 rows already had source/Euler consistency checks;
bounded scale-matched shape measurements describe differences rather than prove
generated dynamics. Generated plate realism remains **REOPENED**; R4.4 is held/
incomplete. R5–R9 include unimplemented process/spherical-generation capabilities,
not failed S5–S7 tests. Unrestricted spherical mechanics, W03 evolved heat/
compaction, unsupported interfaces and whole-world performance remain outside
this assessment. R4.4 is not needed to use the supported described-state route.

[Stage-8 results](#obtained-stage-7-and-8-evidence-22-september-2026) and
[bounded shape validation](#bounded-shape-validation-and-limits) retain their
original identities. The [complete original assessment](https://github.com/Atlantispy/atlas/blob/1f1d78a6dd2ab3d1c533af9f9b5b79e769ce57fd/tectonics/docs/W01_COMBINED_ACCEPTANCE.md)
retains the exact gate table and repair chronology. No new timing comparison or
multi-day simulation was made; Stage-7 timing remains bound to its own workload.

## Obtained Stage 7 and 8 evidence, 22 September 2026

Stage 7, added locally to `c8b876c92b95ad8d4bc3d3fda8b8f94de6f1b84e`, passed 38
focused Windows tests: 22 workflow in 44.798 s and sixteen geometry/shared identity
in 5.086 s. Mixed inventories, explicit fluid history, complete-cell/hidden-interface
refusals, both hemisphere shell volumes, original intervals, cumulative step budgets,
initial-temperature unknowns, cancellation/budgets and immutable outputs were covered.
Warm cache hit called no transport kernel; restoration called no S5 sampler.
Rehashed snapshots with altered support or foreign velocity histories refused.
Review repaired missing live-code registration, incomplete restore geometry/
velocity/accounts, retained-description admission and inventory-loop cancellation.
The failing live-code regression and pre-correction eighteen-test result remain
history, not added to the final count.

Three matched alternating pairs of four independent branches on the same 32-cell,
two-cohort, 0.025 s fixture measured setup reuse, with candidate setup included
and complete workflow/parent/receipt identities equal. Fresh median
3.346319300 s → shared 1.194844900 s saved 2.151474400 s (64.293757%). Shared
peak admitted estimate was 6,041,795 bytes, not RSS, and released to zero. First
native advance (3.885875400 s), authored setup and first plan were excluded equally
and recorded separately: this is **not cold one-off saving**. The final successful
comparison excluded concurrent tests. An overlapping development measurement and
a later denied output-file write were not used as timing evidence. Entry:
`python -I -B tectonics/tools/run_w01_workflow.py --benchmark --output NEW.json`.

Stage 8's `verify.py --w01` passed **71 tests in 54.571858800 s** with no failures,
errors/skips and identical before/after inventory. Counts: twenty representation/
thermal, four initial inventories, 29 workflow/geometry/recovery, six new assembled,
nine shared identity and three status. The separate development six-test run is
not added. Its axial wedge witness has R=10 m, 0–2 m shell, width 10 m,
volume 244π/3 m³ and q=122/75 m; two-cell 0.1 m/s transport for 0.25 s with inlet
2q gives `[q*(1+0.01/pi),q]` and q/4 m³ inflow. Nonuniform MUSCL compares actual
reference/native fields/accounts without demanding backend IDs coincide. Changed
inlet/interval/width cannot hit the wrong cache; cancelled cached substeps do not
masquerade as accepted workflow state. Preparation leases and restore's 4,096-cell
guard were repaired as described above, without changing kernels/gates/ceilings.

Both used Windows/Python 3.12.14, NumPy 2.4.6, SciPy 1.17.1, Shapely 2.1.2,
Numba 0.65.1 and one numerical thread. The
[original Stage-7](https://github.com/Atlantispy/atlas/blob/1f1d78a6dd2ab3d1c533af9f9b5b79e769ce57fd/tectonics/evidence/w01-stage7-workflow.md)
and [Stage-8 reports](https://github.com/Atlantispy/atlas/blob/1f1d78a6dd2ab3d1c533af9f9b5b79e769ce57fd/tectonics/evidence/w01-stage8-acceptance.md)
retain exact commands/test IDs/source/runtime/output identities and static results.
No full suite, release, source repin, new physical law or whole-world/R4.4 campaign
is established by those technical passes.

## Bounded shape validation and limits

The later wording/driver change reused unchanged 71-test package results and
reran only the three affected status methods, not 74 distinct checks. Fixed
seeds 41/42/43, twelve area-ranked plates and 512 supports were measured without
fitting, seed selection, raised resolution or tolerance change. All 36 outlines
matched two independent spherical-area formulae/patch sums: maximum discrepancy
1.5543122344752192e−15 sr, closure 1.7763568394002505e−15 sr, versus the unchanged
2e−11 sr bound. Area L1 errors 0.00826755/0.00918161/0.00710941 were below 0.04.
A declared 52-plate/1,024-support case **refused** unresolved small plates without
a generated result. Total driver 7.116067 s and 96,041,175-byte admission estimate
are validation cost, not speed/RSS. Its deadline was cooperative 120 s/case.

Matched 100/250/500 km sampling and two phases yielded 72 paired records/scale,
not independent Earth observations. Candidate mean compactness differed
−7.6593%/−12.2353%/−14.5058%; inward-turning differences changed sign with scale.
These are descriptive mismatches, **not accuracy percentages or new thresholds**.
Largest-twelve area renormalisation was 1.0736633528442074; ~1,753–2,175 km
segments and 2–3 poorly resolved small ranks cannot acquire 100 km detail through
resampling. All records, including poor resolution, remain. Higher-resolution
behaviour is not inferred. Withheld PS is a within-PB2002 diagnostic; restricted
MS/ON/Peru geometry was not used.

All 5,819 prescribed-motion rows, including 766 withheld rows, already passed
source-derived position/normal/pole rounding checks; maximum raw component
differences 4.77449/1.94575 mm/a are not judged by the old twelve-row 0.2 mm/a
excerpt allowance. That verifies Euler reconstruction, not force-derived history
or generated realism. Whole-W01 realism stays REOPENED/incomplete; R5–R9 contain
unimplemented science, not failed tests of this described-state bridge. Entry:
`python -I -B tectonics/tools/measure_w01_plate_shapes.py`.

## Historical physical/reference corrections and bounded outcomes

The [complete bounded-validation report](https://github.com/Atlantispy/atlas/blob/1f1d78a6dd2ab3d1c533af9f9b5b79e769ce57fd/tectonics/evidence/w01-bounded-validation.md)
retains every original measurement, identity, source review, refusal and correction
below. These additional reduced-model results do not make W01 or R4.4 complete.

Tosi/ASPECT review supported warm-upward sign and an independent continuum
constant-viscosity velocity/pressure/work oracle. Case-5a Phi/Ra became an explicit
**derived project interpretation**, retaining printed values/labels and
`author_confirmed:false`; no author erratum was obtained. ASPECT integrates raw
dissipation/work separately then scales the former for comparison. Periodic
dissipation extrema were wired into the analyser without a second division.
The initial universal ten-contributor rule was superseded: cases1–5a retain ten,
case5b uses nine documented same-equation codes. Empty/missing/replaced/nonfinite
reference rows and changed mappings fail closed. No mature Atlas output selected
the interpretation, and no acceptance tolerance was widened.

Earlier supplement retrieval failure was resolved when Michael supplied the
30-page S1 PDF, SHA-256
817c1ebe44a5f9be45aa716416137e1f9a9d39c5840cac60e5540dba6ac09842.
Tables S14–S23/pages21–30 were extracted with pdfplumber and independently
cross-checked with pypdf; introduction/table pages were rendered/inspected.
Ten tables/626 printed min-max pairs preserve decimal strings, nulls, yield/grid
coordinates and upright-steady versus italic-periodic regime. Unequal printed
numbers do not establish periodicity (GAIA 100×100/yield3.8 is a retained steady
counterexample); code disagreements are not pooled. MC3D data remain excluded
from same-equation comparison, and ELEFANT rows are not invented. Select each
code's finest published exact-yield column with no missing-grid fallback;
SOURCE_ABSENT is not zero. Independent Atlas mesh/time/nonlinear/regime studies
and ten-complete-cycle minimum/maximum averaging remain required, with the original
0.5% envelope margin. Runtime needs only bound 25,270-byte JSON/stdlib, not PDFs.
The runner sibling-import seam was fixed and subprocess-tested. Final reference
verification passed 57 focused plus two four-step 4×4 driver checks; empty
preflight still reports INCOMPLETE_R4_4 rather than mature acceptance.

Windows raw export first gained explicit RAW_DATA_ONLY/NOT_RENDERED, preserving
actual fields/history and source/state metadata without plotting imports. Missing
plot dependencies refuse before run reading/output creation; mocked six-plot
calls were not a real render. The later Matplotlib3.11.2 installation preserved
existing solver versions/execution identity, and five real Agg checks produced
six decoded/hash-matched images plus exact raw-array parity. Three figures were
directly inspected for readable consistent axes/data. All images alone still do
not grant visual/scientific acceptance; suite visual acceptance requires raw plus
all six plots and actual inspection. Display is nearest-neighbour original arrays,
not one pixel/cell. Corrected-source Linux rendering remained unverified. Commands
are the existing visual_convection_r4_4.py with explicit new output, optionally
--raw-only; these historical installations supply no new install authority.

The later mechanical correction applies compatible MAC solenoidal reconstruction
only when constant-viscosity MINRES relative divergence exceeds four binary64 eps
(internal trigger, not relaxed acceptance). Cross modes retain circulation, axis
compressible modes are removed and p_new=p_old−Dv preserves momentum. Direct/
variable-viscosity solvers, genuine tiny-flow/compressible refusal and published
gates remain. Two old analytic tests expecting bit-exact normal MINRES values were
corrected to the actual two-ULP/four-eps independent oracle; subnormal/underflow
contracts did not loosen. Compaction/material transport separately introduced
cohort-partial-thickness-regional-v2, jointly limiting component slopes against
scalar total at both SSP-RK2 stages, with conservative per-component flux and no
post-update normalisation. Single-cohort/upwind and ALE/remap remain separate.
Workspace/compiled identity includes both stages and the new helper; old history
is not silently rebound.

Fresh predeclared three-case Windows controls then passed in 12.249925 s, including
compilation/I/O/plots/source checks but excluding imports/setup. Manufactured
variable-viscosity mechanics refined at ratios 4.005–4.164 within original 3.7–4.5;
work errors 0.970146/0.241899/0.060435%. Hydrostatic 20×10 km cooling with 80 K sine
perturbation reached 5e12 s on 16×8/32×16/64×32 grids: RMS 0.217176/0.0546381/
0.0136811 K, finest max 0.01932463 K, timestep difference 2.27374e−13 K, heat ledger
relative residual 4.06e−17. Conservative two-cohort transport closed 13/11 m³ within
1.78e−15 m³ and total thickness within 5.55e−16. Front mean errors decreased
0.164554/0.099247/0.059953 m (orders ~0.73), while maximum jump errors increased:
no discontinuous pointwise shape acceptance or misapplied smooth second-order gate.
Plots retain visible smearing. Twenty-one snapshots/raw fields/ledgers/manifest
were retained locally; lossless store 299,008 bytes restored final IDs, admitted
peak 75,992,824 bytes/final zero (not RSS). The unavailable earlier chat ZIP was
not authenticated or replayed. These analytic Windows controls do not establish
empirical geology, mature convection, terrain realism, Linux or whole-world scope.

<a id="initial-condition-sampling"></a>

## Initial-condition sampling

Status: implemented and optimised for the declared Stage-4 geometry and geological
representation. This is a representation/sampling stage,
not a plate-history simulation or independent scientific acceptance. The later
[motion adapter](#prescribed-motion-to-regional-forcing) and [assembled regional workflow and
Stage-8 assessment](#stage-7-workflow) retain their own bounded scope;
the separate unfinished R4.4 acceptance campaign is unchanged.

### Entry point

Use `InitialConditionState(case, origins=..., cooling_history=...,
material_bases=..., library=...)` with an existing `GeologicalCase` on a regional
`BoundaryNetwork`, planetary `SphericalAtlas`, or plate-independent
`GeologicalDomain`. Then use the existing `PreparedPrecursor` sampler:

```python
from atlas_tectonics import InitialConditionState, PreparedPrecursor

state = InitialConditionState(
    case, origins=origins, cooling_history=cooling_history,
    material_bases=material_bases, library=library,
)
request = dict(frame_id=state.sampling_domain.frame_id,
               epoch_id=case.epoch_id,
               depth_reference_id=case.depth_reference_id)
with PreparedPrecursor(state, budget=budget) as sampler:
    points = sampler.sample_points(xy_or_directions, depths_m, **request)
    cells = sampler.sample_cells(query_cells, **request)
```

Origins, cooling histories, volume conventions and any missing-data explanations
are input records, not inferred numbers. Source-bound Earth reference materials
require the actual matching `EarthMaterialLibrary`. `PrecursorState` retains its
strict plate-independent contract; the new state has a distinct schema identity.
No sampling mesh, intermediate temperature array, or W02 evolving state is
required to describe the original geology.

### What is sampled

- Fixed geological features: original case/topology, province and layer IDs,
  material/cohort/source identity and explicit precedence are retained. Plate and
  region selectors expand into references to every constituent region/patch;
  neither plates nor geological features move when the query grid changes.
- Points: exact supported membership, all matching provinces in precedence
  order, winning unit, weak-zone associations, initial temperature and requested
  scalar fields. Shared seams retain all applicable memberships. Depth bands
  are top-inclusive and bottom-exclusive. Planar coordinates are metres;
  spherical inputs are direction vectors, with radial depth in metres.
- Cells: actual polygon-prism or spherical shell-sector intersections are split
  by province, layer and optional body. Sparse rows contain bulk, matrix, pore,
  cohort and material volumes. Cell temperatures are volume-weighted integrals,
  not centre samples or heat inventories. Spherical volumes use the radial
  shell metric, not surface area multiplied by depth.
- Reference mass: explicitly request `reference_mass_temperature_k`. Only
  positive-volume contributing materials must provide density at that reference
  temperature. Unused unknown catalogue entries cannot block a valid inventory.
  The result is **reference mass**, never hot/pressurised in-situ mass.

Weak zones preserve declared membership and precedence, not an invented averaged
damage law. Fault ribbons retain their original trace/dip/depth descriptions in
the case; they do not acquire slip, material or meshed fault surfaces by sampling.

### Validity and missing data

Point temperatures are checked against every active solid and pore-fluid
`valid_temperature_k` interval. Cells check the whole fragment temperature
envelope, including tabulated interior extrema and any temperature offset; a
valid average cannot conceal an invalid interior. Bounded spatial-prior offsets
use a conservative envelope and refuse an uncertifiable cell instead of silently
accepting it. Unknown validity intervals remain visible through
`material_temperature_validity_known`; this mask is not approval of a
temperature/pressure-dependent constitutive law.

Unknown point temperatures have a separate known mask and require explicit
`require_temperature=False`; the `temperature()` accessor still refuses them.
Unknown porosity cannot produce a fabricated solid/pore inventory. Cell queries
may explicitly omit temperature using `include_temperature=False`. Missing scalar
fields, incompatible frames/epochs/depth references, unsupported depths, thermal
extrapolation and out-of-range materials are refused, not filled with defaults.

### Reuse, resources and storage

The existing prepared geometry indexes, shared immutable units, bounded thermal
reuse, work/memory limits and ordered executor are retained. Topology selectors
are resolved once with a finite link envelope. Exact topology-owned spherical
faces reuse already-validated disjointness, avoiding impossible cross-horizon
unions; repeated faces still require non-overlapping depth bands. Arbitrary query
polygons use the existing overlap checks. Worker choice does not change sample
identity or numerical policy. No new dependency, scheduler or storage service
was added.

The measured optimisation pass also prepares immutable layer boundaries and
active-material temperature-limit intersections once per plan. Repeated cell
footprints reuse a query-local, memory-admitted routing cache (at most 1,024
entries); unique footprints are not cached. Depth, geometry, precedence and
material checks still run. Long thermal tables select interior knots with
binary searches and interpolate them in one vector operation, preserving the
original segment formula and summation order instead of repeatedly converting
the full table for every segment. No approximation or reduced precision is
introduced, and no mutable query cache is shared between workers.

`save_precursor_state` / `load_precursor_state` also round-trip the explicitly
typed `InitialConditionState`. `save_initial_samples` / `load_initial_samples`
retain the original case, topology, material library, source/history definitions,
query geometry and numerical arrays in the existing verified, lossless,
deduplicated `ArrayStore`. Restoration does not regenerate a world or substitute
the current source for a historical execution binding. The sampling method is
now `atlas.precursor-sampling.v3`; changed source is a new execution identity.

### Deliberate representation boundaries

Stage 4 supplies constant-depth layers and explicit body bands, not arbitrary
3-D geological interfaces. Geometry remains planar or conditioned minor-arc
spherical patches; a whole sphere is represented by its actual patches, never
one fictitious polygon. General spherical cell averages of Cartesian cosine
priors remain explicitly unsupported; spherical point priors, radial thermal
means and material inventories are supported. This implementation does not
silently approximate an unsupported mean.

Motion-to-regional forcing is Stage 6; W01-to-W02 initialisation/evolution is
Stage 7; assembled scientific/resource/cache/restoration assessment is Stage 8.
Their implemented supported routes are documented at the links above; Stage 5
alone does not establish them. No R4.4 run or whole-world physical simulation is
needed to test Stage 5 representation contracts.

### Focused verification

From the repository root with the existing compatible environment:

```text
python -I -B -c "import sys,unittest; sys.path[:0]=['tectonics/src','tectonics/tests']; suite=unittest.defaultTestLoader.loadTestsFromNames(['test_w01_initial_sampling','test_precursor_sampling','test_precursor_contracts','test_precursor_execution','test_precursor_scaling']); r=unittest.TextTestRunner(verbosity=1).run(suite); sys.exit(not r.wasSuccessful())"
```

The new tests cover regional plate/region selection, seam membership, mixed-cell
and refined inventories, missing data, material temperature limits, original
topology restoration, whole-sphere face inventories and serial/threaded parity.
Existing R2 tests retain the analytic geometry, thermal, resource, cancellation,
source-invalidation and storage checks. These are small synthetic fixtures, not
an Earth calibration or a claim about consumer whole-world execution time.

Recorded 21 September 2026 on Windows / CPython 3.12.14: the final optimised
implementation passed **185 focused tests in 33.343 s**. Two additional tests
then integrated an independent advisory review's six rational planar/spherical
mean expectations and one-ULP extrapolation refusal. Those two plus the existing
interior-temperature validity regression passed in **0.288 s**: **187 distinct
focused tests passing**, with unchanged production checks reused rather than
rerun. No failures remain in this selected scope. The independent expectations
come from affine areas and polynomial antiderivatives, not a copy of the
production segment formula. Static coding-safety and diff checks also passed;
the safety-tool suite had 30 passes and one Windows symlink-permission skip
(0.144 s).
This is not an all-Atlas test run or scientific acceptance.

### Measured optimisation scope

The baseline is the implemented, pre-optimisation Stage-5 package derived from
dev42 (`82ef5b69f08ab904a4b6ca84d4fb624ba139d51b`), not pristine dev42 (which
lacked the new entry point). Both full package source inventories and the
benchmark script were hashed; source stability was checked during each run.
The baseline sampler SHA-256 is
`f6f3b6142940f1b3a5211243d7507749163d202a42b6e21b00602b6fc42e515d`.

Same-machine, three-call medians, one numerical native thread and serial query
execution. Times cover each complete query, including admission, validation and
result construction; **plan setup is separate**. Profiles are excluded from
timed calls. Windows, CPython 3.12.14, NumPy 2.4.6, SciPy 1.17.1, Shapely 2.1.2.

| Synthetic workload | Before (s) | After (s) | Saved (s) | Less query time |
|---|---:|---:|---:|---:|
| 100,000 points; 256 layers | 0.139224 | 0.131647 | 0.007577 | 5.44% (inconclusive) |
| 64 cells; 128 layers | 0.295600 | 0.137684 | 0.157916 | 53.42% |
| 24 cells; 2,049-knot thermal table | 3.908962 | 0.071906 | 3.837055 | 98.16% |
| 84 planetary patches; 8 depth bands each | 0.174549 | 0.071818 | 0.102731 | 58.85% |

Point-call ranges overlap; no reliable point-sampling speed-up is established.
The three cell-query ranges do not overlap in these runs. This is a bounded
comparison, not a confidence interval, whole-generator percentage or projection
of R4.4/whole-world evolution. The thermal-table gain addresses repeated work
that grows quadratically with table length, not a reduction in thermal fidelity.

For a one-off query, the separately measured plan setup plus first query was:

| Workload | Before (s) | After (s) |
|---|---:|---:|
| Points | 0.250985 | 0.254488 |
| Layered cells | 0.398323 | 0.230348 |
| Thermal-table cells | 4.047245 | 0.161058 |
| Planetary depth bands | 0.281309 | 0.163481 |

These are single cold observations, not medians; input-fixture construction is
recorded separately. All **263 output arrays were independently checked as
bit-for-bit identical** across the four matched workloads. Every resource
reservation was released; no memory refusal or tolerance relaxation occurred.

The reproducible driver is `tectonics/tools/benchmark_w01_sampling.py`:

```text
python -I -B tectonics/tools/benchmark_w01_sampling.py --source BASELINE_SRC --output BEFORE
python -I -B tectonics/tools/benchmark_w01_sampling.py --source tectonics/src --output AFTER --compare BEFORE
```

Use a source directory containing `atlas_tectonics` and fresh output directories.
The driver retains raw repetitions, setup, source hashes, arrays and resource
accounting in each output directory. Frozen local baseline/evidence are retained
by the engineering task; no private paths or coordination records are published.

<a id="prescribed-motion-to-regional-forcing"></a>

## Prescribed motion to regional forcing

**reviewed and integrated locally on 22 September 2026.**
The source basis is the supplied dev42 + implemented/optimised Stage-5 snapshot.
This stage supplies prescribed kinematic input; it does not derive forces,
stress, uplift, temperature, damage or mantle evolution from velocity.
Stage 7 material initialisation/evolution and Stage 8 acceptance remain separate.
R4.4's acceptance requirements and held status are unchanged.

### Gap and reused components

Existing `rigid_velocity`, coordinate-frame transformations and shared-boundary
kinematics describe point velocities and their sides. `regional.py` consumes
N+1 face velocities for N cells, but it does not certify that projection of a
plate velocity is a justified one-dimensional reduction. The new
`PreparedRegionalForcing` bridges that gap. It uses existing immutable validated
`BoundaryNetwork` or `SphericalAtlas` ownership, prepared geometry indexes,
SI/epoch validation, source/callable checks, WorkBudget and ArrayStore. It does
not replace the Stage-5 geological description or sampler.

### Public definitions and entry points

- `PrescribedPlateMotion`: named plate, parent frame and epoch, snapshot time,
  planar rigid or planet-centred Euler velocity, source and explicit units.
- `PlanarRegionalSection` / `SphericalRegionalSection`: an oriented section and
  its instantaneous reference-frame velocity in the same parent axes. Directions
  use the existing normalisation convention; geometry itself is not snapped.
- `RegionalMotionDefinition`: validated ownership snapshot, exactly one motion
  per plate, source, start time and positive interval in forward SI seconds.
- `RegionalReduction`: one of the two supported spatial reductions below and
  the explicit temporal rule `frozen-at-start` and positive `reference_width_m`
  defining the fixed transverse metric normalisation. There is no ignore flag or
  user-adjustable omitted-flow tolerance.

All authored fields are immutable and included in identity. `GeologySource`
retains authored/generated/synthetic distinctions; source kind is never inferred
from numerical values. Motion descriptions contain no query-grid samples or RNG.

```python
# definition, section and reduction are explicitly constructed typed inputs.
with PreparedRegionalForcing(definition, section, reduction, budget=budget) as plan:
    samples = plan.project(
        offsets_m, frame_id=section.frame_id,
        epoch_id=definition.epoch_id, time_s=definition.start_time_s,
    )
    forcing = plan.faces(
        grid, frame_id=section.frame_id, epoch_id=definition.epoch_id,
        start_time_s=definition.start_time_s, duration_s=definition.duration_s,
    )
    forcing.validate_boundaries(left=left, right=right)
    # forcing.face_velocity_m_s has exactly grid.cells + 1 values.
    # No material is initialised or advanced by this call.
```

All velocity/rate/length units are explicit `m/s`, `rad/s`, `m`; time is `s`.
Unspecified years, cm/year, angular degrees or cross-epoch/frame guesses are
refused. Use the existing TimeAxis/EpochOffset/frame conversions before making
a prescription, with their provenance recorded in the supplied source. Section
coordinates `s` increase from the declared origin; RegionalGrid1D.origin_m is an
offset along this section, not an unrelated global Cartesian coordinate.

### Reduction, reference frames and time

#### Planar columns

For a plate, `v(r) = U + omega cross (r - pivot)`. The section frame velocity is
`V + Omega cross (r - section_origin)`. Tangent, left transverse and up axes form
the local basis. All absolute, reference and relative components are returned.

Solver-ready planar reduction requires `omega - Omega == 0` and relative
translation parallel to the section with zero relative vertical velocity. Thus
there is no cross-section or vertical flux anywhere in the affine field, not
merely at the selected faces. A co-rotating frame can meet this requirement;
an unmatched planar rotation cannot. A velocity that happens to project to zero
cross-flow at one query is not sufficient. The represented quantity is column
thickness/inventory per unit transverse measure on the transect, not a finite-width
average of arbitrary laterally varying geology.

#### Spherical columns

The supported section is a strictly minor great-circle arc at reference radius R.
`r(s) = R (a cos(s/R) + t0 sin(s/R))`, `t0 = pole cross a`.
Along is the oriented great-circle tangent, cross-left is its pole, and up is
radial. The reference frame may rotate about the same sphere centre, but not
translate that centre. Solver-ready output requires the relative Euler vector
to be parallel to the section pole. Its material angular motion has no radial or
meridional component. The section speed is `ds/dt = R * relative_angular_rate`.
No Cartesian chord length is substituted for arc length.

The compatible regional conserved quantity is **volume-equivalent column
inventory divided by `(reference arc length * reference_width_m)`**, in metres.
It is NOT arbitrary raw radial layer thickness: a finite spherical layer has
radial/area metric factors. The width is an explicit fixed metric normalisation,
not permission to average an arbitrary nonuniform latitude strip. Stage 7 must
prepare a compatible material inventory using that declared metric; Stage 6
creates no material data. No
spherical finite-volume dynamics capability is implied by providing these speeds.

#### Bounds and temporal interpretation

The spatial test is conservative: every plate in the supplied topology must meet
the reduction, even an unqueried plate. For local work, supply an independently
validated regional topology crop; do not hide an incompatible owner by using a
coarse query grid. Directional zero tests use a fixed 64-binary64-epsilon bound
scaled by the products in the dot/cross calculation. This accommodates only
round-off in rotated directions, not an absolute physical m/s allowance. Tiny
unrepresented transverse velocities are still refused. Returned residual
components are not clipped or replaced by zero.

`frozen-at-start` explicitly holds the start-epoch spatial prescription and
ownership in section coordinates for exactly the requested positive interval.
This is the existing regional fixed-forcing time approximation, **not exact
finite Euler rotation, moving ownership geometry or automatic frame integration**.
Changing the interval, source, motion or topology requires another prescription.
No timestep is shortened, no future flow is extrapolated, and no temporal error
bound is inferred from a kinematic snapshot. General time-dependent forcing and
moving-grid evolution are unsupported here.

### Ownership, boundaries and refusal

`project` preserves all inclusive index hits and all owner-specific components.
`selected_rows == -1` indicates different plate owners without an explicit region
selection. Same-plate seams retain their region rows but have one plate motion.
Spherical membership inherits the established index's tiny boundary-predicate
band; all reported owners are retained. No nearest-owner fallback, geometry
snapping or velocity averaging is performed.

`faces` requires whole-section domain coverage, not just successful point queries.
A shared face can have one velocity when every sided along-component is exactly
equal, while retaining its multiple owner rows. A genuinely discontinuous
**interior** face is refused even if a caller selects one side: a contact/flux law
is missing. Full-section interplate seam intersections are prepared independently
of grid faces: an interior discontinuity between faces is also refused, including
a thin plate hidden behind identical endpoint velocities. The guard applies to
the requested grid crop, so a crop wholly within a compatible plate remains usable.
Network intersections use their existing domain chart. Atlas intersections use
finite great-circle arcs, stable short-edge normals and conservative angular
bounds; an ill-conditioned, nearly coincident pair of arc planes refuses output
rather than silently declaring no intersection. Exactly coplanar overlap is checked.
A discontinuous **external** endpoint can use an explicit region only
when that region covers the full adjacent section cell. This side validation is
supported on planar/conditioned spherical BoundaryNetworks. For a multi-chart
atlas discontinuous endpoint, a separately verified regional crop is required.

Nonzero external velocities are never zeroed for a closed boundary. The existing
regional validator refuses them; incoming material remains missing until the
caller supplies an explicit TransportBoundary reservoir. Neither the adapter nor
its renderer invents exterior thickness, density or material. A velocity array
alone does not authorise a Stage-7 geological evolution.

General relative planar rotation, frame tilt, transverse/vertical flow, nonaxial
Euler reductions, small-circle sections, sphere translation, arbitrary 3-D
sections, ambiguous discontinuous fluxes, unresolvable coordinate spacing and
wrong/missing units or epochs are explicitly refused for solver-ready output.
Projection remains available for supported diagnostic geometries with nonzero
residual components, but is not marked solver-ready.

### Reuse, ownership and restoration

The prepared object holds fixed immutable basis/affine transforms and region-to-
plate lookups, plus the existing spatial index. Independent velocity calculations
and face grouping are vectorised in bounded batches. `backend='reference'` uses
clear scalar arithmetic for the same complete query/index/validation path. It is
an equivalence/performance control, not an approximate fallback. No global
scheduler, mutable query history or new cache service is added.

Every request owns scratch, checks cancellation and verifies the current source
before and after work. Close refuses active readers; results own read-only byte-
backed arrays. WorkBudget bounds admitted storage, not total interpreter/GEOS RSS.
Captured output arrays become caller-owned after the temporary query reservation
closes. Limits and batch size control resource use, not physical tolerances.

`save_regional_forcing` writes the existing self-contained topology and one atomic
forcing snapshot to ArrayStore, using its established chunk checks/dedup/cache.
Identity binds the executable source/runtime, topology, full motion/source,
frame/epoch, interval, section geometry, reduction, ownership selection, query
grid and backend. `load_regional_forcing` reconstructs typed inputs, re-evaluates
the saved bounded kinematics and requires exact metadata, identity and array
agreement. Changed policy/source or missing/corrupt data is refused rather than
rebound. This is data restoration, not a dynamics restart or finite-time advance.

### Focused checks and compatibility witness

Run only the Stage-6 and affected selected tests documented in the review packet.
The new file is `tectonics/tests/test_w01_regional_forcing.py`. It contains
independent translation/rotation/frame/covariance controls, planar/spherical seams,
unit/epoch/refusal tests, grid/order reproducibility, unchanged geological
features, memory/cancellation/source checks and fresh-process restoration.

A direct synthetic witness supplies u=1 on all four faces of a three-cell grid,
cell width 1, dt=0.25, H=[1,2,3], and left incoming H=4. Existing upwind transport
returns H=[1.75,1.75,2.75], inflow 1 and outflow 0.75, in both reference and Numba
backends. This witness is not automatic Stage-7 initialisation, scientific
validation of a plate history or an R4.4 simulation.

### Local integration review and timing — 22 September 2026

Only the second chat candidate (`PreparedRegionalForcing`) was reviewed and
integrated. The first candidate was withdrawn, not layered underneath it. Parent
review found that the original face-only interface check accepted a coarse grid
which hid a discontinuity; the continuous-section guard above closes that gap.
Six focused regressions cover coarse/narrow plate interfaces, conditioned and
global spherical sections, coplanar ambiguity and a short rotated seam. Existing
atlas sum/difference normals and half-angle distances avoid cancellation there.
These changes are AI-assisted implementation work, not independent validation
of the selected geological model.

**200 distinct focused tests passed, no failures, errors or skips:** 50 Stage-6
tests in 24.419303 s; 150 selected dependency/Stage-5 checks in 10.497688 s. The
dependency checks preceded the final local arc-normal refinement; that change
was covered by the final 50-test Stage-6 run. The initial uncorrected 44-test
candidate also passed, demonstrating why those tests alone did not catch the gap.
No full Atlas suite, long simulation, Stage-7 run or R4.4 acceptance was attempted.

Reproduce the focused set from the repository root in PowerShell (configured
Python with the existing tectonics dependencies; no installation required):

```powershell
$env:PYTHONPATH="$PWD/tectonics/src;$PWD/tectonics/tests"
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
$env:NUMBA_NUM_THREADS='1'
python -B -m unittest test_w01_regional_forcing test_w01_coordinates.LocalFrameTests test_w01_coordinates.TimeTests test_foundations.RotationTests test_w01_boundaries.SharedPlanarTests test_w01_boundaries.SharedSphericalTests test_w01_spherical_atlas.AtlasQueries test_regional_transport.RegionalDefinitionTests test_regional_transport.RegionalMathematicsTests test_w01_initial_sampling.RegionalInitialSampling
```

The included benchmark compares the scalar and vectorised complete `faces()`
paths in this same implementation. It has eight ownership strips, 4,095 cells /
4,096 faces, 512-row velocity batches and a co-rotating frame. The corrected
fixture gives every plate the same admissible translation: unequal strip speeds
from the submitted benchmark would hide unsupported internal interfaces. Hence
the submitted 51.8% Linux result is not adopted as local integration evidence.

Five alternating pairs on Windows/CPython 3.12.14, NumPy 2.4.6, SciPy 1.17.1,
Shapely 2.1.2 and Numba 0.65.1, with one native numerical thread:

| Complete prepared query | Median seconds | Observed range seconds |
|---|---:|---:|
| Scalar arithmetic reference | 0.114567900 | 0.108651100–0.122100900 |
| Default vectorised arithmetic | 0.083489400 | 0.081923900–0.085701300 |

**0.031078500 s saved per query; 27.1267% less time (1.3722x).** Ranges did
not overlap. Every published numerical array matched exactly in all five pairs;
independent velocity and ownership expectations passed. Backend-bound IDs remain
different by design. Raw pairs, scalar/vectorised seconds respectively:
0.108651100/0.083489400, 0.111673700/0.083402800,
0.114567900/0.085424200, 0.122100900/0.085701300,
0.121746900/0.081923900.

Definition/geometry setup was 0.006441400 s and prepared-plan setup 0.173405900 s,
separate from queries. First scalar/vectorised calls were 0.113010500/0.082699100 s;
this adapter has no JIT. Peak admitted storage was 39,795,149 bytes and all
reservations were released; that is not measured process RSS. No earlier
production Stage-6 adapter exists for comparison. These are bounded adapter
savings, **not whole-generator or R4.4 speed-ups**.

```text
python -I -B tectonics/tools/benchmark_w01_forcing.py --source . --output FRESH_RESULT.json
```

Use a fresh result path. The driver records raw timings, runtime/source identities,
setup, array equivalence and resource accounting; it does not run a simulation.

<a id="3cr2-initial-state"></a>
<a id="3cr2-scaling"></a>

## R2: geological substrate and static sampling

[precursor_r2.json](../cases/precursor_r2.json) registers the static contract.
[W01 sampling](W01_REGIONAL_WORKFLOW.md#initial-condition-sampling) owns the supported initial-condition
interface; [execution/indexing](OPTIMISATION_REFERENCE.md#3cr2-initial-execution)
owns scheduling, reuse, resource admission and measured costs.

**Plate-independent substrate.** `GeologicalDomain` is a bounded planar area,
conditioned spherical patch, or an entire named reference sphere. It has no
physical plate or region owners. Existing `GeologicalCase` validates its original
materials, formation cohorts, ordered columns, thermal profiles, provinces,
faults and weak zones against this support. Old `BoundaryNetwork`/`SphericalAtlas`
cases and their serialised definitions remain supported. A pre-partition case
refuses selectors that require final plate/region IDs; its computational sampling
cells cannot determine the later physical plate partition.

`PrecursorState` adds one explicit origin assignment per source (observed,
authored, sampled named prior or model-evolved import), separate known/unknown
cooling histories, density/volume bases, optional initial scalar fields and
explicit mantle/slab inputs. An observed label requires a cited record but is not
independent verification; model-evolved input requires its parent-state identity
but does not run that model. Formation times are never replaced by cooling dates.
All times are SI seconds in the case's named epoch; a frame, epoch or depth-datum
mismatch requires explicit conversion, not a renamed array.

**Inherited and deeper structure.** Existing faults/sutures and weak zones remain
independent of plate labels. Exact finite-trace corridor membership is available
at points; overlapping weakness follows the existing explicit precedence without
invented multiplication, averaging or a damage law. Optional slab/mantle records
use named footprints and constant surface-relative depth bands with explicit
body precedence. They can replace column material or extend support below the
lithosphere base. These are supplied initial structures, not dynamically formed,
dipping/curved 3D slabs or inferred slab-pull forces.

**Material knowledge and property conditions.** Exact bindings to the existing
offline Earth-material library retain its full source/condition dependency and
automatically obtain volume bases. Partial records remain partial; source-bound
values cannot be silently rebound or extrapolated. Grain volume, reference
aggregate/matrix volume, explicit pore volume, bulk volume and mass are distinct.
Additional porosity on an already-bulk reference rock is refused. A bulk-reference
row does not assert its unknown intrinsic solid/pore split. Optional
`reference_mass_temperature_k` computes only source-reference-density inventory,
not in-situ mass of hot/pressurised lithosphere or a common pressure assumption.
No new hot/high-pressure or constitutive law is selected by R2.

**Sampling added to W01 stage 5.** `PreparedPrecursor` supplies immutable point
samples and conservative initial inventories for polygon-prism or minor-arc
shell-sector cells. Province overlap is resolved by subtracting higher-priority
footprints before integrating lower-priority material; body bands similarly
replace rather than double-count it. All province candidates are retained at
points. Layer/body intervals are top-inclusive and bottom-exclusive; cell faces
have zero extensive volume. A winning centre point is never substituted for a
mixed-cell average. Unsupported depths, missing required porosity/temperature or
unresolved property requests fail explicitly. Optional unresolved scalar fields
and reference masses carry known masks; convenience accessors refuse unknown
values rather than treating numeric placeholders as physical zeroes.

For planar area A and positive downward depths a,b, V=A(b-a). For a spherical
footprint whose reference-surface area is A on radius R,

    V = A/(3 R²) * [(R-a)³ - (R-b)³]
      = A*(b-a)/3 * [((R-a)/R)² + ((R-a)/R)*((R-b)/R) + ((R-b)/R)²].

The factored form avoids subtraction of nearly equal radius cubes. For explicit
porosity phi, matrix volume is V(1-phi), explicit pore volume is V phi, and each
constituent receives its declared fraction of matrix volume. Existing fractional
round-off allowances are not renormalised: bulk-coverage and phase-volume
residuals are reported separately. Cohort/material indices refer to shared
immutable records, preserving origins and formation dates without rich objects
copied into every cell. Crust and lithosphere thickness remain the existing
separate column quantities.

**Initial thermal/other fields.** Constant and piecewise-linear profiles integrate
analytically with the appropriate radial metric. The existing E04 half-space
initial reference uses bounded quadrature for cell means, with an explicit error
estimate and refusal rather than midpoint fallback. Mean temperature is
volume-weighted temperature, not heat/enthalpy; this adds no thermal evolution.
Temperature offsets must also have a non-negative envelope on requested cell
support; a positive mean cannot conceal potentially sub-zero temperatures.
Stress, damage and prescribed forcing can be explicitly supplied/unresolved
scalar components with units and interpretation, not an inferred mechanical state.

A named prior is the bounded Cartesian cosine field

    f(r) = mean + amplitude/N * sum_i cos(k_i dot (r-origin) + phase_i).

SHA256(name, unsigned-64-bit seed, mode index) supplies fixed per-mode streams.
Amplitude means maximum deviation, not standard deviation; wavelengths are named
feature scales, not an asserted fitted correlation length. Domain/frame/origin
and seed belong to the identity. Planar coordinates are (x,y,depth) metres;
spherical coordinates are geocentric Cartesian metres, without a longitude seam.
Changing support resolution/order does not redraw the field. Planar polygon-prism
prior means are analytic Fourier integrals including holes. Statistical inputs
remain assumptions, not simulated geological events.

**Explicit remaining limits.** General dipping/curved 3D structure and arbitrary
volumetric interpolation remain unimplemented. Spherical point priors and radial
base-profile means work, but spherical cell means of Cartesian spectral priors
are refused. Positive-volume overlap between query cells is refused by default;
when charts cannot certify disjointness, no snapping or blanket sliver tolerance
is substituted. Compatible patches are required, or the caller must explicitly
request non-additive overlapping queries. A set of individually queried spherical
volumes is not thereby certified as a global disjoint mesh. Static sampling does not itself close broader W01 interpolation, forcing/evolution,
combined scientific acceptance or R3–R9 physics.

Broad-phase caps include minor-arc edges/interiors, retain exact intersections
for uncertain candidates and preserve tiny positive-volume overlaps. Dense cap
overlap can still require quadratic work; indexing is not arbitrary cross-chart
repair or a global disjoint-mesh certificate. Batching must preserve complete
request checks, global hit/row/work ceilings, original order and fixed per-cell
summation. Threading cannot multiply admission or change numerical arrays.
[The scaling case](../cases/precursor_r2_scaling.json) and original tests/measurements
retain these limits. Static T04/T05/T06/T14/T15 credit does not qualify their dynamic
scopes. Existing limitations on dipping structures and spherical-prior means remain.
