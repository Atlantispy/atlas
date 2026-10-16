"""Reference-only spatial records; bounded explicit legacy-consumer exports.

One authenticated bundle owns the codec DAG. Per-kind references bind its
manifest index and keep the exact original canonical byte count and digest.
Publication checks authenticate manifests only; reopen also proves each used
logical child. Neither authentication stage silently substitutes for the other.
"""
from contextlib import contextmanager
from hashlib import sha256
import json

import numpy as np

from compact_contracts import ContractError, SegmentRef
from content_cache import ChargeSpec
from record_tables import RecordCodec, SCHEMA as CODEC_SCHEMA, canonical, Scratch
from record_views import CompactRecord, RecordRef, LogicalExchange, _metadata as codec_metadata
from segment_store import SegmentBackend


BUNDLE_SCHEMA = 'atlas.spatial-record-bundle.v1'
REFERENCE_SCHEMA = 'atlas.spatial-record-ref.v1'
EXPORT_LOGICAL_BYTES = 32 << 20
EXPORT_OWNED_BYTES = 256 << 20
SMALL_LOGICAL_BYTES = 4 << 20
STATE_NAMES = ('schema', 'state_id', 'owner_id', 'funding_id', 'time_s', 'intervals',
               'parent_state_id', 'collar_state_id', 'support_id', 'trajectory_id',
               'grid_id', 'thermal_mesh_id')
EXCHANGE_NAMES = ('schema', 'result_id', 'state_id', 'owner_id', 'parent_state_id',
                  'collar_state_id', 'source_flow_stage_id', 'source_audit_id',
                  'spatial_graph_id', 'global_transport_id', 'joined_heat_id')
DIFFERENTIAL_NAMES = ('interval_id', 'parent_network_id', 'endpoint_network_id',
                      'start_time_s', 'end_time_s', 'trajectory_id', 'prior_trajectory_id')


def require(ok, message):
    if not ok:
        raise ContractError(message)


def _scope(store, budget, scope=None):
    scope = getattr(store, 'scope', None) if scope is None else scope
    require(scope is not None and scope.run_budget is budget and store.scope is scope,
            'record publication requires its actual retained store scope')
    return scope


def _check(cancel):
    if cancel is not None:
        stopped = cancel.is_set() if hasattr(cancel, 'is_set') else cancel()
        require(not stopped, 'compact record operation cancelled')


def _producer(source_producer):
    require(type(source_producer) is dict and bool(source_producer), 'actual record producer required')
    return sha256(canonical(source_producer)).hexdigest()


def _descriptor(value, kind):
    require(type(value) is dict and set(value) == {'bytes', 'sha256', 'compact'},
            'complete compact record descriptor required')
    require(type(value['bytes']) is int and value['bytes'] >= 0 and
            type(value['sha256']) is str and len(value['sha256']) == 64 and
            all(c in '0123456789abcdef' for c in value['sha256']), 'invalid logical record identity')
    compact = value['compact']
    require(type(compact) is dict and set(compact) == {'schema', 'segment', 'field'} and
            compact['schema'] == REFERENCE_SCHEMA and compact['field'] == kind,
            'record field/schema binding differs')
    return SegmentRef.from_wire(compact['segment'])


def publish_records(store, rows, *, budget, source_producer, scope=None, cancel=None):
    """Pack all sibling records together, so repeated graph subtrees share nodes."""
    scope = _scope(store, budget, scope)
    require(type(rows) is dict and 0 < len(rows) <= 16 and
            all(type(k) is str and 0 < len(k) <= 64 for k in rows), 'bounded distinct record set required')
    packed = RecordCodec().pack_record(rows, record_schema=BUNDLE_SCHEMA, scope=scope,
                                      check=lambda: _check(cancel))
    root = packed.root()
    identities = {}
    for kind in sorted(rows):
        child = root.field(kind)
        identity = child.identity()
        identities[kind] = dict(bytes=identity.canonical_bytes, sha256=identity.sha256)
        child.close()
    with packed.metadata_bytes() as held:
        metadata = canonical(dict(schema=BUNDLE_SCHEMA, codec=json.loads(held.value), records=identities))
        ref = SegmentBackend().publish(store, record_schema=BUNDLE_SCHEMA, identity=packed.identity(),
            metadata=metadata, arrays=packed.array_sources, producer=_producer(source_producer),
            representation_profile=CODEC_SCHEMA, scope=scope, cancel=cancel)
    result = {kind: dict(identity, compact=dict(schema=REFERENCE_SCHEMA,
              segment=ref.to_wire(), field=kind)) for kind, identity in identities.items()}
    root.close()
    packed.close()
    return result


