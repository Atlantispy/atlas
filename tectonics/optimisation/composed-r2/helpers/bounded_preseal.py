"""R2 option A (D3): bounded pre-seal checks of one unsealed interval candidate.

Revision 2 (16 Oct 2026, after the refuter; see DESIGN-rev2-changes.md). New module for
the Step 8 chat. Runs after the driver and _successor_checks, immediately before
store.seal_and_promote. It reads manifests and raw stored chunk rows of THIS interval only.
Revision 3 (16 Oct 2026, fixes/r3/final/DESIGN-r3-final.md): rebased on the live hotfix
(G8 term and digest delegated to interval_store_set); an accumulator offered without the
storage layer's recomputation functions is refused; the mesh docstring below follows the
publish-and-keep route.
Revision 4 (16 Oct 2026, docstring only): the mesh docstring follows (b') and the accepted
trace (published by persist_mesh inside _publish, not bound afterwards). No code changes.

- every chunk row the candidate wrote: read-and-hash of (descriptor, codec, payload)
  against its stored_sha, NO decode; counts and bytes equal the candidate's in-process
  counters. The row hash does not cover the chunk id (gap G8): when the storage layer
  offers local_chunk_binding_digest() (an order-independent (id, stored_sha) digest kept
  by put_chunk), the same binding is recomputed here, with the storage layer's own term
  and digest functions, over the rows just read and hashed, and the two must be equal;
  otherwise ('unavailable') only a decoding read binds an id to its content, which is the
  fresh reader's;
- every manifest the candidate wrote: native manifest validation (resolve_manifest), its
  stored digest, and by schema: segment roots opened as SegmentView (root key, index
  pages, Merkle tree, coverage, logical bytes) with every leaf's chunk present with its
  exact descriptor locally or in a referenced sealed ancestor (no decode); restart
  aliases reconstructed to their native manifest and hashed against the alias identity;
  plain native manifests' local chunk references present with exact descriptors;
- the head: written in this interval, its metadata hashing to the identity _publish
  produced in this process, its compact record descriptors bound by their bundle roots,
  parent/root links, and its array-name inventory (names only);
- the store change token is unchanged across the whole check.

The production record identities handed to the fresh reader come from that head, whose
canonical hash equals the produced row: the record descriptors, the partition v2
descriptor identity and the v3 mesh identity. No live partition or mesh stream runs
before the seal. Nothing here calls resolve_chunk, a codec decode,
CompactRecord.from_segment, export_record, restore_records, restore_checkpoint or a
partition restore. Per-scalar re-decoding and the streamed identity recomputation
belong to the mandatory independent fresh-process reader, which reads the SEALED files.
"""
import json
from hashlib import sha256

import numpy as np

PRESEAL_SCHEMA = 'atlas.r2-bounded-preseal.v2'
# Fixed transient booking under the run budget (category below). Manifest verification
# and SegmentView opens additionally book their own existing charges; nothing here scales
# with record size: one chunk row (<= 64 KiB payload + 4 KiB) is held at a time.
PRESEAL_WORK_BYTES = 4 << 20
CHECK_EVERY = 256
BUNDLE_SCHEMA = 'atlas.spatial-record-bundle.v1'
REFERENCE_SCHEMA = 'atlas.spatial-record-ref.v1'
# Gap G8: optional storage-side accumulator, feature-detected on the candidate. The term
# and digest are the storage module's own (interval_store_set.chunk_binding_term and
# chunk_binding_digest); this module keeps no private formula.
CHUNK_BINDING_API = 'local_chunk_binding_digest'
# The storage functions this module's recomputation delegates to. interval_store_set
# defines them in the same file as the accumulator method (8888fcaa), so a real candidate
# offers all three or none; one offered without the others is refused, never trusted.
CHUNK_BINDING_RECOMPUTE_FUNCTIONS = ('chunk_binding_term', 'chunk_binding_digest')
CHUNK_BINDING_ABSENT = 'unavailable: chunk id/content binding is checked only by a decoding read (G8)'


