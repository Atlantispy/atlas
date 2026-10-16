# Step 8: how to get representative simultaneous-live memory evidence

Read-only map. No files were edited and no measurement runs were made. I parsed the existing receipts with small scripts kept in my scratchpad.

Path prefixes used below:
- T = `C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10`
- R = `T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1`
- C = `R/compact-geometry-r1`
- I = `T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/runtime-integration-r1/runtime-src/atlas_tectonics`
- H = `T/fidelity-integration-20261005/heat-repair-20261007`

## 0. Findings that change the approach

1. **The per-category breakdown of the shared budget stops working before transport and heat run.** `WorkBudget` keeps at most 63 named categories per ledger. Anything after that is lumped into `other` (`I/resources.py:341`).
   - The W4 owner run `R/test-results/step8-owner-after-r3/result.json` (`store_statistics.shared_budget`) has exactly 64 categories, including `other`.
   - No `spatial-transport-*`, `heat-*` or `indexed-spatial-*` category exists in that run. Transport, heat and state-issue reservations all landed in `other`, whose peak is 3,143,499,538 B.
   - Categories that do stay readable:
     - the retained scope's own ledger, which is a separate child budget (`C/content_cache.py:375`);
     - `record-workspace`;
     - the heat process meter's side ledger.

2. **The W4 logical peak of 3,204,075,520 B is probably the heat meter's per-worker start allowance, not data.** This is an inference I have not verified.
   - The meter books `CHILD_START` = 384 MiB per worker until that worker's first reading, plus a 256 MiB margin (`H/private_heat_process_meter_r1.py:82-84`).
   - The default is 6 workers once at least 16 faces need reconstruction (`H/private_heat_functionals_parallel_r1.py:137,156`).
   - 6 × 384 MiB = 2,415,919,104 B. Add a parent reading of about 300.8 MB plus the 268 MB margin and the result is about 2.99 GB of the 3.14 GB `other` peak.
   - To verify, record `METER.returned()` / `last_report()` (`process_meter_r1.py:698-706`) and the parallel `report()` at the heat checkpoint.

3. **The IV1 high-water mark (pre-compact) is a re-read after publication, not the advance itself.** The r8 run (`H/heat-original-connected-20261013-r8.json`, `heat_forward_memory.returned_calls`) shows:

   | Metered scope (r8) | Private peak | OS peak commit | Booked |
   |---|---:|---:|---:|
   | `producer-re-read-after-publication` — `workflow.inspect()` inside `_meter.read_scope` (`H/private_heat_original_joined_r6.py:76-84`) | 8,568,279,040 B | 8,955,494,400 B | 13,735,194,240 B of 17,179,869,184 (old rule would have booked 24.63 GB) |
   | Forward call | 2,931,499,008 B | — | 5.68 GB |

   - The forward call's process peak was 4,001,533,952 B, of which workers took 1,452,441,600 B.
   - The later run r9 (`.guard.json`) was hard-stopped on the **1 GiB free-memory floor** with a sampled process-tree peak of 9,054,748,672 B, in the `actual-heat-endpoint-committed` phase.
   - This matches the plan's "Interval one reached 9 GB at commit" (`COMPACT_EVERYWHERE_PLAN.md:1078`).
   - **Consequence:** the post-publication re-read (cold restore) must be part of Step 8's overlap evidence.

4. **The 0.25 s guardian sampling can miss peaks.**
   - r8's sampled tree peak is 5.10 GB, but its meter saw an 8.50 GB working set (`working_set_peak_bytes`).
   - Use the OS lifetime counters at checkpoints: `peak_wset`, `peak_pagefile`, and above all the job's `PeakJobMemoryUsed`.
   - `PeakJobMemoryUsed` is an exact, simultaneous whole-tree peak commit. It is already in the guard's `EXTENDED_LIMITS` struct (`R/probes/structure-census-r3/guard/windows_workload_job.py:36-39`). It can be read with the same query-only handle that `verify_current_membership` uses (`:247-265`). No receipt records it today.

5. **`measure_live_owner.py` does not use `CollarWorkflow`.** It has no `_publish` ExitStack and no post-publication re-read. It runs with a 6 GiB budget, no guardian and garbage collection (GC) switched off. The production runner leaves GC on (`R/run_prepared_restart.py:1033`).