def _bundle_metadata(segment, refs, source_producer=None):
    if source_producer is not None:
        require(segment._owner.value['producer'] == _producer(source_producer),
                'record producer differs from authenticated root')
    # The authenticated root owner already pays for the decoded manifest.
    # Borrow its bounded metadata rather than manufacture an unowned copy.
    metadata = segment._owner.value['metadata']
    require(type(metadata) is dict and set(metadata) == {'schema', 'codec', 'records'} and
            metadata['schema'] == BUNDLE_SCHEMA and type(metadata['records']) is dict and
            0 < len(metadata['records']) <= 16, 'unknown or incomplete record bundle metadata')
    scratch = Scratch(segment.scope.run_budget, 2 << 20)
    codec, identity = codec_metadata(canonical(metadata['codec']))
    require(identity == segment.info.ref.identity and segment.info.array_count == len(codec['arrays']),
            'bundle codec identity or column inventory differs from authenticated root')
    for name, descriptor in codec['arrays'].items():
        with segment.info.array(name) as held:
            require(held.value.dtype == descriptor['dtype'] and list(held.value.shape) == descriptor['shape'],
                    'bundle codec column descriptor differs from authenticated index')
    for kind, descriptor in metadata['records'].items():
        require(type(kind) is str and 0 < len(kind) <= 64 and type(descriptor) is dict and
                set(descriptor) == {'bytes', 'sha256'} and type(descriptor['bytes']) is int and
                descriptor['bytes'] >= 0 and type(descriptor['sha256']) is str and
                len(descriptor['sha256']) == 64 and all(c in '0123456789abcdef' for c in descriptor['sha256']),
                'unknown or malformed bundle logical record descriptor')
    for kind, descriptor in refs.items():
        require(metadata['records'].get(kind) == {k: descriptor[k] for k in ('bytes', 'sha256')},
                'record identity differs from authenticated bundle index')
    del scratch
    return metadata


def verify_records(store, refs, *, budget, scope=None, cancel=None, source_producer=None):
    """Check descriptors, index and root bindings without opening payload arrays."""
    scope = _scope(store, budget, scope)
    require(type(refs) is dict and 0 < len(refs) <= 16, 'bounded record references required')
    groups = {}
    for kind, descriptor in refs.items():
        ref = _descriptor(descriptor, kind)
        groups.setdefault(ref.to_json(), (ref, {}))[1][kind] = descriptor
    for ref, selected in groups.values():
        require(ref.identity.record_schema == BUNDLE_SCHEMA, 'foreign record bundle schema')
        segment = SegmentBackend().open(store, ref, scope=scope, cancel=cancel)
        _bundle_metadata(segment, selected, source_producer)
        segment.close()
    return True


@contextmanager
def open_records(store, refs, *, budget, scope=None, cancel=None, source_producer=None):
    """Yield owned references and prove every requested legacy logical identity."""
    scope = _scope(store, budget, scope)
    require(type(refs) is dict and 0 < len(refs) <= 16, 'bounded record references required')
    groups = {}
    for kind, descriptor in refs.items():
        ref = _descriptor(descriptor, kind)
        groups.setdefault(ref.to_json(), (ref, {}))[1][kind] = descriptor
    segments, records, roots, children = [], [], [], {}
    for ref, selected in groups.values():
        require(ref.identity.record_schema == BUNDLE_SCHEMA, 'foreign record bundle schema')
        segment = SegmentBackend().open(store, ref, scope=scope, cancel=cancel)
        metadata = _bundle_metadata(segment, selected, source_producer)
        record = CompactRecord.from_segment(segment, canonical(metadata['codec']), check=lambda: _check(cancel))
        root = record.root()
        with root.keys() as keys:
            require(set(keys.value) == set(metadata['records']), 'bundle logical record inventory differs')
        segments.append(segment); records.append(record); roots.append(root)
        for kind, descriptor in selected.items():
            child = root.field(kind)
            identity = child.identity()
            require(identity.sha256 == descriptor['sha256'] and identity.canonical_bytes == descriptor['bytes'],
                    'record logical identity differs from its authenticated descriptor')
            children[kind] = child
    # Tracebacks and intentionally retained native-state borrows keep their
    # paid owners. Dropping the local carriers retires backing through GC;
    # forcing close would invalidate an adopted cells child.
    yield children
    # Native state adoption may retain cells by borrow. Its view keeps both
    # CompactRecord and SegmentView alive and paid; forced close here would
    # invalidate a deliberately retained successor state.


