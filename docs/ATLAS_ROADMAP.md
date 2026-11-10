# Atlas: completion and development roadmap

**Reconciled:** 3 November 2026<br>
**Original planning baseline:** 26 September 2026, `remake`, commit `6285d4a`<br>
**Status:** A development plan, not a claim of completed implementation or scientific acceptance.

## 1. What we are building

Atlas is a science-informed world generator. It should produce varied, coherent worlds in which tectonics, rocks, terrain, water, climate, ecology and human geography affect one another. It must do more than draw a plausible-looking map or connect individually passing components.

The immediate priorities are to repair the remaining tectonics realism and reliability problems, then complete and connect the other modules. Reuse sound existing work. Do not restart the project or rewrite every module merely because a newer implementation is possible.

### Product requirements

- **Atlas 1.0 produces a world at a selected epoch**, with compatible seasonal conditions where relevant. This does not require simulating every process from planetary formation to the present.
- Any claimed geological history must nevertheless be represented explicitly. A present-day motion field does not establish past crust formation or ocean ages.
- Different seeds must produce meaningful differences in the planet, not just different colours, names or rotations of the same template. The same seed and scientific inputs must reproduce the same result under the declared numerical contract.
- Keep a reusable engine, world profiles and execution/detail profiles separate. The Diadem is the principal development case, not a compulsory setting for all worlds.
- Keep Diadem and generic-world projects visibly distinct. Do not silently generate replacements for protected Diadem geography or treat synthetic worlds as approved Diadem inputs. Generation constrained by authored world facts can be developed later; current authority protections remain in force.
- Support regional, continental and eventual planetary coverage with suitable geometry and budget-selected resolution. Existing grid sizes are not permanent product targets. Finer output is not automatically finer physical accuracy.
- Provide usable speed/detail choices, provisionally **Preview, Balanced and Research**. Each must disclose its approximation and be checked against appropriate references. Do not achieve a faster tier merely by loosening acceptance tests.
- Ordinary world creation must not depend on multi-day research simulations. Keep expensive scientific reference cases separate from the consumer generation path.
- Provide New World, Save World, Load World and inspectable scientific layers. Reopening must restore the saved world, not silently generate another one.

The broader [product and scale contract](PRODUCT_AND_SCALE_CONTRACT.md) remains relevant. Its older capability descriptions and open decisions must be read alongside later implementation records, not treated as a complete current inventory.

## 2. How to use this plan

This document was requested so another implementer, including Claude, can continue from the repository. Its creation did not resume simulation or implement the fixes below. Start coding when the owner asks you to work from this plan, and respect any remaining explicit holds.

1. Read [AGENTS.md](../AGENTS.md), [CURRENT_STATE.md](CURRENT_STATE.md), and the affected route in [CODING_SAFETY.md](CODING_SAFETY.md). Check the actual checkout and its changes. A pushed snapshot and another agent's local work are not necessarily identical.
2. Choose the next bounded checkpoint below. Inspect its implementation, actual imports and existing evidence before writing replacements. Review any supplied patch against the current branch; a patch described as ready is not automatically applied or accepted.
   For a future module, use its [connected completion scope](MODULE_SCOPES.md) as part of the brief: identify initial-input producers, state ownership, consumers and feedbacks before choosing an isolated solver task. Resolve that slice's scientific decisions in the owning method document before building dependent code.
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

Delivery and outstanding review findings belong in [current state](CURRENT_STATE.md).
The [evidence guide](CURRENT_EVIDENCE.md) distinguishes current bindings from
historical results; a result can remain valid for its original source version
without supporting a claim about today's code.

## 4. Phase A — make the repository and its evidence dependable

The table defines Phase A's obligations. Consult [current state](CURRENT_STATE.md)
for their delivery and the [evidence guide](CURRENT_EVIDENCE.md) for the retained
repair results, publication digest trails and source-capacity consequences.
[Environment qualification](TECTONICS_ENVIRONMENT.md) owns platform and install
coverage. Resolve blocking correctness and evidence issues before producing new
acceptance claims; completed repairs do not require another campaign merely to
refresh this roadmap.

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

