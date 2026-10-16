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
from hashlib import sha256
from itertools import chain
from pathlib import Path
import sys
import textwrap


BASE_SHA = '4d1ddc7f2042fabbbd6aa21e591dfcb1dc698f1af1a59a912e7ee6411bfb3a44'
FACADE_SHA = 'd79b7017f62d349fdb089caf29b09af325ffb3f648b13307896a0efdae8f2c05'
PARALLEL_SHA = '6ecbe13e69706027ccff7ff0538db532e9bd764ee291941cbc7aba7e9d08e99d'
CELL_FIELDS = frozenset(('cell_id', 'volume_m3', 'centroid_m', 'faces'))
FACE_FIELDS = frozenset(('face_id', 'centroid_m', 'area_vector_m2', 'owners', 'vertices_m'))
# Additional runtime helpers selected by the composed native/compact closure.
# Only loaded members are captured. This is not a filename-prefix permission.
# It covers every non-private_heat_ helper the composed native modules import,
# directly or through another helper (derived from the composed import graph
# in test_private_heat_bundle_extended), plus the continuation's routing text.
WORKER_RUNTIME_HELPERS = (
    'heat_payload_indexed_patch', 'mesh_tables', 'native_transfer', 'spatial_transfer',
    'exterior_mesh_patch', 'mimetic_patch', 'spatial_indexed_patch', 'compact_store',
    'partition_tables', 'partition_native_patch', 'workflow_transfer', 'geometry_transfer',
    'spatial_workflow_patch', 'partition_workflow_patch', 'partition_store', 'partition_routing_patch',
    'partition_routing_transform', 'pressure_indexed_patch', 'funding_transfer', 'continuation_transfer',
    'materialise_endpoint', 'historical_admission', 'runtime_compatibility',
)


def _check(cancel):
    if cancel is not None and cancel():
        raise CancelledError('Indexed numerical metric preparation cancelled')


def is_indexed(geometry):
    return getattr(geometry, '_indexed', None) is not None


class IndexedMetricPayload:
    """Explicit native metric adapter; neither a full record nor a Mapping."""
    __slots__ = ('geometry', 'view', 'budget', 'cancel', '_sealed')

    def __setattr__(self, name, value):
        if getattr(self, '_sealed', False):
            raise AttributeError('indexed numerical payload binding is immutable')
        object.__setattr__(self, name, value)

    def __init__(self, geometry, *, budget, cancel=None):
        from atlas_tectonics.integration_mimetic_heat import MimeticGeometry
        from atlas_tectonics.resources import WorkBudget
        from mesh_tables import CompactMesh
        if (type(geometry) is not MimeticGeometry or type(budget) is not WorkBudget or
                type(getattr(geometry, '_indexed', None)) is not CompactMesh or
                geometry._budget is not budget or geometry._indexed.budget is not budget or
                geometry._encoded is not None or geometry.geometry_id != geometry._indexed.geometry_id):
            raise TypeError('actual validated indexed metric and identical caller budget required')
        self.geometry, self.view, self.budget, self.cancel = geometry, geometry._indexed, budget, cancel
        self._sealed = True

    @property
    def cell_count(self):
        return self.view.cell_count

    @property
    def face_count(self):
        return self.view.face_count

    def cell(self, index):
        from mesh_tables import OwnedRow, require
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
        from mesh_tables import OwnedRow, require
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
    if depth > 16 or type(value) not in (dict, list, str, int, type(None)):
        raise TypeError('only bounded plain numerical metric rows may be retained')
    total = (COUNT.own_bytes(value, G) if counted else
             max(sys.getsizeof(value), COUNT.refused_bytes(value, G, padding)))
    if type(value) is dict:
        for key, child in value.items():
            total += _plain_bytes(key, COUNT, G, counted, padding, cancel, depth+1)
            total += _plain_bytes(child, COUNT, G, counted, padding, cancel, depth+1)
    elif type(value) is list:
        for child in value:
            total += _plain_bytes(child, COUNT, G, counted, padding, cancel, depth+1)
    if total > sys.maxsize:
        raise OverflowError('active numerical metric graph exceeds addressable storage')
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
    import private_heat_gmp_resources_r1 as R
    import private_heat_decimal_sparse_core_r1 as P
    import private_heat_counted_blocks_r2 as COUNT
    from atlas_tectonics.exact_arithmetic import library
    payload = IndexedMetricPayload(geometry, budget=budget, cancel=cancel)
    G = library()
    if G is None:
        raise RuntimeError('selected exact backend required')
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


