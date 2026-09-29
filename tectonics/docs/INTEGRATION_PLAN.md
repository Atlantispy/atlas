# Complete tectonics integration plan

28 September 2026. **WORKING NON-CANON — plan, not implemented capability.**

This is the forward integration scope for finishing the tectonics generator.
It replaces the narrower interpretation of W12 completion and the provisional
B2 implementation order. [W12_ASSEMBLY.md](W12_ASSEMBLY.md) remains the record of
what actually exists. [CURRENT_STATE.md](../../docs/CURRENT_STATE.md) remains the
single progress summary; do not maintain another competing status ledger here.

This is the complete planning scope, not blanket execution authority. The latest
owner instruction permits the repair and acceptance work through **I02.2 only**;
stop before I02.3 unless separately resumed. Preparing the later briefs does not
start them. See the coordinator's WORKFLOW_DECISIONS.md and bridge/loop.json for
live controls, [the I01 physical contract](I01_PHYSICAL_CONTRACT.md) and the single
current-state record. No installations, reopening R4.4, broad/full-world runs,
commits, pushes or paid overage are implied. The I01-only automatic timeout
continuation permission has expired. Do not change an in-flight brief or its
editable files when updating this plan; use the revised plan for its successor.

## 1. The outcome we must deliver

From a seed and a declared Earth-like planetary scenario, a user can create a
different, physically consistent tectonic world, evolve it to a chosen snapshot,
inspect the actual calculations, save it, reopen it and continue it. The resulting
plates, boundaries, crust, material histories, ocean ages, temperatures and
tectonic vertical response must describe **the same evolved world**. Supported
regional detail must derive from that world and return its accounted consequences,
not exist as unrelated demonstration arrays.

Atlas 1.0 can still deliver a fixed point in time. A represented tectonic history
is an internal means of obtaining a consistent snapshot, not a requirement that
the user manually author every timestep. Conversely, merely preparing starting
conditions or exporting each solver's results does not satisfy this outcome.

Required user routes:

1. **Generate:** seed/settings → initial state → supported causal history → saved
   selected-time tectonic snapshot. Report failures; do not silently hunt seeds.
2. **Inspect:** globe/map, layers, boundary motion, time, local sections, units,
   assumptions and numerical/scientific evidence from actual saved results.
3. **Continue:** the original source-compatible state advances without regenerating
   its past, resetting ages or losing material and mechanical memory.
4. **Change deliberately:** changed physical inputs create an identified successor
   and recompute its dependencies; a camera or display change does not rerun physics.
5. **Consume:** geology, terrain and other modules can use typed, spatially and
   temporally compatible outputs without reverse-engineering internal arrays.

Whole-sphere **coarse tectonic** generation and supported regional detail are part
of this completion target. Regional examples alone cannot close it. This does
not promise global metre-scale mechanics or a particular planetary run time.

## 2. Scope and scientific ownership

