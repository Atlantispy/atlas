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
   - For F6, require B ≤ A.
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
