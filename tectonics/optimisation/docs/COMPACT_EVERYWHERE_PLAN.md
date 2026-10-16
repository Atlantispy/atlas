# Integrated optimisation plan: compact data, resumability and exact computation

15 October 2026. Private engineering successor. **Status: Step 8 / WP14 ACTIVE by Michael's explicit request; Steps 1–7 gaps closed. Later integration and acceptance remain INCOMPLETE.**

**Objective.** Complete the agreed WP0-WP25 optimisation programme: preserve exact scientific results and restartability while reducing live memory, storage, repeated decoding and computation. The first operational milestone is a compact interval-two advance, publication and independent reopen under the existing guards. The programme finishes only after every planned optimisation has a measured enabled/disabled outcome and the final enabled composition passes its affected checks. L1/L2 remain later phases with their stated authority boundaries.

**Current evidence.** Steps 1–7 now satisfy their stated component/source-transform scope, with the earlier gaps closed in the explicit table in section 3. This includes the completed Step 2 lifetime inventory and the genuine Step 7 owner-heat/checkpoint result. Step 8 live-memory implementation and representative peaks remain incomplete; Step 9 migration/runner/reader, Step 10 composition/measurement and Step 11 real IV2 acceptance remain later obligations. Frozen RC1 and historical reviewed inputs are unchanged.

**Reading order.** Decisions D1-D6 below control the design. Section 3 is the single execution schedule, dependency map and ownership rule for all 26 packages. Sections 1-2 and 6-13 supply the detailed contracts and source coverage. Section 4 defines measurement and resource acceptance; section 14 defines completion and continuation. Earlier estimates and open-decision wording in the historical workflow record are superseded where this plan expressly reconciles them.

**Step 2 / WP0a and source inventory completed, 15 October 2026.** The guarded census covered the unchanged original IV1 store; the missing WP14 source-lifetime inventory is now closed with 25 lifecycle groups and 43 current source bindings. [Measured census](probes/structure-census-r3/structure-census.json), [guarded run](probes/structure-census-r3/run.json), and [verification/inventory](test-results/wp0a.json). Historical measurements and failures are preserved. The inventory adds no new process-peak measurement, migration or IV2 acceptance.

- *Previously measured* sizes are attributed to `test-results/caps.json` and `CLAUDE_HANDOFF_20261015.md`; confirm their bindings before reusing them for implementation.
- *Derived* sizes and timings are planning scenarios only. WP0 replaces them with measurements for the selected composition; a ratio or fixture pass never proves IV2 acceptance.
- All source transforms must recheck the exact current anchor and source identity. The source references below describe RC1, not an assurance that a later composition has identical seams.

Abbreviations:
- **R** = this plan's `resumability-r1` directory.
- **RC1** = `composed-r1/runtime-src/atlas_tectonics`. It is frozen, and the anchors quoted below are exact strings in it.
- **HLP** = `composed-r1/helpers`.
- **C** = `compact-geometry-r1`.
- **IV1** = interval one, the historical r9 head. **IV2** = interval two, the successor.

**Michael's decision, 15 Oct: B, compact-first.** Every large geometry or heat record on the run path is written, read and validated through the lossless compact representation:
- arrays and CSR offsets;
- exact integer and rational pools;
- shared immutable IDs;
- content-addressed blobs, with chunk sharing between intervals;
- bounded owned views.

Whole-JSON reconstruction happens only through an explicit, charged export. Storing everything as compactly as possible is the standing principle, because it saves RAM and makes open, load, save and read faster.

Raising store limits remains a possible future option. It is **not** how this run gets through.

Every optimisation item is a **planned work item**: the four encodings plus zstd, every cache, and every further technique. Each is gated by its measurement and enabled only where it shows a net gain with no change to accuracy or accounting.

The following stay unchanged:
- physics, exactness, provenance and accounting;
- the guard limits: 12 GiB RSS, 1 GiB free floor, 10 GiB start and 16 GiB logical.

**Decided constraints D1-D6 (Michael, 15 Oct 2026, recorded in WORKFLOW_DECISIONS.md). These are settled; section 5 lists implementation risks, not renewed approval questions:**

- **D1: re-derive codec item ceilings from the 128 MiB segment size.** Examples are MAX_NODES, MAX_EDGES, MAX_ITEMS and MAX_INTEGER_BYTES.
  - They remain enforced bounds, charged before materialising, with tests at each bound.
  - No accuracy or accounting change.
- **D2: allow a packaging-only heat issuer revision, r12 to r13, to compact the heat ledger.**
  - The numerical heat kernel must be AST-identical to the original.
  - Exact equality is required on the existing heat controls: arrays, and the enthalpy, residual, face, source and boundary accounts.
  - The new helper identity is recorded. The physics does not change.
- **D3: keep a BOUNDED post-publication re-validation inside the advance.**
  - It goes through compact views and the per-chunk hash index, never a whole-record decode.
  - This is distinct from the 14 Oct decision that dropped only the runner's extra same-process cold reopen.
  - The independent fresh-process reader remains mandatory.
- **D4: measure IV2's real store increment first; keep max_store_bytes at 4 GiB for IV2.**
  - Layout (Michael, 15 Oct): **one sealed, compact store file per interval, plus a small catalog** (section 9, WP13). Unchanged data is referenced read-only, by content hash, from earlier interval files rather than stored again. This replaces the earlier idea of rolling over only when a store nears its limit.
  - Raising max_store_bytes stays a simpler fallback (Michael: limits may be raised in future, but not instead of the compact layout).
- **D5: use the already-installed `blosc2` in `.r44-env`.** WP10 verifies its support for the planned zstd, shuffle, delta and trained-dictionary paths before relying on each one.
  - The earlier 15 October environment check records Python 3.12.14 with `blosc2` present and `zstandard`, `numcodecs` and `lz4` absent. Reuse that evidence only against unchanged environment identity; verify each required codec/filter/dictionary API in WP10. Package presence alone does not prove every proposed API exists. No installation or dependency change is authorised by this plan revision.
  - Compression stays measurement-gated per array class. Its runtime-identity change is acceptable because composition is new anyway.
- **D6: convert ALL of IV1's large records to compact form at migration**, not just the mesh and partition: exchange 106 MB, graph 105 MB, transport, state, certification, and the 357 MB heat ledger. Future runs then always start from compact data.
  - Each conversion goes into the exclusive working copy only, once.
  - It is verified exactly against the authenticated original bytes, by streamed canonical identity and original SHA-256.
  - It runs under a bounded, charged transient decode, with throttled guard checks.
  - The original store and every historical receipt stay untouched as evidence. No logical identity changes.

## 0. Why the current layout cannot publish IV2

These are RC1 code-reading findings from the original design. They define the seams to repair; each owner confirms the relevant anchors and bindings before applying a transform. They are not newly measured IV2 behaviour.

**1. Aliases count toward the snapshot limit.**
- `storage.ArrayStore.put` counts aliased arrays at their declared size: `total += math.prod(desc['shape']) * ...`, then refuses at `if total > self.limits.max_array_bytes:`.
- The `spatial-mesh:` and `partition-dag:` aliases in a successor therefore count toward the 512 MiB.
- `put` also caps chunk references at `min(max_chunks, max_manifest_bytes // 68)` = **15,420**.
- It refuses when `staged_bytes + addition > max_staging_bytes`.

**2. A freshly built IV2 mesh is legacy JSON.**
- `build_differential_mesh` ends in `encoded = _encode_mesh_record(record)`, producing `ExteriorMesh._json`.
- The issued state is therefore not an `IndexedSpatialSnapshot`.
- `_publish` calls `_COMPACT_SPATIAL.state_record(...)`, which falls back to a full `state.record()`.
- `_spatial_records` then writes `spatial-record:mesh` as JSON.

**3. The exchange is held and written as whole JSON.**
- `SpatialExteriorAdvance._record` holds the exchange as JSON bytes.
- `result_id` and `record()` each call `json.loads(self._record)`.
- `_publish` calls `exterior_advance.record()`.
- Exchange, graph, transport and heat-ref are each written as a whole `spatial-record:*` JSON array.

**4. Publication is followed by a full re-read, which the reader repeats.**
- `_publish` ends with `self._token = None`, so the runner's `_successor_checks` → `workflow.inspect()` runs a full `_refresh`.
- That refresh reads every operand under `require(total <= store.limits.max_array_bytes, ...)` and decodes each record with a `6*len+128*slots` charge.
- It also restores the heat ledger with a 6x charge in `snapshot_store_r3.restore`.
- The independent reader repeats all of this in a fresh process.

**5. The heat ledger is a single put.**
- It is stored as ONE put (`metadata_utf8` + `field_i`), checked by `_manifest(metadata, store.limits.max_array_bytes)`.
- At IV2 it refuses inside the advance, before publication.

## 1. Large-record inventory

All sizes are logical bytes. IV2 is projected as IV1 × 3.8 (charts) to × 5 (constraints).

**Baseline inventory.** This table describes the historical layout inspected before Steps 3–7. Its “Current representation” column is historical, not the status of the latest compact source. The step checkpoints in section 3 and the source-lifetime inventory in section 10 record the subsequent changes; the original size measurements remain attributed to their original inputs.

Abbreviations in the table:
- **P**: produced
- **W**: written
- **R**: re-read
- **V**: validated

| Record | IV1 measured | IV2 projected (legacy form) | Produced / written / re-read / validated | Current representation | Codec |
|---|---|---|---|---|---|
| partition `partition-record:partition` | 114,107,489 | 434-571 MB | **P:** native `_assemble_partition`.<br>**W:** `CollarWorkflow._publish`→`_partition_payload`→`C/partition_workflow_patch.payload` (`convert_native`, `partition_store.publish`).<br>**R:** `_refresh`→`_restore_partition`→`PW.restore`.<br>**V:** header equality, `DifferentialPartition.from_compact`, `_refresh` binding, reader `validate_migrated_lineage` | IV1: legacy JSON, converted to DAG v1 at materialise (`PW.historical_partition`).<br>IV2: one DAG v1 root plus `partition-dag:` aliases in the successor | **Existing** `partition_tables`: a typed DAG with node kinds and CSR child refs; pools for ints, rational-hex pairs, 32-byte IDs and strings; carried constraints and ray histories shared.<br>**Needs:** v2 storage (segments, reference-only binding) and re-derived ceilings |
| mesh `spatial-record:mesh` | 190,778,119 | 725-954 MB (handoff floor 0.43 GB) | **P:** `integration_differential_mesh.build_differential_mesh`.<br>**W:** `_publish`→`_spatial_records` (legacy loop), or `C/spatial_workflow_patch.records`→`persist_mesh`.<br>**R:** `_spatial_restore_records`→`Y.restore_records`; cold heat via `restore_checkpoint` + `ram_context_indexed_patch`.<br>**V:** `S._stream_stats`, `exterior_owner.restore/validate_parent`, `metric_identity` | IV1: compact v2 after materialise.<br>**IV2: legacy JSON** | **Existing** `mesh_tables`: float metric columns, CSR connectivity, tag palettes, rational and ID pools. `compact_store` v2 packs supports as JSON blobs into ONE `support-blobs` array.<br>**Needs:** v3, with a fresh-production seam, segmented or partition-shared supports, and no array over 128 MiB |
| exchange remainder `spatial-record:exchange` | 106,131,490 | 403-531 MB | **P:** `HLP/private_heat_joined_consumer_r6.finish` (`O._json(exchange)`).<br>**W:** `_publish` (`exterior_advance.record()`)→`_spatial_records`.<br>**R:** `_refresh`→`workflow_arrays`→`_spatial_restore_records`.<br>**V:** `integration_spatial_owner.validate_exchange`, r6 `validate_saved_exchange`, `integration_spatial_reservoir.validate_saved`, `integration_dual_measures.transport_audit`, `_context` | canonical JSON | **New** `record_tables`. Holds ids and rules, `joined_heat_plan`, `dual_measure_audit` and `finite_proposal`.<br>`finite_proposal` carries a **near-copy of the graph** (`graph=graph` plus inventory rows); hash-consing stores the shared parts once |
| graph `spatial-record:graph` | 104,701,198 | 398-524 MB | **P:** `integration_spatial_ale._close_record`, decoded in r6 by `step.graph.record()`.<br>**V:** `validate_exchange` (`_hash(graph)`), `_refresh` graph block, `_check_certification_records`, `transport_audit` | canonical JSON | **New** `record_tables`. Holds `cells` (id, kind, index, source_key, exact bounds), `transfers`, `inactive_zero_measure_cells`, `original_face_intervals` and `selected_face_representatives` (original + 2 fields).<br>Rows become key-shape IDs plus refs; rationals go to the integer pool and IDs to the ID pool; equal rows are shared |
| transport `spatial-record:transport` | ~6.4 MB | 24-32 MB | **P:** `step.result.record()`.<br>**V:** `validate_exchange`, `validate_saved`, `transport_audit` | JSON | **New**: `cell_ids` become an ID column; `exact_stocks` become rational columns |
| spatial state `spatial-record:state` | 3,105,816 | 12-16 MB | **P:** r6 `finish`.<br>**W:** `_spatial_records` / `X.compact_record`.<br>**V:** `exterior_owner.restore`, X logical metadata | JSON or envelope | Existing envelope; its cells table goes through `record_tables` |
| certification `certification-record:final` | ~0.6 MB | 2.3-3 MB | `_certification_payload` / `_restore_certification` / `_check_certification_records` | JSON + float force arrays | `record_tables` at rest; charged export on restore |
| differential geometry `differential-record:geometry` | <1.05 MB | <5.3 MB | `_differential_payload` / `_restore_differential` | JSON + network arrays | as certification |
| heat-ref `spatial-record:heat` | KB | KB | r6 `heat.reference()`, which carries the CAS receipt | JSON | stays JSON; receipt schema r4 for new intervals |
| **heat ledger** (CAS snapshot) | 356,538,370 | 1,355-1,783 MB | **P:** `HLP/private_heat_native_issuer_r12.advance` (metadata JSON + 5 binary64 fields).<br>**Pre-save V:** `checkpoint_consumer_r9._validate`.<br>**W:** r6 `forward`→`CAS.save`→`snapshot_store_r3.save`.<br>**R:** `restore_checkpoint`→`restored_binding_r9.restore`→`r3.restore` (`store.get`, 6x).<br>**V:** `_equations_body`, `_context` | one put | **New** `heat_ledger_tables`. Per-cell exact lists and `exact_paired_face_energy_j[nf]` become rational columns over a binary integer pool; `cell_ids`/`face_ids` become refs to the mesh ID column; `caller_snapshot` is hash-consed; float fields stay raw |
| other head arrays (collar, exterior-fv, audits, network, force) | ~1.05 MB / ~184 arrays | ~4-5.3 MB | numeric | raw | already compact |

**Transients not stored (memory risk R1).** These records are never written to the store, but they are large in memory:
- `bounds.record()` and `mesh.record()` in `advance_spatial`. The IV1 `preadvance-bounds.json.gz` dump alone is 20.3 MB gzipped.
- `step.graph.record()` in r6.
- `DifferentialPartition._json`.

**Historical IV1 migration (D6): convert ALL large records.**
- The IV1 exchange, graph, transport, certification and heat ledger are converted once into `interval-0000` (section 9).
- Each is verified exactly against the authenticated original bytes.
- The original store stays untouched as evidence.
- By code reading, the restart path itself reads only the IV1 partition, mesh, state and geometry via `materialise_endpoint`, and `_refresh` starts at the migrated root. So the other conversions serve future runs and reads, not this restart's correctness; WP0 confirms this.

## 2. Seams, sharing, identity and held memory per record

Rules that apply to every seam:
- **Transforms only.** Target sources are never edited. Each seam is a source transform in a WP-owned patch module.
- **Exact anchors.** Each transform requires its anchor exactly once, and WP9 applies them in a fixed order.
- **Reference-only successors.** A successor binds its compact records by reference only, as snapshot key plus descriptor digests. These are checked in `publication_check` inside the writer transaction. Aliases count toward `max_array_bytes`; references do not.
- **Migrated root logical identity unchanged.** D6 and WP13 produce a new physical `interval-0000` containing all large records in compact form. Existing partition/mesh aliases may be retained only if WP0 verifies the resulting per-put, manifest and store bounds; the old approximately 3,200-chunk observation covers those aliases alone. The original root/store stays untouched.
- **Append-only history.** Snapshots are append-only and never evicted. History is read through bounded views.

**2.1 Partition (WP4).**
- **Publish**
  - Both `_publish` branches of `header, partition_arrays = scratch.enter_context(self._partition_payload(` pass `store=`. The non-migrated branch currently writes JSON.
  - `partition_workflow_patch.payload` changes `yield header, _aliases(store, ref)` to `yield header, {}`.
- **Re-read**
  - `arrays = _COMPACT_PARTITION.workflow_arrays(self._store, previous['key'], budget=self._budget)` falls through to the small head `get`.
  - `PW.restore` opens via segment views.
- **Validate** (unchanged)
  - `compact_header(view, {}, ref) == header`;
  - `from_compact`;
  - `partition_binding != _COMPACT_PARTITION.binding(partition, _hash)`;
  - the reader's lineage check.
- **Share**
  - The IV1 DAG is pinned once, by the root. IV2 supports embed `interval_id`, so they are new.
  - Within-DAG hash-consing shares carried constraints.
  - Byte-identical segments dedupe automatically, because chunk IDs are content addresses (`_blob_id` = sha256(descriptor+raw)).
  - A retry is caught by `adapter.find`.
  - Planned 4b seeds IV2 pools from the parent's order (gated).
- **Identity**
  - Unchanged: `partition_id`, the ordered support hashes, and the streamed `iter_descriptor_json` sha256 and bytes (equal to the IV1 blob).
  - A new parity test checks the streamed hash equals `sha256(_json(descriptor()))` for a fresh partition.
- **Held** Root metadata, a small index and a page cache of at most 64 MiB.

**2.2 Mesh (WP3).**
- **Produce**
  - New `C/differential_mesh_patch.py`, anchored at `        encoded = _encode_mesh_record(record)` and the `lease = budget.reserve(8192+4*len(encoded), ...)` that follows.
  - It packs into a CompactMesh, streaming `support.record()` one support at a time, and returns `ExteriorMesh.from_compact(view)`.
  - `geometry_id` comes from streaming `iter_legacy_json`. It must equal `sha256(_encode_mesh_record(record))`.
- **Live**
  - In `advance_spatial`, at `        geometry, thermal = bounds.record(), mesh.record()`, the mesh side becomes `X.mesh_header(mesh)`.
- **Issue**
  - The existing `_issue` branch (`if is_compact(record.get('thermal_mesh'))`) yields an IndexedSpatialSnapshot.
  - r6 already passes `INDEXED.stored_mesh(mesh)`.
  - So `_publish` takes the compact branch.
- **Publish**
  - `Y.records`→`persist_mesh`→`compact_store` v3.
  - Successors drop `arrays.update({PREFIX+name: store.reference(ref['snapshot_key'], name) for name in ref['array_bindings']})`.
  - The migrated root keeps it, via an `aliases=` flag.
- **Re-read and validate**
  - `Y.restore_records`;
  - `ram_context_indexed_patch`;
  - `heat_payload_indexed_patch.materialise`;
  - `INDEXED.metric_identity`.
- **Supports** (decided by WP0)
  - If the mesh support hashes are a subset of the partition `support_ids`, the mesh keeps only a support-ID column. Its `support_reader` streams one support from the partition DAG and checks it by sha256.
  - Otherwise the supports go into `record_tables` segments.
  - There is never a single `support-blobs` array, which would exceed 512 MiB at IV2.
  - Nothing is stored twice (section 8).
- **Share**
  - The interval-invariant `grid_lines`, `voxels`, `radial_layers` and `cones` are kept as separate arrays, so their chunks dedupe across intervals (WP0 verifies they are invariant).
  - `existing_mesh` covers republication.
- **Identity** `thermal_mesh_id` is the streamed legacy sha256. At IV1, the blob sha256 equals `thermal_mesh_id`.
- **Held** Header, column index and a page cache of at most 64 MiB. Supports are never held.

