# Atlas: completion and development roadmap

**Date:** 26 September 2026  
**Planning baseline:** `remake`, commit `6285d4a`  
**Status:** WORKING NON-CANON. A development plan, not a claim of completed implementation or scientific acceptance.

## 1. What we are building

Atlas is a science-informed world generator. It should produce varied, coherent worlds in which tectonics, rocks, terrain, water, climate, ecology and human geography affect one another. It must do more than draw a plausible-looking map or connect individually passing components.

The immediate priorities are to repair the remaining tectonics realism and reliability problems, then complete and connect the other modules. Reuse sound existing work. Do not restart the project or rewrite every module merely because a newer implementation is possible.

### Product requirements

- **Atlas 1.0 produces a world at a selected epoch**, with compatible seasonal conditions where relevant. This does not require simulating every process from planetary formation to the present.
- Any claimed geological history must nevertheless be represented explicitly. A present-day motion field does not establish past crust formation or ocean ages.
- Different seeds must produce meaningful differences in the planet, not just different colours, names or rotations of the same template. The same seed and scientific inputs must reproduce the same result under the declared numerical contract.
- Keep a reusable engine, world profiles and execution/detail profiles separate. The Diadem is the principal development case, not a compulsory setting for all worlds.
- Keep Diadem and generic-world projects visibly distinct. Do not silently generate replacements for protected Diadem geography or treat synthetic worlds as canon. Canon-constrained generation can be developed later; current authority protections remain in force.
- Support regional, continental and eventual planetary coverage with suitable geometry and budget-selected resolution. Existing grid sizes are not permanent product targets. Finer output is not automatically finer physical accuracy.
- Provide usable speed/detail choices, provisionally **Preview, Balanced and Research**. Each must disclose its approximation and be checked against appropriate references. Do not achieve a faster tier merely by loosening acceptance tests.
- Ordinary world creation must not depend on multi-day research simulations. Keep expensive scientific reference cases separate from the consumer generation path.
- Provide New World, Save World, Load World and inspectable scientific layers. Reopening must restore the saved world, not silently generate another one.

The broader [product and scale contract](PRODUCT_AND_SCALE_CONTRACT.md) remains relevant. Its older capability descriptions and open decisions must be read alongside later implementation records, not treated as a complete current inventory.

## 2. How to use this plan

This document was requested so another implementer, including Claude, can continue from the repository. Its creation did not resume simulation or implement the fixes below. Start coding when the owner asks you to work from this plan, and respect any remaining explicit holds.

1. Read [AGENTS.md](../AGENTS.md), [CURRENT_STATE.md](CURRENT_STATE.md), and the affected route in [CODING_SAFETY.md](CODING_SAFETY.md). Check the actual checkout and its changes. A pushed snapshot and another agent's local work are not necessarily identical.
2. Choose the next bounded checkpoint below. Inspect its implementation, actual imports and existing evidence before writing replacements. Review any supplied patch against the current branch; a patch described as ready is not automatically applied or accepted.
3. Use published research and relevant existing software when selecting scientific methods. Explain what was adopted, adapted or rejected, why it fits, and its licence/dependency implications. Do not build an inferior substitute merely to keep everything home-grown.
4. Correct the model and its integration, optimise useful stable work, then run proportionate checks. Reuse valid evidence; do not repeat an expensive campaign for reassurance or because another agent produced it.
5. Make a small coherent change with a descriptive commit when committing is authorised. Preserve unrelated work and historical results. Keep failures visible and deliver code, focused checks, measured timings and the next unresolved point.

**No broad rewrite, source-check bypass, silent historical rebind, destructive cleanup or held R4.4 run is authorised by this document.** Missing private data or runtimes must be reported, not replaced with fabricated evidence. Do not require an acknowledgement after every routine step; ask only for a material unresolved choice, authority or resource commitment.

## 3. Starting position and evidence status

