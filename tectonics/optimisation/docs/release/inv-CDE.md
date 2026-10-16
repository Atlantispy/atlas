# Inventory C / D / E for the release-vs-strict build decision

Root: `fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/composed-r2`
(all paths below are relative to it). Scope: `src/atlas_tectonics/*.py` (236 files) and `helpers/*.py` (369 files).
Method: rg / sed -n / wc only; nothing executed. Where I did not read the code that decides a point, the cell says "unverified".
Abbreviations: `H/` = `helpers/`, `S/` = `src/atlas_tectonics/`.

## C. Resource guards that protect the user's machine

| # | Guard | Where defined (file:line) | Threshold: where set, fixed or computed | In-run or start-only | On breach |
|---|---|---|---|---|---|
| C1 | External RSS limit on the whole workload job tree (guardian samples the tree every 0.25 s) | `H/private_heat_continuation_guard_r3.py:30` `RSS_LIMIT`, `:41-47` `_limits`, `:224` `supervise`, `:346` trigger | Fixed 12 GiB. `_limits` accepts only a value at or below the constant, so callers can only tighten. Passed as `RSS_BYTES` at `H/run_prepared_restart.py:46`; recorded at `:837-839` | In-run, independent process | `trigger('rss_limit')`, cooperative grace of at most 5 s (`:48-49`), then `job.stop()` (`H/private_heat_continuation_guard_r3.py:367`, `:393`, `:410`) = TerminateJobObject (`H/windows_workload_job.py:232-233`). Record status FAILED |
| C2 | Free-physical-memory floor | same file `:31` `FREE_FLOOR`, `:41-47`, `:348` trigger | Fixed 1 GiB, may only be raised. `H/run_prepared_restart.py:46` `FREE_BYTES` | In-run | Same path as C1 |
| C3 | Cancel-file / user cancel | same file `:172` `check()` raises `GuardAborted`, `:344`; `H/launch_monitored_interval.py:646-684` `cancel` | Not a number; file presence | In-run | Status INTERRUPTED; `terminate_unresponsive_guardian` option |
| C4 | Windows job object: kill-on-close, no breakaway, single exclusive job name, membership verified | `H/windows_workload_job.py:18-19` flags, `:128-146` `WindowsJob`, `:147-151` `verify_limits`, `:247-259` membership | Fixed (no numbers) | Whole run | Supervisor death kills the tree; a name clash raises `RuntimeError('Exclusive fresh workload job required')` |
| C5 | Start gate: 10 GiB physically available | `H/run_prepared_restart.py:46` `START_BYTES`, `:831-832`, second gate `:1100`; `H/launch_monitored_interval.py:43-46`, `:366-374`; `H/run_fresh_interval.py:478-493`; `H/launch_fresh_interval.py:129-136` | Fixed constant 10 GiB; launcher warns below 14 GiB (`launch_fresh_interval.py:7`, `:159-160`) | Start-only | Refuses to start (`require`) |
| C6 | Disk-headroom preflight | `H/run_prepared_restart.py:845-847`; `H/launch_monitored_interval.py:224-225`, `:373-374`; `H/launch_fresh_interval.py:135-136`; `H/run_fresh_interval.py:491-493` | Computed: 2 x store + staging + query quota (compact route uses `COMPACT_STORE_LIMITS`) | Start-only | Refuses to start |
| C7 | Logical memory ledger (`WorkBudget`, 16 GiB). Accounting only; not allocated RAM | `H/run_prepared_restart.py:46` `LOGICAL_BYTES`, `:833` `WorkBudget(LOGICAL_BYTES, max_predicate_work_units=1<<44)`; `S/resources.py:117` class, `:16` `MemoryLimitError`, admission `:266-340`; library default `:513` `DEFAULT_BUDGET` 256 MiB | Fixed 16 GiB in the runner; library default 256 MiB | In-run, every mandatory reservation | Mandatory: `MemoryLimitError("projected combined workspace exceeds memory budget")` and refusal counters. Optional (`try_reserve`, `:269`): returns False, nothing else changes |
| C8 | Measured admission: ledger follows real process memory plus a margin | `H/private_heat_process_meter_r1.py:82-84` `MARGIN` 256 MiB, `CHILD_MARGIN` 128 MiB, `CHILD_START` 384 MiB; `:327` raises `MemoryLimitError`; `:575` `open` | Fixed margins applied to a live reading | In-run | Charges the ledger; over budget raises `MemoryLimitError` |
| C9 | Optional parallel-worker admission (physical RAM reserve, budget fraction, predicate units) | `S/integration_parallel_selection.py:74-150` `InterfaceParallelPolicy`, `:122` `ram_reserve_bytes` = 2 GiB, `:715-760` `_resources` (`:736-745` memory test `available >= n*one + reserve`); batch admission `S/integration_parallel_dispatch.py:1274-1285` | Computed from live `psutil.virtual_memory().available`, ledger headroom and measured per-worker cost; reserve is a fixed default | Per batch decision, in-run | Fewer workers or serial fallback with a reason string; not a failure |
| C10 | Child worker guard (RSS and deadline), parent polls `resource.json` every 50 ms | `S/integration_parallel_dispatch.py:308-600` `_Child`, `:152`, `:163` `_resource_report`, `:359` | Computed per child from ledger share and profile (not re-derived) | In-run | Child stopped / refusal reported (exact branch unverified) |
| C11 | Heat-face worker pool sized from the ledger | `H/private_heat_functionals_parallel_r1.py` (worker count computed from available ledger; line not captured) | Computed | In-run | Fewer workers |
| C12 | CPU-slot guards: outer x inner threads at most logical CPUs; pool slots; executor byte charge | `S/execution.py:38-61` (`:57-59`), `:532-534`, `:595` | Computed from `os.cpu_count` | Construction and pool creation | `TectonicsError`; deferral of work when `charge > available_bytes` |
| C13 | Launcher: hook refusal; 60 s wait for RUNNING | `H/launch_fresh_interval.py:143-144`; `H/launch_monitored_interval.py:50` `HOOK_ENV`, `:418-420` | Fixed | Start | Refuse / abort launch |
| C14 | Old-route start floor 13 GiB and own guard constants (`START_AVAILABLE`) | `H/probe_heat_original_connected_r9.py:29-30`, `:153` `WorkBudget`; `H/private_heat_continuation_support_r3.py:277-283`, `:84-88` `disk_preflight`; comment at `H/fresh_interval_driver.py:33` ("r9's admission and work ceilings, verbatim") | Fixed 13 GiB | Start-only | Refuse |
| C15 | Strict-execution test | `S/reuse.py:646` `require_strict_execution`; imported `H/probe_heat_original_connected_r9.py:140`, called `:147` | Not a number | Start of the r9 flow | Raises if the runtime is not in strict mode (body not read) |