6. **Most of `measure_live_capacity.py` has never run.**
   - The mesh, other-family and heat branches have not executed, even in smoke mode, because smoke skips them (`measure_live_capacity.py:502-516`). Only the graph and numeric phases ran (`capacity-mechanics-r1`).
   - The authentic run refused at the first graph pack.

7. **The 10 GiB start gate cannot just be edited.** `GUARDS` is also compared for equality against the census's `guard_limits` (`measure_live_capacity.py:33-34,58`). The new start setting must be a separate constant (see section 5).

## 1. Live structures in `measure_live_owner.py` and how to measure each at its real overlap

Every measured structure below is released together at `:267` (the publication views at `:262-265`). So the true simultaneous overlap of everything is the `numeric-commit-and-seal` point (`:226`). Each stage's transient sits on top of whatever is live at that stage.

| Structure | Created | Released | Real overlap partners | Cheapest checkpoint-only measurement |
|---|---|---|---|---|
| Fixture `case` (collar, funding, owner source, initial bounds/stage/wall) and the shared budget | `:159` (budget created at `w4_owner_heat_child.py:151`) | with-exit after `:279` | everything | Baseline at `measured-start`. Record `len(stats['categories'])` there to show the category limit is already used up. |
| `initial_mesh` (legacy) | `:161` | `:279` | everything | Included in the baseline; also `exterior-thermal-mesh-retained` (a named category). |
| `PreparedSpatialOwner` plan/definition/initial state | `:162-164` | with-exit | everything | `spatial-owner-*` named categories; included in the baseline. |
| Retained scope, catalog, candidate, `ArrayStore` | `:165-173` | `:266,274` | everything | `scope.stats()` purposes (`retained:interval-owned` 15.8 MB) and `store-retained`. |
| `source`, `bounds`, `wall` (fresh, live construction) | `:178` | `:267` | through commit | Window `measured-start→fresh-bounds`; retained `record-tables`; `bounds._json.identity().canonical_bytes` plus packed column bytes (same method as `measure_live_capacity.backing_inventory`, `:223-236`). |
| Compact endpoint `mesh` | `:180` | `:267` | through commit | Retained `mesh-memory-columns/view/static-supports` and `mesh-row`. |
| `graph` (compact working record) | `:182` | `:267` | through commit | Window `fresh-mesh→closed-graph`; packed bytes from `graph._json`. |
| `PreparedSpatialTransport`: plan, sparse matrix, GMRES, rational lists (transient) | inside `owner.transport` (`I/integration_spatial_owner.py:624-626`) | at return | bounds, mesh, graph, fixture | Window `closed-graph→transport-solve`: Δ`peak_reserved_bytes`, Δ`other` peak, Δ`peak_pagefile`, Δ job peak. Its categories are lumped into `other`. |
| `step.result` (compact transport snapshot) | `:184` | `:267` | through commit | Retained `transport-result-field` (861,072 B at W4) and `-arrays`. |
| Collar transport stage | `:186-187` | `:267` | through commit | Window `transport-solve→collar-transport`. Currently it has no checkpoint of its own; add one. |
| `boundary_owner` and `boundary` dict | `:189-195` | `:267` | through commit | The Scratch reservation itself (65536+1024×faces). |
| Heat: `bind_owner_call` → forward kernel r13 (meter, 6 workers) → CAS save; `LiveJoinedHeat` keeps **result and call** | `:196-198` (`H/private_heat_joined_consumer_r6.py:129-177`) | `:267` | everything before it | Window into `heat-forward-and-checkpoint`. The meter report gives private, working-set and worker peaks plus calculated side-ledger category peaks; the parallel report gives worker counts. Read retained `heat-field*`. Read the guardian's per-phase `worker_process_count` and tree RSS. |
| `adopted`, `native` (native endpoint fields) | `:200-201` | `:267` | through commit | Split the current single checkpoint: add `heat-adopted` and `native-endpoint`. |
| `exterior`: finish with grouped account, state issue (§2b) and exchange repack (`exchange_record_patch.build_advance`, `C/exchange_record_patch.py:51`) | `:202` | `:267` | through commit | Window `native-endpoint→joined-finish`; `record-workspace` peak delta (a named category, so readable); `exterior.state._snapshot.nbytes` (`C/spatial_indexed_patch.py:159`). |
| `ExecutionContext` workers | `:196` | `:203` | heat stage | Guardian `worker_process_count`; job peak. |
| `saved`/`state`/`exchange`/`children`/`rows` | `:204-209` | `:262-265` | publication | Checkpoint after `:209` (currently missing). |
| `publish_records` bundle DAG (packs graph/transport/heat subtrees into new builder tables while the originals are still live) | `:210` (`C/spatial_records_patch.py:72-95`) | inside the call | everything | Window `→compact-record-publication`: `record-workspace` peak and the builder limit. |
| Mesh storage payload and numeric `put` | `:213-215` | `:223` | everything | Window plus `numeric.statistics()` (`peak_prepared_bytes`, staged bytes). |
| Component arrays dict and `put` | `:216-223` | `:223` | everything | Same as the row above. |
| Seal/promote | `:224-225` | — | everything | `numeric-commit-and-seal`: **this is the true simultaneous overlap.** |

