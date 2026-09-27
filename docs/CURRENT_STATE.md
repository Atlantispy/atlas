# Atlas: current development state

**Updated: 27 September 2026. WORKING NON-CANON.** This is the current
development summary, not scientific acceptance or a finished world dataset.
The active repair checkout is `remake`; the changes below are local and not yet
committed or pushed. Check the actual checkout before continuing.

## Active checkpoint

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

The independent [composition-aware phase prerequisite](../tectonics/docs/I01_PHASE_PARTITION.md)
now retains solid/liquid component inventories after extraction. Nine tests pass
in 0.001 s; the [analytical campaign](../tectonics/evidence/i01-phase-partition-r1.json)
passes in 0.056310 s. Removing 1,000 kg liquid from the 10,000 kg binary control
leaves 9,000 kg with 1,000 kg liquid; fixed-P/T re-equilibration preserves that
residue to 1.03e-12 kg per component. Reusing the initial composition would
incorrectly imply 1,800 kg liquid. Three interleaved 200-call medians are
0.0020979 s Newton versus 0.0163525 s bisection: 0.0142546 s / 87.17% saved,
mass parity 2.37e-9 kg. This is an analytical supplied-partition control, not
mantle calibration or a world speedup. The common phase enthalpies, energy datum
and pressure-work law are still required before energy-bearing melt delivery.

The independent [composition-aware caloric closure](../tectonics/docs/I01_PHASE_ENERGY.md)
now derives solid/liquid composition and energy from one ideal-mixture law,
inverts supplied enthalpy and transfers finite liquid with its component energy.
Twelve focused tests pass in 0.016 s, including independent thermodynamic
derivatives, pure/congruent latent plateaux, signed energy references and refusals.
The [analytical extraction/cooling campaign](../tectonics/evidence/i01-phase-energy-r2.json)
passes in 0.4004804 s. Its 10000 kg source carries 5.8 GJ; extracting 1000 kg
transfers 0.9 GJ and leaves 4.9 GJ. Recovered residual temperature differs by
1.69e-10 K; the source/solid/surroundings energy residual is 1.20e-7 J.
Three interleaved 40-call medians: safeguarded Newton 0.0192148 s versus
bisection 0.1134367 s, saving 0.0942219 s / 83.06%, with 2.32e-8 K temperature
parity. The initial passing r1 result remains historical after improving the
Newton safeguard; physics and tolerances were unchanged. This is a kernel
comparison and an analytical ideal-mixture closure, not calibrated mantle
petrology or a completed Katz-to-W08 join. The native receiver, evolving-pressure
work and physical extraction/supply remain separate connections.

The compatible [finite magma receiver](../tectonics/docs/I01_MAGMA_RECEIVER.md)
now connects prescribed extraction to same-pressure composition/enthalpy mixing.
Thirteen tests pass in 0.010 s; the [bounded campaign](../tectonics/evidence/i01-magma-receiver-r1.json)
passes in 0.1822241 s. Independent pure/binary results include crystallisation,
induced melting, mixing entropy and pressure-volume work without double-counting
latent heat. Repeated donor/receiver energy residual is 1.91e-6 J. Three interleaved
20-call medians for eight co-arriving parcels: batched 0.0126724 s versus sequential
0.0470029 s, saving 0.0343305 s / 73.04%, temperature parity 2.28e-13 K. This closes
the bounded compatible-receiver seam, not pressure transport, material calibration,
physical extraction rates, native emplacement or I02 persisted transactions.

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
coupled controls. Next is the physical breakup closure choice and its bounded
feasibility, not another admission optimisation. A thin-continent cutoff is not ocean birth, nor is
a prescribed event a generated transition. I02 remains unstarted.
No full-world run, native source edit, installation, commit or push was performed
for this continuation.

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
classifies **41 records: twenty-four current, sixteen historical and one superseded**.
Current items are the Step 7 r2 *case matrix* and the B1 diagnostic tool/input
bindings, the Windows installation receipt bound to its package-version record,
and I01's initial, 2D, pressure/temperature, corrected transition, nonlinear
motion-admission, actual-column and finite-strain admission, phase-aware delivery, dry melt production,
composition-aware phase partition, caloric closure and compatible magma receiver, nonlinear column,
reviewed thermal/history, evolving column weakening, layered column heat,
resistance-to-motion, force-driven thermal/motion, finite-strain, coupled finite-water/flexure and columns-to-GPE/torque
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
