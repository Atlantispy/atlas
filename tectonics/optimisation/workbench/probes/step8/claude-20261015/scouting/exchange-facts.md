# Facts for redesigning the two cross-holder repacks (Step 8 / WP14)

Everything below comes from reading the code, plus four small read-only scripts in my scratchpad. Those scripts printed the transformed `finish` sources, and listed the diagnostics' top-level keys and retained-stats checkpoints. Nothing was edited and nothing was run beyond that.

Path aliases:
- **C** = `…/resumability-r1/compact-geometry-r1`
- **R** = `…/resumability-r1`
- **I** = `…/runtime-integration-r1/runtime-src/atlas_tectonics`
- **H** = `…/heat-repair-20261007`

Scripts (read-only, absolute paths):
- `<SCRATCH>`
- `…\scratchpad\diag_keys.py`
- `…\scratchpad\retained_stats.py`

---

## 0. Which finish runs in the live composition, and the order of source transforms

**Two finish paths both call `build_advance`.**

- **Joined r6 path (PRIVATE heat).** `owner.finish` dispatches to `J.finish` when the heat label is PRIVATE (I/integration_spatial_owner.py:718-720). The measured live run uses this path: `heat_method=J.METHOD` (C/measure_live_owner.py:164).
  - Transform order is set in C/private_heat_bundle.py:363-364 and 443-448:
    1. `INDEXED.joined_source` (C/private_heat_indexed_runtime.py:285-294)
    2. `EXCHANGE.producer_source`
    3. `LEDGER.joined_source` (C/heat_ledger_issuer_patch.py:251-272)
    4. `VALIDATION.joined_source` (C/spatial_validation_patch.py:382-394)
    5. `LIVE.joined_source` (C/live_spatial_patch.py:97-153)
  - `PAYLOAD.additional_transform` does not touch r6 (C/heat_payload_indexed_patch.py:258-262).
- **Native path (MimeticHeatResult: EXTREMUM or hybrid).** The source chain is `LIVE.owner_source(VALIDATION.owner_source(EXCHANGE.holder_source(SIP.transform(TRANSFER.spatial_owner_source(I owner)))))` (C/test_step7_bundle.py:47-49 plus C/live_memory_composition.py:24). This path calls `build_advance` only when a construction scope is active (C/live_spatial_patch.py:663-674). It is covered by C/test_live_native_owner.py.

The transformed r6 `finish` (printed by `show_finish.py joined finish`):
- builds the exchange inside `with LIVE_SPATIAL.input_stack() as _live_inputs, LIVE_SPATIAL.record_access(step.graph, …) as graph:`;
- sets `transported = _live_inputs.enter_context(LIVE_SPATIAL.transport_access(step.result, …))`;
- runs `EXCHANGE_RECORD.build_advance(...)`, then `del exchange, graph, transported`, then `validate_owner(...)`, then returns from inside the `with` blocks. At that return the access stacks close their refs.

---

## 1. Exact Python type of every top-level value in the exchange dict passed to `build_advance`

The dict is built at H/private_heat_joined_consumer_r6.py:312-324, as rewritten by C/live_spatial_patch.py:149-151. The native version is I/integration_spatial_owner.py:795-806, rewritten by C/live_spatial_patch.py:659-662. Types below assume compact construction is active, as in the live composition.

