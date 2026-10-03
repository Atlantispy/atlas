# How Atlas tectonics is made

This is the reader's guide to the implemented tectonics machinery: what each
process does, what it consumes and produces, which research supports it, and how
we check the result. It assumes curiosity, not specialist geophysics training.
Status: **WORKING NON-CANON**. For delivery and next work, use
[current status](../../docs/CURRENT_STATE.md); this guide explains methods rather
than keeping another progress diary.

For the remaining implementation sequence and its definition of completion, see
the [complete tectonics integration plan](INTEGRATION_PLAN.md). The existing W12
column assembly and exports are not the full evolved-world generator.

**Whole-planet evolution is a required destination, not an optional extension.**
The intended engine advances the entire sphere's plates, material and history,
with more detailed calculations in active regions. Those regions must return
their forces and transfers to the global calculation at a shared accepted time.
It is not necessary to calculate every quiet part of a planet at fault-scale
resolution. Nor do a global starting map and several isolated regional tests
count as an evolved planet. The integration plan assigns this connection to
I03/I04/I07/I09 and its whole-world acceptance to I11, including measured time,
memory and storage. The new three-dimensional regional solver is a component of
that route, not completion of the whole-planet requirement.

## Follow a world through the generator

Read down this table in execution order. It follows the existing New World and
regional-continuation route, with the new force-driven connections identified
where they belong. Not every supported regional case uses every physical process.

