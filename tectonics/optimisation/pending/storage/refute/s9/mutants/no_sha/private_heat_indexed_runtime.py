"""Source-bound indexed heat adapters; exact arithmetic and checks are retained.

This is an additive source transformer, not a running-module patch. The actual
issuer still authenticates the owner, transport, execution and fixed numerical
producer. A compact metric reuses the logical identity its CompactMesh streamed
and sealed in this process (S9), or else is rehashed through bounded canonical
streaming; there is no whole legacy record decode in the numerical/projection route.
"""
from hashlib import sha256
from types import MappingProxyType


ISSUER_SHA = 'e42649f848397551da18263322775441f664922538f204c1e47962f97481d3d6'
PROJECTION_SHA = '662f94b04046e83976a763d016bdcfdc83dbf7941ea6a1a2c307e0a61fcb88e6'


def metric_identity(geometry, *, cancel=None):
    """Recompute the SAME logical identity without materialising its encoding."""
    from atlas_tectonics.integration_mimetic_heat import MimeticGeometry
    from mesh_tables import CompactMesh
    import private_heat_issuer_resources_r4 as R
    if type(geometry) is not MimeticGeometry:
        raise TypeError('actual metric required for identity verification')
    R.check(cancel)
    view = getattr(geometry, '_indexed', None)
    if view is None:
        return sha256(geometry._encoded).hexdigest()
    if (type(view) is not CompactMesh or not view._sealed or
            view.budget is not geometry._budget or geometry._encoded is not None):
        raise ValueError('indexed metric lost its authenticated same-budget geometry')
    if view.scope is not None:
        # The v3 cold opener already authenticated exactly one full logical
        # stream. Reuse only that process-local seal, after file/cancel checks.
        identity = view.identity()
        R.check(cancel)
        if identity.sha256 != view.geometry_id:
            raise ValueError('sealed indexed geometry differs from its logical identity')
        return identity.sha256
    sealed = _sealed_unscoped_identity(view, cancel)
    if sealed is not None:
        R.check(cancel)
        return sealed
    digest = sha256()
    for raw in view.iter_legacy_json():
        R.check(cancel)
        digest.update(raw)
    result = digest.hexdigest()
    if result != view.geometry_id:
        raise ValueError('immutable indexed geometry differs from its logical identity')
    return result


def _sealed_unscoped_identity(view, cancel):
    """S9: the identity CompactMesh.__init__ streamed and sealed in THIS process, or None.

    That constructor checked every array sha256, froze the arrays into one funded
    bytes-backed read-only allocation, streamed the whole legacy record against
    geometry_id and sealed the result. A later full stream re-encodes exactly those
    frozen rows, so only its support reads can tell anything new: they re-read every
    support blob through the reader and refuse a changed or missing one. That part
    is kept here exactly (same reads, same length/sha256 check against the frozen
    inventory, same refusal); the row re-encoding is what is skipped. The seal is
    reused only while the arrays are still that one allocation (an unpickled or
    substituted array is not), the reader is a plain blob reader, its support source
    (when it has one) is unchanged, and the seal names this geometry_id. Anything
    else returns None and the caller takes the original full stream.
    """
    import numpy as np
    import mesh_tables as MT
    import private_heat_issuer_resources_r4 as R
    arrays, reader = view._arrays, view._reader
    if (type(arrays) is not MappingProxyType or not arrays or view._segment is not None or
            hasattr(reader, 'iter_json') or hasattr(reader, 'export')):
        return None
    owners = set()
    for array in arrays.values():
        if type(array) is not np.ndarray or array.flags.writeable:
            return None
        # _freeze: frombuffer(_Bytes) then reshape, so the bytes sit one or two views down.
        raw = array.base
        for _ in range(4):
            if type(raw) is not np.ndarray:
                break
            raw = raw.base
        if type(raw) is not MT._Bytes or type(raw.owner) is not MT._Allocation or raw.owner.guard is None:
            return None
        owners.add(id(raw.owner))
    if len(owners) != 1:
        return None
    source = getattr(reader, 'source', None)
    if source is not None:
        check_unchanged = getattr(source, 'check_unchanged', None)
        if not callable(check_unchanged):
            return None
        # As identity()'s segment branch does: a changed support file refuses here.
        check_unchanged()
    identity = view.identity()
    if identity.record_schema != MT.LEGACY or identity.sha256 != view.geometry_id:
        return None
    # The full stream's support reads, kept: mesh_tables.CompactMesh._support_blob's
    # charge, check, read and length/sha256 refusal, without its JSON decode (the
    # canonical-form check is a function of these same verified bytes).
    for index in range(len(arrays['s.id'])):
        size, ident = int(arrays['s.size'][index]), view.ident(int(arrays['s.blob'][index]))
        owner = MT._view_allocation(view, size+65536)
        view._check()
        blob = reader(ident, size)
        MT.require(type(blob) is bytes and len(blob) == size,
                   'support blob length/hash differs')
        del blob, owner
        R.check(cancel)
    return identity.sha256


