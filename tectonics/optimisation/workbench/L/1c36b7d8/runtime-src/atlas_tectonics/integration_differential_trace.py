"""Owned plate traces projected onto the actual regional Q2 boundary space.

This is an explicitly nonconforming boundary discretisation.  It does not
change a native velocity after solving, treat its FE error as FV round-off,
or impose zero net flux on an open basal boundary.  Endpoint force geometry
and time-integrated prescribed-interval geometry are distinct issued inputs.
SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction as Q
from dataclasses import dataclass, field
import hashlib
import json
import math
import weakref
from contextlib import ExitStack

import numpy as np

from . import integration_differential_geometry as G
from . import integration_regional_driving as D
from . import integration_volume as V
from . import integration_wall_measures as W
from . import integration_sphere as S
from ._validation import TectonicsError, frozen
from .integration_regional_evolution import RegionalVolumeMap
from .regional_execution3d import PreparedRegionalStokes3D, SIDES, _digest_array
from .resources import WorkBudget


POWERS = tuple((i, j) for i in range(4) for j in range(4) if (i, j) != (3, 3))
SCHEMA = 'atlas.differential-q2-trace.v1'


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class IntervalTraceAudit:
    """Final-rate physical trace evidence, explicitly NOT a GCL certificate."""
    _json: bytes = field(repr=False)
    _resource: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('IntervalTraceAudit is issued by audit_interval_solution')

    @property
    def audit_id(self):
        return hashlib.sha256(self._json).hexdigest()

    def record(self):
        return json.loads(self._json)


def _add(a, b):
    result = dict(a)
    for key, value in b.items():
        result[key] = result.get(key, Q(0))+value
    return {k: v for k, v in result.items() if v}


def _scale(a, q):
    return {k: v*q for k, v in a.items() if v*q}


def _mul(a, b):
    result = {}
    for (i, j), p in a.items():
        for (k, l), q in b.items():
            key = i+k, j+l
            result[key] = result.get(key, Q(0))+p*q
    return {k: v for k, v in result.items() if v}


def _power(a, n):
    result = {(0, 0): Q(1)}
    for _ in range(n):
        result = _mul(result, a)
    return result


def _normalised_queries(bounds):
    u, v = ({(0, 0): -a/(b-a), (int(j == 0), int(j == 1)): 1/(b-a)}
            for j, (a, b) in enumerate(bounds))
    return tuple(tuple((i, j, q) for (i, j), q in sorted(_mul(_power(u, p), _power(v, r)).items()))
                 for p, r in POWERS)


def _contact_queries(native_face, exterior_face):
    """Native normalised monomials in an exactly coincident exterior chart.

    A neighbouring material voxel may have a different origin or tangent
    orientation. Comparing its raw u/v monomials would silently change the
    constraint. Only a coplanar, opposite-facing rectangle contained in the
    native face is admitted; no Cartesian AABB or coordinate snapping is used.
    """
    dot = lambda a, b: sum((x*y for x, y in zip(a, b)), Q(0))
    origin, eu, ev, normal, bounds = native_face
    other, tu, tv, outward, rectangle = exterior_face
    delta = tuple(a-b for a, b in zip(other, origin))
    if (tuple(-v for v in normal) != outward or dot(normal, delta) or
            dot(normal, tu) or dot(normal, tv)):
        raise TectonicsError('component contact is not an exact opposite native face')
    coordinates = []
    for tangent, (low, high) in zip((eu, ev), bounds):
        constant = dot(tangent, delta)
        first, second = dot(tangent, tu), dot(tangent, tv)
        for u, v in W._rectangle(rectangle):
            if not low <= constant+first*u+second*v <= high:
                raise TectonicsError('component contact extends outside the actual native face')
        coordinates.append({power: value/(high-low) for power, value in
            (((0, 0), constant-low), ((1, 0), first), ((0, 1), second)) if value})
    return tuple(tuple((i, j, q) for (i, j), q in
                       sorted(_mul(_power(coordinates[0], p), _power(coordinates[1], r)).items()))
                 for p, r in POWERS)


def _shape():
    one = ({0: Q(1), 1: Q(-3), 2: Q(2)}, {1: Q(4), 2: Q(-4)}, {1: Q(-1), 2: Q(2)})
    return tuple({(i, j): a*b for i, a in u.items() for j, b in v.items()}
                 for u in one for v in one)


SHAPE = _shape()


def _integral(poly, area, duration):
    return area*duration*sum((v/Q((i+1)*(j+1)) for (i, j), v in poly.items()), Q(0))


def _enclosed(poly, moments):
    lower = upper = Q(0)
    for key, coefficient in poly.items():
        lo, hi = moments[key]
        lower += coefficient*(lo if coefficient >= 0 else hi)
        upper += coefficient*(hi if coefficient >= 0 else lo)
    return lower, upper


def _point_modes(cell, axis, end):
    """Six? No: three physical global angular modes, in native components."""
    origin, eu, ev, _, bounds = W._face(cell, axis, end)
    x0 = W._point((origin, eu, ev), (bounds[0][0], bounds[1][0]))
    du = tuple(q*(bounds[0][1]-bounds[0][0]) for q in eu)
    dv = tuple(q*(bounds[1][1]-bounds[1][0]) for q in ev)
    vectors = []
    for k in range(3):
        unit = tuple(Q(int(i == k)) for i in range(3))
        cross = lambda x: tuple(unit[(i+1) % 3]*x[(i+2) % 3]-unit[(i+2) % 3]*x[(i+1) % 3] for i in range(3))
        coefficients = [cross(x) for x in (x0, du, dv)]
        vectors.append(tuple({power: sum(cell.basis[i][j]*c[i] for i in range(3))
                              for power, c in zip(((0, 0), (1, 0), (0, 1)), coefficients)
                              if sum(cell.basis[i][j]*c[i] for i in range(3))}
                             for j in range(3)))
    return tuple(vectors)


def _linear_solve(matrix, rhs):
    # Use the actual retained D1 policy for a general matrix: conditioning
    # <=1e12 and normwise residual <=1e-11. A new componentwise check would
    # divide cancellation at analytically zero entries by its own round-off.
    # Exact physical trace/flux and dual-norm enclosures are checked separately.
    result, _ = D.D._general_solve(matrix, rhs)
    if not np.isfinite(result).all():
        raise TectonicsError('Q2 trace projection produced nonfinite coefficients')
    return result


def _dual_bound(exact_mass, reaction, dual, lower_eigenvalue):
    """Certify r'M^-1r using exact residuals, not a fitted solver allowance.

    For any computed t, r'M^-1r = 2r't-t'Mt + e'M^-1e, e=r-Mt.
    Q2's one-dimensional reference mass has Gershgorin lower bound 1/30;
    its tensor product has lower bound 1/900. Assembly adds the incident
    face area*time weights, giving the supplied strictly positive bound.
    """
    r, t = tuple(Q(float(v)) for v in reaction), tuple(Q(float(v)) for v in dual)
    residual = list(r)
    energy = Q(0)
    for (i, j), value in exact_mass.items():
        residual[i] -= value*t[j]
        energy += value*t[i]*t[j]
    upper = 2*sum((a*b for a, b in zip(r, t)), Q(0))-energy
    upper += sum((v*v for v in residual), Q(0))/lower_eigenvalue
    if upper < 0:
        raise TectonicsError('invalid certified boundary mass dual norm')
    return upper


def _rational_reservation(values, objects=0):
    """Integer-width storage plus rational/object bookkeeping, not a bit cap."""
    return 4096+256*objects+128*len(values)+8*sum((V._bits(v)+7)//8 for v in values)


def _radius_up(value):
    """A 24-bit dyadic upper bound of one nonnegative rational radius."""
    if value <= 0:
        return Q(0)
    n, d = value.numerator, value.denominator
    shift = 24-(n.bit_length()-d.bit_length())
    if shift >= 0:
        return Q(-((-n << shift)//d), 1 << shift)
    return Q(-((-n)//(d << -shift)) << -shift)


def _independent_constraints(rows, targets, budget, *, retained_basis=None, radii=None, resolution=Q(0),
                            enclosed=None):
    """Exact dependence or an unresolved enclosure only; all rows stay audited.

    Midpoints define the numerical KKT matrix, not a new physical support.
    Dependent target intervals must contain the exact zero equation. The
    final represented flux is still tested on ALL original physical rows.
    No SVD threshold, normal-velocity tolerance or area pruning is applied
    to an exact row.

    ``radii`` are the certified half-widths of ENCLOSED row coefficients (a
    time-integrated moving mask is known only as an interval about its
    midpoint). They are carried through the elimination as in interval
    Gaussian elimination: subtracting ``a_p b`` from a row adds
    ``(|a_p|+r_p) e_j + r_p |b_j|`` to its radius at j, where ``r_p`` is the
    row's own radius at the pivot and ``e`` the pivot row's; dividing a new
    pivot row by its pivot ``a_p`` gives ``(r_j+|b_j| r_p)/(|a_p|-r_p)``.
    A basis pivot is passed over only where the row has neither a midpoint
    nor a radius. With ``a_p = 0`` and ``r_p > 0`` the true multiplier is
    anywhere within ``r_p``: midpoints and target stay as they are and the
    radius takes ``r_p (e_j+|b_j|)``. The true row, eliminated at every
    earlier pivot, then lies within that radius of the midpoint remainder.

    When no remaining coefficient exceeds the radius in max norm, an empty
    remainder included, the true rows may be exactly dependent (a face's
    component masks sum to its plate mask) and the remainder is enclosure
    arithmetic, not a physical equation. Scaling it to unit size would put a
    noise row with a noise target in the KKT system, so it is left out of the
    numerical equations. It is NOT called dependent, its target is not tested
    against zero, and it stays in the final audit. Only a row left with no
    remainder and no radius is exactly dependent.

    ``resolution`` is the caller's declared resolution of an enclosed
    remainder ``rho`` in 1-norm. ``|rho . v| <= |rho|_1 max|v_i|`` whatever
    the support, so when it is a declared stream width over a bound of the
    nodal normal speeds, a remainder not above it cannot change a represented
    stream by that width at speeds within the bound. Without it a row far
    below every declared width enters at unit weight whenever its enclosure
    happens to be narrow and is left out whenever it is not, so the
    constraint set would follow the integrator's accuracy and not the
    geometry. It is a declared selection threshold of the numerical equations
    and certifies no stream; the final audit of every row does.

    ``enclosed`` receives (row number, remaining max norm, radius max norm,
    remaining 1-norm) for every enclosed row that reaches this decision. The
    row is kept only if its max norm exceeds the radius and its 1-norm
    exceeds ``resolution``; it is unresolved when either does not.
    With exact rows (no radii) every decision and reservation is the exact
    rule, and ``resolution`` is not consulted.
    """
    selected, basis = [], []
    with ExitStack() as temporary:
        retained = temporary if retained_basis is None else retained_basis
        for number, (original, bounds) in enumerate(zip(rows, targets)):
            row, rhs = dict(original), list(bounds)
            radius = {} if radii is None else {i: _radius_up(q) for i, q in radii[number].items() if q}
            for pivot, known, right, known_radius in basis:
                factor = row.get(pivot, Q(0))
                if not factor and pivot not in radius:
                    continue
                # A zero midpoint multiplier with a radius changes no midpoint
                # or target: only the radii below are computed and reserved.
                operands = tuple(known.values())
                if factor:
                    operands += (*row.values(), factor, *(q for pair in (*rhs, *right) for q in pair))
                with budget.reserve(32768+64*sum((V._bits(q)+7)//8 for q in operands)+
                                    1024*(len(known)+(len(row)+len(rhs) if factor else 0))+
                                    256*(len(radius)+len(known_radius)),
                                    category='differential-trace-exact-rank-work'):
                    if factor:
                        row = _add(row, _scale(known, -factor))
                        rhs = [(a-factor*(d if factor >= 0 else c),
                                b-factor*(c if factor >= 0 else d))
                               for (a, b), (c, d) in zip(rhs, right)]
                    own = radius.pop(pivot, Q(0))
                    if known_radius or own:
                        size = _radius_up(abs(factor)+own)
                        for i, q in known_radius.items():
                            radius[i] = _radius_up(radius.get(i, Q(0))+size*q)
                        if own:
                            for i, q in known.items():
                                if i != pivot:
                                    radius[i] = _radius_up(radius.get(i, Q(0))+own*abs(q))
            if not row and not radius:
                if any(not a <= 0 <= b for a, b in rhs):
                    raise TectonicsError('dependent physical component constraints have incompatible normal targets')
                continue
            if radius:
                uncertain = max(radius.values())
                operands = (*row.values(), uncertain, resolution)
                with budget.reserve(32768+64*sum((V._bits(q)+7)//8 for q in operands)+1024*len(row),
                                    category='differential-trace-exact-rank-work'):
                    remaining = max(map(abs, row.values()), default=Q(0))
                    total = sum(map(abs, row.values()), Q(0))
                    unresolved = remaining <= uncertain or total <= resolution
                if enclosed is not None:
                    values = remaining, uncertain, total
                    retained.enter_context(budget.reserve(_rational_reservation(values, len(values)),
                        category='differential-trace-exact-rank-retained'))
                    enclosed.append((number, *values))
                if unresolved:
                    continue
            # Choose equation coordinates before binary64 conversion. A tiny
            # first column can make exact RREF rows almost parallel after
            # scaling, although a different pivot gives the same well-scaled
            # constraints. No nonzero entry or independent row is discarded.
            pivot = max(row, key=lambda i: (abs(row[i]), -i)); factor = row[pivot]
            row = {j: q/factor for j, q in row.items()}
            rhs = [(a/factor, b/factor) if factor > 0 else (b/factor, a/factor) for a, b in rhs]
            # The kept pivot exceeds every radius, so the divisor is positive.
            own = radius.pop(pivot, Q(0))
            if radius or own:
                radius = {i: _radius_up((radius.get(i, Q(0))+abs(row.get(i, Q(0)))*own)/(abs(factor)-own))
                          for i in sorted(set(radius) | (set(row) if own else set())) if i != pivot}
            values = (*row.values(), *(q for pair in rhs for q in pair), *radius.values())
            retained.enter_context(budget.reserve(_rational_reservation(values, len(values)),
                category='differential-trace-exact-rank-retained'))
            selected.append(number); basis.append((pivot, row, rhs, radius))
        if retained_basis is not None:
            # Exact backwards elimination is a change of equation coordinates,
            # not removal of nearly dependent physical rows. Their tiny exact
            # differences must not be rounded away before numerical solving.
            basis = [entry[:3] for entry in basis]
            for at in range(len(basis)-1, -1, -1):
                pivot, known, right = basis[at]
                for j in range(at):
                    old_pivot, row, rhs = basis[j]
                    factor = row.get(pivot, Q(0))
                    if not factor:
                        continue
                    operands = (*row.values(), *known.values(), factor,
                                *(q for pair in (*rhs, *right) for q in pair))
                    with budget.reserve(32768+64*sum((V._bits(q)+7)//8 for q in operands)+
                                        1024*(len(row)+len(known)+len(rhs)),
                                        category='differential-trace-exact-rank-work'):
                        row = _add(row, _scale(known, -factor))
                        rhs = [(a-factor*(d if factor >= 0 else c),
                                b-factor*(c if factor >= 0 else d))
                               for (a, b), (c, d) in zip(rhs, right)]
                    values = (*row.values(), *(q for pair in rhs for q in pair))
                    retained.enter_context(budget.reserve(_rational_reservation(values, len(values)),
                        category='differential-trace-exact-rank-retained'))
                    basis[j] = old_pivot, row, rhs
            normalised = []
            for _, row, rhs in basis:
                scale = max(map(abs, row.values()))
                normalised.append(({i: q/scale for i, q in row.items()},
                                   tuple((a/scale, b/scale) for a, b in rhs)))
            values = tuple(q for row, rhs in normalised for q in
                           (*row.values(), *(q for pair in rhs for q in pair)))
            retained.enter_context(budget.reserve(_rational_reservation(values, len(values)),
                category='differential-trace-exact-rank-retained'))
            return selected, normalised
    return selected


def _coefficient_resolution(width, sphere_radius, rates):
    """Declared 1-norm resolution of an interval trace's enclosed remainders.

    ``|rho . v| <= |rho|_1 max|v_i|`` for a remainder rho of any support. No
    rigid speed of the candidate plate ``rates`` exceeds ``R |omega|_1``
    within the sphere radius R, so a remainder whose 1-norm is not above
    ``width/(R |omega|_1)`` moves no stream by the declared stream ``width``
    at nodal normal speeds within that bound. A predictor trace is solved
    with rates that may differ from the candidate rates, so this is a
    declared selection threshold: the final actual-rate audit of every row is
    what certifies the streams. Plates at rest declare no resolution.
    """
    speed = sphere_radius*max(sum(map(abs, rate)) for rate in rates)
    return width/speed if speed else Q(0)


def _unresolved_record(enclosed, resolution, budget):
    """What the enclosure rule adds to a component-partition record.

    ``enclosed`` and ``resolution`` are those of ``_independent_constraints``.
    Nothing is added when every enclosed row was kept, so such a trace keeps
    its identity. Otherwise the partition rule names the unresolved rows as
    left out beside the exact dependent ones, and they are listed with the
    two margins that condition the decision. A row's margin is the smaller of
    its remaining max norm over the radius and, with a positive resolution,
    its remaining 1-norm over that: above one for a kept row, at most one for
    an unresolved row.
    """
    if not enclosed:
        return {}
    values = tuple(q for _, *entry in enclosed for q in entry)
    with budget.reserve(32768+64*sum((V._bits(q)+7)//8 for q in (*values, resolution))+1024*len(values),
                        category='differential-trace-exact-rank-work'):
        margins = [(number, a > b and one > resolution, min(a/b, one/resolution) if resolution else a/b)
                   for number, a, b, one in enclosed]
        unresolved = [(number, margin) for number, kept, margin in margins if not kept]
        if not unresolved:
            return {}
        resolved = [margin for _, kept, margin in margins if kept]
        return dict(
            rule='all actual component-mask rows retained; exact dependent equations and the listed '
                 'enclosure-unresolved rows only removed from numerical KKT; unresolved rows still audited',
            enclosure_unresolved_rows=dict(rows=[number for number, _ in unresolved],
                declared_coefficient_resolution=V._encoded(resolution),
                largest_unresolved_remaining_over_limit=float(max(margin for _, margin in unresolved)),
                smallest_resolved_remaining_over_limit=float(min(resolved)) if resolved else None,
                rule='remaining max-norm coefficient not above the propagated certified enclosure radius, or '
                     'remaining 1-norm not above the declared coefficient resolution; margins are the smaller '
                     'of max norm over radius and 1-norm over a positive resolution; the resolution of an '
                     'interval trace is the declared stream width over the rigid plate speed bound R*|omega|_1 '
                     'of its candidate rates, zero otherwise; it is a declared selection threshold, since a '
                     'predictor trace may be solved at other rates, and the final actual-rate audit of every '
                     'row certifies the streams; left out of the numerical KKT only, never called dependent '
                     'and still audited'))


def _partition_endpoint(partition, geometry, *, static, endpoint, network_id):
    """Which endpoint of an already typed partition is the physical pose?

    A current pose after an accepted interval is its retained END, not a new
    initial partition and never the original start. The caller performs the
    source/native-cell/resource checks before consuming any returned endpoint.
    """
    continued = static and partition['scope'] == 'physical-interval'
    if continued:
        matches = (geometry.get('accepted_interval_id') == partition.get('interval_id') and
            geometry.get('accepted_support_id') == partition.get('end_support_id') and
            geometry.get('accepted_trajectory_id') == partition.get('trajectory_id') and
            geometry.get('trajectory') == partition.get('trajectory') and
            partition.get('endpoint_network_id') == network_id and
            partition['end_time_s'] == geometry['time_s'])
        evaluation = 'end'
    else:
        matches = (partition['scope'] == 'initial-current' and
            partition.get('current_geometry_id') == geometry.get('geometry_id') if static else
            partition['scope'] == 'physical-interval' and partition.get('interval_id') == geometry.get('interval_id'))
        matches = (matches and partition['network_id'] == (network_id if endpoint != 'end' else geometry['parent_network_id']) and
            partition['start_time_s'] == geometry['start_time_s'] and partition['end_time_s'] == geometry['end_time_s'])
        evaluation = 'start' if static else endpoint
    if not matches:
        raise TectonicsError('component partition differs from the actual accepted geometry or clock')
    return evaluation


class _TraceConstructionScratchOwner:
    """Keep only release callbacks alive with an escaping construction error."""
    def __init__(self, stack):
        self.release = weakref.finalize(self, stack.close)


class PreparedDifferentialTrace:
    """Finite, source-bound Q2 L2 projection with physical face-flux moments.

    The current implementation uses a declared dense boundary KKT solve, not
    an unbounded factor cache. Its full storage/factor scratch is admitted
    before allocation. Basal ``open_side`` is natural in all three components;
    all other faces are prescribed. The pressure/reservoir law is supplied to
    the actual mechanics independently, never invented by this projector.
    """
    def __setattr__(self, key, value):
        if not key.startswith('_') and hasattr(self, key):
            raise TectonicsError('differential trace definitions are immutable')
        object.__setattr__(self, key, value)

    def __init__(self, native, volume_map, interval, layer, *, network, plate_ids, endpoint,
                 open_side, max_moment_width, max_volume_width, max_leaves, budget,
                 component_partition=None, interval_predictor=False, force_geometry=None):
        scratch = ExitStack()
        owner = _TraceConstructionScratchOwner(scratch)
        try:
            self._construct(native, volume_map, interval, layer, network=network,
                plate_ids=plate_ids, endpoint=endpoint, open_side=open_side,
                max_moment_width=max_moment_width, max_volume_width=max_volume_width,
                max_leaves=max_leaves, budget=budget, component_partition=component_partition,
                interval_predictor=interval_predictor, force_geometry=force_geometry,
                _construction_scratch=scratch)
        except BaseException as error:
            # The traceback still owns construction locals. Keep their scratch
            # charged until that escaping error and traceback become unreachable.
            owners = getattr(error, '_trace_construction_scratch_owners', ())
            error._trace_construction_scratch_owners = (*owners, owner)
            raise
        else:
            # The helper's transient locals die before this release. Dense KKT
            # capacity, retained fields/receipts and predictor owners stay live.
            owner.release()

    def _construct(self, native, volume_map, interval, layer, *, network, plate_ids, endpoint,
                   open_side, max_moment_width, max_volume_width, max_leaves, budget,
                   component_partition=None, interval_predictor=False, force_geometry=None,
                   _construction_scratch):
        self._guard = None
        self._retained = ExitStack()
        if (type(native) is not PreparedRegionalStokes3D or type(volume_map) is not RegionalVolumeMap or
                type(interval) not in (G.DifferentialInterval, G.CurrentGeometry) or type(layer) is not V.RadialLayer or
                type(network) is not S.SphereNetwork or
                type(budget) is not WorkBudget or native._resource is not budget or interval._resource is not budget):
            raise TectonicsError('issued native, physical map, differential geometry and shared budget required')
        if ((endpoint is not None and type(endpoint) is not str) or endpoint not in (None, 'start', 'end', 'current') or
                type(open_side) is not str or open_side not in SIDES or
                (type(interval) is G.CurrentGeometry) != (endpoint == 'current')):
            raise TectonicsError('explicit endpoint or interval projection and one open physical face required')
        data, plan, mapped = interval.record(), native.descriptor(), volume_map.record()
        volume_map.native_binding(native)
        static = type(interval) is G.CurrentGeometry
        if type(interval_predictor) is not bool:
            raise TectonicsError('interval predictor selection must be explicit boolean')
        current_force = None
        if interval_predictor:
            if (static or endpoint is not None or type(force_geometry) is not G.CurrentGeometry or
                    force_geometry._resource is not budget or component_partition is None):
                raise TectonicsError('interval predictor needs complete component masks and accepted-start force geometry')
            current_force = force_geometry.record()
            if (current_force['network_id'] != data['parent_network_id'] or
                    current_force['time_s'] != data['start_time_s'] or
                    current_force.get('accepted_trajectory_id', W._hash([])) != data['prior_trajectory_id'] or
                    (current_force.get('accepted_support_id') is not None and
                     current_force['accepted_support_id'] != data['start_support_id'])):
                raise TectonicsError('interval predictor force geometry is not its actual accepted start')
        elif force_geometry is not None:
            raise TectonicsError('separate force geometry belongs only to an explicit interval predictor')
        expected_network = data['network_id'] if static else data['endpoint_network_id' if endpoint == 'end' else 'parent_network_id']
        if (network.network_id != expected_network or
                network.sphere.descriptor() != mapped['embedding']['sphere']):
            raise TectonicsError('trace needs the actual current network on the original physical sphere/frame')
        owners = data['plate_ids'] if static else tuple(data['plate_angular_velocity_rad_s'])
        if (type(plate_ids) is not tuple or len(plate_ids) != 2 or any(type(p) is not str for p in plate_ids) or
                len(set(plate_ids)) != 2 or any(p not in owners for p in plate_ids)):
            raise TectonicsError('two distinct actual plate owners required')
        if layer.radius_m != W._decode(data['radius_m']):
            raise TectonicsError('radial trace support differs from the actual sphere')
        for side in SIDES:
            expected = ['traction']*3 if side == open_side else ['velocity']*3
            if list(plan['boundary_types'][side]) != expected:
                raise TectonicsError('top/lateral prescribed trace and explicit full-traction open face required')
        if plan['physical_mean_pressure_pa'] is not None:
            raise TectonicsError('natural normal traction fixes pressure; no second mean-pressure datum')
        width, volume_width = W._q(max_moment_width), W._q(max_volume_width)
        if min(width, volume_width) < 0 or type(max_leaves) is not int or max_leaves < 1:
            raise TectonicsError('finite caller-declared moment/work bounds required')
        if static and volume_width:
            # A current-state trace declares no material velocity and reads no
            # rate: its faces and component walls are asked for spatial
            # moments only, and a rate width would certify nothing.
            raise TectonicsError('a current-state trace certifies no volume rate; its volume width must be zero')
        counts = tuple(plan['cells']); shape = tuple(2*n+1 for n in counts)
        nv = math.prod(shape)
        mask = native.velocity_mask().ravel()
        fixed = np.flatnonzero(mask)
        # Five boundary surfaces, one normal constraint per physical cell face.
        nc = sum(math.prod(counts[j] for j in range(3) if j != 'xyz'.index(s[0])) for s in SIDES if s != open_side)
        partition = None
        component_endpoint = 'start' if static else endpoint
        contact_groups, supports = {}, {}
        if component_partition is not None:
            if (type(component_partition) is not G.DifferentialPartition or
                    component_partition._resource is not budget):
                raise TectonicsError('component constraints require an issued complete differential partition')
            partition = component_partition.record()
            identified = dict(data, **({'geometry_id': interval.geometry_id} if static else {'interval_id': interval.interval_id}))
            component_endpoint = _partition_endpoint(partition, identified, static=static, endpoint=endpoint,
                                                     network_id=network.network_id)
            if (partition['source'] != mapped['source'] or partition['volume_map_id'] != volume_map.volume_map_id or
                    partition['native_cells'] != [row['cell'] for row in mapped['cell_sources']]):
                raise TectonicsError('component partition differs from the actual source, native cells, geometry or clock')
            supports = {support.support_id: support for support in component_partition.supports}
            if set(supports) != set(partition['support_ids']):
                raise TectonicsError('complete component partition lost an issued support')
            for group in partition['native_contacts']:
                key = group['native_index'], group['axis'], group['end']
                if key in contact_groups:
                    raise TectonicsError('duplicate native component-contact group')
                contact_groups[key] = group
                if group['side'] != open_side:
                    if group['excluded_subfaces']:
                        raise TectonicsError('a prescribed rigid trace overlaps an excluded natural reservoir contact')
                    nc += len(group['contacts'])
        size = 65536+64*(len(fixed)+nc)**2+4096*(nv+nc)+16*len(volume_map._record)
        self._guard = budget.reserve(size, category='differential-q2-trace-dense-kkt')
        self._guard.__enter__()
        try:
            self._budget, self._native, self._interval = budget, native, interval
            self._endpoint, self._plate_ids, self._fixed = endpoint, plate_ids, fixed
            self._interval_predictor = interval_predictor
            duration = Q(1) if endpoint is not None else W._decode(data['duration_s'])
            nd = len(fixed); index = {int(d): i for i, d in enumerate(fixed)}
            mass = np.zeros((nd, nd)); load_lo = np.zeros((nd, 6)); load_hi = np.zeros_like(load_lo)
            constraints, flux_lo, flux_hi, energy_lo, energy_hi, receipts = [], [], [], np.zeros((6, 6)), np.zeros((6, 6)), []
            exact_mass, exact_load, exact_energy = {}, {}, {}
            # Exact outputs live beside the binary64 KKT system. Charge
            # retained rational fields by their actual integer widths; the
            # following lifetime stack also bounds cumulative assembly work.
            def retain(values, objects=0):
                self._retained.enter_context(budget.reserve(_rational_reservation(values, objects),
                    category='differential-trace-exact-assembly'))
            incident = [Q(0)]*nd
            exact_constraints, exact_flux, constraint_bounds = [], [], []
            face_records = []
            cells = [V.CartesianCell.from_record(r['cell'], budget=budget) for r in mapped['cell_sources']]
            for side in SIDES:
                if side == open_side:
                    continue
                axis, end = 'xyz'.index(side[0]), int(side[1]); other = [j for j in range(3) if j != axis]
                for flat, cell in enumerate(cells):
                    ijk = np.unravel_index(flat, counts)
                    if ijk[axis] != (counts[axis]-1 if end else 0):
                        continue
                    low_r2, high_r2 = cell.radial_bounds_squared_m2
                    if low_r2 < (layer.radius_m-layer.bottom_depth_m)**2 or high_r2 > (layer.radius_m-layer.top_depth_m)**2:
                        raise TectonicsError('trace cell is not wholly within declared physical radial support')
                    face = W._face(cell, axis, end); bounds = face[4]
                    area = math.prod(b-a for a, b in bounds)
                    queries = _normalised_queries(bounds); modes = _point_modes(cell, axis, end)
                    nodes = []
                    for i in range(3):
                        for j in range(3):
                            at = [2*v for v in ijk]; at[axis] += 2*end; at[other[0]] += i; at[other[1]] += j
                            nodes.append(int(np.ravel_multi_index(tuple(at), shape)))
                    normal = np.zeros(nd); exact_normal = {}
                    for a, node in enumerate(nodes):
                        entry = (2*end-1)*_integral(SHAPE[a], area, duration)
                        normal[index[3*node+axis]] = float(entry)
                        exact_normal[index[3*node+axis]] = entry
                        for component in range(3):
                            incident[index[3*node+component]] += area*duration
                        for b, second in enumerate(nodes):
                            m = _integral(_mul(SHAPE[a], SHAPE[b]), area, duration)
                            for component in range(3):
                                key = index[3*node+component], index[3*second+component]
                                exact_mass[key] = exact_mass.get(key, Q(0))+m
                    target_lo, target_hi = np.zeros(6), np.zeros(6)
                    exact_target = [(Q(0), Q(0))]*6
                    coverage = [Q(0), Q(0)]
                    for plate in owners:
                        selected = plate in plate_ids
                        polynomials = queries if selected else (queries[0],)
                        arguments = dict(moment_polynomials=polynomials,
                            max_moment_widths=(width,)*len(polynomials) if selected else (Q(0),),
                            max_leaves=max_leaves, budget=budget)
                        if static:
                            measure = G.enclose_current_face(interval, plate, layer, cell, axis, end, **arguments)
                        elif endpoint is None:
                            measure = G.enclose_differential_wall(interval, plate, layer, cell, axis, end,
                                max_width_m3=volume_width, **arguments)
                        else:
                            measure = G.enclose_differential_face_at(interval, plate, layer, cell, axis, end,
                                endpoint=endpoint, max_rate_width_m3_s=volume_width, **arguments)
                        # The issued measure charges its own encoded bytes.
                        # This separate retained copy, final definition and
                        # JSON encoding belong to this projector's lifetime.
                        self._retained.enter_context(budget.reserve(8192+12*len(measure._json),
                            category='differential-trace-moment-record'))
                        record = measure.record()
                        if not record['met']:
                            error = TectonicsError('physical trace moments did not meet caller-declared bounds')
                            error.physical_measure_failure = dict(measure=record,
                                query=dict(plate_id=plate, cell=cell.record(), axis=axis, end=end,
                                    endpoint=endpoint, moment_polynomials=record['moment_polynomials'],
                                    max_moment_widths=[V._encoded(width)]*len(polynomials),
                                    max_width_m3=V._encoded(volume_width), max_leaves=max_leaves),
                                geometry=interval.descriptor())
                            raise error
                        moments = {key: tuple(map(W._decode, values)) for key, values in zip(POWERS, record['moment_bounds'])}
                        # Reserve products, denominator combinations and the
                        # small polynomial sums BEFORE producing the load.
                        arithmetic = tuple(q for pair in moments.values() for q in pair)+cell._geometry()
                        _construction_scratch.enter_context(budget.reserve(
                            32768+32*sum(V._bits(q) for q in arithmetic),
                            category='differential-trace-rational-work'))
                        coverage[0] += moments[(0, 0)][0]
                        coverage[1] += moments[(0, 0)][1]
                        if not selected:
                            if moments[(0, 0)][1] != 0:
                                raise TectonicsError('an unselected plate owns actual prescribed interface area')
                            continue
                        receipts.append(record)
                        owner = plate_ids.index(plate)
                        for k in range(3):
                            mode = 3*owner+k
                            target = _enclosed(_scale(modes[k][axis], 2*end-1), moments)
                            exact_target[mode] = target
                            target_lo[mode], target_hi[mode] = map(float, target)
                            for a, node in enumerate(nodes):
                                for component in range(3):
                                    key = index[3*node+component], mode
                                    entry = _enclosed(_mul(SHAPE[a], modes[k][component]), moments)
                                    previous = exact_load.get(key, (Q(0), Q(0)))
                                    exact_load[key] = previous[0]+entry[0], previous[1]+entry[1]
                            for l in range(3):
                                poly = {}
                                for component in range(3):
                                    poly = _add(poly, _mul(modes[k][component], modes[l][component]))
                                key = mode, 3*owner+l; value = _enclosed(poly, moments)
                                prior = exact_energy.get(key, (Q(0), Q(0)))
                                exact_energy[key] = prior[0]+value[0], prior[1]+value[1]
                    if not coverage[0] <= area*duration <= coverage[1]:
                        raise TectonicsError('owned physical faces do not enclose the complete prescribed face')
                    constraints.append(normal); flux_lo.append(target_lo); flux_hi.append(target_hi)
                    exact_constraints.append(exact_normal); exact_flux.append(tuple(exact_target))
                    constraint_bounds.append({i: (q, q) for i, q in exact_normal.items()})
                    retain(tuple(exact_normal.values())+tuple(q for pair in exact_target for q in pair), len(exact_normal)+6)
                    face_records.append(dict(side=side, native_cell_index=list(map(int, ijk)), physical_cell_id=cell.cell_id))
                    if partition is not None:
                        group = contact_groups.get((flat, axis, end))
                        if group is None or group['physical_cell_id'] != cell.cell_id:
                            raise TectonicsError('issued partition omits an actual prescribed native face')
                        for contact in group['contacts']:
                            support = supports.get(contact['support_id'])
                            if support is None:
                                raise TectonicsError('component contact has no issued source support')
                            source = support.record()
                            voxel = V.CartesianCell.from_record(source['voxel'], budget=budget)
                            subface = W._face(voxel, contact['axis'], contact['end'])
                            component_queries = _contact_queries(face, subface)
                            try:
                                measure = G.enclose_component_wall(support, contact['logical_cell_id'],
                                    contact['axis'], contact['end'], endpoint=component_endpoint,
                                    moment_polynomials=component_queries, max_moment_widths=(width,)*len(component_queries),
                                    max_width_m3=volume_width, max_leaves=max_leaves, budget=budget,
                                    moments_only=static)
                            except Exception as error:
                                # Preserve the exact failed query even when resource
                                # admission stops before a geometric receipt exists.
                                # This is diagnostic evidence, never an issued measure.
                                requests, tb = [], error.__traceback__
                                while tb is not None:
                                    frame = tb.tb_frame
                                    if frame.f_code.co_name == '_admit_budgets':
                                        requests.append(dict(requested_bytes=frame.f_locals.get('count'),
                                                             category=frame.f_locals.get('category')))
                                    tb = tb.tb_next
                                error.component_moment_failure = dict(support=source, measure=None,
                                    exception_type=type(error).__name__, requested_reservations=requests,
                                    budget_after_unwind=budget.statistics(),
                                    query=dict(logical_cell_id=contact['logical_cell_id'], axis=contact['axis'],
                                        end=contact['end'], endpoint=component_endpoint,
                                        moment_polynomials=[[[i, j, V._encoded(q)] for i, j, q in terms]
                                                            for terms in component_queries],
                                        max_moment_widths=[V._encoded(width)]*len(component_queries),
                                        max_width_m3=V._encoded(volume_width), max_leaves=max_leaves,
                                        moments_only=static))
                                raise
                            self._retained.enter_context(budget.reserve(8192+12*len(measure._json),
                                category='differential-component-trace-record'))
                            record = measure.record()
                            if not record['met']:
                                error = TectonicsError('physical component moments exceed the caller-declared widths')
                                error.component_moment_failure = dict(support=source, measure=record,
                                    query=dict(logical_cell_id=contact['logical_cell_id'], axis=contact['axis'],
                                        end=contact['end'], endpoint=component_endpoint,
                                        moment_polynomials=[[[i, j, V._encoded(q)] for i, j, q in terms]
                                                            for terms in component_queries],
                                        max_moment_widths=[V._encoded(width)]*len(component_queries),
                                        max_width_m3=V._encoded(volume_width), max_leaves=max_leaves,
                                        moments_only=static))
                                actual = [W._decode(pair[1])-W._decode(pair[0]) for pair in record['moment_bounds']]
                                summaries = []
                                for value in actual:
                                    try:
                                        approximate = float(value)
                                    except OverflowError:
                                        approximate = None
                                    summaries.append(dict(
                                        approximate=approximate if approximate is not None and math.isfinite(approximate) else None,
                                        status='finite' if approximate is not None and math.isfinite(approximate) else 'outside-binary64-range',
                                        numerator_bits=value.numerator.bit_length(), denominator_bits=value.denominator.bit_length()))
                                error.add_note('COMPONENT_MOMENT_FAILURE '+json.dumps(dict(
                                    support_id=contact['support_id'], logical_cell_id=contact['logical_cell_id'],
                                    axis=contact['axis'], end=contact['end'], requested_width=V._encoded(width),
                                    achieved_width_summaries=summaries, max_leaves=max_leaves,
                                    leaves=record.get('leaves', record.get('work'))),
                                    sort_keys=True, separators=(',', ':')))
                                raise error
                            moments = {key: tuple(map(W._decode, values))
                                       for key, values in zip(POWERS, record['moment_bounds'])}
                            if source['plate_id'] not in plate_ids:
                                if moments[(0, 0)][1] != 0:
                                    raise TectonicsError('an unselected plate owns prescribed component contact')
                                continue
                            owner = plate_ids.index(source['plate_id'])
                            row_bounds = {index[3*node+axis]: _enclosed(_scale(SHAPE[a], 2*end-1), moments)
                                          for a, node in enumerate(nodes)}
                            midpoint = {i: (lo+hi)/2 for i, (lo, hi) in row_bounds.items() if lo+hi}
                            targets = [(Q(0), Q(0))]*6
                            for k in range(3):
                                targets[3*owner+k] = _enclosed(_scale(modes[k][axis], 2*end-1), moments)
                            normal = np.zeros(nd)
                            for i, q in midpoint.items():
                                normal[i] = float(q)
                            constraints.append(normal)
                            flux_lo.append(np.asarray([float(lo) for lo, _ in targets]))
                            flux_hi.append(np.asarray([float(hi) for _, hi in targets]))
                            exact_constraints.append(midpoint); constraint_bounds.append(row_bounds)
                            exact_flux.append(tuple(targets)); receipts.append(record)
                            retain(tuple(q for pair in (*row_bounds.values(), *targets) for q in pair), len(row_bounds)+6)
                            face_records.append(dict(side=side, native_cell_index=list(map(int, ijk)),
                                physical_cell_id=cell.cell_id, support_id=support.support_id,
                                logical_cell_id=contact['logical_cell_id'], source_key=source['source_key']))
            for (i, j), value in exact_mass.items():
                mass[i, j] = float(value)
            for (i, j), (lo, hi) in exact_load.items():
                load_lo[i, j], load_hi[i, j] = float(lo), float(hi)
            for (i, j), (lo, hi) in exact_energy.items():
                energy_lo[i, j], energy_hi[i, j] = float(lo), float(hi)
            c = np.asarray(constraints); flux = (np.asarray(flux_lo)+np.asarray(flux_hi))/2
            enclosed, resolution = [], Q(0)
            if partition is not None:
                if endpoint is None:
                    # The declared stream width over the largest rigid speed
                    # of this interval's candidate rates: a selection
                    # threshold of the numerical rows, also where a predictor
                    # trace is solved with other rates. The final actual-rate
                    # audit of every row is what certifies the streams.
                    resolution = _coefficient_resolution(volume_width, layer.radius_m, [
                        tuple(map(W._decode, rate)) for rate in data['plate_angular_velocity_rad_s'].values()])
                selected, equations = _independent_constraints(exact_constraints, exact_flux, budget,
                    retained_basis=_construction_scratch, enclosed=enclosed, resolution=resolution,
                    radii=[{i: (hi-lo)/2 for i, (lo, hi) in bounds.items() if hi != lo} for bounds in constraint_bounds])
                reduced = np.zeros((len(equations), nd))
                right = np.zeros((len(equations), 6))
                for j, (row, targets) in enumerate(equations):
                    for i, q in row.items():
                        reduced[j, i] = float(q)
                    right[j] = [float((a+b)/2) for a, b in targets]
            else:
                selected = list(range(len(c)))
                reduced, right = c[selected], flux[selected]
            block = np.block([[mass, reduced.T], [reduced, np.zeros((len(reduced), len(reduced)))]])
            rhs = np.vstack(((load_lo+load_hi)/2, right))
            try:
                projected = _linear_solve(block, rhs)[:nd]
            except TectonicsError as exc:
                magnitudes = np.max(np.abs(reduced), axis=1)
                exc.add_note('physical trace KKT: '+repr(dict(boundary_dofs=nd,
                    physical_rows=len(c), exact_independent_rows=len(selected),
                    constraint_max_abs_range=(float(np.min(magnitudes)), float(np.max(magnitudes))),
                    constraint_condition=float(np.linalg.cond(reduced)),
                    block_condition=float(np.linalg.cond(block)))))
                raise
            full = np.zeros((6, nv, 3)); full.reshape(6, -1)[:, fixed] = projected.T
            self._full, self._mass, self._constraints = frozen(full), frozen(mass), frozen(c)
            self._projected, self._flux = frozen(projected), frozen(flux)
            self._exact_mass, self._exact_load, self._exact_energy = exact_mass, exact_load, exact_energy
            retain(tuple(exact_mass.values())+tuple(q for table in (exact_load, exact_energy)
                for pair in table.values() for q in pair), len(exact_mass)+len(exact_load)+len(exact_energy))
            self._exact_constraints, self._exact_flux = exact_constraints, exact_flux
            self._constraint_bounds = constraint_bounds
            self._lower_eigenvalue = min(incident)/900
            if self._lower_eigenvalue <= 0:
                raise TectonicsError('a prescribed degree of freedom has no physical face mass')
            self._duration = duration
            self._definition = dict(schema=SCHEMA,
                **({'current_geometry_id': interval.geometry_id} if static else {'interval_id': interval.interval_id}),
                native_plan_id=native.plan_id, material_source=plan['material_source'], volume_map_id=volume_map.volume_map_id,
                network_id=network.network_id, sphere_frame=network.sphere.descriptor(),
                geometry={k: plan[k] for k in D.GEOMETRY_KEYS}, plate_ids=list(plate_ids), endpoint=endpoint,
                open_side=open_side, duration_weight=V._encoded(duration), physical_moment_receipts=receipts,
                boundary_cell_faces=face_records, modes_sha256=_digest_array(full),
                method='constrained physical Q2 L2 projection; per-boundary-cell normal moments',
                algebra_policy='retained D1 general solve: normwise1e-11, condition1e12; exact error/flux accounted separately',
                units='spatial m2/m3/m4' if endpoint is not None else 'time-integrated m2s/m3s/m4s',
                time_rule='endpoint force lift' if endpoint is not None else 'prescribed prior rate; explicit first-order interval geometry',
                scope='FE trace discretisation, not numerical FV flux repair or a basal reservoir law')
            if partition is not None:
                self._definition['component_partition'] = dict(partition_id=component_partition.partition_id,
                    funding_id=partition['funding_id'], grid_id=partition['grid_id'],
                    source=partition['source'], independent_constraint_rows=selected,
                    actual_constraint_count=len(exact_constraints),
                    rule='all actual component-mask rows retained; exact dependent equations only removed from numerical KKT',
                    numerical_equations='exact maximum-magnitude column pivots; exact reduced-row basis; positive row max-norm scaling before binary64 conversion',
                    scope='trace predictor; actual final-rate directed streams and GCL remain required')
                self._definition['component_partition'].update(_unresolved_record(enclosed, resolution, budget))
                if static and partition['scope'] == 'physical-interval':
                    self._definition['component_partition']['evaluation_endpoint'] = 'end'
                    self._definition['component_partition']['accepted_current_geometry_id'] = interval.geometry_id
            if interval_predictor:
                self._definition['interval_predictor'] = dict(force_geometry_id=force_geometry.geometry_id,
                    force_network_id=current_force['network_id'], force_time_s=current_force['time_s'],
                    candidate_interval_id=interval.interval_id,
                    candidate_plate_angular_velocity_rad_s=data['plate_angular_velocity_rad_s'],
                    rule='frozen time-integrated masks; same-parent mechanics only; final actual-rate geometry audit required',
                    time_rule='explicit first-order accepted-start pressure and state; provisional interval trace operator')
            self.trace_id = hashlib.sha256(json.dumps(self._definition, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        except BaseException:
            self.close()
            raise

    def descriptor(self):
        if self._guard is None:
            raise TectonicsError('differential trace is closed')
        self._native.descriptor()
        return dict(trace_id=self.trace_id, **json.loads(json.dumps(self._definition)))

    def modes(self):
        self.descriptor()
        return self._full

    def velocity(self, angular_rates_rad_s):
        self.descriptor()
        rates = np.asarray(angular_rates_rad_s, dtype=float)
        if rates.shape != (2, 3) or not np.isfinite(rates).all():
            raise TectonicsError('actual two-plate angular-rate vectors required')
        if self._endpoint is None and not self._interval_predictor:
            expected = self._interval.record()['plate_angular_velocity_rad_s']
            if any(tuple(Q(float(v)) for v in row) != tuple(map(W._decode, expected[p]))
                   for p, row in zip(self._plate_ids, rates)):
                raise TectonicsError('interval trace cannot replace the rates that actually advanced its physical geometry')
        return frozen(np.einsum('a,aij->ij', rates.ravel(), self._full))

    def error_and_work(self, rates, reaction, *, max_l2_error_squared, max_work_error,
                       actual_velocity_m_s=None):
        """Bound the actual FE trace error and dual FE-reaction work error.

        The reaction norm is the L2 Riesz representative of the *discrete*
        nodal reaction. It is not a bound on an uncomputed continuum traction.
        Squared error has units m4/s2 (endpoint) or m4/s (interval); work is W
        or J respectively. All physical moment intervals remain exact here.
        """
        self.descriptor()
        values = tuple(self._exact_mass.values())+tuple(q for table in (self._exact_load, self._exact_energy)
            for pair in table.values() for q in pair)
        # The exact residual/energy sums need new numerators and denominators;
        # admission includes the binary64 inputs before their conversion.
        amount = 65536+512*len(values)+16*(sum(V._bits(v) for v in values)+2150*(2*len(self._fixed)+6))
        with self._budget.reserve(amount, category='differential-trace-error-work'):
            return self._error_and_work(rates, reaction, max_l2_error_squared, max_work_error,
                                       actual_velocity_m_s)

    def _error_and_work(self, rates, reaction, max_l2_error_squared, max_work_error, actual_velocity_m_s=None):
        # Validate actual rates even when an issued native velocity is supplied.
        # Final interval audits must use that actual solved field, not replace
        # it with this rebuilt projector's different numerical minimiser.
        projected_velocity = self.velocity(rates)
        field = projected_velocity if actual_velocity_m_s is None else D._array(
            actual_velocity_m_s, projected_velocity.shape, 'actual native boundary velocity')
        velocity = field.ravel()[self._fixed]
        omega = tuple(Q(float(v)) for v in np.asarray(rates).ravel())
        d = tuple(Q(float(v)) for v in velocity)
        lo = hi = sum((value*d[i]*d[j] for (i, j), value in self._exact_mass.items()), Q(0))
        for values, coefficients in ((self._exact_load, lambda i, j: -2*d[i]*omega[j]),
                                     (self._exact_energy, lambda i, j: omega[i]*omega[j])):
            for (i, j), (a, b) in values.items():
                coefficient = coefficients(i, j)
                lo += coefficient*(a if coefficient >= 0 else b)
                hi += coefficient*(b if coefficient >= 0 else a)
        if hi < 0:
            raise TectonicsError('negative upper bound of an actual squared trace error')
        r = D._array(reaction, self._full.shape[1:], 'actual native reaction').ravel()[self._fixed]
        dual = _linear_solve(self._mass, r)
        norm2 = _dual_bound(self._exact_mass, r, dual, self._lower_eigenvalue)*self._duration**2
        work2 = hi*norm2
        limit, work_limit = W._q(max_l2_error_squared), W._q(max_work_error)
        if min(limit, work_limit) < 0 or hi > limit or work2 > work_limit**2:
            raise TectonicsError('actual differential FE trace/work error exceeds caller-declared bounds')
        torque, contraction_error = D._fsum_contract(self._full, np.asarray(reaction))
        flux = []
        for normal, intervals, targets in zip(self._exact_constraints, self._constraint_bounds, self._exact_flux):
            actual = sum((v*d[i] for i, v in normal.items()), Q(0))
            represented = _enclosed({(i, 0): d[i] for i in intervals},
                                   {(i, 0): pair for i, pair in intervals.items()})
            bounds = _enclosed({(i, 0): q for i, q in enumerate(omega)},
                               {(i, 0): pair for i, pair in enumerate(targets)})
            flux.append(dict(represented=V._encoded(actual), physical_bounds=list(map(V._encoded, bounds)),
                outside_enclosure=V._encoded(max(Q(0), bounds[0]-actual, actual-bounds[1]))))
            if intervals != {i: (q, q) for i, q in normal.items()}:
                flux[-1]['represented_bounds'] = list(map(V._encoded, represented))
                flux[-1]['outside_enclosure'] = V._encoded(max(Q(0), bounds[0]-represented[1], represented[0]-bounds[1]))
        result = dict(trace_id=self.trace_id, l2_error_squared_bounds=[V._encoded(max(Q(0), lo)), V._encoded(hi)],
            discrete_traction_l2_squared_upper=V._encoded(norm2), work_error_squared_upper=V._encoded(work2),
            boundary_cell_normal_integrals=flux,
            projected_plate_torque_n_m=torque.reshape(2, 3).tolist(),
            torque_contraction_roundoff_n_m=contraction_error.reshape(2, 3).tolist(),
            scope='discrete FE trace/reaction work; not continuum traction-error certification')
        if actual_velocity_m_s is not None:
            result['actual_velocity_sha256'] = _digest_array(field)
            result['evaluation'] = 'actual solved native field on final physical masks; no velocity replacement'
        return result

    def close(self):
        self._retained.close()
        if self._guard is not None:
            self._guard.__exit__(None, None, None)
            self._guard = None

    def __enter__(self):
        self.descriptor()
        return self

    def __exit__(self, *_):
        self.close()


class DifferentialPlateBoundaryLift(D.PlateBoundaryLift):
    """Typed work-adjoint lift from the issued current physical trace.

    Unlike the legacy nodal-owner lift, this declares its FE interface error.
    All six angular rates remain available with the natural basal boundary;
    a smaller rate subspace must be an explicit physical constraint.
    """
    def __init__(self, network, native, volume_map, trace, boundary_id, *,
                 angular_rate_basis, map_source, constraint_source,
                 max_l2_error_squared, max_work_error, budget):
        self._guard = None
        if (type(trace) is not PreparedDifferentialTrace or trace._budget is not budget or
                trace._native is not native or type(network) is not S.SphereNetwork or
                type(volume_map) is not RegionalVolumeMap):
            raise TectonicsError('issued current differential trace and its actual source/native geometry required')
        record = trace.descriptor(); plan = native.descriptor()
        if (record['network_id'] != network.network_id or
                (trace._endpoint is None and not trace._interval_predictor) or
                record['volume_map_id'] != volume_map.volume_map_id):
            raise TectonicsError('force lift requires current geometry or an explicit accepted-start interval predictor')
        boundary = next((b for b in network.boundaries if b.boundary_id == boundary_id), None)
        if boundary is None or trace._plate_ids != (boundary.left_plate_id, boundary.right_plate_id):
            raise TectonicsError('trace owner order differs from the actual replaced boundary')
        limits = W._q(max_l2_error_squared), W._q(max_work_error)
        if min(limits) < 0:
            raise TectonicsError('nonnegative independently declared FE error/work bounds required')
        basis = np.asarray(angular_rate_basis, dtype=float)
        if basis.ndim != 2 or basis.shape[0] != 6 or not 1 <= basis.shape[1] <= 6 or not np.isfinite(basis).all():
            raise TectonicsError('explicit finite six-by-k angular-rate basis required')
        D.D.solve_torque(basis.T@basis, np.zeros(basis.shape[1]))
        if basis.shape[1] < 6:
            D._name(constraint_source)
        elif constraint_source is not None:
            raise TectonicsError('six independent rates have no kinematic constraint source')
        D._name(map_source)
        nv = trace._full.shape[1]
        self._guard = budget.reserve(65536+4096*nv+16*len(volume_map._record),
                                     category='differential-plate-lift')
        self._guard.__enter__()
        try:
            physical = volume_map.native_binding(native)
            mapped = volume_map.record()
            embedding = mapped['embedding']
            orientation = np.asarray([[float(Q(*map(int, v))) for v in row] for row in embedding['basis']])
            origin = np.asarray([float(Q(*map(int, v))) for v in embedding['origin_global_m']])
            points = origin+native.coordinates('velocity')@orientation.T
            if _digest_array(points) != physical['physical_points_sha256']:
                raise TectonicsError('differential lift does not reproduce the actual physical node coordinates')
            self._budget, self._trace = budget, trace
            self._trace_limits = limits
            self.plate_ids = trace._plate_ids
            self._full, self._basis = trace._full, frozen(basis)
            self._modes = frozen(np.einsum('ak,aij->kij', basis, self._full))
            self._mask = native.velocity_mask()
            self._points = frozen(points)
            self._geometry = {k: plan[k] for k in D.GEOMETRY_KEYS}
            self._material_source = plan['material_source']
            self._pressure_reference = plan.get('pressure_reference')
            self._current_pose = None
            described = dict(schema='atlas.differential-plate-boundary-lift.v1',
                network_id=network.network_id, sphere_frame=network.sphere.descriptor(),
                boundary_id=boundary_id, plate_ids=list(self.plate_ids), geometry=self._geometry,
                physical_volume_binding=physical, trace=record, angular_rate_basis=basis.tolist(),
                physical_points_sha256=_digest_array(points), modes_sha256=_digest_array(self._modes),
                map_source=map_source, constraint_source=constraint_source,
                max_l2_error_squared=V._encoded(limits[0]), max_work_error=V._encoded(limits[1]),
                pressure_reference=self._pressure_reference,
                rule='issued physical owned-face Q2 projection; force transfer is its algebraic adjoint',
                scope='same-time open-base mechanics; actual basal inventory and interval transport remain separately owned')
            self._definition = D._json(described)
            self.lift_id = hashlib.sha256(self._definition).hexdigest()
        except BaseException:
            self.close()
            raise

    def descriptor(self):
        self._trace.descriptor()
        return super().descriptor()

    def trace_account(self, rates, reaction):
        return self._trace.error_and_work(rates, reaction,
            max_l2_error_squared=self._trace_limits[0], max_work_error=self._trace_limits[1])


def audit_interval_solution(trace, native_faces, force_exchange, *,
                            max_l2_error_squared, max_work_error, budget):
    """Audit a same-parent solution on its actual FINAL-rate interval masks.

    The final field is immutable issued native evidence, not the minimiser of
    the newly rebuilt trace. This test may succeed without bitwise equality of
    successive predictors. Publication additionally requires the independent
    physical directed-stream/GCL closure bound to the same native measure and
    final interval. No tolerance on angular rates or material volume is added.
    """
    from .integration_native_faces import NativeFaceMeasures
    from .regional_execution3d import RegionalMechanicalSnapshot
    if (type(trace) is not PreparedDifferentialTrace or trace._budget is not budget or
            trace._endpoint is not None or type(trace._interval) is not G.DifferentialInterval or
            type(native_faces) is not NativeFaceMeasures or native_faces._resource is not budget or
            type(force_exchange) is not RegionalMechanicalSnapshot or type(budget) is not WorkBudget):
        raise TectonicsError('actual final interval trace, native face evidence and force exchange required')
    descriptor, native, force = trace.descriptor(), native_faces.record(), force_exchange.descriptor()
    if 'component_partition' not in descriptor:
        raise TectonicsError('final interval trace needs the complete physical component partition')
    stage = native_faces._stage
    native_faces.validate_source(native_faces._collar, stage)
    mechanics = stage.source_stage.initial_mechanics
    interval = trace._interval.record()
    driving = force.get('driving', {})
    source_trace = driving.get('lift', {}).get('trace', {})
    if (force.get('schema') != D.SCHEMA+'.result' or force.get('native_result_id') != mechanics.result_id or
            native['mechanical_result_id'] != mechanics.result_id or
            native['volume_map_id'] != descriptor['volume_map_id'] or
            native['start_time_s'] != interval['start_time_s'] or native['end_time_s'] != interval['end_time_s'] or
            Q(force.get('time_s', -1)) != W._decode(interval['start_time_s']) or
            driving.get('network_id') != interval['parent_network_id'] or
            driving.get('material_source') != descriptor['material_source'] or
            source_trace.get('geometry') != descriptor['geometry'] or
            source_trace.get('open_side') != descriptor['open_side'] or
            force.get('algebra_relative_residual', float('inf')) > D.ALGEBRA or
            force.get('virtual_work_relative_residual', float('inf')) > D.WORK):
        raise TectonicsError('final trace and force do not share the actual native proposal, geometry or accepted clock')
    plates = driving['plate_ids']
    omega = D._array(force_exchange.array('omega_rad_s'), (len(plates), 3), 'actual solved plate rates')
    expected = interval['plate_angular_velocity_rad_s']
    if set(plates) != set(expected) or any(tuple(Q(float(q)) for q in values) !=
            tuple(map(W._decode, expected[p])) for p, values in zip(plates, omega)):
        raise TectonicsError('final physical interval does not use every actual solved plate rate')
    pair = omega[[plates.index(p) for p in trace._plate_ids]]
    with budget.reserve(65536+8*(len(trace._definition.get('physical_moment_receipts', ()))+
                               mechanics.nbytes), category='differential-final-trace-audit'):
        account = trace.error_and_work(pair, mechanics.array('velocity_constraint_reaction_n'),
            max_l2_error_squared=max_l2_error_squared, max_work_error=max_work_error,
            actual_velocity_m_s=mechanics.array('velocity_m_s'))
        record = dict(schema='atlas.differential-final-trace-audit.v1',
            interval_id=trace._interval.interval_id,
            partition_id=descriptor['component_partition']['partition_id'], trace_id=trace.trace_id,
            native_measure_id=native_faces.measure_id, source_flow_stage_id=stage.result_id,
            native_result_id=mechanics.result_id, force_exchange_id=force_exchange.result_id,
            parent_state_id=native['parent_state_id'], start_time_s=interval['start_time_s'],
            end_time_s=interval['end_time_s'], material_source=descriptor['material_source'],
            angular_velocity_rad_s=expected, trace_account=account,
            max_l2_error_squared=V._encoded(W._q(max_l2_error_squared)),
            max_work_error=V._encoded(W._q(max_work_error)),
            force_algebra_relative_residual=force['algebra_relative_residual'],
            force_virtual_work_relative_residual=force['virtual_work_relative_residual'],
            velocity_replaced=False, source_heat_reapplied=False,
            scope='final actual-rate FE trace/work only; matching exact directed material/GCL closure still mandatory')
        encoded = D._json(record)
        guard = budget.reserve(8192+4*len(encoded), category='differential-final-trace-retained')
        guard.__enter__()
        try:
            result = object.__new__(IntervalTraceAudit)
            object.__setattr__(result, '_json', encoded)
            object.__setattr__(result, '_resource', budget)
            weakref.finalize(result, guard.__exit__, None, None, None)
            return result
        except BaseException:
            guard.__exit__(None, None, None)
            raise
