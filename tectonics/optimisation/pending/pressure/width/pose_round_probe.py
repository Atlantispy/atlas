"""Width probe for the pose rounding design (T/ps/width, 16 Oct). Synthetic inputs only; no state.

Usage: python -B pose_round_probe.py frozen:<folder>|test:<folder> OUT_JSON [STEPS ...]

Calls the runtime's UNCHANGED step functions (integration_wall_measures._rotated_normal,
integration_exterior_mesh._segment_quaternion and _qmul) in two compositions over n identical
coaxial steps (pose_width_steps.py's representative plate rate and 1 Myr binary64 interval):
  exact    the current composition (_pose_vector / _representative_pose, called as they are)
  rounded  the proposed composition: after each step that moved the value, round every component
           to the nearest multiple of a dyadic quantum and add that quantum to the error radius:
             ray:        q = 2**(floor(log2 max|v_in|) - (32+2*level) - GUARD_RAY)
             quaternion: q = 2**(floor(log2 goal) - GUARD_QUAT), goal = operator_goal/(8*n) as now
           (|r|_2 <= sqrt(k)/2 * q <= q for k = 3 or 4 components; see DESIGN.md)
Records the widest numerator/denominator bits, the error radii, and every rounded result as exact
rationals (hex num/den strings) so check_round_mpmath.py can test the enclosure independently.
The exact composition is run only up to EXACT_MAX steps (its width grows by ~547-1291 bits a step).
"""
import json
import sys
from fractions import Fraction as Q
from pathlib import Path

GUARD_RAY = 8
GUARD_QUAT = 7
EXACT_MAX = 12


def bits(values):
    return max(max(abs(v.numerator).bit_length(), v.denominator.bit_length()) for v in values)


def floor_log2(x):
    """floor(log2 x) for a positive rational, exactly."""
    e = x.numerator.bit_length()-x.denominator.bit_length()
    return e-1 if Q(2)**e > x else e


def round_to(values, quantum):
    return tuple(round(v/quantum)*quantum for v in values)


def rounded_pose_vector(W, vector, omega, t0, t1, level, arena, prior=()):
    """The proposed _pose_vector: identical steps, plus a recorded dyadic rounding after each moving step."""
    steps = tuple((w, duration, duration) for w, duration in prior)+((omega, t0, t1),)
    error, added = Q(0), Q(0)
    for w, a, b in steps:
        before = vector
        norm = max(map(abs, vector))
        vector, delta = W._rotated_normal(vector, w, a, b, level, arena)
        error += delta
        if vector is not before:
            quantum = Q(2)**(floor_log2(norm)-(32+2*level)-GUARD_RAY)
            vector = round_to(vector, quantum)
            error += quantum
            added += quantum
    return vector, error, added


def rounded_representative_pose(E, W, segments, operator_goal, arena):
    """The proposed _representative_pose: identical segments and check, plus a recorded rounding per product."""
    quaternion, error, added = (Q(1), Q(0), Q(0), Q(0)), Q(0), Q(0)
    goal = operator_goal/(8*len(segments))
    quantum = Q(2)**(floor_log2(goal)-GUARD_QUAT)
    for record in segments:
        omega = tuple(map(W._decode, record['angular_velocity_rad_s']))
        duration = W._decode(record['end_time_s'])-W._decode(record['start_time_s'])
        q, delta = E._segment_quaternion(omega, duration, goal, arena)
        quaternion = round_to(E._qmul(q, quaternion), quantum)
        error = (1+delta)*error+delta+quantum
        added += quantum
    if error >= 1 or 4*error > operator_goal:
        raise ValueError('rational pose failed its derived placement budget')
    return quaternion, 4*error, 4*added


def text(q):
    return '%x/%x' % (q.numerator, q.denominator)    # hex: no decimal digit limit


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
    import rc1_env
    rc1_env.install(sys.argv[1])
    out = Path(sys.argv[2])
    counts = [int(s) for s in sys.argv[3:]] or [1, 2, 3, 6, 12, 50, 200, 1000]
    from atlas_tectonics import integration_exterior_mesh as E
    from atlas_tectonics import integration_volume as V
    from atlas_tectonics import integration_volume_bounds as B
    from atlas_tectonics import integration_wall_measures as W
    from atlas_tectonics.resources import WorkBudget
    budget = WorkBudget(1 << 32)
    axis = (0.36, -0.48, 0.8)
    rate = 3.17e-15
    omega = tuple(Q(float(rate*a)) for a in axis)
    duration = Q(float(3.15576e13))
    ray = tuple(Q(float(v)) for v in (0.6, 0.0, 0.8))
    operator_goal = Q(1, 2**52)
    rows = []
    for n in counts:
        with B._Arena(budget) as arena:
            segments = [dict(angular_velocity_rad_s=[V._encoded(q) for q in omega],
                             start_time_s=V._encoded(Q(0)), end_time_s=V._encoded(duration))]*n
            prior = ((omega, duration),)*n
            zero = (Q(0),)*3
            row = dict(steps=n)
            rq, rerr, radded = rounded_representative_pose(E, W, segments, operator_goal, arena)
            row.update(quat_rounded_bits=bits(rq), quat_rounded_error=float(rerr), quat_error_bits=bits((rerr,)),
                       quat_added_error=float(radded), quat_added_share_of_goal=float(radded/operator_goal),
                       quat_rounded=[text(v) for v in rq], quat_rounded_error_exact=text(rerr))
            if n <= EXACT_MAX:
                eq, eerr = E._representative_pose(segments, operator_goal, arena)
                row.update(quat_exact_bits=bits(eq), quat_exact_error=float(eerr),
                           quat_rounded_minus_exact=float(max(abs(a-b) for a, b in zip(rq, eq))))
            for level in (0, 24):
                # End mesh: every step is a prior (endpoint) rotation and the current rate is zero.
                rv, verr, vadded = rounded_pose_vector(W, ray, zero, duration, duration, level, arena, prior)
                row.update({'ray%d_rounded_bits' % level: bits(rv), 'ray%d_rounded_error' % level: float(verr),
                            'ray%d_error_bits' % level: bits((verr,)),
                            'ray%d_added_error' % level: float(vadded),
                            'ray%d_added_share' % level: float(vadded/(verr-vadded)) if verr > vadded else None,
                            'ray%d_rounded' % level: [text(v) for v in rv],
                            'ray%d_rounded_error_exact' % level: text(verr)})
                if n <= EXACT_MAX:
                    ev, eerr = W._pose_vector(ray, zero, duration, duration, level, arena, prior)
                    row.update({'ray%d_exact_bits' % level: bits(ev), 'ray%d_exact_error' % level: float(eerr),
                                'ray%d_rounded_minus_exact' % level: float(max(abs(a-b) for a, b in zip(rv, ev)))})
            rows.append(row)
            print({k: v for k, v in row.items() if not isinstance(v, (list, str))}, flush=True)
    out.write_text(json.dumps(dict(omega=[text(q) for q in omega], duration=text(duration), ray=[text(q) for q in ray],
                                   operator_goal=text(operator_goal), guard_ray=GUARD_RAY, guard_quat=GUARD_QUAT,
                                   rows=rows), indent=1), encoding='utf8')


if __name__ == '__main__':
    main()