def ordered_cell_ids(geometry, *, cancel=None):
    """One cell identity at a time, retaining the decoded row while borrowed."""
    import private_heat_issuer_resources_r4 as R
    view = getattr(geometry, '_indexed', None)
    if view is None:
        with R.decoded(geometry._encoded, budget=geometry._budget, cancel=cancel) as owned:
            for row in owned.value['cells']:
                R.check(cancel)
                yield row['cell_id']
    else:
        for index in range(view.cell_count):
            R.check(cancel)
            owned = view.cell(index)
            yield owned.value['cell_id']


class _Cell:
    __slots__ = ('owner',)

    def __init__(self, owner):
        self.owner = owner

    def __getitem__(self, name):
        return self.owner.value[name]

    def get(self, name, default=None):
        return self.owner.value.get(name, default)


class _Cells:
    __slots__ = ('view',)

    def __init__(self, view):
        self.view = view

    def __len__(self):
        return self.view.cell_count

    def __iter__(self):
        for index in range(len(self)):
            yield _Cell(self.view.cell(index))


class _MeshRows:
    __slots__ = ('mesh', 'header', 'cells')

    def __init__(self, mesh):
        self.mesh, self.header = mesh, mesh.header()
        self.cells = _Cells(mesh._compact)

    def __getitem__(self, name):
        if name == 'cells':
            return self.cells
        return self.header.value[name]

    def get(self, name, default=None):
        if name == 'cells':
            return self.cells
        return self.header.value.get(name, default)


def mesh_rows(mesh):
    """Bounded native consumer view, never JSON-persistable disguised dict."""
    from atlas_tectonics.integration_exterior_mesh import ExteriorMesh
    if type(mesh) is not ExteriorMesh:
        raise TypeError('actual native exterior mesh required')
    return _MeshRows(mesh) if mesh.is_compact else mesh.record()


def stored_mesh(mesh):
    """The spatial issuer owns compact persistence and logical-ID validation."""
    return mesh._compact if mesh.is_compact else mesh.record()


def spatial_record(state):
    """Retain compact mesh ownership while exporting only the small state body."""
    from spatial_indexed_patch import logical_record
    return logical_record(state)


def compare_spatial_records(test, state, expected):
    """Exact logical comparison, including every geometry byte, without expansion.

    Compact values, the thermal mesh and compact state cells, are compared by
    their exact canonical byte streams in order. A RecordRef borrow has no value
    equality by design, so ``==`` on two borrows of identical cells is False
    (audit D4(i), 16 Oct 2026); every other field keeps ordinary equality.
    """
    from mesh_tables import CompactMesh
    from record_views import RecordRef
    import native_transfer as N
    import json
    actual = spatial_record(state)

    def compact(value):
        return type(value) is CompactMesh or isinstance(value, RecordRef)
    streamed = sorted(key for key in set(actual) | set(expected)
                      if compact(actual.get(key)) or compact(expected.get(key)))
    if not streamed:
        test.assertEqual(actual, expected)
        return
    scratch = N._Allocation(state._budget, 65536+128*(len(actual)+len(expected)),
                            category='indexed-reopen-state-comparison')
    test.assertEqual(set(actual), set(expected))
    test.assertEqual({k: v for k, v in actual.items() if k not in streamed},
                     {k: v for k, v in expected.items() if k not in streamed})

    def chunks(value):
        if type(value) is CompactMesh:
            yield from value.iter_legacy_json()
        elif isinstance(value, RecordRef):
            with value.iter_json() as stream:
                for held in stream:
                    with held:
                        yield bytes(held.value)
        else:
            for piece in json.JSONEncoder(sort_keys=True, separators=(',', ':'),
                                          allow_nan=False).iterencode(value):
                yield piece.encode()
    # Chunk boundaries need not match (legacy JSON vs compact streams). Compare
    # bounded byte slices in order rather than weakening equality to a hash.
    for key in streamed:
        readers = (iter(chunks(actual[key])), iter(chunks(expected[key])))
        a = b = memoryview(b'')
        while True:
            if not a:
                a = memoryview(next(readers[0], b''))
            if not b:
                b = memoryview(next(readers[1], b''))
            if not a or not b:
                test.assertEqual(bool(a), bool(b), key)
                break
            size = min(len(a), len(b))
            test.assertEqual(a[:size], b[:size], key)
            a, b = a[size:], b[size:]
        del readers, a, b
    _ = scratch


