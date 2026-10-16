"""Refuter wr1 spot checks (read-only on the runtime). Usage: python -B -I refute_checks.py <T>"""
import sys
from fractions import Fraction as Q
from pathlib import Path

T = Path(sys.argv[1])
sys.path.insert(0, str(T/'ps'/'scripts'))
import rc1_env  # noqa: E402
rc1_env.install('frozen:'+str(T/'ps'/'c'/'wr1'))
from atlas_tectonics import integration_exterior_mesh as E  # noqa: E402
from atlas_tectonics import integration_spatial_pressure as P  # noqa: E402
from atlas_tectonics import integration_volume as V  # noqa: E402
from atlas_tectonics import integration_volume_bounds as B  # noqa: E402
from atlas_tectonics import integration_wall_measures as W  # noqa: E402
from atlas_tectonics.resources import WorkBudget  # noqa: E402

budget = WorkBudget(1 << 32)
fails = []


def req(ok, msg):
    if not ok:
        fails.append(msg)
        print('FAIL', msg)


def enc(v):
    return V._encoded(Q(v))


def seg(w, t0, t1):
    return dict(angular_velocity_rad_s=[enc(x) for x in w], start_time_s=enc(t0), end_time_s=enc(t1))


def old_pose(segments, goal, arena):
    quaternion, error = (Q(1), Q(0), Q(0), Q(0)), Q(0)
    g = goal/(8*len(segments))
    for r in segments:
        omega = tuple(map(W._decode, r['angular_velocity_rad_s']))
        d = W._decode(r['end_time_s'])-W._decode(r['start_time_s'])
        q, delta = E._segment_quaternion(omega, d, g, arena)
        quaternion = E._qmul(q, quaternion)
        error = (1+delta)*error+delta
    return quaternion, error


def old_vec(vector, omega, t0, t1, level, arena, prior=(), inverse=False):
    steps = tuple((w, d, d) for w, d in prior)+((omega, t0, t1),)
    if inverse:
        steps = tuple((tuple(-q for q in w), a, b) for w, a, b in reversed(steps))
    error = Q(0)
    for w, a, b in steps:
        vector, delta = W._rotated_normal(vector, w, a, b, level, arena)
        error += delta
    return vector, error


def n2(a, b):
    return sum((x-y)**2 for x, y in zip(a, b))


k = tuple(Q(float(v)) for v in (0.36, -0.48, 0.8))
rate = Q(float(3.17e-15))
D = Q(float(3.15576e13))
goal = Q(1, 10**20)
with B._Arena(budget) as arena:
    # 1. delta rule
    ray = tuple(Q(float(v)) for v in (0.6, 0.0, 0.8))
    v, e = W._pose_vector(ray, tuple(rate*x for x in k), Q(0), Q(0), 24, arena)
    req(v == ray and e == 0 and type(e) is Q, 'delta rule t0=t1=0: %r %r' % (v == ray, e))
    # 2. coaxial histories with scaled / antiparallel / zero / zero-duration segments
    scales = [Q(1), Q(-3, 7), Q(float(2.5)), Q(0), Q(-1), Q(float(1e-3))]
    for n in (1, 3, 6, 40):
        segs = []
        for i in range(n):
            c = scales[i % len(scales)]
            w = tuple(c*rate*x for x in k)
            t0 = Q(i)*D
            t1 = t0 if i % 5 == 4 else t0+D
            segs.append(seg(w, t0, t1))
        quat, err4 = E._representative_pose(segs, goal, arena)
        rates = [tuple(map(W._decode, s['angular_velocity_rad_s'])) for s in segs]
        rot = V.CartesianCell((0, 0, 0), (1, 1, 1), budget=budget).rotated(quat, budget=budget).basis
        ax = P._common_axis(rot, rates)
        req(ax is not None, 'coaxial axis lost n=%d' % n)
        oq, oe = old_pose(segs, goal, arena)
        e_new = err4/4
        req(e_new >= oe and n2(quat, oq) <= (e_new-oe)**2, 'quat enclosure n=%d' % n)
        req(e_new <= oe*(1+Q(1, 2**11)), 'quat share n=%d' % n)
    # 3. non-coaxial history: componentwise, enclosure
    j = tuple(Q(float(v)) for v in (0.8, 0.6, 0.0))
    segs = [seg(tuple(rate*x for x in (k if i % 2 else j)), Q(i)*D, Q(i+1)*D) for i in range(7)]
    quat, err4 = E._representative_pose(segs, goal, arena)
    oq, oe = old_pose(segs, goal, arena)
    e_new = err4/4
    req(e_new >= oe and n2(quat, oq) <= (e_new-oe)**2, 'quat enclosure alt')
    # 4. ray: forward and inverse, levels 0 and 24, prior histories
    prior = tuple((tuple(rate*x for x in (k if i % 2 else j)), D) for i in range(6))
    for level in (0, 3, 24):
        for inverse in (False, True):
            for a, b in ((Q(0), D), (D/3, D/2), (Q(0), Q(0))):
                nv, ne = W._pose_vector(ray, tuple(rate*x for x in j), a, b, level, arena, prior, inverse=inverse)
                ov, oe = old_vec(ray, tuple(rate*x for x in j), a, b, level, arena, prior, inverse)
                req(ne >= oe and n2(nv, ov) <= (ne-oe)**2,
                    'ray enclosure L%d inv=%s a=%s b=%s' % (level, inverse, a, b))
                req(all(type(x) is Q for x in nv) and type(ne) is Q, 'ray types')
    # 5. end(n) == start(n+1)
    w_n, w_m = tuple(rate*x for x in j), tuple(rate*x for x in k)
    p0 = prior[:3]
    for level in (0, 24):
        for inverse in (False, True):
            end = W._pose_vector(ray, w_n, D, D, level, arena, p0, inverse=inverse)
            start = W._pose_vector(ray, w_m, Q(0), Q(0), level, arena, p0+((w_n, D),), inverse=inverse)
            req(end == start, 'end(n)==start(n+1) L%d inv=%s' % (level, inverse))
    # 6. a single-step vector at an exact-parallel later step keeps delta == 0
    v1, e1 = W._pose_vector(k, w_m, Q(0), D, 0, arena, ((w_m, D),))
    req(v1 == k and e1 == 0, 'axial ray stays exact')

print('REFUTER CHECKS', 'PASS' if not fails else 'FAIL %d' % len(fails))