| key | r6 / PRIVATE path | native path |
|---|---|---|
| `schema` | `str` `'atlas.private.spatial-composed-advance.r1'` (r6:30, 312) | `str` `'atlas.spatial-exterior-advance.v1'` |
| `owner_id`, `parent_state_id`, `collar_state_id`, `source_flow_stage_id`, `source_audit_id`, `spatial_graph_id`, `global_transport_id`, `joined_heat_id` | `str` (64-hex) | same |
| `spatial_graph` | **`record_views.RecordRef`, exact class.** `LIVE_SPATIAL.reference(graph)` returns `_Object.ref` (live_spatial_patch.py:294-299). That ref is `record.borrow()` (a `copy` of the root `RecordRef`, record_views.py:991-999) made in `access()` (live_spatial_patch.py:397-399). The root comes from `holder_record()` → `payload.root()` (260-262). Its view is the graph holder's `_json` CompactRecord, schema `'atlas.spatial-working-record.v1'` (live_spatial_patch.py:246). | same (owner_source tail 644-648, 659-660) |
| `transport` | **`record_views._ObjectRecordRef`.** `_TransportObject.ref` is `result.record()` (live_spatial_patch.py:376, 381), which is `LIVE_TRANSPORT.result_record` → `_ObjectRecordRef(snapshot._record.root(), overlay=<new 'atlas.transport-result-header.v1' record>.root())` (live_transport_result.py:117-125). The body view has schema `'atlas.spatial-implicit-transport.v1'` (71-72). | same (661-662) |
| `joined_heat` | **`dict`**: `heat.reference()` = `json.loads(self._reference)` (r6:102-103). Built at r6:149-157 and bounded to ≤32 KiB together with the header (163-164). This is **not** `heat.descriptor()`. | **`dict`**: `heat.descriptor()` = `MimeticHeatResult.descriptor()` → `json.loads(self._metadata)` (I/integration_mimetic_heat.py:365-366; I/regional_execution.py:81-82) |
| `joined_heat_plan` | `dict`: `json.loads(self._call._plan)` (r6:105-106). `_plan` is bytes (H/private_heat_native_issuer_r12.py:224). | `dict`: `json.loads(encoded)` (integration_mimetic_heat.py:368-372) |
| `heat_boundary_account`, `physical_geometry` | `str` literals | same |
| `heat_projection_rule` | `str`: `grouped.value['proof']['rule']` (r6:319; H/private_heat_grouped_account_r1.py:76-77) | **absent** |
| `finite_proposal` (optional) | **`_ObjectRecordRef`**. `LIVE_FINITE.record` overlays a `'atlas.finite-proposal-header.v1'` record on the `'atlas.finite-spatial-stock-proposal.v1'` record root (C/live_finite_patch.py:86-93). This holds when the proposal was issued under an active scope (63-78); otherwise it is a `dict`. | same |
| `dual_measure_audit` (optional) | `dict`: `json.loads(step.measure_audit)`, where `measure_audit` is bytes (I owner:122, 637) | same |

**No `RecordRef` appears below the top level** in either path. `joined_heat`, `joined_heat_plan` and `dual_measure_audit` are pure `json.loads` output, and every other value is a `str`. The only refs are the top-level `spatial_graph`, `transport` and `finite_proposal`; for the latter two, the base and overlay refs live inside the `_ObjectRecordRef`'s owned tuple.

In the native path without an active scope, `spatial_graph` and `transport` would be plain dicts, but that branch skips `build_advance` (live_spatial_patch.py:667-673). The r6 path always calls `build_advance`. There, legacy (non-compact) holders yield dicts from `record_access` / `transport_access` (412-438, 369-375).

Two facts about the import cost (record_tables.py):
- `_Builder._add` imports refs field by field (`keys` / `field` / `at` / `scalar`; 238-243, 293-337). It hash-conses by `(kind, payload, shape, children)` (376-385) but keeps **no memo per source `(view, index)`**. Traversal time therefore grows with the *expanded* tree, and the full canonical stream is re-hashed (`emit`, 136-140).
- The builder's scratch is capped by `WorkBudget(MAX_BUILD_BYTES = 256 MiB)` (29, 118). A record is capped at `MAX_ITEMS = 4,000,000` nodes (25, 380).

---

## 2. Readers of `holder._record` and the `CompactRecord` checks on it

**Direct readers of `SpatialExteriorAdvance._record`.** Only these exist in C and R:
- C/exchange_record_patch.py:
  - `initialise` 60-71: `isinstance(...CompactRecord)` at 60, budget check at 61, `LogicalExchange(holder._record, holder._record._root)` at 63, `composite_identity` at 65
  - `result_id` 75-79: `_live()` at 76; legacy `json.loads` at 79
  - `record` 83-87: `from_body` at 84; legacy at 87
  - `header` 92-112: refuses non-compact at 92-93
  - `close` 116-117
- Native legacy fallback: `_retain(result, 8192+len(result._record))` (I owner:808-809; live_spatial_patch.py:671-673)
- Test: C/test_exchange_record_patch.py:146 (`compact._record.root()`) and :345 (legacy measurement)
- The R hits for `._record` (funding_transfer, workflow_transfer, spatial_transfer, …) belong to other holder classes, not `SpatialExteriorAdvance`.

