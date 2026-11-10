# Atlas tectonics package

This isolated package supplies scientific components,
explicitly bounded connected workflows, command tools and source-bound evidence.
It imports neither `engineering/work` nor `shared_generator`; those are separate
Atlas routes. Static spherical geometry, regional evolution and a physically
accepted evolving planet are different capabilities.

The version string is `0.1.0.dev42`. It was not incremented for later integration
modules and is not a release or acceptance marker. Receipts bind actual source
and execution identities. Read [current delivery and acceptance](../docs/CURRENT_STATE.md#current-delivery-and-acceptance)
for reviewed scope, platform coverage, holds and remaining work, including I04/I05a.
Numerical checks and physical acceptance are separate outcomes.

[Scientific guide](docs/HOW_TECTONICS_IS_MADE.md) · [Environment](#tectonics-environment) ·
[Commands](#commands) · [API examples](#api-examples) · [Evidence](#verification-and-evidence)

## Scientific methods and navigation

[How Atlas tectonics is made](docs/HOW_TECTONICS_IS_MADE.md) explains the methods,
inputs, outputs, scientific/software references and check limits in generation
and dependency order. Use its chapters and the specialist contracts below;
current delivery status belongs in the current-state record.

| Question | Maintained explanation |
| --- | --- |
| Coordinates, geometry, descriptions and reference materials | [Foundations chapter](docs/how-it-works/01-foundations.md), [specialist contracts](docs/FOUNDATIONS.md) |
| Transport, cooling, compaction, loads and support | [Material, heat and support foundations](docs/how-it-works/01-foundations.md) |
| Regional mechanics, recovery and resource ownership | [Regional mechanics](docs/how-it-works/02-tectonic-processes.md#w07-calculate-slow-regional-deformation), [coupling and reliability](docs/how-it-works/03-coupling-and-reliability.md) |
| Seeded starting worlds and regional continuation | [New worlds](docs/how-it-works/04-new-worlds.md), [combined acceptance](docs/NEW_WORLD_EVOLUTION.md#combined-lifecycle-qualification), [portable bundles](docs/NEW_WORLD_EVOLUTION.md#portable-world-projects) |
| Experimental force-driven convection | [Dynamics chapter](docs/how-it-works/05-experimental-dynamics.md), [scientific plan](docs/TECTONICS_PLAN.md) |
| Coupled physics, shared state, exchanges and accepted time | [Physical integration](docs/how-it-works/06-physical-integration.md), [I02 workflow](docs/I02_WORKFLOW.md) |
| Evolving sphere, starting families and reduced driving feedback | [I03 network](docs/I03_SPHERICAL_NETWORK.md), [I04 causal start](docs/I04_CAUSAL_START.md), [I05 moving state](docs/I05_MOVING_STATE.md), [shared ports](docs/I04_I05_PORTS.md) |
| Fixed-box 3-D mechanics and evolution | [Solver](docs/REGIONAL_MECHANICS_3D.md), [evolution](docs/REGIONAL_EVOLUTION_3D.md) |
| Supplied collision, changing inputs and supported histories | [Underthrust](docs/W08_SHORTENING.md#prescribed-collision-and-underthrusting), [evolving mechanics](docs/EVOLVING_MECHANICS.md), [histories](docs/EVOLVING_MECHANICS.md#tectonics-continuation-step-4-supported-dated-histories) |
| Numerical versus physical validation | [Validation](docs/W10_VALIDATION.md), [I01 closure matrix](docs/I01_CLOSURE_MATRIX.md) |
| Execution, persistence, exact reuse and optimisation limits | [Execution reference](docs/OPTIMISATION_REFERENCE.md), [optimisation navigation](optimisation/README.md) |

Scientific ownership is defined in the [reader guide](docs/HOW_TECTONICS_IS_MADE.md#scientific-ownership-and-maintenance)
and [module boundaries](docs/TECTONICS_PLAN.md#current-module-boundaries-and-continuation-23-september-2026).
Further hydrology, erosion/deposition, geological, compaction and magmatic work
belongs with its receiving module; existing shared code, imports and checkpoint
dependencies stay intact. Mechanical response remains in tectonics.

<a id="environment"></a>

## Tectonics environment

Use a separate Python 3.12 or 3.13 environment for this package, **not** the old
source-only `tools/develop.py` environment. Dependencies and version ranges live
in `tectonics/pyproject.toml`; only Numba is exact-pinned there. A passing run must
record its actual versions, not claim all dependencies are pinned. The optional
`visual` extra supplies Matplotlib for the diagnostic tool, not the physical core.
The commands below install dependencies only when you explicitly run them.

The tested and pinned route is Windows AMD64 CPython 3.12.14 with the requirement
files in [`requirements/`](requirements/): use the
[recreate commands](../docs/TECTONICS_ENVIRONMENT.md#recreate-an-environment) in the
[tectonics environment record](../docs/TECTONICS_ENVIRONMENT.md). The commands below
instead install floating versions within the `pyproject.toml` ranges. Linux and
Python 3.13 have no current pinned qualification; their older receipts retain
their historical scope ([environment limits](../docs/TECTONICS_ENVIRONMENT.md),
[current status](../docs/CURRENT_STATE.md)).

From the repository root on Linux/macOS:

```sh
python3.13 -m venv tectonics/.venv
tectonics/.venv/bin/python -m pip install -e 'tectonics[visual]'
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  tectonics/.venv/bin/python -I -B tectonics/verify.py > fresh-tests.json
```

From the repository root in Windows PowerShell:

```powershell
py -3.13 -m venv tectonics\.venv
& .\tectonics\.venv\Scripts\python.exe -m pip install -e ".\tectonics[visual]"
$env:OPENBLAS_NUM_THREADS="1"; $env:OMP_NUM_THREADS="1"; $env:MKL_NUM_THREADS="1"
& .\tectonics\.venv\Scripts\python.exe -I -B .\tectonics\verify.py > fresh-tests.json
```

No activation or shell-policy change is necessary. Normal interpreter links and
copied interpreters are both supported; `--copies` is no longer required as an
Atlas workaround. Source/data/extension symlink guards remain. Use `-B` for local
source imports: the verifier intentionally refuses pre-existing local bytecode.
Do not delete an existing working tree to get a pass; investigate it or use a clean
copy. Do not use `--system-site-packages` for a fresh independent installation;
the cleanup test harness used it only to reuse already installed dependencies
without downloading/installing anything. Instructions for any platform are not
platform acceptance; the recorded full-suite outcome is in
[current status](../docs/CURRENT_STATE.md#current-delivery-and-acceptance). Full verification
also exercises real filesystem symlinks; a host unable to create those fixtures
has not completed that part of verification. Skips are not counted as a full pass.

Primary environment reference: [Python's venv documentation](https://docs.python.org/3.13/library/venv.html).

### Focused regression selections

Use the existing verifier with the tested environment for the changed boundary:

| Option | Coverage |
| --- | --- |
| `--i01` | All I01 component/control test modules. |
| `--i02` | All I02 state, exchange, clock, persistence and workflow tests, including measurement integration. |
| `--i02-quick` | I02 tests excluding only the four full timing-harness integration tests. |
| `--i02-measurement` | Those four real-workload measurement, restart and failure-propagation tests. |
| `--regional3d` | Regional 3-D component, solver and evolution test modules. |
| `--quick` | Full discovery or one focused profile with only the registered measured slow tests omitted; reports a quick selection, not a full gate. |

For example, `python -I -B tectonics/verify.py --i02-quick` records the actual
selected test IDs, timing and source identities. The quick and measurement
selections together cover the complete I02 selection. Choose the selection that
covers the changed boundary and its affected consumers; use `--i02` when complete
I02 coverage is required. Quick-only is not equivalent coverage. The separate
general `--quick` option can combine with the focused profiles in this table;
it additionally omits their registered slow tests and cannot combine with
`--core`, `--native`, `--acceptance` or the legacy W01/W04/W05/W06 profiles.
[Development tools](../docs/DEVELOPMENT_TOOLS.md#when-the-full-gate-is-still-required) owns that
selection policy. Existing W01/W04/W05/W06 profiles are unchanged, and invoking
the verifier **without options runs the full suite**. Focused profiles neither
loosen tolerances nor establish physical or whole-generator acceptance. Do not
compare their timings as though they ran equivalent work.

For repository navigation/planning edits, the
[before-commit guard](../docs/CODING_SAFETY.md#before-every-commit) can avoid
unrelated I01/I02 numerical reruns while still checking Git-normalised evidence
and line endings. Its reviewed document allowlist is deliberately narrow.

## Commands

Run from the repository root using the declared compatible environment. These
calculation/measurement commands are explicit actions, not setup requirements for
documentation changes. Use new output paths and never rebind changed-source runs.

### Supported W12 and authored precursor examples

```text
python -B tectonics/tools/run_tectonics.py --directory w12-demo
python -B tectonics/tools/run_tectonics.py --directory w12-demo --resume
```

The first directory must be new. [Supported assembly](docs/W12_ASSEMBLY.md)
describes the bounded W01–W04 example, graph/cache connection, exports and native
recovery dependencies. The [read-only bridge](docs/W12_ASSEMBLY.md#read-only-ui-connection)
uses `tools/read_tectonics.py` without starting a simulation; it is a backend
reader rather than a browser UI.

```sh
# Authored two-province initial output; no simulation or reference download.
python -I -B tectonics/tools/prepare_precursor_example.py > initial-example.json
# Existing files refuse; load the result by its reported sample_id, then .state.
python -I -B tectonics/tools/prepare_precursor_example.py --save-store initial-example.db
# Restricted prescribed-motion regional workflow.
python -I -B tectonics/tools/run_w01_workflow.py
```

The examples use authored assumptions, not calibrated Earth-like defaults.
See [initial sampling](docs/W01_REGIONAL_WORKFLOW.md#initial-condition-sampling), [regional workflow](docs/W01_REGIONAL_WORKFLOW.md)
and [precursor execution](docs/OPTIMISATION_REFERENCE.md#3cr2-initial-execution)
for geometry, memory, history and source restrictions.

### Offline plate-reference assessment

```sh
# Strict consistency: exit 1 reports the retained discrepancies.
python -I -B tectonics/tools/prepare_plate_reference.py --verify-only > 3cr1-strict.json
# Permitted uses: exit 0 only for exact audited data and known findings.
python -I -B tectonics/tools/prepare_plate_reference.py --verify-only --assess-use > 3cr1-use.json
```

Both return exit 2 for unavailable/changed inputs. `--assess-use` does not waive
strict checks. [Source-use contract](docs/FOUNDATIONS.md#3c-r1-reviewed-source-use-contract-18-september-2026)
and [policy](cases/plate_reference_use_policy.json) define the different populations,
scale/phase restrictions, source discrepancies and reserved holdouts. Raw diagnostics
are not qualified morphology or geological acceptance.

### Component checks and visuals

| Component | Bounded numerical/timing check | Optional diagnostic visual |
| --- | --- | --- |
| Precursor | `python -I -B tectonics/tests/check_precursor_r2.py` | `python -I -B tectonics/tools/visual_qa.py --output /new/path` |
| Local rheology | `python -I -B tectonics/tests/check_constitutive_r3.py` | `python -I -B tectonics/tools/visual_r3.py --output /new/path` |
| Steady 2-D mechanics | `python -I -B tectonics/tests/check_stokes_r4_1.py` | `python -I -B tectonics/tools/visual_stokes_r4_1.py --output /new/path` |
| Thermal/composition evolution | `python -I -B tectonics/tests/check_thermochemical_r4_2.py` | `python -I -B tectonics/tools/visual_thermochemical_r4_2.py --output /new/path` |
| Variable mechanics | [Execution contract](docs/OPTIMISATION_REFERENCE.md#3cr4-3-execution) | `python -I -B tectonics/tools/visual_variable_stokes_r4_3.py --output /new/path` |

These cards are not full benchmark campaigns. Visuals require the optional
`visual` extra, inspected outputs and new destinations. The thermal example
advances an authored 48×48 box for 40 steps; endpoint velocity is recomputed from
the accepted endpoint, rather than an intermediate stage. This is not calibration.

### Bounded R4.4 studies

These commands do not authorise held R4.4 work. The component plan owns the
[scientific acceptance](docs/TECTONICS_PLAN.md#3cr4-progress), and the optimisation
reference owns [execution and recovery](docs/OPTIMISATION_REFERENCE.md#storage-contract).

For an explicitly authorised study, from the scoped source root using the declared installed environment (no automatic installation or repinning):

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python -I -B tectonics/tools/run_convection_r4_4.py \
  --output NEW_RUN --case tosi-1 --cells 16 --dt 1e-5 \
  --max-steps 30000 --segment-steps 1000 --sample-every 25 --save-every 500

OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python -I -B tectonics/tools/run_convection_r4_4.py \
  --output NEW_RUN --resume --segment-steps 1000

OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python -I -B tectonics/tools/analyse_convection_r4_4.py \
  --run CLOSED_RUN --output NEW_ANALYSIS.json

OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python -I -B tectonics/tools/visual_convection_r4_4.py \
  --run CLOSED_RUN --output NEW_VISUAL_DIRECTORY

OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python -I -B tectonics/verify.py --acceptance
```

These example run controls are exploratory, not the registered 32/64/128 adequacy
triplet and not a guarantee of a mature state by the selected terminal time.
`--seconds` requests a cooperative per-invocation bound. A genuine physical refusal
needs investigation, not an automatic retry under weaker controls. Successful
finite-schedule completion means only that the predeclared steps were accepted.

For an actual three-run study, give the auditor three `--run` paths in coarse-to-fine
order and `--study-axis mesh`, `timestep` or `nonlinear`. It verifies the non-varied
controls and actual mature regimes before considering differences. Fill a copy of
`convection_r4_4_campaign.example.json` with actual run paths, the final unchanged
source's `verify.py --acceptance` record and separately recorded source-bound visual
inspections. Run `assess_convection_suite_r4_4.py --manifest CAMPAIGN.json --output
NEW_SUITE_RESULT.json`. Missing evidence returns `INCOMPLETE_R4_4` and exit status 1;
malformed or unsafe input is refused with exit status 2. A fabricated PASS field in
a campaign manifest is not consumed as evidence.

Visuals come from decoded actual states and re-solved simultaneous endpoint flow.
Raw arrays, complete source/state/flow identities and file hashes are retained.
Temperature/viscosity/pressure displays use unsmoothed original cells; velocity
arrows use declared face-to-centre averages without unit-vector normalisation.
Histories are saved diagnostic samples. Assistant inspection and Michael's visual
approval are separate records; the renderer asserts neither. Initial transient
pictures are not promoted to mature convection or observational evidence.


## Reproducible diagnostic visuals

```sh
# Use the environment's Python as above. The destination must not already exist.
python -I -B tectonics/tools/visual_qa.py --output tectonics/visual_output/review
```

This runs the unchanged authored R2 example and a fixed seed-41 plate-layout
candidate, loads the existing pinned PB2002 bytes offline, and records identities
and provenance next to the PNGs. It adds no physics and changes no source data.
The source-data inventory is read/verified, not reacquired or requalified.
Formation ages come from sampled unit/cohort records; cooling age is separate.
PB2002 segment symbols mean left/right subduction or **non-subducting**, not a
blanket transform classification. Raw source curves remain separate and are not
converted into certified morphology. Rendering clips the antimeridian and globe
limbs; six globe views include both poles. Optional Matplotlib absence fails
clearly without affecting ordinary numerical use of Atlas.

A visual check records what was inspected and any problems; generating a PNG is
not automatic approval. No landform, velocity or thermal-evolution result is
implied. The two earlier chat plots with hard-coded ages and a wrong `-` legend
are withdrawn as evidence; the corrected plots supersede them.

## API examples

These retained examples illustrate declared interfaces. Radii, parameters and
initial values are synthetic or explicit trial inputs, not Earth/Diadem calibration.
Use the separate package environment above; source/runtime checks still apply.
Scientific explanations and limits live in the linked specialist contracts.

### Coordinates and time

[Contract and limitations](docs/FOUNDATIONS.md#w01-coordinates). Local coordinates are 3-D chords, not a map projection; time has a named epoch and explicit units.

```python
from atlas_tectonics import (SphericalFrame, LocalCartesianFrame,
    TimeAxis, SECOND, JULIAN_MEGAYEAR)

# Synthetic example radius, not Earth calibration.
sphere = SphericalFrame(radius_m=6_400_000., frame_id="example-planet-axes")
xyz = sphere.to_cartesian([[30., 45., 100.]], angle_unit="degrees")
region = LocalCartesianFrame(sphere, "example-region", longitude_rad=0., latitude_rad=0.)
local = region.positions_from_cartesian(xyz)
velocity = region.vectors_from_cartesian([[1., 2., 3.]])  # no origin subtraction
ago = TimeAxis("example-epoch", JULIAN_MEGAYEAR, 0., "before")
formation_time_s = float(ago.to_seconds(10.))  # negative forward-time timestamp
```

### Feature geometry

[Contract and limitations](docs/FOUNDATIONS.md#w01-geometry). Queries return all owners. No snapping or automatic polygon repair; spherical topology uses conditioned charts and actual-sphere metrics.

```python
from atlas_tectonics import (PlanarGeometry, GeometryFeature, GeometryIndex,
    SphericalFrame, SphericalChart, SphericalGeometry)
region = PlanarGeometry.polygon([[0, 0], [2, 0], [2, 2], [0, 2]],
                                frame_id="synthetic-plane")
with GeometryIndex((GeometryFeature("region-a", region),)) as index:
    hits = index.query([[1, 1], [2, 1], [3, 1]])
    print(hits.pairs)  # all matching (query index, feature index) pairs
sphere = SphericalFrame(2., "synthetic-sphere")  # not an Earth calibration
chart = SphericalChart(sphere, (1., 1., 1.))
octant = SphericalGeometry.polygon([[1, 0, 0], [0, 1, 0], [0, 0, 1]], chart=chart)
print(octant.area_m2)  # pi/2 steradians times radius squared
```

### Shared regional boundaries

[Contract and limitations](docs/FOUNDATIONS.md#w01-boundaries). Coverage must be exact. Supplied velocities describe motion; they do not predict forces.

```python
from atlas_tectonics import PlanarGeometry, BoundaryRegion, build_boundary_network

def rectangle(x0, x1):
    return PlanarGeometry.polygon(
        [[x0, 0], [x1, 0], [x1, 1], [x0, 1]], frame_id="example-plane")

network = build_boundary_network(rectangle(0, 2), (
    BoundaryRegion("west", "plate-a", rectangle(0, 1)),
    BoundaryRegion("east", "plate-b", rectangle(1, 2)),
))
edge = network.edge(network.interplate_edges[0])
assert edge.left_region_id == "west" and edge.right_region_id == "east"
motion = network.motion({"plate-a": [0, 0], "plate-b": [2, 0]}, [0, 0])
assert motion.opening_m_s[0] == 2
```

### Initial spherical partition

[Contract and limitations](docs/FOUNDATIONS.md#w01-stage3c). Unweighted spherical Voronoi ownership is a geometry fixture, not a geological size distribution or evolving planet.

```python
from atlas_tectonics import (SphericalFrame, PlanetPartitionSettings,
    generate_planetary_partition)

# Example radius is deliberately synthetic; supply the actual case's radius/frame.
world = generate_planetary_partition(
    SphericalFrame(1_000_000., "example-planet"),
    PlanetPartitionSettings(plate_count=12, seed=42),
)
areas_m2 = world.areas()
neighbours = world.adjacency()
# Existing world.index(), save_spherical_atlas() and load_spherical_atlas() apply.
```

### Candidate plate layout

[Contract and limitations](docs/OPTIMISATION_REFERENCE.md#plate-layout-science-correction). Reference-conditioned size spectra do not establish outline/dynamic acceptance. `require_geological_layout_acceptance(atlas)` refuses that claim.

```python
from atlas_tectonics import SphericalFrame, PlateLayoutSettings, generate_plate_layout
# Radius is an explicit world input. Settings below specify a statistical trial,
# not an accepted Earth reconstruction or a prediction of mantle-driven plates.
atlas = generate_plate_layout(
    SphericalFrame(6_371_000., "example-world"),
    PlateLayoutSettings(plate_count=12, seed=41, support_cells=512),
)
```

### Reference materials

[Contract and limitations](docs/FOUNDATIONS.md#w01-earth-materials). Reference conditions, source ranges and unknowns remain explicit; this is not a hot/high-pressure constitutive law.

```python
from atlas_tectonics import earth_material_library, sediment_matrix

library = earth_material_library()
materials, evidence = library.definitions((
    "rock.granite", "rock.basalt", "rock.peridotite", "fluid.fresh_water"))
# Attach the returned records/evidence to the existing GeologicalCase description.
# The initial geometry, layer order and material origins still belong to the case.

matrix = sediment_matrix("quartz_sand_or_silt_matrix", porosity=0.30,
                         pore_fluid="fluid.fresh_water")
# matrix.conductivity_bounds_w_m_k is a range, NOT an invented exact conductivity.
# matrix.heat_production_w_m3 remains None without an explicit source assumption.
```

### Regional transport

[Contract and limitations](docs/FOUNDATIONS.md#w02-regional). Open inflow requires explicit data. Inventory is m² per unit width under common density, not kg. No clipping or automatic substeps.

```python
import numpy as np
from atlas_tectonics import (RegionalGrid1D, TransportBoundary,
                            advect_regional, transport_timestep_limit)

grid = RegionalGrid1D(cells=128, length_m=128.0)
left = TransportBoundary("open", exterior_thickness_m=2.0,
                         material_id="synthetic-external-reservoir")
right = TransportBoundary("open")
h = np.ones(grid.cells)                     # synthetic thickness, m
u = np.full(grid.cells + 1, 0.25)            # prescribed velocity, m/s
limit = transport_timestep_limit(u, grid, left=left, right=right)
step = advect_regional(h, u, grid, 0.5, left=left, right=right)
# step.balance_residual_m2 checks after - before - left_exchange - right_exchange.
```

### Distinct material histories

[Contract and limitations](docs/FOUNDATIONS.md#w02-cohorts). Formation identities remain separate; transfers do not predict production. Retaining every earlier receipt is a caller policy.

```python
import numpy as np
from atlas_tectonics import (RegionalGrid1D, MaterialCohort, MaterialState,
    MaterialBoundary, advect_materials)

cohorts = (MaterialCohort("old", "basalt", "source-A", -100.0),
           MaterialCohort("young", "basalt", "source-B", -10.0))
state = MaterialState(RegionalGrid1D(16, 16.0), cohorts,
    np.array([[1.0] * 16, [2.0] * 16]), time_s=0.0, epoch_id="synthetic-seconds")
inflow = MaterialBoundary("open", {"old": 1.0, "young": 2.0}, "west")
outflow = MaterialBoundary("open", None, "east")
result = advect_materials(state, np.ones(17), 0.2, left=inflow, right=outflow)
# result.state.ages_s() == (100.2, 10.2); histories were not blended.
```

### Conservative remap and ALE

[Contract and limitations](docs/FOUNDATIONS.md#w02-completion). Mesh and material velocity differ. Cropping/filling and unsafe stages refuse; coarsening is not reversible.

```python
import numpy as np
from atlas_tectonics import (ColumnGrid1D, MaterialCohort, MaterialState,
    MaterialBoundary, remap_materials, advect_ale)

mesh = ColumnGrid1D(np.linspace(0, 1, 65), frame_id="synthetic-region")
state = MaterialState(mesh, (MaterialCohort("a", "rock", "origin", 0.),),
                      np.ones((1, 64)), time_s=0., epoch_id="example")
finer = ColumnGrid1D(np.linspace(0, 1, 129), frame_id="synthetic-region")
state = remap_materials(state, finer)
velocity = 0.1 * state.grid.edges_m
result = advect_ale(state, velocity, velocity, 0.5,
                    left=MaterialBoundary("closed"),
                    right=MaterialBoundary("closed"))
# The domain stretches by 5%; inventory is conserved and thickness falls.
# Save or consume result before reusing/releasing its owner's memory allowance.
```

### Local rheology

[Contract and limitations](docs/OPTIMISATION_REFERENCE.md#3cr3-execution). Temperature/depth here are dimensionless in [0,1]. SI needs explicit `DiffusiveScales` with separate length/depth normalisation. No hidden pressure or measured strength.

```python
from atlas_tectonics import PreparedRheology, reference_rheology

# Named dimensionless local reference; initial damage is deliberately supplied.
with PreparedRheology(reference_rheology("bf23-memory")) as law:
    response = law.evaluate(temperature=[0.0, 0.5, 1.0], depth=0.1,
                            strain_rate_ii=1.0, damage=0.0)
    memory = law.advance(damage=20.0, strain_rate_ii=0.0,
                         temperature=0.0, elapsed=1.0)
viscosity = response.array("viscosity")  # immutable result, not mantle calibration
healed_damage = memory.array("damage_after")
```

### Steady mechanical control

[Contract and limitations](docs/OPTIMISATION_REFERENCE.md#3cr4-1-execution). The uniform free-slip steady box has no thermal evolution or plate dynamics. The direct reference is explicit, not a fallback.

```python
import numpy as np
from atlas_tectonics import (
    StokesBox2D, DiffusiveScales, reference_rheology, PreparedStokes2D,
)
box = StokesBox2D(32, 32, 1.0, 1.0, "analytical-x-right-z-up")
scales = DiffusiveScales("declared-unit-SI", 1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
# Uniform downward body force: a hydrostatic pressure response, no circulation.
fx = np.zeros((box.nz, box.nx - 1))
fz = np.full((box.nz - 1, box.nx), -1.0)
with PreparedStokes2D(box, reference_rheology("constant"), scales) as plan:
    result = plan.solve(fx, fz, frame_id=box.frame_id,
                        epoch_id="analytical-steady", time_s=0.0,
                        source="Authored hydrostatic verification case")
pressure_pa = result.array("pressure_pa")
```

### Shared resource admission

[Contract and limitations](docs/OPTIMISATION_REFERENCE.md#combined-acceptance). Shared allocation estimates are not total process RSS. Caller-retained arrays and independent processes remain separate costs.

```python
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.execution import KernelExecutor
from atlas_tectonics.storage import ArrayStore, StoreLimits

# Example execution envelope, not an Earth parameter or owner hardware estimate.
run_budget = WorkBudget(256 * 1024**2)
# Pass budget=run_budget to the executor/store/standalone calls in the same run.
# Kernels keep pure numerical interfaces; no disk paths enter their equations.
```

### Incremental storage

[Contract and limitations](docs/OPTIMISATION_REFERENCE.md#storage-profiles-delivery). Supply full invocation identities, arrays and metadata. Replacements must be complete named chunks; existing stores retain their chunk size.

```python
# Snapshot IDs are supplied full scientific invocation identities (SHA-256).
from atlas_tectonics.storage import ArrayStore, StoreLimits, storage_profile
profile = storage_profile("balanced")
limits = StoreLimits(profile.chunk_bytes, max_array_bytes=16*1024**2,
                     max_store_bytes=64*1024**2, decoded_cache_bytes=1024**2)
with ArrayStore("existing-directory/fields.sqlite", limits, profile.compression) as store:
    store.put(parent_id, {"material": material, "temperature": temperature}, metadata)
    # Share the parent's unchanged data; replace only COMPLETE named chunks.
    store.put_incremental(child_id, parent_id,
                          {"temperature": {0: replacement_chunk}}, child_metadata)
```

### Independent execution batches

[Contract and limitations](docs/OPTIMISATION_REFERENCE.md#execution-reuse-delivery). Requests are independent complete cases; the caller controls retained output memory.

```python
from atlas_tectonics.execution import KernelExecutor
# requests yields (depth_array, age_array_or_scalar) pairs.
with KernelExecutor() as executor:
    for temperatures in executor.temperatures(requests, thermal_parameters):
        consume(temperatures)  # caller controls retained output memory
```

### Optional persistent cooling

[Contract and limitations](docs/OPTIMISATION_REFERENCE.md#storage-contract). Use an existing trusted directory. `store=None` avoids persistent I/O; `backend="reference"` explicitly selects diagnostic reference evaluation. Storage limits are examples, not owner budgets.

```python
from pathlib import Path
import numpy as np
from atlas_tectonics.parameters import ThermalParameters
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore, StoreLimits, Compression
from atlas_tectonics.reuse import cached_temperature

limits = StoreLimits(chunk_bytes=32768, max_array_bytes=8*1024**2,
                     max_store_bytes=32*1024**2, decoded_cache_bytes=128*1024)
profile = ThermalParameters("synthetic", "example only", 300., 1300., 1.)
with ArrayStore(Path("existing-cache-directory") / "fields.sqlite", limits,
                Compression(codec="zstd", level=3, shuffle="byte")) as store:
    temperature = cached_temperature(np.linspace(0, 10, 4096), 1., profile,
        store=store, backend="scipy", budget=WorkBudget(32*1024**2))
```

### Cooling, rotation and flexure batches

[Contract and limitations](docs/OPTIMISATION_REFERENCE.md#delivered-optimisations-4-5). These are complete independent requests, not spatial tiles. `consume` is caller handling, not an Atlas API; discard consumed batches to bound retention.

```python
# Ordinary calls use the selected optimisations without opt-in switches.
temperature = half_space_temperature(depth_m, age_s, parameters)
rotated = rotation.apply(points_m)
deflection = operator.solve(loads_pa)   # (..., grid.cells), independent leading cases

# These consume separate complete requests, not independent spatial solver tiles.
for rotated_batch in rotation.apply_batches(point_batches, budget=budget):
    consume(rotated_batch)
for deflection_batch in operator.solve_batches(load_batches, budget=budget):
    consume(deflection_batch)
```

### Persistence and memory boundaries

Storage chunks are flat C-order typed-array pieces, not physical boundaries.
Non-native byte order normalises losslessly; shapes, signed zeros and categorical
values remain. Masked/object/nonfinite arrays refuse. A separate boolean mask
requires explicit consumer support. `max_array_bytes` bounds the complete snapshot
on writes and full materialisation, not each field independently. Partial reads
through `read_chunk()`/`iter_chunks()` check each declared array against that limit
without materialising the complete snapshot.
`max_store_bytes` bounds retained database pages/records. Allow another
database-sized rollback journal and any explicitly required recovery copy;
SQLite cache and codec workspace
are separate. Inputs must remain unchanged during writes. Restored immutable
arrays can outlive cache entries and still count as caller RAM.

Identity checks use actual current source bytes, not timestamps. Corruption,
identity conflicts, missing dependencies and exceeded limits fail explicitly.
SHA-256 supports identity/corruption detection, not a signature or a security
boundary against an attacker controlling the trusted directory/process. Runtime
binaries are assumed immutable during a process. Result persistence is not proof
of evolving-world restart; no automatic deletion or history migration follows.
See [cache ownership](docs/OPTIMISATION_REFERENCE.md#cache-contract) and
[storage/recovery](docs/OPTIMISATION_REFERENCE.md#storage-contract).

## Verification and evidence

```sh
# Original mathematical core selection.
python -I -B tectonics/verify.py --core
# Complete software regression, not a world-generation command.
python -I -B tectonics/verify.py
# Complete regression plus bounded process-tree resource/platform acceptance.
# Requires the explicit acceptance extra (psutil); installs nothing.
python -I -B tectonics/verify.py --acceptance > item12-local.json
```

The verifier writes test details to stderr and a new versioned record to stdout.
It refuses pre-existing local `.pyc` files: `-B` prevents writes, not reads.
Missing required dependencies block verification rather than silently skipping it.
[Focused profiles](#focused-regression-selections) do not establish full-suite or
physical acceptance. Consult [current evidence](../docs/CURRENT_EVIDENCE.md), its
[register](evidence/current-evidence.json) and [full-suite status](../docs/CURRENT_STATE.md#current-delivery-and-acceptance).
Dated receipts describe bound sources, workload, runtime and platform; a README
edit does not refresh them. Original records remain in [`evidence/`](evidence/),
including the [first delivery](docs/FOUNDATIONS.md#first-remake-evidence-and-limits). Historical optimisation
ratios are not whole-generator speedups or world-scale forecasts.

## Delivery and licence

Review changes against the intended baseline and preserve newer/unrelated files.
Label update-only bundles and never run them standalone. Source publication,
local integration, runtime compatibility and physical acceptance are separate.
Never repin saved checkpoints or rewrite historical receipts. Optional visual
outputs remain ignored; retained structured evidence and tracked historical logs
stay intact.

**Atlas-owned code is AGPL-3.0-only.** See [the licence](LICENSE),
[project scope](../LICENSING.md) and [third-party notices](THIRD_PARTY_NOTICES.md).
PB2002 and other third-party material retain their own licences. The superseded
Apache proposal is not an alternative grant.