def _source(source, expected):
    if type(source) is not str or sha256(source.encode()).hexdigest() != expected:
        raise ValueError('indexed metric source transform requires exact reviewed predecessor')
    return source


def _replace(source, old, new):
    if source.count(old) != 1:
        raise ValueError('indexed numerical metric seam missing or ambiguous')
    return source.replace(old, new, 1)


def inventory_source(source):
    source = _source(source, BASE_SHA)
    source = _replace(source, 'import private_heat_low_geometry_kernel_r1 as LOW\n',
        'import private_heat_low_geometry_kernel_r1 as LOW\nimport heat_payload_indexed_patch as INDEXED_PAYLOAD\n')
    source = _replace(source,
        '    decode_bytes, json_counts = json_decode_inventory(geometry._encoded, cancel=cancel)\n',
        '    if INDEXED_PAYLOAD.is_indexed(geometry):\n'
        '        decode_bytes, json_counts = INDEXED_PAYLOAD.indexed_inventory(geometry, cancel=cancel)\n'
        '    else:\n'
        '        decode_bytes, json_counts = json_decode_inventory(geometry._encoded, cancel=cancel)\n')
    return _replace(source, '        payload = geometry.record()\n',
        '        if INDEXED_PAYLOAD.is_indexed(geometry):\n'
        '            payload_owner = work.stack.enter_context(INDEXED_PAYLOAD.materialise(geometry, budget=budget, cancel=cancel))\n'
        '            payload = payload_owner.value\n'
        '        else:\n'
        '            payload = geometry.record()\n')


def facade_source(source):
    source = _source(source, FACADE_SHA)
    source = _replace(source, 'import private_heat_geometry_inventory_r1 as BASE\n',
        'import private_heat_geometry_inventory_r1 as BASE\nimport heat_payload_indexed_patch as INDEXED_PAYLOAD\n')
    # There are two identical policy tests: change the prospective one only.
    marker = '        if JSON.select_policy() == JSON.DERIVED:\n            # Still inside r1\'s metadata lease:'
    source = _replace(source, marker,
        '        if not INDEXED_PAYLOAD.is_indexed(geometry) and JSON.select_policy() == JSON.DERIVED:\n'
        '            # Still inside r1\'s metadata lease:')
    start = source.index('        # One json.loads, no safe point inside:')
    end = source.index('        owner._value = dict(prepared=prepared, payload=payload, inventory=plan)', start)
    block = source[start:end]
    return source[:start]+('        if INDEXED_PAYLOAD.is_indexed(geometry):\n'
        '            payload_owner = work.stack.enter_context(INDEXED_PAYLOAD.materialise(geometry, budget=budget, cancel=cancel))\n'
        '            payload = payload_owner.value\n'
        '        else:\n')+textwrap.indent(block, '    ')+source[end:]


def parallel_source(source):
    source = _source(source, PARALLEL_SHA)
    source = _replace(source, 'def _ours(name):\n',
        '_INDEXED_RUNTIME_HELPERS = frozenset('+repr(WORKER_RUNTIME_HELPERS)+')\n\n\ndef _ours(name):\n')
    source = _replace(source,
        "    return name.startswith('private_heat_') or name == 'atlas_tectonics' or name.startswith('atlas_tectonics.')\n",
        "    return name in _INDEXED_RUNTIME_HELPERS or name.startswith('private_heat_') or name == 'atlas_tectonics' or name.startswith('atlas_tectonics.')\n")
    return _replace(source,
        "            if ((place.parent == candidate and place.name.startswith('private_heat_'))\n",
        "            if ((place.parent == candidate and (place.name.startswith('private_heat_') or\n"
        "                    place.suffix == '.py' and place.stem in _INDEXED_RUNTIME_HELPERS))\n")


TRANSFORMS = {
    'private_heat_geometry_inventory_r1.py': inventory_source,
    'private_heat_geometry_inventory_r3.py': facade_source,
    'private_heat_functionals_parallel_r1.py': parallel_source,
}


def additional_transform(inputs):
    """Compose BEFORE literal-pin DAG reconciliation; add helper separately.

    Returns the same explicit file set. The new helper's original input pins
    must not be rewritten into successor hashes by the parent's pin reconciler.
    Copy helper_source() into the composed dependency directory afterwards.
    """
    if type(inputs) is not dict or not set(TRANSFORMS) <= inputs.keys():
        raise ValueError('complete authenticated numerical heat predecessor closure required')
    outputs = dict(inputs)
    for name, transform in TRANSFORMS.items():
        outputs[name] = transform(inputs[name].decode()).encode()
        compile(outputs[name], name, 'exec')
    return outputs


def helper_source():
    return Path(__file__).read_bytes()
