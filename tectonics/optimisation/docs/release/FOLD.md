# FOLD: helpers into a private subpackage with package-relative identity (R1)

16 Oct 2026, 17:49. Design only, written for the coordinator's review (condition d). Nothing under atlas_tectonics or composed-*
was edited, and nothing was run except read-only scans.

Paths used below:
- R = the resumability-r1 folder.
- S = R/composed-r2/src/atlas_tectonics.
- `helpers` = R/composed-r2/helpers.
- H = the heat-repair-20261007 tectonics tree.
- Line numbers are from composed-r2.

## 0. Summary

**What.** Move the helpers that heat calls actually use into `atlas_tectonics/_private/`. Every recorded source key becomes a
package-relative path.
- Today these helpers are top-level modules on sys.path. Their identity is keyed by absolute resolved paths, and five of them
  contain literal `C:/Users/...` paths.

**Why.**
- Remake cannot ship IDs that bind a user's folder.
- composition.json's root_rule ("never move or copy this composition") ties every result to one folder on one machine.

**When.** As the last stage of N12's assembly, in the X1 generation. Heat result IDs then change once (§4).

**Proof.** A D-b compare on a real heat call (§5).
- The checker does not trust field names. It applies the fold manifest to the old record and recomputes every ID from its
  preimage. It then requires the result to equal the new record byte for byte.
- An ID may therefore differ only because a mapped input differed.

**Finding (identity gap).** Four helpers pin heat-repair (H) copies of three package modules, but the code that runs at call time
is composed-r2's own copy in S. The fold closes this gap. It is the one place where a pin's *value* changes as well as its key
(F5). Because it is more than a renaming, it is put to the coordinator in §8.

## 1. Fields that change (listed up front, condition b)

Nothing outside this table may change. That covers every array, number, refusal code, and every pin to a file whose bytes are
unchanged.

| # | Field | Where (composed-r2) | Before | After |
|---|---|---|---|---|
| F1 | `sources` (key → sha256) in finisher records | finish_kernel_r2 ~385, finish_kernel_r3 ~440, finish_issue_owned_r4 228/293 (`key = str(Path(path).resolve())`) | absolute resolved path → sha of the helper file | `atlas_tectonics/_private/<name>.py` → sha of the *folded* file |
| F2 | `consumer` | checkpoint_consumer_r10:51 `R.stream_hash(_SOURCES, cancel)` | hash over absolute keys | recomputed over F1-style keys and shas |
| F3 | `source_bindings`, `additional_bindings` | finish_inventory_r1:467 `admit(...)`; endpoint_inventory_r3 `derive(...)` | absolute keys | as F1 |
| F4 | execution identity `runtime` | `R.stream_hash(origin['execution'])` | composed-r2 execution | folded execution; it changes in X1 anyway |
| F5 | three pin *values* for re-keyed package files | geometry_inventory_r1 `_PINS` (35); interval_inventory_r4 `_PINS` (32); low_solver_kernel_r2 (37) and r5 (58) `_SOURCE_PATHS` | H bytes: mimetic_heat 4eb824b4, exact_gmp 1cecc336, spatial_transport 70cdfc9a | the S bytes that run: 7d020e15, 5f3be654, 19426e08 |
| F6 | work bookings derived from path length, where they appear in a record | finish_inventory_r1:419, finish_issue_owned_r4:299, finish_kernel_r10:145, forward_kernel_r13:251, endpoint_inventory_r3:121, interval_inventory_r1:119 | longer, absolute | must be ≤ before (shorter keys) |
| F7 | derived IDs | `result_id` = `stream_hash(record minus result_id)` (issuer_resources_r1:119; checked in `verified_private`), plus any ID whose preimage holds F1–F6 or F8 | — | recomputed; never compared by name alone |
| F8 | sibling pins (19 constant SHA pins, 15 name→sha pins) | helpers' `_PINS`/`_SOURCES` tables | sha of the unfolded sibling | sha of the folded sibling; keyed by relative path |

Notes on the table:
- **POLICY_PATH.** decimal_inventory_r1:38 pins integration_mimetic_newton at ef0f3b48. The H and S bytes are identical, so only
  its key changes, not its value.
- **F6 site that counts bindings.** decimal_inventory_r1:393 counts bindings, not path lengths. The fold adds no bindings, so the
  count must be unchanged.
- **Ordering.** stream_hash sorts keys (`sort_keys=True`). New key names only change where entries sort; the IDs stay
  deterministic.

### 1a. The identity gap (F5)

- Five literal user paths sit in five helpers: geometry_inventory_r1, interval_inventory_r4, low_solver_kernel_r2,
  low_solver_kernel_r5 and decimal_inventory_r1. All five point at files in the H tree. All five cited lines were rechecked at
  17:50.
- geometry_inventory_r1 pins H's `integration_mimetic_heat.py` (4eb824b4), but at line 216 it imports
  `atlas_tectonics.integration_mimetic_heat`. Assuming S is on sys.path, that import loads S's file (7d020e15).
- spatial_transport is the same case: H 70cdfc9a, S 19426e08.
  - The low-solver kernels hash H's file at import.
  - decimal_inventory_r1:208 imports `_workspace` from the package, which loads S's copy.
- exact_gmp is pinned at H 1cecc336 by interval_inventory_r4. Any package import of it loads S's copy, 5f3be654.
- **Effect.** The check passes today because the H file still exists unchanged. But it certifies a file that does not run.
- **Second weakness.** `_verify_sources` (geometry_inventory_r1 ~131-140) opens `HERE/name`. When `name` is absolute, Windows
  path joining silently discards HERE.
- **Status.** "S runs" is established by reading the code, not by measurement. The trace in §2 measures it.

## 2. Module map

**Target layout.** `atlas_tectonics/_private/`, flat, with every file name kept.
- Each old key then maps to exactly one new key, so a reviewer can compare files by name.
- No rename churns the pins.

**Which modules move: decided by measurement.**
- The static closure is 119 modules (47,886 lines).
- The runtime set is taken from a `sys.modules` trace, recording each module's name and `__file__`, at the end of:
  - one real heat-call replay;
  - composed-r2's focused heat tests.
- The same trace settles which copy of atlas_tectonics runs (§1a).

**Classes:**
1. **Runtime helpers.** Fold them.
2. **The 24 source-transform modules.** These rewrote package source text at compose time. Some are still imported at run time,
   e.g. integration_spatial_owner:15 `import live_spatial_patch`.
   - If the trace shows a runtime import, fold the module unchanged; the rewrite text is just data.
   - Otherwise the module stays with the composer tooling, outside the package.
3. **historical_admission**, imported by partition_workflow_patch, materialise_endpoint and historical_compact_heat.
   - It finds the T tree by walking up the parent folders for `.r44-env` plus the heat-repair folder (line 65, using
     HISTORICAL_RELATIVE at line 37).
   - It then runs old modules with `exec(compile(...))` (213-217).
   - Under R2 (fresh runs, no migration) nothing on a fresh run should call it.
   - Proposal: leave it out of the package. If the trace shows a fresh run imports it, keep it, but take its root from an
     explicit argument, refuse when the argument is absent, and never walk parent folders.
4. **functionals_parallel_r1 workers.**
   - Remove the `sys.path.insert` at 879.
   - Fully qualify the module names that are passed as strings: kernel names in the hello message (883), the gmp_resources
     import (886), and mpfr_lu_resources 262/309.
   - Pickle carries data between processes only (223-246, 632, 994-1029). Records are JSON and IDs use stream_hash, so a pickled
     class path changing touches no identity.
   - An unqualified name fails closed: ImportError is caught at 633.
