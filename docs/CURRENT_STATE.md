# Atlas: current development state

**Updated: 28 September 2026. WORKING NON-CANON.** This is the current
development summary, not scientific acceptance or a finished world dataset.
The active repair checkout is `remake`; the changes below are local and not yet
committed or pushed. Check the actual checkout before continuing.

## Active checkpoint

The [connected 3D regional advance](../tectonics/docs/REGIONAL_EVOLUTION_3D.md)
now takes actual solved deformation through conservative component-mass,
enthalpy and scalar-history transport, conduction, supported weakening/healing
and endpoint constitutive/mechanical feedback. Finite-mode driving responds to
the changed resistance. All six faces have finite inflow stocks/explicit exports;
the transport representation preserves exterior driving and reports its bounded
interior correction. Twelve transport tests pass in 6.569 s, thirteen heat tests
in 7.460 s, and nine joined tests in 19.8664455 s. No skips. The
[new receipt](../tectonics/evidence/regional-evolution3d-r1.json) passes in
25.9262947 s. On its 3x3x3 quiescent connected fixture, preparation reuse takes
0.5050915 s versus 1.1233156 s rebuilt: 0.6182241 s (55.04%) saved, with
bit-identical state/mechanical arrays. These small Windows timings are not a
planetary forecast. The previous mechanical sources and receipt are unchanged;
adding three package modules changes execution identity, not old evidence bytes.

The current branch is first-order, fixed-box Boussinesq evolution with scalar
memory. Next connections are objective elastic/finite-strain tensor history,
compatible moving surfaces, actual spherical plate mapping and physical
separation/junction reorganisation. MC-05 and I01 remain open. Whole-planet
evolution, interacting regional feedback and measured planetary resource use
remain explicit I11 requirements, with ownership across I03/I04/I07/I09.

The [declared elastic-core connection](../tectonics/docs/I01_ELASTIC_CORE.md)
is reviewed and integrated as MC-07's bounded single-layer choice. The same
layer now supplies both bending stiffness and load-transfer depth. Eighteen
focused tests pass in 0.246 s; all [six controls](../tectonics/evidence/i01-elastic-core-r1.json)
pass in 0.184093 s. Review corrected oversized-number refusal and clarified the
flat-reference approximation; no physical law or tolerance was retuned.
At 16,384 cells, the added median cost is 0.0201 ms (1.57%), not a speedup.
Four I01 choices remain open: separation, initiation resistance, the calibrated
melt provider, and physical junction reorganisation (MC-01/02/03/05).
The [separation-law candidate](../tectonics/docs/I01_SEPARATION_LAW.md) requires
correction before admission. Its 24 initial tests pass in 0.329 s and nine local
controls in 0.0438411 s, but targeted review found missed plastic evolution at
exact yield, inconsistent residual-cohesion/event semantics and numeric-range
failures. Proposed transport/healing wording also needs correction. These are
pre-correction prototype results, not a physical separation or MC-01 pass.
MC-02 now has a [selected resolved-initiation method](../tectonics/docs/I01_INITIATION_DECISION.md)
and [prospective comparison record](../tectonics/cases/i01_initiation_decision_v1.json).
It keeps stress/plastic history, explicit pore pressure and physical weakening
length, and separates a genuine force-release test from a prescribed-velocity
reaction crossing. The [input/comparison tool](../tectonics/tools/check_i01_initiation_inputs.py)
now checks source/review coverage and prepares source-bound comparison plans.
It compares signed force against convergence at both curves' knots and integrates
work with explicit extraction uncertainty and predeclared allowances. Thirteen
focused synthetic tests pass in 0.037 s, with no skips, including the recovered
source-record guard. The original paper now supports explicit case-23 plate roles (40 Myr
right/subducting; 10 Myr left/overriding) and recorded material constants.
Basal temperature remains conflicting, several complete input profiles remain
missing. All 28 reported graphical readings have now been received, but their
extraction omitted the script, coordinate calibration and exact vector selection.
They remain outside the active reference curve pending a reproducible extraction.
Missing definitions,
reference data and allowances remain explicit; preparation refuses them. This is
comparison machinery, not an initiation simulation or solver-input adapter.
Complete benchmark inputs and comparison allowances remain outstanding, so MC-02
is not closed. No physical calibration or numerical acceptance threshold was guessed.
Actual core inputs remain declared; general support and boundary assembly belong
to I04/I08. This does not mark I01 or generated-world acceptance complete.

