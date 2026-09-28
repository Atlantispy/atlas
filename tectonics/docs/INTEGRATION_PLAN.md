# Complete tectonics integration plan

26 September 2026. **WORKING NON-CANON — plan, not implemented capability.**

This is the forward integration scope for finishing the tectonics generator.
It replaces the narrower interpretation of W12 completion and the provisional
B2 implementation order. [W12_ASSEMBLY.md](W12_ASSEMBLY.md) remains the record of
what actually exists. [CURRENT_STATE.md](../../docs/CURRENT_STATE.md) remains the
single progress summary; do not maintain another competing status ledger here.

This plan was originally delivered as planning/documentation only. The owner has
since authorised I01 research, specifications and bounded feasibility controls;
see [its physical contract](I01_PHYSICAL_CONTRACT.md) and the single current-state
record. That continuation does not authorise I02–I12 production work, installation,
reopening R4.4, a full-world run, commit or push.

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

### I01 — Freeze the end-to-end contract and physical closure choices

The reviewed [closure matrix](I01_CLOSURE_MATRIX.md) and its
[machine-readable mirror](../cases/i01_closure_matrix_v1.json) map the promised
routes to producers, evidence and remaining decisions in generation order.
They distinguish missing I01 physics from later implementation; the matrix is
not a completed generator or an accepted separation law.

MC-06 now has a [conditional lateral-conduction criterion](I01_LATERAL_HEAT.md)
and a [bounded control](../evidence/i01-lateral-heat-r1.json). It selects the
thermal error rule, while valid contact geometry, whole-window bounds and
coupled feedback remain I05/I06 implementation/admission work. MC-04 now has a
[reviewed basal specification and accounts](I01_BASAL_CLOSURE.md), with
[eight bounded controls](../evidence/i01-basal-closure-r1.json), including an
independent exact mechanical-work solution. Actual transport, source-state to
prescription binding and resolved-depth sensitivity remain I05/I07 work.
Four physical-choice items remain open: MC-01, MC-02, MC-03 and MC-05.
MC-02 now has a [resolved-initiation method and prospective test specification](I01_INITIATION_DECISION.md),
including retained stress, prescribed pore pressure, physical-length weakening
and a genuine force-release check. Benchmark inputs and comparison allowances
still need completion before I07 implementation; the current authored-R control
is not a generated-initiation result. MC-07's
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
that chain. Its implementation and physical controls remain open, not another
request to rerun the completed contact/ridge helpers.
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
These controls are not generated boundary/rupture acceptance. D2/D6 physical
closure remains open; consult current state for the remaining dependencies,
not an assumed I02 start. Original I01 source-bound files and receipts are unchanged.

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

### I02 — Common state, exchange transactions and accepted-time controller

**Depends on:** I01 contracts; independent of the final complexity of a solver.
**Reuse:** native stores, execution identity, [material histories](../src/atlas_tectonics/materials.py),
[dated histories](../src/atlas_tectonics/tectonic_history.py) and W12 publication.
Add the contract from section 4, an event calendar and candidate→validate→commit
sequence. Keep speculative updates separate from accepted state. A failed or
cancelled interval changes neither committed state nor source/sink totals.

**Finish when:** a zero-motion synthetic state round-trips, one transfer is debited
and credited once, incompatible time/frame/units refuse, a failed multi-component
update rolls back, and resume matches uninterrupted execution. This is plumbing
acceptance, not a realism milestone.

### I03 — Evolving sphere, conservative history and spatial bridges

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

```text
I01 → I02 → I03 → {I04 driving/events ↔ I05 state/property updates}
                         → I06 → I07 → I08 → I09 → I10 → I11 → I12
```

I04 and I05 must be developed against the same interface and iterated together;
their dependency cycle is physical, not a build-system cycle. I08's ownership/
datum contracts and I10's API/storage work can be prepared once I01–I02 contracts
exist. Their scientific completion still depends on real upstream results.
Independent method controls can run in parallel; the committed time history cannot.
Do not delegate shared-file edits concurrently. Claude's currently assigned
environment work stays separate unless the owner explicitly changes that scope.

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

Procedural Tectonic Planets remains a separately labelled authoring/performance
reference from the prior diagnosis (abstract-level review), not scientific
validation of the proposed force/localisation closures. Do not silently replace
those closures with a graphics recipe.

## 10. Completion and next action

Integration is complete only at **I12**, when the section-1 outcome and required
matrix are met. A new shared-state class, connected graph, green unit suite,
regional demo, export table or visually attractive world is not a substitute.

Continue **I01** from its physical-contract/control checkpoint, resolving the
remaining generated-boundary/rupture decisions before building another purported
complete assembly. I02 can then establish the first reusable state/transaction
slice. Do not repeat completed reading or bounded controls without changed inputs,
a failure or missing required coverage.

Plan-only verification: local source/interface inspection, documentation links,
mandatory repository safety/path checks. No physical run, performance gain,
scientific acceptance or completion of any I-increment is claimed by this file.