@contextmanager
def export_record(store, descriptor, kind, *, budget, scope=None, cancel=None, source_producer=None):
    with open_records(store, {kind: descriptor}, budget=budget, scope=scope, cancel=cancel,
                      source_producer=source_producer) as records:
        with records[kind].export(max_logical_bytes=EXPORT_LOGICAL_BYTES,
                                 max_owned_bytes=EXPORT_OWNED_BYTES) as owned:
            yield owned.value


class _OwnedDict(dict):
    """Small native compatibility dictionary retaining every exported owner."""
    def __init__(self, value, owners):
        super().__init__(value)
        self._owners = owners


def _header(value, names):
    if isinstance(value, RecordRef):
        with value.select(names) as selected:
            held = selected.export(max_logical_bytes=SMALL_LOGICAL_BYTES,
                                   max_owned_bytes=SMALL_LOGICAL_BYTES-65536)
        overhead = value.scope.reserve(ChargeSpec('compact-record-header', 65536), required=True).commit(None)
        return _OwnedDict(held.value, [held, overhead])
    return {name: value[name] for name in names}


def headers(state, exchange, refs, *, mesh_reference=None):
    result = _header(state, STATE_NAMES)
    result['record_blobs'] = {k: refs[k] for k in ('state',) if k in refs}
    if mesh_reference is not None:
        result['compact_mesh'] = mesh_reference
    elif 'mesh' in refs:
        result['record_blobs']['mesh'] = refs['mesh']
    other = None
    if exchange is not None:
        other = _header(exchange, EXCHANGE_NAMES)
        graph = exchange.field('spatial_graph') if isinstance(exchange, RecordRef) else exchange['spatial_graph']
        other['parent_collar_state_id'] = _header(graph, ('parent_state_id',))['parent_state_id']
        if isinstance(graph, RecordRef):
            graph.close()
        other['record_blobs'] = {k: refs[k] for k in ('exchange', 'graph', 'transport', 'heat')}
    return result, other


@contextmanager
def records(cls, state, exchange, budget, *, store, source_producer=None, persist=True,
            cancel=None, aliases=None, scope=None, support_source=None):
    import spatial_workflow_patch as Y
    from mesh_tables import CompactMesh
    scope = _scope(store, budget, scope)
    require(not aliases, 'segmented spatial successors cannot contain mesh aliases')
    owner = state.indexed_record() if hasattr(state, 'indexed_record') else None
    saved = owner.value if owner is not None else state
    require(isinstance(saved, dict) and type(saved.get('thermal_mesh')) is CompactMesh,
            'segmented spatial publication requires its compact mesh')
    mesh = saved['thermal_mesh']
    # V3 mesh publication verifies an existing immutable reference or persists
    # only columns owned here; partition-owned supports stay external.
    mesh_ref = Y.persist_mesh(store, mesh, source_producer, budget=budget, cancel=cancel,
                              scope=scope, support_source=support_source)
    rows = {'state': {k: v for k, v in saved.items() if k != 'thermal_mesh'}}
    borrowed = []
    if exchange is not None:
        if isinstance(exchange, RecordRef):
            body = exchange.without(('spatial_graph', 'transport', 'joined_heat'))
            graph, transport, heat = (exchange.field(k) for k in ('spatial_graph', 'transport', 'joined_heat'))
            borrowed.extend((body, graph, transport, heat))
        else:
            require(type(exchange) is dict, 'actual exchange record required')
            body = {k: v for k, v in exchange.items() if k not in ('spatial_graph', 'transport', 'joined_heat')}
            graph, transport, heat = (exchange[k] for k in ('spatial_graph', 'transport', 'joined_heat'))
        rows.update(exchange=body, graph=graph, transport=transport, heat=heat)
    refs = publish_records(store, rows, budget=budget, source_producer=source_producer,
                           scope=scope, cancel=cancel)
    a, b = headers(saved, exchange, refs, mesh_reference=mesh_ref)
    for child in borrowed:
        child.close()
    yield a, b, {}


