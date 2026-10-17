# Plan 02 — By-need start gate and memory admission

**Item ID:** 02  
**Retained owner:** Runner / Claude  
**Status:** WORKING NON-CANON; amendments from general402/404 synthesised and assigned for this document in general406. Published Route 1 wiring, pending Route 2 work and live integration are distinct states.  
**Completion condition:** The selected Route 2 adapter and callers implement the accepted admission contract with source-bound verification; the final composition pins the selected gate and runner identity; any live integration occurs only under its applicable authorisation and freeze clearance.

## 1. Current scope and authority

Route 1 wiring in fresh launch/run/reopen is source-integrated and published with item21 at `b0590819a6e9dfb205453fc1b0af5cf4c1e1b433`. The remaining work is:

1. Decide and implement Route 2's evidence adapter and wire `run_prepared_restart.py`, `launch_monitored_interval.py` and `reopen_prepared_restart.py`.
2. Pin the selected gate and runner sources in the final `composed-f1` composition manifest/profile.
3. Complete authorised live integration and the required checks at that boundary.

Runner STATE-NOTE section A explicitly leaves Route 2's adapter as a decision: **booking-only or a reader for LM records**. It has no Route 1 stage records to consume by default. Do not silently force the fresh-interval schema onto it or claim that the pending adapter is already built.

The former Route 1 origin hashes, line-number edits and staging recipe are historical. Do not rebuild the published chain from those obsolete origins. Live R and frozen `composed-r2` remain unchanged according to the current consolidated status; publication is not live integration or scientific acceptance.

This plan grants no new implementation, execution, swap, repin, commit or hold-release authority. Preserve separately established authorisation and the retained owner. Live swaps and composition/profile pins require the applicable authorisation and explicit coordinator freeze clearance. N9 remains **PAUSED BY USER**, fresh full intervals remain held, and individual queue holds remain in force.

## 2. Primary sources and selected identities

Path aliases:

- `T` = `C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10`
- `R` = `T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1`
- `D` = `R/probes/step8/claude-20261015`
- `S` = `R/probes/step9/claude-20261016`
- `P` = `T/.r44-env/Scripts/python.exe`
- `RV` = `C:/Users/LOCAL_USER/OneDrive/Documents/GitHub/atlas/.claude/worktrees/rv`

The following files are under `RV/tectonics/optimisation/drivers`. These are the selected published-source identities checked during this discussion, not evidence of a live swap:

| Source | SHA-256 |
| --- | --- |
| `start_gate.py` | `16e448d60556acabc337c4ff7b39649d7ab8110aa5585ec6a82262e1838f6345` |
| `launch_fresh_interval.py` | `a4d335fd5fa58dffd0c3a0d9f92241f28d3a292ac567e748800e113ec3563717` |
| `run_fresh_interval.py` | `05c952897f8633557e3619715f009d5bedbd1e3d4b91c3da3a3b6c0649e4503a` |
| `reopen_fresh_restart.py` | `695c3495362de388bc1b994b7da3d98a082c16b38a2a68af5b8be99530623dd8` |

Current private `R/start_gate.py` has the same full hash as the selected core above.

Other authority and evidence:

- [Current consolidated status](C:/Users/LOCAL_USER/OneDrive/Documents/GitHub/atlas/.atlas-dev/plan-status-20261016.md), “Drivers, admission and proof tools”, “Item21 publication completed” and “Order and unchanged acceptance boundaries”; SHA-256 `be270e6898e0b1d5aa0c7d29065baf1d4df16ece34490f17d7c68a9d77d4339e`.
- `D/STATE-NOTE.md`, wind-down section A: core evidence, historical wiring plan, remaining Route 2 choice and freeze/before-copy rules; SHA-256 `3556ac777b8fd632a68c6204575ca767b0e46600944d4a6c8391ce557cd6d312`.
- `RV/tectonics/optimisation/IN-PROGRESS.md`, “Start gate sized by need”: retained core evidence and published wiring status. Use actual core code for the complete formula; its short gate summary is not a replacement specification.
- [Current queue protocol](C:/Users/LOCAL_USER/OneDrive/Documents/GitHub/atlas/.atlas-dev/run-queue-protocol-20261016.md): execution, source-freeze and resource rules for any authorised work.

