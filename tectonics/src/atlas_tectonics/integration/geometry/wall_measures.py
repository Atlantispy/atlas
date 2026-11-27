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
from pathlib import Path
import math
import os
import threading
import weakref

from . import volume as V
from . import volume_overlap as O
from . import volume_bounds as B
from . import collar_geometry as G
from atlas_tectonics.integration.resources import WorkBudget, select_budget


METHOD = 'exact-rational-enclosed-rigid-space-time-wall-v1'


def _text(record):
    return json.dumps(record, sort_keys=True, separators=(',', ':'))


def _hash(record):
    return hashlib.sha256(_text(record).encode()).hexdigest()


class TrajectoryHash:
    """Running `_hash(prefix-wrapped list)`: one appended item costs one item rendering.

    The compact JSON of a list is `[`, the item texts joined by commas, `]`, so the
    id of the list so far is a copy of the running state fed the closing bytes.
    """

    def __init__(self, prefix='', suffix=''):
        self._state = hashlib.sha256((prefix+'[').encode())
        self._suffix = (']'+suffix).encode()
        self._count = 0

    def append(self, item):
        self._state.update(((',' if self._count else '')+_text(item)).encode())
        self._count += 1

    def extend(self, items):
        for item in items:
            self.append(item)

    def copy(self):
        other = object.__new__(TrajectoryHash)
        other._state, other._suffix, other._count = self._state.copy(), self._suffix, self._count
        return other

    def id(self):
        state = self._state.copy()
        state.update(self._suffix)
        return state.hexdigest()


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
        with V._work((*term, *omega, middle, major), arena.resource, convert_values=False):
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


# Pose width (b-ray): a posed vector is rounded after every step with a nonzero
# radius to a dyadic quantum <= 2**-POSE_ROUND_GUARD_RAY of that step's own radius
# and of its Taylor target; the radius is raised outward by at least the quantum.
POSE_ROUND_GUARD_RAY = 12


def _floor_log2(x):
    """floor(log2 x) for a positive int or Fraction, exactly."""
    if type(x) not in (int, Q) or x <= 0:
        raise V.VolumeError('positive exact rational required')
    x = Q(x)
    e = x.numerator.bit_length()-x.denominator.bit_length()
    return e-1 if Q(2)**e > x else e


def _ceil_log2(x):
    """ceil(log2 x) for a positive int or Fraction, exactly."""
    e = _floor_log2(x)
    return e if Q(2)**e == x else e+1


def _round_to(values, quantum):
    """Each value to the nearest multiple of quantum (ties to even): a tuple of Fractions."""
    return tuple(round(v/quantum)*quantum for v in values)


