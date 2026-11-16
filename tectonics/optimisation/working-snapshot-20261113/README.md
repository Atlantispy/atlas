# Working snapshot (first published 13 November 2026)

Status: **WORKING NON-CANON**. This folder is a working snapshot of the optimisation package, published so the
later work is visible on the review branch. It is not the reviewed folded package. The work made after the fold
has not yet been reviewed, and nothing here claims scientific acceptance. The sections below describe what
this folder's code does, read from the code itself, and say nothing about its correctness: only the
repeated-check removals were reviewed, as built arms with focused tests, and no run on real data was cleared
by those reviews. Paths are relative to `atlas_tectonics/`. For the reader, adoption and continuation method
this code builds on, read [the interval chain](../drivers/INTERVAL_CHAIN.md).

## History

- 13 November 2026: first snapshot of the working arm.
- 15 November 2026: replaced by the package exactly as run by the diagnostic chain of 14 November that
  first used the wired optimisations (64 jobs per admission batch, eight heat workers, parallel geometry, the
  reader running beside its producer, the query hold and the admission group; see
  [the wired set](#the-wired-set-15-november)).
- 15 November 2026: replaced by the package exactly as run by the next diagnostic chain, which added the
  recheck removal (checks already made by an earlier step are not repeated by a later one; see
  [the recheck removal](#the-recheck-removal-15-november)).
- 15 November 2026: the order fix, as run by its diagnostic chain: results no longer depend on
  identifier order (an order derived from content; see [the order fix](#the-order-fix-15-november)).
- 15 November 2026: the step 6 open patch, as run by its diagnostic chain: the interval reader's open no
  longer repeats the heat binding's proof (see [the step 6 open](#the-step-6-open-15-november)).
- 15 November 2026: duplicate-removal unit A with its widths fix, as run by its diagnostic chain: the
  independent reader reads records only, without repeating work an earlier step did (see
  [unit A](#unit-a-the-records-only-reader-15-november)).
- 15 November 2026: batch 2, as run by its diagnostic chain: the restart seed carried across
  intervals, duplicate-removal unit C, the next producer's open (units P and Q), root initial workers,
  geometry workers kept between batches, the geometry id memo and source checks once per heat worker
  (see [batch 2](#batch-2-15-november)).
- 15 November 2026: the next private batch, as run by its diagnostic chain (coverage sidecar buffer,
  heat solver picks, single decodes and verifies, bounds from bytes held and related removals, the heat predictor beside the reconstruction;
  see [the next private batch](#the-next-private-batch-15-november)).
- 16 November 2026: the first result-moving break, as run by its reference chain and its
  kill-and-resume chain (vertex homes chosen by geometry and kept, public-safe edges in the heat
  limiter, counts of work left out of identifiers; see
  [the first result-moving break](#the-first-result-moving-break-16-november)).

Each update is one commit, so its diff shows exactly what changed. The first five 15 November sections were read
from the code at `f29ca36`, the batch 2 section from the code at `9f5080c`, the next private batch from the code at `1e0643e` and the first result-moving break from the code at `25811eb`; the other sections were written for the 13 November contents, and their line
numbers may have moved since. Every chain named here is diagnostic only; none is scientific acceptance, and
none of the 15 and 16 November changes has a review record in this repository.

## Contents

- `atlas_tectonics/`: the public package and `_private`, copied byte for byte from the working arm, with the
  source-list files `_application_sources.json` and `_application_sources.sha256`.
- Left out: the compiled compression library and compiled Python files.
- `.gitattributes` keeps git from rewriting line endings in this folder.

## The one difference from the working arm

`atlas_tectonics/_private/run_fresh_interval.py` line 1312: a machine-specific path to the real-input
qualification folder is replaced by `Path(os.environ['ATLAS_REAL_INPUT_QUALIFICATION'])`. Because of that edit,
this file's row in `_application_sources.json` does not match its bytes here. Every other file is identical to
the arm.

## One identity check per read batch

A sealed store set's file identity (path, links, sidecars and file token) was checked before and after every
manifest and chunk read. The later code checks it once when a read batch starts and once when it ends:

- `_private/interval_store_set.py` `read_batch` (lines 948-972): reads on the calling thread inside the batch
  skip their own per-call identity checks. Nested batches join the outer batch. A file opened inside the batch
  is checked by its own open and again at the batch's end.
- A file replaced, rewritten, re-attributed or given a sidecar during the batch is refused at the batch's end,
  before any result leaves the batch: `_private/segment_store.py` (lines 698-705) withholds results until the
  closing check, and the closing check also runs when the batch body fails.
- Payload checks are unchanged: every chunk's stored checksum and typed content hash are verified on every read.
  Cancellation is still checked on every call.
- Users of the batch: streamed mesh rows (`_private/mesh_tables.py` `_row_batch`, line 1204: checked before and
  after each row, not per decoded value) and the fresh interval advance with its reopen controls
  (`_private/fresh_interval_driver.py` lines 278-280: the second check comes before anything is sealed).
- Related reuse: a cached page is not re-verified on each hit for the life of its view, because it was verified
  when cached and is content-addressed (`_private/record_views.py` lines 439-441); a partition support identity
  reuses the sealed body verification only while its file is unchanged (`_private/partition_v2.py` line 440);
  restart metadata fields are stored as one canonical JSON segment, read back with a few chunk reads and one
  hash (`_private/compact_restart_store.py` lines 40-44).

## The wired set (15 November)

Six execution choices that change how work is scheduled or checked, not what is calculated:

- **64 jobs per admission batch.** `_private/fresh_interval_driver.py` line 127 sets `INITIAL_BATCH_JOBS = 64`
  for the initial admission pool (the pool accepts 1 to 64; its default is 16).
- **Eight heat workers.** The same file, line 138, sets the heat functionals' worker pool to eight; each task is
  one face and rows are put back by index.
- **Parallel geometry.** Line 51 sets `ALE_PARALLEL` to automatic with four workers for interval 1; the code
  states that no result depends on it. A successor entered without a measured worker selection keeps the
  fixed serial policy of line 52, the comparison arm. Since batch 2 the four workers are kept between
  batches ([Part B](#geometry-workers-kept-between-batches-part-b)).
- **The reader beside its producer.** The independent reader starts while its producer is still running and
  waits at a gate (`_private/overlap_reader.py` `admitted_before_gate`, line 219): before the gate it uses only the producer's
  closed measurement record, and it tests that record against the authenticated producer receipt after the
  gate. Its comparisons after the gate are unchanged.
- **The query hold.** `integration_endpoint_checkpoints.py` lines 73-80: completed query records are written and
  synced but not made visible, then published as a group of at most 64 (or 64 x 22,096 work units) after one
  fresh strict execution check. A stopped process leaves at most 63 partial files, which no reader opens and
  which are recomputed.
- **The admission group.** `integration_dual_geometry.py` `MeasurementGroup` (line 699): one strict execution
  check covers up to 64 cached measurement calls; every call of the group, hit or miss, is followed by that
  check before any miss is published. A stopped process loses the held misses, which are measured again.

The same commit adds two diagnostic-only routes. `_private/reuse_previous_run.py` lets a fixed reader read the
previous run's sealed interval when the two trees differ only in reader files that bind no producer output; its
record is branded `NOT SCIENTIFICALLY PERMISSIBLE` and is never adoptable. `--record-failed-prior` (diagnostic
trees only) records, instead of refusing, a failed test of how an earlier producer ended.

## The recheck removal (15 November)

Checks that an earlier step has already made on the same bytes or objects are not repeated by a later step:

- The bounded pre-seal check no longer reads and hashes every chunk row of the candidate again
  (`_private/bounded_preseal.py` `check_candidate`, line 293); its manifest checks remain. The candidate's
  final re-verification after it is made read-only, and a cached-read check at the end of every read batch,
  are removed from `_private/interval_store_set.py`.
- The workflow's own heat checkpoint save is no longer read back: `_r3_heat_checkpoint_reason`
  (`integration_regional_workflow.py` line 1696) compares store tokens only.
- When an exterior owner is present, the collar is verified once, by that owner (line 1056).
- Source files are no longer re-hashed during preparation to detect a change (for example
  `_mimetic_enclosure.py` `assert_current`, line 30), and the fixture identity check in `reuse.py` reuses a
  selection it has been handed.

Every chunk's stored checksum and content hash is still verified on read. The diagnostic chain that first ran
this code measured 260 s less per chain; that is a timing of one diagnostic run, not acceptance.

## The order fix (15 November)

Several identifiers were hashes that included a run identifier (`funding_id`, `flow_id`, `source_id` or the
parent partition id), so results ordered by identifier moved when the execution identity changed. The keys
are now made from content only:

- collar cells: `kind` and `cell_id` (`integration_differential_geometry.py`, `integration_differential_ale.py`,
  `integration_exterior_mesh.py`, `integration_spatial_ale.py`);
- native faces: `axis` and grid position (`integration_native_faces.py` line 313; a face container holds one
  flow at a time, so the flow id is not needed to tell faces apart);
- basal stocks: the lineage without `source_id` (`integration_basal_inventory.py` line 137);
- carried partition regions: without the parent partition id, which stays in `parent_chart` as provenance
  (`integration_differential_geometry.py` line 5742).

The run identifiers are still recorded; they are no longer part of the keys. A second diagnostic chain and a
decoded comparison found every stored number equal to the first; only identifiers differ.

## The step 6 open (15 November)

The interval reader's open (step 6) repeated proofs that the heat binding's restore had just made on the same
objects:

- `RestoredHeatBinding` (`_private/private_heat_restored_binding_r10.py`) records which exchange object its
  restore checked. `proved_for` (line 369) is true only for those very objects, in the same process, and an
  audit-array set that its own validation compared.
- When it is true, `PreparedSpatialOwner` (`integration_spatial_owner.py`, `_proved_composed` at line 190)
  skips recomputing the spatial graph identity, the exchange identity and the transport snapshot. The heat
  identity and the other comparisons remain.
- The cold restore (`integration_private_heat_cold.py` `restore_checkpoint`, line 127) no longer re-reads the store's change
  token and the parent and head metadata around the restore: the workflow's chain walk read them, and its read
  batch and closing token cover the store.
- `_private/spatial_indexed_patch.py` `issue` (line 345) computes the record's metadata digest and identity in
  one pass over its JSON stream instead of two.

On its diagnostic chain step 6's open was measured 1,049 s shorter.

## Unit A: the records-only reader (15 November)

The independent reader of an interval repeated work that the producer and the chain's first step had done.
`_private/reopen_fresh_restart.py` now chooses its core with `records_only` (line 521): a non-review interval
whose runner record carries widths, or a root, is read by the records-only core `_records_only` (line 527).
That core:

- opens the pending sealed file, which hashes it;
- for an interval, takes the producer's width table instead of re-measuring; for a root, scans its two native
  records;
- then applies the width gate.

It runs no admission, opens no workflow and checks no sources; the chain's first step checked them. Anything
else, including every review interval, runs the full core as before, and a records-only result is never
accepted for a review-only producer. The producer side records the widths as it publishes
(`_private/spatial_records_patch.py` line 107, merged by `WidthTable.merge` in `_private/width_gate.py` line
247), and `_private/record_views.py` defers a record's root render until a whole-record use (line 1885); the
render's flag clears only after it passes. The widths fix makes the producer's width check stop asking for
identities that need a partition view it does not have. The chain's values equal the previous chain's; only
identifiers differ.

## Batch 2 (15 November)

Seven changes, one commit each, then one commit that repins the source tables. None changes what is
calculated; each removes repeated work or allows a diagnostic reuse.

### The restart seed across intervals

Run B of an interval may reuse the measurement store that run A recorded (the seed). Until now the seed was
refused unless run A's measurement composition equalled run B's. `_private/run_fresh_interval.py` now also
accepts a seed recorded under an earlier profile, named by path and SHA-256 (`--reuse-previous-run`):

- only on a diagnostic tree, whose manifest says `DIAGNOSTIC_UNCERTIFIED_NO_QUALIFICATION`
  (`diagnostic_tree`, line 536); proof and real trees refuse it, and a Release step refuses it
  (`_across_refused_in_release`, line 1424);
- the earlier profile is read against its pin before admission;
- `_across_change` (line 895) compares the two compositions member by member. Unknown members and a
  different interpreter seed refuse; differences in the profile, source proof, advance driver and helper
  digests are listed in the seed record under `across_change`, and `composition_equal` is false when any is
  listed.

Interval 2's gate (`root_anchor`) accepts such an interval 1 only when interval 1's tree is diagnostic and
its seed record carries that list. A seed across a change is a recorded diagnostic reuse, never a proof that
the two compositions agree.

### Duplicate-removal unit C: the partition opened once

When a successor's workflow restores its compact partition, the partition view that the restored thermal
mesh's support source already holds is reused (`_private/partition_workflow_patch.py` `held_partition`, line
399, passed from `integration_regional_workflow.py` line 1313). It is reused only when it is sealed and has
the same segment reference on the same store scope; otherwise the partition is opened as before
(`restore`, line 404). The heat module's pin of `integration_regional_workflow.py` moves with that file.

### The next producer's open (units P and Q)

In an ordinary run the open of an adopted head now loads what the next interval reads and proves nothing
about it. One run-time switch, `open_proofs` in `_private/compact_contracts.py` (line 261, false by
default, read by `proving()`), decides; the proofs sit behind it in fourteen files. It is turned on:

- by a producer started with `--open-proofs` (proof mode; `_private/run_fresh_interval.py` line 1584),
  which records `open_proofs` in its run record;
- by the independent reader's full core (`_private/reopen_fresh_restart.py` line 801);
- by the tests, through the `proofs()` context manager (line 269).

With the switch on, the open is exactly the open before this change. With it off, the open skips, among
others, the parent validation and the eight snapshot identities, the spatial owner's measure and saved-cell
checks (`integration_spatial_owner.py` line 930), the cold restore's transport identity comparison and the
column digests and canonical re-encodes of stored records; the mesh's logical identity is taken from the
record. What stays: the store's check of every chunk it reads (for disk damage), the typed descriptor
comparisons, and the comparison of the stored heat record's libraries, execution and sources with this
process. A stream that also feeds unit A's width table keeps running. The encoder round trip that the
proofs show is shown by the tests and by any run in proof mode, not by an ordinary run.

### Root initial workers (R1)

Initial admission now runs eight producer workers, one per core, instead of two
(`_private/fresh_interval_driver.py` `INITIAL_WORKERS`, line 129; `integration_initial_parallel.py`
`MAX_WORKERS`, line 35). The serial route (0 workers) for an overlap reader is unchanged.

### Geometry workers kept between batches (Part B)

`ALE_PARALLEL` (`_private/fresh_interval_driver.py` line 51) now sets `keep_workers`
(`integration_parallel_selection.py` line 134, off by default). A kept geometry worker
(`integration_parallel_dispatch.py` `_kept_worker`, line 365) holds one context for its life and serves one
batch at a time, read from its standard input (`serve`, line 658; the session's handle is `_Served`, line
1247). Each batch is still bound by its inputs and checked before and after its members run; the package
source is read once per worker process. Each kept worker holds its own memory baseline, charged within the
session's budget share; after a batch the worker is idle again, or is ended if it is above its baseline
(`_release`, line 1764). Per-batch time marks are written to the resource report only and never stop a run.
With `keep_workers` off, the one-shot worker per batch is unchanged.

### The geometry id memo

`DifferentialInterval.interval_id` and `DifferentialSupport.support_id`
(`integration_differential_geometry.py`, `_memo_id` at line 114) hash the object's canonical JSON once and
keep the digest in a slot. The JSON is immutable and set once at issue, so the digest cannot change.

### Source checks once per heat worker (R-B)

In strict mode `helper_source_digest` (`reuse.py` line 947) reads each source and owner pair in full once
per process and keeps the digest (line 944); a later call in the same process returns it without re-reading
or re-walking the two paths. The cancellation check stays on every call. Release mode is unchanged: external
or uncovered sources are read in full on every call.

### The repin

The last commit regenerates `_application_sources.json` and `.sha256` for the changed files and moves the
END factory and provider (`_private/q297_end_factory_v2.py`, `_private/q297_end_provider_v2.py`) to the
correspondence proof, grid, graph, partition and carry digests of batch 2's tree.

Batch 2 was run by one diagnostic chain. That establishes only that the package ran as published; it is not
review and not scientific acceptance.

## The next private batch (15 November)

Eleven changes, one commit each, then one commit that repins the source tables. All are in `_private`. None
changes a stored result: the chain that carried them was compared value by value with the run before it, and
its only expected record difference is a memory figure and the phase mark described under the heat predictor.
Line numbers are those of `1e0643e`.

### Writes and reads done once

- **Coverage sidecar buffer.** The prepared interval driver writes the certification sidecar through a 64 KiB
  buffer (`prepared_interval_driver.py`, `_SIDECAR_BUFFER`, line 47), charged in the sidecar's reservation
  (line 241), instead of one unbuffered write per token-sized chunk.
- **Bounds from bytes held.** When the bounds a step hashed before its advance are the solution's bounds (same
  SHA-256), both interval drivers hand those bytes to the sidecar directly, with no render and no record open
  (`fresh_interval_driver.py` line 492, `prepared_interval_driver.py` line 484). Otherwise the record is opened
  as before; the sidecar's hash decides.
- **One restart-store alias lookup.** An alias read in the compact restart store does one lookup instead of a
  locator search followed by the read (`compact_restart_store.py` lines 264 and 426, with a lookup in
  `interval_store_set.py`).
- **Each heat assembly value decoded once.** When an interval's lower and upper bounds are the same value, the
  two heat interval assembly kernels decode it once (`private_heat_interval_assembly_kernel_r1.py` line 162 and
  its plan 40b variant).

### The heat low solver

`private_heat_low_solver_kernel_r5.py` converts the public energies to exact fractions once and reads that list
three times (line 367). Its residual sum moves a cell to GMP rationals once the cell's denominator reaches
12,275 bits (`_GMP_RESIDUAL_BITS`, line 170), the measured width above which GMP is faster; both forms are
canonical, so the returned fractions are the same values either way.

### Checks that ran twice

- **The native heat issuer** no longer verifies its implementation a second time straight after the first
  (`private_heat_native_issuer_r13.py`, `_advance_verified` line 592 and `_advance_legacy_packaging_verified`
  line 683).
- **The heat finish** no longer recomputes a residual only to compare it with the ledger the correction already
  keeps (`private_heat_finish_kernel_r11.py` line 171); the tests keep that comparison.
- **The heat correction and the closed guard.** Three more compare-only ledger checks leave ordinary runs
  (`private_heat_correction_owned_r1.py` line 348; `private_heat_closed_owned_r5.py` line 257): the issue tests
  the issued state's ledger. In the one case the issue cannot see, a closed step whose guard settles on theta 0
  (the issued state is then the low one), the guard still tests the state the correction handed in (line 247),
  so every refusal is as before.
- **The public residual.** The heat finish issue now fills the public residual as the exact sum the audit tested
  (`private_heat_finish_issue_owned_r4.py` line 205), and the comparison leaves ordinary runs, so the record no
  longer claims an audit that did not run. The projection step still recomputes the three residuals from the
  record and tests the identity before anything is stored.
- **The snapshot equations at save.** The heat checkpoint repeats the snapshot's equations from stored bytes
  only with proofs on (`private_heat_checkpoint_consumer_r10.py` line 202); in ordinary runs the projection
  step's audit of the record stands for them, and the stored arrays' form and inputs are still tested. The next
  open already skipped these equations outside proof mode, so an ordinary chain now runs them nowhere on the
  stored snapshot.

### The heat predictor beside the reconstruction (H9)

The heat forward kernel runs the low predictor on its own thread beside the reconstruction instead of after it
(`private_heat_forward_kernel_r13.py`, the `heat-predictor` thread at line 263). Its working set is reserved on
the run's ledger first; the thread starts with default numeric contexts; it runs beside only where the pool can
start workers, otherwise in the old order; a predictor failure ends the reconstruction, and the caller's guard
is checked fresh before the result is used. `private_heat_stage_lifetime_r3.py` lets the completed output be
taken from the side ledger the predictor ran on.

The driver marks its phases by watching for the start of certain functions, the low predictor among them. The
geometry observer now records a mark only on the thread that created it (`private_heat_geometry_observer_r1.py`
lines 17 and 31), so the predictor's thread adds none: run records no longer carry the heat-low-predictor phase
mark. Before this, both threads wrote the guard's control file through a temporary name made from the process
id alone, and a chain stopped on the rename.

### The repin

The last commit regenerates `_application_sources.json` and `.sha256` for the changed files.

The batch was run by one diagnostic chain and compared with the run before it. That establishes only that the
package ran as published and moved no stored value; it is not review, not a timing result and not scientific
acceptance.

## The first result-moving break (16 November)

Three changes that move stored results or identifiers on purpose, landed together so that references are made
again once. Each is one commit; a fourth commit adds the pins issued for the run and the source tables. Line
numbers are those of `25811eb`.

### Vertex homes chosen by geometry and then kept

Each vertex of the plate network is stored in the frame of its home (a plate, or a ridge record). Where several
boundary records of the same rank carried a vertex, the home used to be the carrier of the record with the
smallest record ID, so a name chose the frame. Now (`integration_sphere.py`):

- `_carriers` (line 599) lists every carrier a vertex may have: one per record of its lowest rank (a trench
  before a transform before a ridge), or the one plate it lies inside when no record carries it. A vertex that
  no record carries and that is not inside exactly one plate is refused.
- `_rehomed` (line 647) keeps a vertex's home while that home still carries one of those records. Otherwise,
  where the records name one carrier, that carrier is the home; where they name two or more, the home is the
  carrier of the record that is first by a geometric key: the sorted positions of the record's vertices, all in
  one frame, compared exactly and made without arithmetic. Two records with equal keys are refused. The key is
  a convention, not a physical rule: it is free of names and follows the coordinate frame.
- At a declaration there is no home to keep and the positions are the declared points (`_homes`, line 642,
  called at line 784). At an event the positions are the directions in the sphere's axes and the stored homes
  are passed in (`integration_events.py` line 554).
- A stored home is now state. The layout check only confirms that it is one of the vertex's carriers (line 809)
  and no longer derives it again. In proof mode and in the tests, `_kept_over` (line 681), called when a moved
  network is issued (`integration_transfer.py` line 1504), refuses a layout in which a vertex changed its home
  while the old home still carries it.

### Public-safe edges in the heat limiter, and its share in doubles

When the full high-order correction does not pass the step's temperature bounds, the heat correction limits it
face by face (`_private/private_heat_correction_owned_r1.py`). The limiter worked to the exact edge, a cell's
capacity times a bound, and a later rounding guard then scaled the whole correction back by one common factor
when the rounded public temperature failed the public check. Now:

- `_public_edge` (line 312) replaces each exact edge by the double nearest to it on its inner side whose public
  temperature passes that check (used at line 375), so the limited result passes the public check and the guard
  has nothing left to contract. It steps at most eight doubles inward (`_EDGE_STEPS`, line 309); past that it
  keeps the exact edge, the case is counted, and the guard contracts as before.
- Two figures join the step's evidence (line 405): the count of such fallbacks, and the share of the correction
  that survives, which is the sum over faces of the final factor times the size of the face's correction, over
  the sum of those sizes. `_share` (line 294) computes it in doubles with an order-free sum (`math.fsum`), so
  face order cannot move it. It is a report figure and never stops a run.
- The code now names the published limiter it follows, Zalesak's flux-corrected transport (S. T. Zalesak,
  J. Comput. Phys. 31, 335-362, 1979), and says which parts are the package's own: the public-safe edges, the
  guard's common factor, and the use of this limiter between two conduction schemes (line 361).

Thirteen other `_private` files change only in the pins that follow this file's hash.

### Counts of work leave the identifiers

An identifier used to be the hash of its whole record, counts of work included. Two runs that reached the same
values with different effort (another iteration count, another number of quadrature leaves) then produced
different identifiers, and anything ordered by an identifier followed the effort. Now an id-maker hashes its
record without the listed counts. The stored record keeps every field, so ceilings, budgets and readers of
those figures read what they read before, and a record that holds no listed count hashes the same bytes as
before (`_validation.py`: `effort_paths`, line 167, and `without_effort`, line 172).

| Identifier | Left out of the hash | Where |
| --- | --- | --- |
| `result_id` of a snapshot | By producing schema: solver and Krylov iteration counts, nonlinear histories and elapsed time, refinements, integration leaves, the transport's field-error figures | `regional_execution.py`: `RESULT_EFFORT` (line 26); every maker takes its metadata through `identity_metadata` (line 43) |
| Proposal id | The attempt number | `integration_differential_coupling.py`: `PROPOSAL_EFFORT` (line 42) |
| Interval, measure, pose and bounds ids | Work units, leaves and query counts | `integration_differential_geometry.py`: `_effort_id` (line 118) and the `_EFFORT` lists (lines 147, 204, 223 and 379) |
| Balance id | How the belt solve ended | `integration_driving.py`: `BALANCE_EFFORT` (line 52) |
| Driving digest | The outer iteration count and history, and the belt solve's end | `integration_feedback.py`: `DRIVING_EFFORT` (line 52) and `_driving_digest` (line 406) |
| Directed id | Quadrature leaves | `integration_native_projection.py`: `DIRECTED_EFFORT` (line 28) |
| Column state id | Evaluation and iteration counters | `integration_state.py`: `COLUMN_EFFORT` (line 63) and `_column_identity` (line 899) |

Compact records are hashed member by member in a stream that leaves out the same members and hashes the same
bytes as the in-memory form (`_private/record_views.py`: `feed_without`, line 2668, and `feed_result_metadata`,
line 2716; the transport's top-level counts in `_private/spatial_validation_patch.py`, `transport_effort`, line
997). Graph ids and mesh geometry ids are not changed here.

Identifiers move by design. Values move too, in their last places: cells born in a step are ordered by an
identifier that this changes, and sums taken in that order round differently.

### The pins issued for the run

The identities bound by the first interval's end provider move with the changes above, so a capture run on the
new code issued them again: the grid, graph, partition and correspondence-proof hashes in
`_private/q297_end_provider_v2.py` (lines 14 to 17) and `_private/q297_end_factory_v2.py` (line 24 and the run
row at line 34), and the grid file named in `_private/run_fresh_interval.py` (line 1317). The source tables are
regenerated for every changed file.

### What was run

The package as published here was run by a reference chain of eight steps and by a second chain that was killed
and resumed at three points. The second equals the first in every value; 83 identifiers differ, all from one
identity that includes the run folder's path. Against the previous reference, compared cell by cell through the
map from old to new identifiers, receipts and non-heat values agree and transport stocks differ by at most
6.05e-16 relative. Every heat cell differs by about 1e-07 J, about three times the size measured for the limiter
change alone. That excess is explained and not removed: last-place differences in two of the heat's inputs are
amplified by the accurate heat scheme in cells that hold almost no heat capacity
([issue #88](https://github.com/Atlantispy/atlas/issues/88), [issue #89](https://github.com/Atlantispy/atlas/issues/89)). The comparison was reviewed outside this repository and the
heat difference recorded as explained, not equal. That is not scientific acceptance.

## Reader process census

The independent reader is launched under the continuation guard with `--diagnostic-reader-integrity`
(`_private/reopen_fresh_restart.py` line 859). With that flag the guard
(`_private/private_heat_continuation_guard_r3.py`) does three things beyond its usual supervision:

- At the reader's cooperative close it lists every process in the Windows job from handles it holds
  (`_reader_census`, lines 140-190). The job may hold only the registered reader process, or that process and
  one child that is the system `conhost.exe` started with the single argument `0x4`. Any other process, a job
  that changes during the census, or a launcher that differs from the registered parent refuses. The result is
  the receipt field `diagnostic_reader_close`.
- At exit it accepts only that console host as a remaining process (`_reader_exit_census`, lines 192-213);
  anything else is recorded as `live_descendants_at_exit`.
- After cleanup it records the job's process accounting as `diagnostic_reader_terminal` and refuses unless no
  process is active.

The reader copies the close census into its own record as `reader_process_proof` (line 984).
`validate_reopen_receipt` (lines 994-1085) requires that proof to equal the guard's census, the parent identity
to agree across the reader record, guard receipt and guard control, the console host (if any) to be the system
`conhost.exe` with argument `0x4`, the terminal job to be empty, and the reader's launch context (job name,
nonce, parent) to match the guard. What this establishes: the reader ran with no unexplained process beside it
in its job. It does not establish anything about the values the reader read.

## Command-line options of the interval runners

Every runner takes `--profile` and `--profile-sha256` and one action (`--launch` or `--workload`; the prepared
reader also `--finalise`), plus the start-gate arguments.

| Runner (`_private/`) | Other options, as declared in the code |
| --- | --- |
| `run_fresh_interval.py` (lines 1664-1684) | `--mode`; `--production-release` (explicit authenticated packaged production only); `--dev-timing` (opt-in timing and memory diagnostics); `--stop-before-advance` (run B smoke, interval 1 only); `--seed-receipt-sha256` with `--seed-store-sha256` (run B reuses the measurement store run A recorded); `--reuse-previous-run` with `--reuse-previous-run-sha256` (with a seed, diagnostic trees only: the earlier profile the seed was recorded under); `--open-proofs` (proof mode: the open of an adopted head proves what it loads); `--interval N` (N >= 2) with `--parent-adopted-sha256` |
| `run_prepared_restart.py` (lines 1757-1766) | `--stop-before-advance`, `--dev-timing`, `--production-release` |
| `reopen_fresh_restart.py` (lines 1246-1265) | `--mode`, `--interval`; the receipt pins `--producer-receipt-sha256`, `--reopen-receipt-sha256`, `--guard-receipt-sha256`, `--guard-control-sha256`, `--verdict-sha256`; `--overlap-spec` with `--overlap-gate-sha256`; `--reader-fallback` with `--fallback-claim-sha256`; `--review` with `--review-approval-sha256` |
| `reopen_prepared_restart.py` (lines 1404-1416) | `--producer-receipt-sha256`, `--output-directory`, `--mode` (default `successor`), `--store-route` (default `readonly`), `--reopen-receipt-sha256` |

## Environment variables read by this package

| Variable | Where | What the code does with it |
| --- | --- | --- |
| `ATLAS_EXACT_ARITHMETIC` | `exact_arithmetic.py` line 181 | `auto` (default), `python` or `gmpy2`; any other value refuses. |
| `ATLAS_DEV_STAGE_TIMING` | `_private/dev_stage_timing.py` line 33 | Development stage timing; see the [compact plan](../docs/COMPACT_EVERYWHERE_PLAN.md). |
| `ATLAS_INITIAL_MEASUREMENT_SEED` | `_private/run_fresh_interval.py` lines 134, 1081; `_private/reopen_fresh_restart.py` line 185 | Never read: the runner and the reader refuse to start if it is set. Seeds are explicit arguments only. |
| `ATLAS_REAL_INPUT_QUALIFICATION` | `_private/run_fresh_interval.py` line 1312 | The qualification folder (the one difference from the arm, above). |
| `ATLAS_RECORD_SPILL_DIR` | `_private/record_tables.py` line 213 | Spill folder for record tables when the module setting is not given. |
| `ATLAS_INTERFACE_PARALLEL`, `ATLAS_INTERFACE_PROFILE` | `_private/runtime_joined_control.py` lines 147-150 | Interface parallel mode `auto` (default), `serial` or `off`, and an optional profile path. |
| `ATLAS_HEAT_WORKERS_STRICT` | `_private/private_heat_functionals_parallel_r1.py` line 219 | `1`: a recorded heat-worker problem raises instead of falling back to the serial calculation; unset or empty is off. |
| `ATLAS_PLAN15_ASSEMBLY_CONTRACT`, `..._SHA256` | same file, lines 1241, 1459-1460 | Names the Plan15 observer contract and its pin; when neither is set, only the Plan15 observer path is skipped. |
| `ATLAS_FOCUSED_ARTIFACT_DIR` | several `_private` runner and runtime modules | See the [release check policy](../docs/release/RELEASE-CHECKS.md). |
| `ATLAS_CONTINUATION_JOB_CONTEXT` | set by the continuation guard | Passes the guard's job context to the workload. |
| `PYTHONHASHSEED` | several runners and worker modules | Must be `0`. |