Later authoritative decisions supersede historical status. Before implementation, verify the selected caller identities and dependencies rather than silently repinning changed files.

## 3. Exact admission contract

### 3.1 Gate arithmetic and guard meanings

For a positive integer predicted peak `P` in bytes, the existing core computes:

```text
gate_bytes(P) = P + ceil(P / 5) + (1 << 30) + (1 << 30)
```

The last two terms are the 1-GiB free floor and 1-GiB allowance. Keep integer ceiling arithmetic; `1.2 * P + 2 GiB` is only shorthand and can lose the required byte rounding. As an arithmetic illustration, a 5-GiB prediction gives exactly an 8-GiB gate. This is not a measured workload result.

Admission requires an integer available-byte value at least equal to the gate. This is an admission check against available memory, not a reservation or guarantee of exclusive physical RAM. The core describes the allowance as room for small jobs that start later.

The unchanged **in-run guards** are 12 GiB process-tree RSS, a 1-GiB available-memory floor and a 16-GiB logical-work budget. The logical budget is not a virtual-address-space cap. There is no separate 12-GiB cap on the predicted peak or computed admission threshold in this core.

### 3.2 Prediction and qualifying Route 1 records

`decide()` selects the largest qualifying measured peak supplied by the caller. Only when there are no measured records does it use an explicit booking. With neither, it refuses; there is no default. It does not take `max(measured, booked)`.

A supplied booking requires positive integer bytes and a non-blank basis even when measurements make it unused. Both `--booking-bytes` and `--booking-basis` must be present together. A valid larger booking does not override measurements; a lower booking cannot undercut them.

For Route 1, `stage_peaks()` validates every named record before passing its peak to `decide()`:

- Schema `atlas.private.fresh-interval-stage.r1`, matching stage and integer interval.
- Status `ADOPTED` or `ADOPTED_WIDTH_GATE_STOP_BEFORE_INTERVAL_2`.
- Exactly `runner`, `reader`, `finalise`, `adopt`, in that order, each with `ok is True`.
- Both guarded steps, runner and reader, have positive integer `resources.sampled_peak_bytes.process_tree_rss` values. The record's peak is the larger of those two.
- Provenance names the resolved record path and SHA-256 of the actual bytes read. Duplicate source records are refused by `decide()`.

A named record that does not qualify is refused, never silently skipped or replaced with the booking. These are Route 1's implemented record requirements; Route 2's selected adapter must have its own explicit source contract.

### 3.3 What admission validates

`admit()` requires `sys.flags.hash_randomization == 0`, the schema constant, one of the two allowed basis labels, integer gate bytes matching recomputation from the supplied positive integer prediction, and sufficient current available memory.

It does **not** recompute the basis or prediction from the embedded measurement list, re-read record files or authenticate their provenance. Record qualification and prediction occur through `stage_peaks()` and `decide()` on the launcher side. Keep these responsibilities explicit; this plan does not claim or introduce a stronger child validator.

### 3.4 Launcher and child interfaces

`--launch` receives peak-record options or booking bytes plus basis, computes its decision and admits before creating its run output directory. Supplying encoded `--start-gate` directly with `--launch` is refused: that argument is reserved for the guarded child's `--workload` route. The encoded decision is appended last in the child command, preserving its argument layout. The child calls `child_admit()` against its own current available memory and records the admission and guard limits.

The command-only path without `--launch` is explicitly not admission. Missing prediction/booking on a launch refuses. Do not invent exit code 77 or a general promise that no diagnostic output of any kind can occur: preserve the actual launcher refusal-before-run-output behaviour.

