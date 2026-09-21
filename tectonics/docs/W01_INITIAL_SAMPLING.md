# W01 Stage 5 — initial-condition sampling

Status: implemented and optimised for the declared Stage-4 geometry and geological
representation, **WORKING NON-CANON**. This is a representation/sampling stage,
not a plate-history simulation or independent scientific acceptance. W01
Stages 6–8 and the separate unfinished R4.4 acceptance campaign are unchanged.

## Entry point

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

## What is sampled

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

## Validity and missing data

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

## Reuse, resources and storage

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

## Deliberate representation boundaries

Stage 4 supplies constant-depth layers and explicit body bands, not arbitrary
3-D geological interfaces. Geometry remains planar or conditioned minor-arc
spherical patches; a whole sphere is represented by its actual patches, never
one fictitious polygon. General spherical cell averages of Cartesian cosine
priors remain explicitly unsupported; spherical point priors, radial thermal
means and material inventories are supported. This implementation does not
silently approximate an unsupported mean.

Motion-to-regional forcing is Stage 6; W01-to-W02 initialisation/evolution is
Stage 7; assembled scientific/resource/cache/restoration acceptance is Stage 8.
None is claimed complete here. No R4.4 run or whole-world physical simulation
is needed to test Stage 5 representation contracts.

## Focused verification

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

## Measured optimisation scope

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