The repository contains implementations across all **18 modelling categories**. This is component coverage, not proof that all 18 are complete, scientifically accepted or connected into a production world generator. Native tectonics has substantial W01-W12 work and newer world-creation adapters; retain those investments.

Three generated-world realism problems have been identified:

- Plate boundaries inherit coarse support-cell zig-zags.
- Starting crust uses an overly restrictive three-province template, producing similarly sized, nearly round continents in the tested ocean-majority scenario.
- That scenario assigns one cooling age to its oceanic background, rather than a spatially varying, history-consistent age field.

The saved boundary correction is a **prototype**, not completed integration. The tracked [new_world_boundary.py](../tectonics/tools/new_world_boundary.py) contains coalescing and area-constrained spherical smoothing, but its existence alone does not establish that generation uses it or that it passes final acceptance.

The recent external review also reports stale evidence bindings, signed-zero/digest and bundle issues, an approaching source-inventory limit and public-path leakage. These are **reported findings to reconcile against the checkout**, not newly verified results of this roadmap. Old evidence may remain valid for its original source version while being unsuitable for a claim about current code.

## 4. Phase A — make the repository and its evidence dependable

Resolve blocking correctness and evidence issues before producing new acceptance claims. Keep this bounded; it is not a new global infrastructure project.

| Priority | Work | Completion condition |
| --- | --- | --- |
| A1 | Reconcile the previous review's v2 digest patch, W12 signed-zero rewrite issue and portable-bundle fixes. Obtain the actual patches/reproductions if absent; do not infer their details from their names. | Each applicable defect has a focused regression and a documented resolution. Original records and unrelated numerical behaviour remain preserved. |
| A2 | Distinguish current, historical, superseded and invalid evidence. Inspect the reported Step 2/3/4/5/7 binding problems and the reported large surface-output discrepancy. | A small explicit list identifies evidence used for current claims; a checker rejects stale bindings in that list. Historical evidence remains available and clearly labelled. Changed numerical outputs receive scientific review, not just new hashes. |
| A3 | Resolve the reported 128-Python-file execution-inventory ceiling before it blocks development. | Test the present count and limit. Make a deliberate bounded successor policy if needed, preserving complete source capture. Do not scatter modules into inappropriate folders to evade accounting. Package separation is an architectural option, not a prerequisite for this repair. |
| A4 | Remove personal filesystem paths from public deliverables and prevent recurrence. | Public outputs are sanitised without secrets or usernames. Redacted successor records are distinguished from originals; no silent rewriting of authenticated historical evidence or unnecessary Git-history rewrite. |
| A5 | Record and pin the tested environment. Separate read-only result viewing from exact scientific continuation requirements. | Reproducible dependency/install instructions and platform-specific evidence exist for claimed platforms. Pins do not pretend that identical version strings guarantee identical native binaries or portable restart. Integrity and compatibility refusals remain meaningful. |
| A6 | Simplify current-status reporting and improve change granularity. | One clear current summary points to source-bound evidence and historical detail. Small commits identify what changed and which evidence remains current. Do not rerun unaffected evidence automatically. |

A new, simple evidence format may be introduced for future records while the checker reads necessary historical formats. Do not mass-rewrite old records to make them match. Keep byte integrity, semantic/scientific identity and storage identity distinct.

## 5. Phase B — finish tectonics realism and the usable tectonics module

Order: establish comparable measurements; finish boundary correction; improve starting crust; connect an explicit ocean-age model; supply a declared elevation baseline; close the assembled workflow. Short independent documentation or fixture work can overlap, but dependent outputs must use the corrected geometry and source identities.

### B1. Establish one comparable realism assessment

Use the same method for the original generator, the candidate and the shipped PB2002 reference. Review the offered measurement-tool patch before writing another tool.