_BIND = '''
def _bind_indexed_owner_call(owner, step, mesh, *, g, t, origin, target,
        target_text, absolute_residual_target, boundary, execution, cancel):
    # Called only after bind_owner_call's actual type/origin/runtime gates and
    # its owned graph/transport extraction. This does not admit supplied data.
    prepared = INDEXED_INPUTS.prepare_indexed_inputs(mesh, g, t,
        graph_id=step.graph.geometry_id, funding_id=owner._funding.funding_id,
        source_stage_id=step.source.result_id, parent_state_id=step.parent.state_id,
        duration_s=step.source.duration_s, component_count=owner._component_count,
        heat_capacity_j_kg_k=owner._collar._native._material.heat_capacity_j_kg_k,
        conductivity_w_m_k=owner._definition['conductivity_w_m_k'],
        boundary=boundary, budget=owner._budget, cancel=cancel)
    descriptor = prepared.descriptor()
    data = descriptor.value
    # Preparation's scratch was released on return. Fund the new plan/list
    # containers separately before constructing them; this frame retains the
    # allocation if an escaping exception keeps any of those objects alive.
    assembly = INDEXED_INPUTS._Allocation(owner._budget,
        65536+256*len(data['cell_ids']), 'indexed-heat-owner-call-assembly')
    arrays = {name: prepared.array(name) for name in
              ('enthalpy_j', 'capacity_j_k', 'source_w')}
    plan = dict(schema='atlas.private.composed-heat-plan.r1', method_id=METHOD,
        geometry_id=prepared.geometry.geometry_id,
        conductivity_w_m_k=[data['conductivity_w_m_k']]*len(arrays['enthalpy_j']),
        absolute_residual_target=_enc(target), absolute_residual_target_decimal=target_text,
        original_target=_target_provenance(absolute_residual_target), boundary=data['boundary'],
        endpoint_face_trace_status=N.A.TRACE_STATUS)
    meta = dict(schema='atlas.private.composed-owner-call.r1', owner_id=owner.owner_id,
        owner_definition_id=_hash(owner._definition),
        heat_capacity_j_kg_k=data['heat_capacity_j_kg_k'],
        state_id=step.result.result_id, source_stage_id=step.source.result_id,
        graph_id=step.graph.geometry_id, thermal_mesh_id=mesh.geometry_id,
        duration_s=float(step.source.duration_s), cell_ids=data['cell_ids'],
        source_policy='already-booked-transport; zero added heat source',
        native_origin_signature=origin)
    out = _make_call(meta, arrays, prepared.geometry, execution, plan,
                     (owner, step, mesh, step.result._snapshot))
    _verify_call(out, cancel)
    del meta, plan, arrays, data, descriptor, prepared
    del assembly
    return out

'''


def _replace(source, old, new):
    if source.count(old) != 1:
        raise ValueError('indexed heat source seam missing or ambiguous: '+old[:80])
    return source.replace(old, new, 1)


def _check(source, expected):
    if type(source) is not str or sha256(source.encode()).hexdigest() != expected:
        raise ValueError('indexed heat source differs from exact reviewed predecessor')