Guards that live only in a harness or launcher helper (not in `src/`): C3, C5, C6, C13, C14 and all of C1, C2, C4 (all `helpers/`). `src/` carries only C7, C9, C10, C12. Unwired harness modules with their own sampling: `H/live_memory_probe.py`, `H/ledger_fresh_interval.py`, `H/interface_worker_selection.py`, `measure_live_*` (none appears in the entry-point import closure).
Count: 15 rows (11 distinct guards in `helpers/`, 4 in `src/`).

## D. Diagnostics and instrumentation

"Default" means what happens in an ordinary generator run through `run_prepared_restart` / `run_fresh_interval` with no extra flag.

| # | Item | file:line | Default | Writes files? |
|---|---|---|---|---|
| D1 | Geometry observer on `sys.monitoring` (tool 3): per-stage ticks and timing | `H/private_heat_geometry_observer_r1.py:16`; entered at `H/prepared_interval_driver.py:233` (`with geometry_observer.observe(guard, stages, ticks, ...)`), `:56`, `:74`; `H/run_prepared_restart.py:466`, `:72` (module list); `H/run_fresh_interval.py:305` | **ON by default** (no flag found) | Into the interval record; no separate file found |
| D2 | Process meter records (also the C8 admission mechanism) | `H/private_heat_process_meter_r1.py:575`, `:741` ("what a driver writes into its receipt"); import `H/prepared_interval_driver.py:77` | **ON by default** (functional) | Into the receipt |
| D3 | Guard receipt and record (phase, ticks, status) | `H/private_heat_continuation_guard_r3.py:85` and receipt writes in `supervise` | **ON by default** | Yes (receipt, control, cancel files in the output folder) |
| D4 | Passive resource summary (peaks, latest sample) added by transformer | `H/resource_guard_patch.py:22`, `:36-60`; sampler `H/private_heat_resource_diagnostics_r1.py`; module list `H/run_prepared_restart.py:61`; checked by `H/launch_monitored_interval.py:523-525`, shown `:628` | **ON by default** in the monitored route; an error disables only the summary (`resource_guard_patch.py:9`) | Into the guard receipt only |
| D5 | Dev stage timing, `dev-stage-timing.jsonl` (cap 256 MiB, exclusive create) | `H/dev_stage_timing.py:20` `ENV`, `:21` `FILENAME`, `:19` `SCHEMA`, `:39` `Recorder`; gates `H/run_prepared_restart.py:151-155`, `H/launch_monitored_interval.py:327-359`, `H/run_fresh_interval.py:646-665` | Opt-in: `ATLAS_DEV_STAGE_TIMING=1`. Off otherwise, but any value other than unset/0/1 is refused (`:155`, `:331`) even when timing is off | Yes, when on |
| D6 | `dev_stage_timing_report` (reads D5 output) | `H/dev_stage_timing_report.py` | Standalone tool, not in the entry-point closure | Reads; output not checked |
| D7 | Focused artifact capture: runner sets `ATLAS_FOCUSED_ARTIFACT_DIR` | set at `H/run_prepared_restart.py:734-757` (`:749`) and `H/run_fresh_interval.py:427-443` (`:429`); consumed at `H/partition_routing_patch.py:407-419` `retain_compact_trace` | **Variable is set in a normal run.** Whether a trace file is written every run or only on failure is unverified (the calling hook is in an external historical control, `H/assemble_resumable.py:159-160`) | Possibly (unverified) |
| D8 | Parallel profile store `<query_directory>.parallel-profile.json` | path `H/prepared_interval_driver.py:111`, passed `:120` and `:207` (`InterfaceParallelPolicy(mode='auto', workers=2, profile_path=...)`); `S/integration_parallel_profile.py:480-514` `save` | **ON by default** in the prepared-interval driver | Yes (JSON beside the query directory) |
| D9 | Child worker `resource.json` (also read by the parent guard, C10) | `S/integration_parallel_dispatch.py:163-176` | ON whenever a worker child is launched | Yes (per-child folder, atomic replace) |
| D10 | Wall-batch timing `_observer` hook | `S/integration_differential_ale.py:359`, `:381`, `:408-412`, `:446-447` | Opt-in argument (`_observer=None`); whether the production driver passes one is unverified | Depends on the observer |
| D11 | Postcheck report (`write=True` default) | `H/launch_monitored_interval.py:479`, `:608` | ON in the postcheck call | Yes (what it writes was not read) |
| D12 | Source-proof receipt (`sources.verify()`, `production_acceptance=False`) | `H/run_prepared_restart.py:837-839` | ON by default | In the record |
| D13 | Failure capture on the old route | `H/private_heat_continuation_support_r3.py:299-325` | On failure only | Yes |
| D14 | Launcher warnings | `H/launch_fresh_interval.py:159-160` | ON | stdout only |
| D15 | Measurement tools: `measure_live_*`, `live_memory_probe`, `ledger_fresh_interval`, `interface_worker_selection`, `codec_measure`, `codec_tradeoff`, `codec_training` | `H/` (see E) | Off, not reached from entry points | Yes, when run by hand |