**Indirect readers** go through `advance.record()`, `.header()`, `.result_id` or `.close()`:
- spatial_records_patch: `advance_header` 421-425 → `advance.header(fields=EXCHANGE_NAMES)`; `advance_record` 428-433 → `advance.record()`.
- `records` 247-251 uses `exchange.without(...)` and `exchange.field(...)`; `headers` 211-226 uses `_header()` → `select().export()` plus `field('spatial_graph')`.
- Workflow seams (spatial_records_patch.py:480-491) replace `exterior_advance.record()` at I/integration_regional_workflow.py:1529 and 1541, and feed `_spatial_records` (1568-1570). `audit_arrays()` (I owner:148-151) uses `_transport` and `_heat`, not `_record`.
- measure_live_owner.py:206-209, 255-257: `exterior.record()`, `.without`, `.field`, `.close`; `result_id` at 249.
- spatial_validation_patch, heat_cold_patch, private_heat_restored_binding_r10 and the native `validate_exchange` consume an **exchange value** (dict or RecordRef, wrapped by `_SV.access`), never `holder._record`:
  - spatial_validation_patch.py:25-27, 156-172, 209-228
  - heat_cold_patch.py:204-208, 255-257
  - restored_binding_r10.py:60-62, 81-107
- **The restore path already feeds a composite** `LogicalExchange.from_records(opened['exchange'], spatial_graph=…, transport=…, joined_heat=…)` into native validation (spatial_records_patch.py:300-304). That shows `_SV.access`, `exchange_identity` (`without` plus stream) and `is_record` (`isinstance RecordRef`, kind `'object'`) all accept a composite.

**What breaks if `holder._record` became `LogicalExchange.from_records(body_root, spatial_graph=…, transport=…)`**, which is an `_ObjectRecordRef` and not a `CompactRecord`:
1. `initialise`: the `isinstance` check fails, so `_result_id` stays `None` and the foreign-budget check is skipped. Line 63 also could not work: a composite has no `_root`, and `RecordRef.__init__` requires a `CompactRecord` view (record_views.py:977-978). Use `holder._record.composite_identity(state_id)` directly instead.
2. `result_id` and `record()` drop to the legacy branch, and `json.loads(<_ObjectRecordRef>)` raises `TypeError`.
3. `header()` raises `ContractError('owned exchange header requires a compact holder')`. Workflow `advance_header` then fails.
4. `close()` becomes a silent no-op. Composite `RecordRef.close()` exists (record_views.py:1178-1184) and raises `RuntimeError` while borrowed (content_cache.py:243-248), which matches the semantics the tests expect, but it would never be called.
5. **Pieces that already work with a composite:**
   - `LogicalExchange.from_body(record=composite)` takes `record.borrow()` (record_views.py:1197) and uses `body._view._check`; `_ObjectRecordRef` sets `_view` and `index` from its base (1275).
   - `.scope`, `_live()`, `kind`, `keys`, `field`, `iter_json`, `export` and `_decoded_stats` (non-ordinary memo key, 1364-1366) all work.
   - Byte identity is unchanged: keys are emitted via `sorted()` (1260) and `T.string_parts` (1328), children stream canonical bytes, and the builder also uses `sorted(value)` and `string_parts` (record_tables.py:305, 149).
6. **Lifetime trap.** The composite borrows each override (`v.borrow()`, 1269) and its base (dependency, 1270-1271). The finish's access stacks call `borrowed.close()` (live_spatial_patch.py:398, 405-407) and the transport `record.close()` (379-388) at normal `with` exit. If the composite borrowed `LIVE_SPATIAL.reference(graph)` or `.reference(transported)`, those closes would raise `RuntimeError('owner has live child borrows')`. The composite must take its own refs, for example `step.graph._json.root()` and a fresh `step.result.record()`, and drop rather than close them. `Owned.__del__` retires them (content_cache.py:285-287). The `from_body` pattern already works this way.
7. **Lifetime extension.** The composite would keep the finite-proposal record alive for as long as the advance lives; today only `step` holds it. Graph and transport are already held for that long, via `RegionalCollarAdvance.transport_stage.spatial_graph` and `advance._transport`.
8. **Tests that would fail** (details in §6): test_exchange_record_patch
   - `test_graph_finite_graph_and_face_rows_are_hash_consed` (`_record.root()`; the graph and `finite_proposal.graph` share an index)
   - `test_failed_native_constructor…` (`assertIsInstance(packed, CompactRecord)`)
   - `test_no_eager_body_json_export…` only if `result_id` is not cached at init
   - `test_close_refuses_live_public_borrow…` if `close` stops closing.

   Its fixtures pass plain dicts for `spatial_graph` and `transport`, so `build_advance` still needs a pack path for non-ref values.

---

## 3. The state row and `joined_heat` in publication

