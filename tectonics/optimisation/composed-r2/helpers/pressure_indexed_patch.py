"""Indexed compact pressure consumer; the frozen native pressure arithmetic is intact.

transform() adds three exact dispatch seams to the frozen differential pressure
source. Ordinary dictionary states execute the original statements unchanged.
An indexed spatial state is read through its owned small logical body, sealed
CompactMesh rows/support blobs and compact partition handles: no whole mesh or
partition record is exported. Each supplied support is posed exactly once and
only one decoded posed view is live at a time. Exact constraint records that
escape into regions['_physical_planes'] are decoded once per DAG node under a
separately charged owner, alive while any region, region copy or retained
traceback can still borrow them. Mathematics, proof premises, order, refusal
types and messages are the native ones; the compact codecs are storage
authentication, never physical acceptance.

Top-level imports are standard library only: the ordinary route loads nothing.
"""
import ast
from dataclasses import dataclass
from fractions import Fraction as Q
from hashlib import sha256
import json
import sys


BASE_SHA256 = '8615d60bd46ccb822b7fa1089d487997f40c110bc7c6865d7e16eaebad6663d2'
TRANSFORMED_SHA256 = '65d9095fde5fe685a78e1b15d113a7f3e830c6f4895508abd58983144519c551'
# funding_transfer.pressure_source(transform(frozen)); the composer pins both,
# because pressure_source has no input guard of its own.
COMPOSED_SHA256 = '8d3d8f3dd11d632ce6a75380a17fdcd19b281fafa03b68401a2726d228c02a33'
# WorkBudget keeps 63 labels; this module books only these three.
RETAINED = 'pressure-constraint-retained'
ENTRIES = 'pressure-indexed-entries'
SCRATCH = 'pressure-indexed-scratch'
BLOCK = 65536
REGION_CHARGE = 4096
INDEX_ENTRY = 256
NAME_CHARGE = 256
_ABSENT = object()


class PressureIndexedRefused(ValueError):
    pass


_SEAMS = (
    ('def _current_regions(sphere, funding, collar, state, spatial_state, supports, endpoint,\n'
     '                     radius, support_radius, budget):\n'
     '    from . import integration_exterior_mesh as E, integration_support as U\n',
     'def _current_regions(sphere, funding, collar, state, spatial_state, supports, endpoint,\n'
     '                     radius, support_radius, budget):\n'
     '    from pressure_indexed_patch import is_indexed as _pressure_indexed\n'
     '    if _pressure_indexed(spatial_state):\n'
     '        from pressure_indexed_patch import current_regions as _indexed_regions\n'
     '        return _indexed_regions(sphere, funding, collar, state, spatial_state, supports, endpoint,\n'
     '                                radius, support_radius, budget)\n'
     '    from . import integration_exterior_mesh as E, integration_support as U\n'),
    ('    f, c, geo, pressure = funding.descriptor(), spatial_state.record(), geometry.record(), reservoir_pressure.descriptor()\n',
     '    from pressure_indexed_patch import state_record as _pressure_state_record\n'
     '    f, c, geo, pressure = funding.descriptor(), _pressure_state_record(spatial_state), geometry.record(), reservoir_pressure.descriptor()\n'),
    ("    mesh = c['thermal_mesh']\n",
     '    from pressure_indexed_patch import mesh_header as _pressure_mesh_header\n'
     "    mesh, _pressure_mesh_owner = _pressure_mesh_header(c['thermal_mesh'], budget)\n"),
)


def _once(source, old, new):
    # Exactly one occurrence, counting overlaps, and it must start a line: an
    # indented copy of the anchor inside a deeper line can never satisfy it.
    hits, at = [], source.find(old)
    while at >= 0:
        hits.append(at)
        at = source.find(old, at+1)
    if (not old.endswith('\n') or old.startswith('\n') or len(hits) != 1 or
            (hits[0] and source[hits[0]-1] != '\n')):
        raise PressureIndexedRefused('pressure indexed seam missing, ambiguous or not line-anchored: '+old[:80])
    return source[:hits[0]]+new+source[hits[0]+len(old):]