@contextmanager
def restore_records(cls, state_header, exchange_header, arrays, budget, *, store,
                    scope=None, support_source=None):
    import spatial_workflow_patch as Y
    from compact_store import CompactMeshStoreV3
    scope = _scope(store, budget, scope)
    require(type(arrays) is dict and not arrays, 'compact spatial operands are reference-only')
    expected = state_header['compact_mesh']
    Y.verify_reference(store, expected, budget=budget)
    require(expected['schema'] == 'atlas.compact-mesh-store.v3', 'segmented spatial state requires v3 mesh')
    mesh = CompactMeshStoreV3(store, scope=scope, support_source=support_source).open(
        SegmentRef.from_wire(expected['segment']), expected_geometry_id=expected['geometry_id'])
    refs = dict(state_header['record_blobs'])
    require(set(refs) == {'state'}, 'compact state record inventory differs')
    if exchange_header is not None:
        other = exchange_header['record_blobs']
        require(set(other) == {'exchange', 'graph', 'transport', 'heat'}, 'compact exchange record inventory differs')
        refs.update(other)
    with open_records(store, refs, budget=budget, scope=scope,
                      source_producer=expected.get('source_producer')) as opened:
        state_ref = opened['state']
        selected = state_ref.without(('cells',))
        metadata = selected.export(max_logical_bytes=SMALL_LOGICAL_BYTES,
                                   max_owned_bytes=SMALL_LOGICAL_BYTES)
        selected.close()
        cells = state_ref.field('cells')
        require(cells.kind == 'array', 'state cells must be a compact row array')
        state = _OwnedDict(dict(metadata.value, cells=cells, thermal_mesh=mesh), [metadata])
        exchange = None
        if exchange_header is not None:
            exchange = LogicalExchange.from_records(opened['exchange'],
                spatial_graph=opened['graph'], transport=opened['transport'], joined_heat=opened['heat'])
        require(headers(state, exchange, refs, mesh_reference=expected) == (state_header, exchange_header),
                'compact spatial lineage differs from full logical state')
        yield state, exchange
        if exchange is not None:
            exchange.close()
        # The caller must have completed native state adoption before releasing
        # this context; owned metadata remains charged if deliberately retained.


@contextmanager
def certification_payload(cls, solution, budget, *, store, source_producer, cancel=None):
    from atlas_tectonics.integration_regional_inventory import _width
    cls._certification_required(True, solution)
    require(solution._resource is budget, 'certification must share publication budget')
    force = solution.proposal.force_exchange
    width = len(solution._json)+len(solution.proposal._json)+_width(solution.proposal._owner._definition)+force.nbytes
    # Keep the native descriptor-decode reservation; compact persistence alone
    # does not remove the producer's separately owned Python dictionaries.
    with budget.reserve(65536+10*width, category='differential-certification-encode'):
        records = cls._certification_records(solution)
        ref = publish_records(store, {'certification': records}, budget=budget,
                              source_producer=source_producer, cancel=cancel)['certification']
        arrays = {'certification-force:'+k: force.array(k) for k in force.array_names}
        yield cls._certification_header(records, ref), arrays


def restore_certification(cls, header, arrays, budget, *, store, graph, interval, expected,
                          source_audit, cancel=None, source_producer=None):
    from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot
    require(type(header) is dict and type(arrays) is dict and arrays and
            all(k.startswith('certification-force:') for k in arrays),
            'complete compact certification operands required')
    fields = {k.removeprefix('certification-force:'): v for k, v in arrays.items()}
    require(all(type(a) is np.ndarray and a.dtype == np.dtype('float64') for a in fields.values()),
            'actual saved differential force fields are missing or malformed')
    ref = header['record_blob']
    with export_record(store, ref, 'certification', budget=budget, cancel=cancel,
                       source_producer=source_producer) as records:
        require(type(records) is dict and set(records) == {'solution', 'proposal', 'iteration', 'force', 'bindings'},
                'saved differential certification record set differs')
        with budget.reserve(65536+3*sum(a.nbytes for a in fields.values()),
                            category='compact-certification-force'):
            force = RegionalMechanicalSnapshot(records['force'], fields)
            cls._check_certification_records(records, force, graph, interval, expected, source_audit)
            require(cls._certification_header(records, ref) == header,
                    'saved certification header differs from complete accepted evidence')


