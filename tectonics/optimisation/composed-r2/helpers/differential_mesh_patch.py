"""Fresh mesh v3 packaging seam; the native scientific computation is unchanged."""
from hashlib import sha256

from mesh_tables import CompactMesh, _Allocation, _width, pack_mesh, require


def produce(record, *, budget, context):
    """Publish from the native builder's rows, retaining no complete mesh JSON."""
    from compact_store import CompactMeshStoreV3
    require(type(context) is dict and set(context) == {'resolver', 'support_source', 'producer'},
            'fresh mesh v3 requires explicit resolver, support source and producer')
    from support_source import SupportSource
    source, resolver = context['support_source'], context['resolver']
    require(type(source) is SupportSource and source.scope is getattr(resolver, 'scope', None)
            and source.scope.run_budget is budget,
            'fresh mesh v3 context has foreign scope or run budget')
    static_size = sum(_width(value) for name, table in record['support_tables'].items()
                      if name != 'differential_supports' for value in table.values())
    static_owner = _Allocation(budget, static_size+65536)
    static = {}
    differential = set(record['support_tables'].get('differential_supports', {}))
    def write(content, raw):
        if content in differential:
            identity = source.identity(content)
            require(identity.sha256 == content and identity.canonical_bytes == len(raw),
                    'fresh support differs from partition-owned source')
        else:
            require(content not in static or static[content] == raw, 'static support hash collision')
            static[content] = raw
    def read(content, size):
        if content in static:
            return static[content]
        raw = bytearray()
        with source.iter_json(content, max_chunk_bytes=65536) as stream:
            for held in stream:
                with held:
                    raw.extend(held.value)
        require(len(raw) == size and sha256(raw).hexdigest() == content,
                'fresh shared support bytes differ')
        return bytes(raw)
    metadata, arrays = pack_mesh(record, support_writer=write, budget=budget)
    # The produced view lives in the partition's scope and holds the partition as
    # a dependency, so it can stay bound to its own publication (16 Oct 2026,
    # audit A2): no reopen of the unsealed candidate, as live_mesh_patch.finish.
    view = CompactMesh(metadata, arrays, support_reader=read,
                       expected_geometry_id=metadata['geometry_id'], budget=budget,
                       scope=source.scope, dependencies=(source._owner,))
    adapter = CompactMeshStoreV3(resolver, scope=source.scope, support_source=source)
    ref = adapter.publish(view, producer=context['producer'])
    from live_mesh_patch import _published
    result = _published(context, source.scope, view, ref)
    _ = static_owner
    from atlas_tectonics.integration_exterior_mesh import ExteriorMesh
    return ExteriorMesh.from_compact(result, budget=budget)


def transform(source):
    """Exact bounded packaging anchors only; no source writes or kernel edits."""
    signature = 'thermal_subdivisions=1, max_witness_refinements=0, closed_graph=None):'
    start = '        encoded = _encode_mesh_record(record)\n'
    tail = '''        lease = budget.reserve(8192+4*len(encoded), category='differential-thermal-mesh-retained')
        lease.__enter__()
        try:
            result = object.__new__(E.ExteriorMesh)
            object.__setattr__(result, '_json', encoded); object.__setattr__(result, '_resource', budget)
            weakref.finalize(result, lease.__exit__, None, None, None)
            return result
        except BaseException:
            lease.__exit__(None, None, None)
            raise
'''
    require(type(source) is str and source.count(signature) == 1 and source.count(start+tail) == 1,
            'fresh differential mesh packaging seam is missing or ambiguous')
    source = source.replace(signature,
        'thermal_subdivisions=1, max_witness_refinements=0, closed_graph=None, compact_context=None):', 1)
    return source.replace(start+tail,
        '        from differential_mesh_patch import produce\n'
        '        return produce(record, budget=budget, context=compact_context)\n', 1)
