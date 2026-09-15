# Atlas

**A vibe-coded world generator for physically informed, internally consistent worldbuilding.**

Atlas is being developed for the fictional world of the **Diadem**. Its aim is to connect the physical landscape with the ecological and human systems that depend on it: not just where mountains and rivers appear, but how ground conditions, water, climate, living things, resources and settlements fit together.

**OpenAI's ChatGPT/Codex does the coding under the project owner's direction.** The owner supplies the worldbuilding requirements, decisions and feedback; AI assistants write the code and carry out much of the technical testing. Vibe-coding describes the development process, not a substitute for source review, reproducible tests or independent scientific validation.

**Current status: experimental, WORKING NON-CANON.** Atlas has implementations across 18 modelling categories, connected execution infrastructure and a runnable public component-development package. It is not yet a complete, independently validated world generator. Mountain and wider terrain realism remain unaccepted.

[The 18 categories](#the-18-modelling-categories) · [How it works](#how-atlas-works) · [Progress](#what-has-been-achieved) · [Outputs](#what-atlas-produces) · [Try it](#try-the-public-development-package) · [Roadmap](#development-direction)

## What Atlas is trying to achieve

The goal is an inspectable worldbuilding system in which decisions have traceable consequences. A change to terrain can matter to water movement; water and ground conditions can matter to vegetation and agriculture; those results can inform settlement opportunities, population support and connectivity.

Atlas combines **supplied world constraints** with **explicit modelling choices**. Existing geography, selected species parameters, population records and political decisions are inputs where a component requires them, not facts that the program is entitled to invent. Alternative scenarios should remain distinguishable, and an experimental result should not silently become Diadem canon.

Three objectives guide the architecture:

- **Connected rather than isolated outputs.** Components exchange identified quantities and results through declared dependencies, instead of unrelated scripts producing superficially compatible maps.
- **Explainable assumptions and limitations.** Inputs carry their units, spatial and temporal context, evidence and status. Missing knowledge must remain visible.
- **Repeatable experimentation.** Results are tied to the source, inputs and runtime that produced them, with caching, continuation and recovery designed around those identities.

These are project objectives supported by the mechanisms below. They do not imply that every category is fully coupled, calibrated or ready for a whole-world run.

## The 18 modelling categories

The following list follows the exact category order in the [snapshot contract](engineering/work/generator_upgrade_r11/snapshot.py). The [registered operation catalogue](engineering/work/generator_upgrade_r26/registry.py), retained by [R31](engineering/work/generator_upgrade_r31/registry.py), contains **32 operations spanning all 18 categories**; several operations serve more than one category.

**Category coverage means implemented component entry points, not 18 finished or scientifically accepted systems.** Most scientific routes still require dependencies or inputs absent from the public development package. The table describes their actual scope rather than promising unrestricted generation.

| # | Category | What the current implementation covers |
| --- | --- | --- |
| 1 | **Plate tectonics** (`plate_tectonics`) | [Structural and motion snapshots](engineering/work/diadem_tectonics_r2/snapshot.py) from supplied fault, block, event and lineage records. Declared block velocities are not a simulation of rigid plates or inferred geological history. |
| 2 | **Geology** (`geology`) | [Regional geological interpretation, layered ground columns and material properties](engineering/work/generator_upgrade_r26/physical.py) that can feed terrain calculations. Results depend on selected source fields and explicit geological assumptions. |
| 3 | **Topography and topology** (`topography_topology`) | [Terrain construction, advancement and derived views](engineering/work/generator_upgrade_r31/topography.py), including the relationships used to route water and sediment. The native route remains bounded; realistic mountain formation is not accepted. |
| 4 | **Hydrology** (`hydrology`) | [Surface-water routing and terrain/water interactions](engineering/work/generator_upgrade_r26/physical.py) using declared runoff, connectors, durations and ground states. Conservation checks do not establish a complete calibrated watershed model. |
| 5 | **Political borders** (`political_borders`) | [Physical district formation followed by political assignment and typed joins](engineering/work/generator_upgrade_r20/pipeline.py). Political rules and exclusions are supplied separately; the model does not invent legitimate ownership or approve a map. |
| 6 | **Settlements** (`settlements`) | [Settlement-candidate construction](engineering/work/generator_upgrade_r26/human.py) from explicit candidate, spatial and supporting inputs. Candidate opportunities are not automatically realised settlements or accepted canon. |
| 7 | **Populations** (`populations`) | [Reference-population assignment and scenario placement](engineering/work/generator_upgrade_r22/placement.py), with supplied weights and capacity limits, exact totals and visible unplaced balances. This is not autonomous demographic history generation. |
| 8 | **Biomes** (`biomes`) | [Cell classification](engineering/work/generator_upgrade_r26/environment.py) using climate metrics, plant functional-type results and declared classification controls. A classification remains conditional on those inputs and rules. |
| 9 | **Climate** (`climate`) | [Bounded moist-air transport along a transect](engineering/work/generator_upgrade_r4/climate.py), driven by prescribed atmospheric conditions. This is not a global atmospheric-circulation model. |
| 10 | **Precipitation** (`precipitation`) | [Precipitation transport and rain/snow partitioning](engineering/work/generator_upgrade_r26/environment.py), using explicit temperature and phase laws. It does not independently discover an entire world's weather. |
| 11 | **Plant and animal ranges** (`plant_animal_ranges`) | [Species density, finite stocks, ranges, residence exposure and recruitment](engineering/work/generator_upgrade_r22/species.py), using selected biological parameters and evidenced geographical applications. Natural-history prose is not silently converted into numerical coefficients. |
| 12 | **Soils and ground conditions** (`soils_ground_conditions`) | [Coupled soil heat/water calculations](engineering/work/generator_upgrade_r26/environment.py), crop–soil interactions and [rooted ground carried through terrain changes](engineering/work/generator_upgrade_r22/moving_roots.py). Material and biological inputs remain explicit. |
| 13 | **Erosion and sediment transport** (`erosion_sediment_transport`) | [Incision, material removal, transport and deposition](engineering/work/generator_upgrade_r31/topography.py) within the terrain/geological routes. Numerical accounting and bounded error checks are separate from empirical acceptance of the erosion laws. |
| 14 | **Seas and coastal processes** (`seas_coastal_processes`) | [Explicit coastal cases and continuation](engineering/work/generator_upgrade_r19/driver.py), including flow, sediment and finite river-pulse stores. This is a bounded coastal model, not a complete global ocean simulation. |
| 15 | **Resources and land suitability** (`resources_land_suitability`) | [Resource and suitability arrays](engineering/work/generator_upgrade_r26/environment.py) built from declared registers and source arrays. Modelled opportunity is not proof of an observed deposit, extractable reserve or productive site. |
| 16 | **Land use and agriculture** (`land_use_agriculture`) | [Land commitments, timed finite irrigation, crops and local food accounting](engineering/work/generator_upgrade_r21/pipeline.py), with distinct reduced and coupled-soil alternatives. The runner does not automatically register actual Diadem farms. |
| 17 | **Infrastructure and connectivity** (`infrastructure_connectivity`) | [Static transport fields](engineering/work/generator_upgrade_r26/human.py) and [connections between placed people, supplied demand and finite service networks](engineering/work/generator_upgrade_r22/placement.py). Placement cannot create missing stocks or route capacity. |
| 18 | **Natural hazards** (`natural_hazards`) | [Bounded shallow-soil stability calculations](engineering/work/generator_upgrade_r26/physical.py) using supplied slope, material, pore-pressure and root-reinforcement cases. The category is not a general earthquake, volcano or disaster simulator. |

## How Atlas works

### 1. Bind the inputs before computing

A recipe identifies its world, snapshot, calendar, spatial frame, vertical reference and scenario. Component ports declare the quantity, unit and spatial/temporal support expected on each connection. Source files and selected implementations have recorded identities.

This helps prevent a result for one area, season or scenario being mistaken for an interchangeable input elsewhere. The [snapshot contract](engineering/work/generator_upgrade_r11/snapshot.py) distinguishes modelled products, supplied constraints and unknown results, and carries unresolved issues alongside the output.

### 2. Connect explicit component operations

A recipe forms a **dependency graph**: each operation names what it consumes and produces. The [R31 registry](engineering/work/generator_upgrade_r31/registry.py) connects current and retained producers through that interface. For example, the geological route can construct material columns, apply a declared terrain/water forcing and expose a derived terrain view.

This is not a single universal pipeline that automatically runs all 18 categories. A recipe selects the relevant operations and must provide the required inputs. Connections still need meaningful physical assumptions; matching interface fields alone is not scientific validation.

### 3. Preserve numerical meaning

The native terrain work uses [explicit numerical policies](engineering/work/native_terrain_r2/numerics.py), including fixed-quantum integer accounting and deterministic allocation for represented quantities. [Evolution checks](engineering/work/native_terrain_r2/evolve.py) compare alternative step resolutions, track error budgets and refuse unsupported conditions.

Not every solver uses exact arithmetic: other components retain their disclosed floating-point methods and tolerances. Likewise, a drainage-topology change that requires explicit treatment is a reason to stop, not permission to force continuation. The current native accepted-step ceiling remains 256.

### 4. Reuse work without disguising changed inputs

The [execution machinery](engineering/work/generator_upgrade_r24/executor.py) schedules ready operations after their dependencies finish; bounded workers support independent work. Ordered terrain intervals and shared-state operations still require their intended sequencing.

The [R12 runtime](engineering/work/generator_runtime_r12/) combines invocation identities, authenticated cache records and continuation checks. A cached result is not accepted simply because its filename exists. Declared dependency or source changes affect reuse, while timing and reuse diagnostics remain distinguishable from scientific content.

### 5. Branch experiments without duplicating closed history

[Native terrain R5](engineering/work/native_terrain_r5/) stores identical closed compressed history records once and lets independent controls reference them. Branches share those immutable bytes while retaining separate current states. Control publication checks for stale or changed state before replacement.

A shared store is therefore a dependency, **not a disposable cache**. The [R5 operational tools](docs/R5_OPERATIONS.md) inventory dependencies and support byte-preserving backup, verification and staged recovery. They do not replace the original runtime's validation of a scientific checkpoint.

### 6. Review results before accepting them

Execution completion, numerical checks, scientific validation and fictional-world canon are separate outcomes. Source-bound receipts make a result inspectable; they do not make it physically true. Atlas preserves this distinction in the [connected executor](engineering/work/generator_upgrade_r24/executor.py) and [current-state record](docs/CURRENT_STATE.md).

## What has been achieved

Progress below describes implemented work or explicitly recorded evidence, not a new test run triggered by this README.

| Area | Demonstrated progress | Remaining boundary |
| --- | --- | --- |
| Connected generator | Implementations through **generator upgrade R31**, with registered routes across the 18 categories and explicit source/operation identities. R31 replaces six topography routes while retaining other operation identities. | Connected component coverage is not an accepted end-to-end world. |
| Execution infrastructure | **Runtime R12** provides tested graph execution, authenticated caching and worker behaviour; the wider orchestration also retains its connected scheduler. | The public component tests are not full R31 integration tests. |
| Native terrain development | R2 addressed numerical representation; R3 reduced repeated copying; R4 selected interval prediction; R5 introduced shared immutable history. | R4 changes requested/rejected history; full historical-trajectory identity must not be inferred. Native terrain is only one part of Atlas. |
| Shared-history storage | In three recorded matched, already-loaded branch comparisons, R5 reduced creation time from **3.70 to 0.68 seconds** and added disk from **8.00 to 0.88 MB**. | Ordinary interval timing was essentially unchanged. This is a branch/storage result, not a solver speed-up or whole-world forecast. |
| Recovery support | Dependency inventory, deduplicated byte backup, independently anchored verification and new-directory restoration, with **49 synthetic recovery tests** recorded passing. | A real Windows backup and isolated native restart still need their own evidence. |
| Independent development | A clean offline public setup recorded **277 passing tests**: 127 runtime, 25 selected numerical and 125 tooling tests, with no failures, errors or skips on Linux/CPython 3.13.5. | This is a dated, explicitly selected test set, not all Atlas tests or a claim about every operating system. |

Evidence: [native development and measurement limits](docs/CURRENT_STATE.md), [R31 integration tests](engineering/work/test_r31_registry.py), [recovery evidence](docs/R5_OPERATIONS_EVIDENCE.md), [independent-development evidence](docs/INDEPENDENT_DEVELOPMENT_EVIDENCE.md). Successive timing ratios have different scopes and must not be added or multiplied into a headline generator speed-up.

## What Atlas produces

The code contains several output families rather than just a rendered map:

- **Structured component products and receipts:** identified values, units, source/status information, unresolved issues and execution evidence exchanged through the graph.
- **Physical and spatial state:** geological columns, terrain and water state, numerical arrays, candidate geometries, allocations and related analytical results, depending on the selected route.
- **Checkpoints and history:** native controls plus their referenced compressed records, with separate source/runtime dependencies needed for continuation.
- **Review and interchange products:** the retained [shared generator](shared_generator/engine/) includes spatial/database builders and [analytical exports](shared_generator/engine/export_analytical_tables.py), including Parquet and CSV derived from database tables. These are separate retained workflows, not outputs of the small public demonstration.

The public repository does **not** ship a finished Diadem world or its large generated datasets. It is a source and development repository, not a ready-made world download.

The runnable public example is deliberately small: a [four-node integer graph](development/fixtures/runtime_graph.json) produces `a=2`, `b=3`, `c=3`, `d=11`. Its second execution reuses all four cached products and is checked against independent expected values and the retained graph implementation. This demonstrates execution and reuse, not landscape generation.

## Try the public development package

Use CPython **3.12 or 3.13** and a fresh writable checkout. From the repository root, the bootstrap creates an isolated, editable public-component environment **offline**, without pip, third-party package downloads, private inputs or the original Windows installation.

### Windows PowerShell

```powershell
py -3.13 -I -B tools/develop.py bootstrap
.\.atlas-dev\venv\Scripts\python.exe -I -B tools/develop.py smoke --binding .atlas-dev/bindings/initial.json
.\.atlas-dev\venv\Scripts\python.exe -I -B tools/develop.py test --binding .atlas-dev/bindings/initial.json --profile all-public --report .atlas-dev/tests-initial.json
```

### Linux or macOS

```sh
python3.13 -I -B tools/develop.py bootstrap
.atlas-dev/venv/bin/python -I -B tools/develop.py smoke --binding .atlas-dev/bindings/initial.json
.atlas-dev/venv/bin/python -I -B tools/develop.py test --binding .atlas-dev/bindings/initial.json --profile all-public --report .atlas-dev/tests-initial.json
```

`all-public` runs the three selected `runtime`, `numerics` and `tooling` profiles, **not indiscriminate tests of the entire repository**. These commands exercise bounded public fixtures and component tests; they are not world-generation commands. Windows/macOS commands are documented but were not verified on those systems in the recorded delivery; the tested platform was Linux/CPython 3.13.5.

Bootstrap refuses an existing environment rather than overwriting it. Changes to source, runtime or checkout location require an explicit new public binding; do not edit an old binding to make it pass. See the [development guide](docs/INDEPENDENT_DEVELOPMENT.md) for capability checks, new bindings, focused profiles and troubleshooting.

## Repository guide

| Location | Purpose |
| --- | --- |
| [`engineering/work/generator_upgrade_r31/`](engineering/work/generator_upgrade_r31/) | Current wider generator integration. Retains earlier implementations; a higher directory number is not a replacement for every predecessor. |
| [`engineering/work/generator_runtime_r12/`](engineering/work/generator_runtime_r12/) | Execution, cache, source-capture and worker infrastructure. |
| [`engineering/work/native_terrain_r5/`](engineering/work/native_terrain_r5/) | Latest bounded native terrain storage/session route; depends on R1–R4 and other retained components. |
| [`engineering/work/`](engineering/work/) | Geological, tectonic, terrain, environmental, biological and human-system implementations and their tests. |
| [`shared_generator/engine/`](shared_generator/engine/) | Retained shared generator builders, contracts, validators and export tools. |
| [`development/`](development/) | Public development package, environment/profile declarations and small fixtures. |
| [`tools/`](tools/) and [`tests/`](tests/) | Development entry point, source-wiring checks, R5 recovery tools and focused tooling tests. |
| [`docs/`](docs/) | [Current state](docs/CURRENT_STATE.md), [coding/dependency map](docs/CODING_SAFETY.md), [recovery runbook](docs/R5_OPERATIONS.md) and [development workflow](docs/INDEPENDENT_DEVELOPMENT.md), with evidence records. |

## Development direction

The priorities are capability and trustworthy evidence, not simply increasing revision numbers:

1. **Establish physical acceptance.** Test the unresolved terrain/mountain behaviour and other modelling assumptions against appropriate explicit criteria. A reproducible implementation is only the starting point.
2. **Extend meaningful coupling.** Improve scenario connections across the 18 categories while preserving their units, timing, finite resources, uncertainties and supplied world constraints.
3. **Complete reproducible scientific installations.** Extend beyond the public component package with compatible, explicitly identified scientific/runtime dependencies and public fixtures. Portability must not masquerade as historical restart compatibility.
4. **Simplify and harden operation.** Reduce delicate adapter indirection when changing the affected code, maintain source/dependency maps and establish real recovery drills for shared stores and native controls.

These are development priorities, not completed features, delivery dates or permission to start simulations. Optimisations should follow measured bottlenecks in the relevant workload, not speculative whole-generator speed claims.

## Scope, safeguards and contribution

The public scientific source originated in the **15 September 2026 export**, followed by separately documented public tooling and development additions. It includes the approved embedded Diadem values and source references. It is not automatic synchronisation with the original Windows workspace, and a GitHub change is not local integration until reviewed and applied there.

Private coordination and source-owner records, personal tools, credentials, installed libraries, large input datasets, saved checkpoints and generated world data remain excluded. Public copies sanitise local directory names and a private project identifier; **their bytes do not automatically authenticate historical execution hashes**.

The full scientific routes still depend on excluded components, including the recursively sealed scientific bundle and the original bound checkpoint codec. Native compressed history uses a pinned Windows Zstandard library. Copying these source folders to another operating system does not establish compatibility. The public package deliberately does not fabricate replacements for historical dependencies.

Read [AGENTS.md](AGENTS.md) and the relevant [coding-safety map](docs/CODING_SAFETY.md) before changing code. Identify AI assistance, preserve unrelated work and provide focused, reproducible evidence. Keep the following boundaries intact:

- Do not disable hash/source verification, silently repin checkpoints, relax acceptance tolerances or raise the native 256-step ceiling to obtain a pass.
- Preserve retained predecessors and immutable history dependencies. Backup, restoration, cleanup and migration require explicit scope; a copied control alone is not a restartable delivery.
- Report what actually ran and what remains untested. Code approval, scientific validation and Diadem canon are separate decisions requiring their own review.

Proposed improvements and pull requests are welcome. No automatic merging, background simulation, full-world/whole-year run or synchronisation is enabled by this documentation or the public setup.

## Licence

No project-wide licence has been selected by the owner. Existing third-party notices retain their own terms; public visibility is not a new project-wide licence grant.