def transform(source):
    """Frozen differential pressure source -> indexed dispatch candidate, once.

    Apply BEFORE funding_transfer.pressure_source; the input guard refuses the
    reverse order and a second application by design.
    """
    if type(source) is not str or sha256(source.encode()).hexdigest() != BASE_SHA256:
        raise PressureIndexedRefused('reviewed frozen differential pressure source required exactly once')
    for old, new in _SEAMS:
        source = _once(source, old, new)
    ast.parse(source)
    if sha256(source.encode()).hexdigest() != TRANSFORMED_SHA256:
        raise PressureIndexedRefused('indexed pressure candidate differs from its reviewed digest')
    return source


def _indexed_module():
    # An IndexedSpatialSnapshot can exist only once its defining module is
    # loaded, so the ordinary route never imports the compact codec to ask.
    return sys.modules.get('spatial_indexed_patch')


def is_indexed(spatial_state):
    X = _indexed_module()
    return X is not None and type(getattr(spatial_state, '_snapshot', None)) is X.IndexedSpatialSnapshot


def state_record(spatial_state):
    """Ordinary: exactly state.record(). Indexed: owned small body + sealed mesh.

    The indexed _LogicalRecord carries its decode allocation; hold it for the
    caller's frame while borrowing any of its values.
    """
    if not is_indexed(spatial_state):
        return spatial_state.record()
    return _indexed_module().logical_record(spatial_state)


def mesh_header(mesh, budget):
    """(header fields, owner): the identical dict, or a charged compact header."""
    if type(mesh) is dict:
        return mesh, None
    import spatial_indexed_patch as X
    if not X.is_compact(mesh):
        # Leave every other value to fail in the original statement as before.
        return mesh, None
    owned = X._view(mesh, budget).header()
    return owned.value, owned


class _Lease:
    """One reservation, entered now and released only when this owner dies."""
    __slots__ = ('_guard', 'size')

    def __init__(self, budget, size, category):
        self._guard = None
        self.size = size
        guard = budget.reserve(size, category=category)
        guard.__enter__()
        self._guard = guard

    def __del__(self):
        guard = self._guard
        if guard is not None:
            self._guard = None
            guard.__exit__(None, None, None)


class _OwnedPlanes(tuple):
    """Exact borrowed (issued constraint record, elapsed) pairs plus their owner.

    Equal to the legacy tuple; moving_wall_integrals uses only truth, len and
    zip. Copies cannot escape without the owner: pickling/copying is refused.
    """
    def __new__(cls, items, owner):
        result = super().__new__(cls, items)
        object.__setattr__(result, '_owner', owner)
        return result

    def __setattr__(self, name, value):
        raise AttributeError('immutable owned pressure planes')

    def __delattr__(self, name):
        raise AttributeError('immutable owned pressure planes')

    def __reduce_ex__(self, protocol):
        raise TypeError('owned pressure planes are process-local borrowed records')

    def __reduce__(self):
        raise TypeError('owned pressure planes are process-local borrowed records')

    def __copy__(self):
        raise TypeError('owned pressure planes are process-local borrowed records')

    def __deepcopy__(self, memo):
        raise TypeError('owned pressure planes are process-local borrowed records')


