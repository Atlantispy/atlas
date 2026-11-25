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
from contextlib import contextmanager
from dataclasses import dataclass, field
from fractions import Fraction as Q
from itertools import product
import hashlib
import math
import weakref
from atlas_tectonics._private import live_spatial_patch as LIVE_SPATIAL

from . import integration_volume as V
from . import integration_volume_bounds as B
from . import integration_collar_geometry as F
from . import integration_exterior_mesh as E
from . import integration_wall_measures as W
from .resources import WorkBudget
from .resources import canonical_json


class GCLInfeasible(V.VolumeError):
    """Exact cut certificate; no numerical or physical bound was relaxed."""
    def __init__(self, nodes, incoming_lower, outgoing_upper, unsatisfied):
        super().__init__('certified volume/face bounds have no exact GCL circulation; no flux or volume repair applied')
        self.cut_cell_ids = tuple(nodes)
        self.incoming_lower_m3 = incoming_lower
        self.outgoing_upper_m3 = outgoing_upper
        self.unsatisfied_m3 = unsatisfied


def _issue(cls, record, budget, *, physical_surfaces=None):
    result = LIVE_SPATIAL.issue(cls, record, budget, _legacy_issue)
    if physical_surfaces:
        from .integration_regional_inventory import _width
        lease = budget.reserve(4096 + 8 * _width(physical_surfaces), category='spatial-physical-surfaces')
        lease.__enter__()
        try:
            object.__setattr__(result, '_physical_surfaces', dict(physical_surfaces))
            weakref.finalize(result, lease.__exit__, None, None, None)
        except BaseException:
            lease.__exit__(None, None, None)
            raise
    return result


