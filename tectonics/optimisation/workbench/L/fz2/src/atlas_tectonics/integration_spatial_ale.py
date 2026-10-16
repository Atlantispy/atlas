"""Certified Cartesian space-time measures for the retained rigid exterior.

Physical cells are moving cone/radial-shell material intersected with FIXED
Cartesian voxels, not the thermal mesh's planar radial surrogate. Cone and
radial interfaces have exactly zero relative flux. Cartesian interfaces use
the existing full-interval enclosure, including zero-endpoint transit.

An exact lower/upper-capacity circulation chooses one jointly conservative
representative. It neither normalises mass nor turns a divergence tolerance
into face uncertainty. Infeasible supplied native fluxes are refused.
SPDX-License-Identifier: AGPL-3.0-only
"""
from collections import deque
from dataclasses import dataclass, field
from fractions import Fraction as Q
from itertools import product
import hashlib
import json
import math
import weakref

from . import integration_volume as V
from . import integration_volume_bounds as B
from . import integration_collar_geometry as F
from . import integration_exterior_mesh as E
from . import integration_wall_measures as W
from .resources import WorkBudget


class GCLInfeasible(V.VolumeError):
    """Exact cut certificate; no numerical or physical bound was relaxed."""
    def __init__(self, nodes, incoming_lower, outgoing_upper, unsatisfied):
        super().__init__('certified volume/face bounds have no exact GCL circulation; no flux or volume repair applied')
        self.cut_cell_ids = tuple(nodes)
        self.incoming_lower_m3 = incoming_lower
        self.outgoing_upper_m3 = outgoing_upper
        self.unsatisfied_m3 = unsatisfied


def _encoded(record):
    return json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _issue(cls, record, budget):
    encoded = _encoded(record)
    lease = budget.reserve(8192+4*len(encoded), category='spatial-ale-retained')
    lease.__enter__()
    try:
        result = object.__new__(cls)
        object.__setattr__(result, '_json', encoded)
        object.__setattr__(result, '_resource', budget)
        weakref.finalize(result, lease.__exit__, None, None, None)
        return result
    except BaseException:
        lease.__exit__(None, None, None)
        raise


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class SpatialALEBounds:
    _json: bytes = field(repr=False)
    _resource: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('spatial bounds are issued by enclose_spatial_ale()')

    @property
    def bounds_id(self):
        return hashlib.sha256(self._json).hexdigest()

    def record(self):
        return json.loads(self._json)


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class SpatialALEGraph:
    _json: bytes = field(repr=False)
    _resource: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('closed spatial graphs are issued by close_spatial_ale()')

    @property
    def geometry_id(self):
        return hashlib.sha256(self._json).hexdigest()

    def record(self):
        return json.loads(self._json)


def _circulation(nodes, edges, arena):
    """Exact feasible bounded circulation, via residual augmenting paths.

    Each edge is (donor, receiver, lower, upper). No tolerances or floating
    graph arithmetic. Work is finite (Edmonds--Karp) and charged per search;
    intermediate rational sizes use the shared arithmetic admission.
    """
    labels = {key: i for i, key in enumerate(nodes)}
    if len(labels) != len(nodes):
        raise V.VolumeError('unique circulation node identities required')
    count = len(nodes)
    adjacency = [[] for _ in range(count+2)]
    balance = [Q(0)]*count
    def add(i, j, capacity):
        forward = [j, len(adjacency[j]), capacity]
        reverse = [i, len(adjacency[i]), Q(0)]
        adjacency[i].append(forward); adjacency[j].append(reverse)
        return forward
    saved = []
    for a, b, lo, hi in edges:
        if a not in labels or b not in labels or a == b or lo < 0 or hi < lo:
            raise V.VolumeError('invalid bounded circulation edge')
        i, j = labels[a], labels[b]
        balance[i] -= lo; balance[j] += lo
        saved.append((add(i, j, hi-lo), lo, hi))
    source, sink, required = count, count+1, Q(0)
    for i, value in enumerate(balance):
        if value > 0:
            add(source, i, value); required += value
        elif value < 0:
            add(i, sink, -value)
    arena.keep((*balance, *(q for edge in edges for q in edge[2:])), 8*(len(edges)+count))
    sent = Q(0)
    while sent < required:
        previous = [None]*(count+2); previous[source] = (-1, -1)
        queue, visits = deque((source,)), 0
        while queue and previous[sink] is None:
            i = queue.popleft()
            for ei, (j, _, capacity) in enumerate(adjacency[i]):
                visits += 1
                if capacity > 0 and previous[j] is None:
                    previous[j] = (i, ei); queue.append(j)
        # The same byte-equivalent predicate allowance as the geometry arena,
        # charged to actual examined arcs, not 64 copies of the ENTIRE graph
        # for every (often very short) search. Rational scratch is separately
        # reserved below. Edmonds--Karp still supplies a finite O(V E^2) cap.
        arena.work(count+2+2*visits)
        if previous[sink] is None:
            cut = {key for key, i in labels.items() if previous[i] is not None}
            incoming = sum((lo for a, b, lo, hi in edges if a not in cut and b in cut), Q(0))
            outgoing = sum((hi for a, b, lo, hi in edges if a in cut and b not in cut), Q(0))
            if incoming-outgoing != required-sent or incoming <= outgoing:
                raise V.VolumeError('internal bounded-circulation cut certificate failure')
            raise GCLInfeasible(sorted(cut), incoming, outgoing, required-sent)
        path, at = [], sink
        while at != source:
            i, ei = previous[at]; path.append((i, ei)); at = i
        arena.work(4*len(path))
        amount = min(adjacency[i][ei][2] for i, ei in path)
        with V._work((amount, sent, *(adjacency[i][ei][2] for i, ei in path)), arena.resource):
            for i, ei in path:
                j, ri, capacity = adjacency[i][ei]
                adjacency[i][ei][2] = capacity-amount
                adjacency[j][ri][2] += amount
            sent += amount
    return tuple(hi-edge[2] for edge, lo, hi in saved)


