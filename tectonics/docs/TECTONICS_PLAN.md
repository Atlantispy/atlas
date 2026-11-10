# Atlas tectonics component plan

This plan defines scientific responsibilities, component
contracts and capability gates. Use [CURRENT_STATE](../../docs/CURRENT_STATE.md)
for the active checkpoint and holds, the [roadmap](../../docs/ATLAS_ROADMAP.md) for
programme direction and the [integration plan](INTEGRATION_PLAN.md) for coupled
integration order and finish rules. I01–I12 are integration increments, not new
W-packages. Limited W12 technical assembly does not complete the generator.
W00–W12, the R1–R9 obligations and M0–M7 below retain scientific responsibilities
and required outcomes; the integration plan owns the sole remaining I01–I12
execution route. These tables do not create parallel implementation sequences.

The scientific-fidelity repair remains paused at the owner's request. R4.4 and
full-interval scientific work remain held; this plan lifts no hold or execution
gate. Independent authorised work retains its own scope. Generated tectonics,
mountain/terrain realism and complete world execution remain unaccepted.

Read [How Atlas tectonics is made](HOW_TECTONICS_IS_MADE.md) for the accessible
explanation. Specialist methods retain their detailed contracts and obtained
results; [OPTIMISATION_REFERENCE](OPTIMISATION_REFERENCE.md) owns execution,
cache/storage/language decisions and matched-error measurements. Case contracts
and tests remain beside implementation. Reading editions are not extra authorities.
The [evidence register](../../docs/CURRENT_EVIDENCE.md) classifies only declared
byte bindings; unlisted W01–W12 receipts keep their original source/runtime scope.
Git history retains superseded progress prose. Moving an explanation neither
repins historical results nor makes them current.

<a id="current-module-boundaries-and-continuation-23-september-2026"></a>

## Scientific ownership

Retain the mixed package layout unless a separately scoped change warrants
migration. File placement does not assign scientific ownership. Preserve existing
components/dependencies and defer non-tectonic expansion to the receiving module.
Every physical contribution has one owner and is applied once.

| Responsibility | Owner of further scientific development |
| --- | --- |
| Plate/block motion, fault deformation, extension, spreading, shortening, subduction and associated mechanics | Tectonics |
| Geological descriptions, properties, melting/transfer/emplacement and rock history | Geology; tectonics consumes required properties and accounts |
| Sediment layers, compaction and pore fluids | Geology / erosion and sediment transport; soil-specific work belongs to soils and ground conditions |
| Drainage, runoff, lakes and water exchange | Hydrology |
| Incision, hillslopes, sediment routing and deposition | Erosion and sediment transport; topography/topology owns resulting terrain representation |
| General heat/material accounts, load construction, caching, storage and resources | Shared services or explicit interfaces; no second implementation merely to change ownership |

Tectonics retains its necessary thermal/mechanical response, including cooling,
isostasy and flexure. A receiver owns its response to tectonic outputs; tectonics
owns its response to supplied loads/properties/forcing. Existing W03/W04/W08
adapters remain usable in place. W09 Steps 4–5 remain unfinished cross-module
surface work for their individual owners, not the next tectonics expansion.