5. **Duplicates.** N12 resolves RC7/C22 (emitted wins, or Heat removes the copies) before the fold. The fold tool refuses if
   two files claim one module name.

**Import rewrite.** It is applied to the helpers and to the 22 package modules that import them.
- `import X as K` → `from atlas_tectonics._private import X as K`.
- `from X import y` → `from atlas_tectonics._private.X import y`, including the lazy ones inside functions.
- Module names held in strings are fully qualified.

**`_private/__init__.py`.** Empty, with no eager imports, so import order and import cost are unchanged.

**New file `_private/_identity.py`.**
- `PKG_PARENT` is the folder containing the package.
- `relkey(path)` returns the POSIX path relative to `PKG_PARENT`. It refuses any path outside the package.
- `resolve(rel)` returns the real path for reading a file.
- Every key is built by this one function, so no helper can build keys a different way.

## 3. Identity after the fold (condition c)

- **Key form.** A POSIX path relative to the package's parent folder. This is the convention composition.json already uses for
  its `outputs` (for example `atlas_tectonics/__init__.py`).
- **File reads.** Reads still use real paths; `HERE` stays for opening files. Only the *recorded* key changes.
- **Sibling pins stay.** Each check still reads the file and compares its sha; the recorded key becomes `relkey(...)`.
  - What this protects: a run never mixes helper versions.
  - What it costs: one hash per pinned file. That cost is unchanged.
- **The five literal user paths.** Each becomes a package-relative name resolved through `_identity`, pinned to the bytes that
  run (F5).
  - `_verify_sources` refuses an absolute name instead of letting it silently replace HERE.
