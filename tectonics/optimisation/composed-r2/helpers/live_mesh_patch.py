"""Explicit compact producer lifetimes; exact native geometry stays unchanged.

Apply after exterior_mesh_patch / differential_mesh_patch. A compact context
contains the actual shared ``scope``. Existing persisted differential contexts
continue to name ``resolver``, ``support_source`` and ``producer`` explicitly.
No context selects the original native producer and its native JSON result.
"""
from __future__ import annotations

import ast
from hashlib import sha256
import json
import sys
import traceback

import numpy as np

import mesh_tables as M


SharedSupportRecord = M.SharedSupportRecord
# Step 8 early releases in the compact record bodies: dead chart, pose, cache
# and index structures end at their last use, and assembly drops each
# candidate polygon once it has been consumed. Lifetimes only. Test-only
# switch for same-source before/after measurement (mesh production is not a
# heat-issuer dependency, so its identity guard does not capture it).
EARLY_RELEASE = True


def drain(candidates):
    """Yield candidates in their original order, dropping each from the list
    as it is consumed; _assemble iterates its candidates exactly once."""
    candidates.reverse()
    while candidates:
        yield candidates.pop()


def support_table(supports):
    from partition_native_patch import _Supports
    if type(supports) is _Supports:
        return {supports.view.support_id(i): SharedSupportRecord(supports.view, supports.view.support_id(i))
                for i in range(len(supports))}
    return {support.support_id: support for support in supports}


def support_sequence(supports, budget):
    """Accept only the actual native tuple or the validated compact sequence."""
    from partition_native_patch import _Supports
    from partition_v2 import PartitionV2
    return type(supports) is tuple or (type(supports) is _Supports and
        type(supports.view) is PartitionV2 and supports.view._sealed and
        supports.view.scope.run_budget is budget)


def _record_bytes(value, depth=0):
    """Conservative object retention, counting shared values repeatedly.

    This includes list capacity, dict tables, strings and scalar objects before
    the geometry arena releases them. Native support handles own their payload;
    compact support references retain their already-paid partition separately.
    """
    M.require(depth <= 128, 'fresh mesh record nesting exceeds bound')
    size = sys.getsizeof(value)
    if type(value) is dict:
        return size+sum(_record_bytes(k, depth+1)+_record_bytes(v, depth+1) for k, v in value.items())
    if type(value) is list:
        return size+sum(_record_bytes(v, depth+1) for v in value)
    if type(value) in (str, int, float, bool, type(None), SharedSupportRecord):
        return size
    from atlas_tectonics.integration_differential_geometry import DifferentialSupport
    M.require(type(value) is DifferentialSupport, 'unsupported fresh mesh record value')
    return size


def own_record(record, budget):
    # Both references travel together, including through exception tracebacks.
    return M.OwnedRow(record, M._Allocation(budget, 65536+_record_bytes(record)))


def _scope(context, budget):
    from content_cache import RetainedScope
    M.require(type(context) is dict and set(context) in (
        {'scope'}, {'resolver', 'support_source', 'producer'}),
        'explicit shared compact mesh context required')
    scope = context.get('scope') if 'scope' in context else context['resolver'].scope
    M.require(type(scope) is RetainedScope and scope.run_budget is budget,
              'fresh mesh context has foreign scope or run budget')
    if 'support_source' in context:
        from support_source import SupportSource
        M.require(type(context['support_source']) is SupportSource and context['support_source'].scope is scope,
                  'fresh mesh support source has foreign retained scope')
    return scope


