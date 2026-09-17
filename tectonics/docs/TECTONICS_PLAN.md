# Atlas tectonics simulation plan

**Report 05 | ATLAS-TECTONICS-PLAN-1 | Revision 11 | 17 September 2026**
**Status: development plan with a delivered foundation; remaining capabilities are proposed, not physically accepted.**

Atlas is vibe-coded, with OpenAI ChatGPT/Codex doing the coding under Michael’s direction. The owner has selected Earth-like mobile-plate tectonics for the intended 1.0 release. Atlas remains world-agnostic; the Diadem is the principal development case, not the definition of the underlying physics.

**Revision 11 — regional W02 implementation complete.** The local delivery adds
conservative nonuniform remapping, ALE moving volumes with u-w fluxes, explicit
1D plate/block ownership, split/merge/reassignment/activity events, material marker
maps and self-contained cold restoration. Together with regional/cohort transport
and prescribed transfers, all named W02 responsibilities now have an executable
**1D regional, constant-density, prescribed-kinematics** implementation and tests.
This is not arbitrary-dimensional/planetary topology or physical/geological acceptance.
Future spherical polygons/junctions and force/productivity laws remain W01/W06–W08
extensions; they are not silently claimed by a 1D pass. W04 load construction is the
next physical increment. The [existing optimisation reference](OPTIMISATION_REFERENCE.md#w02-completion-delivery)
records measured methods, memory and remaining validity boundaries. Accuracy-first
compiled defaults, W00–W12 dependencies and prior acceptance tolerances are retained.

**Revision 10 — material cohorts and formation history.** The second W02 increment
adds nonnegative partial-thickness transport by cohort, explicit known/unknown
formation times, immutable lineage receipts, and prescribed birth/addition/removal
transactions with per-cohort regional accounts. Higher-accuracy MUSCL/SSP-RK2 is
the default even when upwind is faster. Runtime, memory pressure and cache policy
must not silently lower accuracy; optimise execution of the selected equations.
The existing snapshot store, cache controls and executor are reused. This is
fixed-grid, common-velocity, constant-density volume accounting, not a variable-
density or multi-velocity model. Remapping, moving topology and plate-membership
events remain future W02 work. Physical production/recycling rates, mechanical
closure and W05 terrain acceptance are not supplied by bookkeeping events.
See [cohort implementation and checks](OPTIMISATION_REFERENCE.md#w02-materials-delivery).

**Revision 9 — W02 regional transport delivered.** Open/closed fixed-grid transport,
explicit external accounts, timestep advice, compiled upwind/MUSCL profiles, existing
executor/cache integration and independent refinement checks are now implemented.
This is one W02 increment, not all material/event history or a W05 geological pass.
No prior numerical kernel, fixture or tolerance was altered. Current tests and
selection limits are recorded in the existing optimisation reference's
[W02 section](OPTIMISATION_REFERENCE.md#w02-regional-delivery).

**Revision 8 — combined resource acceptance.** Item 12 now adds shared parent/component
byte admission, retained-state lifetimes, pooled CPU/worker allowances and a combined
resource/platform acceptance route. The local Linux run passes the regression suite
and bounded compute/cache/compression/incremental-recovery combinations. **Windows
acceptance is still pending an actual local run.** Item 1 remains skipped; items
2–11 and the scientific K/M modes, equations, parameters, W00–W12 and T01–T16 remain
intact. See the [existing optimisation reference](OPTIMISATION_REFERENCE.md#combined-acceptance)
for evidence and limits. These are engineering foundations, not geological acceptance
or completion of the coupled tectonic model. Two maintained documents remain the
policy: this plan and the optimisation reference, with case/tests beside code.
No new general roadmap or publication is part of this delivery.

**Navigation:** [Scope](#recommended-architecture-and-10-scope) · [State and interfaces](#scientific-state-and-interface-contracts) · [Equations](#equation-plan-and-gaps-to-close) · [Work packages](#work-packages-and-dependency-gates) · [Coupling](#coupling-timestep-and-state-acceptance-policy) · [Execution and optimisation](#numerical-and-computational-design) · [Validation](#verification-physical-validation-and-decision-rules) · [Milestones](#milestones-decision-ownership-and-risk-control)

## Executive decision

Develop a **physically tested, multiscale tectonics system**, not a mountain-placement algorithm and not a collection of seventeen integrated software packages. Use a shared description of the world, plate history and material accounts, with two explicitly different ways to calculate deformation: prescribed kinematic experiments and regional mechanical calculations. Couple only the surface and thermal processes required to interpret each experiment. Design for efficient execution from the outset. Verify any enabling acceleration against an appropriate numerical reference while the physical investigation proceeds; later optimise and scale accepted behaviour at matched error. Build production interfaces only after the relevant scientific and resource gates.

The first delivered foundation contains restricted versions of the **small mathematical reference suite**: rotations and boundary signs, periodic conservative thickness transport, analytical cooling and uniform periodic load response. Continue from those kernels rather than rebuilding them; they do not complete W01–W04. The first coupled mechanism should be prescribed regional extension plus a separately checked vertical response. This is a recommendation for an informative test, not a claim that extension explains the Diadem. Shortening, shear and subduction must receive their own subsequent tests.

**What this plan selects:** architecture direction, scientific responsibilities, candidate equation families, work order, required evidence, optimisation priorities and release gates. **What it does not select:** calibrated Earth/Diadem parameters, a complete mechanical closure for every regime, a production machine, runtime budgets, an external solver dependency, or permission to execute any case. Parameters and unresolved constitutive choices have named decision gates rather than hidden defaults.

The full 1.0 tectonics scope below is deliberately broader than the first prototype. If a required regime remains unsupported, the deliverable must be a labelled research preview or an explicitly narrower capability release—not an unqualified claim of complete Earth-like tectonics.

## 1. Basis, constraints and intended result

### 1.1 How this plan uses the pre-studies

Reports 01–03 supply the modelling, optimisation and implementation assessments. Report 04 supplies the stable identifiers **P01–P15**, **E01–E28**, **F01–F17** and **O01–O17**. They are retained here; they are not new Atlas module names or a replacement for its eighteen categories. In particular, Report 04 identifies gaps in yielding, free-surface treatment, mass creation/consumption, magmatic transfer and water/sediment closure. This plan treats those gaps as work, not as capabilities already supplied by the equations. [[R01](#research-basis); [R02](OPTIMISATION_REFERENCE.md#scientific-methods); [R03](#research-basis); [R04](#research-basis)]

The repository baseline described in those studies is `7d0e707a576fe08b9bcb816466a0a8fb5f115808`. This is **not a fresh audit of GitHub or the Windows workspace**. The studies identify an active tectonic snapshot adapter, existing geometry/route reuse, a native 256-cell domain and a fixed-quantum material ledger. Preserve them as historical implementations with their own meanings; new experiments must not silently alter their bindings or relax their limits. [[R03](#research-basis); [A01][url-001]; [A02][url-002]; [A04][url-003]; [A06][url-004]; [A07][url-005]]

This revision consolidates documentation only. No numerical code, Atlas test, simulation, benchmark, source repinning, dependency installation or Windows integration is part of this update. Any companion repository-documentation publication is recorded separately; checking documents is not running the model. Execution references PS01–PS08 and language references LS01–LS05 are retained with the optimisation reference; no scientific-software re-audit was performed.

**Implementation status supplement:** the historical pre-study baseline above is preserved. The subsequent remake foundation at `11317165b7e2aeab7201a1fe3e3f646cb640d51e` provides the restricted kernels listed in the optimisation reference’s current-baseline section. This does not complete W01–W04 or validate real terrain. The current update changes documents, not that implementation.

### 1.2 Owner requirements retained

| Requirement | Consequence for this plan |
| --- | --- |
| Accuracy is the default | Keep the most accurate supported selected scheme as normal; optimise it rather than selecting lower order/precision for speed. Refuse an inadequate resource budget instead of silently downgrading physics or accuracy. |
| Earth-like tectonics for 1.0 | Assume a mobile lithosphere with terrestrial-style physical relationships; do not require a model of the origin of plate tectonics. |
| Physical parameters are not buried in solver code | Use explicit, versioned Earth-like profiles in 1.0; reserve user-facing customisation for later without making it a release obligation. |
| Atlas must not require the Diadem | World identity, radius/geometry, material parameters, constraints and initial conditions are inputs. History A is a compatibility example, not a universal template or independent validation case. |
| Eventual whole planets | Establish spherical rotation and area conventions early. Full planetary physical execution is a later scale gate, not a claim made by passing regional cases. |
| Resolution as fine as feasible, including 1 m | Keep evidence, process, exchange and output spacing separate. No fixed 100 m/10 m product ceiling; no promise of metre-scale whole-planet physics. |
| Realism before production wiring | Independent equations and bounded mechanism tests precede the end-to-end production chain. Interfaces needed to test a mechanism are allowed in its future scope; production integration remains later. |
| Learn methods, do not integrate packages now | Reuse scientific ideas and documented algorithms as references. Any future source, data, library or database adoption needs a separate dependency/provenance and permission review. |

### 1.3 What a successful tectonics result contains

The tectonics product should provide evolving plate/block geometry; deformation and displacement; crustal/lithospheric state; surface and subsurface material histories; specified thermal and magmatic consequences; and the uncertainties, applicability limits and accounts behind them. A terrain view must identify what elevation came from tectonics, loading, thermal support, erosion, deposition or generated visual detail.

A successful numerical run is not necessarily geologically plausible. A geologically plausible unconstrained case is not automatically compatible with the Diadem. Code correctness, numerical accuracy, physical adequacy, world-design compatibility and canon approval remain distinct judgements.

<a id="current-implementation"></a>

### 1.4 Current implementation and document maintenance

**Current local engineering status:** the item-12 package builds on local items
2–11 (remote base `0590774b…`). Shared resource and combination tests are Linux-
accepted within their measured envelope; Windows is unverified. The next scientific
work now continues from delivered open-boundary transport towards the remaining
material-history/creation work and physically defined loading.
Continue using the optimised defaults, and carry resource/ownership tests into each
physical increment. No statement here means a new remote commit or a passed W05.


Verified documentation baseline: `remake` at `612d53eba495202101a8e638578f47fb37752649`; delivered numerical foundation: `11317165b7e2aeab7201a1fe3e3f646cb640d51e`. The [module README][url-006] and [delivery record][url-007] are the source of this status, not a new run.

| Work package | Delivered portion | Still outstanding |
| --- | --- | --- |
| W00 | Synthetic foundation case and verification rules. | The next physical case’s complete inputs, observations and acceptance decisions. |
| W01 | Rotations, boundary diagnostics and immutable parameters. | General geological sampler, plate polygons, topology and independently verified sides. |
| W02 | Regional implementation complete: cohorts/history, prescribed transfers, conservative nonuniform remap, ALE u-w motion, complete interval ownership, split/merge/reassignment/activity, marker maps, direct snapshot restoration and existing executor/cache integration. | Physical/geological acceptance is not implied. General 2D/spherical junctions and predictive source/force laws require W01/W06–W08 extensions. |
| W03 | Analytical half-space temperature reference. | Evolving thermal solver, finite plate and compaction. |
| W04 | Uniform periodic 1D discrete flexure. | Physical load construction and further geometries/boundaries. |
| W05–W10 | Planning and method studies only. | Coupled mechanisms and independent physical validation. |
| W11 | Local items 2–12 and W02-specific native, allocation, accuracy-cost and combined-path checks; bounded Linux evidence. Item 1 explicitly skipped. | Windows acceptance, future mechanisms and their physical scale-transfer/world-scale evidence. |
| W12 | Planning only. | Production integration and release acceptance after scientific and scale gates. |

**Two maintained documents:** update this plan for scope, equations, dependencies and acceptance; update `OPTIMISATION_REFERENCE.md` for execution, storage, language and method detail. Word files are reading editions of the same Markdown content, not extra authorities. Keep change history inside these documents/Git history; do not create another supplement, general review guide, source-register file or performance-plan copy for routine findings. Case specifications and obtained test evidence stay next to code and are not competing roadmaps.

Previous versions and scientific pre-studies remain historical evidence. They are not deleted from prior chat attachments or restated as newly verified. Retired optimisation pages are superseded by the reference; no numerical source or historical evidence bytes are rewritten by consolidation.

<a id="recommended-architecture-and-10-scope"></a>

## 2. Recommended architecture and 1.0 scope

### 2.1 Three scientific layers, not seventeen software integrations

**World/history layer.** Holds geometry, finite rotations, shared boundaries, events, material identity and initial geological/thermal descriptions. It can replay an authored history or propose a constrained generated history. Generated proposals must pass structural and physical admissibility checks; random rotations and arbitrary polygon repairs are not a validated tectonic model. GPlates, GPlately and World Builder are the method references. [[S01][url-008]; [S03][url-009]; [S04][url-010]; [S06][url-011]]

**Regional process layer.** Applies an explicitly chosen deformation model to a named domain with external boundary information. Begin with reduced kinematics where that answers the question. Use a selected mechanical formulation when stress, strength, localisation or slab/overriding-plate response is part of the claim. LaMEM, ASPECT, Underworld and pTatin3D are alternative references—not four solvers to run in sequence. [[R01](#research-basis); [S08][url-012]; [S10][url-013]; [S13][url-014]; [S16][url-015]]

**Surface/history layer.** Converts rock movement, physical loading and the necessary water/sediment processes into surface elevation and stratigraphy. Track material budgets and geological histories independently of rendering resolution. gFlex, pyBacktrack, FastScape, selected Landlab components, Badlands and goSPL supply the main method references. [[R04](#research-basis)]

### 2.2 Two deformation modes, with no silent substitution

| Mode | Recommended role | Mandatory statement |
| --- | --- | --- |
| **K: prescribed kinematics** | Initial reference cases and supported reduced geological scenarios: motion or fault displacement is specified, while transport, thickness and defined vertical consequences are calculated. | Motion is prescribed or generated by a stated scenario rule; it is not predicted from mantle forces. |
| **M: regional mechanics** | Questions needing stress/strength-dependent deformation, subduction-wedge flow, shortening, distributed strain or localisation. | Geometry, rheology, initial state and mechanical/thermal boundaries close the equations; their adequacy needs separate evidence. |

Mode M may take boundary velocities from Mode K. In that configuration K supplies boundary forcing, not a second displacement to add to M’s solution. Likewise, flexure may supply a missing load response only when that response is not already represented by the mechanical calculation. Every contribution has one physical owner.

**Candidate numerical baseline for M:** a two-dimensional, inertia-free viscous/Stokes calculation on a structured staggered grid, with explicit material fields and conservative transfers; compare it with a compatible mixed finite-element alternative at the design gate. Start at constant viscosity before adding thermal coupling and pressure-sensitive yielding. This is a proposed small reference formulation, not a decision to recreate LaMEM, approve all its laws or restrict eventual three-dimensional modelling. [[S08][url-012]; [S10][url-013]; [S16][url-015]]

### 2.3 Release scope: required, conditional and deferred

| Scope | Planned 1.0 treatment |
| --- | --- |
| Kinematics and topology | Required: regional translations/rotations, spherical rigid rotations, shared boundaries, reference frames, time-dependent stages and explicit supported boundary events. |
| Material creation and recycling | Required: ridge birth, age, tracked subduction/export, accretion and plate/crust identity separation, with explicit source/sink accounts. |
| Extension and spreading | Required: continental thinning, normal-fault kinematic consequences, breakup when selected, ocean-crust creation and cooling; no invented height bands. |
| Convergence | Required: supported subduction and continental-shortening/collision cases, clear regime transitions, material budgets and defensible vertical response. |
| Shear | Required: transform/oblique motion and supported local transpression/transtension; pure shear must not invent crustal mass or blanket uplift. |
| Thermal and support response | Required where causally relevant: cooling/heating, density/strength effects, isostatic/flexural support and sediment compaction/loading without double counting. |
| Magmatism | Required reduced accounts where oceanic crust, arcs or volcanic construction are claimed; source, rate, emplacement geometry and heat treatment must be justified. |
| Surface evolution | Required for claims about final landforms: adequate runoff/routing, erosion, deposition and loading for the selected regime. Full climate need not be solved simultaneously. |
| Special events | Conditional: back-arc opening, fault reactivation, post-collision extension, terrane accretion, hotspot tracks and caldera collapse. A scenario invoking one needs its tested closure. |
| Specialist diagnostics | Optional: elastic dislocation diagnostics, phase-equilibrium property tables and thermochronometric observations. They must answer a needed question, not expand scope automatically. |
| Beyond the baseline | Deferred: self-organising global mantle convection, spontaneous initiation of every fault/subduction zone, individual earthquake rupture/waves, full reactive two-phase magma transport, non-Earth-like tectonic regimes and universal metre-scale mechanics. |

Complete planetary execution is a separate capability claim even if spherical mathematics is present. Whether it is included in the eventual 1.0 release should depend on its evidence and resource gate, not on a new restriction of the owner’s long-term product intent.

<a id="scientific-state-and-interface-contracts"></a>

## 3. Scientific state and interface contracts

### 3.1 State to represent explicitly

| State group | Minimum content | Main consumers |
| --- | --- | --- |
| World and run profile | Geometry/radius, gravity, units, reference frame, time convention, scenario, boundary extent, selected laws and validity envelope. | Every process. |
| Plates and blocks | Stable identity, polygons/shared sections, material membership, finite-rotation stages, rigid versus deforming status. | Kinematics, birth/recycling, regional boundaries. |
| Boundaries and faults | Side identity, orientation, boundary velocity, type/activity intervals, polarity, dip/slip geometry as needed, junctions and event lineage. | Regional deformation, subduction, hazard-facing outputs. |
| Crust and lithosphere | Distinct thicknesses, composition/material classes, density/strength inputs, temperature or justified reduced thermal state. | Mechanics, loading, material accounts. |
| Conserved material | Material/origin IDs, represented mass and support volume/area, phase/class, sources/sinks, split/merge transactions. | All creation, transport, erosion and deposition. |
| Geological history | Formation time, deformation, burial/exhumation and temperature history at the resolution required by a selected diagnostic. | Geological products and validation. |
| Solver fields | Velocity, pressure/stress, strain rate and accumulated strain, thermal fields and solver boundary/reference data. | Mechanics and state update. |
| Surface and load state | Rock surface, sediment thickness, water/ice load where relevant, compaction state, reference column and prior support response. | Vertical response, hydrology and terrain. |
| Numerical state | Mesh/partition, timestep, transfer operators, tolerances, physical versus numerical regularisation, cache identities, accepted-step receipt. | Execution and reproducibility. |

A passive tracer is not automatically a parcel with conserved mass. A birth age is not a cooling age. A computational node is not a permanent geological entity. Intensive-property interpolation is not conservation of an extensive quantity. These distinctions are explicit in the pre-study’s material and diagnostic links. [[R04](#research-basis), P02/P05/P11/P14]

### 3.2 Minimum interface contract

Each exchange carries the quantity, units, sign/frame, spatial support, physical start/end time, intensive/extensive classification, material/source identities, uncertainty or applicability status, and whether the result is supplied, generated, numerically derived or independently validated. An interface also names the receiving approximation: converting a three-dimensional stress field into a reduced load is not a neutral file conversion.

A future step result should conceptually contain a candidate state, material and energy transfers, explicit surface contributions, events, unresolved conditions and error diagnostics. The accepted state remains unchanged until validation succeeds. This is a data contract for future coding—not a requirement to add a new general scheduler or plugin framework.

### 3.3 Canon and generated detail

Keep authored constraints in a separate world profile with hard/soft status and uncertainty. Do not optimise the physical parameters against a desired mountain outline and then use that same outline as independent validation. A compatibility study can be reported honestly as an inverse/constrained scenario. It must be accompanied by tests that were not constructed around the Diadem.

Procedural fine detail remains permissible. Label it as procedural, physically resolved or interpolated, retain its seed and scale, and prevent decorative detail from silently altering scientific drainage, loads or conserved resources. If fine detail is promoted into physical geometry, it becomes a changed model state that needs affected calculations and accounts to be revisited.

<a id="parameter-separation"></a>

### 3.4 Parameter separation without a customisation feature

**Scope.** Keep scenario-dependent physical values outside new solver logic so supported values can be exposed through future customisation without rewriting equations. For 1.0, use the selected Earth-like profiles. No sliders, public override interface, arbitrary-composition engine or mandatory 2.0 feature is added to this plan.

**Minimal design.** Pass a small typed parameter record, or the relevant subset, explicitly into each kernel. Keep physical/model choices, numerical controls and execution settings separate. Record parameter names, units, source/assumption, applicable law and tested range when established. A parameter may describe a scalar, spatial field or material law; do not flatten a variable viscosity or composition model into one universal constant. Do not build a general configuration framework.

**Defaults and identity.** Keep defaults together in named, versioned Earth-like material/case profiles, using only values selected through the existing scientific gates. Validate units, finite values, required fields and combinations supported by the chosen laws; missing required knowledge must not trigger invented defaults. Resolve and freeze the complete profile before computation and record its content identity with the run. No new numerical defaults are chosen here.

**Propagation and reuse.** Changing an input must recompute its affected derived properties and invalidate dependent scientific results. Changing only runtime parameter values need not recompile an unchanged expression, but must not reuse stale results. Record derived-value provenance. A future composition or mantle-flow control can expose only behaviour represented by a supported law: parameter separation does not itself supply new chemistry, mantle physics or scientific validation.

**What stays fixed.** Mathematical constants and coefficients fixed by an equation need not become world settings. Unit conventions remain explicit. Numerical tolerances, overflow bounds, safety limits and source/checkpoint verification are not ordinary planetary customisation controls. Existing source-bound implementations, values and histories stay unchanged unless separately authorised; do not silently repin or widen them.

**Acceptance in existing work.** W00 selects the profile; W01 and later kernels consume it. During future implementation, check unchanged Earth-like results when values are merely moved out of code; explicit versus default-profile agreement; invalid-input refusal; correct propagation and cache invalidation; and persistence of the exact resolved profile through restart. These extend existing case/identity checks, not a new simulation or test programme. Broader user customisation remains future work.

<a id="equation-plan-and-gaps-to-close"></a>

## 4. Equation plan and gaps to close

### 4.1 Retained equation-to-method map

The existing equation IDs remain authoritative navigation labels. Inclusion below is not unconditional selection of every equation or software mode. [[R04](#research-basis)]

| Process / equations | Planned use | Method study and place in the work |
| --- | --- | --- |
| P01 / E01–E02 | Rigid and relative/boundary-frame motion. | F01/O01; W01–W02. |
| P02 / E03 | Birth, ageing and retirement of oceanic material. | F02/O02; W02 and W06. |
| P03 / E04 | Explicit thermal/feature initial conditions; half-space cooling as a restricted reference. | F03/O03; W01 and W03. |
| P04 / E05–E09 | Mass, creeping-flow mechanics, heat, creep and coupled solver structure. | F04–F07/O04–O07; W07–W08. Yield/free-surface closure is additional work. |
| P05 / E10–E11 | Material trajectories and intensive projection. | F04/F06/F07; W02/W07. Extensive transfer must separately satisfy E23. |
| P06 / E12–E13 | Uniform elastic flexure and analytical/spectral reference. | F08/O08; W04. Variable rigidity and other boundaries are later extensions. |
| P07 / E14–E15 | Solid-preserving compaction and restricted age–depth response. | F09/O09; W03/W09. Thermal depth is an alternative to resolving the same support, not an extra term. |
| P08 / E16–E17 | Prescribed listric geometry and constant/divergence-free advection check. | F11/O11; W05. Not the general deforming crust thickness law. |
| P09 / E18 | Acyclic accumulation without unresolved storage. | F11/O11; W09. Real lakes need an additional storage/discharge law. |
| P10 / E19–E21 | Restricted stream-power and diffusion reference models. | F10/O10; W09. Not a drop-in replacement for Atlas’s material-aware erosion. |
| P11 / E22–E23 | Sediment and finite-volume/remapping accounts. | F12–F13/O12–O13; W02/W09/W11. Transport closure remains required. |
| P12 / E24–E25 | Conditional elastic-slip diagnostic. | F14–F15/O14–O15; W08/W10 only if needed. Not million-year plastic deformation. |
| P13 / E26 | Conditional equilibrium/property calculation. | F16/O16; W08/W10 after pressure–temperature–composition validity. |
| P14 / E27 | Conditional thermal-history observable. | F17/O17; W10 after trustworthy material histories. |
| P15 / E28 | Single-owner conversion of rock motion and surface processes into elevation. | W04–W10; connecting identity, not a complete physical solver. |

### 4.2 Core equations the plan builds around

**Motion and its limits — E01–E02.**

$$\mathbf v(\mathbf r)=\boldsymbol\omega\times\mathbf r,\qquad \mathbf r_{n+1}=\mathsf R_{n+1,n}\mathbf r_n$$

$$\Delta\mathbf v=\mathbf v_R-\mathbf v_L,\qquad v_n=\Delta\mathbf v\cdot\hat{\mathbf n},\qquad \mathbf v_{a,b}=\mathbf v_a-\mathbf v_b$$

Position is m, angular velocity rad/s and velocity m/s. Finite rotations are ordered. Plate-relative motion cancels a common frame velocity; trench-relative influx still needs the moving boundary. Whole-planet parameters and geological-time conversions must be explicit. [[S01][url-008]; [S03][url-009]]

**Added planning relationship N01 — deforming crustal thickness.** Derived by vertically integrating mass conservation for a selected column representation:

$$\partial_t(\rho_c H_c)+\nabla_h\cdot(\rho_c H_c\mathbf v_h)=s_{add}-s_{remove}$$

For constant density and no sources, $DH_c/Dt=-H_c\nabla_h\cdot\mathbf v_h$. Here $H_c$ is m, $\rho_c$ kg/m³, and the sources are kg/(m²·s); the horizontal velocity is the consistently thickness/mass-weighted column transport velocity. Layered or vertically sheared columns need their integrated flux, not an arbitrary surface velocity. Uniform extension at areal strain rate $\theta$ gives $H_c(t)=H_{c0}e^{-\theta t}$; shortening reverses the sign. Variable density, underplating, erosion and three-dimensional transport require their explicit terms. This is not E17’s purely advective thickness equation except under its compatible constant/divergence-free assumptions. [[R04](#research-basis), E05/E17/E23; derived here]

**Added planning relationship N02 — moving-boundary material flux.**

$$\dot M_{out}=\int_{\Gamma}\rho H(\mathbf v-\mathbf v_b)\cdot\hat{\mathbf n}_{out}\,ds$$

For a vertically integrated material layer, the result is kg/s. It provides the accounting for surface-domain retirement, ridge creation and regional export, but it does not prescribe productivity, accretion efficiency or slab forces. Sources and sinks need physical event identities. Crust and lithospheric mantle have separate thicknesses and ledgers. [[R04](#research-basis), E02/E05/E23; derived here]

**Mechanical baseline — E05–E08.**

$$\nabla\cdot\mathbf v=0,\qquad -\nabla p+\nabla\cdot(2\eta\mathsf D)+\rho_b\mathbf g=\mathbf0,\qquad \mathsf D=\tfrac12(\nabla\mathbf v+\nabla\mathbf v^T)$$

$$\rho_0 c_p(\partial_tT+\mathbf v\cdot\nabla T)=\nabla\cdot(k_T\nabla T)+H_T$$

This is an explicitly restricted incompressible/Boussinesq comparison, not every geodynamic formulation. Stress/pressure is Pa, viscosity Pa·s, heat production $H_T$ W/m³, conductivity W/(m·K), and temperature K. A density used for buoyancy must not silently change the conserved mass density. Constant-viscosity tests precede temperature/strain-dependent creep. Compressibility, latent/shear/adiabatic heating, elasticity and yield need named additions when relevant. [[S10][url-013]; [S11][url-016]]

**Yielding is a closure gate, not an omitted term.** The proposed first nonlinear mechanical family is viscous creep with a dimensionally explicit pressure-sensitive yield cap. Freeze the invariant, dimensional convention, cohesion/friction law, effective-pressure/pore-pressure treatment, tensile limit, flow rule, strain history and regularisation before implementing localisation. A common effective-viscosity construction compares creep viscosity with $\tau_y/(2\dot\epsilon_{II})$, but this expression alone is not a complete plasticity model. In ASPECT’s documented conventions, the two- and three-dimensional yield formulae differ. No universal coefficients or an unreviewed pressure clamp are selected here. [[S11][url-016]]

**Load response — E12–E13.**

$$D_f\nabla_h^4w+\Delta\rho g w=q_L,\qquad D_f=\frac{Y T_e^3}{12(1-\nu^2)}$$

$$w(x)=\frac{q_0\cos(kx)}{D_fk^4+\Delta\rho g}\quad\text{for a uniform periodic sinusoidal load}$$

Deflection $w$ is downward-positive m; load $q_L$ Pa; $D_f$ N·m; $T_e$ effective elastic thickness, not crustal thickness. The comparison assumes a flat, thin, small-deflection elastic plate with uniform rigidity and no imposed in-plane stress. Spectral/analytical and finite-difference answers must use the same boundary problem. [[S18][url-017]; [S20][url-018]]

**Added planning relationship N03 — local buoyancy check.** For dry, uniform crust/mantle densities with $\rho_m>\rho_c$ and a specified common compensation reference, a local Airy comparison gives $\Delta h=(1-\rho_c/\rho_m)\Delta H_c$. It tests a restricted support response; do not add it independently to a flexural or mechanical solution already incorporating that buoyancy. Spatial rigidity, density layering and water replacement require the appropriate different load operator. [Derived hydrostatic column balance; compare [S18][url-017]]

**Surface accounting — E28.**

$$\partial_t h+\mathbf v_h\cdot\nabla_hh=v_z+\mathcal D-\mathcal E$$

All right-hand rates are vertical thickness rates in m/s; $h$ is upward-positive. A normal erosion speed requires geometric conversion. Downward deflection contributes through its material derivative only if not already included in $v_z$. This identity does not by itself supply a free-surface traction condition, erosion law or sediment-distribution law. [[R04](#research-basis), P15]

### 4.3 Closures that must be selected explicitly

| Decision | Proposed route | What must be fixed before its work package can claim the process |
| --- | --- | --- |
| C01: mechanical strength/localisation | Newtonian reference, then a documented creep plus pressure-sensitive yield family. | Invariants, constitutive parameters and evidence, pressure/tension treatment, flow rule, weakening and mesh-independent regularisation. |
| C02: surface mechanics | Choose one free-surface method for M; retain a reduced flexural path for K. | Stress boundaries, surface motion, buoyancy reference, mesh strategy and stabilisation. Sticky-air or a height field is not automatically equivalent to a true free surface. |
| C03: oceanic production/recycling | Birth and sink fluxes from moving boundaries, explicit productivity and accretion parameters. | Crustal thickness/density and thermal state of new material, extraction/recycling reservoir and transfer destination. |
| C04: subduction/collision transition | Prescribed, source-visible transition rules first. | Polarity, dip/history, entry of continental material, flux partition, slab/overriding response and unsupported-event refusal. |
| C05: water and sediment | Start with explicit runoff and a restricted transport regime, then add lake/storage and deposition where needed. | Erosion law, entrainment/capacity or settling closure, porosity, finite supply, outlet law and physical closed-basin handling. |
| C06: magmatism | Reduced source-to-emplacement account, conditional on a selected scenario. | Source/rate, intrusive/extrusive/reservoir fractions, volume-to-mass conversion, footprint/geometry, thermal and load effects, independent calibration. Equilibrium melt fraction is not eruption flux. |
| C07: thermal/vertical ownership | Select resolved temperature-density support or a documented reduced cooling/subsidence relationship. | Reference state, valid age range, material/compaction model and all loads already included. Never apply both alternatives to the same effect. |

These are bounded scientific decisions attached to later packages, not permission to fill missing science with defaults. The plan remains usable because each capability has a deliverable and stopping condition; it does not pretend the pre-studies already provide a complete closure set.

<a id="work-packages-and-dependency-gates"></a>

## 5. Work packages and dependency gates

Each W-package ends with a reviewed evidence record. Any failed gate blocks its dependent capability, but not unrelated analytical work. Parameters used to obtain a fit must be separated from withheld validation data. The foundation status below is already delivered; remaining work is subject to its scoped development and execution requirements. This document edit authorises no simulation or benchmark.

### W00 — Freeze the scientific case and evidence rules

**Question:** what claim is the next experiment actually testing? Produce a short case contract identifying Mode K or M, domain and regime, equations, initial/boundary data, units, physical duration, numerical representation, output quantities and explicit exclusions. Register analytical expectations and failure cases before implementation.

Create three distinct evidence sets: exact/manufactured verification, analogue/observational validation, and Diadem compatibility. Where a published benchmark is used, record the exact setup, source version, input permissions, measured observables and uncertainty. A graph or table in a paper must be acquired and interpreted explicitly; merely citing its title is not an executable fixture.

**Output/gate:** one reviewable case specification with a physical question and quantitative acceptance procedure. Add the compact execution card from [the optimisation reference’s execution card](OPTIMISATION_REFERENCE.md#execution-card): candidate task independence, state ownership, cost/memory estimates, cache identities, equality policy and applicable PF/PT checks. Select finite resources for the specific proposed experiment; unresolved values are not unlimited. No production integration or universal configuration framework.

### W01 — Coordinates, rotations and initial geological fields

**Dependencies:** W00. **References:** P01/P03, E01/E02/E04, F01/F03.

Establish regional east/north/up and spherical Cartesian conventions with explicit conversion at legacy x-east/y-south interfaces. Implement future reference tests for finite rotations, composition order, inverse motion and reference-frame changes. State geometric and area errors separately from the physical model’s uncertainty.

Define a compact world/case description for crust types, layers, faults, weak zones and thermal profiles. Seeded generation may create initial plates/weakness patterns under declared priors, but cannot embed the desired final mountain surface. Sampling at a new grid must not move the underlying feature or silently supply unsupported material.

Use the parameter separation in Section 3.4: kernels receive a frozen, identified Earth-like profile rather than scattered physical literals. This is ordinary input design inside W01 and subsequent kernels, not a new framework or a user customisation feature.

**Deliverables:** conventions, pure initial-condition sampler, small known geometries and rotation/profile fixtures. **Gate:** rigid distances and zero strain, side/trace reversal, seam/pole tests for spherical primitives, unit/time round trips and correct thermal boundary limits. These tests validate representation, not the selected plate history.

### W02 — Conservative material history and boundary events

**Regional completion (17 September 2026):** the remaining representation, motion
and event operations are delivered on ColumnGrid1D. The verification case
`cases/w02_completion.json` binds equations, coverage, immutability, conservation,
formation history, cold restoration and optimised defaults. All 488 tests pass on
the recorded Linux runtime, including 78 new cases. This closes implementation of
the regional contracts, not every geometry or scientific validation gate.
The prior fixed-grid subsection below records the earlier delivery state.


**Delivered fixed-grid portion (17 September 2026):** regional open/closed transport
now has cohort partial thicknesses, formation-time metadata, explicit exterior
composition, and parent-bound prescribed transfer receipts. The sum of cohort
quantities is the total; no independent total-density constraint is claimed.
Self-contained snapshots preserve histories and zero-volume catalogue entries.
See `cases/material_transport.json` and the existing scientific case notes.
That earlier remaining remap/motion/ownership work is supplied by the regional
completion above. General planetary geometry and predictive forcing are not supplied.


**Delivered increment:** `RegionalGrid1D`, `TransportBoundary`, `advect_regional`
and timestep advice now supply fixed-grid, constant-density one-field transport.
Compiled MC-limited MUSCL/SSP-RK2 is the new regional default; first-order upwind and
independent references are explicit. The two schemes have distinct identities and
CFL/accuracy envelopes. Source-reservoir labels are provenance, not a transported
mixture or full history. Remaining W02 responsibilities below are still outstanding.

**Dependencies:** W01. **References:** P02/P05/P11, E03/E10/E11/E23, N01/N02; F02/F04/F06/F07/F13.

Track material identity separately from plate identity and mesh identity. Move material, record birth/removal, and transfer extensive quantities conservatively. Treat particle-to-mesh intensive projection separately. Establish thickness change from area deformation under constant-density analytic cases before variable properties or mixed layers.

Use shared boundaries with explicit side ownership and junctions. Supported ridge opening, subduction retirement, split/merge and active/inactive transitions become events with before/after geometry and mass/area accounts. Do not cure overlaps by deleting material, allocate the same volume to two plates, or reset history when a plate changes identity. Closed-world area coverage must remain valid; regional external exchanges must remain visible.

**Deliverables:** material/event schema, boundary-account reference, moving-point and column tests. **Gate:** known extension/shortening, sharp tagged-material advection, birth-age history, reversible motion where physically reversible, explicit sinks, and unchanged totals under a remap-only step. Event discovery itself remains a declared rule, not a force prediction.

### W03 — Thermal evolution, lithosphere age and compaction

**Dependencies:** W01–W02. **References:** P03/P07, E04/E07/E14/E15; F03/F09.

Begin with one-dimensional conduction and half-space cooling as a limiting check. Compare a finite plate with prescribed deep and surface temperatures where the half-space approximation is no longer appropriate. Handle zero thermal age explicitly: a ridge initial condition is not obtained by numerically dividing by zero or introducing an undocumented minimum age.

Derive or select the thermal-density/support relationship consistently. A reduced age–depth relation is an alternative calculation with its own calibration range. Compaction must conserve solid material while changing bulk volume and load; fixed-area decompaction identities cannot be reused blindly in laterally deforming columns.

**Deliverables:** thermal/age/compaction specification and references; named density and support ownership. **Gate:** thermal boundary limits, conserved solid thickness, heat accounting for the selected equation, time/grid refinement and independent bathymetry/heat-flow or column comparisons once suitable data are selected. No duplication of thermal subsidence and density-driven buoyancy.

### W04 — Vertical support from a physically defined load

**Dependencies:** W01, with W02/W03 when material or thermal loads are used. **References:** P06/P15, E12/E13/E28, N03; F08/F09.

First solve uniform, small-deflection flexure for a periodic sinusoid and a local-isostatic limiting case. Derive the load in Pa from a stated reference column, density contrast and replacement medium; thickness alone is not a load. Then test domain enlargement, nonperiodic boundaries and only subsequently variable rigidity with the correct operator.

Record whether a result is total deflection from the reference state or an increment. Repeatedly adding the total deflection at every step is an error. Effective elastic thickness is a constitutive parameter, not automatically crustal thickness or actual full lithospheric thickness.

**Deliverables:** load-construction and support contracts, analytical solution fixtures and candidate numerical method. **Gate:** sinusoid amplitude/sign, superposition where linear, convergence with domain/grid and independent load response. A model passing this gate explains response to a load, not where the mountain or magma load originated.

### W05 — First coupled mechanism: regional extension

**Dependencies:** W02 and W04; W03 when thermal/compaction effects are in scope. **References:** P08/P15, E16/E17/E28 and N01; F11/F08.

Recommended initial case: a prescribed detachment geometry and displacement with no Diadem shape targets. Begin with constant horizontal velocity and a translated thickness profile. Where the velocity field has nonzero divergence, use the appropriate conservative thickness law and sources, not the constant-translation check.

Connect the physical column/load change to a single vertical-response treatment. Measure hanging-wall displacement, basin subsidence, footwall/shoulder response, crustal thinning and boundary export. Treat the listric geometry as prescribed: this experiment does not prove spontaneous fault initiation or stress-controlled localisation.

**Deliverables:** mechanism specification, independent reference implementation, component-versus-coupled comparison, and an analogue/observational challenge plan. **Gate:** accounts close; changing grid, timestep and domain does not control the qualitative result; uplift/subsidence signs and amplitudes match justified expectations. Do not interpret success as acceptance of collision or of History A.

### W06 — Spreading, passive margins and changing plate histories

**Dependencies:** W02–W05. **References:** P01–P03/P07, E01–E04/E15 and N02; F01/F02/F03/F09.

Extend the kinematic regime to selected breakup and ocean-birth events. Compute creation at moving ridges, track material age and cool it. Test asymmetric spreading, ridge migration and explicit plate-boundary transitions; distance to today’s ridge is not a general formation-age estimator.

Keep continental thinning and new oceanic material distinct. A passive margin inherits its rift and thermal history after the active ridge moves away. Generated motion proposals must obey geometric/flux constraints, carry their priors and be rejected or revised when inconsistent. They do not become physically force-balanced because they produce complete polygons.

**Deliverables/gate:** coherent birth/age/cooling history with finite material sources, independently verified motion and boundary coverage. Expansion to spherical surfaces requires spherical area/normal tests, not a planar result relabelled global. Thermal depth and mantle/lithosphere accounts must remain consistent.

### W07 — A selected regional mechanical backend

**Dependencies:** W00–W03; W04 supplies checks of loading, not automatically an added response. **References:** P04/P05/P15, E05–E11/E28; F04–F07.

Study one explicit mixed velocity–pressure formulation. Start with constant-viscosity analytical/manufactured velocity fields, pressure-reference handling, rigid-body modes and boundary traction. Compare candidate discretisations against those cases before adopting a framework architecture. Add variable viscosity and heat transport only after that baseline passes.

C01 and C02 must close before strain localisation or surface mechanics is claimed: pressure convention, creep/yield law, physical strength/weakening parameters, tensile behaviour, free surface, stabilisation and mesh/particle transfer. Use reference pressure plus the solved perturbation consistently when a creep or thermodynamic law needs absolute pressure.

**Deliverables:** one selected formulation, boundary/constitutive specification, verified reference solver and public benchmark definition. **Gate:** force/divergence/thermal residuals, independently calculated fields, sharp material contrasts, convergence and mesh-independent quantities of interest. A low nonlinear residual cannot excuse a numerically defined shear-zone width. If a reduced K-mode answers the question sufficiently, M is not mandatory for that particular case.

### W08 — Shortening, transform/oblique motion, subduction and magmatism

**Dependencies:** W02/W04/W06, and W07 where mechanical response is claimed. These are separate cases, not one universal tuned recipe.

**Shortening/collision:** first verify uniform shortening and thickness/mass conservation; then supported underthrusting, distributed strain, loading/foreland response and material accretion. Test finite strain and boundary effects. A thickened crust plus a buoyancy response does not automatically reproduce a fold-and-thrust belt; fault localisation and structural geometry require the relevant mechanical or reduced closure.

**Transform/oblique:** begin with pure shear and translated markers, then prescribed bends/stepovers and oblique motion. Test local compression/extension, offset histories, volume balance and frame invariance. Optional E24/E25 elastic responses serve a diagnostic, not an accumulated million-year plastic model.

**Subduction:** use a prescribed slab/plate kinematic benchmark with a mechanically computed wedge as the first thermal-mechanical reference. A published community benchmark explicitly uses this mixed approach; it tests boundary and rheological treatment, not spontaneous global plate formation. Follow with a buoyant-slab/free-surface benchmark only if the claimed response needs it. The methods literature warns that viscosity averaging and artificial surface layers can materially change results. [[N-S01][url-019]; [N-S02][url-020]]

Close C03/C04 before geological histories: slab polarity/geometry/time, oceanic material sinks, accretion versus erosion, trench migration, overriding shortening/extension, and collision/subduction-cessation rules. Back-arc opening and rollback remain conditional until separately tested. A valid boundary projection does not choose which plate subducts.

**Magmatism:** close C06 before producing volcanic mass. The mantle/crust/reservoir budget must reconcile extraction, intrusive addition, eruption, storage and external export. Melt fraction from E26, if later used, is not a rate or pathway. Reduced emplacement needs a calibrated rate and geometry with validity limits; no arbitrary cone is to be labelled mechanically predicted. Caldera collapse and hotspots are optional scenario packages with their own volume, thermal and load accounts.

**Deliverables/gate:** separate regime evidence records with clear prescribed/predicted distinctions, geological observables and cross-regime transition tests. An unsupported case stays unsupported rather than receiving generic mountain uplift. Full 1.0 claims require all core regime gates, not just the successful extension case.

### W09 — Necessary surface response and source-to-sink accounting

**Dependencies:** an accepted tectonic mechanism from W05/W06/W08; W03/W04 for feedback. **References:** P09–P11/P15, E18–E23/E28; F10–F13.

Use explicit water forcing initially; solving global climate is not a prerequisite for a bounded terrain experiment. Keep physical topography separate from any surface altered solely for routing. Genuine closed basins need storage, overflow/evaporation/infiltration treatment where relevant; E18’s accumulation is not transient water dynamics.

Use the linear, fixed-receiver stream-power update and sinusoidal hillslope diffusion only as narrowly defined reference calculations. Before actual basin morphology is claimed, close C05: material-aware incision, finite sediment source, entrainment or capacity/settling law, deposition, porosity and outlets. E22 balances material but does not choose its flux. Preserve origin and history through transport and compaction.

**Deliverables/gate:** tagged sediment pulse through a closed/open catchment; dry/no-forcing limits; receiver changes; lake conservation; geometry/coupling refinement; and independent profiles/stratigraphy where available. Load-feedback tests must not apply the same sediment, thermal or isostatic effect twice. This mechanism coupling is not the full eighteen-category production chain.

### W10 — Independent realism challenge and uncertainty

**Dependencies:** the relevant mechanism gates, with W09 for final-landform claims. Separate verification from validation and from visual preference. Reserve material/parameter regions or independent data that were not used for calibration.

Use a ladder: exact/manufactured cases; published multi-code benchmarks; analogue deformation experiments; then geodetic/geological observations appropriate to the selected mechanism. The identified analogue shortening/extension benchmark is a candidate source, but this plan has not acquired its full numerical setup or licensed data. [[N-S03][url-021]] Cross-code agreement with shared equations/data is numerical corroboration, not complete independent physical proof.

Quantities of interest include surface and basement displacement, crustal thickness, strain/slip distribution, heat flow, basin volume, mass export, drainage structure and stratigraphy. Thermochronology is optional only after material thermal histories exist. Compare uncertainty and sensitivity to forcing, boundaries, strength, effective elastic thickness and erosion parameters—not only one best-looking run.

**Deliverables/gate:** accepted within a stated validity envelope, rejected, or unresolved. Never equate ensemble spread with calibrated uncertainty by default. Retain failed explanations. Only after independent credibility is established does a Diadem constraint-compatibility test assess its authored landforms.

### W11 — Matched-error optimisation, multiresolution and scale

**Dependencies and timing:** W00 defines the question and finite envelope. W11 is a cross-cutting workstream, not a blanket wait for every physical model to pass. Its design reviews begin in W01–W04. An enabling performance study may occur alongside W05–W10 after the relevant numerical reference/invariants exist, especially when needed to make an authorised realism experiment practical. Broad scale and production claims still require the relevant W10 physical acceptance. All performance execution remains separately authorised.

Start with measured repeated setup, geometry decoding, projection rebuilds, per-object overhead and material-history size. Prioritise bounded reuse, contiguous arrays, batched work and appropriate ordered algorithms. Choose implicit updates or approximations only through a new numerical/model identity. Compare total cold/warm cost, memory, storage and physical error; a faster kernel alone is insufficient.

Then test adaptive support, conservative remapping, nonuniform layers, spherical meshes and cross-partition fluxes. Coarse/fine regions need explicit exchange rules and boundary closure; a halo alone cannot isolate a globally connected river or stress field. Changing partitions must not move geology, reset history or change accepted results outside the declared tolerance.

**Deliverables/gate:** evaluated PF decisions, per-calculation execution cards, applicable PT01–PT14 results and, after relevant physical acceptance, a feasible measured workload envelope with independently checked scale transfer. No universal grid or machine is selected now. One-metre outputs remain eligible; output density and process resolution remain separate. GPUs, MPI and large symbolic frameworks are conditional choices, not mandatory next tasks.

### W12 — Production integration and release acceptance

**Dependencies:** relevant W10 physical gates and W11 resource/scale gates. Only now select production adapters into Atlas’s wider graph and retained spatial outputs. Reuse existing execution, source identity and recovery systems where suitable; do not build another chain of copied module globals merely to attach the new work.

A separately identified producer must publish the equation/closure version, inputs, numerical policy, declared scope, output identities, material/load accounts and restart dependencies. Historical R5 controls are not rebadged as checkpoints of changed physics. Public fixtures and a reproducible compatible runtime must accompany any independent-execution claim.

**Release gate:** supported regime matrix, scientific evidence, finite resource envelope, coherent checkpoint/recovery drill, clean-versus-incremental comparison and truthful documentation. Code approval, physical acceptance and fictional canon remain separate. Main-branch publication requires its own coding/publication scope; this documentation consolidation changes no numerical implementation.

<a id="coupling-timestep-and-state-acceptance-policy"></a>

## 6. Coupling, timestep and state-acceptance policy

### 6.1 A future physical step

The following is conceptual execution order, not runnable code or a production instruction:

1. Verify the accepted starting state, selected laws, sources, frame/time and boundary inputs. Choose a candidate interval limited by physical events, numerical accuracy and transport constraints.
2. Locate the next plate/boundary event. Split an interval at a topology or forcing discontinuity rather than averaging through an unrepresented event.
3. Evaluate kinematics and regional boundary forcing. In M-mode, solve the coupled mechanics/thermal problem with its declared boundary conditions and pressure reference.
4. Construct a candidate material update: horizontal/vertical movement, thickness, birth/subduction/accretion and associated heat/material exchanges. Preserve source identity and finite accounts.
5. Evaluate the selected vertical response and physical surface motion. Include only effects not already owned by the mechanics or previous support state.
6. Subcycle the necessary water/sediment/compaction processes. Exchange integrated transfers at common physical times, not by assuming their numerical timesteps are equal.
7. Where loads, geometry or temperature feed back strongly, iterate the selected coupling or reduce the macro interval. Compare one interval with a refined or reversed-order reference to expose splitting error. Do not assume a chosen splitting order is harmless.
8. Re-establish affected geometry/connectivity and verify accounts, field bounds, residuals, accuracy estimates and event consistency. On failure, reject the candidate; preserve the accepted state and the failure evidence.
9. Commit one coherent accepted state and receipt. Cache only quantities valid for that state, and save restart information at a policy-defined cadence distinct from scientific output sampling.

### 6.2 Timesteps are selected by meaning, not calendar convenience

Use physical forward time internally with explicit conversion from geological age and declared year length. Transport may require a Courant constraint; an implicit thermal/incision solver may be stable at a larger interval while still inaccurate. Localisation, slab motion, free surfaces and topology events can impose different limits. Choose the smallest applicable constraint and perform temporal-refinement checks for the coupled quantities of interest. [[R04](#research-basis); [S27][url-022]; [S28][url-023]]

Do not fix one timestep for tectonics, rainfall, sediment, thermochronology and rendering. Nor does an existing 256-interval limit imply a physical duration. Any future successor that changes a computational bound needs its own scoped numerical/resource evidence; this plan does not change the retained native boundary.

### 6.3 Ownership of vertical and thermal effects

| Effect | Ownership rule |
| --- | --- |
| Fault/continuum movement | One selected K or M source for each represented displacement contribution. |
| Isostatic/flexural response | One reference state and response operator; do not add local Airy support to the same response already in flexure or M. |
| Thermal subsidence | Resolved thermal-density support or a reduced age-depth model for that effect, never both. |
| Sediment | Deposition changes thickness; compaction changes bulk volume; loading changes support. They are related but distinct updates. |
| Magma | New mass, emplacement volume and heat are linked accounts, not independent terrain decorations. |
| Erosion | Surface removal and unloading are distinct, with shared material/account identities. |
| Visual refinement | Remains separate from scientific state unless explicitly promoted and re-evaluated. |

<a id="numerical-and-computational-design"></a>

## 7. Numerical and computational design

### 7.1 One place for detailed optimisation decisions

The [consolidated optimisation reference](OPTIMISATION_REFERENCE.md) is the sole maintained home for execution, cache, memory/storage, native-language and optimisation-study detail. This plan states the scientific obligations and where those decisions enter the work. Do not copy the reference back into a new supplement.

| Responsibility retained in the plan | Detailed specification in the reference |
| --- | --- |
| Per-process independence and shared-state ownership | [Process placement](OPTIMISATION_REFERENCE.md#process-placement) and [execution contract](OPTIMISATION_REFERENCE.md#execution-contract) |
| Complete identities, bounded reuse and invalidation | [Cache contract](OPTIMISATION_REFERENCE.md#cache-contract) |
| Host/device working sets, chunks, palettes, streaming and coherent recovery | [Storage contract](OPTIMISATION_REFERENCE.md#storage-contract) and [volumetric representation](OPTIMISATION_REFERENCE.md#volumetric-storage) |
| Python orchestration and selective native numerical work | [Language and native boundary](OPTIMISATION_REFERENCE.md#native-boundary) |
| All PF01–PF26 candidate families and PT01–PT14 checks | [Candidate register](OPTIMISATION_REFERENCE.md#candidate-register) and [measurement and tests](OPTIMISATION_REFERENCE.md#performance-tests) |
| O01–O17 scientific-software methods and MC01–MC39 transferable patterns | [Scientific methods](OPTIMISATION_REFERENCE.md#scientific-methods) and [Minecraft patterns](OPTIMISATION_REFERENCE.md#minecraft-methods) |
| All 84 named mod records and their limitations | [Screening index](OPTIMISATION_REFERENCE.md#mod-screening) |
| One compact execution record per selected case | [Inline execution-card specification](OPTIMISATION_REFERENCE.md#execution-card) |

### 7.2 Principles that remain binding

**Keep three representations distinct.** A small analytical/high-accuracy reference verifies the equation. Process state uses arrays, sparse operators and justified precision. Material/provenance accounts retain stable extensive quantities and histories. Preserve the historical fixed-quantum routes; any new conservative representation needs explicit conversion, residual, overflow and reproducibility rules. A floating solver is not permission to silently round away mass.

**Design efficiently from the outset.** Use pure/batched interfaces, explicit ownership, finite working sets and valid cache identities from the first kernel. A serial reference is not a single-threaded production decision. Verified enabling acceleration may support a realism experiment before that experiment establishes physical adequacy. Production still waits for the relevant physical and resource gates.

**Do not alter the scientific question to obtain a performance result.** Keep E execution, N numerical, M model-reduction and S scale/representation changes distinct. Changing precision, a random stream, a drainage rule, a timestep or a mechanical law requires the corresponding numerical/scientific review. Camera-based culling applies to display, not to hidden material's physical influence.

**Reuse what exists.** The remake already has arrays, batching and immutable flexural-operator reuse. Measure a current cost before adding another cache, scheduler, native language or voxel framework. Keep historical source/checkpoint safeguards unchanged.

### 7.3 Resolution, duration and resources

Let $A$ be a sampled surface area and $\Delta x$ a nominal square-cell spacing. Approximately $N=A/(\Delta x)^2$ samples are required; a uniform volume scales with $(\Delta x)^{-3}$. These are count estimates, not runtime predictions. A world need not store every layer at every output resolution or every point at every historical time.

Select process resolution from error and represented physics; select output detail from purpose and budget. Use compact features, layer columns and history sampling where justified. For a future planetary route, pick a true spherical area/edge representation and test metric distortion, seams, poles and conservation. A full climate/tectonic solve at 1 m is not implied by a metre-sampled terrain export.

Before each authorised benchmark/run, fill total parent-plus-worker peak RAM, scratch/persistent/staging/recovery storage, wall-time ceiling, cancellation policy, available cores, dependency versions and recovery requirements. The plan deliberately invents no owner hardware specification or deadline. Unfilled fields block a production claim, not the scientific planning work.

Before selecting a mesh, record characteristic length $L_0$, velocity $U_0$, density, viscosity $\eta_0$, thermal diffusivity $\kappa$ and the phenomenon’s physical timescale. A viscous stress scale is $\eta_0 U_0/L_0$ and an advective time is $L_0/U_0$ when $U_0$ is nonzero. A thermal Peclet number $Pe=U_0L_0/\kappa$ identifies the relative importance of the selected advection and diffusion terms; it is a diagnostic, not a universal switch that permits dropping a term. [E06/E07; dimensional analysis]

For a chosen Maxwell material, $\tau_M=\eta/\mu$ is a useful relaxation timescale, where shear modulus $\mu$ is Pa and viscosity Pa·s. Compare the physical timescale with that material model before applying repeated elastic displacements over geological time. Real heterogeneous/yielding lithosphere cannot be reduced to one global Maxwell time. The selected constitutive model must explain why an elastic, viscous, viscoelastic or plastic approximation is appropriate. [[S39][url-024]; [R01](#research-basis)/[R04](#research-basis)]

This scale analysis provides an early feasibility/validity filter without a simulation. It also guards against importing a centimetre-scale laboratory setup or short earthquake-cycle equation into a kilometre-scale geological problem without matching the relevant nondimensional behaviour.

### 7.4 Development placement and current next step

| Work | Required performance planning |
| --- | --- |
| W00 | Define the finite case, equality/error policy, inputs, cost/memory estimate and relevant PF/PT checks. The execution card belongs with its case, not in another general-purpose document. |
| W01–W04 | Keep explicit parameters, array/batch interfaces, accepted/candidate ownership and valid setup reuse. No compulsory worker pool for a tiny fixture. |
| W05–W09 | Specify physical coupling barriers, shared-face ownership, bounded scratch and necessary enabling acceleration. Verify the numerics independently of physical acceptance. |
| W10 | Parallelise independent cases/diagnostics where valid. Keep stable random identities and validation separate from performance tuning. |
| W11 | Measure enabling work when needed; then compare accepted behaviour at matched error and broaden the workload envelope. No speculative whole-world speed multiplier. |
| W12 | Carry only supported backends, compatible fixtures and tested cache/recovery behaviour into production. |

The next substantive work is W04 physical load/buoyancy construction from the delivered regional material state, with W03 thermal/compaction where needed. Reuse W02 transport, cohorts, remapping and events rather than rebuilding them. Apply the existing optimised execution and resource tests during that physical increment.

<a id="verification-physical-validation-and-decision-rules"></a>

## 8. Verification, physical validation and decision rules

### 8.1 Four independent gates

| Gate | Evidence | What passing does not mean |
| --- | --- | --- |
| **V1: implementation verification** | Units/signs, manufactured/analytic solutions, conservation, field bounds and declared invalid-input refusal. | The constitutive law is true for a geological setting. |
| **V2: numerical adequacy** | Mesh/time/coupling/domain refinement, appropriate residuals, remapping/rounding error and resolved physical features. | A visually plausible field matches independent observations. |
| **V3: physical adequacy** | Withheld analogue/geophysical/geological observables and sensitivity/uncertainty within a defined regime. | Every world, scale, history or boundary condition is covered. |
| **V4: world compatibility and release** | Required authored constraints, provenance, resources, output/restart consistency and named supported capabilities. | Canon approval or an untested generic-planet guarantee. |

A common modelling assumption across two codes weakens their independence as physical evidence. Use exact checks, alternate discretisations and observations/experiments for different purposes. Software-family agreement and agreement between AI reviewers are not acceptance metrics.

### 8.2 Required verification matrix

T01–T16 remain scientific/numerical verification families. The new PT01–PT14 matrix in [the optimisation reference’s performance tests](OPTIMISATION_REFERENCE.md#performance-tests) supplies execution, cache, resource and recovery checks; passing it does not replace these physical tests.

| ID | Case | Expected quantity or invariant |
| --- | --- | --- |
| T01 | Finite rotation and its inverse | Rigid distances/area and zero strain; noncommuting composition handled correctly. |
| T02 | Common motion and trace reversal | Relative behaviour invariant; side/normal conventions preserved. |
| T03 | Constant translation / uniform extension | Translated field; $H=H_0e^{-\theta t}$ under the stated source-free approximation. |
| T04 | Birth, migration, subduction | Correct age and mass/area transfer; no double ownership or unexplained disappearance. |
| T05 | Heat diffusion / half-space / finite plate | Analytic limits, heat accounting and time/depth refinement in their valid regimes. |
| T06 | Compaction and reversal | Fixed solid mass/volume under declared density and area; correct zero-compaction limit. |
| T07 | Periodic flexure | E13 amplitude, sign and superposition; independent sparse/spectral comparison if implemented. |
| T08 | Mechanics manufactured solution | Velocity/pressure error, divergence and force residual; null-space and boundary treatment. |
| T09 | Variable strength / free surface | Viscosity/yield and surface-convergence behaviour; no mesh-only localisation claim. |
| T10 | Pure shear / oblique cases | Expected strain/mass/thickness behaviour and finite offsets. |
| T11 | Subduction benchmark | Specified thermal/mechanical observables under exactly matching boundary/rheology assumptions. |
| T12 | Incision / diffusion | Fixed-network solution and transient refinement; sinusoidal diffusion decay; no unsupported stability-to-accuracy inference. |
| T13 | Sediment and real closed lake | Tagged solid and water budgets, storage/outflow and changed routing without destructive numerical filling. |
| T14 | Coupling / remap / partition | Zero-forcing and isolated-effect checks, no double counting, geometric and extensive conservation. |
| T15 | Restart and source change | Same accepted state under the declared equality policy; refusal of stale binding or incompatible checkpoint. |
| T16 | Withheld geological case | Predetermined quantities and independent uncertainty envelope, not only fitted final topography. |

### 8.3 Threshold policy

Set acceptance thresholds before optimising or fitting the candidate. For an analytic case use absolute and relative error with physically stated normalisation; do not divide by a near-zero reference. Evaluate convergence over at least three refinement levels where practical and compare the observed order with the scheme’s expected regime. Discontinuities and non-smooth events require appropriate norms and event/location errors rather than an unjustified smooth-solution order.

For a conserved quantity, the residual is final storage minus initial storage minus integrated sources plus sinks/external export. Require exact reconciliation for a declared integer account; for floating transfers require a specified error bound and stable accounting procedure. Solver residual thresholds must be tighter than the error they are allowed to contribute, but a residual alone is not physical accuracy.

Do not invent one universal percentage for every geological observable. Tolerances must reflect numerical truncation and independent measurement/model uncertainty, recorded separately. A failed run cannot redefine its own limits after seeing the result. A changed scientific model gets a new identity and comparison, not a backdated pass.

## 9. All seventeen software families: decisions, not dependencies

| Family | Planned lesson | Disposition |
| --- | --- | --- |
| F01 GPlates / pyGPlates | Spherical rotations, shared boundaries, cached time states. | Early mathematical foundation; not a mantle-force predictor. |
| F02 GPlately | Moving ocean-material birth/age/removal; separate gridding. | Early history reference; reject hidden initial-age guesses. |
| F03 Geodynamic World Builder | Compact feature-based initial geometry and thermal/composition sampling. | Early case-definition reference. |
| F04 LaMEM | Staggered mechanics and moving material; solver/data separation. | Candidate regional mechanics reference, not a framework clone. |
| F05 ASPECT | Governing formulations, creep/yield conventions, adaptive/multigrid methods. | Closure and verification reference; advanced solvers conditional. |
| F06 Underworld | Material history versus mesh fields; batching and equation visibility. | Use narrow lessons first; UW2 and UW3 are not assumed identical. |
| F07 pTatin3D | Mixed pressure–velocity solve and matrix-free/preconditioning lessons. | Specialist comparison; incomplete earlier source access remains a caveat. |
| F08 gFlex | Load-to-deflection equations and analytical/finite-difference verification. | Early physical-support reference; FFT is a derived candidate, not a certified stable feature claim. |
| F09 pyBacktrack | Thermal subsidence and solid-preserving decompaction. | Early where needed; inverse/reconstruction workflow is not generative physics. |
| F10 FastScape family | Restricted implicit incision, ordered graph sweep and ADI diffusion. | Surface-response reference after law selection; Python/Fortran/C++ scopes remain distinct. |
| F11 Landlab | Prescribed extension and TVD; routing/depression-policy separation. | First mechanism candidate, not blanket validation of all Landlab components. |
| F12 Badlands | Source-to-sink material, stratigraphy and controlled remeshing. | Later surface/material coupling. |
| F13 goSPL | Spherical finite volumes and explicit distributed face flux. | Scale study after a valid serial operator; no metre-scale claim. |
| F14 PyLith | Prescribed-slip mechanics, nondimensionalisation and interface constraints. | Optional diagnostic; not spontaneous rupture inferred from older papers. |
| F15 cutde | Triangular elastic response; dense/blocked/matrix-free trade-offs. | Optional diagnostic; low-rank compression is approximate. |
| F16 MAGEMin | Pressure–temperature–composition equilibrium and bounded properties. | Optional after material-state validity; not an eruption model. |
| F17 GDTchron | Independent thermal-history observables and batch histories. | Optional validation stage, not a tectonic driver. |

All entries inherit the source and version caveats of Reports 01–04. No new feature claim is based on the under-review pyBacktrack/goSPL extensions. No code or database copying is selected; a future implementation must review the exact source/data rights and required notices separately from the scientific method. [[R01](#research-basis); [R02](OPTIMISATION_REFERENCE.md#scientific-methods); [R03](#research-basis); [R04](#research-basis)]

## 10. Responsibilities across Atlas’s eighteen categories

This is an interface plan, not a task to build the whole generator now. Tectonics owns the selected deformation/material history. It should not absorb every downstream scientific responsibility.

| Category | Tectonic contribution / boundary |
| --- | --- |
| Plate tectonics | Plate/block motion, boundary history, supported regional deformation and material birth/recycling. |
| Geology | Material structure, deformation, thermal/magmatic histories and exposure; geology supplies density/strength/stratigraphy laws. |
| Topography and topology | Rock displacement plus explicit surface/support contributions; drainage topology remains a distinct physical/numerical responsibility from plate topology. |
| Hydrology | Geometry and structural changes, defined loads and boundary fluxes; no universal water dynamics implied by accumulation. |
| Political borders | Later constraints/opportunities only; physical deformation does not generate legitimate political ownership. |
| Settlements | Later terrain/ground opportunity and hazard context; not automatically realised sites. |
| Populations | Indirect downstream support/constraints; no tectonically determined population count. |
| Biomes | Indirect elevation/material and history forcing through climate/soil/ecology. |
| Climate | Continental positions, elevation and land–ocean geometry where used; full atmospheric circulation is separately scoped. |
| Precipitation | Explicit forcing for the test; later climate interaction, with intervals and units preserved. |
| Plant and animal ranges | Indirect habitat/barrier/history information, not biological coefficients inferred from geology. |
| Soils and ground conditions | Parent material, thermal/structural setting and disturbance; soil water/root/failure laws remain explicit. |
| Erosion and sediment transport | Tectonic forcing and exposed materials in; removal, transfer, deposition and unloading out. |
| Seas and coastal processes | Basin/coast/seafloor movement and selected boundary histories; water/sediment/sea-level conventions remain separate. |
| Resources and land suitability | Geological/magmatic/structural evidence; occurrence and economic/extractable quantities are separate claims. |
| Land use and agriculture | Later terrain, material and water constraints, not tectonic crop or food predictions. |
| Infrastructure and connectivity | Later topographic barriers, ground stability and hazard context; no road construction in this plan. |
| Natural hazards | Active structure, strain/slip, slab/volcanic setting as inputs; event probabilities, recurrence and exposure are separate validated models. |

<a id="milestones-decision-ownership-and-risk-control"></a>

## 11. Milestones, decision ownership and risk control

### 11.1 Milestones and permitted conclusions

| Milestone | Work packages | Permitted conclusion |
| --- | --- | --- |
| M0: case contract | W00 | A specific scientific question and acceptance procedure are defined. |
| M1: representation/accounts | W01–W02 | Geometry, motion and material bookkeeping pass their stated mathematical checks. |
| M2: vertical/thermal references | W03–W04 | Selected thermal, compaction and load responses are independently verified. |
| M3: first mechanism | W05 plus a W10 challenge | A stated extensional regime is physically supported within a measured envelope. |
| M4: tectonic breadth | W06–W08 plus relevant W10 challenges | Named spreading, shear, shortening and subduction regimes are supported; failures remain visible. |
| M5: terrain response | W09–W10 | The tectonic/surface combination has credible landform and material-history evidence beyond imposed outlines. |
| M6: useful scale | W11 | Behaviour survives specified optimisation/resolution/resource conditions. |
| M7: production/readiness | W12 | Reproducible supported outputs and recovery can be delivered at the stated scope. |

Thermal/support references and kinematics can be developed in parallel after W00. Regional mechanics is a separate branch and is not a prerequisite for the first kinematic extension check. W11 execution design and verified enabling acceleration accompany the relevant packages; its production-scale acceptance remains after physical evidence. Regime tests share infrastructure but do not inherit one another’s scientific pass. W12 cannot be pulled forward by an attractive screenshot or an implementation milestone.

**Decision ownership:** Michael chooses scope, world intent and resource priorities. Future coding agents implement the agreed case; they do not change its scientific criteria to get a pass. Independent reviewers challenge equations, assumptions, evidence and reproducibility. A suitably qualified domain review is desirable at physical acceptance gates; agreement among AI systems alone is not independent experimental evidence.

### 11.2 Highest-priority risks

| Risk | Mitigation and stop condition |
| --- | --- |
| Desired landforms become the answer key | Withhold validation cases; label Diadem fitting as compatibility, not proof. |
| Reference models become an unscalable permanent backend | Retain transparent cases; estimate representation costs early; select production representation only with accepted physics and matched-error evidence. |
| More adapter/version layers hide behaviour | Narrow pure interfaces and explicit dependencies; no source-bound in-place monkey-patching as the default new architecture. |
| Load or thermal response counted twice | One contribution owner/reference and isolated-effect tests at every coupling. |
| Rigid plates are treated as undeformable continents | Explicit deforming zones, block/plate distinction and supported strain partition. |
| Numerical regularisation creates the geology | Record it as part of the method; test mesh/parameter sensitivity and physical localisation length. |
| New material/retirement corrupts history | Separate birth/deposition/cooling ages, extensive ledgers, boundary transactions and remap tests. |
| Planetary scope drives premature complexity | Spherical primitives early, useful regional physics first, global physical scale only after gates. |
| Fine output is presented as fine evidence | Preserve four resolution descriptors and procedural-detail labels. |
| Missing closures are disguised by labels | C01–C07 block their claimed processes until specified, tested and reviewed. |
| Parallel work changes the physical result | Stable work/stream identities, explicit dependencies, current boundary data and PT01/PT02/PT07; no silent event or material divergence. |
| Caches or queued work exceed resources | Byte budgets, back-pressure, ownership and PT03–PT06; no unbounded pools or metadata-only source authentication. |
| A fast result cannot be recovered | Immutable accepted state, coherent publication and PT09–PT11; shared history is not disposable cache data. |

### 11.3 Items that remain open, with a concrete resolution point

Before W00 can be signed off: select the first case’s observables, physical domain and duration, benchmark/data access and finite experimental budget; fill the relevant execution-card decisions. Estimate early memory/work and identify safe parallel units without building a runtime framework. This plan recommends extension as the first coupled case but does not authorise executing it.

Before W07: choose the mechanical discretisation and C01/C02 specifications, including solver/thread ownership and true-residual checks. Before W08: close productivity/recycling, transitions and any claimed magmatism. Before W09: choose water/storage and sediment closures. For each enabling W11 study: identify the verified numerical baseline, actual workload, hardware, error criteria and finite limits; broader W11 scale claims also require relevant W10 acceptance. Before W12: agree public runtime/fixtures, release scope, recovery and source/data licensing decisions.

These decisions are not an excuse to keep writing general plans. Each is resolved in the smallest relevant package, with the case’s equations and expected evidence in hand. Do not attempt to decide every future planetary process before implementing the first independently testable mechanism.

## 12. Next development scope and review guide

**Current next task after regional W02:** construct and verify the physical load /
buoyancy connection in W04 from actual thickness/material changes, with explicit
densities and reference columns. W03 thermal/compaction extensions remain where
needed; W05 follows only the relevant physical checks. Do not repeat the general
optimisation programme or rebuild delivered W02 infrastructure. The guidance below identifies the next physical increment, not another rebuild.


**Recommended next task:** implement W04's reference-column/load connection using W02's material inventories. Select explicit densities and reference states; verify signs, limits and independent flexural/buoyancy responses without double counting. Preserve the existing independent tests and resource contracts. Do not repeat W02 or begin full production integration before the relevant physical evidence.

For Claude or another reviewer, review this plan in the following order: (1) whether the two deformation modes are honestly distinguished; (2) whether N01/N02 and E28 close the material/surface links without double counting; (3) whether C01–C07 identify real missing physics rather than hiding it; (4) whether the proposed cases can falsify errors independently of Diadem geometry; (5) whether the core 1.0 scope and later planetary aims are realistic and distinct; (6) whether optimisation is matched to a verified equation and fixed error budget; (7) whether the P01–P15 execution map respects nonlocal/sequential dependencies; (8) whether cache identities, resource admission, random streams and PT01–PT14 tests can catch real failures. Challenge any PF candidate whose added complexity exceeds its demonstrated benefit.

A review finding should identify the section/equation, the suspected physical or numerical failure, supporting evidence and the smallest correction or verification. Competing preferences are not defects by themselves. Proposed plan changes remain reviewable, not automatic code changes.

**Bottom line:** establish coherent motion and material accounts, verify thermal/support responses, demonstrate one causal mechanism, then earn each additional tectonic regime and its surface consequences. Efficient design and verified enabling acceleration support that investigation from the beginning. Broad physical scale claims and production integration still follow independent realism evidence. This is the plan—not a claim that any future gate has passed.

## References and evidence scope

The pre-study register remains historical evidence, not a separate maintained planning file. Scientific methods remain grounded in the four pre-studies and the original three benchmark leads. Revision 2 adds PS01–PS08: targeted official documentation about execution, parallel randomness, solver reuse, storage and measurement, checked on 16 September 2026. Dynamic documentation is not a pinned or installed runtime; select exact versions before implementation. Proposed Atlas rules are design judgements, not blanket claims about those packages. No source is evidence that Atlas ran or passed a test.

**[R01](#research-basis) — Modelling capabilities and scientific methods.** Supplied Atlas pre-study, 15 September 2026. Planning evidence; not an installed or independently accepted physical model.

**[R02](OPTIMISATION_REFERENCE.md#scientific-methods) — Specific optimisation methods.** Supplied Atlas pre-study, 15 September 2026. Planning evidence; not an installed or independently accepted physical model.

**[R03](#research-basis) — Implementation feasibility.** Supplied Atlas pre-study, 15 September 2026. Planning evidence; not an installed or independently accepted physical model.

**[R04](#research-basis) — Equation–process–method cross-reference.** Supplied Atlas pre-study, 15 September 2026. Planning evidence; not an installed or independently accepted physical model.

**[S01][url-008] — GPlates: pyGPlates Primer.** Official documentation. Rotation hierarchy, topology, deformation; documentation labelled pyGPlates 1.0.0.

**[S03][url-009] — pyGPlates: calculate_velocities.** Official API documentation. Rotation-based velocities and radius/time conventions.

**[S04][url-010] — GPlately: SeafloorGrid.** Official methods/API documentation. Documentation labelled 2.0.0; initial-age heuristic and surviving-seed artefacts explicitly described.

**[S06][url-011] — Fraters et al. (2019): The Geodynamic World Builder.** Peer-reviewed methods paper. Initial conditions, not time evolution; Cartesian and spherical geometry.

**[S08][url-012] — LaMEM official repository.** Official repository. Marker-in-cell, staggered finite differences, PETSc and rheology; no runtime reproduced.

**[S10][url-013] — ASPECT: Basic equations.** Official scientific documentation. Stable documentation labelled 3.0.0; equation families and approximations.

**[S11][url-016] — ASPECT: Material model.** Official scientific documentation. Creep, yielding and explicit warning about rheological parameter conventions.

**[S13][url-014] — Underworld: Introduction.** Official documentation. Underworld3 is a rewrite; Underworld2 remains a distinct code family.

**[S16][url-015] — May, Brown and Le Pourhiet (2015): Matrix-free multigrid for heterogeneous Stokes flow.** Institutional record of peer-reviewed methods paper. Q2–P1-discontinuous/material-point method and hybrid multigrid; full paper/code not audited.

**[S18][url-017] — Wickert (2016): Open-source modular solutions for flexural isostasy, gFlex v1.0.** Peer-reviewed methods paper. Analytical and finite-difference methods; boundaries and variable rigidity.

**[S20][url-018] — Hindle and Besson (2023): Corrected flexure finite differences with abrupt coefficient changes.** Peer-reviewed methods paper. Independent warning about discretising variable rigidity and interfaces.

**[S27][url-022] — Fastscapelib C++: Eroders.** Official API/scientific documentation. First-order implicit SPL and nonlinear Newton treatment; not all Fortran features inferred.

**[S28][url-023] — Braun (2023): Implicit algorithm for threshold stream-power incision.** Peer-reviewed methods paper. Accuracy and nonlinear convergence caveats; thresholds change the problem.

**[S39][url-024] — PyLith: Governing elasticity equations.** Official scientific documentation. Static/quasistatic/dynamic formulations and rheologies.

**[A01][url-001] — Atlas: coding and dependency map.** Pinned Atlas source documentation. Read through GitHub connector; active route and source-identity boundaries.

**[A02][url-002] — Atlas: active tectonic adapter.** Pinned Atlas source code. Read through GitHub connector; R3 snapshot, pinned inputs and no category acceptance.

**[A04][url-003] — Atlas: native common domain.** Pinned Atlas source code. Source-defined 256-cell envelope; not a product target.

**[A06][url-004] — Atlas: native numerical policy.** Pinned Atlas source code. Fixed-quantum accounting; must not be silently replaced by floating-point implementation.

**[A07][url-005] — Atlas: topography kernels.** Pinned Atlas source code. Target for relevant routing/geometry method study, not a claim of modification.

**[N-S01][url-019] — van Keken et al. (2008): A community benchmark for subduction zone modeling.** Primary author institutional record and abstract. Kinematically prescribed slab plus dynamically computed wedge. Full benchmark configuration/data not acquired or executed.

**[N-S02][url-020] — Schmeling et al. (2008): A benchmark comparison of spontaneous subduction models—Towards a free surface.** Peer-reviewed primary methods paper; publisher abstract/preview. Numerical/laboratory comparison; viscosity averaging and free-surface sensitivity. No figures/tables or performance results reproduced.

**[N-S03][url-021] — Schreurs et al. (2006): Analogue benchmarks of shortening and extension experiments.** Primary institutional bibliographic record. Candidate benchmark identified only. Full experimental configuration and data must be obtained before use.

<a id="research-basis"></a>

### Historical research basis

R01 (modelling), R03 (implementation feasibility) and R04 (the 28-equation/15-process cross-reference) are the dated pre-studies already supplied in this conversation. They remain source material, not additional maintained plans, and are not reproduced in this two-document edition. R02’s optimisation methods and R06’s Minecraft methods now have their maintained home in the [optimisation reference](OPTIMISATION_REFERENCE.md). The primary scientific sources above continue to support the plan. A reference to R04 preserves an equation identifier; it does not assert that every R04 equation is fully specified or implemented here.


[url-001]: https://github.com/Atlantispy/atlas/blob/7d0e707a576fe08b9bcb816466a0a8fb5f115808/docs/CODING_SAFETY.md
[url-002]: https://github.com/Atlantispy/atlas/blob/7d0e707a576fe08b9bcb816466a0a8fb5f115808/engineering/work/generator_upgrade_r29/tectonics.py
[url-003]: https://github.com/Atlantispy/atlas/blob/7d0e707a576fe08b9bcb816466a0a8fb5f115808/engineering/work/native_terrain_r1/domain.py
[url-004]: https://github.com/Atlantispy/atlas/blob/7d0e707a576fe08b9bcb816466a0a8fb5f115808/engineering/work/native_terrain_r2/numerics.py
[url-005]: https://github.com/Atlantispy/atlas/blob/7d0e707a576fe08b9bcb816466a0a8fb5f115808/engineering/work/topography_r1/kernels.py
[url-006]: https://github.com/Atlantispy/atlas/blob/11317165b7e2aeab7201a1fe3e3f646cb640d51e/tectonics/README.md
[url-007]: https://github.com/Atlantispy/atlas/blob/11317165b7e2aeab7201a1fe3e3f646cb640d51e/tectonics/evidence/DELIVERY.md
[url-008]: https://www.gplates.org/docs/pygplates/pygplates_primer
[url-009]: https://www.gplates.org/docs/pygplates/generated/pygplates.calculate_velocities
[url-010]: https://gplates.github.io/gplately/latest/sphinx/html/generated/gplately.SeafloorGrid.html
[url-011]: https://se.copernicus.org/articles/10/1785/2019/
[url-012]: https://github.com/UniMainzGeo/LaMEM
[url-013]: https://aspect-documentation.readthedocs.io/en/stable/user/methods/basic-equations/index.html
[url-014]: https://www.underworldcode.org/intro-to-underworld/
[url-015]: https://www.research-collection.ethz.ch/handle/20.500.11850/690333
[url-016]: https://aspect-documentation.readthedocs.io/en/stable/parameters/Material_20model.html
[url-017]: https://gmd.copernicus.org/articles/9/997/2016/
[url-018]: https://se.copernicus.org/articles/14/197/2023/
[url-019]: https://ora.ox.ac.uk/objects/uuid%3A9f5ad33b-3fba-4658-9764-19436dfcc4e3
[url-020]: https://www.sciencedirect.com/science/article/pii/S0031920108001568
[url-021]: https://gfzpublic.gfz.de/pubman/item/item_234212_1
[url-022]: https://fastscapelib.readthedocs.io/en/latest/api_cpp/eroder.html
[url-023]: https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2023JF007140
[url-024]: https://pylith.readthedocs.io/en/stable/user/governingeqns/elasticity/index.html