@contextmanager
def differential_payload(interval, budget, *, store, source_producer, cancel=None):
    from atlas_tectonics.integration_differential_geometry import DifferentialInterval
    require(type(interval) is DifferentialInterval and interval._resource is budget,
            'actual shared-budget differential interval required')
    network = interval.endpoint_network
    with budget.reserve(65536+8*len(interval._json)+8*network.nbytes,
                        category='differential-workflow-encode'):
        record = dict(interval=interval.descriptor(), endpoint_network=network.descriptor())
        ref = publish_records(store, {'differential': record}, budget=budget,
                              source_producer=source_producer, cancel=cancel)['differential']
        header = {k: record['interval'][k] for k in DIFFERENTIAL_NAMES}
        header['record_blob'] = ref
        yield header, {'differential-network:'+k: v for k, v in network.arrays().items()}


def restore_differential(header, arrays, budget, *, store, cancel=None, source_producer=None):
    from atlas_tectonics.integration_differential_geometry import DifferentialInterval
    from atlas_tectonics import integration_sphere as S
    require(type(header) is dict and type(arrays) is dict and
            all(k.startswith('differential-network:') for k in arrays),
            'complete compact differential operands required')
    ref = header['record_blob']
    with export_record(store, ref, 'differential', budget=budget, cancel=cancel,
                       source_producer=source_producer) as record:
        require(type(record) is dict and set(record) == {'interval', 'endpoint_network'},
                'saved differential geometry record changed')
        fields = {k.removeprefix('differential-network:'): v for k, v in arrays.items()}
        network = S.restore_network(record['endpoint_network'], fields, budget=budget)
        require(set(fields) == set(network.arrays()), 'saved differential endpoint has unowned fields')
        interval = DifferentialInterval.restore(record['interval'], network, budget=budget)
        expected = {k: record['interval'][k] for k in DIFFERENTIAL_NAMES}
        require(header == dict(expected, record_blob=ref), 'saved differential lineage differs from actual geometry')
        return interval


def verify_publication_references(store, row, *, budget, scope=None, cancel=None, source_producer=None):
    """Called inside the existing publication transaction, before head commit."""
    if getattr(store, 'scope', None) is None:
        return
    if source_producer is None:
        source_producer = row.get('exterior_state', {}).get('compact_mesh', {}).get('source_producer')
    for header_name, kinds in (('exterior_state', {'state', 'mesh'}),
            ('exterior_advance', {'exchange', 'graph', 'transport', 'heat'})):
        header = row.get(header_name)
        if header is None:
            continue
        refs = header.get('record_blobs', {})
        expected = kinds - ({'mesh'} if 'compact_mesh' in header else set())
        require(set(refs) == expected, 'complete spatial publication record set required')
        verify_records(store, refs, budget=budget, scope=scope, cancel=cancel, source_producer=source_producer)
        if 'compact_mesh' in header:
            from spatial_workflow_patch import verify_reference
            verify_reference(store, header['compact_mesh'], budget=budget)
    for header_name, kind in (('differential_certification', 'certification'),
                              ('differential_geometry', 'differential')):
        if header_name in row:
            verify_records(store, {kind: row[header_name]['record_blob']},
                           budget=budget, scope=scope, cancel=cancel, source_producer=source_producer)


def publication_check(check, store, row, *, budget, cancel=None, source_producer=None):
    def checked():
        check()
        verify_publication_references(store, row, budget=budget, cancel=cancel, source_producer=source_producer)
    return checked


def advance_header(advance):
    if hasattr(advance, 'header'):
        owner = advance.header(fields=EXCHANGE_NAMES)
        return _OwnedDict(owner.value, [owner])
    return advance.record()


@contextmanager
def advance_record(advance):
    record = advance.record()
    yield record
    if isinstance(record, RecordRef):
        record.close()


def _replace(source, old, new):
    require(source.count(old) == 1, 'record source seam missing or ambiguous: '+old[:100])
    return source.replace(old, new, 1)


