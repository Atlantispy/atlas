"""Actual complete-grid FV face evidence for physical component integration.

No outer rigid replacement, material mask, divergence allowance or new velocity
projection is supplied here. Geometry consumes this issued evidence and must
close actual component and finite-stock transfers separately.
SPDX-License-Identifier: AGPL-3.0-only
"""
from contextlib import ExitStack
from dataclasses import dataclass, field
from fractions import Fraction as Q
from itertools import product
import hashlib
import json
import weakref

import numpy as np

from . import integration_volume as V
from . import integration_wall_measures as W
from .integration_regional_inventory import _width
from .regional_collar3d import PreparedRegionalCollar3D, RegionalCollarSourceFlowStage
from .resources import WorkBudget


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _vector(value):
    return [V._encoded(v) for v in value]


def _q2_face_polynomial(nodal_values):
    """Exact tensor Lagrange trace at (0,1/2,1)^2, not sample fitting."""
    basis = ((1, -3, 2), (0, 4, -4), (0, -1, 2))
    return {(i, j): sum((nodal_values[3*a+b]*basis[a][i]*basis[b][j]
            for a in range(3) for b in range(3)), Q(0)) for i in range(3) for j in range(3)}


def _evaluate(polynomial, s, t):
    return sum((value*s**i*t**j for (i, j), value in polynomial.items()), Q(0))


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class NativeFaceMeasures:
    _json: bytes = field(repr=False)
    _resource: object = field(repr=False, compare=False)
    _collar: object = field(repr=False, compare=False)
    _stage: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('NativeFaceMeasures is issued by measure_native_faces')

    @property
    def measure_id(self):
        return hashlib.sha256(self._json).hexdigest()

    def record(self):
        return json.loads(self._json)

    def validate_source(self, collar, source_flow_stage):
        if collar is not self._collar or source_flow_stage is not self._stage:
            raise V.VolumeError('native face evidence belongs to another actual source/flow stage')
        collar._check_source_flow_stage(source_flow_stage)


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class ComponentNormalPolynomial:
    """Issued chart transformation, not a component ownership/flux certificate."""
    _json: bytes = field(repr=False)
    _resource: object = field(repr=False, compare=False)
    _measures: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('component polynomials are issued from actual NativeFaceMeasures')

    @property
    def polynomial_id(self):
        return hashlib.sha256(self._json).hexdigest()

    def record(self):
        return json.loads(self._json)

    def validate_source(self, measures):
        if type(measures) is not NativeFaceMeasures or measures is not self._measures:
            raise V.VolumeError('component polynomial belongs to another actual native measure')
        measures.validate_source(measures._collar, measures._stage)

    @property
    def polynomial(self):
        with self._resource.reserve(65536+8*len(self._json), category='component-normal-decode'):
            return tuple((i, j, W._decode(q)) for i, j, q in self.record()['normal_polynomial_m_s'])


def _component_chart_polynomial(native_face, target_face, polynomial, increasing_normal):
    """Exact scalar pullback to dimensional u/v, with outward-normal sign."""
    from .integration_differential_trace import _contact_queries, POWERS
    outward = target_face[3]
    sign = V._dot(outward, increasing_normal)
    if sign not in (-1, 1) or tuple(sign*q for q in increasing_normal) != outward:
        raise V.VolumeError('component target normal is not parallel to the actual native normal')
    # Reuse the exact opposite-contact affine proof; the target can be either
    # side of a native face. Its own outward orientation is applied below.
    query_face = (*native_face[:3], tuple(-q for q in outward), native_face[4])
    queries = dict(zip(POWERS, _contact_queries(query_face, target_face)))
    transformed = {}
    for power, coefficient in polynomial.items():
        for i, j, value in queries[power]:
            transformed[i, j] = transformed.get((i, j), Q(0))+sign*coefficient*value
    return ({p: q for p, q in transformed.items() if q}, sign,
            (queries[(1, 0)], queries[(0, 1)]))


