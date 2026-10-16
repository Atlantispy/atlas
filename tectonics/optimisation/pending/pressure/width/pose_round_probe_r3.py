"""Width probe r3 for the pose rounding design (T/ps/width, 16 Oct). Synthetic inputs only; no state.

Usage: python -B pose_round_probe_r3.py frozen:<folder>|test:<folder> OUT_JSON

r3 applies the refuter's fixes (STATE.md 16 Oct 15:49) to the r2 rules. Both quanta now follow the step's
ACTUAL error, and nothing is rounded after an exact step (delta == 0):
  ray:        q = 2**(floor_log2(min(delta, t_L)) - GUARD_RAY), t_L = max|v_in|/2**(32+2L), the step's target
  quaternion: q = 2**(floor_log2(delta) - GUARD_QUAT); when every nonzero step rate is exactly parallel to one
              k (the first), the product is held as (w, s*k) and only w and s are rounded, s to
              q_s = 2**(floor_log2(q) - ceil_log2(|k|_1)), so the vector part stays exactly parallel to k and
              the posed-boundary axis certificate (spatial_pressure._common_axis) survives
The radius is then rounded outward to the same quantum (round_up(e+q, q)), as in r2.

Calls the runtime's UNCHANGED _rotated_normal, _segment_quaternion, _qmul, CartesianCell.rotated and
_common_axis. Cases: one coaxial history at the representative rate and at two slow rates (5.5e-17 and
1e-19 rad/s); one alternating non-coaxial history. Per row it records widths, the added share of the actual
certified error (against the unrounded recurrence, in binary64), the axis certificate (and, as the mutant
that must lose it, r2's componentwise rounding of the same coaxial history), the delta == 0 rule at
t0 = t1 = 0, end(n) == start(n+1), a swept current step, and every rounded result as hex rationals for
check_round_mpmath_r3.py.
"""
import json
import sys
from fractions import Fraction as Q
from pathlib import Path

GUARD_RAY = 12
GUARD_QUAT = 12
EXACT_MAX = 6
AXIS = (0.36, -0.48, 0.8)
OTHER_AXIS = (0.8, 0.6, 0.0)
CASES = (('rep', 3.17e-15, 'coaxial', (1, 2, 6, 50, 200, 1000)),
         ('slow55', 5.5e-17, 'coaxial', (1, 50, 1000)),
         ('slow19', 1e-19, 'coaxial', (1, 50, 1000)),
         ('alt', 3.17e-15, 'alternating', (2, 6, 50, 200)))
OPERATOR_GOAL = Q(1, 10**20)        # D:772 and P's max_operator_error in production


def bits(values):
    return max(max(abs(v.numerator).bit_length(), v.denominator.bit_length()) for v in values)


def floor_log2(x):
    """floor(log2 x) for a positive rational, exactly."""
    e = x.numerator.bit_length()-x.denominator.bit_length()
    return e-1 if Q(2)**e > x else e


def ceil_log2(x):
    e = floor_log2(x)
    return e if Q(2)**e == x else e+1


def round_to(values, quantum):
    return tuple(round(v/quantum)*quantum for v in values)