def _pack(held, *, budget, scope, source=None):
    """Return paid columns and support reader after the input frame has gone."""
    from content_cache import ChargeSpec
    record = held.value
    shared = record['support_tables'].get('differential_supports', {})
    references = ({ident: SharedSupportRecord(source, ident) for ident in shared} if source is not None else
                  {ident: row for ident, row in shared.items() if type(row) is SharedSupportRecord})
    static_size = sum(M._support_width(table, value) for table, rows in record['support_tables'].items()
                      for ident, value in rows.items() if not (table == 'differential_supports' and ident in references))
    static_owner = scope.reserve(ChargeSpec('mesh-static-supports', static_size+65536+256*len(references))).commit({})
    static = static_owner.value
    def write(content, raw):
        if content in references:
            parent = references[content].view
            found = parent.identity(content) if parent is source else parent.support_identity(content)
            M.require(found.sha256 == content and found.canonical_bytes == len(raw),
                      'fresh support differs from compact partition')
        else:
            M.require(content not in static or static[content] == raw, 'static support hash collision')
            static[content] = raw
    dependencies = [static_owner]
    # Dependencies, rather than ambient strong references, make parent close
    # refuse while this mesh or a borrowed mesh row still needs the partition.
    seen = set()
    for row in references.values():
        M.require(row.view.scope is scope, 'fresh mesh support has foreign retained scope')
        if id(row.view) not in seen:
            seen.add(id(row.view))
            dependencies.extend((source._owner,) if row.view is source else (row.view.record._owner, row.view._index))
    def read(content, size):
        if content in static:
            return static[content]
        row = references[content]
        ref = row.view.ref_for(content) if row.view is source else row.view.support_by_id(content)
        try:
            raw, offset = bytearray(size), 0
            with ref.iter_json(max_chunk_bytes=65536) as stream:
                for part in stream:
                    with part:
                        stop = offset+len(part.value)
                        M.require(stop <= size, 'fresh shared support exceeds admitted size')
                        raw[offset:stop] = part.value
                        offset = stop
            M.require(offset == size and sha256(raw).hexdigest() == content,
                      'fresh shared support bytes differ')
            return bytes(raw)
        finally:
            ref.close()
    metadata, arrays, owner = M.pack_mesh(record, support_writer=write, budget=budget, _defer_freeze=True)
    return metadata, arrays, owner, read, tuple(dependencies)


def _expected_root(view, source):
    """The v3 root CompactMeshStoreV3.publish derives from this produced view.

    Same derivation as publish: codec from the view metadata, support IDs and
    an oversized header moved to columns, and the static support table in
    original order. In-memory hashing only; nothing is read from the store.
    """
    from compact_store import HEADER_COLUMN, V3_HEADER_SCHEMA, V3_SCHEMA
    def described(raw, dtype, shape):
        return {'dtype': dtype, 'shape': list(shape), 'sha256': sha256(raw).hexdigest()}
    codec = json.loads(view._metadata)
    support_ids = codec['header'].pop('support_ids', None)
    arrays = dict(view._arrays)
    columns = {name: row for name, row in codec['arrays'].items() if name not in ('s.blob', 's.size')}
    rows, digest, end = [], sha256(), 0
    for index in range(len(arrays['s.id'])):
        if M.TABLES[int(arrays['s.table'][index])] == 'differential_supports':
            continue
        ident, size = view.ident(int(arrays['s.blob'][index])), int(arrays['s.size'][index])
        raw = view._reader(ident, size)
        M.require(type(raw) is bytes and len(raw) == size and sha256(raw).hexdigest() == ident,
                  'produced static support bytes differ')
        rows.append((index, int(arrays['s.blob'][index]), size, end))
        digest.update(raw)
        end += size
        del raw
    index_rows = np.array(rows, dtype='<u8').reshape(-1, 4)
    columns['static.index'] = described(index_rows.tobytes(), index_rows.dtype.str, index_rows.shape)
    columns['static.bytes'] = {'dtype': '|u1', 'shape': [end], 'sha256': digest.hexdigest()}
    if support_ids is not None:
        raw = b''.join(bytes.fromhex(value) for value in support_ids)
        columns['header.support_ids'] = described(raw, '|u1', (len(support_ids), 32))
    header = M.canonical(codec['header'])
    binding, ids = source.binding.to_wire(), support_ids is not None
    inline = {'schema': V3_SCHEMA, 'codec': codec, 'support_source': binding,
              'header_support_ids': ids, 'arrays': columns}
    moved = {'schema': V3_HEADER_SCHEMA, 'codec': {k: v for k, v in codec.items() if k != 'header'},
             'support_source': binding, 'header_support_ids': ids,
             'arrays': {**columns, HEADER_COLUMN: described(header, '|u1', (len(header),))}}
    return inline, moved


def _published(context, scope, view, ref):
    """Keep the produced view, bound to the v3 root just published from it.

    R2 principle: the in-memory object stays bound to the identity it produced.
    Only the segment root is read here, and it must describe exactly this view.
    The stored column bytes are hashed by bounded_preseal before the seal and
    the complete mesh is validated by the fresh reader (Step 9(a)); the former
    reopen validated it per scalar on the unsealed candidate (more than 24 min
    for the authentic IV1 mesh, profile r5, 16 Oct 2026).
    """
    from content_cache import ChargeSpec
    from segment_store import SegmentBackend, parse
    source = context['support_source']
    # Owner convention: a refusal leaves the segment and its root borrow to the
    # failed frame, which retires them; closing here would mask the refusal
    # with the segment's own live-borrow refusal.
    segment = SegmentBackend().open(context['resolver'], ref, scope=scope)
    M.require(segment.info.ref.to_wire() == ref.to_wire(), 'published mesh reference differs')
    with segment.metadata() as held:
        # The parsed root, plus the expected root derived from the view's
        # own metadata: its decode and the canonical header bytes.
        size = M._decode_charge(held.value)+M._decode_charge(view._metadata)+len(view._metadata)+65536
        with scope.reserve(ChargeSpec('mesh-root-binding', size)):
            root = parse(held.value)
            M.require(root in _expected_root(view, source),
                      'published mesh root differs from the produced mesh')
            del root
    return M.bind_published(view, segment, source, check=view._check)


