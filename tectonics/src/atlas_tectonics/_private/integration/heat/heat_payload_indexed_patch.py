"""Owned numerical metric projection, not a legacy geometry expansion.

The actual indexed MimeticGeometry has already run native metric validation.
Its CompactMesh owns immutable shared IDs/exact numbers and authenticated
support references. Only IDs/incidence, centres, normals and polygon vertices
are projected here. No physical-support blob, row annotation, cartesian support
or provenance graph is decoded. Exact hex rational spelling and row order are
the codec's original spelling/order.

The typed row API returns OwnedRow: retain that wrapper while borrowing .value.
The numerical kernel deliberately receives its existing plain {cells, faces}
shape, not a dict/Mapping impersonator. Each decoded row remains separately
funded until a counted persistent payload lease adopts it. Existing LIFE then
counts the whole minimal graph before retiring that producer. Kernel face_data
remains a borrowed alias into this live graph; its _prepared_bytes and worker
MOMENT_FIELDS serializer therefore retain their original valid ownership model.

No arithmetic, precision, rank, polygon validation, order or acceptance changes.
This is an additive source transform; never write its outputs over old sources.
"""
from concurrent.futures import CancelledError
from itertools import chain
import sys


CELL_FIELDS = frozenset(('cell_id', 'volume_m3', 'centroid_m', 'faces'))
FACE_FIELDS = frozenset(('face_id', 'centroid_m', 'area_vector_m2', 'owners', 'vertices_m'))


def _check(cancel):
    if cancel is not None and cancel():
        raise CancelledError('Indexed numerical metric preparation cancelled')


def is_indexed(geometry):
    return getattr(geometry, '_indexed', None) is not None


class IndexedMetricPayload:
    """Explicit native metric adapter; neither a full record nor a Mapping."""
    __slots__ = ('geometry', 'view', 'budget', 'cancel', '_sealed')

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)

    def __init__(self, geometry, *, budget, cancel=None):
        self.geometry, self.view, self.budget, self.cancel = geometry, geometry._indexed, budget, cancel
        self._sealed = True

    @property
    def cell_count(self):
        return self.view.cell_count

    @property
    def face_count(self):
        return self.view.face_count

    def cell(self, index):
        from atlas_tectonics._private.codecs.mesh_tables import OwnedRow, require
        _check(self.cancel)
        view, a = self.view, self.view._arrays
        # Index validation must precede the NumPy row lookup.
        require(type(index) is int and 0 <= index < self.cell_count, 'cell index outside table')
        linked = view._range('c.face_offset', index)
        owner = view._row_owner(a['c.q'][index, :4], 512*(linked.stop-linked.start))
        row = dict(cell_id=view.cell_id(index), volume_m3=view._pair(a['c.q'][index, 0]),
            centroid_m=[view._pair(q) for q in a['c.q'][index, 1:4]],
            faces=[[view.face_id(int(i)), int(sign)] for i, sign in
                zip(a['c.face'][linked], a['c.sign'][linked], strict=True)])
        _check(self.cancel)
        return OwnedRow(row, (owner, self))

    def face(self, index):
        from atlas_tectonics._private.codecs.mesh_tables import OwnedRow, require
        _check(self.cancel)
        view, a = self.view, self.view._arrays
        require(type(index) is int and 0 <= index < self.face_count, 'face index outside table')
        vertices = view._range('f.vertex_offset', index)
        owners = view._range('f.owner_offset', index)
        allocated = view._row_owner(chain(a['f.q'][index], a['f.vertex'][vertices].flat),
            512*(vertices.stop-vertices.start+owners.stop-owners.start))
        row = dict(face_id=view.face_id(index), centroid_m=[view._pair(q) for q in a['f.q'][index, :3]],
            area_vector_m2=[view._pair(q) for q in a['f.q'][index, 3:]],
            owners=[view.cell_id(int(i)) for i in a['f.owner'][owners]],
            vertices_m=[[view._pair(q) for q in point] for point in a['f.vertex'][vertices]])
        _check(self.cancel)
        return OwnedRow(row, (allocated, self))


def indexed_inventory(geometry, *, cancel=None):
    """No full-record decode occurs; the active projection has its OWN lease.

    Zero refers only to the absent legacy JSON parser component. It is not a
    zero charge for metric rows or a proxy: materialise() pays those separately
    before handing their ordinary dictionary graph to the unchanged LIFE walk.
    """
    payload = IndexedMetricPayload(geometry, budget=geometry._budget, cancel=cancel)
    _check(cancel)
    return 0, (('indexed_cells_separately_owned', payload.cell_count),
               ('indexed_faces_separately_owned', payload.face_count))


def _plain_bytes(value, COUNT, G, counted, padding, cancel, depth=0):
    _check(cancel)
    total = (COUNT.own_bytes(value, G) if counted else
             max(sys.getsizeof(value), COUNT.refused_bytes(value, G, padding)))
    if type(value) is dict:
        for key, child in value.items():
            total += _plain_bytes(key, COUNT, G, counted, padding, cancel, depth+1)
            total += _plain_bytes(child, COUNT, G, counted, padding, cancel, depth+1)
    elif type(value) is list:
        for child in value:
            total += _plain_bytes(child, COUNT, G, counted, padding, cancel, depth+1)
    return total


def materialise(geometry, *, budget, cancel=None):
    """Return actual P.OwnedSolve of the fully funded minimal metric graph.

    Fixed-length table lists are prospectively admitted before allocation.
    One codec row lease overlaps transfer into the counted graph. Alias counts
    are deliberately repeated, as in LIFE; no object is credited twice away.
    The 64 KiB metadata covers workspace/owner, counters and bounded traversal,
    not a purported operating-system memory bound. Existing counted-blocks
    unsupported-runtime fallback remains conservative and explicit.
    """
    from atlas_tectonics._private.integration.heat import gmp_resources as R
    from atlas_tectonics._private import private_heat_decimal_sparse_core_r1 as P
    from atlas_tectonics._private.integration.heat import counted_blocks as COUNT
    from atlas_tectonics._exact_runtime import selected
    payload = IndexedMetricPayload(geometry, budget=budget, cancel=cancel)
    G = selected.library()
    # Two pointer tables, including allocator/debug growth allowance. Their
    # actual retained container counts replace this prospective bound below.
    initial = 65536+32*(payload.cell_count+payload.face_count)
    work = R.OwnedWorkspace(budget, initial, category='heat-indexed-metric-payload', cancelled=cancel)
    work.__enter__()
    try:
        counted = COUNT.supported(G)
        padding = None if counted else COUNT.padding()
        graph = dict(cells=[None]*payload.cell_count, faces=[None]*payload.face_count)
        count = lambda value: _plain_bytes(value, COUNT, G, counted, padding, cancel)
        held, empty = count(graph), count(None)
        work.resize_before_allocation_or_after_drop(max(initial, 65536+held))
        for rows, getter in ((graph['cells'], payload.cell), (graph['faces'], payload.face)):
            for index in range(len(rows)):
                _check(cancel)
                owned = getter(index)
                increment = count(owned.value)-empty
                work.resize_before_allocation_or_after_drop(max(work.lease.count, 65536+held+increment))
                rows[index] = owned.value
                held += increment
                owned = None  # complete row remains charged by this payload lease
        _check(cancel)
        work.resize_before_allocation_or_after_drop(65536+held)
        return P.OwnedSolve(graph, work)
    except BaseException:
        work.__exit__(*sys.exc_info())
        raise
