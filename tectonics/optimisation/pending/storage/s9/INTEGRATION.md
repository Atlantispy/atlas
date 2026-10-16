# S9 integration note: metric_identity reuses the CompactMesh seal (unscoped views)

From "Small optimisations", 16 Oct 2026. This is a DRAFT; it becomes final once q20 reports (the tests and refuter mutants
are in). It is for "Runner pipeline and final integration", who applies it. Design:
T/fidelity-integration-20261005/claude-review-steps1-7-20261015/fixes/backlog/item13-design.md §B.

## What it does
`private_heat_indexed_runtime.metric_identity` used to stream the whole legacy record a second time for an unscoped
CompactMesh view, after `CompactMesh.__init__` had already streamed it and sealed it against `geometry_id` in this
process. The candidate adds `_sealed_unscoped_identity(view, cancel)`:
- It reuses that seal only when **all** of the following hold:
  - the arrays are still the one funded, read-only, bytes-backed allocation;
  - the reader is a plain blob reader (no `iter_json` or `export`) and there is no segment;
  - the support source passes `check_unchanged()`;
  - the seal is LEGACY and names this `geometry_id`.
- It keeps every support-blob read of the full stream exactly: `_view_allocation`, `view._check()`, `reader(ident, size)`,
  then the same type/len/sha256 refusal, with `R.check(cancel)` per blob.
- It skips only the row re-encoding, which is a pure function of the frozen, sha-identical arrays.
- Anything else returns None and the original full stream runs.

The returned identity is the same value; r13's `meta['geometry_id'] == metric_identity(...)` check is unchanged and
still runs. No numbers change.

## Change (owner file unchanged since my base)
| File (owner path) | Base sha256 | Candidate sha256 | Diff |
|---|---|---|---|
| composed-r2/helpers/private_heat_indexed_runtime.py | 997277d8 | ec170fc4 | T/so/s9/private_heat_indexed_runtime.diff (97 lines) |
| new: test_s9_seal_reuse.py | - | 341ae911 | 12 cases (3 added for the refuter's P3 mutants) |

## Composition (generation note needed: explicit repin)
1. Repin `private_heat_indexed_runtime.py` 997277d8 -> ec170fc4 in composed-r2/composition.json (line 122). Add
   test_s9_seal_reuse.py beside test_private_heat_indexed_runtime.py (264c1c47, unchanged).
2. Generation note: "S9/item 13 seal-reuse generation: metric_identity reuses the in-process CompactMesh seal for
   unscoped views, keeping every support read; private_heat_indexed_runtime 997277d8 -> ec170fc4; + test_s9_seal_reuse
   341ae911".
3. Composition hashes that bind this file (route records, frozen-check inventories) move with the repin. Arrays don't.

## Proof
- Refuter: the first pass found a P1 (closure readers were never re-read). It is FIXED: every support read is kept.
  The delta re-review PASSED with no P0-P2 (T/so/refute/s9/delta-review.txt). Its three surviving P3 mutants
  (no_loop_check, no_iterjson_guard, no_owner_count) now have tests.
- Tests (T/so/s9/tests-r6.log; run_all_tests.sh, base then candidate, one process per module; the loaded lines confirm
  which runtime ran), 16 Oct 14:46:
  - test_private_heat_indexed_runtime: base 4 OK, candidate 4 OK. test_differential_mesh_v3: base 2 OK, candidate 2 OK.
  - test_s9_seal_reuse: candidate 12 OK. On base, 8 pass and the 4 that assert no second stream fail, as expected.
  - test_ram_context_indexed_patch: setUpModule ERROR on base AND candidate ("unbound import in composed heat
    helpers: geometry_transfer.py imports partition_v2"). This is pre-existing and not S9: your diagnosis was the
    legacy-route import fence against geometry_transfer's lazy partition_v2 import, and its fix belongs to
    geometry_transfer's owner. Re-run this module once that lands.
- Refuter mutants (T/so/s9/mutants-r2.log; r1 ran with a broken test and is superseded): each of the 7 mutants is
  killed by its specific test (no_sha, no_loop_check, no_iterjson_guard, no_owner_count, skip_last_blob,
  no_loop_rcheck, no_source_check); the unmodified candidate passes 12/12.
- W4 before/after, q20 (T/so/s9/w4/t1; base cand cand base on heat_control_on_frozen.py child, unchanged):
  - each arm must PASS its own frozen check against g13-same-call-live1 (2561b092) with identical array digests;
  - the cand arms must have loaded ec170fc4 from w4/cand-src;
  - summary harness summarise_s9_w4.py fails closed; 17 planted faults are in w4/mutants-summary-r1.log.
  - Numbers: PENDING.
- Ruff F,E9,B,PLE, base against candidate: no introduced findings.

## Gain caveat (refuter P3)
The 1.5-1.9 s per advance projected in item 13 was for the whole stream. The candidate keeps the support reads, and
for the r2 store reader each read builds a workspace and hashes whole chunks. The measured gain is therefore q20's
number, not the projection. If q20 shows no gain, S9 is not enabled.

## Later-step impact
Each heat advance on an unscoped view saves the row re-encoding of one full legacy stream. Restart and reopen views
are scoped or segment-backed, so they take the full stream as before. Next-interval capacity: no new memory, since
the support reads charge less (size+64 KiB rather than 2×size+64 KiB plus decode).
