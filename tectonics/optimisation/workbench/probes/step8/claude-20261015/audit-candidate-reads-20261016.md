# Same-interval candidate re-reads in the live advance and finish path (audit, 16 Oct 2026)

A read-only audit (one Explore agent, 25 min). It covered the live advance and finish path of one
interval, for any re-read of an object written earlier in the same interval, from the unsealed
candidate. Excluded: `test_*`, `measure_*`, `*ref_*` copies and every `bridge` folder. Nothing was run
or edited. F = read in code; I = inference.

Abbreviations:
- RC1 = `R/composed-r1/runtime-src/atlas_tectonics/integration_regional_workflow.py` (b8175261).
- JC = `heat-repair-20261007/source/tectonics/tests/i04_differential_joined_control.py`.
- JH = `R/composed-r1/helpers/private_heat_original_joined_r6.py`.

**Why candidate reads are slow (F).**
- `_Segment.cache` is decided once, when the view is built. `cache_identity()` returns None whenever the
  resolver has `.interval` (C/segment_store.py:514-526).
- So every scalar read becomes `segment.read(name, i, i+1)` (C/record_views.py:385-387): one page walk
  (manifest resolve and parse) plus one chunk decode with `_blob_id`.
- The CompactRestartStore facade forwards `.interval` (R/compact_restart_store.py:153-159), so views
  opened through it are uncached too.

## Status per finding

| # | Re-read | Cost | Status |
|---|---|---|---|
| A1 | live_mesh_patch.finish `adapter.open` after publish (C/compact_store.py:561-697, `mesh_from_segment` `_validate` + `iter_legacy_json`) | per-scalar: more than 24 min 53 s on the authentic IV1 mesh (profile r5) | **FIXED 16 Oct 06:05.** The produced view is kept and bound to the published root: `live_mesh_patch._published`, `mesh_tables.bind_published`, decision-05. |
| A2 | differential_mesh_patch.produce publish then open (C/differential_mesh_patch.py:45-46) | per-scalar | Not on the live path: live_mesh_patch replaces this tail in the live composition. **Recommend** routing `produce` through `live_mesh_patch._published` or retiring it, so no second route keeps the reopen. Owner to confirm. |
| A3 | every later reader of the reopened mesh: (a) coverage gate R/compact_restart_patch.py:15-60; (b) heat inputs C/private_heat_mesh_patch.py:154-186, C/heat_payload_indexed_patch.py:150-191, C/private_heat_indexed_runtime.py:47-60; (c) heat-ledger IDs C/heat_ledger_tables.py:149-165 and `_MeshIds.iter_json`; (d) state issue C/spatial_indexed_patch.py:226-332 (four full mesh streams); (e) joined finish and grouped account | per-scalar on the A1 route | **FIXED with A1.** All of these now read the in-memory columns. The heat-ledger mesh binding still records the published segment ref. |
| A4-A7, A15 | partition verify, `persist_mesh` reference checks, republish root re-check, successor head manifest re-read, `store.metadata` x4 | index level, cheap | Leave. |
| A8 | publication check inside the writer transaction (spatial_records_patch.py:582-611, `verify_records`) | index level | Leave. |
| A9/A10/A11/A13 | the post-publication `_refresh` (RC1 1038-1238) re-reads every successor record per node | **per-node and per-scalar** (decision-05: 40-min reopen; heat ledger 2,402-2,454 s) | Avoided only if the R2 token adoption (A9, publication_token_transform) or `postpublication` (A10, compact_restart_patch) is composed. See D2. **For the Step 10 composer.** |
| A12 | `_check_reopened` streams `iter_legacy_json` of both sides (JH:110 -> C/private_heat_indexed_runtime.py:127-163); with the token set it compares the mesh with itself | two full streams | Now in-memory CPU (A1). Time: profile r6, `mesh-streamed-in-memory`. |
| A14, A16, A17 | bounded_preseal, seal digest and file hash, duplicate-chunk compare | bytes and index | Inherent to the seal. Leave. |
| X1 | `_publish` -> `_validate_differential_solution` -> `current_geometry` -> `_refresh()`, because the heat checkpoint save changed the token (RC1 1543-1545, 1572, 1266-1268) | **full parent restore before every `put`**: in IV1 `restore_migrated_root` (open_records of the interval-0 state bundle through the uncached facade); from IV2 on, the full cold restore of the previous successor (I) | **Open, for the RC1/Step 10 owner.** Keep the token current across the heat checkpoint save, or let `current_geometry` use the live object. |
| X2 | each heat `_verify_call` -> `_origin_signature` re-streams the parent state and parent mesh (issuer r12:190-209, 497-501; C/spatial_indexed_patch.py:235-281) | parent data, uncached | **Open.** Heat side (mine): the issuer is H (read-only), so the fix is a composition-level cache of the verified origin signature. Storage side: whether sealed parent reads through the facade must be uncached (S1). |
| X3 | about 10 `store.metadata(root)` rebuilds of the 337 KB root fields | chunk level | Leave (one rebuild is a few ms). |

## Could not resolve (for the composer)
- **D1. The A1 wiring is not in the sources yet.** No production code passes `compact_context` with a
  resolver; JC builds the mesh without it.
  - The Step 10 composition must wire `{'resolver': candidate, 'support_source': S, 'producer': digest}`.
  - S must be the in-memory partition's SupportSource (`support_source(view)`). `open_support_source(candidate, ...)` would be a per-node partition reopen.
- **D2. The R2 transform and `partition_workflow_transform.transform_v2` cannot be chained as written.**
  Both demand the exact RC1 digest. No tree has both `_r2_metadata_chain` and
  `_RESTART.postpublication`. The composer needs the second transform pinned to the first's output
  digest.
- **D3.** Read counts for A3/A12 were not measured. Profile r6 gives the in-memory stream time.
- **D4. Two likely blockers on the post-publication path (I, not run):**
  1. **(spatial, not mine)** `compare_spatial_records` asserts equality on two different `cells`
     RecordRef borrows (C/spatial_indexed_patch.py:199-200). RecordRef has no `__eq__`
     (C/record_views.py:1011), so the check probably fails.
  2. **(heat, mine; CONFIRMED in code)** JH's two-scalar inspection edit reads
     `heat._result._snapshot._metadata` (JH:98). The compact r13 CompactHeatSnapshot has no `_metadata`
     slot (C/heat_ledger_tables.py:232), so the read raises AttributeError.
     - `heat_ledger_issuer_patch.joined_source` rewrites the joined consumer's reads, but not JH's edit.
     - JH's failure-only replay (`len(repeated._snapshot._metadata)`, JH:30) has the same issue for a compact transport result.
     - Fix (heat, mine, queued): a new JH revision for Step 10 that reads both scalars through `HEAT_COLD.ledger_access`, as the consumer does.

## Checked and already avoided
- **Partition:** publish, then bind with no reopen.
- **Spatial, certification and differential records:** written from in-memory columns, and the recipe
  proofs run in memory.
- **Heat:** the r4 save does not reopen.
- **bounded_preseal:** never decodes, and the mesh identity check is O(1).
- **Live producers:** no store access.
- **`endpoint_record_identities`:** on the root-only branch only.
- **v1/v2 adapters:** refuse non-ArrayStore stores.
- **`metric_identity`:** reuses its seal.
- **`spatial_audit_arrays` and `retained_inventory_accounts`:** fresh reader only.