**2.3 Exchange, graph, transport, heat-ref and state.** WP5 handles publication and restore; WP6 handles validation.
- **Produce** (function from WP5, registered in r6 by WP7's bundle)
  - Anchor `            result = O.SpatialExteriorAdvance(state, O._json(exchange), step.result, heat)` and its `reserve(65536+3*O._width(exchange), ...)`.
  - These pack the dict into a hash-consed CompactRecord. The graph and the finite graph share subtrees, and no JSON is built.
- **Holder** (`SpatialExteriorAdvance`)
  - Anchors `        return _hash(dict(state_id=self.state.state_id, exchange=json.loads(self._record)))` and `        return dict(result_id=self.result_id, state_id=self.state.state_id, **json.loads(self._record))`.
  - The id becomes a streamed hash computed once and cached. `record()` returns a LogicalRecord.
  - In `_publish`, `exterior_advance.record()['spatial_graph_id']` and `row.update(exterior_state=..., exterior_advance=exterior_advance.record())` use header views instead.
- **Publish**
  - A hook in `Y.records` plus the legacy anchor `                name = 'spatial-record:'+kind` turn each kind (exchange, graph, transport, heat-ref, state cells) into a segment-store record.
  - Each `record_blobs[kind]` becomes `{bytes, sha256, compact: ref}`, with the logical bytes and sha256 unchanged.
  - The check at `                self._store.put(row['key'], dict(payload, **blobs), row, publication_check=check,` is wrapped so it verifies every compact reference from manifests only.
- **Re-read**
  - `_refresh` reads about 5 MB of numeric operands.
  - `_spatial_restore_records` yields a LogicalExchange. Its `get()` returns owned, charged small values (at most 4 MiB). Large children come back as views.
  - The LogicalExchange is not a Mapping.
- **Validate** (WP6, `C/spatial_validation_patch.py`), in `validate_exchange`
  - `                _hash(exchange['spatial_graph']) != exchange['spatial_graph_id'] or`
  - `        body = {k: v for k, v in exchange.items() if k not in ('state_id', 'result_id')}` (streamed composite identity)
  - `            tr = RegionalMechanicalSnapshot({k: v for k, v in exchange['transport'].items() if k != 'result_id'}, transport)` (charged export, at most 32 MB)
  - `                graph = (exchange['finite_proposal']['graph'] if self._finite is not None`
  - `                for cell in exchange['spatial_graph']['cells']:`
- **Validate**, elsewhere
  - `validate_saved` and `transport_audit` move to row iteration.
  - In `_refresh`, `                            graph = exchange['spatial_graph']` keeps small gets, and `_hash(graph.get('support_ids'))` becomes a small export.
  - In `_check_certification_records`, `_hash(graph) != s['graph_id']` becomes a view identity.
  - r6 `validate_saved_exchange`/`validate_plan` and `_context` take views.
- **Share**
  - Within an interval: the graph and the finite graph, rows across the three face lists, and ID pools with the mesh.
  - Across intervals: only identical pool segments.
- **Identity**
  - The `record_blobs` sha256 values are canonical JSON per kind.
  - `spatial_graph_id` is a streamed `_hash(graph)`.
  - The exchange `result_id` is a streamed `_hash(dict(state_id, exchange=body))`.
- **Held** Nothing of the exchange survives `_refresh`. Validators charge per row block.

**2.4 Certification and differential geometry (WP5).**
- **Anchors**
  - `            raw = _json(records)\n            name = 'certification-record:final'`;
  - `_restore_certification` (`raw = values.tobytes()`);
  - `            raw = _json(record)\n            ref = dict(array='differential-record:geometry'`;
  - `_restore_differential`.
- **At rest** `record_tables`.
- **Restore** A charged export, because the consumers need dicts: `RegionalMechanicalSnapshot(records['force'], fields)` and `DifferentialInterval.restore`.
- **Identity** Float arrays and the header `record_blob` sha256/bytes are unchanged.
- **Held** Only `DifferentialInterval`.

**2.5 Heat ledger (WP7).**
- **Produce: H-a, selected by D2.** The packaging-only `private_heat_native_issuer_r13` assembles ledger columns directly; the numerical kernel stays AST-identical. The earlier H-b save-time tokenizer leaves live metadata JSON resident and is not the selected production path. It does not discharge WP14's live-memory requirement.
- **Pre-save validation**
  - `checkpoint_consumer_r9._validate` at `R.decoded(snapshot._metadata, budget=call._budget, cancel=cancel) as view:` becomes r10.
  - r10 streams `_equations` per cell and per face in the original order, with identical exact arithmetic.
- **Save**
  - The r6 `forward` anchor is `    receipt = CAS.save(store, result, call, cancel=cancel)`. The path becomes CAS r10 → `snapshot_store_r4.save`: an index plus segments of at most 128 MiB.
  - The receipt keeps r3's logical block: `metadata_bytes`, `metadata_sha256`, `logical_bytes` and `fields[name, shape, sha256]`.
- **Re-read**
  - `restore_checkpoint` anchor `B.restore(store, exchange['joined_heat']['checkpoint'],`. The path becomes `restored_binding_r10` → `snapshot_store_r4.open`.
  - There is no `store.get` and no 6x charge. Today that charge is 2.1 GB at IV1 and 8.1-10.7 GB at IV2.
  - `_equations_body` streams.
- **Share**
  - The cell and face ids become refs to the mesh ID column, with an order check.
  - Floats seed the next interval, so the exact values do not compound.
- **Identity**
  - `result_id` is `I._snapshot_identity` over the streamed metadata plus the field shapes and sha256s.
  - The r4 receipt is used for newly produced intervals. D6 conversion gives an authenticated legacy-r3-to-compact lookup in interval-0000; historical r3 receipt bytes and logical identities remain untouched. WP7/WP8 must test both lookup routes, so converting all historical ledgers does not make an old receipt unreadable.
- **Held** An index plus a page cache, released when the cold context exits.

## 3. Work packages, execution order and ownership

### Authoritative 21-step work sequence

**Michael's confirmed plan, 15 October 2026.** The numbered steps below are the execution sequence. Work-package identifiers are implementation ownership labels and must never be substituted for step numbers. This table supersedes conflicting step mappings in earlier notes; the detailed contracts and dependency tables below support it and do not renumber or reorder it. A step is complete only when its stated work and required evidence are complete. Separately authorised parallel package work does not complete or skip its enclosing step.

| Step | Work | Packages |
| ---- | ---- | -------- |
| 1 | Add stage timing and memory attribution so subsequent choices use measured bottlenecks. | **WP19** |
| 2 | Rerun the guarded census: record sizes, sharing, arithmetic widths, metadata and restart consumers. Inventory large live objects and their lifetimes. | **WP0a, WP14** |
| 3 | Establish shared interfaces for segmented storage, compact records, bounded views, identities and cache ownership. | **WP1, WP2, WP11** |
| 4 | Implement one sealed store per interval, the catalog, cross-file references, atomic publication and recovery. | **WP13** |
| 5 | Connect compact partition and mesh production, including shared supports and reference-only successors. Agree their shared interface first; develop disjoint parts in parallel. | **WP4, WP3** |
| 6 | Connect compact publication, restoration and validation for exchange, graph, transport, state, certification and geometry records. | **WP5, WP6** |
| 7 | Produce the heat ledger directly in compact form. Preserve the numerical kernel, historical receipt compatibility and exact accounts; complete the outstanding owner-heat check. | **WP7** |
| 8 | Remove remaining whole-record copies during construction, advance and commit. Measure representative memory peaks and release structures after their last use. | **WP14**, through the owning packages |
| 9 | Connect migration, runner and reader. Convert **all large interval-one records** in the working copy while preserving the original store. | **WP8** |
| 10 | Compose the candidate; measure actual storage, manifests, memory and available codec options. Complete affected parity, refusal, recovery and pre-advance smoke checks. | **WP9, WP0b/0c** |
| 11 | Run the guarded real interval-two advance through commit and publication, then perform independent fresh-process reopening. This establishes the **compact IV2 milestone**. | **WP8, WP9** |
| 12 | Complete measured compression, bounded caches and mapped hot-array reads. Evaluate their combined costs as well as individual gains. | **WP10, WP11, WP12** |
| 13 | Compact worker payloads, diagnostic captures and completed-query storage, retaining exact replay and restart behaviour. | **WP15, WP16, WP17** |
| 14 | Improve scheduling: cross-support batches, costly jobs first, warm worker pools and measured worker counts. Parallelise independent heat work within the memory allowance. | **WP18** |
| 15 | Add exact empty/zero-volume certificates and whole-region fast paths before subdivision. | **WP20** |
| 16 | Remove provably redundant constraints, merge equivalent charts and share constraint histories while preserving identity requirements. | **WP21** |
| 17 | Extend filtered and vectorised predicates, retaining exact fallback for ambiguous cases. | **WP22** |
| 18 | Improve exact arithmetic, invariant reuse, spatial pruning and incremental child calculations; reduce unnecessary allocations and repeated work. | **WP23** |
| 19 | Reprofile. Compile remaining hot kernels only if the specified benefit gate justifies the build and identity changes. Keep the Python reference and fallback. | **WP24** |
| 20 | Evaluate heat warm starts and iterative refinement with exact residual verification and unchanged certified records/accounts. | **WP25** |
| 21 | Integrate the final enabled combination, update measurements and complete affected advance/publication/reopen checks. Record every optimisation’s measured outcome. |  |

### Revised execution order, 16 October 2026

**Decided by the coordinator, delegated by Michael ("based on performance and accuracy").** The 15 October table above is kept unchanged as history. Rule applied: take every change that keeps results exact and saves time; take none that changes a physical number; raise no guard or limit. Full decision and evidence: section 7b of `C:/Users/LOCAL_USER/OneDrive/Documents/GitHub/atlas/.atlas-dev/plan-order-review-20261016.md`.

| Order | Work | Steps / packages | Condition |
| ---- | ---- | ---- | ---- |
| 1 | Steps 1-8 as above; Step 8 (live working memory) finishes as planned. | Steps 1-8 | unchanged |
| 2 | Connect migration, runner and reader. Catalog promotion waits for the independent fresh-process reader to pass on the sealed candidate; a sealed file left by a crash before promotion is never auto-adopted (re-run the reader, then promote). | Step 9, WP8, WP13 | |
| 3 | Before the single Step 10 composition, where ready when Step 9 is: growth change (a), stop storing and posing support constraints no component references; growth change (b), pieces proved empty do not seed next-interval charts (both for new intervals only, as a reviewed identity successor under WP21's route); WP20 exact zero/emptiness certificates; WP22 filtered predicates; WP18 cross-support batching and hardest-first ordering; the R1 record_views/record_tables batch; remaining WP23 items ranked by the hardest-query profile. Anything not ready waits until after interval 2. | WP21 (a, b), WP20, WP22, WP18, R1, WP23 | exact parity of every heat, transport and volume number; exact certificates only, certified bounds equal or tighter |
| 4 | Compose the candidate once; measure and run the pre-advance checks. | Step 10, WP9, WP0b/0c | |
| 5 | Guarded real interval-two advance through commit and publication, then independent fresh-process reopen: the compact IV2 milestone. | Step 11, WP8, WP9 | |
| 6 | After interval 2, one recomposition: Step 12 (WP10 compression stays here, since it buys disk, not speed), Step 13, Step 14 part 2 (worker counts), Steps 19 and 20. | Steps 12, 13, 14 part 2, 19, 20 | option comparisons on saved inputs |
| 7 | Interval 3 is the acceptance run for that recomposition. The Step 21 interval-two rerun is dropped. | | launches only when growth is controlled and a paper check on measured interval-two counts fits every guard and limit, with a stated time forecast |

Not approved: (c) merging siblings that carry material (changes the heat and transport discretisation); (d) re-basing carried constraints, to be revisited before about interval 100 (nesting depth limit 128).

**Clarification, 16 October 2026 (coordinator, at Michael's question).** Row 6 is not one lumped step. After interval 2, Steps 12, 13, 14 part 2, any remaining Step 18 items, 19 and 20 stay separate steps in their original order. Each keeps its own owner, tests and measured enable/disable gate, and is checked on saved inputs before the next starts. Only the final integration is combined: one recomposition, with interval 3 as its acceptance run in place of the old Step 21 interval-two rerun. Updated wording: review section 7b item 4.

**Current position:** Step 8 / WP14 is active. Steps 1–7 retain their closed, scoped evidence. Step 9 migration/runner/reader and Step 12 consumer activation remain incomplete; neither substitutes for Step 8.

### Steps 1–7 gap closure, 15 October 2026

Michael's request to fix the gaps authorises this closure. It supersedes the pause only for the missing earlier-step inventory, contracts, checks and defects. The following statuses refer to the work assigned to each step; combined candidate/runtime acceptance remains in Steps 8–11.

| Step | Requirement satisfied and bound evidence | Gap closed in this pass |
|---|---|---|
| 1 | Checkpoint-only timing and memory attribution; [WP19 receipt](test-results/wp19.json). | Updated the stale checkpoint test for both legacy and compact labels; eight affected timing controls pass, with no timing behaviour change. |
| 2 | Historical guarded census plus complete source-lifetime inventory; [WP0a receipt](test-results/wp0a.json), field `step2_gap_closure_20261015`. | Completed 25 lifecycle groups across all nine head-record families, ledger/root mesh and additional live work; bound 43 current sources. Census bytes are unchanged and were not remeasured. |
| 3 | Shared storage/view/identity/ownership contracts; [Step 3 receipt](test-results/step3-contracts.json). | Added the existing sealed-scan result and method to the shared declarations; syntax, fields and signature match the implementation. |
| 4 | Sealed files, catalog, cross-file references, publication/recovery; [component receipt](test-results/step4-components.json). | Reconciled original component evidence with subsequent source-bound Step 6/7B changes. Native storage/resource dependencies still match. The original host-denied hardlink fixture remains an explicit skip. |
| 5 | Compact partition publication and differential mesh production, shared supports and reference-only successors; [Step 5/5B receipt](test-results/step5-mesh-partition.json). | Distinguished implemented compact output/persistence from remaining native construction dictionaries and duplicate encodings. Those removals are Step 8, not a missing persistence feature. |
| 6 | Compact publication, restoration and validation of all six named families; [Step 6 receipt](test-results/step6-records-validation.json). | Resolved fresh-versus-restored consumer ambiguity: fresh graph/transport holders remain native working data; restored records use compact references. Existing parity/refusal evidence applies at its recorded scope. |
| 7 | Direct compact heat ledger, unchanged numerical kernel/exact accounts, historical receipt compatibility and genuine owner check; [Step 7 receipt](test-results/step7-heat-ledger.json), [owner result](test-results/step7-owner-heat-final-pass.json). | Fixed the later facade change that made the original heat-writer route import a Step 9-only helper. Original and facade refusal/ownership controls pass in two focused tests. |

**Closure:** the identified Steps 1–7 gaps are closed for those steps' stated component/source-transform scope. The ten affected tests in this pass passed; declaration consistency and focused lint also passed. Prior failures remain recorded. Original Step 5/6/7 receipts and the Step 7B bound changes are reused within their tested scopes; no benchmark or genuine-owner solve was repeated merely for a status refresh.

This closure does not establish representative simultaneous-live memory, complete migration/runner/reader integration, a frozen combined candidate, or a real IV2 advance. Step 8 remains incomplete and paused. The Step 9 access-violation fixture and unfinished Step 12 consumer activation remain unresolved later work. This pass changes no numerical computation or representation cost, so it makes no new time/RAM/disk improvement claim.


### Step 3: frozen joint contracts, 15 October 2026

**Scope.** This is the interface-freeze part of Stage B1. The normative contracts below, [reference value types](compact-geometry-r1/compact_contracts.py), [interface declarations](compact-geometry-r1/compact_interfaces.pyi) and [focused verification](test-results/step3-contracts.json) are the shared baseline for WP1/WP2/WP11/WP13 and WP3/WP4 support ownership. The declarations are deliberately non-executable; they do not implement or accept a storage backend, codec, cache, migration or interval advance. Completing Step 3 does not complete Stage B1. Implementations must satisfy the remaining component gates before consumer integration.

**Identity and wire format (WP1/WP13).** Keep three identities distinct: (1) the existing exact logical-record SHA-256 and canonical byte length; (2) authenticated representation/index/chunk bindings; (3) the final physical interval-file SHA-256. Compression, rechunking and relocation cannot change scientific logical IDs. Representation changes may change the second identity; file bytes determine the third. None is scientific admission by itself.

`SegmentRef` has exactly these six fields, encoded as canonical ASCII-escaped JSON with sorted keys and compact separators, at most 4,096 bytes:

```json
{
  "schema": "atlas.segment-ref.v1",
  "root_key": {"workflow_id": "<sha256>", "interval": 0, "snapshot_key": "<sha256>"},
  "identity": {"record_schema": "<logical schema>", "sha256": "<sha256>", "canonical_bytes": 0},
  "logical_bytes": 0,
  "array_bindings": {
    "schema": "atlas.binding-index.v1",
    "root_key": {"workflow_id": "<sha256>", "interval": 0, "snapshot_key": "<sha256>"},
    "digest": "<sha256>", "count": 0
  },
  "merkle_root": "<sha256>"
}
```

The placeholders above illustrate fields; they are not valid hashes. Hashes are exactly 64 lower-case hexadecimal characters. Integer fields are checked unsigned 64-bit values, with booleans refused. `record_schema` is a nonempty UTF-8 string of at most 256 bytes; the consuming domain adapter validates its allowed logical schemas. Duplicate or extra keys, unknown physical schema versions, malformed/noncanonical wire bytes and overflow refuse. The binding-index root belongs to the same workflow and no later interval than the record root. Catalog resolution establishes the actual allowed ancestor set; DTO validation alone cannot authenticate it. Root keys bind logical schema/identity, producer identity and representation profile; a matching key with different immutable invocation metadata is a conflict, never an overwrite. Exact logical canonicalisation profile is authenticated in the root metadata.

References contain no absolute paths or current-file seal/hash. The authenticated catalog maps `(workflow_id, interval)` to a safe relative file, logical seal and final physical hash. This avoids a seal hashing its own physical SHA. `canonical_bytes` counts original logical JSON bytes; `logical_bytes` counts declared typed-array bytes including externally referenced bytes. They are different quantities. `array_bindings.count` is the number of named arrays, including empty arrays. Large array inventories live behind the authenticated binding index, not inside the 4 KiB reference.

**Segments, indexes and publication (WP1).** `SegmentBackend.publish` accepts a lazy array-source factory: find a verified existing `(schema, logical identity, producer, representation profile)` before requesting arrays or encoding. Preserve an existing parent owner reference; otherwise search the current candidate then eligible sealed ancestors in deterministic earliest-owner order. Publish only missing content. Hash-consing checks exact typed content on a candidate match. No second durable global chunk store is introduced.

Every logical segment and every backing native put independently obeys all four bounds: 128 MiB logical bytes, 2,048 chunk references, 256 KiB complete encoded manifest and 64 KiB root/index metadata. Referenced bytes/chunks count even when the new file stores no copy. Partial chunks across many small arrays still count separately. Array descriptors, metadata and locator overhead count towards the full manifest. The measured historical head manifest is 586,212 bytes: the successor must use indexed bindings and be measured against the 256 KiB target, not receive an exception.

Binding/index pages are authenticated **manifest metadata**, with actual encoded page size at most 64 KiB, fan-out at most 256 and root-to-leaf depth at most eight pages. This permits `verify` to traverse manifests without fetching payload arrays. An empty `u1` carrier may satisfy the existing nonempty native array-inventory rule without introducing chunks. Refuse a page that cannot meet both page and complete-manifest bounds. Do not silently put an oversized index into an opaque payload and still call verification manifests-only.

Array names order by exact UTF-8 bytes. Within each array, logical ranges start at zero and cover the declared flattened element count exactly, without gaps or overlaps. Leaves bind array ordinal/name, dtype, shape, logical start/count and the unchanged native typed decoded-content chunk ID. Referenced leaves address a whole native chunk; a changed partial chunk is newly encoded. Repeated content IDs at distinct logical positions are valid; duplicate names, ranges or ordinal/leaf positions are not. Hash node kind, child count, ordered ranges/ordinals and ordered child digests with versioned domain separation; do not duplicate an odd final leaf to pad a tree. Any deletion, insertion or reorder changes or invalidates the content root. A separate manifest/index digest binds locators and representation details; the content Merkle excludes physical path and lossless codec. Both bindings are checked.

For these **new storage hashes only**, freeze `H(tag, body) = SHA256(ASCII(tag) + NUL + canonical_JSON(body))`, using the reference encoding above and no floats. Native typed chunk hashing and scientific identity functions remain unchanged. A content leaf uses tag `atlas.segment-leaf.v1` and exact fields `ordinal`, `array_ordinal`, `name`, `dtype`, `shape`, `start`, `count`, `chunk_id`. Global leaf ordinals increase from zero in array/range order. A branch uses tag `atlas.segment-branch.v1` with `leaf_count` and ordered `children`, each containing `first_ordinal`, `leaf_count`, `digest`; ranges are contiguous and counts must reconcile. An empty array has one zero-count leaf with null `chunk_id`; it still binds name/dtype/shape. An empty array inventory has the empty branch with zero leaves. The record content root uses tag `atlas.segment-content.v1` with `identity`, `array_count`, `logical_bytes`, `tree_digest`. Each binding page uses tag `atlas.binding-page.v1` over its complete page body excluding its own digest; page locators/typed source descriptors belong to that authenticated body. The root locator key uses tag `atlas.segment-root.v1` over `identity`, `producer`, `representation_profile`. Page-body layout is versioned under WP1; changing it requires a new page schema and affected fixtures, without changing the frozen logical identities or external reference fields.

`SegmentView.read(name, start, stop, max_owned_bytes=...)` uses flattened element offsets and returns an owned, charged typed-byte range from covering chunks only. `iter(..., block_bytes=..., max_owned_bytes=...)` yields owned byte blocks. Index metadata and outstanding returned blocks share the retained scope. `verify` reports manifest authentication only; `VerificationEvidence` separately reports full-file SHA, selective payload verification and logical-body validation, including checked payload bytes. A manifest-only call must not set the other flags.

**Generic records and exact values (WP2).** Implement the declared `RecordCodec`, `CompactRecord`, `RecordRef`, `LogicalRecord` and `LogicalExchange` interfaces. Packing takes an explicit `record_schema`, the shared scope, cancellation/guard check and optional authenticated pool seeds. Pack/hash-cons/stream the identity in one traversal. Seal the logical identity only after complete successful packing. Cancellation leaves no discoverable completed root.

These views are not `Mapping` or implicit recursive sequences. `field(name)` and `at(index)` return owner-retaining child references; a missing field raises `KeyError`, distinct from an explicit null scalar. `size` is immediate child count for a container and canonical byte length for a scalar. `scalar(max_owned_bytes=...)`, `iter_rows(max_rows=..., max_owned_bytes=..., fields=...)` and `export(max_logical_bytes=..., max_owned_bytes=...)` are explicit expansion boundaries. Row iteration returns shallow owned rows of child references; field selection does not recursively decode children. Never add a hidden whole-record `dict(view)`, `.items()` expansion or fallback decode. Generic JSON-domain packing has no partition-specific field gate; domain adapters retain their separate admission checks.

The frozen `atlas.legacy-json.v1` profile preserves the existing sorted string keys, compact separators, ASCII JSON escaping, finite binary64/Python float spelling including negative zero, and original list order. Rational compression must reproduce the **original string spellings**, including sign, radix and accepted lexical distinctions. A numeric-looking string stays a string. Only use reduced/dyadic/shared-denominator encodings after exact re-encoding parity; otherwise preserve segmented string tokens. Shared denominators reference an existing exact value, never manufacture an LCM to force sharing. No approximate conversion, silent fraction reduction or process-global integer-to-string limit relaxation.

Use byte columns for tags/signs and magnitude/token bodies, little-endian binary64 for floats, exact 32-byte content IDs, checked unsigned 64-bit offsets/lengths, and the narrowest authenticated per-segment `u1/u2/u4/u8` pool references that include any sentinel. Authenticate dtype, spelling class and key-shape ordering; refuse unknown tags, features or schemas. Physical-schema dispatch is explicit: a new compact format never falls through to opaque legacy JSON.

The WP0a heat maxima require 256,808 numerator-magnitude bytes and 256,818 denominator-magnitude bytes; the largest encoded pair is 1,027,263 bytes and crosses many 64 KiB chunks. Preserve the existing 1 MiB **individual binary-magnitude** ceiling. The measured values fit that ceiling; this is not evidence that decoded rows, arithmetic or IV2 fit memory. Before decoding, derive a charged bound from descriptors, exact integer/string expansions, scratch and retained outputs. Bound both row count and bytes. An oversized row uses an explicit field/scalar streaming route or refuses before allocation; it never bypasses a block cap. The existing 32 MiB transport export remains an explicit charged exception for that consumer, not a general graph/heat export allowance.

**Shared supports and parent pools (WP3/WP4).** `support_source(partition_view)` accepts a sealed compact partition in the same retained scope. Its binding contains the partition `SegmentRef`, ordered support-inventory digest and count. `id_at`, `ref_for`, `identity`, streamed JSON and explicit export preserve each support's exact content ID and canonical length. Mesh v3 owns only its ordered support-ID column and the authenticated source binding; its order need not match partition order. Resolve every ID exactly, verifying the corresponding support body. Missing IDs, changed bytes or length, foreign scopes and unsupported routes refuse. Do not stage per-support snapshots or a second `support-blobs` copy. One-support native materialisation may use an explicitly bounded owned export. No automatic fallback to duplicated v2 storage.

The 2,016 identical historical supports and their 113,020,661 matched bytes justify this design for the inspected input; future meshes still undergo coverage/content checks. Similarly, graph and finite-graph adapters may share the measured 97,664,880 identical field-value bytes but retain different cells/transfers and distinct whole-record identities.

Parent seeding initially covers value, ID and key-shape pools. Require compatible profiles, authenticated parent bindings and the same scope. Preserve parent entry order and immutable segment widths/bytes; append entries, allowing wider **new** segments through the authenticated directory. Do not seed a whole unreachable parent node DAG. Versioned unused pool entries are distinct from hidden unreachable scientific nodes, which remain refused. Any locality permutation must prove bijection, inverse and coverage; canonical output follows original logical order. Pool seeding/reordering remains disabled until its measured benefit gate passes.

**One retained budget and explicit ownership (WP11).** `create_retained_scope` creates one 256 MiB child of the exact existing run `WorkBudget` for the complete cold/post-publication context. Every view, cache, interval handle, index and outstanding owned read uses that same scope; never one allowance per file/view/worker. Reject foreign scope/owner adoption. Charge each unique backing allocation once, plus prepaid owner/key/index capacity and pending reservations. Copies are separate allocations. The scope's declaration does not replace the existing `WorkBudget` API: `reserve`/`try_reserve` remain context managers, and the new `Reservation` keeps an entered context alive through ownership transfer.

Reserve before allocation. A `ChargeSpec` includes backing capacity, owner/container overhead and index/key capacity, not merely used payload length. `commit` attaches the **same** reservation to the resulting owner; no release/re-reserve gap or unsupported cross-budget reparenting. `Owned.retain()` creates a paid ownership carrier for the same backing. Callers retain the wrapper while using `.value`; a raw escaped value is not self-owning. Explicit owner/view close refuses live child borrows. Cache retirement and stream close release only unborrowed resources; the final idempotent release occurs after the last borrower, dependency or held failure reference. Independently retained tracebacks and suspended/failed generators cannot leave reachable buffers uncharged. A yielded owned block remains valid and charged after generator advance/close.

Support cache 128 MiB, certified-fact cache 64 MiB, page cache 64 MiB and verified-hash set 20,000,000 bytes/200,000 entries are subordinate **cache-retention quotas**, not additive allowances or mandatory-read size limits. A valid 128 MiB read may bypass the 64 MiB page cache when the aggregate/run budgets permit. A cache taking custody of an already owned backing does not charge the backing twice. Declined insertion leaves the caller's owned value intact. Keep the native decoded cache disabled when WP1 supplies the single page-cache layer.

Optional admission evicts eligible unpinned entries and retries once, then returns a decline without worker revocation or mandatory-refusal accounting. Mandatory reads reclaim eligible entries and use existing mandatory admission; an unresolved shortage raises `MemoryLimitError`. Pinned entries cannot be evicted or credited as reclaimed. WP11 does not register a second `_revoker`, replace `_scope`, or change the existing optional-worker owner; current resource ancestry permits only one owner. Never hold a cache lock across admission/revocation or cancellation callbacks. Codec/row scratch, producer state and worker/export workspaces remain separately charged to the run budget. Escaping results belong to the retained scope; scratch cannot become an uncharged output. Logical reservations are not measured RSS. The 12 GiB process-tree RSS ceiling, 1 GiB free floor, 10 GiB start gate and 16 GiB logical run limit are unchanged.

Cache keys are immutable and domain-separated. Support keys bind exact support identity plus decoder/schema. Page/hash keys bind process epoch, authenticated immutable file identity, typed chunk ID and descriptor digest. View-seal keys bind ordered descriptor bindings, logical schema/profile and identity. Fact keys include predicate kind, every ordered and role-labelled exact operand, every result-affecting parameter, method/execution identity and certificate/verifier schema; no operand reordering without an established symmetry contract. Verify before insertion and check cancellation before returning a hit. Certified false results may be cached; cancellation, budget refusal, timeout, partial proof and operational declines may not. Fresh processes revalidate required bytes.

Report current/peak aggregate charges, pending/live/pinned/evictable/non-cache bytes, category current/peak occupancy, entries/hits/misses/insertions/evictions/declines/reclaimed bytes in existing receipts. Do not sum overlapping cache occupancy as physical memory. Cache activation still requires net measured benefit and cache-on/off exact parity; this contract does not enable caches or claim savings.

**Interval set, catalog and atomicity (WP13).** The external catalog schema is `atlas.interval-catalog.v1`: workflow ID, unsigned generation and ordered entries. Each entry has interval, safe relative filename, final file SHA-256, logical seal, nullable parent interval/seal, head `SegmentRef`, producer/runtime identities and sorted unique `(earlier interval, seal)` references. Entries are contiguous from migration root zero; a successor's parent is the preceding entry. Bound the complete encoded catalog at **1 MiB**; charge its decoded/index/rewrite allocations. Refuse before promotion if it cannot fit. No silent history pruning or paged-format fallback. This is a new envelope bound, not a raised store limit.

`IntervalStoreSet.open_catalog`, `begin_interval`, `resolve_manifest`, `resolve_chunk`, candidate `seal` and store-set `promote` use the declarations. `create_migration` is the explicit absent-catalog bootstrap: it binds a new workflow ID and scope without accepting a head; only `begin_interval(parent=None)` for root zero is legal there. `head` and expected catalog digest are null until the D6-verified migration root is promoted. Existing-catalog opening never silently creates a workflow. Resolvers take the requester interval, enforce catalog membership and ancestor closure, and reject missing, future, cyclic, foreign, unsealed or unlisted dependencies. A writer may address its own unlisted candidate; accepted readers may not. Validate safe catalog-relative basenames, reject traversal/absolute/reparse escapes, and bind the opened file identity. Never search arbitrary paths or use a changed file's pathname as a trusted cache identity. Default files remain `interval-0000.sqlite`, `interval-0001.sqlite`, etc.; an orphan name collision refuses instead of overwriting or auto-adopting it.

Open the latest and only required ancestors lazily and genuinely read-only. At most **eight** handles may be open; actual funded native cache/metadata costs count in the shared retained scope. Pins protect borrowed handles. If all eight are pinned, refuse another open rather than evicting a borrower or silently opening a ninth. Validate reference closure and seals when each required file first opens; validate decoded chunk payloads on reads. Full physical-file SHA verification is a separate explicit evidence scope.

The frozen `ArrayStore` constructor performs writer PRAGMAs and `BEGIN IMMEDIATE`; its `ArrayReference` includes an absolute store path and rejects another store. Its strict v1 snapshot chunks are local string IDs and its SQLite schema rejects extra tables. Therefore WP13 must implement a reviewed **read-only opener and versioned logical binding layer**, not call that constructor on sealed history or insert cross-file objects into v1 chunk arrays. Preserve ordinary per-file ArrayStore v1 schema and native typed chunk hashing. Cross-file locators live in the new bounded authenticated metadata/index layer; native payload arrays refer only to locally owned chunks. The storage integrator is the single writer of any shared storage transforms. Existing single-file behaviour must pass unchanged before integration.

Seal preimage: version/workflow/interval; sorted `(snapshot key, manifest-body SHA)` inventory; sorted unique local `(typed chunk ID, descriptor SHA)` inventory; parent logical seal; sorted unique external `(owner interval, owner seal)` edges. Exclude exactly one reserved final seal snapshot and the physical-file SHA. The reserved snapshot has a zero-chunk carrier, so exclusion cannot hide data. Domain-separate this seal from record/index/content hashes. The final physical hash lives only in the catalog.

Use `H("atlas.interval-seal.v1", body)` with exact body fields `workflow_id`, `interval`, `manifests`, `chunks`, `parent_seal`, `references`. Inventories are arrays of the pairs above, ordered by key/ID or numeric interval, with duplicate keys refused; parent seal is null only for migration root zero. Canonical hash preimages stream through bounded owned blocks; this wire definition does not permit building the complete inventory or logical record in memory. Hash each native canonical typed descriptor as `H("atlas.chunk-descriptor.v1", descriptor)` for the seal inventory, without altering the native chunk ID. The reserved seal snapshot key is `H("atlas.interval-seal-key.v1", {"workflow_id": ..., "interval": ...})`; exactly one such final snapshot is permitted. Its immutable metadata binds the seal and its version, and its empty carrier has no payload. Root keys for ordinary records must not use this reserved identity namespace.

Publication transitions are **WRITING -> QUIESCED -> SEALED -> CATALOG_PROMOTED**. Join writers/codec jobs, commit and finalise journals/WAL, then close ordinary writable handles. A sole final seal writer writes the seal snapshot, flushes and closes; hash final bytes and allow no later writes. Verify required ancestors. Under the single-writer publication lock, check the expected parent/catalog digest, write and flush a complete temporary catalog, then use the supported Windows durable atomic replacement. Only promotion accepts the head. Before replacement the previous catalog remains authoritative; after a completed replacement the whole new entry may be visible, never a hybrid. Retain unlisted sealed files and temporary catalogs as unaccepted diagnostics; no auto-adoption/deletion. Process-crash simulation alone does not prove power-loss durability. Active sealed files are never recompressed in place; the existing L1 archive-copy boundary remains.

**Implementation gates and next ownership.** The pure reference/budget-shape checks in the Step 3 receipt establish only the declared wire boundary. The following remain mandatory before Stage B2 integration:

| Owner | Remaining component evidence |
|---|---|
| WP1 + storage integrator | 600 MiB segmented record at unchanged native limits; fragmented-array/ref/manifest ceilings; order/duplicate-position tamper refusal with valid repeated content; manifests-only traversal; find-before-encode; cancellation without partial root; unchanged-prefix staging. |
| WP2 | Existing 1,217-spelling corpus plus negative zero, escaped/non-BMP strings and lexical rational variants; exact giant-value streaming/charged-export refusal; non-Mapping traversal; unknown format/tag/dtype refusal; bounded row/DAG ownership; composite identity parity. |
| WP11 | Aggregate pressure/refusal before allocation; shared backing charged once; mandatory read bypasses optional cache quota; pinned eviction and optional-worker owner preservation; held exception/traceback/generator lifetimes; foreign-scope refusal; key isolation/cancellation and cache-on/off parity. |
| WP13 + storage integrator | Three sealed interval files with actual shared chunks and no duplicated unchanged payload; read-only cold/fresh-process reader; catalog/path/closure/identity/handle refusals; final-hash/no-later-writer checks; every publication crash point and actual supported Windows durability; old single-file tests. |
| WP3/WP4 | Shuffled mesh-vs-partition support order; exact complete support coverage; missing/changed/foreign support refusal; no duplicate support arrays; one-support native ownership; parent-pool dtype/append/unused-entry and permutation checks. |
| WP0/WP8/WP9 | Add explicit handlers for the frozen new physical formats before compact census; measure complete head/catalog/index/row/retained costs on the actual candidate; integrate reviewed current inputs and affected source identities before any migration or advance. |

Step 4 supplies the WP1/WP2/WP11/WP13 component evidence below; Step 5 supplies the core shared-support WP3/WP4 evidence. The table retains the original scope of each gate. Optional pool/permutation/support-cache benefit gates and WP0/WP8/WP9 integration remain outstanding. No physical savings, IV2 memory fit, backend acceptance or runtime readiness is inferred from Step 3 alone.

### Step 4: compact components implemented and tested, 15 October 2026

**Status: COMPLETE at component scope; Stage B2 and real-workload acceptance remain INCOMPLETE.** The [component receipt](test-results/step4-components.json) binds the implemented sources, frozen native dependencies, final combined test cases and measurements. Of 92 tests, 91 passed and one actual-hardlink fixture was skipped because the Windows sandbox refused its creation. Focused Ruff and declaration syntax checks passed. No original database, frozen RC1 composition or historical reviewed-input pin was changed; all new stores were synthetic fixtures.

- **WP1:** `segment_store.py` publishes bounded typed chunks and authenticated metadata indexes, finds existing records before requesting arrays, verifies ordered complete coverage without payload decoding, and reads only covering chunks. A real-limit 600 MiB logical fixture contained 9,600 distinct native chunks. Peak logical run reservations were 34,980,880 B and peak retained reservations 24,495,120 B. These are charged reservations, not RSS measurements. Authenticated reordered/duplicate ranges, cancellation, changed-prefix staging and held read ownership are covered.
- **WP2:** `record_tables.py` and `record_views.py` implement exact generic columns, shape/ID/integer interning, narrow references, rational/dyadic encoding, lexical fallback and explicit owned traversal/export. The original 1,217-spelling corpus and the measured 1,027,263-byte giant pair pass. A high-sharing 203,088,011-byte logical graph used 52,511 column bytes; a second graph copy added 76 bytes (0.145%). That fixture is not an estimate for all unique records. Builder and validation workspaces each have a fixed 256 MiB ceiling; import row scratch is at most 32 MiB, and final tables use the existing aggregate retained scope. Oversized unique imports refuse explicitly; no spill path exists. Parent-pool seeding and locality reordering remain disabled pending their benefit gates.
- **WP11:** `content_cache.py` and `certified_fact_cache.py` implement shared backing ownership, dependency pins, charged streams, pressure/eviction, exact cache keys and failure-frame retention. One existing run-budget child owns the aggregate 256 MiB retained scope; no second worker revoker is installed. Runtime certified-fact hooks, support caches and their representative benefit gates remain later work.
- **WP13:** `interval_store_set.py` and `interval_catalog.py` implement unlisted candidates, read-only sealed files, native typed-content sharing, bounded catalog CAS, final seals/hashes and eight-handle ownership. Tests cover a real three-file shared chain, archive recompression, five process crash boundaries, native single-file compatibility, corruption/closure refusals and fresh-process reopening. Previously verified file tokens stay charged and checked even after handle eviction. Actual Windows flush/write-through calls are exercised; hardware power-loss durability is not measured. The API basis is [MoveFileExW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexa) and [FlushFileBuffers](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-flushfilebuffers).

**Combined read result and bounded reuse.** The first sealed codec reopen exceeded its 60-second test limit. A bounded profile isolated repeated scalar-to-manifest reads and redundant path checks. The correction preserves full before/after path, sidecar and file-identity checks, and uses the shared 64 MiB page quota for immutable, authenticated complete columns no larger than 64 KiB. Cache misses under pressure fall back to the required scalar read; larger columns and unlisted candidates keep direct bounded reads. The same 73,080-byte record then reopened in a fresh process in 10.206 seconds and streamed with exact logical SHA/length parity. On the actual sealed-file 128-lookup sample, reuse reduced underlying reads from 128 to one and elapsed time from 1.716 to 0.461 seconds. The in-memory fixture was slower with reuse, so this is a disk-path result, not universal acceleration. Future WP3 page consumers must share the same verified category implementation or integrate a common verifier; a second independent page cache is refused. No whole-run speedup or IV2 fit is claimed.

**Step 4 handoff:** Step 5 / Stage B2 starts with WP3 mesh v3 and WP4 partition v2, including partition-owned support bindings, exact coverage and the compact producer/consumer boundary. Its current checkpoint follows below. Existing checkpoint-only timing remains unchanged.

### Step 5: mesh v3 and partition v2 component integration, 15 October 2026

**Status: COMPLETE at core component and source-transform scope.** [Bound evidence](test-results/step5-mesh-partition.json). Partition v2 owns the exact generic descriptor DAG and ordered support inventory. Mesh v3 stores ordered support IDs plus an authenticated partition binding, with separate static tables; it stores no duplicate differential support bodies or per-support snapshots. Shared chunks are reused by exact content identity. Logical support order, body/descriptor hashes, native geometry IDs and provenance remain unchanged. Explicit older-format readers remain available; the v3 route refuses unsupported or mismatched sources rather than duplicating support bodies. Reused mesh references also authenticate the producer digest against the sealed root.

**Implemented boundary.** Fresh native partition payloads and both publication branches emit reference-only headers. Fresh mesh packaging, indexed spatial persistence/restore and the ExteriorMesh/MimeticGeometry ownership seams retain compact views. Direct routing and pressure consumers accept authenticated v2 support references, with bounded owned exports only where native computation needs one support or constraint. Sealed metric identity avoids a second full mesh stream. Parent-pool seeding, locality permutations and the decoded-support LRU remain disabled pending their WP4/WP11 measurement gates; this is not acceptance of every optional WP4 optimisation.

**Shared reader correction.** Initial small compact cold opens exceeded 120 seconds. Repeated support hashing, raw slices bypassing reuse and per-scalar physical-path checks were corrected without raising limits. Internal non-yielding reads use serialised before/after freshness checks and retain cancellation checks; each streamed block exits that scope before escape. Authenticated native chunks of at most 64 KiB now also serve larger columns through the existing 64 MiB page quota. An optional paid directory holds at most 128 chunk bindings; it holds no payloads. Optional pressure falls back to required bounded reads. Root's 23 affected view/codec/stream-input tests and two compound-read tests pass, with the final native-page lock covered separately. The bounded large-column sample dropped from 40 underlying reads to one. These are compact component measurements, not a legacy whole-workflow speed comparison.

The first large cold attempt cancelled at its 600-second test deadline while streaming the partition descriptor for generic validation, before domain or mesh admission. Retained bytes stayed near 18.1 MB. A warmed 4,000-lookup profile found repeated cache verification and owner-carrier admission even with zero underlying reads. The correction holds at most 128 paid immutable page borrows from the same shared cache within one compound read, releasing them before return/yield. It preserves paid failure-traceback lifetime and drops optional pins before a required pressure fallback. Focused view/stream-input and shared-source tests pass. The same large fixture subsequently passed in a fresh process in 505.599 s; the earlier timeout remains failed evidence.

**Large gate and limits.** The 7,700-support fixture contains 674,649,790 support logical bytes, a 675,180,856-byte partition descriptor and 675,698,476-byte mesh. It published and reopened at the unchanged native limits, with exactly one full mesh stream and 31,601,894 retained bytes after open (30.14 MiB, below 64 MiB); all reservations released on close. The largest observed diagnostic sample was 44,708,810 retained bytes, not a measured process-RAM peak. Catalog plus store occupied 886,168 B (865.40 KiB). This deliberately high-sharing fixture repeats an 81,920-byte token: it is not 600 MiB of unique physical data, a general compression ratio or proof of real IV2 fit. No matched old completed-open RAM or physical-store baseline exists. Separate small two-process, native identity/header, mixed static/shuffled-support, reference-only successor, producer-lineage and routing/pressure controls pass. One pre-existing superseded stand-in test remains skipped; focused Ruff has no introduced findings, retaining seven pre-existing B905 findings. Optional standalone Pyright remains unconfigured for this component directory and is not claimed passing.

**Outstanding integration.** WP5/WP6/WP7 own remaining publication, validation and heat work; WP8 must adapt the legacy-only geometry-transfer/materialisation route and connect the runner/readers. Persisted v2 failure-diagnostic replay remains WP16: current capture refuses explicitly while preserving the original error and making no new memory admission after a budget refusal. WP14 still needs representative combined live-memory evidence. WP9 must compose the current reviewed sources, and WP0b must add new-format census handlers and measure the actual compact working copy before real migration or IV2 acceptance. No original database, frozen runtime or historical source pin is changed by this component work.

**Step 5B: cold mesh preparation, COMPLETE, 15 October 2026.** The user authorised the remaining preparation bottleneck as a bounded follow-up. `CompactMeshStoreV3.open` now encloses header reconstruction, static/shared support coverage, derived-column hashing and admission in the existing mesh/partition compound-read scopes. This borrows the already charged pages; it introduces no new cache, skipped validation, changed format or higher limit. Both sources must pass the closing freshness check before the mesh escapes. Scalar cancellation remains active. Preparation and admission statements are unchanged apart from their enclosing scopes and local metadata cleanup.

The same sealed 7,700-support fixture reopened in **306.727 s (5m07s), previously 505.599 s (8m26s): 198.871 s / 39.3% less elapsed time in this single comparison**. The targeted preparation interval fell from **162.993 s to 1.578 s (99.0% less)**. Retained allocation after open stayed **31,601,894 B (30.14 MiB)**; catalog/store stayed **886,168 B (865.40 KiB)**. Process memory is newly measured: working set at open 149,803,008 B (142.86 MiB), process-lifetime peak observed through the final support check 153,649,152 B (146.53 MiB), and private-commit peak 1,130,541,056 B (1.053 GiB). These are distinct from retained accounting and a minimum RAM requirement; there is no historical process-memory baseline. Unchanged validation phases varied too, so the entire elapsed reduction is not attributed solely to this patch. OS cache state was uncontrolled on both runs. Added checkpoint observation cost was 0.00229 s, included without adjustment.

Three targeted preparation tests pass (page reuse, cancellation before admission, final mesh/partition freshness refusal), plus the five existing mesh controls and two fresh-process differential controls. The differential module's initial combined invocation refused its required fresh-process boundary; the corrected separate invocation passed. Owner review preserved those results at their affected scope; final metadata cleanup is covered by the three targeted tests and large run. Exact logical identity, one full mesh stream, 7,700 supports / 674,649,790 support logical bytes, zero reservations after close, unchanged fixture/source hashes during the measured run and focused lint all pass. [Existing Step 5 receipt, Step 5B checkpoint](test-results/step5-mesh-partition.json), [raw measurement](probes/step5b/run-20261015-r1/measurement.json). The remaining approximately five minutes is chiefly generic, partition and mesh validation. WP5/WP6 then WP7/WP8 remain next; optional cache/arithmetic acceleration retains its later measured gates. No real migration, IV2, frozen composition, source repin or scientific acceptance occurred.

### Step 6: compact records and validation completed, 15 October 2026

**Status: COMPLETE at WP5/WP6 component and source-transform scope.** `spatial_records_patch.py` publishes one authenticated compact DAG bundle with per-kind logical byte counts and SHA-256 values; graph and finite-proposal graph share the same subtree. Publication verifies manifests before head commit. Restore verifies the used logical children, returns an explicit non-Mapping exchange and preserves owned compact state cells through native adoption. Certification/differential restore keeps its bounded explicit exports and original numeric-array checks. `exchange_record_patch.py` packs the fresh body once, retains native transport/heat handles and caches the exact original composite result ID. Fresh state cells also pack once when the owner has its existing retained scope; the legacy route is preserved.

`spatial_validation_patch.py` routes native validation through paid small fields, streamed hashes and rows, with the existing 4 MiB field/row and 32 MiB transport caps. A structure-aware direct export handles larger fields without whole-record JSON buffers; the established JSON decoder remains the fast path for ordinary rows up to 32 KiB when its existing conservative admission fits. This avoids an observed small-row slowdown from using direct traversal everywhere. No allocation limit was raised. A 6,429,821-byte synthetic transport plus 7,700 support IDs and conductivity values fit their unchanged caps. Failed tracebacks and escaped rows/cells retain their funding.

**Evidence.** Seventy-six distinct focused tests pass across the new components, shared codec/views, native compact-cell restore and legacy indexed/workflow boundaries, reusing checks only where the affected route stayed unchanged. This includes **442 legacy/compact route comparisons** across eleven validation routes, the twelve mutation cases plus valid inputs, and actual public exchange overlays. The runner's eleven structural checks pass with compact metadata without payload reads. Workflow transforms compose with both existing partition stages and refuse repeated application. Focused Ruff is clean. The synthetic successor has a **7,680 B numeric payload** and an **8,226 B actual native complete manifest**, below the 2% and 25% targets. Every per-kind logical hash matches legacy; repeat publication adds no chunks. [Step 6 owning receipt](test-results/step6-records-validation.json).

**Measurements.** The final matched fresh-process producer sample changed tracked peak allocation from **47,335,976 B to 2,286,908 B (95.2% less)**, retained allocation from **3,391,552 B to 177,402 B (94.8% less)** and sampled process peak working set from **129.00 MiB to 119.29 MiB (7.5% less)**. Packaging was **slower: 0.01675 s to 0.14576 s**, an extra 0.12901 s. This deliberately shared synthetic fixture is neither a full-workflow benchmark nor a minimum-RAM claim. Shared-codec changes after the earlier observation justified one final fresh process per mode, with the relevant source files checked unchanged before/after. [Final producer measurement](test-results/step6-producer-final.json). The [earlier observation](test-results/step6-producer-measurement.json), which lacked helper-file bindings, remains historical.

The separate synthetic publication fixture used **54,664 B for its sealed interval and catalog**, plus **32,768 B for the separate native numeric-head database**; no matched legacy persistence or process-RAM baseline was measured. Packing/sealing observations were 0.12614/0.02301 s; a later correctness rerun varied to 0.20666/0.03107 s, so neither is a speedup claim. Final compact row processing used **166,720 B additional tracked allocation at both 1,000 and 3,800 rows**, taking 0.10629/0.43110 s. This compares compact scale, **not old versus compact row memory**. The interim direct-only decoder's 102,252 B row figure and slower timings remain in raw evidence but do not describe the final small-row fast path.

**Continuation.** WP7 must register the producer transforms and finish the heat ledger, cold bridge and restored `validate_for` consumers; WP8 must attach the existing owner scope and connect materialisation/runner/readers. WP9 remains the frozen-composition owner. WP14 still needs combined representative live-memory evidence; WP0b must measure actual compact working data. No historical database, frozen runtime/source pin, guard, real migration or IV2 run was changed or advanced by Step 6. The interrupted unsealed synthetic reopen, corrected ownership/fixture failures, superseded uncommitted disk observation and decoder-size repair are retained in the owning receipt.

### Step 7: compact heat ledger and checkpoint completed, 15 October 2026

**Status: COMPLETE at WP7 component, source-transform and bounded genuine-owner checkpoint scope.** Exact rational ledger tables preserve original numerator/denominator spelling, canonical metadata hashes, result IDs and float bytes. v3 mesh cell/face IDs and repeated caller IDs share admitted mesh columns after exact order checks. The r4 store uses bounded segments rather than one oversized metadata array; new r4 receipts and authenticated historical-r3 lookups both reopen. Historical receipt bytes and original stores remain unchanged.

The explicit compact successor emits r13 packaging, r10 checkpoint/restored consumers and r4 storage, registers the Step 6 producers/validators and reconciles their dependency pins. The numerical kernel AST and r12 logical method/schema labels remain unchanged. Streamed equations and bounded cold adapters replace whole-ledger decoding. Forty-four distinct focused tests pass across recorded runs; focused Ruff is clean. The [owning receipt](test-results/step7-heat-ledger.json) preserves individual evidence, source bindings and limits.

**Genuine owner check.** The [final fresh-process fixture](test-results/step7-owner-heat-final-pass.json) uses the actual PreparedSpatialOwner and SpatialOwnerTransport with a fresh compact mesh: 236 cells and 832 faces. r13 advances, r10 validates, r4 saves and seals, and r10 restores exactly the same result and all five arrays. The complete fixture took 184.09 s, with zero retained bytes after close; this includes setup and accounting checks and has no matched old-method timing baseline. Its fresh mesh is the explicit in-memory compact route; v3 partition-owned ID sharing is covered separately. Genuine origin is true, fixture-only is false and production acceptance remains false. The first extended check exposed a SegmentView/SegmentInfo reference cycle after successful restore; a one-way descriptor now releases metadata promptly while escaped descriptors retain funding. The failed log remains evidence.

**Large ledger.** The 80,000-cell / 240,000-face synthetic fixture round-tripped **616,160,149 logical metadata bytes** at unchanged real limits. Packing/saving took **39.94/10.50 s**; fresh-process reopening took **206.60 s**. Tracked peaks were **74.54 MiB writing / 30.09 MiB reopening**, with **18.52 MiB retained at open** and zero after close. Its interval plus catalog occupy **71,056 B**, using deliberately extreme sharing. The raw cold recorder's 76,611 B included evidence files; it is not the physical-store figure. There is no old-format time/RAM/disk baseline or measured process RAM for this fixture. Original measurement bindings and their limitations are retained; later shared-ID/provenance branches and the lifetime repair have focused coverage, without presenting the large timings as a final-code rerun.

**Matched observations.** The final 512-cell / 1,536-face synthetic comparison preserves identical 4,051,335-byte metadata, result identity and all five arrays. r3 to r4 save time was **0.14906 to 0.11297 s**; reopening was **slower, 0.06102 to 2.12556 s**. Reopen tracked peak fell **48.69 to 30.09 MiB (38.2%)**, sampled process peak working set **145.89 to 128.70 MiB (11.8%)**, and physical store **135,168 to 120,206 B (11.1%)**. These are single observations, not an overall workflow gain or a minimum-RAM requirement. Save timing excludes input packaging; both final children import the codec before timing. The earlier observation used lazy codec import and predates the lifetime fix, so cross-round timing changes are not attributed solely to that fix. [Final matched evidence](probes/step7/matched-r2/measurement.json).

**Handoff and limits.** WP8 must connect the existing scope, materialisation, runner, reader and authenticated historical source admission. Storage receipt compatibility does not itself admit historical source identities. WP9 must select the explicit compact successor and bind current sources. A diagnostic of the older composition entrypoint refuses the current mesh-v3 helper inventory at its missing content_cache import; its old closure is not accepted for the new candidate, and the import guard was not widened. WP14 combined live-memory evidence and WP0b actual-data measurements remain outstanding. No historical data migration, frozen-source repin, guard change or IV2 advance occurred.

### Step 7B: compact reopening optimised, 15 October 2026

**Status: COMPLETE at the bounded reader scope.** Sealed record admission now visits each authenticated native leaf once, including empty columns. Scalar access reuses typed views of the existing paid page borrows within a read batch. Canonical reconstruction reuses small exact DAG fragments in an optional, per-traversal 1 MiB LRU: at most 1,024 entries, each no larger than 64 KiB, with separately charged bounded construction and a direct fallback if admission is refused. Every ordered logical byte still enters the identity hash. Structural validation, exact spelling, reachability, native authentication and real store limits remain enforced. Shared mesh-ID and generic streams check cancellation/freshness before returning each block.

**Matched result against the preserved Step 7 compact reader.** The same saved 616,160,149-byte logical ledger reopened in **31.24293 s versus 189.07803 s: 83.5% less time, or 6.05x faster**. The small saved fixture improved from **2.05859 to 0.84264 s: 59.1% less time, or 2.44x faster**. Small figures are medians of three fresh processes per version; the large comparison has one process per version. Both include catalog verification, exact restore, field hashes and closure, with identical result/metadata/array identities and zero reservations after close. Fixture and receipt bytes are unchanged. [Matched evidence](probes/step7b/measurement.json).

**RAM and disk.** Tracked peak stayed **31,552,512 B (30.09 MiB)** for both fixtures. Sampled peak process working set was **127.84 to 127.38 MiB** for the small fixture and **132.30 to 131.96 MiB** for the large one; those tiny differences are treated as effectively unchanged, not a proven RAM saving. Sampled private peaks were 98.27 to 97.80 MiB and 102.47 to 102.22 MiB respectively. Physical interval/catalog size stayed **120,206 B small / 71,056 B large**. Retained-at-open accounting changed by only +76/+112 B; exact values and separate lifetime peak counters are in the evidence. Observed peaks do not establish minimum RAM requirements.

**Checks and limits.** Sixty-five distinct focused tests pass across the recorded runs, including the final 46-test record/heat/store/consumer/composition suite; focused Ruff is clean. The existing [Step 7 receipt, Step 7B checkpoint](test-results/step7-heat-ledger.json) binds the sources and test evidence. A source check detected concurrent WP10 codec work; a separate dependency-only reopen confirmed that codec module is absent from this benchmark's read path. It was neither reverted nor included in the Step 7B acceptance claim. The earlier 206.60 s large timing remains historical; 189.08 s is this matched baseline. OS cache and unrelated system load were uncontrolled, the large fixture deliberately uses extreme sharing, and these are component gains rather than an end-to-end workflow result. Historical r3 performance was not rerun; the small compact reopen still exceeds its previously recorded 0.06102 s. The original genuine-owner result remains bound to its original Step 7 sources. No real migration, frozen-source repin, numerical-kernel change or IV2 advance occurred. Continue with Step 8, then Step 9; retain WP14 combined live-memory and WP0b actual-data obligations.

**Deferred reopen optimisation targets (Michael, 15 October 2026).** Keep these for a later measured optimisation pass; do not extend Step 7B now. First profile the remaining final-reader cost on the same saved fixtures, separating native decoding, column validation, DAG traversal, canonical-byte construction/hashing and ownership/file-check bookkeeping. The saved pre-7B small profile measured only 0.000295 s in ten decompression calls; it does not apportion the remaining 0.84264 s after Step 7B. Investigate fewer repeated traversals and redundant reconstruction, more batched typed-column processing, and safely reusable authenticated validation results bound to immutable source/representation identities. Any combined passes or reuse must preserve every required check, exact ordered logical hashes, cancellation, freshness, bounded ownership and optional-cache fallback. Compare time, process/tracked RAM and physical disk against the saved Step 7B baseline before enabling changes. Do not assume compression is the bottleneck or weaken checks to improve timing.

**Large-fixture size clarification.** The 616,160,149 B figure is the expanded canonical logical metadata size. The fixture was already persisted as compact, deduplicated, compressed data; its physical interval plus catalog occupy 71,056 B (about 69.4 KiB). This deliberately repetitive synthetic fixture exercises large logical size and sharing, not 616 MB of unique physical data, a general compression ratio or a real-workload capacity guarantee. Reopening streams the logical identity without holding the whole expanded ledger in RAM.

**Sequencing.** Michael resumed Step 8 on 15 October 2026 after the logical-versus-physical fixture-size clarification. Future reopen optimisation remains deferred above.

### Step 8: live working-memory optimisation (WP14), ACTIVE, 15 October 2026

**Active file ownership.** The partition worker completed its live-partition helper/tests and the explicitly handed-off incremental record_tables.py / partition_v2.py builder; it now owns the scaled simultaneous-live measurement. The mesh worker completed differential_mesh_patch.py, exterior_mesh_patch.py, mesh_tables.py, live-mesh and live-collar helpers/tests. The spatial/heat worker owns exchange_record_patch.py, spatial_indexed_patch.py, spatial_validation_patch.py, heat_ledger_issuer_patch.py, private_heat_mesh_patch.py, live-spatial helpers/tests and the genuine owner measurement. Root owns spatial_records_patch.py, private_heat_bundle.py, live-finite and compact transport-result helpers, test-only source composition and these records. Shared writers stay ordered. I/H/RC1 sources stay unchanged.

**Implementation checkpoint, 15 October 2026.** Direct compact partition/mesh construction, bounded graph/transport/finite/dual/collar consumers, earlier release of publication workspaces and paid failure/array escape lifetimes are implemented at component scope. The 2016-support partition comparison preserves the same 123,747,711-byte logical record and 983,735-byte packed arrays: charged peak falls 193.4 to 57.4 MB and process peak 270.2 to 145.9 MB, while construction rises 47.1 to 99.4 seconds. Both endpoints already have the same compact representation; the additional build time does not imply faster subsequent partition use. Mesh retained output falls but its measured overall construction peak does not. The publication fixture lowers reservations at commit from 18.74 to 15.98 MB, with unchanged 25,088-byte storage and effectively unchanged process peak. These are measured trade-offs, not an overall speed-up.

**Acceptance still open.** The genuine owner advance/publication/numeric commit comparison and the scaled simultaneous-live measurement are in progress. Native owner heat/finish consumers are receiving the final bounded-access adaptation. The [Step 8 checkpoint receipt](test-results/step8-live-memory.json) records valid component checks and their limits. Do not infer combined peak memory from isolated measurements, or claim full workflow/IV2 acceptance here.

**Parallel-chat delivery.** “Implement WP10 resumability” delivered Step 13's WP17 completed-query storage component and WP16 diagnostic-capture component with dedicated tests/measurements. WP17 remains disabled after slower serial-write measurements; WP16's eligible mesh/bounds/closed-graph formats remain unwired, while trace/failure/direct-column formats remain disabled on their measured costs. Shared integration remains with this chat. Measured results and required later re-evaluations are recorded under WP16/WP17 below. This is not completion of all Step 13.

**Next independent recommendation.** WP16 has now returned its isolated component. WP15 worker payloads follows after the active producer interfaces settle, with exact result/restart behaviour and measured parent/worker memory. Shared codecs, runner integration, frozen sources and IV2 remain with the current owner. This chat has not dispatched a new external assignment.

**Previous pause checkpoint.** The Step 8/WP8 conflation and failed Step 9 actual-owner fixture remain recorded. Michael subsequently authorised gap closure for Steps 1–7 and now explicitly says “do step 8”. The active work below is WP14 construction/advance/commit memory; it does not resume the failed Step 9 fixture or authorise real IV2.

**Scope correction from Michael, 15 October 2026.** The chat sequence's Step 8 is: "Remove remaining whole-record copies during construction, advance and commit. Measure representative memory peaks and release structures after their last use." Step numbers and work-package numbers are distinct. The implementation below incorrectly treated Step 8 as WP8. Its supporting integration work is retained, but it does not complete Step 8. The current owner must finish WP14's current-source lifetime inventory, remove the remaining construction/advance/commit copies, verify exact stage output parity and exception ownership, and measure representative IV2-shape simultaneous-live peaks under the unchanged guards. Tiny storage measurements and a pre-advance/root reopen cannot substitute for that evidence. Section 10 retains the detailed WP14 contract.

**Step 9 / WP8 integration, prematurely started; incomplete and paused.**

**Scope and writers.** Integrate the existing compact components and one shared retained scope with materialisation, interval publication and independent reopening; preserve authenticated historical admission, D3, original stores/receipts and all resource guards. Root owns `run_prepared_restart.py`, `launch_monitored_interval.py`, any necessary `historical_admission.py` adapter seam, their tests and final integration. The materialisation worker owns `materialise_endpoint.py`, `workflow_transfer.py` and their focused tests. The reader worker owns `reopen_prepared_restart.py` and reader tests. The storage-bridge worker owns the new `compact_restart_store.py` compatibility boundary and its focused tests. Shared interface decisions are agreed before dependent edits; no two writers edit the same file. WP9 composition/frozen inputs, real migration and IV2 remain outside this Step 8 implementation checkpoint. Completion requires exact compact identities, manifest-only reference evidence, bounded post-publication checks, per-operation storage/retained/cache reporting and a fresh-process integration fixture.

**Every WP.**
- Tests run at **real store limits**: 64 KiB chunks, 512 MiB max_array, 1 MiB manifest, 1 GiB staging, 4 GiB store.
- Use `.r44-env` with `-B`.
- Ruff runs check-only and counts introduced findings only: same executable and rules for base and candidate.
- Use Pyright for navigation.
- Do any bound proofs in the review environment.
- No store limit or guard limit changes.

**Common acceptance criteria.**
1. Lossless: the streamed canonical sha256 and length equal the legacy or logical IDs byte for byte.
2. Every put in the tests stays within 25% of max_array logical, 2,048 chunks and 25% of the manifest.
3. Codec/validation working memory scales with the segment or row block, not the logical record size. Total live memory also includes producer state, retained views/caches, worker payloads and codec workspaces; section 4 accounts for the sum.
4. Tampering, a missing or reordered segment, an unknown schema, and an old reader on a new schema are all refused.
5. Cancellation leaves no partial root.
6. Ruff reports no introduced findings.
7. **Every agreed optimisation remains in scope.** Implement and test each planned item in its owning package, subject to its explicit prerequisite (including the WP24 hotspot/build gate). Enable it only where the relevant measured path shows a net gain with no accuracy/accounting change. A failed benefit gate means tested and disabled, with the result in the existing receipt; it is not silent omission. A prerequisite-blocked item stays INCOMPLETE with the precise dependency and next action. Storage-only or pre-advance measurements cannot decide compute-path gates. No extra receipt system is introduced.

**WP0: Census v2.** Owns `R/probes/probe_codec_census.py` and its test.
- **0a, now.** Guarded, read-only selected reads that measure:
  - per-sub-field bytes;
  - the overlap between the finite graph and the graph;
  - mesh supports against partition `support_ids`;
  - static-table invariance;
  - heat n, nf, and the metadata/field split;
  - rational lengths;
  - head metadata bytes;
  - restart-path IV1 reads.
- **0b, after WP9.** On a scratch copy:
  - codec ratios;
  - node and pool counts against the ceilings;
  - segment counts;
  - per-put usage;
  - held and peak bytes;
  - cache hit rates.
- **Format compatibility.** Measurement must consume compact array descriptors and authenticated references directly, counting logical mentions separately from unique content and physical encoded bytes. The Step 2 helper already recognises current mesh-store v2, partition-store v1, support snapshots, links and workflow aliases; fixtures cover sharing and unknown-schema refusal. The original measured here contains no compact snapshots. As WP1/WP2/WP3/WP7/WP13 fix their new segment/view/interval-file schemas, add and test their explicit census handlers before WP0b. Resolve cross-file content identities without expanding compact data into legacy JSON or counting referenced bytes as new storage. Existing-schema fixture coverage is not acceptance of a future version. WP19 checkpoint timing itself is independent of the record representation.
- **0c.** Compression classes (section 6).
- **Accept** when every launch-critical quantity in sections 1 and 4 has a measured value or a verified bound, derived extrapolations remain explicitly labelled, and the original store identity is unchanged. Actual advance/commit peaks come from Stage D, not 0a/0b or a pre-advance smoke. Keep historical estimates only as comparison evidence.

**WP0a measured checkpoint.** Status: COMPLETE for the eight selected historical-data questions. WP0b/WP0c and candidate launch evidence remain INCOMPLETE. The source closure contains 257 pinned inputs including the frozen I runtime; prepared identities matched before and after. The final run took 168.407 seconds, with a guardian-sampled process-tree RSS peak of 128,536,576 B (122.58 MiB), a logical reservation peak of 311,107,312 B (296.70 MiB), zero final reservations and no guard breach. These are census costs, not simulation costs or WP19 instrumentation overhead. It streamed 901,402,722 B through temporary files and removed the successful run's scratch directory.

| Measurement | Result and implication |
|---|---|
| Per-record and sub-field bytes | Partition 114,107,489 B; mesh 190,778,119 B; exchange 106,131,490 B; graph 104,701,198 B; transport 6,422,727 B; state 3,105,816 B; certification 587,767 B; differential JSON geometry 42,225 B; heat reference 3,370 B. Complete field breakdowns, rational widths and numeric-array descriptors are in the census. Nested totals can overlap parents; do not sum both. |
| Finite graph versus graph | The embedded graph is 104,837,549 B. Common top-level values accounting for 97,664,880 B compare byte-for-byte equal, including 87,483,777 B of physical-measure receipts. Cells and transfers differ; the records are not interchangeable. Shared-field totals exclude object syntax and are not a measured compressed saving. |
| Mesh supports versus partition IDs | All 2,016 mesh supports match partition IDs and compare byte-for-byte equal: 113,020,661 B of support values. No ID-hash mismatch, differing body for a matched ID, or unmatched mesh ID. WP3/WP4 can target shared ownership without assuming that unrelated graph savings are additive. |
| Static tables | Root/head mesh grid lines (268 B) and voxels (3,361 B) are byte-identical; mesh/partition grid lines also match. Radial-layer/cone tables are absent on this differential route. This establishes equality for these saved inputs only; future invariance and cache eligibility remain route-qualified. |
| Heat coverage and split | 855 cells and 8,569 faces. Exact metadata is 356,504,170 B; the five binary64 fields total only 34,200 B. Exact paired-face energy alone is 166,784,242 B. Compact heat must address the exact ledger, not merely its small float fields. |
| Rational widths | Heat maxima: numerator 2,054,462 bits; denominator 2,054,539 bits; one encoded pair reaches 1,027,263 B. Mesh maxima reach 614,116 / 614,105 bits; graph 13,616 / 13,628; partition 265 / 266. These lexical measurements preserve spelling; they are not scientific validation. WP2/WP7 must test these exact width classes and derive charged row/integer bounds before claiming compact compatibility; no narrowing or rounding is allowed. |
| Head metadata and complete manifest | Historical head: 191 arrays, 526,874,255 logical B and 8,212 chunk references. Metadata itself is 18,797 B, below 64 KiB; the complete manifest is 586,212 B, above the 256 KiB design target. Reducing inline metadata alone does not solve the reference-table size. The new compact successor is still unmeasured. |
| Current restart reads | The source-mapped first-conversion path selects 308,366,839 unique array B; the initial workload rereads 2,496 B, giving 308,369,335 B with those repeated reads. This excludes full-database hashing/copying, manifest authentication and successor reads/writes. Exchange/graph/transport/heat-ledger census reads are additional D6 investigation, not payload decodes performed by current materialisation. Existing compact conversion reuse skips raw mesh/partition reads. |

The original store has three snapshots, 253 arrays, 907,453,676 logical array B, 907,301,572 unique referenced raw B and 885,430,400 stored payload B. Its physical SQLite file is 895,205,376 B; manifests total 1,322,479 B and chunk descriptors 406,818 B. These quantities have different accounting meanings. Compact interval files, cross-file references and their storage overhead remain WP0b measurements.

Both original hashes equal `3f70c26de17535a96b7ddd494aee72900decee272ae0f88edab3a42af1548899`; file identity and read-only store token were unchanged, with no sidecars. The final receipt hash is `02f0a05a7f05855d7ef578b879666489e8b2711405da2031204df372b5e379ae`. Earlier [r1](probes/structure-census-r1/structure-census.json) and [r2](probes/structure-census-r2/structure-census.json) refused diagnostic key/aggregate bounds; their original-after checks also passed. The scanner now bounds active keys/counts and groups content-ID map keys in field summaries, retaining exact bytes and duplicate checks. No store, guard or scientific limit changed.

Focused verification covers 17 scanner tests, 20 structural-measurement tests, eight compact-format tests and 13 launch/source-boundary tests, with unchanged evidence reused. The initial default temporary-directory test invocation was denied by the sandbox; the corrected workspace-temp invocation passed. No unrelated software suite or scientific interval was run. The WP14 source-only inventory below records the remaining live-memory seams.

**WP1: Segment store.** Owns new `C/segment_store.py` and its test.
- **Tests**
  - a synthetic **600 MiB**-logical payload;
  - range reads touch only covering chunks;
  - idempotent republish;
  - a shared-prefix payload stages only the changed parts;
  - Merkle-root verification (section 8);
  - refusals;
  - charged peak at most 2 × segment + chunk.

**WP2: Generic record codec and views.** Owns new `C/record_tables.py`, `C/record_views.py` and their tests.
- **Builds** the `partition_tables` node model without schema gates, plus:
  - key-shape interning;
  - hash-consing;
  - a binary integer pool;
  - dyadic/shared-denominator rational columns (section 8);
  - narrow dtypes;
  - a string fallback.
- **Tests**
  - the 1,217-spelling corpus from `test_materialise_endpoint`;
  - a 200 MB graph-like record whose second copy costs at most 3%;
  - composite identity equals `_hash`;
  - Mapping use is refused;
  - export is charged.

**WP3: Mesh v3.** Owns `C/mesh_tables.py`, `C/compact_store.py`, `C/spatial_indexed_patch.py`, `C/spatial_workflow_patch.py`, `C/exterior_mesh_patch.py`, new `C/differential_mesh_patch.py`, and tests.
- **Delivers**
  - the §2.2 seams;
  - no duplicate support bytes;
  - a sealed identity (section 7);
  - a page cache;
  - reference-only successors.
- **Tests**
  - fresh `geometry_id` parity against `_encode_mesh_record`;
  - 7,700 synthetic supports (more than 512 MiB of supports) publish and reopen;
  - publish and reopen across two processes;
  - held bytes after open at most 64 MiB;
  - one full mesh stream per cold reopen.

**WP4: Partition v2.** Owns `C/partition_tables.py`, `C/partition_store.py`, `C/partition_workflow_patch.py`, `C/partition_workflow_transform.py`, `C/partition_native_patch.py`, and tests.
- **Delivers**
  - §2.1;
  - segments;
  - ceilings derived from the segment size (D1);
  - `support_source(view)` for WP3;
  - wiring of the support LRU (section 7);
  - 4b, pool seeding from the parent's order, so leading pool segments share chunks across intervals (gated);
  - locality reordering behind a permutation array (section 8, gated).
- **Tests**
  - a 600 MiB synthetic DAG;
  - the IV1 byte-exact header;
  - fresh-partition descriptor parity;
  - a fresh-process reopen of a reference-only successor.

**WP5: Record publication and restore.** Owns new `C/spatial_records_patch.py` (anchors in §2.3 and §2.4, plus the publication check), new `C/exchange_record_patch.py`, and tests.
- **Test** an IV2-shaped synthetic successor:
  - the numeric head payload is at most 2% of max_array and its complete manifest meets the common 25% target; if measured metadata exceeds this, WP5/WP8 must design bounded referenced metadata, preserve all eleven structural checks and logical identity, and test that path before launch;
  - every `record_blobs` sha256 equals its legacy value;
  - the runner's 11 structural checks pass on metadata only.

**WP6: Validation consumers.** Owns new `C/spatial_validation_patch.py` and its tests.
- **Tests**
  - legacy and compact inputs give identical accept/refuse results on 12 mutated exchanges (every input type × route);
  - the peak stays within the row-block cap at 3.8x scale.

**WP7: Heat ledger.** Owns new `C/heat_ledger_tables.py`, `C/private_heat_snapshot_store_r4.py`, `C/private_heat_checkpoint_consumer_r10.py`, `C/private_heat_restored_binding_r10.py`, `C/heat_cold_patch.py`, `C/heat_ledger_issuer_patch.py` (H-a, D2), `C/ram_context_indexed_patch.py`, and `C/private_heat_bundle.py`. The bundle registers the WP5 and WP7 helper transforms and reconciles pins; predecessors are kept.
- **Tests**
  - a **616 MB**-logical synthetic ledger (n=80k, nf=240k, about 1.1 KB per rational) round-trips at real limits;
  - `result_id` and `metadata_sha256` equal r3;
  - streamed `_equations` matches r9 on mutated ledgers;
  - the **unfinished W4 owner-heat check**, including the fresh compact mesh and r13 packaging path;
  - historical r3 receipt lookup through the authenticated D6 mapping, plus new r4 receipt reopen.

**WP8: Runner, reader and materialise.** Owns `R/materialise_endpoint.py`, `R/workflow_transfer.py`, `R/run_prepared_restart.py`, `R/reopen_prepared_restart.py`, `R/launch_monitored_interval.py`, and tests.
- **Delivers**
  - v3/v2 stores at materialise;
  - a manifest-only check, `compact_references_verified`;
  - receipts with per-put usage, held bytes, store bytes and cache stats;
  - streamed record identities in the reader;
  - D3.

**WP9: Composition r2.** Owns `R/assemble_resumable.py`, `R/reviewed-inputs-r2.json`, `R/composed-r2/**`, `R/composed-checks/**` and `R/test_assemble_resumable.py`.
- **Delivers**
  - applying the transforms in order, each anchor exactly once;
  - fixing `test_w4_pressure_t8`, which still uses v1 mesh refs;
  - re-measuring the identity;
  - rerunning the affected checks;
  - census 0b/0c;
  - a pre-advance smoke (`--stop-before-advance`) for composition, migration, opening and setup only;
  - the guarded real-advance launch gate in section 4, with WP14 live-memory evidence and the owner-heat check.
- **Candidate ready for Stage D** when the affected checks pass, the measured census meets the section 4 targets and the pre-advance smoke stays within guards. **IV2 acceptance** additionally requires the real advance, commit and independent fresh-process reader. Composition or smoke success alone is not acceptance.

**WP10: Lossless compression layer** (section 6). Owns new `C/storage_codec_patch.py`, `C/codec_policy.json`, `C/codec_measure.py`, `C/codec_tradeoff.py`, codec runtime/backend/training/dictionary components, `C/cold_archive.py`, `C/cold_archive_worker.py`, and their tests. Michael's 15 October extension explicitly requests combined delta + zstd and purposeful `.tar.zst` use for suitable completed data.
- `C/storage_codec_patch.py` transforms `storage.ArrayStore._encode/_decode/put` to add:
  - a per-array codec policy;
  - `delta-v1`;
  - `delta-zstd-v1`: modular integer differences followed by the bounded native zstd backend, with none/byte/bit shuffle;
  - per-class zstd with byte/bit shuffle and level (check the actual backend capabilities, D5 and the scoped implementation note in section 6);
  - a trained-dictionary label;
  - bounded parallel encode/decode with async prefetch (at most 2 threads, workspace charged; section 8).
- Palettes are already in the store; WP10 sets the narrow-int policy that makes them engage.
- **Tests**
  - exact round-trip for every codec;
  - chunk ID = `_blob_id(descriptor, decoded raw)` for every codec;
  - the same raw data stored raw and as zstd dedupes to one row;
  - an old reader refuses the new labels;
  - workspace stays within `codec_workspace_bytes`;
  - parallel and serial runs give identical manifests.
- **Accept** when an array codec is enabled only where WP0c shows a net gain. Separately, completed diagnostic/export bundles automatically select `.tar.zst` only after their actual size and pack/restore time gates pass; this is an offline delivery route, not an array codec or an accepted-store migration.

**WP11: Bounded content caches** (section 7). Owns new `C/content_cache.py` and its test, plus new `C/certified_fact_cache.py` and `C/certified_fact_patch.py` with tests. The patch wires the cross-query fact cache into the existing per-query decline/proof reuse site, which WP11 locates. Owner WPs wire the other caches into their own files: support LRU in WP4, page cache and verified-hash set in WP1, sealed identities in WP2/WP3/WP7.
- **Tests**
  - booked bytes equal held bytes;
  - eviction under simulated budget pressure;
  - pinned entries are never evicted while borrowed;
  - hit/miss/evict counters;
  - **bit-identical results with caches on and off**;
  - a content change produces a new key;
  - the cross-query fact key covers every operand plus the method identity, and budget/cancel refusals are never cached.

**WP12: Zero-copy reads of hot raw arrays** (section 8). Owns new `C/raw_sidecar_store.py` and its test.
- **What it is.** An immutable, content-addressed raw sidecar file holding the hot raw arrays: the current mesh metric/connectivity columns and the partition node tables. Arrays are read through `mmap` as read-only numpy views.
- **Binding.** The ArrayStore stays the authority. The sidecar is an optional, regenerable local cache, outside the one-authoritative-file-per-interval layout; its absence must never prevent reopening the catalog. It is excluded from scientific identity and is not a second durable source. All mappings and outstanding borrows are charged and closed before replacement. The sidecar is bound by the same chunk IDs and descriptor digests, and it is verified once per process against the store chunks before any use.
- **Tests:**
  - views are byte-identical to the store reads;
  - a tampered or truncated sidecar is refused;
  - views stay pinned while borrowed;
  - mapped pages are charged as held bytes;
  - deleting the sidecar falls back to store reads with identical results.
- **Gate.** Enabled only where WP0b shows that hot-array read time drops by at least 5% of the run path. This is a storage-engine extension (D5).

### Integrated execution, ownership and completion

The authoritative 21-step sequence above replaces the earlier three-wave/session estimate. The dependency and ownership tables below elaborate that sequence; they do not replace its numbering or order. The work-package definitions and their tests remain the scope contract, including additions in sections 6–13. A later position in the sequence does not remove an item. Core interval-two readiness and completion of the whole optimisation programme are separate milestones.

Steps 1 / WP19, 2 / WP0a, 3 / joint interface freeze, 4 / storage/view/cache components, 5 / mesh-partition components, the bounded Step 5B follow-up, 6 / compact records-validation and 7 / compact heat-ledger/source composition are complete at their recorded scopes. The genuine owner-heat/checkpoint check now passes. WP8 runtime integration, WP9 frozen composition, WP14 combined live-memory evidence and WP0b actual compact-data measurements remain outstanding. The historical census must not be rerun merely because work crosses a step boundary. Current compact sources must enter WP9's reviewed successor inventory before real use; frozen RC1 and historical reviewed inputs have not been repinned. Reuse valid unchanged evidence within its original scope.

#### Dependency order

| Stage | Packages and work | Required result before moving on |
|---|---|---|
| A. Instrument and measure | Land **WP19** first. Run **WP0a** selected, guarded, read-only census. Start **WP14**'s inventory of full-record construction, exports and stage-spanning lifetimes from the composed sources. | Stage timings preserve execution behaviour; baseline facts distinguish measurements from projections. The census and lifetime inventory inform interfaces and resource budgets. No full interval is required for this stage. |
| B1. Freeze storage and view interfaces | **WP1** supplies segments; **WP2** supplies logical record tables/views; **WP13** supplies the interval-set/catalog contract and implementation. Agree WP3/WP4 support ownership and `support_source` before either consumer is integrated. **WP11** supplies shared cache contracts and bounded companion components. | Segment references, identities, ownership, cancellation and cross-file references have one agreed contract. WP13's storage-set tests pass before integrating publication, materialisation or reopen. Owners may develop against stubs, but stubs are not acceptance evidence. |
| B2. Connect producers, consumers and live memory | Implement **WP3** mesh v3, **WP4** partition v2, **WP5** record publication/restore, **WP6** validation consumers and **WP7** heat ledger, with **WP14**'s live-working-data changes integrated by those owners. **WP8** connects materialisation, runner and reader to the interval set. Include the outstanding owner-heat check. | Compact data stays compact through the affected advance and commit paths. All interval-one large records are covered by D6. WP14 has representative advance/commit evidence, not only a pre-advance open. |
| C. Compose and establish core readiness | **WP9** assembles the candidate. **WP0b** measures the complete compact working copy after composition; **WP0c** measures available codec candidates, completing remaining classes with WP10. WP8/WP9 perform the staged smoke and required cross-process checks. | Capacity, identity, representative live-memory and control gates pass on the composed candidate. A `--stop-before-advance` smoke covers preparation only. Representative advance/commit coverage must be resolved before launch; actual real-run peaks remain to be measured in Stage D. |
| D. Run the core continuation | Use the frozen candidate for the authorised guarded IV2 continuation and mandatory independent fresh-process reopen. Retain completed-query persistence and the existing strict acceptance boundary. | Record the actual continuation/reopen outcome and resource measurements. A launch or a passing preparation smoke is not completion. Failures retain their exact evidence and reopen only the affected work. |
| E. Complete measured acceleration cycles | Evaluate and integrate the remaining **WP10–WP12**, **WP15–WP18**, **WP20–WP25**, using **WP19**, WP0 measurements and the core baseline. The dependency order below controls these cycles. | Every planned item has a recorded disposition under its own gate; enabled candidates pass their affected checks. The whole programme is not complete merely because core IV2 succeeds. |
| F. Validate the final enabled combination | **WP9** integrates the accepted combination; **WP8** verifies its migration, publication and independent-reader boundary. Update affected WP0/WP19 measurements. | Final checks cover the changed combination and required continuation behaviour. Reuse unchanged evidence and retain the existing acceptance standard; do not rerun the whole interval for each option. |

Measurement-gated candidates may be built and tested alongside Stages B1–C when their interfaces are stable and file ownership is disjoint. They enter the core candidate only after their own gate passes. If the measured core cannot meet a guard without a particular candidate, that candidate becomes a core dependency; otherwise its later evaluation must not delay core readiness. This applies to compression/caches/sidecars and to worker, diagnostic and query-store changes. It is not an assumption that IV2 fits without them: WP0 and the capacity/memory gates decide that.

#### Acceleration cycles and retained scope

| Cycle | Scope and dependency |
|---|---|
| Storage and reads | **WP10** measures all planned encodings, palettes, shuffle/compression/dictionary policies and bounded parallel I/O. **WP11** completes every bounded cache and certified-fact reuse gate, with wiring by the consuming owner. **WP12** evaluates hot-array sidecars after the store/view contracts are stable. Use WP0b/0c to decide activation and remeasure combinations where codec, cache and sidecar effects interact. |
| Transfer, captures and restart | **WP15** compact worker payloads depends on stable views and, where selected, WP12. **WP16** compact diagnostic captures retains explicit exact JSON export and replay coverage. **WP17** columnar completed-query storage retains strict execution binding, hit/miss semantics and partial-write/stale/foreign handling. Existing correct persistence remains available until its successor is accepted. |
| Worker execution | **WP18** follows measured WP15 payload costs and the live-memory work. Retain cross-support batches, hardest-first ordering, bounded worker-count increases, warm pools, heat first-pass workers, heat-mesh queries and independent heat tails. Worker counts are selected by measured whole-tree memory, not by the requested upper counts alone. |
| Exact geometry and arithmetic | **WP20** zero-volume certificates, **WP21** exact simplification/chart merging, **WP22** broader filtered/vectorised predicates and **WP23** exact arithmetic, invariants, pruning and child-fact reuse retain their full definitions. WP19 chooses their priority; shared arithmetic edits are integrated in an ordered sequence so each comparison has a known base. Coordinate WP11 proof/invariant caches through the same owner. |
| Compiled kernels | Evaluate **WP24** after WP18 and WP20–WP23 have been assessed. Its explicit profiling gate decides whether remaining hot kernels justify the compiled implementation and new build/source-identity class. Keep the Python reference and fallback. A gate that is not met is recorded as such; it does not become an unsupported speedup claim or silently disappear from the plan. |
| Heat solves | **WP25** follows stable compact heat consumers and can be evaluated independently of disjoint geometry work. Retain both previous-interval warm starts and mixed-precision iterative refinement with exact residual verification, together with identical certified records/accounts and iteration measurements. |

All additional techniques assigned by sections 12 and 13 stay attached to their named package. Read each cited source entry fully before implementation. Existing measurement gates still apply, including net gain, no accuracy/accounting regression, and explicit disabled outcomes for candidates that do not qualify. Conditional work such as WP24 retains its stated prerequisite; no candidate is reported built or tested merely because its gate was discussed.

Use bounded saved-input and representative stage comparisons for individual options. Measure compatible groups before freezing the final enabled combination; do not add separate multi-hour IV2 runs to every work package. A further long run is justified only by a mandatory acceptance requirement or a named coverage gap left by the actual changes. Focused parity does not establish full-run acceptance where that remains required.

#### One writer at each integration boundary

The package's existing owned-file list remains authoritative. Before parallel implementation, the integrating owner records the actual writer for each shared target in the existing work record; ownership is by file and integration seam, not by package label alone. Unidentified targets are located before assignment. No guessed paths or concurrent edits to the same target are permitted.

| Boundary | Ownership rule |
|---|---|
| WP1/WP10/WP12/WP13 storage | Each owner writes its own declared component. One storage integrator orders transforms that affect the same storage implementation and checks the combined interface. WP13 is connected before WP5/WP7 publication and WP8 opening are accepted. |
| WP3–WP7 and WP14 | WP14 owns the cross-cutting lifetime inventory and acceptance question. The existing WP3–WP7 owner writes the changes in its own producer/consumer files; WP14 supplies the required change and reviews the resulting lifetime boundary. It is not a second writer over all five packages. |
| WP8/WP9/WP19 runtime | WP19 owns its diagnostic component. WP8 is the writer for timing hooks in runner/reader/materialisation files; WP9 is the sole writer of composition, source ordering and the frozen candidate inventory. |
| WP15/WP18 workers | Assign one worker-runtime writer for shared payload, dispatch, pool and scheduling targets. WP15 establishes payload contracts before WP18 changes scheduling against them. Heat bridge changes go through the WP7 owner; launcher changes go through WP8. |
| WP20–WP24 and WP11 arithmetic reuse | Assign one exact-geometry/arithmetic writer for overlapping kernel targets, particularly WP22–WP24. Other contributors may prepare independent proofs, fixtures or isolated candidates; the writer integrates them sequentially. WP11 owns its cache companions, while the kernel writer integrates shared call sites. |
| WP7/WP18/WP25 heat | The heat owner integrates shared heat-consumer or solver targets. Independent compact-storage and solver work may proceed in parallel only with disjoint files and a stable interface. |
| WP16/WP17 shared callers | Diagnostic and query-store owners write their own components; the existing runtime/consumer owner integrates shared call sites. |

Final integration reviews the actual combined change and its affected boundaries. It reuses valid package evidence rather than automatically requesting a second review or rerunning every suite.

#### Completion boundary and later phases

The existing work record must distinguish: core implementation ready, real IV2/reopen outcome, and completion of the full WP0–WP25 optimisation scope. Keep failed, disabled and conditional items visible with their measured or prerequisite-based reasons. Do not label planned techniques as delivered or carry earlier runtime acceptance onto changed sources without the required checks.

After successful IV2, **L1** remains archival compact copies alongside untouched originals; **L2** remains the separate compact-first plan for the rest of Atlas, requiring its own scoping and owner approval. Neither is silently folded into this execution schedule or used to claim wider Atlas completion.

## 4. Capacity, memory, performance and launch evidence

**Measured improvement reporting (Michael, 15 October 2026).** At each completed subsection checkpoint, report **time taken, RAM used and physical disk space**, with before/after figures and the measured change, and retain the comparison in this plan and the existing owning receipt. Use the same input, operation, measurement boundary and relevant configuration; name the previous version and tested candidate. Label process RSS/private/peak RAM separately from tracked retained allocations; observed use is not a proven minimum RAM requirement. Label physical stored bytes separately from expanded logical bytes. Report physical reads/writes where relevant. Distinguish component results from end-to-end improvement; separate component gains are not an overall multiplier. A timed-out baseline stays a timeout, an estimate stays an estimate, and unmatched workloads do not acquire a speedup or savings ratio. Reuse valid recorded baselines; do not add unrelated benchmark runs or another reporting ledger. If a time, RAM or disk baseline/measurement is absent, include that dimension as not measured.

| Completed bounded comparison | Previous version | Implemented version | Measured change | Evidence/scope |
|---|---:|---:|---|---|
| 128 sealed-file scalar lookups | 1.716 s, direct reads | 0.461 s, authenticated small-column reuse | 3.7x faster | [Step 4 receipt](test-results/step4-components.json); same sealed-file fixture, not whole workflow |
| 40 large-column scalar/raw lookups | 40 underlying reads | 1 underlying read | 39 reads avoided | [Step 5 receipt](test-results/step5-mesh-partition.json); same sealed synthetic column; no claim about overall run time |
| 4,000 warmed scalar lookups | 0.538877 s, repeated verified cache gets | 0.0309396 s, paid page borrows within one atomic read | 17.4x faster | [Step 5 receipt](test-results/step5-mesh-partition.json); same two columns, zero underlying reads in both, profiling enabled in both |
| Complete large compact cold reopen | Timed out at 600 s during generic validation | Passed in 505.599 s | Now completes within the test deadline; no exact speedup factor from a timeout | [Step 5 receipt](test-results/step5-mesh-partition.json); same already sealed 7,700-support fixture |
| Retained RAM after that large reopen | No successful old-open measurement | 31,601,894 B (30.14 MiB) | Savings not measured; below the 64 MiB retained-open gate | Tracked allocations, not total process RAM or minimum RAM required |
| Physical disk for that large fixture | No matched old-format store | 886,168 B (865.40 KiB) | Savings not measured | Deliberately high-sharing synthetic catalog/store; not a general-data compression claim |
| Step 5B mesh preparation | 162.993 s | 1.578 s | 99.0% less time | Same saved fixture; support-inventory completion to mesh-validation start |
| Step 5B complete cold reopen | 505.599 s | 306.727 s | 198.871 s / 39.3% less time observed | Single matched workload comparison; other unchanged phases also varied; OS cache uncontrolled |
| Step 5B retained RAM after open | 31,601,894 B | 31,601,894 B | Unchanged | 30.14 MiB tracked allocation; not total process RAM |
| Step 5B process RAM | Not measured | 146.53 MiB lifetime peak working set; 1.053 GiB peak private commit | Savings not measured | Peak counters read at completion checkpoints, through final support verification; at open working set was 142.86 MiB |
| Step 5B physical catalog/store | 886,168 B | 886,168 B | Unchanged | Same fixture files byte-for-byte; reference receipt excluded on both sides |
| Step 6 producer packaging | 0.01675 s | 0.14576 s | 0.12901 s slower | Final matched fresh-process synthetic sample; relevant source files checked unchanged |
| Step 6 producer tracked peak / retained | 47,335,976 / 3,391,552 B | 2,286,908 / 177,402 B | 95.2% / 94.8% less | Tracked allocation; not process RAM or minimum required RAM |
| Step 6 producer sampled process peak working set | 129.00 MiB | 119.29 MiB | 7.5% less observed | Same sample; 5 ms sampling; no whole-workflow claim |
| Step 6 synthetic persisted records | Not measured | 54,664 B sealed interval/catalog; separate numeric head 32,768 B | Disk savings not measured | Different fixture from producer measurement; no matched legacy store baseline |
| Step 6 compact row-processing scale | 1,000 rows: 166,720 B / 0.10629 s | 3,800 rows: 166,720 B / 0.43110 s | Row allocation stays bounded as count grows | Additional tracked row allocation; not an old-format comparison |
| Step 7 matched heat save | 0.14906 s, r3 | 0.11297 s, r4 | 0.03609 s less observed | Input packaging excluded; codec imported before timing; one final sample |
| Step 7 matched heat reopen | 0.06102 s, r3 | 2.12556 s, r4 | 2.06454 s slower | Same synthetic logical result; includes store/catalog verification, field hashing and close |
| Step 7 reopen tracked peak | 51,052,600 B | 31,552,512 B | 38.2% less | 48.69 to 30.09 MiB; tracked reservations, not process RAM |
| Step 7 reopen sampled process peak working set | 145.89 MiB | 128.70 MiB | 11.8% less observed | 5 ms sampling; includes interpreter/imports; no minimum-RAM claim |
| Step 7 matched physical heat store | 135,168 B | 120,206 B | 11.1% less | SQLite plus compact catalog; evidence/receipt files excluded |
| Step 7 large logical ledger | No matched r3 baseline | 39.94 s pack / 10.50 s save / 206.60 s reopen | Savings not measured | 616,160,149 logical metadata bytes; original bound fixture evidence |
| Step 7 large tracked memory / physical store | Not measured | 74.54 MiB write peak / 30.09 MiB cold peak; 71,056 B store | Savings not measured | Deliberately high-sharing synthetic data; process RAM not measured |
| Step 7B small compact reopen | 2.05859 s | 0.84264 s | 59.1% less time; 2.44x faster | Medians of three fresh processes per version; same saved fixture and exact identities |
| Step 7B large compact reopen | 189.07803 s | 31.24293 s | 83.5% less time; 6.05x faster | One fresh process per version; same 616,160,149-byte logical fixture; OS cache uncontrolled |
| Step 7B tracked peak RAM, both fixtures | 31,552,512 B | 31,552,512 B | Unchanged | 30.09 MiB; tracked reservations, not minimum required RAM |
| Step 7B sampled peak process working set, small / large | 127.84 / 132.30 MiB | 127.38 / 131.96 MiB | Effectively unchanged | 5 ms sampling; small medians, large single observations; no material saving claimed |
| Step 7B physical interval/catalog, small / large | 120,206 / 71,056 B | 120,206 / 71,056 B | Unchanged | Files and receipts unchanged; [matched evidence](probes/step7b/measurement.json) |
| Step 8 partition construction, 2,016 supports | 47.100 s; 270,151,680 B peak process RSS | 99.415 s; 145,895,424 B peak process RSS | 111.1% more time; 46.0% less peak RSS | [Matched compact-endpoint evidence](probes/wp14-partition/handoff.json); identical logical record and 983,735 B packed arrays, not measured physical-store savings |
| Step 8 partition construction, charged peak | 193,367,745 B | 57,412,041 B | 70.3% less | Same comparison; both finish with the same compact representation, so this extra build time establishes no later reuse speed gain |
| Step 8 ordinary mesh construction, 216 cells / 752 faces | 2.16291 s; 189,956,096 B peak RSS; 4,747,132 B retained output charge | 2.99595 s; 190,672,896 B peak RSS; 719,335 B retained output charge | 38.5% more time; no process-peak gain; 84.8% less retained output charge | [Mesh/collar evidence](probes/step8/mesh-collar-handoff.json); exact logical identity; ephemeral output, no authoritative store written |
| Step 8 publication/commit lifetime fixture | 0.26586 s; 157,122,560 B peak RSS; 18,735,536 B reserved at commit; 25,088 B store | 0.25554 s; 157,347,840 B peak RSS; 15,980,804 B reserved at commit; 25,088 B store | 14.7% less reserved at commit; process peak and disk effectively unchanged | [Before](probes/step8/publication-before.json) / [after](probes/step8/publication-after.json); one small timing pair, no robust speed claim |

Historical reference only: the original fresh-process IV1 workflow reader recorded 447.656 s (7m28s) to reopen the whole workflow in `fidelity-integration-20261005/heat-repair-20261007/reader-memory-20261013-r3.json`. This is not comparable with a compact mesh/partition fixture. A matching new whole-workflow result is still needed before reporting an overall speedup. Source pin and full-workflow acceptance boundaries remain unchanged.

**No measured IV2 fit is claimed.** The original design estimated growth of 3.8-5 times IV1 and compact ratios of 0.40-0.55 (heat 0.45-0.55). Those assumptions remain useful stress scenarios. WP0a now provides measured historical sizes; the assumed ratios still require WP0b/0c measurements of the actual compact candidate and are not launch evidence.

**Historical measurements and illustrative projections.** Values below are decimal MB unless MiB/GiB is explicit. The WP0a checkpoint above supplies exact measured IV1 sizes and supersedes older estimates at that scope; the rounded historical figures below remain illustrative inputs, and all IV2 columns are projections.

| Item | Reported IV1 | Derived IV2 legacy | Derived IV2 compact |
|---|---|---|---|
| Partition | 114.1 MB | 434-571 MB | 173.4-313.8 MB |
| Mesh | 190.8 MB | 725-954 MB | 290.0-524.6 MB |
| Exchange | 106.1 MB | 403-531 MB | 80.7-145.9 MB, assuming half is shared |
| Graph | 104.7 MB | 398-524 MB | 159.1-287.9 MB |
| Transport, state, certification and other operands | See section 1 | Growth not measured | Components must be enumerated by WP0 |
| Heat ledger | 356.5 MB | 1,355-1,783 MB | 609.7-980.5 MB |

The earlier 1,332-2,286 MB compact-total scenario is not a capacity bound: it used assumed sharing and ratios and did not explicitly enumerate every retained record/metadata component. WP0 replaces it with a complete inventory including differential geometry, indexes, receipts, reference tables and store overhead. The old 2,349/3,349 MB combined-working-copy totals are withdrawn: they mixed the original store with a partial IV1 conversion and predate D6/WP13.

**Storage accounting for the selected layout.** Report these separately, without counting a referenced chunk twice:

1. `interval-0000`: measured unique encoded chunks for ALL compact IV1 records, their manifests/indexes, authenticated legacy-receipt mapping and actual SQLite overhead. The original evidence store is separate and unchanged.
2. Each successor file: its new unique encoded chunks plus manifests/indexes/reference metadata and actual SQLite overhead. List bytes referenced from each earlier sealed file separately; they are neither new physical bytes nor a waiver of logical bounds.
3. Total disk footprint: original evidence + all interval files + catalog + completed-query store + optional raw sidecars/captures. This can exceed one file's 4 GiB bound; each ArrayStore file must independently remain within 4 GiB.
4. Transient disk/staging peak: unfinished interval, journals/WAL if used, codec buffers, conversion spills, sidecars and temporary catalog/replacement files. Measure the implementation's real behaviour, not an assumed 2% overhead. Include its needed free-disk margin in the existing launch preflight; do not change the existing RAM free-floor guard.

Use the actual production store-limit accounting for logical/encoded/store bytes and report physical file size separately. D4 permits no store-limit raise for this run. If measured capacity fails, repair compact representation/sharing within this plan and remeasure the affected path; do not silently relax a bound.

**Per-put design targets at the unchanged store limits.**

| Quantity | Design target | Required evidence |
|---|---|---|
| Segment logical bytes | At most 128 MiB, 25% of the 512 MiB limit | Actual largest put, before compression |
| Chunk references | At most 2,048 per put | Actual count including rounding across arrays |
| Complete manifest | At most 256 KiB, 25% of the 1 MiB limit | Encoded manifest including metadata and all references |
| Staging | Remains below 1 GiB with measured transient headroom | Peak staging across the actual publication sequence |
| Root metadata / inline SegmentRef | At most 64 KiB / 4 KiB | Boundary tests and census; larger tables use bounded authenticated indexes |
| Numeric successor-head payload | At most 2% of 512 MiB | Actual numeric arrays; complete head manifest measured separately |

The old 560,352 B successor-manifest estimate is **above** the common 256 KiB target even though below the store's hard limit. WP0a measured the original historical head at 586,212 B, of which only 18,797 B is metadata; that is a different object and does not turn the successor estimate into a measurement. WP0b must measure the actual new compact successor. WP5/WP8/WP13 must keep its complete manifest within the target using bounded authenticated references; no head exemption is assumed. Compression reduces physical bytes, not logical per-put limits. Boundary/refusal tests remain mandatory.

**Memory accounting and margins.**

- Keep the existing 12 GiB RSS guard, 1 GiB free-memory floor, 10 GiB start gate and 16 GiB logical budget. Preserve the current monitor's accounting and cancellation cadence. Parent, worker and codec/prefetch memory must be measured together; a worker-count increase must fit the same available envelope.
- The 256 MiB post-publication/cold-reader target is **one aggregate cap across retained views and caches**, not a cap per object. WP11 allocates shared sub-budgets. Individual maxima (support LRU 128 MiB, fact cache 64 MiB, verified-hash set about 20 MB, page caches up to 64 MiB) are ceilings, not simultaneously available allocations. Evict unpinned entries or decline optional caching rather than overbook the aggregate. Pinned bytes stay charged; exception/cancellation paths release ownership correctly.
- The codec/validator temporary target is at most two 128 MiB segments plus one explicitly sized row block. Add retained views/caches, producer state, required charged exports, worker payloads and codec workspaces when evaluating TOTAL peak. WP0/WP6/WP7 set and test the row-block and export caps before launch; the 32 MB transport export must be accounted for explicitly. The temporary target alone is not a bound on the whole advance.
- WP14 removes whole-record lifetimes and measures construction, advance, finish and commit on representative IV2-shape inputs. WP15/WP18 include parent/worker copies and simultaneous in-flight work. WP19 attributes measured RSS/private bytes alongside logical reservations; the two are reported separately.
- Record measured high-water marks and distance to each hard guard in the existing receipt. A scenario forecast must also include measured simultaneous-live components and state its uncertainties. Crossing a guard is a failed attempt, not acceptance. A stop-before-advance run supplies no advance/commit peak measurement.

**Evidence sequence.**

| Stage | What it proves | What remains unproven |
|---|---|---|
| WP0a, bound to existing evidence | Record sizes, sharing, head metadata, arithmetic widths and restart consumers | Candidate encoding ratios and actual IV2 peaks |
| WP0b/0c on the composed scratch candidate | Actual codecs, puts, manifests, conversion peaks, held bytes, cache behaviour and storage costs | Full forward/commit behaviour |
| Focused parity/refusal/boundary checks and owner-heat control | Exactness and safety of the changed paths at the stated fixture scope | End-to-end IV2 acceptance |
| Pre-advance smoke | Migration, composition, reopen/setup and guard wiring | Advance, finish, commit and publication peaks |
| Guarded real IV2 attempt | Actual advance, commit/publication, resource peaks and resumable outcome | Independent cold-reader correctness until that reader passes |
| Independent fresh-process reader | Published compact state, reference chain, identities and required scientific/accounting checks | Unexercised later optimisations or broader Atlas stages |

Authorise the Stage D attempt only after the preceding candidate gates pass and the evidence predicts margin under unchanged guards. The monitored attempt establishes the previously unmeasured live peak; do not pretend an actual peak must already have been proved before the first attempt. If it stops, keep the previous accepted catalog head, completed-query work and failure evidence, repair the named cause, and rerun only the affected checks before retrying. Check the existing operational maintenance/update window before a multi-hour run; this plan changes no machine update policy.

**Performance comparisons and benefit gates.** Record separate baseline and candidate composition identities. Hold authenticated inputs, unrelated sources/dependencies, guards, environment, thread settings and declared cold/warm cache state fixed except for the explicit factor being measured (for example the worker count or cache toggle). Report elapsed time and percentage change for the same accepted outcome, plus memory/storage costs where relevant. Include dispatch, verification, persistence and reopen costs when they move work between stages. Hit rate alone is not a benefit: no cache is enabled if lookup, retention or added verification makes its path slower. WP19 instrumentation must be identical on both sides, or its overhead separately established. Do not benchmark a multi-hour run repeatedly for each option; use saved representative inputs and focused controls, then one combined affected acceptance run where the changed paths require it.

## 5. Risks, owners and required responses

Decisions D1-D6 are settled at the top of this document. Remaining engineering unknowns have an owning package and a concrete evidence requirement:

| Risk | Owner and response |
|---|---|
| R1: live advance/commit RAM, including whole-record transients | WP14 with WP3-WP7 removes large copies; WP15/WP18 account for worker copies; WP19 measures. Real Stage D execution resolves remaining live-peak uncertainty. |
| R2: codec ceilings, header size and pool growth | WP0 measures counts/widths; WP1-WP4/WP7 derive enforced segment bounds and test at/over each boundary. Large reads remain charged and bounded. |
| R3: byte-exact logical identity and spelling | WP2-WP7 check canonical identity immediately at production and through historical migration. Unsupported compact spellings use exact string fallback; no rounding. |
| R4: a missed whole-dict consumer | WP6 owns the type-by-route accept/refuse matrix; non-Mapping views expose missed consumers. WP14 inventories stage-boundary record materialisation. |
| R5: forward heat on a fresh compact mesh | WP7 completes the owner-heat check before Stage D, then WP8 verifies the real new-interval cold path. |
| R6: pinned heat helper revisions | WP7 is the heat owner; record the r13 packaging identity, prove kernel AST identity and exact account parity, preserve predecessor helpers and historical receipts. |
| R7: optimistic size/sharing scenarios | WP0 replaces launch-critical assumptions with measurements; WP13 checks each actual interval file and the whole disk footprint. No store-limit workaround. |
| R8: repeated identity/validation CPU | WP2/WP3/WP7 seal only identities verified in the process; WP11 measures bounded reuse. A fresh process validates its required bytes again. |
| R9: changed execution identity | WP9 records the composed identity; WP17 refuses old/foreign completed-query hits. Reusing logical chunk content never makes an old execution checkpoint current. |
| R10: uncharged or multiply retained cache data | WP11 owns the aggregate retained-memory budget; owners expose actual held bytes, borrows and evictions. WP12 accounts for mapped pages and sidecar lifetimes. |
| R11: catalog crash, missing history or cold-file recompression | WP13 implements section 9's atomic seal/reference rules and immutable archival successors; tested crash points cannot advance an unaccepted catalog head. |
| R12: overlap between storage, live-memory and speed packages | Section 3 assigns one file writer and a dependency contract before edits. WP9 alone composes the result; combined tests cover changed interfaces. |

Resolve ordinary implementation choices inside these contracts. A new dependency installation, altered hard limit, changed accepted scientific result or identity semantics, canon decision, live/EXE promotion or external publication still needs its applicable existing authority. This plan does not reopen settled D1-D6 decisions or lift unrelated holds.

## 6. Lossless compression on top of the compact layout

**What exists.** `storage.Compression` (RC1 `storage.py`) supports:
- `codec`: raw, or zstd through optional blosc2;
- `level` 0-9;
- `shuffle`: none, byte or bit (zstd only);
- `palette`: int/bool chunks with at most 256 distinct values become `palette-packed-v1`, at 1, 2, 4 or 8 bits;
- `categorical='auto'`: adds `rle-v1` and `uniform`;
- `use_dict`: a per-frame dictionary (zstd only).

`_encode` keeps the smallest candidate per chunk, and floats are never palettised. The historical store uses raw, byte shuffle, palette true and no dictionary. So integer chunks already get palette, RLE or uniform encoding, and nothing gets zstd. There is no delta filter, and no per-array policy (the policy is per store).

**Invariant.** Identities and content addresses hash the **decoded raw bytes**.
- `_blob_id` = sha256(`atlas-typed-chunk-v1` + descriptor + raw).
- Only `stored_sha` covers the encoded payload.
- Logical IDs are streamed canonical JSON.

Decoded-content identities survive a lossless codec change; encoded-payload hashes, physical file hashes and runtime/producer identities can change and must be recorded. A chunk first stored raw is reused by a zstd writer while the same immutable chunk remains available. WP10 tests this for every codec.

**Planned work items: the four encodings below, plus zstd per class with shuffle and level.** All are lossless and all are planned (WP10). Each is measured by WP0c and enabled per class only where the adoption rule shows a net gain. None changes accuracy or accounting.

| Technique | Array classes | Status |
|---|---|---|
| **Delta encoding** (store differences, mostly tiny) | CSR offsets, sorted lookup/permutation arrays (`support.lookup`), creation-order child refs, integer-pool offsets, sorted ordinals. Follow with palette, bit-pack or zstd | Implemented privately: `delta-v1` and combined `delta-zstd-v1`; real-class activation awaits WP0c |
| **Byte/bit shuffle** (group same-significance bytes so zstd finds runs) | float64 metric/field columns, u4/u8 indices, delta-ed offsets, integer-pool magnitudes | Exists; only takes effect under zstd |
| **Palettes** (a repeated value becomes a small index, as in Minecraft block-state palettes) | node kinds (9), tag columns (`kind`, `material_support_kind`, `radial_band`, `s.table`), owner signs, booleans, key-shape IDs | Already active for ints. Codecs must store tags as narrow ints, not strings |
| **Trained zstd dictionary** (for many small, similarly structured chunks) | string pool, small canonical metadata, any remaining support blobs. Not big-int magnitudes, which are near-random | New. One dictionary per class, stored as a content-addressed chunk and named by its sha256 in the codec label (D5). The existing per-frame `use_dict` is too weak for 64 KiB chunks |

**Costs.**
- CPU on every write and every read: `_chunk` decodes every time, and `decoded_cache_bytes` is 0.
- Decoder workspace, charged within the 8 MiB `codec_workspace_bytes`.
- No zero-copy view of compressed payloads, and therefore no mmap path.
- Compression shrinks store, staging and I/O bytes. It does **not** relax the per-put logical limits.

**Measurement (WP0c, using `C/codec_measure.py`).** On sampled real chunks, in memory and without writes, run the store's own `_encode/_decode` and the candidate filters. Report, per array class:
- compression ratio;
- encode and decode MB/s (median);
- workspace;
- run-path read frequency, split into:
  - **hot**: current mesh metric/connectivity, partition node tables, heat projection;
  - **cold**: prior intervals, validated ledgers, pools, supports.

**Adoption rule (`codec_policy.json`).** Enable a codec for a class only if all of these hold:
- ratio ≤ 0.8;
- added decode time ≤ 5% of that class's read path;
- cold saving ≥ 1% of 4 GiB.

These remain the existing per-class adoption thresholds. WP10 measures total encode/decode/persistence cost as well; compression is disabled where overall cost outweighs the saving. Raw fallback is mandatory if a proposed API or decoder-workspace bound is unavailable. A missing optional codec does not authorise installation or block compact-core acceptance; its planned item stays BLOCKED with the exact capability gap and required next action, not falsely completed. A demonstrated failed benefit gate can instead produce a tested-disabled outcome.

**User-accepted WP10 trade-off, 15 October 2026.** Michael explicitly accepts the observed delta+zstd byte/1 result: 8.75% longer total time for a 20% smaller physical database compared with plain zstd byte/1 on identical input. The shared codec_tradeoff.py helper now implements that narrow exception in both assess_adoption and runtime policy validation. It requires decision wp10-delta-zstd-space-tradeoff-20261015, candidate delta-zstd-v1 byte/1, comparator zstd byte/1, matched positive physical byte counts, real-report SHA-256 and total times. Inclusive limits are at least 20% less physical storage and at most 8.75% longer total time. Incomplete, malformed or synthetic evidence cannot enable it; the evidence owner must authenticate the report and matched observations. Without explicit exception evidence, the strict total-time improvement requirement remains. WP0c must supply representative real-class/read-frequency/persistence evidence; WP8/WP9 integration, exactness, memory limits, compression ratio, decode-cost and cold-saving gates still apply. No production array rule was enabled and the original benchmark evidence is preserved. The tar.zst routing policy is unaffected.

The most-read hot arrays stay raw where zero-copy reads matter. Cold history may use a higher zstd level.

**Scoped WP10 implementation update, 15 October 2026.** The installed Blosc2 interface did not expose the required reusable-dictionary and native-workspace bounds. Michael subsequently authorised enabling those capabilities: the private hash-pinned `native/wp10_zstd.dll` and `native/wp10_train.exe` supply bounded zstd and owned offline training. This is the explicit scoped successor to D5's original environment-only investigation, not general installation authority. The default array policy remains disabled pending WP9 composition and representative WP0c evidence. `delta-zstd-v1` combines both operations on the same integer chunk, including signed wraparound, while keeping decoded bytes and typed IDs exact. The complete delta plus native workspace is charged within 8 MiB; this path conservatively uses one preparation worker and serial native prefetch. Ordinary zstd remains available for other array classes. Synthetic results are component evidence, not production adoption.

**Purposeful `.tar.zst` finalisation of completed bundles.** `cold_archive.finalise_completed_bundle` receives an explicit closed diagnostic/export file list and automatically selects the representation. The measurement CLI finalises completed synthetic reports of at least 64 KiB into a sibling `.bundle` directory; this is the default export behaviour, without an opt-in compression flag. A compressed result is selected only when archive plus manifest/receipt allowance is at most 80% of the equivalent plain bundle, actual packing takes at most `2 + raw_bytes / (16 MiB/s)` seconds, and verified restoration takes at most `1 + raw_bytes / (64 MiB/s)` seconds. Failed benefit gates retain a plain directory and their measured reason. These are bounded offline latency allowances, not a claim that compression has zero cost or beats a direct copy. Compression level 3 is synchronous; no zstd worker option is set.

The first route is limited to 256 explicit regular files, 64 MiB per file and 256 MiB total. Tar packaging requires at least two files; an isolated file stays plain. Measurement exports group the completed report with copied policy and backend-build provenance. The route refuses live controls, SQLite/database files, links, reparse points and unsafe/aliased names. Originals remain unchanged. A plain UTF-8 manifest and receipt bind every byte and the compressed SHA; restoration requires the trusted receipt SHA from finalisation, writes only a new directory, checks every regular member and never invokes native filesystem extraction. Arbitrary external archives are unsupported. Python worker plus inherited native tool share an owned 128 MiB Windows Job cap, with a separate charged 16 MiB parent allowance and a 30 s operation deadline; this offline allowance is separate from the 8 MiB array-codec limit. Sources, candidate bytes, verification copies, packing/restoration time and actual Job memory peaks are reported. Temporary disk demand is a conservative file-byte estimate, not a filesystem quota. Keeping originals means a smaller delivered bundle does not itself reduce existing workspace usage.

`.tar.zst` is tar packaging followed by Zstandard; it does not add another array-compression algorithm. It is useful for transferring/retaining groups of completed text, JSON, CSV and diagnostic evidence. It is excluded from hot reads, active checkpoints and accepted interval-set opening, so it adds no archive/dearchive step there. No automatic deletion, retirement or active-lineage switch is authorised.

**WP10 extension checkpoint.** Implemented and checked at private component/default completed-export scope; [owning receipt](test-results/wp10.json). The accumulated focused evidence is 84 passing cases and two host-denied link-creation fixtures, not a new whole-project rerun. The exact Step 7B scanner-only diff was reviewed for the private publication transform; Step 7 code was not edited. Twelve matched synthetic storage observations show combined delta+zstd uses 901,120 B versus 1,126,400 B for plain zstd (20% less), but takes 101.52 ms versus 93.35 ms total (8.75% longer); RAM is effectively unchanged, so this is not an activation result. Three matched completed-bundle observations reduce 3,155,345 B to about 749,900 B including metadata (76.2% less), with median finalisation 0.271 s and restoration 0.168 s; plain copy takes 0.00384 s. Maximum archive Job memory is 21,495,808 B, with no RAM-saving claim. The actual measurement CLI automatically delivered a three-file `.tar.zst` package, 423,263 B of selected contents in a 31,182 B delivered bundle, and a fresh restore verified every byte. Cache/system load were uncontrolled. WP8/WP9 composition and real-class WP0c activation remain outstanding; no IV2 acceptance is implied.

**Independent WP10 completion, 15 October 2026.** All WP10 work that can be completed separately from the main worker is now finished: codecs, combined delta+zstd, purposeful default completed-bundle tar.zst routing, measurements, and the approved time/space exception in both assessment and runtime policy validation. This last policy change passed 29 focused tests (20 assessment tests and nine runtime-policy checks); the accumulated inventory is 97 passes and two host-denied link fixtures across 99 cases, reusing valid unchanged-path evidence. Codec execution and benchmark inputs were unchanged, so the recorded RAM/disk/time observations were preserved without rerunning benchmarks. Only WP8/WP9 integration and representative real-class WP0c evidence/activation remain with the main worker; the default array policy stays disabled.

## 7. Caches (WP11, wired by the owner WPs)

Every cache below is a planned work item. Each is enabled only where its measured hit rate or time saving passes the acceptance gate.

**Rules for every cache.**
- **Bounded.** Each cache has a fixed byte or entry cap.
- **Charged.** Entries are charged to the logical WorkBudget in a named category, so there is no hidden RAM.
- **Never stale.** Keys are immutable content hashes: support sha256, chunk `_blob_id`, or snapshot key plus descriptor digests.
- **Evictable.** LRU eviction; under budget pressure the cache evicts unpinned entries and the request is retried once.
- **Ownership-safe.** An entry stays pinned while a borrowed view is live, because releasing an owner whose data is still borrowed saves nothing.
- **Result-neutral.** No cache may change a result. Hits return bytes or objects whose hash was verified at insertion.
- **Measured.** Hit, miss, evict and held-byte counters go into the receipts. WP0b and the smoke run report them.

| Cache | Where it applies | Expected benefit | Risk / guard |
|---|---|---|---|
| Decoded-support LRU keyed by support ID or content sha256 (W1-C issue **C-D16**) | Compact partition/mesh support handles used by walls, interfaces, screens and contacts (`partition_native_patch`, `pressure_indexed_patch`, `partition_routing_patch`). Today each of these re-materialises one native support | Removes repeated DAG decode of the same support across consumers; probably the main reopen CPU cost for routing and pressure (measure) | Decoded objects are large: cap at 128 MiB, charged, pinned while borrowed. Owner: WP4 |
| Decoded-chunk cache | `ArrayStore` already has one: LRU keyed by chunk ID, `decoded_cache_bytes` (default **0**), `verified_cache_entries` 2048, counted in `_resident_bytes`. Use a **single** layer: the WP1 segment page cache, charged to the budget, rather than also enabling the store's cache | Repeated covering-chunk reads during validation passes avoid the SQLite read, verify and decode | Double caching. Keep the store's cache at 0 unless WP0b shows a gain. Owner: WP1 |
| Per-process verified-chunk-hash set | Chunk IDs whose sha256 was verified in this process (extends the connection-scoped `_verified`), capped at about 200k entries (about 20 MB charged) | The post-publication re-read and repeated reads skip re-hashing chunks this process just wrote or verified | Covers only same-process, same-file trust; any reopen in a new process verifies again. Owner: WP1 |
| Sealed identity per compact view | CompactMesh, CompactPartition, CompactRecord and HeatLedger views keep the streamed logical sha256 they computed, bound to the root key and descriptor digests (**W2-E**: `metric_identity` streams the mesh twice per cold reopen) | Saves one full stream per consumer: about 1-1.5 min per IV2 pass | Only identities computed or verified in this process are cached. A stored seal is never trusted without one verification per process. Owners: WP2, WP3 |
| Cross-query certified-fact cache | Extends the existing per-query decline/proof reuse to across queries. Key: content hash of (predicate kind, exact operand bytes, exact method identity) → result plus certificate | Shared walls and interfaces repeat the same exact predicates across endpoint queries | The key must include every operand and the method. Budget and cancel refusals are never cached. Capped at 64 MiB charged, and a hit rate is required to keep it. Owner: WP11 (`certified_fact_patch`) |
| Existing persistent stores | The completed-query store (2,000,000 entries / 8 GiB) and the per-query source re-hash cache (300 s full re-read) | Unchanged. Already measured | The new execution identity invalidates old completed queries (R9) |

**WP11 tests.** Each cache passes this matrix (the rules above in test form):
- A/B runs with the cache on and off are bit-identical;
- booked bytes equal held bytes;
- forced pressure evicts entries and the retry succeeds;
- pinned entries survive eviction;
- counters are exact;
- a changed content key misses.

**Acceptance.**
- A cache is enabled only after a representative exercised path shows a net benefit. The existing selection threshold is a hit rate above 50% OR a measured time saving of at least 5% on its path, but a high hit rate alone never overrides slower elapsed time or excess memory. Compute caches require compute-path measurements; a pre-advance smoke cannot decide their gate.
- All caches together stay within the §4 target of 256 MiB held.

## 8. Further techniques

All are planned work items. Each is gated by its measurement and enabled only for a net gain with no change to accuracy or accounting.

| Technique | Benefit | Cost | Exactness | Verdict |
|---|---|---|---|---|
| Merkle / per-chunk hash index | The manifest already lists content-addressed chunk IDs. A per-record Merkle root over each array's chunk-ID list (in `SegmentRef`) lets reopen and re-read skip unchanged chunks (static tables, IV1 history, cached verified IDs) | Small index, plus one root check | sha256 throughout. The streamed canonical **logical** identity is still computed whenever a consumer needs it, then sealed (section 7) | **Adopt** (WP1, WP11) |
| Shared-denominator / common-scale rational columns | Large where denominators repeat. Dyadic (2^k) denominators from binary64-derived values shrink to an exponent | gcd on decode; LCM blow-up if forced | Must reproduce the exact original spelling, including the reduced form and the hex/decimal class. Verified at pack time per value; otherwise falls back to (num, den) pool refs | **Planned, WP2/WP7** (enabled per column where it shrinks) |
| Bit-packing and varints | Small counts, sign bits and flags | Varints break O(1) CSR indexing | Lossless | **Planned, WP2-WP4**: narrowest fixed dtypes (u1/u2/u4, sign bit-planes) plus palette and delta. Varints for cold append-only streams (gated) |
| Zero-copy mmap of hot raw arrays | No copy for hot metric columns | Chunks are SQLite BLOBs in pages, so mmap would need a raw sidecar file: a storage-engine change | Unaffected. The sidecar is bound by chunk IDs and verified once per process | **Planned, WP12** (raw sidecar plus mmap; gated; D5). Fallback is the current one-copy `memoryview` reads |
| Parallel chunk encode/decode and async prefetch | zstd/blosc2 and hashlib release the GIL for large buffers. Prefetching the next covering chunks helps sequential row streams | Threads × workspace (charged). SQLite reads are serialised by the store lock | Deterministic: chunk IDs are order-independent and manifest order is fixed | **Planned, WP10** (at most 2 threads; gated) |
| Remove the compact_store v2 duplicate support bytes | v2 stores each support twice: as a staged per-support snapshot and in the packed array. Fixing this saves 0.1-0.15 GB at IV1 and about 0.4-0.75 GB at IV2 | None. Write supports straight into content-addressed segments (reusable after cancellation), or share them through the partition | Unchanged support sha256 | **Adopt** (WP3) |
| Static-table and key-shape sharing | Interval-invariant grid tables and object key-shape tables are stored once per workflow and referenced by key | Small | Content-addressed | **Adopt** (WP2, WP3) |
| Single-pass pack + identity | Avoids a second streamed pass over GB-scale records at publication | Small | The identity is computed over the same canonical bytes the parity check uses | **Adopt** (WP2) |
| Locality reordering of rows (cluster by plate/support) | Better chunk sharing and compression | Needs a permutation array, because logical order is part of the identity | Lossless with a permutation | **Planned, WP4/WP2** (gated) |

## 9. Storage layout, atomic publication and immutable history (WP13)

**Decision.** Each interval is stored in its own compact store file, sealed once complete and read-only from then on. A small catalog file ties the intervals together. Every technique in sections 6-8 applies inside each interval file. This replaces the earlier idea of rolling over to a new file only when a store nears its limit.

**Why.**
- No file ever grows without bound.
- A failure in interval N cannot damage intervals 1 to N-1.
- Saving is a simple atomic sequence:
  1. finish writes and validation in an unlisted candidate interval file, finalise its database journal/WAL and close writable handles;
  2. compute its logical Merkle seal, write any final in-file seal metadata, then flush/fsync all final bytes and close it;
  3. compute the SHA-256 of those final bytes, make the candidate immutable, and verify its required references; no further mutation is allowed;
  4. write/fsync a temporary catalog containing the complete entry, then replace the active catalog atomically using the supported Windows durability mechanism.

  Define a stable seal preimage: ordered manifests, decoded-content chunk IDs and referenced parent seals, excluding the seal field itself and the whole-file SHA. Store the final file SHA only in the catalog to avoid a self-referential file hash. WP13 tests both process-crash recovery and the supported filesystem durability semantics; a mocked replace alone does not prove power-loss durability.
- Closed intervals can be backed up and verified independently. Relocation/archive operations retain the complete reachable reference set. Cold recompression creates a separate immutable archive set under the rule below; it never rewrites an active sealed file.
- Reopen resolves the latest file and its transitive reference closure. Verify seals and identities when each referenced file is first opened, and verify chunk payload hashes when read. A manifest/Merkle-root check alone does not prove the stored payload bytes are intact. Report full-file SHA verification separately from selective payload verification; never claim a full physical-file check from a lazy read.

**Layout.**
- `<workflow>/catalog.json` is the only mutable accepted-state index. An in-progress interval file is writable but is never accepted state. The catalog is an ordered list, rewritten by temp-file plus replace with the durability treatment above. Its growth is O(intervals plus reference edges), not constant: WP13 measures serialised bytes and peak rewrite cost against an explicit charged bound before launch. If the bound is reached, refuse advancement and retain the previous catalog; design a paged successor before larger histories, without silently raising limits. Each entry contains:
  - interval number;
  - file name;
  - file SHA-256;
  - seal: the Merkle root over that file's manifests and chunk IDs;
  - parent interval and parent seal;
  - the logical head identity (unchanged scientific IDs);
  - the set of earlier files the interval references;
  - producer/runtime identity.
- `<workflow>/interval-0000.sqlite` holds the migration root. It contains IV1 converted compact per D6, verified exactly against the authenticated original. The original historical store stays untouched, outside this set, as evidence.
- `interval-0001.sqlite`, `interval-0002.sqlite` and so on follow, one per successor interval. Each file is an ordinary ArrayStore with the existing per-file limits (512 MiB per snapshot, 1 MiB manifest, 4 GiB per file).

**Cross-file sharing.**
- Unchanged chunks are not stored again. The new interval's manifests refer to them by content hash plus the interval file that holds them, read-only.
- Only files listed in the catalog entry's reference set may be referenced. References may only point to earlier, already sealed files.
- A referenced chunk is verified by its content hash when read. The referenced file's seal is checked when it is first opened in a process.
- This keeps the compact layout's chunk-sharing savings while every file stays immutable once sealed.

**Atomicity and recovery.**
- An interval file that is not yet in the catalog is an unaccepted attempt, including a fully sealed file left by a crash before catalog replacement. It is never read as accepted state. It can be kept for diagnostics or removed by an explicit command; nothing deletes it automatically.
- A restart resumes from the catalog's last entry. Completed geometry queries live in the separate completed-query store, unchanged.

**Opening.**
- A thin store-set layer opens the latest interval file plus, lazily and read-only, only the earlier files its manifests actually reference.
- File handles are bounded with an LRU and charged to the budget. An open file/view stays pinned while borrowed; eviction cannot close a live borrower. Validate safe catalog-relative paths, file identity and the entire required reference closure; missing, cyclic, future, foreign or unsealed references fail closed. An unavailable archive dependency is not an empty chunk or a reason to skip validation.
- The independent reader uses the same layer on a copy, or read-only.

**Identity and provenance.**
- Scientific logical identities and parent links (`parent_key`, `parent_digest`) are exactly as today.
- The catalog adds the physical file seals and the reference sets. The seal of interval N covers its references to earlier seals, so the chain is tamper-evident end to end.

**Interaction with the other work packages.**
- WP1 segments and Merkle roots supply the per-file seal.
- WP5 and WP7 publication writes into the current interval file.
- WP8 runner, reader and materialise create and open the interval set instead of a single working-copy store. Migration writes `interval-0000`.
- WP9 composes the new layer.
- WP10 chooses compression before an active interval file is sealed. Later recompression is L1 work on a separate archive set: create new files with new physical names/hashes, preserve decoded chunk/logical identities, rebuild and verify the archive catalog and all affected reference/seal links, and independently reopen the archive set before claiming it valid. Keep the original files and active catalog unchanged. Switching the active lineage to a recompressed set is a separate reviewed migration; it is not an in-place maintenance action.
- WP10's `.tar.zst` route packages completed diagnostic/export copies only, under section 6. It currently refuses interval databases and active control files. Extending it to a sealed lineage requires L1's complete reachable reference set, independent reopen and archive-catalog obligations; a byte-valid tar bundle alone does not establish an accepted lineage.

**WP13: Interval file set and catalog.**
- **Owns:** new `C/interval_store_set.py`, `C/interval_catalog.py` and their tests.
- **Tests:**
  - atomic catalog update: a crash at each of the four publication steps, including after the new file is sealed but before catalog replacement, leaves the previous accepted state valid;
  - final-file hash after all seal/database writes; exclude circular hash inputs and prove no later writer alters the file;
  - catalog growth/bound refusal and temporary-file recovery;
  - a recompressed archive set keeps logical IDs, has new verified physical hashes, leaves the active set unchanged and reopens independently;
  - an unsealed interval file is refused as accepted state;
  - a cross-file reference to a later, unsealed or unlisted file is refused;
  - a tampered referenced chunk or seal is detected;
  - lazy opening touches only referenced files;
  - handle LRU and budget charging;
  - restart from the last catalog entry;
  - a synthetic 3-interval chain where interval 3 references unchanged chunks of intervals 1 and 2, with no duplicate storage;
  - a fresh-process reader verifies the chain;
  - the existing single-file ArrayStore behaviour is unchanged.
- **Acceptance:**
  - every sealed file is immutable;
  - the whole chain verifies from the catalog;
  - storage of unchanged data is not duplicated;
  - each file stays within its limits at the projected IV2 size.

## 10. Further coverage: everywhere else compact data structures are suitable (Michael, 15 Oct)

WP14-WP17 extend the same scheduled programme to live memory, workers, diagnostics and restart caches. Section 3 assigns their dependencies and integration points; none is an unscheduled appendix. Rules for all of them:
- same principles: lossless and exact, charged, content-addressed where shared;
- whole-record reconstruction only through an explicit, charged export;
- each item measurement-gated;
- no change to physics, results or guard limits.

**WP14: Live in-memory working data during the advance. Highest RAM value; risk R1.**

Today these records are expanded to whole Python/JSON graphs during computation. Interval one reached 9 GB at commit.

Targets:
- `bounds.record()` and `mesh.record()` in `advance_spatial`;
- `step.graph.record()` in the joined heat consumer;
- `DifferentialPartition._json`, the in-memory partition copy;
- the native working dictionary inside `_assemble_partition` while charts are built;
- any other whole-record `record()` or `_json` held across a stage boundary. WP14 inventories these first using the composed sources, representative instrumented advances and Stage D measurements. A pre-advance smoke covers setup only and cannot supply a live-advance memory sample.

**Initial Step 2 source inventory, 15 October 2026 (historical checkpoint).** Started from the selected frozen I runtime, the pinned historical joined-heat helper and current R/C sources. The eight original seams below are preserved; the completed current-source inventory follows them. This was source-only evidence, not composition or a measured live-memory result. In particular, advance_spatial already deletes decoded validation records before graph closure, transport and heat.

| Source seam | Construction and visible lifetime | Owner / remaining work |
|---|---|---|
| `integration_regional_workflow.CollarWorkflow.advance_spatial` | Whole bounds, mesh, interval and partition records are used for lineage validation; explicit deletions precede graph closure and the operators. | WP6 with WP3/WP4: replace the full-record validation transients, retaining the existing early release. |
| `integration_differential_geometry._issue` / `DifferentialPartition` | Encoded `_json` and support handles escape with the issued partition. Current compact admission holds a view and refuses implicit `.record()`. | WP4: compact admission does not prove fresh compact production. |
| `integration_differential_geometry._assemble_partition` | Working regions, supports, cells, contacts and the final dictionary coexist through `_issue`; support handles escape. Parent-support exports have their own retained ownership in the current patch. | WP4: measure simultaneous construction/export lifetimes and held-exception cleanup. |
| `integration_differential_mesh.build_differential_mesh` | Cells, faces, tables and the complete record coexist with encoding; the issued mesh retains `_json`. | WP3: produce compact data directly. `from_compact` and explicit `legacy_record()` already separate compact access from charged expansion. |
| `private_heat_joined_consumer_r6.grouped_account` inside `finish` | Whole graph, transport and mesh records are decoded while `finish` already holds its own decoded records; two heat scalars currently require ledger decoding. | WP6/WP7: remove nested full-record materialisation; verify exceptional ownership. |
| `private_heat_joined_consumer_r6.finish` | Whole graph/transport/metric records coexist with new state and exchange encoding; encoded results and transport/heat handles escape. | WP5/WP6/WP7: change producers and consumers together; compact `.record()` refusal exposes unfinished consumers. |
| `CollarWorkflow._publish` / `_spatial_records`; C `spatial_workflow_patch.records` | Decoded rows and encoded blobs live through `store.put` until the publication context exits. The compact branch avoids full mesh expansion but still holds indexed-state metadata, its envelope and exchange/graph/transport records. | WP5/WP3: measure the combined lifetime; mesh aliases alone do not discharge WP14. |
| R `materialise_endpoint.spatial_records` / `materialise` | Raw/decode/conversion values have explicit normal release points after spatial adoption and geometry/partition restoration. The migrated base survives across its context yield; escaped values and tracebacks retain allocation ownership. | WP8 with WP3/WP4: retain those boundaries and verify compact conversion plus exception paths. |

Source bindings: I is the frozen manifest `597c00328bb8aede225a8a936dcea2edab42d3c894eb87caeb974fdfd576979d`; R materialisation and the historical heat helper are included in the WP0a prepared-source receipt. Additional current-C inventory bindings are `partition_native_patch.py` = `b39b1622e7f8c2b6cd82fb88843e6126851ce6254543e0be1c3ebc7796d453d8`, `partition_workflow_transform.py` = `bb6943af238de4de745b33024ac47d6aed4dfd4b7b6379f2bfda750bd9712d09`, and `exterior_mesh_patch.py` = `60cec74b1210a2c0ea43c42a849b584be44aaa16068edb5aba83b54a9a30576d`. Recheck changed seams at their owning package. Representative advance/commit measurements and all WP14 acceptance work remain INCOMPLETE.

**Step 2 inventory closure, 15 October 2026.** The initial eight seams above are retained as historical findings. The current source-only inventory is now complete for this step: **25 lifecycle groups, all nine measured head-record families, the CAS heat ledger and root mesh, plus bounds, numeric/solver buffers, aggregate publication/restore, caches, workers, diagnostics and completed queries**. Each group records creation, overlapping structures, last use/release, exceptional ownership evidence and the later step responsible for any removal. The full rows and **43 source hashes** are in [the existing WP0a receipt](test-results/wp0a.json), field `step2_gap_closure_20261015`. This extends the inventory; it does not repin the historical census or frozen runtime.

| Remaining live-memory seam | Exact lifetime distinction now recorded | Next owning work |
|---|---|---|
| Partition preparation, supports and body | Preparation caches survive their final scientific use; support metadata causes decode/reissue; the successor body is decoded and issued a second time. Per-support polyhedra already have earlier arena transfers/releases. | Step 8 / WP4 |
| Parent support exports | v2 retains whole exported supports because chart inputs refer into them; charges remain attached, but values survive nested assembly. | Step 8 / WP4 |
| Differential and ordinary meshes | Differential final output is already compact; construction maps/arenas and codec lists/arrays still overlap. The ordinary rigid-mesh builder retains its full JSON route. Closure graph scratch already has an explicit early release. | Step 8 / WP3 |
| Bounds, graph and transport | Validation dictionaries are deleted before operators. Issued bounds/graph remain native; fresh `finish` and `grouped_account` decode graph and transport twice. These are working copies, not failed compact exports. | Step 8 / WP6 |
| State and exchange | Compact cells and sibling DAG sharing are implemented; producer cell lists, lookup dictionaries and exchange trees survive packing/final validation. | Step 8 / WP5 |
| Heat | Direct ledger packing removes giant rational-string JSON; numerical/projection lists, input list copies and immutable field-copy transitions remain. The small heat reference deliberately retains the full result and call. | Step 8 / WP7 |
| Certification and geometry | Compact persistence and bounded owned restores are implemented; native producer descriptor/field copies overlap publication. Plain reservation contexts alone do not prove traceback lifetime. | Step 8 / WP5–WP6 |
| Aggregate publication, restore and caches | Account for all live payload contexts, codec/index/native store buffers, completed heat fields and active borrows together. A bounded cache or isolated retained peak is not the combined process peak. | Step 8 / WP14; Step 12 cache evaluation |
| Worker, diagnostic and query payloads | Explicit ownership and some streaming already exist; parent/worker duplication, diagnostic graph/bounds expansion and per-query JSON growth remain. | Steps 13–14 |

**Inventory acceptance is not removal acceptance.** No representative advance/commit peak is claimed here. Step 8 must implement the remaining releases/copy removals and verify exact stage outputs, held-exception ownership and measured simultaneous-live memory under the unchanged guards. The current R migration/transfer helpers were inventoried as incomplete Step 9 work, not accepted or silently resumed.

Approach:
- Consumers read through the compact views already planned (mesh v3, partition v2, `record_tables`) by owned row access, instead of whole records.
- Where a native function genuinely needs a dictionary, it receives a bounded, charged, per-item export for the item it is working on, never the whole record.
- Producers emit compact form directly where the seam allows: "compact from production".

Tests:
- legacy-versus-compact parity of every affected stage's outputs, byte-identical;
- peak charged and peak measured memory on real-shape synthetic data at IV2 scale;
- held-exception lifetime, with no leaked reservations.

Acceptance:
- representative IV2-shape advance/commit evidence predicts margin under the unchanged 12 GiB guard, with all simultaneous-live components accounted for; actual Stage D high-water marks then confirm or refute that prediction;
- identical results.

**WP15: Worker payloads.** Parallel geometry and heat workers currently receive serialised inputs: the routing InputMap, heat first-pass payloads and endpoint batch jobs.
- Send compact references instead: segment and content IDs, plus row ranges, or shared read-only buffers or memory-maps (WP12) where possible.
- Workers open bounded views themselves.
- Outcome: less copying, less parent and worker RAM, faster dispatch.

Tests:
- worker result parity;
- per-worker memory;
- refusal and cleanup on worker failure;
- behaviour unchanged when parallel is off.

Acceptance: identical results; lower measured per-worker and parent memory.

**WP16: Diagnostic captures.** Pre-advance mesh, bounds and closed-graph dumps, continuation trace inputs, failure captures, and dev-timing files when enabled. The IV1 examples are 49, 20 and 22 MB of gzipped JSON.
- Write captures in the compact record formats, optionally zstd-compressed (section 6).
- Provide one explicit export tool that turns a capture back into JSON for humans and replay scripts.
- Replay scripts read the compact form directly where practical.

Tests:
- capture, compact, export round trip equals the original JSON bytes;
- replay parity on one saved capture.

Acceptance: identical replay results; smaller captures and faster writes.

**Measured component outcome, 15 October 2026.** WP16 private component complete and measured; shared integration remains pending. The owning chat reports 47 focused tests passing and one host-denied hardlink fixture skipped. Exact-byte export and fresh-process saved pressure replay match the historical result. One matched fresh-process pair per class found mesh/bounds/closed-graph transport 11.7–15.7% smaller and writes 24.3–41.4% quicker; reads were 19.7–43.5% slower and no process-RAM saving was demonstrated. These three formats are eligible for owner integration, not already wired. Trace, small failure and direct-column captures remain tested but disabled on the measured size/reopen trade-offs. Evidence: [WP16 receipt](diagnostic-captures/wp16-result.json), SHA256 db9cc5fb914d4ee199d3843d68e221e8c0fe7fae2d6811599c3550b9c6209967. Preserve originals; persisted-v2 failure caller integration must preserve the original exception and make no new admission after budget refusal. No shared codec, runner, frozen source, WP9 freeze or IV2 change was made.

**Required re-evaluation, without another activation reminder.** When WP14/WP15 producer interfaces settle, reassess direct compact columns using already-owned inputs and complete construction/capture/reopen/export costs. During WP16 integration, reassess continuation trace and small failure captures after applicable codec/producer changes. Step 21 must explicitly reconsider all three with the final configuration, enable configurations that pass the existing measured gates, and record a measured reason for anything still disabled. Reuse valid unchanged evidence; these are pending obligations, not demonstrated future gains.

**WP17: Completed-query store.** IV2 may have 15,000-60,000 entries.
- Store entries as compact columnar batches: content IDs, keys, exact result rationals in pools.
- Use a compact index rather than one JSON file per entry, keeping the strict execution binding, validation, partial-write handling and stale/foreign rejection exactly as today.
- Outcome: faster lookup, less disk and fewer files.

Tests: the existing 30 completed-query tests (W5-A) plus large-count lookup and resume tests.

Acceptance: identical hit/miss semantics and results; measured lookup time and store size are reported.

**Measured component outcome, 15 October 2026.** The independent WP17 component passed 77 accumulated focused tests, including all 30 original W5-A cases, exact replay, refusal, crash-before-commit recovery and quotas. At 15,000 synthetic completed queries, disk fell from 18,638,481 to 6,606,848 bytes (64.55%) and files from 15,001 to 2; serial storage writes rose from 29.47 to 104.16 seconds. Three alternating 1,000-query pairs confirmed 2.21–3.97× slower writes. Corrected fresh-process reopen was 10.128 versus 0.004 seconds, while hit lookup was 1.170 versus 4.810 ms. No process-RAM saving is established; the earlier apparent saving was a directory-list measurement artefact and is withdrawn. A separate 60,000-query batch-128 population and sampled fresh-process reopen passed, but this is not native per-query throughput. Compact storage remains disabled by default; bounded pacing is tested but unwired. Evidence: [WP17 receipt](endpoint-checkpoints/wp17-result.json), SHA256 479d97eb51d0a3380acf41d76623948f2e4d3cee76dc883878fb63958f0c98d4. No WP9 input freeze or IV2 was performed.

**Future optimisation targets requested by Michael.** In Step 13/WP17 integration, measure bounded batches and durable paced writes to amortise transaction, index and flush costs. A completed-query acknowledgement must still mean its batch is durable; preserve cancellation, restart, exact execution binding, quotas and partial-write recovery. In Step 14/WP18, evaluate parallel independent encoding/preparation feeding a bounded writer queue; measure whether extra writers help or merely increase database contention. Compare each option and the combined configuration against the same existing file-store workload, reporting total and per-query time, hit/reopen latency, process/logical memory and disk. Geometry or heat speed-ups benefit both storage choices and do not by themselves erase this storage regression. Enable only a measured beneficial configuration; these are future targets, not demonstrated fixes.

**Later phases. Planned, after the IV2 run succeeds.**
- **Phase L1: archival compact copies of older stores and run artefacts.** Examples are the 895 MB historical r9 store, earlier runs' stores and artefact folders.
  - These are converted into compact interval-file sets beside the originals, verified exactly against them.
  - The originals are never modified, moved or deleted. Deletion would need Michael's explicit authority and a tombstone.
- **Phase L2: the rest of Atlas beyond this tectonics run.** That means terrain, climate, soil, vegetation and the other generator stages.
  - This becomes a separate, larger compact-first plan. It reuses the same codecs, segment store, interval file sets and caches, and audits each stage's large records the same way: sizes, consumers and identity.
  - It needs its own scoping and owner approval.

## 11. Speed: geometry and heat, all accuracy-preserving (Michael, 15 Oct)

Every item here must:
- give byte-identical outputs, or the same certified results where a certified range is already approved;
- keep the existing exactness gates;
- be measured, so it is enabled only for a net gain;
- leave the guard limits unchanged.

WP19 lands in Stage A. Its real per-stage measurements select the order within the scheduled acceleration stages; the package numbers are stable identifiers, not a numerical execution order.

**WP18: Parallelism that actually engages.** This extends the existing batching.
- **Endpoint volumes.** Batches currently span only the current support. Workers start only if that one support projects at least 120 s (`integration_parallel_rolling.py` ~468-476, `AutomaticEndpoints._beyond`), so about 2,000 moderate supports stay serial.
  - Let batches span several supports, so the gate uses total remaining work.
  - Schedule hardest first, ordering by learned or estimated cost, so the slow tail starts early.
  - Keep the 64-request / 32-job limits or re-derive them.
  - Results and receipts must stay order-independent, as today.
- **Worker count.** Raise from 2 to 4-8 where measured memory per worker keeps the tree inside 12 GiB with margin.
- **Persistent warm worker pools** across batches and stages, to avoid repeated start-up and imports.
- **Heat first pass.** It is face-independent: 967 s on 6 workers in r8. Move to 10-12 workers within memory.
- **Heat-mesh construction.** Its component-volume queries use the same parallel route.
- **Parallelise the serial heat tails** where independent: LOW predictor, finish and projection sub-steps.

Tests: identical outputs serial versus parallel; memory per worker; cleanup on failure; serial fallback.

**WP19: Checkpoint-only development timing.** Source implementation complete, 15 October 2026; successor composition and real-workload measurement pending.

Michael's later instruction narrows the earlier per-query design: Codex chooses meaningful checkpoints, normally at the end of a subsection. This supersedes per-query recording and extra liveness timestamps.
- Off by default; enable with `ATLAS_DEV_STAGE_TIMING=1` or the launcher's `--dev-timing`. Only unset, `0` and `1` are valid environment values.
- Explicit completion calls only. No query hooks, guard method wrappers, tracing, timer, additional monitor or polling. Existing guardian checks and liveness remain unchanged.
- A normal interval route records completed plans; historical authentication; checkpoint copying; endpoint materialisation; frozen initial workload authentication; root publication/reopen; pressure and force selection; geometry with pre-advance coverage; heat/projection with endpoint publication; post-publication reopen controls; interval source verification; and final source/original verification. The diagnostic session also closes after the function's final cleanup. The stopped-before-advance route records only the subsections it actually completes.
- Wall and parent-process CPU are the intervals between those completion boundaries, including instrumentation and intervening verification. They are not isolated function timings. Worker CPU stays separate in the existing guardian's sampled process-tree evidence. No cost is inferred for uncheckpointed work after an abrupt stop.
- Parent private/RSS observations and logical reservations are captured at checkpoints. Sample maxima and OS process-lifetime peaks are labelled; they do not prove subsection peaks or incremental diagnostic RAM. Optional guardian evidence remains sampled and is never added to exact parent CPU totals.
- Events stream to `dev-stage-timing.jsonl` beside the run receipt. Bounds are 16 KiB per event, 256 MiB per log, 256 report aggregates, and a 256 KiB optional shared-budget reservation once that budget exists. The reservation is accounting, not a measured physical-memory limit. Recording failure or a cap stops diagnostics and marks them incomplete without replacing a workload result or cancellation.
- `dev_stage_timing_report.py --events <run-directory>/dev-stage-timing.jsonl [--guard-receipt <guard-receipt>]` reconciles integer wall/CPU totals. A normally closed failed workload has complete timing coverage but an incomplete final subsection; truncated/malformed evidence cannot become successful workload acceptance.

Implementation: [recorder](dev_stage_timing.py), [report](dev_stage_timing_report.py), source-bound runner/launcher options, twelve runner/driver completion calls and successor helper inventory. The frozen composition and `reviewed-inputs.json` remain unchanged. WP9's existing successor-composition path must review current inputs and verify the affected imports before this can be used on a real run.

Verification: **78 focused tests pass**, including exact totals, partial evidence, diagnostic failures, budget release, launch flags, completed-boundary placement and enabled/disabled driver selector behaviour; targeted Ruff checks pass. [Evidence and limits](test-results/wp19.json). The broad native preparation fixture was not completed; no real scientific run or independent acceptance is claimed.

Measured local overhead: one controlled experiment, three interleaved blocks of 1,000 synthetic checkpoints each, with actual memory sampling and file writes. Median enabled cost above disabled was **8.38 microseconds per checkpoint**; first enabled setup **11.28 ms**, later setup about **0.42 ms**; logs averaged **286 bytes per checkpoint** including session markers. This is local observation overhead with warm filesystem cache, not a whole-simulation percentage or incremental RAM measurement. [Raw measurements and source bindings](test-results/wp19-overhead.json). Use the same instrumentation on both sides of later performance comparisons.

**WP20: One-shot exact certificates for zero-volume slivers.**
- The r4 stall was the subdivision loop trying to settle zero versus positive volume.
- Before subdividing, try a small exact infeasibility or emptiness certificate: an exact LP feasibility check, or a Farkas certificate over the query's half-spaces.
- Proved "empty" ends the query. Otherwise fall back to the unchanged subdivision.

Tests: on saved r4-style queries, certified results equal the subdivision results; leaf counts are reported.

**WP21: Exact constraint simplification and chart merging.** This limits growth from interval to interval.
- Remove half-spaces that are exactly proved redundant.
- Merge charts whose exact constraint sets are identical.
- Deduplicate carried constraint histories.
- Canonical logical order and identities stay as defined by retaining original logical records/permutations while sharing or simplifying the computation. If an optimisation truly requires changed identity semantics, leave that path disabled pending an explicit reviewed identity successor and its existing authority. Region/volume equality alone does not authorise a new scientific identity.
- This cuts work in every later stage and in storage.

Tests: exact equality of the represented regions and volumes before and after; chart and constraint counts reported per interval.

**WP22: Filtered exact predicates everywhere they apply.** This extends filtered-exact-r1 beyond planes and cap orientation.
- Cone-proof sign tests, ray/triangle and edge predicates, clipping orientation, and voxel/box classification.
- binary64 with proved error bounds, falling back to exact GMP only when ambiguous (Shewchuk/CGAL-style).
- Vectorise the float filters with numpy over many items at once.

Tests: identical decisions to the exact path on randomised and saved inputs, including near-degenerate cases; filter hit rates.

**WP23: Exact arithmetic efficiency, all lossless.**
- **Homogeneous (projective) integer coordinates** where divisions occur, removing rational divisions and gcd work.
- **Lazy rational reduction:** keep numerator and denominator unreduced through intermediate steps and reduce only at output or comparison. The stored canonical form is unchanged.
- **Shared-denominator and common-scale arithmetic**, in line with the storage plan.
- **Precompute per-support invariants once per interval:** exact plane equations, normals and posed vertices, held in the support cache (WP11).
- **Conservative spatial pruning:** outward-rounded bounding boxes and a BVH/grid to skip exact tests that are provably irrelevant.
- **Child-from-parent reuse in subdivision:** a child inherits its parent's proven facts.

Tests: identical outputs; per-kernel timings.

**WP24: Compiled hot kernels.**
- Move the cone-proof and clipping inner loops, about 85% of the stalled stage's samples, into compiled code (Cython or a C extension) over the same exact GMP arithmetic.
- The Python versions stay as reference and fallback.
- Gate: adopt only if WP19 shows these kernels still dominate after WP18 and WP20-WP23, because it adds a build step and a new source-identity class.

Tests: decision-for-decision identity with the Python kernels on large saved query sets.

**WP25: Heat warm start and mixed-precision certified solves.**
- This is a separately identified acceleration candidate after the compact heat baseline. It does not relax D2: the packaging-only r13 successor still proves an AST-identical numerical kernel. Any later solver changes carry their own source identity and exact certified-record/account checks before integration.
- Start the LOW predictor from the previous interval's solution.
- Where a certified solve is iterative, use floating-point iterative refinement with exact residual verification.
- The certified results are unchanged; only the work to reach them falls.

Tests: identical certified heat records and accounts on the existing controls; iteration counts.

**Caches (all bounded, charged, content-keyed and measured; see WP11).**
- decoded supports;
- decoded chunks;
- verified chunk hashes;
- sealed identities;
- cross-query and cross-interval certified facts, keyed by exact inputs, so unchanged regions reuse proofs;
- posed-support and rotation transforms per support per time;
- exact plane and normal invariants;
- the completed-query store, which already exists.

## 12. Further techniques from the mod-inspired ideas register (Michael, 15 Oct)

Source: `The Diadem - Local Workspace/06_Generator_System/engine/MOD_INSPIRED_GENERATOR_IDEAS_TO_EVALUATE.md` (57 entries).
- Mapped by entry title and summary, not a full read of every entry. The next session should read each cited entry before implementing it.
- About 25 entries are already covered by sections 1-11 or by finished work.
- About 20 are rendering, UI, GPU or noise items that do not fit exact geometry and heat.

The eleven mappings below are included in the owning packages and the section 3 schedule. Read the full cited source entry before implementation; this summary is discovery evidence, not a substitute. Each retains the same accuracy and measurement gate.

| Register entry | Application here | Expected effect | WP |
|---|---|---|---|
| 054 Durable paced asynchronous checkpoint persistence | Completed-query writes: a background writer batches fsyncs while the strict check and publication semantics stay per query. A query counts as complete only once its batch is durable. | End-to-end miss cost was 61 ms against a 41 ms check, so about 20 ms per query goes to write and fsync. At 15-60k queries that is roughly 5-20 min saved. | WP17 |
| 043 Section summaries, direct grouped access | Per-chunk and per-segment summaries (exact bounding boxes, min/max, counts) stored with each segment, so reads and queries skip irrelevant chunks without decoding them | Fewer reads and decodes; faster pruning | WP1/WP2 |
| 019 Persistent derived indexes with atomic refresh | Persist the spatial pruning index (BVH or grid over supports and charts) in each interval file, so it is not rebuilt on every open | Faster start of each stage and each reopen | WP23/WP13 |
| 010C Homogeneous-region exact fast paths | Cells provably wholly inside or outside every constraint get their exact volume (whole cell or zero) without subdivision. This extends the existing padded-containment shortcut. | Can remove many subdivisions in bulk regions | WP20 |
| 032 Bounded buffer pools | Reuse charged byte and array buffers in codecs, I/O and float filters instead of reallocating per item | Less allocation churn; steadier RAM | WP1/WP10/WP22 |
| 037 Batch runtime-boundary crossings | Call numpy and gmpy2 on batches, not item by item, in hot loops | Lower Python overhead in hot paths | WP22/WP23 |
| 027 Resolve handlers once, dispatch directly | Bind hot function and method references once outside loops; use direct dispatch tables instead of per-item lookups | Small but broad CPU saving | WP23 |
| 008/046 Dependency-aware task graph across stages | Overlap independent work. Examples: compact-encode and seal the previous interval's records, or prepare heat-mesh inputs, while geometry runs. Bounded and charged. | Hides encode, publication and setup time behind compute | WP18 |
| 017 Packed coordinate identities | Single packed integer keys for voxel and cell coordinates instead of tuples or strings in lookups and storage | Faster lookups; smaller ID columns | WP2/WP3 |
| 029 Stage-specific retention | Explicitly release each structure after its last use in a stage (charged leases closed), so only live data stays in RAM | Lower peak RSS during the advance | WP14 |
| 021 Tight bounds with extent caching | Cache exact per-support extents and bounding boxes, updated only when the pose changes | Fewer recomputed bounds | WP11/WP23 |

## 13. Game Optimisation Benchmark: the 94 techniques mapped (Michael, 15 Oct)

**Source:** Michael's 11-category list of 94 techniques, pasted in chat on 15 Oct.

**Excluded as not applicable:**
- Categories 7 (lighting) and 8 (rendering and GPU).
- From category 6, simulation LOD is **rejected** because it would reduce accuracy. Hot-path patches for third-party content do not apply.

**Already covered by sections 1-12:**
- Algorithmic changes: incremental work, indexing, shared work (WP20, WP21, WP23, WP11).
- Data structures, ADTs, arrays/maps and packed keys (codecs, section 12 entry 017).
- Octrees, KD trees and BVHs (WP23, section 12 entry 019).
- Memoisation and caching (WP11).
- Fast paths (WP22, section 12 entry 010C).
- Strength reduction (WP23).
- Deforestation (WP14).
- Loop-invariant code motion and common subexpression elimination (WP23, existing proof reuse).
- Copy elision (WP12, WP15).
- Memory layout and narrow types (codecs, bit-packing).
- Memory pooling (section 12 entry 032).
- SIMD/data-level parallelism (WP22 numpy batches).
- Multithreading, and segmentation with prioritisation (WP18).
- Asynchronous and lazy loading (section 8, section 9).
- Persistent caching across launches (completed-query store, persisted indexes).
- Deduplicated replication (content-addressed chunks).
- Macro (dictionary) compression (WP10).
- Embedded databases (ArrayStore).
- Dead store elimination (content addressing).

**Additional techniques assigned to the scheduled packages** (all accuracy-preserving and measurement-gated):

| Technique (category) | Application here | WP |
|---|---|---|
| Induction-variable stepping (2) | **Exact incremental evaluation during subdivision.** A child box's plane and constraint values are the parent's values plus exact deltas, instead of being re-evaluated from scratch. The same applies to sweep loops. | WP23 |
| Partial evaluation / code generation (1) | Generate specialised exact predicate functions for the common constraint shapes, such as fixed half-space counts and axis-aligned boxes, instead of generic interpreted loops. This feeds WP24. | WP23/WP24 |
| Expression templates / loop fusion (1, 2) | Fuse chains of exact operations into one integer expression, such as determinants and plane tests, with no intermediate rational temporaries. Fuse repeated passes over the same arrays. | WP23 |
| Abstract data types swap (1) | Keep the interfaces but replace any remaining Python `Fraction` and other generic types in hot paths with gmpy2 `mpq`/`mpz` (exact and faster). Audit the hot paths first. | WP23 |
| Loop interchange / tiling for locality (2) | Group and order queries by support and chart, so each decoded support and its cached invariants are used many times while still hot (pairs with the WP11 support cache). | WP18/WP11 |
| Bounds-checking elimination (2) | Keep every safety check, but where a check is provably invariant over a block (type, identity, budget scope) do it once per block or batch instead of once per element. | WP23 |
| Jump threading (2) | The same guard re-tested across layered wrappers, such as budget, cancel and identity checks, is tested once per scope. The cancel and guard cadence must still meet the existing responsiveness bounds. | WP23 |
| Test reordering (2) | Order predicate and filter tests so the cheapest, most decisive test runs first, from measured decisiveness rates (WP19). | WP22 |
| Rematerialisation (2) | Cache-design rule: do not cache values that are cheaper to recompute than to look up and keep resident. Each cache must show a measured net gain. | WP11 |
| Speculative execution (4) | Use idle cores to prefetch and decode the supports and segments of upcoming queries, and to precompute the next stage's independent inputs. Results are discarded if unused. Bounded and charged. | WP18 |
| External sorting (1) | Any sort or canonical ordering that compact conversion of 400-950 MB records needs uses a bounded-memory external merge sort, never a whole in-RAM sort. | WP2/WP14 |
| Memory attribution profiling (11) | Record parent private/RSS observations at completed subsection checkpoints alongside logical budget categories. Label process-lifetime and guardian sampled peaks separately; checkpoint observations do not prove stage peaks. No tracemalloc during timed runs. | WP19 |
| Integer / fixed-point arithmetic (3) | Exact dyadic values stored as an integer plus a shared exponent (exact fixed point), extending section 8's shared denominators to arithmetic as well as storage. | WP23 |

**Considered and left out:**
- Loop unrolling, inversion and reversal; register allocation; instruction selection and scheduling; branch-offset optimisation; prescient stores; tail calls; trampolines. In Python these are the interpreter's job, or not a lever.
- Cache-collision reduction: only relevant if packed keys show hashing hotspots. WP19 would reveal that.
- Load spreading and event-driven updates: no periodic per-tick work here.
- Network items: not applicable.
- Pathfinding: not applicable.

## 14. Completion, evidence reuse and continuation

**Two distinct milestones.**

1. **Compact IV2 accepted:** the selected candidate completes the real interval-two advance and publication under unchanged guards, bounded in-process revalidation passes, and the independent fresh-process reader verifies scientific/accounting identities, compact references and historical receipt compatibility. The catalog still reopens the preceding accepted state after a simulated interrupted attempt. This milestone permits the scheduled acceleration work to continue; it does not mean all WP0-WP25 work is complete.
2. **Optimisation programme complete:** every WP0-WP25 package and every technique assigned in sections 6-13 has an outcome in the existing package/composition receipts: implemented and enabled with measured benefit; implemented/tested and disabled because its benefit gate failed; or an explicitly prerequisite-gated item such as WP24 measured out under its stated gate. An unresolved failure, missing measurement or missing authority stays INCOMPLETE. The final enabled composition passes all affected parity, bound, recovery and independent-reopen checks. Broader Atlas L2, archival L1 and live/EXE promotion are not implied.

**Evidence is bound to what was exercised.** Record exact source/helper/runtime/configuration and authenticated input identities, guard/thread/cache settings, output identities, elapsed time and resource peaks in the existing receipts. Reuse adequate unchanged evidence at its exact scope. A source change invalidates only the affected evidence and downstream dependencies; a new thread or doc revision alone is not a reason to rerun tests. A new composition identity can invalidate old completed-query hits even where a focused mathematical result remains reusable.

**Combined integration.** WP9 maintains the accepted candidate composition and the affected-check matrix; WP8 owns its runner/reader result. Optional accelerations are combined only after individual focused parity and benefit checks. Re-exercise the changed live/commit/reopen path on the combined candidate where needed, because independent wins can compete for memory or change scheduling. Do not run a fresh multi-hour interval for documentation-only changes or unchanged unrelated packages.

**Existing records only.** Update this plan's status, the current WORKFLOW_DECISIONS entry and existing package/composition receipts at meaningful checkpoints. Keep the detailed historical entries and predecessor evidence. Do not create another task registry, recurring monitor or review ledger. A due result/dependency return uses the authorised direct-return route with the exact outcome/evidence and next action; routine bookkeeping does not wake another task.

**Next action: complete Step 8 / WP14.** Remove the remaining whole-record copies and unnecessary stage-spanning retention identified in the 25-group inventory; preserve exact stage outputs, identities and paid exception lifetimes. Measure representative simultaneous-live construction/advance/commit memory with matched time/RAM/disk evidence under unchanged guards. Test-only current-source composition is allowed for these checks; frozen WP9, real migration and real IV2 remain later steps.
