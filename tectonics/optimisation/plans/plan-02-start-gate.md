# Plan 02 — By-need start gate and memory admission

**Item ID:** 02  
**Owner:** Plan02 integration owner

**Status:** WORKING NON-CANON; selected generation and known loader repair installed privately, short checks passed. Corrected positive publication/reopen and requested end review remain deferred.

**Completion condition:** Complete Plan02's positive prepared-state publication/reopen validation and end review. Binding into Plan31's assembled candidate belongs to its separate later integration stage and does not block Plan02 completion.

## 1. Current scope and authority

The [Plan02 source snapshot](../workbench/plan02/README.md) contains the selected
Route1/Route2 callers, runner, adjacent launcher, gates and companion tests,
together with the later native transfer metadata repair. Its
[source map](../workbench/plan02/SOURCE-MAP.json) distinguishes original and
public bytes. The original/public method difference is documented there.

Route2's adapter is implemented: it consumes qualifying source-bound monitored
producer or independent-reader completion evidence, and uses an explicit booking
only when no measurements are supplied. Its complete role, command-key and
failure rules are in [the admission contract](../workbench/plan02/ROUTE2_ADMISSION.md).
It does not substitute Route1's stage-record schema.

Private live installation and the scoped source/profile/C18 checks are recorded.
The loader now admits both initial and evolved collar metadata without dropping
their heat/transport identifiers. Corrected positive prepared-state publication
and independent reopen remain unrun after that repair, deferred by the owner.
No fresh scientific interval or final-assembly integration is established.

The public workbench snapshot preserves the frozen `composed-r2` and main package.
It excludes private profiles, execution receipts and stores and is not runnable
as a native installation. All scientific and individual holds remain. This
document does not start or authorise a run.

## 2. Historical Route1 sources and identities

The records in this section describe the earlier Route1 publication. For the
current Plan02 source selection use the source map linked above; these historical
paths and hashes are not a current public runtime profile.

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

- Current consolidated status (private evidence unavailable in this public snapshot), “Drivers, admission and proof tools”, “Item21 publication completed” and “Order and unchanged acceptance boundaries”; SHA-256 `be270e6898e0b1d5aa0c7d29065baf1d4df16ece34490f17d7c68a9d77d4339e`.
- `D/STATE-NOTE.md`, wind-down section A: core evidence, historical wiring plan, remaining Route 2 choice and freeze/before-copy rules; SHA-256 `3556ac777b8fd632a68c6204575ca767b0e46600944d4a6c8391ce557cd6d312`.
- `RV/tectonics/optimisation/IN-PROGRESS.md`, “Start gate sized by need”: retained core evidence and published wiring status. Use actual core code for the complete formula; its short gate summary is not a replacement specification.
- Current queue protocol (private evidence unavailable in this public snapshot): execution, source-freeze and resource rules for any authorised work.

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

The reviewed [prepared-construction v2 component](../workbench/plan02/prepared-construction-v2-r3/README.md)
now uses the actual retained constructor and writer to emit the closed v2 profile,
explicit historical root and declared files query store. Its operational public
build_restart_profile and selected_restart_profile APIs are connected to Plan31's
real authenticated loader. Paired receiving retains its fresh-v1 primary and
separate prepared-v2 companion, with exact shared source and explicit per-leg
bindings. Bounded actual source/profile/API checks support this completed component.


Route2's adapter and all three prepared/monitored callers are implemented and
installed together with the compatible fresh-route generation. The known metadata
repair is also installed. No duplicate adapter decision or caller rewrite remains.
The remaining Plan02 runtime validation is corrected root publication followed
by an independent reopen, without advancing a simulation interval.

Use current source-bound edits and the existing before-copy/staging/rollback requirements. The earlier `S/gate_wiring_stage.py`, `S/gate_swap_apply.py` and `R/L/gs` recipe is historical planned work, not proof those artefacts exist or a mandate to repeat Route 1 changes. Check the current queue and source freeze before any authorised live replacement; never alter files imported by an active or protected queued run.

At the separate later integration stage, the replay/final composition and profile
must pin the selected gate and runner sources as an explicit successor identity.
Preserve old manifests, receipts and source pins and verify the changed seams.
This remains a downstream obligation, not a Plan02 completion prerequisite.

## 5. Evidence and proportionate verification

**Retained core evidence:** 23 tests and 43/43 planted mutants caught, as recorded in the Runner handoff and `IN-PROGRESS.md`. These counts describe that core revision; they are not fixed future test counts or proof of every caller. Preserve the published chain-r3 evidence described in the consolidated status and reuse it only while its tested scope, code, inputs and configuration remain valid.

The retained selected-adapter and changed-caller checks cover the mandatory refusal cases:

1. No qualifying prediction and no declared booking: refuse before run-output creation.
2. Where the selected adapter supports measured records, a lower booking cannot replace the measured peak. A 5-GiB measured peak with a 2-GiB booking still gives an 8-GiB gate. Do not fabricate a measured-record path for a booking-only adapter.
3. Available memory below the computed gate: refuse before run-output creation.

Cover the selected adapter's invalid-evidence cases, paired booking arguments, seed failure, gate consistency and the child handoff as applicable. Preserve required independent refutation for a new comparison/harness route, while reusing adequate unchanged checks. Do not automatically rerun the full core mutant suite solely because this plan was revised.

Use the existing queue lane and appropriate shell for any authorised check. `S/run_start_gate_checks.sh` is a Bash script, not Python input. Its current script performs the seed check and runs the core tests/mutants, but writes fixed `start-gate-tests.log` and `start-gate-mutants.log` paths. If a rerun is justified, the owner must preserve historical evidence and arrange fresh output paths; do not blindly overwrite those logs. This core wrapper alone does not verify Route 2.

Use focused static checks against the retained baseline and distinguish introduced findings from existing ones. The historical Runner handoff records a Pyright missing-import/search-path finding; a broad statement that every global type check is clean is not an acceptance substitute.

Label subsequent figures as MEASURED with source/scope, PROJECTED with basis, or PROPOSED as appropriate. Gate constants are existing contracts and the 5-to-8-GiB example is arithmetic, not a new measurement. Remove invented machine-load histories, timings, failures, harness results and filler citations.

## 6. Outstanding completion conditions

- [x] Route2 adapter and explicit evidence contract implemented.
- [x] All three callers and compatible fresh-route dependencies installed together; scoped checks retained.
- [x] Known metadata defect repaired; short controls and live source/profile checks passed privately.
- [x] Private live integration and scoped C18 evidence recorded separately from publication and scientific acceptance.
- [ ] Positive prepared-state publication and independent reopen on the repaired successor; deferred by the owner.
- [x] Reviewed v2/store implementation and operational public receiving API integrated.

The held native proof above remains open under its own declared scope.
Individual-plan verification after full assembly, including Plan02's former
final-generation restart/profile/store verification and return requests, is
CANCELLED BY OWNER, not passed or reassigned. Plan31/Plan26 still deliver their own
assembly/fold outputs and required checks without a separate Plan02 sign-off.
This assigned component completes on its actual implementation/integration,
necessary checks, required acceptance and verified publication.

The assembly owner binds its selected generation as part of its own actual
output. No later individual Plan02 verification or return gate is retained.

Start-gate readiness is an input to the selected replay/final-build routes; it is
not permission to run them. N9's explicit resume, separate tool/proof conditions
and all fresh-interval and individual holds remain independent requirements.
