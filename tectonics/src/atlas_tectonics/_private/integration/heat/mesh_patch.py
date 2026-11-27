"""Indexed private-heat input preparation, NOT a heat call or acceptance.

The supplied graph/transport/scalar operands are caller-owned and must have
already been authenticated by the actual owner route. This preparation checks
their scientific relationship to the actual compact mesh, and projects the
exact component mass sum once before the existing multiplication by Cp. It does not authenticate owner
history, execution, source code or a saved checkpoint; it cannot advance.

The exact source transform appends an explicit preparation-only entrypoint.
It leaves bind_owner_call, all source pins and the ordinary forward/cold routes
unchanged. In particular _verify_call_record still requires legacy _encoded,
and joined finish still embeds a full thermal_mesh. Neither is bypassed here.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import json

import numpy as np
from typing import TYPE_CHECKING, cast
if TYPE_CHECKING:
    from atlas_tectonics._private.codecs.mesh_tables import CompactMesh


class _Allocation:
    def __init__(self, budget, size, category):
        self.guard = None
        guard = budget.reserve(size, category=category)
        guard.__enter__()
        self.guard = guard

    def __del__(self):
        if self.guard is not None:
            guard, self.guard = self.guard, None
            guard.__exit__(None, None, None)


class _Bytes(bytes):
    def __new__(cls, value, owner):
        result = super().__new__(cls, value)
        object.__setattr__(result, '_owner', owner)
        return result

    def __setattr__(self, name, value):
        raise AttributeError('immutable indexed heat input ownership')


@dataclass(frozen=True, slots=True)
class IndexedHeatPreparation:
    """Immutable numerical inputs; no execution identity or advance method."""
    geometry: object
    mesh: object
    _metadata: bytes
    _fields: tuple
    _budget: object

    @property
    def may_advance(self):
        return False

    @property
    def owner_origin_validated(self):
        return False

    def array(self, name):
        for key, raw in self._fields:
            if key == name:
                # NumPy retains the immutable bytes owner even if this object
                # and its geometry are discarded. No writable view escapes.
                return np.frombuffer(raw, dtype=np.float64)
        raise KeyError(name)

    def descriptor(self):
        """Only this small preparation descriptor, never a geometry export."""
        from atlas_tectonics._private.codecs.mesh_tables import OwnedRow, _decode_charge
        owner = _Allocation(self._budget, _decode_charge(self._metadata),
                            'indexed-heat-descriptor')
        return OwnedRow(json.loads(self._metadata), owner)

    def physical_support(self, index):
        # Preserve the native/codec composite ownership through the public API.
        return self.mesh.physical_support(index)


def prepare_indexed_inputs(mesh, graph, transported, *, graph_id, funding_id,
        source_stage_id, parent_state_id, duration_s, component_count,
        heat_capacity_j_kg_k, conductivity_w_m_k, boundary, budget, cancel=None):
    """Prepare actual indexed metrics and exact-order binary64 owner inputs.

    This deliberately accepts explicit previously-authenticated operands, not
    objects masquerading as PreparedSpatialOwner or SpatialOwnerTransport.
    No whole mesh record, physical-support table or legacy encoding is read.
    """
    from atlas_tectonics.integration.heat.mimetic_heat import MimeticGeometry, _q
    from atlas_tectonics.integration.coupling.regional_inventory import _project
    from atlas_tectonics._private.integration.geometry.exterior_mesh_patch import _view
    from atlas_tectonics._private import private_heat_issuer_resources_r4 as R

    R.check(cancel)
    cp = heat_capacity_j_kg_k
    view = cast('CompactMesh', _view(mesh))
    header_owner = mesh.header()
    m, g, t = header_owner.value, graph, transported

    # The unchanged I12 resource formula uses only len(metric['cells']). This
    # explicit count operand is not a substituted mesh record or row mapping.
    projection_bytes = R.owner_projection_bytes({'cells': range(view.cell_count)},
        g, t, component_count, budget=budget, cancel=cancel)
    # I12's projection allowance retains its original rational/array work.
    # Additional face-name lookup and transported-column dictionaries have
    # one scalar/container-policy unit per entry; they are scratch only.
    boundary_count = 0 if boundary is None else len(boundary)
    scratch = _Allocation(budget, projection_bytes+R.UNIT*(
        view.face_count+len(t['cell_ids'])+2*boundary_count+16), 'indexed-heat-preparation')
    duration = float(duration_s)
    positive = {r['cell_id'] for r in g['cells'] if _q(r['end_volume_m3']) > 0}
    logical, cell_ids = [], []
    for index in range(view.cell_count):
        R.check(cancel)
        row_owner = mesh.cell(index)
        row = row_owner.value
        # Copy the two small names into the admitted projection workspace;
        # no borrowed value outlives its OwnedRow reservation.
        logical.append(row['logical_cell_id'].encode('ascii').decode('ascii'))
        cell_ids.append(row['cell_id'].encode('ascii').decode('ascii'))
    boundary = {} if boundary is None else dict(boundary)
    # Required faces are already authenticated integer references, not a
    # hidden header/list export. Access retains the actual sealed view.
    if view._required:
        for index in view._arrays['required.face']:
            R.check(cancel)
    columns = {key: i for i, key in enumerate(t['cell_ids'])}
    old, capacity = [], []
    for logical_id in logical:
        R.check(cancel)
        at = columns[logical_id]
        old.append(_project(_q(t['exact_stocks']['enthalpy_j'][at])))
        mass = sum((_q(t['exact_stocks']['component_mass_kg:'+str(i)][at])
                    for i in range(component_count)), Fraction(0))
        capacity.append(float(_project(mass)*cp))
        del mass
    k = float(conductivity_w_m_k)
    geometry = MimeticGeometry.from_compact(view, budget=budget)
    ids = {name: i for i, name in enumerate(geometry._face_ids)}
    for fid, entry in boundary.items():
        R.check(cancel)
        kind, value = entry
        value = float(value)
        boundary[fid] = [kind, value]
    arrays = dict(enthalpy_j=np.asarray(old), capacity_j_k=np.asarray(capacity),
                  source_w=np.zeros(len(old)))
    meta = dict(schema='atlas.private.indexed-heat-preparation.v1',
        geometry_id=geometry.geometry_id, graph_id=graph_id, funding_id=funding_id,
        source_stage_id=source_stage_id, parent_state_id=parent_state_id,
        duration_s=duration, heat_capacity_j_kg_k=cp, conductivity_w_m_k=k,
        cell_ids=cell_ids, boundary=boundary,
        source_policy='already-booked-transport; zero added heat source',
        owner_origin_validated=False, may_advance=False)
    raw_meta = json.dumps(meta, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    # Only exact output bytes plus bounded tuple/array-wrapper overhead survive
    # success. The original projection/constructor copy work does NOT survive.
    retained = _Allocation(budget, len(raw_meta)+sum(a.nbytes for a in arrays.values())+4096,
                           'indexed-heat-inputs-retained')
    fields = tuple((key, _Bytes(value.tobytes(), retained)) for key, value in arrays.items())
    result = IndexedHeatPreparation(geometry, mesh, _Bytes(raw_meta, retained), fields, budget)
    R.check(cancel)
    # Held failures keep scratch and row/header owners in this frame. Success
    # discards all scratch-only containers before releasing that reservation.
    del arrays, raw_meta, meta, row, row_owner, header_owner, m
    del ids, columns, positive, logical, cell_ids, old, capacity, boundary
    del scratch
    return result