**State row.**
- `indexed_record(state).value` is `dict(state_id, **json.loads(snapshot._metadata), thermal_mesh=snapshot._mesh)`. When `snapshot._cells` exists, `cells = snapshot._cells.borrow()` is a **`RecordRef` into a separate CompactRecord** with schema `'atlas.spatial-state-cells.v1'`, packed once in `SIP.issue` (C/spatial_indexed_patch.py:303-313, 186-201, 204-211).
- `_metadata` excludes `cells` and `thermal_mesh` (133-135; asserted at test_spatial_compact_cells.py:117).
- The publication row drops `thermal_mesh` (spatial_records_patch.py:245; measure_live_owner.py:205).
- Native JSON fields, confirmed by the diagnostics `state.json` keys: `schema`, `state_id`, `owner_id`, `funding_id`, `time_s` (float), `intervals` (int), `parent_state_id`, `collar_state_id`, `support_id`, `trajectory_id`, `trajectory` (dict), `grid_id`, `thermal_mesh_id`, `projection_accounts` (dict). Optional: `finite_stock_state`, which stays a plain dict because `FiniteStockState` is not repacked (live_finite_patch.py:65-66; I reservoir:101-113), plus `measure_policy` and `native_material_quadrature_m3`.
- In the measured run, state cells are 172 rows (222,980 B) of a 225,798 B row.

**`joined_heat`.**
- In the compact heat path, `heat.descriptor()` is **refused**. `LiveJoinedHeat.descriptor()` → `ComposedHeatResult.descriptor()` → `CompactHeatSnapshot.descriptor()` raises `ContractError('whole heat descriptor refused…')` (H r6:95-97; H issuer_r12:486-487; C/heat_ledger_tables.py:341-342).
- The r6 exchange therefore uses `heat.reference()`, a plain dict of 4,957 B in diagnostics. Its keys: `call_id`, `checkpoint` (CAS receipt `{invocation, metadata}` holding ledger and field-payload SegmentRefs), `consumer_sources`, `duration_s`, `fixture_status`, `geometry_id`, `ledger`, `loaded_dependency_identity`, `method_id`, `native_admission`, `original_target`, `plan_id`, `production_acceptance`, `result_id`, `runtime_identity`, `schema`, `state_id`.
- The heat ledger CompactRecord (`'atlas.private.heat-ledger.logical.v1'`, heat_ledger_tables.py:19) is **already published as its own segment** by `private_heat_snapshot_store_r4.save` (153-178).
- In the native path, `joined_heat` is the full `MimeticHeatResult` metadata dict. Its only compact copy is the exchange pack.

---

## 4. Storage API contracts

**`SegmentBackend.publish(candidate, *, record_schema, identity, metadata, arrays, producer, representation_profile, scope, cancel=None)`** (C/segment_store.py:296-403):
- `candidate.scope is scope` (298). `identity` is a `LogicalIdentity` with `record_schema == identity.record_schema` (299-300). `producer` is a 64-hex digest (301). `representation_profile` is a str of 1-256 UTF-8 bytes (302-303).
- `metadata` is canonical bytes ≤ `ROOT_METADATA_MAX` = 64 KiB (304); `parse` requires canonical form (58-67).
- The root key is `h('atlas.segment-root.v1', {identity, producer, representation_profile})` (308-310). If that key exists, the call returns the existing ref only when the metadata is equal, otherwise it refuses with a conflict (311-323). Republication is idempotent.
- `arrays` is a **callable** returning sources with `.info` (name, dtype, shape, logical_bytes) in strictly increasing UTF-8 name order (324-338). `source.blocks(max_owned_bytes=NATIVE_CHUNK_BYTES)` yields same-scope `Owned` blocks of ≤64 KiB that are re-spliced into 64 KiB chunks (354-377).
- `cancel` must have `.is_set()` (40-42). Note that `spatial_records_patch._check` also accepts plain callables, but `publish` does not.
- The root manifest is `{schema, identity, producer, representation_profile, metadata, reference, index}` and must total ≤64 KiB (396-398).
- The SegmentRef carries a content Merkle over identity, array_count, logical_bytes and tree_digest (394-395) and is ≤4096 B (compact_contracts.py:199-203).

**`open(stores, ref, *, scope, cancel=None)`** (405-407) returns a `SegmentView`.
- It validates the exact root keys, identity and reference, the root-key recomputation and the index digest (440-450). `_validate` walks every binding page: Merkle, coverage, canonical chunk ranges (595-627).
- `metadata()` / `metadata_bytes()` return the canonical user metadata (629-636).
- `cache_identity()` is `None` for a candidate (463-475), and `scan()` refuses a candidate (696).

