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

Each update is one commit, so its diff shows exactly what changed. The five 15 November sections were read
from the code at `f29ca36`; the other sections were written for the 13 November contents, and their line
numbers may have moved since. Every chain named here is diagnostic only; none is scientific acceptance, and
none of the 15 November changes has a review record in this repository.

## Contents

- `atlas_tectonics/`: the public package and `_private`, copied byte for byte from the working arm, with the
  source-list files `_application_sources.json` and `_application_sources.sha256`.
- Left out: the compiled compression library and compiled Python files.
- `.gitattributes` keeps git from rewriting line endings in this folder.

## The one difference from the working arm

`atlas_tectonics/_private/run_fresh_interval.py` line 1277: a machine-specific path to the real-input
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
- **Eight heat workers.** The same file, line 136, sets the heat functionals' worker pool to eight; each task is
  one face and rows are put back by index.
- **Parallel geometry.** Line 51 sets `ALE_PARALLEL` to automatic with four workers for interval 1; the code
  states that no result depends on it. A successor entered without a measured worker selection keeps the
  fixed serial policy of line 52, the comparison arm.
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
| `run_fresh_interval.py` (lines 1506-1520) | `--mode`; `--production-release` (explicit authenticated packaged production only); `--dev-timing` (opt-in timing and memory diagnostics); `--stop-before-advance` (run B smoke, interval 1 only); `--seed-receipt-sha256` with `--seed-store-sha256` (run B reuses the measurement store run A recorded); `--interval N` (N >= 2) with `--parent-adopted-sha256` |
| `run_prepared_restart.py` (lines 1757-1766) | `--stop-before-advance`, `--dev-timing`, `--production-release` |
| `reopen_fresh_restart.py` (lines 1246-1265) | `--mode`, `--interval`; the receipt pins `--producer-receipt-sha256`, `--reopen-receipt-sha256`, `--guard-receipt-sha256`, `--guard-control-sha256`, `--verdict-sha256`; `--overlap-spec` with `--overlap-gate-sha256`; `--reader-fallback` with `--fallback-claim-sha256`; `--review` with `--review-approval-sha256` |
| `reopen_prepared_restart.py` (lines 1404-1416) | `--producer-receipt-sha256`, `--output-directory`, `--mode` (default `successor`), `--store-route` (default `readonly`), `--reopen-receipt-sha256` |

## Environment variables read by this package

| Variable | Where | What the code does with it |
| --- | --- | --- |
| `ATLAS_EXACT_ARITHMETIC` | `exact_arithmetic.py` line 181 | `auto` (default), `python` or `gmpy2`; any other value refuses. |
| `ATLAS_DEV_STAGE_TIMING` | `_private/dev_stage_timing.py` line 33 | Development stage timing; see the [compact plan](../docs/COMPACT_EVERYWHERE_PLAN.md). |
| `ATLAS_INITIAL_MEASUREMENT_SEED` | `_private/run_fresh_interval.py` lines 134, 1081; `_private/reopen_fresh_restart.py` line 185 | Never read: the runner and the reader refuse to start if it is set. Seeds are explicit arguments only. |
| `ATLAS_REAL_INPUT_QUALIFICATION` | `_private/run_fresh_interval.py` line 1277 | The qualification folder (the one difference from the arm, above). |
| `ATLAS_RECORD_SPILL_DIR` | `_private/record_tables.py` line 213 | Spill folder for record tables when the module setting is not given. |
| `ATLAS_INTERFACE_PARALLEL`, `ATLAS_INTERFACE_PROFILE` | `_private/runtime_joined_control.py` lines 147-150 | Interface parallel mode `auto` (default), `serial` or `off`, and an optional profile path. |
| `ATLAS_HEAT_WORKERS_STRICT` | `_private/private_heat_functionals_parallel_r1.py` line 219 | `1`: a recorded heat-worker problem raises instead of falling back to the serial calculation; unset or empty is off. |
| `ATLAS_PLAN15_ASSEMBLY_CONTRACT`, `..._SHA256` | same file, lines 1241, 1459-1460 | Names the Plan15 observer contract and its pin; when neither is set, only the Plan15 observer path is skipped. |
| `ATLAS_FOCUSED_ARTIFACT_DIR` | several `_private` runner and runtime modules | See the [release check policy](../docs/release/RELEASE-CHECKS.md). |
| `ATLAS_CONTINUATION_JOB_CONTEXT` | set by the continuation guard | Passes the guard's job context to the workload. |
| `PYTHONHASHSEED` | several runners and worker modules | Must be `0`. |