Count: 15 rows; 7 on by default (D1, D2, D3, D4, D8, D12, D14), 2 on whenever the feature runs (D9, D11), 1 environment variable set by default whose file output is unverified (D7), 1 opt-in (D5), 4 off / harness (D6, D10, D13, D15).
Flag for the decision: D1 is the only item that installs a `sys.monitoring` callback in a normal run; D3/D4/D8 write receipts by design.

## E. Test- and proof-only code

185 distinct files in `helpers/` (`composition.json` lists all 369 helpers, so the current composition manifest ships these 185 too); 0 in `src/`.

| Category | Count | Names (or pattern) |
|---|---|---|
| `test_*` | 155 | `test_a3_heat_fixes` ... `test_xmc_mesh_shared` (full list: every `H/test_*.py`) |
| `probe_*` | 2 | `probe_execution_identity`, `probe_heat_original_connected_r9` |
| `measure_*` | 7 | `measure_live_capacity`, `_capacity_overlaps`, `measure_live_mesh_capacity`, `measure_live_owner`, `_owner_guarded`, `measure_live_publication`, `measure_raw_sidecar` |
| `step7_*` | 2 | `step7_owner_heat_check`, `step7_same_call_heat_control` |
| `*_control*` | 1 (same file as the step7 control) | `step7_same_call_heat_control` |
| `codec_measure` / `codec_training` / `codec_tradeoff` | 3 | plus their tests `test_codec_measure`, `test_codec_training`, `test_codec_dictionaries` counted under `test_*` |
| `*ref_*` copies | 16 | `a2ref_compact_store`, `a3ref_heat_cold_patch`, `a3ref_heat_ledger_issuer_patch`, `a3ref_heat_ledger_tables`, `r1aref_record_views`, `w1ref_content_cache`, `w1ref_interval_catalog`, `w1ref_interval_store_set`, `w1ref_segment_store`, `w2ref_record_tables`, `w3ref_heat_ledger_tables`, `w3ref_mesh_tables`, `w3ref_partition_v2`, `w3ref_spatial_validation_patch`, `xmref_mesh_tables`, `xmref_spatial_records_patch` |
| Total distinct | 185 (155+2+7+2+3+16; the control is a step7 file) | |

