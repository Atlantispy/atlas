# Part-implemented work (16 Oct 2026)

Status: WORKING NON-CANON. Work stopped at a weekly usage limit. Each entry gives the state, where the files are in
this snapshot, what is left and the acceptance gate. Paths are relative to `tectonics/optimisation/`. "Built" means
implemented and focused-tested, with its proof run still pending. Proof runs need the private inputs and pinned
identities, which are not in this snapshot.

Rules that apply to every item below:
- Exactness first. Each change keeps physical results bit-identical, or changes only listed identity fields under
  field parity. No tolerance is relaxed. No in-run guard is raised: 12 GiB RSS, 1 GiB free floor, 16 GiB logical,
  256 MiB caps, the 1 MiB integer limit and the 256 accepted-step ceiling.
- Every process that imports the runtime pins `PYTHONHASHSEED=0` and fails closed unless
  `sys.flags.hash_randomization == 0`. Do not run it under `python -I`, which ignores the variable. Production
  parallel scheduling depends on seed 0. `-I` is only for helpers that never import the runtime.
- New revisions are new files. Earlier revisions and old run records are never edited.
- A harness or comparison tool gets an independent refutation pass, with planted failures, before its proof run.

## Start gate sized by need

- **State:** Route1 and Route2 callers, runner and adjacent launcher are installed
  together in the private workspace. The subsequent loader repair admits both
  current producer metadata shapes. Source copies and exact export scope are in
  [workbench/plan02](workbench/plan02/README.md); this public snapshot is not a
  native installation. Retained private checks cover local integration and the
  repair within their declared scopes.
- **Left for Plan02:** corrected positive prepared-state publication and
  independent reopen, then requested end review. Those runs remain deferred.
- **Later integration:** bind the selected generation in the actual replay/final
  assembly at its separate plan stage. That future stage does not block Plan02
  completion. All interval and individual holds remain.
- **Gate:** available memory must cover `P + ceil(P / 5) + 2 GiB` for the selected
  predicted peak `P`; in-run guards are unchanged.

## Interval-N driver (continuation)

- **State:** the interval-N chain and S1 query-stage changes are applied to this branch from `ac/r/chain-r3`, step
  `item21-r3-verdict-pin`: fresh-run, reopen and launch drivers, their three tests, and `test_s1_query_stages.py`.
  Focused private evidence is reused for those exact source bytes; method notes are in `drivers/INTERVAL_CHAIN.md`.
  This is branch code application, not live runtime replacement, a manifest re-pin or scientific acceptance.
- **Left:** finish-driver S1, geometry and S2 capture-writer work are unchanged and remain pending in the ordered
  final composition. The S1 query-stage changes do not complete the separate S1 heat-finish work. All run holds remain.
- **Gate:** a continued interval is bit-identical to one produced by the reference route from the same sealed start.

## Pose and heat-number width

- **State:** design accepted (`pending/pressure/width/DESIGN.md`, rounding the pose and summing the outward deviation
  bound). Conditions 1-3 pass. On the pose path the proven bound is under 0.049% of the actual certified radius,
  and the measured end-pose change is 0.010-0.033% (up to 1,000 intervals, four histories), against a limit of 1%
  cumulative over 1,000 intervals. Bounded heat values grow by at most a factor of (1 + 2^-11).
- **Left:**
  1. Condition 4, the interval-1 replay with both arms (about 5 h). `dump_arm` r1 is usable. `compare_arms` r1 was
     refuted: it accepted any 64-hex change as an identity, matched geometric `radius_m` as a radius field, fixed a
     field's kind by its first leaf, skipped the interval-1 partition, read `0x` exact integers as ids, and passed
     identical arms. Write `compare_arms_r2` and `dump_arm_r2` as new files, with each reproducer as a planted
     failure, then refute again. The replay job script is designed but not written. It waits for the start gate.
  2. Open choice: whether a candidate arm that stops repeatably (memory limit, native crash) while the reference
     completes is FAIL or VOID. Either must block acceptance.
  3. Geometry integration after the rounding lands, then the width gate re-pin and an identity successor.
- **Gate:** zero refusal flips, and the change stays under 1% of the certified error.

## Pressure stage speed