def _round_up(value, quantum):
    """The least multiple of quantum not below value."""
    return -((-value)//quantum)*quantum


# Decoded histories issued by differential_geometry._history in the current query:
# id(tuple) -> [tuple, record rows, lazy (digest, digest without the last row)]. The held
# tuple keeps its id unique.
_history_digests = {}
# Forward pose after a history's steps, by (vector, vector types, level, history digest):
# (vector, error, arena work charges of those steps). Shared by all queries of the process.
_pose_memo = {}
_pose_lock = threading.Lock()
# shortcut: unmeasured figure; set from the entry count in the first Debug profile.
pose_memo_limit = 4096


def _register_history(history, rows):
    _history_digests[id(history)] = [history, rows, None]


def _history_digest(history):
    entry = _history_digests.get(id(history))
    if entry is None or entry[0] is not history:
        return None
    if entry[2] is None:
        # One rendering gives both ids: the list so far equals _text(rows[:-1]), then _text(rows).
        running = TrajectoryHash()
        running.extend(entry[1][:-1])
        before = running.id()
        running.extend(entry[1][-1:])
        entry[2] = running.id(), before
    return entry[2]


class _Charges:
    # Forwards a pose step's arena work and records it for replay on a memo hit.
    def __init__(self, arena):
        self.arena, self.resource, self.counts = arena, arena.resource, []

    def work(self, count):
        self.counts.append(count)
        return self.arena.work(count)


def _pose_vector(vector, omega, t0, t1, level, arena, prior=(), *, inverse=False):
    digests = None if inverse or not prior else _history_digest(prior)
    if digests is None:
        steps = tuple((w, duration, duration) for w, duration in prior)+((omega, t0, t1),)
        if inverse:
            steps = tuple((tuple(-q for q in w), a, b) for w, a, b in reversed(steps))
        return _pose_steps(vector, steps, level, arena, Q(0))
    head = (tuple(vector), tuple(map(type, vector)), level)
    with _pose_lock:
        hit = _pose_memo.get(head+digests[:1])
        start = None if hit is not None or len(prior) < 2 else _pose_memo.get(head+digests[1:])
    if hit is None:
        # Each step's rounding reads only the level and the incoming vector and error, so the
        # pose after n-1 steps plus step n equals the full fold.
        charges = _Charges(arena)
        if start is None:
            posed, error = _pose_steps(vector, tuple((w, d, d) for w, d in prior), level, charges, Q(0))
            counts = ()
        else:
            for count in start[2]:
                arena.work(count)
            w, d = prior[-1]
            posed, error = _pose_steps(start[0], ((w, d, d),), level, charges, start[1])
            counts = start[2]
        hit = posed, error, counts+tuple(charges.counts)
        with _pose_lock:
            # Insertion order is history age: the oldest histories go first at the cap.
            while len(_pose_memo) >= pose_memo_limit:
                del _pose_memo[next(iter(_pose_memo))]
            _pose_memo[head+digests[:1]] = hit
    else:
        # Same work units as the skipped steps; their temporary reservations are not re-taken.
        for count in hit[2]:
            arena.work(count)
    return _pose_steps(hit[0], ((omega, t0, t1),), level, arena, hit[1])


# The pose-memo file carries entries between the processes of one run (CARRIER-r1 section 1). It is
# no input to any result: with or without it every value, record byte and work unit is equal.
def pose_memo_name(stem):
    # D-2: the method is in the name; a file written under another method is simply not found.
    return stem+'.pose-memo.'+METHOD+'.json'


pose_memo_file, pose_memo_added_file = pose_memo_name('pool'), pose_memo_name('added')


def _memo_number(value):
    return [type(value) is Q, str(value)]


def save_pose_memo(path, since=frozenset()):
    """Write the memo entries whose keys are not in `since`; nothing is written when there are none."""
    with _pose_lock:
        entries = [item for item in _pose_memo.items() if item[0] not in since]
    rows = []
    for (vector, _, level, digest), (posed, error, counts) in entries:
        if all(type(x) in (int, Q) for x in (*vector, *posed, error)):
            rows.append([[_memo_number(x) for x in vector], level, digest, [_memo_number(x) for x in posed],
                         _memo_number(error), list(counts)])
    if rows:
        # Whole file, then rename: a killed process leaves the old file or none.
        path = Path(path)
        temporary = path.with_name(path.name+'.tmp')
        temporary.write_text(json.dumps(rows, separators=(',', ':')), encoding='utf-8')
        os.replace(temporary, path)


def load_pose_memo(path):
    """Merge a memo file this run wrote (read on trust, 1804); missing or unreadable is a miss.

    Returns the keys held afterwards, so a worker can save only what it added."""
    number = lambda pair: (Q if pair[0] else int)(pair[1])
    entries = {}
    try:
        for vector, level, digest, posed, error, counts in json.loads(Path(path).read_text(encoding='utf-8')):
            vector = tuple(map(number, vector))
            entries[vector, tuple(map(type, vector)), level, digest] = (
                tuple(map(number, posed)), number(error), tuple(counts))
    except (OSError, ValueError, TypeError):
        entries = {}
    with _pose_lock:
        for key, value in entries.items():
            if len(_pose_memo) >= pose_memo_limit:
                break
            _pose_memo.setdefault(key, value)
        return frozenset(_pose_memo)


def _pose_steps(vector, steps, level, arena, error):
    for w, a, b in steps:
        # Prior segments are endpoint rotations; only the current segment's
        # interval is time-dependent, even when applying the inverse product.
        before = vector
        vector, delta = _rotated_normal(vector, w, a, b, level, arena)
        error += delta
        if delta:
            # Round to nearest moves the vector by <= sqrt(3)/2*quantum in the
            # 2-norm and round_up adds >= quantum: the radius still encloses the
            # true pose, and both stay on a short dyadic grid. delta == 0 is an
            # exact step and is never rounded.
            target = max(map(abs, before))/Q(2**(32+2*level))
            quantum = Q(2)**(_floor_log2(min(delta, target))-POSE_ROUND_GUARD_RAY)
            vector = _round_to(vector, quantum)
            error = _round_up(error+quantum, quantum)
    return vector, error


def _clip2(poly, line, arena=None):
    """Counterclockwise convex polygon clipped by a*u+b*v+c >= 0."""
    if arena is not None:
        with V._work((*line, *(q for p in poly for q in p)), arena.resource, convert_values=False):
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
        with V._work((*linear, *(q for p in poly for q in p)), arena.resource, convert_values=False):
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


class _Chain:
    """One leaf's clip chain on the reference route: the three functions, unchanged, behind one object.

    integration_exact_gmp._Chain2 is its GMP-resident twin (_chain chooses, once per leaf).
    """
    def __init__(self, arena):
        self.arena = arena

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def clip(self, poly, line, *, width_cache=None):
        return _clip2(poly, line, self.arena)

    def integral(self, poly, linear):
        return _integral(poly, linear, self.arena)

    def exact(self, poly):
        return poly


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
    return O._dot(normal, face[1]), O._dot(normal, face[2]), O._dot(normal, face[0])-offset


_CHAIN_REFERENCE = (_clip2, _line, _integral)


def _chain(arena):
    """The chain for ONE leaf, fixed at its entry by B._resident's rule.

    A wrapped or replaced _clip2, _line or _integral keeps the reference route, so instrumentation still sees
    every call.
    """
    K = B._resident()
    if K is B or (_clip2, _line, _integral) != _CHAIN_REFERENCE:
        return _Chain(arena)
    return K._Chain2(arena)


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
        with V._work((*omega, t0, t1, *cell._geometry()), resource, convert_values=False):
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
                with V._work((*omega, ca, cb, *(q for pair in box for q in pair)), resource, convert_values=False):
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
    vertices = cell._vertices()
    absolute = sum(max(abs(p[j]) for p in vertices) for j in range(3))
    del vertices
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
    _fresh: bool = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('WallMeasures is issued by measure_walls()')

    @property
    def measure_id(self):
        return hashlib.sha256(self._json).hexdigest()

    def descriptor(self):
        return dict(measure_id=self.measure_id, **json.loads(self._json))


def _issued(encoded, budget, *, fresh=False):
    lease = budget.reserve(8192+4*len(encoded), category='space-time-wall-measures-retained')
    lease.__enter__()
    try:
        result = object.__new__(WallMeasures)
        object.__setattr__(result, '_json', encoded)
        object.__setattr__(result, '_resource', budget)
        object.__setattr__(result, '_fresh', fresh)
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


def _funded_source_volume(exterior, account, basal, budget):
    lower, upper = exterior['geometry_volume_enclosure_m3']
    error = account['component_volume_max_deviation_m3']
    if basal:
        # The difference includes every prism cut from this patch and layer.
        operands = (lower, upper, error, account['source']['volume_m3'], exterior['stocks']['volume_m3'])
    else:
        operands = (lower, upper, error, account['debit']['volume_m3'])
    # The physical-volume workspace policy budgets 128 bytes per operand bit.
    # Bound the integers from their hex strings before decoding any Fraction.
    width = sum(len(n) + len(d) for n, d in operands)
    with budget.try_reserve(65536 + 512*width + 256*len(operands), category='wall-source-volume') as admitted:
        if admitted:
            lo, hi, deviation, offset, *peeled_stock = map(_decode, operands)
            if basal:
                offset -= peeled_stock[0]
            return lo + offset + deviation, hi + offset - deviation
    return None


def _measure_walls(funding, sphere, collar, *, parent_state_id, start_time_s, end_time_s,
                   angular_velocity_rad_s, max_volume_error_m3, max_leaves, budget, original, prior_trajectory=(),
                   _issued_volumes=False):
    """Issue source-bound wall partitions and independent endpoint/GCL bounds.

    The finite-volume cells are the ORIGINAL source cone/shell rotated along
    one immutable absolute trajectory, minus the FIXED complete collar box.
    Their extensive state belongs to the caller; it is never resampled here.
    This first representation is coarse per-patch/layer, not spatially refined.
    """
    from atlas_tectonics.integration import support as U
    if type(parent_state_id) is not str or not parent_state_id:
        raise V.VolumeError('actual parent exterior state identity required')
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
    cell_ids = [cell.cell_id for cell in cells]
    if cell_ids != [row['cell_id'] for row in original['cell_accounts']]:
        raise V.VolumeError('actual fixed full-grid cell identity changed')
    base = cells[0]
    lower, upper = base.lower_m, cells[-1].upper_m
    grid = V.CartesianCell(lower, upper, base.origin_m, base.basis, budget=budget)
    keys = tuple((r['patch_id'], r['sublayer']) for r in original['exterior_remainder'])
    patch_ids = {k[0] for k in keys}
    patches = {p.patch_id: p for p in support.patches if p.patch_id in patch_ids}
    del patch_ids
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
    support_base = dict(grid_cell_ids=cell_ids)     # A-1 root: no funding_id; the record keeps it
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
                    faces.append(dict(side=side, face_index=face_index, cell_id=cell_ids[flat],
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
                            rows.append(dict(side=side, face_index=face_index, cell_id=cell_ids[flat],
                                exterior_cell_key=list(key), inward_volume_m3=V._encoded(values[0]),
                                outward_volume_m3=V._encoded(values[1]),
                                inward_bounds_m3=list(map(V._encoded, result['inward'])),
                                outward_bounds_m3=list(map(V._encoded, result['outward'])),
                                inward_max_deviation_m3=V._encoded(deviations[0]),
                                outward_max_deviation_m3=V._encoded(deviations[1])))
    endpoints = []
    start_support_id = end_support_id = None
    previous_patch = None
    radius_squared = None
    basal = 'basal_inventory' in original
    for index, key in enumerate(keys):
        layer = geometry[key]
        source_volume = None
        if _issued_volumes:
            source_volume = _funded_source_volume(original['exterior_remainder'][index],
                original['source_accounts'][index], basal, budget)
        if source_volume is None:
            if key[0] != previous_patch:
                with U.geometry_workspace(budget):
                    area = U.area_interval_sr(patches[key[0]].cells)
                previous_patch = key[0]
            if radius_squared is None:
                radius_squared = Q(sphere.network.sphere.radius_m)**2
            volume_per_area = layer.volume_per_area_m
            source_volume = tuple(q*radius_squared*volume_per_area for q in area)
            del volume_per_area
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
        if start_support_id is None:
            start_support_id = support_id(start)
        start_child_id = _hash(dict(support_id=start_support_id, key=list(key)))
        if end_support_id is None:
            end_support_id = support_id(end)
        end_child_id = _hash(dict(support_id=end_support_id, key=list(key)))
        endpoints.append(dict(exterior_cell_key=list(key),
            start_support_id=start_child_id, end_support_id=end_child_id,
            start_volume_bounds_m3=list(map(V._encoded, outside[0])), end_volume_bounds_m3=list(map(V._encoded, outside[1])),
            geometry_volume_change_bounds_m3=list(map(V._encoded, change)),
            flux_volume_change_bounds_m3=list(map(V._encoded, flux)),
            gcl_intersection_bounds_m3=list(map(V._encoded, common)),
            chosen_volume_change_m3=V._encoded(chosen),
            chosen_volume_change_error_m3=V._encoded(selected_error[key]),
            chosen_change_admissible_bounds_m3=list(map(V._encoded, admissible))))
    if start_support_id is None:
        start_support_id, end_support_id = support_id(start), support_id(end)
    record = dict(schema='atlas.rigid-space-time-wall-measures.v1', method=METHOD,
        funding_id=funding.funding_id, collar_plan_id=collar.plan_id, parent_state_id=parent_state_id,
        source=original['source'], start_time_s=V._encoded(start), end_time_s=V._encoded(end),
        trajectory=trajectory, start_support_id=start_support_id, end_support_id=end_support_id,
        prior_trajectory_id=_hash(history), trajectory_id=_hash(completed),
        grid_cell_ids=support_base['grid_cell_ids'], rows=rows, faces=faces, exterior_cells=endpoints,
        max_volume_error_m3=V._encoded(width), max_leaves=max_leaves,
        support_rule='rotated original actual cone/radial-layer minus fixed full-grid box; no endpoint stock resampling',
        scope='coarse per-source patch/layer FV geometry; rigorous integration bounds; no field/time-discretisation accuracy bound')
    encoded = json.dumps(record, sort_keys=True, separators=(',', ':')).encode()
    return _issued(encoded, budget, fresh=True)


def measure_walls(funding, sphere, collar, *, parent_state_id, start_time_s, end_time_s,
                  angular_velocity_rad_s, max_volume_error_m3, max_leaves, budget, prior_trajectory=()):
    """Issue the bounded full space-time wall and independent GCL certificate.

    See `_measure_walls` for the geometric contract. Both geometric predicates
    and the candidate/report tables have explicit shared work-budget charges.
    Failed admission releases every transient lease; nothing is partly issued.
    """
    from atlas_tectonics.regional.collar3d import PreparedRegionalCollar3D
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
        original = funding.descriptor()
        count = len(original['exterior_remainder'])
        faces = 2*sum(collar.cells[i]*collar.cells[j] for i, j in ((0, 1), (1, 2), (0, 2)))
        with budget.reserve(131072+8192*(faces*count+math.prod(collar.cells))+256*text_size, category='space-time-wall-tables'):
            return _measure_walls(funding, sphere, collar, parent_state_id=parent_state_id,
                start_time_s=start_time_s, end_time_s=end_time_s, angular_velocity_rad_s=angular_velocity_rad_s,
                max_volume_error_m3=max_volume_error_m3, max_leaves=max_leaves, budget=budget,
                original=original, prior_trajectory=prior_trajectory,
                _issued_volumes=getattr(funding, '_source_volume_proven', False))
