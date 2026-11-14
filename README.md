# Atlas

**A vibe-coded world generator for physically informed, internally consistent worldbuilding.**

Atlas is intended to become a **world-agnostic generator**, developed primarily for the fictional world of the **Diadem**. The Diadem is its first major use case, not a required setting or a maximum extent: eventual scope may include **whole planets**. Its aim is to connect physical landscapes with their ecological and human systems, at resolutions selected for coverage, purpose and available resources. Current code still contains Diadem-specific dependencies; generalised or planetary generation is not claimed as implemented.

**OpenAI's ChatGPT/Codex and Anthropic's Claude Code do the coding under the project owner's direction.** The owner supplies the worldbuilding requirements, decisions and feedback; AI assistants write the code and carry out much of the technical testing. Vibe-coding describes the development process, not a substitute for source review, reproducible tests or independent scientific validation.

**Current status: experimental** Atlas has implementations across 18 modelling categories, connected execution infrastructure and a runnable public component-development package. It is not yet a complete, independently validated world generator. Mountain and wider terrain realism remain unaccepted.

[Product and scale](#product-and-scale-contract) · [The 18 categories](#the-18-modelling-categories) · [How it works](#how-atlas-works) · [Current state](docs/CURRENT_STATE.md#current-delivery-and-acceptance) · [Outputs](#what-atlas-produces) · [Try it](#try-the-public-development-package) · [Roadmap](#development-direction)

## What Atlas is trying to achieve

The goal is an inspectable worldbuilding system in which decisions have traceable consequences. A change to terrain can matter to water movement; water and ground conditions can matter to vegetation and agriculture; those results can inform settlement opportunities, population support and connectivity.

Atlas combines **supplied world constraints** with **explicit modelling choices and reproducible generation**. Existing geography, species parameters, population records and political decisions are inputs where a component requires them. New worlds may instead use declared generators, parameters and seeds; a complete pre-authored world is not an intended universal prerequisite. Generated assumptions must not masquerade as measured or authored facts. Alternative scenarios remain distinguishable, and experimental results do not silently replace authored world facts.

Three objectives guide the architecture:

- **Connected rather than isolated outputs.** Components exchange identified quantities and results through declared dependencies, instead of unrelated scripts producing superficially compatible maps.
- **Explainable assumptions and limitations.** Inputs carry their units, spatial and temporal context, evidence and status. Missing knowledge must remain visible.
- **Repeatable experimentation.** Results are tied to the source, inputs and runtime that produced them, with caching, continuation and recovery designed around those identities.

These are project objectives supported by the mechanisms below. They do not imply that every category is fully coupled, calibrated or ready for a whole-world run.

## Product and scale contract

The [product and scale contract, revision 2](docs/PRODUCT_AND_SCALE_CONTRACT.md)
defines a **world-independent, multiresolution product direction**, not a completed
generator. The reusable engine is to be separated from world profiles and run/detail
profiles. Regional, continental and eventual planetary coverage are within scope;
the current Diadem frame is one case, not a hard-coded universal geometry.

There is **no fixed 100 m/10 m delivery target or permanent finest-resolution cap**.
Choose resolution per extent, layer and purpose against a finite budget, including
**1 m or finer where feasible**. At a fixed budget, larger coverage generally calls
for a coarser base representation, while selected areas can retain finer detail.
Higher-resolution larger areas remain possible targets where the budget supports
them; neither a 1 m planet nor automatic adaptive refinement is implemented or
promised here. Evidence/assumption, process, exchange and output support remain
separate: generated fine detail is valid worldbuilding but not measured accuracy.

| Scope | Source-defined size or limit | Do not infer |
| --- | --- | --- |
| Retained Diadem 100 m terrain interface | **18,600 × 22,000 = 409,200,000 cells** over a **2,200 × 1,860 km** rectangle. A single raw float32 field is **1,636,800,000 bytes (1.52 GiB)**. | Land/active area, a whole-pipeline RAM estimate or a completed world-scale simulation. |
| Current native R1–R5 common domain | **256 cells** (at most **16 × 16** for a square grid), **2,048 connectors**, **8,192 total layers**. | A production-sized terrain backend or a universal limit for other Atlas routes. |
| Current native continuation | **256 accepted intervals including predecessor history**. R4/R5 proposal requests are at most **5 years**; the retained case runner targets **1,000 elapsed years**. | Achieved physical duration, a Diadem geological timescale, or permission to raise limits. |
| Climate transect | **32 cells per transect**. | A global atmospheric-circulation solver. |
| Existing Diadem 10 m local workflows | Selected footprints; retained local recipes still declare **100 m effective terrain resolution**. | A permanent 10 m product limit, new 10 m evidence, or a ban on feasible 1 m output. |

The contract links each bound to source, uses the Diadem rectangle as an example
(including hypothetical 1 m coverage), and separates **observed limits**, **derived
counts**, **owner-confirmed intentions**, **proposed requirements** and **open decisions**. The [planning record](docs/contracts/product-scale-v1.json)
is documentation, not runnable configuration.

The product is a coherent route through appropriate scientific producers,
execution infrastructure and spatial delivery machinery—not whichever directory
has the highest revision. The retained shared builders consume existing terrain
and water inputs; current bounded native experiments do not yet supply a proven
world-scale replacement. The production connection and its remaining work are tracked in
[current state](docs/CURRENT_STATE.md). World generalisation and eventual planetary geometry,
coverage and physics remain additional design requirements. Production hardware,
RAM/disk/time budgets, requested/selected resolutions, per-process supports, masks
and physical horizons must be specified before a production-size run. This contract does not authorise one.

## The 18 modelling categories

The following list follows the exact category order in the [snapshot contract](engineering/work/generator_upgrade_r11/snapshot.py). The [registered operation catalogue](engineering/work/generator_upgrade_r26/registry.py), retained by [R31](engineering/work/generator_upgrade_r31/registry.py), contains **32 operations spanning all 18 categories**; several operations serve more than one category.

**Category coverage means implemented component entry points, not 18 finished or scientifically accepted systems.** Most scientific routes still require dependencies or inputs absent from the public development package. The table describes their actual scope rather than promising unrestricted generation.

| # | Category | What the current implementation covers |
| --- | --- | --- |
| 1 | **Plate tectonics** (`plate_tectonics`) | The wider R31 route retains [structural and motion snapshots](engineering/work/diadem_tectonics_r3/snapshot.py) from supplied records. The separate [tectonics package](tectonics/README.md) adds W01–W12 physical methods, seeded initial worlds and [I01 coupled-process controls](tectonics/docs/how-it-works/06-physical-integration.md). These additions are not automatically wired into R31 or a completed evolving planet. |
| 2 | **Geology** (`geology`) | [Regional geological interpretation, layered ground columns and material properties](engineering/work/generator_upgrade_r26/physical.py) that can feed terrain calculations. Results depend on selected source fields and explicit geological assumptions. |
| 3 | **Topography and topology** (`topography_topology`) | [Terrain construction, advancement and derived views](engineering/work/generator_upgrade_r31/topography.py), including the relationships used to route water and sediment. The native route remains bounded; realistic mountain formation is not accepted. |
| 4 | **Hydrology** (`hydrology`) | [Surface-water routing and terrain/water interactions](engineering/work/generator_upgrade_r26/physical.py) using declared runoff, connectors, durations and ground states. Conservation checks do not establish a complete calibrated watershed model. |
| 5 | **Political borders** (`political_borders`) | [Physical district formation followed by political assignment and typed joins](engineering/work/generator_upgrade_r20/pipeline.py). Political rules and exclusions are supplied separately; the model does not invent legitimate ownership or approve a map. |
| 6 | **Settlements** (`settlements`) | [Settlement-candidate construction](engineering/work/generator_upgrade_r26/human.py) from explicit candidate, spatial and supporting inputs. Candidate opportunities are not automatically realised settlements or approved world records. |
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

Start with [How Atlas tectonics is made](tectonics/docs/HOW_TECTONICS_IS_MADE.md)
for the scientific explanation in generation and dependency order. Its linked
chapters explain inputs, methods, references, outputs and what the checks establish.
The [physical integration chapter](tectonics/docs/how-it-works/06-physical-integration.md)
connects material history, strength, motion, heat, geometry and accepted-state recovery.
Specialist contracts are linked from that guide and the [package README](tectonics/README.md).

The wider generator uses explicit recipes and identified component ports rather
than a universal pipeline that automatically runs every category. The
[snapshot contract](engineering/work/generator_upgrade_r11/snapshot.py) distinguishes
supplied constraints, modelled products and unknowns;
[R31](engineering/work/generator_upgrade_r31/registry.py) connects selected operations,
while [R12](engineering/work/generator_runtime_r12/) supplies authenticated execution
and reuse. [Native R5](engineering/work/native_terrain_r5/) shares immutable closed
history between experiments. Shared stores are dependencies, not disposable caches;
the [R5 runbook](docs/R5_OPERATIONS.md) covers their operational boundaries.

Use [current delivery and acceptance](docs/CURRENT_STATE.md#current-delivery-and-acceptance)
for implemented scope, reviewed acceptance, evidence and remaining work. Execution,
numerical verification, physical validation and approval of authored-world changes remain separate decisions.
Historical measurements live with their owner records, not in this front page.


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
| [`tectonics/`](tectonics/README.md) | Native tectonics package: usage, commands and navigation to scientific methods, tests, tools, cases and source-bound evidence. |
| [`tectonics/optimisation/`](tectonics/optimisation/README.md) | Optimisation methods, plan navigation and retained source selections; delivery status remains in current state. |
| [`desktop/`](desktop/README.md) | Windows Electron build of the Atlas UI and its tectonics backend (unsigned development build; a rebuild needs the UI owner's snapshot, which is not in this repository). |
| [`tectonics/requirements/`](tectonics/requirements/) | [Windows tectonics environment pins and metadata checks](docs/TECTONICS_ENVIRONMENT.md), distinct from the offline public-component environment and exact native restart identity. |
| [`tools/`](tools/) and [`tests/`](tests/) | Development entry point, source-wiring checks, R5 recovery tools and focused tooling tests. |
| [`docs/`](docs/) | [Current state](docs/CURRENT_STATE.md), [coding/dependency map](docs/CODING_SAFETY.md), [recovery runbook](docs/R5_OPERATIONS.md), [development workflow](docs/INDEPENDENT_DEVELOPMENT.md), [development speed tools](docs/DEVELOPMENT_TOOLS.md) and [current evidence register](docs/CURRENT_EVIDENCE.md), with evidence records. |

## Development direction

The [Atlas roadmap](docs/ATLAS_ROADMAP.md) sets out the production connection,
regional proof and eventual world-independent expansion. The
[product and scale contract](docs/PRODUCT_AND_SCALE_CONTRACT.md) defines coverage,
resolution and budget decisions; the [module scopes](docs/MODULE_SCOPES.md) distinguish
planned non-tectonics work. Use [current state](docs/CURRENT_STATE.md) for the active
checkpoint and outstanding work. These documents do not authorise a simulation.


## Scope, safeguards and contribution

The public scientific source originated in the **15 September 2026 export**, followed by separately documented public tooling and development additions. It includes the approved embedded Diadem values and source references. It is not automatic synchronisation with the original Windows workspace, and a GitHub change is not local integration until reviewed and applied there.

Private coordination and source-owner records, personal tools, credentials, installed libraries, large input datasets, saved checkpoints and generated world data remain excluded. Public copies sanitise local directory names and a private project identifier; **their bytes do not automatically authenticate historical execution hashes**.

The full scientific routes still depend on excluded components, including the recursively sealed scientific bundle and the original bound checkpoint codec. Native compressed history uses a pinned Windows Zstandard library. Copying these source folders to another operating system does not establish compatibility. The public package deliberately does not fabricate replacements for historical dependencies.

Read [AGENTS.md](AGENTS.md) and the relevant [coding-safety map](docs/CODING_SAFETY.md) before changing code. Preserve unrelated work and provide focused, reproducible evidence. Keep the following boundaries intact:

- Do not disable hash/source verification, silently repin checkpoints, relax acceptance tolerances or raise the native 256-step ceiling to obtain a pass.
- Preserve retained predecessors and immutable history dependencies. Backup, restoration, cleanup and migration require explicit scope; a copied control alone is not a restartable delivery.
- Report what actually ran and what remains untested. Code approval and scientific validation are separate decisions requiring their own review.

Proposed improvements and pull requests are welcome. No automatic merging, background simulation, full-world/whole-year run or synchronisation is enabled by this documentation or the public setup.

## Licence

Atlas-owned source code is licensed under **AGPL-3.0-only**. See
[LICENSING.md](LICENSING.md) for the scope and [LICENSE](LICENSE) for the terms.
Third-party material retains its own notices; the code licence does not implicitly
cover fictional-world text, artwork or other non-code creative content.
