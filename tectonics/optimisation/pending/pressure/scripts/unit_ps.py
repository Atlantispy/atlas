"""Unit checks for the T/ps candidates (no admission, no stage): seconds of CPU.

1. P3: the candidate coupling helpers against the base composed-r2 module loaded beside them
   (atlas_tectonics.ps_base_coupling, same package imports): _mul, _scale, _jet_is_constant,
   _dyadic_outward and _jet_outward on random exact inputs, including reversed, mixed-type,
   equal, zero and negative intervals. Results must match in type and exact value (a Fraction's
   numerator and denominator); exceptions must match in type.
2. P1 encoding: _enc/_dec round trip keeps every type and value; noncanonical rationals, unknown
   tags and objects=False cells/poses are refused.
3. P1 request shape: check_request accepts the one shape and refuses variants; the transformed
   binding routes only that schema to it.
4. Transforms: each refuses its own output (applied twice) and an unpinned input.
5. P1 r3 (refuter finding 4): _decoded_bound is the interface route's bound; _open_ledger books it
   on the child ledger and HOLDS it until the batch's stack closes (also after a garbage
   collection); a ledger one byte too small refuses. scripts/mutants_p1r3.py runs the same check
   on mutants that must fail.
Usage: unit_ps.py <candidate frozen:folder> <base composed-r2 folder>
"""
import importlib.util
import random
import sys
from fractions import Fraction as Q
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc1_env  # noqa: E402

PS = HERE.parent
FAILS = []


def check(name, condition):
    if not condition:
        FAILS.append(name)
        print('FAIL', name, flush=True)


def same(x, y):
    if type(x) is not type(y):
        return False
    if type(x) in (tuple, list):
        return len(x) == len(y) and all(same(a, b) for a, b in zip(x, y, strict=True))
    if type(x) is Q:
        # value AND the component types (a numpy-backed Fraction keeps numpy components)
        return (x.numerator == y.numerator and x.denominator == y.denominator
                and type(x.numerator) is type(y.numerator) and type(x.denominator) is type(y.denominator))
    return x == y


def outcome(fn, *args):
    try:
        return 'ok', fn(*args)
    except Exception as error:  # noqa: BLE001
        return 'raise', type(error).__name__


def agree(name, fa, fb, *args):
    a, b = outcome(fa, *args), outcome(fb, *args)
    ok = a[0] == b[0] and (same(a[1], b[1]) if a[0] == 'ok' else a[1] == b[1])
    check('%s%r' % (name, args), ok)


def rational(rng):
    kind = rng.random()
    if kind < 0.1:
        return Q(0)
    if kind < 0.2:
        return rng.choice((Q(1), Q(-1), Q(1, 2), Q(-1, 4)))
    n = rng.randint(-10**rng.randint(1, 40), 10**rng.randint(1, 40))
    d = rng.randint(1, 10**rng.randint(1, 40))
    return Q(n, d)


def value(rng):
    q = rational(rng)
    return int(q) if rng.random() < 0.15 and q.denominator == 1 else q


def open_ledger_failures(W, RS, open_ledger):
    """Section 5; returns the failing checks (empty when the booking is held and bounded)."""
    import gc
    from contextlib import ExitStack
    from atlas_tectonics.integration_routing_views import _decoded_json_capacity
    fails = []
    args = dict(gravity=Q(-98, 10), support_radius=Q(5), radius=Q(6), width=Q(1, 2), max_leaves=64)
    record = dict(schema=W.INPUT_SCHEMA, regions=W._enc([dict(density=Q(33, 10), name='r%d' % i) for i in range(40)]),
                  profiles=W._enc([Q(i, 7) for i in range(50)]), native_box=W._enc(None),
                  reservoirs=W._enc([]), args=W._enc(args), walls=W._enc([]))
    raw = W.canonical(record)
    ids = [W.hashlib.sha256(raw).hexdigest()]
    inputs = {ids[0]: raw}
    decoded = W._decoded_bound(raw)
    if decoded != _decoded_json_capacity(raw)+65536+4*len(raw):
        fails.append('decoded bound is not the interface route bound')
    with ExitStack() as holds:
        ledger, shared = open_ledger(lambda: RS.WorkBudget(1 << 30), holds, inputs, ids, decoded)
        gc.collect()
        held = ledger.reserved_bytes
        if held < decoded:
            fails.append('decoded bound not held after decode + gc: %d < %d' % (held, decoded))
        if shared['args'] != args or len(shared['regions']) != 40:
            fails.append('decoded inputs differ')
    if ledger.reserved_bytes > held-decoded:
        fails.append('booking not released when the stack closes: %d' % ledger.reserved_bytes)
    with ExitStack() as holds:
        small = outcome(open_ledger, lambda: RS.WorkBudget(decoded-1), holds, inputs, ids, decoded)
    if small[0] != 'raise':
        fails.append('a ledger one byte too small was accepted')
    return fails