class PresealRefused(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise PresealRefused(message)


def workflow_hash(value):
    """Identical to integration_regional_workflow._json/_hash (RC1 lines 27-32)."""
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return sha256(raw).hexdigest()


class _Throttle:
    """Event-like cancel for store APIs; calls the caller's check every N polls.

    The runner's check is guard.check(force=True), which raises on a guard stop; a
    callable returning True, or an Event that is set, also cancels. Inside this
    module's own loops that raises PresealRefused('... cancelled'); inside a store API
    the API's own cancellation error is raised (segment_store: CancelledError)."""

    def __init__(self, cancel, every):
        self.cancel, self.every, self.polls = cancel, every, 0

    def is_set(self):
        self.polls += 1
        if self.cancel is None or (self.polls - 1) % self.every:
            return False
        if hasattr(self.cancel, 'is_set'):
            return bool(self.cancel.is_set())
        return bool(self.cancel())


def chunk_binding_term(cid, stored_sha):
    """One term of the G8 binding sum: exactly interval_store_set.chunk_binding_term."""
    import interval_store_set as I
    return I.chunk_binding_term(cid, stored_sha)


def chunk_binding_digest(total, count):
    """The text local_chunk_binding_digest() returns for `count` inserted rows:
    exactly interval_store_set.chunk_binding_digest(count, total)."""
    import interval_store_set as I
    return I.chunk_binding_digest(count, total)


def head_record_descriptors(head):
    """The successor head's compact record descriptors, selected exactly as
    endpoint_record_identities selects them (RO 242-252): every header is required."""
    require(type(head) is dict and head.get('kind') == 'successor', 'successor head required')
    try:
        refs = dict(head['exterior_state']['record_blobs'])
        require(set(refs) == {'state'}, 'complete compact state record required')
        exchange = head['exterior_advance']['record_blobs']
        require(set(exchange) == {'exchange', 'graph', 'transport', 'heat'}, 'complete compact exchange records required')
        refs.update(exchange)
        for header, kind in (('differential_certification', 'certification'), ('differential_geometry', 'differential')):
            refs[kind] = head[header]['record_blob']
    except (KeyError, TypeError) as error:
        raise PresealRefused('complete compact successor record headers required: ' + repr(error)) from error
    return refs


def array_inventory(names, *, exterior, spatial, differential):
    """Names-only copy of the full _refresh 'unowned arrays' refusals for a successor head
    (RC1 integration_regional_workflow.py 1203-1225)."""
    names = list(names)
    has = lambda *prefixes: any(n.startswith(prefixes) for n in names)
    require(exterior or not has('exterior-fv:'), 'unowned exterior arrays in a closed collar checkpoint')
    require(spatial or not has('spatial-audit:'), 'unexecuted or unowned spatial solve arrays in collar checkpoint')
    require(spatial or not has('spatial-record:'), 'unowned spatial record blobs in collar checkpoint')
    require(differential or not has('differential-network:', 'differential-record:'),
            'unexecuted or unowned differential geometry in collar checkpoint')
    require(differential or not has('certification-record:', 'certification-force:'),
            'unexecuted or unowned differential certification in collar checkpoint')
    require(differential or not has('partition-record:'), 'unowned differential partition in collar checkpoint')
    return sorted(names)


def _hash_local_chunks(candidate, cancel):
    """Read-and-hash every chunk row of this candidate; no codec decode."""
    import interval_store_set
    from compact_contracts import NATIVE_CHUNK_BYTES, _sha
    from interval_catalog import digest
    from interval_store_set import typed_descriptor
    count = payload_bytes = binding = 0
    # The binding is computed only when the candidate keeps the storage accumulator,
    # so stores that predate G8 never touch the storage binding functions.
    accumulator = getattr(candidate, CHUNK_BINDING_API, None)
    if accumulator is not None:
        require(callable(accumulator) and all(callable(getattr(interval_store_set, name, None))
                                              for name in CHUNK_BINDING_RECOMPUTE_FUNCTIONS),
                'storage offers the chunk binding accumulator without its recomputation (G8)')
    with candidate._lock:
        candidate._writing()
        cursor = candidate._db.execute('SELECT id,descriptor,codec,stored_sha,payload FROM chunks ORDER BY id')
        try:
            for cid, desc, codec, stored, payload in cursor:
                require(not cancel.is_set(), 'bounded pre-seal check cancelled')
                _sha(cid, 'local chunk identity')
                require(type(desc) is bytes and type(codec) is str and type(stored) is str and
                        type(payload) is bytes and len(stored) == 64 and len(codec) <= 128 and
                        len(payload) <= NATIVE_CHUNK_BYTES + 4096, 'invalid bounded candidate chunk record')
                typed_descriptor(desc)
                require(digest(desc + b'\0' + codec.encode() + b'\0' + payload) == stored,
                        'candidate chunk stored hash mismatch (read-and-hash): ' + cid)
                if accumulator is not None:
                    binding += chunk_binding_term(cid, stored)
                count += 1
                payload_bytes += len(payload)
                del payload
        finally:
            cursor.close()
    stats = candidate.local_statistics()
    require(count == stats['local_chunks'] and payload_bytes == stats['encoded_payload_bytes'],
            'candidate chunk inventory differs from its in-process production counters')
    if accumulator is None:
        return count, payload_bytes, CHUNK_BINDING_ABSENT
    require(accumulator() == chunk_binding_digest(binding, count),
            'candidate chunk id/content binding differs from its in-process production accumulator')
    return count, payload_bytes, 'storage-accumulator'


def _local_descriptor(candidate, cid):
    row = candidate._db.execute('SELECT descriptor FROM chunks WHERE id=?', (cid,)).fetchone()
    return None if row is None else row[0]


def _leaf_present(candidate, owner, cid, descriptor):
    """Chunk existence with its exact descriptor; never resolve_chunk (which decodes)."""
    if owner == candidate.interval:
        return _local_descriptor(candidate, cid) == descriptor
    require(type(owner) is int and 0 <= owner < candidate.interval and owner in candidate._references,
            'leaf references an interval outside the candidate reference closure')
    with candidate.stores.borrow_handle(owner) as handle:
        return handle.value.contains_chunk(cid, descriptor)


def _open_root(store, candidate, ref, cancel, leaves):
    """SegmentView open = root key, index pages, Merkle, coverage; then leaf presence."""
    from segment_store import SegmentBackend, canonical
    view = SegmentBackend().open(candidate, ref, scope=store.scope, cancel=cancel)
    try:
        count = 0
        for entry in view._entries():
            body = entry['content']
            if body['chunk_id'] is not None:
                require(_leaf_present(candidate, entry['owner'], body['chunk_id'], canonical(entry['descriptor'])),
                        'segment leaf chunk missing or descriptor differs: ' + body['chunk_id'])
            count += 1
        leaves[0] += count
        # Keep only a bundle's small records table (needed for descriptor binding).
        metadata = view._owner.value['metadata']
        if ref.identity.record_schema == BUNDLE_SCHEMA and type(metadata) is dict:
            return {'records': metadata.get('records')}
        return None
    finally:
        view.close()


def _verify_local_manifests(store, candidate, cancel, head_key):
    import math

    from compact_contracts import NATIVE_CHUNK_BYTES, SegmentRef, SnapshotLocator
    from interval_catalog import canonical, digest
    from interval_store_set import seal_key
    from segment_store import PAGE_SCHEMA, ROOT_SCHEMA
    seal = seal_key(candidate.workflow_id, candidate.interval)
    # The store's own module (R); imported apart from the C modules above.
    import compact_restart_store as CRS
    roots, aliases, leaves = {}, [], [0]
    counts = {'manifests': 0, 'roots': 0, 'pages': 0, 'aliases': 0, 'native': 0, 'manifest_bytes': 0}
    head = None
    with candidate._lock:
        keys = [k for (k,) in candidate._db.execute('SELECT id FROM snapshots ORDER BY id')]
    # Only ids are held (64 hex chars each); bodies are verified one at a time.
    for key in keys:
        require(not cancel.is_set(), 'bounded pre-seal check cancelled')
        require(key != seal, 'candidate already carries its final seal')
        locator = SnapshotLocator(candidate.workflow_id, candidate.interval, key)
        with candidate.resolve_manifest(locator, cancel=cancel) as held:
            body = held.value
            stored = candidate._db.execute('SELECT digest FROM snapshots WHERE id=?', (key,)).fetchone()[0]
            require(digest(body) == stored, 'candidate manifest stored digest mismatch: ' + key)
            manifest = json.loads(body)
        counts['manifests'] += 1
        counts['manifest_bytes'] += len(body)
        meta = manifest['metadata']
        schema = meta.get('schema') if type(meta) is dict else None
        if schema == ROOT_SCHEMA:
            ref = SegmentRef.from_wire(meta['reference'])
            require(ref.root_key == locator, 'segment root locator differs from its own manifest')
            roots[key] = (ref, _open_root(store, candidate, ref, cancel, leaves))
            counts['roots'] += 1
        elif schema == PAGE_SCHEMA:
            counts['pages'] += 1          # authenticated through its root's Merkle walk
        elif schema == CRS.ALIAS_SCHEMA:
            require(meta.get('invocation') == key, 'restart alias invocation differs')
            aliases.append(key)
            counts['aliases'] += 1
        else:
            # Same exact local-reference rule put_manifest enforced at write time.
            for desc in manifest['arrays'].values():
                itemsize = np.dtype(desc['dtype']).itemsize
                count, width = math.prod(desc['shape']), NATIVE_CHUNK_BYTES // itemsize
                for index, cid in enumerate(desc['chunks']):
                    wanted = canonical({'dtype': np.dtype(desc['dtype']).str, 'count': min(width, count - index * width)})
                    require(_local_descriptor(candidate, cid) == wanted,
                            'native manifest references a missing or foreign local chunk')
            counts['native'] += 1
        del manifest, meta, body
    require(counts['manifests'] == candidate.local_statistics()['manifests'],
            'candidate manifest inventory differs from its in-process production counters')
    for key in aliases:
        require(not cancel.is_set(), 'bounded pre-seal check cancelled')
        # Reconstructs the exact native v1 manifest from the segment index (names, shapes,
        # dtypes, chunk ids, metadata) and requires sha256/bytes == the alias identity.
        # store._segment takes no cancel: each walk is one segment index (at most
        # SEGMENT_CHUNK_REFERENCES leaves); the poll above runs between aliases.
        with store._read_scope(), store._workspace(8 * store.limits.max_manifest_bytes,
                                                   category='r2-preseal-alias'), store._segment(key) as view:
            # Its segment is this interval's (verified above) or an identical sealed ancestor's
            # (publish reuses an existing root); either way the open re-validates the index.
            require(view is not None and (view.ref.root_key.snapshot_key in roots or
                    view.ref.root_key.interval < candidate.interval),
                    'restart alias does not reference a verified segment')
            # Store route (1) (compact_restart_store 3bc480aa): a root-kind row may keep named
            # fields in compact records that only a decoding read rebuilds. A successor interval
            # writes no root-kind row, so such an alias is refused here, never decoded.
            require('external' not in view._owner.value['metadata'],
                    'restart alias with externalised root metadata in a successor interval')
            native_manifest = store._manifest_from_segment(key, view)
        if key == head_key:
            head = {'metadata': native_manifest['metadata'], 'array_names': sorted(native_manifest['arrays'])}
        del native_manifest
    counts['leaves'] = leaves[0]
    return counts, roots, head


def _descriptor_bound(store, candidate, roots, kind, descriptor, cancel):
    """A v1 compact descriptor is bound by its bundle root's records table (manifest-only)."""
    from compact_contracts import SegmentRef
    from segment_store import SegmentBackend
    require(type(descriptor) is dict and {'bytes', 'sha256', 'compact'} <= set(descriptor),
            'complete compact record descriptor required: ' + kind)
    compact = descriptor['compact']
    if compact.get('schema') != REFERENCE_SCHEMA:
        # v2 recipe: each segment opens (manifest-only); identity streaming is the reader's.
        for wire in compact['segments']:
            ref = SegmentRef.from_wire(wire)
            if ref.root_key.snapshot_key not in roots:
                SegmentBackend().verify(candidate, ref, scope=store.scope, cancel=cancel)
        return 'recipe'
    require(compact.get('field') == kind, 'record field binding differs: ' + kind)
    ref = SegmentRef.from_wire(compact['segment'])
    require(ref.identity.record_schema == BUNDLE_SCHEMA, 'foreign record bundle schema: ' + kind)
    if ref.root_key.snapshot_key in roots and ref.root_key.interval == candidate.interval:
        stored, metadata = roots[ref.root_key.snapshot_key]
        require(stored == ref, 'record descriptor references another segment root: ' + kind)
    else:
        view = SegmentBackend().open(candidate, ref, scope=store.scope, cancel=cancel)
        try:
            metadata = view._owner.value['metadata']
        finally:
            view.close()
    records = metadata.get('records') if type(metadata) is dict else None
    require(type(records) is dict and records.get(kind) == {k: descriptor[k] for k in ('bytes', 'sha256')},
            'record identity differs from its authenticated bundle index: ' + kind)
    return 'bundle'


def check_candidate(store, *, head_key, budget, production_head_sha256, links=None,
                    record_descriptors=None, production_records=None, cancel=None, check_every=CHECK_EVERY):
    """Store-level bounded pre-seal check; returns bounded evidence or raises PresealRefused.

    store: the CompactRestartStore whose current resolver is this interval's UnlistedCandidate.
    head_key: the successor head invocation (after['head']).
    production_head_sha256: workflow._published_identity['sha256'], the canonical hash of the
        row _publish produced in this process (transform seam 2).
    links: optional dict(parent_key, parent_sha256, root_key, root_sha256).
    record_descriptors: optional {kind: descriptor}; default head_record_descriptors(head).
    production_records: optional {kind: {'sha256','nbytes'}} computed at production in this
        process, compared with the persisted descriptors.
    """
    from interval_store_set import UnlistedCandidate
    candidate = getattr(store, 'candidate', None)
    require(type(candidate) is UnlistedCandidate and not store.readonly and not store.in_publication,
            'bounded pre-seal checks require the current unsealed candidate')
    require(store.scope.run_budget is budget and store._budget is budget, 'bounded pre-seal checks require the run budget')
    require(type(production_head_sha256) is str and len(production_head_sha256) == 64,
            'production head identity from this process is required')
    cancel = _Throttle(cancel, check_every)
    token = store.change_token()
    with store._workspace(PRESEAL_WORK_BYTES, budget, category='r2-preseal-bounded-check'):
        chunks, payload_bytes, chunk_binding = _hash_local_chunks(candidate, cancel)
        counts, roots, head = _verify_local_manifests(store, candidate, cancel, head_key)
        require(head is not None, 'successor head is not a record written in this interval')
        metadata = head['metadata']
        require(workflow_hash(metadata) == production_head_sha256,
                'persisted head metadata differs from the row produced in this process')
        if links is not None:
            require(metadata.get('key') == head_key and metadata.get('parent_key') == links['parent_key'] and
                    metadata.get('parent_digest') == links['parent_sha256'], 'head/parent link differs')
            for key, wanted in ((links['parent_key'], links['parent_sha256']), (links['root_key'], links['root_sha256'])):
                found = store.metadata(key)
                require(found is not None and workflow_hash(found) == wanted, 'persisted parent or root differs')
        descriptors = head_record_descriptors(metadata) if record_descriptors is None else record_descriptors
        kinds = {kind: _descriptor_bound(store, candidate, roots, kind, d, cancel) for kind, d in sorted(descriptors.items())}
        if production_records is not None:
            for kind, wanted in production_records.items():
                if kind in descriptors:
                    got = descriptors[kind]
                    require({'sha256': got['sha256'], 'nbytes': got['bytes']} == wanted,
                            'record identity differs from the identity computed at production: ' + kind)
    require(store.change_token() == token, 'store changed during bounded pre-seal checks')
    return {'schema': PRESEAL_SCHEMA, 'interval': candidate.interval, 'head_key': head_key,
            'chunks_read_and_hashed': chunks, 'encoded_payload_bytes_hashed': payload_bytes,
            'chunk_binding': chunk_binding, 'decoded_chunks': 0, 'whole_record_exports': 0,
            'record_bindings': kinds, 'head_array_names': head['array_names'], **counts}


def head_partition_identity(head):
    """The successor's partition v2 logical identity, bound by the head hash.

    Equal to partition_workflow_patch.descriptor_stats(view) on the v2 route: that streams
    view.iter_json() = CompactRecord._stream(root), exactly the bytes of _parts(root);
    CompactRecord._validate (run by every from_segment open, the fresh reader's included)
    requires their sha256 and length to equal record.identity(); publish_partition_v2
    publishes identity=view.identity() and bind_segment requires ref.identity ==
    view.identity(); payload() writes ref.to_wire() as the header's compact_partition."""
    from compact_contracts import SegmentRef
    from partition_v2 import DESCRIPTOR
    header = head.get('differential_partition')
    require(type(header) is dict and header.get('record_blobs') == {} and 'compact_partition' in header,
            'compact v2 partition header required')
    ref = SegmentRef.from_wire(header['compact_partition'])
    require(ref.identity.record_schema == DESCRIPTOR, 'partition v2 descriptor identity required')
    return {'sha256': ref.identity.sha256, 'nbytes': ref.identity.canonical_bytes}


def head_mesh_identity(head):
    """The successor's v3 mesh logical identity (a LogicalIdentity), bound by the head hash.

    Equal to the iter_logical_json stream of the mesh: a CompactMesh is sealed only after
    its legacy JSON has been streamed into its identity (CompactMesh.__init__,
    mesh_from_segment), and v3 publication puts view.identity() (or, for a reopened view,
    its segment ref whose identity mesh_from_segment proved equal) into the reference."""
    from compact_contracts import SegmentRef
    from compact_store import V3_SCHEMA
    from mesh_tables import LEGACY
    header = head['exterior_state'].get('compact_mesh')
    require(type(header) is dict and header.get('schema') == V3_SCHEMA and 'segment' in header,
            'compact v3 mesh reference required')
    ref = SegmentRef.from_wire(header['segment'])
    require(ref.identity.record_schema == LEGACY and ref.identity.sha256 == header.get('geometry_id'),
            'v3 mesh identity differs from its geometry')
    return ref.identity


def production_record_identities(workflow, head, descriptors):
    """record['record_identities'] without reading the candidate or streaming a record.

    The descriptor identities, the partition v2 identity and the v3 mesh identity come
    from the head, whose canonical hash check_candidate proved equal to the row _publish
    produced in this process. The live partition is not read: on the adopted-token path it
    is the native partition, which payload() converted and published without attaching a
    compact view. The live mesh is cross-checked in O(1) only: it must be a sealed
    CompactMesh whose verified identity equals the head's. It is never streamed here: under
    (b') (Step 10 chain, 16 Oct 2026) the fresh mesh is the produced in-memory compact view,
    built unpublished at the joint advance and published by persist_mesh inside _publish
    (publish_mesh_patch). It is NOT bound to that root afterwards: the coordinator accepted
    the trace that no same-interval consumer reopens it by reference (the by-reference v3
    openers are restore paths only, and _refresh returns on its adopted token). So its
    same-interval reads use the in-memory columns, and a stream is still unnecessary:
    CompactMesh.__init__ proved the identity when the view was sealed. A view reopened from
    the candidate instead (differential_mesh_patch.produce, audit A2, not on the live route)
    would read candidate pages; the O(1) cross-check reads none either way."""
    import spatial_indexed_patch as SI
    result = {k: {'sha256': v['sha256'], 'nbytes': v['bytes']} for k, v in descriptors.items()}
    result['partition'] = head_partition_identity(head)
    identity = head_mesh_identity(head)
    held = workflow.exterior_state.indexed_record()
    mesh = held.value['thermal_mesh']
    require(SI.is_compact(mesh) and mesh.geometry_id == identity.sha256 and mesh.identity() == identity,
            'live compact mesh differs from the head mesh reference')
    del held, mesh
    result['mesh'] = {'sha256': identity.sha256, 'nbytes': identity.canonical_bytes}
    return result


def publication_references(store, head, *, budget, cancel=None):
    """The existing manifest-only publication verifier (spatial_records_patch.py:505-527):
    verify_records (SegmentView open + _bundle_metadata, no payload arrays) for every head
    record set, with cancel, and spatial_workflow_patch.verify_reference for the compact
    mesh, which takes no cancel (one segment open)."""
    import spatial_records_patch as SR
    producer = head['exterior_state']['compact_mesh']['source_producer']
    SR.verify_publication_references(store, head, budget=budget, cancel=cancel, source_producer=producer)


def bounded_preseal(workflow, *, store, before, after, budget, cancel=None,
                    verify_references=publication_references, live_identities=production_record_identities):
    """Runner-level wrapper: replaces reader.endpoint_record_identities before the seal.

    Precondition: _successor_checks passed (so the persisted parent equals the live parent).
    Returns the evidence dict; evidence['record_identities'] is what the runner records for
    the fresh reader's 'compact_record_identities_identical' comparison, closed by the
    reader's own canonical_record_identities(successor=True)."""
    import reopen_prepared_restart as reader
    published = getattr(workflow, '_published_identity', None)
    require(type(published) is dict and published.get('key') == after['head'],
            'publication identity from this process is missing (R2 transform not composed)')
    chain_head = workflow._r2_metadata_chain()
    require(type(chain_head) is dict and chain_head.get('key') == after['head'] and
            store.metadata(after['head']) == chain_head, 'metadata chain does not end at the persisted head')
    root, parent = json.loads(workflow._root), store.metadata(before['head'])
    require(parent is not None, 'persisted parent missing')
    links = {'parent_key': before['head'], 'parent_sha256': workflow_hash(parent),
             'root_key': root['key'], 'root_sha256': workflow_hash(root)}
    if verify_references is not None:
        # Event-like throttle: SegmentView polls cancel.is_set() per index entry.
        verify_references(store, chain_head, budget=budget, cancel=_Throttle(cancel, CHECK_EVERY))
    descriptors = head_record_descriptors(chain_head)
    evidence = check_candidate(store, head_key=after['head'], budget=budget,
                               production_head_sha256=published['sha256'], links=links,
                               record_descriptors=descriptors, cancel=cancel)
    array_inventory(evidence['head_array_names'], exterior=workflow._exterior_owner is not None,
                    spatial=workflow._is_spatial(), differential=workflow._is_differential())
    evidence['token_adopted'] = published['token_adopted']
    identities = live_identities(workflow, chain_head, descriptors)
    try:
        evidence['record_identities'] = reader.canonical_record_identities(identities, successor=True)
    except reader.ReopenRefused as error:
        raise PresealRefused('production record identities are incomplete: ' + str(error)) from error
    return evidence