def component_normal_polynomial(measures, face_id, voxel, axis, end, *, budget, projection=None):
    """Transform the solved Q2 normal trace onto one exact physical rectangle.

    The native face and target rectangle must be coplanar with parallel/opposite
    normals and exact full containment. No AABB, velocity fitting or snapping
    is used. W._face's dimensional orthonormal u/v coordinates have unit area
    Jacobian; normalised native-coordinate derivatives retain their true scale.
    The caller's issued component partition must separately prove ownership.
    """
    if (type(measures) is not NativeFaceMeasures or type(voxel) is not V.CartesianCell or
            type(budget) is not WorkBudget or measures._resource is not budget or voxel._resource is not budget or
            type(axis) is not int or axis not in (0, 1, 2) or type(end) is not int or end not in (0, 1) or
            type(face_id) is not str):
        raise V.VolumeError('actual native measures, target Cartesian face and shared budget required')
    measures.validate_source(measures._collar, measures._stage)
    projection_width = 0
    if projection is not None:
        from .integration_native_projection import NativeFluxProjection
        if type(projection) is not NativeFluxProjection or projection._resource is not budget:
            raise V.VolumeError('issued same-budget native normal projection required')
        projection.validate_source(measures)
        projection_width = len(projection._json)
    with budget.reserve(131072+8*(len(measures._json)+projection_width)+8*_width(voxel.record()), category='component-normal-chart'):
        record = measures.record()
        selected = [r for r in record['faces'] if r['face_id'] == face_id]
        if len(selected) != 1:
            raise V.VolumeError('one face in the actual native measure is required')
        row = selected[0]
        index = row['lower'] if row['lower'] is not None else row['upper']
        native_cell = V.CartesianCell.from_record(record['cells'][index]['geometry'], budget=budget)
        native_face = W._face(native_cell, row['axis'], int(row['lower'] is not None))
        target = W._face(voxel, axis, end)
        polynomial = {(i, j): W._decode(q) for i, j, q in row['mechanical_normal_polynomial_m_s']}
        increment = Q(0)
        if projection is not None:
            projected = next(r for r in projection.record()['faces'] if r['face_id'] == face_id)
            increment = W._decode(projected['normal_increment_m_s'])
            polynomial[0, 0] = polynomial.get((0, 0), Q(0))+increment
        increasing = tuple(map(W._decode, row['chart']['increasing_normal']))
        values = (*native_cell._geometry(), *voxel._geometry(), *polynomial.values())
        with V._work(values, budget):
            transformed, sign, queries = _component_chart_polynomial(native_face, target, polynomial, increasing)
            encode = lambda p: [[i, j, V._encoded(q)] for (i, j), q in sorted(p.items()) if q]
            derivatives = tuple({(i-int(k == 0), j-int(k == 1)): q*(i if k == 0 else j)
                for (i, j), q in transformed.items() if (i if k == 0 else j)} for k in (0, 1))
            integral = sum((q*((target[4][0][1]**(i+1)-target[4][0][0]**(i+1))/Q(i+1))*
                ((target[4][1][1]**(j+1)-target[4][1][0]**(j+1))/Q(j+1))
                for (i, j), q in transformed.items()), Q(0))
            coordinate = tuple({(i, j): q for i, j, q in query} for query in queries)
            jacobian = tuple(tuple(p.get(k, Q(0)) for k in ((1, 0), (0, 1))) for p in coordinate)
            output = dict(schema='atlas.native-component-normal-polynomial.v1',
                native_measure_id=measures.measure_id, native_face_id=face_id,
                native_physical_cell_id=native_cell.cell_id, target_physical_cell_id=voxel.cell_id,
                target_cell=voxel.record(), target_axis=axis, target_end=end,
                **{k: record[k] for k in ('collar_plan_id', 'parent_state_id', 'source_flow_stage_id',
                    'flow_id', 'mechanical_result_id', 'volume_map_id', 'source', 'start_time_s', 'end_time_s', 'duration_s')},
                chart=dict(origin_m=_vector(target[0]), tangents=[_vector(v) for v in target[1:3]],
                    outward_normal=_vector(target[3]), bounds_m=[_vector(v) for v in target[4]],
                    normal_sign=int(sign), surface_area_jacobian=V._encoded(Q(1)),
                    native_normalised_coordinates=[encode(p) for p in coordinate],
                    native_normalised_coordinate_jacobian=[_vector(v) for v in jacobian]),
                normal_polynomial_m_s=encode(transformed), derivative_u_s_1=encode(derivatives[0]),
                derivative_v_s_1=encode(derivatives[1]),
                exact_mechanical_signed_volume_m3=V._encoded(integral*W._decode(record['duration_s'])),
                native_face_numerical_evidence={k: row[k] for k in ('raw_sampling_residual_m_s',
                    'fv_sample_correction_m_s', 'represented_gauss_minus_mechanical_volume_m3',
                    'booked_minus_mechanical_volume_m3')},
                scope='exact mechanical Q2 chart only; no component ownership, sign-split flux or FV correction allocation')
            if projection is not None:
                signed = integral*W._decode(record['duration_s'])
                area = (target[4][0][1]-target[4][0][0])*(target[4][1][1]-target[4][1][0])
                correction = sign*increment*area*W._decode(record['duration_s'])
                output.update(schema='atlas.native-component-normal-polynomial.v2',
                    native_projection_id=projection.projection_id,
                    numerical_normal_increment_m_s=V._encoded(sign*increment),
                    exact_signed_volume_m3=V._encoded(signed),
                    exact_mechanical_signed_volume_m3=V._encoded(signed-correction),
                    exact_numerical_volume_correction_m3=V._encoded(correction),
                    scope='mechanical Q2 plus issued one-face numerical offset; component ownership and signed-stream integration remain required')
        with budget.reserve(65536+4*_width(output), category='component-normal-encode'):
            encoded = _json(output)
            lease = budget.reserve(8192+4*len(encoded), category='component-normal-retained')
            lease.__enter__()
            try:
                result = object.__new__(ComponentNormalPolynomial)
                for key, value in dict(_json=encoded, _resource=budget, _measures=measures).items():
                    object.__setattr__(result, key, value)
                weakref.finalize(result, lease.__exit__, None, None, None)
            except BaseException:
                lease.__exit__(None, None, None); raise
        measures.validate_source(measures._collar, measures._stage)
        return result