def _audit_outer_face(row, physical_normals, physical_streams, *, speed_scale, absolute_limit, relative_limit, budget):
    """Audit SAME affine rigid field, separating quadrature from field change.

    Positive-part Gauss quadrature is not exact when an affine normal changes
    sign inside a face. Replacing that integral by its analytic value changes
    no velocity. Only sample differences and the equivalent NET arithmetic
    representation correction consume the original normal-change allowance.
    """
    with V._work((*row['normals'], *row['raw_normals'], *physical_normals,
                  *row['weights'], *physical_streams, row['area_m2'], row['duration_s']), budget):
        weights = row['weights']; factor = row['area_m2']*row['duration_s']
        if factor <= 0 or len(physical_normals) != len(weights) or any(w <= 0 for w in weights):
            raise V.VolumeError('positive physical wall area/time and matching quadrature required')
        integrate = lambda values, sign: factor*sum((max(sign*v, Q(0))*w for v, w in zip(values, weights)), Q(0))
        sampled = tuple(integrate(row['normals'], sign) for sign in (1, -1))
        true_gauss = tuple(integrate(physical_normals, sign) for sign in (1, -1))
        old = max(abs(a-b) for a, b in zip(row['normals'], row['raw_normals']))
        pointwise = max(abs(a-b) for a, b in zip(row['normals'], physical_normals))
        net_delta = (physical_streams[0]-physical_streams[1])-(true_gauss[0]-true_gauss[1])
        arithmetic_equivalent = abs(net_delta)/(factor*sum(weights, Q(0)))
        total = old+pointwise+arithmetic_equivalent
        if total > absolute_limit or (total and (not speed_scale or total > relative_limit*speed_scale)):
            raise V.VolumeError('outer rigid sample plus net arithmetic correction exceeds ORIGINAL transport allowance')
        return dict(exact_sampled_gauss_positive_m3=sampled[0], exact_sampled_gauss_negative_m3=sampled[1],
            exact_physical_gauss_positive_m3=true_gauss[0], exact_physical_gauss_negative_m3=true_gauss[1],
            physical_positive_m3=physical_streams[0], physical_negative_m3=physical_streams[1],
            positive_part_quadrature_difference_m3=physical_streams[0]-true_gauss[0],
            negative_part_quadrature_difference_m3=physical_streams[1]-true_gauss[1],
            old_normal_correction_m_s=old, sample_to_physical_normal_correction_m_s=pointwise,
            signed_net_arithmetic_volume_correction_m3=net_delta,
            net_arithmetic_equivalent_normal_m_s=arithmetic_equivalent, total_normal_correction_bound_m_s=total)