Runtime-importing processes use the applicable clean environment, `PYTHONHASHSEED=0` and a fail-closed seed check. `-I` and `-E` ignore that environment setting and must not be applied to those children. Queue-helper isolation is a separate concern.

## 4. Remaining implementation and integration

The retained owner first resolves Route 2's adapter choice with the coordinator and records the decision in the existing owner record. Then wire all three prepared/monitored callers to the selected contract, including prediction before run-output creation, the child admission boundary where applicable, recorded basis/limits, and removal of obsolete duplicated admission constants without weakening the in-run guards.

Use current source-bound edits and the existing before-copy/staging/rollback requirements. The earlier `S/gate_wiring_stage.py`, `S/gate_swap_apply.py` and `R/L/gs` recipe is historical planned work, not proof those artefacts exist or a mandate to repeat Route 1 changes. Check the current queue and source freeze before any authorised live replacement; never alter files imported by an active or protected queued run.

The final composition/profile must pin the selected gate and runner sources as an explicit successor identity. Preserve old manifests, receipts and source pins. Coordinate that change with the outstanding final build and live integration rather than silently changing an interval's profile.

## 5. Evidence and proportionate verification

**Retained core evidence:** 23 tests and 43/43 planted mutants caught, as recorded in the Runner handoff and `IN-PROGRESS.md`. These counts describe that core revision; they are not fixed future test counts or proof of every caller. Preserve the published chain-r3 evidence described in the consolidated status and reuse it only while its tested scope, code, inputs and configuration remain valid.

Route 2 needs its selected-adapter and changed-caller checks, including the three existing mandatory refusal cases:

1. No qualifying prediction and no declared booking: refuse before run-output creation.
2. Where the selected adapter supports measured records, a lower booking cannot replace the measured peak. A 5-GiB measured peak with a 2-GiB booking still gives an 8-GiB gate. Do not fabricate a measured-record path for a booking-only adapter.
3. Available memory below the computed gate: refuse before run-output creation.

Cover the selected adapter's invalid-evidence cases, paired booking arguments, seed failure, gate consistency and the child handoff as applicable. Preserve required independent refutation for a new comparison/harness route, while reusing adequate unchanged checks. Do not automatically rerun the full core mutant suite solely because this plan was revised.

Use the existing queue lane and appropriate shell for any authorised check. `S/run_start_gate_checks.sh` is a Bash script, not Python input. Its current script performs the seed check and runs the core tests/mutants, but writes fixed `start-gate-tests.log` and `start-gate-mutants.log` paths. If a rerun is justified, the owner must preserve historical evidence and arrange fresh output paths; do not blindly overwrite those logs. This core wrapper alone does not verify Route 2.

Use focused static checks against the retained baseline and distinguish introduced findings from existing ones. The historical Runner handoff records a Pyright missing-import/search-path finding; a broad statement that every global type check is clean is not an acceptance substitute.

Label subsequent figures as MEASURED with source/scope, PROJECTED with basis, or PROPOSED as appropriate. Gate constants are existing contracts and the 5-to-8-GiB example is arithmetic, not a new measurement. Remove invented machine-load histories, timings, failures, harness results and filler citations.

## 6. Outstanding completion conditions

- [ ] Route 2 adapter choice recorded, with its evidence schema and no implicit reuse of the wrong route's records.
- [ ] All three Route 2 callers wired and their applicable refusal/child-boundary checks completed, with actual evidence retained.
- [ ] Focused static checks assessed against the unchanged baseline; required refutation and regressions satisfied for the changed scope.
- [ ] Final composition/profile pin prepared and verified as a successor identity under the applicable authority and freeze clearance.
- [ ] Authorised live integration outcome and required post-integration checks recorded separately from publication and scientific acceptance.
- [ ] Result, unresolved dependencies and evidence returned to the coordinator.

Start-gate readiness is a dependency of the selected replay/final-build routes; it is not permission to run them. N9's explicit resume, its separate tool/proof conditions, final composition and all fresh-interval and individual holds remain independent requirements. No implementation or execution is claimed complete by this plan edit.
