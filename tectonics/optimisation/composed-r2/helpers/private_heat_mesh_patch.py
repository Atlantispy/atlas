"""Indexed private-heat input preparation, NOT a heat call or acceptance.

The supplied graph/transport/scalar operands are caller-owned and must have
already been authenticated by the actual owner route. This preparation checks
their scientific relationship to the actual compact mesh, and preserves I12's
exact projection and mass-sum operation order. It does not authenticate owner
history, execution, source code or a saved checkpoint; it cannot advance.

The exact source transform appends an explicit preparation-only entrypoint.
It leaves bind_owner_call, all source pins and the ordinary forward/cold routes
unchanged. In particular _verify_call_record still requires legacy _encoded,
and joined finish still embeds a full thermal_mesh. Neither is bypassed here.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import math

import numpy as np


BASE_ISSUER_SHA256 = 'e42649f848397551da18263322775441f664922538f204c1e47962f97481d3d6'


class IndexedHeatRefused(ValueError):
    pass


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
        from mesh_tables import OwnedRow, _decode_charge
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
    from atlas_tectonics.integration_exterior_mesh import ExteriorMesh
    from atlas_tectonics.integration_mimetic_heat import MimeticGeometry, _q
    from atlas_tectonics.integration_regional_inventory import _project
    from atlas_tectonics.resources import WorkBudget
    from exterior_mesh_patch import _view
    import private_heat_issuer_resources_r4 as R

    R.check(cancel)
    if (type(mesh) is not ExteriorMesh or not mesh.is_compact or
            type(budget) is not WorkBudget or mesh._resource is not budget):
        raise IndexedHeatRefused('actual indexed ExteriorMesh and shared WorkBudget required')
    import live_spatial_patch as LIVE_SPATIAL
    if not LIVE_SPATIAL.is_record(graph) or not LIVE_SPATIAL.is_record(transported):
        raise IndexedHeatRefused('explicit caller-owned graph and transported records required')
    for identity in (graph_id, funding_id, source_stage_id, parent_state_id):
        if (type(identity) is not str or len(identity) != 64 or
                any(c not in '0123456789abcdef' for c in identity)):
            raise IndexedHeatRefused('explicit canonical source operand IDs required')
    if type(component_count) is not int or component_count <= 0:
        raise IndexedHeatRefused('original positive component count required')
    cp = heat_capacity_j_kg_k
    if type(cp) not in (int, float) or not math.isfinite(cp) or cp <= 0:
        raise IndexedHeatRefused('original positive finite material heat capacity required')
    view = _view(mesh)
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
    if (not math.isfinite(duration) or duration <= 0 or
            _q(g['end_time_s'])-_q(g['start_time_s']) != Fraction(duration) or
            g['source_flow_stage_id'] != source_stage_id or
            t['source_stage_id'] != source_stage_id or t['state_id'] != parent_state_id):
        raise IndexedHeatRefused('actual source, transported state and physical interval differ')
    if (m['funding_id'] != funding_id or m['funding_id'] != g['funding_id'] or
            ('source' in m) != ('source' in g) or m.get('source') != g.get('source') or
            m['support_id'] != g['end_support_id'] or m['grid_id'] != g['grid_id'] or
            m['trajectory_id'] != g['trajectory_id'] or m['time_s'] != g['end_time_s']):
        raise IndexedHeatRefused('thermal geometry is not this transported endpoint')
    if 'booked_cell_rule' in m and (type(m['booked_cell_rule']) is not dict or
            m['booked_cell_rule'].get('closed_graph_id') != graph_id):
        raise IndexedHeatRefused('thermal cells were booked by a different graph')
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
    if set(logical) != positive:
        raise IndexedHeatRefused('every positive transported cell must remain represented')
    boundary = {} if boundary is None else dict(boundary)
    # Required faces are already authenticated integer references, not a
    # hidden header/list export. Access retains the actual sealed view.
    if view._required:
        for index in view._arrays['required.face']:
            R.check(cancel)
            if view.face_id(int(index)) not in boundary:
                raise IndexedHeatRefused('required physical boundaries must be explicitly supplied')
    columns = {key: i for i, key in enumerate(t['cell_ids'])}
    if len(columns) != len(t['cell_ids']):
        raise IndexedHeatRefused('transported cell order contains duplicates')
    old, capacity = [], []
    for logical_id in logical:
        R.check(cancel)
        at = columns[logical_id]
        old.append(_project(_q(t['exact_stocks']['enthalpy_j'][at])))
        mass = np.asarray([_project(_q(t['exact_stocks']['component_mass_kg:'+str(i)][at]))
                           for i in range(component_count)])
        capacity.append(float(np.sum(mass)*cp))
    k = float(conductivity_w_m_k)
    if not math.isfinite(k) or k <= 0:
        raise IndexedHeatRefused('uniform positive owner conductivity required')
    geometry = MimeticGeometry.from_compact(view, budget=budget)
    ids = {name: i for i, name in enumerate(geometry._face_ids)}
    for fid, entry in boundary.items():
        R.check(cancel)
        if fid not in ids or len(geometry._incidence[ids[fid]]) != 1:
            raise IndexedHeatRefused('boundary must name an actual one-owner face')
        if type(entry) not in (list, tuple) or len(entry) != 2:
            raise IndexedHeatRefused('typed thermal boundary pair required')
        kind, value = entry
        value = float(value)
        if (not math.isfinite(value) or kind not in ('temperature', 'power') or
                kind == 'temperature' and value <= 0):
            raise IndexedHeatRefused('finite physical boundary declaration required')
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
    del arrays, raw_meta, meta, mass, row, row_owner, header_owner, m
    del ids, columns, positive, logical, cell_ids, old, capacity, boundary
    del scratch
    return result


_ENTRY = '''

def prepare_indexed_mesh_inputs(mesh, graph, transported, *, graph_id, funding_id,
        source_stage_id, parent_state_id, duration_s, component_count,
        heat_capacity_j_kg_k, conductivity_w_m_k, boundary, budget, cancel=None):
    """Preparation only; does not issue an OwnerHeatCall or validate provenance."""
    from private_heat_mesh_patch import prepare_indexed_inputs
    return prepare_indexed_inputs(mesh, graph, transported, graph_id=graph_id,
        funding_id=funding_id, source_stage_id=source_stage_id,
        parent_state_id=parent_state_id, duration_s=duration_s,
        component_count=component_count, heat_capacity_j_kg_k=heat_capacity_j_kg_k,
        conductivity_w_m_k=conductivity_w_m_k, boundary=boundary, budget=budget, cancel=cancel)
'''


def issuer_source(source):
    """Append only the explicit preparation API to the exact reviewed issuer."""
    if type(source) is not str or hashlib.sha256(source.encode()).hexdigest() != BASE_ISSUER_SHA256:
        raise IndexedHeatRefused('private issuer source differs from reviewed base')
    return source+_ENTRY