class PressureConstraintOwner:
    """Separately charged arena of exact constraint subtrees borrowed by regions.

    Each distinct compact DAG node, or (support, name) for a native support, is
    decoded once; capacity is charged before json.loads. Records are shared
    read-only: _face_on_wall and the rigid plane path only read them.
    """
    __slots__ = ('_budget', '_blocks', '_free', '_records', '_native', 'stats')

    def __init__(self, budget):
        self._budget, self._blocks, self._free = budget, [], 0
        self._records, self._native = {}, None
        self.stats = dict(charged=0, record_bytes=0, decoded=0, shared_hits=0, regions=0)

    @property
    def reserved(self):
        return sum(block.size for block in self._blocks)

    def hold(self, size):
        if size > self._free:
            block = max(BLOCK, size)
            self._blocks.append(_Lease(self._budget, block, RETAINED))
            self._free += block
        self._free -= size
        self.stats['charged'] += size

    def planes(self, items):
        # Measured region dicts are 1.7-1.9 KB without the cell and records.
        self.hold(REGION_CHARGE)
        self.stats['regions'] += 1
        return _OwnedPlanes(items, self)

    def record(self, entry, name):
        from partition_routing_patch import CompactSupport
        from record_views import RecordRef
        handle = entry.handle
        if type(handle) is CompactSupport:
            key = entry.nodes.get(name)
            if key is None:
                table = entry.nodes.get(None)
                if table is None:
                    table = entry.nodes[None] = handle._ref.field('constraints')
                key = entry.nodes[name] = table.field(name)
        else:
            key = entry.support_id, name
        cache_key = (key._view, key.index) if isinstance(key, RecordRef) else key
        if cache_key in self._records:
            self.stats['shared_hits'] += 1
            return self._records[cache_key]
        value = self._decode(key) if type(handle) is CompactSupport else self._native_record(entry, name)
        self._records[cache_key] = value
        self.stats['decoded'] += 1
        return value

    def _keep(self, raw):
        from atlas_tectonics.integration_routing_views import _decoded_json_capacity
        size = _decoded_json_capacity(raw)
        self.hold(size)
        self.stats['record_bytes'] += size

    def _decode(self, node):
        # Size by streaming, charge the bounded join, then the decoded graph.
        from partition_routing_patch import _iter_ref
        from partition_native_patch import MAX_NATIVE_SUPPORT_BYTES
        from record_views import RecordRef
        size = 0
        for part in _iter_ref(node):
            size += len(part)
            if isinstance(node, RecordRef) and size > MAX_NATIVE_SUPPORT_BYTES:
                raise PressureIndexedRefused('selected pressure constraint exceeds native support bound')
        scratch = _Lease(self._budget, 65536+3*size, SCRATCH)
        buffer = bytearray()
        for part in _iter_ref(node):
            buffer += part
        raw = bytes(buffer)
        del buffer
        self._keep(raw)
        value = json.loads(raw)
        del raw, scratch
        return value

    def _native_record(self, entry, name):
        import mesh_tables as M
        from partition_native_patch import owned_support_record
        if self._native is None or self._native[0] != entry.support_id:
            self._native = None
            self._native = entry.support_id, owned_support_record(entry.handle)
        value = self._native[1].value['constraints'][name]
        # The subtree outlives its charged full decode: book it before encoding.
        scratch = _Lease(self._budget, 65536+2*M._width(value), SCRATCH)
        self._keep(M.canonical(value))
        del scratch
        return value

    def release_scratch(self):
        self._native = None


@dataclass(frozen=True, slots=True, eq=False)
class _PosedEntry:
    support_id: str
    handle: object
    time_s: object
    duration: object
    plate_id: object
    radial_layer: object
    voxel: object
    constraints: dict
    pairs: tuple
    nodes: dict
    lease: object


def _present(value, key):
    if value is _ABSENT:
        raise KeyError(key)
    return value


def _json_value(value):
    return None if value is _ABSENT else value


def _pair(part):
    # Native issuer/schema-gated components are objects. Legacy would read a
    # malformed component only while scanning before a match; this route
    # refuses it while posing instead (fail-closed, never a silent pass).
    if type(part) is not dict:
        from atlas_tectonics import integration_pressure_coupling as C
        raise C.PressureCouplingRefused('physical support components must be issued objects')
    return part.get('logical_cell_id', _ABSENT), part.get('constraints', _ABSENT)


def _literals(pairs, refs):
    """Legacy resolve_physical_support's first matching component, same errors."""
    for lid, literals in pairs:
        if lid is _ABSENT:
            raise KeyError('logical_cell_id')
        if lid == refs['logical_cell_id']:
            return literals
    from atlas_tectonics import integration_volume as V
    raise V.VolumeError('thermal physical support reference has no matching component')