- **State:** the parallel wall routes (P1-P3) are built and verified on a small case (`pending/pressure/c/`). The
  measured small-case total is 108.3 → 45.9 s. The stage profile on real interval 1 has not run.
- **Left:** the profile run, then the full-scale proof. P4 is not built; its
  separate integration can use the repaired shared primitives in `workbench/plan06/`.
- **Gate:** byte-identical pressure records against the serial reference.

## Exact heat kernels

- **H3 (heat certification kernel):** revision 3 accepted (cache names fixed so the identity guard sees the loaded
  implementation); its proof run has not run. Files: `pending/kernels/l3r3/` and `pending/kernels/h3/`.
- **D5 (exact twin and GMP wall measures):** repaired and privately integrated;
  source snapshot in [workbench/plan06](workbench/plan06/README.md). Rebuilt
  exactness/accounting checks passed. Measured kernel regressions justify
  keeping it disabled. Final selected Plan31/N9 binding and collective review
  remain open; the original refuted sources are retained.
- **L4 (interpreter binaries in identity):** approved, not started. It touches the shared runtime record in `reuse`,
  so the change needs review before it starts.
- **G-PY:** revision 3 passed parity. Revision 4 waits for the stacked geometry parity and replaces revision 3 at
  landing.

## Parallel start-up (per-world admission)

- **State:** ip9 build (`pending/kernels/initpar/`, transform `pending/kernels/transforms/initpar_r1.py`) passes its
  checks and smoke run; the proof run has not run. ip9 supersedes ip8.
- **Gate:** fails closed unless workers are actually adopted; the store must match the serial run byte for byte.

## Geometry

- **Done:** Step 10 parity on real intervals 1 and 2. Six stages, no violations, structure identical to the reference
  except 245 charts no longer started. Surface CPU time: interval 1 893 → 454 s, interval 2 885 → 620 s (MEASURED,
  serial shards). D1+D2 transforms 70/70.
- **Left:** three proof runs: the six-worker interface rerun on interval 2, jets parity revision 2, and the stacked
  D1+D2+G-PY parity. Then endpoint batching (WP18 revision 2: refutation, smoke, proof). Projected interval-2
  endpoints 402 → about 217 s.

## Heat finish and reconstruction speed

- **H1c:** the four-route heat proof has not run; the full ABBA timing runs only after it passes. Harness and job
  scripts are in `pending/heat/scripts/` (latest revisions are the highest-numbered files).
- **H5a:** kept; its comparison is part of the H1c proof.
- **S1:** 30/30, not refuted; lands in the final assembly after H5a.
- **Stage markers:** the seam is decided (a fail-closed closure seam); its test is red by design until the finish
  driver is built. The S2 speed-up waits for the markers; S4 waits for the commit markers.

## Storage

- **Merged:** sealed interval-1 heat reopen 46.1 → 15.7 s (MEASURED), in `composed-r2/helpers/segment_store.py`.
- **L3:** design accepted; build not started.
- **WP12:** accepted on condition that a guard-equivalence section is written first.
- **Known test failure:** `test_wp10_integration` swaps `sys.modules` entries at module level, which leaks into the
  step-7b tests. Fix: restore them in `setUpModule`/`tearDownModule`, then run the 17-module step-7b set. Do not mark
  it as expected.

## Small optimisations

- **S2 (capture writers):** revision 9 final for exactness (37/37 mutants killed). Its before/after timing has not run.
  The capture library path must become package-relative, with the native library carried in the package and pinned.
- **S9:** held until its harness smoke and mutants pass.

## Final assembly and landing

- **Assembly:** the assembly manifest is accepted as a draft (`pending/storage/assembly-manifest.md`). Order: freeze
  the manifest, assemble with pins, build the frozen final composition, then write the acceptance record.
- **Helper fold:** design accepted (`docs/release/FOLD.md`), with its parity checker. The fold transformer and its
  parity arms are not written.
- **Landing on remake:** the changed test expectations (`docs/release/EXPECTATIONS.md`, groups A-D) are accepted. At
  landing, re-run the expectation check and refuse if any bound is looser, record the new I03 state ID as a successor,
  and state where I04 feedback controls use the cell-mean approximation. Landing waits for the identity generation and
  the helper fold.