Keep the [existing ownership decision](TECTONICS_PLAN.md#current-module-boundaries-and-continuation-23-september-2026).
Do not move packages merely to reorganise ownership.

| Tectonics must own | Exchange with another owner | Not a prerequisite for this standalone release |
| --- | --- | --- |
| Plate/block motion, deforming zones, shared boundaries, supported creation/reorganisation/retirement events and junction compatibility | Geological descriptions, material/strength properties and inherited structure from geology | A complete petrological/metamorphic/mineral-deposit generator |
| Extension, spreading, transform/oblique deformation, supported shortening, subduction and collision | Magmatic source, transfer and emplacement laws from geology; tectonics books applicable material, heat and mechanical consequences once | General reactive melt transport or every kind of volcanism |
| Material transport, crustal thickening/thinning, crust birth/consumption and tectonic history | Erosion/deposition and water loads from their owners | Complete climate, drainage, erosion and sediment-routing simulations |
| Thermal/mechanical response needed by tectonics, supported isostasy/flexure and tectonic elevation/bathymetry baseline | Ground geometry and material changes to terrain; accepted load/removal feedback back to tectonics | Finished valleys, cliffs, coastlines, soils, ecosystems or human geography |
| Execution of this coupled tectonic state, restart, evidence and performance | Shared Atlas execution/storage services; UI presentation owned by the UI workstream | A second scheduler, cache or UI-specific scientific generator |

Standalone cases may use explicit zero external erosion/water change or supplied
forcing. Missing required inputs must not silently become zero. Those cases test
tectonics; they do not establish the accuracy of absent downstream processes.

The Earth-like starting scenario assumes plate tectonics already exists. We need
not simulate planetary accretion or the original emergence of tectonics from a
stagnant lid. Initial plates, inheritance, slabs and forcing may be declared
assumptions. Subsequent claimed deformation and boundary changes must follow the
selected physical model, not a visual repair. Self-organising global mantle
convection and spontaneous initiation of every fault remain outside this target;
this does not waive the causal-generation requirement.

For Diadem-specific generation, retain the existing project/source/canon admission
block until compatible approved inputs are available. Public synthetic controls
are not permission to create replacement Diadem geography.

## 3. What exists, and what integration still needs

W-numbers identify responsibilities, **not twelve operations to run serially**.
Existing code is reusable only inside its stated physical and geometric envelope.
The table distinguishes connection work from genuinely new modelling.

| Existing area | Reuse | Remaining integration or mechanism |
| --- | --- | --- |
| W01 geometry/geology/forcing | Shared spherical atlas, descriptions, finite-cell sampling, compatible regional forcing | Continuously evolving global boundaries; moving-world resampling; conservative sphere↔regional exchanges; no discarded sideways motion |
| W02 material/history | Cohorts, finite-volume transport, remap, moving cells, birth/removal and 1D topology operations | Spherical material transport and events; global geometry/ownership closure; transfer of complete state, not just ownership labels |
| W03 thermal/compaction | Analytical cooling, heat accounts, finite-water compaction and column histories | Coupled moving/heterogeneous state; formation versus cooling/reheating histories; legitimate handoff to mechanics; stationary-column restrictions must not be bypassed |
| W04 support | Physical loads, uniform/variable regional flexure and evolving reference-load support | Consistent spatial/vertical reference for the world; global/regional support ownership; a supported 2D/spherical response where the claim requires it, not tiled 1D transects |
| W05 extension | Supplied-fault deformation, material exports and dry regional response | Selection/continuation from the evolving world; material/thermal return; explicit transition to breakup rather than creating ocean wherever polygons separate |
| W06 spreading | Birth strips, age-resolved cooling, finite sources/sinks, staged histories and inherited margins | Moving global ridge histories and closed accounts; inherited/new ocean age separation; heterogeneous W06→W07 bridge |
| W07 mechanics | Regional Stokes, rheology/strength, separate heterogeneous thermal and surface-coupling components | Assemble compatible evolving material/thermal/force/surface state. The simple workflow's homogeneous, closed, constant-viscosity restrictions are not the scope of all lower-level code |
| W08 regimes | Shortening, shear, underthrusting, subduction benchmark, finite magmatic accounts and supported joins | Global event dispatch, physical transitions, conservative plan-view↔section transfers and return to the world; prescribed slab/fault geometry is not emergent geometry |
| Continuation adapters | Evolving rigidity/forces and supported dated histories | A common coupled clock and transactional state. Sequences of mechanical snapshots currently do not automatically integrate their velocities into world geometry |
| W09 retained surface work | Existing routing/water/erosion components and their contracts | Tectonic exchange/feedback boundary only; finish their science with the appropriate modules later |
| W10 evidence | Independent equations, numerical controls, published/observational comparisons and B1 diagnostics | Coupled-chain physical tests and generated-world numerical/visual acceptance, with current source bindings |
| W11 machinery | Prepared operators, valid reuse, bounded work, storage and existing parallel controls | Correct invalidation across the new feedback loop; measured coupled performance and history growth |
| W12 delivery | Stationary W01→W04 assembly, typed native exports, graph/cache, jobs and readers | Production producer for the complete evolved state; actual physical joins and consumer validation, not exports alone |
| New World | Seed/settings, initial layout/crust/motion, projects and bounded regional continuation | Replace snapshot-only orchestration with an evolved-world producer; preserve the old initial-condition route and old saved files honestly |

Entry points are the [coding route map](../../docs/CODING_SAFETY.md#1-choose-the-route-before-reading-the-stack),
[foundation methods](how-it-works/01-foundations.md),
[process methods](how-it-works/02-tectonic-processes.md),
[W12 route matrix](W12_ASSEMBLY.md#supported-route-matrix) and
[causal-generation diagnosis](NEW_WORLD_LAYOUT.md#causal-generation-diagnosis-and-replacement-design).
This inventory is not a fresh acceptance run of those components.

## 4. Architecture: one evolving physical state

Use a coarse spherical world, regional process domains where needed, and separate
output sampling. More display pixels must not create different faults or a new
tectonic history. Conversely, finer **process** resolution is a different numerical
calculation and must carry its own error/identity information.

```text
Seed / declared geological scenario / existing world
                         |
             Identified initial physical state
                         |
       +---------- One accepted-time loop -------------------+
       |                                                     |
       v                                                     |
Motion/forces + material/temperature/strength                  |
       |                                                     |
Boundary evolution + supported regional mechanics             |
       |                                                     |
Conservative material/birth/sink and heat updates               |
       |                                                     |
Updated thickness, properties, loads and owned support response|
       |                                                     |
Event/topology closure + coupled error checks ------ accept ---+
                         |
              Atomic saved state and accounts
                         |
          UI / geology / terrain / other consumers
                         ^
       Identified external loads or material exchanges
```

The diagram specifies dependencies, not a fixed one-pass numerical splitting.
Strong feedback requires correction/iteration within an interval, or a demonstrated
split-error bound and substeps. Accepting individually converged components is
not sufficient to accept their coupled state.

### State and exchange contract

Every accepted state must preserve:

- World, scenario, epoch and forward-time convention; sphere/frame and vertical
  reference; source, equation/closure, parameter and numerical-policy identities.
- Plate/block IDs separately from crust/material IDs; finite rotations and actual
  velocity fields; one shared boundary/junction network, event lineage and origin.
- Cohort formation and cooling/reheating histories, spatial occupancy, grain/pore
  volume and reference mass where defined, layer order where a solver needs it,
  finite source/sink stocks and cumulative transfers.
- Temperature/enthalpy with heat-capacity and reference conventions; density and
  rheology laws; required damage, strain, stress or peak-load memory. An averaged
  temperature or pressure snapshot cannot manufacture those histories.
- Material/reference/thermal/external loads with contribution owners; mechanical
  and support references; absolute tectonic elevation where supported and explicit
  unknown masks otherwise. A relative displacement is not absolute elevation.
- Each representation's support, footprints, quadrature/weights and transform;
  projection error and omitted dimensions; accepted exchange interval and parent ID.
- Resource use, numerical residuals/error estimates, refusals and committed restart
  dependencies. Scientific unknowns are not failed-byte-verification warnings.

Map material **amounts**, not independent cell-centre labels. Record an exchange
once with equal debit/credit and a named exterior/reservoir if it leaves the
represented lithosphere. Fixed-density reference mass and thermally varying
buoyancy are distinct. Inflows need actual compositions and thermal conditions.
Depth-averaged, shell-volume, planar-width and full-volume representations need
explicit conversions; identical array shapes are not compatibility evidence.

On a closed sphere, physical surface ownership must cover exactly the sphere
without gaps or overlapping owners. Surface-area closure and crustal mass closure
are different: thinning, thickening, creation and consumption need their own
accounts. Do not renormalise plate areas or inventories after an inconsistent step.

### Physical contribution ownership

| Contribution | Rule |
| --- | --- |
| Motion | Kinematic forcing supplies a mechanical boundary condition OR directly advances a kinematic region; never add both displacements to the same material |
| Thermal buoyancy | Use the mechanical body's resolved buoyancy or the declared reduced support path for a given contribution; no repeated local-subsidence plus flexure addition |
| Flexure | Total equilibrium response is measured from one reference; add only its change between accepted states, never sum successive total deflections |
| Material transfer | One cohort debit/credit through shared exchange accounting, including ridge birth, subduction/export and magmatic transfer |
| Heat | Advected enthalpy, conductive flux, supplied basal heat and any selected dissipation/latent terms each have one owner and reference convention |
| External loading | Water/sediment/geological changes enter once with their timing and footprint; a receiving module does not independently reapply tectonic displacement |
| Regional refinement | Regional solution replaces or corrects its declared coarse contribution; overlapping local calculations cannot both own the same material or work |

## 5. Scientific decisions that must close before their implementation

These are mandatory deliverables, not permission to insert plausible-looking
defaults. I01 resolves them into exact equations, parameters, input needs,
validity ranges and tests before the affected producer is integrated.

| Decision | Recommended investigation / resolution | Completion evidence |
| --- | --- | --- |
| D1: global driving motion | Compare a reduced spherical plate force/torque model with documented imposed mantle/boundary forcing and mechanically resolved deforming belts. Keep prescribed rotations as a reference mode. Do not force the answer to a random RMS speed. A full global convection calculation is not the automatic fallback. | Named terms/units, frame and nullspace treatment, energy/work and torque residuals, reference cases and bounded cost. Missing forces stay visible; balance alone does not validate a force law |
| D2: boundary creation and changes | Specify strength, pressure/temperature dependence, inherited weaknesses, damage/healing if used, and a physical regularisation length; distinguish prescribed initial boundaries from subsequently calculated failure/events | Controlled localisation and continuation, sensitivity to physical forcing/strength, mesh-orientation/refinement checks and explicit transition laws; no bend-score minimisation |
| D3: ocean birth and recycling | Opening relative to a moving ridge, actual birth time/position, finite material/heat sources, supported subduction polarity and destination | Exact constant/staged-history controls and all source/sink balances; inherited ocean ages never silently become newly formed crust |
| D4: thermal/mechanical coupling | Select the thermal and constitutive models compatible with each evolving material representation; identify missing advection/source/phase terms | Heat and material accounting, common returned endpoint, coupled time/space controls; do not average heterogeneous W06 histories into a falsely homogeneous W07 input |
| D5: support and reference surface | Select global/local support geometry and how regional flexure/mechanics replaces it; define reference density/load, rigidity and vertical datum | Exact/simple load controls, exterior-domain sensitivity, no double counting, a documented datum/sea-level prescription separate from crust type |
| D6: regime and representation transitions | Declare rift→spreading, ocean entry→subduction, continental entry→collision, shear/oblique transitions and allowed topology events | Compatible overlap/transfer maps, required fault/slab geometry and memory, simultaneous-event policy and transactional refusal |

The recommended direction is **an evolving spherical history with physically
specified driving/event laws and targeted regional mechanics**. This is an Atlas
architecture proposal, not a published ready-made solution. A kinematic-only
mode remains useful but cannot silently become the answer to D1/D2. If the
required causal model cannot meet accuracy/resource goals, report that specific
trade-off before changing scope. A full plan is not evidence that these research
choices are already solved.

## 6. Implementation order and acceptance per increment

I-numbers below are integration increments, not replacements for W01–W12.
Each increment includes its focused checks, affected documentation and early
performance measurement. Do not postpone all testing or optimisation until I11.

### How Codex and Claude use these briefs

Each numbered assignment below is a bounded delivery, not an instruction to send
an entire stage in one large prompt. Codex selects the next dependency-ready
assignment and supplies exact editable paths and current input identities.
Claude implements it and prepares focused tests; Codex reviews the actual patch,
executes the required checks and sends corrections or the next authorised brief.
The current shell-free Claude route cannot execute its tests: prepared tests and
passing tests must remain distinct. The UI owner retains UI implementation.

**Research must resolve a coding decision.** Start with the stage's named local
method contract and existing evidence. Reopen only relevant primary equations or
reference-software sections to answer the stated unresolved question. Record the
selected equations, units/conventions, inputs, validity, algorithm, independent
check and reason for the choice in the existing method document. Reading ends
when those are sufficient to implement the bounded change; do not return another
general literature survey. Sources listed here are targeted reading, not claims
that their complete methods have been inspected, reproduced or newly validated.
No new physical law is authorised merely by appearing in a bibliography.

Where a benchmark's exact inputs cannot be recovered, identify what it would
establish and use an independently justified analytical, manufactured or available
reference case for that claim. Keep missing empirical calibration and full-event
acceptance visible. Never tune thresholds to generated results or promote two
implementations of the same equations into independent geological validation.

Every dispatch is assembled from this compact contract, not a fresh standalone
plan or the entire conversation:

| Brief field | Required content |
| --- | --- |
| Outcome and scope | One numbered assignment, real user/process outcome, explicit exclusions and current authority |
| Inputs and prerequisites | Accepted upstream state/contracts and exact source/evidence pointers; unknowns and genuine blockers |
| Research decision | Named question, primary paper/software sections, retained choice and exact unresolved extension; omit new research when already settled |
| Implementation | Actual APIs/files to reuse, exact editable paths, input/output and contribution ownership; preserve unrelated edits |
| Acceptance and cost | Existing tolerances plus justified new criteria fixed before testing; smallest adequate seam/physical checks, resource limits and matched timing where relevant |
| Return | Saved code/docs, tests prepared versus run, measured results, sources actually used, unsupported cases and next review action |

Keep the returned evidence in existing files/registers. Reuse adequate unchanged
checks; no automatic reviewer-of-reviewer, whole-suite rerun or research-only
follow-up. A required independent comparison addresses a named risk. Failed
checks are fixed at their generating cause, not hidden through smoother output.
Package extraction/source changes require honest identity/evidence handling, not
silent repinning. Each accepted scientific change updates the reader guide in
generation order before new evidence capture. No token instrumentation.

The stage gates below remain mandatory: a substep is complete only for its named
output, not the entire stage. Stages with physical feedback have dependency-ready
substeps; they need not wait for each other's full acceptance before work begins.
The [dependency order](#dependencies-and-sensible-parallel-work) specifies these
connections. Unsupported required physics is a blocker, not a reduced default.

### I01 — Freeze the end-to-end contract and physical closure choices

**Focused brief: retain the completed baseline.** Reuse the
[physical contract](I01_PHYSICAL_CONTRACT.md), [closure matrix](I01_CLOSURE_MATRIX.md)
and their current evidence. No new I01 coding/research assignment is needed merely
to start a later stage. If an implementation exposes a specific missing equation,
input, ownership rule or invalid assumption, isolate that question, consult the
primary source already cited by its method document, correct the affected contract
and test only the changed claim. Return the resolved requirement to its named
I02–I09 owner; do not restart the entire scientific review. The original full-event
conditions remain assigned to those later stages.

The reviewed [closure matrix](I01_CLOSURE_MATRIX.md) and its
[machine-readable mirror](../cases/i01_closure_matrix_v1.json) map the promised
routes to producers, evidence and remaining decisions in generation order.
They distinguish missing I01 physics from later implementation; the matrix is
not a completed generator or an accepted separation law.

The I01 review repairs enforce actual thermal/mechanical density and prepared
thermal content, require explicit supported branches for common-Gibbs inversions,
and reuse the unchanged separation filter factor. All 592 I01 tests and the
affected connected controls pass; the current evidence register points to fresh
receipts rather than rewriting old ones. I02's current authority is stated above.

MC-06 now has a [conditional lateral-conduction criterion](I01_LATERAL_HEAT.md)
and a [bounded control](../evidence/i01-lateral-heat-r1.json). It selects the
thermal error rule, while valid contact geometry, whole-window bounds and
coupled feedback remain I05/I06 implementation/admission work. MC-04 now has a
[reviewed basal specification and accounts](I01_BASAL_CLOSURE.md), with
[eight bounded controls](../evidence/i01-basal-closure-r1.json), including an
independent exact mechanical-work solution. Actual transport, source-state to
prescription binding and resolved-depth sensitivity remain I05/I07 work.
The remaining-choice pass distinguishes I01 selection/feasibility from the full
physical-event acceptance already assigned to I05–I09. The latter gates are not
waived or counted as completed by small controls. MC-01's
[resolved-band control](I01_SEPARATION_FEASIBILITY.md) now passes fixed-length/time
refinement and independent energy accounts with irreversible bond history.
MC-03's compatible instantaneous segregation control now passes. Together with
the retained G25 checks and selected focusing/thermal contract, this completes
its I01 choice and bounded feasibility, not source-to-crust evolution or physical
calibration. Exact receipts and review details belong in CURRENT_STATE.
MC-02 now has a [resolved-initiation method and prospective test specification](I01_INITIATION_DECISION.md),
including retained stress, prescribed pore pressure, physical-length weakening
and a genuine force-release check. Its independent
[analytical verification route](I01_INITIATION_VERIFICATION.md) now has
[sixteen passing controls](../evidence/i01-initiation-verification-r1.json).
This closes I01's choice and bounded prerequisite verification without requiring
an unreconstructable published experiment. Li and Gurnis (2023) and Gurnis,
Hall and Lavier (2004) remain external comparison sources; missing inputs are
not invented. I07 must still lock the complete physical case and pass coupled
refinement, boundary-sensitivity and true release tests before initiation
acceptance. The current authored-R control is not a generated event. MC-07's
[water-loaded columns-to-GPE connection](I01_WATER_GPE.md) now passes nineteen
tests and [eight controls](../evidence/i01-water-gpe-r1.json), without a second
isostatic correction or load. Structural dry/Airy/uniform cases need no further
input; nonuniform finite rigidity requires an explicit shear-transfer depth.
The [declared single-core producer](I01_ELASTIC_CORE.md) now supplies that depth
and rigidity from the same homogeneous material layer. Eighteen tests and
[six bounded controls](../evidence/i01-elastic-core-r1.json) support selecting
this MC-07 branch. Core geometry and moduli are explicit inputs, not inferred
from effective elastic thickness or D2 strength. Spherical/boundary assembly,
variable rigidity and curved-reference admission remain I04/I08 work.
MC-05 now has [exact contact detection](I01_JUNCTION_EVENTS.md) followed by a
[local outgoing ridge check](I01_RIDGE_JUNCTION.md): two endpoint laws and
ownership-oriented growth are checked for a supplied symmetric-ridge candidate.
Physical boundary birth and complete geometric admission are still required;
these prerequisites do not close MC-05 or select a graph edit.
The [MC-05 physical route](I01_JUNCTION_REORGANISATION.md) now selects a local
multidirectional deforming region, using the common separation/initiation/magma
mechanisms, followed by joint material-derived topology extraction. I07 must
retain both horizontal directions and vertical structure in the general regional
solve; the declared 3D constitutive convention needs explicit parameter conversion.
I09 owns work-conjugate feedback, I03 the shared geometry and I02 the joint commit.
No graph score, contact-only flip or new standalone junction fracture law replaces
that chain. The [multidirectional feasibility control](I01_JUNCTION_FEASIBILITY.md)
now runs eight actual plate-coupled 3D solves with independent force, torque and
power checks. Its [passing receipt](../evidence/i01-junction-feasibility-r1.json)
supports I01 selection; evolving shared mechanisms and joint topology acceptance
remain I03/I07/I09/I02 work. Do not rerun completed contact/ridge helpers merely
to replace those missing physical connections.
MC-01's elastic-memory subchoice is now **retain**, with the
[logarithmic-objective direction and exact coaxial control](I01_ELASTIC_MEMORY.md)
checked by twelve tests and [nine controls](../evidence/i01-elastic-memory-r1.json).
This does not close MC-01's separation mechanism or implement the general law.
I02/I05 preserve and transport stress; I07 owns non-coaxial mechanics and its
stored-energy/heat balance. Omitting stress memory is not an admitted default.

Delivered design/control slice: [I01 physical contract](I01_PHYSICAL_CONTRACT.md),
[versioned case record](../cases/i01_closures_v1.json) and
[bounded control evidence](../evidence/i01-controls-r1.json), followed by a bounded
[2D localisation probe](I01_FAULT2D.md), [pressure/temperature mechanical snapshots](I01_STRENGTH.md)
and [reviewed D6 transition specification and controls](I01_TRANSITIONS.md).
The [nonlinear motion-admission certificate](I01_DECOUPLING.md) supplies a bounded
scalar prerequisite, not a physical rupture trigger. The reviewed
actual-column extension in [I01_COLUMN_ADMISSION.md](I01_COLUMN_ADMISSION.md)
now derives a sufficient exact upper bound from the represented mixed-creep
column for fixed-geometry, fixed-temperature extension windows. Its ten tests
and eight controls pass without fitting the rheology; non-admission is not
misreported as excessive actual error. It remains separate from physical
separation and finite-strain transport. The reviewed
[thermal/history prototype](I01_THERMAL.md) now evolves temperature and accumulated
plastic history with the retained mechanical response in a bounded small-strain
material/reference cell. Analytical, grid/time, energy/history and refusal
controls pass; finite-strain transport and global embedding remain open.
The independent [phase-aware melt-delivery connection](I01_DELIVERY.md) now joins
finite liquid separation to unchanged W08 placement/cooling with conserved
component and enthalpy accounts. It requires a prescribed extraction amount.
The independent [dry decompression control](I01_MELTING.md) now produces retained
melt while coupling phase equilibrium and thermal cooling along a supplied
pressure path. Its exact and tighter-reference controls pass. Compatible phase
thermodynamics between this batch law and the common-Tm delivery law, extraction,
transport and source compaction remain physical closures; the two prototypes are
not silently joined by passing a fraction between incompatible models.
The independent [composition-aware phase partition](I01_PHASE_PARTITION.md)
now provides a fixed-P/T component-balance prerequisite: extraction changes
bulk composition and re-equilibration preserves the depleted liquid inventory.
Nine tests and an analytical binary control pass. It does not supply missing
phase enthalpies or connect the incompatible thermal laws; a shared provider
must own `F,c_s,c_l,h_s,h_l`, a common datum and pressure-work convention before
the existing W08 emplacement can receive its energy-bearing payload. I01 owns
that model choice; I05 owns moving thermal/material implementation and I06 its
ocean-birth use. No reset of original Katz composition after extraction.
The [nonlinear column-resistance control](I01_COLUMN.md) adds published-convention
creep coefficients, regularised friction and depth-integrated force/work for
explicit supplied profiles. It is a constitutive diagnostic, not a resolved
rupture reaction or an automatic replacement for the existing D2 solver.
The reviewed [evolving column-weakening adapter](I01_WEAKENING.md) now evolves
raw per-point plastic history and transmitted resistance with the compatible
vertical/mean-pressure closure, fixed-rate/force controls and bounded history
envelopes. Immutable preparation and direct-entry guards were corrected during
review. Temperature remains prescribed; it is not laterally resolved rifting,
thermal feedback, finite-strain evolution or a separation criterion. The column's
mixed creep exponents also do not directly fit the scalar decoupling family.
The new [resistance-to-motion connection](I01_MOTION_COUPLING.md) balances
external driving force against disjoint generalised drag and that evolving
column resistance. It solves rate at each history stage, with signed nonlinear
root checks, consistent work, time/depth refinement and measured warm-start reuse.
This is a fixed-temperature regional feasibility connection, not spherical
assembly or a rigorous separation certificate. The reviewed
[column-heat connection](I01_COLUMN_HEAT.md) now evolves conduction, mechanical
heat and thermal weakening on identical depth support. Nineteen focused tests
and all seven corrected r2 controls pass; geometry/capacity pairing and physical
layer-mean reporting were repaired without changing the valid-case physics.
The reviewed [force-driven thermal/motion connection](I01_THERMOMECHANICAL_MOTION.md)
now joins force-balanced motion to that thermal/history evolution, keeping
external drag dissipation out of the column heat account. Twelve focused tests
and all six bounded controls pass, including second-order homogeneous oracles,
coupled time/depth refinement and atomic refusals. It does not replace
finite-strain transport or a physical separation criterion.
The reviewed [finite-strain column](I01_FINITE_STRAIN.md) now connects changing
width/thickness and pressure with material-following temperature/history and
force-balanced motion in a closed affine strip. Twenty-three tests and all seven
corrected r2 controls pass; mass, capacity, work and heat are accounted together.
This removes the fixed-geometry limit for that bounded representation, not for
lateral/localised flow or rupture. Its measured eigensystem/warm-start reuse
saves 75.66% on one matched control; no world-runtime claim.
The [finite-water/flexure control](I01_WATER_FLEXURE.md) now couples a 2D periodic,
constant-rigidity plate to a changing wet mask and conserved water volume.
Dry restoring force, shared endpoint, exact controls and grid refinement are
checked; no double water feedback or repeated addition of total deflection.
This is D5 closure feasibility, not I08 finite-regional/global embedding.
The [dry columns-to-GPE connection](I01_GPE.md) now uses the same material and
thermal columns for support and driving traction, with a common compensated
datum and no extra ridge push. Exact layer moments, spherical gradients and
the retained D1 torque solver are checked together against analytical hemisphere
rotations and work. This is D1/D5 feasibility, not I04 evolving-world sampling;
water-loaded or mechanically resolved columns need their own compatible join.
The reviewed [finite-strain admission](I01_FINITE_ADMISSION.md) connects a
conditional conservative motion bound to issued states of the evolving strip,
preserving absolute reference, elapsed time and history. Its nineteen tests and
five bounded controls pass; no rupture or automatic switch is authorised.
Efficient persisted continuation belongs to I02/I05, not another I01 adapter.
The [common ideal-mixture energy law](I01_PHASE_ENERGY.md) and
[compatible finite receiver](I01_MAGMA_RECEIVER.md) also close bounded
composition/enthalpy feasibility; they do not calibrate mantle material or select
pressure transport and extraction rates. Their current receipts and remaining
boundaries are recorded in the current-state page.
These controls are not generated boundary/rupture acceptance. The new
[bond-history/resolved-band specification](I01_SEPARATION_FEASIBILITY.md) and
[porous-flow/cooling-barrier route](I01_MELT_ROUTE.md) complete the I01 choices.
Their complete physical applications stay with the named later owners. Consult
current state for executed feasibility and remaining dependencies. Original
source-bound receipts are unchanged; documentation-only drift is labelled.

**Depends on:** this plan. **Work:** turn D1–D6 into versioned, testable model
specifications; define generated versus prescribed modes and required/unsupported
regimes. Bind a compact acceptance matrix to the promised user routes. Review the
primary papers and applicable software before choosing each new law.

Specify whether plate count and continental fraction constrain the initial state
or selected-time result. Default recommendation: initial-state controls; final
values evolve. A final-state target requires an explicit inverse problem, not
post-run area correction. Specify initial history horizon and inherited age/thermal
assumptions. No circular dependency requiring the completed world as its own input.

**Finish when:** every promised product has a producer, every feedback has an owner,
every physical decision has equations/input requirements/validity/tests, and the
new mechanism feasibility is demonstrated by a bounded control or remains openly
blocked. No complete-generator claim while D1/D2 are unresolved.

**Acceptance boundary clarified, 28 September:** this finish rule is about model
selection, complete equations/input/support/test contracts and bounded feasibility.
It does not require I07's implementation to exist before I02 can begin. Retain
the matrix's original full-event acceptance conditions with their implementation
owners. Independent analytical verification is an allowed alternative for I01
where exact published inputs cannot be recovered; it never becomes empirical
validation or permission to generate an unsupported event.

### I02 — Common state, exchange transactions and accepted-time controller

**Status: I02.1 and I02.2 reviewed; stopped before I02.3.** The owner's later stop
instruction supersedes the earlier approval to continue through all eight I02
steps. The bounded continuation and ownership correction are accepted with
refreshed dependent evidence; the remaining steps require fresh authority.
Claude implements bounded assignments and Codex reviews their actual changes.
Preserve existing work; permission, usage and unresolved technical failures still
stop dispatch. No blanket installation, broad simulation or publication approval.

**Depends on:** I01's equations, ownership, support and acceptance contracts.
**Outcome:** one real, connected, restartable physical workflow using the existing
coupled solver, alongside the shared machinery later stages will extend. Empty
state containers and synthetic transfer tests alone do **not** finish I02.

**Focused research:** I02.1–I02.2 reuse the exact reference/history and admission
contracts in [finite strain](I01_FINITE_STRAIN.md) and
[finite admission](I01_FINITE_ADMISSION.md), not a new physical law. I02.3–I02.5
must answer where the native store atomically owns the accepted parent and all
accounts; consult SQLite's [transactions](https://www.sqlite.org/lang_transaction.html),
[atomic commit](https://www.sqlite.org/atomiccommit.html) and the documentation for
the actual [journal mode](https://www.sqlite.org/wal.html) in use. Do not assume
SQLite atomicity covers an unrelated file or a separately committed head pointer.
I02.6–I02.8 reuse existing job/readers and evidence machinery. The eight assignments
below already define the implementation order and acceptance; do not replace
them with the earlier, cancelled combined state/transaction brief.

The first physical route is the existing constant-drive, layered finite-strain
column: temperature changes strength and motion; deformation changes geometry
and heating; the next interval inherits those changes and their accounts. Use a
supplied supported initial case, not a new random-world or whole-planet run.
Retain its physical assumptions and acceptance bounds. The original mechanical
and thermal reference state must survive continuation, rather than each call
starting the calculation again or treating the deformed state as a new reference.

#### I02.1 — Define the shared state around the actual calculation

Implement section 4's common envelope with world/scenario, epoch and elapsed
time, parent identity, geometry/frame/support, units, source/runtime identity,
equations and numerical policy. Give each physical quantity and account exactly
one producer/owner. Preserve identified native payloads rather than flattening
material, thermal and mechanical history into untyped arrays.

Reuse [material histories](../src/atlas_tectonics/materials.py),
[dated histories](../src/atlas_tectonics/tectonic_history.py) and compatible finite
[inventory accounts](../src/atlas_tectonics/w08_inventory.py). Declare reference
mass versus current volume, thermal reference and signed enthalpy explicitly.
The initial adapter must name its supported fields; absent elasticity, melt,
global geometry or other state stays unsupported/unknown, never fabricated zero.
Other adapters must declare the same compatibility and ownership information.

**Done when:** the real initial column can be represented without losing its
inputs/history; wrong time, units, support, reference or ownership is rejected.

#### I02.2 — Turn the existing coupled solver into a continuable core

Refactor [finite-strain evolution](../tools/check_i01_finite_strain.py) into
initialisation, incremental advancement and result construction, retaining its
existing `evolve` entry point as a compatibility wrapper over the same equations.
Give the reusable kernel a package-owned implementation; do not make production
code depend on a campaign script through `sys.path` changes. Move only the
necessary helpers and update affected source identities explicitly.

Carry stretch, temperature departure, weakening history, conduction clock,
displacement/strain history, global step index, mechanical/thermal accounts and
required diagnostic extrema/counters between calls. Reconstruct geometry from
the original reference and current deformation. Speculative changes belong to
an isolated candidate; callers cannot mutate the committed state through aliases.

**Done when:** advancing the same case in two in-memory pieces agrees with the
original uninterrupted calculation within its existing declared tolerances,
including histories and accounts, not only the final displayed temperature.

#### I02.3 — Commit physical state and exchanges together

Reuse the native [ArrayStore](../src/atlas_tectonics/storage.py), its immutable
chunks, references, incremental writes and transactional publication. Add only
the missing accepted-state/transfer coordination. Each proposal names its parent,
interval, producer, transfer identity, donor, receiver, quantities and basis.
Check finite availability and compatible support; debit and credit once, including
signed enthalpy. External exchange needs a named source/sink, not an unexplained
balancing correction. Finite transfer support does not invent a transport law.

Validate the expected parent and update the accepted-state pointer, all affected
accounts and transfer records in the **same store transaction**. A preflight
check outside the writer transaction is insufficient. Freeze/own submitted data;
the store cannot protect mutable caller arrays on its own. Identical replay is
idempotent; a changed replay or stale competing writer refuses. A rejected,
cancelled or failed candidate leaves the previous accepted prefix untouched.

**Done when:** a small two-reservoir transfer and multi-component failure tests
prove conservation, exactly-once application, rollback and stale-parent refusal.

#### I02.4 — Put advancement under one accepted clock

Connect the real core to candidate → coupled checks → atomic commit. Every
participant consumes the same accepted parent and interval; no component may
quietly advance ahead and publish a mixed-time world. Reuse the existing coupled
heat/motion/geometry calculation, not a new unverified one-pass split.

For this first route, preserve the original global timestep schedule: continuation
chunks contain whole original steps, not a newly calculated `duration / steps`
at each restart. Keep the 256 accepted-step ceiling cumulative and retain existing
temperature, physical-horizon and admission limits. Requested save points must
respect that schedule. The event calendar records prescribed interval boundaries
and supported events; it must stop at unsupported physics, not manufacture an
event or silently step past it. Future adaptive/event-localising adapters need
their own admitted policy; storage chunking must never choose the physical step.

**Done when:** multiple requested advances retain one clock and the same numerical
path; failures report the last accepted time and cannot reset cumulative limits.

#### I02.5 — Save, reopen and continue the actual state

Persist the accepted physical arrays, original references, histories, global
schedule, cumulative accounts, limits and transfer identities using native
references and lossless storage. A checkpoint is not just a map or final summary.
Reopening validates schema, source/runtime, inputs, support and parent lineage;
incompatibility refuses continuation without silently rebinding an old result.

Rebuild disposable prepared operators/factors from pinned inputs rather than
serialising opaque solver objects or replaying from time zero. Provide an
engine-owned restoration path for [finite admission](../tools/check_i01_finite_admission.py)
that validates restored state and issues its corresponding admission context;
caller-supplied fingerprints alone must not authorise continuation. Scientific
counters survive reopening; operational timing records remain separate from
physical identity. Preserve cumulative workload limits instead of resetting them.

**Done when:** a fresh process resumes the real partially completed case to the
same physical/account result as uninterrupted execution, without repeating the
accepted prefix. Injected interruption exposes either the old complete checkpoint
or the new complete checkpoint, never a mixture.

#### I02.6 — Expose one usable backend workflow

Provide a small backend/CLI route to create a supported case, advance, inspect
status/results, cancel, save and load/continue. Return actual saved physical
fields with units, support, accepted time and identity, plus clear completed,
partial, cancelled and refused outcomes. Inspecting a checkpoint must not restart
physics or require loading every historical array.

Reuse compatible lifecycle and publication seams from existing project/job
tools and [W12 assembly](../src/atlas_tectonics/assembly.py); do not retarget an old
scientific producer or pretend this case is a generated planet. Keep UI work
with its owner. I10 still owns the full world-project/UI/downstream delivery path.

**Done when:** one command-level create → advance → save → load → continue →
inspect sequence executes the real coupled route without hand-assembling its
intermediate arrays, with cancellation retaining usable accepted progress.

#### I02.7 — Verify the joined route and measure its overhead

Use small focused tests for contracts, once-only exchanges, signed enthalpy,
rollback, competing writers, source/support mismatch and limit-reset attempts.
Then use one existing nontrivial coupled case for direct-solver versus workflow,
chunked versus uninterrupted, and fresh-process continuation comparisons. Include
its nonzero thermal/weakening history and complete account checks. Reuse unchanged
I01 evidence; rerun only controls affected by core extraction or changed coupling.
No relaxed tolerances, expanded step ceilings or broad planet campaign.

Measure elapsed time for bare physics, the wrapped workflow, checkpoint writes
and reopening/remaining work on the same declared workload. Report raw times and
percentage overhead or savings, distinguishing cold preparation and warm reuse.
Measure checkpoint growth and unchanged-chunk reuse without duplicating history.
Prefer lazy reads, bounded active state, lossless compression and exact operator
reuse; parallelise only genuinely independent work when measurement supports it,
not sequential feedback stages. Do not claim that framework integration itself
makes the physical solve faster.

Run targeted native Windows lifecycle checks; obtain a corresponding targeted
Linux result where an authorised environment is available. If unavailable, record
that platform coverage gap explicitly, not a cross-platform pass. No installation
or broad regression campaign is implied by this plan.

#### I02.8 — Close the integration and explain how to use it

Update the existing how-it-works chapter in generation order: initial state →
coupled physical step → checks/commit → checkpoint/continuation → inspected
outputs. Explain what is calculated, the actual papers/software reused and what
the checks establish. Complete source-bound method documentation before capturing
new evidence; update the current evidence register and state without rewriting
historical receipts or keeping competing status documents.

**I02 is complete only when** the shared-state, finite-exchange and failure guards
pass **and** the real coupled route works through the full backend lifecycle,
including interruption/reopening with preserved history and measured overhead.
Report outstanding platform coverage separately. This establishes a connected
workflow for the declared supported case, not merely plumbing tests and not
whole-planet tectonics acceptance.

**Boundary with later stages:** I03–I09 still implement evolving spherical
geometry, causal world/motion production, transport/melt, physical transitions,
support and their coupled acceptance. I02 must carry their state and exchange
contracts without pretending those producers are implemented. I10 connects the
complete scientific route to the world-project/UI and downstream consumers;
I11–I12 retain their wider end-to-end acceptance and release responsibilities. Whole-planet
evolution remains the target, not a feature removed by using a bounded first case.

### I03 — Evolving sphere, conservative history and spatial bridges

**Focused research decisions:** choose a conservative spherical intersection/remap
method for the actual cell edges and physical measures; specify polar/seam
handling, regional projection bounds and which quantities need integrals rather
than interpolation. Compare [ESMF's conservative regridding conventions](https://earthsystemmodeling.org/regrid/)
and [Kritsikis et al. (2017), general spherical meshes](https://gmd.copernicus.org/articles/10/425/2017/)
with retained W02 transport. Use [pyGPlates](https://www.gplates.org/docs/pygplates/pygplates_reference)
for topology/rotation/shared-segment semantics, not as a physical forward solver.
Conservation must use Atlas's actual support areas, not a mismatched approximate
grid measure or post-transfer normalisation. Reference software is not automatically
a new dependency; decide reuse versus a bounded native implementation explicitly.

**Ordered assignments:**

1. **I03.1 — Define one shared spherical network.** Extend I02 with uniquely
   owned faces, shared boundaries/junctions, orientations, finite rotations and
   separate plate/material identities. Verify closed coverage and valid topology;
   distinguish area, reference mass and phase-volume accounts.
2. **I03.2 — Move geometry and transfer complete material.** Connect rotations,
   shared-edge intersections and conservative transfers to the accepted state.
   Carry history/enthalpy through the same transfers; handle rigid rotation,
   stationary fields, seams/poles and mesh changes without resetting ages. Agree
   the transport interface with I05, which owns its evolving constitutive content.
3. **I03.3 — Build both spatial bridges.** Implement sphere-to-region extraction
   and region-to-sphere replacement with width, depth, orientation, quadrature,
   projection validity and coverage. Preserve full vectors, forces/work and
   untouched exterior state. Verify exact/round-trip controls and refuse unresolved
   overlaps or incompatible omitted dimensions.
4. **I03.4 — Commit joint geometry changes.** Consume supplied supported event
   proposals through I02; update shared junctions, material accounts and lineage
   together with deterministic simultaneous-event handling and rollback. Include
   a closed-sphere source/sink control. Event geometry controls do not establish
   the physical generation of the events; I06/I07/I09 supply that evidence.

**Efficiency/exclusions:** reuse geometry-indexed searches and sparse overlap maps
only while geometry identities match; work on intersecting supports and shared
immutable history. No copied full history per cell, cosmetic fault fairing,
area/mass repair, invented event law or discarded sideways motion. The original
finish gate below still applies to the joined geometry route.

**Depends on:** I02. **Reuse:** [spherical atlas](../src/atlas_tectonics/spherical_atlas.py),
rotation primitives, W01 sampling and W02 conservative principles. Add moving
shared boundaries/junctions, material ownership and finite rotations; define and
implement the necessary spherical transfers rather than renaming `PlateTopology1D`.
Mesh repair may preserve the physical state, not move a fault to improve its score.

Build sphere→regional and regional→sphere mappings with declared widths, depth
support, orientation, projection validity, heat/material accounts and covered
physics. Carry the complete velocity vector; use a supported higher-dimensional
representation or refuse, never discard motion outside a chosen section.

**Finish when:** exact rigid rotation, stationary state, one supplied ridge/source
control, shared-junction movement and source/sink accounts hold; rotated coordinates
and different sampling meshes represent the same physical case within the declared
bound. Include a closed-sphere source/sink control, not only an open transect.

### I04 — Causal starting-world and motion/boundary producer

**Focused research decisions:** map the selected D1/D2 forces, GPE gradients,
boundary integrals and physical weakening length onto changing spherical geometry
without mesh-direction bias. Identify which coefficients are supported material
inputs versus scenario assumptions. Reopen [I01_GPE.md](I01_GPE.md),
[I01_WATER_GPE.md](I01_WATER_GPE.md), the closure/weakening methods and
[Clennett et al. (2023)](https://www.nature.com/articles/s41598-023-37117-w)
for the force-consistency challenge; read its full relevant methods before adopting
anything beyond the existing contract. A balanced torque or Earth-fitted coefficient
does not independently validate a generated world's driving law.

**Ordered assignments:**

1. **I04.1 — Replace the initial template with a declared family.** Reuse New
   World's seed, layout, structure and thermal input contracts. Define continuous
   inherited geology/weaknesses independently of sampling, including declared
   geotherms, initial slabs and unknown ocean history. Initial plate count and
   continental fraction remain starting controls, not corrected final targets.
2. **I04.2 — Put D1 onto the evolving sphere.** Connect the selected torque and
   dry/water-loaded GPE laws to I03 geometry and compatible column properties.
   Start with known forcing; verify signs, nullspace/frame, torque and power.
   A boundary contribution receives either its admitted reduced resistance or
   a regional replacement, never both.
3. **I04.3 — Connect material-dependent boundary response.** Apply the selected
   temperature/pressure/creep/physical-length weakening laws, retaining transported
   raw history. Produce motion and supported event proposals with their admission
   evidence; do not directly edit a network because a stress flag changed.
4. **I04.4 — Close the first property/motion feedback.** Consume I05's current
   properties at a common endpoint and expose the reaction ports needed by I07/I09.
   Verify changed forcing, temperature and strength, frame invariance and fixed-
   physical-length refinement. Test initial diversity separately from calculated
   evolution. I09 owns the final multi-region coupling, not a prerequisite that
   prevents these producer/control substeps from being implemented.

**Efficiency/exclusions:** reuse geometry integrals and resistance preparations
only under complete determining identities. No fitted attractive rotations,
target-RMS speeds, final area/count correction, paused fairing prototype or claim
of self-organising mantle convection. Develop I04 and I05 against one interface;
complete their coupled checks together rather than repeatedly designing adapters.

**Depends on:** I01–I03. Replace the fixed three-province template with a declared
family of geological starting conditions independent of sampling resolution.
Preserve initial uncertainty as seed-labelled assumptions. Separate inherited
history from newly simulated history and retain continent/crust versus dry-land
distinctions.

Implement the selected D1/D2 laws: material/temperature/strength/forcing influence
motion and boundary events; subsequent geometry follows accepted history. Feed
updated state back to those laws. Start with simple known forcing before claiming
autonomous global generation. Do not integrate the paused fairing prototype as
the realism repair or merely fit random rotations to prettier boundaries.

**Finish when:** controlled physical changes affect the calculated response in
the expected direction/regime; common-frame changes do not; physical length scales
survive refinement; genuine ridge/transform bends remain possible. Initial diversity
and calculated evolution are assessed separately. A finite prescribed-history
demo cannot close this increment by itself.

### I05 — Moving material, thermal state and evolving properties

**Focused research decisions:** define moving-grid/material energy fluxes and
admitted contact geometry; decide when the selected lateral-conduction bound
requires an explicit lateral solve, and how phase fronts preserve the provider's
enthalpy convention. Reopen [lateral heat](I01_LATERAL_HEAT.md),
[elastic memory](I01_ELASTIC_MEMORY.md), [basal closure](I01_BASAL_CLOSURE.md),
[melt route](I01_MELT_ROUTE.md) and the pinned common-provider method. Use
[NIST FiPy's discretisation](https://pages.nist.gov/fipy/en/stable/numerical/discret.html)
as a finite-volume flux comparison, not automatic admission of a deformed mesh.
The current G25 phase-crossing refusal must remain until an explicitly supported
front/inversion treatment is implemented and checked.

**Ordered assignments:**

1. **I05.1 — Transport complete material records.** Join W01 sampling and W02
   transport/remap to I03 overlaps and I02 accounts. Preserve layer order,
   formation/cooling dates, original profiles, maximum compaction load, raw plastic
   history, irreversible bonds and supported stress/stretch state. Shared cells
   must not erase surviving bonded material or create averaged artificial bridges.
2. **I05.2 — Evolve heterogeneous heat on moving support.** Pair material and
   energy fluxes through the same intersections, with explicit mesh/material
   velocities, heat-capacity references and thermal contact. Reuse W03/W06/W07
   within their admission envelopes; give new supported geometry a new bridge,
   not relaxed guards on an old stationary/homogeneous interface.
3. **I05.3 — Derive compatible current properties and basal exchanges.** Connect
   finite strain, heat, weakening and basal accounts, including actual inflow/
   outflow material and per-column history clocks. Apply the lateral-heat rule.
   Return density, strength and admitted rigidity inputs to I04/I08; thermal
   thickness cannot manufacture an elastic core or pressure history.
4. **I05.4 — Carry phase changes and finite energy-bearing supply.** Join the
   selected provider/segregation/energy interfaces, handling supported melting/
   freezing fronts and donor depletion without inventing latent heat or resetting
   temperature/composition. Check conservative component/phase/enthalpy accounts;
   an unsupported path refuses before changing the accepted parent.
5. **I05.5 — Verify the production joins.** Use passive transport, deforming
   columns, two-age occupied-ocean cooling, interface fluxes, basal exchange and
   retained-memory cases with time/space refinement and resumed parity. Deliver
   current properties to I04 and a tested energy-bearing supply contract for I06;
   no requirement to finish I06 crust birth before implementing its inputs.

**Efficiency/exclusions:** reuse correctly keyed thermal/filter operators and
unchanged cohort projections, not accumulated historical factors. No cooling at
mean age, zero-filling ocean masks, resetting formation on reheating, invented
pore-pressure dynamics or automatic conversion of elastic work into heat. General
noncoaxial mechanics remains I07; full geochemical evolution remains geology-owned.

**Depends on:** I02–I03; supplies the state updates consumed iteratively by I04.
Connect W01 sampling, W02 transport and appropriate W03/W07 thermal components
without bypassing stationary/homogeneous admission guards. Preserve layer order,
formation/cooling dates, enthalpy and constitutive memory through resampling and
regime changes. Use actual current state to derive each permitted density,
viscosity/strength and rigidity input; thermal thickness is not elastic thickness.

**Finish when:** passive advection, deforming columns, a heterogeneous cooling
mixture and changed-property controls conserve the represented quantities and
show coupled timestep/space convergence. Update pore/water accounts only where
the existing drained-compaction law is applicable; do not invent pore-pressure
dynamics or extend a law beyond its validity just to complete a link.

In particular, W06 thermal means are over occupied oceanic material, not the whole
cell; empty masked entries are not temperatures. Preserve age distributions when
evaluating nonlinear cooling, rather than cooling at mean age. Moving a column
must not reset its initial profile or maximum compaction load. This is a new
evolving bridge, not permission to relax `bind_regional_geology`'s current refusals.

### I06 — Extension, breakup, spreading and ocean history

**Focused research decisions:** which selected separation route is admitted for
the actual loading/material history, what determines ridge motion, and can the
supported pressure/enthalpy path actually supply and accommodate liquid? Reopen
[breakup closure](I01_BREAKUP_CLOSURE.md),
[resolved separation](I01_SEPARATION_FEASIBILITY.md) and
[melt delivery](I01_MELT_ROUTE.md). Target
[Brune et al. (2014)](https://www.earthbyte.org/Resources/Pdf/Brune_etal_2014_Rift_migration.pdf)
for resolved rift geometry/basal sensitivity and
[ASPECT melt transport](https://aspect-documentation.readthedocs.io/en/latest/user/methods/melt-transport.html)
for phase/compaction flux conventions. Use the tracer-history reference in
section 9 for ocean ages; none of these is an automatic replacement closure.

**Ordered assignments:**

1. **I06.1 — Connect extension to an event-ready neck.** Join W05, I05 histories
   and shared geometry. Keep mechanical decoupling, physical material separation,
   exposed mantle and oceanic crust birth distinct. Use supplied-event controls
   while the I07 neck prerequisite is being built; label them as such.
2. **I06.2 — Admit separation and split conservatively.** Satisfy the chosen
   closure's whole-window validity, spatial/thermal/coupling and event-account
   requirements. Preserve irreversible bond history. Consume I07.1–I07.2's
   full-neck/free-surface/mixed-material/basal/exterior evidence where required;
   pointwise failure or a thickness cutoff is not a substitute. Split the actual
   material positions without turning separated continental material into basalt.
3. **I06.3 — Supply and form actual crust.** Join I05's compatible source/phase
   state to retained segregation/delivery/receiver and W06 birth accounts. Test
   finite supply, receiver accommodation, permitted outlets and heat removal.
   Exposed mantle remains exposed mantle if magmatic supply is insufficient.
4. **I06.4 — Evolve moving ridges and birth histories.** Adapt the retained
   prepared spreading/history operators to I03 segments, left/right full motion
   and finite birth-time intervals. Cover migration, asymmetric spreading,
   cessation and only admitted jumps/reassignments. Birth age follows trajectories,
   not distance to whichever ridge is nearest at the current time.
5. **I06.5 — Accept the connected rift-to-spreading route.** Preserve margins,
   thermal/material history and source/exterior accounts across the event and
   save/reopen continuation. Include constant/staged controls, shear-only no-birth,
   exhausted supply and an inactive ridge. Do not close I06 while its required
   I05 phase-front or I07 separation evidence is absent.

**Efficiency/exclusions:** batch changed segment intersections and share immutable
birth histories without collapsing age distributions. No post-hoc ocean filling,
assumed unlimited melt or relabelling a prescribed event as generated. Pull forward
I07's shared mechanics prerequisites as described below; the numbering is not a
requirement to finish all of I06 before those kernels can be built.

**Depends on:** I03–I05. Connect W05 extension to an explicitly selected breakup
criterion and W06 birth/spreading histories. Use the evolving shared ridge, left
and right motion and source supply. Continental thinning is not ocean-crust birth.
Track ridge migration, cessation and only explicitly supported jumps/reassignments.

**Finish when:** one coupled rift→spreading case carries the same material and
thermal history across the transition, actual young crust originates at the ridge,
ages follow spreading trajectories, and finite sources/exports close. Compare
constant and staged analytical controls, including asymmetric spreading and an
inactive ridge. Do not fill unknown old oceans using nearest-present-ridge distance.

### I07 — Convergence, collision, transform and regional mechanics

**Focused research decisions:** finish the selected general stress-history
integration and its energy/frame tests; define complete supported neck/initiation/
junction cases rather than another scalar proxy. Reopen
[elastic memory](I01_ELASTIC_MEMORY.md),
[Schrank et al. (2017)](https://doi.org/10.1093/gji/ggx297),
[initiation](I01_INITIATION_DECISION.md),
[separation](I01_SEPARATION_FEASIBILITY.md) and
[junction reorganisation](I01_JUNCTION_REORGANISATION.md). Consult the pinned
[ASPECT material conventions](https://aspect-documentation.readthedocs.io/en/v3.0.0/parameters/Material_20model.html)
alongside its actual implementation where the existing method records a discrepancy.
Use Gurnis, Hall and Lavier (2004), Li and Gurnis (2023) and the W08/FEniCS-SZ
references for their stated comparisons, not missing case values. Exact archive
reproduction is not mandatory when an independently justified test establishes
the required claim; full coupled physical-event acceptance is still mandatory.

**Ordered assignments:**

1. **I07.1 — Implement the shared general material kernel.** Extend the selected
   logarithmic-objective elastic formulation to noncoaxial deformation with
   retained creep/plastic rates, pressure conventions, raw history and physical
   weakening length. Define tensor/frame/energy ports once for necks, initiation
   and junctions. Keep fixed material modulus unless a changing-modulus energy
   law is separately admitted. Check rigid rotation, shear, unloading, frame
   covariance and independent stored-energy/dissipation accounts.
2. **I07.2 — Resolve evolving regions and the neck prerequisite.** Reuse compatible
   heterogeneous solvers/context seams, adding actual moving-material/free-surface
   transfers rather than treating stationary `evolving_mechanics.py` contexts as
   that implementation. Join I05 heat/composition/history and basal conditions;
   resolve the full mixed-material neck and required depth/exterior/along-strike
   sensitivities. Return admitted separation/handoff evidence to I06. These two
   kernel substeps need I02/I03/I05 interfaces, **not completed I06**.
3. **I07.3 — Implement the resolved initiation experiment.** Lock coefficients,
   geometry, thermal/history state, boundaries, observation window and numerical
   criteria. Compare forced and genuinely released continuations of the same
   accepted parent, replacing driving velocity with zero driving traction while
   preserving physical support. Check convergence/sinking, gravitational and
   elastic change, dissipation and external work, with required refinement/frame/
   exterior controls. A force zero-crossing or prescribed weak band is not proof.
4. **I07.4 — Join ocean entry, collision and full-vector deformation.** Consume
   actual I06 cohorts through heterogeneous W06-to-W07 and W08 boundary joins.
   Preserve age/heat/composition and all represented motion; integrate velocities
   into displacement. Reserve incoming stock once across global consumption and
   regional retirement. Check continental-arrival regime change, pure transform
   no-birth/no-blanket-uplift and oblique motion; retain unsupported-event refusals.
5. **I07.5 — Connect the multidirectional junction region.** Retain both horizontal
   directions, vertical structure, parent history and explicit parameter
   conversions. Use the shared separation/initiation/magma mechanisms; return
   work-conjugate reactions to I09 and material-derived interface proposals to
   I03, with I02 owning the joint commit. Check competing directions, symmetry,
   finite-source competition and the declared event/handoff window.

**Efficiency/exclusions:** reuse sparse structure, valid warm starts and prepared
operators under actual geometry/material/boundary identities. Keep diagnostics
bounded and measure a representative joined solve before increasing support.
No second constitutive implementation, new fluid science, steady-slab substitute
for evolving subduction, or unrestricted long campaign. I07.4's combined acceptance
waits for I06; I09 later verifies the full returned-feedback route.

**Depends on:** I03–I06 for the combined ocean-to-convergence chain. Close the
heterogeneous W06→W07 transfer and connect W08 to actual global boundary segments.
Reuse separate heterogeneous thermal/strength/surface solvers where compatible;
the constant-viscosity homogeneous demonstration is not the universal backend.

Build on the explicit contexts in [evolving_mechanics.py](../src/atlas_tectonics/evolving_mechanics.py):
current layer/parcel geometry and material amounts, heat and property reconstruction,
viscosity at centre/shear sites, forces on staggered faces, all velocity/traction
boundary components and a physical pressure reference. Moving surfaces also need
compatible material/heat/internal-variable remapping; a solver that accepts a
deformed mesh does not itself provide that transfer.

For [MC-05 junction reorganisation](I01_JUNCTION_REORGANISATION.md), provide a
shared multidirectional regional solve retaining both horizontal directions and
vertical structure. Preserve the actual parent's stress and material history;
use the declared 3D constitutive convention with explicit parameter conversion.
Return work-conjugate reactions through I09, rather than holding plate motion
immune to regional resistance. Use the shared MC-01/02/03 mechanisms, not a
second junction-fracture law. I03 extracts joint topology only from their
supported outputs; a prescribed multi-arm geometry is not physical birth evidence.

Implement the D6 regime transitions and footprint↔section transfers. Keep fault
and slab geometry/polarity explicitly supplied or calculated by a named law.
Pure transform, oblique deformation, oceanic consumption, underthrusting and
continental collision need distinct material/work outcomes. Integrate compatible
velocity histories into displacement; a sequence of Stokes snapshots alone does
not do so. Preserve W08 refusals on combined events until their coupling is defined.

Keep the steady slab/wedge benchmark separate from time-dependent subduction heat
and material history. The global sink and regional retirement operation must debit
one incoming stock, not each remove it independently. Supplied underthrust work
minus gravitational change is not automatically dissipated heat. Magmatic fluxes
remain geology-owned exchanges; simultaneous demands share finite source accounts.

**Finish when:** an ocean cohort produced by I06 enters a supported convergence
case without losing age/heat/mass; continental arrival changes the regime under
the specified law; pure shear creates no artificial crust; an oblique case retains
all represented motion. Include exact map controls plus one material/thermal/mechanical
coupling control, not another unrestricted long subduction campaign.

### I08 — One supported tectonic surface and external feedback boundary

**Focused research decisions:** identify the admitted core geometry/material
basis, vertical datum, regional exterior conditions and replacement mapping.
Decide whether the represented extent needs a spherical response or fits a
justified regional approximation. Reopen [elastic core](I01_ELASTIC_CORE.md),
[water/flexure](I01_WATER_FLEXURE.md), [water/GPE](I01_WATER_GPE.md) and
[Wickert (2016), gFlex](https://gmd.copernicus.org/articles/9/997/2016/)
for the actual variable-rigidity/boundary terms. Existing planar periodic checks
do not establish spherical support; the current declared homogeneous core does
not automatically define variable/multiple cores or yield an inferred elastic
thickness from temperature.

**Ordered assignments:**

1. **I08.1 — Bind accepted columns to one surface datum.** Join inventory, heat,
   density, compaction and loads to selected D5 support. Preserve the unloaded
   reference and distinguish total equilibrium response from its change; changing
   rigidity cannot reset the absolute reference.
2. **I08.2 — Implement the required spatial response.** Reuse compatible flexure
   machinery; implement the admitted variable-rigidity/map or spherical operator
   with its real boundaries, Poisson terms and exterior loading. Give coarse
   support and regional replacement disjoint contribution ownership. Admit the
   actual core geometry before using it; no tiled-profile global solution.
3. **I08.3 — Connect external feedback ports.** Exchange dated, spatially supported
   terrain/geology/water/sediment fields with units, datum and I02 once-only
   accounts. Make accepted removal/deposition/water loading affect the next
   tectonic state. Return identified elevation/bathymetry components; do not
   implement other modules' process laws or manufacture missing loads.
4. **I08.4 — Verify the joined surface.** Test changed loads, unchanged load with
   changed rigidity, datum shifts, water volume, coarse/regional replacement and
   exterior sensitivity. Check energy/work where claimed and absence of repeated
   thermal/compaction/flexure contributions. Use a small supplied external-feedback
   control, then actual upstream results for stage acceptance.

**Efficiency/exclusions:** cache prepared support operators only under matching
geometry/rigidity/boundary identities, reuse independent right-hand sides where
valid, and measure the complete coupled solve. No inferred sea level from land
fraction, unowned yielding/core extension or claim of finished eroded terrain.

**Depends on:** I05–I07. Connect physical inventory, temperature and loads to the
selected D5 response. Preserve the absolute reference when rigidity changes.
Where a world-scale plate response is required, implement its supported spatial
operator; independent 1D flexure strips cannot be called a global plate solution.

Return a tectonic elevation/bathymetry baseline in one explicit datum, including
its load/thermal/structural components. Sea level or water inventory is a supplied
rule/input, not inferred from continental fraction. Define terrain/geology/water/
sediment input and output ports with interval, footprint, units, component ownership
and exactly-once accounts. No full downstream simulator is required for the control.

**Finish when:** changed load and unchanged-load/changing-rigidity cases respond
correctly; no compaction/thermal/flexural contribution is counted twice; a small
external removal/deposition/water-load control affects the next tectonic state.
The output is not advertised as eroded, hydrologically realistic finished terrain.

### I09 — Close global↔regional feedback and process scheduling

**Focused research decisions:** choose conservative replacement/return operators,
the coupling iteration and residual definitions, region activation/overlap rules
and a bounded meaningful case. Start with I03/I04/I05/I07/I08 interfaces and the
selected force/GPE/heat/account contracts. Use the section-9 force-consistency
and conservative-transfer references for named questions, not another general
mantle literature survey. Decide which feedback requires iteration and which
split is justified by an error bound before implementing the controller.

**Ordered assignments:**

1. **I09.1 — Define planetary multiresolution ownership.** Join the coarse closed
   sphere and detailed regions at one frame/time, with distinct process/exchange/
   display supports. Implement conservative restriction/prolongation, activation/
   retirement and coarse-contribution replacement. Merge or explicitly couple
   interacting footprints; preserve exterior state and histories when refining.
2. **I09.2 — Close force, torque, work and finite accounts.** Connect I04 driving,
   I07 reactions and I08 loads/GPE. Transfer velocity/traction on the same oriented
   support so internal work cancels. Remove replaced reduced resistance and
   duplicate ridge/slab/bending forces. Centrally reserve shared sources; workers
   return proposals, not independent debits to one reservoir.
3. **I09.3 — Implement accepted-interval feedback.** Evaluate from an immutable
   parent, exchange results, update geometry/forces/strength/loads, resolve events
   and correct the endpoint. Apply predeclared residual/iteration/error limits;
   refuse a nonconverged interval without ageing rock or spending accounts.
   Individually successful component solves do not authorise a world commit.
4. **I09.4 — Preserve continuation and bounded execution.** Use I02 transactions,
   checkpoints and existing resource control. Preserve stress/contact/plastic
   memory, event state and external exchanges across interruption and replay.
   Parallelise independent regions under one budget; keep physical-time and
   shared-state publication ordered. Verify changed dependencies invalidate reuse.
5. **I09.5 — Climb the smallest useful validation ladder.** Check exact exchange/
   work controls, one joined region, then a short coarse-sphere scenario with
   supported detail and an actual regime transition. Compare direct components,
   assembled execution and interrupted/resumed results, plus feedback and spatial/
   time transfer error. Prepare the missing I11 H/K coverage and cost forecast;
   do not silently launch their larger withheld/global acceptance campaigns.

**Efficiency/exclusions:** forecast active supports, nonzeros, iteration counts,
cohorts and checkpoint growth; use measured cost estimates before deciding on
parallel execution. Reuse valid preparations, not stale physics. Keep the 256
accepted-step ceiling and all support/error guards; no whole-planet runtime
promise based on a tiny regional solve or silent scientific downgrade on timeout.

**Depends on:** I04–I08. Run compatible process branches from the same parent time,
exchange their results, correct coupled inputs, resolve events, then commit.
This is not a serial call to every W-package or parallel mutation of one world.
Use an explicit coarse/regional replacement rule; detect overlap and conserve
transferred inventories. Refresh forces/strength/loads before the next interval.

Split at physical events and limit motion/coupling error. Rejected steps must not
age rock, consume reservoirs or publish a partial world. Require a converged
coupled result or demonstrated split-error accuracy, not only local solver success.
Checkpoint the actual continuation state, including memory and external exchanges.

**Finish when:** one short connected scenario crosses an actual regime transition,
changes properties/forcing through feedback and survives interruption before and
after commit. Direct component reference, assembled run and resumed run agree
within their predeclared numerical requirements. General untested events remain
refusals; ordinary required scenarios must not succeed only by disabling them.

### I10 — Connect W12, New World, saved projects, UI and consumers

**Focused research decisions:** what must a project retain to inspect an old
result versus continue its native calculation, and which changed dependencies
invalidate which descendants? Start with the existing W12 and New World
project/job/bundle contracts, not a new application framework. Consult SQLite
transaction/backup semantics only for unresolved persistence joins. The existing
[desktop](../../desktop/README.md) uses Electron with a Python payload; retain
that route and its isolation rather than assuming an unrelated packager is in use.

**Ordered assignments:**

1. **I10.1 — Register the evolved-world producer.** Bind I09's actual accepted
   state to a new W12/graph producer and typed ports. Test physical-input and
   source changes invalidate the correct descendants; unchanged requests reuse
   results. Preserve legacy producer identities and reject fixture substitution.
2. **I10.2 — Complete the project lifecycle.** Join create/advance/status/cancel
   to existing jobs and portable projects. Save all required native continuation
   dependencies; support inspection-only states explicitly when continuation is
   incompatible. Check failure preserves the user's current project and last
   accepted progress. No UI-side reconstruction of physical state.
3. **I10.3 — Produce data-derived inspection and exports.** Return indexed sphere,
   sections, quantities, masks, units, time and method/source identities from the
   same saved result. Use lazy selected-field reads and display-only levels of
   detail; test that export, map and section values agree without a new solve.
4. **I10.4 — Hand a stable contract to the UI owner.** Supply real small saved
   examples, valid/refused/partial responses and New/Save/Load/cancel semantics.
   The UI owner implements controls and presentation separately; Codex checks
   the shared native route, not just mock responses. Do not run two writers on
   the UI or scientific files. A return must include actual UI/backend evidence.
5. **I10.5 — Connect one actual downstream reader.** Feed an existing compatible
   geology or terrain consumer the evolved fields through typed ports; prove
   reference/time/support preservation and mismatch refusal. This is a tectonic
   handoff, not a new geology/erosion generator. Execute the full user lifecycle
   below and record read/reopen/invalidation costs without rerunning physics for
   view changes. No whole-I10 completion before the real UI/consumer joins pass.

**Depends on:** I02 interface contracts and I09 for full scientific delivery.
Reuse [assembly.py](../src/atlas_tectonics/assembly.py),
[workflow_ports.py](../src/atlas_tectonics/workflow_ports.py),
[w12_graph.py](../tools/w12_graph.py), New World session/project/job/bundle tools
and the native readers. Register a new versioned physical producer; do not silently
retarget an old R31 operation or insert a fixed W12 fixture as the generated world.

Backend API must expose create/advance/status/cancel/save/load/inspect/export with
one scientific state identity. Distinguish initial, in-progress, complete, refused
and incompatible-continuation states. Preserve the current project on failure;
make old saves inspectable where supported without silently converting history.
Cache and resume must authenticate all relevant dependencies, including current
geometry and property state. A cosmetic UI change cannot alter generation.

The UI owner receives the stable API/field contract, representative actual saved
results, progress/cancellation/error semantics and New/Save/Load requirements.
It renders the backend's geometry/values, shows source/method/units/time and supports
the existing "how this is made" explanation. Backend owns science and data-derived
views; UI owns controls/presentation. No UI handoff is sent by this planning turn.

**Finish when:** the same generated world survives CLI→UI→save→load→continue→export,
one dependent consumer receives the actual evolved arrays, and unchanged reruns
reuse work while changed physics invalidates the correct descendants. Validate
the real native route; fake API tests alone do not establish this.

### I11 — End-to-end realism, portability and resource acceptance

**Focused research decisions:** which independent observations/reference problems
challenge each claimed process, what spatial/time supports make comparisons
meaningful, and which numerical uncertainty can be separated from model error?
Reuse [W10's method-level validation](W10_VALIDATION.md), B1's matched-sampling
boundary diagnostics and the exact process references already selected. Compare
applicable ocean-age/depth/heat-flow observations and published deformation
controls, not visual attractiveness alone. Reopen original equations/benchmark
definitions only for missing coverage. A fitted Earth distribution is not a
universal constraint on generated planets.

**Ordered assignments:**

1. **I11.1 — Freeze the smallest complete acceptance set.** Map section 7 cases
   A–K to current, source-compatible evidence and genuinely missing checks. Fix
   development/withheld seeds, scenario, physical horizon, tolerances, outputs and
   resource budget before execution. Independently justify new thresholds. Do
   not fill a missing generated-event case with a prescribed-event demonstration.
2. **I11.2 — Run causal and joined physical checks.** Reuse unchanged controls;
   execute missing cross-stage cases and inspect conserved quantities, physical
   sensitivity and mesh/time/coupling errors. Compare actual saved numeric fields
   and data-derived views at matched physical scales. Diagnose jagged boundaries,
   continental templates and inconsistent ocean ages at their generating causes;
   keep all attempted seeds/refusals, including failed withheld cases.
3. **I11.3 — Prove lifecycle and native platforms.** Exercise real Windows and
   Linux create/save/reopen/continue, cancellation, source mismatch, privacy-safe
   export, UI agreement and consumer use. Distinguish platform-specific runtime
   continuation from portable inspection; metadata or synthetic path checks are
   not native portability evidence. Reuse valid environment results and obtain
   missing platform evidence without an unapproved installation.
4. **I11.4 — Close the planetary resource claim.** Forecast case K using measured
   supports/cohort/event growth, then request any still-needed run authority.
   Compare cold, warm, incremental and resumed complete paths, including I/O and
   meaningful evolving full-sphere/multiple-region work. Report seconds, peak
   memory, persisted bytes and measured raw/percentage changes, including
   regressions. Correct evidenced bottlenecks with matched quality; no automatic
   realism downgrade, bigger ceilings or multi-hour R4.4 substitute. Finish only
   when the required physical, lifecycle and practical gates below all pass.

**Whole-planet requirement (owner reaffirmed 28 September 2026):** completion
must include an evolving full sphere, not merely a global initial layout plus
isolated small-region runs. I03 owns global geometry and material/history
coverage; I04 owns global motion; I07 supplies detailed active-region mechanics;
I09 returns regional forces and reconciles all exchanges at a common accepted
time. Use a declared multiresolution allocation of effort, not a uniformly
junction-resolution planetary mesh. Regional sizes/resolutions follow physical
influence and finite resources, not the existing demonstration's small footprint.
Case K must exercise that complete connection, including multiple interacting
regions and preservation of material/heat/history outside them. Tiny regional
checks and a renderer showing a globe cannot satisfy this requirement. Record
whole-run elapsed time, peak memory and storage before claiming consumer-scale
planetary usability; no planetary run is authorised by this requirement alone.

**Depends on:** I04–I10; tests/measurements develop alongside earlier increments.
Run the compact matrix in section 7, including actual sphere-wide output and
numerical/visual inspection. Fix generating causes when it fails; never redraw
the result to pass. Register fresh evidence only for the exact tested sources,
inputs, configuration and runtime. Preserve unrelated historical receipts.

Measure complete cold/warm/incremental/resumed paths, not just a cheap solver
kernel. Exercise native save/restore on Windows and Linux before claiming both;
environment metadata and a skipped OS test do not prove portability. Coordinate
with, and reuse valid results from, the separate environment work rather than
reinstalling or rerunning it merely for reassurance.

**Finish when:** required cases pass the predeclared physical/numerical/representation
and practical runtime criteria, every required field comes from the accepted
evolved state, the actual UI view is consistent, and remaining exclusions are
genuinely outside the scope in section 2. No nine-hour R4.4 run is implied.

### I12 — Release the integrated tectonics module

**Focused research decisions:** what scientific/runtime data must ship for the
five user routes, what can an older project safely inspect/continue, and what
operating-system support has actually been demonstrated? Reuse the tested build,
environment pins and existing notices. Consult official
[Electron packaging](https://www.electronjs.org/docs/latest/tutorial/application-distribution)
and [security](https://www.electronjs.org/docs/latest/tutorial/security) guidance
for the existing desktop wrapper's final process/file-access boundary. These
references support release engineering, not tectonics realism.

**Ordered assignments:**

1. **I12.1 — Freeze the supported release contract.** Reconcile capabilities,
   mandatory evidence, known exclusions, input requirements, source/runtime and
   downstream versions. Update the existing how-it-works guide and a short actual
   user example in dependency order. Distinguish supplied history from generated
   evolution and component support from whole-route acceptance. No new status ledger.
2. **I12.2 — Assemble and test the native distribution.** Use
   [desktop/build.py](../../desktop/build.py), its manifest and existing runtime
   tests to package the reviewed sources and dependencies into a new destination.
   Keep the Windows executable with its required resources; do not promise a
   single-file executable. Exercise an isolated profile and the real user routes
   without the development checkout, preserving projects, cancellation and
   native identity checks. Include only authorised examples and required notices,
   not private data, caches or coordination files. No installer/download implied.
3. **I12.3 — Deliver the accepted module and handoff.** Confirm all five user
   routes and the declared platform matrix against the release bytes, supply
   the example, method/evidence links and typed consumer contract, and identify
   exactly what other modules may rely on. Record package size/startup/read costs
   without rerunning unchanged scientific campaigns. Git publication, signing,
   distribution outside the approved destination and Diadem canon acceptance
   remain separately authorised actions, not automatic effects of this checklist.

**Depends on:** I11. Update capability/status documentation, the reader guide,
source-bound examples, current evidence and downstream contract versions. Mark
old initial-world and stationary-column demonstrations accurately, preserving
their provenance. Record installed versus actually tested platform paths.

**Finish when:** all five user routes in section 1 work; the mandatory scientific
and engineering cases are accepted; the three observed generation defects are
resolved at their causes; no hidden manual arrays or unsupported bridges are
needed; and a user can operate tectonics without completing the other 17 modules.
Technical release, Git publication and Diadem canon remain separate actions.

### Dependencies and sensible parallel work

The execution order is not a strict I01, I02, ..., I12 loop. Use these dependency
milestones to avoid circular waits and premature stage-complete claims:

| Milestone | Dependency-ready work | What still cannot be claimed |
| --- | --- | --- |
| Shared foundation | Retain I01; complete I02's real lifecycle, then I03's shared geometry/maps | An evolving planet or physically generated event |
| Driving/state pair | Agree I04/I05 ports; implement initial/driving producers alongside conservative material/thermal properties, then their first feedback control | Full regional feedback merely because both producers run |
| Shared mechanics prerequisite | I07.1–I07.2 use available I02/I03/I05 contracts before complete I06; return the actual neck/separation evidence to I06.2 | I07 ocean-to-collision acceptance from a material kernel or neck alone |
| Compatible supply and breakup | I05.4 supplies supported phase/energy transport; I06 joins that and the mechanical prerequisite to real separation/birth/history | Generated oceanic crust from prescribed splitting or missing phase-front support |
| Joined regimes and support | I06 cohorts feed I07.4; shared mechanisms support I07.3/I07.5; I08 joins the resulting columns/loads | Full initiation/junction acceptance from contact or scalar feasibility tests |
| Full feedback and delivery | I09 closes all returned reactions/accounts; I10 exposes the actual evolving world; I11 accepts it; I12 packages the accepted release | End-to-end acceptance from component, mock API or packaging checks |

I04 and I05's feedback is physical, not a reason to require each completed stage
before the other can start. Likewise, I07's reusable mechanical kernels are
prerequisites for I06 breakup; the **combined** I07 acceptance subsequently needs
I06 ocean cohorts. Keep these assignments in their owning stages and return their
results; do not create a second constitutive model or call either stage complete
early. I07.3's initiation case can be developed when its own kernel/state inputs
are ready; it need not wait for unrelated mature-ocean output.

I08 datum/port contracts and I10 API/storage preparation can proceed after the
relevant I01/I02 interfaces stabilise. Their final acceptance still needs real
upstream results. Independent method/reference work can be delegated concurrently;
shared-file edits and accepted-time history cannot. Each assignment has one writer,
an exact source scope and a named receiving review. No completed-step dependency
alone grants authority beyond the currently approved I02 sequence.

## 7. Acceptance matrix — prove the complete promised route

Use existing valid component evidence plus focused tests at changed seams. Start
small, retain successful bound results, and escalate only for a changed input,
failure or missing required coverage. Do not rerun every W-suite for every edit.

| Case | What must be established |
| --- | --- |
| A: no motion / rigid spherical rotation | No invented deformation, heat, relief, material or age reset; frame and orientation invariance |
| B: physically driven deformation/localisation | Expected response to changed strength/forcing and physical-length refinement; not fixed final geometry with different metadata |
| C: rift → spreading → mature ocean | Compatible transition, finite creation/heat supply, independent trajectory ages and cooling/support response |
| D: ocean → subduction → continental arrival | Same cohorts/thermal histories cross the interface; explicit polarity, sinks/accretion and collision transition |
| E: transform and oblique motion | Full vector retained; pure shear does not imply blanket uplift or new material |
| F: loads, evolving properties and external feedback | Once-owned thermal/compaction/flexure, fixed absolute reference, accepted external exchange affects the next step |
| G: topology events and regional exchange | Shared junction/plate network stays closed; births, splits, mergers and retirements conserve the represented accounts; no overlap/gap repair hiding loss |
| H: generation robustness and morphology | A fixed, predeclared development/withheld seed and parameter matrix; actual boundary/continent/ocean-age outputs at matched physical scales, never cherry-picked successful worlds |
| J: integrated lifecycle | Fresh create, save/load, cancellation at commit boundaries, resume, changed-source/input refusal, correct cache reuse/invalidation, consumer and UI agreement |
| K: bounded global acceptance | A coarse full sphere evolved for a declared physically meaningful interval, containing multiple active regimes and supported local detail, within the agreed resource envelope |

Before executing H/K, record exact seeds, physical scenario, interval, outputs,
resolutions, tolerances and budget in the existing case/evidence machinery. Start
with the smallest set covering distinct required regimes and then add only missing
coverage. A short test that cannot form or change the relevant features cannot
prove their realism, regardless of its step count. Record all attempted cases and
refusals; no automatic retry-until-attractive generator.

Assessment layers are separate:

- **Numerical:** conservation, equation/constraint residuals, common endpoint,
  mesh/time/projection sensitivity and independent analytical/reference controls.
- **Physical:** selected laws appropriate to their regime; age/depth/heat-flow and
  deformation relationships challenged by applicable independent evidence, not
  merely against another implementation of the same equations.
- **Morphological:** existing B1 matched-scale bend/motion/flip/shear measures,
  correct reference split, multiple seeds and actual data-derived views. PB2002
  is a comparison, not a target distribution or a shortest-boundary objective.
- **User workflow:** complete automatic construction and reliable continuation,
  no manual intermediate arrays, and no display geometry different from physics.
- **Practical:** declared hardware, full elapsed time, peak memory, storage growth,
  cancellation latency and consumer-usable results. Passing tiny controls alone
  cannot establish planet-scale usability.

Existing tolerances and holds remain. New criteria must be physically/numerically
justified **before** the acceptance run, not fitted afterwards. If the original
model lacks a usable independent criterion, that is a design deliverable in I01,
not permission to call a successful execution realistic.

A claim that depends on a held or failed scientific case must expose that
dependency. Reusing its solver does not erase the hold. Either demonstrate a
genuinely different bounded validity claim or obtain authority to address the
held case; do not bypass it through the new assembly.

## 8. Performance and growth are part of implementation

No token-usage instrumentation. Measure elapsed seconds, peak RAM and persisted
bytes when they answer an actual implementation/scale question. For comparisons,
keep physics, input, resolution, error requirements and output scope matched;
report baseline, candidate, raw difference and percentage, including regressions.

- Reuse prepared geometry, transfer maps and matrix work only while their actual
  dependencies are unchanged. New geometry, rheology, boundary conditions or time
  history must invalidate the affected cache entries.
- Keep current state bounded; store immutable shared cohorts/events and requested
  checkpoints using the existing lossless store. Avoid copying every full world
  at every numerical substep or growing all historical matrix factors in RAM.
- Use lazy requested-field loading and data-derived display levels without
  changing the scientific state. Coarse display is not coarse science.
- Parallelise independent plate/region operations only when the chosen equations
  permit it, with a shared resource budget and controlled native thread counts.
  Coupled global solves need their own appropriate solver; do not independently
  tile globally coupled flexure or mutate shared reservoirs from workers.
- Reuse existing scheduling estimates, including the user's approximate two-minute
  parallelism preference where applicable; predict cost before expensive work,
  and do not run the full job serially merely to decide whether to parallelise it.
- Put detail where physics requires it and validate transfer/refinement. Any
  reduced scientific mode is a named model choice, never an automatic downgrade
  after timeout. Later consumer realism settings must disclose changed assumptions,
  not just use a visually smoother rendering.

For each new expensive kernel, one representative cold/warm measurement after
correctness is sufficient initially. Before H/K, forecast work and storage from
the measured support/event/cohort growth and state the uncertainty; use a finite
time/memory/output limit. The current interactive initialisation limit is not a
measured promise for evolved-world generation. Do not launch multi-hour simulations
to discover an already predictable budget failure.

No credible total implementation-time or planetary-runtime estimate exists yet:
D1/D2 and spherical exchanges are the largest uncertainties. Measure their bounded
prototypes first and update the existing plan; do not present a small reference
timing as a whole-generator forecast.

## 9. Research and software basis

References inform different parts of the design; none certifies the whole hybrid.
No external library was installed or adopted while writing this plan.

| Reference and inspection scope | Use and limit |
| --- | --- |
| [pyGPlates reconstruction/deformation example](https://www.gplates.org/docs/pygplates/sample-code/pygplates_reconstruct_crustal_thickness_and_tectonic_subsidence) and [API reference](https://www.gplates.org/docs/pygplates/pygplates_reference), documented interfaces | Separate supplied rotations/topologies from material reconstruction. Reconstruction is not physical prediction of the initial network |
| [Karlsen et al., tracer-based seafloor ages](https://arxiv.org/html/1910.03351v1), methods and limitations reviewed during the diagnosis | Explicit birth, transport and destruction generate age from a declared history. Atlas still needs conservative quantities and its own geometric/numerical treatment |
| [ASPECT continental extension](https://aspect-documentation.readthedocs.io/en/latest/user/cookbooks/cookbooks/continental_extension/doc/continental_extension.html), documented setup/weakening/limits reviewed during the diagnosis | Mechanically driven localisation under supplied forcing; not a ready-made globe or complete-breakup solution |
| [Clennett et al. (2023)](https://gfzpublic.gfz.de/pubman/faces/ViewItemOverviewPage.jsp?itemId=item_5023127), institutional abstract and indexed publisher discussion inspected | Candidate force/torque consistency challenge. A residual can expose missing forces as well as bad kinematics; minimising it alone does not prove realistic motion. Full methods remain required before adopting a force law |
| [Wickert (2016), gFlex](https://gmd.copernicus.org/articles/9/997/2016/), published method scope checked | Distinguish profile and map-view response, physical boundary conditions and load ownership. Does not make Atlas's existing 1D support a spherical solver |
| [Existing method-by-method guide](HOW_TECTONICS_IS_MADE.md) and its linked primary research | Preserve the exact W01–W08 constitutive, thermal, transport and benchmark basis; reopen applicable equations before extending a model's validity |
| [ESMF conservative regridding](https://earthsystemmodeling.org/regrid/) and [Kritsikis et al. (2017)](https://gmd.copernicus.org/articles/10/425/2017/), targeted I03 reading | Decide actual spherical overlap/measure/weight treatment; conservation of one field integral is not automatic preservation of constitutive histories or topology |
| SQLite [transactions](https://www.sqlite.org/lang_transaction.html), [atomic commit](https://www.sqlite.org/atomiccommit.html) and [WAL](https://www.sqlite.org/wal.html), official persistence references | I02/I10 must bind physical state and accepted-head/accounts to the actual native transaction and journal mode; references do not prove Atlas's full restart path |
| [Electron security](https://www.electronjs.org/docs/latest/tutorial/security) and [packaging](https://www.electronjs.org/docs/latest/tutorial/application-distribution), official desktop references | I10/I12 retain the actual local Electron/Python wrapper and review its process/file boundary; packaging and security are distinct from scientific acceptance |

The focused 28 September briefs additionally point to the owning I01 documents
for the selected logarithmic-objective stress law, Gurnis initiation comparisons,
phase/provider transport and breakup/junction conditions, plus Brune's rift case,
FiPy and ASPECT where their specific conventions need comparison. These are
future targeted implementation readings unless an existing method record states
what was actually consulted. This planning pass checked selected reference
identity/scope and official documentation; it did not reproduce the papers,
benchmark reference software or adopt a library. Full relevant methods must be
read before implementing a new scientific extension.

Procedural Tectonic Planets remains a separately labelled authoring/performance
reference from the prior diagnosis (abstract-level review), not scientific
validation of the proposed force/localisation closures. Do not silently replace
those closures with a graphics recipe.

## 10. Completion and next action

Integration is complete only at **I12**, when the section-1 outcome and required
matrix are met. A new shared-state class, connected graph, green unit suite,
regional demo, export table or visually attractive world is not a substitute.

**I01 is complete as a model-choice, contract and bounded-feasibility stage.**
Claude's active assignment is I02.1's shared initial-state contract; do not edit
that in-flight brief or append another assignment to it. Codex reviews the return
and continues the authorised eight-step I02 sequence using these bounded briefs.
I03–I12 are planned, not newly started or authorised by this document. Preserve
the physical-event gates assigned to their later implementation stages. Do not
repeat completed reading or bounded controls without changed inputs, a failure
or missing required coverage.

Plan-only verification: local source/interface inspection, documentation links,
mandatory repository safety/path checks. No physical run, performance gain,
scientific acceptance or completion of any I-increment is claimed by this file.