- **Gate.** Scan the folded tree and the B-arm records (§5) for drive letters, `/Users/`, `\Users\`, `the-diadem` and
  `Codex/`. The required result is zero hits.
  - This gate also enforces the rule for the public review branch.
- **root_rule.** The fold retires the "permanent root" rule, because identity no longer depends on location. composed-r2 itself
  is never moved (R2).

## 4. Timing within X1 and N12 (condition a)

**Placement.** The fold is the last stage of N12's `assemble_r3`. It runs after:
- every heat transform: H1a/H1c → H2 → L1 → H3, with C14's resources repin 8b451aa8 → fadac10d, then H5a and N6;
- the geometry transforms: D2 → G-PY and D5 → N9;
- the single reuse.py revision (source_handles r2 + L4).

**Why last.**
- Every transform rewrites helper bytes and their pins.
- If the fold came earlier, every later transform would have to understand the folded layout, and pins would be recomputed
  twice.

**Re-pinning.**
- Runner folds the C15 heat-pin cascade once.
- The fold's re-pin is then one more bottom-up pass, in topological order over the pin graph, and it refuses if it finds a
  cycle.
- EXPECTED_HEAT/COLD are re-derived in the same pass.

**One ID change.**
- composed-f1 is composed directly in the folded layout.
- The fresh runs therefore carry X1 and R1 as one ID change.
- U1 and U2 land after this, so their receipts are captured once.

**C14 compatibility.**
- The fold does not reorder H2 → L1 → H3. It consumes H3's output.
- If L4 has to fall back to riding with the first of H3/G-PY (X1's fallback), the fold still goes last, so R1's change is not
  split.

## 5. Parity test (condition b): D-b compare on a real heat call

**The heat call.**
- It must use real inputs (not a fixture).
- It must exercise:
  - finish_kernel_r10's `sources`;
  - checkpoint_consumer_r10's `consumer`;
  - inventory `admit` (`source_bindings`);
  - the exact-GMP and mimetic-heat paths.
- It must fit the small lane.
- Pick the smallest such call recorded in composed-r2's first-interval evidence. The exact call is chosen at implementation and
  run through a runq ticket.

**Arms.** All arms replay the same call.
- **A:** composed-f1 unfolded, run from its own root.
- **A′:** the same as A, run again (the noise arm). A and A′ must be byte-identical; otherwise no layout comparison means
  anything.
- **B:** composed-f1 folded.

**Checker ("derive, don't trust").**
1. Load the fold manifest. For every module it lists:
   - old key → new key;
   - old sha → new sha;
   - the three F5 re-pins.
2. Transform A's record:
   - Map F1, F2's inputs, F3, F5 and F8.
   - For F4, check that B's execution record differs from A's only in mapped keys and shas, then substitute it.
   - For F6, require B ≤ A. (Superseded at R2 by the exact booking rule in v25/bookings.py; for rationals see §12.)
3. Recompute every derived ID (F2, F7) bottom-up with the record's own `stream_hash`.
4. Require the transformed A to equal B byte for byte in canonical JSON, arrays included.
- Why this design: an allow-list by field name could hide a real numerical change inside an allowed ID. Recomputing each ID from
  its preimage closes that.

**AST gate on the fold itself.**
- Each folded module's AST must equal the original's, except for import nodes, pin literals and calls that build keys.
- Cost: seconds.
- What it catches: an accidental code edit on a path the single heat call does not exercise.

**Focused tests.** composed-r2's focused heat tests on both layouts must give the same pass/fail set.

## 6. Mutants (each must make the checker or a gate fail)

Every mutant is applied to a copy of B's record or of the folded tree, never to evidence.

| # | Mutant | Caught by |
|---|---|---|
| M1 | one array value moved by +1 ulp | byte compare (numbers) |
| M2 | a non-identity field changed (a refusal code, or a count outside F6) | byte compare |
| M3 | one absolute path left in a `sources` key | manifest mapping + gate (c) |
| M4 | one sibling pin dropped from `_SOURCES` | key-set mismatch |
| M5 | an F5 pin left on the H bytes (the old gap) | manifest says S |
| M6 | a stale `_SOURCES` key for a module the fold did not emit | manifest mapping |
| M7 | a path-length booking that grows | the F6 ≤ rule |
| M8 | a forged `result_id` (right preimage, wrong hash) | ID recomputation |
| M9 | a code edit in a folded module outside import, pin and key nodes | AST gate |

Negative controls (these must pass):
- **N1:** the `sources` dict built in a different insertion order. It must pass because stream_hash sorts keys.
- **N2:** the noise arm, A against A′ with the identity mapping.

## 7. Work and cost

**Where.** The fold tool, the manifest writer, the AST gate and the checker live in `T/rm/fold/`. They go neither in the repo
nor in composed-*.

**Runs.** All are runq tickets, `small`:
- one trace run;
- the three arms (A, A′, B) of one heat call;
- focused tests on two layouts.

**Not estimated.** I have not timed the chosen call, so the CPU time is not estimated here. It is measured on the trace run and
then booked.

## 8. Decisions for the coordinator

1. **F5: re-pin three files from H bytes to S bytes inside R1's one change?** Recommend yes. The alternative keeps pins on bytes
   that never run.
2. **historical_admission outside the package under R2?** Recommend yes, subject to the trace.
3. **Fold placement?** Recommend the last stage of N12. The alternative, a separate step after the freeze, would split the ID
   change across two generations.
4. **Ownership.** N12's chain (Small/Runner) owns the stage order; the fold tool is new work. It needs an assignment, plus Heat
   and Kernels' agreement, because C14 already gives them a choice in this same generation.

**Evidence used (read-only):** `rm/reconcile/idscan.json` and `rm/reconcile/closure.json` (from `idscan.py`), the cited
helper lines, composition.json, and `T/so/assembly-manifest.md` (X1, C14, C15, RC7/C22, step 5/6).

## 9. Coordinator decisions and sign-offs (added after review)

### Coordinator, 16 Oct (about 17:52)

FOLD.md is accepted. Rulings on the §8 points:

1. **F5 re-pin inside R1:** APPROVED. First, two pieces of small-lane evidence:
   - a loaded-file trace on one real heat call, showing which mimetic_heat, exact_gmp and spatial_transport files execute;
   - a byte diff between the H copies and the S copies.
   If the bytes are identical, the re-pin is bookkeeping. If they differ, it is recorded as an identity-coverage defect (§10),
   with the affected records listed. Old receipts are never rewritten.
2. **historical_admission:** stays out of the package under R2. APPROVED.
3. **Fold placement:** the last N12 assemble_r3 stage. APPROVED.
4. **Fold tool owner:** this lane.
   - Build it as new files under `T/rm/fold/`, outside every package whose source is pinned.
   - Heat and Kernels sign off F1-F8 before the parity run.
   - The parity run needs a ticket: smoke and refuter first, then a REQUEST with a measured peak.

### Kernels, 16 Oct 17:53: AGREE with F1-F8, plus one H3 condition

**The hazard.** H3 loads its compiled helper by **path**, not by import.
- `private_heat_certification_kernel_r1` reads `Path(__file__).resolve().parent/'private_heat_compiled_dot_r1.py'`, checks the
  sha, then runs the file under the unqualified `sys.modules` key `private_heat_compiled_dot_r1`.
- An import-graph inventory would miss this helper.
- A module-name rewrite could qualify `_H3_NAME`.
- Either mistake makes H3 silently fall back to the Python route (route `unavailable: OSError`). Records stay identical, but
  the speed is lost and nothing reports it.

**Added fold rules:**
- **K1.** Fold `private_heat_compiled_dot_r1.py` next to the kernel, byte-equal (62c100cf, pinned as a constant inside the
  kernel). The helper must have no helper imports.
- **K2.** Leave `_H3_NAME` and the load hook unchanged. The module-name rewrite (§2) applies to import statements and to the
  string names listed there. It excludes `_H3_NAME`, and the fold tool keeps an explicit list of what it excludes.
- **K3.** Fold check: `h3_status()['route'] == 'compiled'` on the folded tree. It must fail loudly, never fall back silently.
- **Module set.** The runtime set is taken from the trace and from the files loaded by path, not from imports alone.

**Fields Kernels confirmed are not path-bound:**
- `reuse._runtime_record` keys its binaries by label.
- `exact_arithmetic.runtime()` returns paths, but reuse hashes them under labels.
- H3's `build_info.mpfr_dll` and its seal's `str(path)` go only into process state and the h3-route.json evidence, never into a
  record. They are a scrub item for the public branch only.
- L4 uses only label keys.
- G-PY, D5 and I19 use only package-relative imports.

**F5 does not affect D5 or H3.** They use gmpy2 through exact_arithmetic, not integration_exact_gmp.

### Heat, 16 Oct (about 17:57): AGREE with F1-F8 for H5a and N6, with two additions

**H1, an extra F6 site.** N6 adds finish_kernel_r11. Its path-length booking is at r11:148 (r10:145 moved down by 3 docstring
lines).
- S1 (pending integration in T/hs/s1) moves closed_owned r4 -> r5 and finish_kernel r10 -> r11.
- The F6 list carries both r10:145 and r11:148.

**H2, a path-bound check that is not a recorded field.**
- What it is: closed_owned (r4 and r5) re-reads every `_SOURCES` file by its resolved path on every `closed_guard` call and
  compares it with its pin. The finish kernel's walk does the same at import.
- After the fold these keys resolve to `atlas_tectonics/_private/...` automatically. The bytes must be the folded files'
  bytes; a stale key or file refuses with "Closed guard source changed".
- Added fold check K4: the B arm runs a real heat call, so this guard runs on the folded tree on every call. Any stale key
  fails the arm.

**Other confirmations from Heat:**
- N6's `_SOURCES` reach `I.issue` through `bindings` (F1).
- Finish diagnostics that carry stage inventories are dropped unread (native_issuer_r13 604-614), so no record holds them.
- H5a's pins are keyed by basename (F8).
- The forward content digest 081aac58 is pinned on 9 lines in 6 files (`hs/evidence/h5a-generation-note-r1.md`). The F8 re-pin
  covers those lines.
- No file changed by H5a or N6 holds a heat-repair pin. F5's literal values appear only in geometry_inventory_r1 and
  interval_inventory_r4.
  - low_solver_kernel_r2 and r5 hash the heat-repair spatial_transport file at import, so its value is computed, not
    written in the file.

## 10. Identity-coverage defect and design addenda (16 Oct, written 18:04)

### 10.1 Evidence (condition 1a and 1b, small lane)
- Byte diff: rm/fold/pindiff.py → rm/fold/pindiff.json. AST classification of each heat-repair (H) copy against the
  composed-r2 (S) copy, CR stripped.
  - mimetic_heat (H 4eb824b4, S 7d020e15): S adds MimeticGeometry.cell_id/from_compact/legacy_record and
    _CompactMetricRow(s); changes MimeticGeometry and MimeticGeometry.record.
  - exact_gmp (H 1cecc336, S 5f3be654): S adds FILTER_CAP_POINT_BITS/FILTER_PLANE_BITS, _cap_face,
    _filtered_poly_side, _filtered_relation, _noncollinear, _repeat_volume_exact, and imports of
    integration_filtered_predicates and spatial_transport._workspace; changes _all_beyond, _all_within, _clip and _face.
  - spatial_transport (H 70cdfc9a, S 19426e08): S adds imports of live_finite_patch, live_spatial_patch and
    live_transport_result; changes PreparedSpatialTransport (__init__, advance) and SpatialTransportResult.record.
  - mimetic_newton: byte-identical (ef0f3b48).
- Loaded-file trace: rm/fold/trace_frozen.py, run by rm/fold/run_trace.sh on the small lane (17:58:44–18:00:34; tree
  peak RSS 1.04 GiB). It covers one real heat call on composed-r2. The reviewed harness
  (probes/step9/claude-20261016/heat_control_on_frozen.py, `child`) ran unchanged in the traced process, with
  reference composed-checks/r2-heat-control.json.
  - Control result: PASS, and frozen check PASS on every field (result_id, metadata bytes and sha, arrays, exact
    accounts, plan, snapshot). 236 cells, 832 faces, 103.4 s, peak working set 274,661,376 B.
  - All four target modules executed from composed-r2/src: 7d020e15, 5f3be654, 19426e08 and ef0f3b48.
  - All four H copies were opened (read for hashing) but none was executed. 0 modules loaded from heat-repair src.
  - All five pin holders loaded, plus forward_kernel_r13 and low_ledger_inventory_r1.
  - The tool's pinned_by regex caught only plain string literals (geometry_inventory_r1 → mimetic_heat,
    interval_inventory_r4 → exact_gmp). The `Path('dir')/'file.py'` pins in low_solver_kernel_r2:37, r5:58 and
    decimal_inventory_r1:38 are cited from the code.
  - Also seen: the call imports 9 heat-repair *test* modules as fixtures (i02_workflow_fixtures, i03_fixtures,
    test_i03_bridges, test_i04_regional_owner, test_i04_spatial_workflow, test_integration_collar_geometry,
    test_integration_spatial_ale, test_regional_collar3d, test_regional_evolution3d). They are harness inputs, not
    package code, and both parity arms must load them from the same frozen path.
  - The same composed-r2 call reproduced its own reference record bit for bit. That is one sample of the A' noise arm.

### 10.2 Defect: pins certify files that do not execute
In composed-r2, three pins name H copies whose code differs from the S copies that actually run (10.1). The pin
checks hash the H file, find the expected value and pass, but the code they vouch for is not the code that executes.
The mimetic_newton pin names identical bytes, so it only needs bookkeeping.

### 10.3 Affected records
- **Recorded, LOW records:**
  - low_solver_kernel_r2 builds `_SOURCE_PATHS` (34-40) → `_SOURCES` = {resolved path: sha256} → `_bindings` (61).
  - low_solver_kernel_r5 does the same: 54-62 → `_bindings` (155) → `source_bindings=_SOURCES` (231).
  - Both carry {H spatial_transport path: 70cdfc9a} while 19426e08 runs.
  - Reach: records issued through forward_kernel_r13 (which imports r5) and low_ledger_inventory_r1 (which imports r2).
  - Derived IDs over those bindings stay self-consistent. verified_private recomputes over what is stored, so the stale
    binding still verifies, but it does not identify the code that ran.
  - Arrays and numerical results are not affected (10.1: bitwise reproduction).
- **Not recorded, startup checks only:**
  - geometry_inventory_r1 `_PINS` (29-36; `_verify_sources` 131, called at 255). Importers: heat_payload_indexed_patch,
    geometry_inventory_r3, polygon_moment_inventory_r1, stage_lifetime_r3.
  - interval_inventory_r4 `_PINS` (25-32; `verify_sources` 48). Importer: interval_assembly_kernel_r5.
  - These give a false guarantee, but they do not write a false record.
- **Not scanned:** the stored sqlite and compact stores were not searched for the H spatial_transport key. The
  decision does not need that scan, because old receipts are never rewritten. Under R2 (fresh runs, no migration),
  records written after the fold carry true bindings, and the old ones stay as history with this note.
- **Scope:** composed-r2 and anything composed from it. In Heat's T/hs/lw runtime-src, spatial_transport is 70cdfc9a
  (= H), so the LOW binding is true there. Its exact_gmp is 6f7e6e4d, though, so any startup-only exact_gmp pin it
  runs has the same gap as above.

### 10.4 Consequences for the fold
- F5 moves the three pins to S; the checker's sha_map maps {H key: H sha} → {relkey: S sha} and nothing else.
- **New gate G-PIN, prompted by this defect:** the fold refuses unless, for every pinned file, the pinned sha equals the
  sha of the file that `python -I` actually imports under that module name in the folded tree. That subprocess check
  would have caught this defect. It is added as mutant M10: point one pin at a stale copy, and G-PIN must fail.

### 10.5 Design addenda (from the sign-offs)
1. **Read by key.** closed_owned r4/r5 `closed_guard` and the finish walk re-read every `_SOURCES` file by its key.
   With package-relative keys, every read by key goes through `_identity.resolve(key)`. The AST gate treats
   `str(Path(x).resolve())`, `_identity.relkey(x)` and `_identity.resolve(x)` as one form, KEY(x), so only that
   rewrite is allowed at those sites. One W4 run on the folded tree covers it (Heat's H2/K4).
2. **K5, cwd guard.** Arm B runs from a cwd that is not the package parent, so any read that misses `resolve` fails
   loudly instead of resolving against the cwd by luck.
   The fold's K5 key-reader check (fold_r4, a separate static check) has a recorded limit (R2 decision 1): K5 traces key tables through module-level assignments and module aliases (`import M`, `from P import M`) to a fixpoint, but not through `from M import NAME` of a table; it sees readers only as `a / name`, `Path(name)`, `open(name)`, `os.path.*(name)` and `.joinpath(name)`, and a reader in any other form is skipped, not refused (a silent-miss class, not fail-closed).
   The backstop is an equation, not a smoke observation: the records rule ties the private-source table A vs B
   (91 = 91), and mutant M4 covers a dropped entry.
3. **Full metadata capture.** Arms A and B save the full canonical metadata bytes of every issued record, the same way
   ab_heat_r5's proof observer does with sys.monitoring, and not just digests. That lets the checker recompute every ID
   instead of trusting it.
4. **Checker (rm/fold/parity.py; modes `records`, `noise`, `ast`):**
   - It maps path-keyed dicts and path strings through the manifest.
   - It fails on any absolute path left unmapped, and on any user path in B.
   - Derived IDs come from a recipe registry: `self_ids` (hash of the enclosing record without the field, recomputed
     deepest first) and `external` (stated preimage, checked against A, then mapped and rehashed).
   - Any difference left over fails, including an unregistered hex-64.
5. **Module set.** The modules folded are: the helpers the trace loaded, plus helpers opened by path from pin holders,
   plus the closure over pin references. The trace's own opened-not-loaded list is not used as a source, because it
   includes the harness's frozen-input hashing (about 260 helper files). Heat-repair test fixtures stay outside the
   package (10.1).

### 10.6 Composition coverage (coordinator question, 18:06)
- **The composition pins the files that ran.** composed-r2/composition.json `outputs` hashes all 236 src files, and
  its entries for the four are exactly the shas the trace saw executing:
  - integration_mimetic_heat 7d020e15…
  - integration_exact_gmp 5f3be654…
  - integration_spatial_transport 19426e08…
  - integration_mimetic_newton ef0f3b48…
- **So at composition level, the running code is identity-covered.** The composition manifest names and hashes the
  bytes that executed, and its root rule makes launchers refuse any other root. That holds even though the LOW
  helpers' own source_bindings name the heat-repair spatial_transport file.
- **At record level it is not shown.** No helper I checked hashes these four package files into a record:
  issuer r13, forward_kernel r13, gmp_resources_r1 and indexed_runtime import them but do not hash them. One question
  is open: whether `execution.provenance` (F4) carries package digests. This control saves only digests of the
  metadata, not the metadata itself, so it cannot say. Section 10.5(3)'s full metadata capture answers it in the
  parity arms.
- `frozen: false` (checked 18:07): composed-checks/assemble_r2.py:325 writes it as a constant. No reader of
  composition.json's `frozen` exists in composed-r2/helpers, composed-checks or probes. HCF's `'frozen': True` is
  its own control.json, not this flag. So in r2 the flag gates nothing; it only labels the composition.
- **Open item, after F4 is answered (not part of R1):** if `execution.provenance` carries no package digests,
  records do not name the code they executed. The later fix is records naming their executed code (coordinator,
  16 Oct).

## 11. Fold tooling status (16 Oct 18:09; checker revised 18:30 after the refuter)
Files are in T/rm/fold; nothing was written to composed-* or atlas_tectonics.
- **parity.py** (sha c0efe8a5…; v1 was 2ad138ec). Modes:
  - `records A B MANIFEST`: fold parity, "derive, don't trust";
  - `noise A A2`: the A' arm;
  - `ast ORIG FOLDED MANIFEST`: AST gate;
  - `pins FOLDED MANIFEST`: G-PIN, using a `python -I -B` subprocess from outside the tree.
  - v2 principle: **translate the original by the manifest, then compare exactly; nothing is erased.** Absolute
    literals go through key_map. Hex-64 values (bare or `sha256:`-prefixed, at any depth) that equal an old sha in
    sha_map become the new sha; an old sha with two new shas is refused. `<identity_name>.NAME` becomes its declared
    `identity_constants` key. A seed or expected digest that is not an old pin must stay byte-identical.
  - Imports become unforgeable IMPORT(bound, target) markers (a NUL-named node no source can contain). The identity
    import is dropped only when it binds `identity_name` to atlas_tectonics._identity, and it is refused where the
    original module already uses that identifier. KEY needs exactly `str(Path(x).resolve())` (Path a Name, no
    keywords) or `<identity_name>.relkey(x)`. Folded code may not import a helper outside atlas_tectonics._private
    (statement or string importer), and may not hold a drive, UNC or user path literal.
  - Records: key_map must be injective, and a mapped key may not collide with a key already in the same dict.
    Bookings are `int` and 0 ≤ B ≤ A. Booking, self-ID and external paths are written in B's key space. An external
    preimage that contains one of A's self-IDs is refused. The user-path screen also covers UNC, `~/`, `\Users\`,
    `/home/` and `%USERPROFILE%`, case-insensitively, and no longer flags URLs. KeyError, ValueError, TypeError and
    OSError become FAIL JSON.
  - G-PIN: every sha_map new sha must equal FOLDED_SRC/<key>; no .pyc may exist anywhere in the tree; each pinned
    module must import from FOLDED_SRC/<key> as a .py whose sha equals both the pin and sha_map's new sha; no helper
    stem may be importable at top level.
  - On a mismatch, the checker names the changed field, not the self-ID that inherits the change.
- **selftest.py** (sha 2710c4d3…): 48 cases with HELPERS_DIR, 0 wrong (47 without).
  - Positives pass: a correct fold (now also exercising a nested prefixed pin, a booking under a path key in B space,
    and a "/" data string), an AST fold, and G-PIN on the right file.
  - Mutants fail: M1, M2/M2b, M3, M4, M5/M5b, M6/M6b, M7/M7b, M8/M8b/M8c, M9 and M9b–M9m, M10 and M10b–M10d.
  - Refuter regressions fail: R01/R01b, R03 (NaN gives FAIL JSON), R04, R05/R05b–R05e, R06.
  - Negative controls pass: N1 (insertion order), N2 (noise), N3 (URL text is not a user path).
  - parity.stream_hash gives the same bytes as the real private_heat_issuer_resources_r1.stream_hash.
  - B is built by hand, separately from the checker. Record mutants recompute B's own IDs, so each one is caught by its
    edit, not by a stale ID.
- **Review tools** (check-only): Pyright reports 0 errors on both files. Ruff (0.16.9, same rules and executable for
  base and candidate) finds only style classes already present in v1: UP031 %-formatting and C408 dict() calls (the
  helpers' idiom), I001 and RUF100. The one correctness-class hit, B905 zip without strict, sits right after an
  explicit length check. No fixes applied.

### 11.1 Refuter results (one agent, 18:19) and outcome
Scripts: rm/fold/refute/. All 13 confirmed findings were fixed in v2 and re-run at 18:30:
- **HIGH, now FAIL:** r01 key collision (non-injective map, and an abs key landing on an existing key); r21 pins not
  tied to bytes (AST pin edit is now caught, and `pins` checks sha_map against the files); r10 any path literal or
  `_identity.UPPER` swap, any hex-64 seed or digest change, any "/" literal change (all 10 r10 cases are now False).
- **MEDIUM, now FAIL:** r02 nested or prefixed pins (all four shapes: stale FAIL, correct PASS); r20 stale .pyc;
  r22 unqualified import plus a top-level copy (G-PIN; the AST gate catches it when the manifest lists the modules,
  selftest M9j); r10 `_identity as X` shadowing and KEY callee or keyword changes.
- **LOW, now FAIL:** r04 external preimage containing a self-ID (fail-closed, including the case where B is right);
  r05 bool or negative bookings and the UNC, `~/`, `..\Users\` and `%USERPROFILE%` leaks.
- **Fail-closed by design (documented, FAIL JSON from the CLI):** a hex-64 data digest directly under a mapped key
  must be in sha_map (the fold lists data files with old = new); float bookings; NaN. The r03 cases that put A-space
  keys into booking or self-ID paths now raise KeyError, because those paths are B-space by contract. The r11 cases
  pass once the manifest declares the mapping (key_map, a lower-case identity constant); relative imports and slash-form
  private names stay refused.
- r30 (probes that held): all still hold.
- Names: helper `private_heat_snapshot_store_r3` already defines a function `_identity`, so the fold must bind the
  identity module under another `identity_name` (for example `_atlas_identity`); the gate refuses a clash.
- **Not built yet:**
  - the fold transformer (manifest writer and rewrite), which is the next piece;
  - the arm harness with full metadata capture.
  - The parity ticket cannot be requested until composed-f1 and the folded tree exist.
- **Measured cost for booking:** one composed-r2 heat call under trace takes about 110 s wall, with a tree peak RSS of
  1.04 GiB on the small lane. The three arms are about 3 × that, plus fold time.
- **Rewrite-site inventory** (rm/fold/inventory.py, read-only AST scan, 18:10):
  - The 105 helpers loaded by the traced heat call (inv-traced.json) contain:
    - 556 helper imports;
    - 6 module names written as strings;
    - 77 `__file__` anchors;
    - 41 key builds;
    - 5 absolute literals, in exactly the five pin holders of §1a;
    - 0 star or relative imports.
  - All 214 non-test helpers (inv-all.json) contain 1,113 imports, 58 string module names, 68 key builds and 18
    absolute literals in 14 modules. Beyond the five, the extra literal-holders are original_joined_r5–r8,
    original_spatial_r1, original_continuation_r1, cold_archive(_worker) and step7_same_call_heat_control.
  - The read-by-key count is noisy: store opens get counted too. The real source re-reads are mainly the 22 sites of
    the form `Path(k).read_*`, and those need confirming one by one.
- **Transformer specification, for whoever builds it next:**
  1. Module set: the closure (§10.5.5), minus historical_admission (R2), minus test_*. Any helper outside the set
     that the closure needs makes the fold refuse.
  2. Rewrite only through AST-located spans: imports (§0 rules), string module names, the 5 pin literals (F5 to S
     shas; the others become a relkey plus a folded sha), and key builds to `_identity.relkey`.
  3. Read-by-key sites go through `_identity.resolve`.
  4. Write the manifest (key_map, sha_map, bookings, self_ids, external, modules, pins, identity_name,
     identity_constants). sha_map must cover every folded file, including any data file whose digest sits under a
     path key (old = new). Booking, self-ID and external paths are in B's key space. Pick an identity_name that no
     module uses (not `_identity`).
  5. Write no bytecode into the folded tree (run everything with -B) and leave no helper importable at top level.
  6. Then run the gates in this order: the `ast` gate, G-PIN, and the K5 cwd guard in arm B. The fold refuses on any
     failure.

### 11.2 parity.py v2.1 (23 Oct 00:02): two gate fixes reported by Plan 20, plus a stem rule
Source: Plan 20's request W/work/plan20/requests/plan26-return-r1.md (e5dbde23), where W is the
shared plan workspace. Both findings were reproduced here before the fix.
- **Missing ctx (false FAIL, version-dependent).** v2 built `ast.Name('Path')` without ctx when it normalised folded
  `<identity_name>.resolve(x)`. On Python 3.12 (.r44-env runs 3.12.14) that dumps unlike the original's parsed
  `Path(x)`, so every correct resolve() site failed the `ast` gate. Python 3.13 fills in Load. Every synthesised
  Name now carries `ast.Load()`.
- **Imports inside source text (false PASS).** compact_restart_patch.workflow_source() injects
  `import compact_restart_patch as _RESTART` as text into the workflow source it builds. v2 compared strings
  verbatim, so a bare helper import left in folded text passed the gate. Now:
  - on the folded side, any import statement inside a string (statement start = line start or `;`) that names a
    declared helper bare is a violation;
  - `import atlas_tectonics._private.X as Y` and `from atlas_tectonics._private.X import ...` normalise to the
    original form, and only when X is a declared helper.
  - `import P.X` without an alias binds P, not X, so it keeps its prefix and differs.
  - The text form `from atlas_tectonics._private import X` is refused (fail-closed); the transformer must emit the
    dotted `as` form.
  - Concatenated or computed import text is out of the gate's sight. G-PIN's no-top-level-helper rule makes such an
    import fail at run time instead. (This was not the only gap: v2.1 also missed literal text; see §11.3.)
- **Stem rule (tightening).** A qualified name now drops its private prefix only when the remainder names a helper
  the manifest declares: the stems of key_map and modules `.py` keys. v2 stripped any `atlas_tectonics._private.`
  prefix. Consequence for the transformer: every helper that folded code imports from the private package must be
  declared, which the closure in step 1 already gives.
- **Tests.** selftest.py e73eee83: 58/58, with 10 new cases (2 positives, M9n–M9u). The positives and M9p, M9s and
  M9t are wrong under v2, which is why they were added. Pyright 0 errors. Ruff check-only with v2's rules
  (E,F,W,B, line 120): the same two findings as v2 (one E501, one guarded B905); nothing introduced.
- **On Plan 20's capture fragment** (W/work/plan20/integration-r1/seam/r1, read only):
  - v2 fails compact_restart_patch (CRP) and ledger_fresh_interval (LG) on the ctx pair.
  - v2.1 passes LG, capture_store and storage_zstd_backend as given.
  - v2.1 fails CRP only on the text import (line 217).
  - With the two text sites rewritten to the `as` form, and its four imported helpers declared
    (compact_restart_store, exterior_mesh_patch, native_transfer, workflow_transfer), CRP passes. That experiment
    was in scratch; nothing in W was edited.
- Files: parity.py 416a6da1 (v2 kept as rm/fold/v21/parity_v2_c0efe8a5.py.txt); diffs in rm/fold/v21/. Plan 20's
  seam_checks.py pins c0efe8a5, so its harness refuses v2.1 until it re-pins.

### 11.3 parity.py v2.2 (23 Oct 00:33): fixes for the v2.1 refuter's findings
One refuter agent tested v2.1. Its cases are in rm/fold/v21/refute/ (r21–r28 plus three probe scripts), and each
was reproduced here before the fix. The text gap was wider than §11.2 said.
- **resolve() matched any Path (r21).** v2.1 normalised folded `<identity_name>.resolve(x)` to `Path(x)` for every x.
  Now:
  - A literal argument must be a key_map value. It becomes RESOLVE(key), and so do the original's
    `Path(<literal that is a key_map key>)` and the folded `Path(<identity_name>.<constant>)`.
  - A non-literal argument becomes `Path(expr)`. This is the read by key of §10.5.1, and resolve refuses non-keys
    at run time.
  - A starred argument, an extra keyword, or a folded `Path(<key literal>)` still differs. The last is cwd-relative.
  - The Path rules apply only when, on both sides, Path is bound solely by `from pathlib import Path`. `Path = str`,
    a star import or `pathlib.Path` switch them off (fail-closed).
- **Identity name unchecked (r22).** The check now runs whenever folded code uses the identity name: when it imports
  atlas_tectonics._identity, or when it calls `<identity_name>.resolve`, `.relkey` or `.<constant>`. The gate
  refuses if that name is an identifier anywhere in the original. It also refuses if anything other than a
  module-level import of the identity module binds the name. For the transformer, this means it must import the
  identity module at module level, never inside a function.
- **Literal text escapes (r23).** v2.1's line scan missed bare helper imports in literal text in these forms:
  - after `if 1:`;
  - across a backslash continuation;
  - after a lone CR or a form feed;
  - spelled with full-width letters (NFKC);
  - in a `__import__` or importlib call inside text;
  - in text nested inside text;
  - in bytes literals.

  Text that mentions import or find_spec, or that is not ASCII, is now dedented and parsed. The parse is walked for
  import statements, importer calls and nested strings, to depth 4. Text that does not parse goes to a regex screen
  over an NFKC copy, with CR, form feed and continuations normalised first.
- **Text rewrite changed other strings (r24, r26).** The rewrite of `P.X` to `X` inside text is now accepted only if
  the rewritten text reparses to the text's own tree with only the import names unqualified. Otherwise the text is
  compared verbatim. A whole string is unqualified only when it is exactly `P.<helper>`, the import_module case.
  `P.X.py` and `P.X.attr` still differ.
- **Stem set (r25).** The private helpers are now the key_map and modules entries whose new key is a `.py` under
  atlas_tectonics/_private/. Each maps to the name the original module had.
  - A rename (old stem differs from new name) is honoured.
  - Two helpers may not fold from the same original name.
  - A module folded outside _private gets no mapping. Importing it from _private fails.
  - If the original imports such a module bare, the fold must keep that import unchanged:
    `from atlas_tectonics import X` against a bare `import X` is refused. This fails closed and is left for review
    by hand.
- **`import P.X` binds the package (r27).** Import markers now record what each name is bound to:
  - `import P.X` binds atlas_tectonics, so it still differs from `import X as atlas_tectonics`;
  - `import P.X.f as s` binds a module, so it differs from `from X import f as s`, which binds an attribute.
- **False fails fixed (r28).** These correct text imports are now accepted: a helper that is not the first name in a
  multi-name import; `from P.X.sub import ...`; and an alias equal to the helper name.
- **Residuals, documented and not gated:**
  - A data string that is itself a valid import statement naming a helper is normalised like source text. This is
    low risk; v2 failed it.
  - A key literal used indirectly as a cwd-relative path, for example passed to open() through a variable, is
    compared verbatim on both sides. This is unchanged since v2.
  - The gate cannot see computed or concatenated import text, or dynamic bindings (exec, globals(), setattr on
    modules). G-PIN's no-top-level-helper rule makes such a bare import fail at run time.
  - `resolve(expr)` against `Path(expr)` passes by design (§10.5.1), including `resolve(__file__)`. resolve refuses
    any non-key at run time.
- **Tests.**
  - selftest.py bdb489bf: 89/89. The 31 new cases are M12a–M12v and 9 positives; a case can carry its own
    manifest. It runs only with RR/composed-r2/src and RR/composed-r2/helpers on PYTHONPATH (and the helpers dir as
    its argument): private_heat_issuer_resources_r1 imports a sibling by bare name, so without them the run stops at
    that import, which is not a gate failure.
  - All refuter scripts were re-run. The only false passes left are the residuals above. The only false fail left is
    the fail-closed non-private case.
  - Pyright CLI: 0 errors.
  - Ruff check-only with v2's rules: parity.py has the same E501 and guarded B905 as v2, and selftest.py keeps its
    one existing E501. Nothing was introduced.
- **On Plan 20's seam r1** (read only, with the four extra helpers declared in a scratch manifest as in §11.2):
  - v2.2 gives the same verdicts as v2.1. capture_store, ledger_fresh_interval and storage_zstd_backend pass.
    compact_restart_patch fails only on the bare text import at line 217.
  - With both text sites in the `as` form, all four modules pass.
  - seam_checks.py's AST_DIFF diagnostic calls `_Normalise(ctx, False)`. v2.2's signature is
    `_Normalise(ctx, folded, path_ok)`, so that diagnostic should call `parity.ast_diff` instead.
- **Files.**
  - parity.py c886c61b; selftest.py bdb489bf.
  - v2.1 is kept as rm/fold/v22/parity_v21_416a6da1.py.txt and selftest_v21_e73eee83.py.txt.
  - Diffs are rm/fold/v22/parity_v21_to_v22.diff and selftest_v21_to_v22.diff.
  - **Accepted** by the coordinator on 23 Oct (message received 00:37), replacing v2 c0efe8a5 and v2.1 416a6da1.
    The coordinator reproduced the selftest (89, 0 wrong), r21–r28 (only the r24 data-string residual) and the
    refusal-message check. The residuals above are accepted by design. Plan 20 re-pins to c886c61b.

## 12. Rational bookings: the limb rule (R3 ruling on decision 6, 23 Oct; message received 10:37)

R3 of the R1 fold was ACCEPTED at coordinator level, on condition C1 below. The handoff is
rm/fold/HANDOFF-R1-step5.md.

- **The rule** is as v25/bookings.py lines 15-18 declare it:
  - it applies to gmpy rows only;
  - the (|numerator|, denominator) multiset digest must be equal;
  - a size difference must be whole 8-byte limbs, at most one limb per eight values per row;
  - any size difference on a non-gmpy row, or with unequal digests, is a problem.
- **The cap is on the NET size difference per row, not on the limbs that move.** It is a memory-accounting bound.
  Correctness rests on the digests, which fix the values exactly. Nobody should read the cap as absolute: the
  mechanism probe (p6/limb-order-probe.json 02f76eec) moves 1,050 limbs over 2,856 values (0.37 per value) in
  absolute terms, while its net is +24 limbs, inside the cap of 357.
- **Decision 6 ruling:**
  - The literal test (A vs A′ shows the same class of difference as A vs B) is withdrawn as the criterion. It
    presupposed run-to-run allocation noise, and A′ byte-identical to A disproves that noise.
  - The explanation is accepted: allocation is order-determined. gmpy2 reuses freed mpq objects with their limbs,
    and the fold's new package bytes give new cell IDs and so a new sorted order (STATE 05:28). The probe shows
    identical sizes in a repeated order and whole-limb moves on an equal multiset under a cell-ID sort.
  - "B always smaller" (p6: six gmpy rows, 452 limbs, all with B smaller) is an observation, not a correctness signal.
    No recomputation of the real rows' sign or size is required.
- **Condition C1:** the ticketed parity run adds a second B arm, B′, from the same fold, run sequentially like the
  others (rm/fold/run_parity_r7.sh). v25/limbs_r2.py must report A vs A′ and B vs B′ with rows_differing 0, and the
  three booking reports (A vs B, A′ vs B, A vs B′) must be byte-identical. This makes "order-determined" a measured
  property on both sides: a B whose sizes varied run to run would make the limb cap a flake risk for the gate.
- The residual is recorded as RF3 in RELEASE-CHECKS.md §7.

### 12.1 Correction to the decision 6 mechanism statement (coordinator, 23 Oct, after a cold review; verdict unchanged)

The section above is kept as written. Two statements in it are corrected here.

**The mechanism.** The limb differences are over-allocation on equal magnitudes, determined by order. Which mechanism
causes it is unproven. There are three candidates:
- free-list reuse, as in the explanation above. The probe shows reuse can happen, not that it did.
- a different summation order or operand pairing. GMP never shrinks a limb buffer, so a different pre-gcd
  intermediate size persists even on fresh objects.
- mpq values that crossed a process boundary (pickle, from_binary) arrive tight, and both arms ran 12 workers.

The real rows fit the last two better than reuse:
- The probe's reuse is mixed-sign, with B larger. The real rows are one sign, at two derive sites only.
- The endpoint row with 48,866 values moved 0 bytes.

Benign either way. The real guard is that repeats are identical, and that is measured (C1).

**Support from q74 (p20c-r2, 23 Oct 12:43).** In q74, B is larger: 3 gmpy rows, +96 limbs. In q72 (p20c-r1), B was
smaller: 6 rows, 452 limbs. In both runs the repeats are identical. Plan 18's routing fix renumbers the cell ids, so
the order changes. A sign that flips with the order, on equal values, is what a mixed-sign mechanism determined by
order predicts. It is not something a fixed bias between A and B would produce.

**"The digests fix the values exactly."** The value digest uses |numerator|. It proves equal magnitudes, not equal
values. The sign is proven by the records and journal checks.

**The cap.** It is fitted to the data it accepts (0.07 against 0.125). Over-allocation scales with value length, so a
later interval with longer values may trip it. That fails closed: noise to expect, not a risk.

## 13. Later fold items (p20c-r3 re-fold or the next fold revision, whichever comes first; recorded 23 Oct 12:40)

None of these changes q74. They ride together with the next re-fold and its parity ticket.

1. **bookings r3:** record gmpy2.version() and gmpy2.mp_version() in each arm's record. Today the build equality is
   known only by reading.
2. **bookings r3, tight limbs:** for each gmpy row, compute the tight limb count from (n, d) and require
   getsizeof ≥ tight on both arms. Report each arm's gap as over-allocation, whatever its cause.
3. **limbs r3, one-sided cap:** B − A ≤ cap per row. B smaller carries no memory risk. Keep the net form: an absolute
   cap per value would fail the probe's benign reuse.
4. **bookings r3, value digest:** use (n, d), or state the reason for keeping |n|. Until then, records say that the
   sign is proven by the records and journal checks, not by the bookings digest.
5. **Accounting question:** the low_ledger _admit row is exactly half the interval_inventory derive row at both
   stages (1,428 vs 2,856 values; 104 vs 208; 800 vs 1,600). Does the interval row count the ledger's 1,428 values
   twice? The answer goes in the step note before any change.
6. **hcf_prepare r15, cross-composition cell key** (the coordinator's decision; no ID redesign):
   - Match exterior cells by logical_cell_id (content-derived; integration_exterior_mesh.py:693/901).
   - Match collar cells by physical_cell_id (geometric; integration_volume.py:358, row field :656).
   - Together these match all 236 cells. cell_id renumbers with any package byte change, and the 64 collar logical
     ids carry funding_id.
   - r15 adds physical_cell_id to HCF's KEY_FIELDS (:102), as one value replaced, the same way r14 replaces
     EXPECTED_R13. HCF itself stays unchanged.
   - **Route changed in preparation (23 Oct):** KEY_FIELDS is read only by HCF's child, and that child fails
     on any workspace module outside its frozen layout (HCF:268-272, 309), so a wrapper cannot replace it. The cell
     key is saved instead by arms_r7's child at the same return point, with kind and physical_cell_id among its key
     fields, and compared by v27/cells_keyed.py in run_parity_r9 (an r2 reference arm R; cells-ra, cells-ab, each
     required to match 172 exterior and 64 collar cells). hcf_prepare_r15 is prepare only. R3-STEP-NOTE.md has
     the detail.
7. **Fold mutant, sibling helpers layout must refuse** (from the storage cold review):
   - Under option (b), the retargeted key atlas_tectonics/_private/native/wp10_zstd.dll is found only when the folded
     helper sits inside the package root that holds atlas_tectonics/. The r11 test test_wp16_preadvance.py:223
     arranges exactly that.
   - A fold that keeps a sibling helpers/ folder finds no ancestor and refuses at preflight, failing closed.
   - Add a mutant proving that refusal.
8. **RF2 owner change** (rm/fold/RF2-DESIGN.md): an environment-anchored MPFR path in the two embedded sources, in
   p20c-r3. The fold then retires the two `carry` decisions by declaration.
   - **Withdrawn from r3 (coordinator, 13:00):** the MPFR load pin goes to Michael as a backlog decision, and r3
     changes neither compiled_dot, the certification kernel nor its resources. The two carries (FP:999, FP:1006)
     stay, and the fold stays PRIVATE.

**Status, 23 Oct 13:45:** items 1-7 are prepared as tools, and none has run on r3. Items 1-4 are arms_r7 and v27
bookings/limbs_r3; item 5 is answered in R3-STEP-NOTE.md (each singleton is charged twice); item 6 is above; item 7
is mutants_r4, which passes 14 of 14 on the r2 fold. The r3 run order is under "At staging" in R3-STEP-NOTE.md.

## 14. r4 retarget and the RF2 decision (23 Oct, written 19:46)

**Retarget (coordinator, 19:20 and r4 staged at about 19:40).** p20c-r3 (72fd75fa) was superseded before
qualification, and its post-apply run is void. The fold's target is p20c-r4: Plan 20 r12 and RF2 on Plan 18 r5.
- **Identities:** composition 21e666b8, run manifest 5cb8d0af, profile 338adae2, BUILD-RESULT 8c379fac,
  constructor 057d8b19. Plan 20's bind check is integration-r4/bind/check_fold_r4.py b4d084af.
- **Against p20c-r2:** 10 changed, 3 added, 628 kept. r3p/dry/compare.json is PASS with every sha as listed:
  - r12: CRP 17abf869, LG 07154a51, test_wp16_preadvance 89a85a2a;
  - RF2: the host private_heat_functionals_parallel_r1 554e68b7;
  - Plan 18 r5: content_cache 85fe9a5f, partition_routing_patch ffb95381, test_retained_handle_check 8b3c8ed1, and
    r4's bytes for the other six tests.
- **Protected identities unchanged:** compiled_dot e0be3a30, certification kernel 4099a297, certification resources
  40943b9c.
- **The tools need no change for the retarget,** because the composition is an argument. hcf_prepare_r15 takes the r4
  record (6bf1e79a).

**Correction to §13 item 8.** Only the MPFR *load pin* was withdrawn from r3. RF2's path anchoring is in r3 and r4.
- FP 554e68b7 rewrote both embedded sources with no machine path. The MPFR library path is now
  `_ASSEMBLY_MPFR_PATH`, joined from sys.exec_prefix and injected.
- So FP:999 and FP:1006 are no longer abs sites. Their two `carry` decisions retire by declaration
  (r3p/mk_declared_r12.py 3566ad87 → declared-r12.json 2b1a0fa8).
- With those two retired, every other decision moves along its line map: 460 decisions, 22 moved, 2 retired, 0
  added. The routing site lands at line 598 on r4 (576 on r3).
- The r4 dry fold (synthetic trace) is PASS with private [], and the literal scan finds 0.

**RF2 decision (coordinator, 23 Oct about 19:40).** RF2 closes at the r4 fold if all three hold:
- (a) the real r4 fold reports private: [] and the literal scan finds 0 private names;
- (b) r9 parity passes on r4;
- (c) the r4 arms record which MPFR library file actually loaded (resolved path and sha256), and it is the same file
  in every arm.

Once RF2 is closed, the fold is "ready to publish". Publishing is Michael's word: the targeted public copy is
prepared but not pushed. (c) needs a tool change, because no arm records the DLL today: arms_r8, wobs r2, and an r9
check. It was proposed at 19:42 and nothing is changed before the coordinator's yes.

**Rehearsal on p20c-r3 (q87, 19:34-19:41, peak 0.92 GiB): FAIL at mutants.** The steps up to and including the
fold passed.
- **rows:** all 236 cells are bitwise equal to p20c-r2. This is the early answer that Plan 20's r3 changes keep the
  W4 numbers.
- **mutants:** the 8 r3 mutants are ok. The 6 data-key preflight cases ERROR, because r12's task_file calls a new
  module-level `_holds`, and the mutants_r4 preflight executes only task_file, the CAPTURE_* assignments and
  capture_backend.
- **Fix, proposed and awaiting yes:** the preflight also takes the module-level functions those call, transitively.
- Detail: rm/fold/R3-STEP-NOTE.md, "r4 retarget, rehearsal and the RF2 decision".
- **Fix 1 approved and applied** (mutants_r4 d97ab0a4). The real prep q89 ran it: mutants 14/14.
- **Fix 2 approved and applied:** the native library record (arms_r8 e234562e, wobs2 b51c8017, v27/mpfr_same
  e442cd1e). The workers deviation is accepted: (c) closes on the five arms, and any uncovered worker makes the
  worker line INCOMPLETE without blocking (c).
- **q89 (prep on p20c-r4): PASS**, 7 min 22 s, 0.96 GiB. RF2 condition (a) is met: private [] and 0 literals.
  MANIFEST is 1d6f7ea3 and rows are bitwise equal on 236 cells.
- **Known cosmetic defect:** run_parity_r9.sh (8a89fa63), as generated, keeps r8's header lines 2 and 4 ("arms r7",
  "runq small"). mk_r9 edits only declared lines, and these were not declared. The body runs arms_r8 as a normal
  queue ticket (q90). The generated file is left as it is.
- **Carried for final assembly** (not a fold item): p20c-r4 does not carry Plan 18's endpoint look-ahead (stage 77;
  the volume auto module moves from 2b9d9fc5 to 96cbf772).
- **q90 (r9 parity on p20c-r4): PASS**, 14 min 15 s, 1.01 GiB. All five children passed, and so did records,
  noise, bookings, limbs, cells-ra, cells-ab and mpfr. Every arm loaded the same libmpfr (b81a548e), at FP's
  exec_prefix path. Workers: 51 of 60 covered, all with the same file (INCOMPLETE by rule; this does not block (c)).
- **RF2 CLOSED (23 Oct 20:30):** (a) q89, (b) q90, (c) q90. The fold is "ready to publish"; publishing is
  Michael's word. Return: rm/fold/PLAN20-RETURN-R4.md (b68dbbc9).
- **Worker-coverage correction:** the heat workers do load MPFR, through FP's native binding (not gmpy2, which is
  why the q74 snapshots showed no gmpy2 module). The accepted rule (at most one, the same file) held for all 51
  covered workers. The 9 uncovered workers are those the pool ends without an exit snapshot.