def issuer_source(source):
    _check(source, ISSUER_SHA)
    source = _replace(source, 'import private_heat_native_projection_r4 as N\n',
        'import private_heat_native_projection_r4 as N\n'
        'import private_heat_indexed_runtime as INDEXED\n'
        'import private_heat_mesh_patch as INDEXED_INPUTS\n'
        'import mesh_tables as INDEXED_TABLES\n'
        'import exterior_mesh_patch as INDEXED_EXTERIOR\n'
        'import spatial_indexed_patch as INDEXED_SPATIAL\n'
        'import native_transfer as INDEXED_NATIVE_TRANSFER\n'
        'import spatial_transfer as INDEXED_SPATIAL_TRANSFER\n')
    # Include all new runtime helpers in both on-disk and loaded-semantics
    # identities. No path discovery, unbound plugin or fresh call-time repin.
    source = _replace(source,
        'pending, modules = [sys.modules[__name__], N, F, CERT, FUNCTIONS, LOADED_IDENTITY], {}',
        'pending, modules = [sys.modules[__name__], N, F, CERT, FUNCTIONS, LOADED_IDENTITY,\n'
        '                        INDEXED, INDEXED_INPUTS, INDEXED_TABLES, INDEXED_EXTERIOR, INDEXED_SPATIAL,\n'
        '                        INDEXED_NATIVE_TRANSFER, INDEXED_SPATIAL_TRANSFER], {}')
    source = _replace(source, 'def _snapshot_identity(snapshot, budget, cancel=None):\n',
        '''def _snapshot_identity(snapshot, budget, cancel=None):
    _check(cancel)
    if type(snapshot) is INDEXED_SPATIAL.IndexedSpatialSnapshot:
        if snapshot._budget is not budget:
            raise ValueError('indexed snapshot has a foreign resource owner')
        return INDEXED_SPATIAL.snapshot_identity(snapshot)
    return _legacy_snapshot_identity(snapshot, budget, cancel)


def _legacy_snapshot_identity(snapshot, budget, cancel=None):
''')
    marker = "        mv = scope.stack.enter_context(RESOURCES.decoded(mesh._json, budget=owner._budget, cancel=cancel))\n"
    branch = '''        if mesh.is_compact:
            return _bind_indexed_owner_call(owner, step, mesh, g=g, t=t, origin=origin,
                target=target, target_text=target_text, absolute_residual_target=absolute_residual_target,
                boundary=boundary, execution=execution, cancel=cancel)
'''
    source = _replace(source, marker, branch+marker)
    source = _replace(source, 'def _verify_call_record(call, meta, cancel=None):\n',
                      _BIND+'def _verify_call_record(call, meta, cancel=None):\n')
    return _replace(source, 'hashlib.sha256(call._geometry._encoded).hexdigest()',
                    'INDEXED.metric_identity(call._geometry, cancel=cancel)')


def projection_source(source):
    _check(source, PROJECTION_SHA)
    source = _replace(source, 'import private_heat_public_float_r1 as PUBLIC\n',
        'import private_heat_public_float_r1 as PUBLIC\n'
        'import private_heat_indexed_runtime as INDEXED\n')
    start = source.index('        with R.decoded(geometry._encoded, budget=budget, cancel=cancel) as metric_owner:\n')
    end = source.index("        if record['face_ids'] != list(geometry._face_ids):\n", start)
    source = source[:start]+'''        if (record.get('schema') != A.SCHEMA or record.get('private_only') is not True
                or record.get('production_acceptance') is not False
                or record.get('endpoint_face_trace_status') != A.TRACE_STATUS):
            raise ValueError('Expected distinct private integrated-transfer result')
        # This workspace already funds the ordered identity list. Indexed
        # access replaces only the formerly whole-mesh decode/order check.
        if ordered != list(INDEXED.ordered_cell_ids(geometry, cancel=cancel)):
            raise ValueError('Original cell order differs from the actual metric complex')
'''+source[end:]
    return _replace(source, 'hashlib.sha256(geometry._encoded).hexdigest()',
                    'INDEXED.metric_identity(geometry, cancel=cancel)')


def joined_source(source, *, expected_sha256):
    _check(source, expected_sha256)
    source = _replace(source, 'import private_heat_grouped_account_r1 as ACCOUNT\n',
        'import private_heat_grouped_account_r1 as ACCOUNT\n'
        'import private_heat_indexed_runtime as INDEXED\n')
    if source.count('mesh.record()') != 3:
        raise ValueError('joined mesh consumer inventory changed')
    source = source.replace('mesh.record()', 'INDEXED.mesh_rows(mesh)')
    return _replace(source, 'thermal_mesh=metric, cells=sorted(cells, key=lambda r:',
                    'thermal_mesh=INDEXED.stored_mesh(mesh), cells=sorted(cells, key=lambda r:')
