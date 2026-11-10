# W08 finite-source magmatism and joined histories

Status: local implementation, 23 September 2026.
The original [W08 design](W08_REGIMES.md) and [case register](../cases/w08_regimes.json)
remain unchanged. The new [joined fixture](../cases/w08_joined_r1.json) was frozen
before candidate execution, SHA256
`01269a9de5e3c94f7adf04f8aed5e970364af5f8af49889bd733e9f97d4395d4`.

The Step-1 document is preserved as a frozen executable case input. Its pending
implementation/source-adapter language describes that historical design capture.
Steps 2–5 document their implemented routes, including the
[resolved Step-4 interpretation](W08_SUBDUCTION.md#source-resolution-and-step-4-closure);
the joined-history section owns the joined scope and its remaining limits. The
[finite-source magmatism section](#w08-step-5-finite-source-magmatism) records
the separate Step 5 component.

[Joined histories](#supported-joined-route) · [Checkpoint and recovery](#checkpoint-and-cache-contract) · [Finite-source magmatism](#w08-step-5-finite-source-magmatism)

## Supported joined route

`PreparedW08Workflow` serialises an explicit dated sequence of finite shortening,
full-vector affine transform/oblique motion, prescribed crust/mantle retirement,
finite magma transfer and cessation. It composes the existing finite affine maps,
retirement and reservoir algorithms; it does not replace their physical laws.
The inputs are `W08Inventory`, `W08Region` and immutable `RegimeInterval` records.

Each physical node owns its complete component masses and signed isobaric
enthalpy once. Crust, mantle, melt, solid source, reservoir, intrusion, extrusion,
accretion, deep storage and export remain distinct. Incoming retirement material
credits declared destinations simultaneously. Magmatic outlets compete in the
existing coupled transfer solve. Unselected stocks survive every regime change.
In particular, cessation changes the clock, not the reservoir contents.

Node origin/formation labels describe the supplied stores, not the age of a
newly mixed receiving rock. Tagged donor/component/enthalpy transfer receipts are
preserved for the entire bounded history; mixing never silently assigns the
receiver's initial age to incoming material. No new birth or phase conversion is
inferred merely from a regime label. A supplied thermal closure is forwarded to
the existing magmatic phase checks.

Transitions require a unique event ID, old/new regime, named boundary,
continuous represented geometry, polarity and coupling/kinematic/thermal source
bindings. Changed forcing starts a new segment and a new material operator;
changed coefficients cannot reuse an old numerical factor. Supplied dates split
the history. If a finite stock exhausts earlier, the supported exact endpoint is
computed and committed before `W08ExhaustionError` stops unspecified continuation.
The exception exposes its retained `.output`; loading it does not spend it again.
The existing refusal of singular mixed-recharge depletion remains unchanged.

This joined route uses prescribed affine footprints and homogeneous stock
withdrawal/placement. The previously accepted non-affine fault/network tools,
steady wedge diagnostics, explicit host-replacement and heat-paid melting tools
remain separate typed component operations. They are not silently converted into
arbitrary transient histories. Unsupported continental entry, geometry jumps,
empty pass-through and an unspecified simultaneous retirement/melting law refuse.

## Regional physical owners

`W08Region` conservatively allocates selected current stocks to disjoint planar
parcels using supplied unit-sum mass weights and receiving densities. It exposes
immutable component mass, mass, advected enthalpy, volume and thickness. Density
changes affect volume but do not manufacture mass or heat.

The reference and current footprints are retained. The load contribution is
`g*(current mass/current area - reference mass/reference area)`; shortening and
emplacement therefore enter once. Intrusive underplating and surface extrusion
have separate volume/thickness contributions. The terminal stock and its spatial
view are one material, not two inventories. Advected enthalpy is not an extra
latent-heat or radiogenic source. The view is a physical input to the W03/W04/W07
owners, not a second flexure, thermal PDE or free-surface solve. Host displacement
or replacement still requires its explicit finite-host Step 5 operation.

## Checkpoint and cache contract

Only a completed supplied interval or a validated exact-exhaustion endpoint may
be saved. The retirement and magma kernels publish the supplied interval end
itself (`end_time_s`, shared end-time rule), not `start+(end-start)`, which can
fall one ulp short: an interval from 0.020301896609317943 s to 0.3 s was refused
as a mid-event output before 30 September 2026. An exhaustion endpoint is still
derived as start plus the exhaustion duration. When that derived end rounds onto
the declared end (the exhaustion duration one ulp short of end minus start), the
interval completes exactly as it does when the durations are equal, and the
schedule continues; previously the workflow refused its own result. One `ArrayStore.put` transaction publishes current/reference geometry,
reference stocks, component/enthalpy stocks, formation/origin bindings, finite
deformation, completed event cursor, exhausted nodes, owners and transfer history.
The output identity and parent checkpoint/output identities are checked together.
The immutable chunk store reuses identical payloads; no new history-storage stack
or copied grid for every intermediate evaluation was added.

Restore verifies the contiguous metadata prefix and latest payload, recreates
the typed state, reconciles every node against its tagged transfers, checks
reference geometry/finite deformation, then continues at the next interval.
Completed material solves are not replayed. Corrupt or incomplete payloads,
partial events, missing prefix entries, changed owners or source/runtime bindings
refuse. Explicit foreign checkpoint IDs refuse rather than becoming a cache miss.
This is active-state recovery, not a full re-read of every historical payload.

Candidates are immutable and separately admitted before publication. They become
the active state only after commit. Both pre-commit rollback and interruption
after commit/before adoption are tested. All producer and store work shares the
128 MiB accounting envelope, one native numerical thread and 256 cumulative
accepted intervals, including internal variable-mass integration steps. The
tagged-history metadata is bounded to 512 KiB. Accounted work is not process RSS.
Only the latest live output is retained; caller-retained older outputs require
their own allowance. Source membership remains bounded to 128 files (115 now).
The later [A3 capacity repair](../../docs/CURRENT_EVIDENCE.md#historical-repair-qualification)
raised that bound to 512 files; the count above is this checkpoint's.

## Acceptance and timing

The frozen A07 control transfers exactly 6 kg at 4 kg/s up to 1.5 s, then retains
all stocks to 3 s. The five-regime control composes shortening and shear, retires
finite crust/mantle and feeds a mixed reservoir, intrusion and extrusion before
cessation. Its controls cover 8/16/32 parcels and 1/2/4 interval partitions.
The existing 1e-10 exact-map and 128-epsilon extensive gates were not loosened.

Eleven inventory, six regional-view and ten workflow test methods have passing
Windows evidence. Nine shared execution-identity checks also pass. Focused
coverage includes exact restart, no flux replay, exhaustion, source changes,
owners, atomic failure, corruption and missing history. Static safety remains
13 selected source maps and 41 required paths. No Linux execution or whole-world
campaign is claimed by this Windows run.

The [joined timing report](../evidence/w08-joined.json) separately measures cold
preparation/execution/materialisation, a prepared latest-result hit, first write,
verified restore and interrupted continuation, with three rotated repeats. It
also measures three identical requests with and without preparation reuse,
including setup, close and output materialisation on both sides. Faster paths
are not advertised as a whole-generator or new-physics speed-up.

Measured Windows medians (three rotated repeats, all final bytes identical):

| Matched three-request workload, setup included | Seconds |
| --- | ---: |
| Repeated cold preparation | 2.9310746 |
| Prepare once, reuse twice | 1.0546066 |
| Saving | **1.8764680 (64.0198%)** |

The single cold complete result costs 0.9988960 s. Separately timed operations:
prepared latest hit 0.0541844 s; first checkpoint pack/validate/write 0.0614539 s;
verified restore after preparation 0.0673941 s; prefix recovery/remaining two
intervals/checkpointing after preparation 0.4334950 s. These narrow timings
exclude the explicitly recorded setup and are not the setup-inclusive claim.
Including new preparation and close, restore costs 0.5363079 s (0.4625881 s,
46.3099% saved versus cold); continuation costs 0.8833820 s (0.1155140 s,
11.5642% saved). Previous checkpoint creation is a sunk cost, excluded from both
recovery comparisons. First-write timing is one final checkpoint in an empty
store; a complete restorable prefix is used in both recovery routes.

The entire timing/control run took 34.8141 s. Maximum shared admitted work was
36,341,666 bytes (34.6581 MiB), including store work and untimed seed preparation,
against the unchanged 128 MiB cap. This is not RSS. Evidence SHA256:
`c7d16d581cafe2deca3d7fb0ca5c33bc0c36d58cd5a38eaf19c1e0b577aa5721`.

The Step 2 shortening/foreland, Step 3 distributed-strain, Step 4 five-case
subduction and Step 5 basalt thermal/density references remain their existing
labelled evidence. This integration adds no new geological calibration and does
not repin old reports to the changed package identity. The expensive subduction
campaign was not repeated; its physics, mesh choices and gates were not changed.

Exact execution: the 11 inventory methods passed in the first 21-method run;
the four storage tests initially exposed a test harness error (directory passed
as SQLite filename), corrected before their successful 10.798 s run. The final
10 workflow methods passed in 18.037 s. The regional owner's six methods passed
in 0.033 s. After the final resource-lifetime adjustment, the two affected
restart/atomic methods plus nine identity methods passed in 7.784 s. The static
suite passed 31 methods with one environmental skip in 0.125 s. Passing
unaffected checks were reused; no whole-project suite was rerun.

Reproduction, from the repo with the approved scientific Python environment:

```text
PYTHONPATH=tectonics/src;tectonics/tests
python -B -m unittest test_w08_inventory test_w08_region test_w08_workflow
python -B -m unittest test_execution_reuse.IdentityTests
python -B tools/check_coding_safety.py
python -B tectonics/tools/check_w08_joined.py --repo . --report NEW_REPORT.json
```

On Linux the two `PYTHONPATH` entries use `:` rather than `;`.

## Research and existing software checked

- [PETSc TSSetEventHandler](https://petsc.org/release/manualpages/TS/TSSetEventHandler/):
  documentation read. Event location and the state/equation change are separate;
  the workflow commits their complete event boundary, not a half-applied update.
- [PETSc TSRestartStep](https://petsc.org/release/manualpages/TS/TSRestartStep/):
  documentation read. Discontinuous state or coefficients invalidate continuation
  history. New regime segments prepare fresh material operators.
- [Keller and Suckale (2019)](https://academic.oup.com/gji/article/219/1/185/5523132):
  conservation/transfer excerpts rechecked, not the entire paper. Distinguishing
  internal transfers from external sources and conserving each component informed
  the joint accounts. Atlas does not claim to implement that paper's multiphase
  continuum dynamics.
- Existing Atlas W07 parent-linked recovery, W08 finite-motion/material kernels
  and transactional `ArrayStore` were inspected and reused. No external solver
  was installed or executed for this increment.

## W08 step 5: finite-source magmatism

23 September 2026. Step5 is COMPLETE for the prescribed
finite-transfer C06 route. The frozen design and original A04-A06 gates remain
unchanged. Step6 owns joined regime histories, checkpoint/restart and combined
acceptance; this increment does not replay R4.4.

### Implemented route and ownership

- `magmatic_thermodynamics.py`: exact supplied common-Tm enthalpy inversion,
  unequal component heat capacities, phase-change plateau, signed external heat,
  and heat-paid finite solid-to-liquid conversion. Already-liquid extraction
  does not pay latent heat again. Empty stocks have no invented temperature or
  melt fraction. Properties and the enthalpy reference are identity-bound.
- `magmatic_transfer.py`: finite source-melt, well-mixed reservoirs, intrusive,
  extrusive and export stocks. Mass rates are supplied kg/s, donor rows and
  receiver columns. Components and isobaric enthalpy evolve together; exports
  sample the evolving reservoir, not its initial mixture. Solid melting is a
  separate paid conversion. Sorted IDs make simultaneous outlets order-neutral.
- `magmatic_emplacement.py`: mass-weighted placement at receiving density,
  surface extrusion or basal underplating, and finite host displacement or
  replacement. Host volume, components and signed enthalpy go to an explicit
  destination. Incoming/outgoing thermal conventions must match. Net structural
  load is incoming minus outgoing host mass per area, not gross injected mass.

`result.payload(edge_index, source_density)` only exposes terminal intrusive or
extrusive transfers. Placement entries give one owner for their volume, net
load and advected enthalpy; advected heat is not also a new heat source. An entry
does not itself run the W03/W04/W07 structural or thermal solvers. The Step6
history owner must book it once and reject incompatible alternative branches.
`accounting_entries` already refuses repeated transfer IDs and reuse of the
same host-stock snapshot in a supplied batch. It is not a persistent transaction
ledger: different-duration evaluations are alternatives from the same start,
not additive increments. Consecutive evolution uses the returned remaining
inventory and an explicitly supplied next segment.

#### Declared source kinds and the supplied phase rule

R7, 1 October 2026 (review s14 missed #1). When a transfer is given a
`MagmaticThermodynamics` law, it checks every declared source against that law,
at preparation and again in each published remainder. A `source-melt` node must
be fully liquid and a `source-solid` node fully solid. Anything else is refused,
including a source that external heat or mixing carries across the transition
during the segment. Reservoir, intrusion, extrusion and export nodes carry no
phase requirement, and an empty node has no phase to check.

A node that holds latent heat is judged by the liquid fraction from the enthalpy
inversion. A node that holds none has a temperature but no liquid fraction
(`single_phase`): that is every node of a zero-latent law, and any node made only
of zero-latent components. Its declared kind is judged by temperature against
the common melting temperature instead. `source-melt` must be above it and
`source-solid` below it. A node exactly at it is refused as ambiguous, because
solid and liquid have the same enthalpy there. The comparison is exact, with no
tolerance, and uses the temperature the enthalpy inversion publishes for that
node (reference temperature plus enthalpy over heat capacity), so a source within
round-off of the melting temperature is judged by that published value.
This applies the frozen design's single-melting-temperature rule
(solid below the solidus enthalpy, liquid above the liquidus enthalpy) to a
plateau of zero width. The R7 brief decided it; no new source was consulted.
Zero-latent laws stay usable for transfers.

Before this repair the check passed every node without a liquid fraction. With
zero latent heat and a 1473.15 K melting temperature, a `source-melt` at 300.5 K
and a `source-solid` at 3000 K were both accepted. Energy accounts were not
affected; only the phase admission was open. A transfer that declares such a
source on the wrong side of the melting temperature, or exactly at it, is now
refused. The retained fixture of `test_thermodynamic_reference_binding` had a
`source-melt` at 300.5 K under a 350 K melting temperature; it now uses a melting
temperature below its stocks and still checks the enthalpy-reference binding.
Added tests hold both kinds on each side of and exactly at the melting
temperature, a node of zero-latent components under a mixed law, the two reviewed
cases, a melt source cooled across the melting temperature during a segment, and
the same rule through the shared-inventory adapter `advance_magmatic`. The joined
workflow forwards its thermal law to that adapter, so it inherits the rule.

Two other rules read the phase of a node, and their behaviour is unchanged. With
latent heat all three take it from the same enthalpy inversion. Without latent
heat the other two still treat a nonempty node as having no established phase and
refuse it at every temperature. The paid conversion `melt_source_fraction`
requires a source the inversion calls solid and a product it calls liquid; with
no latent cost to pay, the inversion calls such a node neither (`single_phase`).
The I01 delivery separation (`extract_liquid` in
[`check_i01_delivery.py`](../tools/check_i01_delivery.py), method in
[I01_DELIVERY.md](I01_DELIVERY.md)) refuses it on the ground that a zero-latent
law does not establish liquid availability. Under a zero-latent law a melt
source can therefore be declared and transferred, but it can be neither produced
by that conversion nor separated as liquid for delivery. The temperature test
serves the declared-kind check of a transfer only, so the three rules read the
same zero-latent node differently. R7 did not reconcile them.

### Numerical design and efficiency

Homogeneous finite feeds and constant-mass mixed reservoirs use an augmented
matrix exponential, including cumulative edge transfers. Held feed states stay
extensive and coefficients use q/M0: the operator is not made badly scaled merely
by changing the mass unit or source size. Positive and negative heat have separate
nonnegative source maps, combined with signed energies only at materialisation.
No negative component mass is clipped into a pass.

Changing-mass mixtures use DOP853 with every accepted transfer map checked for
nonnegative material-origin coefficients, finite values and final compensated
extensive closure. DOP853 is not an unconditionally positivity-preserving method;
the supported route is admission-gated and refuses a negative map. It retains
only active integration state, not a growing history. A mixed-reservoir endpoint
with simultaneous recharge and exact depletion is singular in this formulation
and is refused unless a separately resolved endpoint law is supplied. Exact
homogeneous finite-source exhaustion, including competing outlets, is supported;
continuation beyond it is refused, never silently clamped or extrapolated.

Per segment: at most64 nodes,64 components,256 simultaneous edges,256 accepted
integration intervals and4096 derivative evaluations; one native thread and
128MiB admitted work. These are explicit prototype admission limits, not an RSS
measurement or planetary performance claim. Thermal/placement detached snapshots
are caller-owned, as in the existing column kernels; retained transfer arrays
remain leased for their lifetime. Plans are thread-bound, non-reentrant and
source-verified. They keep one latest result and one latest exact operator.
All three new modules participate in the existing execution source identity.

R7, 1 October 2026 (review s14 missed #2). Each retained inventory or result
array is now copied to bytes of its own before its lease is attached, as
`w08_inventory` already did. An inventory built from another inventory's public
arrays used to borrow those bytes. Its reservation then stayed charged until the
source inventory was released, even after the copy itself had been discarded: in
the reviewed 64-node, 64-component case each discarded copy left 33,792 bytes
reserved against the shared default budget. The cost of the repair is one extra
transient copy of each small retained array: at most 32 KiB for an inventory's
component table and 128 KiB for a result's edge-component table, inside the work
already admitted for the operation. Values and identities are unchanged. An
added test rebuilds and discards an inventory from another's public arrays and
requires the owner's reserved bytes to return to their earlier value.

### Acceptance and measured evidence

The [r1 fixture](../cases/w08_magmatism_r1.json) was frozen before the joined
candidate run; SHA256
`b0eade66ba4c196f9775dc83039bb210a8182e42913673652771389d550c2cb4`.

52 new focused methods have passing evidence:20 thermodynamics,21 emplacement,
11 transfer/integration. The final changed transfer code and9 shared identity
methods passed together in5.093s. The unchanged thermal/emplacement methods had
already passed in the first joined run. Static checks passed13 maps/41 paths;
31 coding-safety methods completed in0.114s with one environmental skip.

The first joined run exposed a signed-heat matrix issue; retaining nonnegative
source maps fixed it. A stronger physical-scale benchmark then exposed poorly
scaled held-feed coefficients; q/M0 fixed that without changing the governing
equations or acceptance thresholds. A test requiring bit-exact recipient masses
was corrected to the frozen floating-point gate (observed discrepancy below
2e-15kg); the exhausted source still has exactly zero mass and enthalpy.

Controls cover A04 finite throughflow and competing source exhaustion; A05 exact
continuous mixing/cumulative exports, unequal-cp325K mixing and2200J complete
crystallisation; A06 receiving volume and finite host accounting;1/2/4 event
partitions and8/16/32 spatial cells. A separate variable-mass analytic solution
checks the adaptive route to the unchanged1e-10 normalised gate. Extensive gates
remain128 binary64 eps times account magnitude, with compensated sums.

Independent physical control uses Calogero et al.'s basalt cp1480J/(kg K),
latent heat400000J/kg, melt density2830kg/m3 and solid density3100kg/m3.
Cooling a declared1m3 parcel from1423.15K to473.15K releases5.11098GJ and yields
0.9129032258064516m3 solid, preserving2830kg. Finite host replacement uses the
paper's granitoid density2650kg/m3. Endpoint/area/volume normalisation and common
Tm1200K are explicit scenario choices, not paper parameters. Complete cooling
energy is independent of the chosen Tm between these endpoints. This checks
calorimetry and density conversion, not the paper's full transient sill model.

Three rotated repeats on native Windows, with identical materialised output
identities, include input setup, context creation, source verification, transfer,
phase inversion and32-cell emplacement:

| Three requested outputs | Fresh preparation | Prepared reuse | Saved |
| --- | ---: | ---: | ---: |
| Different durations1/2/3s |0.8076002s|0.3577272s|0.4498730s /55.7049%|
| Identical duration3/3/3s |0.8101634s|0.3253394s|0.4848240s /59.8427%|

These are medians, not a first-ever-process import or whole-generator speedup.
Both routes share immutable scenario inputs; the baseline rebuilds the plan and
execution context for each output. The largest measured operation reservation
was231808bytes, excluding separately owned inputs/context/interpreter baseline.
The [raw timing report](../evidence/w08-magmatism-timing.json) retains every trial,
full source digests, fixture identity and output identities.

Commands run from the repository root with `PYTHONPATH=tectonics/src;tectonics/tests`
(native Windows science environment; no Linux run claimed):

```text
python -B -m unittest test_w08_magmatic_transfer test_w08_magmatic_thermodynamics test_w08_magmatic_emplacement -v
python -B -m unittest test_w08_magmatic_transfer -q
python -B tectonics/tools/check_w08_magmatism.py --report <local-report.json>
python -B -m unittest test_w08_magmatic_transfer test_execution_reuse.IdentityTests -q
python -B tools/check_coding_safety.py
python -B -m unittest discover -s tests -p test_coding_safety.py -q
```

### Papers and software checked

- [Spera and Bohrson (2002), EC-RAFC](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2002GC000315)
  and [author software page](https://magma.geol.ucsb.edu/papers/ECAFC.html):
  coupled finite energy/mass/species accounts and recharge. Guidance, not a
  reproduced EC-RAFC crystallisation/assimilation model; spreadsheet not executed.
- [Keller and Suckale (2019)](https://doi.org/10.1093/gji/ggz287), equation39c
  and AppendixB6: separate transport and latent reaction energy.
- [ASPECT latent-heat source](https://raw.githubusercontent.com/geodynamics/aspect/main/source/heating_model/latent_heat_melt.cc):
  reaction heating is not advected enthalpy a second time. Source inspected;
  ASPECT was not installed or run.
- [Calogero, Hetland and Lange (2020)](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2018JB016773),
  Table1 and section3: independently sourced calorimetric/density inputs above.
- [Rhodes et al. (2024)](https://doi.org/10.1038/s41598-023-50880-0): host
  accommodation requires explicit mechanics; no universal accommodation ratio
  was imported from this paper.
- [SciPy expm](https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.expm.html)
  (Al-Mohy and Higham's scaling/squaring method) and
  [DOP853](https://docs.scipy.org/doc/scipy/reference/generated/scipy.integrate.DOP853.html):
  official algorithm/API documentation. The implementation ran withSciPy1.17.1;
  documentation access does not imply installation of its latest version.
