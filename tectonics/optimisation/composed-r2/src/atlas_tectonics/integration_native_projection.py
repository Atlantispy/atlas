"""Exact complete-grid FV closure with a finite, natural basal boundary.

Only one constant numerical normal offset per interior/natural face is allowed.
The mechanical Q2 solution is immutable; prescribed traces stay fixed. Component
positive/negative measures must subsequently integrate this SAME polynomial.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import dataclass, field
from contextlib import ExitStack
from fractions import Fraction as Q
import hashlib
import heapq
import json
from math import comb
import weakref

from . import integration_volume as V
from . import integration_volume_bounds as B
from . import integration_wall_measures as W
from .integration_collar_geometry import FullCellFunding
from .integration_native_faces import NativeFaceMeasures
from .integration_regional_inventory import _width
from .integration_spatial_ale import _circulation
from .resources import WorkBudget


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _close_faces(nodes, faces, *, speed_scale, absolute_limit, relative_limit, budget):
    """Exact bounded *correction* circulation; not physical opposed streams.

    Each row supplies its signed increasing-normal integral and correction
    volume factor A*dt. Temporary reverse arcs parameterise one signed offset;
    only that offset survives. They never become independent material fluxes.
    """
    outside = 'native-projection-exterior'
    if not nodes or len(set(nodes)) != len(nodes) or outside in nodes:
        raise V.VolumeError('unique nonempty complete native cell identities required')
    if min(speed_scale, absolute_limit, relative_limit) < 0:
        raise V.VolumeError('nonnegative original native numerical limits required')
    with B._Arena(budget) as arena:
        residual = dict.fromkeys(nodes, Q(0))
        incident, limits, edges, selected = [], [], [], []
        maximum = min(absolute_limit, relative_limit*speed_scale)
        for face in faces:
            lower, upper = face['lower'], face['upper']
            if ((lower is not None and lower not in residual) or
                    (upper is not None and upper not in residual) or lower == upper):
                raise V.VolumeError('each native face needs actual distinct adjacent cells')
            a = outside if lower is None else lower
            b = outside if upper is None else upper
            factor = face['factor_m2_s']
            old, sampling = face['old_correction_m_s'], face['sampling_error_m_s']
            if factor <= 0 or min(old, sampling) < 0:
                raise V.VolumeError('positive face area/time and nonnegative numerical errors required')
            base = old+sampling  # never reclaim cancellation of earlier corrections
            if base > maximum:
                raise V.VolumeError('existing native/sample correction exceeds ORIGINAL transport allowance')
            cap = maximum-base if face['adjustable'] else Q(0)
            incident.append((a, b)); limits.append(base)
            net = face['signed_volume_m3']
            if lower is not None:
                residual[lower] += net
            if upper is not None:
                residual[upper] -= net
            selected.append(len(edges))
            edges += [(a, b, Q(0), factor*cap), (b, a, Q(0), factor*cap)]
        # Fixed residual edges give precisely B*delta=-div(original Q2).
        # The outside node is algebraic only: the real basal stocks remain
        # separately finite in the subsequent joint material circulation.
        for node, value in residual.items():
            if value > 0:
                edges.append((node, outside, value, value))
            elif value < 0:
                edges.append((outside, node, -value, -value))
        chosen = _circulation([*nodes, outside], edges, arena)
        corrected, final = [], dict.fromkeys(nodes, Q(0))
        for face, (a, b), base, at in zip(faces, incident, limits, selected):
            delta_volume = chosen[at]-chosen[at+1]
            delta = delta_volume/face['factor_m2_s']
            total = base+abs(delta)
            if total > absolute_limit or (total and (not speed_scale or total > relative_limit*speed_scale)):
                raise V.VolumeError('total native normal correction exceeds ORIGINAL transport allowance')
            if not face['adjustable'] and delta:
                raise V.VolumeError('prescribed mechanical face cannot receive a numerical normal offset')
            net = face['signed_volume_m3']+delta_volume
            if a != outside:
                final[a] += net
            if b != outside:
                final[b] -= net
            corrected.append(dict(normal_increment_m_s=delta, signed_volume_m3=net,
                signed_volume_correction_m3=delta_volume, total_normal_correction_bound_m_s=total))
        if any(final.values()):
            raise V.VolumeError('exact complete native cell continuity failed')
        return corrected, residual


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class NativeFluxProjection:
    _json: bytes = field(repr=False)
    _resource: object = field(repr=False, compare=False)
    _measures: object = field(repr=False, compare=False)
    _funding: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('NativeFluxProjection is issued by project_native_faces')

    @property
    def projection_id(self):
        return hashlib.sha256(self._json).hexdigest()

    def record(self):
        return json.loads(self._json)

    def validate_source(self, measures, funding=None):
        if measures is not self._measures or (funding is not None and funding is not self._funding):
            raise V.VolumeError('native projection has another actual measure/funding')
        measures.validate_source(measures._collar, measures._stage)


def project_native_faces(measures, funding, *, budget):
    """Issue one consistent normal offset, or refuse the original limits.

    All actual interior faces and only fully funded natural basal faces are
    adjustable. The other five prescribed walls retain the solved Q2 trace.
    No divergence tolerance or positive-part quadrature error is velocity credit.
    """
    if (type(measures) is not NativeFaceMeasures or type(funding) is not FullCellFunding or
            type(budget) is not WorkBudget or measures._resource is not budget or funding._resource is not budget):
        raise V.VolumeError('actual native measures, finite basal funding and shared budget required')
    measures.validate_source(measures._collar, measures._stage)
    with budget.reserve(131072+12*(len(measures._json)+funding._snapshot.nbytes), category='native-projection-input'):
        record, funded = measures.record(), funding.descriptor()
        basal = funded.get('basal_inventory', {})
        side = basal.get('side')
        if (record['collar_plan_id'] != funded['collar_plan_id'] or record['source'] != funded['source'] or
                side not in ('x0', 'x1', 'y0', 'y1', 'z0', 'z1') or
                basal.get('compartment_kind') != 'reservoir'):
            raise V.VolumeError('matching source with explicit bidirectional basal funding required')
        axis = 'xyz'.index(side[0])
        if measures._collar._native._pattern[side][axis] != 'traction':
            raise V.VolumeError('only an explicitly natural basal normal may be corrected')
        contacts = {(r['lineage']['reservoir']['side'], tuple(r['lineage']['reservoir']['face_index']))
                    for r in basal['stocks'] if r['kind'] == 'reservoir'}
        basal_faces = [r for r in record['faces'] if r['side'] == side]
        required = {(side, tuple(v for j, v in enumerate(r['index']) if j != axis)) for r in basal_faces}
        if contacts != required or len(contacts) != len(basal['stocks']):
            raise V.VolumeError('every corrected basal face needs one actual finite compartment')
        nodes = ['native:'+str(r['index']) for r in record['cells']]
        numerical = []
        for row in record['faces']:
            numerical.append(dict(lower=None if row['lower'] is None else nodes[row['lower']],
                upper=None if row['upper'] is None else nodes[row['upper']],
                signed_volume_m3=W._decode(row['mechanical_exact_signed_volume_m3']),
                factor_m2_s=W._decode(row['physical_area_m2'])*W._decode(row['duration_s']),
                old_correction_m_s=W._decode(row['old_normal_correction_m_s']),
                sampling_error_m_s=max((abs(W._decode(q)) for q in row['raw_sampling_residual_m_s']), default=Q(0)),
                adjustable=row['side'] is None or row['side'] == side))
        speed, absolute, relative = (W._decode(record[k]) for k in
            ('original_native_speed_scale_m_s', 'absolute_limit_m_s', 'relative_limit'))
        corrected, residual = _close_faces(nodes, numerical, speed_scale=speed, absolute_limit=absolute,
                                          relative_limit=relative, budget=budget)
        faces = []
        for original, inputs, values in zip(record['faces'], numerical, corrected):
            polynomial = {(i, j): W._decode(q) for i, j, q in original['mechanical_normal_polynomial_m_s']}
            polynomial[0, 0] = polynomial.get((0, 0), Q(0))+values['normal_increment_m_s']
            faces.append(dict(face_id=original['face_id'], side=original['side'], lower=original['lower'], upper=original['upper'],
                adjustable=inputs['adjustable'],
                corrected_normal_polynomial_m_s=[[i, j, V._encoded(q)] for (i, j), q in sorted(polynomial.items()) if q],
                original_signed_volume_m3=V._encoded(inputs['signed_volume_m3']),
                old_normal_correction_m_s=V._encoded(inputs['old_correction_m_s']),
                sample_evaluation_error_m_s=V._encoded(inputs['sampling_error_m_s']),
                **{k: V._encoded(v) for k, v in values.items()},
                original_booked_positive_m3=original['booked_positive_m3'],
                original_booked_negative_m3=original['booked_negative_m3']))
        output = dict(schema='atlas.complete-grid-native-flux-projection.v1', native_measure_id=measures.measure_id,
            funding_id=funding.funding_id, basal_side=side,
            **{k: record[k] for k in ('collar_plan_id', 'parent_state_id', 'source_flow_stage_id',
                'flow_id', 'mechanical_result_id', 'volume_map_id', 'source', 'start_time_s', 'end_time_s', 'duration_s',
                'absolute_limit_m_s', 'relative_limit', 'original_native_speed_scale_m_s')},
            method='exact bounded normal-offset circulation; interior and natural basal faces only',
            faces=faces, original_cell_divergence_m3={k: V._encoded(q) for k, q in residual.items()},
            final_cell_divergence_m3={k: V._encoded(Q(0)) for k in nodes},
            source_normal_samples_changed=False, mechanical_solution_changed=False,
            numerical_rule='old native correction plus exact sample evaluation error plus absolute face offset; no cancellation reclaimed',
            quadrature_rule='actual Q2 opposed streams must be integrated from this same polynomial; Gauss discrepancy is not velocity credit',
            scope='native numerical continuity only; component mask/finite-stock GCL acceptance remains required')
        with budget.reserve(65536+4*_width(output), category='native-projection-encode'):
            encoded = _json(output)
            lease = budget.reserve(8192+4*len(encoded), category='native-projection-retained'); lease.__enter__()
            try:
                result = object.__new__(NativeFluxProjection)
                for key, value in dict(_json=encoded, _resource=budget, _measures=measures, _funding=funding).items():
                    object.__setattr__(result, key, value)
                weakref.finalize(result, lease.__exit__, None, None, None)
            except BaseException:
                lease.__exit__(None, None, None); raise
        measures.validate_source(measures._collar, measures._stage)
        return result


def _bernstein_range(polynomial, bounds):
    """Exact tensor-Q2 convex-hull bounds after a rectangle affine pullback.

    For q(u,v)=sum a_ij u^i v^j on [0,1]^2, its Bernstein coefficients
    b_kl=sum a_ij C(k,i)/C(2,i) C(l,j)/C(2,j). The basis is nonnegative
    and sums to one, so their extrema enclose q without sampling its roots.
    """
    powers = {}
    for (i, j), value in polynomial.items():
        for k in range(i+1):
            for l in range(j+1):
                term = (value*comb(i, k)*bounds[0][0]**(i-k)*(bounds[0][1]-bounds[0][0])**k*
                        comb(j, l)*bounds[1][0]**(j-l)*(bounds[1][1]-bounds[1][0])**l)
                powers[k, l] = powers.get((k, l), Q(0))+term
    values = [sum((value*Q(comb(k, i), comb(2, i))*Q(comb(l, j), comb(2, j))
                   for (i, j), value in powers.items() if i <= k and j <= l), Q(0))
              for k in range(3) for l in range(3)]
    return min(values), max(values)


def _directed_q2_bounds(polynomial, factor, *, max_width, max_leaves, budget, cancel=None, _arena=None):
    """Enclose both signs; select one counterflow, never independent slack.

    The normalised face has unit area; factor is physical area times duration.
    Each leaf has exact signed integral I. On a sign-changing leaf with area A
    and range [l,h], N is in [max(0,-I), min(-l*A,h*A-I)], and P=N+I.
    Summing these paired intervals preserves the exact full-face signed flux.
    """
    from .regional_heat3d import _cancel
    _cancel(cancel)
    polynomial = {key: Q(value) for key, value in polynomial.items() if value}
    if (any(type(i) is not int or type(j) is not int or not 0 <= i <= 2 or not 0 <= j <= 2
            for i, j in polynomial) or factor <= 0 or max_width < 0 or
            type(max_leaves) is not int or max_leaves < 1):
        raise V.VolumeError('actual Q2, positive area/time, nonnegative width and finite leaf ceiling required')
    from contextlib import nullcontext
    if _arena is not None and _arena.resource is not budget:
        raise V.VolumeError('shared directed quadrature arena has another budget')
    with (B._Arena(budget) if _arena is None else nullcontext(_arena)) as arena:
        def leaf(bounds):
            _cancel(cancel)
            arena.work(32+64*len(polynomial))
            values = (*polynomial.values(), *(q for pair in bounds for q in pair), factor)
            with V._work(values, budget):
                net = sum((value*(bounds[0][1]**(i+1)-bounds[0][0]**(i+1))/Q(i+1)*
                           (bounds[1][1]**(j+1)-bounds[1][0]**(j+1))/Q(j+1)
                           for (i, j), value in polynomial.items()), Q(0))
                low, high = _bernstein_range(polynomial, bounds)
                if low >= 0:
                    pair = (Q(0), Q(0))
                elif high <= 0:
                    pair = (-net, -net)
                else:
                    area = (bounds[0][1]-bounds[0][0])*(bounds[1][1]-bounds[1][0])
                    pair = (max(Q(0), -net), min(-low*area, high*area-net))
                if pair[0] < 0 or pair[1] < pair[0]:
                    raise V.VolumeError('inconsistent exact Q2 directed enclosure')
                arena.keep((*values, net, *pair), 1)
                return net, pair

        unit = ((Q(0), Q(1)),)*2
        signed, (lower, upper) = leaf(unit)
        queue, serial, leaves = [(lower-upper, 0, unit, lower, upper)], 0, 1
        if max_width > 0 and factor*(upper-lower) > max_width:
            from .integration_q2_directed import negative_bounds
            lower, upper, leaves = negative_bounds(polynomial, target_width=max_width/factor,
                max_leaves=max_leaves, budget=budget, bernstein_range=_bernstein_range,cancel=cancel,
                _arena=_arena)
            lower = max(lower,Q(0),-signed)
            if lower > upper:
                raise V.VolumeError('analytic directed enclosure contradicts exact signed flux')
        axes = [axis for axis in range(2) if any(key[axis] for key in polynomial)]
        while factor*(upper-lower) > max_width:
            if leaves >= max_leaves or not queue or not axes:
                raise V.VolumeError('Q2 directed-volume quadrature leaf ceiling reached; no flux accepted')
            _, _, bounds, old_low, old_high = heapq.heappop(queue)
            axis = max(axes, key=lambda j: (bounds[j][1]-bounds[j][0], -j))
            midpoint = sum(bounds[axis])/2
            lower -= old_low; upper -= old_high
            for pair in ((bounds[axis][0], midpoint), (midpoint, bounds[axis][1])):
                child = list(bounds); child[axis] = pair; child = tuple(child)
                _, (lo, hi) = leaf(child)
                lower += lo; upper += hi; serial += 1
                if hi > lo:
                    heapq.heappush(queue, (lo-hi, serial, child, lo, hi))
            leaves += 1
        signed, low, high = factor*signed, factor*lower, factor*upper
        negative = (low+high)/2
        positive = negative+signed
        if min(positive, negative) < 0:
            raise V.VolumeError('paired Q2 directed representative became negative')
        return dict(positive_volume_bounds_m3=(low+signed, high+signed),
            negative_volume_bounds_m3=(low, high), positive_volume_m3=positive,
            negative_volume_m3=negative, signed_volume_m3=signed,
            maximum_chosen_deviation_m3=(high-low)/2, leaves=leaves)


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class NativeDirectedVolumes:
    _json: bytes = field(repr=False)
    _resource: object = field(repr=False, compare=False)
    _measures: object = field(repr=False, compare=False)
    _projection: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('NativeDirectedVolumes is issued by choose_native_directed_volumes')

    @property
    def directed_id(self):
        return hashlib.sha256(self._json).hexdigest()

    def record(self):
        return json.loads(self._json)

    def validate_source(self, measures, projection):
        if measures is not self._measures or projection is not self._projection:
            raise V.VolumeError('directed volumes have another actual native measure/projection')
        projection.validate_source(measures)


def choose_native_directed_volumes(measures, projection, *, max_width_m3, max_leaves, budget, cancel=None):
    """Issue full-face opposed Q2 streams with caller-bounded quadrature only.

    A common midpoint q of N and P-n is chosen, N=q and P=q+n. The exact signed
    n is unchanged, including the separately admitted numerical normal offset.
    Component-mask ownership and subsequent material GCL remain mandatory.
    """
    if (type(measures) is not NativeFaceMeasures or type(projection) is not NativeFluxProjection or
            type(budget) is not WorkBudget or measures._resource is not budget or projection._resource is not budget):
        raise V.VolumeError('issued native measures/projection and shared budget required')
    projection.validate_source(measures)
    width = W._q(max_width_m3)
    if width < 0 or type(max_leaves) is not int or max_leaves < 1:
        raise V.VolumeError('explicit nonnegative quadrature width and finite leaf ceiling required')
    with budget.reserve(131072+12*(len(measures._json)+len(projection._json)), category='native-directed-input'), ExitStack() as retained:
        native, projected = measures.record(), projection.record()
        originals = {row['face_id']: row for row in native['faces']}
        faces = []
        for row in projected['faces']:
            original = originals[row['face_id']]
            polynomial = {(i, j): W._decode(q) for i, j, q in row['corrected_normal_polynomial_m_s']}
            factor = W._decode(original['physical_area_m2'])*W._decode(original['duration_s'])
            selected = _directed_q2_bounds(polynomial, factor, max_width=width, max_leaves=max_leaves, budget=budget,cancel=cancel)
            if selected['signed_volume_m3'] != W._decode(row['signed_volume_m3']):
                raise V.VolumeError('directed quadrature changed the admitted signed face volume')
            retained.enter_context(budget.reserve(4096+16*_width(selected), category='native-directed-face'))
            faces.append(dict(face_id=row['face_id'], side=row['side'], lower=row['lower'], upper=row['upper'],
                corrected_normal_polynomial_m_s=row['corrected_normal_polynomial_m_s'],
                **{key: ([V._encoded(q) for q in value] if isinstance(value, tuple) else
                         value if key == 'leaves' else V._encoded(value)) for key, value in selected.items()}))
        from .integration_q2_directed import source_digest, ORDER
        output = dict(schema='atlas.native-directed-volumes.v1', native_measure_id=measures.measure_id,
            native_projection_id=projection.projection_id,
            **{key: projected[key] for key in ('funding_id', 'collar_plan_id', 'parent_state_id',
                'source_flow_stage_id', 'flow_id', 'mechanical_result_id', 'volume_map_id', 'source',
                'start_time_s', 'end_time_s', 'duration_s')},
            faces=faces, max_width_m3=V._encoded(width), max_leaves=max_leaves,
            analytic_quadrature=dict(source_sha256=source_digest(),decimal_precision=80,taylor_order=ORDER),
            method='exact Q2 Bernstein or analytic quadratic-root/Decimal80 Taylor bounds; dyadic largest-width refinement; paired counterflow midpoint',
            quadrature_rule='positive and negative share one counterflow; exact signed volume unchanged; no velocity credit',
            scope='full-face streams only; no component ownership or material GCL acceptance')
        with budget.reserve(65536+4*_width(output), category='native-directed-encode'):
            encoded = _json(output)
            lease = budget.reserve(8192+4*len(encoded), category='native-directed-retained'); lease.__enter__()
            try:
                result = object.__new__(NativeDirectedVolumes)
                for key, value in dict(_json=encoded, _resource=budget, _measures=measures, _projection=projection).items():
                    object.__setattr__(result, key, value)
                weakref.finalize(result, lease.__exit__, None, None, None)
            except BaseException:
                lease.__exit__(None, None, None); raise
        projection.validate_source(measures)
        return result
