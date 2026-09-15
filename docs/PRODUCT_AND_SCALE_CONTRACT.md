# Atlas product and scale contract

**Contract ID:** `ATLAS-PRODUCT-SCALE-1` · **Revision:** 2 · **Date:** 15 September 2026

**Status:** PROPOSED CONTRACT FOR REVIEW; project remains WORKING NON-CANON.

**Source review basis:** [`3ed5dd95b20150553528d9e83c0520b7617652df`](https://github.com/Atlantispy/atlas/tree/3ed5dd95b20150553528d9e83c0520b7617652df).

This implements the requested *product and scale definition*, not the later
production integration or regional experiment. Atlas is vibe-coded: OpenAI
ChatGPT/Codex writes the code under the owner's direction. This revision is for
owner and independent review, including Claude's review; agreement is not assumed.

**Revision 2 corrects the product definition after the owner's clarification:**
Atlas is intended to become independent of the Diadem and may eventually generate
whole planets. Resolution is configurable and budget-dependent, with 1 m or finer
output within scope where feasible; 100 m and 10 m are current Diadem implementation
examples, not permanent product targets. These owner-confirmed intentions do not
establish that the current implementation supports those capabilities.

**Reading rule:** **Observed** identifies a source-defined interface or limit;
**Derived** identifies arithmetic on those values; **Required** states this
proposed product contract; **Open** identifies a decision not established by the
available evidence. A required capability is not a claim of current implementation.
The [companion planning record](contracts/product-scale-v1.json) separates these
classes. It is documentation, not an executable recipe, runtime configuration,
new checkpoint schema or permission to run anything.

## 1. The product we are defining

**Owner-confirmed direction:** Atlas is intended to become a **world-agnostic
world generator**. The Diadem is the primary development use case, not the product's
required setting or maximum extent. The eventual scope includes local areas,
regions, continents and potentially **whole planets**. Existing Diadem-specific
implementations remain what they are; this is a target architecture, not a claim
that generalisation or planetary modelling has been implemented.

**Required:** deliver reproducible, scenario-specific world datasets and explicitly
selected process histories: mutually interpretable physical, ecological and
human-system products with traceable assumptions, unresolved areas and acceptance
status. Worlds without a relevant category, such as populations on an uninhabited
planet, must declare that category not applicable rather than fabricate inhabitants.

There is **no fixed project-wide output spacing or product resolution ceiling**.
Resolution is selected per world, extent, layer, process and detail region against
an explicit performance/storage budget and intended use. **1 m or finer output is
an eligible target where feasible**, not a promised present capability and not
restricted in principle to local areas. Larger fine-resolution coverage remains
eligible when the selected implementation and budget support it. A resolution
choice must be assessed jointly with area, layers, physical duration, error and
boundary requirements; smaller cell spacing alone is not proof of better results.

### Separate reusable engine, world profiles and run profiles

**Required architecture direction, not an implemented module split:**

- **Reusable engine:** world-independent interfaces, processes, scheduling,
  numerical/accounting rules, storage and validation. Do not make Diadem names,
  the current rectangle, its grid direction or its authority paths universal
  assumptions of new interfaces.
- **World profile:** the selected geometry, extent, units, calendar, physical
  parameters, species, cultures and authored constraints. Diadem data is one
  profile. Applicable planetary parameters must be explicit rather than silently
  copied from Earth or the Diadem.
- **Run/detail profile:** selected categories and goals, base/process/output
  supports, detail regions, physical intervals, budgets, stopping rules and
  producer/input identities. No example spacing is an approved default for all runs.

Future generative runs must be able to create new worlds from explicitly selected
parameters, constraints and reproducible seeds. A complete pre-authored terrain,
population or political map must not be a universal prerequisite. Where generated
parameters replace authored inputs, their generator, seed and assumptions must be
identified; this is deliberate generation, not silent invention of missing evidence.

Two modes must remain visible:

| Mode | What counts as success | What it does not prove |
| --- | --- | --- |
| **Integrate supplied world inputs** | Verified terrain, water, political and other selected inputs are combined into consistent analytical products with exact provenance. | That Atlas generated the input mountains, rivers or climate physically. |
| **Generate or evolve new modelled fields** | An identified producer with declared parameters, seed where used, forcing, spatial/time support and acceptance criteria supplies new fields through a reviewed interface; declared procedural refinement can add generated detail. | That an arbitrary existing input can be relabelled as simulated, or a bounded reference model can already generate the whole Diadem. |

**Required:** every release names the mode used for each category. Importing a
terrain authority is a useful production operation; it is not a substitute for
proving a terrain-generating backend. Conversely, existing constraints must not
be discarded merely to make a workflow appear fully generative.

### Roles, not a choice of one directory

- **Spatial processing/delivery candidates:** `shared_generator/engine` contains
  the retained raster, database, analytical and export workflows. Its Stage 6C
  builder consumes an existing terrain authority, hydrology and registry; it is
  not itself a from-scratch terrain constructor. **Observed:** [builder](../shared_generator/engine/build_stage6c_100m.py).
- **Scientific producer/reference candidates:** `engineering/work` contains
  heterogeneous models, including small reference/experimental routes and
  array-based components. R31 is an orchestration entry point, not a demonstration
  of a complete world-scale pipeline. **Observed:** [R31 registry](../engineering/work/generator_upgrade_r31/registry.py).
- **Execution and evidence:** runtime R12 and retained connected orchestration
  provide source-aware execution and reuse. Preserve useful mechanisms without
  requiring production solvers to adopt every reference implementation's data
  structure. **Observed:** [route map](CODING_SAFETY.md).
- **Integration boundary:** producer selection, exchange schemas and the working
  route into delivery remain to be established in recommendation 2. This contract
  does not select or implement that bridge.

A production backend may use arrays or other suitable representations and a
small reference implementation may check it. Neither numerical agreement nor
exact arithmetic establishes that the physical model is true. No blanket
conversion to `Fraction`, floating point, GPU processing or a different solver is
selected here.

## 2. Required inputs and outputs

### Input contract

Each actual release recipe must identify these dependencies, or explicitly mark
an unused item as not applicable with a reason. Missing required data blocks a
complete release claim; it must not be silently filled with plausible values.
A declared generative procedure may create an input from its specified parameters
and seed, provided the product is labelled generated and its provenance is retained.
This does not require every input to originate in an already authored world.
Private locations and data belong in private manifests, not this public document.

| Input family | Required declaration |
| --- | --- |
| Frame and domain | World/scenario/snapshot/calendar IDs; world geometry and extent; horizontal frame and units; vertical datum and units; origin, axis directions, cell-centre convention; domain, land/water/unknown masks and coverage geometry; mask IDs/hashes. A planetary profile must declare surface geometry/size and valid distance, area and neighbour definitions; a planar profile must declare its finite boundaries. |
| Selected spatial authorities | Terrain generation and lineage; water/coast/catchment topology; relevant political and settlement registries; per-layer/per-footprint authority and permitted overrides. An input labelled “working” is not canon. |
| Physical state and forcing | Selected geological/material state, initial terrain or its generative recipe, atmospheric/water conditions, rates versus amounts, time intervals, coefficients and their evidence or declared assumptions. Applicable gravity, rotation, atmospheric and other world parameters must be explicit where a model consumes them. Supplied, generated and modelled forcing remain distinguishable. |
| Biological and human inputs | Species parameters, range/stock/occupancy definitions, population baselines, crop/land commitments, resources, political choices, service/network capacities and constraints required by the selected operations. Narrative does not automatically supply numerical parameters. |
| External boundary exchanges | Which neighbouring areas/catchments/coasts contribute water, sediment, heat, people or goods; their supports, intervals, input hashes and conservation/transfer rules. A cropped region does not erase its upstream sources. |
| Source and runtime | Exact consumed source identity, producer versions, input hashes, selected libraries/interpreter/platform and any required original codec, source bundle, authority approval or checkpoint chain. Locate dependencies separately from authenticating them. |
| Execution and acceptance | Selected categories and dependency graph; reproducible seeds where used; immutable numerical/tolerance policy; requested and selected resolutions, detail/coverage strategy and physical endpoints; workload/budget envelope; stopping conditions and explicitly authorised output locations. Changes in resolution require a revised identified plan, not silent fallback. |

Existing mechanisms are starting points, not a claim that all fields above are
already combined in one release manifest: [snapshot context and ports](../engineering/work/generator_upgrade_r11/snapshot.py),
[relative source catalogue](../shared_generator/engine/source_catalogue.py),
[terrain generation identity](../shared_generator/engine/stage6c_terrain_authority.py).

### Output contract

**Required:** a selected production release provides the following logical bundle.
These are product requirements, not a newly implemented storage format.

| Output | Required content and meaning |
| --- | --- |
| Release manifest | Input/source/runtime identities; category coverage and mode; masks, frames, times and resolutions; selected producer and output identities; unresolved issues; acceptance status. |
| Physical/spatial products | Terrain and relevant ground, water, climate, biome, resource and hazard fields, plus applicable vector/network topology. Every product records actual evidence and process support, not only its raster spacing. |
| Ecological/human products | Selected ranges/stocks, populations, candidates or realised settlements, land use, political assignments and network/service outputs. Preserve the distinction between opportunity, scenario allocation and accepted world state. |
| Accounting and consistency evidence | Water/material/other finite-resource budgets where applicable; graph connectivity, unit/time/frame checks; boundary transfers; masked/unknown regions and unallocated balances. |
| Review/interchange outputs | Spatial layers and analytical tables linked to the same release. Existing Zarr, SQLite/GeoPackage, Parquet and CSV routes are candidates with different roles, not interchangeable editable authorities. |
| Change and recovery record | Which dependencies changed, which products were reused/rebuilt, checkpoint dependencies where continuation is claimed, and which complete output generation is current. A history control without its store/runtime is not a restartable delivery. |

Coverage statuses in the release contract must distinguish **supplied**, **modelled**,
**derived/refined**, **unknown/blocked**, and **not applicable** with reasons. These
are descriptive product states, not changes to existing runtime enums. A partial
regional study may be useful with declared exclusions; an “all-category world”
claim must account for all 18 categories as applicable, not applicable with reason,
or explicitly unresolved. It cannot hide missing areas behind zero values.

## 3. Spatial contract: four different resolutions

**Required:** describe four different quantities for each spatial product:

1. **Evidence/assumption support:** the footprint and effective scale supported
   by the source or declared generative model. Measured observations, simulated
   processes, authored constraints and procedural detail have different claims.
   A vector may have exact stored geometry without known physical accuracy at
   every vertex.
2. **Process support:** the cells, columns, reaches, transect segments, catchments
   or administrative units on which the calculation actually operates.
3. **Exchange support:** the support used when transferring information between
   components, including any aggregation or interpolation.
4. **Output sampling:** where values are stored or displayed: a selected grid,
   mesh or vector representation, potentially with multiple detail levels and
   1 m or finer sampling where feasible. No single spacing is universal.

They may differ. **A 1 m output does not imply that climate or tectonics were
solved at 1 m, or that every metre is observationally known.** Fine detail generated
for a fictional world is legitimate: label its process, assumptions and relationship
to the coarser state. Distinguish physically simulated detail, constrained procedural
detail and simple interpolation. Interpolation alone is not new physical information.
Retained local Diadem recipes themselves declare `effective_resolution_m=100.0`
while producing 10 m cells:
[Stage 6C5](../shared_generator/engine/build_stage6c5_10m.py) and
[Stage 6C5R](../shared_generator/engine/build_stage6c5r_physical_10m.py).

### Resolution follows coverage, purpose and budget

**Required planning principle:** for a fixed budget, larger coverage generally
favours a coarser base representation; smaller requested areas can use finer detail.
This is a starting heuristic, not a law that prevents high-resolution large worlds
when resources and algorithms allow them. Select useful fidelity, not the smallest
possible number irrespective of purpose.

For a fixed-area two-dimensional square-cell raster, **N = A / h²**, where A is
area in square metres and h is cell spacing in metres (ignoring boundary rounding).
Reducing spacing by 10 multiplies the cell count by **100**. With unchanged dtype
and field count it also multiplies raw field storage by 100; solver runtime need
not scale by the same factor. At the same cell budget, spacing scales with the
square root of area. These are arithmetic relations, not Atlas benchmarks.

**Proposed multiresolution design:** retain a consistent coarse world context and
add finer regions where needed. Support the selection of per-layer/process detail,
regionally generated or cached detail, and streaming where justified. Do not require
all detailed cells of an entire world to exist in memory or storage simultaneously.
The implementation strategy remains open; these are requirements for the future
production design, not features already delivered by the current R5 store.

Examples—not presets or guarantees—include a coarser planetary context with finer
continents, detailed regions and 1 m local areas; a small map wholly at 1 m; or a
larger high-resolution area when its measured resource envelope permits it. “Only
local 1 m” and “always global 100 m” are both inappropriate permanent restrictions.
Persist requested versus selected resolution and any explicit refinement/coarsening
decision. Refuse or obtain a revised profile if the request cannot meet its budget;
never silently return a coarser result under the requested resolution label.

Reproducible refinement must preserve neighbouring-region agreement, selected
parent constraints and the identities of generated detail. It must declare whether
fine results can feed back into the coarse world. Repeating an equivalent request
must not change neighbouring results merely because detail was requested in a
different order, unless the selected stateful procedure explicitly models that order.
A procedural feature that changes drainage or resources must update/revalidate its
consumers; decorative detail cannot silently change the physical authority.

### Future planetary coverage

**Required future design capability, not current implementation:** a whole-planet
profile needs an explicitly declared surface/size, frames, units, cell areas,
neighbours and cross-region joins appropriate to that surface. It must avoid treating
a rectangular map edge as the planet's physical boundary. Longitude wrap or polar
handling is representation-dependent; choose and validate a representation rather
than assuming the current Diadem Cartesian frame is global. Closed-surface boundary
accounting, atmosphere/ocean coupling and applicable world parameters require their
own acceptance evidence. This change does not select a spherical mesh, projection,
planet radius, planetary climate model or atmosphere.

### Diadem workload example — not the generic world frame

**Observed Diadem-specific interface:** the retained authority expects **18,600 rows × 22,000
columns**, float32, with transform `(0.1, 0, 0, 0, 0.1, 0)` in local kilometres.
The source stack declares `LOCAL_CARTESIAN_KM_NO_EPSG`; map north is decreasing Y,
not a guessed EPSG coordinate system. These are existing Diadem interface expectations,
not generic Atlas dimensions or fresh validation of the absent live terrain. Sources:
[authority constants](../shared_generator/engine/stage6c_terrain_authority.py),
[source-stack frame](../shared_generator/engine/stage6c_source_stack.py),
[builder grid note](../shared_generator/engine/build_stage6c_100m.py).

**Derived:** the rectangular frame is **2,200 km × 1,860 km**, or **4,092,000 km²**.
This is not the Diadem's land area, political area, active-cell count or ecological
support area. Those require their actual selected masks. No masked count is inferred
from another review's approximate figures.

| Spacing over this entire rectangle | Rows × columns | Cells | One uncompressed float32 field | Role in this contract |
| --- | --- | ---: | ---: | --- |
| 4 km | 465 × 550 | 255,750 | 1,023,000 bytes (0.98 MiB) | Scale arithmetic only; not a selected process grid. |
| 1 km | 1,860 × 2,200 | 4,092,000 | 16,368,000 bytes (15.61 MiB) | An existing carrier support; not universal process or evidence resolution. |
| 100 m | 18,600 × 22,000 | 409,200,000 | 1,636,800,000 bytes (1.52 GiB) | Retained Diadem interface; not a universal delivery requirement. |
| 10 m | 186,000 × 220,000 | 40,920,000,000 | 163,680,000,000 bytes (152.44 GiB) | Hypothetical whole-frame workload; no run selected or universal prohibition. |
| 1 m | 1,860,000 × 2,200,000 | 4,092,000,000,000 | 16,368,000,000,000 bytes (14.89 TiB) | Hypothetical whole-frame workload; 1 m eligibility does not guarantee feasible dense coverage. |

Calculation: `N = rows × columns`; `raw_bytes = N × 4`.
MiB = 2²⁰ bytes; GiB = 2³⁰ bytes; TiB = 2⁴⁰ bytes. A float64 field uses twice these bytes. These
figures exclude masks, multiple layers, working copies, halos, indexes, Python
objects, history, codecs and export staging. They are neither RAM forecasts nor
compressed-storage predictions. Cell spacing and float32 encoding do not assert
vertical accuracy. For contrast, a **1 km × 1 km** square at **1 m** contains
**1,000,000 cells**; one raw float32 field is **4,000,000 bytes (3.81 MiB)**.
This isolates area dependence; it is not a promise that all processing fits in 4 MB.

### Proposed delivery tiers

| Tier | Spatial requirement | Definition still needed before a run |
| --- | --- | --- |
| **Component/reference** | Explicit small domain within the selected component's real limits; no world coverage claim. | Exact fixture, support, boundary conditions and applicable limits. |
| **Regional integration** | A named connected catchment/coastal/other justified region with required external dependencies; selected delivery grid. | Region polygon, upstream closure, halo/exchange rules, valid mask and cell count. No arbitrary tile is selected here. |
| **World/continental snapshot** | World-profile-defined geometry and coverage with budget-selected base and detail resolutions; applicable categories declared. The Diadem is an initial case, not a compulsory setting. | World profile, valid domain, resolutions, per-category producers and finite budgets. |
| **Whole-planet snapshot — eventual scope** | Consistent closed-surface representation and cross-region exchanges, with variable detail; do not reuse a planar rectangle as planetary physics. | Planet geometry/parameters, global processes, mapping/joins, resolutions and independent feasibility/acceptance evidence. |
| **Detailed area/product** | Selected sites, corridors, regions or full small maps at requested feasible resolution, including 1 m or finer. No permanent local-only cap on high-resolution coverage. | Footprints, evidence/assumption support, refinement method, boundary inputs, process support and measured budget. |

**Observed local examples, not a compulsory production tiling design:** Stage 6C5
uses a 2.2 km core (**220 × 220 fine cells**) with further support. Stage 6C5R uses
a 3 km delivered window (**300 × 300**) and a 5 km analysis window
(**500 × 500**, before other support). These scripts are bounded local consumers;
existing site selections do not select all future local outputs.

### Exchange rules that a production route must satisfy

**Required:** every scale-changing edge records its source/destination support,
method, units, coverage, missing-data policy and error/validation evidence.
Extensive quantities such as mass, water volume or headcount must conserve totals
within the specified boundary and declared numerical policy. Intensive quantities
such as elevation, temperature or density require a physically appropriate
transfer rule, not indiscriminate summation. Categorical and identity fields must
not be numerically averaged into invented classes or ownership.

For connected water/sediment networks, preserve contributing areas, receiver/outlet
identities, transfer time intervals and boundary ledgers. Halos alone do not solve
whole-catchment routing. Independent tiles are permissible only where independence
is justified; scheduling more 256-cell jobs does not prove correct regional coupling.
Any terrain replacement must resolve its compatibility with selected water/coast
constraints rather than silently overriding them or creating uphill/drainless joins.
For mixed-resolution or planetary neighbours, conservation uses the actual declared
cell areas and boundary geometry, not the assumption that every stored sample
represents the same area.

## 4. The 18 categories: product support and time meaning

The keys and order come from the existing
[snapshot contract](../engineering/work/generator_upgrade_r11/snapshot.py).
This table specifies what a selected release must declare; it does not add models.
Detailed current component scope remains in the [README category table](../README.md#the-18-modelling-categories).

| # | Category key | Required product/support | Required temporal meaning; no default horizon implied |
| --- | --- | --- | --- |
| 1 | `plate_tectonics` | Selected structural blocks, faults, relationships and declared motion in a fixed frame. | Snapshot epoch; velocity reference interval. Do not infer past plate evolution from a motion snapshot. |
| 2 | `geology` | Selected material domains and supported ground columns/layers. | Geological state epoch and any explicit event sequence. Rock age is not solver runtime. |
| 3 | `topography_topology` | Terrain field and receiver/connectivity state with evidence/process/output supports. | Surface snapshot; where evolved, initial and final physical time, forcing intervals and accepted history. |
| 4 | `hydrology` | Catchments, reaches/storages, routed water and external exchanges. | Rate versus integrated volume, event/season interval and initial/final stores. |
| 5 | `political_borders` | Boundaries and assignments from explicit decisions on named spatial units. | Effective date/scenario, not an inferred political history. |
| 6 | `settlements` | Candidates or realised settlements, stable IDs and supporting footprints. | Assessment/realisation date and selected scenario. Candidate age is not simulated settlement history. |
| 7 | `populations` | Supported population ledgers, allocations and unplaced balances. | Census/reference date or explicitly modelled demographic interval; stock versus flow. |
| 8 | `biomes` | Conditional biome classes on declared cells/supports. | Climate/vegetation assessment period, including seasonal versus long-term averaging. |
| 9 | `climate` | Selected atmospheric/land conditions on declared process supports. | Prescribed forcing interval, sample/average period and calendar. A transect is not planetary circulation. |
| 10 | `precipitation` | Rain/snow rates and totals with phase assumptions and support. | Event/season accumulation interval and rate-integration convention. |
| 11 | `plant_animal_ranges` | Selected species ranges, densities, stocks, residence and recruitment ledgers. | Seasonal occupancy/exposure versus census stock or recruitment period; avoid double counting moving stock. |
| 12 | `soils_ground_conditions` | Soil/material, water/heat and root properties at declared depth/spatial support. | Initial state, event/season interval and initial/final water/energy stores where applicable. |
| 13 | `erosion_sediment_transport` | Eroded, transported, deposited and exported material by support and origin where represented. | Physical interval and cumulative history; finite stores and interval rates must agree. |
| 14 | `seas_coastal_processes` | Selected coastal state, forcing, sediment and river-pulse exchanges. | Event/tidal/other selected interval and boundary phase; not an invented global ocean history. |
| 15 | `resources_land_suitability` | Declared opportunity/suitability fields and supported resource quantities. | Assessment date/scenario; any renewability, depletion or production period must be explicit. |
| 16 | `land_use_agriculture` | Land commitments, crop/irrigation and food-accounting products. | Crop calendar, season and timed allocations; do not spend the same stored water or food twice. |
| 17 | `infrastructure_connectivity` | Network/support, costs, connectivity, service capacities and allocations. | Network/scenario date; demand and capacity periods, closures and travel-time basis. |
| 18 | `natural_hazards` | Selected hazard cases or susceptibility outputs with regime/assumption labels. | Event/scenario duration; susceptibility is not a probability or return period without an explicit model. |

## 5. Time contract and actual native ceilings

**Required:** distinguish (a) world snapshot date, (b) forcing/averaging period,
(c) simulated physical duration, (d) numerical trial/accepted interval and
(e) computer wall time. Each temporal exchange names its calendar, start/end,
units and stock/flow convention. Unit conversion must use the selected model's
explicit year/second convention; no universal hidden year length is introduced.

There is **no selected project-wide geological duration, global timestep or rule
that all eighteen categories advance on the same clock**. For a static world
snapshot, declaring the state/forcing period is mandatory; evolving millions of
years is not automatically required. For a terrain-history claim, its starting
state, elapsed horizon, governing processes and acceptance criteria are mandatory.
Seasonal products require a selected season/calendar, not an assumed 365-day run.
Those production horizons remain **Open** pending the specific world/case
selection. Calendars and applicable physical parameters belong to the world profile;
Diadem or Earth conventions are not mandatory for unrelated worlds.

### Observed implementation limits (not production targets)

| Route and source | Bound | Consequence |
| --- | --- | --- |
| [Native common domain](../engineering/work/native_terrain_r1/domain.py), retained by R2 and R5 | **256 cells**, **2,048 connectors**, **8,192 total layers** | At most 16 × 16 for a square domain; physical size depends on declared spacing. Not a 64 × 64 or whole-frame backend. |
| [Native R2 validation](../engineering/work/native_terrain_r2/evolve.py), retained by [R5 session](../engineering/work/native_terrain_r5/session.py) | **256 accepted intervals including predecessor history** | Migration/branching does not reset the budget. It is not 256 years, and rejected trials still cost work. |
| [R4 interval proposal](../engineering/work/native_terrain_r4/scheduling.py), retained by [R5 runner](../engineering/work/native_terrain_r5/runner.py) | **5 years maximum requested interval** | Acceptance/error/topology checks may require smaller intervals or refusal. This is the proposal route's bound, not a general limit on every Atlas API. |
| [Retained R4 case runner](../engineering/work/native_terrain_r4/runner.py), used by R5 | **1,000 years target elapsed time** in this saved-case runner | A case target, not evidence of completion, a Diadem geological requirement or authorisation to execute it. |
| [Climate transect](../engineering/work/generator_upgrade_r4/climate.py) | **32 cells per transect** | Not a world-scale atmospheric grid. |
| [Snapshot graph contract](../engineering/work/generator_upgrade_r11/snapshot.py) | **128 stages**, **8 MiB encoded snapshot bound** | Stage/envelope limits, not terrain cell counts or a total dataset/storage allowance. |
| [Native R2 mass policy](../engineering/work/native_terrain_r2/numerics.py) | **2⁻⁶⁴ kg quantum**, **256-bit** mass/error counts | A representation/accounting rule, not measured physical accuracy or a requirement for every production solver. |

The effective domain limit is the tightest limit on the selected execution path,
not the largest constant found in any predecessor. No 4,096-cell universal ceiling
is asserted. Different Atlas components also use arrays and floating-point methods.
A branch/history-storage optimisation does not raise spatial limits, supply new
physics or guarantee a physical horizon. These are current implementation limits,
not permanent product requirements. Larger domains need an explicitly developed
and validated successor, not just edited constants. **None is changed here.**

## 6. Resource and service-level contract

**Open:** the public sources and available requirements do not establish an approved
production machine, end-to-end runtime target, RAM cap, disk budget or acceptable
recovery time. It would be false precision to choose a convenient laptop/server
specification or derive a full-world duration from the integer smoke graph.

**Required:** before a production-size run is scheduled, its profile must fill in:

| Field | Required decision/measurement |
| --- | --- |
| Target environment | OS, processor/core count, interpreter/dependency identities, usable RAM, scratch/storage medium and capacity; GPU only if explicitly selected. |
| Peak memory | Total resident-memory ceiling including parent, workers, native allocations, indexes, buffers, masks and publication. Worker estimates alone are insufficient. |
| Storage | Source + authority + outputs + scratch + caches + history + staging + required recovery copies + reserve, accounting for concurrent generations. |
| Time | Separate end-to-end cold-run and warm/incremental deadlines and termination policies; include verification, I/O, initialisation, compute and publication. No infinite allowance for an unspecified value. |
| Parallel work | Worker ceiling, admission estimates, coupling constraints and measured peak working set. A parallel flag is not a proof of memory safety or independence. |
| Continuation/recovery | Maximum tolerated lost work and restore duration, complete dependency inventory, integrity verification and an isolated restart drill where restart is claimed. |
| Workload | World geometry/frame/mask identity, active cells/objects, field/layer counts, requested and selected resolutions, simultaneous detail levels, selected categories, periods/intervals, footprints, output inventory and cache/streaming conditions. |

A profile with unresolved mandatory values is **NOT READY FOR PRODUCTION EXECUTION**;
it is not equivalent to zero, unlimited resources or permission to run. A separately
scoped component test may use its own explicit smaller profile. This is a review
and release policy, not a new enforcement mechanism in the existing runners.

**Observed defaults are not owner budgets:** Stage 6C has a **1,024 MiB prefetch
allowance** and 1,200-cell analysis blocks; its comment excludes other process
memory. Stage 6C5R uses **512 MiB per-site admission estimates** and explicitly says
these are not a process RAM cap. Their existence does not establish an Atlas-wide
1 GiB or 512 MiB working set. Sources:
[Stage 6C constants](../shared_generator/engine/build_stage6c_100m.py),
[Stage 6C5R constants](../shared_generator/engine/build_stage6c5r_physical_10m.py).

The 409.2-million-cell Diadem example makes dense per-cell Python object histories
unsuitable as an unexamined production assumption, especially as requested coverage
or resolution increases. It does not by itself prove which solver,
tile size or hardware will meet the budget. Bound working sets, expose I/O and
history costs, and measure the selected regional/production path when authorised.

## 7. What counts as meeting this contract

These are **Required review gates for a future delivery**, not claims that the
repository already enforces or passes them.

| Gate | Evidence required | Current contract-stage status |
| --- | --- | --- |
| Product coverage and independence | Named world/profile, release mode/tier, selected categories, deliverables, extent and unresolved areas. All-category claims account for all 18 keys. A generic-engine claim must not require undeclared Diadem constants or data. | Direction defined; no generalised engine or release demonstrated by this contract. |
| Input readiness | Exact obtainable sources, authority/mask/forcing decisions, compatible runtime and complete continuation dependencies. | Historical/private dependencies remain excluded from the public checkout. |
| Scale/time meaning | Evidence/assumption, process, exchange and output supports; requested/selected detail; unit/time conversion; interval/stock/flow consistency; no relabelling interpolation as physical detail. | Required; per-world resolutions, production supports and horizons not selected. |
| Numerical/physical acceptance | Fixed prior criteria; conservation and permitted error, cross-boundary behaviour, appropriate independent physical comparisons and uncertainty. | Existing safeguards retained; mountain/world physical acceptance unresolved. |
| Production integration | Explicit producer-to-spatial-output path, immutable input/consumer identities, and consistent release publication. | Recommendation 2; not implemented by this document. |
| Resource feasibility | Representative workload evidence meeting the agreed total RAM, disk and cold/incremental runtime budgets. | Budgets and regional workload not selected; no benchmark run. |
| Repeatability/recovery | Clean versus incremental agreement under the chosen numerical policy; no stale reuse; coherent interruption recovery and isolated restart when promised. | Existing tooling helps; production-path evidence not established here. |

An exact-result comparison is appropriate only where exactness is the declared
contract. A justified approximation requires predetermined tolerances and error
accounting. Neither “looks plausible” nor “matches the reference” alone is full
physical validation. No test-count threshold substitutes for these gates.

## 8. Open decisions and bounded next step

The following **Open** items are deliberately not guessed:

| ID | Decision needed | Blocking consequence |
| --- | --- | --- |
| D1 | Select the production terrain/hydrology producer and its interface to the retained spatial pipeline; distinguish integrating supplied authorities from generating new ones. | No complete generative production path can be claimed. |
| D2 | Select the first world profile (initially Diadem), active domain/mask generation and meaningful regional footprint, including external dependencies and detailed areas at the requested spacing. Keep eventual planetary geometry a separately designed capability. | Active cells, applicable geometry and actual workload remain unknown. |
| D3 | Select requested and budget-feasible base/detail resolutions, per-process/exchange supports and generation/refinement rules; assess 1 m where useful and feasible. | Current 100 m/10 m examples do not choose a universal grid or solver scale; planetary/mixed-resolution support is not automatic. |
| D4 | Select the snapshot/scenario date and any forcing, seasonal or physical-evolution horizons and initial/boundary states. | No whole-year/geological duration or universal timestep is authorised. |
| D5 | Set the target machine and finite total-memory, storage, time and recovery budgets with the owner. | No production-scale run is ready to schedule. |
| D6 | Select obtainable fixture/runtime/input packages and quantitative acceptance criteria for that production path. | Public component tests are not proof of full scientific-installation or world-generation readiness. |

These are inputs to the next recommendation, not six new implementation projects.
Recommendation 2 should return one proposed end-to-end producer/delivery design
and a filled candidate workload profile for review. Recommendation 3 would obtain
representative regional evidence only after its own scope and execution permission.
Do not pre-empt either by raising limits, repinning sources, installing missing
scientific components, running a simulation or synchronising the Windows workspace.

## 9. Review and evidence boundaries

For review, challenge the **world-agnostic product definition**, **eventual planetary
scope**, **budget-selected multiresolution design including 1 m or finer**, the
separation of core/world/run profiles, and the difference between current capability
and requirements. Check the Diadem example arithmetic, the smallest active native
limit, unresolved budgets/horizons and whether gates expose false world-scale claims. Review these decisions against source and actual needs rather
than seeking agreement between model names.

The JSON companion contains calculated counts and unresolved values as `null`;
it is a planning record, deliberately not consumable as a production recipe.
Its public paths reference code, not private authority locations or IDs.

**Evidence for revision 2:** the owner's scope/resolution correction, targeted
documentation-consistency and arithmetic checks, local link checks against the
retained path inventory, and exact patch-application checks. Unchanged source-defined
observations are retained from revision 1. Earlier coding-safety test results are
not presented as newly executed tests. See this revision's review packet/check log. No simulation, performance benchmark,
new public/historical execution binding, codec installation, live data read,
Windows integration, licence decision or physical/canon acceptance is part of
this change. Source links identify the reviewed definitions; test files linked
elsewhere may be inspection material rather than reproducible public run evidence.
