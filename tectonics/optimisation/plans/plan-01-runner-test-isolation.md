# Plan 01 — Runner test isolation and module leak repair

**Item ID:** 01  
**Retained owner:** Runner / Claude  
**Status:** WORKING NON-CANON. Reviewed test-only repair published as a workbench successor; frozen composed-r2 remains unchanged.
**Scope:** Test-only repair of the import-time state leak in `C/test_wp10_integration.py`, followed by the existing named 17-module regression when authorised.  
**Completion condition:** Candidate setup no longer contaminates test discovery; deliberately replaced module bindings, the parent-package attribute and `sys.path` are restored after successful or failed setup; the canonical suite has no failures or errors; the successor failure record reflects the actual result.

## 1. Authority, sources and paths

This document grants no new implementation or execution authority. Preserve separately established authority, the retained owner, source freezes, queue requirements and individual holds. N9 remains **PAUSED BY USER** and fresh full-interval runs remain held. This repair is not scientific acceptance, final integration or publication.

Path aliases follow the Runner handoff:

- `T` = `C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10`
- `R` = `T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1`
- `C` = `R/compact-geometry-r1`
- `D` = `R/probes/step8/claude-20261015`
- `S` = `R/probes/step9/claude-20261016`
- `P` = `T/.r44-env/Scripts/python.exe`
- `B` = `T/fidelity-integration-20261005/claude-review-steps1-7-20261015/fixes/backlog`

Primary evidence read for this revision:

| Source | Relevant evidence |
| --- | --- |
| [Current consolidated status](C:/Users/LOCAL_USER/OneDrive/Documents/GitHub/atlas/.atlas-dev/plan-status-20261016.md), “Drivers, admission and proof tools” and “Order and unchanged acceptance boundaries” | Current ownership, outstanding isolation repair, conditional ram_context readiness issue, published start-gate wiring and holds. SHA-256 `be270e6898e0b1d5aa0c7d29065baf1d4df16ece34490f17d7c68a9d77d4339e`. |
| `D/STATE-NOTE.md`, wind-down section D, lines 128–144 | Diagnosed leak, before-copy rule, named test order, planned command and booking, successor failure-record requirements. SHA-256 `3556ac777b8fd632a68c6204575ca767b0e46600944d4a6c8391ce557cd6d312`. |
| Same handoff, lines 249–251 and 477–478 | Historical post-merge result and peak; actual ram_context diagnosis and owner referral. |
| `C/test_wp10_integration.py`, candidate construction and `--fresh` entry | Import-time path insertion, three module replacements, parent storage attribute and separate fresh-reader route. Handoff prefix `8d586e4635b4a58c`; prefixes are discovery references, not full acceptance pins. |
| [Current queue protocol](C:/Users/LOCAL_USER/OneDrive/Documents/GitHub/atlas/.atlas-dev/run-queue-protocol-20261016.md) | Execution and resource rules for any authorised run. |

Later authoritative decisions take precedence over older handoff status. Recheck affected source identities before implementation and retain full pins in the existing owner evidence. Unsupported literature claims and invented implementation examples have been removed.

## 2. Diagnosed problem and retained evidence

At import time, `test_wp10_integration.py` prepends paths and constructs transformed candidates through `_candidate_module`. That helper writes into `sys.modules` before executing candidate code. The test replaces `segment_store`, `interval_store_set` and `atlas_tectonics.storage`, and sets the parent package's `storage` attribute. Later modules in the same process can receive those candidate bindings.

The Runner handoff identifies the resulting failure as:

```text
test_step7b_segments.Step7BSegmentTests.test_one_index_walk_exact_native_payloads_descriptors_and_empty_arrays
```

The diagnosis is retained evidence; the repair has not yet been demonstrated. `C/test_step7b_segments.py` remains unmodified.

| Classification | Evidence and meaning |
| --- | --- |
| **MEASURED / retained result** | `S/b17m-post.*`, 18:21 post-merge check: 17 modules, 235 tests, one failure and eight skips (`STATE-NOTE` lines 129 and 249–251). Line 251 records a 0.42 GiB peak. These are historical results, not required future counts or a memory ceiling. |
| **PROJECTED / planning estimate** | `STATE-NOTE` line 137 estimates approximately five minutes and 0.42 GiB for the next named check. No precise 300-second or 450-MiB acceptance limit is established. |
| **Existing proposed booking** | The owner's next command requests one core and 1 GiB in the small lane. Booking is distinct from measured usage, acceptance and in-run guards. |

Record actual counts, skips, duration, memory observations and failures from a subsequent authorised check. Do not invent a passing transcript or add skips to reproduce historical counts.

## 3. Bounded fixture repair

Create the owner's before-copy under `D/before-src/` before changing the test. Keep the repair in `C/test_wp10_integration.py` unless a concrete dependency requires a separately authorised change.