def _posed_entry(support, view, endpoint, budget):
    """Slim charged retention of one posed support; its full view is dropped."""
    import mesh_tables as M
    from atlas_tectonics.integration_routing_views import _decoded_json_capacity
    from partition_native_patch import owned_support_record
    from partition_routing_patch import CompactSupport, retain_support, support_fields
    handle = retain_support(support)
    pairs = tuple(_pair(part) for part in view['components'])
    duration = _ABSENT
    if endpoint != 'start':
        # Bounded charged field read (compact) or charged owned decode (native),
        # never the unfunded legacy support.record().
        owned = (support_fields(handle, ('duration_s',)) if type(handle) is CompactSupport
                 else owned_support_record(handle))
        duration = owned.value.get('duration_s', _ABSENT)
        del owned
    shape = dict(time_s=view['time_s'], plate_id=view['plate_id'], radial_layer=view['radial_layer'],
                 voxel=view['voxel'], constraints=view['constraints'], duration_s=_json_value(duration),
                 components=[[_json_value(a), _json_value(b)] for a, b in pairs])
    scratch = _Lease(budget, 65536+2*M._width(shape), SCRATCH)
    lease = _Lease(budget, 4096+NAME_CHARGE*len(view['constraints'])+
                   _decoded_json_capacity(M.canonical(shape)), ENTRIES)
    del scratch, shape
    return _PosedEntry(view['support_id'], handle, view['time_s'], duration, view['plate_id'],
                       view['radial_layer'], view['voxel'], view['constraints'], pairs, {}, lease)


def _exterior_index(view, budget):
    """{logical_cell_id: row index}, last occurrence winning as in the legacy dict."""
    lease = _Lease(budget, 4096+INDEX_ENTRY*view.cell_count, ENTRIES)
    thermal = {}
    for index in range(view.cell_count):
        row = view.cell(index)
        value = row.value
        if value['kind'] == 'exterior':
            thermal[value['logical_cell_id']] = index
        del row, value
    return thermal, lease


def _blob_identity(view, ident):
    # The authenticated content SHA-256 of the canonical support blob; equals
    # the legacy hashlib.sha256(_json(raw)) without decoding the blob.
    return view.ident(int(view._arrays['s.blob'][view._support_position('differential_supports', ident)]))


