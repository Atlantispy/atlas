# I01 closure matrix: promised routes, owners and remaining decisions

**27 September 2026. WORKING NON-CANON. Route and acceptance matrix only: not a
status ledger, configuration, evidence run or scientific acceptance.** This is the
compact matrix that the [integration plan](INTEGRATION_PLAN.md#i01--freeze-the-end-to-end-contract-and-physical-closure-choices)
asks I01 to bind to the promised user routes. It separates the physical choices I01
still owns from work already assigned to I02–I12. [Current state](../../docs/CURRENT_STATE.md)
remains the single progress record. The [physical contract](I01_PHYSICAL_CONTRACT.md)
and the linked method documents remain the equations of record. The machine-readable
mirror is [i01_closure_matrix_v1.json](../cases/i01_closure_matrix_v1.json).

## 1. How to read it

- **Routes.** G is generated (`coupled_generated_candidate_v1`). P is prescribed or
  reference (`prescribed_history_v1`). X is an explicit required input. P and X never
  satisfy a promised G route.
- **Evidence.** Names are records in the [evidence register](../evidence/current-evidence.json);
  each receipt is `tectonics/evidence/<name>.json`. *Current* describes source
  freshness: the recorded bytes and declared bindings still match. Every cited I01
  receipt is a bounded control: it records `scientific_acceptance` false or a
  `PASS_BOUNDED_..._ONLY` status. The B1 and New World receipts are descriptive or
  historical. None is generated-world acceptance. The JSON mirror carries the
  register's digests.
- **Remaining items** (section 5) have four classes: **MC** missing I01 choice or
  bounded feasibility; **LS** selected, later-stage implementation; **IN** explicit
  input or calibration; **UR** unsupported route or refusal.
- **Two distinct closure levels.** The plan's I01 finish rule accepts a specified
  method plus bounded feasibility (or an explicit supported-regime restriction).
  Original full-event `closes_when` requirements below remain physical acceptance
  gates for their named implementation owners. The newly recorded I01 choices do
  not claim those later gates have passed. Incomplete source archives need not
  block analytical verification of independently declared equations.
- **No completion arithmetic.** Closing every MC item would not generate a planet or
  finish I01 by itself. The plan's I01 finish rule and review still apply; world
  acceptance is plan cases A–K in I11. Treat wording that infers full-generator or
  physical-event acceptance from I01 selection/feasibility as stale. I01 completion
  itself is decided by the plan's finish rule and the integrating owner's review.
  The same applies to wording that presents a ladder extrapolation as a separation
  certificate or proven handoff bound, crustal disconnection as plate separation, or a
  supplied magma input as the melt-derived generated route.

## 2. Promised routes

| Route | Rows | Required beyond I01 (owner; plan case) |
| --- | --- | --- |
| Generate | CM-01 to CM-15 | Causal D1/D2 response and actual D6 transitions on a closed evolving sphere; withheld seeds (I04–I09; A–H, K) |
| Inspect | CM-09, CM-15, CM-16 | Actual saved fields with units, time and datum; no display-only geometry (I10; J) |
| Continue | CM-02, CM-05, CM-16 | Full material, thermal and mechanical memory; interrupted commit and resume parity (I02, I09, I10; J) |
| Change deliberately | CM-16 | Dependency invalidation and an explicit successor; display changes reuse state (I10; J) |
| Consume | CM-15, CM-16 | Same endpoint, frame and support; conserved transfers; an actual downstream consumer (I08, I10; F, J) |

## 3. The matrix, in generation order

| Row | Step | D | Generated route now | Build owner | I01 choice / remaining boundary |
| --- | --- | --- | --- | --- | --- |
| CM-01 | Initial-state controls, not final targets | all | Selected | I04 | — |
| CM-02 | Inherited history | D2–D4 | Selected; inputs | I04, I05 | — |
| CM-03 | Plate and continent network | D2, D6 | Initial: X/P. Later: only through CM-06, CM-07, CM-11, CM-14 | I04 | MC-01/02/05 choices have bounded evidence; generated network acceptance remains |
| CM-04 | Motion | D1 | Selected; bounded evidence | I04, I09 | MC-07 |
| CM-05 | Material and thermal transport, properties | D2–D4 | Selected; bounded evidence | I03, I05 | MC-04; MC-06 criterion selected, coupled application remains I05 |
| CM-06 | Rift deformation, weakening, decoupling | D2, D6 | Selected; bounded evidence | I05, I07, I09 | — |
| CM-07 | Material separation (breakup) | D2, D6 | Creep regime: analytical feasibility. Cohesion-loss route: selected with resolved-strip feasibility; full event acceptance remains open | I05, I06, I07 | MC-01/04/06 selected; physical application remains I05/I06/I07 |
| CM-08 | Melt supply and ocean-crust birth | D3, D4, D6 | Provider/flow/thermal route selected; bounded segregation mechanics passes. Melt-derived crust acceptance remains later work | I05, I06 | MC-03/04 selected; source-to-crust and phase-front integration remain |
| CM-09 | Spreading, ridges and ocean ages | D3 | Selected; bounded evidence | I03, I06 | — |
| CM-10 | Trench consumption and slab inventory | D3, D6 | Selected; bounded evidence | I03, I07 | — |
| CM-11 | Subduction initiation | D2, D6 | Method selected; analytical prerequisites verified. Full event generation blocked pending I07 | I07 | MC-02 selection complete; physical acceptance remains |
| CM-12 | Continental arrival and collision | D6 | Selected; bounded evidence | I07 | — |
| CM-13 | Transform and oblique motion | D6 | Selected; bounded evidence | I07 | — |
| CM-14 | Topology events and junctions | D6 | Resolved-patch route selected; multidirectional coupled mechanics verified. Physical mechanism/event integration remains open | I02, I03, I07, I09 | MC-05 selection complete; physical acceptance remains |
| CM-15 | Support, datum, water and flexure | D5 | Selected; bounded evidence | I08 | MC-07 |
| CM-16 | Save, continue, inspect, change, consume | contract §2 | Selected contract | I02, I10 | — |

## 4. Row details

Feedback ownership and exchange rules not repeated here are in
[contract §2](I01_PHYSICAL_CONTRACT.md#2-product-and-feedback-ownership) and
[plan §4](INTEGRATION_PLAN.md#4-architecture-one-evolving-physical-state).

**CM-01 Initial-state controls, not final targets.**
- *Routes:* X: seed, planet radius, initial plate count, initial continental fraction,
  history start and requested endpoint describe the initial state. G: their final
  values evolve. A final-state target is an unimplemented inverse problem (UR-04),
  never a post-run area correction.
- *Law and exchange:* [contract §1](I01_PHYSICAL_CONTRACT.md#1-user-routes-clock-and-starting-assumptions).
  SI units, seconds forward from a named epoch, Ma only as an import convention, no
  universal spin-up.
- *Owners:* I04 builds the starting family. Every later row consumes it; nothing
  writes back to a committed initial state.
- *Evidence:* design only. `new-world-s2-r1` to `new-world-s4-r1` are historical and
  describe today's initial-condition route.
- *Remaining:* I04 needs a declared family independent of sampling resolution, with
  initial diversity judged apart from evolution (case H).

**CM-02 Inherited history.**
- *Routes:* X/P: formation ages, thermal histories, inherited weaknesses, initial slabs
  and mantle forcing, each with its origin and unknown masks. Hot-born ocean may start
  cooling at birth. Reheating never resets formation age. Initial continental geotherms
  (`k_i T'' + H_i = 0`) are applied once.
- *Owners:* I04 supplies and I05 carries. D1 reads initial slabs, D2 inherited
  weakness and D4 thermal state.
- *Evidence:* the D2 and breakup fixtures treat weakness as an authored initial
  assumption (`i01-controls-r1`, `i01-breakup-closure-r2`).
- *Refused:* unknown age as zero, mean-age cooling of mixtures, nearest-present-ridge
  ages (UR-03).
- *Remaining:* report how much retained material depends on assumed history
  (contract §1).

**CM-03 Plate and continent network.**
- *Routes:* initial boundaries are declared assumptions with origins (X/P). Later
  boundaries are G only through D2 localisation and D6 events. Today's layout uses
  geometric graph costs and ignores structure ([B2 diagnosis](NEW_WORLD_LAYOUT.md#causal-generation-diagnosis-and-replacement-design)).
- *Law:* D2 `atlas.nonlocal-weakening-candidate.v1` with a physical length; D6
  `atlas.regime-transactions.v1`.
- *Evidence:* `i01-controls-r1` (1D), `i01-fault2d-r1` (periodic 2D), `i01-strength-r1`.
  `boundary-kinematics-r1` is a descriptive PB2002 comparison, not acceptance.
  The separation, initiation and junction choices now have `i01-separation-feasibility-r3`,
  `i01-initiation-verification-r1` and `i01-junction-feasibility-r1` respectively;
  these do not generate or admit an evolving boundary network.
- *Refused:* bend-score optimisation, fairing and fitted random rotations presented as
  mechanics (UR-03, UR-08).
- *Remaining:* in I04, layout consumes structure and inheritance; forcing and strength
  changes move the response and frame changes do not; physical lengths survive
  refinement at arbitrary orientation on the production mesh. The 2D probe covers only
  a periodic square. Case B.

**CM-04 Motion (D1).**
- *Routes:* G `atlas.plate-torque-resistance.v1`: `M_i omega_i + reactions = b_i` with
  basal drag, GPE traction `-(L0/L) grad_s U` from the same columns and datum as D5 (no
  separate ridge push), slab pull from attached inventory only and recorded mantle
  forcing. P: prescribed rotations remain a reference mode (UR-01).
- *Exchange:* rad/s and N m. Positive drag anchors the declared mantle frame; net
  rotation is reported, never subtracted after the solve.
- *Evidence:* `i01-controls-r1`, `i01-gpe-r1`, `i01-motion-coupling-r1`,
  `i01-thermomechanical-motion-r2`, `i01-finite-strain-r3`, `i01-water-gpe-r1`,
  `i01-elastic-core-r1`.
- *Validity:* dry compensated columns, manufactured hemispheres and fixed-temperature
  regional balances; separately, periodic planar water-loaded traction with a
  declared shear-transfer depth for nonuniform finite rigidity, now produced
  together with rigidity by one explicitly declared homogeneous core.
- *Remaining:* I04 adds the evolving sphere, changing geometry, regional reactions and
  supported force-parameter challenges; I09 converges the coupled endpoint. Water-loaded
  columns and the selected single-core MC-07 branch have bounded pressure/load
  evidence, not arbitrary curved-reference or boundary acceptance. Coefficients are IN-03.

**CM-05 Material and thermal transport, evolving properties.**
- *Routes:* G `atlas.cohort-enthalpy-coupling.v1` with D3 cohort transport:
  finite-volume enthalpy with mesh velocity distinct from material velocity; per-cohort
  enthalpy and history; constant-per-material `Cp` and `k`; properties from one endpoint
  state; raw plastic history transported and never filtered in place.
- *Evidence:* `i01-thermal-r2`, `i01-column-heat-r3`, `i01-thermomechanical-motion-r2`,
  `i01-finite-strain-r3`, `i01-finite-admission-r2`.
- *Validity:* small-strain periodic cell, fixed-geometry columns and a closed laterally
  uniform strip. No lateral transport, inflow or melting.
- *Refused:* mean-age cooling, averaged viscosities or ages as W07 input, bypassed
  stationary or translation guards.
- *Remaining:* I03 spherical transfers; I05 heterogeneous deforming bridge, W06
  occupied-material means, age distributions and the necking-chain belt state. The
  chain's lateral-conduction criterion is selected in MC-06, but its conditional
  assumptions must be established on the actual coupled chain; basal inflow needs MC-04.

**CM-06 Rift deformation, weakening and decoupling.**
- *Routes:* G column law (composite creep plus regularised friction), evolving
  weakening, force-balanced motion, column heat and finite strain. Mechanical
  decoupling is the separate D6 record `atlas.rift-decoupling-handoff.v1`.
- *Evidence:* `i01-column-r1`, `i01-weakening-r2`, `i01-column-heat-r3`,
  `i01-thermomechanical-motion-r2`, `i01-finite-strain-r3`, `i01-decoupling-r1`,
  `i01-column-admission-r1`, `i01-finite-admission-r2`, `i01-transitions-r2`.
- *Validity:* laterally uniform strips. The linear handoff bound covers only its linear
  control. The homogeneous strip is admitted at 10%; the layered strip is honestly
  uncertified at 1%.
- *Refused:* a derivative ratio as a nonlinear or plastic release.
- *Remaining:* I02 declares `eps_v`; I09 compares coupled and replacement solutions
  with a declared norm, reference scale and history window (transitions §3); I05
  carries the belt state; I07 resolves belts.

**CM-07 Material separation (breakup).**
- *Routes:*
  - Creep-dominated, one fixed power law with 2 < n ≤ 4 and a quadratic weakness: G
    `atlas.necking-connectivity-breakup.v1`, analytical continuum feasibility only. The
    resolved certificate is not implemented (`UNRESOLVED`).
  - Plastic-dominated or brittle, including the retained column: refused by the chain.
    MC-01 now selects cohesion loss of bonded connectivity, irreversible cohort
    bond history and explicit support/physical-width inputs, with
    [resolved-strip feasibility](I01_SEPARATION_FEASIBILITY.md). Retaining elastic
    memory and MC-04's basal specification remain selected. The full mixed-material
    x–z neck and through-lithosphere event admission remain I05/I07 work (section 6).
  - P: a prescribed separation time and axis tests transfers only (UR-02).
- *Records:* only an admitted through-lithosphere separation
  ([contract §8](I01_PHYSICAL_CONTRACT.md#8-d6--physical-events-not-label-switches))
  splits ownership. Crustal disconnection is at most a separately named milestone.
  Crustal, mantle-lithosphere and mechanical-handoff diagnostics stay separate
  (section 6.1).
- *Evidence:* `i01-breakup-closure-r2`, `i01-transitions-r2`, `i01-finite-strain-r3`.
  `i01-separation-feasibility-r3` passes six controls, with eighteen focused tests:
  fixed-length/time refinement, independent energy accounts and non-breakage
  controls in a synthetic nonuniform shear strip. Physical acceptance stays false.
  The retained column is `REFUSED_REQUIRES_RESOLVED_NECK`: plastic share 0.5506 at the
  committed state and 0.5506–0.7858 across the sampled ×1–×1000 rates at stretch
  1.0–1.4. Its eventual breakup is `UNRESOLVED`, neither predicted nor excluded.
- *Refused:* thickness or strain cutoffs, ladder extrapolations as events or proven
  bounds, crustal disconnection alone as plate separation, decoupling as breakup,
  n > 4, flat or fixed-width necks as events, a universal fracture energy,
  magma-assisted breakup and thin continent relabelled as ocean (UR-03, UR-05, UR-07).
- *Remaining:* for the chain, the five certificate obligations of
  [breakup §5](I01_BREAKUP_CLOSURE.md#5-what-the-ladder-establishes-analytical-feasibility-not-a-resolved-event)
  (I05 state; I06 certificate and split). For the plastic regime, the original
  full-neck comparison, supported material inputs, basal sensitivity, transported
  bond records and event/handoff requirements remain with I05/I07 and I02/I03.
  NA-01's diagnostic specification is complete; it does not satisfy those gates.

**CM-08 Melt supply and ocean-crust birth.**
- *Routes:*
  - Melt-derived G: full source-to-crust implementation and physical acceptance
    remain open. MC-03 supplies the selected provider/flow/thermal route. Katz dry batch production, the ideal-mixture
    partition/energy/pressure/receiver family and W08 common-Tm delivery are different
    laws; none may be joined by passing a melt fraction. `atlas.decompression-supply.v1`
    is a full-extraction column inventory, not a supply.
    The [provider connection contract](I01_THERMO_PROVIDER_CONTRACT.md) now selects
    interface requirements: explicit units/basis/reference, domain/capabilities,
    extensive accounts and failure semantics. Its experimental G25/MAGEMin adapter
    now supplies common-Gibbs phase H/S/V, finite extraction and same-pressure
    receiving. Sixteen analytical tests and the 21.741 s Windows native campaign
    pass ([receipt](../evidence/i01-gibbs-provider-r2.json)); this dry software
    reference is not withheld calibration. The [selected melt route](I01_MELT_ROUTE.md)
    now specifies compatible porous flow, focusing and a solved cooling barrier,
    including its restrictions. The [segregation control](I01_MELT_SEGREGATION.md)
    now passes nine controls and twenty-one focused tests. It solves instantaneous
    two-phase mechanics for pre-existing liquid; it is not a live G25-to-receiver
    connection, time-advanced porosity or generated crust.
  - Supplied finite magma (X, IN-06): `dM_phase = rho_ref,phase h_ref,phase dA_birth`
    from finite named material and hot-birth enthalpy accounts; exhaustion refuses
    (contract §5). [Plan §2](INTEGRATION_PLAN.md#2-scope-and-scientific-ownership) makes
    magmatic source laws a geology exchange and admits supplied inputs in standalone
    cases, which test tectonics without establishing absent processes. This route
    satisfies neither MC-03 nor melt-derived generation, and it unblocks no Generate
    obligation.
  - No supply: the new floor is exhumed mantle, a separate D3 phase, never basalt.
- *Evidence:* `i01-melting-r1`, `i01-delivery-r1`, `i01-phase-partition-r2`,
  `i01-phase-energy-r3`, `i01-phase-pressure-r2`, `i01-magma-receiver-r2`,
  `i01-transitions-r2`, `i01-gibbs-provider-r2` (experimental G25 connection only),
  and `i01-melt-segregation-r1` (nine instantaneous mechanical controls).
  The segregation receipt is historical after three relative-link corrections in
  its method document; tool/case/test bindings remain unchanged and its numerical
  evidence remains valid. The original receipt is neither repinned nor rerun.
- *Validity:* dry Katz parcels at 0–3.5 GPa and at most 40% melt; an analytical ideal
  mixture, not calibrated mantle; a same-pressure receiver; delivery needs a
  prescribed extraction amount.
- *Remaining:* I05/I06 implement and physically accept the selected transport,
  phase-front and thermal route and its physical acceptance. I06 creates birth at the moving ridge from a supplied source (a
  tectonics test) and from the selected melt-derived provider, with finite source
  and export closure (case C). The melt-derived route also needs the axial lid
  `z_lid(rate)`, Tp provenance and MC-04.

**CM-09 Spreading, ridges and ocean ages.**
- *Routes:* G `atlas.spherical-cohort-transactions.v1`: half-rates `b_left` and
  `b_right`; birth area only with actual sources; ages from spherical trajectories;
  axis motion by declared symmetric accretion `f = 1/2` (`atlas.boundary-migration.v1`).
  P: asymmetric accretion and ridge jumps (UR-02).
- *Evidence:* `i01-controls-r1` (staged spherical lune), `i01-transitions-r2`.
- *Refused:* nearest-present-ridge ages, equal half-rates presented as a prediction,
  area renormalisation.
- *Remaining:* I03 adds moving segments and closed-sphere accounts; I06 adds coupled
  rift-to-spreading with constant, staged, prescribed-asymmetric and inactive-ridge
  controls (case C).

**CM-10 Trench consumption and slab inventory.**
- *Routes:* G incoming area `c dl dt` with `c = (v_down - v_trench) dot n_in > 0`, declared
  polarity, named slab, accretion or exterior destinations and one debit. The
  first-in, first-out attached window drives slab pull. X: initial slabs.
- *Evidence:* `i01-controls-r1` (sink accounts), `i01-transitions-r2` (slab and
  collision closed forms).
- *Refused:* convergence alone creating an established slab; distance buffers as
  consumption; two sinks debiting one stock.
- *Remaining:* I03 intersections and one-time debits; I07 carries the same cohorts
  across the interface (case D). Inputs IN-03 and IN-06.

**CM-11 Subduction initiation.**
- *Routes:* G `atlas.subduction-initiation-state.v1` specifies state and inventory, but
  self-sustaining subduction needs `C g sum(dm_i l_i) >= R(state)`, and `R(state)` has no
  validated reduced closure. [MC-02 now selects the resolved I07 method](I01_INITIATION_DECISION.md):
  retained elastic memory, declared pore-pressure ratio, physical-length
  plastic weakening and shared through-thickness diagnostics. A separate
  force-release test must distinguish continued sinking from elastic rebound.
  [Independent analytical verification](I01_INITIATION_VERIFICATION.md) now
  establishes the bounded flow/release/energy prerequisites. Full supported-case
  inputs and comparison allowances remain I07 requirements before event testing;
  this is not generated-initiation acceptance.
  Li and Gurnis (2023) is the preferred primary candidate, with source and numeric
  histories inspected and one diagnostic row reconstructed. Missing input and
  basalt-density files, case mapping and numerical conventions prevent exact
  reproduction, an optional source-reproduction route rather than the exclusive
  I01 prerequisite. Gurnis, Hall and
  Lavier (2004) remains supporting evidence; neither replaces the Atlas release test.
  P: prescribed initiation (UR-02).
- *Evidence:* `i01-transitions-r2` and `i01-initiation-verification-r1`:
  sixteen analytical controls and eight focused tests, not a subduction event.
- *Refused:* a universal convergence-distance trigger; buoyant young ocean
  self-sustaining without an admitted phase-change law.
- *Remaining:* I07's full supported case, predeclared allowances, space/time,
  rotation/exterior checks and genuinely unforced continuation (case D).

**CM-12 Continental arrival and collision.**
- *Routes:* G `atlas.collision-buoyancy-handoff.v1`: bracketed arrival, asymptotic entry
  and handoff by remaining convergence, then W08 shortening with a high-resistance D1
  interface. Arriving continent follows a declared partition (IN-06) or resolved I07
  mechanics. Slab breakoff is prescribed or refused (UR-02).
- *Evidence:* `i01-transitions-r2`.
- *Remaining:* I07 (case D). A later merge is a topology event that keeps suture
  weakness.

**CM-13 Transform and oblique motion.**
- *Routes:* G `atlas.full-vector-adapter.v1`: slip creates no area or uplift, and there
  is no angle threshold.
- *Evidence:* `i01-transitions-r2`.
- *Remaining:* I07 (case E). Strain partitioning is a resolved I07 output.

**CM-14 Topology events and junctions.**
- *Routes:* G `atlas.event-transaction.v1` (bracketed triggers, joint proposals,
  cascades) with `atlas.topology-transactions.v1` split, merge and retire. Junctions
  have compatible instantaneous velocities while velocity-triangle closure holds;
  that does not prevent two junctions colliding. The [affine contact helper](I01_JUNCTION_EVENTS.md)
  locates such contact on declared planar paths, without a sign-change requirement.
  The [outgoing ridge check](I01_RIDGE_JUNCTION.md) tests both new endpoint laws
  and positive ownership-oriented growth for supplied all-ridge candidates. This
  still needs exterior geometry, material/supply and physical birth admission.
  It is not yet connected to moving-world geometry. The selected
  [reorganisation route](I01_JUNCTION_REORGANISATION.md) evolves a multidirectional
  region using the shared physical mechanisms, then extracts the joint network.
  [Eight actual coupled 3D solves](I01_JUNCTION_FEASIBILITY.md) now establish
  bounded multidirectional mechanical feasibility (**MC-05**). Evolving shared
  failure/initiation/magma histories, physical interfaces and joint event admission
  remain unimplemented. Ridge jumps and polarity reversal are prescribed only (UR-02).
- *Evidence:* `i01-transitions-r2`, `i01-junction-events-r1` and
  `i01-ridge-junction-r1`; the latter two cover supplied local kinematics, not
  physical selection or graph changes. `i01-junction-feasibility-r1` records eight
  real 3D solves with three focused tests and independent force/torque/power checks.
- *Refused:* rubber-band closure, recolouring, smoothing and renormalised areas.
- *Remaining:* I07 shared multidirectional regional mechanics and mechanism-derived
  interfaces; I02 event calendar and transactions; I03 shared network with exact
  `4 pi R^2` ownership; I09 work-conjugate regional/global feedback and cascades
  within intervals (case G).

**CM-15 Support, datum, water and flexure (D5).**
- *Routes:* G `atlas.fixed-datum-support-water.v1`: local Airy base with owned regional
  replacement, finite connected water with a dry restoring coefficient, and the full
  variable-rigidity map-view operator. Sea level or water inventory and rigidity are
  inputs (IN-07).
- *Evidence:* `i01-controls-r1`, `i01-water-flexure-r1`, `i01-gpe-r1`, `i01-water-gpe-r1`, `i01-elastic-core-r1`.
- *Validity:* self-gravity, rotation, geoid and mantle-volume closure are explicit
  omissions; thin-column volume needs its declared geometric bound.
- *Refused:* tiled 1D profiles as a 2D or spherical response; summed total
  deflections; water counted twice.
- *Remaining:* I08 finite regions, exterior sensitivity, variable rigidity, a validated
  replacement mapping and external ports (case F). MC-07 now selects a declared
  single homogeneous core to produce both rigidity and shear depth. Inference
  from D2, multiple/yielding cores and curved-reference or boundary admission
  are not supplied by that bounded constant-rigidity branch.

**CM-16 Save, continue, inspect, change and consume.**
- *Routes:* G I02 atomic accepted state (parent, common endpoint, identities,
  reservations, all-or-nothing commit); I10 lifecycle and consumers; I08 external ports.
- *Evidence:* none for the evolved route. `new-world-bundle-r1` and `new-world-bundle-r2`
  are historical and cover the initial-condition route.
- *Remaining:* I02 zero-motion round trip, once-only transfer, rollback and resume
  parity; I10 CLI, UI, save, load, continue and export with a dependent consumer and
  correct invalidation (case J).

## 5. Remaining items by class

### MC: I01 choices and bounded feasibility

I01 owns each decision. Priority follows the plan's emphasis on generated-boundary and
rupture decisions, then items with no admissible interim route. *Interim* says what
keeps the Generate route honest until the item closes. MC-06 has a selected
conditional criterion, MC-04 a reviewed boundary/account specification and
MC-07 a bounded declared single-core branch. MC-02 now has independent analytical
prerequisite verification; MC-05 has actual multidirectional regional controls;
MC-01 has passed resolved-strip controls and selected irreversible bond history.
Their I01 choices are selected, while full event acceptance remains with I07 and
the shared-state owners. MC-03 now combines the retained G25 checks, nine passed
instantaneous segregation controls and the selected flow/thermal contract. All
seven MC choices have selection/feasibility support; the plan's I01 closure review
remains with the integrating owner, and full physical acceptance stays later work.
Selection does not certify the later coupled application.

| ID | Priority | Item | Exact reason | Interim | Builder | Source |
| --- | --- | --- | --- | --- | --- | --- |
| MC-01 | Selected; bounded resolved feasibility | Cohesion loss of bonded connectivity with irreversible cohort history; elastic memory retained | [Six resolved-strip controls and seventeen tests](I01_SEPARATION_FEASIBILITY.md) support the choice; full mixed-lithosphere event acceptance still needs the original section 6 comparison and supported physical inputs | Supported strip mechanics; prescribed separation only until full admission | I05, I07; I02/I03 event integration | [selected method](I01_SEPARATION_FEASIBILITY.md); [contract](I01_PHYSICAL_CONTRACT.md) §§4, 8; [elastic memory](I01_ELASTIC_MEMORY.md) |
| MC-04 | Selected bounded specification | Basal closure of thinning lithosphere: mechanical base condition, incoming temperature or enthalpy and composition, material and domain-volume balance with the moving free surface | [Reviewed specification](I01_BASAL_CLOSURE.md) and [bounded accounts](../evidence/i01-basal-closure-r1.json); independent exact work control. Inflow equals side outflow only at constant domain volume | Closed-strip runtime unchanged; open-base transport and resolved sensitivity remain later work | I05, I07 | [method and sources](I01_BASAL_CLOSURE.md#9-sources) |
| MC-02 | Selected; bounded verification | Resolve initiation rather than fit `R(state)` | [Independent analytical route](I01_INITIATION_VERIFICATION.md) verifies gravity-flow, force release versus clamping, and energy ownership. Original archives remain incomplete; I07 needs the full supported case and event tests | Prescribed initiation; declared initial slabs until I07 acceptance | I07 | [decision and sources](I01_INITIATION_DECISION.md); transitions §§6, 10, 11 |
| MC-05 | Selected; bounded regional feasibility | Physical junction reorganisation | [Eight real 3D mechanical solves](I01_JUNCTION_FEASIBILITY.md) verify the selected multidirectional route. Shared failure/initiation/magma histories and full event acceptance remain outstanding; contact or mechanical response alone is not a birth law | Supported regional mechanics; no generated reorganisation certificate | I07, I03, I09; I02 commit | [physical rule](I01_JUNCTION_REORGANISATION.md); [controls](I01_JUNCTION_FEASIBILITY.md); transitions §§5, 9, 10 |
| MC-03 | Selected; bounded feasibility | Corrected-G25 compatible provider, porous flow/focusing and solved axial cooling barrier | Retained G25 checks, [nine segregation controls and twenty-one tests](I01_MELT_SEGREGATION.md), and the [flow/thermal contract](I01_MELT_ROUTE.md) support selection. Segregation is instantaneous mechanics, not a live provider-to-receiver advance; full phase-front/source-to-crust and empirical acceptance remain I05/I06 | Supplied finite magma (IN-06): X only; no generated crust or validated lid from these controls | I05, I06 | [melt route](I01_MELT_ROUTE.md); [provider contract](I01_THERMO_PROVIDER_CONTRACT.md); plan I01 |
| MC-07 | Selected bounded branch | Pressure/load join and its material shear-transfer depth | [One declared homogeneous core](I01_ELASTIC_CORE.md) produces rigidity and shear depth together; [six controls](../evidence/i01-elastic-core-r1.json) support the existing planar join. Core depth and properties are explicit inputs, not inferred from effective elastic thickness or D2 strength | Compensated limits and the supported single-core branch; no arbitrary curved-reference, spherical or weak/broken-boundary acceptance | I04, I08 | [elastic-core method and sources](I01_ELASTIC_CORE.md); [water-loaded GPE](I01_WATER_GPE.md) |
| MC-06 | Selected conditional criterion | Error criterion for omitting lateral conduction | [Exact residual bound](I01_LATERAL_HEAT.md) with [bounded controls](../evidence/i01-lateral-heat-r1.json); requires whole-window contrast bounds and the same prescribed thermal operator/forcing | Coupled-neck omission remains uncertified; no automatic solver switch | I05, I06 | breakup §§5, 8; [method and sources](I01_LATERAL_HEAT.md) |

### LS: selected, later-stage implementation

Do not build these as further I01 prototypes. A new I01 control needs an MC item.

| ID | Owner | Work already assigned | Plan case |
| --- | --- | --- | --- |
| LS-I02 | I02 | Accepted-state contract, event calendar, candidate-validate-commit, `eps_v` numerical contract, persisted identity of issued states, once-only delivery transactions | plumbing |
| LS-I03 | I03 | Moving shared boundaries and junctions, conservative spherical transfers, moving ridge segments, closed-sphere source and sink control | A, G |
| LS-I04 | I04 | Starting family that consumes structure and inheritance; D1/D2 on the evolving sphere; force-parameter challenges; orientation-independent localisation on the production mesh | B, H |
| LS-I05 | I05 | Heterogeneous deforming thermal/material bridge; conservative raw-history and irreversible bond-cohort transport; necking-chain belt state and per-column clocks; W06 occupied-material means and age distributions | A, F |
| LS-I06 | I06 | Chain connectivity-loss certificate (five obligations) and split; rift-to-spreading with finite supply; exhumed-mantle phase; ridge controls | C |
| LS-I07 | I07 | Full-neck physical acceptance of selected MC-01/04; full initiation case under selected MC-02; W06-to-W07 bridge; D6 transitions on actual boundaries; collision, transform and strain partitioning; evolving shared mechanisms and physical interfaces in selected MC-05 multidirectional mechanics; velocity histories integrated into displacement | C, D, E, G |
| LS-I08 | I08 | Regional replacement mapping, finite regions and exterior sensitivity, variable rigidity, one tectonic surface and datum, external ports | F |
| LS-I09 | I09 | Coupled endpoint convergence or split-error bound; decoupling comparison; global-regional replacement; scheduling | B–G |
| LS-I10 | I10 | Lifecycle API, UI, save, load, continue, export, consumers and invalidation | J |
| LS-I11 | I11, I12 | Predeclared realism, portability and resource acceptance; release | H, K |

### IN: explicit inputs or calibration

Provenance is required for each; no Earth calibration is implied.

| ID | Inputs | Rows |
| --- | --- | --- |
| IN-01 | Seed, planet radius, initial plate count, initial continental fraction, history start, requested endpoint | CM-01, CM-03 |
| IN-02 | Inherited formation ages, thermal histories, weaknesses, initial slab geometry and inventory, mantle velocity or tractions, with unknown masks | CM-02 to CM-04, CM-07, CM-10, CM-11 |
| IN-03 | D1 coefficients: basal drag `D`, `L0/L`, slab transmission `C`, any interface `k_ij` | CM-04, CM-10 |
| IN-04 | D2 materials: creep laws with support, cohesion/friction/softening, residual strength and bond semantics, cohesion-loss temperature/pressure support and whole-history certificate, physical band width, `eta_p`, physical length `ell`, healing `h(T)`, pore pressure; no implicit rewelding | CM-03, CM-06, CM-07, CM-11 |
| IN-05 | D4 properties: `k`, `Cp`, radiogenic heat, `Ts`, `Tb`, mantle `Tp`, the rule for converting dissipation to heat | CM-05, CM-06, CM-08 |
| IN-06 | D3/D6 supplies and partitions: crust thickness, density, composition and hot-birth enthalpy, stock sizes, accretion fraction `f`, collision partition, attached-window length | CM-08 to CM-10, CM-12 |
| IN-07 | D5: compensation datum and reference densities, water inventory and connectivity rule, rigidity or `Te` law, regional boundaries | CM-15 |

### UR: unsupported routes and refusals

| ID | Route or refusal | Why it cannot satisfy Generate | Rows |
| --- | --- | --- | --- |
| UR-01 | Prescribed rotations or kinematic-only mode | A reference mode with no force balance (contract §3; plan §5) | CM-04 |
| UR-02 | Prescribed separation, initiation, junction reorganisation, ridge jumps, polarity reversal, rift migration, asymmetric accretion, slab breakoff | Tests transfers only; never a generated transition (transitions §§1, 10) | CM-07, CM-09, CM-11, CM-12, CM-14 |
| UR-03 | Cutoffs, floor-truncated ladder extrapolations as events, decoupling as breakup, thin crust as basalt, nearest-ridge or zero ages, area renormalisation, visual repair | No physical law; the outcome is set by the cutoff or repair (breakup §3; contract §§5, 8) | CM-02, CM-03, CM-05, CM-07 to CM-10, CM-14 |
| UR-04 | Final-state count or fraction targets | Needs an inverse problem; post-run correction is prohibited (contract §1) | CM-01 |
| UR-05 | Reduced-chain regimes: n > 4, n ≤ 2, flat or fixed-width necks, plastic-dominated states | Refused or not established by the chain (breakup §§4–6) | CM-07 |
| UR-06 | Melt fractions passed between Katz, ideal-mixture and W08 laws | Incompatible reference states and fusion energies (melting method) | CM-08 |
| UR-07 | Pore-fluid evolution, unrestricted elastic stress evolution, magma-assisted breakup, universal fracture energy, geoid and self-gravity, reactive melt transport, spontaneous global convection | No general implementation today, or outside the release scope (plan §2). MC-01 retains elastic memory, with a bounded coaxial control only; general non-coaxial implementation is I07's. MC-02 independently retains memory and selects a prescribed pressure-ratio scenario, not fluid evolution or a validated initiation solver | CM-07, CM-11, CM-15 |
| UR-08 | New World initial-condition saves and W12 fixtures presented as evolved worlds | Initial conditions, not a causal history (plan §3; B2 diagnosis) | CM-03, CM-16 |

## 6. Separation: rules, open choices and the next assignment

Generated separation of plastic-dominated or brittle lithosphere stays **open**: no
admitted mechanism removes through-lithosphere connectivity at finite time. The
chain's analytical feasibility (breakup §5) is not the retained lithosphere's event.

### 6.1 Rules for any separation claim

1. **One ownership event, three diagnostics.** Only an admitted through-lithosphere
   separation ([contract §8](I01_PHYSICAL_CONTRACT.md#8-d6--physical-events-not-label-switches))
   splits plate ownership, by the transitions §3 split rule. Crustal disconnection may
   be recorded only as a separately named milestone; alone it neither removes connected
   mantle coupling nor splits ownership. Crustal connectivity, mantle-lithosphere
   connectivity and the mechanical handoff are recorded separately. A nonlinear or
   plastic handoff needs the actual coupled-versus-replacement solution error, with a
   declared norm, reference scale and history-window bound
   ([transitions §3](I01_TRANSITIONS.md#3-continental-separation-atlasrift-decoupling-handoffv1)).
   This matrix does not change the contract.
2. **Required negative example.** Take a manufactured neck with a fixed physical length
   `w > 0` (for example a width set by the D2 length `ell`), factors `a, c > 0` and
   `a w < H_c`:

   ```text
   h(u) = H_c - u/c                        for u <= u_a = c (H_c - a w)
   h(u) = a w exp(-(u - u_a)/(c a w))      for u >  u_a   (slope continuous at u_a)
   ```

   At `u = c H_c`, `h = a w/e > 0`, and `h` stays positive at every finite opening. Now
   admit only rungs `h_k = H_c 2^-k >= c_w w`. If `a <= c_w`, every admitted rung lies on
   the linear branch, so `u_k = c (H_c - h_k)` and every increment ratio is exactly 1/2.
   Given at least the five rungs its window needs, the breakup §5 ratio rule
   (`ratio_max` 0.9, `ratio_spread` 0.02) then reports `FINITE_LIMIT`, exponent 1 and
   the false limit `c H_c`. Halving `w` leaves that limit unchanged. Any separation
   logic must refuse this field: no event, finite-limit proof or handoff-error bound
   follows. The extrapolation may be reported only as a diagnostic.
3. **Consequences for every ladder.**
   - A ladder extrapolation is a diagnostic, never a certificate or a proven
     handoff-error bound. The chain's status rests on the declared power law's exact
     asymptotics, which its ladder only corroborates (breakup §5, obligations 1 and 3).
     A resolved field has no such asymptotics.
   - Grid refinement (N versus 2N) at a fixed physical regularisation length, the D2
     `ell`, tests the numerical convergence of one physical model. Changing `ell`
     changes the physics (IN-04): report it as a sensitivity, never as refinement.
   - The shear-zone width and the geometric neck width are measured separately. Neither
     is established as equal to the other or to `ell`.
   - Detection levels are reporting levels. A lower floor or level does not turn a
     diagnostic into an event, and no smaller cutoff may replace a refused one.
   - Every comparison reports the neck's stress, pressure, temperature and strain-rate
     ranges against declared coefficient support (breakup §5, obligation 1).
4. **Why ladders and manufactured fields cannot settle it** (Atlas reasoning; no source
   is claimed). While the velocity gradient stays bounded, material moves by a
   continuous, invertible map. A connected material set therefore stays connected, and
   its thickness stays at least its initial value times
   `exp(-integral of the maximum strain-rate magnitude dt)`. Breakup §2's fixed-width
   neck and the exponential branch above are special cases. Material separation at
   finite time needs one of three things:
   - a finite-time singularity shown for the resolved solution from its declared laws'
     asymptotics, not from a ladder;
   - an admitted change of state or composition, such as melting with extraction;
   - an admitted failure law that creates a discontinuity.

   Manufactured connectivity or accounting controls establish none of these.

<a id="62-choices-that-stay-open"></a>

### 6.2 Selected choices and outstanding physical acceptance

I01's selections and bounded controls are recorded above. I07 owns the remaining
full-neck comparisons, with I05 for material and history accounts. The original
acceptance conditions below remain unwaived; I01 selection is not their completion.
Comparison tolerances must be fixed before execution. The candidate
resolved-neck set stays provisional except for the explicit subchoices below. It comprises retained
composite creep; the
[contract §4](I01_PHYSICAL_CONTRACT.md#4-d2--strength-and-physical-length-localisation)
D2 elements (the plane-strain yield with absolute `P_eff`, softening of cohesion and
friction with history, healing `h(T)`, the Helmholtz length `ell`, the plastic viscosity
`eta_p` and transported raw `kappa`); a free surface; owned shear heating; and
retained elastic stress memory with the logarithmic-objective direction below.

**MC-01, separation mechanism.**
- *I01 choice:* cohesion loss of bonded connectivity, with irreversible cohort
  bond history, physical width, explicit material support and retained elastic memory.
  Six resolved-strip controls and seventeen tests pass in the
  [bounded feasibility route](I01_SEPARATION_FEASIBILITY.md).
- *Why physical acceptance stays open:* no full-neck event is admitted. A universal fracture energy and magma-assisted breakup
  are refused (UR-07), cutoffs are refused (UR-03) and truncated ladders fail the
  negative example. The retained coefficients are not evaluated at the stresses where
  creep would take over from the plastic branch (breakup §6).
- *Bounded comparison:* the retained lithosphere as one resolved x–z neck, on N and 2N
  at fixed `ell` and once with a changed `ell` as a separate sensitivity. Record the
  three diagnostics, both widths and the support ranges separately, and pass the
  negative example through the same decision logic. For the declared power law,
  compare the chain's ladder values at the rungs the grid resolves; this is a
  consistency check, not plastic-event evidence.
- *Acceptance:* a mechanism is admitted only if its event converges between N and 2N at
  fixed `ell`, rests on no threshold whose influence is not removed, refuses the
  negative example and stays inside coefficient support along the approach. Replacing
  the belt must meet the transitions §3 bound over the history window.
- *Blocked meanwhile:* generated plastic-regime separation, including the retained
  column (CM-07); later boundaries from separation (CM-03); split transactions it would
  trigger (CM-14); and ocean birth after a generated separation (CM-08). A prescribed
  separation tests transfers only (UR-02). If no mechanism passes, the route stays
  blocked. Only the owner can reclassify it as unsupported
  ([plan §5](INTEGRATION_PLAN.md#5-scientific-decisions-that-must-close-before-their-implementation)).

**MC-01, elastic memory in the rift neck.**
- *I01 selection:* **retain** elastic stress memory. Omission has no demonstrated
  rift-wide bound and is not the default. The [method](I01_ELASTIC_MEMORY.md)
  selects a logarithmic-objective constitutive direction, informed by Schrank et
  al. (2017) and ASPECT's actual stress-history source, without equating the two laws.
- *Bounded evidence:* an exact coaxial Maxwell update checks relaxation, rotation,
  independent stored-energy/work/heat accounts and coefficient reuse in
  [nine controls](../evidence/i01-elastic-memory-r1.json) and twelve tests.
  Constructed deformation history fixes the shared axes; general shear is refused.
- *Later implementation:* I02 persists stress; I05 transports it; I07 implements
  the general logarithmic spin and nonlinear creep/plastic coupling. The control
  is not that implementation and does not validate a resolved separation event.
- *Any future omission:* still needs a bound along the whole approach, or a
  predeclared comparison of the three diagnostics. A long timestep alone is not
  a bound. No omission is admitted here; full separation acceptance stays open.

**MC-04, basal closure.**
- *Choice:* an explicit mechanical base condition; incoming temperature or enthalpy
  and composition, with provenance; and a material and domain-volume balance that
  includes the moving free surface. The I05 strip or chain accounts and the I07
  resolved domain both need all three.
- *I01 selection:* the [reviewed specification](I01_BASAL_CLOSURE.md) supplies all
  three parts and the [bounded receipt](../evidence/i01-basal-closure-r1.json)
  checks their accounts, inventory/geometry and boundary guards, endpoint matching
  and an independent exact mechanical-work solution. The I01 choice is selected;
  the resolved comparison is not completed. An inflow inventory alone is not a boundary closure.
  The ASPECT cookbook, as recorded in the
  [finite-strain source table](I01_FINITE_STRAIN.md#9-sources), balances side outflow by
  basal inflow under a free surface. Breakup §11 records its statement that breakup
  needs upwelling asthenosphere. That is one configuration: basal inflow equals side
  outflow only where the domain volume is held constant, and it is not a free-surface
  identity.
- *Bounded comparison:* each fully specified closure on the MC-01 configuration and on
  the I05 accounts.
- *Acceptance:* material, domain-volume and enthalpy accounts close within the
  predeclared tolerance, including the free-surface volume change. The exterior account
  is debited once. The closure states its validity, and the diagnostics' sensitivity to
  it is reported, not tuned.
- *Later implementation:* I05/I07 must bind transported source states and solved
  fluxes to one prescription, predeclare resolved tolerances and compare base depths
  and laws. I02 owns once-only commit. The resolved neck (CM-07) and melt-derived
  path (CM-08) still need their other choices; the closed-strip runtime stays unchanged.

### 6.3 NA-01: selected separation diagnostics

The [separation decision](I01_SEPARATION_DECISION.md) and its
[case](../cases/i01_separation_decision_v1.json) now select the records,
material-support rules and mechanical comparison contract. NA-01's diagnostic
assignment is complete; its original scope was documentation only. The later
MC-01 resolved-strip controls are separate evidence, not a full event certificate. The exact
exponential-tail counterexample remains a mandatory refusal.

**Selected:**

1. The records and diagnostics of section 6.1 (1): the through-lithosphere separation
   event, the crustal disconnection milestone, mantle-lithosphere connectivity and the
   mechanical handoff. Each is computed on tracked material amounts, with the
   through-thickness integrated strength requested by
   [transitions §11](I01_TRANSITIONS.md#11-mechanical-inputs-a-rupture-or-initiation-law-needs-from-d2)
   item 5, which MC-02 shares. The record also fixes the handoff norm, reference scale
   and history window; `eps_v` stays with I02.
2. The rules of section 6.1 (2) and (3), as refusal conditions. The negative example
   becomes a mandatory refusal case for any later separation tool.
3. Reuse MC-04's already selected basal prescription, thermal/compositional source
   and moving-volume accounts for I05/I07. That independent choice is not counted
   again; its resolved implementation and source-prescription binding stay later work.

**NA-01 prepared** MC-01's mechanism comparison by fixing its diagnostics.
The subsequent MC-01 method/history selection and bounded feasibility now pass
separately. General implementation and full separation admission remain I05/I07
work; neither NA-01 nor the resolved strip supplies that physical acceptance.

The definitions also check the union of crust and mantle: an alternating-material
bridge may remain even if each subset has no complete side-to-side path. They
keep geometric neck width separate from plastic-zone width and fix a whole-window
maximum velocity norm, replacement reference speed and expiry rule. I02 still
supplies eps_v; no production value or wider nonlinear certificate is invented.

**Decision boundary.** The shared diagnostic/evidence specification is selected.
NA-01 alone closes no additional MC item. The selected MC-01 method still needs
I07's full resolved comparison before physical events can be admitted.

**Next owner obligations.** I05 supplies supported material inputs and conservative
cohort/bond transport; I07 implements the original full-neck comparison, including
the negative example, fixed-ell refinement, thermal/material evolution and basal
sensitivity; I03/I07 cover exterior and along-strike paths. I02 later supplies
`eps_v`, persistence and one atomic event commit. This record starts none of those
increments. I01's seven selections now have bounded support; its final finish-rule
review remains with the integrating owner.

**Files.** `tectonics/docs/I01_SEPARATION_DECISION.md` and
`tectonics/cases/i01_separation_decision_v1.json`, plus one paragraph in section 7 of
the [reader chapter](how-it-works/06-physical-integration.md). The source-bound
contract, transitions and breakup documents stay unchanged. Any contract amendment is
a separate owner decision.

**Checks.** JSON parsing, links, `tools/check_public_paths.py`,
`tools/check_coding_safety.py` and `tools/check_current_evidence.py`. No scientific
rerun applies.

**Not in NA-01.** Selecting a separation mechanism or failure law; admitting elastic
omission; any I05–I07 code or evidence-register changes; closing MC-02, MC-03 or
MC-05 to MC-07. Current guide/matrix/status links only record this documentation.

## 7. Sources

**Read for this matrix (repository):** `AGENTS.md`, `CLAUDE.md`, `README.md`,
`docs/CURRENT_STATE.md`, `docs/CODING_SAFETY.md`, `docs/CURRENT_EVIDENCE.md`, the
evidence register, [INTEGRATION_PLAN.md](INTEGRATION_PLAN.md),
[I01_PHYSICAL_CONTRACT.md](I01_PHYSICAL_CONTRACT.md),
[I01_BREAKUP_CLOSURE.md](I01_BREAKUP_CLOSURE.md) and its case, the retained-control
section of `i01-breakup-closure-r1`, [I01_TRANSITIONS.md](I01_TRANSITIONS.md),
`cases/i01_closures_v1.json`, the [reader chapter](how-it-works/06-physical-integration.md),
and the B2 section of [NEW_WORLD_LAYOUT.md](NEW_WORLD_LAYOUT.md). Targeted excerpts
only: the integration boundaries of the melting, phase-energy, phase-pressure,
phase-partition and GPE methods; W07 surface-strength and boundary-condition notes;
function inventories of the breakup and transitions tools; source keys of the I01
receipts.

**Reread for the review correction:** contract §§4, 5 and 8; transitions §§3, 6 and
10–11; breakup §§1–8 and 10–14, the case's ladder gates and the tool's `ladder_verdict`
rule; plan §§2 and 5 and the I01, I06 and I07 increments; the ASPECT and inflow lines of
the finite-strain method; and reader §7. No external source was read for the correction,
and it makes no new physical choice. The negative example and the bounded-rate argument
in section 6.1 are Atlas derivations, not cited results.

**Reused, not reread:** primary research recorded in the linked method documents,
with the reading scope stated there. This includes Brune et al. (2014); the ASPECT
continental-extension cookbook, parameter file and strain-weakening source; Hutchinson
and Neale (1977); Audoly and Hutchinson (2019); Gurnis, Hall and Lavier (2004); Duretz
et al. (2023); Clennett et al. (2023); Katz et al. (2003) as quoted by Brune; Keller and
Katz; and Wickert (2016).

**Not accessible:** Huismans and Beaumont (2011, Nature 473:74). The publisher and
PubMed pages did not load. A search-index summary of its abstract was seen and is not
used as authority. It remains the named crust-first/mantle-first limitation in
breakup §11.

No external software was installed or run. No test, campaign or measurement was run
for this matrix.

The current consistency pass uses the corrected separation r3, initiation r1
and junction r1 controls, the plan's I01 finish boundary and the selected melt
route, plus the delivered melt-segregation receipt and its documented prose-only
drift. It adds no simulation or physical acceptance; I01's final closure review
remains with the integrating owner.

The subsequent I01 repair refreshed heat, thermomechanical motion, finite strain,
admission, breakup and G25 receipts after enforcing actual thermal density and
explicit thermodynamic branch support. The machine-readable mirror and current
citations above use those new receipts. Physical event requirements are unchanged;
592 I01 tests pass and I02 remains paused.

## 8. Checks for this document

This is a documentation and design-record change, so no scientific rerun applies.
Check JSON parsing, paths, cross-references, register digests and link anchors, then
run the standard static checks:

```text
python -B tools/check_public_paths.py
python -B tools/check_current_evidence.py
python -B tools/check_coding_safety.py
```