**How to read the numbers without sampling inside scientific loops:**

1. **At every checkpoint**, record:
   - the full `budget.statistics()` (`categories`, `category_peaks`, `peak_reserved_bytes`);
   - `scope.stats()` (`retained`, `pinned`, `pending`, `evictable`, `non_cache`, purpose bytes and purpose peaks);
   - `psutil.Process().memory_info()`: `rss`, `private`, `peak_wset`, `peak_pagefile`;
   - `virtual_memory().available`;
   - the job's `PeakJobMemoryUsed`;
   - `guard.phase(name)`, which pulls the guardian's per-phase sampled tree RSS and private bytes.

   The existing `checkpoint()` (`:144-156`) records only reserved/peak totals and process RSS, private bytes and peak working set.

2. **Stage transients.** A peak counter that rose during a stage gives that stage's exact peak. If it did not rise, the stage peak is bounded by the earlier peak; report it as "≤ earlier peak", not as a value.

3. **Size of each structure at the real overlap: a "release ladder".** After the commit checkpoint, replace the single `del` at `:267` with ordered deletions, with a checkpoint after each:
   - publication views (`:262-265`);
   - `heat`;
   - `exterior`/`native`/`adopted`;
   - `transport`/`step`;
   - `graph`;
   - `mesh`;
   - `bounds`/`source`/`wall`.

   Each drop in reserved bytes, `other`, retained purposes and private bytes is the structure's exclusively owned share while everything else is live. Backing that is shared shows up on its last holder. With GC off, these deletions are refcount-immediate.

4. **What not to do.** Do not try to recover per-category detail by changing `resources.py` or installing a `budget._scope` hook. The meter already owns `_scope` (`process_meter_r1.py:137-145`). Changing `resources.py` would alter loaded-dependency identities that flow into the heat bindings, which risks changing result IDs.

## 2. The five omitted overlaps from `capacity-summary.json`

**(a) Actual solver, `PreparedSpatialTransport`, GMRES and rational workspace**
- **Code:**
  - `I/integration_spatial_transport.py:316-399`: plan reservation `spatial-transport-plan`, encoding and construction scratch, sparse matrix.
  - `:418-622`: step allowance at `:451-453`; per-field `8*nc*width` at `:482`; GMRES with `restart=min(40,nc)` at `:487-493`; exact refinement at `:522-550`; width lease at `:586`; result at `:616-619`.
  - Step 8 transform: `C/live_spatial_patch.py:600-624`.
  - For IV1-type owners with finite stocks, the solved graph is `finite_proposal._transport_inputs()` (`I/integration_spatial_owner.py:619-621`).
- **W4:** exercised, between `closed-graph` and `transport-solve`.
  - After-r3: the logical peak did not move (113,748,548 B); process peak went from 223,936,512 to 224,849,920 B.
  - At this scale it is negligible, and its category is lumped into `other`.
- **At IV1/IV2 scale:** this needs authentic data. Run the real `PreparedSpatialTransport(...).advance` in the capacity harness on authentic IV1 inputs:
  - the transport graph from the exchange's `finite_proposal` (105.9 MB);
  - `exact_input_stocks` (889 cells × 44 fields) and the `field_errors.allowed` bounds from `spatial-record:transport`;
  - require the authentic `result_id`, which also serves as an exact-output check.