def current_regions(sphere, funding, collar, state, spatial_state, supports, endpoint,
                    radius, support_radius, budget):
    """Native _current_regions contract and order for an indexed spatial state."""
    from atlas_tectonics import integration_differential_geometry as G
    from atlas_tectonics import integration_spatial_pressure as P
    from atlas_tectonics import integration_pressure_coupling as C
    from atlas_tectonics import integration_volume as V
    from atlas_tectonics import integration_wall_measures as W
    from atlas_tectonics import integration_support as U
    from atlas_tectonics.integration_routing_views import _decoded_json_capacity
    f, current = funding.descriptor(), state_record(spatial_state)
    fields = collar._fields(state)
    cells = collar.cell_geometries()
    material = collar._native._material
    count = len(collar._native._composition)
    masses = fields['component_mass_kg'].reshape(count, -1)
    regions, densities = [], []
    for i, (cell, energy) in enumerate(zip(cells, fields['enthalpy_j'].flat)):
        low, high = cell.radial_bounds_squared_m2
        if low < support_radius**2 or high > radius**2:
            raise C.PressureCouplingRefused('native material outside the declared pressure support')
        rho, temperature = P._density(material, Q(float(energy)), tuple(Q(float(v)) for v in masses[:, i]), budget)
        regions.append(dict(cell=cell, cone=(), radial=(support_radius, radius), density=rho, plate_id=None))
        densities.append(dict(cell_id=cell.cell_id, density_kg_m3=V._encoded(rho), temperature_k=V._encoded(temperature)))
    view = current['thermal_mesh']
    if view.budget is not budget:
        raise C.PressureCouplingRefused('compact pressure mesh belongs to another budget')
    thermal, index_lease = _exterior_index(view, budget)
    if len(thermal) != len(current['cells']) or set(thermal) != {r['cell_id'] for r in current['cells']}:
        raise C.PressureCouplingRefused('carried fields and physical support have different cell coverage')
    posed = {}
    for support in supports:
        if type(support) is not G.DifferentialSupport or support._resource is not budget:
            raise C.PressureCouplingRefused('issued current physical component supports required')
        measure = G.posed_support(support, endpoint=endpoint, budget=budget)
        scratch = _Lease(budget, _decoded_json_capacity(measure._json), SCRATCH)
        posed_view = measure.record()
        del measure
        if posed_view['support_id'] in posed:
            raise C.PressureCouplingRefused('duplicate physical support')
        posed[posed_view['support_id']] = _posed_entry(support, posed_view, endpoint, budget)
        # Keep only the slim entry: the materialised support and view go now.
        del posed_view, scratch, support
    patch_faces = {p.patch_id: p.face_id for p in U.required(sphere.material).patches}
    face_plates = {face.face_id: face.plate_id for face in sphere.network.faces}
    owner = PressureConstraintOwner(budget)
    for row in current['cells']:
        mesh_owner = view.cell(thermal[row['cell_id']])
        mesh_row = mesh_owner.value
        if row['source_key'] != mesh_row['source_key']:
            raise C.PressureCouplingRefused('carried cell lineage differs from its physical support')
        refs = mesh_row['physical_support']
        extra, cone, physical_planes, held = (), (), (), None
        if 'differential_support_id' in refs:
            support_id = _blob_identity(view, refs['differential_support_id'])
            entry = posed.get(support_id)
            if entry is None:
                # Legacy resolves the mesh's own support (VolumeError first).
                held = view.support('differential_supports', refs['differential_support_id'])
                _literals(map(_pair, held.value['components']), refs)
                raise C.PressureCouplingRefused('force supplied a different physical component geometry')
            # Equal content SHA-256 of two canonical encodings (G._encoded and
            # mesh_tables.canonical) implies legacy's posed[id][0] == raw.
            literals = _literals(entry.pairs, refs)
            if W._decode(entry.time_s) != Q(current['time_s']):
                raise C.PressureCouplingRefused('component force geometry has another clock')
            planes, physical_planes = [], []
            elapsed = Q(0) if endpoint == 'start' else W._decode(_present(entry.duration, 'duration_s'))
            for name, sign in _present(literals, 'constraints'):
                plane = entry.constraints[name]
                normal = tuple(-sign*W._decode(v) for v in plane['normal'])
                planes.append((*normal, -sign*W._decode(plane['offset']), W._decode(plane['error_euclidean'])))
                # Borrow the exact issuer record in the SAME literal order.
                # It is a premise to prove on each wall, never a stored verdict.
                physical_planes.append((owner.record(entry, name), elapsed))
            extra, plate, layer, voxel = tuple(planes), entry.plate_id, entry.radial_layer, entry.voxel
        else:
            voxel_owner = view.support('voxels', refs['voxel_id'])
            layer_owner = view.support('radial_layers', refs['radial_layer_id'])
            cone_owner = view.support('cones', refs['cone_id'])
            held = voxel_owner, layer_owner, cone_owner
            if current['intervals'] or current['time_s'] != f['time_s']:
                raise C.PressureCouplingRefused('old source cones cannot locate an advanced differential field')
            cone = tuple(tuple(map(W._decode, p)) for p in cone_owner.value)
            plate = face_plates[patch_faces[row['source_key'][0]]]
            layer, voxel = layer_owner.value, voxel_owner.value
            del voxel_owner, layer_owner, cone_owner
        if W._decode(layer['radius_m']) != radius or layer['convention'] != V.PHYSICAL_RADIAL_SHELL:
            raise C.PressureCouplingRefused('pressure uses another radial geometry convention')
        rb, rt = radius-W._decode(layer['bottom_depth_m']), radius-W._decode(layer['top_depth_m'])
        if not support_radius <= rb < rt <= radius:
            raise C.PressureCouplingRefused('current material band outside declared pressure support')
        exact = row['exact']
        rho, temperature = P._density(material, W._decode(exact['enthalpy_j']),
            tuple(W._decode(exact['component_mass_kg:'+str(i)]) for i in range(count)), budget)
        regions.append(dict(cell=V.CartesianCell.from_record(voxel, budget=budget),
            cone=cone, world_planes=extra, _physical_planes=owner.planes(physical_planes),
            radial=(rb, rt), density=rho, plate_id=plate))
        densities.append(dict(cell_id=row['cell_id'], density_kg_m3=V._encoded(rho), temperature_k=V._encoded(temperature)))
        del mesh_owner, mesh_row, refs, held, layer, voxel
    owner.release_scratch()
    del posed, thermal, index_lease, owner
    return regions, densities, cells