### E-reach. Test/proof modules reachable from the production entry points

Entry points checked: `run_fresh_interval`, `run_prepared_restart`, `launch_fresh_interval`, `launch_monitored_interval`, `fresh_interval_driver`, `prepared_interval_driver`, `assemble_resumable`. Strict check = real import or quoted module name, not a docstring mention.

| From | To | file:line of the reference | Level | Notes |
|---|---|---|---|---|
| `run_fresh_interval` | `probe_heat_original_connected_r9` (in `FRESH_MODULES`) | `H/run_fresh_interval.py:72`; bound as `D=` at `:300` | 1 | A probe module is the production driver's source of the flow (`D.*`) |
| `run_prepared_restart` | `probe_heat_original_connected_r9` (in `REQUIRED_MODULES`) | `H/run_prepared_restart.py:70` | 1 | |
| `prepared_interval_driver` | `probe_heat_original_connected_r9 as D` | `H/prepared_interval_driver.py:72` | 1 | |
| `fresh_interval_driver` | `probe_heat_original_connected_r9` (named; docstring `:3`, comment `:33`) | `H/fresh_interval_driver.py:3`, `:33` | 1 | Docstring/comment only; its source is checked against r9 by `test_fresh_interval_driver` (`:19`), not imported |
| `assemble_resumable` | `probe_execution_identity.py` (copied into the build) | `H/assemble_resumable.py:119` (`COPIED_HELPERS`); output named at `:976` | 1 | Shipped file, not imported |
| `probe_heat_original_connected_r9` | `probe_heat_original_reopen_r4` (external historical-tests module) |  `H/probe_heat_original_connected_r9.py:129` | 2 | Not in `helpers/`; supplied by the external tests root |
| `probe_heat_original_connected_r9` | `test_i04_differential_force.check_initial_pressure_force`, `i04_differential_fixture`, `i04_differential_modes` (external) | `H/probe_heat_original_connected_r9.py:136-138` | 2 | Same external tests root |
| `run_fresh_interval` | `i04_differential_fixture`, `i04_differential_modes`, `test_i04_differential_force` (external) | `H/run_fresh_interval.py:75`, `:299`, `:303-304` | 1 | `check_initial_pressure_force` and `ACTUATED_CONTROL` are bound from them |
| `run_prepared_restart` / `prepared_interval_driver` | `i04_differential_modes` (external) | `H/run_prepared_restart.py:72`, `:808`; `H/prepared_interval_driver.py:86` | 1 | |
| `assemble_resumable` | external pins: `i04_differential_spatial_fixture`, `test_i04_spatial_workflow`, `i04_differential_joined_control`, `i04_differential_fixture` | `H/assemble_resumable.py:151-168` (`IMPORTED_REFERENCES` `:159-160`) | 1 | `*_control` module imported by the composition |
| `import unittest` in production modules | stdlib | `H/fresh_interval_driver.py:26`, `H/prepared_interval_driver.py:23`, `H/probe_heat_original_connected_r9.py:22` | 1-2 | Test framework is a runtime import |

Other E modules (all `test_*`, `measure_*`, `step7_*`, `*ref_*`, `codec_*`): no strict import found from any entry point, one or two levels deep. My first name-based closure flagged 15 more `test_*` names at levels 2-3 (e.g. `test_bounded_preseal`, `test_mesh_v3`); the strict check found none of them imported outside E files themselves. The only E-to-E links found: `H/step7_same_call_heat_control.py:68` imports `test_private_heat_bundle_extended`; `H/measure_live_mesh_capacity.py:192-193` imports `test_mesh_tables` and `test_partition_tables`. Neither of those sources is reached from an entry point.

Count: 185 E files in `helpers/`; 3 E modules reachable from production (`probe_heat_original_connected_r9` strictly imported, `probe_execution_identity` copied into the build, `test_fresh_interval_driver` mentioned only); 4 external historical-tests modules bound at import (`probe_heat_original_reopen_r4`, `test_i04_differential_force`, `i04_differential_modes`, `i04_differential_fixture`), plus 3 external pins in `assemble_resumable` (`test_i04_spatial_workflow`, `i04_differential_joined_control`, `i04_differential_spatial_fixture`).
Not verified: the external historical-tests root is not in this tree, so what those modules import and write was not read.