| Order | What happens | Continue reading |
| --- | --- | --- |
| 1. Define the request | Choose the seed, world settings, extent and explicit assumptions. The seed makes the starting request reproducible; it is not geological history. | [Request and settings](how-it-works/04-new-worlds.md#1-make-a-reproducible-request) |
| 2. Build the starting geometry | Construct connected plate regions and shared boundaries in a declared spatial frame. | [Plate layout](how-it-works/04-new-worlds.md#2-choose-plate-sizes-and-construct-connected-regions), [frames and geometry](how-it-works/01-foundations.md#w01-describe-space-geology-and-prescribed-motion), [one shared spherical network (I03)](how-it-works/06-physical-integration.md#the-shared-spherical-network-one-owner-for-every-point-of-the-sphere) |
| 3. Populate the starting material | Supply crust, layers, inherited structure and initial temperatures, keeping their origin and unknown history visible. | [Crust and materials](how-it-works/04-new-worlds.md#3-supply-crust-materials-and-inherited-structure), [initial temperature](how-it-works/04-new-worlds.md#4-assign-initial-temperature-without-inventing-thermal-history) |
| 4. Establish motion and interpret boundaries | The existing route fits starting motion to the supplied crust and junction constraints. The I01 force-driven controls instead calculate motion from driving forces and resistance; they are not yet a replacement wired into New World. | [Initial motion](how-it-works/04-new-worlds.md#5-fit-initial-plate-motions-to-the-crust-and-junctions), [boundary interpretation](how-it-works/04-new-worlds.md#6-interpret-complete-boundaries-not-just-two-plate-arrows), [force-driven connections](how-it-works/06-physical-integration.md) |
| 5. Prepare a compatible regional case | Sample the actual starting material into the chosen cells/columns and retain complete normal and sideways motion, units and inventories. | [Regional admission](how-it-works/04-new-worlds.md#7-admit-a-regional-experiment-from-the-saved-world), [sampling](how-it-works/01-foundations.md#sampling-points-and-finite-cells) |
| 6. Advance the selected physical processes | Calculate supported deformation, material movement and thermal response. Where coupled, strength changes motion, motion changes heat/history/geometry, and those changes feed back into strength during subsequent integration stages. | [Existing regional evolution](how-it-works/04-new-worlds.md#8-calculate-deformation-and-its-vertical-response), [physical methods](how-it-works/02-tectonic-processes.md), [I01 feedbacks](how-it-works/06-physical-integration.md) |
| 7. Calculate support and accept the new state | Translate compatible material/thermal changes into loads and vertical response. Check force, material and heat accounts and supported transition conditions before accepting an interval. Return to the calculation with the updated state; this is a loop, not a one-off stack of maps. | [Heat and support methods](how-it-works/01-foundations.md), [coupled loads and transition controls](how-it-works/06-physical-integration.md), [separation diagnostic specification](I01_SEPARATION_DECISION.md), [one accepted clock and atomic commit (I02 joined route)](how-it-works/06-physical-integration.md#8-accept-save-and-continue-one-evolving-state), [moving the shared network and carrying its rock (I03)](how-it-works/06-physical-integration.md#move-the-plates-of-the-shared-network-and-carry-their-rock), [handing a region to a regional model and back (I03)](how-it-works/06-physical-integration.md#hand-part-of-the-network-to-a-regional-model-and-take-it-back), [supplied plate splits, merges and ridge jumps (I03)](how-it-works/06-physical-integration.md#change-which-plate-owns-which-cells-supplied-splits-merges-and-ridge-jumps) |
| 8. Save, inspect and hand off | Save accepted outputs and their identities, resume only compatible work, inspect maps/numerical fields and provide typed products to downstream modules. | [Save and resume](how-it-works/04-new-worlds.md#9-save-the-world-and-resume-only-compatible-work), [inspect a generated world](how-it-works/04-new-worlds.md#10-assess-an-actual-generated-world), [workflow and delivery](how-it-works/03-coupling-and-reliability.md), [save, reopen and continue the first joined route](how-it-works/06-physical-integration.md#8-accept-save-and-continue-one-evolving-state) |

Validation and safe reuse accompany the relevant step; they are not postponed
until the final map. Support can also feed back within a coupled solve, rather
than being calculated only after motion. The links distinguish existing runnable
connections from I01's bounded controls and the remaining integration work.

## Detailed chapters in that reading order

The W-numbers identify work packages. They are useful references, but they are
not twelve commands that every world must run in order. Each package contains
several methods, and a supported scenario selects compatible ones. The chapters
below explain those methods individually, with links to code, tests, evidence
records, papers and relevant existing software.

| Chapter | What it explains |
| --- | --- |
| [1. Start-to-finish overview: from a seed to a saved world](how-it-works/04-new-worlds.md) | Reproducible settings; candidate plates, initial crust and temperatures; crust-conditioned motion and junctions; regional evolution; project/bundle save/load; numerical and visual realism assessment. |
| [2. Foundations: W01–W04](how-it-works/01-foundations.md) | Frames and time; plate geometry and boundaries; geological descriptions and sampling; full-vector forcing; material transport, remapping and moving grids; cooling, compaction, physical loads and elastic support. |
| [3. Physical processes: W05–W08](how-it-works/02-tectonic-processes.md) | Extension; crust birth and spreading histories; regional flow and material laws; surface/thermal feedback; shortening, sliding and underthrusting; subduction; finite magma and supported regime joins. |
| [4. Connecting the physical processes: I01](how-it-works/06-physical-integration.md) | Strength, localisation and evolving history; retained elastic memory; motion/heat feedback and finite deformation; three-dimensional regional flow, conservative material/heat carriage and force feedback; lateral heat and basal accounts; gravitational driving and water loading; melt composition/delivery and transition safeguards; the I02 joined route's accepted clock, atomic state-and-exchange commits, save/continue and inspection; I03: one closed spherical network beside that history, moved by supplied rotations with conservative transfer of its rock, bridged to regional models and changed by supplied plate splits, merges and ridge jumps. |
| [5. Coupling, delivery and reliability: W09–W12](how-it-works/03-coupling-and-reliability.md) | Retained water/erosion interfaces; validation at different levels; measured optimisation, caching, storage and parallelism; actual workflow assembly, exports, jobs and recovery. |
| [Appendix: the separate force-driven experiment](how-it-works/05-experimental-dynamics.md) | Local material laws and strain memory; physical-length regularisation; buoyancy-driven flow; coupled heat/composition; the unfinished mature-convection challenge. This is a separate route, not another mandatory stage. |

Each chapter is a current explanation, not a separate historical version. The
specialist method documents remain the place for full equations, exact contracts
and detailed recorded experiments.

The I-numbers belong to the later integration programme, not a renaming of the
W-packages. The I01 chapter explains the bounded connections built to test its physical
choices. It distinguishes those implemented controls from the remaining work to
assemble an evolving world; it does not replace the separate experimental appendix.
File names are stable link identifiers, not instructions about execution order.

## The complete W-package map

| Package | Question it answers | Main product or responsibility |
| --- | --- | --- |
| W00: define the case | What physical question, assumptions and acceptance criteria are being tested? | A declared case and evidence policy; a planning responsibility, not another numerical solver. |
| W01: geometry and initial conditions | Where are the plates, rocks and temperatures, and what motion is supplied? | Identified frames, regions, shared boundaries, sampled inventories and compatible forcing. |
| W02: material history | Where does each amount of material go when rock or the grid moves? | Conserved cohorts, transfers, boundary/event accounts and recoverable history. |
| W03: thermal state and compaction | How do cooling and pore closure affect columns and their loads? | Temperatures, heat, porosity, thickness and reference-relative load changes. |
| W04: support and bending | How does the lithosphere respond to those physical loads? | Supported displacement, slope and curvature under explicit edge/rigidity assumptions. |
| W05: regional extension | What does a specified stretching/fault history do to a region? | Deformed/thinned material and a supported dry regional response. |
| W06: spreading and histories | When and where is oceanic material made, cooled, moved and removed? | Finite birth/exit accounts, age-resolved cooling and supported staged histories. |
| W07: regional mechanics | What slow flow and stress follow from a specified regional problem? | Velocity, pressure, strain/stress and supported surface/thermal evolution. |
| W08: additional regimes | How do supported shortening, sliding, underthrusting, slab/wedge and magmatic scenarios behave? | Regime-specific deformation and material/heat accounts, with explicitly supported joins. |
| W09: downstream interfaces | How can water and surface-process components consume the geometry and material? | Retained routing, finite-water and erosion components; not completed global feedback. |
| W10: scientific challenge | Are the equations implemented correctly, resolved sufficiently and physically appropriate? | Scoped independent comparisons, findings and uncertainty, not a universal realism badge. |
| W11: efficient execution | Can the same accepted calculation avoid unnecessary work? | Measured preparation/reuse, bounded execution and storage improvements. |
| W12: assembly and delivery | Can supported components be used, saved, inspected and resumed together? | A concrete column workflow, graph connection and typed output/recovery interfaces. |

The table maps responsibility, not twelve equally complete capability claims.
Each chapter states its actual supported connections and remaining limits.

## How the pieces connect

Atlas combines several representations, rather than treating a globe, a vertical
column and a regional cross-section as the same grid. A connection must preserve
units, time, reference frame, physical support and the amount of material.

```text
Supplied geology or seeded starting world
                 |
       geometry + sampling + motion
                 |
        admitted regional scenario
        /            |             \
 prescribed      force-balance     column thermal /
 deformation     calculation      compaction route
        \            |             /
      compatible material / heat / support outputs
                 |
     typed handoff to geology, terrain, water, etc.

Identity, caching, resource controls, saving and inspection span the routes.
```

This diagram shows available kinds of calculation, not automatic interchange
between every branch. For example, W12's runnable column case joins W01 sampling,
W03 thermal/compaction work and W04 support. The generated regional-world route
instead uses sampled real starting material, W08 affine deformation and a
specifically declared dry local support law. It does not silently acquire W07
stress localisation or a whole-planet history because those methods also exist.

Motion can be **prescribed**, **seeded and reconciled**, or **calculated from
forces**. These are different scientific claims. Drawing a geometrically valid
plate map does not prove that simulated mantle forces created it.

## What the evidence can tell us

The chapters connect each method to concrete checks. Four questions must stay
separate:

| Level | Example question | Useful evidence |
| --- | --- | --- |
| V1: implementation | Does a rigid rotation preserve distances? Does a material transfer conserve its inventory? | Analytical answers, independent formulations and invalid-input controls. |
| V2: numerical resolution | Does the answer stabilise when cells or timesteps become smaller? | Separate space/time/solver studies of the actual output quantities. |
| V3: physical adequacy | Does the model reproduce independent geological or laboratory observations for its intended setting? | Appropriate observations, uncertainty, calibration separation and physical comparisons. |
| V4: supported assembly | Do compatible inputs survive the connected workflow, save/load and interruption? | End-to-end cases, direct-call comparisons, fresh-process recovery and refusal tests. |

NASA's [verification guidance](https://www.grc.nasa.gov/WWW/wind/valid/tutorial/verassess.html)
distinguishes correct implementation from accuracy of a particular calculation.
Neither automatically establishes empirical realism. Agreement between two
programs can still reflect a shared simplifying assumption. Visual inspection
helps reveal reversed axes, missing regions or implausible patterns; it cannot
replace conservation or resolution checks.

**Reading evidence status:** a test file defines a check; it is not a passing-run
receipt. A recorded pass applies to the code, inputs, runtime and configuration
named in that record. Receipts linked from these chapters are dated records of
those runs. Only receipts that the [current-evidence register](../../docs/CURRENT_EVIDENCE.md)
lists as current still match the files they bind; treat every other linked receipt,
including all W01–W12 records, as historical or unclassified, not as evidence
about today's code. Most checks compare the code with analytical cases, its own
refinements, conservation accounts or warm/cold parity. Those are V1/V2 evidence
that the implementation is consistent, not V3 validation against independent
observations. A current case matrix defines an experiment; it does not prove the
experiment passed.

The guide was expanded by reading code, existing checks and method references.
No numerical campaign was rerun to write it. Detailed findings remain in
[W10 validation](W10_VALIDATION.md) and the affected method records. Performance
results likewise keep their measured workload, numerical error and hardware scope;
a small-case speedup is not a planetary runtime forecast.

## A short vocabulary for reading outputs

- **Cohort:** material with a shared recorded origin/history, tracked without
  inventing new material when it changes cells.
- **Field:** a quantity distributed through space, such as temperature or velocity.
- **Support:** the points, cells, faces, depths or regions to which a value applies.
  A centre sample is not necessarily a cell average.
- **Intensive versus extensive:** temperature describes a state; mass, volume and
  heat content describe amounts. Averaging one is not summing the other.
- **Rheology:** the rule describing how material deforms under stress and how
  temperature, pressure or deformation history change that behaviour.
- **Isostasy and flexure:** local column-weight balance and the additional sideways
  spreading of a response by plate bending. Their contributions must not be counted
  twice through different adapters.
- **Residual and convergence:** a residual measures disagreement with equations;
  iterative convergence reduces it. Neither alone proves adequate grid resolution.
- **Reference:** the frame, pressure datum, elevation level or material state against
  which a value is defined. Displacement is not automatically absolute elevation.
- **Identity/provenance:** which source, inputs, methods and runtime produced a result.
  A matching hash supports integrity/reuse, not physical truth.

Lengths are normally metres, time seconds, absolute temperature kelvin, pressure
and stress pascals, and angular velocity radians per second. Documents may show
km, Ma or cm/year with explicit conversion. Formation age, cooling age and elapsed
simulation time are separate. Unknown values and their masks are not zeroes.

## Scientific ownership and maintenance

Tectonics owns plate/block motion, fault deformation, regional mechanical response
and their necessary thermal/support calculations. Geology, hydrology, erosion,
soils and other modules own further effects on their state. Retained helper code
can stay in this package without making all future science tectonics work. See
[the ownership decision](TECTONICS_PLAN.md#current-module-boundaries-and-continuation-23-september-2026).

Research links in the chapters say whether a source supplies a physical model,
a numerical technique, observations or a software comparison. A cited external
program is not automatically an installed dependency, copied implementation or
newly executed cross-code benchmark. Where the connection is an Atlas scenario
choice, the guide says so rather than borrowing a paper's authority.

When a method changes, update its explanation, code/evidence links and affected
connection in the relevant chapter as part of the same delivery. Update this index
and the READMEs when coverage changes. Keep explanations in generation/dependency
order, showing feedback loops and optional branches rather than development dates
or W/I numbering. Explain the process, its inputs and outputs,
the role of papers/software actually consulted, and what the checks establish.
Use existing evidence where valid; documentation maintenance alone does not need
a numerical rerun or a rewritten source-bound receipt. Do not create dated copies
or paste a running development log.
Use [the roadmap](../../docs/ATLAS_ROADMAP.md) for planned work and
[the tectonics README](../README.md) for execution entry points.
