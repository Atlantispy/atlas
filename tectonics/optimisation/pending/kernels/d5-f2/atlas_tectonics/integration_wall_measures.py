"""Certified space--time rigid-material flux through fixed Cartesian walls.

The represented trajectory is exp(t*skew(omega)), not endpoint interpolation.
Rational Taylor remainder bounds enclose its rotating halfspaces. Exact polygon
integration encloses the positive and negative linear normal flux separately.
No stock, heat, field reconstruction, native velocity or clock is changed here.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import dataclass, field
from fractions import Fraction as Q
import hashlib
import heapq
import json
import math
import weakref

from . import integration_volume as V
from . import integration_volume_overlap as O
from . import integration_volume_bounds as B
from . import integration_collar_geometry as G
from .resources import WorkBudget, select_budget


METHOD = 'exact-rational-enclosed-rigid-space-time-wall-v1'


def _hash(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _q(value):
    if type(value) not in (int, float, Q) or type(value) is float and not math.isfinite(value):
        raise V.VolumeError('finite explicit real scalar required')
    return Q(value)


def _decode(pair):
    return Q(int(pair[0], 16), int(pair[1], 16))


def _quantum(width, max_leaves):
    """Outward precision allocation: total added width <= requested width/2."""
    if not width:
        return Q(0)
    target = width/(4*max_leaves)
    exponent = target.numerator.bit_length()-target.denominator.bit_length()
    value = Q(2**exponent) if exponent >= 0 else Q(1, 2**(-exponent))
    return value/2 if value > target else value


def _outward(pair, quantum):
    if not quantum:
        return pair
    a, b = (q/quantum for q in pair)
    return Q(a.numerator//a.denominator)*quantum, Q(-((-b.numerator)//b.denominator))*quantum


def _rotated_normal(normal, omega, t0, t1, level, arena):
    """Midpoint vector and componentwise rigorous common error radius.

    Taylor's matrix tail is bounded in the induced infinity norm by the first
    omitted majorant term divided by 1-x/(N+2). For the time interval itself,
    |d(R n)/dt|_2=|omega cross n|_2 <= its L1 norm. This bound uses exact
    orthogonality of the MATHEMATICAL exponential, not a rounded pose matrix.
    Increasing arithmetic precision is an algorithm policy, never acceptance.
    """
    twin = _D5.rotated_normal(normal, omega, t0, t1, level, arena)
    if twin is not _D5.DECLINED:
        return twin
    middle, half = (t0+t1)/2, (t1-t0)/2
    derivative = O._cross(omega, normal)
    if not any(derivative):
        return normal, Q(0)
    norm_a = max(abs(omega[1])+abs(omega[2]), abs(omega[0])+abs(omega[2]),
                 abs(omega[0])+abs(omega[1]))
    norm_n = max(map(abs, normal))
    x = abs(middle)*norm_a
    target = norm_n/Q(2**(32+2*level))
    total, term, major, order = list(normal), normal, norm_n, 0
    exact_scale = (type(middle) is Q and type(normal) is tuple and len(normal) == 3
                   and type(omega) is tuple and len(omega) == 3
                   and all(type(q) in (int, Q) for q in (*normal, *omega)))
    while True:
        next_major = major*x/(order+1)
        ratio = x/(order+2)
        if ratio < 1 and next_major/(1-ratio) <= target:
            tail = next_major/(1-ratio)
            break
        arena.work(64)
        with V._work((*term, *omega, middle, major), arena.resource):
            if exact_scale:
                scale = None
                try:
                    scale = middle/(order+1)
                    term = tuple(scale*v for v in O._cross(omega, term))
                finally:
                    scale = None
            else:
                term = tuple(middle*v/(order+1) for v in O._cross(omega, term))
            total = [a+b for a, b in zip(total, term)]
            major = next_major
        order += 1
    # 3*tail bounds the Euclidean norm of three componentwise Taylor tails.
    # Rotation preserves that norm, so composition ADDS errors rather than
    # repeatedly inflating a component box under every accepted rotation.
    return tuple(total), 3*tail+half*sum(map(abs, derivative))


def _pose_vector(vector, omega, t0, t1, level, arena, prior=(), *, inverse=False):
    steps = tuple((w, duration, duration) for w, duration in prior)+((omega, t0, t1),)
    if inverse:
        steps = tuple((tuple(-q for q in w), a, b) for w, a, b in reversed(steps))
    error = Q(0)
    for w, a, b in steps:
        # Prior segments are endpoint rotations; only the current segment's
        # interval is time-dependent, even when applying the inverse product.
        vector, delta = _rotated_normal(vector, w, a, b, level, arena)
        error += delta
    return vector, error


def _clip2(poly, line, arena=None):
    """Counterclockwise convex polygon clipped by a*u+b*v+c >= 0."""
    twin = _D5.clip2(poly, line, arena)
    if twin is not _D5.DECLINED:
        return twin
    if arena is not None:
        with V._work((*line, *(q for p in poly for q in p)), arena.resource):
            return _clip2(poly, line)
    if not poly:
        return ()
    a, b, c = line
    signs = tuple(a*p[0]+b*p[1]+c for p in poly)
    if min(signs) >= 0:
        return poly
    if max(signs) <= 0:
        return ()
    out = []
    for p, q, sp, sq in zip(poly, poly[1:]+poly[:1], signs, signs[1:]+signs[:1]):
        if sp >= 0:
            out.append(p)
        if sp*sq < 0:
            f = sp/(sp-sq)
            out.append(tuple(p[j]+f*(q[j]-p[j]) for j in range(2)))
    return tuple(p for j, p in enumerate(out) if p != out[j-1]) if len(out) >= 3 else ()


def _integral(poly, linear, arena=None):
    """Exact integral of an affine nonnegative function over a planar polygon."""
    if arena is not None:
        with V._work((*linear, *(q for p in poly for q in p)), arena.resource):
            return _integral(poly, linear)
    if not poly:
        return Q(0)
    total, a = Q(0), poly[0]
    values = lambda p: linear[0]*p[0]+linear[1]*p[1]+linear[2]
    exact = (type(poly) is tuple and type(linear) is tuple and len(linear) == 3
             and all(type(q) in (int, Q) for q in linear)
             and all(type(p) is tuple and len(p) == 2
                     and all(type(q) in (int, Q) for q in p) for p in poly))
    for b, c in zip(poly[1:-1], poly[2:]):
        twice = (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
        if twice < 0:
            raise V.VolumeError('wall polygon orientation changed')
        if exact:
            # Affine linearity: f(a)+f(b)+f(c) uses each coefficient once.
            # No new retained rational local or polygon/point cache is created.
            total += twice*(linear[0]*(a[0]+b[0]+c[0])
                            +linear[1]*(a[1]+b[1]+c[1])+3*linear[2])/6
        else:
            total += twice*(values(a)+values(b)+values(c))/6
    if total < 0:
        raise V.VolumeError('negative sign-split wall integral')
    return total


def _face(cell, axis, end):
    transverse = tuple(j for j in range(3) if j != axis)
    fixed = cell.lower_m[axis] if end == 0 else cell.upper_m[axis]
    origin = tuple(cell.origin_m[j]+cell.basis[j][axis]*fixed for j in range(3))
    eu, ev = (tuple(cell.basis[j][k] for j in range(3)) for k in transverse)
    normal = tuple((1 if end else -1)*cell.basis[j][axis] for j in range(3))
    bounds = tuple((cell.lower_m[k], cell.upper_m[k]) for k in transverse)
    return origin, eu, ev, normal, bounds


def _rectangle(bounds):
    (u0, u1), (v0, v1) = bounds
    return ((u0, v0), (u1, v0), (u1, v1), (u0, v1))


def _point(face, uv):
    origin, eu, ev = face[:3]
    return tuple(origin[j]+eu[j]*uv[0]+ev[j]*uv[1] for j in range(3))


def _line(face, normal, offset=0):
    twin = _D5.line(face, normal, offset)
    if twin is not _D5.DECLINED:
        return twin
    return O._dot(normal, face[1]), O._dot(normal, face[2]), O._dot(normal, face[0])-offset


def _radial_planes(face, bounds, layer, inner):
    """Rigorous shell halfplane bounds on the actual two-dimensional face."""
    midpoint = tuple((a+b)/2 for a, b in bounds)
    centre = _point(face, midpoint)
    residual = sum(((b-a)/2)**2 for a, b in bounds)
    squared = O._dot(centre, centre)
    gradient = tuple(2*v for v in centre)
    lo2, hi2 = layer.bottom_radius_m**2, layer.top_radius_m**2
    # Direct min/max includes the closest point within the plane rectangle.
    coords = tuple((a+O._dot(face[0], e), b+O._dot(face[0], e))
                   for (a, b), e in zip(bounds, face[1:3]))
    constant = O._dot(face[0], face[0])-sum(O._dot(face[0], e)**2 for e in face[1:3])
    minimum = constant+sum(0 if a <= 0 <= b else min(a*a, b*b) for a, b in coords)
    maximum = constant+sum(max(a*a, b*b) for a, b in coords)
    if minimum >= lo2 and maximum <= hi2:
        return ()
    if minimum >= hi2 or maximum <= lo2:
        return ((Q(0), Q(0), Q(-1)),)
    lower = lo2+squared-(0 if inner else residual)
    upper = hi2+squared-(residual if inner else 0)
    return (_line(face, gradient, lower), _line(face, tuple(-v for v in gradient), -upper))


def _wall_leaf(layer, cones, face, bounds, omega, t0, t1, level, arena, prior=()):
    original = _rectangle(bounds)
    velocities = tuple(O._dot(face[3], O._cross(omega, direction)) for direction in (face[1], face[2], face[0]))
    globals_ = tuple(_point(face, p) for p in original)
    absolute = sum(max(abs(p[j]) for p in globals_) for j in range(3))
    normals = tuple(tuple(_pose_vector(n, omega, t0, t1, level, arena, prior)
                          for n in V._cone_normals(cone)) for cone in cones)
    result = []
    for sign in (-1, 1):  # inward, outward relative to the complete native grid
        linear = tuple(sign*v for v in velocities)
        signed = _clip2(original, linear, arena)
        whole = _integral(signed, linear, arena)*(t1-t0)
        limits = []
        for inner in (True, False):
            total = Q(0)
            for cone in normals:
                poly = signed
                for normal, error in cone:
                    pad = error*absolute*(1 if inner else -1)
                    poly = _clip2(poly, _line(face, normal, pad), arena)
                    if not poly:
                        break
                for line in _radial_planes(face, bounds, layer, inner):
                    poly = _clip2(poly, line, arena)
                total += _integral(poly, linear, arena)*(t1-t0)
            limits.append(min(whole, total))
        if not 0 <= limits[0] <= limits[1] <= whole:
            raise V.VolumeError('space-time wall enclosure lost nonnegative ordering')
        result.append(tuple(limits))
    arena.work(128+64*sum(map(len, normals)))
    return tuple(result)


def enclose_rotating_wall(layer, cones, cell, axis, end, *, angular_velocity_rad_s,
                         start_offset_s, end_offset_s, max_width_m3, max_leaves, budget,
                         prior_rotations=()):
    """Enclose both signs of flux of actual rotating cone/shell material.

    This integrates the whole time interval, including material absent from
    both endpoint wall traces. Returned intervals are NOT accepted if `met`
    is false. One explicit per-sign width and finite subdivision limit apply.
    """
    if type(layer) is not V.RadialLayer or type(cell) is not V.CartesianCell:
        raise V.VolumeError('typed radial layer and Cartesian wall cell required')
    if type(axis) is not int or axis not in (0, 1, 2) or type(end) is not int or end not in (0, 1):
        raise V.VolumeError('wall axis/end must be integer indices')
    if type(angular_velocity_rad_s) is not tuple or len(angular_velocity_rad_s) != 3:
        raise V.VolumeError('one explicit constant angular velocity triple required')
    omega = tuple(map(_q, angular_velocity_rad_s))
    if type(prior_rotations) is not tuple or any(type(p) is not tuple or len(p) != 2 or
            type(p[0]) is not tuple or len(p[0]) != 3 for p in prior_rotations):
        raise V.VolumeError('explicit prior rotation/positive duration pairs required')
    prior = tuple((tuple(map(_q, w)), _q(duration)) for w, duration in prior_rotations)
    if any(duration <= 0 for _, duration in prior):
        raise V.VolumeError('prior segments need positive durations')
    t0, t1, width = map(_q, (start_offset_s, end_offset_s, max_width_m3))
    if t0 < 0 or t1 <= t0 or width < 0 or type(max_leaves) is not int or max_leaves < 1:
        raise V.VolumeError('positive forward interval, nonnegative error and finite work limit required')
    resource = select_budget(budget)
    quantum = _quantum(width, max_leaves)
    cones = tuple(V.convex_cone_union((cone,), budget=resource) for cone in cones)
    if not cones:
        raise V.VolumeError('actual source cones required')
    face = _face(cell, axis, end)
    with B._Arena(resource) as arena:
        with V._work((*omega, t0, t1, *cell._geometry()), resource):
            first = _wall_leaf(layer, cones, face, face[4], omega, t0, t1, 0, arena, prior)
            first = tuple(_outward(pair, quantum) for pair in first)
        sums = [list(pair) for pair in first]
        queue, serial, leaves = [], 0, 1
        def push(bounds, a, b, level, values):
            nonlocal serial
            uncertainty = max(hi-lo for lo, hi in values)
            if uncertainty:
                serial += 1
                heapq.heappush(queue, (-uncertainty, serial, bounds, a, b, level, values))
                arena.keep((a, b, *(q for pair in values for q in pair)), 1)
        push(face[4], t0, t1, 0, first)
        while queue and max(b-a for a, b in sums) > width and leaves < max_leaves:
            _, _, bounds, a, b, level, old = heapq.heappop(queue)
            # A whole face rectangle already within the radial shell has no
            # spatial quadrature error: its planar cuts are integrated exactly.
            # Refine time alone there; gratuitous spatial subdivision would
            # multiply work without resolving the moving-plane uncertainty.
            # At curved contacts all dimensions shrink to ensure convergence.
            dimension = level % 3 if _radial_planes(face, bounds, layer, True) else 0
            children = []
            if dimension == 0:
                middle = (a+b)/2
                children = [(bounds, a, middle), (bounds, middle, b)]
            else:
                k = dimension-1
                middle = sum(bounds[k])/2
                for right in (False, True):
                    split = list(bounds)
                    split[k] = (middle, bounds[k][1]) if right else (bounds[k][0], middle)
                    children.append((tuple(split), a, b))
            new = []
            for box, ca, cb in children:
                with V._work((*omega, ca, cb, *(q for pair in box for q in pair)), resource):
                    value = _wall_leaf(layer, cones, face, box, omega, ca, cb, level+1, arena, prior)
                    value = tuple(_outward(pair, quantum) for pair in value)
                push(box, ca, cb, level+1, value)
                new.append(value)
            for sign in range(2):
                for endpoint in range(2):
                    sums[sign][endpoint] += sum(v[sign][endpoint] for v in new)-old[sign][endpoint]
            leaves += 1
        return dict(inward=tuple(sums[0]), outward=tuple(sums[1]), leaves=leaves,
                    met=max(b-a for a, b in sums) <= width, work_units=arena.work_units)


def _whole_face(cell, axis, end, omega, dt):
    face = _face(cell, axis, end)
    normal = tuple(O._dot(face[3], O._cross(omega, p)) for p in (face[1], face[2], face[0]))
    polygon = _rectangle(face[4])
    values = tuple(normal[0]*p[0]+normal[1]*p[1]+normal[2] for p in polygon)
    return tuple(_integral(_clip2(polygon, tuple(sign*v for v in normal)), tuple(sign*v for v in normal))*dt
                 for sign in (-1, 1)), min(values)*max(values) >= 0


def _pose_planes(cones, omega, t0, t1, level, cell, arena, inner, prior=()):
    absolute = sum(max(abs(p[j]) for p in cell._vertices()) for j in range(3))
    groups = []
    for cone in cones:
        planes = []
        for normal in V._cone_normals(cone):
            vector, error = _pose_vector(normal, omega, t0, t1, level, arena, prior)
            planes.append((*(-v for v in vector), -error*absolute*(1 if inner else -1)))
        groups.append(tuple(planes))
    return tuple(groups)


def _volume_leaf(layer, cones, cell, omega, time, level, arena, prior=()):
    """Endpoint volume bounds independent of accumulated wall flux."""
    minimum, maximum = cell._radial_bounds()
    inner2, outer2 = layer.bottom_radius_m**2, layer.top_radius_m**2
    if minimum >= outer2 or maximum <= inner2:
        return Q(0), Q(0)
    centre = tuple(cell.origin_m[i]+sum(cell.basis[i][j]*(cell.lower_m[j]+cell.upper_m[j])/2
                   for j in range(3)) for i in range(3))
    residual = sum(((b-a)/2)**2 for a, b in zip(cell.lower_m, cell.upper_m))
    squared, gradient = O._dot(centre, centre), tuple(2*v for v in centre)
    result = []
    for inner in (True, False):
        total = Q(0)
        for planes in _pose_planes(cones, omega, time, time, level, cell, arena, inner, prior):
            poly = B._box(cell)
            if not (minimum >= inner2 and maximum <= outer2):
                planes += ((*gradient, outer2+squared-(residual if inner else 0)),
                    (*(-v for v in gradient), -inner2-squared+(0 if inner else residual)))
            for plane in planes:
                poly = B._clip(poly, plane, arena)
                if not poly:
                    break
            total += B._volume(poly, arena)
        result.append(min(cell.volume_m3, total))
    return tuple(result)


def _endpoint_volume(layer, cones, grid, omega, time, width, max_leaves, resource, prior=(), *, positive_witness=False):
    """Physical enclosure, optionally retaining a certified positive subset.

    Outward dyadic rounding may turn a strictly positive lower bound into zero.
    An exact inner polyhedron is a subset of the TRUE posed cone and shell:
    its halfspaces include the exponential-rotation error and the quadratic
    radial remainder. Its volume therefore remains a valid lower witness even
    when that rounded lower bound vanishes. If requested, subdivision seeks
    such a witness under the SAME leaf/work limit; failure proves no positivity.
    No thermal surrogate, epsilon floor or changed upper bound is used.
    """
    quantum = _quantum(width, max_leaves)
    with B._Arena(resource) as arena:
        initial = _volume_leaf(layer, cones, grid, omega, time, 0, arena, prior)
        witness = initial[0] if positive_witness else Q(0)
        low, high = _outward(initial, quantum)
        queue, serial, leaves = [(low-high, 0, grid, 0, low, high)], 0, 1
        while queue and (high-low > width or positive_witness and not witness and high > 0) and leaves < max_leaves:
            _, _, parent, level, a, b = heapq.heappop(queue)
            axis = level % 3
            middle = (parent.lower_m[axis]+parent.upper_m[axis])/2
            updates = []
            for right in (False, True):
                lower, upper = list(parent.lower_m), list(parent.upper_m)
                (lower if right else upper)[axis] = middle
                child = V.CartesianCell(tuple(lower), tuple(upper), parent.origin_m, parent.basis, budget=resource)
                exact = _volume_leaf(layer, cones, child, omega, time, level+1, arena, prior)
                if positive_witness:
                    witness = max(witness, exact[0])
                lo, hi = _outward(exact, quantum)
                serial += 1
                if lo != hi:
                    heapq.heappush(queue, (lo-hi, serial, child, level+1, lo, hi))
                    arena.keep((*child._geometry(), lo, hi), 1)
                updates.append((lo, hi))
            low += sum(q[0] for q in updates)-a
            high += sum(q[1] for q in updates)-b
            leaves += 1
        if high-low > width:
            raise V.VolumeError('endpoint shadow geometry exceeds declared integration width/work budget')
        if witness > high:
            raise V.VolumeError('physical inner-subset witness exceeds enclosing upper bound')
        return max(low, witness), high


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class WallMeasures:
    _json: bytes = field(repr=False)
    _resource: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('WallMeasures is issued by measure_walls()')

    @property
    def measure_id(self):
        return hashlib.sha256(self._json).hexdigest()

    def descriptor(self):
        return dict(measure_id=self.measure_id, **json.loads(self._json))

    @classmethod
    def restore(cls, record, *, budget):
        """Restore retained evidence from the trusted source-bound local store.

        This checks encoded size, canonical identity and the record contract;
        it DOES NOT re-integrate or newly certify a caller-authored geometry.
        The transaction's retained source/CAS binding authenticates the record.
        """
        if type(record) is not dict or type(budget) is not WorkBudget:
            raise V.VolumeError('stored measure record and explicit budget required')
        stack, size = [record], 0
        while stack:
            item = stack.pop()
            if type(item) is dict:
                if any(type(k) is not str for k in item):
                    raise V.VolumeError('string record keys required')
                size += 64*len(item)+sum(len(k) for k in item)
                stack.extend(item.values())
            elif type(item) is list:
                size += 32*len(item); stack.extend(item)
            elif type(item) is str:
                size += 4*len(item)
            elif type(item) in (int, bool):
                size += 64+(abs(item).bit_length()+7)//8
            else:
                raise V.VolumeError('canonical exact JSON measure values required')
            if size > budget.max_bytes:
                raise V.VolumeError('stored wall evidence exceeds caller resource budget')
        with budget.reserve(65536+8*size, category='space-time-wall-restore'):
            if record.get('schema') != 'atlas.rigid-space-time-wall-measures.v1' or record.get('method') != METHOD:
                raise V.VolumeError('unsupported stored wall method')
            identity = record.get('measure_id')
            body = {k: v for k, v in record.items() if k != 'measure_id'}
            encoded = json.dumps(body, sort_keys=True, separators=(',', ':')).encode()
            if type(identity) is not str or hashlib.sha256(encoded).hexdigest() != identity:
                raise V.VolumeError('stored wall evidence identity changed')
            required = ('funding_id', 'collar_plan_id', 'parent_state_id', 'source', 'start_time_s',
                        'end_time_s', 'trajectory', 'prior_trajectory_id', 'trajectory_id',
                        'start_support_id', 'end_support_id', 'grid_cell_ids', 'rows', 'faces', 'exterior_cells')
            if any(k not in body for k in required) or type(body['rows']) is not list or type(body['faces']) is not list:
                raise V.VolumeError('stored wall contract is incomplete')
            segments = body['trajectory'].get('segments')
            if type(segments) is not list or not segments or _hash(segments) != body['trajectory_id'] or _hash(segments[:-1]) != body['prior_trajectory_id']:
                raise V.VolumeError('stored wall trajectory identity changed')
            return _issued(encoded, budget)


def _issued(encoded, budget):
    lease = budget.reserve(8192+4*len(encoded), category='space-time-wall-measures-retained')
    lease.__enter__()
    try:
        result = object.__new__(WallMeasures)
        object.__setattr__(result, '_json', encoded)
        object.__setattr__(result, '_resource', budget)
        weakref.finalize(result, lease.__exit__, None, None, None)
        return result
    except BaseException:
        lease.__exit__(None, None, None)
        raise


def _history(prior_trajectory, epoch, start):
    cursor, rotations, records = epoch, [], []
    for record in prior_trajectory:
        if type(record) is not dict or set(record) != {'start_time_s', 'end_time_s', 'angular_velocity_rad_s'}:
            raise V.VolumeError('canonical accepted trajectory segment required')
        if type(record['angular_velocity_rad_s']) is not list or len(record['angular_velocity_rad_s']) != 3:
            raise V.VolumeError('canonical accepted angular velocity triple required')
        pairs = [record['start_time_s'], record['end_time_s'], *record['angular_velocity_rad_s']]
        if len(pairs) != 5 or any(type(p) is not list or len(p) != 2 or any(type(q) is not str for q in p) for p in pairs):
            raise V.VolumeError('canonical trajectory rational pairs required')
        try:
            a, b, *w = map(_decode, pairs)
        except (ValueError, ZeroDivisionError) as exc:
            raise V.VolumeError('invalid stored trajectory rational') from exc
        if a != cursor or b <= a or b > start or any(V._encoded(q) != p for q, p in zip((a, b, *w), pairs)):
            raise V.VolumeError('accepted trajectory must tile epoch to current start exactly')
        cursor = b
        rotations.append((tuple(w), b-a))
        records.append(dict(start_time_s=V._encoded(a), end_time_s=V._encoded(b), angular_velocity_rad_s=list(map(V._encoded, w))))
    if cursor != start:
        raise V.VolumeError('complete accepted trajectory prefix required; previous motion cannot be reset')
    return tuple(rotations), records


def _measure_walls(funding, sphere, collar, *, parent_state_id, start_time_s, end_time_s,
                   angular_velocity_rad_s, max_volume_error_m3, max_leaves, budget, prior_trajectory=()):
    """Issue source-bound wall partitions and independent endpoint/GCL bounds.

    The finite-volume cells are the ORIGINAL source cone/shell rotated along
    one immutable absolute trajectory, minus the FIXED complete collar box.
    Their extensive state belongs to the caller; it is never resampled here.
    This first representation is coarse per-patch/layer, not spatially refined.
    """
    from . import integration_support as U
    from .regional_collar3d import PreparedRegionalCollar3D
    if type(funding) is not G.FullCellFunding or type(collar) is not PreparedRegionalCollar3D:
        raise V.VolumeError('issued funding and typed prepared collar required')
    if type(budget) is not WorkBudget or funding._resource is not budget or collar._budget is not budget:
        raise V.VolumeError('shared explicit geometry/consumer WorkBudget required')
    if type(parent_state_id) is not str or not parent_state_id:
        raise V.VolumeError('actual parent exterior state identity required')
    original = funding.descriptor()
    if original['source']['sphere_state_id'] != sphere.state_id or original['collar_plan_id'] != collar.plan_id:
        raise V.VolumeError('original source/funding/collar geometry binding changed')
    if type(angular_velocity_rad_s) is not tuple or len(angular_velocity_rad_s) != 3:
        raise V.VolumeError('one explicit common angular velocity required')
    omega = tuple(map(_q, angular_velocity_rad_s))
    start, end, epoch, width = map(_q, (start_time_s, end_time_s, original['time_s'], max_volume_error_m3))
    if start < epoch or end <= start or width < 0 or type(max_leaves) is not int or max_leaves < 1:
        raise V.VolumeError('forward source-bound interval and explicit finite integration budgets required')
    prior, history = _history(prior_trajectory, epoch, start)
    support = U.required(sphere.material)
    cells = collar.cell_geometries()
    if [cell.cell_id for cell in cells] != [row['cell_id'] for row in original['cell_accounts']]:
        raise V.VolumeError('actual fixed full-grid cell identity changed')
    base = cells[0]
    lower = tuple(min(c.lower_m[j] for c in cells) for j in range(3))
    upper = tuple(max(c.upper_m[j] for c in cells) for j in range(3))
    if any(c.origin_m != base.origin_m or c.basis != base.basis for c in cells):
        raise V.VolumeError('one exact affine full-grid embedding required')
    grid = V.CartesianCell(lower, upper, base.origin_m, base.basis, budget=budget)
    if grid.volume_m3 != sum((c.volume_m3 for c in cells), Q(0)):
        raise V.VolumeError('issued regular full cells do not tile their enclosing box')
    keys = tuple((r['patch_id'], r['sublayer']) for r in original['exterior_remainder'])
    patches = {p.patch_id: p for p in support.patches if p.patch_id in {k[0] for k in keys}}
    geometry, cones = {}, {}
    for row in original['exterior_remainder']:
        key, record = (row['patch_id'], row['sublayer']), row['radial_layer']
        geometry[key] = V.RadialLayer(*(_decode(record[n]) for n in ('radius_m', 'top_depth_m', 'bottom_depth_m')), budget=budget)
        if key[0] not in cones:
            raw = patches[key[0]].cells
            try:
                cones[key[0]] = (V.convex_cone_union(raw, budget=budget),)
            except V.VolumeError:
                cones[key[0]] = raw
    # Coverage must be established from the actual conforming union, not by
    # normalising a deficient sum of positive row measures.
    union_planes = tuple(G._cone_planes(c) for p in sorted(cones) for c in cones[p])
    envelope_bottom = max(min(s.bottom_radius_m for k, s in geometry.items() if k[0] == p) for p in cones)
    envelope_top = min(max(s.top_radius_m for k, s in geometry.items() if k[0] == p) for p in cones)
    minimum, maximum = grid._radial_bounds()
    if minimum < envelope_bottom**2 or maximum > envelope_top**2:
        raise V.VolumeError('moving full-grid coverage is not common to the actual selected radial intervals')
    with B._Arena(budget) as arena:
        pending, leaves = [(Q(0), end-start, 0)], 0
        while pending:
            a, b, level = pending.pop()
            # A conservative search/coverage enclosure, NEVER material support:
            # inverse-rotate the grid's actual vertices with certified errors.
            # Their convex combinations contain the whole inverse-rotated grid
            # at every time. Exact complement exhaustion against the ACTUAL
            # cone union handles nonconvex unions and internal shared edges.
            inverse = tuple(_pose_vector(p, omega, a, b, level, arena, prior, inverse=True)
                            for p in grid._vertices())
            lower_bound = tuple(min(p[j]-error for p, error in inverse) for j in range(3))
            upper_bound = tuple(max(p[j]+error for p, error in inverse) for j in range(3))
            enclosure = V.CartesianCell(lower_bound, upper_bound, budget=budget)
            uncovered = B._outside_holes(B._box(enclosure), union_planes, arena)
            if not any(B._volume(part, arena) > 0 for part in uncovered):
                leaves += 1
                continue
            if leaves+len(pending)+2 > max_leaves:
                raise V.VolumeError('actual source union does not certify full moving coverage within work budget')
            middle = (a+b)/2
            pending.extend(((a, middle, level+1), (middle, b, level+1)))
    segment = dict(start_time_s=V._encoded(start), end_time_s=V._encoded(end), angular_velocity_rad_s=list(map(V._encoded, omega)))
    completed = history+[segment]
    trajectory = dict(rule='chronological composition of exact constant-skew matrix exponentials',
        epoch_s=V._encoded(epoch), segments=completed)
    support_base = dict(funding_id=funding.funding_id, grid_cell_ids=[c.cell_id for c in cells])
    def support_id(t):
        prefix = history if t == start else completed
        return _hash(dict(**support_base, time_s=V._encoded(t), trajectory_prefix=prefix))
    totals = {key: [[Q(0), Q(0)], [Q(0), Q(0)]] for key in keys}
    selected = {key: [Q(0), Q(0)] for key in keys}
    selected_error = {key: Q(0) for key in keys}
    rows, faces = [], []
    for axis in range(3):
        transverse = tuple(j for j in range(3) if j != axis)
        for finish in (0, 1):
            for i in range(collar.cells[transverse[0]]):
                for j in range(collar.cells[transverse[1]]):
                    index = [0, 0, 0]
                    index[axis] = 0 if finish == 0 else collar.cells[axis]-1
                    index[transverse[0]], index[transverse[1]] = i, j
                    flat = (index[0]*collar.cells[1]+index[1])*collar.cells[2]+index[2]
                    cell = cells[flat]
                    exact, constant_sign = _whole_face(cell, axis, finish, omega, end-start)
                    side, face_index = 'xyz'[axis]+('-' if finish == 0 else '+'), [i, j]
                    face_results = []
                    for key in keys:
                        if exact == (0, 0):
                            result = dict(inward=(Q(0), Q(0)), outward=(Q(0), Q(0)), met=True)
                        else:
                            result = enclose_rotating_wall(geometry[key], cones[key[0]], cell, axis, finish,
                                angular_velocity_rad_s=omega, start_offset_s=0, end_offset_s=end-start,
                                max_width_m3=width, max_leaves=max_leaves, budget=budget, prior_rotations=prior)
                        if not result['met']:
                            raise V.VolumeError('wall space-time integral did not meet declared width/work budget')
                        face_results.append(result)
                    allocations = tuple(G._partition(tuple(r[name] for r in face_results), total)
                                        for name, total in zip(('inward', 'outward'), exact))
                    faces.append(dict(side=side, face_index=face_index, cell_id=cell.cell_id,
                        inward_exact_volume_m3=V._encoded(exact[0]), outward_exact_volume_m3=V._encoded(exact[1]),
                        normal_has_constant_sign=constant_sign))
                    for n, (key, result) in enumerate(zip(keys, face_results)):
                        values = allocations[0][n], allocations[1][n]
                        deviations = []
                        for sign, name in enumerate(('inward', 'outward')):
                            lo, hi = result[name]
                            totals[key][sign][0] += lo; totals[key][sign][1] += hi
                            selected[key][sign] += values[sign]
                            deviations.append(max(values[sign]-lo, hi-values[sign]))
                        selected_error[key] += sum(deviations)
                        if any(values) or any(deviations):
                            rows.append(dict(side=side, face_index=face_index, cell_id=cell.cell_id,
                                exterior_cell_key=list(key), inward_volume_m3=V._encoded(values[0]),
                                outward_volume_m3=V._encoded(values[1]),
                                inward_bounds_m3=list(map(V._encoded, result['inward'])),
                                outward_bounds_m3=list(map(V._encoded, result['outward'])),
                                inward_max_deviation_m3=V._encoded(deviations[0]),
                                outward_max_deviation_m3=V._encoded(deviations[1])))
    endpoints = []
    for key in keys:
        layer = geometry[key]
        with U.geometry_workspace(budget):
            area = U.area_interval_sr(patches[key[0]].cells)
        source_volume = tuple(q*Q(sphere.network.sphere.radius_m)**2*layer.volume_per_area_m for q in area)
        inside = tuple(_endpoint_volume(layer, cones[key[0]], grid, omega, t-start, width, max_leaves, budget, prior)
                       for t in (start, end))
        outside = tuple((max(Q(0), source_volume[0]-hi), source_volume[1]-lo) for lo, hi in inside)
        # The unchanged source measure cancels from the difference. Retaining
        # it twice would invent an unnecessarily large GCL error allowance.
        change = inside[0][0]-inside[1][1], inside[0][1]-inside[1][0]
        inward, outward = totals[key]
        flux = outward[0]-inward[1], outward[1]-inward[0]
        common = max(change[0], flux[0]), min(change[1], flux[1])
        if common[0] > common[1]:
            raise V.VolumeError('independent shadow geometry and integrated wall flux violate GCL')
        chosen = selected[key][1]-selected[key][0]
        admissible = common[0]-selected_error[key], common[1]+selected_error[key]
        if not admissible[0] <= chosen <= admissible[1]:
            raise V.VolumeError('chosen FV volume change exceeds its derived geometry integration bound')
        endpoints.append(dict(exterior_cell_key=list(key),
            start_support_id=_hash(dict(support_id=support_id(start), key=list(key))),
            end_support_id=_hash(dict(support_id=support_id(end), key=list(key))),
            start_volume_bounds_m3=list(map(V._encoded, outside[0])), end_volume_bounds_m3=list(map(V._encoded, outside[1])),
            geometry_volume_change_bounds_m3=list(map(V._encoded, change)),
            flux_volume_change_bounds_m3=list(map(V._encoded, flux)),
            gcl_intersection_bounds_m3=list(map(V._encoded, common)),
            chosen_volume_change_m3=V._encoded(chosen),
            chosen_volume_change_error_m3=V._encoded(selected_error[key]),
            chosen_change_admissible_bounds_m3=list(map(V._encoded, admissible))))
    record = dict(schema='atlas.rigid-space-time-wall-measures.v1', method=METHOD,
        funding_id=funding.funding_id, collar_plan_id=collar.plan_id, parent_state_id=parent_state_id,
        source=original['source'], start_time_s=V._encoded(start), end_time_s=V._encoded(end),
        trajectory=trajectory, start_support_id=support_id(start), end_support_id=support_id(end),
        prior_trajectory_id=_hash(history), trajectory_id=_hash(completed),
        grid_cell_ids=support_base['grid_cell_ids'], rows=rows, faces=faces, exterior_cells=endpoints,
        max_volume_error_m3=V._encoded(width), max_leaves=max_leaves,
        support_rule='rotated original actual cone/radial-layer minus fixed full-grid box; no endpoint stock resampling',
        scope='coarse per-source patch/layer FV geometry; rigorous integration bounds; no field/time-discretisation accuracy bound')
    encoded = json.dumps(record, sort_keys=True, separators=(',', ':')).encode()
    return _issued(encoded, budget)


def measure_walls(funding, sphere, collar, *, parent_state_id, start_time_s, end_time_s,
                  angular_velocity_rad_s, max_volume_error_m3, max_leaves, budget, prior_trajectory=()):
    """Issue the bounded full space-time wall and independent GCL certificate.

    See `_measure_walls` for the geometric contract. Both geometric predicates
    and the candidate/report tables have explicit shared work-budget charges.
    Failed admission releases every transient lease; nothing is partly issued.
    """
    from .regional_collar3d import PreparedRegionalCollar3D
    if type(funding) is not G.FullCellFunding or type(collar) is not PreparedRegionalCollar3D:
        raise V.VolumeError('issued funding and typed prepared collar required')
    if type(budget) is not WorkBudget or funding._resource is not budget or collar._budget is not budget:
        raise V.VolumeError('one shared explicit WorkBudget required')
    if type(prior_trajectory) not in (tuple, list):
        raise V.VolumeError('explicit retained trajectory segment list required')
    # Encoded-size guard before _history creates large rational integers.
    text_size, stack = 0, [prior_trajectory]
    while stack:
        item = stack.pop()
        if type(item) in (list, tuple):
            stack.extend(item); text_size += 32*len(item)
        elif type(item) is dict:
            stack.extend(item.values()); text_size += 256*len(item)
        elif type(item) is str:
            text_size += len(item)
        else:
            raise V.VolumeError('canonical encoded trajectory fields required')
        if text_size > budget.max_bytes:
            raise V.VolumeError('trajectory encoding exceeds caller resource budget')
    with budget.reserve(65536+2*funding._snapshot.nbytes, category='space-time-wall-source'):
        count = len(funding.exterior_remainder())
        faces = 2*sum(collar.cells[i]*collar.cells[j] for i, j in ((0, 1), (1, 2), (0, 2)))
        with budget.reserve(131072+8192*(faces*count+math.prod(collar.cells))+256*text_size, category='space-time-wall-tables'):
            return _measure_walls(funding, sphere, collar, parent_state_id=parent_state_id,
                start_time_s=start_time_s, end_time_s=end_time_s, angular_velocity_rad_s=angular_velocity_rad_s,
                max_volume_error_m3=max_volume_error_m3, max_leaves=max_leaves, budget=budget,
                prior_trajectory=prior_trajectory)


# D5: GMP-resident twins of _rotated_normal, _clip2 and _line (integration_wall_measures_gmp);
# a declined call runs the code above. Imported last, so the module is complete when the twins record
# its reference objects.
from . import integration_wall_measures_gmp as _D5  # noqa: E402
_D5.attach(__name__)
