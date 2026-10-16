"""Exact additive array-backed ExteriorMesh seam, not geometry acceptance.

Only the named source transform is emitted. Frozen runtime sources are never
edited here. A compact view must already bind every exact legacy byte to its
original geometry ID; the native header checks remain independent. Ordinary
legacy construction, restore and record semantics are unchanged.
"""
from __future__ import annotations

import hashlib
import json
import weakref


BASE_SOURCE_SHA256 = 'd1d2abefa7ae4cc5a83d64b80c036475669284002b10eef9bc591f3e2a117503'
_SCHEMA = 'atlas.source-bound-exterior-thermal-mesh.v1'


class CompactExteriorRefused(ValueError):
    pass


def _view(mesh):
    """No implicit conversion or all-record decode on the indexed path."""
    from mesh_tables import CompactMesh
    view = getattr(mesh, '_compact', None)
    if (type(view) is not CompactMesh or not getattr(view, '_sealed', False)
            or view._budget is not mesh._resource):
        raise CompactExteriorRefused('actual same-budget compact ExteriorMesh required')
    return view


def admit_compact_mesh(cls, view, *, budget):
    from mesh_tables import CompactMesh
    from atlas_tectonics.integration_exterior_mesh import ExteriorMesh, METHOD
    from atlas_tectonics.resources import WorkBudget
    if (cls is not ExteriorMesh or type(view) is not CompactMesh or not getattr(view, '_sealed', False)
            or type(budget) is not WorkBudget or view._budget is not budget):
        raise CompactExteriorRefused('actual compact mesh and exact shared WorkBudget required')
    header_owner = view.header()
    header = header_owner.value
    required = ('funding_id', 'source', 'support_id', 'trajectory_id', 'time_s',
                'grid_id', 'endpoint', 'trajectory_segments')
    if (header.get('schema') != _SCHEMA or header.get('method') != METHOD
            or any(k not in header for k in required) or 'grid_lines' not in view._grids):
        raise CompactExteriorRefused('unsupported saved thermal geometry method or header')
    from atlas_tectonics.integration_mimetic_heat import _stream_encoding_capacity
    _, scratch = _stream_encoding_capacity(header['trajectory_segments'], budget)
    # Use the existing audited streaming codec allowance, then hash without a
    # second whole trajectory string. Header ownership survives held errors.
    scratch_owner = _SmallOwner(budget, scratch, category='compact-exterior-trajectory-check')
    digest = hashlib.sha256()
    for chunk in json.JSONEncoder(sort_keys=True, separators=(',', ':'), allow_nan=False).iterencode(header['trajectory_segments']):
        digest.update(chunk.encode())
    trajectory = digest.hexdigest()
    if header['endpoint'] not in ('start', 'end') or trajectory != header['trajectory_id']:
        raise CompactExteriorRefused('saved thermal trajectory differs')
    assert scratch_owner._guard is not None
    # The codec owns its immutable arrays/metadata; the native wrapper retains
    # that actual owner rather than reserving or copying a second mesh.
    guard = budget.reserve(1024, category='compact-exterior-wrapper')
    guard.__enter__()
    try:
        result = object.__new__(cls)
        object.__setattr__(result, '_json', None)
        object.__setattr__(result, '_resource', budget)
        object.__setattr__(result, '_compact', view)
        if view.scope is not None:
            borrowed = view._owner.retain()
            weakref.finalize(result, borrowed.close)
        weakref.finalize(result, guard.__exit__, None, None, None)
        return result
    except BaseException:
        guard.__exit__(None, None, None)
        raise


class _SmallOwner:
    def __init__(self, budget, size=2048, *, category='compact-exterior-support-view'):
        self._guard = None
        guard = budget.reserve(size, category=category)
        guard.__enter__()
        self._guard = guard

    def __del__(self):
        if self._guard is not None:
            guard, self._guard = self._guard, None
            guard.__exit__(None, None, None)


def physical_support(mesh, index):
    """One actual indexed cell and shared support; never a full-table export."""
    from mesh_tables import OwnedRow
    view = _view(mesh)
    allocation = _SmallOwner(mesh._resource)
    cell_owner = view.cell(index)
    cell = cell_owner.value
    refs = cell['physical_support']
    if 'differential_support_id' in refs:
        support_owner = view.support('differential_supports', refs['differential_support_id'])
        support = support_owner.value
        component = next((row for row in support['components']
                          if row['logical_cell_id'] == refs['logical_cell_id']), None)
        if component is None:
            from atlas_tectonics.integration_volume import VolumeError
            raise VolumeError('thermal physical support reference has no matching component')
        return OwnedRow(dict(support=support, component=component),
                        (allocation, cell_owner, support_owner))
    voxel = view.support('voxels', refs['voxel_id'])
    owners = [cell_owner, voxel]
    result = dict(voxel=voxel.value)
    if cell['kind'] == 'exterior':
        layer, cone, header = (view.support('radial_layers', refs['radial_layer_id']),
                              view.support('cones', refs['cone_id']), view.header())
        owners.extend((layer, cone, header))
        result.update(radial_layer=layer.value, original_cone=cone.value,
                      trajectory_id=header.value['trajectory_id'])
    return OwnedRow(result, (allocation, *owners))