def transform(source):
    """Apply after existing spatial/partition transforms; frozen sources stay intact."""
    require(type(source) is str and 'import spatial_records_patch as _COMPACT_RECORDS' not in source,
            'record transform requires unapplied source')
    source = _replace(source, 'import json\n', 'import json\nimport spatial_records_patch as _COMPACT_RECORDS\n')
    changes = (
        ('    def _certification_payload(cls, solution, budget):\n',
         '    def _certification_payload(cls, solution, budget, *, store=None, source_producer=None, cancel=None):\n'
         "        if getattr(store, 'scope', None) is not None:\n"
         '            with _COMPACT_RECORDS.certification_payload(cls, solution, budget, store=store,\n'
         '                    source_producer=source_producer, cancel=cancel) as result:\n'
         '                yield result\n            return\n'),
        ('    def _restore_certification(cls, header, arrays, budget, *, graph, interval, expected, source_audit):\n',
         '    def _restore_certification(cls, header, arrays, budget, *, graph, interval, expected, source_audit, store=None, source_producer=None):\n'
         "        if 'compact' in header.get('record_blob', {}):\n"
         '            return _COMPACT_RECORDS.restore_certification(cls, header, arrays, budget, store=store,\n'
         '                graph=graph, interval=interval, expected=expected, source_audit=source_audit, source_producer=source_producer)\n'),
        ('    def _differential_payload(interval, budget):\n',
         '    def _differential_payload(interval, budget, *, store=None, source_producer=None, cancel=None):\n'
         "        if getattr(store, 'scope', None) is not None:\n"
         '            with _COMPACT_RECORDS.differential_payload(interval, budget, store=store,\n'
         '                    source_producer=source_producer, cancel=cancel) as result:\n'
         '                yield result\n            return\n'),
        ('    def _restore_differential(header, arrays, budget):\n',
         '    def _restore_differential(header, arrays, budget, *, store=None, source_producer=None):\n'
         "        if 'compact' in header.get('record_blob', {}):\n"
         '            return _COMPACT_RECORDS.restore_differential(header, arrays, budget, store=store, source_producer=source_producer)\n'),
        ('                        differential_solution, self._budget))',
         '                        differential_solution, self._budget, store=self._store,\n'
         '                        source_producer=_COMPACT_SPATIAL.producer(self._collar), cancel=cancel))'),
        ('self._differential_payload(differential_interval, self._budget))',
         'self._differential_payload(differential_interval, self._budget, store=self._store,\n'
         '                        source_producer=_COMPACT_SPATIAL.producer(self._collar), cancel=cancel))'),
        ('                                                                               geometry_arrays, self._budget)',
         '                                                                               geometry_arrays, self._budget, store=self._store,\n'
         '                                source_producer=_COMPACT_SPATIAL.producer(self._collar))'),
        ('                                source_audit=source_audit.descriptor())',
         '                                source_audit=source_audit.descriptor(), store=self._store,\n'
         '                                source_producer=_COMPACT_SPATIAL.producer(self._collar))'),
        ("                    exterior_advance.record()['spatial_graph_id'] != differential_solution.graph.geometry_id):",
         "                    _COMPACT_RECORDS.advance_header(exterior_advance)['spatial_graph_id'] != differential_solution.graph.geometry_id):"),
        ('            row.update(exterior_state=_COMPACT_SPATIAL.state_record(exterior_advance.state), exterior_advance=exterior_advance.record())',
         '            row.update(exterior_state=_COMPACT_SPATIAL.state_record(exterior_advance.state),\n'
         '                       exterior_advance=_COMPACT_RECORDS.advance_header(exterior_advance))'),
        ("row['exterior_state'], row['exterior_advance'], self._budget, store=self._store, source_producer=_COMPACT_SPATIAL.producer(self._collar), cancel=cancel))",
         "row['exterior_state'], scratch.enter_context(_COMPACT_RECORDS.advance_record(exterior_advance)),\n"
         '                    self._budget, store=self._store, source_producer=_COMPACT_SPATIAL.producer(self._collar), cancel=cancel))'),
        ("                self._store.put(row['key'], dict(payload, **blobs), row, publication_check=check,",
         "                self._store.put(row['key'], dict(payload, **blobs), row, publication_check=\n"
         '                                _COMPACT_RECORDS.publication_check(check, self._store, row, budget=self._budget, cancel=cancel,\n'
         '                                source_producer=_COMPACT_SPATIAL.producer(self._collar)),'),
    )
    for old, new in changes:
        source = _replace(source, old, new)
    return source