[Underthrusting](UNDERTHRUST.md), [evolving-input mechanics](EVOLVING_MECHANICS.md)
and [supported histories](EVOLVING_MECHANICS.md#tectonics-continuation-step-4-supported-dated-histories) retain their supplied geometry,
host-space, absolute-reference, coincident force/material and recovery contracts.
Uniform thickening does not replace structural collision; a regime label cannot
transfer state between incompatible representations.

## 1. Basis, constraints and intended result

### 1.1 How this plan uses the pre-studies

Reports 01–03 supply the modelling, optimisation and implementation assessments. Report 04 supplies the stable identifiers **P01–P15**, **E01–E28**, **F01–F17** and **O01–O17**. They are retained here; they are not new Atlas module names or a replacement for its eighteen categories. In particular, Report 04 identifies gaps in yielding, free-surface treatment, mass creation/consumption, magmatic transfer and water/sediment closure. This plan treats those gaps as work, not as capabilities already supplied by the equations. [[R01](#research-basis); [R02](OPTIMISATION_REFERENCE.md#scientific-methods); [R03](#research-basis); [R04](#research-basis)]

The repository baseline described in those studies is `7d0e707a576fe08b9bcb816466a0a8fb5f115808`. This is **not a fresh audit of GitHub or the Windows workspace**. The studies identify an active tectonic snapshot adapter, existing geometry/route reuse, a native 256-cell domain and a fixed-quantum material ledger. Preserve them as historical implementations with their own meanings; new experiments must not silently alter their bindings or relax their limits. [[R03](#research-basis); [A01][url-001]; [A02][url-002]; [A04][url-003]; [A06][url-004]; [A07][url-005]]

The remake foundation at `11317165b7e2aeab7201a1fe3e3f646cb640d51e`
provides restricted reference kernels, not completion of W01–W04 or real-terrain
validation. Later evidence keeps its source/runtime identities. Execution sources
PS01–PS08 and language sources LS01–LS05 remain with the optimisation reference;
consolidation is not a fresh scientific-software audit.

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

A successful numerical run is not necessarily geologically plausible. A geologically plausible unconstrained case is not automatically compatible with the Diadem. Code correctness, numerical accuracy, physical adequacy, world-design compatibility remain distinct judgements.


### 1.4 Document and evidence ownership

Keep scope, scientific contracts, dependencies and acceptance obligations here.
Update current status in place in CURRENT_STATE; retain detailed methods, receipts,
original failures, identities and scope at their specialist owner links. Case/test
records are evidence, not additional roadmaps. No historical evidence is repinned.

The Diadem is an explanatory compatibility case, not an answer key. A failure to
explain it is valid. Do not tune global defaults to its outline, hide a special
collapse/event in a general law, or treat a fitted history as independent proof.
Report alternative explanations, unresolved mechanisms and necessary non-Earth-like
assumptions. No physics/infrastructure line-count quota applies.

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

**Reference numerical baseline for M:** a two-dimensional, inertia-free viscous/Stokes calculation on a structured staggered grid, with explicit material fields and conservative transfers; compare it with a compatible mixed finite-element alternative at the design gate. Start at constant viscosity before adding thermal coupling and pressure-sensitive yielding. This is a bounded reference formulation, not a decision to recreate LaMEM, approve all its laws or restrict eventual three-dimensional modelling. [[S08][url-012]; [S10][url-013]; [S16][url-015]]

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

### 3.3 Authored constraints and generated detail

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

### 4.4 Reference use and bounded initial state

The force-driven R1–R4 experiment is separate from the seeded world creator and
W08's prescribed-slab benchmark. Their results cannot inherit one another's
scientific acceptance. [Experimental dynamics](how-it-works/05-experimental-dynamics.md)
explains the route; exact registered cases govern reproduction.

R1's [reference-use contract](FOUNDATIONS.md#3c-r1-reviewed-source-use-contract-18-september-2026)
and [policy](../cases/plate_reference_use_policy.json) distinguish
ACCEPTED_FOR_SCOPED_REFERENCE_USE from strict
REFERENCE_DISCREPANCIES_REQUIRE_REVIEW (exit 1). Keep ON's table/outline areas
separate; MS coincident subsurface traces are not ordinary simple rings. Three
unresolved connectors affect five refused surface edges and nine excluded neighbour
owners; Peru's trace remains open. Source populations are 52 labelled areas, 51
ordinary-shape candidates before scale limits, 43 neighbour counts, 12 closed
orogens, 229 boundary segments and 5,819 motion records. Ten morphology holdouts
remain reserved; all 52 areas are calibration. Neither a complete deformation mask
nor an unrestricted two-owner planetary mesh is accepted. Exact findings, source
identities, omissions and rights remain in the policy and original evidence;
unavailable historical/external-model R9 challenges cannot be made from a derivative
of the same PB2002 data.

<a id="3cr2-initial-state"></a>
<a id="3cr2-scaling"></a>

#### R2: geological substrate and static sampling

[precursor_r2.json](../cases/precursor_r2.json) registers the static contract.
[W01 sampling](W01_REGIONAL_WORKFLOW.md#initial-condition-sampling) owns the supported initial-condition
interface; [execution/indexing](OPTIMISATION_REFERENCE.md#3cr2-initial-execution)
owns scheduling, reuse, resource admission and measured costs.

**Plate-independent substrate.** `GeologicalDomain` is a bounded planar area,
conditioned spherical patch, or an entire named reference sphere. It has no
physical plate or region owners. Existing `GeologicalCase` validates its original
materials, formation cohorts, ordered columns, thermal profiles, provinces,
faults and weak zones against this support. Old `BoundaryNetwork`/`SphericalAtlas`
cases and their serialised definitions remain supported. A pre-partition case
refuses selectors that require final plate/region IDs; its computational sampling
cells cannot determine the later physical plate partition.

`PrecursorState` adds one explicit origin assignment per source (observed,
authored, sampled named prior or model-evolved import), separate known/unknown
cooling histories, density/volume bases, optional initial scalar fields and
explicit mantle/slab inputs. An observed label requires a cited record but is not
independent verification; model-evolved input requires its parent-state identity
but does not run that model. Formation times are never replaced by cooling dates.
All times are SI seconds in the case's named epoch; a frame, epoch or depth-datum
mismatch requires explicit conversion, not a renamed array.

**Inherited and deeper structure.** Existing faults/sutures and weak zones remain
independent of plate labels. Exact finite-trace corridor membership is available
at points; overlapping weakness follows the existing explicit precedence without
invented multiplication, averaging or a damage law. Optional slab/mantle records
use named footprints and constant surface-relative depth bands with explicit
body precedence. They can replace column material or extend support below the
lithosphere base. These are supplied initial structures, not dynamically formed,
dipping/curved 3D slabs or inferred slab-pull forces.

**Material knowledge and property conditions.** Exact bindings to the existing
offline Earth-material library retain its full source/condition dependency and
automatically obtain volume bases. Partial records remain partial; source-bound
values cannot be silently rebound or extrapolated. Grain volume, reference
aggregate/matrix volume, explicit pore volume, bulk volume and mass are distinct.
Additional porosity on an already-bulk reference rock is refused. A bulk-reference
row does not assert its unknown intrinsic solid/pore split. Optional
`reference_mass_temperature_k` computes only source-reference-density inventory,
not in-situ mass of hot/pressurised lithosphere or a common pressure assumption.
No new hot/high-pressure or constitutive law is selected by R2.

**Sampling added to W01 stage 5.** `PreparedPrecursor` supplies immutable point
samples and conservative initial inventories for polygon-prism or minor-arc
shell-sector cells. Province overlap is resolved by subtracting higher-priority
footprints before integrating lower-priority material; body bands similarly
replace rather than double-count it. All province candidates are retained at
points. Layer/body intervals are top-inclusive and bottom-exclusive; cell faces
have zero extensive volume. A winning centre point is never substituted for a
mixed-cell average. Unsupported depths, missing required porosity/temperature or
unresolved property requests fail explicitly. Optional unresolved scalar fields
and reference masses carry known masks; convenience accessors refuse unknown
values rather than treating numeric placeholders as physical zeroes.

For planar area A and positive downward depths a,b, V=A(b-a). For a spherical
footprint whose reference-surface area is A on radius R,

    V = A/(3 R²) * [(R-a)³ - (R-b)³]
      = A*(b-a)/3 * [((R-a)/R)² + ((R-a)/R)*((R-b)/R) + ((R-b)/R)²].

The factored form avoids subtraction of nearly equal radius cubes. For explicit
porosity phi, matrix volume is V(1-phi), explicit pore volume is V phi, and each
constituent receives its declared fraction of matrix volume. Existing fractional
round-off allowances are not renormalised: bulk-coverage and phase-volume
residuals are reported separately. Cohort/material indices refer to shared
immutable records, preserving origins and formation dates without rich objects
copied into every cell. Crust and lithosphere thickness remain the existing
separate column quantities.

**Initial thermal/other fields.** Constant and piecewise-linear profiles integrate
analytically with the appropriate radial metric. The existing E04 half-space
initial reference uses bounded quadrature for cell means, with an explicit error
estimate and refusal rather than midpoint fallback. Mean temperature is
volume-weighted temperature, not heat/enthalpy; this adds no thermal evolution.
Temperature offsets must also have a non-negative envelope on requested cell
support; a positive mean cannot conceal potentially sub-zero temperatures.
Stress, damage and prescribed forcing can be explicitly supplied/unresolved
scalar components with units and interpretation, not an inferred mechanical state.

A named prior is the bounded Cartesian cosine field

    f(r) = mean + amplitude/N * sum_i cos(k_i dot (r-origin) + phase_i).

SHA256(name, unsigned-64-bit seed, mode index) supplies fixed per-mode streams.
Amplitude means maximum deviation, not standard deviation; wavelengths are named
feature scales, not an asserted fitted correlation length. Domain/frame/origin
and seed belong to the identity. Planar coordinates are (x,y,depth) metres;
spherical coordinates are geocentric Cartesian metres, without a longitude seam.
Changing support resolution/order does not redraw the field. Planar polygon-prism
prior means are analytic Fourier integrals including holes. Statistical inputs
remain assumptions, not simulated geological events.

**Explicit remaining limits.** General dipping/curved 3D structure and arbitrary
volumetric interpolation remain unimplemented. Spherical point priors and radial
base-profile means work, but spherical cell means of Cartesian spectral priors
are refused. Positive-volume overlap between query cells is refused by default;
when charts cannot certify disjointness, no snapping or blanket sliver tolerance
is substituted. Compatible patches are required, or the caller must explicitly
request non-additive overlapping queries. A set of individually queried spherical
volumes is not thereby certified as a global disjoint mesh. Static sampling does not itself close broader W01 interpolation, forcing/evolution,
combined scientific acceptance or R3–R9 physics.

Broad-phase caps include minor-arc edges/interiors, retain exact intersections
for uncertain candidates and preserve tiny positive-volume overlaps. Dense cap
overlap can still require quadratic work; indexing is not arbitrary cross-chart
repair or a global disjoint-mesh certificate. Batching must preserve complete
request checks, global hit/row/work ceilings, original order and fixed per-cell
summation. Threading cannot multiply admission or change numerical arrays.
[The scaling case](../cases/precursor_r2_scaling.json) and original tests/measurements
retain these limits. Static T04/T05/T06/T14/T15 credit does not qualify their dynamic
scopes. Existing limitations on dipping structures and spherical-prior means remain.

<a id="3cr3-physical-closure"></a>
<a id="3cr3-stress-hardening"></a>

### 4.5 Local rheology, memory and physical length

[physical_closure_r3.json](../cases/physical_closure_r3.json) registers the selected
local laws and 1D length primitive. These are array kernels with independent
numerical tests, not a Stokes/convection solution. Exact access limits and source
identities remain in that case; [execution](OPTIMISATION_REFERENCE.md#3cr3-execution)
owns batching, resources, source-sensitive reuse, storage and obtained measurements.

#### Selected local models

The order is the constant-viscosity analytical control, the Tosi et al. (2015)
local-law benchmark family, then the Becker & Fuchs (2023) strain-memory family
with a damage-free control. The full published methods and relevant parameter
tables were read before implementation. The exact locations, access limits and
primary-repository corroboration are recorded in the case file. No publication
PDF, ASPECT/CitcomS source, new PB2002 data or new dependency is bundled.

For the Tosi reference, `e = (grad(u) + grad(u).T)/2`,
`eII = sqrt(e:e/2)` and `q = sqrt(2)*eII`. The implemented local formulae are

```
L = exp(-log(contrast_T)*T + log(contrast_z)*z)
P = eta_star + sigma_Y/q
eta = 2/(1/L + 1/P)
```

The Frobenius norm in `P` and factor **two** in the harmonic mean follow the
source; neither is silently replaced by a conventional yield cap. Table-1 cases
1 and 3 use `L` directly. Cases 2, 4 and 5a use the harmonic law, with the named
source values. At zero strain rate and positive sigma_Y its viscosity tends to
`2*L`; zero-stress variants have their separate analytical limit. Case 5b's
periodic-regime survey and all Nusselt/velocity convection comparisons are **not**
run or accepted here. Sources: [Tosi et al., equations 6–10 and Table 1](https://doi.org/10.1002/2015GC005807).

For the selected BF2023 **model-19 local-law subset**, define

```
eta_T = eta0*exp(E/(T+1) - E/2)
f = 1 - Gamma*min(d,dcrit)/dcrit
sigma_y = (a+b*z)*f
eta = min(eta_T, sigma_y/(2*eII))
h(T) = B*exp(-Ed/(T+1) + Ed/2)
D_t d = eII - h*d
```

The registered values are E=40, eta0=1, a=1e6, b=1.51e7, dcrit=10, Gamma=0.9,
Ed=46.1 and B=2.44e9. Gamma=0 supplies the damage-free control. This reproduces
local equations 6–8 and their table values, **not** the paper's full spherical
experiment. Asthenospheric/melt multipliers, continental rafts, empirical 0.1
time rescaling and unspecified absolute viscosity-clipping bounds are absent,
not hidden defaults. This family is not relabelled microphysical grain damage.
Source: [Becker & Fuchs, section 2.3, equations 6–8 and Table 1](https://doi.org/10.1029/2023GC011179).

Damage is an unbounded strain-like history within an explicit computational
limit. Only its **strength effect** saturates; stored damage above dcrit is not
clipped away. Initial damage must be supplied explicitly, including a deliberate
zero. For constant strain rate and temperature over one supplied interval,
`d_new = d*exp(-h*dt) + eII/h*(1-exp(-h*dt))` is evaluated with stable small-h
limits. This is not a spatial advection method or exact integration for varying
thermal/mechanical fields. Existing W02 histories are not silently converted.

#### Units, force ownership and boundary conventions

Local rheology inputs use T,z in [0,1], with finite parameter/rate/history
limits and binary64 arithmetic. SI conversion requires a named `DiffusiveScales`:
`t0=L^2/kappa`, `u0=kappa/L`, `stress0=eta_ref/t0` and `rate0=1/t0`.
The **diffusive length and depth normalisation are separate required quantities**
(radius versus layer thickness must not be conflated). The 20°C material library
is unchanged and is never extrapolated into these phenomenological laws.
Optional viscosity bounds are explicit numerical choices; every clipped point
is reported, and no floor is treated as measured strength or localisation length.

The local thermochemical reference is the selected constant-property Boussinesq
approximation, with `rho'=-rho0*alpha*(T-Tref)+delta_rho*C`, `f=rho'*g`,
`q=-k*grad(T)` and reference heat capacity `rho0*cp`. Each SI material profile
names its source and validity interval. C is a supplied volume fraction in
[0,1], not a renamed plate or provenance ID. The R4 Tosi control has C=0, no
compositional strength multiplier and H=0. A future continental-strength model
requires its own explicit profile; the BF continental-raft extension is not
silently selected. The viscous stress/dissipation helper takes a traceless
symmetric strain tensor; it refuses compressible input rather than inventing a
bulk law or hiding divergence by automatic trace removal.

The pressure variable for the initial R4 box is dynamic pressure with an
Atlas-selected zero-domain-mean gauge. It is **not** fed into the depth-only
BF yield law, a high-pressure EOS or a tensile/friction law. Free-slip, impermeable
walls, fixed top/bottom temperatures and insulated sides are selected for the
Tosi unit box. These choices apply to the named rectangular reference. Body-force density owns thermal/compositional buoyancy once; no extra
slab-pull traction, prescribed plate motion, latent heat or adiabatic work is
added. Viscous dissipation can be computed separately and included only through
the explicit heat-source argument when that approximation is selected.

**Source-convention issue retained:** the printed Tosi momentum equation's
right-hand-side sign with its stated upward unit vector does not directly match
Atlas's `-grad(p)+div(tau)+rho'*g=0` body-force convention. The density/gravity
implementation in the tagged ASPECT benchmark was checked and supports warm
upward buoyancy. This is not an author-confirmed erratum. The case records the
three exact ASPECT file identities. Full R4 acceptance must verify assembly signs, tensor factors,
pressure normalisation and the full numerical benchmark before claiming its
convection solution reproduces the paper. R3 local-law tests do not settle a
future PDE comparison by omission.

#### Fixed length and localisation limits

An **explicit Atlas-selected extension**, separate from both published local
controls, solves `d_bar - ell^2*d_bar_xx = d` on a 1D cell-centred uniform support
with zero normal gradient at its ends. The positive physical ell does not change
with mesh size. The banded SPD operator is tested against independent dense and
analytic modal solutions, including second-order refinement at fixed ell,
constant preservation, integral preservation and non-negativity. Its linear
factorisation is reused; no dense inverse, numerical viscosity floor or repeated
mutation of raw history is used as a substitute for a physical length.

**This operator verification is not a mesh-independent coupled localisation
result.** The primitive is optional and never silently alters the BF reference
input. Raw history and a strength-driving filtered field must remain distinct.
A 2D/3D coupled shear-band model, its boundary behaviour and a physically justified
length require R4/R5 verification before localisation is claimed. The first R4
control is constant viscosity, followed by the unchanged Tosi local laws; it does
not depend on pretending this later gate is already passed.

#### Returned arithmetic is part of the contract

The numerical-hardening review found that
`stress_and_dissipation()` could return zero heat after squaring a tiny strain
rate even when the final heat rate was representable. For viscosity 1e100 and
strain diag(1e-170, -1e-170), the previous zero is replaced by approximately
4e-240 in the caller's consistent units. This is an extreme arithmetic test,
not an observed failure of a mantle-scale simulation.

The equations remain `tau = 2*eta*e`, `Q = tau:e = 2*eta*sum(e_ij^2)`.
Mantissa/exponent evaluation avoids premature overflow/underflow in `2*eta`,
`e^2` and the strain invariant. Each component of tau is evaluated independently;
Q is summed at a power-of-two-normalised scale before final range conversion.
Finite subnormal results are retained. A non-zero physical result that rounds to
zero, or a result outside finite binary64 range, is refused explicitly. Zero
strain is still a valid zero response. Symmetry and tracelessness use the existing
64-epsilon relative criterion in normalised coordinates; no physical tolerance,
source data, constitutive parameter or original test is changed.


Independent exact-float Decimal contraction, subnormal/overflow cases, 3D
invariants, broadcasting, detached ownership and resource refusals support the
arithmetic checks; they do not calibrate a mantle model. Historical results are
not repinned. Zero strain remains a valid zero response.

<a id="3cr4-progress"></a>

### 4.6 Rectangular thermomechanics: component obligations

R4 is incomplete. R4.1 constant mechanics, R4.2 heat/binary transport, R4.3
nonlinear mechanics and R4.4 mature-reference/combined acceptance have distinct
obligations. CURRENT_STATE owns delivery and hold status. No component test count
or short evolved example closes R4/W03/W07, starts R5, supplies planetary topology
or explains Diadem landforms. Constant-property routes retain their original
descriptors and scope when nonlinear modes are added.

<a id="3cr4-1-mechanical-core"></a>

#### R4.1: equations, units and declared boundaries

The solver implements `-grad(p)+eta*laplacian(v)+f=0`, `div(v)=0`, with **constant**
positive viscosity. For this constant-coefficient incompressible case the vector
Laplacian equals `div(2 eta e)`; for variable eta it does not. `StokesBox2D` uses
x right and **z upward from the bottom** in metres, a uniform rectangular grid,
and a named frame. It is not R2's inward depth or a transformed global patch.
All four walls have zero normal velocity and zero normal derivative of tangential
velocity (impermeable/free slip). No no-slip wall, traction, free surface, inflow
or prescribed plate motion is silently approximated by this boundary selection.

`PreparedStokes2D` requires the existing `DiffusiveScales` and an unclipped
constant `RheologyProfile`. Dynamic pressure has a zero-domain-mean gauge; it is
not absolute/lithostatic pressure and is not fed into a pressure-sensitive law.
The force snapshot is explicitly supplied on the interior velocity faces in
N/m^3. It is used once. The optional `face_force_from_density` helper declares
arithmetic interpolation of a cell anomaly to those faces and constant Cartesian
gravity; it does not insert reference density, infer gravity, remap arbitrary
meshes or add a second slab traction. R3's Boussinesq response can provide that
anomaly. Snapshot time/epoch/source describe the input; no time advance occurs.

#### Spatial discretisation and pressure compatibility

Pressure occupies cell centres, u vertical faces and w horizontal faces. The
zero normal boundary DOFs are eliminated. Face-centred finite-volume balances
and centred differences produce `A=-laplacian`, `G=-D.T`. A constant pressure
has zero gradient. It is fixed by a symmetric Lagrange-multiplier augmentation
`[A,G,0;G.T,0,c;0,c.T,0]`, where `c=ones/sqrt(Np)`. **Every continuity equation is
retained**; a pinned pressure is not used to discard a cell's divergence check.
The multiplier is checked for compatibility and cannot conceal a mass source.

The independent small sparse-direct and native iterative routes solve this same
boundary problem; no dense inverse, independently solved physical tiles or silent
fallback may replace it. Detailed solver/preconditioner construction, admission
and measured costs belong to the
[execution reference](OPTIMISATION_REFERENCE.md#3cr4-1-execution).

<a id="3cr4-1-publication-review"></a>

#### R4.1: returned-SI acceptance

Extreme arithmetic probes exposed a gap: the internal normalised solution
could pass while the returned SI fields failed the same equations. A 2x2
circulation with force `20 * smallest_positive_binary64` rounded to a nonzero
velocity with a 20% force residual but reported zero. An arbitrary diffusivity
reference of 1e22 with force 1e-200 and physical viscosity 1e100 also changed a
normal, representable velocity by about 1.19%; diffusivity is not a parameter
of this steady mechanical problem. Neither probe is an Earth-like mantle case. A related density-to-face-force
probe found that rounding an unequal subnormal endpoint mean before multiplying
gravity could introduce a 33% error in a normal final force. Shared-exponent
interpolation now preserves the original half weights without that intermediate
rounding; genuinely unrepresentable final forces still fail explicitly.

The correction normalises original SI forces directly. It evaluates conversions
with `U0 = F L^2/eta` and `P0 = F L` using binary mantissas/exponents, not rounded
intermediate subnormal scale products. Every independent residual/work gate now
checks the returned SI velocity and pressure, re-expressed against the original
force. Accurate nonzero subnormals remain supported; inadequate final rounding
is refused. No original residual or physical tolerance is raised. New records
identify this publication contract; old snapshots retain their historical checks,
source identities and bytes without being relabelled as newly validated.

The correction is registered in [stokes_r4_1_review.json](../cases/stokes_r4_1_review.json).
[Original review tests](../evidence/3cr4-1-review-tests.json) and
[measurements](../evidence/3cr4-1-review-measurements.json) retain the old failures
and corrected scope; this is implementation evidence, not geological validation.

#### R4.1: verification and visual scope

The registered case is [`stokes_r4_1.json`](../cases/stokes_r4_1.json). Analytical
forcing is differentiated from a continuous trigonometric streamfunction and
independent pressure field, not computed by the discrete operator being tested.
Square and unequal-spacing rectangular refinement, zero force, hydrostatics,
checkerboard-pressure exclusion, sign reversal, superposition, SI scale
invariance and warm-upward buoyancy are covered. Separate ghost/central-stencil
momentum residuals, all-cell uncorrected divergence, pressure gauge and discrete
work balance are checked even when MINRES returns success. The force-normalised
residual tolerances are new R4.1 choices; no historical tolerance is changed.

`tools/visual_stokes_r4_1.py` renders actual solved velocity/pressure/divergence,
the explicitly **authored** temperature used to construct buoyancy, and continuous
solution refinement. Face-to-centre averaging is display interpolation only;
raw staggered arrays and provenance are retained. No temperature evolution or
terrain is fabricated. Numerical acceptance, assistant visual inspection and
Michael's visual review remain distinct.

The existing lossless ArrayStore stores complete steady problem/result records
with source/runtime, frame, epoch, time, units, force provenance, scales and law.
Restore does not run a solver or rebind an old record. **This steady result is not an evolving thermal/material checkpoint**; use the
separate R4.2/R4.4 contracts for that claim.
The recorded result explicitly carries `R4_complete=false`.

<a id="3cr4-2-thermochemical"></a>

#### R4.2: equations, physical ownership and boundaries

The [registered case](../cases/thermochemical_r4_2.json) specifies

    rho0 cp [dT/dt + div(u T)] = k lap(T) + H,
    dC/dt + div(u C) = 0,
    rho' = -rho0 alpha (T-Tref) + delta_rho C,  f = rho' g.

T is a cell-average absolute temperature; C is the volume fraction of ONE named
constituent and 1-C is its complement. C is not a plate, material-cohort identity
or formation age. The constant rho0 cp is the selected Boussinesq reference heat
capacity, not an in-situ variable-density mass or latent enthalpy. All quantities
are SI in an explicit x-right/z-up frame and named epoch. Extensive budgets are
for one metre out-of-plane thickness. R2 inward depth is not renamed to z-up, and
no full R2-to-W02 world/history conversion is implied.

Constant positive k, rho0, cp and viscosity are required. The retained R3 thermal/
compositional density anomaly feeds the reviewed mechanical solver once. Mechanical
walls remain closed/free-slip. Thermal sides are insulating; top and bottom are
either both fixed spatially uniform face temperatures or both insulating. A fixed
face is half a cell width from its boundary-cell centre. No hidden periodicity,
open material reservoir, compressibility, phase reaction or moving mesh is added.

H is material internal heating plus an explicit nonnegative scalar/cell source,
held constant for the supplied interval. It is integrated once over that interval.
Dissipation, adiabatic heating and latent heat are not inferred or double-counted.
Missing temperature, invalid composition, excessive density anomaly and unsupported
rheology fail explicitly rather than acquiring arbitrary laws or zero defaults.

#### R4.2: numerical meaning and acceptance limits

The normal step is Strang **D(dt/2)–A(dt)–D(dt/2)**. D is the exact time evolution
of the **second-order discrete finite-volume** diffusion/source operator, not exact
continuum diffusion. A reusable DCT-II in x and DST-II (fixed walls) or DCT-II
(insulated) in z diagonalise this specific constant-coefficient rectangle. The
nonnegative discrete eigenvalues are `4 kappa sin(pi*j/(2*n))^2 / h^2`, with j from
0 to n-1 for insulation and 1 to n for fixed face values. A linear stationary
thermal lift handles the fixed walls. Stable exponential/phi coefficients also
integrate the source and time-mean boundary heat. This avoids an explicit parabolic
CFL restriction and large-step Crank–Nicolson oscillations without changing the
spatial stencil. Splitting error still needs time refinement: a stable large
thermal step is NOT automatically an accurate coupled step.

A is unsplit multidimensional MC-limited finite-volume transport with SSPRK2.
Each shared face has one oriented transfer, used with opposite signs by neighbours.
The two RK stages each solve the constant-viscosity buoyancy response from their
own T/C fields; start-of-full-step velocity is not frozen by default. An explicitly
supplied frozen MAC velocity is a separate kinematic reference experiment. RK
velocities are labelled operator-split intermediates, not simultaneous final-state
mechanics. The demonstration solves endpoint mechanics again before plotting it.

The sufficient multidimensional outgoing-Courant bound is 1/2 (default 0.45),
checked at BOTH Euler stages. Summing outgoing directions matters; taking only a
maximum over axes would be unsafe. Divergence is checked on the actual velocities.
A failure publishes no partial state and requires an explicitly smaller interval;
there is no automatic substep, reduced-order route or material clipping. MC
limiting is formally second order in smooth monotone regions and loses order near
extrema/contacts. The compact-rotation test records observed errors/peak diffusion;
it is not misreported as exact shape preservation or uniform second order.

Raw C excursions within 64 binary64 epsilon are retained and reported, never
renormalised or clipped; larger excursions reject the step. The primary constituent
inventory residual is relative to its own amount, so a trace constituent is not
hidden behind total domain volume. Because only C is independently stored, the
relative precision of a vanishing 1-C is limited by subtraction near unity; both
inventories and the raw bound excursions remain visible. No general multi-material
cohort-advection completion is claimed by this binary pilot.

Every accepted step checks returned endpoint heat against signed integrated outward
boundary heat and source input. Composition and cell-local advective ledgers are
checked independently of the update loop. Zero normal material flux is exact.
Closed-to-material does not mean thermally insulated. Source/field/gauge/validity
checks from the R4.1/R3 components are retained. Subnormal source products are
combined before rounding where possible, and representable attenuated modal tails
are not lost merely because an exponential coefficient underflows first.

#### R4.2: independent checks and restart

Tests use an independent face-balance dense exponential, a separate boundary-heat
integral, analytical diffusion modes, independent transport matrices, rotating
Gauss-averaged compact data, and an independently derived 2x2 circulation mode
coupled to high-accuracy DOP853 integration. The latter is an independent temporal
reference, not a second Earth model. Timestep and spatial refinements remain
separate. Test failures are not fixed by changing retained reference answers.

Endpoint snapshots use the existing lossless ArrayStore and contain both fields,
complete problem/epoch/source definitions, latest-step balances and parent IDs.
A prior parent snapshot is not needed to decode or continue that state. Future
forcing is still explicit caller input; this is not a stored future schedule or
complete past flux/trajectory catalogue. Step objects expose both stage velocities
and shared-face transfers for callers needing those records. Reopen/fresh-process
continuation with the same source, policy and next forcing must reproduce exactly;
changed source/policy is refused rather than silently rebinding a checkpoint.

The real-output visual tool draws authored initial and genuinely evolved final
T/C fields, their difference, separately solved endpoint velocity and conservation
residuals. It retains numerical arrays, case/source identities and output hashes.
Assistant visual inspection and user review are separate from numerical or physical
acceptance. The 48-by-48, 40-step example is illustrative, not a calibrated Earth,
Diadem or full Tosi convection case. No new plate geometry needs a globe render here.

<a id="3cr4-2-review"></a>

#### R4.2: conditioned thermal arithmetic

The insulated diffusion operator no longer uses the material's buoyancy reference
as its numerical temperature offset. With zero thermal expansivity, changing that
reference cannot change this physical experiment, but the old subtraction/FFT/
addition could lose resolved field differences or fail heat accounting. Each
insulated call now uses the midpoint of the supplied field range as an offset.
The physical reference remains unchanged in the density law. These are deliberate
conditioning probes, not claims of realistic 10^16 K mantle reference values.

For short spectral intervals (maximum rate*dt <= 0.5), compute the field change
with `expm1(-rate*dt)` and add it to the original field. The fixed-wall time-mean
increment uses `phi1-1=-x*phi2` rather than subtracting near-ones. For larger
attenuation retain the absolute decayed-field form to avoid cancellation of
nearly all the original temperature. Both forms evaluate the same discrete
exponential/source equation with the original spatial/time order. No rates,
source, boundary values, physical durations or accepted tolerances are changed.
The independent dense exponential and heated steady-parabola refinement checks
cover both forms. Fixed-wall integrated heat remains independently evaluated.

The weighted modal-source helper now combines exponents whenever the intermediate
weight*dt is NONZERO subnormal as well as zero/overflowed. Rounding such a factor
before multiplication by a large mode could otherwise change the final normal
response by 33.3% in the registered arithmetic counterexample. The finite
representable response agrees with direct Decimal products after correction.

#### R4.2: represented clock and integrated interval

A merely increasing binary64 endpoint is insufficient: at epoch 10^16 s,
requesting 3 s produces a representable clock increase of 4 s. Integration must
not use 3 s while recording that it covered 4. New steps require the represented
endpoint difference AND twice the represented thermal half-step to agree with
the requested duration within `min(inventory_rtol,2e-11)` relative precision.
Inadequate intervals fail BEFORE any evolution, not by altering dt silently.
This is a numerical precision guard, not a finest temporal resolution or an
inferred geological timestep. An explicit suitable epoch/interval is the caller's
choice. Ordinary 4096-step non-bit-exact clock sequences remain supported.

`publication_contract=atlas.thermochemical-conditioned-diffusion-and-clock.v1`
labels new records. Earlier snapshots still decode with exactly their original
identity, metadata and arrays, without acquiring the new guarantee. Changed
source/execution identity still prevents an unrequested restart rebind.
The method's finite-volume/Strang equations retain their existing identifier;
source/version and the publication contract identify these arithmetic changes.

[thermochemical_review_r4_2.json](../cases/thermochemical_review_r4_2.json)
retains reference-invariance, short fixed-wall/source/epoch probes, historical
restoration and changed-source refusal. Insulated variance decay, transpose and
complement covariance, source and heated-conduction controls verify the declared
PDE, not mature convection. [Execution and original review evidence](OPTIMISATION_REFERENCE.md#3cr4-2-review-execution)
retain exact scope and costs; no old reference answer or PB2002 record is replaced.

<a id="3cr4-3-variable-mechanics"></a>

#### R4.3: full symmetric stress

The existing uniform staggered rectangle, zero normal wall velocity, zero wall
shear traction and zero-domain-mean dynamic-pressure gauge are retained. Normal
strains/stresses are cell-centred; engineering shear `gamma=du/dz+dw/dx` and
`tau_xz=eta_vertex*gamma` are at interior vertices. Normal stresses are
`tau_xx=2*eta_cell*du/dx`, `tau_zz=2*eta_cell*dw/dz`. The discretised equation is
`-grad(p)+div(2*eta*e)+f=0`, `div(v)=0`. No reference density/gravity is counted
twice and dynamic pressure is not sent to an absolute-pressure material law.

The positive velocity block is
`A=2*Bx.T*eta_cell*Bx+2*Bz.T*eta_cell*Bz+S.T*eta_vertex*S`.
The independent padded stress-divergence stencil and this native sparse derivative
assembly are separately tested. The pressure gradient is the negative divergence
adjoint; the existing gauge augmentation preserves every continuity equation.
For constant viscosity the divergence-free solution agrees with R4.1, while
variable viscosity includes the coefficient-gradient and cross-derivative terms
that an `eta*laplacian(v)` substitution would lose.

`PreparedVariableStokes2D.solve` accepts explicit positive SI viscosity at both
stress supports; it does not invent an average for a discontinuous supplied field.
`solve_rheology` evaluates the unchanged R3 constant/Tosi profiles. Cell temperature
is supplied; interior-vertex temperature is the arithmetic mean of four adjacent
cells. At each stress support, missing strain tensor components are reconstructed
with symmetric local arithmetic averages, then `eII=sqrt(e:e/2)` is evaluated.
This is a named second-order collocation rule for resolved smooth fields, not a
proof of interface, subcell shear-band or mesh-independent localisation accuracy.
Depth is measured down from the top using the separate R3 depth normalisation.

#### R4.3: current-law and returned-field acceptance

Picard iterations solve with lagged viscosity, evaluate viscosity again from the
new velocity and check the **true updated-law** force residual and maximum
log-viscosity change. Default full relaxation is explicit; any alternative fixed
relaxation enters the policy/identity. Tosi's factor-two harmonic combination and
Frobenius plastic denominator remain unchanged, including their zero-rate limits.
No minimum strain rate, hidden yield cap or new viscosity floor is introduced.
Optional existing R3 viscosity bounds remain explicit and return clipping masks.

Default linear GMRES tolerance is `1e-12`; the true normalised momentum gate is
`1e-9`, continuity `1e-10`, pressure-mean gauge `1e-12`, work balance `1e-9`, and
log-viscosity change `1e-8`. These are registered R4.3 numerical policies, not
relaxations of R4.1/R4.2 controls. Maximum iteration counts and a finite contrast
admission envelope do not guarantee convergence for every allowed input. Failure
raises an error; it neither publishes a lagged solution nor changes the law,
mesh, tolerances or solver route. The final test uses the actual rounded returned
SI velocity, pressure and viscosity with the rheology re-evaluated at that velocity.
Independent stress, divergence, gauge and mechanical-work checks remain distinct.

The selected BF model is available for a separate mechanical snapshot **only with
explicit frozen damage**. This neither clips the raw history nor advances/heals
it. The two-field evolving state has no damage field, so BF coupling is refused,
not filled by implicit zeroes. General damage advection, 2D/3D physical-length
regularisation and coupled localisation still need their own selected extension.

#### R4.3: explicit thermochemical coupling

`ThermochemicalProblem(..., mechanical_mode='variable-r4.3')` explicitly enables
constant/Tosi mechanical feedback through `PreparedThermochemical2D`, which accepts
`nonlinear_policy=NonlinearStokesPolicy(...)`. Both RK transport stages must
converge their own current temperature-dependent/yielding mechanics before the
shared-face transfers are accepted. A nonlinear failure or failed second-stage
Courant check publishes no endpoint. The existing Strang split, discrete thermal
exponential, MC/SSPRK2 transport, clock, source/boundary heat and binary-inventory
checks are unchanged. Composition affects buoyancy, not an invented strength law.
Thermal conductivity/capacity are still constant and the domain is still closed.

The default `constant-r4.2` contract deliberately retains its old variable-law
refusal and canonical descriptor. New records retain both stage solution IDs,
true diagnostics, policy and iteration counts, while the accepted endpoint has
its own time and identity. Stored stage velocities are not relabelled as the final
simultaneous flow; visualisation re-solves the endpoint when it displays that flow.
Snapshots decode without a chain of parent deltas, but are not complete archived
trajectories or future forcing schedules. Restart requires the same recorded
source and policy; old source states do not silently rebind.

#### R4.3: independent evidence and limits

The new checks reuse **T08 mechanics**, **T09 strength** (not free-surface or
localisation completion), applicable T05/T14/T15 and the existing PT families.
An independent rectangular streamfunction/pressure with analytically differentiated
exponential viscosity verifies second-order space refinement. A 2x2 continuity
reduction gives an independently written scalar Tosi root; an eight-variable ODE
combines that root with independent transport/heat matrices to check nonlinear
coupled time refinement. Sharp coefficient, hydrostatic, axis-transposition,
pressure-checkerboard, work, constant-limit and refusal tests complement them.

Primary corroboration uses PETSc's DMStag variable-coefficient example and official
SciPy solver documentation; no external implementation is copied. The unchanged
R3 source register remains authoritative for rheological formulas. The benchmark
and visual controls are synthetic, not tuned to PB2002 holdouts or Diadem output.
Bounded direct/iterative and repeated-preparation measurements report actual costs,
not a universal performance claim. Details belong in the
[maintained execution reference](OPTIMISATION_REFERENCE.md#3cr4-3-execution).

Post-stage actual-code visual QA is required. This increment renders solved flow,
viscosity, continuous reduction relative to the zero-rate law, pressure, nonlinear
residuals, independent refinement and short coupled evolution. It retains raw
arrays and source identities. A continuous viscosity reduction is not falsely
labelled as a discrete yielded-region map. Rendering and assistant inspection
remain separate from Michael's visual review and physical acceptance.

<a id="3cr4-4-convection"></a>

### 4.7 Mature convection and combined R4 acceptance

The [registered convection contract](../cases/convection_r4_4.json) defines the
applicable reference, maturity and independent adequacy gates. R4.4 remains held
and incomplete. Component verification and bounded probes cannot satisfy the
following campaign requirements.

#### Reference cases, conventions and source scope

The primary reference remains **Tosi et al. (2015), A community benchmark for
viscoplastic thermal convection in a 2-D square box**, DOI
`10.1002/2015GC005807`, equations 1–21 and Tables 1–2. Case definitions include
1–4, periodic case 5a and **all 21 separately identified case-5b yield values
3.0 through 5.0 at spacing 0.1**. These are 26 configurations, not 26 completed
runs. Case 5b remains applicable, and its exact supplementary data was supplied
and integrated on 22 September 2026. The main reference file contains 490 numerical entries for ten codes solving the
full two-dimensional viscosity problem: 470 individually transcribed Table 2
cells, plus 20 case-1 viscosity-limit entries obtained by applying the two exact
boundary values in its footnote to each code.
MC3D is explicitly excluded from this particular comparison envelope because
its viscosity is laterally averaged, a different equation system discussed in
the paper; the exclusion is not based on Atlas output.

Reference policy **v2 (22 September 2026)** explicitly adopts `Phi/Ra` for the
case-5a extrema, while preserving Table 2's printed `Phi` labels and numbers.
This is a derived project interpretation, **not an author-confirmed erratum**:
the periodic heat/work identity rules out a raw-Phi reading in all ten columns,
and ASPECT 3.0.0 explicitly compares raw dissipation divided by 100 with work.
The analyser now feeds both raw and already-scaled extrema through its periodic
report and compares the scaled channel without dividing it a second time.
No tolerances or maturity gates changed; the derivation and source links are in
the case contract and [bounded evidence](W01_REGIONAL_WORKFLOW.md#bounded-shape-validation-and-limits).

The case-5b source-data blocker is now resolved. The owner supplied Supporting
Information S1; the source-bound `cases/tosi_case5b_reference.json` retains all
626 reported numerical pairs in Tables S14-S23, their printed decimal precision,
code, yield, mesh, source page, upright/italic steady/periodic classification and
explicit dashes. Two independent text extractors agreed on every pair and dash;
the introduction and all ten table pages were also visually checked. No source
figures or article prose are redistributed. The original separate rights remain.

Comparison selects each same-equation code's finest published column at the exact
yield **before examining Atlas output**, with no coarser-column fallback for a
dash or unreported yield. All selected rows are retained and partitioned by their
printed regime; unlike regimes are never pooled. The diagnosed Atlas regime must
have published support, and any disagreement remains explicit in the report.
At yield 3.8, for example, GAIA's finest entry is steady while eight others are
periodic. This is a **finest-published envelope, not an exact-grid error bound**:
source methods and meshes differ. Independent Atlas mesh/time/nonlinear adequacy
is still mandatory, and all three studies' finest representatives must agree on
the physical regime. Both ten-cycle mean Nu extrema enter periodic comparison
and adequacy; global extrema alone cannot substitute for those means.

Tables S14-S22 supply nine same-equation contributors, not necessarily a result
at every mesh/yield. ELEFANT is absent. MC3D's different-law S23 is retained for
provenance but excluded from comparison. Cases 1-5a still require all ten named
Table 2 contributors. Neither absent values nor source deletion can silently
shrink the requirements: genuine source absences remain visible, and changed
reference bytes fail the pinned identity check. Runner identities bind both the
reference data and comparator; old trajectories are not automatically repinned.
Runtime analysis reads the small JSON, not the PDF, and has no PDF-library
dependency. No tolerance was widened and no mature R4.4 trajectory was completed
by this source integration. The held campaign remains incomplete.

The unit square is embedded in positive SI-valued controls with dimensionless
`theta = T_K - 1`, unit diffusivity, and `Ra=100`. This is a numerical embedding,
not Earth calibration. Initial temperatures are exact cell averages of equation
11, including both trigonometric integration factors. Bottom/top theta are 1/0;
sidewalls are insulating and velocity walls are impermeable/free-slip. Zero
composition and zero additional heating are explicit. The retained R3 warm-upward
force convention remains unchanged; no new erratum is asserted for the printed
momentum-sign issue. Changing source cannot rebind an old trajectory automatically.

#### Independent simultaneous endpoint diagnostics

`convection_benchmark.py` re-solves each sampled **accepted endpoint** before
reporting its flow. The two stored RK-stage velocities are not relabelled as that
endpoint. State, force, temperature, rheology, box, time, scaling and clipping
checks bind the new diagnostic to the actual endpoint result.

The diagnostic set includes mean temperature, instantaneous top/bottom Nusselt
numbers, domain and surface RMS velocity, **signed** maximum horizontal surface
velocity, boundary-inclusive sampled viscosity extrema, work, raw dissipation,
`Phi/Ra`, percentage work/dissipation discrepancy, divergence and temperature
bounds. Surface absolute speed and stress-support-only viscosity extrema remain
separate additional channels. The half-cell wall flux is instantaneous, not the
interval-integrated boundary heat in the transport ledger.

MAC dual-volume quadrature is used for RMS velocity. Normal-strain dissipation
is reconstructed at cell centres and shear dissipation at vertices, independently
of the solver's acceptance scalar. The work quadrature uses cell temperature and
centred vertical face velocity. Surface tangential velocity and normal strains
use the nearest interior row; free-slip wall shear is zero. Wall rheology uses
exact fixed-wall temperatures and depth, not adjacent cell temperatures mislabeled
as boundary values. These are declared smooth-field, second-order reconstructions;
they do not find unobserved subcell extrema or prove shear-band resolution.

#### Predeclared maturity and adequacy gates

The JSON contract was saved before the new long trajectories. Its multi-code
reference envelope for Table 2 is the minimum/maximum of all ten applicable
reported values, expanded by 0.5% for rounding/discretisation. The explicit v2
case-specific contributor and normalisation correction above does not change
that margin. This is not a statistical confidence
interval and is only one necessary gate. The published paper does not supply all
of the following universal stopping tolerances; they are Atlas's explicit
numerical acceptance choices, not quotations from the paper.

For steady flow: minimum dimensionless time 0.1, a final window of 0.05 with at
least 101 samples, all ten diagnostic ranges no greater than `1e-4` relative
(with a separate `1e-8` absolute scale), saved temperature-field change no greater
than `1e-4`, and top/bottom heat-flux imbalance no greater than `1e-3`. A finite
sample series cannot prove absence of all between-sample oscillations. A sampled
endpoint must actually match the saved final state for the mature-regime gate.

For periodic flow: ten complete cycles, at least 100 diagnostic samples per
period, stable periods and extrema within 1%, and temperature fields compared
phase-by-phase over the complete cycles with a 1% absolute dimensionless-field
tolerance. Field archives must themselves resolve each period; densely sampled
scalar diagnostics cannot hide sparse stored fields. Case 5b reports **both**
mean cycle minima and maxima, averaged over ten complete cycles, as requested by
the paper. Phase interpolation is a diagnostic only, never an evolved state.

Matched mature-regime adequacy uses meshes 32/64/128, timestep factors 1/0.5/0.25,
and nonlinear tolerance factors 1/0.1/0.01. Finest-pair relative diagnostic-change
gates are respectively 1%, 0.5% and 0.1%, with decreasing, monotone changes or an
explicit unresolved result. Roundoff-level identical values are not assigned an
invented convergence order. Small-grid/transient studies are explicitly exploratory
and cannot satisfy these full-run gates. Tightening includes linear, true momentum
and viscosity-change tolerances together. Non-varied controls and regime/source
identity must match; one endpoint comparison cannot establish adequacy.

`analyse_convection_r4_4.py` verifies actual saved trajectories and reports these
separate gates. `assess_convection_suite_r4_4.py` requires actual three-run studies
for every applicable configuration, reference agreement, conservation/work and
mature-regime checks, actual-code visual inspection, plus a full regression and
bounded resource record bound to the exact current source inventory. Missing or
ambiguous evidence cannot become PASS. The campaign example deliberately has
empty study lists and therefore reports INCOMPLETE_R4_4. Passing these numerical
gates would still not establish Earth/Diadem validity or global tectonic realism.

#### Accepted execution and remaining evidence

The [R4.4 execution contract](OPTIMISATION_REFERENCE.md#3cr4-4-execution) owns the
fixed future schedule, finite total-step envelope, explicit iteration allowance,
resource limits and recovery protocol. No automatic timestep shrinkage, tolerance
relaxation, viscosity floor, alternate-solver fallback or unconverged endpoint is
allowed. Both stages retain current-law and whole-step heat/inventory acceptance.
Accepted states, exact input/source/runtime identities, stage records, balances
and endpoint diagnostics remain bound together. Transactions precede exclusive
atomic receipt publication; changed source/case/future schedule/runtime refuses.
Hard-kill claims are not automatically removed. Failure/cancellation preserves
the last accepted state without publishing a partial endpoint. Relocated-source,
store-copy and fresh-process recovery must preserve these contracts.

The fixed-temperature advection correction uses reflected-wall MC slopes capped
by wall jump in both RK stages and the independent NumPy formulation. Insulating
walls and composition retain their reconstruction. Periodic evidence must reach
the endpoint; final-complete-cycle phase-matched temperature arrays must share the
run's source/configuration/receipt. Nested mesh means restrict to common coarse
cells; time/nonlinear studies retain identical support. Existing axis tolerances
and non-monotonicity rules remain; missing/undersampled data is INCOMPLETE, never
scalar-only acceptance. Bounded preflight, sampling/cadence controls, advisory Courant ceilings and retained
sidecar limits belong to the execution reference. They do not replace evidence or
guarantee a safe future step.

[The dev40 assessment](OPTIMISATION_REFERENCE.md#adaptive-accuracy-and-assessment-limits) retains
the frozen-field spatial-error finding, short corrected-timestep comparison,
unresolved domain-RMS reference miss and rejected stress-support reconstruction.
Those probes are not mature coupled adequacy. Source-bound re-equilibration,
registered mature mesh/time/nonlinear studies, all applicable case/regime
comparisons and assembled regression/resource/recovery/visual evidence remain
required. Case-5b source acquisition is resolved; its full regime/reference
comparison is not. Do not extend a failed coarse-grid result merely by adding
steps, silently rebind old states or run a campaign through known reference
blockers. No unit-test pass, finite run, attractive plot or R4.3 result closes R4.4.

<a id="3cr4-4-native-mechanics"></a>
<a id="3cr4-4-intra-step-guess"></a>
<a id="3cr4-4-exact-source-verification"></a>
<a id="3cr4-4-sparse-template"></a>
<a id="3cr4-4-anderson"></a>
<a id="3cr4-4-cross-step-start"></a>
<a id="3cr4-4-preconditioner-reuse"></a>

#### Numerical-policy and execution boundaries

Exact [native action](OPTIMISATION_REFERENCE.md#3cr4-4-native-execution),
[intra-step guesses](OPTIMISATION_REFERENCE.md#3cr4-4-intra-step-guess-execution),
[source verification](OPTIMISATION_REFERENCE.md#3cr4-4-source-verification-execution),
[sparse templates](OPTIMISATION_REFERENCE.md#3cr4-4-sparse-template-execution),
[Anderson](OPTIMISATION_REFERENCE.md#3cr4-4-anderson-execution),
[cross-step starts](OPTIMISATION_REFERENCE.md#3cr4-4-cross-step-start-execution) and
[preconditioner reuse](OPTIMISATION_REFERENCE.md#3cr4-4-preconditioner-reuse-execution)
retain their detailed policy, identity, memory, refusal and measured-cost contracts
at those existing destinations. They do not change physical laws or confer mature
acceptance.

Full current stress, returned-SI residuals, binary64 and physical thresholds remain
binding. Starting guesses are inputs, never accepted solutions; current forcing
and law must be re-evaluated. Only accepted physical steps may publish successor
state. Operator-split stage flow is not simultaneous endpoint flow. Policies cannot
silently change physical laws, bypass current-law convergence, retry a failed solve
or migrate changed-source/policy trajectories. Exact algorithm parameters and
ownership/refusal controls have their single home at the execution links above.

<a id="work-packages-and-dependency-gates"></a>

<a id="current-implementation"></a>


## 5. Work packages and dependency gates

Each package needs a reviewable case and evidence for its claimed capability.
A failed gate blocks dependants, not unrelated analytical work. This register
defines obligations; CURRENT_STATE owns status. Detailed methods and obtained
results remain at the following owner destinations.

| Package | Method owners |
| --- | --- |
| W00 | [Foundation contracts](FOUNDATIONS.md), selected case and existing execution card |
| W01 | [Sampling](W01_REGIONAL_WORKFLOW.md#initial-condition-sampling), [motion](W01_REGIONAL_WORKFLOW.md#prescribed-motion-to-regional-forcing), [regional workflow](W01_REGIONAL_WORKFLOW.md), [assessment](W01_REGIONAL_WORKFLOW.md#stage-8-combined-acceptance) |
| W02 | [Regional transport, cohorts, remap, ALE and events](FOUNDATIONS.md#w02-regional-case-openclosed-constant-density-thickness-transport) |
| W03 | [Thermal columns](W03_THERMAL_COLUMNS.md), [support](W03_THERMAL_SUPPORT.md), [compaction](W03_COMPACTION.md), [workflow](W03_WORKFLOW.md) |
| W04 | [Loads](W04_COLUMN_LOADS.md), [finite regions](W04_WORKFLOW.md#finite-region-support), [variable rigidity](W04_WORKFLOW.md#fixed-variable-rigidity), [workflow](W04_WORKFLOW.md), [assessment](W04_WORKFLOW.md#combined-supported-workflow-acceptance) |
| W05 | [Regional extension](W05_REGIONAL_EXTENSION.md), [assessment](W05_REGIONAL_EXTENSION.md#combined-acceptance-contract) |
| W06 | [Spreading design](W06_SPREADING.md), [birth](W06_WORKFLOW.md#oceanic-birth-and-spreading), [cooling](W06_COOLING.md), [histories](W06_WORKFLOW.md#changing-motion-histories), [workflow](W06_WORKFLOW.md) |
| W07 | [Mechanics](W07_REGIONAL_MECHANICS.md), [solver](W07_REGIONAL_SOLVER.md), [heterogeneous thermal](W07_REGIONAL_SOLVER.md#w07-step-3--heterogeneous-and-thermal-mechanics), [surface strength](W07_SURFACE_STRENGTH.md), [workflow](W07_WORKFLOW.md), fixed-box [3D mechanics](REGIONAL_MECHANICS_3D.md) / [evolution](REGIONAL_EVOLUTION_3D.md) |
| W08 | [Regimes](W08_REGIMES.md), [shortening](W08_SHORTENING.md), [transform](W08_SHORTENING.md#w08-step-3--transform-and-oblique-motion), [subduction](W08_SUBDUCTION.md), [underthrust](UNDERTHRUST.md), [magmatism](W08_JOINED.md#w08-step-5-finite-source-magmatism), [joined routes](W08_JOINED.md) |
| W09 | [Surface design](W09_SURFACE_PROCESSES.md), [water](W09_WATER.md), [erosion](W09_WATER.md#finite-material-erosion) |
| W10 | [Scoped validation](W10_VALIDATION.md) |
| W11 | [Execution, PF/PT methods and measurements](OPTIMISATION_REFERENCE.md) |
| W12 | [Supported assembly](W12_ASSEMBLY.md); [remaining coupled completion](INTEGRATION_PLAN.md) |

### W00 — Freeze the scientific case and evidence rules

**Question:** what claim is the next experiment actually testing? Produce a short case contract identifying Mode K or M, domain and regime, equations, initial/boundary data, units, physical duration, numerical representation, output quantities and explicit exclusions. Register analytical expectations and failure cases before implementation.

Create three distinct evidence sets: exact/manufactured verification, analogue/observational validation, and Diadem compatibility. Where a published benchmark is used, record the exact setup, source version, input permissions, measured observables and uncertainty. A graph or table in a paper must be acquired and interpreted explicitly; merely citing its title is not an executable fixture.

**Output/gate:** one reviewable case specification with a physical question and quantitative acceptance procedure. Add the compact execution card from [the optimisation reference’s execution card](OPTIMISATION_REFERENCE.md#execution-card): candidate task independence, state ownership, cost/memory estimates, cache identities, equality policy and applicable PF/PT checks. Select finite resources for the specific proposed experiment; unresolved values are not unlimited. No production integration or universal configuration framework.

### W01 — Coordinates, rotations and initial geological fields

**Dependencies:** W00. **References:** P01/P03, E01/E02/E04, F01/F03.

| Stage | Responsibility and scientific boundary |
| --- | --- |
| 1 | Explicit spherical/local/legacy frames, handedness, units and epochs; finite rotations, composition/inverse tests and rigid distances/zero strain. |
| 2 | Planar polygons/traces and conditioned minor-arc patches; metrics, overlays, gaps/overlaps, indexes and persistence. No arbitrary full-sphere Boolean or polygon-soup repair. |
| 3 / 3B | Shared edges/sides/orientation, same-plate seams, cyclic junction sectors, point contacts, canonical vertices and global ownership. A coherent chart or explicit shared binding is required; mismatches are refused rather than welded. Static closure is not dynamics. |
| 3C | Generated partitions retain declared priors. Earth-like acceptance is REOPENED: gap-free Voronoi or area-conditioned geometry, fitted areas and bounded shape measurements do not establish generated dynamics or whole-W01 acceptance. |
| 4 / 4B | Typed materials/cohorts/layers/thermal/fault/weak-zone descriptions with provenance/precedence, condition-aware library and exact bindings. Grain/bulk, pore fluid, reference scalar and constitutive law remain distinct; partial records remain partial. |
| 5 | Fixed-feature point/average/inventory sampling, material-temperature checks, unknown masks, refinement invariance and restoration. Supported geometry/field limits remain explicit; sampling is not evolution. |
| 6 | Prescribed motion into planar strips / axial-Euler hemispheric reductions, moving-frame components, original frozen interval, sided ownership and N+1 velocities. Continuous-section guards refuse unsupported interfaces between faces or out-of-plane motion; unsupported junction-path motion is not a constant-rate port. No force inference. |
| 7 | Actual sampled volumes into W02 cohorts, explicit inflow and unchanged selected MUSCL scheme; original interval, thermal/history provenance and source-bound reuse/continuation. Not unrestricted spherical dynamics or evolved temperature. |
| 8 | Combined representation, workflow, resource/cache and cold-recovery assessment, distinct from whole-package scientific acceptance. A technical pass cannot close S3C, R4.4 or generated-world gates. |

Define compact crust/layer/fault/weak-zone/thermal inputs. A declared seed may
generate a prior but must not embed final mountain geometry. Grid refinement cannot
move geology or invent unsupported properties. Kernels consume the frozen profile
in Section 3.4, not scattered physical literals. Geometry/area error is separate
from physical uncertainty.

**Deliverables/gate:** conventions, pure sampler, known geometry and rotation/profile
fixtures; side/trace reversal, seams/poles, unit/time round trips, rigid metrics and
thermal limits. These qualify representation, not a selected plate history.

### W02 — Conservative material history and boundary events

**Dependencies:** W01. **References:** P02/P05/P11, E03/E10/E11/E23, N01/N02; F02/F04/F06/F07/F13.

Track material identity separately from plate identity and mesh identity. Move material, record birth/removal, and transfer extensive quantities conservatively. Treat particle-to-mesh intensive projection separately. Establish thickness change from area deformation under constant-density analytic cases before variable properties or mixed layers.

Use shared boundaries with explicit side ownership and junctions. Supported ridge opening, subduction retirement, split/merge and active/inactive transitions become events with before/after geometry and mass/area accounts. Do not cure overlaps by deleting material, allocate the same volume to two plates, or reset history when a plate changes identity. Closed-world area coverage must remain valid; regional external exchanges must remain visible.

**Deliverables:** material/event schema, boundary-account reference, moving-point and column tests. **Gate:** known extension/shortening, sharp tagged-material advection, birth-age history, reversible motion where physically reversible, explicit sinks, and unchanged totals under a remap-only step. Event discovery itself remains a declared rule, not a force prediction.

The existing W02 completion is 1D regional, common-velocity, constant-density
and prescribed-kinematics on ColumnGrid1D. It does not supply variable-density,
multi-velocity, general 2D/spherical-junction or predictive source/force laws.
Cohort partial thicknesses sum to the total; exterior and parent-bound transfer
accounts, known/unknown formation dates and zero-volume catalogue entries survive
self-contained snapshots. MUSCL/SSPRK2 remains the accuracy-first regional default;
upwind is a distinct explicit numerical identity. Resource pressure cannot silently
lower accuracy or replace retained fixed-quantum representations.

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

**Subduction:** use a prescribed slab/plate kinematic benchmark with a mechanically computed wedge as the first thermal-mechanical reference. A published community benchmark explicitly uses this mixed approach; it tests boundary and rheological treatment, not spontaneous global plate formation. The delivered bounded implementation and independently derived natural-outflow source resolution are owned by [W08 subduction](W08_SUBDUCTION.md#source-resolution-and-step-4-closure); they do not authenticate every original contributor's code. Follow with a buoyant-slab/free-surface benchmark only if the claimed response needs it. The methods literature warns that viscosity averaging and artificial surface layers can materially change results. [[N-S01][url-019]; [N-S02][url-020]]

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

**Release gate:** supported regime matrix, scientific evidence, finite resource envelope, coherent checkpoint/recovery drill, clean-versus-incremental comparison and truthful documentation. Code approval and physical acceptance remain separate. Main-branch publication requires its own coding/publication scope; this documentation consolidation changes no numerical implementation.

<a id="plate-formation-implementation-plan"></a>

### Causal plate-formation obligations: R1–R9

| Stage | Implementation and deliverable | Acceptance before its dependent claim |
| --- | --- | --- |
| **3C-R1 — Reference data and success criteria** | Extend the existing reference/diagnostic modules to full accessible plate outlines, boundary-step motion and deformation-region data. Preserve raw-source identities, licence, coordinate/time conventions and known uncertainty. Reserve independent regions, reconstructions or model versions for tests not used to choose parameters. Compare at declared physical scales and per-plate resolution. | Check source transcription, sphere-area and perimeter calculations, signs and units against independent values. Register each metric, scientific question, tolerance derivation and holdout split before tuning. PB2002 area-fit values are calibration, not held-out validation; another derivative of the same map is not independent evidence. |
| **3C-R2 — Initial state before final plate labels** | Extend W01's existing geological records with an explicit pre-partition description: continental/oceanic structure, ordered layers, thermal initial state, known formation versus cooling history, inherited weak zones and supported mantle/slab structure. Implement the bounded portion of stage-5 sampling needed to populate test meshes. Distinguish observed, authored, sampled-prior and model-evolved values. | No circular dependency requiring final plates before specifying their geological substrate. Missing thermal/stress/damage state is not filled by unlabeled noise. Seeded fields have documented amplitudes/scales and stable streams; mesh refinement does not redraw the prior. Authored states remain unchanged. |
| **3C-R3 — Freeze the physical closure** | Select one reference rheology, then one memory model; document viscosity, yield, healing, composition, heating and surface/boundary choices. Obtain complete methods/supplements before reproducing a paper. Give each law a versioned parameter profile and finite validity envelope. Separate body forces from prescribed tractions to avoid double-counting slab pull or other forcing. | Hand-calculated constitutive values, reference-unit conversions, temperature/pressure/strain-rate limits, zero-damage and healing-only solutions. The 20°C material catalogue is not a mantle-creep model. Localisation needs demonstrated mesh-independent regularisation; a numerical viscosity floor is disclosed, not treated as measured material strength. |
| **3C-R4 — Verified thermal/mechanical core** | Build the selected W07 structured staggered finite-volume pilot with W03 heat evolution and conservative composition transport. Begin in a 2D box: constant viscosity, then variable viscosity/yielding and the applicable Tosi benchmark cases (PF-C14). Reuse existing numerical interfaces/budgets; a small native sparse direct solution is an independent reference, with preconditioned native iterative solves for larger verified workloads. | Manufactured velocity/pressure, boundary/pressure null-space handling, mass/divergence and heat accounts, space/time/nonlinear convergence and published benchmark diagnostics. Two-dimensional success establishes a solver component, not planet-wide shapes, trench curvature or transform segmentation. |
| **3C-R5 — Process experiments, not decorative contours** | Test weak-zone reactivation against healed/undamaged controls; inherited-structure rifting; segmented spreading and transform development; one-sided subduction with an appropriate surface/interface treatment; curved-trench fragmentation and small-block formation. Use 3D regional geometry when the claimed feature varies along strike. Run paired cases that change one causal ingredient rather than fitting every output. | Each process reproduces its selected independent benchmark/analogue constraints and remains stable under refinement and rotated mesh orientation. Do not require damage to have one universal effect, place a plume beneath every ridge, infer polarity from convergence, or count a 2D cross-section as an along-trench fragmentation test. A failed family remains unsupported. |
| **3C-R6 — Spherical dynamics and plate identification** | Extend the verified formulation to a coupled 3D spherical shell, using globally consistent metric terms and pressure/interface treatment. Existing surface patches are output geometry, not a ready volume mesh. Recover coherent surface regions from independently calculated velocity/strain/damage fields, and fit Euler rotations to candidate interiors. Keep distributed deformation explicitly represented. | Spherical benchmark and rotation/seam tests, conservation, parameter and resolution sensitivity, declared spin-up and sample-selection rules, rigidity residuals and stable segmentation thresholds. A warm-up ends by registered diagnostics, not because one image looks Earth-like. Never prescribe Euler poles then claim recovering them proves independent rigidity. |
| **3C-R7 — Shared geometry and causal event history** | Convert supported field-derived boundaries into the existing shared-edge atlas; maintain one edge, two sides and consistent junctions. Fit boundary/junction velocities subject to the selected kinematic rules. Track persistent material, weakness, plates and events separately; record splits, merges, reactivation, accretion/export and candidate rejection. Use conservative multidimensional transfers where needed; reuse W02 contracts, not its 1D equations under a spherical name. | Underlying surface coverage remains complete without forcing every cell into a perfectly rigid plate; deformation zones do not vanish as polygon gaps. Boundary extraction has a spatial error budget and does not move material. Junction compatibility is stricter than the telescoping sum of relative velocities. Preserve origin/energy/history through events and cold restoration. |
| **3C-R8 — Initialisation and W01 integration** | Supply a named starting-epoch workflow: load an authored/reconstructed state, use a declared statistical candidate, or evolve an accepted dynamic precursor and select its state by the recorded rule. Any faster reduced generator must be calibrated on process results and checked independently before adoption. Map the resulting geology, supported motion and fields through W01 sampling into appropriate regional W02 scenarios. | No manual stitching, unknown-as-zero state or regenerated world on restore. Identical provenance yields the agreed reproducibility. Exact plate-count requests are only supported where the selected origin model warrants them; dynamic mode does not forcibly merge bodies to hit a UI number. An initialisation pass is not complete global material/thermal evolution. |
| **3C-R9 — Independent acceptance and selected default** | Run predeclared ensembles, holdout-data challenges, mesh/time/parameter sensitivity, controls and ablations, then combined execution/cache/storage/restoration/platform checks. Keep accepted regimes, failures and source-bound evidence at their existing owner destinations; CURRENT_STATE owns the active checkpoint. | Keep calibration, numerical verification, physical validation and fictional compatibility separate. No universal percentage realism score; no pass from a lone attractive map or small global-average error hiding lost microplates. Promote the appropriate accuracy-first optimised recipe only for supported regimes. Report platform/resource limits and retain explicit verification/control paths. |

The R1 delivery is limited to the reviewed present-day PB2002 uses described in
the reviewed source-use contract. It does not satisfy the independent-model or historical challenges
reserved for R9. Those unavailable observations cannot be filled from modern Euler
poles or another reformat of PB2002.

### Required observations and failure tests

Use multi-scale area distribution, compactness, elongation/concavity, turning and
segmentation by boundary type, topology and adjacency, small-plate position relative
to margins, intraplate deformation, relative motion, weak-zone persistence,
reorganisation and heat/material accounts. Plates and broad deformation zones are
not interchangeable labels (PF-C15). Total perimeter must ignore computational
seams. Sampling density must not improve a morphology score by adding vertices.
A plate population is temporally variable; do not fit exactly one modern spectrum
(PF-C10). Held-out observables must not have already selected the same parameters.

Numerical thresholds come from the declared equations, source precision and
refinement study, not convenient post-hoc tolerance changes. Use at least three
resolutions for appropriate convergence cases, vary time step independently, and
keep geometric tolerances distinct from physical uncertainty. Model ensembles and
steady/transient sampling windows are registered before scoring, including failed
seeds and error bars. Data versions with shared ancestry are sensitivity challenges,
not additional independent samples.

Reference/statistical, prescribed-kinematic and dynamically produced origins are
different scientific claims, recorded independently of K/M calculation mode. M
may start from an explicit statistical prior; a mature starting epoch need not be
simulated from a magma ocean. Exact plate count, copied Earth outlines, random
wiggles or a fit to Diadem mountains are not acceptance criteria.

R2/R8 credit relevant W01 initialisation; R3–R6 credit the named W03/W07 and
W06/W08 subsets rather than duplicating those modules. W03 sediment compaction,
full W04 loading, other W08 regimes, W09 surface work and production remain separate.
The 1D W02 completion does not establish planetary material evolution. W11's
relevant checks accompany each stage; no later blanket optimisation pass is implied.

After R1–R3 there is a specification/input path, not simulated boundary formation;
after R4–R5, individually supported regional solver/process behaviours, not
whole-planet acceptance. R6–R9 can qualify only tested regimes, laws, resolutions
and data challenges. Statistical candidates remain controls. No stage table
authorises coding, a new solver, a large simulation or resumption through a hold.

[Formation execution](OPTIMISATION_REFERENCE.md#plate-formation-execution-plan)
owns detailed implementation/resource choices. Comments beside code must identify
equations, units, assumptions, contribution ownership, invalidation and failures.
Cases/tests remain beside implementation; no extra general scheduler, cache,
compression format or planning supplement is required.

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
| O01–O17 scientific-software methods and retained engineering patterns | [Scientific methods](OPTIMISATION_REFERENCE.md#scientific-methods) and [engineering methods](OPTIMISATION_REFERENCE.md#engineering-methods) |
| Retained engineering screening lessons and non-goals | [Adoption and boundaries](OPTIMISATION_REFERENCE.md#method-adoption) |
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

### 7.4 Performance obligations by package

| Work | Required performance planning |
| --- | --- |
| W00 | Define the finite case, equality/error policy, inputs, cost/memory estimate and relevant PF/PT checks. The execution card belongs with its case, not in another general-purpose document. |
| W01–W04 | Keep explicit parameters, array/batch interfaces, accepted/candidate ownership and valid setup reuse. No compulsory worker pool for a tiny fixture. |
| W05–W09 | Specify physical coupling barriers, shared-face ownership, bounded scratch and necessary enabling acceleration. Verify the numerics independently of physical acceptance. |
| W10 | Parallelise independent cases/diagnostics where valid. Keep stable random identities and validation separate from performance tuning. |
| W11 | Measure enabling work when needed; then compare accepted behaviour at matched error and broaden the workload envelope. No speculative whole-world speed multiplier. |
| W12 | Carry only supported backends, compatible fixtures and tested cache/recovery behaviour into production. |

<a id="verification-physical-validation-and-decision-rules"></a>

## 8. Verification, physical validation and decision rules

### 8.1 Four independent gates

| Gate | Evidence | What passing does not mean |
| --- | --- | --- |
| **V1: implementation verification** | Units/signs, manufactured/analytic solutions, conservation, field bounds and declared invalid-input refusal. | The constitutive law is true for a geological setting. |
| **V2: numerical adequacy** | Mesh/time/coupling/domain refinement, appropriate residuals, remapping/rounding error and resolved physical features. | A visually plausible field matches independent observations. |
| **V3: physical adequacy** | Withheld analogue/geophysical/geological observables and sensitivity/uncertainty within a defined regime. | Every world, scale, history or boundary condition is covered. |
| **V4: world compatibility and release** | Required authored constraints, provenance, resources, output/restart consistency and named supported capabilities. | Approval to replace authored world inputs or an untested generic-planet guarantee. |

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

### 11.3 Decision points for a capability extension

Resolve the next case's observables, domain/duration, exact data access and finite
budget in W00. Existing decisions in specialist contracts are not reopened merely
because an old generic plan names their design gate. New W07 claims need compatible
discretisation/C01/C02, thread/solver ownership and true residuals; W08 needs its
productivity/recycling, transitions and magma closures; W09 needs water/storage/
sediment closure. W11 studies need the actual numerical baseline, workload,
hardware, error criteria and limits; broad scale claims also need relevant W10
physical evidence. W12 needs runtime/fixtures, release scope, recovery and rights
plus the integration plan's finish rules.

Resolve each missing decision in the smallest affected package. Do not restart
completed stages, decide every planetary process before a bounded mechanism, or
treat a documentation gate as authority to change scientific criteria.

## 12. Review and continuation

Use CURRENT_STATE for the next authorised action and actual holds. INTEGRATION_PLAN
governs the remaining coupled route. Neither this plan nor an old next-stage
sentence starts it.

Review the K/M distinction, N01/N02/E28 accounts and exclusive load/heat ownership;
explicit C01–C07 closures; falsifiable evidence independent of desired geography;
regional versus planetary scope; matched-error execution and nonlocal coupling;
source identities, resources, random streams and recovery. A finding should name
the equation/contract, plausible failure, supporting evidence and smallest required
correction. Preferences alone are not defects; AI agreement is not physical proof.

Meaningful actual-code visual QA remains required for relevant stage delivery.
Record units, source identities and display transformations; inspect geometry,
slivers, discontinuities, unknowns, material/age joins, antimeridian and poles
where applicable. Distinguish renderer defects from model defects and authored
inputs from predictions. A stage with no meaningful visual observable records
that limit. Attractive plots cannot replace numerical/physical gates or owner
review. Delivery reports retain a clear changelog and relevant before/after changes;
they do not grant publication or source-rebinding authority.

## References and evidence scope

The pre-study register remains historical evidence, not a separate maintained planning file. The historical basis comprises the four pre-studies and original three benchmark leads; selected R3/R4 sources are additionally recorded in their case contracts above. Revision 2 adds PS01–PS08: targeted official documentation about execution, parallel randomness, solver reuse, storage and measurement, checked on 16 September 2026. Dynamic documentation is not a pinned or installed runtime; select exact versions before implementation. Proposed Atlas rules are design judgements, not blanket claims about those packages. No source is evidence that Atlas ran or passed a test.

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

**[N-S01][url-019] — van Keken et al. (2008): A community benchmark for subduction zone modeling.** The original planning source was the primary institutional record and abstract. Subsequent [W08 source work](W08_SUBDUCTION.md#papers-and-software-checked) acquired the author-hosted paper, cases and reference rows, and records the bounded five-case comparison and independent natural-outflow derivation. Historical contributor-code equivalence remains NOT_VERIFIED; the delivered source interpretation is not an author-confirmed erratum or spontaneous-subduction result.

**[N-S02][url-020] — Schmeling et al. (2008): A benchmark comparison of spontaneous subduction models—Towards a free surface.** Peer-reviewed primary methods paper; publisher abstract/preview. Numerical/laboratory comparison; viscosity averaging and free-surface sensitivity. No figures/tables or performance results reproduced.

**[N-S03][url-021] — Schreurs et al. (2006): Analogue benchmarks of shortening and extension experiments.** Primary institutional bibliographic record. Candidate benchmark identified only. Full experimental configuration and data must be obtained before use.

<a id="research-basis"></a>

### Historical research basis

R01 (modelling), R03 (implementation feasibility) and R04 (the 28-equation/15-process cross-reference) are the dated pre-studies already supplied in this conversation. They remain source material, not additional maintained plans, and are not reproduced here. R02’s optimisation methods and the retained engineering methods now have their maintained home in the [optimisation reference](OPTIMISATION_REFERENCE.md). The primary scientific sources above continue to support the plan. A reference to R04 preserves an equation identifier; it does not assert that every R04 equation is fully specified or implemented here.


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
