# Current evidence register

30 September 2026. WORKING NON-CANON. Roadmap Phase A2.

Old receipts remain useful history, but documentation must not present one as
evidence about the current checkout after the bytes it bound have changed. The
[register](../tectonics/evidence/current-evidence.json) is the explicit list of
classified evidence; `tools/check_current_evidence.py` is its read-only checker.

## Run it

From the repository root, standard library only (Python 3.10 or later):

```text
python -B tools/check_current_evidence.py
python -B -m unittest discover -s tests -p test_current_evidence.py -v
```

The checker never imports Atlas, runs a campaign, edits a receipt, repins a
digest or writes a file. It exits 0 on a pass and 1 on any failure. Each failure
names the record, the receipt field, the bound file and both digests. `--register`
selects another repository-relative register; paths inside a register are always
repository-relative.

## What each status means

| Status | Meaning | Checked |
| --- | --- | --- |
| `current` | Relied upon for a claim about this checkout. | The receipt must keep its registered bytes. Every repository file it binds must still have the recorded SHA-256. Every digest-bearing receipt field must be either a checked binding or an explicit `not_checked` entry (`runtime`, `artefact` or `historical`) with a reason. |
| `historical` | Retained for its recorded source snapshot; not a current claim or new validation. | Only that the file still exists with its registered bytes. Code moving on never fails it. |
| `superseded` | Replaced for current claims by the named `superseded_by` record. | As historical. The successor must exist, must not be invalid and must not form a cycle. No current record may bind it. |
| `invalid` | Known to be wrong for its own sources; kept only as a trail. | As historical. No current record may bind it, and it cannot be a successor. |

A pass means only that the declared bytes match. It is **not** runtime,
native-execution, platform or scientific verification. Recorded timings and PASS
results remain observations of the original run. Nothing is re-executed.

## Coverage today