The [junction-contact prerequisite](../tectonics/docs/I01_JUNCTION_EVENTS.md)
now locates exact contact between declared constant-velocity planar junction
paths, including a collision with no sign change in squared distance. Ten tests
pass in 0.001 s and nine controls in 0.130276 s. Preparation reuse saves
11.9981 ms (84.613%) for 1,000 identical queries, not a world-run speedup.
This is separate from choosing a physically permitted replacement boundary:
MC-05 stays open, with graph/state/spherical integration still assigned to I03/I09.
The next [outgoing ridge prerequisite](../tectonics/docs/I01_RIDGE_JUNCTION.md)
now checks both proposed junction velocities and ownership-oriented forward
growth. Nine tests pass in 0.002 s; nine controls in 0.169193 s. For 300 repeated
length queries, immutable preparation takes 0.5156 ms versus 24.3163 ms rebuilt,
saving 23.8007 ms (97.8796%) in this small helper only. It rejects impossible local
continuations but supplies neither physical boundary birth nor a full geometry
certificate. No retained contact/transition source or old receipt was rewritten.
The [physical reorganisation route](../tectonics/docs/I01_JUNCTION_REORGANISATION.md)
is now selected: evolve a local multidirectional region using shared material
mechanisms, then jointly extract and commit its physically supported topology.
The [case record](../tectonics/cases/i01_junction_reorganisation_v1.json) fixes
3D conventions, ownership, timing/accounting obligations and nine prospective
controls. The new 3D mechanical component above now supplies a tested solve;
MC-05 remains open for evolving shared physics, topology and physical acceptance. Contact and
compatible movement are completed pieces, not completed reorganisation.

Work follows [the completion roadmap](ATLAS_ROADMAP.md): repair reliability and
evidence, then correct tectonics realism before expanding the other modules.

The [future-module scopes](MODULE_SCOPES.md) now define the 17 non-tectonics
categories' input producers, ownership, connected implementation slices, feedbacks
and acceptance responsibilities, including usability and performance. This is
planning only: it does not change the active tectonics checkpoint or certify those
modules complete. Use these scopes when preparing subsequent implementation briefs.

