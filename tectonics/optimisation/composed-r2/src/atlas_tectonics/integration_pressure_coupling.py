"""Owned radial-wall pressure integrals and exact discrete reference partition.

The hydrostatic pressure here is a declared force reference, never solved mean
stress. Curved radial factors are enclosed, not replaced by layer/face means.
SPDX-License-Identifier: AGPL-3.0-only
"""
from contextlib import ExitStack
from contextvars import ContextVar
from dataclasses import dataclass
from fractions import Fraction as Q
import heapq
import json
import math
import weakref

import numpy as np

from ._validation import TectonicsError
from . import integration_volume as V
from . import integration_volume_overlap as O
from . import integration_patch_heat as PH
from .regional_execution import RegionalMechanicalSnapshot
from .stokes_execution import _factored_scale


class PressureCouplingRefused(TectonicsError):
    pass


_JET_PRECISION = ContextVar('radial_pressure_interval_precision', default=128)


def _dyadic_outward(pair, denominator):
    lo, hi = pair
    if type(lo) in (int, Q) and type(hi) in (int, Q):
        # Scaling exact numerators avoids constructing and reducing temporary
        # Fractions merely to discard their fractional part. Python's integer
        # division is floor division, including for negative endpoints.
        floor = lo.numerator*denominator // lo.denominator
        ceiling = -((-hi.numerator*denominator) // hi.denominator)
        return Q(floor, denominator), Q(ceiling, denominator)
    return (Q((lo*denominator).__floor__(), denominator),
            Q((hi*denominator).__ceil__(), denominator))


def _jet_outward(jet):
    """Bound derivative arithmetic, never physical coefficients or stocks.

    Repeated reciprocal/square-root derivatives otherwise collect unrelated
    large denominators. Outward dyadic rounding at the current request-derived
    precision is part of the enclosure; the unchanged width test must still
    accept the resulting bounds. Context-local state keeps concurrent requests
    independent and is reset even on refusal.
    """
    denominator = 1 << _JET_PRECISION.get()
    return tuple(_dyadic_outward(pair, denominator) for pair in jet)


def _add(a, b):
    return a[0]+b[0], a[1]+b[1]


def _mul(a, b):
    # Ordered exact rational intervals need only their extremal products.
    # Keep the original iterable behaviour for reversed/mixed/non-rational
    # inputs, including its empty-iterable errors and tie result types.
    if (type(a) is tuple and type(b) is tuple and len(a) == len(b) == 2
            and type(a[0]) is Q and type(a[1]) is Q
            and type(b[0]) is Q and type(b[1]) is Q
            and a[0] <= a[1] and b[0] <= b[1]):
        lo, hi = a
        low, high = b
        if lo >= 0:
            if low >= 0:
                return lo*low, hi*high
            if high <= 0:
                return hi*low, lo*high
            return hi*low, hi*high
        if hi <= 0:
            if low >= 0:
                return lo*high, hi*low
            if high <= 0:
                return hi*high, lo*low
            return lo*high, lo*low
        if low >= 0:
            return lo*high, hi*high
        if high <= 0:
            return hi*low, lo*low
        return min(lo*high, hi*low), max(lo*low, hi*high)
    values = tuple(x*y for x in a for y in b)
    return min(values), max(values)


def _scale(a, q):
    values = tuple(x*q for x in a)
    return min(values), max(values)


def _divide(q, interval):
    if interval[0] <= 0 <= interval[1]:
        raise PressureCouplingRefused('interval division crosses zero')
    values = q/interval[0], q/interval[1]
    return min(values), max(values)


def _sqrt(q, bits=72):
    """Outward rational square-root bounds, with no floating predicate."""
    if q < 0:
        raise PressureCouplingRefused('negative squared radius')
    # Relative dyadic resolution; its explicit enclosure remains in the result.
    exponent = (q.numerator.bit_length()-q.denominator.bit_length())//2 if q else 0
    denominator = 1 << max(0, bits-exponent)
    n = math.isqrt(q.numerator*denominator**2//q.denominator)
    lo = Q(n, denominator)
    return lo, lo if lo*lo == q else Q(n+1, denominator)


def _cross2(a, b):
    return a[0]*b[1]-a[1]*b[0]


def _minus(a, b):
    return tuple(x-y for x, y in zip(a, b))


def _hull(points):
    values = sorted(set(points))
    if len(values) < 3:
        return ()
    def half(seq):
        out = []
        for p in seq:
            while len(out) > 1 and _cross2(_minus(out[-1], out[-2]), _minus(p, out[-1])) <= 0:
                out.pop()
            out.append(p)
        return out
    return tuple(half(values)[:-1]+half(values[::-1])[:-1])


def _clip2(poly, normal, limit):
    if not poly:
        return ()
    result = []
    for a, b in zip(poly, poly[1:]+poly[:1]):
        da, db = O._dot(normal, a)-limit, O._dot(normal, b)-limit
        if da <= 0:
            result.append(a)
        if (da < 0 < db) or (db < 0 < da):
            t = da/(da-db)
            result.append(tuple(x+t*(y-x) for x, y in zip(a, b)))
    return _hull(result)


def wall_polygon(cell, first, second):
    """Exact box intersection with the minor radial wall x=u*a+v*b, u,v>=0.

    Returns uv vertices and the side occupied at a coincident box face. Side0
    is the trace's left (positive a cross b), side1 right; None spans both.
    No corner-only radial or material containment is inferred here.
    """
    a, b = tuple(map(Q, first)), tuple(map(Q, second))
    normal = O._cross(a, b)
    if not any(normal):
        raise PressureCouplingRefused('noncollinear radial-wall rays required')
    omitted = max(range(3), key=lambda j: abs(normal[j]))
    i, j = (k for k in range(3) if k != omitted)
    determinant = a[i]*b[j]-a[j]*b[i]
    def uv(p):
        return ((p[i]*b[j]-p[j]*b[i])/determinant,
                (a[i]*p[j]-a[j]*p[i])/determinant)
    vertices = cell.vertices_m
    signed = [O._dot(normal, p) for p in vertices]
    if min(signed) > 0 or max(signed) < 0:
        return (), None
    # Every exact box edge joins vertices differing along exactly one local axis.
    local = [tuple(O._dot(tuple(cell.basis[k][axis] for k in range(3)),
                          _minus(p, cell.origin_m)) for axis in range(3)) for p in vertices]
    points = [p for p, d in zip(vertices, signed) if d == 0]
    for k, p in enumerate(vertices):
        for l in range(k):
            if sum(x != y for x, y in zip(local[k], local[l])) != 1 or signed[k]*signed[l] >= 0:
                continue
            t = signed[k]/(signed[k]-signed[l])
            points.append(tuple(x+t*(y-x) for x, y in zip(p, vertices[l])))
    poly = _clip2(_clip2(_hull(tuple(uv(p) for p in points)), (-1, 0), 0), (0, -1), 0)
    side = 0 if min(signed) == 0 else (1 if max(signed) == 0 else None)
    return poly, side


def _triangle(triangle, a, b, bits):
    points = tuple(tuple(u*x+v*y for x, y in zip(a, b)) for u, v in triangle)
    radii = [O._dot(p, p) for p in points]
    minimum = min(radii)
    for x, y in zip(points, points[1:]+points[:1]):
        d = _minus(y, x); denominator = O._dot(d, d)
        t = max(Q(0), min(Q(1), -O._dot(x, d)/denominator)) if denominator else Q(0)
        minimum = min(minimum, O._dot(tuple(v+t*w for v, w in zip(x, d)),
                                    tuple(v+t*w for v, w in zip(x, d))))
    turns = [_cross2(_minus(y, x), tuple(-v for v in x))
             for x, y in zip(triangle, triangle[1:]+triangle[:1])]
    if all(v >= 0 for v in turns) or all(v <= 0 for v in turns):
        minimum = Q(0)
    radial = _sqrt(minimum, bits)[0], _sqrt(max(radii), bits)[1]
    normal = O._cross(a, b)
    moment = [O._cross(normal, p) for p in points]
    ranges = tuple((min(p[k] for p in moment), max(p[k] for p in moment)) for k in range(3))
    area = abs(_cross2(_minus(triangle[1], triangle[0]), _minus(triangle[2], triangle[0])))/2
    return points, radial, ranges, area


def _integrate(poly, a, b, evaluator, *, width, max_leaves, budget):
    """Certified signed three-component surface integral; no success on exhaustion."""
    if not poly:
        return ((Q(0), Q(0)),)*3, 0
    if len(poly)-2 > max_leaves:
        raise PressureCouplingRefused('pressure integration initial polygon exceeds leaf budget')
    heap, totals, serial = [], [[Q(0), Q(0)] for _ in range(3)], 0
    precision = max(80, 8+width.denominator.bit_length()-abs(width.numerator).bit_length()+2*max_leaves.bit_length())
    denominator = 1 << precision
    def outward(pair):
        # Certified enclosures, NOT stocks: outward dyadic rounding prevents
        # unrelated reciprocal-radius denominators accumulating in leaf sums.
        lo = (pair[0]*denominator).__floor__()
        hi = (pair[1]*denominator).__ceil__()
        return Q(lo, denominator), Q(hi, denominator)
    with ExitStack() as stack:
        def add(triangle, depth):
            nonlocal serial
            with V._work((*a, *b, *(x for p in triangle for x in p)), budget):
                points, radial, moment, area = _triangle(triangle, a, b, 72+depth)
                bound = evaluator(points, radial, moment)
                bound = tuple(outward(_scale(v, area)) for v in bound)
            values = (*a, *b, *(x for p in triangle for x in p), *(x for v in bound for x in v))
            size = 4096+16*sum((V._bits(v)+7)//8 for v in values)
            lease = budget.reserve(size, category='owned-pressure-leaf'); lease.__enter__()
            stack.callback(lease.__exit__, None, None, None)
            for total, pair in zip(totals, bound):
                total[0] += pair[0]; total[1] += pair[1]
            score = max(v[1]-v[0] for v in bound)
            heapq.heappush(heap, (-score, serial, triangle, depth, bound)); serial += 1
        for i in range(1, len(poly)-1):
            add((poly[0], poly[i], poly[i+1]), 0)
        while max(v[1]-v[0] for v in totals) > width:
            if len(heap)+1 > max_leaves:
                error = PressureCouplingRefused('owned wall pressure enclosure exceeds declared torque width/leaf budget')
                error.add_note('PRESSURE_ENCLOSURE_FAILURE '+json.dumps(dict(
                    requested_width=V._encoded(width), max_leaves=max_leaves, leaves=len(heap),
                    achieved_bounds=[[V._encoded(q) for q in pair] for pair in totals],
                    wall_rays=[[V._encoded(q) for q in ray] for ray in (a, b)],
                    polygon=[[V._encoded(q) for q in point] for point in poly]),
                    sort_keys=True, separators=(',', ':')))
                raise error
            _, _, triangle, depth, bound = heapq.heappop(heap)
            for total, pair in zip(totals, bound):
                total[0] -= pair[0]; total[1] -= pair[1]
            # Bisect longest physical edge, retaining every positive-area part.
            def length(i):
                d = _minus(triangle[(i+1)%3], triangle[i])
                v = tuple(d[0]*x+d[1]*y for x, y in zip(a, b))
                return O._dot(v, v)
            i = max(range(3), key=length); j, k = (i+1)%3, (i+2)%3
            midpoint = tuple((x+y)/2 for x, y in zip(triangle[i], triangle[j]))
            add((triangle[i], midpoint, triangle[k]), depth+1)
            add((midpoint, triangle[j], triangle[k]), depth+1)
        return tuple(tuple(v) for v in totals), len(heap)


def _density_range(profile, radial):
    selected = [rho for bottom, top, rho, _ in profile if bottom <= radial[1] and top >= radial[0]]
    if not selected:
        raise PressureCouplingRefused('owned wall outside the pressure profile')
    return min(selected), max(selected)


def _jet_constant(value):
    return (value, value), (Q(0), Q(0)), (Q(0), Q(0))


def _jet_is_constant(a):
    return a[0][0] == a[0][1] and a[1] == (0, 0) and a[2] == (0, 0)


class _RadialJet(tuple):
    """Interval jet with an exact radial expression, local to one calculation.

    Equal interval endpoints alone never establish expression identity. The
    expression stores the full chart norm polynomial and normalised ray edge.
    It is not carried through arbitrary jet arithmetic.
    """
    def __new__(cls, jet, expression):
        result = super().__new__(cls, jet)
        result.expression = expression
        return result


def _same_radial(a, b):
    if _jet_is_constant(a) and _jet_is_constant(b):
        return a[0][0] == b[0][0]
    return (isinstance(a, _RadialJet) and isinstance(b, _RadialJet)
            and a.expression == b.expression)


def _jet_add(a, b):
    if a == _jet_constant(Q(0)):
        return b
    if b == _jet_constant(Q(0)):
        return a
    if _jet_is_constant(a) and _jet_is_constant(b):
        return _jet_constant(a[0][0]+b[0][0])
    return _jet_outward(tuple(_add(x, y) for x, y in zip(a, b)))


def _jet_scale(a, q):
    if q == 0:
        return _jet_constant(Q(0))
    if q == 1:
        return a
    if _jet_is_constant(a):
        return _jet_constant(a[0][0]*q)
    return _jet_outward(tuple(_scale(x, q) for x in a))


def _jet_mul(a, b):
    if _jet_is_constant(a):
        return _jet_scale(b, a[0][0])
    if _jet_is_constant(b):
        return _jet_scale(a, b[0][0])
    return _jet_outward((_mul(a[0], b[0]),
            _add(_mul(a[1], b[0]), _mul(a[0], b[1])),
            _add(_add(_mul(a[2], b[0]), _scale(_mul(a[1], b[1]), 2)), _mul(a[0], b[2]))))


def _jet_reciprocal(a):
    if _jet_is_constant(a) and a[0][0] != 0:
        return _jet_constant(1/a[0][0])
    reciprocal = _divide(Q(1), a[0])
    square = _mul(reciprocal, reciprocal)
    cube = _mul(square, reciprocal)
    return _jet_outward((reciprocal, _scale(_mul(a[1], square), -1),
            _add(_scale(_mul(_mul(a[1], a[1]), cube), 2), _scale(_mul(a[2], square), -1))))


def _angular_wedges(poly):
    """Exact active polygon entry/exit edges between successive vertex rays."""
    values = sorted({v/(u+v) for u, v in poly if u+v > 0})
    planes = []
    for p, q in zip(poly, poly[1:]+poly[:1]):
        normal = q[1]-p[1], p[0]-q[0]
        planes.append((O._dot(normal, p), normal[0], normal[1]-normal[0]))
    result = []
    for left, right in zip(values, values[1:]):
        middle = (left+right)/2
        lower, upper, empty = [(Q(0), None)], [], False
        for c, x, y in planes:
            denominator = x+y*middle
            if denominator > 0:
                upper.append((c/denominator, (c, x, y)))
            elif denominator < 0:
                lower.append((c/denominator, (c, x, y)))
            elif c < 0:
                empty = True
        if empty:
            continue
        if not upper:
            raise PressureCouplingRefused('bounded radial wall polygon has no ray exit')
        low = max(lower, key=lambda pair: pair[0])
        high = min(upper, key=lambda pair: pair[0])
        if high[0] > low[0]:
            result.append((left, right, low[1], high[1]))
    return tuple(result)


def _radial_chart_jets(a, b, normal, left, right, bits):
    """Jets of |(1-t)a+tb| and the exact polar moment/Jacobian factor."""
    direction = _minus(b, a)
    dd = O._dot(direction, direction)
    ad = O._dot(a, direction)
    closest = max(left, min(right, -ad/dd)) if dd else left
    def radius2(t):
        point = tuple(x+t*y for x, y in zip(a, direction))
        return O._dot(point, point)
    square = radius2(closest), max(radius2(left), radius2(right))
    if square[0] <= 0:
        raise PressureCouplingRefused('radial angular chart reaches the origin')
    s = _sqrt(square[0], bits)[0], _sqrt(square[1], bits)[1]
    qprime = tuple(2*(ad+dd*t) for t in (left, right))
    inv_s = _divide(Q(1), s)
    s_jet = _RadialJet((s, _scale(_mul(qprime, inv_s), Q(1, 2)),
             _add(_scale(inv_s, dd),
                  _scale(_mul(_mul(qprime, qprime), _mul(_mul(inv_s, inv_s), inv_s)), Q(-1, 4)))),
             ('sqrt-quadratic', O._dot(a, a), 2*ad, dd))
    inverse = _jet_reciprocal(s_jet)
    factor = _jet_mul(_jet_mul(inverse, inverse), inverse)
    centre_moment, derivative_moment = O._cross(normal, a), O._cross(normal, direction)
    result = []
    for x, y in zip(centre_moment, derivative_moment):
        values = x+y*left, x+y*right
        linear = ((min(values), max(values)), (y, y), (Q(0), Q(0)))
        result.append(_jet_mul(linear, factor))
    return s_jet, tuple(result)


def _radial_interval_jets(s_jet, left, right, entry, exit_, bottom, top):
    def radial_edge(edge):
        if edge is None:
            return _jet_constant(Q(0))
        c, x, y = edge
        if c == 0:
            return _jet_constant(Q(0))
        values = x+y*left, x+y*right
        coefficient = ((min(values), max(values)), (y, y), (Q(0), Q(0)))
        result = _jet_mul(s_jet, _jet_scale(_jet_reciprocal(coefficient), c))
        if isinstance(s_jet, _RadialJet):
            # c/(x+y*t) == 1/(x/c+(y/c)*t), including negative rescaling.
            result = _RadialJet(result, ('radial-edge', s_jet.expression, x/c, y/c))
        return result
    lower_edge, upper_edge = radial_edge(entry), radial_edge(exit_)
    fixed = True
    if lower_edge[0][1] <= bottom:
        lower = _jet_constant(bottom)
    elif lower_edge[0][0] >= bottom:
        lower = lower_edge
    else:
        lower = ((bottom, max(bottom, lower_edge[0][1])), (Q(0), Q(0)), (Q(0), Q(0)))
        fixed = False
    if upper_edge[0][0] >= top:
        upper = _jet_constant(top)
    elif upper_edge[0][1] <= top:
        upper = upper_edge
    else:
        upper = ((min(top, upper_edge[0][0]), top), (Q(0), Q(0)), (Q(0), Q(0)))
        fixed = False
    if _same_radial(lower, upper) or upper[0][1] <= lower[0][0]:
        return lower, upper, True, False
    if upper[0][0] < lower[0][1]:
        fixed = False
    return lower, upper, fixed, True


def _radial_slice(a, b, normal, left, right, entry, exit_, bottom, top, rc, bits):
    """Analytic radial primitive, with explicit shell max/min branches.

    du dv=lambda d(lambda)dt and normal cross x=lambda*(normal cross d).
    Thus the radial primitive is (normal cross d)/|d|^3*[r^4/4-rc^3*r].
    """
    s_jet, factors = _radial_chart_jets(a, b, normal, left, right, bits)
    lower, upper, fixed, possible = _radial_interval_jets(s_jet, left, right, entry, exit_, bottom, top)
    if not possible:
        return (_jet_constant(Q(0)),)*3, True
    def primitive(r):
        square_jet = _jet_mul(r, r)
        return _jet_add(_jet_scale(_jet_mul(square_jet, square_jet), Q(1, 4)), _jet_scale(r, -rc**3))
    if fixed:
        span = _jet_add(primitive(upper), _jet_scale(primitive(lower), -1))
    else:
        # F is increasing for r>=rc. Clamp both actual endpoints there before
        # taking these scalar bounds; no empty radial interval is integrated.
        f = lambda r: r**4/4-rc**3*r
        low = max(Q(0), f(max(rc, upper[0][0]))-f(max(rc, lower[0][1])))
        high = max(Q(0), f(max(rc, upper[0][1]))-f(max(rc, lower[0][0])))
        span = ((low, high), (Q(0), Q(0)), (Q(0), Q(0)))
    return tuple(_jet_mul(factor, span) for factor in factors), fixed


def _integrate_radial_shell(poly, a, b, bottom, top, rc, *, width, max_leaves, budget):
    """Certified radial-first wall integral, with no curved indicator triangles."""
    if not poly or top <= bottom:
        return ((Q(0), Q(0)),)*3, 0
    if not 0 < rc <= bottom < top or any(min(p) < 0 for p in poly):
        raise PressureCouplingRefused('positive physical shell and minor-wall coordinates required')
    normal = O._cross(a, b)
    with V._work((*a, *b, bottom, top, rc, *(q for p in poly for q in p)), budget):
        wedges = _angular_wedges(poly)
    pieces = tuple((left, right, (entry, exit_)) for left, right, entry, exit_ in wedges)
    def evaluate(left, right, edges, bits):
        return _radial_slice(a, b, normal, left, right, *edges, bottom, top, rc, bits)
    def coefficients(edges):
        return (*a, *b, bottom, top, rc, *(q for edge in edges if edge is not None for q in edge))
    return _integrate_angular(pieces, evaluate, coefficients, width=width, max_leaves=max_leaves, budget=budget)


def _integrate_angular(pieces, evaluate, coefficients, *, width, max_leaves, budget):
    """Internal bounded 1-D interval quadrature; callbacks are arithmetic only."""
    if len(pieces) > max_leaves:
        raise PressureCouplingRefused('radial pressure initial angular wedges exceed leaf budget')
    precision = max(96, 16+width.denominator.bit_length()-abs(width.numerator).bit_length()+2*max_leaves.bit_length())
    denominator = 1 << precision
    def outward(pair):
        return _dyadic_outward(pair, denominator)
    heap, totals, serial, leases = [], [[Q(0), Q(0)] for _ in range(3)], 0, {}
    token = _JET_PRECISION.set(precision)
    try:
        def add(left, right, data):
            nonlocal serial
            values = coefficients(data)
            with V._work((left, right, denominator, *values), budget):
                jets, fixed = evaluate(left, right, data, precision)
                whole = tuple(_scale(jet[0], right-left) for jet in jets)
                if fixed:
                    middle = (left+right)/2
                    centre, _ = evaluate(middle, middle, data, precision)
                    tight = []
                    for bound, jet, point in zip(whole, jets, centre):
                        error = max(map(abs, jet[2]))*(right-left)**3/24
                        value = _scale(point[0], right-left)
                        tight.append((max(bound[0], value[0]-error), min(bound[1], value[1]+error)))
                    whole = tuple(tight)
                bounded = tuple(outward(pair) for pair in whole)
                if any(lo > hi for lo, hi in bounded):
                    raise PressureCouplingRefused('radial pressure value and derivative certificates disagree')
            values = (left, right, *values, *(q for pair in bounded for q in pair))
            lease = budget.reserve(4096+16*sum((V._bits(v)+7)//8 for v in values), category='owned-pressure-leaf')
            lease.__enter__(); leases[serial] = lease
            for total, pair in zip(totals, bounded):
                total[0] += pair[0]; total[1] += pair[1]
            heapq.heappush(heap, (-max(hi-lo for lo, hi in bounded), serial, left, right, data, bounded))
            serial += 1
        for piece in pieces:
            add(*piece)
        while max((hi-lo for lo, hi in totals), default=Q(0)) > width:
            if len(heap)+1 > max_leaves:
                error = PressureCouplingRefused('radial-first pressure enclosure exceeds declared torque width/leaf budget')
                error.add_note('PRESSURE_ANGULAR_FAILURE '+json.dumps(dict(
                    requested_width=V._encoded(width), max_leaves=max_leaves, leaves=len(heap),
                    bounds=[[V._encoded(q) for q in pair] for pair in totals]),
                    sort_keys=True, separators=(',', ':')))
                raise error
            _, key, left, right, data, bounded = heapq.heappop(heap)
            for total, pair in zip(totals, bounded):
                total[0] -= pair[0]; total[1] -= pair[1]
            leases.pop(key).__exit__(None, None, None)
            middle = (left+right)/2
            add(left, middle, data); add(middle, right, data)
        return tuple(map(tuple, totals)), len(heap)
    finally:
        for lease in leases.values():
            lease.__exit__(None, None, None)
        _JET_PRECISION.reset(token)


def _jet_power(a, exponent):
    if _jet_is_constant(a):
        return _jet_constant(a[0][0]**exponent)
    result = _jet_constant(Q(1))
    for _ in range(exponent):
        result = _jet_mul(result, a)
    return result


def _jet_extreme(a, b, *, maximum):
    if _same_radial(a, b):
        return a, True
    if (a[0][0] >= b[0][1]) if maximum else (a[0][1] <= b[0][0]):
        return a, True
    if (b[0][0] >= a[0][1]) if maximum else (b[0][1] <= a[0][0]):
        return b, True
    op = max if maximum else min
    return ((op(a[0][0], b[0][0]), op(a[0][1], b[0][1])), (Q(0), Q(0)), (Q(0), Q(0))), False


def _positive_interval_primitive(lower, upper, primitive):
    """Integrate only an ordered radial interval; uncertain order includes0."""
    if _same_radial(lower, upper) or upper[0][1] <= lower[0][0]:
        return _jet_constant(Q(0)), True
    result = _jet_add(primitive(upper), _jet_scale(primitive(lower), -1))
    fixed = upper[0][0] >= lower[0][1]
    if not fixed:
        result = (_mul(result[0], (Q(0), Q(1))), (Q(0), Q(0)), (Q(0), Q(0)))
    return result, fixed


def _donor_radial_pressure(receiver_low, receiver_high, donor_low, donor_high):
    """J=integral r^2*max(0,b-max(a,r)) dr, using true donor endpoints a,b."""
    below_high, first_fixed = _jet_extreme(receiver_high, donor_low, maximum=False)
    below, order_fixed = _positive_interval_primitive(receiver_low, below_high,
        lambda r: _jet_scale(_jet_power(r, 3), Q(1, 3)))
    below = _jet_mul(below, _jet_add(donor_high, _jet_scale(donor_low, -1)))
    middle_low, low_fixed = _jet_extreme(receiver_low, donor_low, maximum=True)
    middle_high, high_fixed = _jet_extreme(receiver_high, donor_high, maximum=False)
    middle, mid_order_fixed = _positive_interval_primitive(middle_low, middle_high,
        lambda r: _jet_add(_jet_scale(_jet_mul(donor_high, _jet_power(r, 3)), Q(1, 3)),
                           _jet_scale(_jet_power(r, 4), Q(-1, 4))))
    return _jet_add(below, middle), all((first_fixed, order_fixed, low_fixed, high_fixed, mid_order_fixed))


def _integrate_radial_pressure(poly, a, b, profiles, donors, rc, outer, gravity, *,
                               width, max_leaves, budget):
    """Exact receiver/donor radial pressure, then certified angular integration.

    donors are actual (polygon,bottom,top,g*density_difference*side_weight).
    Angular events retain every polygon-edge change. They are not a mesh or
    a thermal/material projection. All radii and split/overlap tests are exact.
    """
    if not poly:
        return ((Q(0), Q(0)),)*3, 0
    count = len(poly)+sum(len(row[0]) for row in donors)
    inputs = (*a, *b, rc, outer, gravity, *(q for row in profiles for q in row),
              *(q for p in poly for q in p),
              *(q for shape, low, high, coefficient in donors for q in
                (*(v for p in shape for v in p), low, high, coefficient)))
    with budget.reserve(65536+2048*count, category='pressure-angular-partition'), V._work(inputs, budget):
        receiver = _angular_wedges(poly)
        if not receiver:
            return ((Q(0), Q(0)),)*3, 0
        minimum, maximum = receiver[0][0], receiver[-1][1]
        events = {}
        def insert(key, left, right, value):
            left, right = max(left, minimum), min(right, maximum)
            if right <= left:
                return
            events.setdefault(left, []).append((key, value))
            events.setdefault(right, []).append((key, None))
        for i, (left, right, entry, exit_) in enumerate(receiver):
            insert((-1, i), left, right, (entry, exit_))
        for i, (shape, low, high, coefficient) in enumerate(donors):
            for j, (left, right, entry, exit_) in enumerate(_angular_wedges(shape)):
                insert((i, j), left, right, (entry, exit_, low, high, coefficient))
        active, pieces = {}, []
        knots = sorted(events)
        for left, right in zip(knots, knots[1:]):
            for key, value in events[left]:
                if value is None:
                    active.pop(key, None)
                else:
                    active[key] = value
            receivers = [value for (i, _), value in active.items() if i == -1]
            if not receivers:
                continue
            if len(receivers) != 1:
                raise PressureCouplingRefused('radial receiver angular partition overlaps')
            rows = tuple(value for (i, _), value in sorted(active.items()) if i != -1)
            pieces.append((left, right, (receivers[0], rows)))
        normal = O._cross(a, b)
        def evaluate(left, right, data, bits):
            edges, rows = data
            s, factors = _radial_chart_jets(a, b, normal, left, right, bits)
            low, high, fixed, possible = _radial_interval_jets(s, left, right, *edges, rc, outer)
            if not possible:
                return (_jet_constant(Q(0)),)*3, True
            total = _jet_constant(Q(0))
            for bottom, top, rho, ptop, weight in profiles:
                x, y, selected, exists = _radial_interval_jets(s, left, right, *edges, bottom, top)
                if not exists:
                    continue
                value, ordered = _positive_interval_primitive(x, y,
                    lambda r: _jet_add(_jet_scale(_jet_power(r, 3), (ptop+gravity*rho*top)/3),
                                       _jet_scale(_jet_power(r, 4), -gravity*rho/4)))
                total = _jet_add(total, _jet_scale(value, weight))
                fixed &= selected and ordered
            for entry, exit_, bottom, top, coefficient in rows:
                x, y, selected, exists = _radial_interval_jets(s, left, right, entry, exit_, bottom, top)
                if not exists:
                    continue
                value, ordered = _donor_radial_pressure(low, high, x, y)
                if not selected:
                    value = (_mul(value[0], (Q(0), Q(1))), (Q(0), Q(0)), (Q(0), Q(0)))
                total = _jet_add(total, _jet_scale(value, coefficient))
                fixed &= selected and ordered
            return tuple(_jet_mul(factor, total) for factor in factors), fixed
        def coefficients(data):
            edges, rows = data
            return (*a, *b, rc, outer, gravity, *(q for row in profiles for q in row),
                    *(q for edge in edges if edge is not None for q in edge),
                    *(q for entry, exit_, low, high, coefficient in rows for q in
                      (*(v for edge in (entry, exit_) if edge is not None for v in edge), low, high, coefficient)))
        return _integrate_angular(tuple(pieces), evaluate, coefficients, width=width, max_leaves=max_leaves, budget=budget)


def _pressure(profile, radius, gravity):
    for bottom, top, rho, pressure in profile:
        if bottom <= radius <= top:
            return pressure+rho*gravity*(top-radius)
    raise PressureCouplingRefused('radial pressure evaluation outside prescribed support')


def _radial_linear_mean(points, radial, normal, *, rc=Q(0)):
    """Triangle mean of (r-rc^3/r^2)*(normal cross x), with Hessian bound.

    The linear Taylor term integrates exactly to zero about the centroid.
    ||H(r*l.x)|| <= 3||l||; ||H((l.x)/r^2)|| <= 14||l||/r^3.
    L1 coefficient norms give rational upper bounds without another square root.
    """
    centre = tuple(sum(p[j] for p in points)/3 for j in range(3))
    r = _sqrt(O._dot(centre, centre), 96)
    moment = O._cross(normal, centre)
    variance = sum(O._dot(_minus(p, centre), _minus(p, centre)) for p in points)/12
    factor = r[0]-rc**3/r[0]**2, r[1]-rc**3/r[1]**2
    result = []
    for j, value in enumerate(moment):
        norm = sum(abs(normal[k]) for k in range(3) if k != j)
        remainder = norm*(3+14*rc**3/radial[0]**3)*variance/2
        mean = _scale(factor, value)
        result.append((mean[0]-remainder, mean[1]+remainder))
    return tuple(result)


def _ray_length(planes, points, radial, bottom, top):
    """Enclose radial length of [x,outward] intersect one box and one shell."""
    rlo, rhi = radial
    if rlo <= 0:
        raise PressureCouplingRefused('pressure wall reaches the spherical centre')
    entry = (Q(1), Q(1)); exit_ = (top/rhi, top/rlo)
    entry = (max(entry[0], bottom/rhi), max(entry[1], bottom/rlo))
    for plane in planes:
        values = tuple(O._dot(plane[:3], p) for p in points)
        interval = min(values), max(values)
        if interval == (0, 0):
            if plane[3] < 0:
                return Q(0), Q(0)
        elif interval[0] > 0:
            cap = _divide(Q(plane[3]), interval)
            exit_ = min(exit_[0], cap[0]), min(exit_[1], cap[1])
        elif interval[1] < 0:
            cap = _divide(Q(plane[3]), interval)
            entry = max(entry[0], cap[0]), max(entry[1], cap[1])
        else:
            return Q(0), max(Q(0), top-max(bottom, rlo))
    low = max(Q(0), exit_[0]-entry[1])*rlo
    high = max(Q(0), exit_[1]-entry[0])*rhi
    return min(low, top-bottom), min(high, top-bottom)


def wall_integrals(first, second, profiles, cells, densities, owned_box, *, gravity,
                   support_radius, width, max_leaves, budget):
    """Bound current-minus-archived global torque and current owned wall torque.

    Profiles are exact (bottom radius, top radius, density, top pressure) rows,
    left then right. This kernel has no authority to invent an ownership map.
    Its issued high-level caller supplies the actual disjoint funded grid.
    """
    a, b = tuple(map(Q, first)), tuple(map(Q, second))
    gravity, rc, width = Q(gravity), Q(support_radius), Q(width)
    if gravity <= 0 or rc <= 0 or width < 0 or type(max_leaves) is not int or max_leaves < 1:
        raise PressureCouplingRefused('positive gravity/support and explicit nonnegative width/work budgets required')
    active = []
    for cell, density in zip(cells, densities):
        poly, side = wall_polygon(cell, a, b)
        if poly:
            sides = ((side, Q(1, 2)),) if side is not None else ((0, Q(1, 2)), (1, Q(1, 2)))
            active.append((cell, Q(density), poly, sides, O._box_planes(cell)))
    native_poly, _ = wall_polygon(owned_box, a, b)
    allowance = width/max(1, len(active)+1)
    delta = [(Q(0), Q(0)) for _ in range(3)]
    leaves = 0
    for cell, density, poly, sides, _ in active:
        def anomaly(points, radial, moment):
            if radial[0] < rc:
                raise PressureCouplingRefused('owned cell wall lies below pressure support')
            difference = (Q(0), Q(0))
            for side, weight in sides:
                old = _density_range(profiles[side], radial)
                difference = _add(difference, _scale((density-old[1], density-old[0]), weight))
            if difference[0] == difference[1]:
                average = _radial_linear_mean(points, radial, O._cross(a, b), rc=rc)
                return tuple(_scale(v, -gravity*difference[0]/3) for v in average)
            kernel = radial[0]-rc**3/radial[0]**2, radial[1]-rc**3/radial[1]**2
            return tuple(_scale(_mul(_mul(difference, kernel), v), -gravity/3) for v in moment)
        bounded, used = _integrate(poly, a, b, anomaly, width=allowance, max_leaves=max_leaves, budget=budget)
        delta = [_add(v, w) for v, w in zip(delta, bounded)]; leaves += used
    def pressure(points, radial, moment):
        base = [(Q(0), Q(0)) for _ in range(3)]
        centre = tuple(sum(p[j] for p in points)/3 for j in range(3))
        linear = O._cross(O._cross(a, b), centre)
        average = _radial_linear_mean(points, radial, O._cross(a, b))
        for profile in profiles:
            row = next((row for row in profile if row[0] <= radial[0] and row[1] >= radial[1]), None)
            if row is not None:
                _, top, rho, ptop = row
                for j in range(3):
                    constant = (ptop+gravity*rho*top)*linear[j]/2
                    base[j] = _add(base[j], _add((constant, constant), _scale(average[j], -gravity*rho/2)))
            else:
                interval = _pressure(profile, radial[1], gravity)/2, _pressure(profile, radial[0], gravity)/2
                base = [_add(v, _mul(interval, w)) for v, w in zip(base, moment)]
        changed = (Q(0), Q(0))
        for _, density, _, sides, planes in active:
            for side, weight in sides:
                for bottom, top, rho, _ in profiles[side]:
                    if density == rho:
                        continue
                    length = _ray_length(planes, points, radial, bottom, top)
                    changed = _add(changed, _scale(length, gravity*weight*(density-rho)))
        return tuple(_scale(_add(v, _mul(changed, w)), -1) for v, w in zip(base, moment))
    removed, used = _integrate(native_poly, a, b, pressure, width=allowance,
                                max_leaves=max_leaves, budget=budget)
    return tuple(delta), removed, leaves+used


def reference_torque(native, lift):
    """The SAME native discrete pressure reaction, in actual plate virtual work."""
    definition = native.descriptor()
    if definition.get('pressure_reference') != lift._pressure_reference:
        raise PressureCouplingRefused('native pressure reference differs from physical lift')
    if native._pressure_reference is None:
        return np.zeros((2, 3))
    if definition['pressure_reference']['load_partition'] != 'full':
        raise PressureCouplingRefused('owned pressure replacement requires full physical native loads')
    reaction = _factored_scale(native._pressure_reference['reaction'].reshape(-1, 3),
        (native._eta0, native._scales.velocity_m_s, native._scales.length_m), (), 'reference reaction')
    return np.einsum('aij,ij->a', lift._full, reaction).reshape(2, 3)


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class OwnedPressureCorrection:
    _snapshot: RegionalMechanicalSnapshot
    _resource: object

    def __init__(self, *args, **kwargs):
        raise TypeError('OwnedPressureCorrection is issued from current funded collar state')

    @property
    def correction_id(self):
        return self._snapshot.result_id

    def descriptor(self):
        return dict(correction_id=self.correction_id, **self._snapshot.descriptor())

    def array(self, name):
        return self._snapshot.array(name)

    def arrays(self):
        return {k: self._snapshot.array(k) for k in self._snapshot.array_names}


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class RadialGravityField:
    _snapshot: RegionalMechanicalSnapshot
    _resource: object

    def __init__(self, *args, **kwargs):
        raise TypeError('RadialGravityField is issued from the actual physical volume map')

    @property
    def field_id(self):
        return self._snapshot.result_id

    def descriptor(self):
        return dict(field_id=self.field_id, **self._snapshot.descriptor())

    def array(self):
        return self._snapshot.array('gravity_m_s2')


def radial_gravity_field(collar, datum, *, budget):
    """Actual sphere-centred constant-magnitude gravity at native Gauss points.

    Directions vary spatially. The evolution consumer multiplies them by the
    CURRENT density every mechanics endpoint, not by an admission density.
    """
    from .regional_collar3d import PreparedRegionalCollar3D
    from .integration_radial_pressure import RadialDatum
    if type(collar) is not PreparedRegionalCollar3D or type(datum) is not RadialDatum or collar._budget is not budget:
        raise PressureCouplingRefused('actual mapped collar, radial datum and shared budget required')
    plan = collar.descriptor()
    native = collar._native
    binding = collar._map.record()
    source = native._radial_constitutive
    if source is None or source.descriptor()['volume_map_id'] != plan['volume_map_id']:
        raise PressureCouplingRefused('radial gravity requires the actual mapped radial constitutive source')
    if datum.reference_radius_m != binding['embedding']['sphere']['radius_m']:
        raise PressureCouplingRefused('gravity datum and physical source sphere differ')
    with budget.reserve(65536+1024*native._n*27, category='owned-radial-gravity'):
        # These are the same declared Gauss points used by the native source;
        # no mechanical solve/operator needs to exist before gravity is issued.
        coordinates = source.array('local_position_m')
        points = collar._origin+coordinates@collar._basis.T
        radius = np.linalg.norm(points, axis=-1)
        if np.any(radius <= 0) or np.any(radius > datum.reference_radius_m) or np.any(radius < datum.support_radius_m):
            raise PressureCouplingRefused('native gravity point outside declared radial support')
        gravity = (-datum.gravity_m_s2*points/radius[..., None])@collar._basis
        if not np.isfinite(gravity).all():
            raise PressureCouplingRefused('radial gravity is not representable')
        snapshot = RegionalMechanicalSnapshot(dict(schema='atlas.owned-radial-gravity.v1',
            native_plan_id=native.plan_id, volume_map_id=plan['volume_map_id'],
            embedding=binding['embedding'], datum=datum.record(), datum_id=datum.datum_id,
            rule='local components of -g*x/|x| at actual native volume quadrature; current density is not cached'),
            dict(gravity_m_s2=gravity, physical_position_m=points))
        out = object.__new__(RadialGravityField)
        object.__setattr__(out, '_snapshot', snapshot)
        object.__setattr__(out, '_resource', budget)
        lease = budget.reserve(8192+2*snapshot.nbytes, category='owned-radial-gravity-retained')
        lease.__enter__()
        weakref.finalize(out, lease.__exit__, None, None, None)
        return out


def owned_pressure_correction(sphere, moving, support, base_port, funding, collar, state,
                              *, max_torque_width_n_m, max_leaves, budget):
    """Current fixed-grid density replaces its archived source, spatially.

    The unextracted CSG remainder retains the supplied source geometry/field.
    Rotated or thermally changed remainder needs a new current geometry/field
    producer; this function never treats a fresh funding record as its advance.
    """
    from .integration_collar_geometry import FullCellFunding
    from .regional_collar3d import PreparedRegionalCollar3D, RegionalCollarState
    from .integration_radial_pressure import RadialPressureTrace
    from . import integration_material as M, integration_ports as P
    from .constitutive import boussinesq_response
    from .resources import WorkBudget
    if (type(funding) is not FullCellFunding or type(collar) is not PreparedRegionalCollar3D or
            type(state) is not RegionalCollarState or type(base_port) is not RadialPressureTrace or
            type(support) is not P.TraceSupport or type(budget) is not WorkBudget or
            funding._resource is not budget or collar._budget is not budget):
        raise PressureCouplingRefused('issued source trace, actual funded collar state and shared budget required')
    if (type(max_torque_width_n_m) not in (Q, int) or max_torque_width_n_m < 0 or
            type(max_leaves) is not int or max_leaves < 1):
        raise PressureCouplingRefused('exact nonnegative torque enclosure width and positive work limit required')
    M.bound_moving(moving, sphere)
    funded, plan = funding.descriptor(), collar.descriptor()
    binding = dict(sphere_state_id=sphere.state_id, network_id=sphere.network.network_id,
                   material_id=sphere.material.material_id, moving_id=moving.moving_id)
    if (funded['source'] != binding or funded['collar_plan_id'] != collar.plan_id or
            funded['volume_map_id'] != plan['volume_map_id'] or
            base_port.source_state_id != sphere.state_id or base_port.moving_id != moving.moving_id or
            base_port.material_id != sphere.material.material_id or
            base_port.support_id != support.support_id or support.network_id != sphere.network.network_id):
        raise PressureCouplingRefused('stale source, material wall, funding or collar geometry')
    native, datum = collar._native, base_port.datum
    material = native._material
    if material.reference_temperature_k != datum.reference_temperature_k:
        raise PressureCouplingRefused('native and radial pressure use different physical density reference temperatures')
    if material.composition_density_contrast_kg_m3 != 0:
        raise PressureCouplingRefused('radial source has no declared composition density field to subtract')
    count = math.prod(collar.cells)
    with budget.reserve(262144+16384*(count+support.edges)+8*len(base_port._record),
                        category='owned-pressure-source'):
        fields = collar._fields(state)
        cells = collar.cell_geometries()
        if [c.record() for c in cells] != funded['cell_geometries']:
            raise PressureCouplingRefused('current cell geometry differs from the funded CSG exclusion union')
        mass = np.sum(fields['component_mass_kg'], axis=0)
        temperature = fields['enthalpy_j']/(mass*material.heat_capacity_j_kg_k)
        composition = np.sum(fields['component_mass_kg']*np.asarray(native._composition).reshape((-1, 1, 1, 1)), axis=0)/mass
        response = boussinesq_response(material, temperature, composition, np.zeros(3),
                                      np.zeros((*collar.cells, 3)), budget=budget)
        density = material.density_kg_m3+response['density_anomaly_kg_m3']
        # Actual cell-centred constitutive evaluation; never a whole-patch mean.
        density = tuple(Q(float(v)) for v in density.flat)
        for c in cells:
            low, high = c.radial_bounds_squared_m2
            if low < Q(datum.support_radius_m)**2 or high > Q(datum.reference_radius_m)**2:
                raise PressureCouplingRefused('funded cell extends outside prescribed pressure support')
        inner = [c for i, c in enumerate(cells) if all(s.start <= int(j) < s.stop
                 for s, j in zip(collar._inner, np.unravel_index(i, collar.cells)))]
        owned = V.CartesianCell(tuple(min(c.lower_m[j] for c in inner) for j in range(3)),
            tuple(max(c.upper_m[j] for c in inner) for j in range(3)), inner[0].origin_m,
            inner[0].basis, budget=budget)
        rows = base_port.record()['layer_rows']
        offsets = base_port.layer_offsets
        profiles = [tuple(tuple(PH._rational(row[k]) for k in
                    ('bottom_radius_m', 'top_radius_m', 'effective_density_kg_m3', 'pressure_top_pa'))
                    for row in rows[int(offsets[i]):int(offsets[i+1])]) for i in range(base_port.points)]
        order = {p: i for i, p in enumerate(sphere.network.plate_ids)}
        delta = [[(Q(0), Q(0)) for _ in range(3)] for _ in order]
        removed = [[(Q(0), Q(0)) for _ in range(3)] for _ in order]
        total_leaves = 0
        outer = V.CartesianCell(tuple(min(c.lower_m[j] for c in cells) for j in range(3)),
            tuple(max(c.upper_m[j] for c in cells) for j in range(3)), cells[0].origin_m,
            cells[0].basis, budget=budget)
        edges = [e for e in range(support.edges) if wall_polygon(outer, support.start[e], support.end[e])[0]]
        width = Q(max_torque_width_n_m)/max(1, len(edges))
        for e in edges:
            d, w, leaves = wall_integrals(support.start[e], support.end[e], profiles[2*e:2*e+2],
                cells, density, owned, gravity=datum.gravity_m_s2, support_radius=datum.support_radius_m,
                width=width, max_leaves=max_leaves, budget=budget)
            total_leaves += leaves
            for side, sign in ((0, 1), (1, -1)):
                plate = order[support.plates[e][side]]
                delta[plate] = [_add(a, _scale(b, sign)) for a, b in zip(delta[plate], d)]
                removed[plate] = [_add(a, _scale(b, sign)) for a, b in zip(removed[plate], w)]
        def project(bounds):
            values = np.asarray([[float((a+b)/2) for a, b in row] for row in bounds])
            if not np.isfinite(values).all():
                raise PressureCouplingRefused('owned pressure torque cannot be projected to finite binary64')
            residual = [[V._encoded(Q(float(value))-(a+b)/2) for value, (a, b) in zip(row, exact)]
                        for row, exact in zip(values, bounds)]
            return values, residual
        def encode(bounds):
            return [[list(map(V._encoded, pair)) for pair in row] for row in bounds]
        exact_combined = [[(a[0]-b[1], a[1]-b[0]) for a, b in zip(da, re)]
                          for da, re in zip(delta, removed)]
        projections = {name: project(bounds) for name, bounds in
            (('density_update_torque_n_m', delta), ('removed_wall_torque_n_m', removed),
             ('physical_exterior_correction_n_m', exact_combined))}
        arrays = {name: pair[0] for name, pair in projections.items()}
        arrays['current_cell_density_kg_m3'] = np.asarray(list(map(float, density))).reshape(collar.cells)
        metadata = dict(schema='atlas.owned-radial-pressure-correction.v1', source=binding,
            base_port_id=base_port.port_id, support_id=support.support_id, datum_id=datum.datum_id,
            funding_id=funding.funding_id, collar_plan_id=collar.plan_id, collar_state_id=state.result_id,
            native_state_id=state.native_state.result_id, time_s=state.native_state.descriptor()['time_s'],
            native_plan_id=native.plan_id, plate_ids=list(sphere.network.plate_ids),
            volume_map_id=plan['volume_map_id'], owned_box=owned.record(),
            density_update_bounds_n_m=encode(delta), removed_wall_bounds_n_m=encode(removed),
            physical_exterior_correction_bounds_n_m=encode(exact_combined),
            binary64_minus_enclosure_midpoint_n_m={name: pair[1] for name, pair in projections.items()},
            request=dict(max_torque_width_n_m=V._encoded(Q(max_torque_width_n_m)), max_leaves=max_leaves),
            integration_leaves=total_leaves, source_shadow='old owned density subtracted before current density added',
            remainder='unchanged source cone/shell minus the exact funded cell exclusion union',
            pressure='hydrostatic force reference, not solved material mean stress',
            partition='b_exterior=b_D1+delta_density-actual_owned_wall; native Q1 reference counterterm is separate',
            scope='current fixed-grid material; unchanged exterior CSG geometry and source field only')
        snapshot = RegionalMechanicalSnapshot(metadata, arrays)
        out = object.__new__(OwnedPressureCorrection)
        object.__setattr__(out, '_snapshot', snapshot)
        object.__setattr__(out, '_resource', budget)
        lease = budget.reserve(8192+2*snapshot.nbytes, category='owned-pressure-retained')
        lease.__enter__()
        weakref.finalize(out, lease.__exit__, None, None, None)
        return out