The [current connected evidence chain](#successor-capture-after-i022a-and-the-writer-correction)
contains eight successors captured on 30 September 2026 after the I02 cold-restart
stress-resolution correction, plus the unchanged `i01-column-r2` receipt reused
from 29 September. All eight bounded captures passed. The five
phase/receiver/separation writer-correction receipts and G25 receipt captured on
29 September also remain current; their inputs were unaffected and were not rerun.
The replaced receipts are superseded and remain byte-identical. The separate
separation-performance comparison remains historical.
No physics gate is waived. `python -B tools/check_current_evidence.py` prints the
live record counts; this page does not repeat them.

The superseded entries below retain their original measurements and timings;
those numbers are historical observations, not measurements of the new successors.
Use the linked current receipts in the capture table for the new run results.
I02 evidence covers the bounded column's shared state, continuation, exchanges,
accepted clock and save/reopen workflow; it does not establish physical-event or
whole-world acceptance.

I02 adds engine-owned restoration (`restored()`) to the finite-admission tool.
[i01-finite-admission-r5](../tectonics/evidence/i01-finite-admission-r5.json) now
binds that tool, its method document, the restoration modules and the renewed
upstream receipts. Its predecessor r4 is superseded, with its recorded bytes intact.
Restoration checks consistency in a trusted local store, not authorship of records.
Repair batch R1 (30 September 2026) changed two restoration modules r4 binds
(`src/atlas_tectonics/timebase.py` and `src/atlas_tectonics/w08_inventory.py`).
Successor r5 was captured after R1 and its dtype-identity correction were integrated;
all five controls passed with unchanged sources. Its valid upstream receipts were reused.
See the [I02 workflow method](../tectonics/docs/I02_WORKFLOW.md#8-evidence-effects).

The current [I02 workflow timing receipt](../tectonics/evidence/i02-workflow-timing-r5.json)
was recaptured on 30 September 2026 after the automatic 3-D evolution restart
admission fix changed two bound package modules. Multigrid-first remains unchanged.
It supersedes r4, captured after the multigrid-first choice was applied locally;
r4 superseded r3's earlier uncommitted choice, r3 superseded r2, and r2 succeeded r1
after R1. None was rewritten. r5 records five repetitions on one Windows machine,
unchanged sources and passing equality/parity comparisons. Its 151 source-file digests
are checked by the register; its opaque package/native `execution_identity` is
classified as an unchecked runtime observation. A further change to any package
source makes r5 stale in turn. The column does not use the 3-D solvers; this renews
source bindings, not a 3-D speedup measurement. This is operational timing, not scientific
acceptance, a whole-generator speed claim or other-platform evidence.

I02.1 adds a package module, changing source membership and native execution
identity even though existing physical code is unchanged. The three registered
whole-package records below are therefore historical. Their original successful
measurements remain useful; none was rewritten or rerun to refresh its label.

- **Reviewed melt-segregation numerical evidence:** [nine control groups](../tectonics/evidence/i01-melt-segregation-r1.json)
  pass in 0.1425885 s after imports; 21 tests in 0.031 s. Analytical and manufactured
  solutions, refinement, gravity reversal, mass/pressure balances, dry limits,
  boundary conditions and bit-identical factor reuse support the instantaneous
  1D method. This is not live G25-to-receiver evolution. The receipt is historical
  because three documentation links were corrected after capture; the scientific
  tool, case and tests still match its hashes. No numerical rerun or repinning was
  needed for that link repair. Median savings for 16 changed loads are 1.9642 ms
  (47.36%) at 256 cells and 4.7928 ms (42.32%) at 4096 cells, with an unchanged
  operator. [Method, interfaces and consulted sources](../tectonics/docs/I01_MELT_SEGREGATION.md).

- **Superseded spatial separation feasibility — historical measurements:** [six controls](../tectonics/evidence/i01-separation-feasibility-r3.json)
  pass in 6.391 s; eighteen focused tests pass. Reusing an immutable banded
  Cholesky factor preserves the physical model, input checks and refinement gates.
  Receipt v2 correctly calls the imposed quantity shear displacement, not normal
  opening. A [matched comparison](../tectonics/evidence/i01-separation-performance-r1.json)
  measures 0.4640272 to 0.3708135 s for the same prepared 64-cell/4000-step run:
  **0.0932137 s / 20.0880% saved**. Event brackets are identical; other outputs
  differ only by round-off (largest absolute difference 7.11e-15).
  Initial preparation is excluded. This is not a whole-generator speed claim
  or full lithosphere breakup. [Method and sources](../tectonics/docs/I01_SEPARATION_FEASIBILITY.md).

- **Current independent initiation verification:** [sixteen controls](../tectonics/evidence/i01-initiation-verification-r1.json)
  pass in 0.0009773 s after imports; eight tests in 0.006 s. Analytical gravity-flow,
  real force release versus clamping, and separate gravitational/elastic work
  checks replace dependence on an incomplete archive for I01 method selection.
  They do not validate a subduction event. Full I07 acceptance is retained.
  [Method and consulted sources](../tectonics/docs/I01_INITIATION_VERIFICATION.md).

- **Historical multidirectional junction feasibility:** [eight real 3D solves](../tectonics/evidence/i01-junction-feasibility-r1.json)
  pass the symmetry, load, material-direction, rotation, ownership and independent
  force/torque/power controls in 2.5066567 s; three tests in 3.144 s. This supports
  the selected regional route, not physical boundary birth or a world graph edit.
  [Method and consulted software](../tectonics/docs/I01_JUNCTION_FEASIBILITY.md).

- **Current corrected local separation candidate:** [nine controls](../tectonics/evidence/i01-separation-law-r1.json)
  pass in 0.0452191 s and 35 focused tests in 0.359 s. Exact-yield drive, residual
  cohesion, separate softening/bond events and explicit history support are
  corrected. The final positive fracture-energy guard also rejects underflow
  after division by two, without imposing a physical minimum. This is an exact
  local synthetic-law check, not calibrated rupture, generated separation or
  MC-01 closure. [Method and research basis](../tectonics/docs/I01_SEPARATION_LAW.md).

- **Superseded experimental G25 melt connection — historical measurements:** [Windows receipt](../tectonics/evidence/i01-gibbs-provider-r2.json)
  passes in 21.740828 s; sixteen analytical tests pass. Corrected G25 through
  pinned MAGEMin supplies common-Gibbs phase H/S/V, finite extraction, changed-bulk
  checks and fixed-pressure H/S recovery. Inversions now require a declared
  continuous branch bound to provider, controls, pressure and actual inventory;
  both endpoints and all bisection samples must retain its phase identities.
  This refuses demonstrated crossings, not a proof excluding unsampled ones.
  Median exact-repeat requests take 1.4718673/0.0002556 s uncached/cached:
  1.4716117 s (99.9826%) saved. Dry KLB1 remains a software reference, not
  withheld geological calibration or source-to-crust evolution.
  [Method and sources](../tectonics/docs/I01_THERMO_PROVIDER_CONTRACT.md).

- **Historical connected 3D regional evolution:** [retained receipt](../tectonics/evidence/regional-evolution3d-r1.json)
  binds the package, all three new test modules and the method/tool. Nine joined
  tests pass in 19.8664455 s; twelve transport and thirteen heat tests separately
  pass in 6.569 s and 7.460 s. The receipt's tests and matched timing pass in
  25.9262947 s. Its small 3x3x3 quiescent fixture takes 1.1233156 s rebuilt versus
  0.5050915 s prepared: 0.6182241 s / 55.04% saved with bit-identical outputs.
  This is first-order fixed-box Boussinesq material/thermal evolution and
  constitutive/force feedback, not elastic-tensor, free-surface or planetary
  acceptance. See [method and consulted sources](../tectonics/docs/REGIONAL_EVOLUTION_3D.md).

- **Historical 3D regional mechanics receipt:** [six controls](../tectonics/evidence/regional3d-r1.json)
  bind the implementation, all package source files, its method and focused tests.
  Eleven element tests and thirteen solver tests pass (0.020 s and 4.899 s).
  The small 4x4x4 check passes in 1.7613544 s, including exact fields and
  bit-identical reuse. Median rebuilt/prepared/cached calls take
  0.2708626/0.0845028/0.0392329 s: preparation saves 0.1863598 s (68.80%),
  exact-result reuse 0.2316297 s (85.52%). This is fixed-region mechanics and
  finite-mode force feedback, not geological history or planetary acceptance.
  The source checker does not verify the recorded native execution identity.
  The later transport/heat/evolution module additions change package identity;
  this unchanged receipt retains its original mechanical measurement scope,
  not current whole-package runtime acceptance. Its bound method document now
  describes the new tools-only Euler plate connection, so the receipt is historical
  for that documentation drift; the original numerical code and tests were not
  changed or rerun. Seven focused plate-adapter tests separately passed in 4.675 s.

- **Current I01 elastic-core connection:** [six controls](../tectonics/evidence/i01-elastic-core-r1.json)
  pass in 0.184093 s; eighteen focused tests pass in 0.246 s. One declared rock
  layer produces both bending rigidity and the depth at which load is carried
  sideways. Independent smooth-pressure/Fourier checks support the
  [bounded MC-07 selection](../tectonics/docs/I01_ELASTIC_CORE.md), not inference
  from a thermal/strength profile or arbitrary curved-plate acceptance. At 16,384
  cells the added median cost is 0.0201 ms (1.57%); this short comparison is not
  a speedup or a world-runtime estimate. I04/I08 retain spherical and boundary work.
- **Current I01 outgoing ridge prerequisite:** [nine controls](../tectonics/evidence/i01-ridge-junction-r1.json)
  pass in 0.169193 s; nine focused tests pass in 0.002 s. Exact symmetric-ridge
  endpoint constraints and ownership-oriented growth reject incompatible,
  stationary or reversed local continuations. [Method and sources](../tectonics/docs/I01_RIDGE_JUNCTION.md)
  distinguish local feasibility from boundary birth and complete geometry.
  Preparation reuse saves 23.8007 ms (97.8796%) for 300 repeated length queries,
  not a world-run speedup. MC-05 remains open.
- **Current I01 junction-contact prerequisite:** [nine controls](../tectonics/evidence/i01-junction-events-r1.json)
  pass in 0.130276 s; ten focused tests pass in 0.001 s. Exact affine planar
  contact detection catches a double root without a sign change and preserves
  tiny near misses. Reusing the prepared path saves 11.9981 ms (84.613%) over
  1,000 repeated queries, not a world-solver speedup. [Method and sources](../tectonics/docs/I01_JUNCTION_EVENTS.md)
  distinguish this implemented helper from physical reorganisation, graph edits
  and later moving-world integration, which it does not provide.
- **Current I01 water-to-GPE connection:** [eight controls](../tectonics/evidence/i01-water-gpe-r1.json)
  pass in 0.2123609 s after imports; nineteen focused tests pass in 0.207 s.
  Dry/Airy/uniform limits, finite-flexure Fourier fields, datum changes and
  independent pressure integrals check the join. Negative depth refuses; small
  nonuniform support cannot bypass the shear-depth requirement. At 16,384 cells,
  the join and traction take a median 1.644 ms, with no baseline saving claimed.
  [Method and sources](../tectonics/docs/I01_WATER_GPE.md) leave the material
  producer to the separate elastic-core connection above; weak/broken plate-boundary
  assembly remains later work. The original receipt has not been rewritten.
- **Current I01 elastic-memory control:** [nine checks](../tectonics/evidence/i01-elastic-memory-r1.json)
  pass in 0.1475084 s, with twelve focused tests in 0.002 s. The future rift
  retains stored stress; the exact local update separates stored energy from heat
  and rejects general shear. Prepared coefficients give bit-identical results,
  saving 3.189 ms (34.781%) over 2,000 updates in the bounded benchmark, not a
  whole-generator speedup. [Method and sources](../tectonics/docs/I01_ELASTIC_MEMORY.md)
  distinguish this coaxial control from the later general finite-strain implementation.
- **Current I01 basal closure:** [reviewed controls](../tectonics/evidence/i01-basal-closure-r1.json)
  bind four new files and three retained cases. Fifty focused tests pass in
  0.087 s; all eight controls pass in 0.0237441 s. Geometry-bound inventories,
  thermal boundary conditions, endpoint-account matching and strip containment
  are checked. An independently integrated exact Newtonian flow tests traction,
  gravity and dissipation signs. This selects MC-04's boundary/account contract,
  not a numerical flow solution or coupled I05/I07 acceptance. Sources and
  deferred resolved checks are in the [method](../tectonics/docs/I01_BASAL_CLOSURE.md).
- **Current I01 lateral-conduction criterion:** [bounded controls](../tectonics/evidence/i01-lateral-heat-r1.json)
  bind the four new files. Twelve focused tests pass in 0.876 s; ten control
  checks pass in 0.0710187 s. The analytical error is 0.1498426 K against an exact
  0.15 K bound. This selects a conditional semi-discrete thermal criterion,
  not omission throughout a coupled neck; [assumptions and sources](../tectonics/docs/I01_LATERAL_HEAT.md)
  remain explicit. No solver-speed improvement or old-receipt rewrite is claimed.
- **Superseded I01 breakup analytical feasibility — historical measurements:** [five refreshed controls](../tectonics/evidence/i01-breakup-closure-r2.json)
  passed in 0.5319846 s against the then-current finite-strain/heat chain. The fixed
  power-law analytical route, per-rung limits and numerical gates are unchanged.
  Resolved events and retained-lithosphere breakup remain UNRESOLVED; no
  physical separation or world acceptance is granted.
- **Superseded I01 reversible pressure/energy connection — historical measurements:** [pressure-work controls](../tectonics/evidence/i01-phase-pressure-r2.json)
  bind the method/tool/test/case and corrected partition provider. Thirteen tests
  pass; the campaign passes in 0.6031263 s. Independent pure work integrals,
  binary pressure integration and the receiver connection distinguish enthalpy
  change from external work. Matched 40-call medians: 0.0282109 s Newton versus
  0.1398615 s bisection, saving 0.1116506 s / 79.83%, parity 1.07e-8 K.
  Stable minority-component arithmetic fixes the false near-liquidus refusal;
  heat and entropy inversion pass 1e-6 K inside both phase boundaries. No tolerance
  relaxation, mantle calibration or native delivery is claimed; r1 is historical.
- **Superseded I01 finite-strain admission — historical measurements:** [five refreshed controls](../tectonics/evidence/i01-finite-admission-r2.json)
  pass in 1.9014433 s against the corrected finite-strain/heat chain. Admission
  tolerances, issued-state requirements and numerical law are unchanged.
  This remains a conditional represented-column bound, not rupture, restart
  or world acceptance; [method](../tectonics/docs/I01_FINITE_ADMISSION.md).
- **Superseded I01 compatible magma receiver — historical measurements:** [finite-receipt control](../tectonics/evidence/i01-magma-receiver-r2.json)
  binds the tool/test/case/method and corrected partition dependency. Thirteen
  tests and the 0.1879935 s campaign pass, including independent crystallisation,
  entropy and pressure-volume work accounts. Eight co-arriving parcels take
  0.0129064 s per 20 batched calls versus 0.0479586 s sequentially: 73.09% saved,
  temperature parity 2.28e-13 K. Same-pressure analytical ideal mixture only;
  no native emplacement, flow-rate law or persisted delivery transaction.
- **Superseded I01 composition-aware phase energy — historical measurements:** [analytical extraction/cooling control](../tectonics/evidence/i01-phase-energy-r3.json)
  binds the ideal-mixture caloric law, tests, case, method and corrected
  partition helper. Twelve focused tests pass, including thermodynamic identities
  and pure/congruent melting plateaux. A three-batch comparison saves 83.04% against
  same-accuracy bisection for 40 inversions. This is not calibrated mantle physics,
  native W08 delivery or a whole-world speedup; r1/r2 remain historical after
  the solver safeguard and partition arithmetic changed respectively.
- **Superseded I01 composition-aware phase partition — historical measurements:** [analytical controls](../tectonics/evidence/i01-phase-partition-r2.json)
  bind four files; eleven focused test methods pass and the campaign takes
  0.0579674 s. Component depletion survives re-equilibration without recreating
  extracted liquid. Per-component minority inventories avoid cancellation at
  phase disappearance and with extreme partition coefficients. Three interleaved
  200-call batches take median 0.0020329 s with safeguarded Newton versus
  0.0164274 s bisection: 0.0143945 s / 87.62% saved,
  mass parity 2.37e-9 kg. This is supplied-coefficient fixed-P/T composition
  feasibility, not energy-bearing delivery or a world-runtime claim; see
  [method and the still-required common thermal law](../tectonics/docs/I01_PHASE_PARTITION.md).
- **Superseded I01 material-following finite strain — historical measurements:** [seven refreshed controls](../tectonics/evidence/i01-finite-strain-r3.json)
  pass in 14.2133972 s against the corrected thermal preparation and then-current
  upstream receipts. The actual force/heat/history/geometry chain remains
  compatible with legitimate thermal-operator rebuilding. Mass, whole-strip
  heat capacity, accounts and numerical gates are unchanged. This is a closed
  affine strip, not lateral rupture or a complete world workflow;
  [method and sources](../tectonics/docs/I01_FINITE_STRAIN.md).
- **Superseded I01 actual-column admission — historical measurements:** [connected controls](../tectonics/evidence/i01-column-admission-r1.json)
  bind twelve source/specification and reviewed-receipt files. Ten tests pass in
  0.011 s; eight control checks in 0.1361079 s. An exact upper bound connects
  mixed-creep column resistance to motion admission without changing its laws.
  Reusing the bound saves 0.0175392 s / 93.68% per ten guarded calls in three
  interleaved batches, with identical outputs. Fixed-column sufficient admission
  only; not physical rupture, continuum enclosure or world speedup. The inherited
  layered control remains uncertified at 1%; see [method](../tectonics/docs/I01_COLUMN_ADMISSION.md).
- **Superseded I01 force-driven thermal/motion connection — historical measurements:** [six refreshed controls](../tectonics/evidence/i01-thermomechanical-motion-r2.json)
  pass in 3.6745271 s with the corrected heat preparation. Force, temperature
  and weakening still share integration stages; external drag is not column heat.
  Verified upstream receipt references changed, not equations, forcing or gates.
  Fixed-geometry small-strain feasibility, not world acceptance;
  [method and sources](../tectonics/docs/I01_THERMOMECHANICAL_MOTION.md).
- **Superseded I01 layered column heat — historical measurements:** [seven refreshed controls](../tectonics/evidence/i01-column-heat-r3.json)
  pass in 1.4539432 s; twenty-two focused tests pass. Actual mechanical and
  thermal reference densities must agree for lithostatic columns; an asserted
  fingerprint cannot hide a 1% mismatch. A preparation digest also detects
  replaced capacities, conductances and reference arrays. Supplied-pressure
  analytical fixtures and legitimate rebuilt thermal properties remain supported.
  No physical inputs, equations or tolerances changed. Supplied-rate,
  fixed-geometry small-strain feasibility only; [method](../tectonics/docs/I01_COLUMN_HEAT.md).
  Previous receipts remain unchanged, superseded snapshots.
- **Superseded I01 resistance-to-motion connection — historical measurements:** [force/drag/history controls](../tectonics/evidence/i01-motion-coupling-r1.json)
  bind eight new and retained files. Eight focused tests pass (0.157 s); the
  bounded campaign passes in 1.209959 s. Finest velocity changes are 8.20e-9
  relative in time and 1.36e-4 in depth. One matched cold/warm comparison takes
  0.4459559/0.0926285 s: 0.3533274 s / 79.23% saved with 7.99e-13 relative parity.
  Motion is solved from force and actual evolving resistance, with a disjoint
  drag account. This is a fixed-temperature regional feasibility control, not
  assembled world mechanics or a rupture certificate; see [method](../tectonics/docs/I01_MOTION_COUPLING.md).
- **Superseded I01 evolving column weakening — historical measurements:** [reviewed controls](../tectonics/evidence/i01-weakening-r2.json)
  bind seven tool/case/method/test and retained-helper evidence files. Seventeen
  tests pass in 0.137 s and all seven controls in 0.948857 s. Prepared-coefficient
  reuse takes 0.0347743 versus 0.2257254 s: 0.1909511 s / 84.59% saved in one
  bitwise-matched comparison. Review fixed immutable-storage, provider identity
  and direct-entry/window guards without changing physics or case tolerances.
  Original [r1](../tectonics/evidence/i01-weakening-r1.json) is historical.
  See [the method and physical limits](../tectonics/docs/I01_WEAKENING.md).
- **Current I01 columns-to-driving connection:** [spherical controls](../tectonics/evidence/i01-gpe-r1.json)
  bind the new four-file implementation and unchanged retained torque helper.
  Ten tests pass in 0.007 s; campaign 0.0428281 s. Finest analytical rotation
  error is 0.0100396%, with second-order refinement. Five interleaved medians
  for 4,096 three-layer column moments: scalar 0.0075236 s, vectorised
  0.0001414 s, saving 0.0073822 s / 98.12%, relative parity 2.38e-16.
  This is a kernel comparison and a dry manufactured spherical connection,
  not whole-world validation. See [method and sources](../tectonics/docs/I01_GPE.md).
- **Current I01 water/flexure connection:** [coupled controls](../tectonics/evidence/i01-water-flexure-r1.json)
  bind four new source/case/test/method files. Ten tests pass in 0.062 s; the
  32²/64²/128² campaign passes in 0.113740 s. The finest-pair displacement change
  is 0.002723% of mean water depth. Verified wet-set reuse saves 0.0022661 s /
  31.11% per small solve in an interleaved benchmark. This is a periodic flat
  plate with finite connected water, not regional/global embedding. See the
  [equations, sources and limits](../tectonics/docs/I01_WATER_FLEXURE.md).
- **Current I01 dry melt production:** [parcel controls](../tectonics/evidence/i01-melting-r1.json)
  bind the four new tool/case/test/method files. Nine focused tests and the
  two-path/exact-reference campaign pass; the campaign takes 0.024851 s.
  Tighter-reference differences stay below 0.000962 K and 1.30e-6 mass fraction.
  Analytic versus numerical derivatives save 0.0006566 s / 41.47% in a five-run
  median microbenchmark. This is retained-melt production, not extraction or a
  compatible join to common-Tm delivery. See [method and sources](../tectonics/docs/I01_MELTING.md).
- **Current I01 evolving thermal/history connection:** [reviewed controls](../tectonics/evidence/i01-thermal-r2.json)
  bind nine thermal and retained-helper source/case/method/test files. All five
  controls pass in 6.396674 s; 13 focused tests pass in 0.274 s. Review closed
  input-validation gaps without changing physical equations or tolerances.
  One warm/cold comparison saves 1.054211 s / 65.60%; not a world-runtime claim.
  The [method](../tectonics/docs/I01_THERMAL.md) separates bounded material-reference
  evolution from the translation-only check and unimplemented finite-strain transport.
  [Claude's r1](../tectonics/evidence/i01-thermal-r1.json) remains unchanged and historical.
- **Superseded I01 nonlinear column resistance — historical measurements:** [column controls](../tectonics/evidence/i01-column-r1.json)
  bind the new tool/case/tests/method. Common-stress composite creep, regularised
  friction and unit conventions have 11 passing focused tests. The prescribed
  layered snapshot and 64/128-point comparison pass in 0.0549932 s; force changes
  by 0.0366%. A ten-local-solve comparison saves 0.0003092 s / 86.95% against
  bisection, not against a world run. See [scope and references](../tectonics/docs/I01_COLUMN.md).
- **Historical I01 melt-delivery connection:** [phase-selective delivery](../tectonics/evidence/i01-delivery-r1.json)
  binds its tool/case/method/tests and the then-current native Python tree. Five
  analytical cases and the W08 separation/placement/cooling account pass in
  0.0243872 s; 12 focused tests pass in 0.006 s. Available liquid is separated with
  its own enthalpy, not bulk enthalpy. Extraction timing and amount still require
  a physical producer; see the [method and sources](../tectonics/docs/I01_DELIVERY.md).
- **Current nonlinear motion-admission control:** [I01 decoupling](../tectonics/evidence/i01-decoupling-r1.json)
  binds its new tool/case/method/tests. Exact rational threshold checks, analytical
  oracles and conditional finite-window refusals pass, independently of the
  thermal/history work. The 97.78% saving is a 100-decision micro-comparison against
  exact bisection, not a world-generation estimate. See [scope](../tectonics/docs/I01_DECOUPLING.md).
- **Current I01 transitions:** [reviewed D6 controls](../tectonics/evidence/i01-transitions-r2.json)
  bind the corrected tool, case, method and focused tests. Six controls pass;
  32 focused tests cover the added root/account/frame refusal cases. This is
  authored reduced-model evidence, not generated breakup or subduction initiation.
  The linear-only handoff certificate, full-extraction melt-inventory estimate
  and transmitted-force work limits are in the [method](../tectonics/docs/I01_TRANSITIONS.md).
  [Claude's original r1](../tectonics/evidence/i01-transitions-r1.json) remains
  byte-identical and historical after review found uncovered gaps.
- **Current I01 pressure/temperature connection:** [mechanical snapshots](../tectonics/evidence/i01-strength-r1.json)
  bind the new tool, case, method and focused tests plus the retained 2D helper.
  An exact pressure/temperature oracle, full force/work balance, 17/33/65-grid
  controls and warm/cold parity pass. This is supplied-temperature mechanics,
  not evolved heat/history, rock calibration or rupture; see the
  [method and limitations](../tectonics/docs/I01_STRENGTH.md).
- **Current I01 2D numerical probe:** [2D controls](../tectonics/evidence/i01-fault2d-r1.json)
  bind their separate tool, case and method document. Grid/time comparisons,
  oblique analytical laminates, right-angle covariance and work checks pass.
  This does not settle pressure-sensitive friction, arbitrary-angle fault
  nucleation, material transport, physical calibration or rupture. The first
  [default-thread run](../tectonics/evidence/i01-fault2d-threaded-r1.json) is
  historical against its pre-thread-policy tool, retained for the timing comparison.
- **Current I01 design controls:** [four bounded controls](../tectonics/evidence/i01-controls-r1.json)
  bind their tool, declared case policy and physical-contract document. The four
  controls pass, but do not establish 2D fault generation, physical rupture,
  global evolution or regional water/flexure coupling. Runtime versions are
  observations, not sealed library binaries. No native package is imported.
- **Current:** the Step 7 r2 predeclared matrix and the
  [B1 matched boundary diagnostics](../tectonics/evidence/boundary-kinematics-r1.json).
  B1 checks its tool and two portable input bindings, not a native simulation or
  transitive runtime seal; its source/runtime limitations remain explicit.
  The [Windows installation receipt](../tectonics/evidence/environment-install.json)
  also remains current against its package-version JSON record. Its local smoke
  script, wheel archives and runtime are not repository bindings. It records one
  successful installation, not continuing PyPI availability, current Atlas behaviour
  or a fresh byte audit of installed libraries. Requirement-file consistency is
  checked separately by the environment checker.
- **Historical:** S2, S3, S4 and S5 r1; Step 7 r2; bundle r1 and r2;
  motion-frame r2; the [separation-performance comparison](../tectonics/evidence/i01-separation-performance-r1.json);
  and the line-ending correction trails [r1](../tectonics/evidence/line-ending-digest-correction-r1.json)
  and [r2](../tectonics/evidence/line-ending-digest-correction-r2.json).
- **Superseded:** S7 r1, by S7 r2; the fifteen immediate predecessors of the
  29 September I01 captures; and the eight connected receipts replaced by the
  [30 September successors](#successor-capture-after-i022a-and-the-writer-correction).
  Their original results must not be quoted as current-checkout measurements.
- **Invalid:** none.

Evidence files that are not listed, including the W01-W12 receipts, are
unclassified. The register makes no claim about them.

Integration review found that A3 changed the native `reuse.py` source after Step 7
r2 and bundle r2 ran. Their adapter hashes still match, but this cannot make
their native integration results current. Motion-frame r2 binds its correction
and assessment files, but its embedded project/session integration and generation
observations use changed or unbound dependencies. The whole receipt is therefore
historical; this does not undo the implemented motion correction. None of the
original receipts, source hashes, measurements or runtime identities was rewritten.

Known dependency drift requires historical classification even when all declared
file bindings still match. An unchecked dependency is not evidence of compatibility.
Classification alone does not rerun a physical campaign. The bounded successor
captures below provide new evidence for the changed package/writer sources.

Receipts may contain identities that cannot be checked locally; the register must
name each one if such a receipt is classified current. Each current record's
`limits` are printed on every run. For
example, `native_execution_id` is an atlas_tectonics loaded-code and runtime
identity, not a file hash. The checker never compares it with a file. An opaque
identity observation alone cannot detect changes to package sources or the
scientific runtime. Separate file bindings can check source bytes, as the current
I02 timing receipt does; they still do not verify the installed runtime.
Generated worlds, job files and output identities live outside the repository
and are listed as artefacts.

## Line-ending digest correction r2

Six I01 writers (`check_i01_phase_partition.py`, `check_i01_phase_energy.py`,
`check_i01_phase_pressure.py`, `check_i01_magma_receiver.py`,
`check_i01_separation_feasibility.py` and `check_i01_gibbs_provider.py`) opened
their receipts in text mode with the platform newline. Windows runs therefore wrote
CRLF, and 13 receipts were registered by the digest of those CRLF bytes: 13 register
values and 6 closure-matrix values. Git stores the LF bytes, so no checkout matched.
The writers now write LF, and `test_digest_line_endings.py` refuses an I01 writer
that does not. The [r2 correction trail](../tectonics/evidence/line-ending-digest-correction-r2.json)
records each old and new value with its proof. Only those 64-character values
changed: receipt bytes, measurements and recorded source bindings are unchanged, and
nothing was rerun. Because the writer change alters tool bytes those receipts bind,
the current ones among them became historical rather than being repinned.

## Successor capture after I02.2a and the writer correction

All fifteen original successor captures completed successfully on 29 September
2026 and were then registered as current. Nine covered the connected column
chain after the reviewed package extraction. On 30 September the I02
cold-restart stress-resolution correction required eight further successors;
`i01-column-r2` remained valid and was reused. The current chain is below.
Each affected tool was retargeted before its run, so downstream captures bind
the new upstream receipts and the package owners they execute. Every output was
written as a new file; no old receipt or recorded measurement was rewritten.

| Order | Control in `tectonics/tools/` | Captured current receipt | Receipts it checks |
| --- | --- | --- | --- |
| 1 | `check_i01_column.py` | [i01-column-r2](../tectonics/evidence/i01-column-r2.json), reused from 29 September | none |
| 2 | `check_i01_weakening.py` | [i01-weakening-r4](../tectonics/evidence/i01-weakening-r4.json) | column r2 |
| 3 | `check_i01_column_heat.py` | [i01-column-heat-r5](../tectonics/evidence/i01-column-heat-r5.json) | weakening r4, column r2 |
| 4 | `check_i01_motion_coupling.py` | [i01-motion-coupling-r3](../tectonics/evidence/i01-motion-coupling-r3.json) | weakening r4 |
| 5 | `check_i01_column_admission.py` | [i01-column-admission-r3](../tectonics/evidence/i01-column-admission-r3.json) | motion coupling r3, decoupling r1 |
| 6 | `check_i01_thermomechanical_motion.py` | [i01-thermomechanical-motion-r4](../tectonics/evidence/i01-thermomechanical-motion-r4.json) | column heat r5, motion coupling r3 |
| 7 | `check_i01_finite_strain.py` | [i01-finite-strain-r5](../tectonics/evidence/i01-finite-strain-r5.json) | thermomechanical r4, column heat r5, motion coupling r3 |
| 8 | `check_i01_finite_admission.py` | [i01-finite-admission-r5](../tectonics/evidence/i01-finite-admission-r5.json) | finite strain r5, column admission r3 |
| 9 | `check_i01_breakup_closure.py` | [i01-breakup-closure-r4](../tectonics/evidence/i01-breakup-closure-r4.json) | finite strain r5 |

The five phase/receiver/separation successors and the G25 successor passed on
29 September and remain current without a new capture:

| Control in `tectonics/tools/` | Captured current receipt | Capture boundary |
| --- | --- | --- |
| `check_i01_phase_partition.py` | [i01-phase-partition-r3](../tectonics/evidence/i01-phase-partition-r3.json) | Corrected LF writer; bounded phase controls |
| `check_i01_phase_energy.py` | [i01-phase-energy-r4](../tectonics/evidence/i01-phase-energy-r4.json) | Corrected LF writers; bounded energy controls |
| `check_i01_magma_receiver.py` | [i01-magma-receiver-r3](../tectonics/evidence/i01-magma-receiver-r3.json) | Corrected LF writers; bounded receiver controls |
| `check_i01_phase_pressure.py` | [i01-phase-pressure-r3](../tectonics/evidence/i01-phase-pressure-r3.json) | Corrected LF writers; bounded pressure/energy controls |
| `check_i01_separation_feasibility.py` | [i01-separation-feasibility-r4](../tectonics/evidence/i01-separation-feasibility-r4.json) | Corrected LF writer; bounded spatial separation controls |
| `check_i01_gibbs_provider.py` | [i01-gibbs-provider-r3](../tectonics/evidence/i01-gibbs-provider-r3.json) | Corrected LF writer; pinned isolated Julia/MAGEMin environment |

The 29 September verification recorded 633 I01/I02 tests passing in 12.390 s
and three digest-line-ending tests in 0.777 s. Its Git-normalised candidate
check passed all three guards in 17.7 s, including the exported-byte test suite
in 12.704 s. Those are historical measurements of that day's source snapshot.

On 30 September all eight refreshed captures passed in 24.72 seconds in total
after imports. The final Git-normalised I02 closeout passed all three checks in
154.1 s, including 758 I01/I02 tests in 149.794 s. The evidence register matched
445 digests across 37 current records, with 28 historical, 31 superseded and no
invalid records; the closure-matrix receipt digests and statuses matched the
register. These are the recorded closeout results, not a full-suite or
independent physical-validation claim. No physical law, acceptance threshold,
case or retained 256-step ceiling changed, and no old receipt was repinned.

The separation-performance comparison used a harness outside the repository and
has no successor route. Its older timings remain historical. Capture and
registration are local evidence states; Git commit and publication are separate.

## Integration checks

Claude supplied the checker and 19 focused tests. Review corrected the three
whole-record classifications above and tightened strict JSON parsing: exponent
overflow such as `1e999` is now refused instead of silently becoming infinity.
The focused suite recorded 18 passes and one Windows file-symlink-privilege skip
in 0.526 s; the directory-junction refusal passed. That initial checker reported one current
declaration, nine historical records and one superseded record. No simulation ran.
The added fixed-record classification assertion passed separately in 0.033 s.
Public-path scanning and required static source checks also passed; the latter
recorded 30 passes and its existing Windows privilege skip in 0.122 s.

## When it fails

- **A bound source changed.** Produce a successor receipt from the changed code
  and register it, or reclassify the old record as historical and update the
  documents that cite it. Never edit a recorded digest.
- **A registered file changed.** Review the change. An authorised correction needs
  an explicit trail, like the line-ending correction, before its `sha256` is
  updated in the register.
- **Only CRLF line endings differ.** This is still a failure; the message says so.
  `tectonics/.gitattributes` stores these files with LF. Restore the repository
  bytes of the named file after review, as recorded in the correction trail.
- **An unclassified digest field.** Add a checked binding or a `not_checked` entry
  with its reason. Do not drop the field.

## Writing rules

`pointer` is a JSON Pointer into the receipt. A whole segment `*` matches any key
or list index. `{key}` does the same and passes the matched key into the `file`
template; a rule may have at most one. For example, `/source_sha256/{key}` with
file `{key}` checks every path-to-digest entry. Paths use `/` and must stay inside
the repository. Traversal, drive letters, backslashes, streams, device names,
symlinks and reparse points (including junctions) are refused. A binding can
never target an `_id` field. A rule that matches nothing, or a field claimed by
two rules, is a failure.