B1–B6 are retained outcome labels, not a second implementation or acceptance
queue. **I01–I12 is the single execution and acceptance sequence** in the
[complete integration plan](../tectonics/docs/INTEGRATION_PLAN.md) and
[programme roadmap](https://github.com/Atlantispy/atlas/issues/3). The requirements
below remain in scope through these owners; an old B label starts no separate
campaign or new current-run prerequisite.

| Outcome | Implementation and acceptance home |
| --- | --- |
| B1 matched realism | I11 owns the successor comparison and realism acceptance. |
| B2 causal boundaries | I04 owns the producer; I03–I09 supply connected state and feedback, I10 delivers it and I11 accepts it. |
| B3 varied starting crust | I04 owns the starting family, with I03/I05 geometry and material consumers. |
| B4 ocean-age history | I06 owns history/process, I05 carries formation/thermal memory and I03 supplies transfers. |
| B5 elevation/bathymetry | I08 owns support, datum, accounting and terrain/coastal ports. |
| B6 usable standalone tectonics | I10 owns lifecycle, I11 scientific/platform/resource acceptance and I12 delivery. |

Short independent documentation or fixture work can overlap. Dependent outputs
must use the selected geometry and source identities; consult CURRENT_STATE for
what has actually landed.

### B1. Establish one comparable realism assessment

The [boundary-diagnostic method](../tectonics/docs/NEW_WORLD_LAYOUT.md#matched-boundary-diagnostics-roadmap-b1)
owns the recorded original/prototype/reference comparison and its limitations.
Multi-seed successor checks, applicable outline/reflex gates and loop-phase
sensitivity remain acceptance work after B2. The retained prototype uses saved
original rotations; it does not qualify a successor motion fit.

Use the same method for the original generator, the candidate and the shipped PB2002 reference. Review the offered measurement-tool patch before writing another tool.

- Predeclare physical sampling lengths. The retained comparison uses 100, 250 and 500 km; the earlier suggested 400 km scale is not a recorded result. Any changed scale needs a separately identified series. Never compare different scales as though they were equivalent.
- Define boundary-chain traversal, junction exclusion, closed loops, short chains, resampling phase, weighting and reference coverage consistently. Do not double-count the two sides of a boundary.
- Report mean, median and distributions of bend angles, plus the existing reflex-turning diagnostic where its definition is applicable.
- Count raw normal-motion sign changes per 1,000 km separately from transitions between opening-dominated and shortening-dominated stretches. Declare any obliquity classification in advance and retain the continuous normal/shear components.
- Report shear-dominated length and the distribution of boundary/motion alignment. A classification change must not conceal a geometric defect.
- Use development seeds and a separate withheld set. Do not select attractive seeds or tune to the withheld results. Match reference plate selection and scale where comparisons depend on them.
- Retain independent geometry, conservation and kinematic checks. Earth similarity is a reference for an Earth-like profile, not an exact mandatory template for every possible planet.

Matching an explicitly imposed speed scale is a scaling check, not independent realism evidence. Roughly equal opening and shortening is also insufficient. Do not compare the prototype's mean bend with a reference median.

### B2. Finish the actual boundary correction

**Owner clarification, 26 September 2026:** fix why initial generation produces
unrealistic boundaries; post-generation fairing is not an acceptable realism fix,
even if downstream physics uses the adjusted geometry. The planned integration
below is paused before implementation. The retained prototype and B1 measurements
are diagnostic evidence only, not the chosen production method.

Next establish a scientifically justified generative formulation in which declared
geological and motion assumptions influence boundary creation itself. Compare
applicable research and existing software; distinguish causal mechanisms from
initial-condition priors and numerical mesh maintenance. Do not choose shapes to
match Earth statistics. Reference measurements test outcomes, not provide an
appearance objective. Declare computational costs before any large simulation.

**Diagnosis completed, producer repair still open:** the New World route saves
initial conditions rather than an evolved global tectonic state. Crust is not an
input to the plate-layout producer. A two-candidate control changed continental
coverage from 30% to 40% with exactly zero change to boundary coordinates or
ownership. The [causal-generation design](../tectonics/docs/NEW_WORLD_LAYOUT.md#causal-generation-diagnosis-and-replacement-design)
traces all three defects to their generating code and records research scope.

Replace the former fairing integration with this order:

1. Versioned evolving-world state, separating physical interfaces, material and birth histories from numerical sampling.
2. Bounded history producer with exact-motion controls and explicit opening, birth, consumption/export and inventory accounts. This supplies infrastructure, not physically emergent boundaries.
3. Scientifically specified causal boundary formation/evolution from forcing, material state and inherited weakness. A kinematic-only mode must not silently replace this requirement.
4. Coupled boundary, motion, crust, age and thermal evolution; unsupported topology changes refuse rather than receive cosmetic repairs.
5. New World integration, explicit successors and focused geometry/physics/save-load/matched-scale acceptance on the same generated state.

**Full integration scope now governs the sequence:**
[INTEGRATION_PLAN.md](../tectonics/docs/INTEGRATION_PLAN.md) maps W01–W12 and New
World into I01–I12, including missing physics, all required representation transfers,
feedback, lifecycle and end-to-end acceptance. Use that plan for the detailed stage
sequence and [CURRENT_STATE.md](CURRENT_STATE.md) for the active checkpoint and
authorised next action; the five points above are only a B2 summary, not a complete
integration plan. B3 and B4 share this evolution dependency with B2;
do not close them by painting independent shapes or ages.
Retain native validity, budget/cancellation and source-drift checks. Exact seam
removal can remain representation work, never evidence of physical generation.
Any changed geometry still requires new contacts/motion, correctly scoped
morphology tests, cache invalidation and saved/UI agreement. No full-world or
long convection run is authorised by this design.

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

The detailed [future-module scopes](MODULE_SCOPES.md) cover **all 17 non-tectonics categories**, their input/bootstrap producers, implementation slices, shared ownership, feedbacks, scientific decisions and connected acceptance cases. They are part of this roadmap, not an optional later integration pass. The common scope includes usable API/UI outputs, saved projects, recovery, appropriate optimisation and measured performance. It is planning, not a claim that the listed implementations have passed those requirements.

The category scopes are target requirements, not a fresh audit claiming current implementations are absent or complete. For each slice, identify what already works and what is missing, disconnected, scientifically unsuitable or supported only on a bounded fixture. Repair or extend that route rather than duplicating it. Tectonics is covered by Phase B above; the linked scopes own the other categories’ capabilities and completion evidence.

### Recommended implementation order and feedbacks

Work one coherent increment at a time, in the following dependency groups. This is not a claim that each group can be finished in isolation or that the graph is acyclic.

1. **Geology and physical-surface core — 2, 3, 13, 14.** Connect tectonic exports to geology and an initial surface/coast representation. Establish hydrology interfaces immediately. Complete source-to-sink material handling and drainage updates rather than building a final terrain that water cannot use.
2. **Seasonal climate, water and ground — 9, 10, 4, 12.** Couple atmospheric forcing, precipitation, snow/ice where applicable, soil heat/moisture, evapotranspiration, river/lake flow and coastal boundaries. Revisit the physical surface as these dependencies mature.
3. **Ecology — 8, 11.** Connect seasonal habitat, species inputs, dispersal and occupancy. Return vegetation/root effects to evaporation, infiltration, soil development and erosion.
4. **Hazards and usable potential — 18, 15.** Consolidate relevant physical-module outputs into hazard, resource and use-specific suitability products. Foundational hazard outputs may be developed earlier with their owning process.
5. **Cultivated and inhabited landscape — 16, 6, 7, 17.** Establish agricultural potential and provisional settlement/network candidates, then allocate cultivated land, population, water, food and capacity together. Resolve accessibility feedbacks; do not assume final farms must exist before any settlement candidate or vice versa.
6. **Political geography — 5.** Complete and assign districts using the physical and human layers plus explicit political assumptions. Feed relevant administrative/service constraints back without pretending borders are purely physical outcomes.

Use bounded iteration for terrain–water–soil–vegetation and settlement–land-use–network feedbacks. Declare exchange periods, convergence/stopping conditions and who owns each update. A failed convergence test must be reported, not hidden by accepting the last iteration.

Use the [bootstrap and ownership contracts](MODULE_SCOPES.md#bootstrap-feedback-and-implementation-order) to break circular prerequisites explicitly. Develop the common small mountain-to-coast case as the groups connect; do not wait until every standalone module is written before trying them together. Temporary forcing/candidate drivers must name their replacement producer and cannot silently become a claim of complete generation. Geological construction and seasonal updates use their appropriate clocks; a selected-epoch world does not require every process to rerun monthly.

The older six completion priorities remain covered here: coupled soil physics; changing-ground feedback; missing/disconnected regional geology, coastal, district and cultivation routes; numerical species inputs; compatible physical-to-population/transport joins; then a complete Diadem seasonal-year verification on the replacement terrain.

## 7. Shared engineering requirements across all 18 categories

Reuse and complete the existing shared machinery rather than building a separate scheduler, cache and file format for each module.

| Area | Required behaviour |
| --- | --- |
| Workflow and dependencies | Correct order, explicit feedback loops, preflight validation and dependency-aware invalidation. Only affected work should rerun; cached downstream results must not survive relevant upstream changes. |
| Source and version protection | Identify the actual producer, imported helpers, inputs, scientific settings and runtime. Keep current evidence separate from historical claims and preserve authenticated originals. |
| Data contracts and validation | Explicit units, frames, vertical datums, spherical/planar geometry, coverage, masks, calendars and time intervals. Transfer extensive quantities conservatively; use appropriate rules for intensive and categorical fields. |
| Machine-readable contracts and documentation | After the optimisation programme is complete, migrate executable or report-generation inputs from prose into appropriate versioned code or data contracts as each affected consumer is next changed; keep the scientific explanation in documentation. Trace each actual reader first; migrate consumers and relevant checks together, preserving scientific meaning, fail-closed identity, prior evidence and recovery compatibility. Ordinary source comments that merely link to guidance are navigation, not a runtime dependency. This is not a prerequisite for current optimisation delivery or runs. |
| Storage and data handling | Bounded working sets, streaming/chunked access and lazy loading where useful. Reuse identical immutable data instead of repeatedly copying it. Use lossless compression, including existing Zstd routes where beneficial, without corrupting active controls or provenance. |
| Caching and verified reuse | Cache useful successful work as it is produced. Key all relevant scientific dependencies; validate source/input identity on reuse. Distinguish preparation reuse from identical-result caching. |
| Checkpoints and recovery | Save complete recoverable progress, support cancellation and continue without repeating paid work or transfers. Shared history stores are dependencies, not disposable temporary caches. |
| Execution and resources | Use parallelism where work is independent and expected savings exceed startup/communication costs. Estimate before starting; the previously discussed roughly two-minute trigger is a heuristic to evaluate, not a universal law or reason to wait until a full serial run has finished. Count aggregate worker/native memory. |
| Testing and measurement | Focus on changed behaviour and affected joins; broaden only for shared-system risk. Use deterministic controls, independent physical comparisons, withheld cases, scientific parity and meaningful visual checks where relevant. |

### Delivery order with the I modules

The minimum shared foundation comes before substantial implementation of the next
I-module slice; the remaining shared engineering develops alongside the modules:

1. Complete the current successful IV1 and old/new comparison under its existing
   delivery, admission and scientific controls.
2. In the first implementation slice of the next new or resumed I-module
   assignment, establish or reuse the authoritative package, versioned selected-route
   configuration, real producer-to-consumer fixture and repeatable build/install/check
   route. The module owner connects this foundation before expanding the module.
3. Deliver that module through the shared route immediately. Each following I-module
   and Phase C slice reuses and extends the same machinery as its actual consumers
   require; retire replaced paths as their consumers migrate.

Completing every shared-engineering proposal or migrating every legacy route is
not a prerequisite for starting the next module. Shared engineering is part of
module delivery from its first slice, rather than a separate project after the I
modules. Independent bounded tooling and fixture maintenance keeps its own scope;
this sequence adds no current-IV1 prerequisite and changes no hold or run authority.
The [programme roadmap](https://github.com/Atlantispy/atlas/issues/3) and
[shared-engineering issue](https://github.com/Atlantispy/atlas/issues/38) retain the
existing workflow and ownership boundaries.

### Assessed code consolidation

**Assessment complete; implementation not started.** Static review of source snapshot
`f9e3efde6f12ef199b322e804c63cc5925797aab` identified the bounded work below.
Syntax/duplicate screening and selected consumer inspection do not establish
whole-repository equivalence, runtime compatibility or scientific acceptance.
The mutation candidate pool is **248 Python files / 8,944,114 checkout logical
bytes**; only two recipe reconstructions were checked, each reproducing its stored
source text exactly. These counts are neither deletion clearance nor measured
savings. Implementation requires the relevant owner's authority and an explicit
source successor where identities change.

- **CODE-C01 — first: share source construction and guarded publication.**
  [Combined](../tectonics/optimisation/workbench/combined-runtime-r1/build_selection.py)
  and [Plan39](../tectonics/optimisation/workbench/plan39/build_selection.py) repeat
  the same construction skeleton; [Plan18](../tectonics/optimisation/workbench/plan18/build_selection.py),
  [Plan21](../tectonics/optimisation/workbench/plan21/build_selection.py) and
  [heat receiving](../tectonics/optimisation/workbench/plan40/heat/integration-r2/build_selection.py)
  repeat staged publication with differing path safeguards.
  Use one source-only module under `tools`, thin versioned route descriptors,
  pure overlay composition and one guarded publication boundary. Begin with
  successor Combined/Plan39 constructors; migrate Plan21 and Plan30/S1A pins and
  source-tool bindings before retiring predecessors. Preserve ordering-sensitive
  identity encodings, public/private base provenance, authority flags and
  [Plan22's D10 selection](../tectonics/optimisation/workbench/plan22/build_selection.py).
  Parameterise the existing constructor controls; retain route schemas, pin
  refusals, reserved/case-aliased paths, junction/symlink rejection, destination
  races, validated-byte snapshots and failed-write cleanup. Compare complete
  output membership, bytes and provenance; revalidate final publication paths.

- **CODE-C02 — independently, one fully reconstructed mutation family at a time.**
  Existing [S1 recipes](../tectonics/optimisation/pending/storage/refute/s1/make_mutants.py)
  and [S2 recipes](../tectonics/optimisation/pending/storage/refute/s2/delta-r8/make_my_mutants.py)
  can generate disposable variants instead of retaining every generated copy.
  Retain necessary selected baselines, pinned recipes, shared tests and minimal
  useful results at their existing owners. Before any deletion, reconstruct the
  complete family exactly and migrate its actual source-map and qualification
  consumers.
  Check complete variant coverage, exact outputs, seam-count refusals, clean
  control success and intended fault detection with honest exit/failure reporting;
  setup/import failures do not prove fault detection. The two checked samples,
  S1 `m01_drop_closed` and S2 r8 `b1_block_1p5_mib`, do not qualify the whole pool.

- **CODE-C03 — later, with C04: an explicit generator execution successor.**
  [R29](../engineering/work/generator_upgrade_r29/registry.py),
  [R30](../engineering/work/generator_upgrade_r30/registry.py) and
  [R31](../engineering/work/generator_upgrade_r31/registry.py) repeat registration,
  worker, signature and error-preservation plumbing. Replace the selected R31
  cloning/decorating route with an execution shell taking explicit registration,
  owner, provenance and receipt policies; keep spawn entry points explicit.
  Preserve the six-overridden/26-retained registration split, unaffected
  producer/cache identities, R30 prepared-context closure, receipt schemas,
  primary/cleanup errors and checkpoint behaviour.
  Qualify registry behaviour, serial/spawn identity, cold/warm reuse, drift
  refusals, combined failures and stop/resume through authorised isolated fixtures.

- **CODE-C04 — share capture mechanics within that same successor boundary.**
  [R26 provenance](../engineering/work/generator_upgrade_r26/provenance.py) through
  [R31 provenance](../engineering/work/generator_upgrade_r31/provenance.py) repeat
  inventory, checked-byte hashing, stability and loaded-byte verification while
  already sharing the [R24 reader](../engineering/work/generator_upgrade_r24/verification.py).
  Put a small helper beside that machinery and bind its executed bytes explicitly.
  Keep package prefixes, aliases, extra modules, R29 local capture, R30 retained
  R29 capture and R31 nested `retained_r30` identity as caller policies. Check
  added/deleted files, mutation during capture, loaded-byte mismatch, aliases,
  retained-module drift, exact identity shape and unaffected producer keys.
  Sharing does not remove checks or introduce a persistent mtime/digest cache.

- **CODE-C05 — a small independent test-maintenance change.**
  [Mechanics tests](../tectonics/tests/test_evolving_mechanics.py) and
  [W07 workflow tests](../tectonics/tests/test_w07_workflow.py) duplicate four
  factorisation failure injectors and `Abort`. Share only these instance-level
  injectors in a test-only `regional_failure_fixtures` module. Keep consumer tokens
  and distinct mechanics disposal/resource-recovery versus workflow checkpoint,
  publication and reload assertions. Run both affected classes with all four
  failure modes; do not patch protected module code or collapse recovery scenarios.

- **CODE-C06 — when an affected executor next changes.**
  [R12](../engineering/work/generator_runtime_r12/executor.py) and
  [R24](../engineering/work/generator_upgrade_r24/executor.py) have identical
  25-line `_frontiers` functions. Share only the pure graph-wave calculation,
  with explicit source capture. Check deterministic waves, repeated-parent
  deduplication, completed prefixes, impossible-frontier refusal and serial/wave
  parity. Preserve R24 streaming/out-of-order acceptance/contiguous recovery and
  R12 wave execution as distinct contracts; retain the existing recovery checks.

- **CODE-C07 — when affected native modules next change.**
  [Driving](../tectonics/src/atlas_tectonics/integration_driving.py),
  [ledger](../tectonics/src/atlas_tectonics/integration_ledger.py),
  [ports](../tectonics/src/atlas_tectonics/integration_ports.py) and
  [sphere](../tectonics/src/atlas_tectonics/integration_sphere.py) repeat an immutable
  array-copy primitive with different dtype defaults. Share an explicit typed
  helper beside `_validation`; its float64-only `frozen` is not a substitute.
  Preserve caller validation and bool/int/uint8 types. Check dtype, shape, C-order
  bytes including signed zero, detachment from inputs, write-enable refusal and
  supported empty arrays, plus affected I02–I04 and source-identity controls.

Do not flatten revision folders or merge complete executors, solvers or transport
implementations from textual similarity. Frozen payloads remain until actual
consumers migrate; Plan21 r4 is not interchangeable with Plan22's frozen legacy
Plan21 selection. The unresolved Plan04 width and L frozen-constructor selections
remain protected. This work does not access current runs/stores or historical
archives, change holds, add an IV1 prerequisite or enable a production default.
C06/C07's modest consolidation belongs with relevant authorised changes, not a
separate requalification campaign. No general utility framework or measured
time/RAM/storage saving is proposed.

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

**Retained early Windows delivery requirement:** the bounded development build
has its own [obtained qualification](../desktop/README.md#obtained-windows-qualification).
The requirements below govern affected rebuilds; they are not an unfulfilled
request to package that same baseline again. Package the interface and backend
as a double-clickable `.exe`, without requiring terminal commands.
Coordinate frontend changes with the UI owner. Include the required runtime and
assets (or a clearly documented installer), use writable per-user locations for
projects/cache, preserve New/Save/Load and read-only inspection, and shut down
owned backend processes cleanly. Verify launch on Windows without the development
environment, one small real project save/reopen, and cancellation/close behaviour.
This is a usable development build, not completion of I02–I12 or the later modules.

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

A checkpoint is complete when its requested capability is implemented in the real route, its affected inputs/outputs are connected, the necessary scientific and technical checks pass, applicable performance changes are measured, and documentation/evidence describe those actual bytes. A helper file, passing unit tests, a rendered picture or a handoff alone is not integration.

A finished increment is not automatically a finished module. Future-module completion also requires the common responsibilities and category-specific connections in [MODULE_SCOPES.md](MODULE_SCOPES.md), including the producers for required inputs. Mark unresolved or unsupported coverage explicitly; do not move missing essential connections into a new completion programme after declaring the module done.

The completion summary should be short:

1. What changed and why.
2. Relevant papers/software consulted and the design choice made.
3. Exact focused checks and remaining platform/physical limits.
4. Measured time before/after, workload and regressions when performance changed or is claimed; otherwise mark it not applicable.
5. Files/evidence, source-identity implications and the next unfinished checkpoint.

Do not perform repeated broad audits, coordinator acknowledgements or reviewer-of-reviewer passes. Preserve a concise handoff and stop when the authorised checkpoint and necessary continuations are genuinely complete.

**Starting point for a later coding request:** follow [CURRENT_STATE.md](CURRENT_STATE.md) and the active [tectonics integration plan](../tectonics/docs/INTEGRATION_PLAN.md). Earlier Phase A/B findings remain context, not an instruction to restart completed repairs. Once future-module implementation is authorised, take the next connected increment above using its detailed scope; the roadmap's existence does not resume held simulations or start another module.