**Limits.**
- 64 KiB chunks, binding pages ≤64 KiB, fan-out 16, depth ≤8 (segment_store.py:31, 235, 248-251).
- Per page, `validate_segment_budget`: logical ≤128 MiB, ≤2048 chunk refs, manifest ≤256 KiB, metadata ≤64 KiB (compact_contracts.py:236-254).
- `put_manifest`: metadata ≤64 KiB, manifest ≤256 KiB (C/interval_store_set.py:697-702).
- `put_chunk` is content-addressed and dedupes across ancestors (665-671), refuses non-finite floats (663-664), and enforces `max_store_bytes` of 4 GiB (34-35, 680-681).
- `seal()` asserts the candidate owner is unborrowed (800).

**`CompactRecord` (C/record_views.py):**
- `metadata_bytes()` (771-773) returns canonical codec metadata, which is ≤65,536 B by construction (record_tables.py:432).
- `array_sources()` (781-788) yields the 24 `_ArraySource` columns sorted by UTF-8; `blocks` (1473-1490) works from memory or a segment.
- `storage_payload()` (775-779) is for in-memory records only.
- `from_segment(segment, metadata=None, …)` (484-549):
  - Codec metadata defaults to the segment's user metadata, so the segment metadata **must be** the codec metadata, or callers pass it explicitly as `open_records` does.
  - Requires `segment.info.ref.identity == identity` (499) and exactly 24 columns (500).
  - Verifies column digests by scan (sealed) or per-array iter (candidate) (501-540).
  - Holds the segment as a dependency (543-544).
  - Runs a full structural plus canonical-identity stream, `_validate` (794-971).

**Can an in-memory `pack_record` result be published directly and reopened with the same identity?** **Yes.**
- Precedents: test_record_views.py:272-307 (stream equal after reopen); C/measure_live_capacity.py:213-220; and, in production, `private_heat_snapshot_store_r4.save` / `open` (163-167, 232-235), which uses its own profile and binds `ledger.identity` in the receipt (105-106).
- Condition: the segment's `record_schema` is the record's own schema (`'atlas.spatial-working-record.v1'`, `'atlas.spatial-implicit-transport.v1'`, `'atlas.spatial-state-cells.v1'`, `'atlas.spatial-exchange-body.v1'`), **not** `BUNDLE_SCHEMA`.
- Graph row bytes equal the graph holder record exactly (sha = `geometry_id`). The transport, state and exchange rows do **not** equal any single existing record:
  - transport adds the `result_id` overlay
  - state is small metadata plus the cells record
  - exchange is the body plus `state_id` / `result_id`, minus three fields

---

## 5. Reader contracts in `spatial_records_patch`

- **`_descriptor`** (59-69) requires exactly `{bytes, sha256, compact}`, with `compact` exactly `{schema, segment, field}`, `compact['schema'] == 'atlas.spatial-record-ref.v1'` and `field == kind`. It then parses `SegmentRef`.
- **`verify_records`** (129-142) checks `0 < len(refs) <= 16`, groups refs by segment, and requires `ref.identity.record_schema == BUNDLE_SCHEMA` (138) before open, `_bundle_metadata` and close. It never reads the payload.
- **`_bundle_metadata`** (98-126):
  - optional producer equality, `sha256(canonical(source_producer))` (99-101)
  - metadata keys exactly `{schema, codec, records}` with `schema == BUNDLE_SCHEMA` and 1-16 records (105-107)
  - codec identity equals the segment identity, and `array_count` equals the codec column count (109-111)
  - per-column dtype and shape (112-115)
  - descriptors `{bytes, sha256}` (116-121), and each ref's `{bytes, sha256}` equals the index (122-124)
- **`open_records`** (145-176) does the same, then calls `from_segment(segment, canonical(codec))`. The root key set must equal the index (161-162). It streams each requested child's identity and checks it against the descriptor (165-168). It yields children and does not force-close them (170-176).
- **`restore_records`** (270-308):
  - kinds must be exactly `{'state'}` and `{'exchange','graph','transport','heat'}` (283, 286)
  - the state is rebuilt with cells as a `RecordRef` (291-297)
  - the exchange is `LogicalExchange.from_records(...)` (300-301)
  - `headers(...)` must equal the stored headers, including `record_blobs`, verbatim (302-303)