- **If that composition is not feasible:** bound it by evaluating the pure capacity formulas `_json_encoding_capacity` (`:160`) and `_transport_plan_capacity` (`:241`) and the allowance at `:451` on the authentic records.
  - The GMRES Krylov basis is about (40+1)·889·8 B ≈ 0.29 MB at IV1. The rational lists dominate.

**(b) Fresh-state numeric projection overlapping its immutable copy**
- **Code:**
  - The joined finish (`H/private_heat_joined_consumer_r6.py:238-329`, as transformed by `C/live_spatial_patch.py:97-153`) keeps the `cells` list until `_issue` returns.
  - `C/spatial_indexed_patch.py:297-335`: packs the cells with the record codec while the list is still live (`:303-313`); builds `fields` numpy arrays (`:319-326`); scratch `65536+3·width+32·count·(names+1)` (`:316-317`); `tobytes` immutable copies (`:224`) while `fields` are still live.
- **W4:** exercised, in the `joined-finish` window. Its categories are lumped into `other`; use the stage window, retained purposes and `snapshot.nbytes`.
- **Analytic bound:**
  - IV1: count 847, 44 names, so `fields` ≈ 847×45×8 ≈ 0.30 MB, doubled by the copy, plus scratch and the cells list (state record 3,024,146 B canonical).
  - IV2 at 3.8–5× is still well under 100 MB.

**(c) Restore bytearray overlapping heat fields**
- **Code:** `C/private_heat_snapshot_store_r4.py:241-261`: `bytearray(count)` charged as `heat-field-restore`, then the `own_field` immutable copy, plus all completed fields, plus 64 KiB and 128 KiB stream owners.
- **Narrow bound:** IV1 native fields are 34,200 B in total (census `heat.native_field_bytes`). At IV2 that is about 0.2 MB or less, so this narrow overlap does not matter in practice.
- **The relevant restore is wider:** the whole committed endpoint re-read (`CollarWorkflow.inspect/_refresh` → `spatial_records_patch.restore_records`/`open_records` `:145-176,270-309` → heat `open`). That re-read was the IV1 peak (Finding 3).
- **W4:** not on the current path; `recover_diagnostics` opens the heat only after the measured region (`:303-311`). It can be exercised: add a measured `post-publication-reread` phase that, before releasing anything:
  - reopens the sealed catalog;
  - opens the record refs with `RECORDS.open_records(stores, refs)`;
  - opens the heat checkpoint with `HEAT_STORE.open(stores, receipt, ...)`.
- **Capacity harness:** add `heat_store.open` of the saved heat receipts (`measure_live_capacity.py:325-330`) and `open_records` of the record blocks while all the blocks are retained.

**(d) 8,064 distinct successor partition supports**
- **Code:**
  - Real producer: `prepare_interval_partition` via `live_partition_patch` and `SupportBatch`.
  - Fixture: `C/test_live_partition.py:67-113`. Its cap of 2016 is at `:78`; IDs are distinct per index (`:97-98`).