def _project_native(nodes, faces, boundary_outflow, *, speed_scale, absolute_limit, relative_limit, budget):
    """Exact residual elimination on interior faces under ORIGINAL allowances.

    The source/mechanical samples are immutable. The graph explicitly uses a
    corrected FV integral. A uniform equivalent normal increment is integrated
    at the same represented Gauss samples, so opposed streams remain positive
    parts of ONE corrected field, rather than unrelated added/removed fluxes.
    Fixed physical boundary integrals cannot be changed by this operation.
    """
    residual = {key: Q(boundary_outflow.get(key, 0)) for key in nodes}
    if sum(residual.values(), Q(0)):
        raise V.VolumeError('fixed physical outer wall has nonzero global flux; interior correction cannot repair it')
    if len(residual) != len(nodes):
        raise V.VolumeError('unique native projection cell identities required')
    adjacent = {key: [] for key in nodes}
    with B._Arena(budget) as arena:
        arena.keep(tuple(residual.values()), 16*(len(nodes)+len(faces)))
        original = []
        for i, row in enumerate(faces):
            a, b, normals, weights = row['donor'], row['receiver'], row['normals'], row['weights']
            if a not in residual or b not in residual or a == b or any(w <= 0 for w in weights):
                raise V.VolumeError('valid native interior face and positive represented quadrature weights required')
            with V._work((*normals, *row['raw_normals'], *weights, row['area_m2'], row['duration_s']), budget):
                factor = row['area_m2']*row['duration_s']
                positive = sum((max(v, Q(0))*w for v, w in zip(normals, weights)), Q(0))*factor
                negative = sum((max(-v, Q(0))*w for v, w in zip(normals, weights)), Q(0))*factor
                net = positive-negative
                residual[a] += net; residual[b] -= net
            original.append((positive, negative))
            adjacent[a].append((b, i, 1)); adjacent[b].append((a, i, -1))
        # Deterministic C-order/grid-face traversal, not a hash-name ordering.
        parents = {nodes[0]: None}; order = [nodes[0]]
        for at in order:
            for other, fi, sign in adjacent[at]:
                if other not in parents:
                    parents[other] = (at, fi, -sign); order.append(other)
        if len(order) != len(nodes):
            raise V.VolumeError('native interior correction graph is disconnected')
        delta = [Q(0)]*len(faces)
        for at in reversed(order[1:]):
            parent, fi, sign = parents[at]
            with V._work((residual[at], residual[parent]), budget):
                delta[fi] = -sign*residual[at]
                residual[parent] += residual[at]; residual[at] = Q(0)
        if residual[order[0]]:
            raise V.VolumeError('exact native projection failed fixed-boundary compatibility')
        arena.work(8*(len(nodes)+len(faces)))
        result, maximum = [], Q(0)
        for row, before, dv in zip(faces, original, delta):
            with V._work((*row['normals'], *row['raw_normals'], *row['weights'], dv, row['area_m2'], row['duration_s']), budget):
                factor = row['area_m2']*row['duration_s']
                du = dv/(factor*sum(row['weights'], Q(0)))
                values = tuple(v+du for v in row['normals'])
                positive = sum((max(v, Q(0))*w for v, w in zip(values, row['weights'])), Q(0))*factor
                negative = sum((max(-v, Q(0))*w for v, w in zip(values, row['weights'])), Q(0))*factor
                old = max((abs(a-b) for a, b in zip(row['normals'], row['raw_normals'])), default=Q(0))
                total = old+abs(du)       # no reclaimed budget from cancellation
                maximum = max(maximum, total)
                if total > absolute_limit or (total and (not speed_scale or total > relative_limit*speed_scale)):
                    raise V.VolumeError('total original plus exact FV normal correction exceeds ORIGINAL transport allowance')
                if positive-negative != before[0]-before[1]+dv:
                    raise V.VolumeError('exact opposed-stream projection identity failed')
                result.append(dict(positive=positive, negative=negative, original_positive=before[0], original_negative=before[1],
                    normal_increment_m_s=du, old_normal_correction_m_s=old, total_normal_correction_bound_m_s=total,
                    signed_net_volume_correction_m3=dv))
        check = {key: Q(boundary_outflow.get(key, 0)) for key in nodes}
        for row, value in zip(faces, result):
            q = value['positive']-value['negative']; check[row['donor']] += q; check[row['receiver']] -= q
        if any(check.values()):
            raise V.VolumeError('exact native FV cell continuity failed')
        return result, dict(method='exact-interior-spanning-tree-FV-residual-v1',
            absolute_limit_m_s=E._enc(absolute_limit), relative_limit=E._enc(relative_limit),
            original_native_speed_scale_m_s=E._enc(speed_scale), total_normal_correction_bound_m_s=E._enc(maximum),
            fixed_outer_physical_flux_m3=E._enc(0), source_normal_samples_changed=False,
            rule='explicit FV integrals; old plus new normal correction charged without cancellation, no divergence-tolerance slack')