- **`verify_publication_references`** (389-411) runs inside the publish transaction:
  - exact kind sets (395-402)
  - certification and differential `record_blob` (407-411)
  - metadata only; the test enforces this by making `SegmentView.read` / `iter` fail
- **Other readers of these refs:**
  - R/reopen_prepared_restart.py:243-262 (exact kind sets plus `open_records`)
  - R/workflow_transfer.py:380-389, 404-407, 600-619
  - R/materialise_endpoint.py:320-341 (publishes and verifies historical records through the bundle)
  - R/run_prepared_restart successor checks (structural only; test_step6_integration.py:20-41)
  - R/test_step8_* also touch these, but they are Step 9 work and out of scope

**How an old reader reacts:**
- **(i) New `REFERENCE` schema string:** `_descriptor` raises `ContractError('record field/schema binding differs')` (66-68). This happens on every path, including the publish-time check, restore, reopen and transfer.
- **(ii) New segment `record_schema`:** `ContractError('foreign record bundle schema')` (138, 156). Even with `BUNDLE_SCHEMA`, any user-metadata layout other than `{schema, codec, records}` is refused (105-107).
- **New or renamed kinds:** refused by the exact set checks.

All of these fail closed, with no silent misread. Conversely, intervals published today hold `BUNDLE_SCHEMA` refs, so **new readers must keep the bundle path**.

---

## 6. Existing tests and what they assert

**test_exchange_record_patch.py**
- `test_pinned_source_and_composition_order` (100): the r6, indexed-r6, owner and indexed-owner SHAs are pinned; `producer_source` changes only its seam; transforms apply once.
- `…exact_native_identity_public_record_and_actual_handles` (126): `result_id` equals the legacy one; `record()` is a `LogicalExchange`, not a `Mapping`, and streams `canonical(legacy.record())`; `audit_arrays` keeps the original objects (`is`).
- `…graph_finite_graph_and_face_rows_are_hash_consed` (144): through `_record.root()`, the graph shares an index with `finite_proposal.graph`, and the face lists share one node.
- `…no_eager_body_json_export_and_result_hash_is_cached` (158): no container `json.dumps`; `result_id` is cached (`composite_identity` and `CompactRecord._export` are patched to fail).
- `…header_is_owned_bounded_and_rejects_body_fields` (178)
- `…explicit_scope_…_refusal` (190)
- `…header_bound_and_scalar_contract…` (211): 512 KiB scalar or container refused before export.
- `…close_refuses_live_public_borrow…` (227): `RuntimeError` while `record()` is borrowed; after close, `result_id` raises.
- Cancel and failure funding tests (238, 246, 264, 280): failure frames stay paid until released; 264 asserts the packed argument is a `CompactRecord`.
- `…legacy_bytes_holder_compatibility` (302)

**test_spatial_records_patch.py**
- `test_successor_exact_identities_shared_graph…` (81): per-kind `{bytes, sha256}` equals `canonical(legacy)`; **all kinds share ONE segment** (`len(references) == 1`); manifest ≤25% of the limit; the publication check is metadata-only; the producer check is enforced.
- `test_sealed_reopen_exact_children_and_shared_graph` (124): **cross-row DAG sharing**. The exchange's `finite_proposal.graph` has the same `_view` and index as the graph row, and each child stream equals canonical.
- `…reference_mutations…refuse` (143): sha, bytes, field, schema and merkle_root mutations all refuse; a missing heat kind refuses.
- `…republication_is_exact_and_adds_no_chunks` (161)
- `…logical_child_proof_is_not_replaced_by_authenticated_index` (170)
- Certification and differential round trips (185, 207)
- `…state_cells_stay_views_and_exchange_reassembles_without_decode` (228): restored `state['cells']` is a `RecordRef`; restored is a `LogicalExchange` whose identity equals `sha256(canonical(exchange))`.
- Bounds and cancel (260); workflow transform (273).

**test_live_publication.py**: certification and geometry decodes are released before commit, the header is owned, and a failed publish keeps the decode paid (36, 52, 68).

**test_live_spatial.py**
- Source stages compile once and keep account checks (52); projection shares lists with exact output (84).
- Ownership and normalisation (121, 136, 161); heat package with fresh or persisted mesh (187).
- `test_real_ale_holder_closure_and_transport_exact_without_graph_json` (295): bounds and graph `_json` are `CompactRecord`; `geometry_id` is unchanged; the `graph.record()` stream equals the legacy JSON; the transport `result_id`, record export, columns and arrays equal the legacy ones.
- Failure, nesting and foreign scope (366, 387, 406).