- **W4:** not applicable. W4 is common-rigid and has no differential partition. Only the capacity harness can cover it.
- **Approach:** add a new fixture function in a new file (leave the test file's cap alone). It builds 8,064 rows with a distinct salt, alongside the 2016 parent. Record:
  - the builder child peak per build;
  - `retained:partition-support-index`;
  - packed bytes;
  - wall time (2016 rows took 48.5 s in authentic-r1, so about 3–4 min if linear).
- **Caveat:** the template repeats rational tokens, so it understates the builder's token load. The authentic partition pack (`C/measure_live_mesh_capacity.py:111-118`; 114,107,489 B and 4.89 M strings) has never run. It is likely to hit the same 256 MiB builder limit as the graph, which refused after 16,280,115 of 104,701,198 B. So this item depends on the builder repair.

**(e) Full workflow owner ExitStack and certification producer**
- **Code:**
  - `I/integration_regional_workflow.py:1513-1580`: payload at `:1553`; ExitStack at `:1555`; certification at `:1557`, differential geometry at `:1561`, partition at `:1564` (differential route only); spatial records at `:1568`; `store.put` at `:1571`.
  - `C/spatial_records_patch.py:229-267` (records) and `:311-327`: certification `Scratch(65536+10·width)` plus `publish_records`.
- **W4 (rigid route):** only the spatial-records part and the payload put apply. `measure_live_owner` bypasses the workflow entirely.
  - A precedent for driving the workflow exists: `w4_owner_heat_child.run_indexed:498-530`.
  - That precedent uses a native `ArrayStore`. The compact records path requires a store with a scope (`spatial_records_patch.py:41-45`).
  - Whether the `IntervalStoreSet` candidate can serve as `CollarWorkflow`'s store is unverified. That wiring is Step 9 runner work.
- **Certification:** differential-only and unreachable on W4. `test_i04_differential_certification.py:1-5` points to the joined differential control as the only positive publication path. It needs authentic IV1 data.
  - Bound: certification canonical size 587,767 B × growth, plus the 10×width scratch.
  - `retain_other_records` (`measure_live_capacity.py:270-272`) already covers the retained compact form; it does not cover the producer's decoded solution/proposal JSON. State that gap explicitly.

## 3. What an IV2-shape forecast needs, and what already exists

**Model.**

Tree peak at stage *s* = *B* + *W_s* + Σ over families *f* live at *s* of *g_f*·*R_f*(IV1) + *T_s*(IV2)

- *B*: process baseline.
- *W_s*: worker processes at stage *s*.
- *R_f*: compact retained bytes per family attributable to the process.
- *T_s*: stage transient.
- *g*: growth factor, 3.8–5 (a scenario, not a measurement).

Report a low/high range and the distance to each guard:

| Guard | Distance |
|---|---|
| Tree RSS | 12 GiB − peak |
| Free-memory floor | available at start − *k*·peak − 1 GiB, with *k* measured. *k* ≈ 1.27 from the r1 continuation (free RAM fell 9.0 GB for a 7.06 GB tree). The floor binds before 12 GiB on this machine. |
| Logical budget | 16 GiB − ledger peak, including the meter's 256 MiB margin and 6×384 MiB worker start allowance |
| Retained scope | 256 MiB − scope peak |
| Builder child | 256 MiB − largest single build |

| Component | Evidence that exists (cite) | Status |
|---|---|---|
| IV1 per-family logical sizes | Census `R/probes/structure-census-r3/structure-census.json`: mesh 190,778,119; heat 356,504,170; partition 114,107,489; exchange 106,131,490 (`finite_proposal` 105.9 MB); graph 104,701,198 (receipts 87.5 MB); transport 6,422,727; state 3,105,816; certification 587,767 B. IV1 has 855 cells / 8,569 faces. | Have. ×3.8–5 is about 3.35–4.41 GB logical in total; that is not RAM. |
| IV1 stage peaks (pre-compact, metered heat) | r8 `stage_memory` and `heat_forward_memory` (figures in Finding 3; e.g. heat-native-projection stage: ledger 10.41 GB); r9 guard: 9.05 GB sampled tree, floor trip | Have. These are the legacy anchors each compact stage must replace. |
| Baseline *B* | W4 `measured-start` RSS 208,695,296 B; capacity start 123 MB; r8 192 MB | Have |
| Workers *W* | r8 forward workers peak 1,452,441,600 B (6 workers) | Have at IV1 |
| Partition construction | `R/probes/wp14-partition/handoff.json`: 2016 rows; tracked peak 57,412,041 B; peak working set 145,895,424 B; peak commit 1,124,225,024 B; packed 983,735 B | Synthetic only; 8,064 rows and the authentic partition are missing |
| Mesh | `R/probes/step8/mesh-collar-handoff.json`: 216 cells, retained output 719,335 B; Step 5 large reopen retained 31,601,894 B (`step5-mesh-partition.json`) | Authentic IV1 compact blocks missing |
| Graph | `capacity-authentic-r1`: builder refused at 268,431,680 B; decode charge 2,081,838,392 B | **Blocking**: needs the builder repair |
| Heat ledger | Step 7: 616 MB logical; peak booked 74.54 MiB while writing, 30.09 MiB when cold (`step7-heat-ledger.json`) | Synthetic data with high sharing; IV1 compact publication and re-read missing |
| Heat forward at IV1 | r8 meter: process 4.00 GB, booked 5.68 GB | Have (the numerical kernel is the same) |
| Post-publication re-read at IV1 (compact path) | None | **Must measure**: this is the IV1 peak driver |
| Transport at IV1 | r8 aggregate stage only | Missing (see §2a) |
| W4 stage pattern | after-r3 log and result: process peak 278,327,296 B; ledger peak 3,204,075,520 B; retained peak 32,600,342 B; booked at commit 64,681,252 B | Have, but categories are lumped together and there was no guardian |

**Uncertainties to state:**
- growth *g* and how rational widths grow at IV2;
- how heat scales (faces × width);
- r8's sampled 5.10 GB versus its meter's 8.50 GB working set;
- machine load (free-floor binding);
- GC on versus off;
- sharing that has not been measured.

## 4. The guardian and running `measure_live_owner.py` under it

**How it works today.**
- `measure_live_capacity.guard_files()` (`:108-116`) checks the three guard files against `resource_guard_patch` pins (`R/resource_guard_patch.py:16-22`).
- `launch()` (`:119-145`) copies them to `output/guard` and runs:
  `python -B guard/private_heat_continuation_guard_r3.py --launch --output OUT.json -- python -B <driver> --workload OUT`
  - environment: `PYTHONPATH`/`PYTHONHOME` removed, `PYTHONDONTWRITEBYTECODE` set, BLAS/OMP threads = 1;
  - working directory is the output directory.
- `supervise()` (`guard_r3:224-430`):
  - creates a kill-on-close Windows job with no breakaway (`windows_workload_job.py:137-151`) and launches the workload suspended inside it;
  - every 0.25 s it reads the driver's control file and refuses looser limits (`:286-314`);
  - samples job RSS, private bytes and OS peaks (`:320-342`);
  - triggers on tree RSS > 12 GiB, available < 1 GiB, or a cancel file (`:343-348`);
  - hard-stops after a 5 s grace (`:388-401`).
- On the driver side, `ContinuationGuard(output, record, save)` (`:97-139`):
  - needs the job context environment variable with the *exact* output path (`:110-117`) and checks job membership;
  - `phase()` writes the phase name and copies the guardian's receipt, `resources` and `budget.statistics()` into the record (`:141-184`);
  - `close()` must reach `STOPPED` (`:196-206`).
- **The guardian enforces only 12 GiB and 1 GiB.** The other three limits are enforced in-process:

  | Limit | Where it lives |
  |---|---|
  | 16 GiB logical | `WorkBudget(16<<30)` (capacity harness `:379`) |
  | 256 MiB retained | `RETAINED_BYTES` (asserted at `:413`) |
  | 256 MiB builder | `record_tables.MAX_BUILD_BYTES` (`C/record_tables.py:29,118`) |

**What `measure_live_owner.py` needs to run under the same guardian and limits:**
1. **One process.** Replace the parent→`--child` subprocess (`:505-518`) with `--launch`/`--workload` modes. A child process would count as a worker, and its phases would never reach the guard.
2. **A persistent layout.** Today the layout lives in a TemporaryDirectory (`:510`). Write it under the output directory (or `T/_t`) before launch, record its file hashes in `prepare.json`, and have the workload re-verify them before importing (as the capacity harness does at `:341`).
3. **The 16 GiB logical limit.** Inject `BUDGET_BYTES = 16<<30` through the fixture namespace (`:74`, replacing the current 6 GiB at `:30`). Assert `budget.max_bytes`, `scope.retained_budget.max_bytes == 256<<20` and `MAX_BUILD_BYTES == 256<<20`.
4. **Guard wiring.** Reuse `guard_files()` and the same command line, environment and pins. Create `ContinuationGuard` before the fixture or any workers exist; set `guard.budget = case['budget']`; call `guard.phase()` at every checkpoint.
5. **Cooperative abort.** Pass `cancel` (built on `guard.check`, throttled to 0.25 s) into `owner.transport/heat/finish`, the collar calls and `publish_records`. All of these accept it. Without it, an abort ends in the job being killed and `_terminal_main` marking the receipt failed.
6. **Output location.** Use a fresh directory under `R/probes/step8/` (location rule `:121-122`); keep `TMP`/`TEMP` in `T/_t`.
7. **Diagnostics.** Run the diagnostic export as its own guarded phase after the measured end. Run the release ladder and cleanup assertions before `guard.close()`.

## 5. Concrete plan for the extended harness

**New files** (none of these is on the other chat's ownership list):

- **`C/live_memory_probe.py`** — a `Probe(budget, scope, guard, job_name)` class:
  - `.stage(name, **handles)` records `budget.statistics()`, `scope.stats()`, `memory_info` (`rss`, `private`, `peak_wset`, `peak_pagefile`), `available`, and `PeakJobMemoryUsed` (query-only handle, same pattern as `windows_workload_job.py:247-265`), then calls `guard.phase`;
  - computes stage deltas: Δpeak, Δcategory peaks, Δ`other`, and the new-peak flags;
  - `.heat_report()` reads `METER.returned()/last_report()` and the parallel `report()`;
  - `.sizes(**handles)` reads object-owned byte counts (packed columns, `snapshot.nbytes`, canonical identity) without walking any data;
  - it takes **no budget reservation**, because a new category would only land in `other`;
  - it follows the field names of `R/dev_stage_timing.py:111-123` for WP19 parity.
- **`C/measure_live_owner_guarded.py`** — `launch()`, `workload()`, and `fixtures(budget_bytes)` (same as `:57-76` but with a parameter). It reuses `layout`, `endpoint_mesh`, `diagnostic_record` and `digest_arrays` by import.
  - Checkpoints: `fixture-ready`, `measured-start`, `fresh-bounds`, `fresh-mesh`, `closed-graph`, `transport-solve`, `collar-transport`, `heat-forward-and-checkpoint` (plus the meter/parallel report), `heat-adopted`, `native-endpoint`, `joined-finish`, `execution-closed`, `record-views`, `compact-record-publication`, `mesh-numeric-put`, `component-numeric-put`, `seal-promote` (the overlap point), `post-publication-reread` (§2c), then `release-*` ×7 (the ladder), then separately `diagnostic-export` and `cleanup-verified` (retained = 0, reserved back to baseline).
  - GC: record the choice. I recommend leaving it enabled, as in production, and logging `gc.get_stats()` deltas per checkpoint. GC-free release is already covered by after-r3's GC-off cleanup PASS and the focused tests.
- **`C/live_capacity_fixtures.py`** — `successor_partition_fixture(scope, count=8064, salt=...)`.
- **`C/forecast_live_iv2.py`** — a read-only aggregator. It reads the census, r8/r9, the guarded W4 result, capacity results and component receipts, and writes the §3 model with ranges and the distance to each guard.
- **`C/test_live_memory_probe.py`** — focused mechanics: field completeness; job-peak read refused outside a job; delta logic; start-gate validation.

**Changes to `C/measure_live_capacity.py`:**
- **Start gate.** Keep `GUARDS` unchanged for the census equality check. Add `STEP8_TEST_START_GATE` = max(4 GiB, previous measured peak of this harness + 1 GiB floor + margin). The previous authentic-r1 peak is 779,063,296 B. Record in `prepare.json`: the value, its basis, the source receipt, "authority: Michael 15 Oct, Step 8 tests only", and the unchanged real-run gate (10 GiB at `R/launch_monitored_interval.py:43` and `R/run_prepared_restart.py:46`). Check `available >= STEP8_TEST_START_GATE` at `:125-126`.
- **Probe.** Use the probe in `phase()` (`:393-403`) so the job peak and stage deltas are recorded.
- **Cover the omitted overlaps:**
  - (d) the 8,064-row successor partition beside the parent;
  - (a) authentic `PreparedSpatialTransport` advance with a `result_id` match, or the formula bound;
  - (c) `heat_store.open` and `open_records` over the retained blocks;
  - (e) certification decode held during the pack (already true via `_read_record`), with the gap to the real producer stated;
  - (b) analytic bound from the census, since the W4 run measures it directly.
- **Smoke first.** Add a smoke path for `retain_other_records` and `retain_mesh_blocks`. Neither has run, even in smoke mode.

**Order and run budget:**
1. One W4 guarded run: about 2–3 min, start gate 4 GiB, output `R/probes/step8/owner-guarded-r1`. Add a matched before/after pair only if time or RAM improvements are to be reported (16 GiB versus 6 GiB can change whether optional caches are admitted).
2. Smoke of the extended capacity harness.
3. The heavy capacity run, only after the builder repair.
4. Run `forecast_live_iv2.py`.
5. Write the results into a new dated field of `R/test-results/step8-live-memory.json` and the plan's §4 table.

The same-input heat-parity test remains a separate prerequisite: the guarded W4 run is not evidence of exact-output acceptance.