"""Explicit compact producer lifetimes; exact native geometry stays unchanged.

Apply after exterior_mesh_patch / differential_mesh_patch. A compact context
contains the actual shared ``scope``. Existing persisted differential contexts
continue to name ``resolver``, ``support_source`` and ``producer`` explicitly.
No context selects the original native producer and its native JSON result.
"""
from __future__ import annotations

import sys
import traceback
from typing import cast

from atlas_tectonics._private.codecs import mesh_tables as M


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
    from atlas_tectonics._private.integration.geometry.partition_native_patch import _Supports
    if type(supports) is _Supports:
        return {supports.view.support_id(i): SharedSupportRecord(supports.view, supports.view.support_id(i))
                for i in range(len(supports))}
    return {support.support_id: support for support in supports}


def _record_bytes(value, depth=0):
    """Conservative object retention, counting shared values repeatedly.

    This includes list capacity, dict tables, strings and scalar objects before
    the geometry arena releases them. Native support handles own their payload;
    compact support references retain their already-paid partition separately.
    """
    size = sys.getsizeof(value)
    if type(value) is dict:
        return size+sum(_record_bytes(k, depth+1)+_record_bytes(v, depth+1) for k, v in value.items())
    if type(value) is list:
        return size+sum(_record_bytes(v, depth+1) for v in value)
    if type(value) in (str, int, float, bool, type(None), SharedSupportRecord):
        return size
    return size


def own_record(record, budget):
    # Both references travel together, including through exception tracebacks.
    return M.OwnedRow(record, M._Allocation(budget, 65536+_record_bytes(record)))


def _scope(context, budget):
    scope = context.get('scope') if 'scope' in context else context['resolver'].scope
    if 'support_source' in context:
        pass
    return scope


def _pack(held, *, budget, scope, source=None):
    """Return paid columns and support reader after the input frame has gone."""
    from atlas_tectonics._private.codecs.content_cache import ChargeSpec
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
            parent.identity(content) if parent is source else parent.support_identity(content)
        else:
            static[content] = raw
    dependencies = [static_owner]
    # Dependencies, rather than ambient strong references, make parent close
    # refuse while this mesh or a borrowed mesh row still needs the partition.
    seen = set()
    for row in references.values():
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
                        raw[offset:stop] = part.value
                        offset = stop
            return bytes(raw)
        finally:
            ref.close()
    metadata, arrays, owner = cast('tuple[dict, dict, M._Allocation]',
                                   M.pack_mesh(record, support_writer=write, budget=budget, _defer_freeze=True))
    return metadata, arrays, owner, read, tuple(dependencies)


def _published(context, scope, view, ref):
    """Keep the produced view, bound to the v3 root just published from it.

    R2 principle: the in-memory object stays bound to the identity it produced.
    Only the segment root is read here, and it must describe exactly this view.
    The stored column bytes are hashed by bounded_preseal before the seal and
    the complete mesh is validated by the fresh reader (Step 9(a)); the former
    reopen validated it per scalar on the unsealed candidate (more than 24 min
    for the authentic IV1 mesh, profile r5, 16 Oct 2026).
    """
    from atlas_tectonics._private.codecs.content_cache import ChargeSpec
    from atlas_tectonics._private.codecs.segment_store import SegmentBackend, parse
    source = context['support_source']
    # Owner convention: a refusal leaves the segment and its root borrow to the
    # failed frame, which retires them; closing here would mask the refusal
    # with the segment's own live-borrow refusal.
    segment = SegmentBackend().open(context['resolver'], ref, scope=scope)
    with segment.metadata() as held:
        # The parsed root, plus the expected root derived from the view's
        # own metadata: its decode and the canonical header bytes.
        size = M._decode_charge(held.value)+M._decode_charge(view._metadata)+len(view._metadata)+65536
        with scope.reserve(ChargeSpec('mesh-root-binding', size)):
            root = parse(held.value)
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
        from atlas_tectonics._private.codecs.compact_store import CompactMeshStoreV3
        adapter = CompactMeshStoreV3(context['resolver'], scope=scope, support_source=context['support_source'])
        ref = adapter.publish(view, producer=context['producer'])
        view = _published(context, scope, view, ref)
    from atlas_tectonics.integration.coupling.exterior_mesh import ExteriorMesh
    return ExteriorMesh.from_compact(view, budget=budget)


def build(builder, args, kwargs, context):
    budget = kwargs['budget']
    _scope(context, budget)
    supports = args[2] if len(args) == 3 and builder.__name__.endswith('differential_mesh_record') else None
    if supports is not None:
        pass
    try:
        # Passing the returned wrapper directly avoids retaining the complete
        # input in this public frame while finish freezes the compact columns.
        return finish(builder(*args, **kwargs), budget=budget, context=context)
    except BaseException as error:
        # Preserve exception class/message and stack positions. Inactive build
        # frames must not retain geometry after their arena has been released.
        traceback.clear_frames(error.__traceback__)
        raise