def finish(held, *, budget, context):
    """Release input rows before validating the single frozen column copy."""
    scope = _scope(context, budget)
    metadata, arrays, owner, reader, dependencies = _pack(held, budget=budget, scope=scope,
                                                       source=context.get('support_source'))
    del held
    view = M.CompactMesh(metadata, arrays, support_reader=reader,
        expected_geometry_id=metadata['geometry_id'], budget=budget, scope=scope, dependencies=dependencies)
    del arrays, owner, metadata, reader, dependencies
    if 'resolver' in context:
        from compact_store import CompactMeshStoreV3
        adapter = CompactMeshStoreV3(context['resolver'], scope=scope, support_source=context['support_source'])
        ref = adapter.publish(view, producer=context['producer'])
        view = _published(context, scope, view, ref)
    from atlas_tectonics.integration_exterior_mesh import ExteriorMesh
    return ExteriorMesh.from_compact(view, budget=budget)


def build(builder, args, kwargs, context):
    budget = kwargs['budget']
    scope = _scope(context, budget)
    supports = args[2] if len(args) == 3 and builder.__name__.endswith('differential_mesh_record') else None
    if supports is not None:
        from partition_native_patch import _Supports
        if type(supports) is _Supports:
            M.require(supports.view.scope is scope, 'mesh construction has foreign partition scope')
    try:
        # Passing the returned wrapper directly avoids retaining the complete
        # input in this public frame while finish freezes the compact columns.
        return finish(builder(*args, **kwargs), budget=budget, context=context)
    except BaseException as error:
        # Preserve exception class/message and stack positions. Inactive build
        # frames must not retain geometry after their arena has been released.
        traceback.clear_frames(error.__traceback__)
        raise


def _function(source, name):
    nodes = [node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == name]
    M.require(len(nodes) == 1, 'mesh producer seam is missing or ambiguous')
    node = nodes[0]
    return ''.join(source.splitlines(keepends=True)[node.lineno-1:node.end_lineno])


def _replace(source, old, new):
    M.require(source.count(old) == 1, 'live mesh source anchor is missing or ambiguous')
    return source.replace(old, new, 1)


def transform_exterior(source, *, _releases=True):
    """After exterior_mesh_patch: retain native fallback, add explicit seam."""
    body = _function(source, 'build_exterior_mesh')
    start = "        encoded = json.dumps(result_record, sort_keys=True, separators=(',', ':')).encode()\n"
    M.require(body.count(start) == 1 and body.endswith('            raise\n'), 'ordinary mesh output seam differs')
    record_body = body[:body.index(start)]+'        from live_mesh_patch import own_record\n        return own_record(result_record, budget)\n'
    record_body = _replace(record_body, 'def build_exterior_mesh(', 'def _build_exterior_mesh_record(')
    record_body = _replace(record_body, '        cells, faces = _assemble(candidates, arena)\n',
        '        cells, faces = _assemble(candidates, arena)\n        del candidates\n')
    if _releases:
        record_body = _replace(record_body,
            "            raise V.VolumeError('declared spatial grid exceeds the predeclared physical geometry volume-error budget')\n",
            "            raise V.VolumeError('declared spatial grid exceeds the predeclared physical geometry volume-error budget')\n"
            '        import live_mesh_patch as _LIVE_MESH\n'
            '        if _LIVE_MESH.EARLY_RELEASE:\n'
            '            # Charts, poses, layers and collar cells end with the candidate loop.\n'
            '            del charts, posed, geometry, bands, collar_cells, prior, omega, time\n')
        record_body = _replace(record_body, '        cells, faces = _assemble(candidates, arena)\n',
            '        cells, faces = _assemble(_LIVE_MESH.drain(candidates) if _LIVE_MESH.EARLY_RELEASE else candidates, arena)\n')
        record_body = _replace(record_body,
            "            raise V.VolumeError('thermal exterior does not cover every actual active-grid boundary face')\n",
            "            raise V.VolumeError('thermal exterior does not cover every actual active-grid boundary face')\n"
            '        if _LIVE_MESH.EARLY_RELEASE:\n'
            '            del box_by_cell, radial_by_cell, by_cell\n')
    wrapper = '''
_build_exterior_mesh_native = build_exterior_mesh

def build_exterior_mesh(funding, sphere, wall_measures, *, grid_lines,
                        max_geometry_volume_error_m3, max_leaves, budget, endpoint='end', compact_context=None):
    if compact_context is None:
        return _build_exterior_mesh_native(funding, sphere, wall_measures, grid_lines=grid_lines,
            max_geometry_volume_error_m3=max_geometry_volume_error_m3, max_leaves=max_leaves,
            budget=budget, endpoint=endpoint)
    from live_mesh_patch import build
    return build(_build_exterior_mesh_record, (funding, sphere, wall_measures), dict(grid_lines=grid_lines,
        max_geometry_volume_error_m3=max_geometry_volume_error_m3, max_leaves=max_leaves,
        budget=budget, endpoint=endpoint), compact_context)
'''
    return source+'\n\n'+record_body+'\n'+wrapper