def main():
    candidate, base = sys.argv[1], Path(sys.argv[2])
    rc1_env.install(candidate)
    from atlas_tectonics import integration_pressure_coupling as C
    from atlas_tectonics import integration_pressure_walls as W
    from atlas_tectonics import integration_parallel_binding as B
    spec = importlib.util.spec_from_file_location('atlas_tectonics.ps_base_coupling',
                                                  base/'src'/'atlas_tectonics'/'integration_pressure_coupling.py')
    assert spec and spec.loader
    O = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(O)
    check('base module is not the candidate', not hasattr(O, '_ZERO_PAIR') and hasattr(C, '_ZERO_PAIR'))
    rng = random.Random(20261016)
    # 1. P3
    for _ in range(20000):
        a = (value(rng), value(rng))
        b = (value(rng), value(rng))
        if rng.random() < 0.5:
            a = tuple(sorted(a))
        if rng.random() < 0.5:
            b = tuple(sorted(b))
        if rng.random() < 0.05:
            a = (a[0], a[0])
        agree('_mul', C._mul, O._mul, a, b)
        q = rng.choice((rng.randint(-5, 5), rational(rng)))
        agree('_scale', C._scale, O._scale, a, q)
        agree('_scale3', C._scale, O._scale, (value(rng), value(rng), value(rng)), q)
        agree('_dyadic', C._dyadic_outward, O._dyadic_outward, a, 1 << rng.randint(0, 200))
        z = rng.choice(((0, 0), (Q(0), Q(0)), (Q(0), 0), (Q(1), Q(0))))
        jet = ((a[0], a[0] if rng.random() < 0.5 else a[1]), z, rng.choice(((0, 0), (Q(0), Q(0)), z)))
        agree('_jet_is_constant', C._jet_is_constant, O._jet_is_constant, jet)
        jet = (tuple(sorted(a)), tuple(sorted(b)), tuple(sorted((value(rng), value(rng)))))
        agree('_jet_outward', C._jet_outward, O._jet_outward, jet)
    # P3 refuter (16 Oct): min/max ties are visible only through component types, e.g. a
    # Fraction built from a numpy integer; min() keeps the first of two equal products.
    import numpy as np
    tie = (Q(-1, 2), Q(np.int64(3)))
    agree('_mul-tie', C._mul, O._mul, tie, tie)
    agree('_mul-tie2', C._mul, O._mul, (Q(np.int64(-3)), Q(1, 2)), (Q(-1, 2), Q(np.int64(3))))
    agree('_scale-tie', C._scale, O._scale, (Q(np.int64(2)), Q(2)), 1)
    # out-of-contract denominators take Fraction's own constructor (same value or error as the base)
    for d in (0, -2, Q(4), np.int64(8)):
        agree('_dyadic-odd', C._dyadic_outward, O._dyadic_outward, (Q(1, 3), Q(2, 3)), d)
        agree('_dyadic-odd0', C._dyadic_outward, O._dyadic_outward, (Q(0), Q(0)), d)
    for odd in ((), (Q(1),), (Q(1), Q(2), Q(3)), [Q(1), Q(2)], (1.5, Q(2)), ('x', 'y')):
        agree('_mul-odd', C._mul, O._mul, odd, (Q(1), Q(2)))
        agree('_scale-odd', C._scale, O._scale, odd, 3)
    check('constants', same((C._ZERO, C._ONE, C._HALF, C._THIRD, C._QUARTER, C._MINUS_QUARTER),
                            (Q(0), Q(1), Q(1, 2), Q(1, 3), Q(1, 4), Q(-1, 4))))
    check('jet constants', same(C._JET_ZERO, O._jet_constant(Q(0))) and same(C._JET_ONE, O._jet_constant(Q(1))))
    # 2. encoding
    samples = [0, -1, 2**200, Q(-3, 7), Q(0), 1.5, -0.0, float('1e-300'), 'wall', None, True,
               (1, Q(1, 3), [2.5, ('a', None)]), {'b': 1, 'a': (Q(2), 3)}, [], ()]
    for sample in samples:
        back = W._dec(W._enc(sample), None)
        check('roundtrip %r' % (sample,), same(back, sample) if type(sample) is not dict else
              (type(back) is dict and list(back) == list(sample) and all(same(back[k], sample[k]) for k in sample)))
    check('float sign kept', str(W._dec(W._enc(-0.0), None)) == '-0.0')
    for bad in (['q', '0x2', '0x4'], ['z', 1], ['i'], ['c', 1, 2, 3, 4], ['d', [['a', None], ['a', None]]], 5, 'x'):
        check('refuse %r' % (bad,), outcome(W._dec, bad, None)[0] == 'raise')
    check('objects=False refuses a cell', outcome(lambda: W._dec(['c', None, None, None, None], None, objects=False))[0] == 'raise')
    check('objects=False refuses a pose', outcome(lambda: W._dec(['p', None, None, None], None, objects=False))[0] == 'raise')
    check('unsupported type refused', outcome(W._enc, object())[0] == 'raise')
    check('non-string key refused', outcome(W._enc, {1: 2})[0] == 'raise')
    # 3. request shape
    good = dict(schema=W.SCHEMA, wall=3, walls=10, inputs=['a'*64], max_leaves=4096, test=None)
    check('good request', W.check_request(good) == W.WALL_FIELDS)
    check('binding routes the schema', B.request_fields(good) == W.WALL_FIELDS)
    for change in (dict(wall=10), dict(wall=-1), dict(walls=0), dict(wall=True), dict(inputs=[]),
                   dict(inputs=['A'*64]), dict(inputs=['a'*63]), dict(max_leaves=0), dict(test='other'),
                   dict(schema='atlas.private.pressure-wall.r2'), dict(extra=1), dict(inputs=['a'*64]*(W.MAX_CHUNKS+1))):
        check('refuse request %r' % (change,), outcome(W.check_request, dict(good, **change))[0] == 'raise')
    check('missing field refused', outcome(W.check_request, {k: v for k, v in good.items() if k != 'test'})[0] == 'raise')
    other = dict(good, schema='atlas.private.pressure-wall.r2')
    check('other schema not routed', outcome(B.request_fields, other) != ('ok', W.WALL_FIELDS))
    # 4. transforms
    for name, file in (('ps_p2_spatial', 'integration_spatial_pressure.py'),
                       ('ps_p1_loop', 'integration_differential_pressure.py'),
                       ('ps_p1_binding', 'integration_parallel_binding.py'),
                       ('ps_p1_dispatch', 'integration_parallel_dispatch.py'),
                       ('ps_p3_coupling', 'integration_pressure_coupling.py')):
        tspec = importlib.util.spec_from_file_location('t_'+name, PS/'transforms'/(name+'.py'))
        assert tspec and tspec.loader
        T = importlib.util.module_from_spec(tspec)
        tspec.loader.exec_module(T)
        source = (base/'src'/'atlas_tectonics'/file).read_bytes().decode('utf8')
        once = T.transform(source)
        check(name+' refuses its output', outcome(T.transform, once)[0] == 'raise')
        check(name+' refuses an unpinned input', outcome(T.transform, source+'\n')[0] == 'raise')
        candidate_file = Path(C.__file__).parent/file
        check(name+' output is the candidate file', candidate_file.read_bytes() == once.encode('utf8'))
    # 5. P1 r3
    from atlas_tectonics import resources as RS
    for failure in open_ledger_failures(W, RS, W._open_ledger):
        check(failure, False)
    print('UNIT PASS' if not FAILS else 'UNIT FAIL %d' % len(FAILS), flush=True)
    raise SystemExit(1 if FAILS else 0)


if __name__ == '__main__':
    main()