1. Move candidate construction and its relevant import, module, parent-attribute and path mutations out of module-import time into `setUpModule`. Taking a snapshot there while candidates are still constructed during discovery is insufficient.
2. Capture original presence and object identity for the three affected `sys.modules` entries, the parent package's `storage` attribute, and the original `sys.path` state before the first relevant mutation. Preserve absent-before cases as well as existing objects. Account explicitly for a parent binding introduced or changed during setup.
3. Register restoration with `unittest.addModuleCleanup` before any potentially failing mutation or candidate construction. Restoration must run even when `setUpModule` fails; relying only on `tearDownModule` leaves that path uncovered.
4. Restore deliberately touched bindings and path state exactly. Do not purge every module imported during the test or delete unrelated legitimate imports. Keep candidate handles within the fixture's intended use.
5. Preserve the separate `--fresh` reader entry: candidate initialisation must still happen explicitly under that route, with appropriate cleanup. `setUpModule` is not automatically called by this custom branch.

This is an implementation specification, not a supplied replacement implementation. No generic sandbox framework is required.

Do not add skips or xfails, alter expectations or numerical tolerances, or reorder tests to hide the failure. Any necessary non-test code change invokes the owner's existing D-b byte-identical check plus one refuter. A method or accuracy issue returns to the coordinator as a decision.

## 4. Separate ram_context readiness issue

The former relative-import diagnosis and standalone `ram_context.py` loader are removed. `STATE-NOTE` lines 477–478 attributes the retained failure to a **legacy bundle fence versus `geometry_transfer`'s lazy `partition_v2` import** (`51cad40f`, line 182), reports the real composition unaffected, and records a recommendation for a `sys.modules`-based `_is_v2` to its owner.

The current consolidated status retains an import-binding readiness check **if still applicable to the selected composition**. Its owner should establish applicability and resolve any remaining failure through the existing composition contract. This plan does not prescribe a loader bypass, take over that work, claim the recommendation was implemented, or hide an applicable failure as expected.

## 5. Verification when authorised

Use a bounded fixture check to establish restoration after normal completion and setup failure, including existing-object and absent-before cases, parent-attribute restoration and path restoration. A deliberately omitted restoration in a disposable fixture should be detected. This addresses the failure mode without automatically adding a second full reverse-order suite or a new standalone refuter framework.

Then use the existing single-process `S/run_b17_merge_tests.sh` harness in its canonical order:

1. `test_b17_binding_directory`
2. `test_item14_page_layer`
3. `test_segment_store`
4. `test_s1_sealed_read`
5. `test_record_views`
6. `test_raw_sidecar_store`
7. `test_storage_codec_patch`
8. `test_storage_codec_followups`
9. `test_wp10_integration`
10. `test_w1_segment_fixes`
11. `test_step7b_segments`
12. `test_record_tables`
13. `test_w3_validate_stream_once`
14. `test_wp6_streamed_validation`
15. `test_capacity_failure_chain`
16. `test_record_builder_honest`
17. `test_step7b_record_reuse`

The following is the owner's **planned command**, not an instruction to execute during this plan edit. Run from `T/q`; resolve the aliases above and choose a new tag. The harness refuses an existing tag. Its handoff prefix is `5144804f`; verify the selected harness identity rather than silently repinning it.

```bash
PYTHONHASHSEED=0 "$P" -B -I runq.py small --cores 1 --gib 1 -- \
  bash "$S/run_b17_merge_tests.sh" "<new tag>" \
  test_b17_binding_directory test_item14_page_layer \
  test_segment_store test_s1_sealed_read test_record_views test_raw_sidecar_store \
  test_storage_codec_patch test_storage_codec_followups test_wp10_integration \
  test_w1_segment_fixes test_step7b_segments test_record_tables \
  test_w3_validate_stream_once test_wp6_streamed_validation \
  test_capacity_failure_chain test_record_builder_honest test_step7b_record_reuse
```

Here `-I` applies to the queue helper. Runtime-importing children must retain applicable seed/environment rules; do not copy isolation flags into them indiscriminately. Use the current queue protocol and preserve freezes and holds. The queue's 1.5× elapsed-runtime escalation rule is not a memory multiplier, automatic termination or new acceptance limit.

## 6. Completion evidence and integration boundary

The [reviewed test successor](../workbench/compact-geometry-r1/test_wp10_integration.py) moves candidate construction out of discovery, registers scoped cleanup before mutation, restores state after normal and failed setup, and preserves the explicit fresh-reader cleanup route. The [five-case fixture checker](../workbench/probes/step8/claude-20261015/plan01/plan01_fixture_check.py) includes an omitted-restoration fault.

Retained original-environment evidence records 5/5 fixture checks and the canonical 17-module suite: 235 tests, zero failures/errors, eight existing skips, 263.896 seconds, queue tree peak 0.40 GiB. The successor failure set is empty; no skip, expectation, tolerance or order was changed. These are historical private-environment results, not new public-checkout runs. Original tested source SHA-256 is `7e5d6b7477def80f3cb968215a50d2cd832203be35e5118e08cc7277b36202b9`.

The separate ram_context issue does not block this passing test-only repair; its applicability remains an owner decision for the eventual selected composition. The workbench source preserves the frozen composed-r2 helper and its original manifest pin. Publication does not change the live runtime, repin a composition or establish scientific acceptance.

Plan 01 is not a prerequisite for the already published item21 Route 1 wiring. Plan 02's selected-generation integration and all scientific-run holds remain separate.
