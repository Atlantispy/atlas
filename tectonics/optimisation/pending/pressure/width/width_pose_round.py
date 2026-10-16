"""Pose width successor (b), design r2: bounded-width exact poses in two modules.

transform_wall_measures(source)   integration_wall_measures.py  (b-ray, in _pose_vector)
transform_exterior_mesh(source)   integration_exterior_mesh.py  (b-quat, in _representative_pose)

(b-ray) After each step of _pose_vector whose error radius delta is nonzero, the posed vector is
rounded to the nearest multiple of q = 2**(floor_log2(min(delta, t_L)) - POSE_ROUND_GUARD_RAY), where
t_L = max|v_in|/2**(32+2L) is the step's own Taylor target (as in _rotated_normal), and the radius
becomes round_up(error + q, q). Rounding to nearest moves a 3-vector by <= sqrt(3)/2*q <= q in the
2-norm; round_up adds a value in [q, 2q). True rotations are orthogonal, so the enlarged radii still
add as before. A step with delta == 0 (omega x v == 0, or t0 = t1 = 0) is exact and left untouched,
so end(n) through (w, d, d) equals start(n+1) through (w', 0, 0).

(b-quat) After each segment of _representative_pose whose delta is nonzero, the product is rounded
to q = 2**(floor_log2(delta) - POSE_ROUND_GUARD_QUAT) and the error becomes round_up(e + q, q), where
e is the unchanged recurrence (1+delta)*e_old + delta. When every nonzero segment rate is exactly
parallel to the first one, k, the product is (w, s*k) exactly (k x k = 0), and only w and s are
rounded (s to q_s = 2**(floor_log2(q) - ceil_log2(|k|_1))), so the vector part stays exactly
parallel to k and the posed-boundary axis certificate (Q k = Q^T k = k for the exactly orthogonal
CartesianCell.rotated matrix) is kept. Otherwise the four components are rounded to q. The move is
<= q in both cases, and the induction e_new <= (1 + 2**(1-G)) * e_old holds. The placement check
(error >= 1 or 4*error > operator_goal) is unchanged and is applied to the rounded error.

Every decision (whether to round, the quanta, the axis test, the rounding itself) uses exact int and
Fraction arithmetic only; there is no binary64 value on any decision path. Outputs stay tuples of
Fractions, so the exact_scale and other tuple fast paths still apply. Both edits run inside the same
work accounting as the code they extend: the quaternion rounding inside the existing V._work lease of
the product; the ray rounding on values no larger than the step output just leased by _rotated_normal.

Each transform checks its input pin, refuses a second application, and requires every anchor to occur
exactly once. Record identity: an identity successor (every pose-derived exact value changes).
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    'integration_wall_measures.py': {
        'd6b7d472246af0e8a9415b01465f035c0c860c7b358126fd1bba5c0025e671e0',
    },
    'integration_exterior_mesh.py': {
        'd338238e1abe11db8e01a4b4ee91f99443727fb082f9d9cb6799344e82d445f4',
    },
}
MARKER = {
    'integration_wall_measures.py': 'POSE_ROUND_GUARD_RAY',
    'integration_exterior_mesh.py': 'POSE_ROUND_GUARD_QUAT',
}

WALL_OLD = '''def _pose_vector(vector, omega, t0, t1, level, arena, prior=(), *, inverse=False):
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
'''
WALL_NEW = '''# Pose width (b-ray): a posed vector is rounded after every step with a nonzero
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


def _pose_vector(vector, omega, t0, t1, level, arena, prior=(), *, inverse=False):
    steps = tuple((w, duration, duration) for w, duration in prior)+((omega, t0, t1),)
    if inverse:
        steps = tuple((tuple(-q for q in w), a, b) for w, a, b in reversed(steps))
    error = Q(0)
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
'''

QUAT_OLD = '''def _representative_pose(segments, operator_goal, arena):
    quaternion, error = (Q(1), Q(0), Q(0), Q(0)), Q(0)
    if not segments:
        return quaternion, error
    goal = operator_goal/(8*len(segments))
    for record in segments:
        omega = tuple(map(W._decode, record['angular_velocity_rad_s']))
        duration = W._decode(record['end_time_s'])-W._decode(record['start_time_s'])
        q, delta = _segment_quaternion(omega, duration, goal, arena)
        with V._work((*quaternion, *q, error, delta), arena.resource):
            quaternion = _qmul(q, quaternion)
            error = (1+delta)*error+delta
'''
QUAT_NEW = '''# Pose width (b-quat): the product is rounded after every segment with a nonzero
# error to a dyadic quantum <= 2**-POSE_ROUND_GUARD_QUAT of that segment's error.
POSE_ROUND_GUARD_QUAT = 12


def _pose_round_axis(rates):
    """The first nonzero rate if every nonzero rate is exactly parallel to it, else None."""
    moving = [w for w in rates if any(w)]
    if not moving or any(len(w) != 3 or any(type(q) not in (int, Q) for q in w) for w in moving):
        return None
    if any(any(O._cross(w, moving[0])) for w in moving[1:]):
        return None
    return moving[0]


def _pose_round(quaternion, error, delta, axis):
    """The rounded product and its outward error (exact; delta > 0)."""
    quantum = Q(2)**(W._floor_log2(delta)-POSE_ROUND_GUARD_QUAT)
    if axis is None:
        quaternion = W._round_to(quaternion, quantum)
    else:
        # (c1, s1 k)(c2, s2 k) = (c1 c2 - s1 s2 |k|^2, (c1 s2 + c2 s1) k): the
        # product of coaxial factors is (w, s k) exactly. Rounding w and s keeps
        # it so; |ds k|_2 <= q_s/2*|k|_1 <= quantum/2.
        j = max(range(3), key=lambda i: abs(axis[i]))
        s = quaternion[1+j]/axis[j]
        if any(quaternion[1+i] != s*axis[i] for i in range(3)):
            raise V.VolumeError('coaxial pose product left its exact axis')
        step = Q(2)**(W._floor_log2(quantum)-W._ceil_log2(sum(map(abs, axis))))
        s = round(s/step)*step
        quaternion = (round(quaternion[0]/quantum)*quantum, *(s*k for k in axis))
    return quaternion, W._round_up(error+quantum, quantum)


def _representative_pose(segments, operator_goal, arena):
    quaternion, error = (Q(1), Q(0), Q(0), Q(0)), Q(0)
    if not segments:
        return quaternion, error
    goal = operator_goal/(8*len(segments))
    axis = _pose_round_axis([tuple(map(W._decode, record['angular_velocity_rad_s'])) for record in segments])
    for record in segments:
        omega = tuple(map(W._decode, record['angular_velocity_rad_s']))
        duration = W._decode(record['end_time_s'])-W._decode(record['start_time_s'])
        q, delta = _segment_quaternion(omega, duration, goal, arena)
        with V._work((*quaternion, *q, error, delta), arena.resource):
            quaternion = _qmul(q, quaternion)
            error = (1+delta)*error+delta
            if delta:
                quaternion, error = _pose_round(quaternion, error, delta, axis)
'''

EDITS = {
    'integration_wall_measures.py': ((WALL_OLD, WALL_NEW),),
    'integration_exterior_mesh.py': ((QUAT_OLD, QUAT_NEW),),
}


def _transform(name, source, allow_unreviewed_input):
    if MARKER[name] in source:
        raise ValueError('pose width transform already applied to '+name)
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256[name]:
        raise ValueError(name+' input is not the reviewed module')
    for old, new in EDITS[name]:
        if source.count(old) != 1:
            raise ValueError('pose width anchor must occur exactly once in %s: %s' % (name, old.strip()[:60]))
        source = source.replace(old, new)
    return source


def transform_wall_measures(source, *, allow_unreviewed_input=False):
    return _transform('integration_wall_measures.py', source, allow_unreviewed_input)


def transform_exterior_mesh(source, *, allow_unreviewed_input=False):
    return _transform('integration_exterior_mesh.py', source, allow_unreviewed_input)


TRANSFORMS = {
    'integration_wall_measures.py': transform_wall_measures,
    'integration_exterior_mesh.py': transform_exterior_mesh,
}
