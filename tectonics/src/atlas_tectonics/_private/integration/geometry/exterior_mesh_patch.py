"""Exact additive array-backed ExteriorMesh seam, not geometry acceptance.

Only the named source transform is emitted. Frozen runtime sources are never
edited here. A compact view must already bind every exact legacy byte to its
original geometry ID; the native header checks remain independent. Ordinary
legacy construction, restore and record semantics are unchanged.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, cast
import weakref

if TYPE_CHECKING:
    from atlas_tectonics._private.codecs.mesh_tables import CompactMesh


_SCHEMA = 'atlas.source-bound-exterior-thermal-mesh.v1'


def _view(mesh):
    """No implicit conversion or all-record decode on the indexed path."""
    view = getattr(mesh, '_compact', None)
    return cast('CompactMesh', view)


def admit_compact_mesh(cls, view, *, budget):
    view.header()
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
    from atlas_tectonics._private.codecs.mesh_tables import OwnedRow
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
            from atlas_tectonics.integration.geometry.volume import VolumeError
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