def transform_differential(source, *, _releases=True):
    """After differential_mesh_patch; only new compact branch drops scratch."""
    body = _function(source, 'build_differential_mesh')
    tail = ('        from differential_mesh_patch import produce\n'
            '        return produce(record, budget=budget, context=compact_context)\n')
    record_body = _replace(body, tail,
        '        from live_mesh_patch import own_record\n        return own_record(record, budget)\n')
    record_body = _replace(record_body, 'def build_differential_mesh(', 'def _build_differential_mesh_record(')
    record_body = _replace(record_body, "    static = type(bounds) is D.DifferentialInitialBounds\n",
        '    from live_mesh_patch import support_sequence, support_table\n'
        "    static = type(bounds) is D.DifferentialInitialBounds\n")
    record_body = _replace(record_body, 'type(supports) is not tuple', 'not support_sequence(supports, budget)')
    record_body = _replace(record_body, 'differential_supports={ids[at]: s for at, s in enumerate(supports)}',
                           'differential_supports=support_table(supports)')
    record_body = _replace(record_body, '        cells, faces = E._assemble(candidates, arena)\n',
        '        cells, faces = E._assemble(candidates, arena)\n        del candidates\n')
    if _releases:
        record_body = _replace(record_body, '        # The same exact total as one running sum; see _carry.\n',
            '        import live_mesh_patch as _LIVE_MESH\n'
            '        if _LIVE_MESH.EARLY_RELEASE:\n'
            '            # Cache, bounds rows, collar rows and component IDs end with the support loop.\n'
            '            del measures, bounded, native, component_ids\n'
            '        # The same exact total as one running sum; see _carry.\n')
        record_body = _replace(record_body, '        cells, faces = E._assemble(candidates, arena)\n',
            '        cells, faces = E._assemble(_LIVE_MESH.drain(candidates) if _LIVE_MESH.EARLY_RELEASE else candidates, arena)\n')
        record_body = _replace(record_body, "        history = b['trajectory']['segments']\n",
            '        if _LIVE_MESH.EARLY_RELEASE:\n'
            '            # Assembly and boundary indexes end before packaging.\n'
            '            del boxes, radials, groups, by_cell, native_boxes\n'
            "        history = b['trajectory']['segments']\n")
    # Reconstruct the original packaging for a genuinely native no-context call.
    native_tail = '''        encoded = _encode_mesh_record(record)
        lease = budget.reserve(8192+4*len(encoded), category='differential-thermal-mesh-retained')
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
    native = _replace(body, tail, native_tail)
    native = _replace(native, 'def build_differential_mesh(', 'def _build_differential_mesh_native(')
    wrapper = '''
def build_differential_mesh(funding, bounds, supports, *, endpoint,
                            max_geometry_volume_error_m3, max_leaves, budget,
                            thermal_subdivisions=1, max_witness_refinements=0, closed_graph=None, compact_context=None):
    kwargs = dict(endpoint=endpoint, max_geometry_volume_error_m3=max_geometry_volume_error_m3,
        max_leaves=max_leaves, budget=budget, thermal_subdivisions=thermal_subdivisions,
        max_witness_refinements=max_witness_refinements, closed_graph=closed_graph)
    if compact_context is None:
        return _build_differential_mesh_native(funding, bounds, supports, **kwargs)
    from live_mesh_patch import build
    return build(_build_differential_mesh_record, (funding, bounds, supports), kwargs, compact_context)
'''
    return _replace(source, body, native+'\n\n'+record_body+'\n'+wrapper)