def measure_native_faces(collar, source_flow_stage, *, budget):
    """Retain both booked binary integrals and exact represented Gauss sums.

    The increasing-coordinate normal is used on both sides. Outer ``side``
    supplies its outward sign. Opposed streams remain the existing 3x3 positive-
    part Gauss discretisation, not an asserted exact sign-split Q2 integral.
    A nonzero exact outer net is exposed, never removed or used as uncertainty.
    """
    if (type(collar) is not PreparedRegionalCollar3D or
            type(source_flow_stage) is not RegionalCollarSourceFlowStage or
            type(budget) is not WorkBudget or collar._budget is not budget or
            source_flow_stage._owner is not collar or collar.mechanics_scope != 'complete-grid'):
        raise V.VolumeError('actual complete-grid source/flow and shared budget required')
    collar._check_source_flow_stage(source_flow_stage)
    flow, clock = source_flow_stage.flow, source_flow_stage.record()
    mechanics = source_flow_stage.source_stage.initial_mechanics
    if flow.descriptor()['source_result_id'] != mechanics.result_id:
        raise V.VolumeError('native flow does not name the actual mechanical nodal trace')
    duration = Q(source_flow_stage.duration_s)
    shape = tuple(collar.cells)
    flat = lambda p: (p[0]*shape[1]+p[1])*shape[2]+p[2]
    with ExitStack() as scratch:
        scratch.enter_context(budget.reserve(65536, category='native-face-evidence'))
        boxes = collar.cell_geometries()
        mapping = collar._map.record()
        cells, faces = [], []
        for index, box in enumerate(boxes):
            row = dict(index=index, cell_id=box.cell_id, physical_cell_id=box.cell_id,
                       volume_m3=V._encoded(box.volume_m3), geometry=box.record())
            scratch.enter_context(budget.reserve(4096+8*_width(row), category='native-face-cell-evidence'))
            cells.append(row)
        weights = tuple(Q(float(v)) for v in collar._transport._face_weights)
        abscissas = tuple(Q(float(v)) for v in np.polynomial.legendre.leggauss(3)[0])
        velocity = mechanics.array('velocity_m_s').reshape(*(2*n+1 for n in shape), 3)
        speed = max((abs(Q(float(v))) for label in 'xyz' for v in
                     source_flow_stage.source_stage.flow.array('raw_normal_'+label+'_m_s').flat), default=Q(0))
        outer_net, largest_old = Q(0), Q(0)
        for axis, label in enumerate('xyz'):
            for at in product(*(range(n+int(j == axis)) for j, n in enumerate(shape))):
                below, above = list(at), list(at)
                below[axis] -= 1
                lower = None if at[axis] == 0 else flat(below)
                upper = None if at[axis] == shape[axis] else flat(above)
                selected = lower if lower is not None else upper
                box = boxes[selected]
                end = int(lower is not None)
                side = label+str(end) if lower is None or upper is None else None
                raw_f = tuple(float(v) for v in flow.array('raw_normal_'+label+'_m_s')[at])
                normal_f = tuple(float(v) for v in flow.array('normal_'+label+'_m_s')[at])
                transverse = [j for j in range(3) if j != axis]
                trace_nodes = []
                for a, b in product(range(3), repeat=2):
                    node = [2*i for i in at]
                    node[transverse[0]] += a; node[transverse[1]] += b
                    trace_nodes.append(tuple(node))
                nodal_f = tuple(float(velocity[(*node, axis)]) for node in trace_nodes)
                area_f = float(collar._transport._areas[axis])
                booked_f = tuple(float(flow.array(name+'_'+label+'_m3_s')[at]) for name in ('positive', 'negative'))
                physical = (*box.lower_m, *box.upper_m, *box.origin_m, *(v for r in box.basis for v in r))
                with V._work((*raw_f, *normal_f, *nodal_f, area_f, *booked_f, duration,
                              *weights, *abscissas, *physical), budget):
                    raw, normals = tuple(map(Q, raw_f)), tuple(map(Q, normal_f))
                    nodal = tuple(map(Q, nodal_f))
                    polynomial = _q2_face_polynomial(nodal)
                    sampled = tuple(_evaluate(polynomial, (s+1)/2, (t+1)/2)
                                    for s, t in product(abscissas, repeat=2))
                    area = Q(area_f)
                    factor = area*duration
                    positive, negative = (factor*sum((max(sign*v, Q(0))*w for v, w in zip(normals, weights)), Q(0))
                                          for sign in (1, -1))
                    old = max(abs(a-b) for a, b in zip(raw, normals))
                    largest_old = max(largest_old, old)
                    local = list(box.lower_m)
                    local[axis] = (box.lower_m, box.upper_m)[end][axis]
                    origin = tuple(box.origin_m[i]+sum(box.basis[i][j]*local[j] for j in range(3)) for i in range(3))
                    spans = tuple(tuple(box.basis[i][j]*(box.upper_m[j]-box.lower_m[j]) for i in range(3))
                                  for j in transverse)
                    physical_area = (box.upper_m[transverse[0]]-box.lower_m[transverse[0]])*(
                        box.upper_m[transverse[1]]-box.lower_m[transverse[1]])
                    exact_volume = physical_area*duration*sum(
                        (q/Q((i+1)*(j+1)) for (i, j), q in polynomial.items()), Q(0))
                    outward = (-1 if lower is None else 1) if side is not None else None
                    if outward is not None:
                        outer_net += outward*(positive-negative)
                    row = dict(axis=axis, index=list(at), lower=lower, upper=upper, side=side,
                        area_m2=V._encoded(area), physical_area_m2=V._encoded(physical_area),
                        duration_s=V._encoded(duration), weights=_vector(weights),
                        raw_normals_m_s=_vector(raw), normals_m_s=_vector(normals),
                        exact_gauss_positive_m3=V._encoded(positive), exact_gauss_negative_m3=V._encoded(negative),
                        exact_gauss_net_m3=V._encoded(positive-negative),
                        booked_positive_m3=V._encoded(Q(booked_f[0])*duration),
                        booked_negative_m3=V._encoded(Q(booked_f[1])*duration),
                        old_normal_correction_m_s=V._encoded(old),
                        mechanical_normal_polynomial_m_s=[[i, j, V._encoded(q)] for (i, j), q
                            in sorted(polynomial.items()) if q],
                        mechanical_trace_node_indices=[list(node) for node in trace_nodes],
                        mechanical_trace_nodal_values_m_s=_vector(nodal),
                        raw_sampling_residual_m_s=_vector(a-b for a, b in zip(raw, sampled)),
                        fv_sample_correction_m_s=_vector(a-b for a, b in zip(normals, raw)),
                        mechanical_exact_signed_volume_m3=V._encoded(exact_volume),
                        chart=dict(origin_m=_vector(origin), span_vectors_m=[_vector(v) for v in spans],
                            increasing_normal=_vector(tuple(box.basis[i][axis] for i in range(3))),
                            outward_sign=outward, transverse_axes=transverse,
                            gauss_abscissas=_vector(abscissas), gauss_order='first transverse axis outer, second inner'))
                    row['face_id'] = hashlib.sha256(_json(dict(flow_id=flow.flow_id, axis=axis, index=list(at)))).hexdigest()
                    row['represented_gauss_minus_mechanical_volume_m3'] = V._encoded(positive-negative-exact_volume)
                    row['booked_minus_mechanical_volume_m3'] = V._encoded(
                        Q(booked_f[0])*duration-Q(booked_f[1])*duration-exact_volume)
                    scratch.enter_context(budget.reserve(4096+8*_width(row), category='native-face-row-evidence'))
                    faces.append(row)
        plan = collar._native._transport
        record = dict(schema='atlas.complete-grid-native-face-measures.v2',
            collar_plan_id=collar.plan_id, parent_state_id=source_flow_stage.parent_state_id,
            source_flow_stage_id=source_flow_stage.result_id, flow_id=flow.flow_id,
            mechanical_result_id=mechanics.result_id,
            source=mapping['source'], volume_map_id=collar._map.volume_map_id,
            component_keys=[list(k) for k in sorted({(r['patch_id'], r['sublayer']) for r in mapping['cell_sources']})],
            start_time_s=V._encoded(Q(clock['start_time_s'])), end_time_s=V._encoded(Q(clock['end_time_s'])),
            duration_s=V._encoded(duration), mechanics_scope='complete-grid', cells=cells, faces=faces,
            absolute_limit_m_s=V._encoded(Q(plan.max_velocity_correction_m_s)),
            relative_limit=V._encoded(Q(plan.max_relative_correction)),
            original_native_speed_scale_m_s=V._encoded(speed), old_normal_correction_max_m_s=V._encoded(largest_old),
            outer_signed_net_volume_m3=V._encoded(outer_net), source_normal_samples_changed=False,
            integral_rule='exact sum of represented 3x3 Gauss positive/negative streams; original booked binary values retained',
            polynomial_rule='exact represented mechanical Q2 nodal trace on origin+s*span0+t*span1, 0<=s,t<=1; '
                            'sample arithmetic and FV corrections retained separately, never relabelled physical velocity',
            geometry_authority='native physical faces only; no exterior component partition or completed GCL certificate')
        if collar._registry is not None:
            record['component_registry_id'] = collar._registry.registry_id
            record['component_keys'] = [list(k) for k in collar._registry.source_keys]
        scratch.enter_context(budget.reserve(65536+4*_width(record), category='native-face-encode'))
        encoded = _json(record)
        lease = budget.reserve(8192+4*len(encoded), category='native-face-retained')
        lease.__enter__()
        try:
            result = object.__new__(NativeFaceMeasures)
            for name, value in dict(_json=encoded, _resource=budget, _collar=collar, _stage=source_flow_stage).items():
                object.__setattr__(result, name, value)
            weakref.finalize(result, lease.__exit__, None, None, None)
        except BaseException:
            lease.__exit__(None, None, None); raise
        collar._check_source_flow_stage(source_flow_stage)
        return result
