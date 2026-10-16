# Route (1) steps 2-3 design: fresh-start runner, reader and partitions (16 Oct 2026, ~04:15)

Approved inputs:
- route (1) (`route-comparison.md`);
- step 1, the root-metadata references (landed);
- 9(a) option B (`design-9a-promote-after-reader.md`);
- the step 2 plan (compact partition payload on compact stores).

Paths: R = resumability-r1, C = R/compact-geometry-r1, H = heat-repair-20261007 (read-only).

## How r9 built interval 1 (read in H/probe_heat_original_connected_r9.py, 174-240)

1. `radial_differential_fixture(budget, pressure_space='q1-p0', material_quadrature=True)` -> `case` (collar, owner, funding, source).
2. `spatial.initial_partition(case, max_components=4096)` -> `current, partition`.
3. `spatial.initial_metrics(...)` -> `bounds, mesh`. This uses a measurement cache store.
4. `spatial.initial_spatial_owner(...)` -> the spatial `owner`.
5. `check_initial_pressure_force(...)` calls `prepared(driver, pressure, datum)`, which:
   - runs `Workflow.create(store, collar, owner, funding, exterior_owner=owner, differential_partition=partition, current_geometry=current)`, giving the root (sequence 0);
   - runs `joined._advance_current_interval(...)`, which advances interval 1 and calls `completed_observer` to record the endpoint;
   - runs `joined._check_reopened`.

Everything in steps 1-4 and the pressure/force check is a deterministic function of the fixture and the composition. Nothing is loaded from a stored start.

## Route (1) flow: two runner invocations and the 9(a) protocol at each seal

- **Run A, root (interval-0000):**
  - steps 1-5 up to `Workflow.create` on a `CompactRestartStore`, whose root metadata goes through step 1's byte segments;
  - seal interval-0000;
  - record `sealed_awaiting_reader`;
  - exit.

  The root interval holds only the root (about 24 MB of arrays plus about 337 KB of descriptor fields).
- **Launcher.** The independent reader opens the pending root file and re-derives the root:
  - `CollarWorkflow.open` with the rebuilt fixture checks every root field against the rebuilt definitions, plus the initial state from funding;
  - plus the reader's per-scalar checks.

  On PASS it calls `adopt_and_promote`.
- **Run B, interval 1 (interval-0001):**
  - recompute steps 1-5, deterministically and with the same composition, as the native contract does;
  - `Workflow.open(store, workflow_id, ...)` replaces `create`, and its equality checks prove the recomputed admission equals the stored root;
  - `begin_interval` to get the interval-0001 candidate;
  - `joined._advance_current_interval`;
  - `bounded_preseal`, then seal, then record, then exit.
- **Launcher.** The reader runs on interval-0001; on PASS it calls `adopt_and_promote`. Then the difference-ledger comparator (step 4) runs, read-only, against r9.
- **Interval 2** continues from interval-0001 with the existing successor driver (`prepared_interval_driver`, generalised to an ordinary head).

**Costs.** Run B recomputes the admission once more: the fixture, initial partition, metrics and pressure/force check (r9 timing to be read from its receipt phases; minutes, not hours). This is the price of option B's no-overlap memory rule.

**Alternative.** One process that keeps the admission across the root seal would need the runner to block until the launcher promotes, which is cross-process coordination. Not recommended.

## Step 2 contents

1. **Compact partitions for ordinary workflows on compact stores** (C/partition_workflow_transform.py, approved):
   - the `_publish` condition becomes "migrated or compact store";
   - ArrayStore and migrated paths stay byte-identical;
   - WORKFLOW_OUTPUT_SHA256 changes and is re-pinned by the WP9 composer at Step 10;
   - the interval-0 root partition stays legacy arrays (`_restore_partition` dispatches on `compact_partition`).
   Tests:
   - an ordinary workflow on a compact store publishes a v2 partition and restores it exactly;
   - an ArrayStore workflow's output is byte-identical;
   - a migrated workflow is unchanged;
   - the transform pin moves only by the condition text.
2. **Ordinary-root reader.** A new module `R/reopen_fresh_restart.py` keeps reopen_prepared_restart (the migrated lineage, D6 archival) unchanged. Modes:
   - `root`: open with the rebuilt fixture, plus the per-scalar checks of the root's records;
   - `successor`: the head's successor records re-derived exactly as the existing successor mode does (shared functions imported, not copied); the lineage is root -> successor by key, workflow_id and sequence.
3. **Runner and driver acceptance of an ordinary base.** `_advance_checked` and `prepared_interval_driver` accept `CollarWorkflow` with no `_migration`. The migrated checks stay for migrated bases.

## Step 3 contents

`R/run_fresh_interval.py`, a new runner (the migrated runner stays as it is):
- modes `root` and `interval`;
- the guard and receipt layout of run_prepared_restart;
- the 9(a) protocol;
- the composition and fixture pins in the receipt;
- every failure record carries first_raised.

The launcher gets a `--fresh` route.

## Blockers and dependencies

- Fresh-process end-to-end tests need the WP17 companion fix (storage).
- 9(a) needs the pending-view and `adopt_and_promote` primitives (storage, right after S1).
- The real interval-1 rerun needs the coordinator's go and the full Step 10 composition (Michael's rule).

## Later-step impact

Interval 2 and interval 3 runs use the run-B pattern (open, then advance) from their promoted head.

## Interval 3

Run B's admission recompute is a fixed cost per lineage (once, at interval 1), not per interval.
