# Release-mode check policy for the generator composition (composed-r2)

Thread "Release-mode check policy", 16 Oct 2026. Answers Michael's request: decide which checks stay on in the
packaged **release** build and which run only in **strict** (debug, checkout, tests, scientific evidence).
This is a decision and design deliverable. Nothing in source-bound code was changed.

Paths: `S/` = `R/composed-r2/src/atlas_tectonics/`, `H/` = `R/composed-r2/helpers/`,
R = `T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1`.
Supporting inventories: `T/rm/inv-A.md` (scientific checks), `T/rm/inv-CDE.md` (resource, diagnostics,
test-only). Timings: existing recorded measurements only (§4). Two new probes (`T/rm/time_verify.py`,
`T/rm/time_store_pattern.py`) were written but withdrawn unrun under the coordinator's 14:37 PAUSE. They are not
needed for the decisions.
Existing policy: `docs/CODING_SAFETY.md` §4 "Strict checkout and packaged release execution";
`tectonics/docs/INTEGRATION_PLAN.md` I11.5 and I12.2.

## 0. Headline

1. **Class A (scientific) stays on in every build, unchanged.** That covers about 10,955 `raise` sites, plus the exact
   predicates, certificates, conservation, convergence and the 256-step `MAX_STEPS` ceiling. There is no `__debug__`
   switch and no `assert` in `S/`. Two bare scientific `assert`s in `H/private_heat_finish_arithmetic_r1.py:68-69`
   would vanish under `python -O`, so they must become explicit raises, and release must refuse `-O`.
2. **The release switch only shares the package identity guard (class B).** Today it makes
   `ExecutionContext.verify()` a no-op (`S/reuse.py:882-886`) and moves full checks to store operations through
   `release_boundary()` (`S/reuse.py:651-665`).
3. **As coded, release would not speed this composition up. It would slow it down.**
   - The interval drivers refuse release outright (`require_strict_execution()` at `H/run_fresh_interval.py:469`,
     `H/run_prepared_restart.py:810`, the two reopen drivers, and worker `S/integration_parallel_dispatch.py:182`).
   - The parallel selector falls back to serial in release (`S/integration_parallel_selection.py:576-578`), which
     loses the measured 25-36 % parallel gain.
   - Release runs a full boundary on every ArrayStore get, put start and pre-commit. Each boundary covers both
     captured backends (reference and scipy, `H/fresh_interval_driver.py:87-88`) and re-reads every source byte,
     because release takes no Windows source handles (`S/reuse.py:827`).
   - PROJECTED from recorded part timings (§4):
     - A release boundary costs about 90 ms: 2 backends × 45.3 ms, the measured handle-less `verify_boundary` on
       this composition.
     - A strict `verify()` costs 12.6 ms.
     - So a cold admission would take about 262 s of identity checks in release against about 49 s in strict:
       roughly 210 s *slower*.
     - Seeded hits would take about 174 s against 24 s.
     - The same arithmetic reproduces the measured RC1 → r2 change: 3,876 × 32.7 ms = 127 s predicted against 122 s
       measured.
4. **Recommended policy (§3).** Release keeps full checks at:
   - first capture;
   - store open and reopen;
   - publication (interval seal, promote, adopt, checkpoint, project save, backup and export);
   - cross-process import (worker start and result acceptance).
   It shares the inner repeats: per-record get and put inside an already verified open session, `verify()`, and
   publication-check repeats. In a fixed installed build this is safe: nothing can change code between two boundaries
   without being caught at the next one, and the next one always comes before anything is published.
5. **The size of the prize is modest on this composition.**
   - PROJECTED saving of the recommended release against strict:
     - about 30-55 s on a fresh interval, of which 24-49 s is in initial_metrics (8-17 % of its measured 285 s);
     - about 2-6 s on a continuation interval, which doesn't run initial_metrics.
   - Both are well under 2 % of a whole interval.
   - The guard's 31 % share of admission (S7) was the pre-handles, cold, 4-verifies-per-component case.
     - Source handles have since cut each verify from 45.3 to 12.6 ms (M).
     - Item 7's seeded hits make 2 verifies instead of 4.
   - In heat, 72 % of the issuer guard is data-identity hashing, which stays on in every mode.
   - **Release is about shipping a correct end-user build, not a large speed lever.** It still qualifies under the
     owner's marginal-gains rule.
   - Where checks dominate, release does pay off: the recorded 5 Oct prototype test gave −54 % to 11× on short
     desktop jobs with byte-identical outputs (§4 row 5).