def round_up(value, quantum):
    """The least multiple of quantum >= value (outward for a nonnegative radius)."""
    return -((-value)//quantum)*quantum


def rounded_pose_vector(W, vector, omega, t0, t1, level, arena, prior=()):
    """The proposed _pose_vector: identical steps; after each step with delta > 0 a delta-relative rounding."""
    steps = tuple((w, duration, duration) for w, duration in prior)+((omega, t0, t1),)
    error, reference = Q(0), 0.0
    for w, a, b in steps:
        target = max(map(abs, vector))/Q(2**(32+2*level))
        vector, delta = W._rotated_normal(vector, w, a, b, level, arena)
        error += delta
        reference += float(delta)
        if delta:
            quantum = Q(2)**(floor_log2(min(delta, target))-GUARD_RAY)
            vector = round_to(vector, quantum)
            error = round_up(error+quantum, quantum)
    return vector, error, reference


def coaxial_axis(O, rates):
    moving = [w for w in rates if any(w)]
    if moving and not any(any(O._cross(w, moving[0])) for w in moving[1:]):
        return moving[0]
    return None


def rounded_representative_pose(E, O, W, segments, operator_goal, arena, *, keep_axis=True):
    """The proposed _representative_pose: identical segments and check; delta-relative rounding per product."""
    quaternion, error, reference = (Q(1), Q(0), Q(0), Q(0)), Q(0), 0.0
    goal = operator_goal/(8*len(segments))
    rates = [tuple(map(W._decode, record['angular_velocity_rad_s'])) for record in segments]
    axis = coaxial_axis(O, rates) if keep_axis else None
    for omega, record in zip(rates, segments):
        duration = W._decode(record['end_time_s'])-W._decode(record['start_time_s'])
        q, delta = E._segment_quaternion(omega, duration, goal, arena)
        quaternion = E._qmul(q, quaternion)
        exact = (1+delta)*error+delta
        reference = (1+float(delta))*reference+float(delta)
        if not delta:
            error = exact
            continue
        quantum = Q(2)**(floor_log2(delta)-GUARD_QUAT)
        if axis is None:
            quaternion = round_to(quaternion, quantum)
        else:
            j = max(range(3), key=lambda i: abs(axis[i]))
            s = quaternion[1+j]/axis[j]
            if any(quaternion[1+i] != s*axis[i] for i in range(3)):
                raise ValueError('coaxial product left the axis')
            q_s = Q(2)**(floor_log2(quantum)-ceil_log2(sum(map(abs, axis))))
            quaternion = (round(quaternion[0]/quantum)*quantum, *(round(s/q_s)*q_s*k for k in axis))
        error = round_up(exact+quantum, quantum)
    if error >= 1 or 4*error > operator_goal:
        raise ValueError('rational pose failed its derived placement budget')
    return quaternion, 4*error, 4*reference


def text(q):
    return '%x/%x' % (q.numerator, q.denominator)    # hex: no decimal digit limit


def share(error, reference):
    return (float(error)-reference)/reference if reference else None


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
    import rc1_env
    rc1_env.install(sys.argv[1])
    out = Path(sys.argv[2])
    from atlas_tectonics import integration_exterior_mesh as E
    from atlas_tectonics import integration_spatial_pressure as P
    from atlas_tectonics import integration_volume as V
    from atlas_tectonics import integration_volume_bounds as B
    from atlas_tectonics import integration_volume_overlap as O
    from atlas_tectonics import integration_wall_measures as W
    from atlas_tectonics.resources import WorkBudget
    budget = WorkBudget(1 << 32)
    duration = Q(float(3.15576e13))
    ray = tuple(Q(float(v)) for v in (0.6, 0.0, 0.8))
    zero = (Q(0),)*3

    def axis_kept(quaternion, history):
        rotation = V.CartesianCell((0, 0, 0), (1, 1, 1), budget=budget).rotated(quaternion, budget=budget).basis
        return P._common_axis(rotation, history) is not None

    cases, failures = [], []
    for name, rate, kind, counts in CASES:
        pattern = [tuple(Q(float(rate*a)) for a in AXIS)]
        if kind == 'alternating':
            pattern.append(tuple(Q(float(rate*a)) for a in OTHER_AXIS))
        rows = []
        for n in counts:
            rates = [pattern[i % len(pattern)] for i in range(n)]
            history = tuple((w, duration) for w in rates)
            segments = [dict(angular_velocity_rad_s=[V._encoded(q) for q in w], start_time_s=V._encoded(Q(0)),
                             end_time_s=V._encoded(duration)) for w in rates]
            row = dict(steps=n)
            with B._Arena(budget) as arena:
                rq, rerr, rref = rounded_representative_pose(E, O, W, segments, OPERATOR_GOAL, arena)
                row.update(quat_bits=bits(rq), quat_error_bits=bits((rerr,)), quat_error=float(rerr),
                           quat_reference_error=rref, quat_added_share=share(rerr, rref),
                           quat_added_share_of_goal=(float(rerr)-rref)/float(OPERATOR_GOAL),
                           quat_axis_kept=axis_kept(rq, rates), quat=[text(v) for v in rq], quat_error_exact=text(rerr))
                mq, _, _ = rounded_representative_pose(E, O, W, segments, OPERATOR_GOAL, arena, keep_axis=False)
                row.update(mutant_componentwise_axis_kept=axis_kept(mq, rates))
                if n <= EXACT_MAX:
                    eq, eerr = E._representative_pose(segments, OPERATOR_GOAL, arena)
                    row.update(quat_exact_bits=bits(eq), quat_exact_error=float(eerr),
                               quat_exact_axis_kept=axis_kept(eq, rates))
                for level in (0, 24):
                    # End mesh: every step is a prior (endpoint) rotation and the current rate is zero.
                    rv, verr, vref = rounded_pose_vector(W, ray, zero, duration, duration, level, arena, history)
                    row.update({'ray%d_bits' % level: bits(rv), 'ray%d_error_bits' % level: bits((verr,)),
                                'ray%d_error' % level: float(verr), 'ray%d_added_share' % level: share(verr, vref),
                                'ray%d' % level: [text(v) for v in rv], 'ray%d_error_exact' % level: text(verr)})
                    # Swept current step [0, duration] after n-1 priors (delta includes half*|w x v|).
                    sv, serr, sref = rounded_pose_vector(W, ray, rates[-1], Q(0), duration, level, arena,
                                                         history[:-1])
                    row.update({'sweep%d_bits' % level: bits(sv), 'sweep%d_added_share' % level: share(serr, sref),
                                'sweep%d' % level: [text(v) for v in sv], 'sweep%d_error_exact' % level: text(serr)})
                    # end(n) through the current step at t0 = t1 = duration equals start(n+1) at t0 = t1 = 0.
                    end = rounded_pose_vector(W, ray, rates[-1], duration, duration, level, arena, history[:-1])
                    start = rounded_pose_vector(W, ray, pattern[n % len(pattern)], Q(0), Q(0), level, arena, history)
                    row['end_equals_next_start%d' % level] = end[:2] == start[:2] == (rv, verr)
                    if n <= EXACT_MAX:
                        ev, eerr = W._pose_vector(ray, zero, duration, duration, level, arena, history)
                        row.update({'ray%d_exact_bits' % level: bits(ev), 'ray%d_exact_error' % level: float(eerr)})
            coaxial = kind == 'coaxial' or n == 1
            expected = dict(quat_axis_kept=coaxial, end_equals_next_start0=True, end_equals_next_start24=True)
            if coaxial:
                expected['mutant_componentwise_axis_kept'] = False
            if n <= EXACT_MAX:
                expected['quat_exact_axis_kept'] = coaxial
            for key, want in expected.items():
                if row[key] is not want:
                    failures.append((name, n, key, row[key]))
            print(name, {k: v for k, v in row.items() if not isinstance(v, (list, str))}, flush=True)
            rows.append(row)
        cases.append(dict(name=name, rate=rate, kind=kind, pattern=[[text(q) for q in w] for w in pattern], rows=rows))
    # The delta == 0 rule: a zero-time step returns delta 0 and its input values, so nothing is rounded.
    with B._Arena(budget) as arena:
        w = tuple(Q(float(3.17e-15*a)) for a in AXIS)
        v, delta = W._rotated_normal(ray, w, Q(0), Q(0), 24, arena)
        rv, rerr, _ = rounded_pose_vector(W, ray, w, Q(0), Q(0), 24, arena)
    delta_rule = delta == 0 and tuple(v) == ray and rv == ray and rerr == 0
    if not delta_rule:
        failures.append(('delta_rule', delta, rerr))
    print('delta == 0 rule at t0 = t1 = 0:', delta_rule)
    print('PROBE CHECKS PASS' if not failures else 'PROBE CHECKS FAIL %r' % failures, flush=True)
    out.write_text(json.dumps(dict(duration=text(duration), ray=[text(q) for q in ray],
                                   operator_goal=text(OPERATOR_GOAL), guard_ray=GUARD_RAY, guard_quat=GUARD_QUAT,
                                   delta_rule=delta_rule, failures=[repr(f) for f in failures], cases=cases),
                              indent=1), encoding='utf8')
    raise SystemExit(1 if failures else 0)


if __name__ == '__main__':
    main()