def _legacy_issue(cls, record, budget):
    encoded = canonical_json(record)
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
    _json: object = field(repr=False)
    _resource: object = field(repr=False, compare=False)
    _physical_surfaces: object = field(default=None, repr=False, compare=False)
    _content_id: object = field(default=None, repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('spatial bounds are issued by enclose_spatial_ale()')

    @property
    def bounds_id(self):
        return LIVE_SPATIAL.holder_content_identity(self)

    def record(self):
        return LIVE_SPATIAL.holder_record(self)


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class SpatialALEGraph:
    _json: object = field(repr=False)
    _resource: object = field(repr=False, compare=False)
    _physical_surfaces: object = field(default=None, repr=False, compare=False)
    _content_id: object = field(default=None, repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('closed spatial graphs are issued by close_spatial_ale()')

    @property
    def geometry_id(self):
        return LIVE_SPATIAL.holder_content_identity(self)

    def record(self):
        return LIVE_SPATIAL.holder_record(self)


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


def _physical_value(value):
    """Typed physical value, with no recursive admission of dictionary names."""
    if type(value) in (int, Q):
        return (0, Q(value))
    if type(value) is float and math.isfinite(value):
        return (1, value.hex())
    if type(value) in (list, tuple):
        if len(value) == 2 and all(type(v) is str and v.lstrip('-').startswith('0x') for v in value):
            try:
                return (0, W._decode(value))
            except (ValueError, ZeroDivisionError):
                return None
        converted = tuple(_physical_value(v) for v in value)
        if all(v is not None for v in converted):
            return (2, converted)
    return None


def _stock_physical_key(lineage, *, arena=None):
    """Selected immutable lineage quantities in geometry/exact/binary tiers.

    Field paths are enumerated here. A free label, a dynamic dictionary key,
    a stock's current quantities or a whole nested lineage never ranks a row.
    """
    if not hasattr(lineage, 'get'):
        return None
    geometry, exact, binary = [], [], []

    def add(path, value, *, geometric=False):
        typed = _physical_value(value)
        if typed is None:
            return
        def floating(v):
            return type(v) is float or type(v) in (list, tuple) and any(floating(q) for q in v)
        target = geometry if geometric else binary if floating(value) else exact
        target.append((path, typed))

    kind = lineage.get('kind')
    if kind == 'finite-basal-reservoir':
        cell = lineage.get('physical_cell', {})
        reservoir = lineage.get('reservoir', {})
        if not hasattr(cell, 'get') or not hasattr(reservoir, 'get'):
            return None
        for name in ('basis', 'lower_m', 'origin_m', 'upper_m'):
            add('physical_cell.' + name, cell.get(name), geometric=True)
        for name in ('face_index', 'sublayer'):
            add('reservoir.' + name, reservoir.get(name), geometric=True)
        # Side is a fixed physical coordinate choice, never a destination name.
        side = reservoir.get('side')
        if side in ('x0', 'x1', 'y0', 'y1', 'z0', 'z1'):
            add('reservoir.side', ('x0', 'x1', 'y0', 'y1', 'z0', 'z1').index(side), geometric=True)
        add('reservoir.depth_m', reservoir.get('depth_m'))
    elif kind == 'declared-finite-trench-export':
        add('destination_fraction', lineage.get('destination_fraction'))
    elif kind == 'declared-finite-shell-birth':
        supply = lineage.get('supply', {})
        column = lineage.get('birth_column', {})
        if not hasattr(supply, 'get') or not hasattr(column, 'get') or type(lineage.get('sublayer')) is not int:
            return None
        add('sublayer', lineage['sublayer'], geometric=True)
        if supply.get('side') in ('left', 'right'):
            add('supply.side', int(supply['side'] == 'right'), geometric=True)
        for name in ('reference_radius_m', 'finite_area_m2', 'enthalpy_reference_k',
                     'physical_temperature_k', 'admission_volume_projection_m3'):
            add(name, lineage.get(name))
        declared = lineage.get('declared', {})
        if not hasattr(declared, 'get'):
            return None
        for name in ('absolute_heat_j', 'mass_kg', 'relative_heat_j', 'volume_m3'):
            add('declared.' + name, declared.get(name))
        projection = lineage.get('admission_projection', {})
        if not hasattr(projection, 'get') or not hasattr(projection, 'items'):
            return None
        add('admission_projection.enthalpy_j', projection.get('enthalpy_j'))
        # Component field names are registry labels. Only the multiset of the
        # explicitly named admission mass projections is a physical operand.
        mass_projection = [_physical_value(v) for k, v in projection.items()
                           if type(k) is str and k.startswith('component_mass_kg:')]
        if mass_projection and all(v is not None for v in mass_projection):
            mass_projection = _physical_sorted(mass_projection, arena=arena)
            exact.append(('admission_projection.component_mass_kg', tuple(mass_projection)))
        for name in ('mass_per_area_kg_m2', 'thickness_m'):
            pairs = supply.get(name, ())
            if type(pairs) not in (list, tuple) or any(type(p) not in (list, tuple) or len(p) != 2 for p in pairs):
                return None
            quantities = [_physical_value(pair[1]) for pair in pairs]
            if quantities and all(v is not None for v in quantities):
                quantities = _physical_sorted(quantities, arena=arena)
                binary.append(('supply.' + name, tuple(quantities)))
        add('supply.enthalpy_per_area_j_m2', supply.get('enthalpy_per_area_j_m2'))
        for name in ('base_temperature_k', 'radial_depths_m', 'reference_radius_m', 'surface_temperature_k'):
            add('birth_column.' + name, column.get(name))
        fields = ('alpha_per_k', 'bottom_temperature_k', 'conductivity_w_m_k',
                  'heat_capacity_j_kg_k', 'pore_pressure_pa', 'radiogenic_w_m3',
                  'reference_density_kg_m3', 'thickness_m', 'top_temperature_k')
        layers = column.get('sublayers', ())
        if type(layers) not in (list, tuple) or any(not hasattr(layer, 'get') for layer in layers):
            return None
        for at, layer in enumerate(layers):
            for name in fields:
                add('birth_column.sublayers.%d.%s' % (at, name), layer.get(name))
    else:
        return None
    if not geometry and not exact and not binary:
        return None
    return (3, tuple(_physical_sorted(geometry, arena=arena)),
            tuple(_physical_sorted(exact, arena=arena)), tuple(_physical_sorted(binary, arena=arena)))


def _terminal_lineage_complete(lineage, stock_kind):
    """Match the actual issuer's role and complete typed physical conditions.

    Unknown/custom declarations keep the original selector. Labels below bind
    constructor fields to each other; none becomes an ordering operand.
    """
    if not hasattr(lineage, 'get'):
        return False
    kind = lineage.get('kind')
    if kind == 'finite-basal-reservoir':
        if stock_kind != 'reservoir' or lineage.get('compartment_kind', 'source') != 'reservoir':
            return False
        cell, reservoir = lineage.get('physical_cell'), lineage.get('reservoir')
        if not hasattr(cell, 'get') or not hasattr(reservoir, 'get'):
            return False
        vectors = [cell.get(name) for name in ('lower_m', 'upper_m', 'origin_m')]
        basis = cell.get('basis')
        def exact_vector(value):
            if type(value) not in (list, tuple) or len(value) != 3:
                return False
            return all((typed := _physical_value(v)) is not None and typed[0] == 0 for v in value)
        if (not all(exact_vector(v) for v in vectors) or
                type(basis) not in (list, tuple) or len(basis) != 3 or
                not all(exact_vector(v) for v in basis)):
            return False
        face_index = reservoir.get('face_index')
        sublayer, source_key = reservoir.get('sublayer'), lineage.get('source_key')
        patch = reservoir.get('patch_id')
        depth = _physical_value(reservoir.get('depth_m'))
        return (reservoir.get('side') in ('x0', 'x1', 'y0', 'y1', 'z0', 'z1') and
                type(face_index) in (list, tuple) and len(face_index) == 2 and
                all(type(v) is int and v >= 0 for v in face_index) and
                type(sublayer) is int and sublayer >= 0 and type(patch) is str and bool(patch) and
                type(source_key) in (list, tuple) and len(source_key) == 2 and
                source_key[0] == patch and type(source_key[1]) is int and source_key[1] == sublayer and
                depth is not None and depth[0] == 0 and depth[1] > 0)
    if kind == 'declared-finite-trench-export':
        if stock_kind != 'sink':
            return False
        context, sink = lineage.get('source_context'), lineage.get('sink')
        if not hasattr(context, 'get') or not hasattr(sink, 'get'):
            return False
        radius = context.get('reference_radius_m')
        boundary, destination = context.get('boundary_id'), lineage.get('destination')
        if (type(radius) not in (int, Q, float) or type(radius) is float and not math.isfinite(radius) or
                radius <= 0 or context.get('boundary_kind') != 'trench' or
                type(boundary) is not str or not boundary.strip() or len(boundary) > 256 or
                sink.get('boundary_id') != boundary or
                type(destination) is not str or not destination.strip() or len(destination) > 256):
            return False
        destinations = sink.get('destinations')
        if type(destinations) not in (list, tuple):
            return False
        matches = [row for row in destinations if type(row) in (list, tuple) and len(row) == 3 and type(row[2]) is bool and
                   row[0] == destination and row[2] == lineage.get('declared_stock_node')]
        fraction = _physical_value(lineage.get('destination_fraction'))
        declared = None if len(matches) != 1 else _physical_value(matches[0][1])
        if declared is not None and declared[0] == 1:
            declared = (0, Q(float.fromhex(declared[1])))
        return (len(matches) == 1 and type(lineage.get('declared_stock_node')) is bool and
                len(destinations) == 1 and fraction == (0, Q(1)) and
                context.get('subducting_side') in ('left', 'right') and declared == fraction)
    return False


def _terminal_condition_key(lineage, stock_kind):
    if not _terminal_lineage_complete(lineage, stock_kind):
        return None
    if lineage['kind'] == 'finite-basal-reservoir':
        return (0,)
    if lineage['kind'] == 'declared-finite-trench-export':
        context = lineage['source_context']
        return (1, _physical_value(context['reference_radius_m']),
                int(context['subducting_side'] == 'right'), lineage['declared_stock_node'])
    # The current shell-birth constructor creates sources, not incoming-only
    # reservoirs. A custom public reinterpretation stays on its original path.
    return None


@contextmanager
def _physical_member(record, name):
    """Borrow exactly one metadata member through its actual native route."""
    from ._private.record_views import RecordRef
    reference = LIVE_SPATIAL.reference(record)
    if isinstance(reference, RecordRef):
        try:
            child = reference.field(name)
        except KeyError:
            yield None
        else:
            with child:
                yield child
    else:
        yield record.get(name)


def _physical_region_width(record):
    from ._private.record_views import RecordRef
    from .integration_regional_inventory import _width
    with _physical_member(record, 'physical_regions') as regions:
        return regions._logical_length() if isinstance(regions, RecordRef) else _width(regions)


def _physical_region_keys(record, arena):
    from ._private.record_views import RecordRef
    from ._private.spatial_validation_patch import SMALL_BYTES
    result = {}
    def add(row):
        if not hasattr(row, 'get'):
            return
        source, band, chart = row.get('source_key'), row.get('radial_band'), row.get('chart')
        if (type(source) not in (list, tuple) or len(source) != 2 or type(source[0]) is not str or
                type(source[1]) is not int or type(band) is not int or type(chart) is not int):
            return
        directions = []
        try:
            for point in row['original_cone']:
                p = tuple(map(W._decode, point))
                scale = max(map(abs, p))
                if len(p) != 3 or not scale:
                    return
                directions.append(tuple(q / scale for q in p))
            layer = row['radial_layer']
            radial = tuple(W._decode(layer[k]) for k in ('radius_m', 'top_depth_m', 'bottom_depth_m'))
        except (KeyError, ValueError, TypeError, ZeroDivisionError):
            return
        result[(tuple(source), band, chart)] = (2, tuple(_physical_sorted(directions, arena=arena)), radial)
    with _physical_member(record, 'physical_regions') as regions:
        if isinstance(regions, RecordRef):
            for index in range(regions.size):
                with regions.at(index) as member, member.export(
                        max_logical_bytes=SMALL_BYTES, max_owned_bytes=SMALL_BYTES) as owned:
                    add(owned.value)
        elif type(regions) in (list, tuple):
            for row in regions:
                add(row)
    return result


def _surface_key(record, face, physical_surfaces=None):
    if physical_surfaces is not None and face['face_id'] in physical_surfaces:
        return physical_surfaces[face['face_id']]
    value = _read_surface_key(record, face)
    if physical_surfaces is not None:
        physical_surfaces[face['face_id']] = value
    return value


def _read_surface_key(record, face):
    certificate = face.get('physical_certificate_id')
    if type(certificate) is not str:
        return None
    from ._private.record_views import RecordRef
    from ._private.spatial_validation_patch import SMALL_BYTES
    names = ('origin_m', 'tangent_u', 'tangent_v', 'coordinate_bounds_m')

    def native_surface(table):
        # Only the selected receipt/face fields are decoded. A graph adapter's
        # generic get() would export the complete receipt table instead.
        try:
            with table.field(certificate) as receipt, receipt.field('face') as surface:
                values = []
                for name in names:
                    with surface.field(name) as member, member.export(
                            max_logical_bytes=SMALL_BYTES, max_owned_bytes=SMALL_BYTES) as owned:
                        values.append(_physical_value(owned.value))
                return (0, tuple(values)) if all(v is not None for v in values) else None
        except KeyError:
            return None

    reference = LIVE_SPATIAL.reference(record)
    if isinstance(reference, RecordRef):
        try:
            with reference.field('physical_measure_receipts') as table:
                return native_surface(table)
        except KeyError:
            return None
    table = record.get('physical_measure_receipts', {})
    if isinstance(table, RecordRef):
        return native_surface(table)
    if not hasattr(table, 'get'):
        return None
    receipt = table.get(certificate)
    if receipt is not None and hasattr(receipt, 'get'):
        surface = receipt.get('face')
        if hasattr(surface, 'get'):
            values = tuple(_physical_value(surface.get(k)) for k in names)
            if all(v is not None for v in values):
                return (0, values)
    return None


def _physical_cell_keys(record, *, stock_keys=None, physical_surfaces=None, arena=None,
                        _validated_transfers=False):
    """Call-local physical keys; None means no established unique order.

    IDs retrieve geometry or authenticate the finite port constructor. They
    never enter the ordering key. Restored data can legitimately lack a
    moving segment; absence supplies neither symmetry nor a new refusal.
    """
    from ._private.record_views import RecordRef
    from ._private.spatial_validation_patch import SMALL_BYTES
    rows = record['cells']
    regions = _physical_region_keys(record, arena)
    with _physical_member(record, 'physical_geometry_family') as family:
        if isinstance(family, RecordRef):
            with family.scalar(max_owned_bytes=SMALL_BYTES) as owned:
                differential = owned.value == 'differential-plate-component-partition-v1'
        else:
            differential = family == 'differential-plate-component-partition-v1'
    physical, ports, exterior_classes, exterior_details = {}, {}, {}, {}
    for row in rows:
        key, kind = row['cell_id'], row.get('kind')
        value = None
        if kind == 'collar' and type(row.get('index')) is int:
            value = (0, row['index'])
        elif kind == 'exterior':
            source, voxel = row.get('source_key'), row.get('voxel_index')
            band, chart = row.get('radial_band'), row.get('chart')
            if (type(source) in (list, tuple) and len(source) == 2 and type(source[1]) is int and
                    type(voxel) in (list, tuple) and len(voxel) == 3 and
                    all(type(v) is int for v in voxel) and type(band) is int):
                base_key = (1, source[1], tuple(voxel), band)
                exterior_classes.setdefault(base_key, []).append(key)
                detail = None
                region = (regions.get((tuple(source), band, chart))
                          if type(source[0]) is str and type(chart) in (int, str) else None)
                if region is not None:
                    detail = region
                elif differential and type(row.get('shape_key')) is str:
                    optional_chart = (0, chart) if type(chart) is int else (1,)
                    detail = (1, optional_chart, row['shape_key'])
                elif differential and type(chart) is int:
                    detail = (1, (0, chart), '')
                # A sister chart is a retrieval token, never a physical order.
                exterior_details[key] = detail
                value = base_key
        elif kind in ('inventory', 'finite-inventory'):
            value = ((stock_keys or {}).get(key) if stock_keys is not None else
                     _stock_physical_key(row.get('stock_lineage'), arena=arena))
        physical[key] = value
    for base_key, members in exterior_classes.items():
        details = [exterior_details[key] for key in members]
        if all(d is not None for d in details) and len({d[0] for d in details}) == 1:
            for key, detail in zip(members, details, strict=True):
                physical[key] = (*base_key, detail)
    port_candidates = {}
    for row in rows:
        if row.get('kind') != 'algebraic-port':
            continue
        parent = row.get('collar_cell_id')
        collar = physical.get(parent)
        if arena is not None and type(parent) is str and collar is not None and collar[0] == 0:
            arena.work(12 * (128 + len(parent)))
        matches = []
        if type(parent) is str and collar is not None and collar[0] == 0:
            if parent not in port_candidates:
                candidates = {}
                for axis in range(3):
                    for end in (0, 1):
                        for inward in (False, True):
                            digest = E._hash(dict(collar=parent, axis=axis, end=end, inward=inward))
                            candidates.setdefault(digest, []).append((axis, end, inward))
                port_candidates[parent] = candidates
            matches = port_candidates[parent].get(row['cell_id'], [])
        if len(matches) != 1:
            if type(parent) is str and collar is not None and collar[0] == 0:
                ports[row['cell_id']] = None
            continue
        ports[row['cell_id']] = (2, collar[1], *matches[0])
        physical[row['cell_id']] = ports[row['cell_id']]
    classes = {}
    for row in rows:
        key = row['cell_id']
        if row.get('kind') in ('inventory', 'finite-inventory') and physical[key] is not None:
            classes.setdefault(physical[key], []).append(key)
    tied = {key for members in classes.values() if len(members) > 1 for key in members}
    if not tied and _validated_transfers:
        return physical, ports
    base = dict(physical)
    incidence = {key: [] for key in tied}
    for face in record.get('face_intervals', record.get('transfers', ())):
        for role, own, other in ((0, face['donor'], face['receiver']), (1, face['receiver'], face['donor'])):
            if own in incidence:
                partner = base.get(other)
                incidence[own].append((role, partner, face))
    for members in classes.values():
        if len(members) < 2 or any(partner is None for key in members
                                  for _, partner, _ in incidence[key]):
            continue
        endpoint_classes = {}
        for key in members:
            endpoints = tuple(_physical_sorted([(role, partner) for role, partner, _ in incidence[key]], arena=arena))
            physical[key] = (*base[key], endpoints)
            endpoint_classes.setdefault(endpoints, []).append(key)
        for twins in endpoint_classes.values():
            if len(twins) < 2:
                continue
            surfaces = {}
            for key in twins:
                connections = []
                for role, partner, face in incidence[key]:
                    surface = _surface_key(record, face, physical_surfaces)
                    connections.append((role, partner, surface))
                surfaces[key] = connections
            if not any(surface is None for connections in surfaces.values() for _, _, surface in connections):
                for key in twins:
                    physical[key] = (*base[key], tuple(_physical_sorted(surfaces[key], arena=arena)))
    return physical, ports


def _physical_key_work(value):
    """Logical comparison tariff, separate from storage and timing."""
    if type(value) is tuple:
        return 1 + sum(map(_physical_key_work, value))
    if type(value) is str:
        return 2 + (len(value) + 7) // 8
    if type(value) in (int, Q, bool):
        bits = abs(value.numerator).bit_length() + value.denominator.bit_length()
        return 2 + (bits + 63) // 64
    return 1


def _physical_sorted(values, *, key=None, arena=None, adjacent=False):
    count = len(values)
    if arena is not None and count >= 2:
        width = max(_physical_key_work(v if key is None else key(v)) for v in values)
        comparisons = 2 * count * count.bit_length() + (count - 1 if adjacent else 0)
        arena.work(2 * width * comparisons)
    return sorted(values, key=key)



def _physical_order(record, physical, physical_surfaces=None, arena=None, edges=None):
    """Order the complete free choice; carry fixed positions by identity."""
    rows = record['cells']
    faces = record.get('face_intervals', record.get('transfers', ()))
    if edges is None:
        return None
    active, fixed, free_endpoints, free_faces = set(), [], ([], []), []
    for at, row in enumerate(rows):
        for role in (0, 1):
            index = 2 * at + role
            if edges[index][2] == edges[index][3]:
                fixed.append(index)
            else:
                active.add(row['cell_id'])
                free_endpoints[role].append((row['cell_id'], index))
    for at, row in enumerate(faces):
        index = 2 * len(rows) + at
        total = row.get('partition_total', False)
        if type(total) is not bool:
            return None
        if edges[index][2] == edges[index][3]:
            fixed.append(index)
            continue
        donor, receiver = row['donor'], row['receiver']
        if donor not in physical or receiver not in physical:
            return None
        active.update((donor, receiver))
        free_faces.append((index, row))
    if any(physical[key] is None for key in active):
        return None
    buckets = {}
    for identity in active:
        buckets.setdefault(physical[identity][0], []).append(identity)
    node_order = []
    for kind in sorted(buckets):
        bucket = _physical_sorted(buckets[kind], key=physical.__getitem__, arena=arena, adjacent=True)
        if any(physical[a] == physical[b] for a, b in zip(bucket, bucket[1:], strict=False)):
            return None
        node_order.extend(bucket)
    ranks = {identity: rank for rank, identity in enumerate(node_order)}
    edge_order = []
    for role in (0, 1):
        by_node = dict(free_endpoints[role])
        edge_order.extend(by_node[identity] for identity in node_order if identity in by_node)
    def prefix(item):
        return (ranks[item[1]['donor']], ranks[item[1]['receiver']], item[1].get('partition_total', False))
    ordered_faces = _physical_sorted(free_faces, key=prefix, arena=arena, adjacent=True)
    at = 0
    while at < len(ordered_faces):
        end = at + 1
        while end < len(ordered_faces) and prefix(ordered_faces[at]) == prefix(ordered_faces[end]):
            end += 1
        group = ordered_faces[at:end]
        if len(group) == 1:
            edge_order.append(group[0][0])
        else:
            surfaces = [(index, _surface_key(record, row, physical_surfaces)) for index, row in group]
            if any(surface is None for _, surface in surfaces):
                return None
            ordered = _physical_sorted(surfaces, key=lambda item: item[1], arena=arena, adjacent=True)
            if any(a[1] == b[1] for a, b in zip(ordered, ordered[1:], strict=False)):
                return None
            edge_order.extend(index for index, _ in ordered)
        at = end
    node_order.extend(row['cell_id'] for row in rows if row['cell_id'] not in active)
    return node_order, edge_order + fixed



def _close_record(record, start_volumes_m3, budget, *, _selected_fixed=False,
                  stock_keys=None, physical_surfaces=None, _resolved_ports=None):
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
    # Hash-labelled public rows remain untouched. Only the circulation's
    # scratch traversal uses physical identities: a feasible representative
    # must not change when source/funding hashes rename a collar or face.
    # Admit the additional key tables, uniqueness sets, permutations, sorting
    # workspace and restored-value vector BEFORE allocating any of them. This
    # is the existing 1024-byte container policy, not a measured heap bound.
    from .integration_regional_inventory import _width
    order_bytes = 65536 + 1024 * (16 * len(rows) + 8 * len(transfers))
    order_bytes += 8 * _width((stock_keys, physical_surfaces)) + 8 * _physical_region_width(record)
    order_bytes += 8 * sum(_width(r.get('stock_lineage')) for r in rows)
    with LIVE_SPATIAL.workspace(budget, order_bytes) as order_workspace:
        def canonical_choice(order_arena):
            if _selected_fixed:
                # The dual selector establishes unique identities and fixed
                # arcs. Retain the carried-domain, type and port contracts
                # before using the common graph assembly below.
                ids = [row['cell_id'] for row in rows]
                if (set(start_volumes_m3) != material_keys
                        or any(type(key) is not str for key in ids)):
                    raise V.VolumeError('complete unique fixed cell identities required')
                row_by_id = {row['cell_id']: row for row in rows}
                for row in rows:
                    if row['kind'] != 'algebraic-port':
                        continue
                    if _resolved_ports is not None and row['cell_id'] in _resolved_ports:
                        if _resolved_ports[row['cell_id']] is None:
                            raise V.VolumeError('physical port construction preimage is ambiguous or missing')
                        continue
                    parent = row.get('collar_cell_id')
                    if parent not in row_by_id or row_by_id[parent]['kind'] != 'collar':
                        raise V.VolumeError('physical port must name one retained collar')
                    order_arena.work(12*(128+len(parent)))
                    matches = [(axis, end, inward) for axis in range(3)
                               for end in (0, 1) for inward in (False, True)
                               if E._hash(dict(collar=parent, axis=axis, end=end,
                                               inward=inward)) == row['cell_id']]
                    if len(matches) != 1:
                        raise V.VolumeError('physical port construction preimage is ambiguous or missing')
                # Keep the existing bounded circulation's exact arithmetic,
                # incidence checks, work accounting and infeasibility report.
                # Singleton arcs admit at most one vector regardless of order.
                with B._Arena(budget) as arena:
                    return _circulation([reservoir]+ids, edges, arena)
            surface_cache = dict(physical_surfaces or {})
            physical, resolved_ports = _physical_cell_keys(record, stock_keys=stock_keys,
                physical_surfaces=surface_cache, arena=order_arena, _validated_transfers=True)
            ordered = _physical_order(record, physical, surface_cache, order_arena, edges)
            if ordered is not None:
                # Preserve original input integrity on the established route.
                # The selected physical key supersedes source/chart ranking.
                if len(keys) != len(rows) or any(type(r['cell_id']) is not str for r in rows):
                    raise V.VolumeError('unique physical row identities required')
                for row in rows:
                    kind = row['kind']
                    coordinates = ((row['index'],) if kind == 'collar' else
                        (row['source_key'][1], *row['voxel_index'], row['radial_band'])
                        if kind == 'exterior' else ())
                    if any(type(v) is not int or v < 0 for v in coordinates):
                        raise V.VolumeError('nonnegative physical cell coordinate required')
                    if kind in ('collar', 'exterior'):
                        digest = row.get('physical_cell_id') if kind == 'collar' else row['source_key'][0]
                        if (type(digest) is not str or len(digest) != 64 or
                                any(c not in '0123456789abcdef' for c in digest)):
                            raise V.VolumeError('canonical physical source digest required')
                    if kind == 'algebraic-port':
                        parent = row.get('collar_cell_id')
                        if parent not in physical or physical[parent] is None or physical[parent][0] != 0:
                            raise V.VolumeError('physical port must name one retained collar')
                        if resolved_ports.get(row['cell_id']) is None:
                            raise V.VolumeError('physical port construction preimage is ambiguous or missing')
                node_order, edge_order = ordered
                with B._Arena(budget) as arena:
                    values = _circulation([reservoir] + node_order, [edges[i] for i in edge_order], arena)
                restored = [None] * len(edges)
                for original, value in zip(edge_order, values, strict=True):
                    restored[original] = value
                return tuple(restored)
            # The complete unresolved selection stays on the original canonical
            # path below, including its pre-existing validations and refusals.
            coordinate_limbs = 1

            def count(value):
                nonlocal coordinate_limbs
                if type(value) is not int or value < 0:
                    raise V.VolumeError('nonnegative physical cell coordinate required')
                limbs = max(1, (value.bit_length()+63)//64)
                order_arena.work(limbs)
                coordinate_limbs = max(coordinate_limbs, limbs)
                return value

            def digest(value):
                if (type(value) is not str or len(value) != 64
                        or any(c not in '0123456789abcdef' for c in value)):
                    raise V.VolumeError('canonical physical source digest required')
                return value

            physical, collar_indices = {}, set()
            for row in rows:
                key = row['cell_id']
                if type(key) is not str:
                    raise V.VolumeError('unique physical row identities required')
                order_arena.work(1+len(key))
                if key in physical:
                    raise V.VolumeError('unique physical row identities required')
                kind = row['kind']
                if kind == 'collar':
                    at = count(row.get('index'))
                    digest(row.get('physical_cell_id'))
                    if at in collar_indices:
                        raise V.VolumeError('duplicate physical collar index')
                    collar_indices.add(at)
                    physical[key] = (0, at)
                elif kind == 'exterior':
                    source, voxel = row.get('source_key'), row.get('voxel_index')
                    if (type(source) is not list or len(source) != 2
                            or type(voxel) is not list or len(voxel) != 3):
                        raise V.VolumeError('complete physical exterior coordinates required')
                    physical[key] = (1, digest(source[0]), count(source[1]),
                                     tuple(count(v) for v in voxel),
                                     count(row.get('radial_band')), count(row.get('chart')))
                elif kind == 'algebraic-port':
                    # Reserve the label now so duplicate labels cannot disappear
                    # while the two-pass physical port lookup is constructed.
                    physical[key] = None
                else:
                    raise V.VolumeError('unsupported physical circulation cell kind')
            for row in rows:
                if row['kind'] != 'algebraic-port':
                    continue
                parent = row.get('collar_cell_id')
                collar_key = physical.get(parent)
                if collar_key is None or collar_key[0] != 0:
                    raise V.VolumeError('physical port must name one retained collar')
                if row['cell_id'] in resolved_ports:
                    if resolved_ports[row['cell_id']] is None:
                        raise V.VolumeError('physical port construction preimage is ambiguous or missing')
                    physical[row['cell_id']] = resolved_ports[row['cell_id']]
                    continue
                # Existing records omit axis/end/inward. Authenticate exactly the
                # constructor's finite hash preimage; never infer it from volumes,
                # selected flow, the label's ordering or an arbitrary tie-breaker.
                order_arena.work(12*(128+len(parent)))
                matches = [(axis, end, inward) for axis in range(3)
                           for end in (0, 1) for inward in (False, True)
                           if E._hash(dict(collar=parent, axis=axis, end=end,
                                           inward=inward)) == row['cell_id']]
                if len(matches) != 1:
                    raise V.VolumeError('physical port construction preimage is ambiguous or missing')
                physical[row['cell_id']] = (2, collar_key[1], *matches[0])
            if len(set(physical.values())) != len(rows):
                raise V.VolumeError('duplicate physical circulation cell key')
            # Fixed tuple arity plus the actual coordinate limb width bounds
            # each structural comparison. Two N*ceil(log2(N+1)) comparison
            # allowances cover each finite sort, before that sort allocates.
            comparison_work = 16+6*coordinate_limbs
            order_arena.work(2*comparison_work*len(rows)*max(1, len(rows).bit_length()))
            node_order = sorted(physical, key=physical.__getitem__)
            edge_keys = []
            for row in rows:
                key = physical[row['cell_id']]
                edge_keys.extend(((0, key), (1, key)))
            for row in transfers:
                donor, receiver = row['donor'], row['receiver']
                if donor not in physical or receiver not in physical:
                    raise V.VolumeError('physical face endpoint is missing')
                total = row.get('partition_total', False)
                if type(total) is not bool:
                    raise V.VolumeError('physical face partition role must be boolean')
                edge_keys.append((2, physical[donor], physical[receiver], total))
            if len(set(edge_keys)) != len(edge_keys):
                raise V.VolumeError('ambiguous parallel physical circulation faces')
            order_arena.work(2*(8+2*comparison_work)*len(edges)*max(1, len(edges).bit_length()))
            edge_order = sorted(range(len(edges)), key=edge_keys.__getitem__)
            with B._Arena(budget) as arena:
                ordered = _circulation([reservoir]+node_order,
                                       [edges[i] for i in edge_order], arena)
            restored = [None]*len(edges)
            for original, value in zip(edge_order, ordered, strict=True):
                restored[original] = value
            chosen = tuple(restored)
            return chosen
        # On success the helper drops its key/sort borrows before the workspace
        # owner dies. Bind that owner in this frame: a generator context manager
        # alone need not survive exception propagation. A retained traceback
        # keeps this frame and its owner, so the tables remain paid on failure.
        # Only original-order values escape under unchanged output ownership.
        with B._Arena(budget) as order_arena:
            # Includes both structural passes, sets, key vectors and restoration.
            # _Arena preserves the opt-in predicate ledger, or its existing
            # 32-byte/unit fallback, without increasing either caller cap.
            order_arena.work(64*len(rows)+32*len(transfers))
            chosen = canonical_choice(order_arena)
        del canonical_choice
    del order_workspace
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
    result = LIVE_SPATIAL.remaining(record, ('cells', 'face_intervals', 'schema'))
    result.update(schema='atlas.source-bound-spatial-ale-graph.v1', cells=cells, transfers=positive,
        inactive_zero_measure_cells=inactive, original_face_intervals=LIVE_SPATIAL.reference(transfers),
        selected_face_representatives=selected,
        selection='exact bounded circulation; deterministic representative within original intervals, not exact physical quadrature',
        physical_outer_boundary='closed complete funded cone/radial-shell source; true comoving radial/cone relative flux is zero')
    return result


def close_spatial_ale(bounds, start_volumes_m3, *, budget):
    if type(bounds) is not SpatialALEBounds or type(budget) is not WorkBudget or bounds._resource is not budget:
        raise V.VolumeError('issued spatial bounds on the same explicit WorkBudget required')
    if type(start_volumes_m3) is not dict:
        raise V.VolumeError('exact carried volume mapping required')
    with LIVE_SPATIAL.record_access(bounds) as working:
        with LIVE_SPATIAL.workspace(budget, 65536+8*LIVE_SPATIAL.holder_bytes(bounds)), V._work(tuple(start_volumes_m3.values()), budget):
            surfaces = getattr(bounds, '_physical_surfaces', None)
            record = _close_record(working, start_volumes_m3, budget, physical_surfaces=surfaces)
            record['bounds_id'] = bounds.bounds_id
            result = _issue(SpatialALEGraph, record, budget, physical_surfaces=surfaces)
            del record
            return result


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
            motion['funding_id'] != funding.funding_id or flow.descriptor().get('wall_measure_id') != motion['measure_id']):
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
            key = E._hash(dict(kind='collar', cell_id=box.cell_id))
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
        def whole_face(flat, axis, end_):
            if not wall_measures._fresh:
                return W._whole_face(collar_boxes[flat], axis, end_, omega, dt)[0]
            shape = collar.cells
            index = (flat//(shape[1]*shape[2]), flat//shape[2] % shape[1], flat % shape[2])
            transverse = tuple(j for j in range(3) if j != axis)
            offset = sum(2*shape[(a+1)%3]*shape[(a+2)%3] for a in range(axis))
            offset += end_*shape[transverse[0]]*shape[transverse[1]]
            offset += index[transverse[0]]*shape[transverse[1]] + index[transverse[1]]
            face = motion['faces'][offset]
            return tuple(W._decode(face[k]) for k in ('inward_exact_volume_m3', 'outward_exact_volume_m3'))
        ports = {}
        def port(flat, axis, end_, inward):
            identity = (flat, axis, end_, inward)
            if identity not in ports:
                key = E._hash(dict(collar=native_keys[flat], axis=axis, end=end_, inward=inward))
                ports[identity] = key
                cells[key] = dict(cell_id=key, kind='algebraic-port', collar_cell_id=native_keys[flat],
                    start_volume_bounds_m3=[E._enc(0)]*2, end_volume_bounds_m3=[E._enc(0)]*2)
                pair = whole_face(flat, axis, end_)
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
                        pair = whole_face(flat, axis, end_)
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
                add_face(donor, receiver, (final, final), dict(axis=row['axis'], at=row['index'], positive=positive),
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
            component_keys=original['component_keys'], wall_measure_id=motion['measure_id'],
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