**test_record_views.py**: column cache and tamper tests (30-195), plus `test_real_native_segment_publish_and_bounded_reopen` (272), which publishes a packed record and reopens it with `from_segment` with an identical stream.

**test_record_composition.py**
- Overlay and identity: `composite_identity` equals `sha256({state_id, exchange})`, and importing a body ref twice dedupes floats (31).
- `from_records` composes without re-encoding, an escaped child survives, and closing the source child while borrowed raises (53).
- Plus 68, 90 (foreign-scope import refuses) and 102.

**test_step6_integration.py**: successor checks accept compact descriptors by structure only (20); transform layering (43); store dispatch (56).

**test_spatial_workflow_patch.py**: 163, 209 and 254 cover the v2 route, two-process publish and reopen, exact history equality, and zero reserved bytes after close.

**Related tests not in the list:**
- test_live_native_owner.py (154-163): the native path's exchange `result_id` and `record()` identity equal the legacy ones; whole graph and transport exports are forbidden during heat and finish.
- test_live_transport_result.py:15
- test_spatial_compact_cells.py (108-146): cells are packed once and kept as a `RecordRef`.

---

## 7. Physical disk and sharing

**The transport metadata embeds no graph geometry.** Its keys (I/integration_spatial_transport.py:604-615, plus the `result_id` overlay) are `schema`, `geometry_id` (graph hash string), `state_id`, `source_stage_id`, `cell_ids`, `method`, `exact_input_stocks`, `exact_stocks`, `exact_face_transfers`, `exact_projection_accounts`, `binary_stock_projection_accounts`, `field_errors`, `nonnegative_fields`, `krylov_iterations`, `numerical_contract` and `accuracy`. The diagnostic `transport.json` keys match.

What the bundle can share between rows, inferred from the structure (not measured):
- **graph ↔ transport:** scalars only. That means 236 cell IDs (`cell_ids` width 15,813 B ≈ 236×67, so 64-char strings, which go to the 32 B IDENT pool), the shared `source_stage_id`, key tokens and small rationals.
- **state ↔ transport:** state cells' non-enthalpy exact values are `_enc(_q(exact_stocks[k][at]))`, the same spellings (r6:272, 290-291), so their RATIONAL nodes are shared.
- **state ↔ graph:** `volume_m3` from `end_volume_m3`, `cell_id` and `source_key`.
- **differential / finite runs:** `exchange.finite_proposal.graph` shares unchanged graph subtrees (asserted synthetically at test_spatial_records_patch.py:131-132).
- **heat:** the ledger is a separate segment already; the heat row is about 5 KB.

**Genuine-owner diagnostics** (R/test-results/step8-owner-after-r3, 236 thermal cells, 832 faces):
- Logical record sizes: graph 1,110,173 B, transport 775,359, state 225,798, exchange 21,701 (includes a 20,526 B `joined_heat_plan`), heat 4,957, heat-ledger 1,241,592, mesh 1,343,049.
- Files: `interval-0000.sqlite` 983,040 B; `native.arrays.sqlite` 270,336 B. `before-r4` has the same logical sizes except heat-ledger (1,242,108 B), and its interval file is 978,944 B.
- `retained:record-tables` by stage, from `result.json` checkpoints:

| stage | record-tables bytes | change |
|---|---|---|
| fresh-bounds | 295,664 | |
| closed-graph | 655,550 | +359,886 |
| transport-solve | 1,169,299 | +513,749 |
| heat-solve-and-checkpoint | 2,051,625 | +882,326 (heat ledger) |
| joined-finish | 3,074,675 | +1,023,050 |
| compact-record-publication | 3,185,869 | +111,194 |

The +1,023,050 at joined-finish is the state-cells record plus the exchange copy. The exact split is my inference; the code does not report it. The bundle itself is transient (closed in `publish_records`, 93-94) and does not appear at checkpoints, because the heat peak of 32.6 MB retained dominates there.

Publishing per holder would lose only the cross-row sharing above. Each segment also adds a root manifest and at least 2 binding pages (24 or more leaves at fan-out 16), and small columns become separate small chunks. In return, no new DAG gets written.

---

## Design constraints a redesign must preserve

