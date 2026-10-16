"""Certified time integrals of a moving angular polygon on a fixed face.

Scalar moments require the COMPLETE face inside its radial layer. Rigid normal
flux also admits an exact disk-clipped first-moment formula on radial-cut faces.
Interval signs must prove one clipping topology on the time subinterval. The
polygon moment formula is then analytic and Taylor's theorem bounds its time
integral. Branch uncertainty falls back to the original geometric enclosure;
it is never a guessed sign, a removed component or a new physical tolerance.
SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction as Q
from math import factorial, gcd
import sys
import heapq
import hashlib
from pathlib import Path
from itertools import combinations

from .integration_q2_directed import _Intervals, _Branch
from . import integration_volume as V, integration_volume_overlap as O

ORDER = 12
POSE_LEVEL = 128
_LOADED = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def source_digest():
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED:
        raise V.VolumeError('moving-face integration source changed after loading')
    from .integration_q2_directed import source_digest as interval_digest
    from .integration_circular_moments import source_digest as circular_digest
    from .integration_rigid_intersection import source_digest as intersection_digest
    return hashlib.sha256((_LOADED+interval_digest()+circular_digest()+intersection_digest()).encode('ascii')).hexdigest()


# G-PY: jet products by per-coefficient interval classes (T/ck/transforms/gpy_q2_jets.py).
from decimal import Decimal as _GPY_DECIMAL

_GPY_ZERO = (_GPY_DECIMAL(0), _GPY_DECIMAL(0))
# (low corner, high corner) of _Intervals.mul per sign-class pair; mixed x mixed is separate.
_GPY_CORNERS = {(1, 1): ((0, 0), (1, 1)), (1, 2): ((1, 0), (0, 1)), (1, 3): ((1, 0), (1, 1)),
                (2, 1): ((0, 1), (1, 0)), (2, 2): ((1, 1), (0, 0)), (2, 3): ((0, 1), (0, 0)),
                (3, 1): ((0, 1), (1, 1)), (3, 2): ((1, 0), (0, 0))}


def _gpy_plain(J):
    """A plain _Jets over a plain Decimal _Intervals whose zero is numerically (0, 0)."""
    I = J.I
    return (type(J) is _Jets and type(I) is _Intervals
            and not any(name in I.__dict__ for name in ('mul', 'add', 'sub', 'div', 'neg'))
            and J.zero == _GPY_ZERO)


def _gpy_class(x):
    """(live, point, class) as _Intervals.mul tests them; class 0 = a zero endpoint, 1 > 0, 2 < 0, 3 mixed."""
    if type(x) is not tuple or len(x) != 2 or type(x[0]) is not _GPY_DECIMAL or type(x[1]) is not _GPY_DECIMAL:
        return None
    x0, x1 = x
    if not (x0.is_finite() and x1.is_finite()):
        return None
    if x0.is_zero() or x1.is_zero():
        cls = 0
    elif x0 > 0:
        cls = 1
    elif x1 < 0:
        cls = 2
    else:
        cls = 3
    return (x != _GPY_ZERO, x0 == x1, cls)


def _gpy_product(lm, hm, x, kx, y, ky):
    """_Intervals.mul(x, y) from the classes of x and y."""
    if kx[1] and ky[1]:
        return lm(x[0], y[0]), hm(x[1], y[1])
    cx, cy = kx[2], ky[2]
    if cx == 0 or cy == 0:
        x0, x1 = x
        y0, y1 = y
        p0 = lm(x0, y0)
        t = lm(x0, y1)
        if t < p0:
            p0 = t
        t = lm(x1, y0)
        if t < p0:
            p0 = t
        t = lm(x1, y1)
        if t < p0:
            p0 = t
        p1 = hm(x0, y0)
        t = hm(x0, y1)
        if t > p1:
            p1 = t
        t = hm(x1, y0)
        if t > p1:
            p1 = t
        t = hm(x1, y1)
        if t > p1:
            p1 = t
        return p0, p1
    if cx == 3 and cy == 3:
        return min(lm(x[0], y[1]), lm(x[1], y[0])), max(hm(x[0], y[0]), hm(x[1], y[1]))
    (li, lj), (hi, hj) = _GPY_CORNERS[cx, cy]
    return lm(x[li], y[lj]), hm(x[hi], y[hj])


def _gpy_mul(J, a, b):
    """J.mul(a, b) for a plain J after its zero/convolution routes, or None for the original."""
    if len(a) != ORDER+1 or len(b) != ORDER+1:
        return None
    ka = [_gpy_class(x) for x in a]
    kb = [_gpy_class(y) for y in b]
    if None in ka or None in kb:
        return None
    lm, hm, la, ha = J.I.lo.multiply, J.I.hi.multiply, J.I.lo.add, J.I.hi.add
    z0, z1 = J.zero
    result = []
    for k in range(ORDER+1):
        v0, v1 = z0, z1
        for i in range(k+1):
            kx, ky = ka[i], kb[k-i]
            if kx[0] and ky[0]:
                p0, p1 = _gpy_product(lm, hm, a[i], kx, b[k-i], ky)
                v0 = la(v0, p0)
                v1 = ha(v1, p1)
        result.append((v0, v1))
    return tuple(result)


def _gpy_div(J, a, b):
    """J.div(a, b) for a plain J, or None for the original."""
    if len(a) != ORDER+1 or len(b) != ORDER+1:
        return None
    kb = [_gpy_class(y) for y in b]
    if None in kb:
        return None
    I = J.I
    lm, hm, la, ha = I.lo.multiply, I.hi.multiply, I.lo.add, I.hi.add
    z0, z1 = J.zero
    result, kr = [], []
    for k in range(ORDER+1):
        t0, t1 = z0, z1
        for i in range(1, k+1):
            p0, p1 = _gpy_product(lm, hm, b[i], kb[i], result[k-i], kr[k-i])
            t0 = la(t0, p0)
            t1 = ha(t1, p1)
        value = I.div(I.sub(a[k], (t0, t1)), b[0])
        known = _gpy_class(value)
        if known is None:
            return None
        result.append(value)
        kr.append(known)
    return tuple(result)


class _Jets:
    def __init__(self, intervals=None, *, budget=None):
        self.I = _Intervals() if intervals is None else intervals
        self.zero = self.I.point(0)
        self.z = (self.zero,)*(ORDER+1)
        # Only an explicit owner can admit the extra integer workspace. Other
        # callers, rounded intervals and custom algebras retain the old route.
        self._convolution_budget = budget

    def constant(self, q):
        return (self.I.point(q),)+(self.zero,)*ORDER

    def add(self, a, b):
        if a == self.z:
            return b
        if b == self.z:
            return a
        return tuple(self.I.add(x, y) for x, y in zip(a, b))

    def neg(self, a):
        return tuple(self.I.neg(q) for q in a)

    def sub(self, a, b):
        return self.add(a, self.neg(b))

    def scale(self, a, q):
        if not q:
            return self.z
        if q == 1:
            return a
        factor = self.I.point(q)
        return tuple(self.I.mul(v, factor) for v in a)

    def mul(self, a, b):
        if a == self.z or b == self.z:
            return self.z
        if (type(self) is _Jets and self._convolution_budget is not None
                and type(self.I) is _RationalIntervals
                and sys.implementation.name == 'cpython'
                and type(a) is tuple and type(b) is tuple
                and len(a) == len(b) == ORDER+1
                and all(type(pair) is tuple and len(pair) == 2
                        and type(pair[0]) is type(pair[1]) is Q and pair[0] == pair[1]
                        for jet in (a, b) for pair in jet)):
            # For each coefficient every input occurs at most once. The
            # running denominator divides the product of those denominators;
            # at most 13 products need four extra numerator bits. No large
            # integer arithmetic happens before optional atomic admission.
            bits = 4
            for jet in (a, b):
                bits += sum(pair[0].denominator.bit_length() for pair in jet)
                bits += max(pair[0].numerator.bit_length() for pair in jet)
            digits = (bits+sys.int_info.bits_per_digit-1)//sys.int_info.bits_per_digit
            scratch = 8192+128*(64+digits*sys.int_info.sizeof_digit)
            with self._convolution_budget.try_reserve(
                    scratch, category='exact-jet-convolution') as admitted:
                if admitted:
                    return self._point_convolution(a, b)
        # Do not repeat the leading equality checks: custom inputs may observe
        # them. Declining an optimisation is not a physical-resource refusal.
        if type(self) is not _Jets:
            return tuple(self._sum(self.I.mul(a[i], b[k-i]) for i in range(k+1)
                         if a[i] != self.zero and b[k-i] != self.zero) for k in range(ORDER+1))
        if _gpy_plain(self):
            classed = _gpy_mul(self, a, b)
            if classed is not None:
                return classed
        # Same products, same order, same zero start as the line above; each
        # coefficient is compared with zero once instead of once per k.
        zero, multiply, add = self.zero, self.I.mul, self.I.add
        live_a = [x != zero for x in a]
        live_b = [y != zero for y in b]
        result = []
        for k in range(ORDER+1):
            value = zero
            for i in range(k+1):
                if live_a[i] and live_b[k-i]:
                    value = add(value, multiply(a[i], b[k-i]))
            result.append(value)
        return tuple(result)

    def _point_convolution(self, a, b):
        """Exact array-free convolution, called only inside its workspace lease.

        Normalise once per coefficient, not once per product and partial sum.
        The reservation includes completed coefficients until transfer to the
        caller's existing jet owner. Clear extra locals even with a held trace.
        """
        result = []
        numerator = denominator = terms = p = d = q = e = c = common = None
        c_reduced = denominator_reduced = product = left = right = value = None
        try:
            for k in range(ORDER+1):
                numerator, denominator, terms = 0, 1, 0
                for i in range(k+1):
                    if a[i] == self.zero or b[k-i] == self.zero:
                        continue
                    p, d = a[i][0].numerator, a[i][0].denominator
                    q, e = b[k-i][0].numerator, b[k-i][0].denominator
                    c = d*e
                    common = gcd(denominator, c)
                    c_reduced = c//common
                    denominator_reduced = denominator//common
                    product = p*q
                    left = numerator*c_reduced
                    right = product*denominator_reduced
                    numerator = left+right
                    denominator = denominator_reduced*c
                    terms += 1
                if terms:
                    # Reduce before entering Fraction's Python frame, so an
                    # allocation-error traceback there cannot retain our larger
                    # deferred-denominator integers beyond this lease.
                    common = gcd(numerator, denominator)
                    numerator //= common
                    denominator //= common
                    value = Q(numerator, denominator)
                    result.append((value, value))
                else:
                    result.append(self.zero)
            return tuple(result)
        finally:
            result.clear()
            numerator = denominator = terms = p = d = q = e = c = common = None
            c_reduced = denominator_reduced = product = left = right = value = None

    def _sum(self, values):
        result = self.zero
        for value in values:
            result = self.I.add(result, value)
        return result

    def div(self, a, b):
        if _gpy_plain(self):
            classed = _gpy_div(self, a, b)
            if classed is not None:
                return classed
        result = []
        for k in range(ORDER+1):
            tail = self._sum(self.I.mul(b[i], result[k-i]) for i in range(1, k+1))
            result.append(self.I.div(self.I.sub(a[k], tail), b[0]))
        return tuple(result)


def _cross(a, b, J):
    return tuple(J.sub(J.mul(a[(j+1) % 3], b[(j+2) % 3]),
                       J.mul(a[(j+2) % 3], b[(j+1) % 3])) for j in range(3))


def _rotated(vector, omega, bounds, J, arena):
    from . import integration_differential_geometry as G
    posed = G._rotation_boxes(vector, omega, *bounds, POSE_LEVEL, arena)
    columns = [[(J.I.point(lo)[0], J.I.point(hi)[1])] for lo, hi in posed]
    for k in range(1, ORDER+1):
        previous = [c[-1] for c in columns]
        for j in range(3):
            derivative = J.I.sub(J.I.mul(J.I.point(omega[(j+1) % 3]), previous[(j+2) % 3]),
                                J.I.mul(J.I.point(omega[(j+2) % 3]), previous[(j+1) % 3]))
            columns[j].append(J.I.mul(derivative, J.I.point(Q(1, k))))
    return tuple(tuple(column) for column in columns)


def _normal(constraint, bounds, J, arena):
    from . import integration_differential_geometry as G
    from . import integration_wall_measures as W
    kind = constraint['kind']
    path = G._rigid_plane_path(constraint)
    if path is not None:
        normal, theta, omega = path
        vector = tuple((q, q) for q in normal)
        if any(theta):
            vector = G._rotation_boxes(vector, theta, Q(1), Q(1), POSE_LEVEL, arena)
        return _rotated(vector, omega, bounds, J, arena), Q(0)
    if kind == 'fixed-plane':
        return tuple(J.constant(q) for q in G._load_vec(constraint['normal'])), W._decode(constraint['offset'])
    if kind == 'snapshot-rotated':
        at = W._decode(constraint['snapshot_offset_s'])
        vector, offset = G._constraint_boxes(constraint['constraint'], at, at, POSE_LEVEL, arena)
        return _rotated(vector, G._load_vec(constraint['angular_velocity_rad_s']), bounds, J, arena), offset
    if kind == 'moving-ray-edge':
        rays = []
        for ray in constraint['rays']:
            vector = tuple((q, q) for q in G._load_vec(ray['direction']))
            for w, dt in G._history(ray.get('prior_rotations', ())):
                vector = G._rotation_boxes(vector, w, dt, dt, POSE_LEVEL, arena)
            rays.append(_rotated(vector, G._load_vec(ray['angular_velocity_rad_s']), bounds, J, arena))
        return _cross(*rays, J), Q(0)
    raise V.VolumeError('unsupported physical moving-plane record')


def _line(normal, offset, face, sign, J):
    result = []
    for point in (face[1], face[2], face[0]):
        value = J.z
        for coordinate, coefficient in zip(normal, point):
            value = J.add(value, J.scale(coordinate, coefficient))
        result.append(J.scale(value, sign))
    result[2] = J.sub(result[2], J.constant(sign*offset))
    return tuple(result)


def _active_intersection(line, active, line_for, J, removable=None):
    """Intersect two actual edge lines, only with a closed-interval inverse.

    A shrinking edge can have coincident endpoint vertices at t=0 although
    its supporting line intersects the new cut regularly. Cramer's rule
    avoids the removable 0/0 in endpoint interpolation. If the original
    determinant vanishes at the initial time, an optional exact algebraic
    cancellation may supply a closed-interval regular continuation. Prefer
    that identity even on leaves away from zero: the unreduced quotient can
    have artificial interval derivative growth despite a nonzero denominator.
    Neither route infers a shared edge from proximity.
    """
    if removable is not None:
        regular = removable()
        if regular is not None:
            return regular
    for name in sorted(active, key=repr):
        edge = line_for(name)
        determinant = J.sub(J.mul(line[0], edge[1]), J.mul(line[1], edge[0]))
        if determinant[0][0] <= 0 <= determinant[0][1]:
            continue
        return (J.div(J.sub(J.mul(line[1], edge[2]), J.mul(line[2], edge[1])), determinant),
                J.div(J.sub(J.mul(line[2], edge[0]), J.mul(line[0], edge[2])), determinant))
    return None


def _endpoint_departure(coefficients, derivatives, upper_time, J):
    """Exact signed Taylor prefix plus a rigorously enclosed remainder.

    For t>=0, a same-sign prefix and remainder certify that sign without
    discarding any small nonzero lower term. A negative result is strict only
    on t>0; the numerical enclosure still contains the exact f(0)=0. Mixed
    signs retain the enclosure but do not license a departure classification.
    Coefficients and derivative jets must have the SAME plane orientation.
    """
    bound = None
    prefix = J.zero
    positive = negative = False
    for degree in range(1, ORDER+1):
        coefficient = coefficients[degree-1]
        if degree == 1 and coefficient != 0:
            break
        positive = positive or coefficient > 0
        negative = negative or coefficient < 0
        if positive and negative:
            break
        if coefficient:
            prefix = J.I.add(prefix, J.I.mul(J.I.point(coefficient),
                (J.I.point(0)[0], J.I.point(upper_time**(degree-1))[1])))
        derivative = derivatives[degree]
        current = J.I.add(prefix, J.I.mul(
            (J.I.point(0)[0], J.I.point(upper_time**degree)[1]), derivative))
        bound = current if bound is None else (max(bound[0], current[0]), min(bound[1], current[1]))
        if not positive and derivative[1] <= 0 and (negative or derivative[1] < 0):
            return bound, False
        if not negative and derivative[0] >= 0 and (positive or derivative[0] > 0):
            return bound, True
        if positive and derivative[1] < 0 or negative and derivative[0] > 0:
            break  # Opposing terms require a real crossing/sign proof, not this rule.
    return bound, None


def _fixed_corner_predicate(record, face, arena):
    """Signed value at an exact rectangle corner fixed by the actual pose.

    This is not incidence: tiny nonzero values retain their exact sign. Two
    unambiguous rectangle coordinates locate the physical point. Each of the
    authoritative rigid path's rotations must fix that point; otherwise this
    predicate declines. The caller intersects every returned jet coefficient.
    """
    from . import integration_differential_geometry as G
    paths, corners, cache = {}, {}, {}
    zero = (Q(0),)*3
    def value(name, active, J):
        if name not in record['constraints']:
            return None
        ends = tuple(tuple(end for end in range(2) if ('rectangle', axis, end) in active)
                     for axis in range(2))
        if any(len(row) != 1 for row in ends):
            return None
        ends = tuple(row[0] for row in ends)
        if name not in paths:
            constraint = record['constraints'][name]
            if constraint['kind'] == 'fixed-plane':
                path = (G._load_vec(constraint['normal']), zero, zero, G.W._decode(constraint['offset']))
            else:
                rigid = G._rigid_plane_path(constraint)
                path = None if rigid is None else (*rigid, Q(0))
            arena.keep(() if path is None else tuple(q for vector in path[:3] for q in vector)+(path[3],),
                       1 if path is None else 4)
            paths[name] = path
        path = paths[name]
        if path is None:
            return None
        key = name, ends
        if key not in cache:
            normal, theta, omega, offset = path
            values = (*normal, *theta, *omega, offset, *(q for row in face[:3] for q in row),
                      *(q for row in face[4] for q in row))
            arena.work(128)
            with V._work(values, arena.resource):
                if ends not in corners:
                    u, v = (face[4][axis][end] for axis, end in enumerate(ends))
                    point = tuple(face[0][j]+u*face[1][j]+v*face[2][j] for j in range(3))
                    arena.keep(point, 1)
                    corners[ends] = point
                point = corners[ends]
                constant = None if any(O._cross(theta, point)) or any(O._cross(omega, point)) else O._dot(normal, point)-offset
                arena.keep(() if constant is None else (constant,), 1)
                cache[key] = constant
        return None if cache[key] is None else J.constant(cache[key])
    return value


def _shared_rotation_predicate(record, face, arena):
    """Correlated value on one moving plane and one rectangle edge.

    For a through-origin face w.x=0, an active homogeneous plane m.x=0
    and rectangle plane e.x=h give x=h*(w cross m)/(e.(w cross m)).
    If the queried n and m have the SAME exact rigid pose R, their scalar
    triple product is w.R*(m0 cross n0). Taking this small cross product
    exactly BEFORE rotation preserves nonzero near-parallel determinants.
    This is an alternate analytic value, never an incidence/zero claim.
    """
    from . import integration_differential_geometry as G
    if O._dot(face[0], face[3]) != 0:
        return lambda *args: None
    paths, pairs = {}, {}
    def path(name):
        if name not in paths:
            decoded = G._rigid_plane_path(record['constraints'][name])
            arena.keep(() if decoded is None else tuple(q for vector in decoded for q in vector),
                       1 if decoded is None else 4)
            paths[name] = decoded
        return paths[name]
    def value(name, active, bounds, J):
        if name not in record['constraints']:
            return None
        new = path(name)
        if new is None:
            return None
        for edge in sorted(active, key=repr):
            if not (isinstance(edge, tuple) and len(edge) == 3 and
                    edge[0] == 'rectangle'):
                continue
            _, axis, end = edge
            e = face[1+axis]
            h = O._dot(e, face[0])+face[4][axis][end]
            for old_name in sorted(active, key=repr):
                if old_name not in record['constraints']:
                    continue
                old = path(old_name)
                if old is None or old[1:] != new[1:]:
                    continue
                key = name, old_name
                if key not in pairs:
                    arena.work(128)
                    with V._work((*old[0], *new[0]), arena.resource):
                        cross = O._cross(old[0], new[0])
                        arena.keep(cross, 1)
                        pairs[key] = cross
                cross = pairs[key]
                # Exact parallel planes are already covered by incidence.
                if not any(cross):
                    continue
                theta, omega = new[1:]
                def rotate(vector):
                    posed = tuple((q, q) for q in vector)
                    if any(theta):
                        posed = G._rotation_boxes(posed, theta, Q(1), Q(1), POSE_LEVEL, arena)
                    return _rotated(posed, omega, bounds, J, arena)
                moving = rotate(old[0])
                w_cross_m = tuple(J.sub(J.scale(moving[(j+2) % 3], face[3][(j+1) % 3]),
                    J.scale(moving[(j+1) % 3], face[3][(j+2) % 3])) for j in range(3))
                denominator = J.z
                for j in range(3):
                    denominator = J.add(denominator, J.scale(w_cross_m[j], e[j]))
                if denominator[0][0] <= 0 <= denominator[0][1]:
                    continue
                # A singular/uncertain vertex cannot use this identity; do
                # not spend another rotation workspace on its numerator.
                determinant = rotate(cross)
                numerator = J.z
                for j in range(3):
                    numerator = J.add(numerator, J.scale(determinant[j], face[3][j]))
                arena.work(64*(ORDER+1)**2)
                return J.scale(J.div(numerator, denominator), h)
        return None
    return value


_PHYSICAL_ORIGIN = ('certified-physical-origin',)


def _strict_interior_sign(value, bounds):
    """A weak closed bound plus strict monotonicity proves an interior sign.

    This changes topology metadata only. A point-time query or a derivative
    containing zero cannot establish this proof, however small its width.
    """
    if bounds[0] >= bounds[1] or value[1][0] <= 0 <= value[1][1]:
        return None
    if value[0][0] >= 0:
        return True
    if value[0][1] <= 0:
        return False
    return None


def _time_event_split(bounds, reference, derivative, arena):
    """An interior subdivision hint, never a root or topology certificate.

    A midpoint Newton estimate can put the next cut near a moving vertex
    event instead of spending many dyadic leaves finding it. Both resulting
    CLOSED intervals are still evaluated and certified independently. An
    inaccurate hint cannot discard time, select a sign or grant acceptance.
    Zero-containing derivatives and out-of-interval estimates use bisection.
    The hint is placed on a 16-bit relative dyadic grid so repeated Newton
    ratios do not multiply huge rational denominators in rotation bounds.
    This grid chooses work only; it is not an accuracy or geometry tolerance.
    """
    values = tuple(Q(q) for q in (*bounds, *reference, *derivative))
    arena.work(64)
    with V._work(values, arena.resource):
        a, b, lo, hi, dlo, dhi = values
        if a >= b or dlo <= 0 <= dhi:
            return None
        split = (a+b)/2-(lo+hi)/(dlo+dhi)
        if not a < split < b:
            return None
        subdivisions = 1 << 16
        position = (split-a)/(b-a)*subdivisions
        index = max(1, min(subdivisions-1, round(position)))
        split = a+(b-a)*Q(index, subdivisions)
        arena.keep((split,), 1)
        return split


def _homogeneous_origin_proof(record, face, arena):
    """Exact physical origin and the cuts which contain it for all time.

    No pair of plane identities by itself locates a vertex at the origin:
    coincident planes can contain an entire non-origin edge. The caller tags
    only a constructed origin or an exactly authored rectangle corner.
    """
    from . import integration_wall_measures as W
    values = tuple(q for vector in face[:4] for q in vector)
    values += tuple(q for pair in face[4] for q in pair)
    arena.work(64*(len(record['constraints'])+5))
    with V._work(values, arena.resource):
        if O._dot(face[0], face[3]) != 0:
            return None
        point = tuple(-O._dot(face[0], tangent) for tangent in face[1:3])
        if not all(lo <= q <= hi for q, (lo, hi) in zip(point, face[4])):
            return None
        arena.keep(point, 1)
    def homogeneous(constraint):
        if constraint['kind'] == 'snapshot-rotated':
            return homogeneous(constraint['constraint'])
        if constraint['kind'] in ('moving-ray-edge', 'rotated-normal'):
            return True
        return constraint['kind'] == 'fixed-plane' and W._decode(constraint['offset']) == 0
    names = {name for name, constraint in record['constraints'].items() if homogeneous(constraint)}
    for axis in range(2):
        for end in range(2):
            # Physical offset is tangent.origin + local boundary, not just
            # the local rectangle coordinate (the chart need not be centred).
            if face[4][axis][end] == point[axis]:
                names.add(('rectangle', axis, end))
    return point, frozenset(names)


def _origin_crossing(proof, line_for, J, arena, bounds=None):
    """Called only for strictly opposite open-interval endpoint signs.

    A retained homogeneous edge and a new homogeneous cut then cannot be
    coincident on the open interval. Their unique intersection is the exact
    origin, also its continuous limit at a degenerate time endpoint.
    The retained edge's face normal remains nonzero on the closed interval.
    A new cut may vanish exactly at a time endpoint: the caller's opposite
    strict signs prove its nonzero normal and independence in the open
    interval. A point-time query cannot borrow this limiting construction.
    """
    if proof is None:
        return None
    point, names = proof
    origin = tuple(J.constant(q) for q in point)
    def nonzero(line):
        return any(q[0][0] > 0 or q[0][1] < 0 for q in line[:2])
    def crossing(identity, active, *, strict_crossing=False):
        arena.work(32*(len(active)+1))
        open_crossing = strict_crossing and bounds is not None and bounds[0] < bounds[1]
        if identity not in names or not (nonzero(line_for(identity)) or open_crossing):
            return None
        if any(name in names and nonzero(line_for(name)) for name in active):
            return origin
        return None
    return crossing


def _clip(poly, line, identity, J, incidence=None, guard=None, classification=None, intersection=None,
          origin_crossing=None):
    if not poly:
        return ()
    def value(point, index):
        if identity in point[2] or incidence is not None and incidence(identity, point[2]):
            result = J.z
        else:
            result = J.add(J.add(J.mul(line[0], point[0]), J.mul(line[1], point[1])), line[2])
        return guard(identity, index, len(poly), result, point[2]) if guard is not None else result
    def inside(v, index):
        if classification is not None:
            proved = classification(identity, index, len(poly))
            if proved is not None:
                return proved
        if v[0][0] >= 0:
            return True
        if v[0][1] < 0:
            return False
        raise _Branch()
    def strict(v, index, positive):
        if (v[0][0] > 0) if positive else (v[0][1] < 0):
            return True
        proved = classification(identity, index, len(poly)) if classification is not None else None
        return proved is positive
    out = []
    previous = poly[-1]; old = value(previous, len(poly)-1); old_inside = inside(old, len(poly)-1)
    for index, point in enumerate(poly):
        current = value(point, index); current_inside = inside(current, index)
        if current_inside != old_inside:
            # An exactly on-cut endpoint IS the crossing, including when the
            # other endpoint departs only on the open time interval. Retain
            # all its incidence identities; interpolating would form 0/0.
            on_cut = previous if old == J.z else point if current == J.z else None
            active = on_cut[2] if on_cut is not None else (previous[2] & point[2]) - {_PHYSICAL_ORIGIN}
            crossing = on_cut[:2] if on_cut is not None else None
            if (crossing is None and origin_crossing is not None and
                    strict(old, (index-1) % len(poly), old_inside) and strict(current, index, current_inside)):
                crossing = origin_crossing(identity, active, strict_crossing=True)
                if crossing is not None:
                    active = active | {_PHYSICAL_ORIGIN}
            if crossing is None and intersection is not None:
                crossing = intersection(line, active)
            if crossing is None:
                fraction = J.div(old, J.sub(old, current))
                crossing = tuple(J.add(previous[j], J.mul(fraction, J.sub(point[j], previous[j]))) for j in range(2))
            out.append((*crossing, active | {identity}))
        if current_inside:
            proved = incidence is not None and incidence(identity, point[2])
            out.append((*point[:2], point[2] | {identity}) if proved else point)
        previous, old, old_inside = point, current, current_inside
    return tuple(out)


def _invariant_edge_plane(constraint, arena):
    """Unoriented plane only: differential coaxial rays may reverse its normal.

    Every retained rotation must preserve the exact plane through both initial
    rays. The caller must still prove actual active-line independence and a
    nonzero actual edge normal over its closed time interval. This result must
    never replace a physical halfspace or its time-dependent sign.
    """
    from . import integration_differential_geometry as G
    if constraint['kind'] == 'snapshot-rotated':
        normal = _invariant_edge_plane(constraint['constraint'], arena)
        if normal is None:
            return None
        omega = G._load_vec(constraint['angular_velocity_rad_s'])
        with V._work((*normal, *omega), arena.resource):
            return None if any(O._cross(normal, omega)) else normal
    if constraint['kind'] != 'moving-ray-edge':
        return None
    rays = constraint['rays']
    directions = tuple(G._load_vec(ray['direction']) for ray in rays)
    rotations = tuple(w for ray in rays for w in
        (*tuple(w for w, _ in G._history(ray.get('prior_rotations', ()))),
         G._load_vec(ray['angular_velocity_rad_s'])))
    arena.work(128)
    with V._work(tuple(q for v in (*directions, *rotations) for q in v), arena.resource):
        normal = O._cross(*directions)
        if not any(normal) or any(any(O._cross(normal, w)) for w in rotations):
            return None
        arena.keep(tuple(normal), 1)
        return normal


def _incidence_proof(record, face, arena):
    """Exact moving-plane incidence, including invariant rectangle edges.

    Three planes sharing one actual rigid pose retain their constant linear
    relations. An invariant plane can use that same pose. This proves a new
    plane contains an existing two-plane intersection; it does not merge two
    nearby cuts or infer coincidence from a small interval residual.
    """
    from . import integration_differential_geometry as G
    zero = (Q(0),)*3
    paths, unoriented = {}, set()
    for name, constraint in record['constraints'].items():
        path = G._rigid_plane_path(constraint)
        if path is not None:
            paths[name] = (*path, Q(0))
        elif constraint['kind'] == 'fixed-plane':
            paths[name] = (G._load_vec(constraint['normal']), zero, zero,
                           G.W._decode(constraint['offset']))
        else:
            normal = _invariant_edge_plane(constraint, arena)
            if normal is not None:
                paths[name] = (normal, zero, zero, Q(0))
                unoriented.add(name)
    for axis in range(2):
        for end in range(2):
            normal = face[1+axis]
            paths[('rectangle', axis, end)] = (normal, zero, zero,
                O._dot(normal, face[0])+face[4][axis][end])
    cache = {}
    def contains(name, active, line_for=None, J=None):
        if name not in paths:
            return False
        # One retained edge is sufficient when its complete physical plane
        # coincides with this cut. This is only an on-plane predicate: signs
        # and the actual time-dependent normals remain unchanged. In
        # particular, an offset fixed face does not require a second moving
        # edge merely to recognise its exactly authored rectangle boundary.
        for edge in sorted(active, key=repr):
            if edge not in paths:
                continue
            key = ('coincident-edge', name, edge)
            if key not in cache:
                arena.work(64)
                items = paths[name], paths[edge]
                values = tuple(q for n, t, w, d in items for q in (*n, *t, *w, d))
                proved = False
                with V._work(values, arena.resource):
                    n, a = items[0][0], items[1][0]
                    if any(n) and any(a):
                        pivot = next(i for i, q in enumerate(a) if q)
                        scale = n[pivot]/a[pivot]
                        if (scale and all(n[i] == scale*a[i] for i in range(3)) and
                                items[0][3] == scale*items[1][3]):
                            proved = any(all((t == theta and w == omega) or
                                (not any(O._cross(m, t)) and not any(O._cross(m, w)) and
                                 not any(O._cross(m, theta)) and not any(O._cross(m, omega)))
                                for m, t, w, _ in items) for _, theta, omega, _ in items)
                cache[key] = proved
            if cache[key]:
                inferred = unoriented & {name, edge}
                if inferred and (line_for is None or J is None or not all(
                        any(q[0][0] > 0 or q[0][1] < 0 for q in line_for(item)[:2])
                        for item in inferred)):
                    continue
                return True
        for first, second in combinations(sorted(active, key=repr), 2):
            if first not in paths or second not in paths:
                continue
            key = name, first, second
            if key not in cache:
                arena.work(128)
                items = (paths[name], paths[first], paths[second])
                values = tuple(q for n, t, w, d in items for q in (*n, *t, *w, d))
                proved = False
                with V._work(values, arena.resource):
                    for _, theta, omega, _ in items:
                        if not all((t == theta and w == omega) or
                            (not any(O._cross(n, t)) and not any(O._cross(n, w)) and
                             not any(O._cross(n, theta)) and not any(O._cross(n, omega)))
                            for n, t, w, _ in items):
                            continue
                        n, a, b = (item[0] for item in items)
                        for i, j in ((0, 1), (0, 2), (1, 2)):
                            determinant = a[i]*b[j]-a[j]*b[i]
                            if not determinant:
                                continue
                            alpha = (n[i]*b[j]-n[j]*b[i])/determinant
                            beta = (a[i]*n[j]-a[j]*n[i])/determinant
                            proved = (all(n[k] == alpha*a[k]+beta*b[k] for k in range(3)) and
                                      items[0][3] == alpha*items[1][3]+beta*items[2][3])
                            break
                        if proved:
                            break
                cache[key] = proved
            if cache[key]:
                inferred = unoriented & {name, first, second}
                if inferred:
                    if line_for is None or J is None:
                        continue
                    # The physical lines, not the surrogate unoriented plane,
                    # establish a unique vertex and exclude a zero/reversing
                    # normal throughout this particular closed time interval.
                    a, b = line_for(first), line_for(second)
                    det = J.sub(J.mul(a[0], b[1]), J.mul(a[1], b[0]))[0]
                    if not (det[0] > 0 or det[1] < 0):
                        continue
                    if not all(any(q[0][0] > 0 or q[0][1] < 0
                                   for q in line_for(item)[:2]) for item in inferred):
                        continue
                return True
        return False
    return contains


_FIXED_FACE_SECTION = ('fixed-face-ray-section',)


def _shared_ray_paths(record, face=None, arena=None):
    """Exact symbolic rays retained by edges, including frozen older edges.

    A shared ray normally requires two independent active face lines. If the
    ray itself lies in the fixed face, one nonzero retained face line suffices:
    both homogeneous cuts restrict to that same one-dimensional ray line.
    Ordered rotations remain distinct except for a proved stationary axis:
    every prior/current rotation must individually preserve the original ray.
    No approximate endpoint or cancellation of nonparallel turns is used.
    """
    from . import integration_differential_geometry as G
    def rays(constraint):
        if constraint['kind'] == 'moving-ray-edge':
            result = []
            for ray in constraint['rays']:
                direction = G._load_vec(ray['direction'])
                scale = next(q for q in direction if q)
                direction = tuple(q/scale for q in direction)
                history = tuple(tuple(q*dt for q in w) for w, dt in G._history(
                    ray.get('prior_rotations', ())) if dt and any(w))
                result.append((direction, history, G._load_vec(ray['angular_velocity_rad_s'])))
            return frozenset(result)
        if constraint['kind'] == 'snapshot-rotated':
            at = G.W._decode(constraint['snapshot_offset_s'])
            current = G._load_vec(constraint['angular_velocity_rad_s'])
            return frozenset((direction, history+((tuple(q*at for q in w),) if at and any(w) else ()), current)
                             for direction, history, w in rays(constraint['constraint']))
        return frozenset()
    def stationary(path):
        direction, history, omega = path
        values = (*direction, *(q for vector in (*history, omega) for q in vector))
        def proved():
            return all(not any(O._cross(direction, vector)) for vector in (*history, omega))
        if arena is None:
            constant = proved()
        else:
            arena.work(32*(len(history)+1))
            with V._work(values, arena.resource):
                constant = proved()
        return (direction, (), (Q(0),)*3) if constant else path
    result = {name: frozenset(stationary(path) for path in rays(constraint))
              for name, constraint in record['constraints'].items()}
    known = frozenset().union(*result.values())
    # A moving plane may contain a known ray without having been authored
    # from that ray. Preserve exact common rigid action: R*n dot R*r is
    # n dot r. Ordered ray rotations may be summed ONLY after proving all
    # retained actions commute; equal vector sums alone are not authority.
    for name, constraint in record['constraints'].items():
        if arena is not None:
            arena.work(64*(len(known)+1))
        plane = G._rigid_plane_path(constraint)
        if plane is None:
            continue
        normal, theta, omega = plane
        contained = []
        for ray in known:
            direction, history, velocity = ray
            if velocity != omega:
                continue
            values = (*normal, *theta, *omega, *direction,
                      *(q for vector in history for q in vector))
            def common_action():
                if O._dot(normal, direction) != 0:
                    return False
                vectors = (*history, theta, omega)
                axis = next((v for v in vectors if any(v)), (Q(0),)*3)
                if any(any(O._cross(axis, v)) for v in vectors):
                    return False
                return tuple(sum((v[j] for v in history), Q(0)) for j in range(3)) == theta
            if arena is None:
                proved = common_action()
            else:
                with V._work(values, arena.resource, pairs=4*(len(history)+1)):
                    proved = common_action()
            if proved:
                contained.append(ray)
        if contained:
            if arena is not None:
                arena.keep((), len(contained))
            result[name] = result.get(name, frozenset()) | frozenset(contained)
    rectangle_axes = set()
    fixed = {name: (G._load_vec(c['normal']), G.W._decode(c['offset']))
             for name, c in record['constraints'].items() if c['kind'] == 'fixed-plane'}
    if arena is not None and face is not None:
        # A declared moving edge may retain one exact unoriented plane even
        # though its authored rays move within it. Other known ray paths can
        # then be proved contained without claiming their histories identical.
        for name, constraint in record['constraints'].items():
            if name not in fixed:
                normal = _invariant_edge_plane(constraint, arena)
                if normal is not None:
                    fixed[name] = (normal, Q(0))
    if face is not None:
        fixed[_FIXED_FACE_SECTION] = (face[3], O._dot(face[3], face[0]))
        for axis in range(2):
            for end in range(2):
                normal = face[1+axis]
                fixed[('rectangle', axis, end)] = (normal, O._dot(normal, face[0])+face[4][axis][end])
                if (fixed[_FIXED_FACE_SECTION][1] == 0 and
                        fixed[('rectangle', axis, end)][1] == 0):
                    # The intersection of these TWO exact fixed planes is
                    # a complete stationary axis, not a rounded corner ray.
                    direction = O._cross(face[3], normal)
                    if any(direction):
                        scale = next(q for q in direction if q)
                        direction = tuple(q/scale for q in direction)
                        if arena is not None:
                            arena.keep(direction, 1)
                        rectangle_axes.add((direction, (), (Q(0),)*3))
    known = known | frozenset(rectangle_axes)
    if rectangle_axes:
        for name, constraint in record['constraints'].items():
            path = G._rigid_plane_path(constraint)
            if path is None:
                continue
            normal, theta, omega = path
            if arena is not None:
                arena.work(64*(len(rectangle_axes)+1))
            for ray in rectangle_axes:
                def contains_axis():
                    return O._dot(normal, ray[0]) == 0 and not any(O._cross(theta, ray[0])) and not any(O._cross(omega, ray[0]))
                if arena is None:
                    proved = contains_axis()
                else:
                    with V._work((*normal, *theta, *omega, *ray[0]), arena.resource):
                        proved = contains_axis()
                if proved:
                    result[name] = result.get(name, frozenset()) | {ray}
    for name, (normal, offset) in fixed.items():
        if offset != 0:
            continue
        # A through-origin invariant plane contains the complete ray path,
        # not just its initial sample. Every ordered rotation must preserve
        # that plane; nearby rays and nonparallel rotation axes do not qualify.
        if arena is not None:
            arena.work(64*(len(known)+1))
        contained = []
        for ray in known:
            values = (*normal, *ray[0], *(q for vector in (*ray[1], ray[2]) for q in vector))
            def includes():
                return O._dot(normal, ray[0]) == 0 and all(
                    not any(O._cross(normal, theta)) for theta in (*ray[1], ray[2]))
            if arena is None:
                proved = includes()
            else:
                with V._work(values, arena.resource):
                    proved = includes()
            if proved:
                contained.append(ray)
        result[name] = result.get(name, frozenset()) | frozenset(contained)
    return result


def _ray_incidence_proof(shared_rays, line_for, J, bounds=None):
    cache = {}
    def nonzero(line):
        return any(q[0][0] > 0 or q[0][1] < 0 or
            bounds is not None and _strict_interior_sign(q, bounds) is not None for q in line[:2])
    def contains(name, active):
        # The actual fixed face is an additional homogeneous plane, not an
        # arbitrary vertex tag. A common nonzero ray in this face and both
        # cuts establishes the SAME face line, provided neither restricted
        # normal vanishes in the open interval. A strictly monotone one-sign
        # coefficient can prove endpoint-only departure; the bounded analytic
        # vertex then retains this incidence at the endpoint by continuity.
        # Point-time queries have no such open-interval authority.
        for edge in sorted(active, key=repr):
            key = name, edge, _FIXED_FACE_SECTION
            if key not in cache:
                common = (shared_rays.get(name, frozenset()) & shared_rays.get(edge, frozenset()) &
                          shared_rays.get(_FIXED_FACE_SECTION, frozenset()))
                cache[key] = bool(common) and all(nonzero(line_for(item)) for item in (name, edge))
            if cache[key]:
                return True
        for first, second in combinations(sorted(active, key=repr), 2):
            key = name, first, second
            if key not in cache:
                common = (shared_rays.get(name, frozenset()) & shared_rays.get(first, frozenset()) &
                          shared_rays.get(second, frozenset()))
                proved = False
                if common:
                    a, b = line_for(first), line_for(second)
                    determinant = J.sub(J.mul(a[0], b[1]), J.mul(a[1], b[0]))[0]
                    proved = determinant[0] > 0 or determinant[1] < 0
                cache[key] = proved
            if cache[key]:
                return True
        return False
    return contains


def _start_plane_incidence(record, face, arena):
    """Endpoint-only coincidence from the same two authored ray paths.

    Snapshot rotations are appended in their actual order; noncommuting
    histories are never summed or reordered. Equal unordered ray pairs give
    the same homogeneous plane up to orientation at t=0, even when its pose
    is irrational and the subsequent angular velocities differ. A second
    active line must prove a unique face vertex at that endpoint. This says
    nothing about incidence or sign at positive time.
    """
    from . import integration_differential_geometry as G
    signatures, lines, cache = {}, {}, {}

    def rays_at(constraint, time):
        kind = constraint['kind']
        if kind == 'moving-ray-edge':
            result = []
            for ray in constraint['rays']:
                direction = G._load_vec(ray['direction'])
                history = (*G._history(ray.get('prior_rotations', ())),
                           (G._load_vec(ray['angular_velocity_rad_s']), time))
                values = (*direction, *(q for w, dt in history for q in (*w, dt)))
                arena.work(32*(len(history)+1))
                with V._work(values, arena.resource):
                    turns = tuple(tuple(q*dt for q in w) for w, dt in history if dt and any(w))
                    arena.keep((*direction, *(q for w in turns for q in w)), len(turns)+2)
                result.append((direction, turns))
            return tuple(result)
        if kind == 'snapshot-rotated':
            result = rays_at(constraint['constraint'], G.W._decode(constraint['snapshot_offset_s']))
            if result is None:
                return None
            omega = G._load_vec(constraint['angular_velocity_rad_s'])
            if time and any(omega):
                arena.work(32)
                with V._work((*omega, time), arena.resource):
                    turn = tuple(q*time for q in omega)
                    arena.keep(turn, 2*len(result)+1)
                result = tuple((direction, history+(turn,)) for direction, history in result)
            return result
        return None

    def signature(name):
        if name not in signatures:
            rays = rays_at(record['constraints'][name], Q(0)) if name in record['constraints'] else None
            pair = None if rays is None else frozenset(rays)
            # Keep the exact authored pair; do not infer a second ray from
            # one common path, nearby directions, or matching rotation sums.
            signatures[name] = pair if pair is not None and len(pair) == 2 else None
            arena.keep((), 3)
        return signatures[name]

    def line(name):
        if name not in lines:
            if isinstance(name, tuple) and len(name) == 3 and name[0] == 'rectangle':
                result = tuple((Q(axis == name[1]),)*2 for axis in range(2))
            elif name in record['constraints']:
                normal, _ = G._constraint_boxes(record['constraints'][name], Q(0), Q(0), POSE_LEVEL, arena)
                with V._work(tuple(q for pair in normal for q in pair)+tuple(q for p in face[1:3] for q in p),
                             arena.resource):
                    result = tuple(G._dot_bounds(normal, tuple((q, q) for q in tangent))
                                   for tangent in face[1:3])
            else:
                result = None
            arena.keep(() if result is None else tuple(q for pair in result for q in pair), 1)
            lines[name] = result
        return lines[name]

    def contains(name, active):
        key = name, active
        if key in cache:
            return cache[key]
        pair, proved = signature(name), False
        if pair is not None:
            for edge in sorted(active, key=repr):
                if signature(edge) != pair:
                    continue
                a = line(edge)
                for other in sorted(active-{edge}, key=repr):
                    b = line(other)
                    if a is None or b is None:
                        continue
                    arena.work(64)
                    with V._work(tuple(q for row in (*a, *b) for q in row), arena.resource):
                        first, second = G._product(a[0], b[1]), G._product(a[1], b[0])
                        determinant = first[0]-second[1], first[1]-second[0]
                        proved = determinant[0] > 0 or determinant[1] < 0
                    if proved:
                        break
                if proved:
                    break
        arena.keep((), len(active)+2)
        cache[key] = proved
        return proved
    return contains


def _exact_start_predicates(record, face, arena):
    """Exact endpoint values on analytic vertices, never sampled zero tests."""
    from . import integration_differential_geometry as G
    lines, cache, jet_lines, jet_cache = {}, {}, {}, {}
    E = _Jets(_RationalIntervals())
    start_incidence = _start_plane_incidence(record, face, arena)
    for axis in range(2):
        for end in range(2):
            lines[('rectangle', axis, end)] = (Q(axis == 0), Q(axis == 1), -face[4][axis][end])
    def line(name):
        if name not in lines:
            if name not in record['constraints']:
                return None
            normal, offset = G._constraint_boxes(record['constraints'][name], Q(0), Q(0), POSE_LEVEL, arena)
            if any(lo != hi for lo, hi in normal):
                lines[name] = None
            else:
                n = tuple(lo for lo, _ in normal)
                lines[name] = (O._dot(n, face[1]), O._dot(n, face[2]), O._dot(n, face[0])-offset)
        return lines[name]
    def jet_line(name):
        if name not in jet_lines:
            plain = line(name)
            if plain is None:
                jet_lines[name] = None
            elif isinstance(name, tuple):
                jet_lines[name] = tuple(E.constant(q) for q in plain)
            else:
                normal, offset = _normal(record['constraints'][name], (Q(0), Q(0)), E, arena)
                exact = _line(normal, offset, face, 1, E)
                jet_lines[name] = exact if all(lo == hi for c in exact for lo, hi in c) else None
        return jet_lines[name]
    def value(name, active, *, derivatives=False):
        key = name, active
        if derivatives:
            if key in jet_cache:
                return jet_cache[key]
            result, new = None, jet_line(name)
            if new is not None:
                for first, second in combinations(sorted(active, key=repr), 2):
                    a, b = jet_line(first), jet_line(second)
                    if a is None or b is None:
                        continue
                    arena.work(128*(ORDER+1)**2)
                    determinant = E.sub(E.mul(a[0], b[1]), E.mul(a[1], b[0]))
                    if determinant[0] == E.zero:
                        continue
                    with V._work(tuple(q for c in (*a, *b, *new) for pair in c for q in pair), arena.resource):
                        u = E.div(E.sub(E.mul(a[1], b[2]), E.mul(a[2], b[1])), determinant)
                        v = E.div(E.sub(E.mul(a[2], b[0]), E.mul(a[0], b[2])), determinant)
                        evaluated = E.add(E.add(E.mul(new[0], u), E.mul(new[1], v)), new[2])
                        if all(lo == hi for lo, hi in evaluated):
                            result = tuple(lo for lo, _ in evaluated)
                    break
            jet_cache[key] = result
            return result
        if key in cache:
            return cache[key]
        new = line(name)
        result = None
        if new is None and start_incidence(name, active):
            cache[key] = Q(0)
            return Q(0)
        if new is not None:
            for first, second in combinations(sorted(active, key=repr), 2):
                a, b = line(first), line(second)
                if a is None or b is None:
                    continue
                arena.work(128)
                with V._work((*a, *b, *new), arena.resource):
                    determinant = a[0]*b[1]-a[1]*b[0]
                    if not determinant:
                        continue
                    u = (a[1]*b[2]-a[2]*b[1])/determinant
                    v = (a[2]*b[0]-a[0]*b[2])/determinant
                    result = new[0]*u+new[1]*v+new[2]
                    break
        cache[key] = result
        return result
    return value


class _RationalIntervals:
    """Exact endpoint coefficient algebra, only used for a proved exact pose."""
    def point(self, q):
        value = Q(q)
        return value, value
    def add(self, a, b):
        if (a[0] == a[1] and b[0] == b[1] and
                type(a[0]) is type(a[1]) is type(b[0]) is type(b[1]) is Q):
            value = a[0]+b[0]
            return value, value
        return a[0]+b[0], a[1]+b[1]
    def neg(self, a):
        if a[0] == a[1] and type(a[0]) is type(a[1]) is Q:
            value = -a[0]
            return value, value
        return -a[1], -a[0]
    def sub(self, a, b):
        return self.add(a, self.neg(b))
    def mul(self, a, b):
        if (a[0] == a[1] and b[0] == b[1] and
                type(a[0]) is type(a[1]) is type(b[0]) is type(b[1]) is Q):
            value = a[0]*b[0]
            return value, value
        values = tuple(x*y for x in a for y in b)
        return min(values), max(values)
    def div(self, a, b):
        if b[0] <= 0 <= b[1]:
            raise _Branch()
        # Mixed numeric endpoints can compare equal while their reciprocal
        # arithmetic differs. Only actual Fraction endpoints use this path.
        if (a[0] == a[1] and b[0] == b[1] and
                type(a[0]) is type(a[1]) is type(b[0]) is type(b[1]) is Q):
            value = a[0]/b[0]
            return value, value
        return self.mul(a, (1/b[1], 1/b[0]))


def _multiply(a, b, J):
    out = {}
    for (i, j), x in a.items():
        for (k, l), y in b.items():
            key = i+k, j+l
            out[key] = J.add(out.get(key, J.z), J.mul(x, y))
    return out


def _moment(poly, polynomial, J):
    if len(poly) < 3 or not polynomial:
        return J.z
    result, a = J.z, poly[0]
    for b, c in zip(poly[1:-1], poly[2:]):
        bu, bv = J.sub(b[0], a[0]), J.sub(b[1], a[1])
        cu, cv = J.sub(c[0], a[0]), J.sub(c[1], a[1])
        determinant = J.sub(J.mul(bu, cv), J.mul(bv, cu))
        up = {(0, 0): a[0], (1, 0): bu, (0, 1): cu}
        vp = {(0, 0): a[1], (1, 0): bv, (0, 1): cv}
        powers_u, powers_v = [{(0, 0): J.constant(1)}], [{(0, 0): J.constant(1)}]
        for _ in range(max(i for i, _ in polynomial)):
            powers_u.append(_multiply(powers_u[-1], up, J))
        for _ in range(max(j for _, j in polynomial)):
            powers_v.append(_multiply(powers_v[-1], vp, J))
        value = J.z
        for (i, j), coefficient in polynomial.items():
            for (k, l), term in _multiply(powers_u[i], powers_v[j], J).items():
                weight = coefficient*Q(factorial(k)*factorial(l), factorial(k+l+2))
                value = J.add(value, J.scale(term, weight))
        result = J.add(result, J.mul(determinant, value))
    return result


def _moments(poly, polynomials, J):
    """Same operation order per result, shared one-triangle power tables."""
    results = [J.z for _ in polynomials]
    if len(poly) < 3 or not polynomials:
        return tuple(results)
    keys = set().union(*(p.keys() for p in polynomials))
    if not keys:
        return tuple(results)
    a = poly[0]
    for b, c in zip(poly[1:-1], poly[2:]):
        bu, bv = J.sub(b[0], a[0]), J.sub(b[1], a[1])
        cu, cv = J.sub(c[0], a[0]), J.sub(c[1], a[1])
        determinant = J.sub(J.mul(bu, cv), J.mul(bv, cu))
        up = {(0, 0): a[0], (1, 0): bu, (0, 1): cu}
        vp = {(0, 0): a[1], (1, 0): bv, (0, 1): cv}
        powers_u, powers_v = [{(0, 0): J.constant(1)}], [{(0, 0): J.constant(1)}]
        for _ in range(max(i for i, _ in keys)):
            powers_u.append(_multiply(powers_u[-1], up, J))
        for _ in range(max(j for _, j in keys)):
            powers_v.append(_multiply(powers_v[-1], vp, J))
        products = {key: _multiply(powers_u[key[0]], powers_v[key[1]], J) for key in keys}
        for index, polynomial in enumerate(polynomials):
            value = J.z
            for key, coefficient in polynomial.items():
                for (k, l), term in products[key].items():
                    weight = coefficient*Q(factorial(k)*factorial(l), factorial(k+l+2))
                    value = J.add(value, J.scale(term, weight))
            results[index] = J.add(results[index], J.mul(determinant, value))
    return tuple(results)


def _face_in_layer(face, layer):
    # CartesianCell supplies exact orthonormal tangents and normal. The fixed
    # face's nearest point can lie in its interior, not necessarily a vertex.
    centre = O._dot(face[0], face[3])**2
    low = high = centre
    for tangent, (a, b) in zip(face[1:3], face[4]):
        shift = O._dot(face[0], tangent)
        a, b = a+shift, b+shift
        low += 0 if a <= 0 <= b else min(a*a, b*b)
        high += max(a*a, b*b)
    return low >= layer.bottom_radius_m**2 and high <= layer.top_radius_m**2


def _finite_cone_inside_inner_ball(generators, face, inner2, arena):
    """Bound a cone truncated by a coordinate cap of the actual rectangle.

    The caller supplies certified whole-time positive cone generators. If
    every generator has strictly positive projection onto one signed Cartesian
    axis, the capped cone is the convex hull of the origin and the generators
    scaled to that cap. Its radius is bounded by those vertices. The rectangle
    cap is evaluated in the physical frame, including origin and tangents.
    """
    from . import integration_differential_geometry as G
    arena.work(128)
    with V._work((inner2, *(q for generator in generators for pair in generator for q in pair),
                  *(q for vector in face[:3] for q in vector),
                  *(q for pair in face[4] for q in pair)), arena.resource):
        if inner2 <= 0:
            return False
        for axis in range(3):
            sign = (1 if all(g[axis][0] > 0 for g in generators) else
                    -1 if all(g[axis][1] < 0 for g in generators) else 0)
            if not sign:
                continue
            cap = sign*face[0][axis]+sum(max(sign*tangent[axis]*a, sign*tangent[axis]*b)
                for tangent, (a, b) in zip(face[1:3], face[4]))
            if cap <= 0:
                # A negative cap is disjoint; a zero cap retains only origin,
                # which the positive inner radius excludes exactly.
                return True
            proved = True
            for generator in generators:
                lo, hi = generator[axis] if sign > 0 else tuple(-q for q in reversed(generator[axis]))
                vertex = tuple(G._product(coordinate, (cap/hi, cap/lo)) for coordinate in generator)
                if sum(max(a*a, b*b) for a, b in vertex) >= inner2:
                    proved = False
                    break
            if proved:
                return True
    return False


def _variable_cone_inside_inner_ball(record, component, face, layer, duration, arena):
    """Whole-time inverse-column certificate for actual variable halfspaces.

    N(t)x>=0 gives x=N(t)^-1*q, q>=0, whether or not its rows share a
    rigid pose. A nonzero determinant and strict same-side wall projections
    certify a compact triangular section. Alternatively an actual finite-face
    coordinate cap bounds a truncated cone. Interval vertex radii bound the
    complete convex hull. Midpoints select one candidate triple only; they
    supply no geometric predicate or motion approximation.
    """
    from . import integration_differential_geometry as G
    inner2 = layer.bottom_radius_m**2
    offset = O._dot(face[0], face[3])
    if inner2 <= 0 or not offset:
        return False
    arena.work(256+128*len(component['constraints']))
    basis, representatives = [], []
    for name, sign in component['constraints']:
        normal, distance = G._constraint_boxes(record['constraints'][name], Q(0), duration, POSE_LEVEL, arena)
        if distance != 0:
            continue
        normal = tuple(pair if sign > 0 else (-pair[1], -pair[0]) for pair in normal)
        with V._work(tuple(q for pair in normal for q in pair)+
                     tuple(q for row in representatives for q in row), arena.resource):
            middle = tuple((lo+hi)/2 for lo, hi in normal)
            independent = (any(middle) if not basis else
                any(O._cross(representatives[0], middle)) if len(basis) == 1 else
                O._dot(representatives[0], O._cross(representatives[1], middle)) != 0)
            if independent:
                arena.keep((*tuple(q for pair in normal for q in pair), *middle), 1)
                basis.append(normal); representatives.append(middle)
        if len(basis) == 3:
            break
    if len(basis) != 3:
        return False
    with V._work((offset, inner2, *(q for row in basis for pair in row for q in pair)), arena.resource):
        determinant = G._dot_bounds(basis[0], G._cross_bounds(basis[1], basis[2]))
        if determinant[0] <= 0 <= determinant[1]:
            return False
        orientation = 1 if determinant[0] > 0 else -1
        generators = []
        for j in range(3):
            generator = G._cross_bounds(basis[(j+1) % 3], basis[(j+2) % 3])
            if orientation < 0:
                generator = tuple((-hi, -lo) for lo, hi in generator)
            generators.append(generator)
        proved = True
        for generator in generators:
            denominator = G._dot_bounds(tuple((q, q) for q in face[3]), generator)
            if not (denominator[0] > 0 if offset > 0 else denominator[1] < 0):
                proved = False
                break
            scale = tuple(sorted((offset/denominator[0], offset/denominator[1])))
            vertices = tuple(G._product(coordinate, scale) for coordinate in generator)
            if sum(max(a*a, b*b) for a, b in vertices) >= inner2:
                proved = False
                break
        if proved:
            return True
        return _finite_cone_inside_inner_ball(generators, face, inner2, arena)


def _cone_inside_inner_ball(record, component, face, layer, duration, arena):
    """Prove an entire angular-cone section misses the actual radial shell.

    Three independent homogeneous halfspaces with one exact rigid pose give
    x=R*N^-1*q, q>=0. Equal strict signs of n_wall.R*N^-1 columns make the
    fixed-plane section the convex hull of their scaled intersections. The
    convex squared norm is bounded by its vertex values. Extra component
    constraints and the finite face rectangle can only shrink this section.
    One deterministic independent triple per pose is tried, not all triples.
    """
    from . import integration_differential_geometry as G
    inner2 = layer.bottom_radius_m**2
    offset = O._dot(face[0], face[3])
    if inner2 <= 0 or not offset:
        return False
    arena.work(256+128*len(component['constraints']))
    groups = {}
    for name, sign in component['constraints']:
        path = G._rigid_plane_path(record['constraints'][name])
        if path is None:
            continue
        normal, theta, omega = path
        normal = tuple(sign*q for q in normal)
        basis = groups.setdefault((theta, omega), [])
        if len(basis) == 3:
            continue
        with V._work((*normal, *(q for row in basis for q in row)), arena.resource):
            independent = (not basis or (any(O._cross(basis[0], normal)) if len(basis) == 1
                else O._dot(basis[0], O._cross(basis[1], normal)) != 0))
            if independent:
                arena.keep(tuple(normal), 1)
                basis.append(normal)
    for (theta, omega), basis in groups.items():
        if len(basis) != 3:
            continue
        arena.work(256)
        with V._work((duration, offset, inner2, *theta, *omega,
                      *(q for row in basis for q in row)), arena.resource):
            determinant = O._dot(basis[0], O._cross(basis[1], basis[2]))
            orientation = 1 if determinant > 0 else -1
            generators = tuple(tuple(orientation*q for q in O._cross(basis[(j+1) % 3],
                basis[(j+2) % 3])) for j in range(3))
        proved = True
        for generator in generators:
            posed = tuple((q, q) for q in generator)
            if any(theta):
                posed = G._rotation_boxes(posed, theta, Q(1), Q(1), POSE_LEVEL, arena)
            posed = G._rotation_boxes(posed, omega, Q(0), duration, POSE_LEVEL, arena)
            with V._work((offset, inner2, *(q for pair in posed for q in pair)), arena.resource):
                denominator = G._dot_bounds(tuple((q, q) for q in face[3]), posed)
                if not (denominator[0] > 0 if offset > 0 else denominator[1] < 0):
                    proved = False
                    break
                scale = tuple(sorted((offset/denominator[0], offset/denominator[1])))
                vertices = tuple(G._product(coordinate, scale) for coordinate in posed)
                if sum(max(a*a, b*b) for a, b in vertices) >= inner2:
                    proved = False
                    break
        if proved:
            return True
    return _variable_cone_inside_inner_ball(record, component, face, layer, duration, arena)


def integrate(record, component, layer, face, omega, polynomials, widths, duration,
              *, fallback, max_leaves, arena, moments_only=False, passive=()):
    """Return certified bounds/count/met, or None for unsupported radial moments.

    The original geometric leaf remains an independent enclosure. Taylor
    results are intersected with it; a disagreement refuses. Unresolved
    branch intervals spend the SAME caller-provided leaf allowance.
    With moments_only=True the returned quantities are only the requested
    scalar moments, and omega must be None: no unrelated rigid stream is
    evaluated or represented. The complete radial-face premise still applies.
    ``passive`` indexes returned quantities that ride on the leaves the
    others select: they neither keep an otherwise exact leaf from its
    geometric enclosure nor rank a leaf for bisection. They are enclosed on
    every leaf and summed into the totals, and their widths are tested like
    the others.
    """
    from . import integration_wall_measures as W
    if type(moments_only) is not bool or moments_only and omega is not None:
        raise V.VolumeError('moments-only integration has no velocity field')
    if any(type(index) is not int or not 0 <= index < len(widths) for index in passive):
        raise V.VolumeError('passive moments must index the returned quantities')
    if _cone_inside_inner_ball(record, component, face, layer, duration, arena):
        return ((Q(0), Q(0)),)*len(widths), 1, True
    radial_cut = not _face_in_layer(face, layer)
    if radial_cut and (polynomials or moments_only):
        return None
    shift = tuple(O._dot(face[0], tangent) for tangent in face[1:3])
    distance_squared = O._dot(face[0], face[3])**2
    disk_radii_squared = (layer.top_radius_m**2-distance_squared,
                          layer.bottom_radius_m**2-distance_squared)
    J = _Jets()
    incidence = None
    shared_rays = None
    start_predicate = None
    shared_rotation = None
    fixed_corner = None
    signs = dict(component['constraints'])
    velocity = None if moments_only else tuple(O._dot(face[3], O._cross(omega, p)) for p in (face[1], face[2], face[0]))
    velocity_normal = None if moments_only else O._cross(face[3], omega)
    proof_record = {'constraints': {name: record['constraints'][name] for name in signs}}
    for sign in (() if moments_only else (-1, 1)):
        name = 'velocity-sign:'+str(sign)
        signs[name] = sign
        proof_record['constraints'][name] = dict(kind='fixed-plane',
            normal=list(map(V._encoded, velocity_normal)), offset=V._encoded(Q(0)))
    origin_proof = _homogeneous_origin_proof(proof_record, face, arena)
    if radial_cut and velocity[2] != sum(velocity[j]*shift[j] for j in range(2)):
        raise V.VolumeError('rigid radial-face velocity has a nonzero disk-centre value')
    def evaluate(bounds, reference, radius=None, event_hint=None):
        lines, open_signs = {}, {}
        def line_for(name):
            if name not in lines:
                if isinstance(name, tuple) and len(name) == 3 and name[0] == 'rectangle':
                    _, axis, end = name
                    lines[name] = tuple(J.constant(q) for q in
                        (int(axis == 0), int(axis == 1), -face[4][axis][end]))
                else:
                    normal, offset = _normal(proof_record['constraints'][name], bounds, J, arena)
                    lines[name] = _line(normal, offset, face, 1, J)
            return lines[name]
        def intersection(line, active, identity):
            from .integration_rigid_intersection import intersect
            return _active_intersection(line, active, line_for, J,
                (lambda: intersect(proof_record['constraints'][identity], active, face, bounds, J, arena))
                if identity in proof_record['constraints'] else None)
        ray_contains = _ray_incidence_proof(shared_rays, line_for, J, bounds)
        origin_crossing = _origin_crossing(origin_proof, line_for, J, arena, bounds)
        def contains(name, active):
            if origin_proof is not None and _PHYSICAL_ORIGIN in active and name in origin_proof[1]:
                return True
            if name in ('velocity-sign:-1', 'velocity-sign:1'):
                if not any(velocity):
                    return True
                # A fixed velocity zero line can be one retained rectangle
                # edge; no second moving edge or rounded cancellation needed.
                for axis in range(2):
                    if velocity[1-axis] == 0:
                        for end in range(2):
                            if (('rectangle', axis, end) in active and
                                    velocity[axis]*face[4][axis][end]+velocity[2] == 0):
                                return True
            return incidence(name, active, line_for, J) or ray_contains(name, active)
        def guard(identity, index, count, value, active):
            key = identity, index, count
            if value[0][0] < 0 <= value[0][1] and identity in signs:
                correlated = fixed_corner(identity, active, J)
                if correlated is None:
                    correlated = shared_rotation(identity, active, bounds, J)
                if correlated is not None:
                    correlated = J.scale(correlated, signs[identity])
                    pairs = tuple((max(a[0], b[0]), min(a[1], b[1]))
                                  for a, b in zip(value, correlated))
                    if any(lo > hi for lo, hi in pairs):
                        raise V.VolumeError('correlated geometric predicate contradicts direct interval')
                    value = pairs
            if radius is None:
                reference[key] = value[0]
                return value
            if key not in reference:
                raise _Branch()
            # Earlier clipping predicates have certified the same analytic
            # vertex construction. Mean-value form retains cancellations that
            # separate coordinate intervals cannot: f(t) in f(m)+(t-m)f'(I).
            centred = J.I.add(reference[key], J.I.mul(
                (J.I.point(-radius)[0], J.I.point(radius)[1]), value[1]))
            pair = max(value[0][0], centred[0]), min(value[0][1], centred[1])
            if bounds[0] == 0 and identity in signs:
                at_start = start_predicate(identity, active)
                if at_start is not None:
                    one_sided = J.I.add(J.I.point(signs[identity]*at_start),
                        J.I.mul((J.I.point(0)[0], J.I.point(bounds[1])[1]), value[1]))
                    pair = max(pair[0], one_sided[0]), min(pair[1], one_sided[1])
                    if at_start == 0 and pair[0] < 0 <= pair[1]:
                        if value[1][1] < 0:
                            open_signs[key] = False
                        else:
                            coefficients = start_predicate(identity, active, derivatives=True)
                            if coefficients is not None:
                                signed = tuple(signs[identity]*q for q in coefficients)
                                departure, open_sign = _endpoint_departure(signed, value, bounds[1], J)
                                if departure is not None:
                                    pair = max(pair[0], departure[0]), min(pair[1], departure[1])
                                if open_sign is not None:
                                    open_signs[key] = open_sign
            if pair[0] > pair[1]:
                raise V.VolumeError('moving-plane mean-value enclosure contradicts direct interval')
            strict_sign = _strict_interior_sign((pair, *value[1:]), bounds)
            if strict_sign is not None:
                if key in open_signs and open_signs[key] is not strict_sign:
                    raise V.VolumeError('moving-plane interior sign contradicts endpoint proof')
                open_signs[key] = strict_sign
            if (event_hint is not None and pair[0] < 0 <= pair[1]
                    and key not in open_signs):
                event_hint[0] = _time_event_split(bounds, reference[key], value[1], arena)
            return (pair, *value[1:])
        polygon = tuple((J.constant(u), J.constant(v), frozenset(
            ('rectangle', axis, end) for axis, coordinate in enumerate((u, v))
            for end in range(2) if coordinate == face[4][axis][end])) for u, v in W._rectangle(face[4]))
        if origin_proof is not None:
            polygon = tuple((*point[:2], point[2] | {_PHYSICAL_ORIGIN})
                if (u, v) == origin_proof[0] else point
                for point, (u, v) in zip(polygon, W._rectangle(face[4])))
        for name, sign in component['constraints']:
            line = tuple(J.scale(q, sign) for q in line_for(name))
            polygon = _clip(polygon, line, name, J, contains, guard,
                            lambda identity, index, count: open_signs.get((identity, index, count)),
                            lambda cut, active: intersection(cut, active, name),
                            origin_crossing=origin_crossing)
            if not polygon:
                return (J.z,)*((0 if moments_only else 2)+len(polynomials))
        result = []
        for sign in (() if moments_only else (-1, 1)):
            line = tuple(J.constant(sign*q) for q in velocity)
            clipped = _clip(polygon, line, 'velocity-sign:'+str(sign), J, contains, guard,
                lambda identity, index, count: open_signs.get((identity, index, count)),
                lambda cut, active: intersection(cut, active, 'velocity-sign:'+str(sign)),
                origin_crossing=origin_crossing)
            if radial_cut:
                from . import integration_circular_moments as C
                centred = tuple((J.add(point[0], J.constant(shift[0])),
                                  J.add(point[1], J.constant(shift[1])), point[2]) for point in clipped)
                with V._work((*shift,*(q for pair in face[4] for q in pair)),arena.resource,pairs=4):
                    fixed_axes=tuple(tuple(q+shift[axis] for q in pair) for axis,pair in enumerate(face[4]))
                    outer = C.first_moments(centred, disk_radii_squared[0], J, arena,
                        fixed_axis_coordinates=fixed_axes)
                    inner = C.first_moments(centred, disk_radii_squared[1], J, arena,
                        fixed_axis_coordinates=fixed_axes)
                result.append(J.add(*(J.scale(J.sub(outer[j], inner[j]), sign*velocity[j])
                                      for j in range(2))))
            else:
                poly = {(1, 0): sign*velocity[0], (0, 1): sign*velocity[1], (0, 0): sign*velocity[2]}
                result.append(_moment(clipped, {k: q for k, q in poly.items() if q}, J))
        return (*result, *_moments(polygon, polynomials, J))
    def leaf(a, b, level):
        original = fallback(face[4], a, b, level)
        # An independent exact enclosure cannot be narrowed. In particular,
        # empty and fully covered stationary faces need no Taylor evaluation.
        # A passive quantity keeps its geometric enclosure on such a leaf.
        if all(lo == hi for index, (lo, hi) in enumerate(original) if index not in passive):
            return original, None
        arena.work(32*(ORDER+1)**2*(planes+4))
        event_hint = [None]
        try:
            middle, radius = (a+b)/2, (b-a)/2
            reference = {}
            coefficients = evaluate((middle, middle), reference)
            derivatives = evaluate((a, b), reference, radius, event_hint)
            out = []
            for old, derivative, coefficient in zip(original, derivatives, coefficients):
                value = J.zero
                for k in range(0, ORDER, 2):
                    value = J.I.add(value, J.I.mul(coefficient[k], J.I.point(2*radius**(k+1)/Q(k+1))))
                value = J.I.add(value, J.I.mul(derivative[ORDER], J.I.point(2*radius**(ORDER+1)/Q(ORDER+1))))
                pair = max(old[0], Q(value[0])), min(old[1], Q(value[1]))
                if pair[0] > pair[1]:
                    raise V.VolumeError('moving-face Taylor integral contradicts geometric enclosure')
                out.append(pair)
            return tuple(out), None
        except _Branch:
            return original, event_hint[0]
    # At most(nplanes+4) polygon vertices, two jet-evaluation passes and
    # polynomial powers through degree8. Decimal interval objects are bounded
    # by80-digit contexts; coefficient arithmetic and original geometry share
    # the caller's arena. No persistent per-query cache is retained.
    planes = len(proof_record['constraints'])
    keys = set().union(*(p.keys() for p in polynomials)) if polynomials else set()
    coefficient_count = sum((i+j+1)*(i+j+2)//2 for i, j in keys)
    if keys:
        coefficient_count += sum((n+1)*(n+2)//2 for n in range(max(i for i, _ in keys)+1))
        coefficient_count += sum((n+1)*(n+2)//2 for n in range(max(j for _, j in keys)+1))
    scratch = 131072+(4096*(planes+8)+256*coefficient_count)*(ORDER+1)+128*(planes+4)**3
    with arena.resource.reserve(scratch, category='moving-face-Taylor-scratch'):
        arena.work(128+64*(planes+4)**2)
        incidence = _incidence_proof(proof_record, face, arena)
        shared_rays = _shared_ray_paths(proof_record, face, arena)
        start_predicate = _exact_start_predicates(proof_record, face, arena)
        shared_rotation = _shared_rotation_predicate(proof_record, face, arena)
        fixed_corner = _fixed_corner_predicate(proof_record, face, arena)
        first, first_split = leaf(Q(0), duration, 0)
        totals = [list(pair) for pair in first]
        queue, serial, leaves = [], 0, 1
        def push(a, b, level, values, split):
            nonlocal serial
            error = max((hi-lo for index, (lo, hi) in enumerate(values) if index not in passive), default=Q(0))
            if error:
                serial += 1
                heapq.heappush(queue, (-error, serial, a, b, level, values, split))
        push(Q(0), duration, 0, first, first_split)
        while queue and any(hi-lo > width for (lo, hi), width in zip(totals, widths)) and leaves < max_leaves:
            _, _, a, b, level, old, split = heapq.heappop(queue)
            middle = (a+b)/2 if split is None else split
            children = []
            for ca, cb in ((a, middle), (middle, b)):
                values, next_split = leaf(ca, cb, level+1); children.append(values)
                push(ca, cb, level+1, values, next_split)
            for i in range(len(widths)):
                for j in range(2):
                    totals[i][j] += sum(values[i][j] for values in children)-old[i][j]
            leaves += 1
        return tuple(tuple(pair) for pair in totals), leaves, all(hi-lo <= w for (lo, hi), w in zip(totals, widths))