- Predeclare physical sampling lengths. Suggested comparison scales are 100, 250 and 400 km; retain any existing 500 km baseline as a separately identified series. Never compare different scales as though they were equivalent.
- Define boundary-chain traversal, junction exclusion, closed loops, short chains, resampling phase, weighting and reference coverage consistently. Do not double-count the two sides of a boundary.
- Report mean, median and distributions of bend angles, plus the existing reflex-turning diagnostic where its definition is applicable.
- Count raw normal-motion sign changes per 1,000 km separately from transitions between opening-dominated and shortening-dominated stretches. Declare any obliquity classification in advance and retain the continuous normal/shear components.
- Report shear-dominated length and the distribution of boundary/motion alignment. A classification change must not conceal a geometric defect.
- Use development seeds and a separate withheld set. Do not select attractive seeds or tune to the withheld results. Match reference plate selection and scale where comparisons depend on them.
- Retain independent geometry, conservation and kinematic checks. Earth similarity is a reference for an Earth-like profile, not an exact mandatory template for every possible planet.

Matching an explicitly imposed speed scale is a scaling check, not independent realism evidence. Roughly equal opening and shortening is also insufficient. Do not compare the prototype's mean bend with a reference median.

### B2. Finish the actual boundary correction

Continue the existing prototype unless focused evidence shows a better approach is needed. Its purpose is to remove sampling-grid artefacts from **native geometry**, not merely smooth lines in the renderer.

1. Review and clean the combined helper. Check budget/cancellation handling, source-drift guards, degenerate cases and analytical area derivatives.
2. Coalesce same-plate support cells without changing physical boundaries; retain multiple patches when large or complex plates cannot safely be represented by one chart. Verify equivalence with the slower validated construction where available.
3. Smooth shared spherical boundaries with declared length/displacement controls, fixed junctions, area constraints and final native geometry validation. Keep genuine ridge/transform structure distinguishable from random zig-zags; minimum bend angle is not the objective by itself.
4. Integrate with [new_world_layout.py](../tectonics/tools/new_world_layout.py), binding the helper and successor method to request/result identities. Recompute final plate areas and errors from the final geometry. Preserve the existing area gates and original support-resolution meaning.
5. Correct the morphology assessment's assumption that final patches are still original support cells. Preserve a truthful original-support assignment/rotation check instead of dropping it or manufacturing a pass.
6. **Recalculate the motion fit on the corrected boundaries.** Save and display the same geometry used in physics; downstream contacts, edge indices, caches and result identities must agree.
7. Check create/save/load and the affected regional/UI boundary once, alongside matched numerical and actual visual comparisons. Preserve original saved worlds; generate explicit successors.

Prototype timings and bend reductions are exploratory evidence, not accepted whole-generator speedups or completed realism validation. Weighted spherical partitions and smooth warps remain alternatives, not automatically more physical replacements.

### B3. Replace the fixed starting-crust template

Generate a declared family of continental and oceanic arrangements with variable province counts, unequal sizes, varied placement, elongated/lobed shapes and small fragments. Preserve requested area fractions, valid non-overlapping coverage and reproducibility without seed hunting.

Keep geological geometry independent of arbitrary sampling resolution. Do **not** turn that into a rule that geology can never affect plates or that tectonics can never change geology. Preserve independent seed streams where appropriate while tracking genuine physical dependencies.

Keep continental crust distinct from dry land. A continental margin can be submerged; a crust-type polygon is not automatically a coastline. Changes to the template must feed actual crust intersections, material columns and the motion model, not only presentation.

### B4. Give ocean ages a declared history

Keep the continental/geological precursor before the motion fit. Separate the subsequent ocean-age and thermal construction rather than moving all geology behind a calculation that already needs it.

Choose and document the supported history level before claiming ages:

| Level | Meaning | Use |
| --- | --- | --- |
| Prescribed steady spreading | Declared motion/boundary history over a finite duration, with ages traced along compatible spreading trajectories. | Candidate first increment. State its inherited-crust and validity limits; fixed present rotations alone do not prove a globally valid past network. |
| Staged history | A finite sequence of explicit stages with birth, migration, cessation, reassignment and any supported ridge jumps or asymmetry. | Extend using the existing W06 machinery where its geometry and assumptions apply. Do not assume a regional implementation already supplies a global history. |
| Evolving tectonic history | A globally coupled evolving plate network with creation, destruction and changes of topology. | Longer-term capability; not mandatory for every Atlas 1.0 run and not synonymous with a complete mantle-physics simulation. |

For the first supported model:

- Use the opening component and actual spreading paths. Nearest-present-ridge distance divided by a speed is only a restricted approximation, not a general history reconstruction.
- Define inherited ages for crust not created in the represented interval. Missing current ridges do not determine age. Do not disguise missing history by clipping everything to a maximum age.
- Track formation time, plate ownership and material accounts. Zero age belongs to actual newly formed crust; check ages increase appropriately along supported trajectories and survive save/load.
- Reuse cooling/thermal support laws through explicit interfaces. Age bands/provinces are one storage candidate, but their discretisation error, edge effects and column counts need a bounded assessment.
- Treat established spreading as a changed physical scenario, not merely a rename of an incipient event. Reconcile affected saved contracts and downstream assumptions explicitly.

### B5. Supply a tectonic elevation/bathymetry baseline

Provide an optional whole-world or declared-domain baseline derived from compatible crustal columns, thermal state and isostatic/support assumptions. Define the datum, sea-level or water-inventory rule, reference density/load and missing-data behaviour.

Reconcile thermal buoyancy, cooling subsidence and crustal support so the same contribution is not added twice. Connect to existing W03/W04/W06 outputs only within their supported geometry and physics.

This is **new connected capability**, not proof that the old tectonics solver was defective. It supplies large-scale support/elevation to terrain and seas/coasts; it is not finished mountain topography, erosion, drainage or a coastline inferred from crust type alone.

### B6. Close the standalone tectonics workflow

- Assemble corrected initial-world generation, supported regional evolution, inspection, caching and complete/partial save/load/recovery.
- Validate the affected scientific methods and interfaces numerically and inspect real generated data visually. A concept image is not evidence. Use the predeclared small case set and withheld morphology checks.
- Refresh affected current evidence once the relevant implementation is stable, while retaining failed and historical reports. Do not replay all W01-W12 campaigns simply because the new-world wrapper changed.
- Measure cold creation, changed-input recomputation, warm reuse, restore and end-to-end operation separately, including validation and I/O. Record actual seconds and percentage changes against matched work.
- Keep Windows and Linux claims separate until exercised. A Linux result does not close a Windows issue, or vice versa.
- Document what is calculated, prescribed, approximate and unsupported in plain English, with the equations/methods, sources and evidence available below the explanation.

Tectonics owns motion, deformation, plate/crust history and its physical exports. Other modules own their responses to those exports. Retain already mixed code when relocating it would risk source/checkpoint compatibility; defer expansion to the correct scientific module. In particular, unfinished W09 surface/deposition work belongs in the terrain/water/sediment/geology programme below, not a new tectonics expansion.

### Relevant starting references

These are starting points already raised in the design discussion, not a statement that every suggested method has been implemented or newly reviewed for this roadmap:

- [PB2002 reference data in this repository](../tectonics/reference_data/pb2002/): matched boundary and motion comparisons; inspect its source/licence/coverage notes.
- [Seton et al. (2020), oceanic age and spreading parameters](https://www.earthbyte.org/a-global-dataset-of-present-day-oceanic-crustal-age-and-seafloor-spreading-parameters/): history-aware age comparisons.
- [Cortial et al. (2019), Procedural Tectonic Planets](https://onlinelibrary.wiley.com/doi/abs/10.1111/cgf.13614): relevant procedural tectonic generation, not a substitute for validating Atlas's assumptions.
- [Taubin (1995), curve and surface smoothing](https://www.cs.jhu.edu/~misha/ReadingSeminar/Papers/Taubin95.pdf), [area-preserving geodesic curvature flow](https://www.aimsciences.org/article/doi/10.3934/dcdsb.2017148), and [CGAL constrained remeshing](https://doc.cgal.org/latest/PMP_Remeshing/group__PMP__local__remeshing__grp.html): geometric techniques to assess within shared-boundary, area and validity constraints, not tectonic dynamics.
- Existing [tectonics plan](../tectonics/docs/TECTONICS_PLAN.md), [how tectonics is made](../tectonics/docs/HOW_TECTONICS_IS_MADE.md), and W03-W09 method/acceptance records: reuse supported mechanisms and preserve their limitations.

## 6. Phase C — complete all other modelling categories

The table uses the repository's existing category numbering. It is a **target list**, not a fresh audit claiming the current implementations are absent or complete. For each row, first identify what already works and what is missing, disconnected, scientifically unsuitable or only supported on a bounded fixture. Repair or extend that route rather than duplicating it.

| # | Category | Required connected capability | Key evidence before completion |
| --- | --- | --- | --- |
| 1 | Plate tectonics | Phase B above: varied valid plates/crust, compatible motion and declared ages/history, physical exports and recoverable use. | Matched morphology/kinematics, physical accounts, actual visual inspection and workflow/recovery evidence. |
| 2 | Geology | Regional material domains, layered columns, lithology, structural inheritance and supported fault/magmatic/metamorphic or depositional effects; supply properties and uncertainty to terrain, soils and resources. | Column/volume/mass consistency, justified property laws, source-linked structural controls and conservative exchange of material between modules. |
| 3 | Topography and topology | Generate credible mountains, ridges, valleys, scarps/cliffs and plains from geological/tectonic setting and surface processes; provide multiscale elevation and valid surface/drainage connectivity. | Relief, slope, curvature and drainage metrics at declared scales plus visual sections/maps. Mountain summits must not become uniformly gentle merely because the method smooths everything. Compare with relevant reference terrain; conserve transferred quantities across resolutions. |
| 4 | Hydrology | Connected catchments, rivers, lakes, storage, runoff, infiltration and supported groundwater/snowmelt exchanges, with consistent outlets and seasonal discharge. | Closed water budgets including external exchanges; legitimate endorheic basins, lake spill/merge/split behaviour and routing rebuilt after terrain changes. Do not fill every real depression just to simplify routing. |
| 5 | Political borders | Complete district generation and explicit political assignment using declared cultural/institutional scenarios, accessibility and geographical constraints. | Coverage, adjacency, enclaves/islands and aggregation checks; distinguish physical districts from political decisions. Geography must not silently invent legitimacy or override authored borders. |
| 6 | Settlements | Move from candidates to actual selected settlement locations, sizes and supporting hinterlands, constrained by water, food, hazards, resources and access. | Locations are physically compatible; capacities and dependencies are accounted for; unsuitable or unsupported choices remain visible rather than forced. Relocate provisional locations when corrected terrain requires it, preserving provenance. |
| 7 | Populations | Place declared/generated totals spatially across settlements and rural areas with explicit density, support and seasonal-residence assumptions. | Settlement, district and world totals reconcile; finite capacity and unplaced balances remain explicit. Population totals alone are not a spatial distribution. |
| 8 | Biomes | Derive biome patterns from seasonal climate, water, soils, elevation and vegetation interactions, not just annual means or arbitrary noise. | Known limiting-condition controls, credible transitions and consistency with plant/habitat fields; record classification uncertainty and scale. |
| 9 | Climate | Supply geographically coherent seasonal temperature and atmospheric forcing under declared planetary parameters, land/ocean distribution and orography. | Energy/transport checks appropriate to the selected model, reference climate regimes and seasonality. A small transect is not sufficient evidence for global circulation or planet-scale coverage. |
| 10 | Precipitation | Connect moisture transport, rain/snow partition, orographic effects and seasonal totals to climate and hydrology on compatible supports. | Moisture accounting and rate-to-volume conversion, wet/dry seasonal controls, windward/leeward behaviour and consistent rain/snow inputs downstream. |
| 11 | Plant and animal ranges | Generate suitable, accessible and occupied ranges separately; connect growth, reproduction, dispersal, nutrients, density and seasonal residence to physical conditions and interactions. | Numerical biological inputs with sources/ranges, habitat/dispersal controls and non-double-counted moving populations. Obtain Diadem inputs through the species coordinator, not separate unsolicited requests to every species owner. |
| 12 | Soils and ground conditions | Complete coupled water, heat, freezing/thawing, root and material behaviour over seasons; connect geology, erosion/deposition, vegetation and cultivation. | Moisture evolves during temperature calculations instead of remaining fixed at the starting value; conserve water/energy through phase changes and material transfers; test meaningful seasonal feedbacks. |
| 13 | Erosion and sediment transport | Complete source-to-sink erosion, transport, storage, deposition and supported stratigraphy; link rivers, hillslopes and coasts to changing terrain and soil parent material. | Account for eroded, retained, deposited and exported material; respect finite layers/stocks; deformation/deposition changes drainage and soil rather than only a diagnostic image. Reuse applicable W09 work. |
| 14 | Seas and coastal processes | Connect sea level, bathymetry, shoreline, estuaries, river inputs and supported tidal/wave/current/sediment processes with inland water and coastal terrain. | Consistent wet/dry masks, river-mouth and coast boundaries, water/sediment accounts and coastal sensitivity cases. Do not label a bounded coastal solver as a complete global ocean model. |
| 15 | Resources and land suitability | Derive geologically/ecologically justified resource potential and purpose-specific suitability with limiting factors and uncertainty. | Keep occurrence, recoverable stock, access and productive capacity distinct; avoid opaque scores that conceal missing constraints or manufacture deposits. |
| 16 | Land use and agriculture | Generate actual cultivated areas, crop choices/calendars, irrigation and finite food/water accounts, coupled to soils, climate, settlements and access. | Seasonal crop and water constraints, finite irrigation supplies and area/production reconciliation. Suitability alone must not be presented as a realised farm or harvest. |
| 17 | Infrastructure and connectivity | Connect settlements, resources, production and ports using terrain-aware networks, crossings, travel costs, service capacities and seasonal availability. | Physical route feasibility, connectivity, demand/capacity accounting and closure effects. A line on a map is not transport capacity. Feed accessibility back into settlement/population/land-use choices. |
| 18 | Natural hazards | Connect the supported tectonic, slope, river and coastal hazards to actual exposure; add other hazard types only with explicit models and evidence. | Distinguish susceptibility, event scenarios, probabilities and return periods. Hazard fields must share the physical inputs used by their owning processes, not independently invent them. |

### Recommended implementation order and feedbacks

Work one coherent increment at a time, in the following dependency groups. This is not a claim that each group can be finished in isolation or that the graph is acyclic.

1. **Geology and physical-surface core — 2, 3, 13, 14.** Connect tectonic exports to geology and an initial surface/coast representation. Establish hydrology interfaces immediately. Complete source-to-sink material handling and drainage updates rather than building a final terrain that water cannot use.
2. **Seasonal climate, water and ground — 9, 10, 4, 12.** Couple atmospheric forcing, precipitation, snow/ice where applicable, soil heat/moisture, evapotranspiration, river/lake flow and coastal boundaries. Revisit the physical surface as these dependencies mature.
3. **Ecology — 8, 11.** Connect seasonal habitat, species inputs, dispersal and occupancy. Return vegetation/root effects to evaporation, infiltration, soil development and erosion.
4. **Hazards and usable potential — 18, 15.** Consolidate relevant physical-module outputs into hazard, resource and use-specific suitability products. Foundational hazard outputs may be developed earlier with their owning process.
5. **Cultivated and inhabited landscape — 16, 6, 7, 17.** Establish agricultural potential and provisional settlement/network candidates, then allocate cultivated land, population, water, food and capacity together. Resolve accessibility feedbacks; do not assume final farms must exist before any settlement candidate or vice versa.
6. **Political geography — 5.** Complete and assign districts using the physical and human layers plus explicit political assumptions. Feed relevant administrative/service constraints back without pretending borders are purely physical outcomes.

Use bounded iteration for terrain–water–soil–vegetation and settlement–land-use–network feedbacks. Declare exchange periods, convergence/stopping conditions and who owns each update. A failed convergence test must be reported, not hidden by accepting the last iteration.

The older six completion priorities remain covered here: coupled soil physics; changing-ground feedback; missing/disconnected regional geology, coastal, district and cultivation routes; numerical species inputs; compatible physical-to-population/transport joins; then a complete Diadem seasonal-year verification on the replacement terrain.

## 7. Shared engineering requirements across all 18 categories

Reuse and complete the existing shared machinery rather than building a separate scheduler, cache and file format for each module.

| Area | Required behaviour |
| --- | --- |
| Workflow and dependencies | Correct order, explicit feedback loops, preflight validation and dependency-aware invalidation. Only affected work should rerun; cached downstream results must not survive relevant upstream changes. |
| Source and version protection | Identify the actual producer, imported helpers, inputs, scientific settings and runtime. Keep current evidence separate from historical claims and preserve authenticated originals. |
| Data contracts and validation | Explicit units, frames, vertical datums, spherical/planar geometry, coverage, masks, calendars and time intervals. Transfer extensive quantities conservatively; use appropriate rules for intensive and categorical fields. |
| Storage and data handling | Bounded working sets, streaming/chunked access and lazy loading where useful. Reuse identical immutable data instead of repeatedly copying it. Use lossless compression, including existing Zstd routes where beneficial, without corrupting active controls or provenance. |
| Caching and verified reuse | Cache useful successful work as it is produced. Key all relevant scientific dependencies; validate source/input identity on reuse. Distinguish preparation reuse from identical-result caching. |
| Checkpoints and recovery | Save complete recoverable progress, support cancellation and continue without repeating paid work or transfers. Shared history stores are dependencies, not disposable temporary caches. |
| Execution and resources | Use parallelism where work is independent and expected savings exceed startup/communication costs. Estimate before starting; the previously discussed roughly two-minute trigger is a heuristic to evaluate, not a universal law or reason to wait until a full serial run has finished. Count aggregate worker/native memory. |
| Testing and measurement | Focus on changed behaviour and affected joins; broaden only for shared-system risk. Use deterministic controls, independent physical comparisons, withheld cases, scientific parity and meaningful visual checks where relevant. |

### Performance reporting

- Preserve quality first. Optimise useful work before calling an increment complete, but do not make exhaustive optimisation a prerequisite for every new capability.
- Prefer better algorithms, avoiding repeated computation/copying, reusable prepared operators, suitable data layouts and bounded I/O before adding more workers.
- Measure matched workloads: same coverage, resolution, physical duration, accuracy and requested outputs. Report setup, checks and output costs, not just a favourable kernel.
- Report raw baseline/candidate seconds and `100 × (baseline − candidate) / baseline`. Identify cold, warm, restored and changed-input measurements separately; include relevant hardware, worker counts and variability.
- Report regressions as regressions. Do not add percentages from unrelated stages or claim whole-world savings from tiny fixtures.
- Processing time is the priority over reducing RAM or disk alone, within safe budgets. Report RAM and stored bytes separately. Do not spend effort estimating token savings.
- Choose representative bounded scale cases before long runs. A toy case can exaggerate parallel overhead; that does not establish the correct whole-world policy.

## 8. UI and explainability

Keep the map primary, with progressively available scientific detail. Backend producers supply actual fields, valid masks, units, legends/ranges, dependencies and saved-time identity. The UI must not fabricate data to make an unfinished output look complete.

Maintain a separate frontend/backend integration boundary. Supply a versioned data contract and real small example to the UI owner; do not rewrite the frontend as part of a backend repair or claim integration until it is exercised. If the frontend is unavailable in the checkout, finish the backend contract and explicitly identify that dependency.

New/Save/Load must preserve the seed, settings, generated geometry, scientific outputs and supported continuation state. Show cached, stale, missing, failed and unsupported layers honestly. Previously saved results remain inspectable without silently launching generation or repinning their source history.

Each module needs a concise **How this is made** section explaining:

- what inputs it uses and what it calculates;
- the principal mechanisms, assumptions and scale limits;
- what feeds other modules and what feeds back;
- why the method was chosen, with papers/software actually consulted;
- how the outputs were checked, and what the evidence does not establish;
- the observed quality/runtime consequences of available detail modes.

Write for an interested, above-average reader, not only a numerical modeller. Place specialist derivations and raw reports behind links rather than repeating caveats everywhere.

## 9. Whole-generator acceptance and release order

1. **Small complete synthetic world:** exercise every applicable category and the real joins cheaply. Declare inapplicable categories explicitly, rather than inventing inhabitants or crops. Check multiple seeds without selecting only attractive outputs.
2. **Representative regional case:** demonstrate terrain, climate, water, soil, sediment and biological/human consumers with correct external boundaries. Inspect actual maps and sections and measure end-to-end cold/incremental/recovery behaviour.
3. **Replacement Diadem terrain and compatible inputs:** connect the agreed terrain, climate, soils, rivers/lakes, productive land, settlements, population and transport capacity. Treat superseded geography as temporary fixtures, not permanent authority. Route species inputs through their coordinator and expose missing numerical parameters.
4. **A complete seasonal year:** use the world's declared calendar and carry state between periods. Check storage, heat, water, material, biological residence and human supply accounts; restart part-way and verify the completed result. Do this for the whole Diadem only after replacement terrain and the relevant inputs are ready and the run budget is authorised.
5. **Production feasibility:** measure the selected consumer profiles on representative hardware and coverage. Confirm global seams/poles and cross-region exchanges where planetary coverage is claimed. Do not infer a planet-sized runtime from a small regional simulation alone.
6. **Release:** deliver the usable UI/API, reproducible project files, documented supported profiles, current scientific evidence, measured performance and honest unsupported cases. Optimise and measure the assembled path again where integration exposes new bottlenecks.

Full-year verification means the chosen coupled seasonal workflow, not forcing every geological solver to run monthly or requiring a civilisation-history simulation for a fixed-epoch product.

## 10. What counts as finishing a checkpoint

A checkpoint is complete when its requested capability is implemented in the real route, its affected inputs/outputs are connected, the necessary scientific and technical checks pass, useful performance work is measured, and documentation/evidence describe those actual bytes. A helper file, passing unit tests, a rendered picture or a handoff alone is not integration.

The completion summary should be short:

1. What changed and why.
2. Relevant papers/software consulted and the design choice made.
3. Exact focused checks and remaining platform/physical limits.
4. Measured time before/after, with the workload and any regressions.
5. Files/evidence, source-identity implications and the next unfinished checkpoint.

Do not perform repeated broad audits, coordinator acknowledgements or reviewer-of-reviewer passes. Preserve a concise handoff and stop when the authorised checkpoint and necessary continuations are genuinely complete.

**Default starting point for a later coding request:** reconcile Phase A's existing patches and blocking evidence/reliability findings, then B1 and B2. Continue from the saved boundary work; do not begin another W-package or an expensive world run to avoid closing these issues.
