# Evolving mechanics and supported tectonic histories

23 September 2026. Local implementation on `remake`.
This is the next tectonics increment after [underthrusting](UNDERTHRUST.md),
not W09 surface-process expansion. Existing modules stay in place. The later
[dated-history section](#tectonics-continuation-step-4-supported-dated-histories)
records supported continuation and recovery for these inputs and underthrusting.

[Evolving support](#changing-elastic-properties-and-physical-loads) · [Regional inputs](#coincident-regional-force-material-and-boundary-inputs) · [Dated histories](#tectonics-continuation-step-4-supported-dated-histories)

## Changing elastic properties and physical loads

`evolving_flexure.py` connects actual W03 states to the existing W04 physical
load construction and conservative variable-rigidity Hermite solver. It does not
duplicate the inventory, pore-water placement, thermal load or external-pressure
calculations. The old fixed-property W04 API retains the same calculations after
extracting its shared input validation and load-change construction.

`W04RigidityState` binds each supplied E/Te/nu profile to an actual W03 state/time,
frame, datum and epoch. `W04AbsoluteReferenceLoad` supplies total reference
pressure on the actual reference cells, with source and exact reference
surface/policy/exterior binding. This datum is required: the old anomaly-only
inputs cannot identify an unloaded or stress-free plate when its stiffness changes.
It already includes the reference contributions; it is not another load to add.

`PreparedEvolvingW04Support` retains that fixed reference. At each supplied state,
W04 constructs the physical load change, then the new adapter evaluates

    q_current = q_reference_absolute + W04_physical_load_change
    delta_w = A(D_current)^-1 q_current - A(D_reference)^-1 q_reference_absolute.

Thus unchanged load can produce changed deflection when rigidity changes.
`A(D_current)^-1 delta_q` would miss that response. If the profile/operator is
unchanged, the existing compensated load-difference solve is retained, avoiding
subtraction of nearly identical large solutions. An exact unchanged reference
request avoids a redundant zero-load solve.

The conservative operator remains `(D w'')'' + K w = q`, not local D multiplied
by a uniform biharmonic stencil. Geometry, foundation K, boundary conditions and
accuracy policy remain fixed per preparation. Continuing-plate cases bind both
absolute exterior loads and exterior elastic properties; uncertain omitted loads
remain unsupported for variable rigidity. The complete absolute reference and
current solutions must pass the existing linear/small-slope/strain validity checks.
Changed-profile difference checks use a conservative sum of polynomial maxima
and mesh-change estimates, so large cancelling states cannot hide invalid physics.

Outputs retain the existing once-owned W04 load/sediment/water accounts plus both
absolute pressures and displacements. They are totals from the fixed reference,
not increments to add repeatedly. W03's local support diagnostic stays excluded.
The receiving module owns applying any output to its geometry or material state.

Only the reference operator and one replaceable current operator are retained;
old changing-profile factors are released before their replacement. Matching
profiles reuse factors. All work shares the existing 128 MiB accounting and native
thread controls. Returned outputs have caller-owned storage; no field history grows
inside the plan. Existing source-bound variable-flexure caching remains available.

## Coincident regional force, material and boundary inputs

`evolving_mechanics.py` adds an explicit exchange boundary to the existing W07
regional Stokes solver. `RegionalInputContext` binds dimensions, grid, world
origin, frame, vertical datum, epoch and exact physical instant. Immutable
`RegionalInputBlock` kinds cover:

- material viscosity at the separate normal-stress centres and shear vertices;
- complete physical body-force components on the staggered faces;
- all four boundary components, explicitly velocity or traction;
- optional downward surface pressure on the top-normal sampling support.

Every block names its producer state, source and sampling law. SI units and array
supports are checked before capture. `RegionalMechanicalRequest` rejects mixtures
of different instants, epochs, supports or frames. Physical effect IDs cannot be
duplicated across force, load and boundary inputs; total gravity has at most one
owner. These are declared producer contracts, not an inference that two differently
named physical effects are genuinely independent.

Surface pressure occupies a declared zero top-normal traction slot and is mapped
to negative vertical traction. A prescribed top-normal velocity or an already
occupied load slot refuses instead of silently overriding or adding loads.
W04 or other extra displacement cannot be attached to W07's owned response.

`regional_thermal_gravity` reuses the existing Boussinesq law and named
cell-mean-to-stress-site temperature reconstruction. It supplies replacement total
gravity; including both old and new gravity blocks refuses. The Stokes solver
alone subtracts its reference-pressure gradient. This does not change material
inventory mass, infer material viscosity or evolve heat. The law and temperature
bytes, source and producer state are bound into the resulting force input.

`PreparedEvolvingRegionalMechanics.evaluate(request)` produces a quasi-static
mechanical snapshot. Changing force/boundary values reuse the existing operator;
changed viscosity refills the coefficients and factors while retaining geometry.
Identical coefficients retain factors even when provenance changes. A latest
identical request still verifies live source identity. Only one current operator
and latest response are retained. Geometry, boundary types and pressure convention
changes need a new plan, not a silently reused incompatible operator.

**An interrupted viscosity change no longer breaks the plan (R7 repair).** The
1 October candidate was later integrated within its documented scope; see [current
state](../../docs/CURRENT_STATE.md). A coefficient change can be cancelled, or fail, at three kinds
of moment: before the numeric refill starts, during it (including after the solver
core has taken the new coefficients but before the operator records them), and at
the operator's closing cancellation/source check, after the change was accepted.
The same exception type can come from all three, so the exception does not say
which material the operator holds. Before the repair the interface assumed it
still held the previous one and kept the operator whatever had happened:

- after a cancellation or failure during the refill it held an operator that
  [refuses every operation](W07_REGIONAL_SOLVER.md#w07-step-3--heterogeneous-and-thermal-mechanics), so every later request
  was refused, and a tectonic history on this route could not resume;
- after a cancellation at the closing check it held the new material under the
  previous material's label, so the next request carrying the previous material
  skipped the refill and was solved, and published without error, using the new
  viscosity.

The interface now treats its material label as unknown from the moment it asks
for a change until that change returns. If the change raises and left the
operator invalid (its `usable` property is False), the interface closes it,
releases its storage and prepares a new operator from the next request's
material. If the change raises but the operator is still usable, the operator's
own record names the material it holds, old or new; the next request reads the
label back from that record and asks for a change only if its own material
differs. The operator's own rule is unchanged: nothing is rolled back and an
interrupted operator is never used again.

A replacement operator must carry the execution identity of the plan's first
operator. If the source changed in between, the request is refused and a new plan
is needed; a replacement is never adopted under different source bytes.

What this costs and changes:

- The replacement is a cold preparation, not a refill, and the operator's retained
  allowance is released in between. It publishes the same bytes and identifiers
  as an uninterrupted change; the focused tests compare them.
- `statistics()['preparations']` can exceed one. `statistics()['mechanics']` is
  `None` while no operator is held, which can now also happen after the first
  preparation: from a failure that released the operator until a request has
  prepared a new one. A failure that leaves the operator usable keeps its
  statistics, and a new operator's counters start at zero.
- While the source differs from the first preparation, each refused request still
  pays for one preparation before it is refused.
- After a change that raised but left the operator usable, the next request reads
  the operator's descriptor once. It makes no extra coefficient comparison,
  reservation or source check. A budget that is too small to admit a coefficient
  change therefore still serves the unchanged material after a refused change,
  as it did before the repair; a focused test holds this at the smallest budget
  that admits the fixture's preparation and solve.

These inputs can describe successive supplied states. There is no interpolation,
transport, integrated displacement or invented geological history between them.
Joined histories and persistent continuation are supplied by the separate
[tectonic-history owner](#tectonics-continuation-step-4-supported-dated-histories), within its supported route scope.
Nonlinear constitutive evolution remains with the existing explicitly supported
material/thermal/mechanical producers, not an implicit law in this interface.

## Focused verification

- Nine new evolving-flexure methods pass (16.888 s); two affected methods also
  pass after final close/zero-result changes (6.928 s).
- Three retained W04 checks pass after the shared validation/load extraction
  (7.689 s), including the connected variable-property total-reference route.
- Seventeen new regional-input methods pass (5.154 s): independent affine shear,
  hydrostatic pressure, changed force and thermal-gravity controls; source/time/
  support and double-counting refusals; coefficient reuse; immutable results;
  cancellation and shared reservation release.
- Nine shared execution-identity checks pass (2.275 s). Static safety passes
  13 source maps / 41 paths and 31 tests (0.110 s; one environmental skip).

**Repair note (R7, 1 October 2026 candidate).** The counts and times above are
the 23 September record and are not rewritten. The interrupted-viscosity-change
repair adds eight regional-input methods in their own class of
[the same module](../tests/test_evolving_mechanics.py): cancellation at every
cancellation check of a coefficient change, with the previous and the new
material then solved exactly and with the identifiers an uninterrupted plan
publishes; a cancellation, a factorisation failure and an interruption that is
not an ordinary exception (as a keyboard interrupt is) inside the refill, each
followed by a released operator and a replacement; a cancellation just after an
accepted change; a cancellation before the refill and a budget-refused change,
which both keep the operator and still serve the unchanged material; byte parity
between a replacement operator and an uninterrupted change; and two checks that
a replacement is refused under another execution identity. One added
[tectonic-history method](../tests/test_tectonic_history.py) resumes a stored
regional history after a cancellation inside a coefficient refill, with outputs
equal to an uninterrupted run. Cancellations and failures are injected through
cancel tokens and through attributes of the one operator object; the changed
source is emulated as the existing source-drift method does it. These were run
in the repair's scratch candidate on Windows/CPython 3.12.14 only; no timing is
recorded here and nothing is claimed for other platforms.

The unchanged-load/changed-rigidity control explicitly distinguishes the correct
two-equilibrium calculation from the incorrect current-operator load-delta route.
Actual W03 advancement also checks unchanged inventory/thermal/water accounting.
No existing benchmark threshold, source cap or R4.4 hold is relaxed. Historical
reports are not rebound; the two new modules participate in current loaded-code
identity. The production inventory was then 122 files under the 128-file cap; the
later [A3 capacity repair](../../docs/CURRENT_EVIDENCE.md#historical-repair-qualification)
raised that cap to 512 files.

The bounded runner is `tectonics/tools/check_evolving_inputs.py --report NEW.json`.
It measures three changed regional requests and three changed elastic/load
scenarios, cold versus prepared, including setup, source checks, complete output
hashing and close. Upstream fixture construction and imports are excluded. It
binds all production files, the driver and imported fixture sources; report
overwrite and source changes during measurement refuse.

### Measured preparation reuse

[Original Windows evidence](../evidence/evolving-inputs-r1.json) passes
complete output/identity hash parity for both routes. Medians of three alternating
cold/prepared pairs (three changed outputs each):

| Route | Cold | Prepared | Seconds saved | Time saved |
| --- | ---: | ---: | ---: | ---: |
| Regional mechanics, 12 x 12 | 0.8189610 s | 0.5888821 s | 0.2300789 s | 28.0940% |
| Evolving elastic support, 32 cells | 2.7921546 s | 1.4756385 s | 1.3165161 s | 47.1505% |

Regional requests change viscosity and boundary motion at three labelled times.
Elastic requests change supplied rigidity/load scenarios at one real W03 instant;
actual W03 time advancement is covered separately by the focused test. Regional
controls independently check affine velocity and shear stress. There are no
identical latest-result hits. Peak accounted bytes were 25,803,044 (regional) and
5,101,952 (elastic), including declared caller fixture allowances; all reservations
were released. These are not process RSS measurements. The complete evidence run
took 18.721 s. This measures preparation reuse, not whole-generator speed or an
external-software performance comparison.

## Research and existing software consulted

- [Wickert (2016), gFlex v1.0](https://gmd.copernicus.org/articles/9/997/2016/)
  and its [official governing-equation documentation](https://gflex.readthedocs.io/en/latest/theory_and_numerics.html#governing-equations):
  conservative variable-rigidity flexure and explicit load/boundary meaning.
  The paper page/excerpts and documented equations were checked, not a fresh
  complete PDF reading.
- [Landlab's gFlex wrapper source](https://landlab.csdms.io/_modules/landlab/components/gflex/flexure.html),
  `flex_lithosphere`: a current equilibrium is compared with the prior deflection
  before applying a surface change. Atlas uses a fixed-reference total instead of
  silently accumulating output increments. The two-operator formula above is a
  direct mathematical consequence of the linear equilibrium equation.
- [TU Delft Euler–Bernoulli weak/discrete form](https://teachbooks.tudelft.nl/computational-modelling/structural_linear/euler_bernouilli.html):
  retain the existing C1 Hermite curvature form rather than invent a new stencil.
- ASPECT 3.0 [basic equations](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/methods/basic-equations/index.html),
  [material model interface](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/extending/plugin-types/material-models.html)
  and [static/dynamic pressure](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/methods/pressure-static-dyn.html):
  separate instantaneous mechanics from temperature/composition evolution, respect
  coefficient sampling/dependencies and perform reference-pressure splitting once.

These were documentation/source inspections, not external software executions or
claims of empirical calibration. Existing numerical laws and their component
evidence are retained; this increment verifies their new input/integration boundary.

## Tectonics continuation Step 4: supported dated histories

23 September 2026. Implementation is in
`atlas_tectonics.tectonic_history` and `tectonic_history_codec`.
[Current state](../../docs/CURRENT_STATE.md) owns subsequent repair/integration
status and holds; the numerical and timing records below retain their dated scope.

### Connected scope

The missing history/recovery boundary now covers the recent underthrust and
evolving-mechanics components. It reuses their existing physical calculations;
it is not another terrain, geology or hydrology solver.

| Route | Supplied history | Preserved meaning |
| --- | --- | --- |
| Underthrust section | Dated outputs within the supplied continuous motion/work intervals | Parcel geometry/cohorts, known or unknown enthalpy, finite receiver/exterior stocks, separate supplied work and gravitational change |
| Evolving W04 | Consecutive actual W03 parent states, coincident rigidity, surface and optional exterior loads | One fixed absolute reference; each displacement is a total change, never the sum of earlier totals |
| Evolving regional mechanics | Strictly increasing, coincident material/force/boundary requests | Quasi-static responses to supplied instantaneous inputs; velocities are not silently integrated into displacement |

W05 extension, W06 spreading, W07 regional workflows and W08's dated finite-stock
regime transitions already have their own history/recovery owners and remain in
use. Their representations are not interchangeable: W08 plan-view footprints
cannot be converted to underthrust x/z parcels by changing a regime label. No
unimplemented representation transfer is reported as an automatic physical join.

### Calling contract

`PreparedTectonicHistory(prepared, inputs, source_id=..., store=...)` borrows an
open `PreparedUnderthrust`, `PreparedEvolvingW04Support`, or
`PreparedEvolvingRegionalMechanics`. `inputs` is a tuple of respectively:

- output times in the underthrust plan's interval range;
- `W04HistoryInput(state, surface, rigidity, exterior=None)`;
- `RegionalMechanicalRequest` objects.

There are 1-256 finite, strictly increasing dates. Negative dates are valid for
named epochs; dates are not assumed to be ages. W04 must follow direct W03 parent
links, not independently computed material branches. Regional support, spatial
origin, epoch and boundary types stay fixed. A history cannot change the producer's
reference convention or replace supplied input bytes with a callback.

`run(through=i)` completes through an optional output index; `run()` completes the
schedule. Each returned `TectonicHistoryOutput` contains the original typed
`.result`, `.index`, `.time_s`, `.output_id` and `.checkpoint_id`. `load(i)` restores
an existing output without computing a missing one, returning `None` when it is
absent. Explicit foreign checkpoint
IDs refuse. Closing a history does not close its borrowed physical preparation.

Create the producer and `ArrayStore` beneath the same explicit
`WorkBudget(128 << 20)`. The history charges additional retained inputs, one latest
output and temporary encoding/recovery work beneath that cap. The codec restores
detached immutable result objects, not live native solver factors. The original
typed input schedule and compatible producer preparation are required to resume;
the receiving producer retains ownership of its input-state checkpoint machinery.

### Recovery and optimisation

Every complete output is published in one existing `ArrayStore.put` transaction.
The parent output ID, full input schedule, physical preparation, source/runtime
identity, result ID and date are bound. Recovery checks a contiguous metadata
prefix and decodes only its latest complete result, then solves only missing
outputs. Earlier physical solves, material movement and external-work booking
are not replayed. Failure/cancellation before publication leaves the last accepted
prefix intact. Gaps, damaged payloads, stale sources and incompatible inputs refuse.

Physical result codecs preserve exact float64/uint8 bytes and WKB geometry;
there is no lossy compression or pickle execution. The existing store supplies
lossless compression and exact chunk deduplication. Histories do not copy the
entire accumulated output sequence into every new checkpoint: each record has one
parent link, with only the latest output kept live. Existing factor/preparation
reuse remains active for missing outputs. Native thread, 128 MiB accounted work
and 256-output limits are unchanged. The
[A3 capacity repair](../../docs/CURRENT_EVIDENCE.md#historical-repair-qualification)
raised the original 128 source-file limit to the current 512. Accounted bytes are
not RSS.

**Publication admits fresh-session restoration under the publishing budget
(R4 repair, introduced 30 September 2026; subsequently integrated).** Checkpoints are immutable and recovery
always finds the latest one, so a checkpoint that its own budget could not restore
would block automatic continuation within the fixed cap; a larger store budget cannot rescue it, because a
history refuses budgets above 128 MiB. Before the repair this happened: restoring
reserved three times the retained result plus 512 KiB, then the store read
workspace and its output envelope, then the codec's own restoration, while
publication never admitted that envelope. The underthrust fixture published at a
common budget of 22,636,544 bytes but needed 23,307,104 to restore; the W04 fixture
18,995,200 against 19,576,352. Scaled underthrust parcels (10,000 and 11,000
vertices) published at 128 MiB and then could not be loaded in the same session; at
11,000 vertices every later resume or load also refused.

Of the two repairs considered — admit the restoration before publishing, or cut the
restoration's reservation — Atlas admits it. Cutting it would still not bound the
codec's child reservations and would leave a smaller window. Before `ArrayStore.put`,
the history now reserves and releases, as one admission check, the complete
restoration envelope of the new checkpoint: its own 3× retained allowance plus
512 KiB, plus the largest of the three phases that never overlap — the store read
(its read workspace and 2× the array total), the codec restoration including its
child codecs (one WKB polygon at a time, or the regional snapshot restoration; the
codec's `history_restore_bytes`), and the regional input reconciliation. It does so
while the run still holds the new result and its predecessor, which is more than a
later restore holds, so a refusal happens before anything is written. A focused
test requires the admitted envelope to equal the peak a real restoration then
reserves on all three routes, so a codec or storage change cannot silently reopen
the window. The live latest output is also reused, not decoded again, when it is
the stored latest (continuing in the same session) and its verified database
change token is unchanged; `load` still decodes and verifies the stored record.
The token observes commits by other SQLite connections and row changes through
the store's own connection, just as the store's existing chunk caches do. A
changed token requires restoration before reuse or continuation. Prefix scanning
and restoration are bracketed by token checks: an intervening write refuses
before adoption. New publications capture their token inside the publishing
transaction, after its inserts but before commit, so a write between commit and
adoption cannot be mistaken for verified data. Continuation rechecks the predecessor
token after computing and packing, and the publication callback refuses another
connection's intervening commit during store preparation; the transaction's own
new inserts are not mistaken for an external write. Unchanged warm reuse still avoids
decoding. Out-of-band raw file modification remains unsupported; a token is not
an authentication signature. The cost is a stricter publication limit: the smallest
admitting budget rose from 22,636,544 to 23,506,240 bytes (+3.8%) for the
underthrust fixture and from 18,995,200 to 19,661,696 (+3.5%) for W04 (smallest
budgets found by bisection to 4 KiB). Both scaled underthrust cases are now refused
at 128 MiB before anything is written. Because the admission counts the result
already held, a restore in the same session is covered too while the borrowed
producer retains no more than it did at publication; a later refused or cancelled
run can leave the producer holding its newer state (measured: +4,128 bytes for the
underthrust fixture, +59,840 for W04), and a load at the exact publishing budget
then needs a fresh session or that much more budget. Fresh-session loads and
resumes were checked at the exact smallest publishing budget on all three routes
(underthrust, W04, regional at 4 and 8 cells). The same repair makes `ArrayStore.put` refuse a snapshot
whose total exceeds the store's full read limit, which previously published regional
checkpoints that `get` refused.

Recovered accounts are checked against actual producer inputs: underthrust stocks,
motion/work and centroid gravity; W04 reference/current state IDs and absolute
datum; regional response options, material/source metadata, compensated physical
forces and supplied boundary arrays. Aggregated forces cannot reconstruct each
original input's bytes (even a signed zero can change during summation), so those
checks use the real typed requests rather than inventing source identities.

### Focused evidence

`test_tectonic_history.py` checks all-three direct/continued/recovered output
parity, W04 fixed-reference/parent semantics, source/schedule/context refusals,
corruption, gaps, transactional cancellation/failure, lifetime and shared-budget
release. Since the R4 repair it also checks that a checkpoint published at the
exact smallest admitting budget loads and continues in a fresh session at that
budget, that one byte less is refused before the store is written, that the same
session continues from its live output without decoding it again, that changed
stored payloads refuse warm reuse and continuation, that writes during restoration
or between publication and adoption cannot bless a damaged checkpoint, and that the
admitted restoration envelope equals the actual restoration peak on every route. `test_tectonic_history_codec.py` checks exact typed round trips,
known/unknown signed heat, pressure and signed-zero handling, malformed/nonfinite
records, immutable payloads and bounded cancellation/resource release.

The reproducible timing driver is `tools/check_tectonic_history.py`; the original
report is `evidence/tectonic-history-r1.json`. It compares three already-completed outputs
with latest-checkpoint recovery on the same prepared producer. It includes fresh
history ownership, source verification, complete result hashing and store reopen
for recovery. Upstream producer-input construction and borrowed preparation are
excluded on both paths; initial checkpoint publication is separately measured.
This is saved-work performance, not an acceleration claim for new simulations.

Measured on Windows, three alternating pairs per route, median seconds:

| Three completed outputs | Recompute | Restore | Seconds saved | Saved |
| --- | ---: | ---: | ---: | ---: |
| Underthrust, 2 parcels | 0.5423182 | 0.2709879 | 0.2713303 | 50.03% |
| Elastic support, 8 cells | 1.6308931 | 0.5895647 | 1.0413284 | 63.85% |
| Regional mechanics, 12 x 12 | 0.8954609 | 0.2924879 | 0.6029730 | 67.34% |

All complete result bytes and IDs matched. Recovery computed zero physical
outputs; recomputation evaluated all three. Peak accounted bytes were respectively
34,741,675, 30,902,879 and 43,183,896; reservations returned to zero. The report binds
all 124 production files, the timing driver and imported fixture helper files.

Verification record: ten workflow methods passed (51.959 s). After final input
reconciliation, the affected all-route stopped/warm recovery method passed again
(25.382 s). Nine initial codec methods passed (3.876 s); five affected/new methods
passed after final hardening (3.863 s), with eleven codec methods now present.
This reuses unaffected results rather than rerunning entire solver campaigns.
Nine shared source-inventory checks passed (3.954 s). Required static checks
passed for 13 selected maps and 41 paths; 31 coding-safety tests passed in 0.105 s
with one existing environmental skip. No Linux runtime campaign was run here;
the measured execution and focused recovery tests used Windows.

### Software and research consulted

- [ASPECT 3 checkpoint/restart documentation](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/run-aspect/checkpoint-restart.html): preserve complete physical state and respect restart compatibility. Atlas retains its stricter source/input refusal policy; ASPECT's configurable restart freedoms are not imported.
- [Wickert (2016), gFlex](https://gmd.copernicus.org/articles/9/997/2016/): modular imposed-load/heterogeneous-lithosphere response. The existing absolute-equilibrium W04 semantics remain unchanged; a dated workflow does not turn them into accumulated displacement increments.
- Existing Atlas W05/W06/W07/W08 workflows, `regional_checkpoint` and `ArrayStore`: reused publication, typed snapshot, resource and source-identity conventions rather than introducing another storage engine.

Subsequent [W10 validation](W10_VALIDATION.md) and
[bounded W12 assembly](W12_ASSEMBLY.md) retain their own delivered scope;
[the integration plan](INTEGRATION_PLAN.md) owns remaining coupled execution.
The held R4.4 campaign, source-bound historical reports and downstream scientific
ownership are unchanged. No old next-stage instruction starts new work.
