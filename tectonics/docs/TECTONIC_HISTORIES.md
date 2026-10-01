# Tectonics continuation Step 4: supported dated histories

WORKING NON-CANON, 23 September 2026. Implementation is in
`atlas_tectonics.tectonic_history` and `tectonic_history_codec`.

## Connected scope

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

## Calling contract

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
an existing output without computing a missing one. Explicit foreign checkpoint
IDs refuse. Closing a history does not close its borrowed physical preparation.

Create the producer and `ArrayStore` beneath the same explicit
`WorkBudget(128 << 20)`. The history charges additional retained inputs, one latest
output and temporary encoding/recovery work beneath that cap. The codec restores
detached immutable result objects, not live native solver factors. The original
typed input schedule and compatible producer preparation are required to resume;
the receiving producer retains ownership of its input-state checkpoint machinery.

## Recovery and optimisation

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
reuse remains active for missing outputs. Native thread, 128 MiB accounted work,
128 source-file and 256-output limits are unchanged. Accounted bytes are not RSS.
The later [A3 capacity repair](REVIEW_REPAIRS_2026-09-26.md#a3-follow-on-bounded-source-inventory-capacity)
raised the source-file limit to 512; the other limits stated here are unchanged.

**Every published checkpoint can be restored under the budget that published it
(R4 repair, 30 September 2026 candidate).** Checkpoints are immutable and recovery
always finds the latest one, so a checkpoint that its own budget could not restore
would block that store for good; a larger store budget cannot rescue it, because a
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

## Focused evidence

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

The reproducible timing driver is `tools/check_tectonic_history.py`; its new report
is `evidence/tectonic-history-r1.json`. It compares three already-completed outputs
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

## Software and research consulted

- [ASPECT 3 checkpoint/restart documentation](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/run-aspect/checkpoint-restart.html): preserve complete physical state and respect restart compatibility. Atlas retains its stricter source/input refusal policy; ASPECT's configurable restart freedoms are not imported.
- [Wickert (2016), gFlex](https://gmd.copernicus.org/articles/9/997/2016/): modular imposed-load/heterogeneous-lithosphere response. The existing absolute-equilibrium W04 semantics remain unchanged; a dated workflow does not turn them into accumulated displacement increments.
- Existing Atlas W05/W06/W07/W08 workflows, `regional_checkpoint` and `ArrayStore`: reused publication, typed snapshot, resource and source-identity conventions rather than introducing another storage engine.

Next: W10 tectonics validation, W11 performance/scale, then W12 generator assembly.
The held R4.4 campaign, source-bound historical reports and downstream scientific
ownership are unchanged.