6. **Six decisions for Michael (§5).** All recommendations keep every class-A check and never raise a resource guard.

## 1. What already exists

| Piece | Where | What it does |
|---|---|---|
| Release gate | `S/reuse.py:598-635` `_packaged_mode`; marker written by `desktop/build.py:85-89` | Release needs `tectonics/.desktop-runtime.json` = `{"schema":"atlas.desktop-runtime.v1","identity_mode":"release"}`, the payload's own `resources/python` interpreter, an allow-listed `tools/` entry (`new_world*.py`, `tectonics_job.py`, `read/view_tectonics.py`, `w12_job_worker.py`), `Atlas.exe`, and no links. Anything else is `strict`. No environment variable can enable it. |
| Mode cache | `S/reuse.py:595`, `638-643` | Decided once per process under a lock. |
| Evidence refusal | `S/reuse.py:646-648` `require_strict_execution` (8 callers) | Verification and evidence commands refuse release. |
| Shared capture | `S/reuse.py:812-823` | Release captures each backend once per process and later contexts copy that snapshot. |
| Inner verify | `S/reuse.py:882-886` | Strict runs the full `verify_boundary`. Release only checks that the context isn't closed. |
| Full check | `S/reuse.py:888-919` `verify_boundary` | Same in both modes: the source part (handle hold in strict on Windows, all bytes re-read otherwise) plus the live callable/default/constant walk `_verify_callable_inventory` (`S/reuse.py:414-502`). |
| Release boundary | `S/reuse.py:651-665` | Release only: runs `verify_boundary` on every captured backend. Called from ArrayStore open `S/storage.py:279`, every owning read scope `:471` (get `:1136`, metadata `:1085`, contains `:1070`, reference reads `:831/884/909/923`), put start `:803`, pre-COMMIT `:1047`, backup `:1177/1185`, and `H/historical_admission.py:332`. |
| Cache flights | `S/reuse.py:1341` | In-process result sharing validates with `verify_boundary` in both modes. |
| Mode provenance | `S/storage.py:716, 955-956`; `H/compact_restart_store.py:305-348, 463-483`; `H/integration_restart_catalog.py:93`; `H/workflow_transfer.py:229` | Scientific identity excludes the mode. The mode is recorded separately, and old manifests imply strict. |
| Unit tests | `tectonics/tests/test_optimisation_runtime.py:60, 73, 98-` | Cover: the environment can't enable release, layout admission, mode-independent identity, producer policy surviving reopen. |

## 2. Decision table

Cost key:
- **M** = MEASURED (source named).
- **P** = PROJECTED (method named).
- S7 shares are cProfile shares from `T/so/s7/S7-REPORT.md`. cProfile inflates Python code.

Recommendation key:
- **ON** = on in both builds.
- **STRICT** = strict only.
- **SHARE** = release shares it between boundaries.
- **NO-SHIP** = not in the release payload.

### A. Scientific checks (detail: `T/rm/inv-A.md`)

| # | Family | Representative sites | Protects | Cost | Rec. | Risk if off |
|---|---|---|---|---|---|---|
| A1 | Exact geometry predicates and exact arithmetic: 873 Fraction lines, 413 gmpy2, 205 orient, filtered predicates with exact fallback | `S/integration_filtered_predicates.py`, `S/integration_exact_gmp.py:109-110, 386-388`, `S/exact_arithmetic.py:180-219` | Topology and sign decisions are exact | This is the computation itself. Pressure stages are dominated by exact rational arithmetic (M, S7 finding 2). The binary64 filters are a speed route only. | **ON** | Wrong topology or non-reproducible geometry |
| A2 | Certificates and error/volume bounds: 1,077 `certif` lines, 274 raises | `S/integration_dual_geometry.py:741-765` (bounds re-derived on every cache hit) | A reported value has a proven bound | Part of the computation | **ON** | Unbounded error published |
| A3 | Conservation and balance: 258 `conserv`, 491 `fsum`, 284 raises | see inv-A §3 | Mass, heat and volume closure | Part of the computation | **ON** | Silent drift in mass or heat |
| A4 | Convergence, iteration limits and the 256-step ceiling | `S/integration_state.py:55` `MAX_STEPS` (17 uses); `S/regional_workflow.py:35` | Solves converge or refuse, and runs stay bounded | Part of the computation | **ON**, never raised | Non-converged fields accepted |
| A5 | Physical-validity refusals: about 1,318 raises on finite, positive and range checks | top 25 files in inv-A §5 | Inputs and states are physically admissible | Negligible per call | **ON** | Non-physical states propagate |
| A6 | Cache-hit meaning checks | `S/integration_dual_geometry.py:741-765`; `S/extension_workflow.py:171-173`; `S/integration_feedback.py:704-715` (`verified=` token) | A reused result means the same query at the same precision | Cheap relative to recompute | **ON** | A stale or foreign result is reused |
| A7 | Two bare `assert`s on a 2^-64 bracket and a predicate | `H/private_heat_finish_arithmetic_r1.py:68-69` | Rounding bracket in the heat finish | Negligible | **ON as explicit raises.** Release must refuse `-O`/`PYTHONOPTIMIZE`. Today only `H/launch_monitored_interval.py:51` refuses it. | Under `-O` the check silently disappears |
| A8 | Pressure-force check bound from an external test module | `test_i04_differential_force.check_initial_pressure_force`, bound at `H/run_fresh_interval.py:299-304` and `H/probe_heat_original_connected_r9.py:136-138` | Initial pressure-force acceptance | Small | **ON.** Move it into a shipped production module (see E2). | The check would be lost when test code is stripped |

