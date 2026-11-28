"""(b') D1 wiring: the thermal mesh is built compact and unpublished, and published by _publish.

G-R3-1 (coordinator, 16 Oct 2026; storage's five conditions, condition 1 as redefined after
the refuter). The joined control's end thermal mesh (JC 408) is built with
compact_context={'scope': the workflow store's retained scope}: a sealed in-memory
CompactMesh that writes nothing. Under the composed partition stage (live_partition_patch.transform,
live_memory_composition.STAGES) a proposal is compact when its parent is a restored PartitionV2,
from interval 2 on: the mesh then shares every differential support with the partition. Interval
1's parent is the native root partition, so its proposal is native, and live_mesh_patch copies
the support bodies into its in-memory static table. note_end_mesh records which for run.json.
The stored bytes are the same either way. Nothing is written between the driver's opening
inspect() (JC 227) and CollarWorkflow._publish, so the cancelled call's opening _refresh
(RC1 1457) finds its token current, no full parent restore runs, and R3 needs no mesh rule.
In _publish, compact_partition converts a native proposal ONCE into a PartitionV2 in the
store scope (the conversion _partition_payload would otherwise make inside), the payload
publishes that view, published_support_source builds its SupportSource, and _spatial_records
hands it to persist_mesh, which publishes the v3 mesh from the in-memory view
(CompactMeshStoreV3.publish: no reopen, no per-scalar walk). The same producer, the digest of
_COMPACT_SPATIAL.producer(collar), names both roots.

Not bound after publication: nothing after _publish in the interval opens the mesh by its
reference, and a bound view would not intercept such an open (CompactMeshStoreV3.open
always runs mesh_from_segment). test_publish_mesh_patch traces it instead.

mesh_context is called by the r8 joined helper; published_support_source is the composed
workflow's seam.
"""
from hashlib import sha256

from atlas_shared.errors import AtlasError
from atlas_tectonics._private.integration import native_transfer as N

class PublishMeshRefused(ValueError, AtlasError):
    pass


def require(ok, message):
    if not ok:
        raise PublishMeshRefused(message)


END_MESH_SUPPORTS = []    # one note per end-mesh build in this process; the runner records them


def mesh_context(workflow, partition):
    """compact_context for the JC 408 end-mesh build: the workflow store's retained scope.

    The proposal's supports are the native tuple (interval 1, native root parent: their bodies
    are copied into the mesh's in-memory static table) or the compact sequence over a sealed
    in-memory PartitionV2 in that scope (from interval 2: shared). A compact sequence in another
    scope is refused. A store without a retained scope (the native ArrayStore route) keeps its native
    mesh.
    """
    scope = getattr(workflow._store, 'scope', None)
    if scope is None:
        return None
    supports = partition.supports
    if type(supports) is tuple:
        return {'scope': scope}
    return {'scope': scope}


def note_end_mesh(partition, mesh, budget):
    """Condition 1 as redefined: whether the end mesh shares or copies the differential supports,
    and the copy's bytes and the static-support booking, for run.json (END_MESH_SUPPORTS)."""
    supports = partition.supports
    copied = type(supports) is tuple
    note = {'supports': 'copied' if copied else 'shared', 'differential_supports': len(supports),
            'copied_support_bytes': sum(len(support._json) for support in supports) if copied else 0,
            'mesh_static_supports_booked_bytes': budget.statistics()['categories'].get(
                'retained:mesh-static-supports', 0),
            'compact_mesh': bool(getattr(mesh, 'is_compact', False))}
    END_MESH_SUPPORTS.append(note)
    return note


def compact_partition(partition, interval, funding, collar, budget, store):
    """The partition _publish publishes, as a compact-backed partition in the store's scope.

    A native proposal is converted ONCE (partition_workflow_patch.convert_native, the
    conversion _partition_payload would otherwise make inside), so the published view's
    SupportSource can serve the mesh. A store without a retained scope, or a partition that
    already has its compact view, is returned unchanged.
    """
    scope = getattr(store, 'scope', None)
    if scope is None:
        return partition
    from atlas_tectonics._private.integration.geometry import partition_native_patch as PN
    if PN.compact_view(partition) is not None:
        return partition
    from atlas_tectonics._private.integration.geometry import partition_workflow_patch as PW
    from atlas_tectonics.integration.geometry.differential_geometry import DifferentialPartition
    view = PW.convert_native(partition, budget, scope=scope)
    return DifferentialPartition.from_compact(view, funding, collar, interval, budget=budget)


def mesh_options(workflow, partition):
    """build_differential_mesh keywords at JC 408: the compact context, or none for a native store
    (a runtime without live_mesh_patch's compact_context parameter then sees today's call)."""
    context = mesh_context(workflow, partition)
    return {} if context is None else {'compact_context': context}


def required_boundary_faces(mesh):
    """JC 428's required thermal boundary faces, in record order.

    A compact mesh refuses record() (exterior_mesh_patch), so its required faces are read
    through the indexed columns, as compact_restart_patch.coverage_projection reads them.
    A mesh without required faces raises KeyError, as the native record lookup does.
    """
    view = getattr(mesh, '_compact', None)
    if view is None:
        return mesh.record()['required_thermal_boundary_faces']
    if not view._required:
        raise KeyError('required_thermal_boundary_faces')
    return [view.face_id(int(index)) for index in view._arrays['required.face']]


def failure_mesh_operand(mesh):
    """The joint-advance failure capture's mesh part and its encoded size (failure-only).

    A native mesh keeps its record() and JSON length. A compact, unpublished mesh has
    neither; its identity and counts are captured instead, since it is rebuilt exactly
    from the captured closed graph and the end bounds.
    """
    if getattr(mesh, '_compact', None) is None:
        return mesh.record, len(mesh._json)
    return {'compact_unpublished_mesh': {'geometry_id': mesh.geometry_id, 'cells': mesh.cell_count,
                                         'faces': mesh.face_count}}, 4096


def published_support_source(partition, store, scratch, *, source_producer):
    """The SupportSource of the partition _partition_payload has just published.

    None without a retained store scope or a compact partition view: the mesh is then
    native, or a bound view that persist_mesh only verifies. The partition root must carry
    the digest of source_producer, which persist_mesh also uses for the mesh root
    (condition 5). The source closes with the publication's scratch stack.
    """
    scope = getattr(store, 'scope', None)
    if scope is None:
        return None
    from atlas_tectonics._private.integration.geometry.partition_native_patch import compact_view
    view = compact_view(partition)
    if view is None:
        return None
    from atlas_tectonics._private.codecs.segment_store import SegmentBackend
    from atlas_tectonics._private.integration.geometry.support_source import SupportSource
    producer = sha256(N._json(source_producer)).hexdigest()
    with SegmentBackend().open(store, view.segment_ref, scope=scope) as segment:
        require(segment._owner.value['producer'] == producer, 'partition and mesh producers differ')
    source = SupportSource(view)
    scratch.callback(source.close)
    return source