def _close_record(record, start_volumes_m3, budget):
    """Private arithmetic seam; production entry requires issued bounds."""
    if type(start_volumes_m3) is not dict or any(type(q) not in (int, Q) or q < 0 for q in start_volumes_m3.values()):
        raise V.VolumeError('exact nonnegative carried physical volumes required')
    rows = record['cells']; transfers = record['face_intervals']
    keys = {r['cell_id'] for r in rows}
    material_keys = {r['cell_id'] for r in rows if r['kind'] != 'algebraic-port'}
    if set(start_volumes_m3)-material_keys:
        raise V.VolumeError('a carried spatial cell is missing from current space-time support')
    reservoir = 'volume-endpoint-reservoir'
    if reservoir in keys:
        raise V.VolumeError('reserved circulation identity')
    edges, starts = [], {}
    for row in rows:
        key = row['cell_id']
        value = Q(start_volumes_m3.get(key, 0))
        lo, hi = map(W._decode, row['start_volume_bounds_m3'])
        if not lo <= value <= hi:
            raise V.VolumeError('carried start volume is outside its certified physical interval')
        starts[key] = value
        edges.append((reservoir, key, value, value))
        lo, hi = map(W._decode, row['end_volume_bounds_m3'])
        edges.append((key, reservoir, lo, hi))
    for row in transfers:
        a, b = map(W._decode, row['volume_bounds_m3'])
        edges.append((row['donor'], row['receiver'], a, b))
    with B._Arena(budget) as arena:
        chosen = _circulation([reservoir]+[r['cell_id'] for r in rows], edges, arena)
    ends = {r['cell_id']: chosen[2*i+1] for i, r in enumerate(rows)}
    selected = []
    for row, value in zip(transfers, chosen[2*len(rows):]):
        result = dict(row, volume_m3=E._enc(value))
        lo, hi = map(W._decode, row['volume_bounds_m3'])
        result['max_deviation_m3'] = E._enc(max(value-lo, hi-value))
        selected.append(result)
    # Ports impose EACH signed full wall-face partition. They have no material
    # volume or field: replace each source/port edge with the actual collar
    # owner after its paired fixed-volume equality has been solved exactly.
    ports = {r['cell_id']: r['collar_cell_id'] for r in rows if r['kind'] == 'algebraic-port'}
    positive = []
    for row in selected:
        if row.get('partition_total'):
            continue
        value = W._decode(row['volume_m3'])
        if value:
            positive.append(dict(row, donor=ports.get(row['donor'], row['donor']),
                receiver=ports.get(row['receiver'], row['receiver'])))
    active = {k for r in positive for k in (r['donor'], r['receiver'])}
    cells, inactive = [], []
    for row in rows:
        key = row['cell_id']
        if key in ports:
            continue
        cell = dict(row, start_volume_m3=E._enc(starts[key]), end_volume_m3=E._enc(ends[key]))
        if not starts[key] and not ends[key] and key not in active:
            # Still retained in the certificate; not a positive-volume/sliver
            # deletion. The transport matrix excludes only exact zero rows.
            inactive.append(cell)
        else:
            cells.append(cell)
    balance = {r['cell_id']: starts[r['cell_id']]-ends[r['cell_id']] for r in cells}
    for row in positive:
        v = W._decode(row['volume_m3']); balance[row['donor']] -= v; balance[row['receiver']] += v
    if any(balance.values()):
        raise V.VolumeError('internal exact GCL closure failure')
    result = {k: v for k, v in record.items() if k not in ('cells', 'face_intervals', 'schema')}
    result.update(schema='atlas.source-bound-spatial-ale-graph.v1', cells=cells, transfers=positive,
        inactive_zero_measure_cells=inactive, original_face_intervals=transfers,
        selected_face_representatives=selected,
        selection='exact bounded circulation; deterministic representative within original intervals, not exact physical quadrature',
        physical_outer_boundary='closed complete funded cone/radial-shell source; true comoving radial/cone relative flux is zero')
    return result


def close_spatial_ale(bounds, start_volumes_m3, *, budget):
    if type(bounds) is not SpatialALEBounds or type(budget) is not WorkBudget or bounds._resource is not budget:
        raise V.VolumeError('issued spatial bounds on the same explicit WorkBudget required')
    if type(start_volumes_m3) is not dict:
        raise V.VolumeError('exact carried volume mapping required')
    with budget.reserve(65536+8*len(bounds._json), category='spatial-ale-closure'), V._work(tuple(start_volumes_m3.values()), budget):
        record = _close_record(bounds.record(), start_volumes_m3, budget)
        record['bounds_id'] = bounds.bounds_id
        return _issue(SpatialALEGraph, record, budget)


