"""Exact check of the E (b-quat) cross-arm bounds on the actual pinned producer bodies.

Claims checked for identical inputs (segments, operator goal), before = full6 E, after = wr2 E:
  C1  e_after >= e_before                                  (stored bound pe = 4e is outward)
  C2  e_after - e_before < 2**-11 * e_before, or both zero (DESIGN section 3 precision row)
  C3  |q_after - q_before|_2 <= 2**-12 * e_before          (derived: rounding move <= quantum <= 2**-12 delta)
  C4  |q_after - q_before|_2 <= e_after - e_before         (same induction, tighter)
The function bodies are exec'd from the pinned source bytes (no transcription, no runtime import);
only V._work, the arena and O._cross/O._dot are stubbed. Exact Fractions throughout.
usage: check_equat_bound.py FULL6_E WR2_E WR2_W
"""
import ast
import contextlib
import hashlib
import sys
from fractions import Fraction as Q
from types import SimpleNamespace

PINS = {'full6_e': 'd338238e1abe11db8e01a4b4ee91f99443727fb082f9d9cb6799344e82d445f4',
        'wr2_e': '4b5b11c46d5602ab20ad46a2401ef3c34f64e281d86cdf9c1efd127e3f22840d',
        'wr2_w': 'a7a7dc432a45439aa47d912fd6d1424be7f7c1081d03bd079aa075be6550ebef'}


class VolumeError(ValueError):
    pass


def pinned(path, key):
    raw = open(path, 'rb').read()
    assert hashlib.sha256(raw).hexdigest() == PINS[key], key + ' source differs from its pin'
    return ast.parse(raw)


def functions(tree, names, namespace):
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            exec(compile(ast.Module([node], []), '<pinned>', 'exec'), namespace)
    missing = set(names) - set(namespace)
    assert not missing, missing
    # Module-level integer constants the bodies read (e.g. POSE_ROUND_GUARD_QUAT).
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                and isinstance(node.value, ast.Constant) and type(node.value.value) is int:
            namespace[node.targets[0].id] = node.value.value


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def build(e_tree, w_tree):
    V = SimpleNamespace(_work=lambda *a, **k: contextlib.nullcontext(), VolumeError=VolumeError)
    O = SimpleNamespace(_cross=cross, _dot=dot)
    w_ns = {'Q': Q, 'V': V}
    if w_tree is not None:
        functions(w_tree, ('_floor_log2', '_ceil_log2', '_round_to', '_round_up', '_decode'), w_ns)
    else:
        w_ns['_decode'] = lambda pair: Q(int(pair[0], 16), int(pair[1], 16))
    W = SimpleNamespace(**{k: v for k, v in w_ns.items() if k.startswith('_')})
    ns = {'Q': Q, 'V': V, 'O': O, 'W': W}
    names = ['_qmul', '_segment_quaternion', '_representative_pose']
    if w_tree is not None:
        names += ['_pose_round_axis', '_pose_round']
    functions(e_tree, names, ns)
    return ns['_representative_pose']


def enc(q):
    q = Q(q)
    return [hex(q.numerator), hex(q.denominator)]


def segments(rates, durations):
    out, t = [], Q(0)
    for w, d in zip(rates, durations):
        out.append({'angular_velocity_rad_s': [enc(x) for x in w], 'start_time_s': enc(t), 'end_time_s': enc(t+d)})
        t += d
    return out


def main(full6_e, wr2_e, wr2_w):
    before = build(pinned(full6_e, 'full6_e'), None)
    after = build(pinned(wr2_e, 'wr2_e'), pinned(wr2_w, 'wr2_w'))
    arena = SimpleNamespace(work=lambda n: None, resource=None)
    year = Q(31_557_600)
    slow = (Q(1, 10**14), Q(-3, 10**15), Q(2, 10**14))       # rad/s, plate-like
    cases = {
        'noncoaxial-3': segments([slow, (Q(2, 10**14), Q(1, 10**14), Q(0)), (Q(-1, 10**15), Q(4, 10**14), Q(1, 10**14))],
                                 [Q(10**5)*year]*3),
        'coaxial-5': segments([tuple(k*x for x in slow) for k in (1, 2, 3, 1, 5)], [Q(2*10**5)*year]*5),
        'zero-rate': segments([(Q(0), Q(0), Q(0))]*2, [year]*2),
        'mixed-zero': segments([slow, (Q(0), Q(0), Q(0)), slow], [Q(10**5)*year]*3),
        'single': segments([slow], [Q(10**6)*year]),
        'tiny-rate': segments([(Q(1, 10**19), Q(0), Q(0))]*4, [Q(10**6)*year]*4),
    }
    goals = (Q(1, 2), Q(1, 10**6), Q(3, 10**12))
    failures = evaluated = refused = 0
    for name, segs in cases.items():
        for goal in goals:
            try:
                qb, pb = before(segs, goal, arena)
                qa, pa = after(segs, goal, arena)
            except VolumeError as error:
                failures += 1
                refused += 1
                print('%-13s goal=%-10s refused: %s' % (name, goal, error))
                continue
            evaluated += 1
            eb, ea = pb/4, pa/4
            d2 = sum((x-y)**2 for x, y in zip(qa, qb))
            c1 = ea >= eb
            c2 = (ea == eb == 0) or (eb > 0 and (ea-eb)*2**11 < eb)
            c3 = d2*2**24 <= eb*eb
            c4 = d2 <= (ea-eb)**2
            ok = c1 and c2 and c3 and c4
            failures += not ok
            ratio = float(d2**Q(1, 2) / eb) if eb else 0.0
            print('%-13s goal=%-10s C1 %s C2 %s C3 %s C4 %s |dq|/e_before=%.3e growth=%.3e' % (
                name, goal, c1, c2, c3, c4, ratio, float((ea-eb)/eb) if eb else 0.0))
    print('RESULT', 'PASS' if not failures else 'FAIL %d' % failures,
          'evaluated=%d refused=%d expected=%d' % (evaluated, refused, len(cases)*len(goals)))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:4]))