1. **Logical identities are byte-exact.**
   - `result_id = sha256('{"exchange":'+body+',"state_id":"…"}')` with legacy sorted-key canonical JSON (record_views.py:1213-1228; I owner:141-143).
   - `advance.record()` stays a `LogicalExchange` (`RecordRef`, not a `Mapping`) that streams `canonical({result_id, state_id, **body})`.
   - `spatial_graph_id` equals the graph identity.
   - Per-kind `{bytes, sha256}` equals the canonical bytes of: state (`indexed_record` minus `thermal_mesh`), exchange (minus `spatial_graph` / `transport` / `joined_heat`, plus `result_id` / `state_id`), graph, transport (with `result_id`), and heat.
2. **Holder API semantics.**
   - `result_id` is cached at init with no rehash.
   - `header()` covers only `HEADER_FIELDS` scalars, ≤4 MiB, and refuses before export.
   - `close()` raises while borrowed, and `result_id` raises afterwards.
   - `audit_arrays()` returns the original arrays.
   - `build_advance` still accepts plain-dict values (test fixtures, legacy holders) and refuses `state_id` / `result_id` in the dict (exchange_record_patch.py:48-49).
3. **Ownership and lifetime.**
   - Same `RetainedScope` throughout; `scope.run_budget is state._budget`; foreign scope refused (record_tables.py:240; record_views.py:1236-1242).
   - A composite must not borrow the access-stack refs (live_spatial_patch.py:379-388, 397-407); `Owned.close` raises on live borrows (content_cache.py:247-248). Use fresh refs and drop them.
   - Failure frames keep funding until release.
   - Ownership must retire without `gc.collect` (measure_live_owner.py:175, 255-279).
   - `candidate.seal` requires the candidate unborrowed (interval_store_set.py:800).
   - Composites extend the lifetime of the finite-proposal record.
4. **Readers fail closed and published data persists.**
   - Existing intervals hold `BUNDLE_SCHEMA` / `REFERENCE_SCHEMA` refs, so new readers must keep that path for successor, migrated-root, history, certification and differential data.
   - The reader sites that must learn any new format: `verify_records`, `open_records`, `export_record`, `restore_records`, `verify_publication_references`, R/reopen_prepared_restart.py:243-262, R/workflow_transfer.py:380-407 and 600-619, R/materialise_endpoint.py:320-341.
   - Kind sets stay fixed: `{state}` and `{exchange, graph, transport, heat}`, at most 16 per bundle.
   - `headers()` equality, including `record_blobs` verbatim, holds on restore.
   - The publication check stays metadata-only.
   - The producer binding is `sha256(canonical(source_producer))`.
   - Republication stays idempotent, adding no chunks.
5. **Storage limits.**
   - Codec and segment metadata ≤64 KiB; root manifest ≤64 KiB; native manifest ≤256 KiB.
   - 64 KiB chunks; SegmentRef ≤4 KiB.
   - `arrays` is a factory in UTF-8 name order; `cancel` must have `.is_set()`.
   - `from_segment` needs codec metadata (as the segment metadata or passed explicitly), identity equality and exactly 24 columns. It costs one full canonical stream per reopen.
   - Today's single bundle pack is the largest builder job of the interval: up to 256 MiB of builder scratch and at most 4,000,000 nodes over **all** rows together. Per-holder publication avoids that combined bound.
6. **Provenance gotcha.**
   - The transformed heat issuer captures the `_COMPACT_MODULE_NAMES` modules (heat_ledger_issuer_patch.py:177-186): `record_tables`, `record_views`, `content_cache`, `compact_contracts`, `live_spatial_patch`, `live_transport_result`, `live_finite_patch`, `segment_store`, `spatial_validation_patch`, `heat_cold_patch`, `heat_ledger_*`, `interval_*`. This capture feeds `loaded_dependencies` (H issuer_r12:113-130, 275-278, 588-590).
   - **Editing any of those modules changes heat and exchange IDs in end-to-end runs.** `exchange_record_patch.py` and `spatial_records_patch.py` are outside that set. They are, however, authenticated compact-helper bytes (private_heat_bundle.py:72-84, 432-435) and part of the worker module capture (heat_payload_indexed_patch.py:245-255); I did not verify whether that capture affects identities.
   - Changing r6 seam text changes r6's transformed SHA, which feeds `consumer_sources` in `heat.reference()`.
   - Prove byte parity at component level with identical inputs, old versus new packaging. End-to-end before/after runs already differ by source-bound IDs (step8-owner-comparison.json `limits[0]`).
7. **Ownership flags.**
   - `segment_store.py`, `interval_store_set.py` and `codec_*` belong to another active chat, so flag any change to them.
   - The per-holder publish and reopen route needs no `segment_store` change; precedents are `measure_live_capacity.publish_record` and `private_heat_snapshot_store_r4`.