def enclose_spatial_ale(funding, sphere, collar, wall_measures, source_flow_stage, *,
                        grid_lines, max_volume_error_m3, max_leaves, budget):
    """Issue actual spatial endpoint/Cartesian face-time volume intervals.

    The finite caller grid covers the whole funded radial source and contains
    every full collar cell face. Source charts/radial bands are persistent CV
    labels, not a claim that future mixtures retain their initial temperature.
    """
    from . import integration_support as U
    from .regional_collar3d import PreparedRegionalCollar3D, RegionalCollarSourceFlowStage
    if (type(funding) is not F.FullCellFunding or type(wall_measures) is not W.WallMeasures or
            type(collar) is not PreparedRegionalCollar3D or type(source_flow_stage) is not RegionalCollarSourceFlowStage):
        raise V.VolumeError('issued funding, wall geometry, prepared collar and actual source/flow stage required')
    if (type(budget) is not WorkBudget or any(r is not budget for r in
            (funding._resource, wall_measures._resource, collar._budget)) or source_flow_stage._owner is not collar):
        raise V.VolumeError('source-bound shared geometry/native WorkBudget required')
    collar._check_source_flow_stage(source_flow_stage)
    original, motion = funding.descriptor(), wall_measures.descriptor()
    flow = source_flow_stage.flow
    if (original['source']['sphere_state_id'] != sphere.state_id or original['collar_plan_id'] != collar.plan_id or
            motion['funding_id'] != funding.funding_id or flow.descriptor().get('wall_measure_id') != wall_measures.measure_id):
        raise V.VolumeError('physical source/funding/native wall-flow binding differs')
    start, end = (W._decode(motion[k]) for k in ('start_time_s', 'end_time_s'))
    if Q(source_flow_stage.duration_s) != end-start or Q(source_flow_stage.record()['start_time_s']) != start:
        raise V.VolumeError('native duration/start and exact physical interval differ')
    if type(grid_lines) is not tuple or len(grid_lines) != 3 or any(type(q) is not tuple or len(q) < 2 for q in grid_lines):
        raise V.VolumeError('three explicit finite Cartesian coordinate-line tuples required')
    width = W._q(max_volume_error_m3)
    if width <= 0 or type(max_leaves) is not int or max_leaves < 1:
        raise V.VolumeError('positive predeclared physical integration error and finite subdivision limit required')
    with budget.reserve(131072+2*funding._snapshot.nbytes+2*len(wall_measures._json), category='spatial-ale-source'), B._Arena(budget) as arena:
        lines = tuple(tuple(map(W._q, axis)) for axis in grid_lines)
        if any(a >= b for line in lines for a, b in zip(line, line[1:])):
            raise V.VolumeError('strictly increasing Cartesian grid lines required')
        collar_boxes = collar.cell_geometries(); base = collar_boxes[0]
        origin, basis = base.origin_m, base.basis
        radius = Q(sphere.network.sphere.radius_m)
        translation = tuple(sum(basis[k][j]*origin[k] for k in range(3)) for j in range(3))
        if any(line[0] > -radius-t or line[-1] < radius-t for line, t in zip(lines, translation)):
            raise V.VolumeError('spatial grid must contain complete funded physical source')
        for axis in range(3):
            if not {q for c in collar_boxes for q in (c.lower_m[axis], c.upper_m[axis])}.issubset(lines[axis]):
                raise V.VolumeError('spatial grid omitted an actual collar cell face')
        grid_id = E._hash(dict(lines=[list(map(E._enc, axis)) for axis in lines], origin=E._point(origin), basis=[E._point(r) for r in basis]))
        patches = {p.patch_id: p for p in U.required(sphere.material).patches}
        charts, geometry = {}, {}
        for row in original['exterior_remainder']:
            p = row['patch_id']; key = (p, row['sublayer'])
            if p not in charts:
                try:
                    charts[p] = (V.convex_cone_union(patches[p].cells, budget=budget),)
                except V.VolumeError:
                    charts[p] = patches[p].cells
            g = row['radial_layer']
            geometry[key] = V.RadialLayer(*(W._decode(g[k]) for k in ('radius_m', 'top_depth_m', 'bottom_depth_m')), budget=budget)
        levels = sorted({v for g in geometry.values() for v in (g.bottom_radius_m, g.top_radius_m)})
        regions = []
        for key, g in sorted(geometry.items()):
            for band, (rb, rt) in enumerate(zip(levels, levels[1:])):
                if g.bottom_radius_m <= rb < rt <= g.top_radius_m:
                    layer = V.RadialLayer(radius, radius-rt, radius-rb, budget=budget)
                    for chart, cone in enumerate(charts[key[0]]):
                        regions.append((key, band, chart, layer, cone))
        shape = tuple(len(axis)-1 for axis in lines)
        count = math.prod(shape)*len(regions)
        arena.keep((width,), 16*(count+len(collar_boxes)))
        arena.work(128*count)
        # Two endpoint intervals and both signs on <=3 positive faces per
        # region/voxel. Width sum is <= the caller's physical error request.
        local_width = width/(8*max(1, count))
        history = motion['trajectory']['segments']; last = history[-1]
        omega = tuple(map(W._decode, last['angular_velocity_rad_s']))
        prior = tuple((tuple(map(W._decode, r['angular_velocity_rad_s'])), W._decode(r['end_time_s'])-W._decode(r['start_time_s'])) for r in history[:-1])
        dt = end-start
        cells, faces, boxes, radial_bounds, native_at, physical_nodes = {}, [], {}, {}, {}, {}
        native_keys = []
        for flat, box in enumerate(collar_boxes):
            key = E._hash(dict(kind='collar', funding_id=funding.funding_id, cell_id=box.cell_id))
            native_keys.append(key)
            cells[key] = dict(cell_id=key, kind='collar', index=flat, physical_cell_id=box.cell_id,
                start_volume_bounds_m3=[E._enc(box.volume_m3)]*2, end_volume_bounds_m3=[E._enc(box.volume_m3)]*2)
        for at in product(*(range(n) for n in shape)):
            lo, hi = tuple(lines[j][at[j]] for j in range(3)), tuple(lines[j][at[j]+1] for j in range(3))
            box = V.CartesianCell(lo, hi, origin, basis, budget=budget); boxes[at] = box
            radial_bounds[at] = box._radial_bounds()
            matches = [i for i, b in enumerate(collar_boxes) if all(b.lower_m[j] <= lo[j] and hi[j] <= b.upper_m[j] for j in range(3))]
            if matches:
                if len(matches) != 1:
                    raise V.VolumeError('spatial voxel has ambiguous full-cell owner')
                native_at[at] = matches[0]; continue
            for ri, (source, band, chart, layer, cone) in enumerate(regions):
                radial_min, radial_max = radial_bounds[at]
                if radial_min >= layer.top_radius_m**2 or radial_max <= layer.bottom_radius_m**2:
                    a = b = (Q(0), Q(0))
                else:
                    a = W._endpoint_volume(layer, (cone,), box, omega, Q(0), local_width, max_leaves, budget, prior, positive_witness=True)
                    b = W._endpoint_volume(layer, (cone,), box, omega, dt, local_width, max_leaves, budget, prior, positive_witness=True)
                key = E._hash(dict(source_key=list(source), grid_id=grid_id, voxel_index=list(at), radial_band=band, chart=chart))
                physical_nodes[at, ri] = key
                cells[key] = dict(cell_id=key, kind='exterior', source_key=list(source), voxel_index=list(at), radial_band=band, chart=chart,
                    start_volume_bounds_m3=list(map(E._enc, a)), end_volume_bounds_m3=list(map(E._enc, b)),
                    start_geometry_instance_id=E._hash(dict(logical_cell_id=key, support_id=motion['start_support_id'])),
                    end_geometry_instance_id=E._hash(dict(logical_cell_id=key, support_id=motion['end_support_id'])))
        def add_face(donor, receiver, bounds, identity, **metadata):
            if bounds[1] > 0:
                faces.append(dict(face_id=E._hash(identity), donor=donor, receiver=receiver,
                    volume_bounds_m3=list(map(E._enc, bounds)), **metadata))
        ports = {}
        def port(flat, axis, end_, inward):
            identity = (flat, axis, end_, inward)
            if identity not in ports:
                key = E._hash(dict(collar=native_keys[flat], axis=axis, end=end_, inward=inward))
                ports[identity] = key
                cells[key] = dict(cell_id=key, kind='algebraic-port', collar_cell_id=native_keys[flat],
                    start_volume_bounds_m3=[E._enc(0)]*2, end_volume_bounds_m3=[E._enc(0)]*2)
                pair, _ = W._whole_face(collar_boxes[flat], axis, end_, omega, dt)
                value = pair[0 if inward else 1]
                a, b = (key, native_keys[flat]) if inward else (native_keys[flat], key)
                add_face(a, b, (value, value), dict(port=key, total=True), partition_total=True,
                    error_kind='exact complete signed physical rigid wall')
            return ports[identity]
        for at, box in boxes.items():
            for axis in range(3):
                neighbour = list(at); neighbour[axis] += 1; neighbour = tuple(neighbour)
                if neighbour not in boxes or at in native_at and neighbour in native_at:
                    continue
                for ri, (_, _, _, layer, cone) in enumerate(regions):
                    radial_min, radial_max = radial_bounds[at]
                    if radial_min >= layer.top_radius_m**2 or radial_max <= layer.bottom_radius_m**2:
                        continue       # exact zero area/volume, not sliver culling
                    measure = W.enclose_rotating_wall(layer, (cone,), box, axis, 1, angular_velocity_rad_s=omega,
                        start_offset_s=0, end_offset_s=dt, max_width_m3=local_width, max_leaves=max_leaves,
                        budget=budget, prior_rotations=prior)
                    if not measure['met']:
                        raise V.VolumeError('spatial Cartesian face-time enclosure exceeded declared work/error request')
                    for increasing, name in ((True, 'outward'), (False, 'inward')):
                        bounds = measure[name]
                        if not bounds[1]:
                            continue
                        a = port(native_at[at], axis, 1, not increasing) if at in native_at else physical_nodes[at, ri]
                        b = port(native_at[neighbour], axis, 0, increasing) if neighbour in native_at else physical_nodes[neighbour, ri]
                        donor, receiver = (a, b) if increasing else (b, a)
                        add_face(donor, receiver, bounds, dict(grid_id=grid_id, at=at, axis=axis, region=ri, increasing=increasing),
                            error_kind='certified physical curved cone/shell space-time integration')
        # Keep the original arithmetic hull as evidence, then perform the
        # explicitly audited conservative FV representation correction. This
        # is NOT additional physical geometry uncertainty or unchanged flow.
        native_shape = tuple(collar.cells)
        weights = tuple(Q(float(v)) for v in collar._transport._face_weights)
        native_faces = []
        for axis, label in enumerate('xyz'):
            for at in product(*(range(n+int(j == axis)) for j, n in enumerate(native_shape))):
                if at[axis] in (0, native_shape[axis]):
                    continue
                lower = list(at); lower[axis] -= 1
                flat = lambda p: (p[0]*native_shape[1]+p[1])*native_shape[2]+p[2]
                left, right = native_keys[flat(lower)], native_keys[flat(at)]
                normals = tuple(Q(float(v)) for v in flow.array('normal_'+label+'_m_s')[at])
                raw = tuple(Q(float(v)) for v in flow.array('raw_normal_'+label+'_m_s')[at])
                area = Q(float(collar._transport._areas[axis]))
                native_faces.append(dict(donor=left, receiver=right, axis=axis, index=list(at), normals=normals,
                    raw_normals=raw, weights=weights, area_m2=area, duration_s=dt,
                    booked_positive=Q(float(flow.array('positive_'+label+'_m3_s')[at]))*dt,
                    booked_negative=Q(float(flow.array('negative_'+label+'_m3_s')[at]))*dt))
        boundary_outflow = {key: Q(0) for key in native_keys}
        native_plan = collar._native._transport
        native_speed = max((abs(Q(float(v))) for label in 'xyz' for v in
            source_flow_stage.source_stage.flow.array('raw_normal_'+label+'_m_s').flat), default=Q(0))
        # Same represented Gauss positions used by the native Q2 face rule;
        # physical locations and the affine rigid normal are evaluated exactly.
        import numpy as np
        abscissas = tuple(Q(float(v)) for v in np.polynomial.legendre.leggauss(3)[0])
        outer_audits = []
        for flat, box in enumerate(collar_boxes):
            index = (flat//(native_shape[1]*native_shape[2]), flat//native_shape[2] % native_shape[1], flat % native_shape[2])
            for axis in range(3):
                for end_ in (0, 1):
                    if index[axis] == (native_shape[axis]-1 if end_ else 0):
                        pair, _ = W._whole_face(box, axis, end_, omega, dt)
                        boundary_outflow[native_keys[flat]] += pair[1]-pair[0]
                        at = list(index); at[axis] += end_; at = tuple(at); label = 'xyz'[axis]
                        normals = tuple(Q(float(v)) for v in flow.array('normal_'+label+'_m_s')[at])
                        raw = tuple(Q(float(v)) for v in flow.array('raw_normal_'+label+'_m_s')[at])
                        transverse = [j for j in range(3) if j != axis]
                        physical_normals = []
                        for qa, qb in product(abscissas, repeat=2):
                            local = [(a+b)/2 for a, b in zip(box.lower_m, box.upper_m)]
                            local[axis] = (box.lower_m, box.upper_m)[end_][axis]
                            for j, q in zip(transverse, (qa, qb)):
                                local[j] += q*(box.upper_m[j]-box.lower_m[j])/2
                            point = tuple(box.origin_m[i]+sum(box.basis[i][j]*local[j] for j in range(3)) for i in range(3))
                            physical_normals.append(E.O._dot(tuple(box.basis[i][axis] for i in range(3)), E.O._cross(omega, point)))
                        # Whole-face pair is inward/outward; arrays use the
                        # increasing-coordinate normal on BOTH domain sides.
                        streams = (pair[1], pair[0]) if end_ else pair
                        row = dict(normals=normals, raw_normals=raw, weights=weights,
                            area_m2=Q(float(collar._transport._areas[axis])), duration_s=dt)
                        audit = _audit_outer_face(row, tuple(physical_normals), streams, speed_scale=native_speed,
                            absolute_limit=Q(native_plan.max_velocity_correction_m_s),
                            relative_limit=Q(native_plan.max_relative_correction), budget=budget)
                        outer_audits.append(dict(axis=axis, index=list(at), physical_cell_id=box.cell_id,
                            **{k:E._enc(v) for k,v in audit.items()},
                            booked_positive_m3=E._enc(Q(float(flow.array('positive_'+label+'_m3_s')[at]))*dt),
                            booked_negative_m3=E._enc(Q(float(flow.array('negative_'+label+'_m3_s')[at]))*dt)))
        projected, projection = _project_native(native_keys, native_faces, boundary_outflow,
            speed_scale=native_speed, absolute_limit=Q(native_plan.max_velocity_correction_m_s),
            relative_limit=Q(native_plan.max_relative_correction), budget=budget)
        projection.update(source_flow_id=flow.flow_id, faces=[], outer_faces=outer_audits,
            outer_rule='same affine rigid field at represented Gauss points; exact sign split is quadrature, not a velocity correction')
        projection['total_normal_correction_bound_m_s'] = E._enc(max(
            W._decode(projection['total_normal_correction_bound_m_s']),
            *(W._decode(a['total_normal_correction_bound_m_s']) for a in outer_audits)))
        for row, value in zip(native_faces, projected):
            audit = dict(axis=row['axis'], index=row['index'], donor=row['donor'], receiver=row['receiver'],
                **{k: E._enc(v) for k, v in value.items()})
            audit.update(booked_positive_m3=E._enc(row['booked_positive']), booked_negative_m3=E._enc(row['booked_negative']))
            projection['faces'].append(audit)
            for positive, name in ((True, 'positive'), (False, 'negative')):
                booked, exact, final = row['booked_'+name], value['original_'+name], value[name]
                donor, receiver = (row['donor'], row['receiver']) if positive else (row['receiver'], row['donor'])
                add_face(donor, receiver, (final, final), dict(flow_id=flow.flow_id, axis=row['axis'], at=row['index'], positive=positive),
                    booked_volume_m3=E._enc(booked), exact_discrete_gauss_volume_m3=E._enc(exact),
                    original_volume_bounds_m3=list(map(E._enc, (min(booked, exact), max(booked, exact)))),
                    normal_increment_m_s=E._enc(value['normal_increment_m_s']),
                    total_normal_correction_bound_m_s=E._enc(value['total_normal_correction_bound_m_s']),
                    error_kind='explicit exact conservative FV numerical projection under ORIGINAL normal correction limits')
        touched = {k for f in faces for k in (f['donor'], f['receiver'])}
        cells = [r for key, r in cells.items() if key in touched or any(W._decode(r[n][1]) > 0
            for n in ('start_volume_bounds_m3', 'end_volume_bounds_m3'))]
        result = dict(schema='atlas.source-bound-spatial-ale-bounds.v1', funding_id=funding.funding_id,
            source=original['source'], collar_plan_id=collar.plan_id, parent_state_id=source_flow_stage.parent_state_id,
            source_flow_stage_id=source_flow_stage.result_id, flow_id=flow.flow_id,
            component_keys=original['component_keys'], wall_measure_id=wall_measures.measure_id,
            start_time_s=motion['start_time_s'], end_time_s=motion['end_time_s'],
            start_support_id=motion['start_support_id'], end_support_id=motion['end_support_id'],
            trajectory_id=motion['trajectory_id'], prior_trajectory_id=motion['prior_trajectory_id'],
            trajectory=motion['trajectory'], grid_id=grid_id, grid_lines=[list(map(E._enc, a)) for a in lines],
            grid_embedding=dict(origin_m=E._point(origin), basis=[E._point(r) for r in basis]),
            physical_regions=[dict(source_key=list(k), radial_band=b, chart=c, radial_layer=g.record(), original_cone=[E._point(p) for p in cone])
                              for k, b, c, g, cone in regions],
            cells=sorted(cells, key=lambda r: r['cell_id']), face_intervals=sorted(faces, key=lambda r: r['face_id']),
            native_flux_projection=projection,
            max_volume_error_m3=E._enc(width), per_measure_width_m3=E._enc(local_width), max_leaves=max_leaves,
            endpoint_lower_rule='maximum of outward-rounded lower sum and exact true-support inner-subset witness; same leaf/work cap',
            zero_relative_interfaces='true physical radial spheres and common-rigid material cones, never thermal facets',
            coverage='whole funded source inside sphere-containing Cartesian grid; actual full collar cells excluded exactly')
        if 'component_registry' in original:
            result['component_registry_id'] = original['component_registry']['registry_id']
        return _issue(SpatialALEBounds, result, budget)
