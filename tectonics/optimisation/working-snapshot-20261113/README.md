# Working snapshot, 13 November 2026

Status: **WORKING NON-CANON**. This folder is a working snapshot of the optimisation package, published so the
later work is visible on the review branch. It is not the reviewed folded package. The work made after the fold
has not yet been reviewed, and nothing here claims scientific acceptance. The sections below describe what
this folder's code does, read from the code itself, and say nothing about its correctness: only the
repeated-check removals were reviewed, as built arms with focused tests, and no run on real data was cleared
by those reviews. Paths are relative to `atlas_tectonics/`. For the reader, adoption and continuation method
this code builds on, read [the interval chain](../drivers/INTERVAL_CHAIN.md).

## Contents

- `atlas_tectonics/`: the public package and `_private`, copied byte for byte from the working arm, with the
  source-list files `_application_sources.json` and `_application_sources.sha256`.
- Left out: the compiled compression library and compiled Python files.
- `.gitattributes` keeps git from rewriting line endings in this folder.

## The one difference from the working arm

`atlas_tectonics/_private/run_fresh_interval.py` line 1238: a machine-specific path to the real-input
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
| `ATLAS_REAL_INPUT_QUALIFICATION` | `_private/run_fresh_interval.py` line 1238 | The qualification folder (the one difference from the arm, above). |
| `ATLAS_RECORD_SPILL_DIR` | `_private/record_tables.py` line 213 | Spill folder for record tables when the module setting is not given. |
| `ATLAS_INTERFACE_PARALLEL`, `ATLAS_INTERFACE_PROFILE` | `_private/runtime_joined_control.py` lines 147-150 | Interface parallel mode `auto` (default), `serial` or `off`, and an optional profile path. |
| `ATLAS_HEAT_WORKERS_STRICT` | `_private/private_heat_functionals_parallel_r1.py` line 219 | `1`: a recorded heat-worker problem raises instead of falling back to the serial calculation; unset or empty is off. |
| `ATLAS_PLAN15_ASSEMBLY_CONTRACT`, `..._SHA256` | same file, lines 1241, 1459-1460 | Names the Plan15 observer contract and its pin; when neither is set, only the Plan15 observer path is skipped. |
| `ATLAS_FOCUSED_ARTIFACT_DIR` | several `_private` runner and runtime modules | See the [release check policy](../docs/release/RELEASE-CHECKS.md). |
| `ATLAS_CONTINUATION_JOB_CONTEXT` | set by the continuation guard | Passes the guard's job context to the workload. |
| `PYTHONHASHSEED` | several runners and worker modules | Must be `0`. |