_INDEXED_METHODS = '''    @classmethod
    def from_compact(cls, view, *, budget):
        """Admit an exact immutable table view, not a fresh physical certificate."""
        from exterior_mesh_patch import admit_compact_mesh
        return admit_compact_mesh(cls, view, budget=budget)

    def __eq__(self, other):
        if other.__class__ is not self.__class__:
            return NotImplemented
        left, right = getattr(self, '_compact', None), getattr(other, '_compact', None)
        if left is None or right is None:
            # Preserve the legacy byte-representation equality exactly. A
            # compact representation is deliberately a distinct key domain;
            # cross-format scientific identity is the explicit geometry_id.
            return left is right and self._json == other._json
        return left.geometry_id == right.geometry_id

    def __hash__(self):
        compact = getattr(self, '_compact', None)
        if compact is None:
            return hash((self._json,))
        return hash(('compact-exterior-mesh.v1', compact.geometry_id))

    @property
    def is_compact(self):
        return getattr(self, '_compact', None) is not None

    def header(self):
        from exterior_mesh_patch import _view
        return _view(self).header()

    @property
    def cell_count(self):
        from exterior_mesh_patch import _view
        return _view(self).cell_count

    @property
    def face_count(self):
        from exterior_mesh_patch import _view
        return _view(self).face_count

    def cell(self, index):
        from exterior_mesh_patch import _view
        return _view(self).cell(index)

    def face(self, index):
        from exterior_mesh_patch import _view
        return _view(self).face(index)

    def cell_metrics(self, index):
        from exterior_mesh_patch import _view
        return _view(self).cell_metrics(index)

    def face_metrics(self, index):
        from exterior_mesh_patch import _view
        return _view(self).face_metrics(index)

    def support(self, table, identity):
        from exterior_mesh_patch import _view
        return _view(self).support(table, identity)

    def physical_support(self, index):
        from exterior_mesh_patch import physical_support
        return physical_support(self, index)

    def iter_legacy_json(self):
        from exterior_mesh_patch import _view
        return _view(self).iter_legacy_json()

    def legacy_record(self):
        """Explicit costly compatibility export; retain the returned owner."""
        from exterior_mesh_patch import _view
        return _view(self).legacy_record()

'''


def transform(source):
    """Propose the exact additive source; no writes, runtime monkeypatch or permit."""
    if type(source) is not str or hashlib.sha256(source.encode()).hexdigest() != BASE_SOURCE_SHA256:
        raise CompactExteriorRefused('exterior mesh source differs from exact reviewed base')
    # Authenticate original bytes first. The pinned Windows source has CRLF;
    # textual transform anchors are deliberately platform-independent LF.
    source = source.replace('\r\n', '\n')
    replacements = (
        ('class ExteriorMesh:\n    _json: bytes = field(repr=False)\n',
         'class ExteriorMesh:\n    _json: bytes = field(repr=False)\n'
         '    _compact: object = field(repr=False, compare=False)\n'),
        ('    @property\n    def geometry_id(self):\n        return hashlib.sha256(self._json).hexdigest()',
         _INDEXED_METHODS+'    @property\n    def geometry_id(self):\n'
         "        if getattr(self, '_compact', None) is not None:\n"
         '            from exterior_mesh_patch import _view\n'
         '            return _view(self).geometry_id\n'
         '        return hashlib.sha256(self._json).hexdigest()'),
        ('    def record(self):\n        return json.loads(self._json)',
         '    def record(self):\n'
         "        if getattr(self, '_compact', None) is not None:\n"
         "            raise V.VolumeError('compact mesh requires indexed access; explicit legacy_record() returns owned export')\n"
         '        return json.loads(self._json)'),
        ("    tables, refs = record['support_tables'], cell['physical_support']",
         '    if type(record) is ExteriorMesh:\n'
         '        return record.physical_support(cell)\n'
         "    tables, refs = record['support_tables'], cell['physical_support']"),
    )
    for old, new in replacements:
        if source.count(old) != 1:
            raise CompactExteriorRefused('exterior mesh seam is missing or ambiguous')
        source = source.replace(old, new, 1)
    return source