### B. Integrity and identity checks

| # | Check | Where | Protects | Cost | Strict | Release (recommended) |
|---|---|---|---|---|---|---|
| B1 | First capture per backend: import all modules, runtime binary identities, callable inventory, all source bytes, code digests | `S/reuse.py:812-871`, `_runtime_record:505-592` | Results, caches and checkpoints are tied to the exact code and runtime | M: 0.63 s per context (5 Oct, on 30a79e6, idle machine); M under cProfile: 7 contexts 3.2-3.3 s (S7) | Every context | **ON**, once per backend per process (already coded) |
| B2 | `ExecutionContext.verify()` inner calls: 169 sites in 52 files | e.g. admission `S/integration_dual_geometry.py:720, 733, 734, 770` | In-memory code didn't change during a call | M: 12.6 ms per call unprofiled on composed r2 with source handles; 45.3 ms on RC1 without them (§4 row 1). S7 (M): 3,876 calls = 31 % of cold admission, 54+45 calls = 1-3 % of pressure. | **ON** | **SHARE** (already a no-op in release) |
| B3 | Direct `verify_boundary()` calls: 34 sites in 21 files | heat issuer `H/private_heat_native_issuer_r13.py:282, 336, 487`; `H/fresh_interval_driver.py:100-101`; `H/historical_admission.py:736, 740`; `H/historical_export.py:316, 332`; `H/prepared_interval_driver.py:242`; `S/integration_private_heat_cold.py:217`; `S/integration_regional_workflow.py:1576` | Same as B2, at a named point | S7 (M): about 28 % of the issuer's 1.3-1.8 s per call | **ON** | Keep at publication, export, reopen and restore. **SHARE** the issue-time calls inside one process (`r13:282, 336`). |
| B4 | `release_boundary()` on ArrayStore operations | `S/storage.py:279, 471, 803, 1047, 1177, 1185` | Release's replacement for B2 | P: about 90 ms per call, which is 2 backends × the measured 45.3 ms handle-less boundary | No-op | **ON** at open, backup and export, and before the COMMIT that *publishes*. **SHARE** per-record read scopes and put-start inside a verified open session (decision 1). |
| B5 | Windows source hold (share-deny-write handles) | `S/reuse.py:708-795`; taken `:827`; checked `:893-898` | No source byte can change under a live context | M: the boundary costs 12.6 ms with handles and 45.3 ms with the full re-read, so the re-read costs about 33 ms per backend per boundary | **ON** | Today release takes none and re-reads every source byte at each boundary. Recommended: hold for the process lifetime from first capture (decision 2). |
| B6 | Store byte authentication (chunk/manifest SHA, attested reads) | `S/storage.py` `_chunk:655`, `_manifest:700`, `_read_scope:458-500` | Stored bytes are the bytes written | Part of each read | **ON** | **ON** (data integrity, not code identity) |
| B7 | Snapshot, mesh and origin identity hashing | `H/private_heat_native_issuer_r13.py:185-200` `_snapshot_identity` and callers | A heat call is bound to the exact snapshot it was issued for | S7 (M): 72 % of the issuer guard; grows with mesh size | **ON** | **ON** (survives any source policy, S7 finding 3) |
| B8 | Helper-private pins: issuer `_verify_implementation`, own-file SHA, binding `source_hash`; worker `verify_sources`/`_PINS` | `H/private_heat_native_issuer_r13.py:173-182, 487-492`; `H/private_heat_interval_inventory_r4.py:47`; `H/private_heat_certification_resources_r1.py:81`; `H/private_heat_finish_arithmetic_r1.py:154` | Checkout helpers live outside the package's source membership, so B1 doesn't cover them | S7 (M): workers 1.06 % (4,282 calls × 1.3 ms); issuer share inside B3 | **ON** | Once helpers ship inside the package, B1/B4 cover them. Then check at the boundary and **SHARE** the inner repeats (decision 4). |
| B9 | Cache flight validation | `S/reuse.py:1341` | A coalesced in-process result was produced by verified code | Rare | **ON** | **SHARE** (stays in the process; the producer's own put is a boundary) |
| B10 | Release gate and mode cache | `S/reuse.py:595-643` | Release only in a genuine packaged payload | Once per process | n/a | **ON** |
| B11 | Evidence refusal (`require_strict_execution`) and the parallel strict gate | `S/reuse.py:646`; 8 callers (§1); `S/integration_parallel_selection.py:576-578` | Evidence is never produced in release | Once | **ON** | **ON** for verification and evidence commands. The production interval route and its workers need a release-capable path (decision 3). |
| B12 | Mode provenance | §1 row "Mode provenance" | Producer policy is recorded but excluded from scientific identity | Negligible | **ON** | **ON** |
| B13 | **Gap: no identity boundary at compact-store seal and promote** | `H/compact_restart_store.py:616` `seal_and_promote`, `:631` `seal_pending`; `adopt_and_promote` in the interval store set | Publication of an interval | none today | Covered only if a driver verifies just before; check this when implementing | **Add a full boundary** here. This is release's main publication point. |

### C. Resource guards (detail: `T/rm/inv-CDE.md` §C)

All of these protect the user's machine, and **all stay on in release**. The only question is how they size
themselves. Never above today's values unless Michael gives a number with evidence.

| # | Guard | Where | Today | Release recommendation |
|---|---|---|---|---|
| C1 | In-run tree RSS cap, sampled every 0.25 s | `H/private_heat_continuation_guard_r3.py:30, 41-47, 224, 346` | Fixed 12 GiB; callers can only tighten it | **ON.** Cap = min(12 GiB, physical RAM − 1 GiB floor − OS reserve), measured at start. |
| C2 | In-run free-memory floor | same file `:31, 348`; `H/run_prepared_restart.py:46` | Fixed 1 GiB; may only rise | **ON**, unchanged |
| C3 | Cancel file and user cancel | same file `:172, 344`; `H/launch_monitored_interval.py:646-684` | n/a | **ON** |
| C4 | Windows job object (kill-on-close, no breakaway) | `H/windows_workload_job.py:18-19, 128-151, 247-259` | n/a | **ON** |
| C5 | Start gate | `H/run_prepared_restart.py:46, 831-832, 1100`; `H/launch_monitored_interval.py:43-46`; `H/run_fresh_interval.py:478-493`; `H/launch_fresh_interval.py:129-136` | Fixed 10 GiB | **ON, sized by prediction:** predicted peak × 1.2 + 1 GiB floor (the runq rule), predicted from a per-route peak table measured in strict benchmarks and shipped with the build. Refuse with the needed and free figures. |
| C6 | Disk headroom preflight | `H/run_prepared_restart.py:845-847` and the launchers | Computed | **ON** |
| C7 | Logical ledger (`WorkBudget`) | `H/run_prepared_restart.py:46, 833`; `S/resources.py:117, 266-340`; library default 256 MiB `:513` | 16 GiB logical | **ON.** Keep it as the accounting ledger. The physical guards are C1, C2, C5 and C8. |
| C8 | Measured admission (process meter plus margins) | `H/private_heat_process_meter_r1.py:82-84, 327, 575` | 256/128/384 MiB margins | **ON** |
| C9 | Parallel worker admission (2 GiB reserve) | `S/integration_parallel_selection.py:74-150, 715-760` | Computed | **ON** |
| C10 | Child worker RSS and deadline | `S/integration_parallel_dispatch.py:152-176, 308-600` | Computed | **ON** |
| C11 | Heat pool sized from the ledger | `H/private_heat_functionals_parallel_r1.py` | Computed | **ON** |
| C12 | CPU slot guards | `S/execution.py:38-61, 532-534, 595` | From `os.cpu_count` | **ON** |
| C13 | Launcher hook refusal and RUNNING wait | `H/launch_monitored_interval.py:50, 418-420`; `H/launch_fresh_interval.py:143-144` | n/a | **ON** |
| C14 | Old r9 route constants (13 GiB start floor) | `H/probe_heat_original_connected_r9.py:29-30`; `H/private_heat_continuation_support_r3.py:84-88, 277-283` | Fixed | Retire with the r9 route (E2). Don't ship. |

### D. Diagnostics and instrumentation (detail: `T/rm/inv-CDE.md` §D)

| # | Item | Where | Default today | Rec. | Why |
|---|---|---|---|---|---|
| D1 | Geometry observer (`sys.monitoring` local events on named code objects only) | `H/private_heat_geometry_observer_r1.py:16-70`; `H/prepared_interval_driver.py:233` | On | **ON** | Functional: `on_return` feeds the guard's phase, ticks and `guard.check()` (cancel/RSS). It's narrow and keeps a hook-free scope around geometry. |
| D2 | Process meter records | `H/private_heat_process_meter_r1.py:575, 741` | On | **ON** | This is the C8 mechanism |
| D3 | Guard receipt and record | `H/private_heat_continuation_guard_r3.py:85` | On | **ON**, minimal | The user's run record: status, stop cause, peak |
| D4 | Passive resource summary | `H/resource_guard_patch.py:22-60`; `H/private_heat_resource_diagnostics_r1.py` | On (monitored route) | **ON** | Cheap; useful for support |
| D5 | Dev stage timing (`ATLAS_DEV_STAGE_TIMING=1`) | `H/dev_stage_timing.py:19-39` | Opt-in | **STRICT** | Diagnostic timings aren't acceptance evidence (CODING_SAFETY §4). Release should refuse it. |
| D6 | Stage-timing report tool | `H/dev_stage_timing_report.py` | Standalone | **NO-SHIP** | Developer tool |
| D7 | Focused artifact capture (`ATLAS_FOCUSED_ARTIFACT_DIR`) | `H/run_prepared_restart.py:734-757`; `H/run_fresh_interval.py:427-443`; `H/partition_routing_patch.py:407-419` | Variable set every run; whether a file is written each run is unverified | **STRICT**, or on failure only in release | Debug capture; disk use |
| D8 | Parallel profile store `<query>.parallel-profile.json` | `H/prepared_interval_driver.py:111, 120, 207`; `S/integration_parallel_profile.py:480-514` | On | **ON** | Input to automatic worker selection, which release needs (decision 3) |
| D9 | Child `resource.json` | `S/integration_parallel_dispatch.py:163-176` | On with workers | **ON** | This is the C10 mechanism |
| D10 | Wall-batch `_observer` hook | `S/integration_differential_ale.py:359-447` | Opt-in | **STRICT** | Profiling |
| D11 | Postcheck report | `H/launch_monitored_interval.py:479, 608` | On in postcheck | **STRICT** | Evidence |
| D12 | Source-proof receipt (`production_acceptance=False`) | `H/run_prepared_restart.py:837-839` | On | **STRICT** | Evidence |
| D13 | Failure capture (old route) | `H/private_heat_continuation_support_r3.py:299-325` | On failure | **ON** on failure only | Support; retire with r9 |
| D14 | Launcher warnings | `H/launch_fresh_interval.py:159-160` | On | **ON** | stdout only |
| D15 | Measurement tools: `measure_live_*`, `live_memory_probe`, `ledger_fresh_interval`, `codec_measure/_training/_tradeoff` | `H/` | Off | **NO-SHIP** | Developer tools |

Profiling hooks (cProfile, tracemalloc, settrace) appear nowhere in the production closure.

### E. Test- and proof-only code (detail: `T/rm/inv-CDE.md` §E)

| # | Item | Count / where | Rec. |
|---|---|---|---|
| E1 | `test_*` (155), `probe_*` (2), `measure_*` (7), `step7_*` (2), `codec_*` (3), `*ref_*` copies (16): 185 files, all in `H/`; `composition.json` lists all 369 helpers | `H/` | **NO-SHIP.** The release manifest lists production modules only, and the build fails if a shipped module imports `unittest`, `test_*`, `probe_*`, `measure_*` or `*ref_*`. |
| E2 | Production depends on probe and test code | `probe_heat_original_connected_r9` is the flow source (`H/run_fresh_interval.py:72, 300`; `H/run_prepared_restart.py:70`; `H/prepared_interval_driver.py:72`). External historical-tests modules are bound at run time (`H/run_fresh_interval.py:75, 299, 303-304`; `H/run_prepared_restart.py:72, 808`; `H/prepared_interval_driver.py:86`; pinned at `H/assemble_resumable.py:151-168`). `import unittest` appears at `H/fresh_interval_driver.py:26`, `H/prepared_interval_driver.py:23` and `H/probe_heat_original_connected_r9.py:22`. | **Promote, don't drop.** Before any release, move the flow and the pressure-force check (A8) into reviewed production modules and remove the `unittest` imports. Strict acceptance re-runs unchanged. |
| E3 | `probe_execution_identity.py` copied into the build | `H/assemble_resumable.py:119` | Ship only as a strict verification command (it already refuses release, `:124`), or not at all |

## 3. Class B in release: where full checks stay, what may be shared, and why it's safe

### 3.1 Full check (all captured backends: live callable walk plus source check) runs at

1. **First capture per backend per process** (B1). Already coded.
2. **Store open and reopen**: `ArrayStore.__init__` (`S/storage.py:279`). Add the same at compact-store and interval
   store-set open.
3. **Publication**, before anything becomes visible to another process, session or user:
   - the pre-COMMIT of a put that publishes (`S/storage.py:1047`);
   - compact seal, promote and adopt (B13, to be added);
   - endpoint checkpoint commit;
   - project save;
   - backup (`:1177/1185`);
   - export (`H/historical_export.py:316, 332`).
4. **Cross-process trust points**:
   - worker start: a worker's first capture is its own B1;
   - parent acceptance of a worker result: compare the parent and child identities;
   - restore and reopen of a checkpoint (`H/reopen_*`, `H/private_heat_restored_binding_*`).
5. **Cache reads that cross a session**: the first read of a store opened from disk is covered by item 2. A read of a
   record written by another process goes through a store open, and so is covered too.

### 3.2 Release may share (no full check between two boundaries in one process)

- `ExecutionContext.verify()`. Already a no-op in release, which covers the 3,876 admission calls and
  `publication_check=context.verify`.
- Per-record `get`, `metadata`, `contains` and reference-read scopes, and the put-start boundary, inside an open store
  that a boundary has already verified. Today each costs a full `release_boundary()` (§4).
- Issue-time `verify_boundary` calls inside one process (heat issuer `r13:282, 336`). The consume or publication
  check at `r13:487` stays.
- Helper-private pins (B8) once the helpers ship inside the package's membership.
- In-process cache-flight validation (B9).

### 3.3 Why sharing is safe in a fixed installed build

Three things could change between two boundaries.

**(a) Source bytes on disk.**
- Code already in memory doesn't change when its file changes.
- The next boundary re-reads (or handle-checks) every byte and refuses publication.
- With decision 2, the installed files are write-locked for the process lifetime anyway.

**(b) In-memory bindings.**
- Release runs only allow-listed packaged entry points (B10), and no test or mocking code ships (E1, E2). So only a bug
  in shipped code could rebind a function or mutate a registered constant.
- A persistent rebinding is caught at the next boundary, which always precedes publication. The run is refused; a wrong
  result is never published.
- The residual case is a *transient* patch-and-restore between two boundaries. Strict per-call checks catch it only if
  a verify happens to fall inside the window.
- Release closes that case with a ship-time static check run in strict CI on the release bytes. The check finds no
  assignment to another atlas module's attributes or registered constants, no `setattr` on modules and no
  `mock.patch`.

**(c) Stored data.**
- Byte authentication (B6) and data-identity hashing (B7) stay on.
- Cache keys carry the execution identity captured at B1, and that identity is mode-independent.

**What release gives up.**
- Strict catches an in-memory drift at the next inner call. Release catches it at the next boundary, so it detects
  later and wastes more compute before refusing.
- It never publishes more, because every publication is a boundary.

I11.5's acceptance test must show four things:
- a drift between boundaries makes the seal refuse;
- a source change refuses reuse;
- strict and release produce byte-identical scientific outputs on a matched workload;
- verification commands still refuse release.

### 3.4 How the existing code compares

| Policy element | Existing code | Gap |
|---|---|---|
| Shared first capture | Yes (`S/reuse.py:814-821`) | none |
| Inner `verify()` shared | Yes (`:884-886`) | none |
| Boundaries at store open, backup and pre-commit | Yes | none |
| Boundaries per read scope and at put start | Yes, but this is the cost problem | Too fine-grained; decision 1 |
| Boundary at compact seal, promote and adopt | No | B13 |
| Source hold in release | No: every byte re-read (`:827`, `:900-904`) | Decision 2 |
| Release interval route and workers | Refused (`require_strict_execution` ×5; selector strict gate) | Decision 3 |
| Helper pins mode-aware | No | Decision 4 |
| `-O` refused | Monitored launcher only | A7 |
| No test code in production closure | No (E2) | E2 |

## 4. Measurement

**Release can't run the real admission or heat small cases outside a packaged build.**
- `_packaged_mode` requires the payload layout.
- The interval drivers call `require_strict_execution()`.
- Building a fake payload would be bypassing the gate, so it wasn't done.

**No new timing was run.** The coordinator paused timing at 14:37 (Michael's instruction). The existing development
records already cover every part needed, so the two probes written here were withdrawn unrun at 14:38. They are kept
in `T/rm` in case a direct check of release-as-coded is wanted later; it isn't needed for the decisions.

**Recorded measurements used (all unprofiled unless marked):**

| # | Measure | Value | Source |
|---|---|---|---|
| 1 | `verify_boundary` median, composed RC1 (source re-read, as release does) against r2 (source handles, as strict does); same morning, same machine | **45.3 ms → 12.6 ms** | `R/geometry-growth-r1/HANDOFF.md` §8 "Time" table |
| 2 | `initial_metrics` stage, RC1 against r2 | **407.3 s → 285.2 s (−30 %)** | same table |
| 3 | strict `verify()` on a composed copy | 12.5 ms | `T/fidelity-integration-20261005/claude-review-steps1-7-20261015/fixes/wp9-inventory-notes.md` (source_handles test) |
| 4 | one `verify()` on 30a79e6: `_source_bytes` 16.8 ms + callable walk 9.7 ms; context capture 0.626 s | 27.7 ms | `.atlas-dev/claude-devspeed-verify-cache-20261005-proof.md` "Cost" |
| 5 | Release-mode prototype against strict on 7 desktop workloads; outputs byte-identical | **96.2 s → 44.4 s (−54 %)**. Check-dominated workflows 3-11×; solver-heavy 3-D −2 % | `.atlas-dev/coordinator-performance-review-20261005.md` "Release-mode timing test"; `review-probes/perf-20261005/release-mode/` |
| 6 | cProfile guard shares by stage | admission 31.3 %, pressure 1-3 %, heat issuer 8-10.5 % (28 % of that is source identity), workers 1.06 % | `T/so/s7/S7-REPORT.md` |
| 7 | Seeded admission hits still make 2 full strict verifies (identity, final) | 2 per component | `.atlas-dev/review-item7-item10-20261016.md` "Time claim" |

**Consistency check of the projection model.** Row 1 against row 2: the 32.7 ms per-verify drop × 3,876 admission
verifies predicts 127 s. The measured stage fell by 122 s. The model is within 4 %.

**PROJECTED identity-check time in admission (fresh route, 969 components):**

| Arm | Per component | 969 components | Against strict |
|---|---|---|---|
| Strict, cold (4 verifies × 12.6 ms) | 50 ms | about 49 s | — |
| Strict, seeded hit (2 × 12.6 ms) | 25 ms | about 24 s | — |
| Release as coded, cold (at least 3 store boundaries: get, put start, pre-commit; each 2 backends × 45.3 ms) | at least 270 ms | about 262 s | **about +213 s** |
| Release as coded, seeded hit (get and metadata: 2 boundaries) | 180 ms | about 174 s | **about +150 s** |
| Recommended release (decisions 1 + 2): boundaries at open, seal and backup only, about 25 ms each with handles | about 0 | under 1 s | **about −24 to −49 s** |

**Other stages (PROJECTED, from the S7 call counts × row 1):**
- Pressure: 99 verifies × 12.6 ms ≈ 1.2 s.
- Heat: issue-time issuer boundaries are 2 of 3 per call. The source share is ≲0.3 s per call (profiled, an upper
  bound), so ≲1.2 s per advance pass and ≲3 s in the tail. The tail's 106 reuse verifies add ≈1.3 s.
- Workers: about 1 % (helper pins). This only moves after decision 4.

**Per interval.**
- Fresh interval: about 30-55 s (admission dominates).
- Continuation interval: about 2-6 s, because prepared restarts don't run initial_metrics.

Both are well under 2 % of an interval. The 5 Oct test (row 5) shows the same pattern: release pays off where checks
dominate (short desktop jobs, −54 % to 11×) and barely moves computation-dominated runs (3-D −2 %). The interval
composition is the latter.

**What a later strict-versus-release measurement must do (I11.5).** It needs a real packaged build that has decisions 1
and 3 in place. Run matched inputs and report actual seconds against the denominator. Show byte-identical scientific
outputs. Release timings never replace strict acceptance.

## 5. Decisions (APPROVED by Michael 16 Oct 15:25, via the coordinator: D1-D6 and B13; R1-R6 not started)

Each decision keeps every class-A check, adds no relaxed tolerance, raises no guard, and leaves strict unchanged.

1. **Release boundary granularity.**
   - Recommendation: full checks at open, publication, cross-process and backup/export (§3.1). Share per-record
     store reads and put-start inside a verified open session.
   - Alternative: keep today's per-operation boundaries. As written in CODING_SAFETY §4, "cache reads" are read per
     record, and on this composition that makes release slower than strict (§4).
   - Later-step impact: amend CODING_SAFETY §4's wording to "cache open/import". Add B13. The I11.5 drift-refusal
     test is required.
   - Next-interval capacity: no memory change.
     - PROJECTED against strict: saves about 24-49 s of a fresh interval's admission.
     - Against release as coded: avoids about 150-210 s of added boundaries.
2. **Windows source hold in release.**
   - Recommendation: hold share-deny-write handles from first capture for the process lifetime, so each boundary
     checks handles instead of re-reading about 7.6 MB of source.
   - Impact: Atlas's installed files are locked while it runs, which blocks an in-place update mid-run (desirable).
   - Capacity: no memory change.
     - About 33 ms per backend per boundary (M difference), so about 65 ms per `release_boundary()` call.
     - Reaches 45.3 → 12.6 ms (M) in the measured strict case.
3. **Release interval route and parallel workers.**
   - Recommendation: give the production route a release-capable entry. Allow workers in release, with the worker's
     first capture as its boundary and parent/child identity equality at result acceptance.
   - Verification and evidence commands keep refusing release.
   - Alternative: serial-only release, which gives up the measured 25-36 % parallel gain.
   - Later-step impact: I12.2 packaged-route checks reuse I11.5 parity.
   - Capacity: same memory guards (C9, C10).
4. **Helper-private pins in release.**
   - Recommendation: once the helpers ship inside the package, route the issuer and worker pins (B8) through the
     boundary policy. Strict keeps them per call.
   - Saving is small (workers 1 %; part of the issuer's 28 % source share).
   - Later-step impact: the helpers must first become package modules (also needed for E2).
5. **End-user resource sizing.**
   - Recommendation: keep C1-C13 on.
   - In-run cap = min(12 GiB, physical − 1 GiB floor − OS reserve).
   - Replace the fixed 10 GiB start gate with predicted peak × 1.2 + 1 GiB floor, from a shipped table of
     strict-measured per-route peaks.
   - Nothing goes above today's values without his number.
   - Capacity: on a 16 GiB machine it's unchanged. Smaller machines get a clear refusal instead of a guard stop
     mid-run.
6. **Diagnostics and test code in release.**
   - Recommendation: ship only functional instrumentation (D1-D4, D8, D9, D13, D14).
   - Make D5, D7, D10, D11 and D12 strict-only.
   - Don't ship D6, D15 or E1.
   - Promote the E2 dependencies, including the pressure-force check A8, into production modules first.
   - Make the A7 asserts explicit raises, and make release refuse `-O`.
   - Later-step impact: this is a precondition for any release build.

## 6. Implementation items (later, separate; none started)

- R1: boundary granularity (decision 1) and the B13 seal/promote/adopt boundary, with tests: drift between boundaries
  makes the seal refuse; matched strict and release outputs are byte-identical.
- R2: release source hold (decision 2).
- R3: release-capable interval entry and workers (decision 3).
- R4: mode-aware helper pins once the helpers are package modules (decision 4).
- R5: predicted-peak start gate and machine-sized in-run cap for the packaged launcher (decision 5).
- R6: release manifest of production modules only; promote E2; A7 explicit raises; refuse `-O`; build-time import ban
  and the static rebinding check (§3.3 b).