| Work | Current delivery status | Detail |
| --- | --- | --- |
| A1: review repairs | First repair batch implemented and checked: W12 export/surface policy, bundle inspection/staging and line-ending digest corrections. | [Repair record and exact checks](../tectonics/docs/REVIEW_REPAIRS_2026-09-26.md) |
| A2: evidence status | Checker and bounded register integrated. Historical runs are not relabelled as current numerical acceptance. | [Evidence guide](CURRENT_EVIDENCE.md) |
| A3: source capacity | Limit raised from 128 to 512 Python files, retaining complete hashing and the 2 MiB inventory bound; focused regressions pass. | [Capacity repair](../tectonics/docs/REVIEW_REPAIRS_2026-09-26.md#a3-follow-on-bounded-source-inventory-capacity) |
| A4: public paths | Three W07 historical reports redacted with explicit old/new digest provenance and a regression guard. | [Publication repair](../tectonics/docs/REVIEW_REPAIRS_2026-09-26.md#a4-follow-on-public-path-redaction) |
| A5: tested environment | Windows AMD64 CPython 3.12.14 pins and clean-install evidence reviewed and integrated: all 39 packages install, metadata/dependency checks and ten environment tests pass, and compiled-library/basic rendering smoke checks succeed. Linux and an Atlas visual workflow remain unverified. | [Environment guide](TECTONICS_ENVIRONMENT.md) |
| A6: status and change granularity | One current summary replaces the accumulated status log; no separate archive copy. Scoped delivery and evidence-impact guidance recorded. | [Change procedure](CODING_SAFETY.md#5-source-only-check-and-change-procedure) |
| B1: matched boundary diagnostics | Tool integrated; one retained original/prototype comparison at 100/250/500 km against PB2002 development. Portable inputs, signed components and declared exclusions retained. Prototype motion is not refitted; this is not realism acceptance. | [Method and measured checkpoint](../tectonics/docs/NEW_WORLD_MOTION.md#matched-boundary-diagnostics-roadmap-b1) |
| B2: causal-generation diagnosis | Code trace and a bounded two-candidate experiment completed. New World saves initial conditions; crust does not affect its plate layout. No producer fix implemented. | [Causes and research](../tectonics/docs/NEW_WORLD_LAYOUT.md#causal-generation-diagnosis-and-replacement-design) |
| Complete tectonics integration | I01 contracts and bounded controls include 2D localisation, pressure/temperature response, evolving thermal/plastic history, finite-strain columns, column resistance, melt production/delivery and transition accounts. Spatial embedding, calibrated rupture and generated transitions remain open; I02–I12 are not started. | [Integration plan](../tectonics/docs/INTEGRATION_PLAN.md), [I01 contract](../tectonics/docs/I01_PHYSICAL_CONTRACT.md), [finite-strain method](../tectonics/docs/I01_FINITE_STRAIN.md), [thermal/history](../tectonics/docs/I01_THERMAL.md), [melt production](../tectonics/docs/I01_MELTING.md), [transition controls](../tectonics/docs/I01_TRANSITIONS.md) |

Claude's A5 follow-up is now integrated. It installed into a separate ignored
environment without modifying the scientific environment. The retained receipt
establishes a Windows installation and library smoke check, not native restart
compatibility or scientific acceptance. Linux was unavailable and none was installed.
The owner rejected post-generation fairing as the realism fix, even
when applied to native geometry. Its integration was stopped before source edits.
The owner authorised continuation of **I01: end-to-end contracts and physical
closure choices**. The [four bounded controls](../tectonics/evidence/i01-controls-r1.json)
pass in 0.507892 s after imports; 15 focused tests pass in 0.035 s. These are
prototype/analytical checks outside the native package, not a world run. The final
1D refinement changes stress by 0.2640% and width by 0.07073%; halving the timestep
changes them by 0.01550% and 0.06905%. A first trial exposed round-off-induced
nonuniformity in homogeneous softening; a mathematically equivalent constant-
preserving filter solve fixed it without changing tolerances. The failed local
trial remains retained; native source and old evidence were not rewritten.

The new [2D probe](../tectonics/evidence/i01-fault2d-r1.json) passes its predeclared
33/65/129-grid and 128/256-step controls. Finest-grid changes are 0.01555% in
effective stress and 0.00204% in plastic participation area; timestep halving
changes them by 0.21355% and 0.83230%. Oblique analytical laminates, genuinely 2D
right-angle covariance, uniform history and mechanical work balance also pass.
Eight focused tests pass in 0.113 s. This is fixed-temperature, fixed-material-
coordinate plane strain with prescribed effective strength, not pressure-sensitive
friction, arbitrary-angle fault nucleation, geological calibration or rupture.
No native source or original I01 r1 file was changed.

A scoped single-thread BLAS policy reduced this exact small-control campaign from
[66.1528 s](../tectonics/evidence/i01-fault2d-threaded-r1.json) to 55.3882 s:
10.7645 s / 16.27% less wall time in one comparison. The finest effective stress
differs by 1.97e-7 Pa (about 1.6e-14 relative); all gates remain unchanged.
This is a control-run observation under background load, not a repeated benchmark
or a whole-generator speedup. Thread settings restore after the CLI finishes.

The separate [pressure/temperature connection](../tectonics/evidence/i01-strength-r1.json)
now solves dynamic-pressure feedback on friction together with temperature-dependent
creep, at a supplied thermal/history snapshot. All predeclared 17/33/65-grid,
analytical pressure/temperature, full momentum/work and warm/cold parity checks
pass in 0.259867 s after imports; ten focused tests pass in 0.096 s. Analytical
maximum relative error is 1.33e-8. These smooth snapshots agree to round-off in
the three refinement metrics; that is not a fault-band or thermal-time convergence claim.
Reusing the preceding mechanical state for a 5 K change takes 0.028711 s versus
0.039453 s cold: 0.010742 s / 27.23% less in one small comparison, with 224 versus
321 Krylov iterations and unchanged acceptance gates. No whole-generator saving
is inferred. The first test exposed a 2.05e-15 manufactured-wave phase round-off
error; integer periodic phase construction fixed it without changing tolerance.
The original I01 and 2D sources/receipts are unchanged. This closes the bounded
pressure/temperature-to-mechanics connection, not thermal/history evolution,
geological calibration, arbitrary-angle fault nucleation or rupture.

Claude's D6 delivery is reviewed and integrated as bounded design controls.
Codex corrected missed sub-tolerance crossings, sampled-touch false events,
invalid component transfers cancelling in a joint transaction and observer-
dependent junction residuals. Thirty-two focused tests pass in 0.087 s; all six
[corrected controls](../tectonics/evidence/i01-transitions-r2.json) pass in
0.1847716 s after imports. The original r1 receipt is unchanged and historical.
The separation bound is explicitly linear-only; nonlinear handoffs need an
actual before/after error certificate. Melt-column inventory and transmitted
slab-force work are no longer described as full production/energy closures.

The independent [nonlinear motion-admission control](../tectonics/docs/I01_DECOUPLING.md)
is now implemented for a declared scalar resistance family, with exact rational
threshold decisions and conditional finite-window speed/displacement/work bounds.
Twelve focused tests pass (0.005 s); its controls pass in 0.065826 s after imports.
One comparison of 100 prepared-law checks takes 0.0235752 s by exact bisection
versus 0.0005243 s directly: 0.0230509 s / 97.78% saved, with identical decisions.
This fixes the reduced nonlinear admission calculation, not physical rupture or
an automatically established envelope for D2's evolving coupled state.

The [actual-column admission connection](../tectonics/docs/I01_COLUMN_ADMISSION.md)
now derives a conservative exact bound from the retained mixed-creep column,
without fitting its exponents or changing the rheology. Ten focused tests pass
in 0.011 s; all eight [control checks](../tectonics/evidence/i01-column-admission-r1.json)
pass in 0.1361079 s. A homogeneous analytical motion differs by 1.80e-12 relative;
the inherited layered column is honestly not certified at a 1% omission allowance.
Three interleaved batches of ten public admission calls take median 0.0187222 s
rebuilding versus 0.0011830 s reusing the envelope: 0.0175392 s / 93.68% saved
with identical outputs and guards retained. This is gate-only timing, not a
simulation speedup. The bound covers the represented fixed column, positive
extension and nondecreasing history with the existing total strain ceiling;
changing geometry/thermal state and physical separation remain separate work.

The independent [phase-aware melt-delivery interface](../tectonics/docs/I01_DELIVERY.md)
now separates only existing available liquid, debits the finite source and feeds
unchanged W08 emplacement and explicit crystallisation/cooling accounts. Twelve
tests pass (0.006 s); the analytical/connected controls pass in 0.0243872 s after
imports. The 10,000 kg control delivers 1,000 kg and retains 9,000 kg, with zero
reported energy residual including 1.08e9 J transferred to the surroundings.
This closes the bounded phase-accounting seam, not extraction-rate, permeability,
focusing or mantle phase-equilibrium physics. The D6 inventory is not reused as
a production flux. Native sources and earlier bound receipts remain unchanged.

The independent [nonlinear column-resistance control](../tectonics/docs/I01_COLUMN.md)
adds SI/invariant creep laws, consistent regularised friction and force/work
integration of supplied depth profiles. Eleven focused tests pass (0.006 s);
the layered sensitivity/refinement campaign passes in 0.0549932 s. Doubling
quadrature from 64 to 128 points per layer changes force by 0.0366%. One ten-solve
prepared local-law comparison takes 0.0003556 s by bisection versus 0.0000464 s
by safeguarded Newton: 0.0003092 s / 86.95% saved, with matching stresses. The
immutable preparation reuses coefficients only while profiles are unchanged.
This gives a constitutive/column diagnostic, not a resolved rupture force or
a substitution into the existing evolving mechanical solver. Mean pressure is
supplied explicitly, not inferred from a vertical-overburden approximation.

Claude's [thermal/material-history prototype](../tectonics/docs/I01_THERMAL.md)
is reviewed and integrated as a bounded control. Temperature and accumulated
plastic history now evolve together with pressure-sensitive mechanical response
in the small-strain material/reference cell. Review closed direct-entry validation
gaps and rejected unsupported representation/nested-mechanics declarations; no
physical equation, fixture input or acceptance tolerance changed. Thirteen focused
tests pass in 0.274 s; all five [reviewed controls](../tectonics/evidence/i01-thermal-r2.json)
pass in 6.396674 s after imports. Unchanged strength/fault helper checks were reused.
One matched warm/cold comparison takes 0.552737 s versus 1.606948 s: 1.054211 s /
65.60% saved, with 4.03e-10 relative outcome difference. This is not a whole-world
speedup or finite-strain transport result. Original r1 evidence remains historical
and byte-identical; no native/desktop code changed.

The independent [dry decompression control](../tectonics/docs/I01_MELTING.md)
now calculates retained melt production and its thermal feedback along supplied
pressure paths, including clinopyroxene exhaustion. Nine focused tests and the
[exact/tighter-reference campaign](../tectonics/evidence/i01-melting-r1.json) pass;
the campaign takes 0.024851 s after imports. The two parcel solves take 0.001126
and 0.0013724 s, agreeing with the tighter reference within 0.000962 K and
1.30e-6 mass fraction. A five-run median comparison takes 0.0015835 s using
numerical derivatives versus 0.0009269 s analytically: 0.0006566 s / 41.47% saved,
with 5.86e-8 K temperature difference. This is a microbenchmark, not world speedup.
The path differential and thermal accounts are not presented as conserved full
enthalpy or an absolute entropy state function. Batch melt remains in its source;
compatibility with the existing common-Tm delivery law is not yet established.

The [composition-aware partition](../tectonics/docs/I01_PHASE_PARTITION.md),
[caloric closure](../tectonics/docs/I01_PHASE_ENERGY.md),
[reversible pressure connection](../tectonics/docs/I01_PHASE_PRESSURE.md) and
[finite magma receiver](../tectonics/docs/I01_MAGMA_RECEIVER.md) now use stable
per-component phase inventories. Previously subtracting almost all liquid from
bulk material corrupted the tiny remaining solid's composition and could reject
a valid near-liquidus state. The smaller phase inventory is now computed directly
for each ingredient; the larger is its mass complement. No physical law, root
solver or acceptance tolerance changed. Positive inventories that underflow are
refused, not silently discarded.

Forty-nine affected test methods pass: 35 phase/energy/pressure tests in 0.045 s,
13 receiver tests in 0.011 s, and the added extreme-partition/underflow method in
less than 0.001 s. Independent tie-line tests include 1e-9 disappearing phase
fractions and partition coefficients from 1e-12 to 1e12. Heat and entropy
inversions now recover states 1e-6 K inside both phase boundaries within the
unchanged 1e-7 K criterion. The former cancellation refusal is fixed; unresolved
root conditioning and physically unsupported inputs still refuse.

Four affected source-bound campaigns pass, taking **1.260587 s combined after
imports**: [partition r2](../tectonics/evidence/i01-phase-partition-r2.json)
0.0579674 s, [energy r3](../tectonics/evidence/i01-phase-energy-r3.json)
0.4114995 s, [pressure r2](../tectonics/evidence/i01-phase-pressure-r2.json)
0.6031263 s and [receiver r2](../tectonics/evidence/i01-magma-receiver-r2.json)
0.1879935 s. Their predecessors remain unchanged and historical. These small
campaigns were rerun because their shared numerical dependency changed, not
merely to refresh a status label.

The same-law connections retain component depletion, enthalpy/entropy accounts,
latent plateaux, independent pressure-work integrals and finite receiver mixing.
Pressure changes distinguish delta H = integral V dP from work into material
delta U = -integral P dV. Each pressure sample uses the original source entropy.
A liquid-only receiver still refuses a solid-bearing parcel instead of dropping
its solid mass.

The [common-provider connection contract](../tectonics/docs/I01_THERMO_PROVIDER_CONTRACT.md)
now defines shared identity, component basis, SI units, supported domains,
P/T-H-S requests, extensive accounts and explicit failure semantics. It maps the
retained analytical interfaces for reuse instead of duplicating them. This is a
completed interface specification, not an implemented external adapter or a
calibrated material; MC-03's model/data, extraction, focusing and thermal-lid
choices remain open. Concrete calibration inputs are being researched separately.

Current matched microbenchmarks retain the existing optimisations: partition
Newton 0.0020329 s versus bisection 0.0164274 s per 200 calls (87.62% saved);
enthalpy Newton 0.0197450 s versus 0.1164076 s per 40 calls (83.04%);
entropy Newton 0.0282109 s versus 0.1398615 s per 40 calls (79.83%); eight-parcel
batch mixing 0.0129064 s versus sequential 0.0479586 s per 20 calls (73.09%).
These compare unchanged alternative algorithms, not the old and repaired
inventory arithmetic; **no speedup is claimed from this correctness repair**.

The endpoint review checked the Chemicals 1.5.2 Rachford-Rice numerical notes;
the retained methods document Keller-Katz, R_DMC, Cantera and pyMelt research.
No external package was installed or run. This remains an analytical ideal
mixture, not calibrated mantle petrology, single-phase thermal expansion,
a physical extraction/flow-rate law, native emplacement or I02 persisted transfers.

Claude's [strength-to-evolving-weakening adapter](../tectonics/docs/I01_WEAKENING.md)
has been reviewed and accepted for its bounded column scope. It evolves raw
plastic history and returned resistance with consistent vertical/mean pressure,
under fixed rate or fixed force. Codex corrected mutable prepared storage,
unchecked changed providers, direct execution ceilings and invalid window bounds;
the physical equations, case and numerical tolerances are unchanged. Seventeen
tests pass in 0.137 s; all seven [reviewed controls](../tectonics/evidence/i01-weakening-r2.json)
pass in 0.948857 s. Evolving inherited history lowers resistance by 1.9688% in
the base case; at fixed force the rate rises by 23.0%. One bitwise-matched reuse
comparison takes 0.0347743 versus 0.2257254 s, saving 0.1909511 s / 84.59%.
This does not supply lateral localisation, finite-strain or heat feedback, or
physical breakup. The independent finite-column heat connection is now reviewed
as described below; its shared helpers remain unchanged.

The [layered column-heat connection](../tectonics/docs/I01_COLUMN_HEAT.md) now
couples conduction, mechanical heating and temperature-dependent weakening on
the same depth support. Review corrected volume-weighted layer means and refused
mismatched geometry/heat capacity, including a 101 km inventory presented as a
100 km column. Nineteen focused tests pass in 0.144 s; all seven
[reviewed controls](../tectonics/evidence/i01-column-heat-r2.json) pass in
1.4607544 s. Valid-case physical values are unchanged from r1. A matched reuse
comparison takes 0.0846096 s versus 0.3576032 s rebuilding the conduction operator:
0.2729936 s / 76.34% saved with bitwise parity. This is a bounded control, not a
world speedup. The corrected volume-mean warming is 2.46964 / 5.39403 / 6.19947 /
0.80917 K across the four layers. Motion remains prescribed in that reference
slice; the force-driven connection is now reviewed separately below.

The [force-driven thermal/motion connection](../tectonics/docs/I01_THERMOMECHANICAL_MOTION.md)
now joins the two reviewed adapters: force balance, conduction and thermal/plastic
weakening share every integration stage. Twelve focused tests pass in 0.367 s;
all six [controls](../tectonics/evidence/i01-thermomechanical-motion-r1.json) pass
in 3.6730768 s. At order 64, heating increases endpoint speed by 1.8111% against
the same-force feedback-off run; finest depth velocity changes by 0.0106924%.
Peak warming is 1.99986 K and axial strain 0.00937044. Independent homogeneous
temperature/history orders are approximately 2.00; same-state force/work,
once-only heat, rest/compression and atomic refusal checks pass. One matched
warm/prepared run takes 0.1979926 s versus 1.1310399 s cold/rebuilt, saving
0.9330473 s / 82.49% with 1.43e-12 relative parity. This is a bounded-control
timing, not a world forecast. Review required no numerical correction or fixture
retuning; results were separated from the source-bound method document before
the campaign. Finite-strain transport and physical separation remain open.

Codex completed the independent [resistance-to-motion connection](../tectonics/docs/I01_MOTION_COUPLING.md):
external drive balances disjoint drag and actual layered resistance at each
history-integration stage. Motion is solved, not prescribed. Eight focused tests
pass in 0.157 s; the [bounded campaign](../tectonics/evidence/i01-motion-coupling-r1.json)
passes in 1.209959 s. Finest time/depth velocity changes are 8.20e-9 / 1.36e-4
relative, with work residual 2.80e-13. Warm starts take 0.0926285 s versus
0.4459559 s cold: 0.3533274 s / 79.23% saved in one matched small control,
relative outcome difference 7.99e-13. A compression overshoot found during testing
was fixed by safeguarded log-rate steps, without changing physics or tolerance.
This fixed-temperature regional connection does not claim spherical assembly,
finite strain or separation. It reads reviewed helpers, not Claude's new files.
I02 remains unstarted.

The independent [finite-water/flexure control](../tectonics/docs/I01_WATER_FLEXURE.md)
now couples crustal bending, shoreline position and the same finite water volume
on a constant-rigidity 2D periodic plate. It retains physical mean subsidence and
forebulge uplift, uses dry restoring force to avoid counting water twice, and
returns total equilibrium against an unloaded bed. Ten tests pass in 0.062 s;
the [32²/64²/128² campaign](../tectonics/evidence/i01-water-flexure-r1.json) passes
in 0.113740 s. Finest-pair RMS displacement changes by 0.002723% of the supplied
200 m mean water depth. At 128² cells, verified wet-set reuse reduces five-run
median time from 0.0072849 to 0.0050188 s: 0.0022661 s / 31.11% saved, with
6.26e-13 m maximum displacement difference. This is a local microbenchmark.
Finite regional boundaries, variable rigidity and whole-world coupling remain
I08 work; neither it nor the parallel weakening task is claimed complete here.

The independent [columns-to-driving connection](../tectonics/docs/I01_GPE.md)
now computes dry support and GPE from the same material/thermal columns,
then feeds calculated spherical traction into the retained D1 torque solver.
It keeps reference material mass separate from thermal buoyancy and avoids
double-counting ridge push. Ten tests pass in 0.007 s; the
[three-refinement campaign](../tectonics/evidence/i01-gpe-r1.json) passes in
0.0428281 s. Finest analytical rotation error is 0.0100396%, decreasing by
approximately four per refinement. Five interleaved medians for 4,096
three-layer column moments: scalar 0.0075236 s versus vectorised 0.0001414 s,
saving 0.0073822 s / 98.12%, relative parity 2.38e-16. This is a kernel
microbenchmark, not a whole-generator speedup. It closes this dry D1/D5
feasibility connection, not I04 world sampling/evolution or water-loaded GPE.

The [material-following finite-strain column](../tectonics/docs/I01_FINITE_STRAIN.md)
is now reviewed for its closed affine strip. Twenty-three tests pass in 1.146 s;
all seven [corrected controls](../tectonics/evidence/i01-finite-strain-r2.json)
pass in 13.6352926 s. Review corrected the compression comparator, deadline
expiry during final work, and prescribed-control temperature-window admission.
The original failed r1 receipt remains unchanged; physics and tolerances were
not retuned. The 100 km strip widens to 113.03765 km and thins to 88.46610 km,
carrying temperature/history and conserving mass and heat capacity. Geometry
feedback increases endpoint speed by 43.00%, against a finest depth change of
0.007993%. Reusing the conduction eigensystem and warm guesses takes 1.0343286 s
versus 4.2503381 s: 3.2160095 s / 75.66% saved, relative parity 2.00e-11.
This closes bounded finite-strain coupling, not lateral transport or rupture.

The [finite-strain motion-admission connection](../tectonics/docs/I01_FINITE_ADMISSION.md)
is reviewed: nineteen tests pass in 0.416 s and all five
[bounded controls](../tectonics/evidence/i01-finite-admission-r1.json) in 1.9174636 s.
Issued states now carry their actual cumulative clock/history; edited or rebuilt
states cannot regain a used horizon. Review also closed externally mutable heat
operators. The homogeneous strip is certified at 10%, not 1%; the layered strip
remains honestly uncertified. Three interleaved 40-call medians take 0.1439293 s
rebuilding versus 0.0027452 s reusing the bound: 0.1411841 s / 98.09% saved with
identical answers. This is admission-only timing, excluding evolution. The bound
is conditional, process-local and does not authorise rupture or a solver switch;
efficient persisted continuation belongs to the subsequent state/transport work.

Remaining D2/D6 physical decisions include spatially resolved material transport,
calibrated through-thickness weakening and rupture, compatible melt extraction/supply,
generated initiation resistance/polarity, and global embedding of these bounded
coupled controls. The delivered [breakup closure candidate](../tectonics/docs/I01_BREAKUP_CLOSURE.md)
is now **reviewed as analytical feasibility only**, not a resolved breakup event.
Thirty-seven tests pass in 1.228 s; all five [corrected controls](../tectonics/evidence/i01-breakup-closure-r1.json)
pass in 0.5484289 s. Review corrected the speed sum, unsupported convergence
claim, plastic-regularisation asymptote and geometric/thermal validity statements.
The fixed power-law/quadratic basis is explicit; n>4 is refused even when a
finite slope sample looks acceptable. Resolved connectivity loss remains
UNRESOLVED, with no generated event authorised. The retained column's 0.550579
plastic-work share is an unsupported reduced-route regime, not a universal
no-breakup theorem. Deadline checks now operate inside the integration, and
quadrature reuse has immutable backing and a two-entry cache. The prior private
diagnostic is historical; a new public source-bound receipt is registered.
A thin-continent cutoff is not ocean birth, nor is
a prescribed event a generated transition. I02 remains unstarted.
The reviewed [I01 closure matrix](../tectonics/docs/I01_CLOSURE_MATRIX.md) now maps
16 process rows, five user routes and seven physical-choice items to
their producers, evidence and later implementation owners. Its proposed
floor-truncated breakup certificate was withdrawn: six analytical cases checked
with the actual ladder helper confirm that an apparent finite limit can retain
positive rock thickness. Crustal disconnection, through-lithosphere separation
and mechanical handoff remain distinct. The [basal-boundary choice and accounts
(MC-04)](../tectonics/docs/I01_BASAL_CLOSURE.md) are now reviewed: 50 focused
tests pass in 0.087 s and all eight [bounded controls](../tectonics/evidence/i01-basal-closure-r1.json)
pass in 0.0237441 s. Inventories fill the stated volume, insulating/outflow
conditions constrain heat, endpoint proposals match their source accounts and
the strip cannot export lithosphere as asthenosphere. An independent exact
Newtonian flow checks traction, gravity and dissipation signs without setting
one term to close the balance. I05 transport and I07 resolved boundary coupling,
solver tolerances and depth sensitivity remain later implementation. The
separation mechanism stays open. The elastic-memory subchoice is now to retain
stored stress, as recorded below. The reviewed water-loaded-column pressure/GPE
connection (MC-07) and its declared single-core producer now pass bounded checks;
no material depth is assumed as a numerical default.
The [separation-diagnostics decision](../tectonics/docs/I01_SEPARATION_DECISION.md)
and [design case](../tectonics/cases/i01_separation_decision_v1.json) now complete
NA-01's specification: material and union connectivity, distinct physical widths,
whole-window maximum motion error and its replacement reference speed. The exact
positive-thickness counterexample is retained. This is a documentation decision,
not an implemented event detector or scientific run; the remaining open choices
are listed at the active checkpoint and I02 still owns the production motion tolerance.
Matrix paths, references and public/static checks pass; unchanged scientific
receipts are reused. This is reviewed planning, not a new physical event.
No full-world run, native source edit, installation, commit or push was performed
for this continuation.

The independent [lateral-conduction criterion](../tectonics/docs/I01_LATERAL_HEAT.md)
now selects MC-06's error rule: bound omitted contact heat flow over the whole
interval and compare its temperature effect with a declared allowance. Twelve
focused tests pass in 0.876 s; ten [control checks](../tectonics/evidence/i01-lateral-heat-r1.json)
pass in 0.0710187 s. The exact two-cell error is 0.1498426 K, below the 0.15 K
bound. Preparation and evaluation use sparse contacts, not a dense solver.
This is a conditional thermal-model decision, not permission to omit conduction
throughout a moving coupled neck. I05/I06 own the actual contacts, whole-window
bounds and coupled application.

The independent [elastic-memory choice and control](../tectonics/docs/I01_ELASTIC_MEMORY.md)
retains stored stress for the future rift and selects a logarithmic-objective
constitutive direction. Twelve tests pass in 0.002 s, and all nine
[bounded controls](../tectonics/evidence/i01-elastic-memory-r1.json) pass in
0.1475084 s. Exact coaxial loading, relaxation, rigid rotation and independently
integrated heat/work are checked; general shear is refused. Prepared coefficients
save 3.189 ms (34.781%) over 2,000 identical local updates, with bit-identical
results. This is a local setup-reuse measurement, not a generator speedup.
I02/I05/I07 still implement persistent transport and the general coupled law;
MC-01's separation mechanism remains open.

The reviewed [water-to-GPE connection](../tectonics/docs/I01_WATER_GPE.md) carries
the actual loaded-column stress into gravitational driving without a second
water load or isostatic rebalance. Nineteen tests pass in 0.207 s and all eight
[controls](../tectonics/evidence/i01-water-gpe-r1.json) in 0.2123609 s after imports.
The two reviewed admission gaps are corrected: negative depths refuse, and small
nonuniform bending cannot be misclassified as exactly compensated. Uniform water
adds no traction to the existing dry field; a flat surface alone does not imply
zero dry gravitational traction. Independent Fourier/pressure integrals check
the formula and reference changes. The 16,384-cell join and traction median is
1.6438 ms; the separate retained water solve is 4.0505 ms. No matched baseline
exists, so no percentage saving is claimed. Finite-rigidity joins still require
an explicit effective shear depth and basis; the separately reviewed single-core
producer now supplies them for its selected branch. I04/I08 own spherical and
boundary integration.

The owner brought the Windows `.exe` build forward before I01 completion.
**Atlas Desktop 0.1.0 is built and checked on Windows** with Electron 44.4.5,
relocatable CPython 3.12.14 and all 39 pinned distributions. The approximately
799 MB application folder includes its runtimes and opens without development
Python, Node or terminal commands. See [desktop instructions](../desktop/README.md).
The existing UI owner's 33-file runtime snapshot is packaged without a redesign;
its saved-result reader now waits for child exit during shutdown.

Packaged acceptance: the actual executable created a six-plate/192-support-cell
world, exported it, loaded it through the UI file input, saved it using the real
Save World button and reopened it with identical world-view fields. This took
20.009 s after initial window load. A second process restored the same origin,
profile and world in a 2.539 s check. The actual globe/interface screenshot was
inspected. Both processes exited successfully; no Atlas processes remained.
The first restricted-runner attempt could not launch Chromium's renderer; normal
desktop execution passed with sandboxing retained. Startup failure/timeout is now
reported instead of leaving a blank hung launch. No native scientific source,
compatibility guard or old receipt was changed. The build is unsigned, Windows-only,
and does not complete I01 or later scientific integration.

## Evidence: what the results establish

The [registered evidence](../tectonics/evidence/current-evidence.json) currently
classifies **54 records: thirty-three current, twenty historical and one superseded**.
Current items are the Step 7 r2 *case matrix* and the B1 diagnostic tool/input
bindings, the Windows installation receipt bound to its package-version record,
and I01's initial, 2D, pressure/temperature, corrected transition, nonlinear
motion-admission, actual-column and finite-strain admission, phase-aware delivery, dry melt production,
composition-aware phase partition, caloric and phase-pressure closures, compatible magma receiver,
analytical breakup feasibility, exact affine junction contact and outgoing ridge feasibility, basal-boundary accounts, conditional lateral-heat omission, elastic memory, nonlinear column,
reviewed thermal/history, evolving column weakening, layered column heat,
resistance-to-motion, force-driven thermal/motion, finite-strain, coupled finite-water/flexure, water-loaded GPE, declared elastic core and columns-to-GPE/torque
controls bound to their source/specification. None establishes
generated-world physical acceptance. W01-W12 records outside that
bounded register remain unclassified,
not implicitly accepted. The checker verifies declared bindings, not physics or
every transitive dependency.

Step 7 r2, bundle r2 and the complete motion-frame r2 receipt are historical after
native or unbound integration dependencies changed. Their measurements remain
evidence for the original snapshots. Preserve the original receipts and runtime
identities; do not silently repin them. Focused repair checks and their exact
scope are in the repair record above. No new simulation is implied by this page.

## Latest route

- **Scientific reader guide:** [How tectonics is made](../tectonics/docs/HOW_TECTONICS_IS_MADE.md)
  explains individual methods within W01-W12, seeded worlds and the separate
  experimental dynamics route. Its [I01 chapter](../tectonics/docs/how-it-works/06-physical-integration.md)
  adds the coupled physical-process controls and their remaining integration seams.
  It connects plain-English explanations to research,
  code and scoped evidence; documentation does not renew numerical acceptance.
- **Native tectonics and new-world adapters:** substantial W01-W12 implementation,
  supported regional evolution, saved-result inspection and project/bundle
  handling. Use the [tectonics ownership and implementation plan](../tectonics/docs/TECTONICS_PLAN.md)
  and the [active code-route map](CODING_SAFETY.md), not a historical "next step".
- **Wider generator:** implementations through `engineering/work/generator_upgrade_r31/`,
  with component entry points across 18 categories. That is not 18 complete or
  scientifically accepted systems. See [category scope](../README.md#the-18-modelling-categories).
- **Execution and retained terrain:** runtime R12 and retained connected scheduling;
  native terrain R5 is the bounded storage/session route retaining R1-R4, not the
  entire generator or a new general solver. Shared histories are dependencies.
- **Public component development:** [independent development](INDEPENDENT_DEVELOPMENT.md)
  uses explicit new public bindings and selected fixtures, not historical native
  restart or a full world-generation demonstration.

The retained R5 branch/storage measurement was 3.696854 to 0.680990 seconds and
7,996,951 to 879,786 added bytes, across three matched already-loaded branch
comparisons. Ordinary interval timing was 0.60% slower. This remains a recorded
branch/storage result, not a new timing run, solver speedup or world-scale forecast.

## Boundaries

Generated-world tectonics realism is still open: grid-shaped boundaries,
restrictive starting-crust shapes and an ocean-age field needing explicit history.
The saved boundary helper remains a prototype, not integrated acceptance.
Mountain/terrain realism and a complete whole-world/whole-year run are not accepted.

R4.4 remains held and incomplete. No broad scientific campaign, change to physical
tolerances, removal of source/runtime guards or increase to the retained native
terrain 256-interval ceiling is authorised here. Do not add or multiply unrelated
historical speedup ratios into a whole-generator claim.

Read-only inspection and exact native continuation have different requirements.
Private inputs, codecs and runtime dependencies are not supplied by a public
source snapshot; byte recovery alone is not a restart. Diadem canon, local
integration, Git commit and publication remain separate states.

## Maintaining the current view

The [product and scale contract](PRODUCT_AND_SCALE_CONTRACT.md) remains the product
direction, not a completed capability inventory.

Update this page in place. Do not keep dated copies or accumulate superseded
status updates; Git history can retain committed document versions. Keep method
details and necessary test receipts in their existing records, not duplicate
status archives. Older code still imported by the active route is not redundant.
Make small descriptive commits only when authorised, with their evidence impact
stated; see the change procedure. No old result becomes current just because this
summary changes.
