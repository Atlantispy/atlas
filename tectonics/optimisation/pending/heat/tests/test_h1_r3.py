"""Tests for H1 r3: transforms/h1a_growth_reserve_r3.py then transforms/h1c_growth_inline_r3.py.

Run: <.r44-env python> -B -m unittest test_h1_r3   (from T/hs/tests; PYTHONHASHSEED=0)

1. Anchoring and refusals; the AST shows only reserve/q/rational and the H1 names changed.
2. Differential: the ORIGINAL helper (94dfc016) against H1a r3 + H1c r3 on random sequences of
   q(), rational() (all four operations plus invalid ones) and the integer methods, with
   cancellation, leases shrunk by others, slot/container changes and the 2**27-bit ceiling.
   After every step: result value and type (exact binary serialisation), exception type and
   message, peak_bits, operations, lease and the full resize log must be equal.
3. Regression cases for every H1 refuter finding (T/hs/refute-h1/repro_hostile.py): a type
   whose metaclass makes it equal to int; _shape set on the instance; R deleted or replaced on
   the instance; a staticmethod-wrapped base _shape; a G without mpz. Plus, for the content
   binding: R=None at first use, a gmp module whose file differs, and a rank-like subclass.
4. R3Regressions, for the H1 refuter's r2 re-check (T/hs/refute-h1/repro_identity_drift.py,
   repro_hostile_r2.py): the loaded-implementation identity stays stable across inlined calls
   (with a negative control showing the guard does see an upper-case cache); a replaced G;
   a subclass whose _integer raises; reserve() read order with deleted attributes and a
   non-int width (also for H1a r3 alone); the cache keeps only the registered module.
"""
import ast
import json
import random
import sys
import tempfile
import types
import unittest
from pathlib import Path

HS = Path(__file__).resolve().parents[1]
LAYOUT = HS/'lw'
sys.path[:0] = json.loads((LAYOUT/'control.json').read_text(encoding='utf8'))['paths']
sys.path.insert(0, str(HS/'transforms'))
import h1a_growth_reserve_r3 as H1A  # noqa: E402
import h1c_growth_inline_r3 as H1C  # noqa: E402
import gmpy2 as G  # noqa: E402
import private_heat_gmp_resources_r1 as R  # noqa: E402

SOURCE = (LAYOUT/'helpers'/'private_heat_exact_growth_r1.py').read_bytes().decode('utf8')
AFTER_A = H1A.transform(SOURCE)
AFTER_C = H1C.transform(AFTER_A)
MPZ, MPQ = type(G.mpz(0)), type(G.mpq(0))


def load(name, text):
    module = types.ModuleType(name)
    module.__file__ = str(LAYOUT/'helpers'/(name+'.py'))
    exec(compile(text, module.__file__, 'exec'), module.__dict__)
    return module


OLD = load('h1r3_old_growth', SOURCE)
NEW = load('h1r3_new_growth', AFTER_C)
ONLY_A = load('h1r3_a_growth', AFTER_A)


class Lease:
    count = 0


class Work:
    def __init__(self):
        self.lease, self.log = Lease(), []

    def resize_before_allocation_or_after_drop(self, count):
        self.log.append(count)
        if count > 1 << 42:
            raise MemoryError('fake refusal %d' % count)
        self.lease.count = count


def outcome(fn):
    try:
        value = fn()
        if type(value) is int:
            return ('ok', 'int', G.to_binary(G.mpz(value)))
        if type(value) in (MPZ, MPQ):
            return ('ok', type(value).__name__, G.to_binary(value))
        return ('ok', type(value).__name__, repr(value))
    except BaseException as error:          # noqa: B036
        return ('raise', type(error).__name__, str(error))


def operand(rng):
    k = rng.random()
    if k < 0.30:
        return G.mpq(rng.getrandbits(rng.randint(0, 600))*rng.choice((1, -1)), rng.getrandbits(rng.randint(0, 400))+1)
    if k < 0.40:
        return G.mpq(rng.getrandbits(rng.randint(0, 300)), 1 << rng.randint(0, 200))
    if k < 0.50:
        return G.mpq(0)
    if k < 0.65:
        return G.mpz(rng.getrandbits(rng.randint(0, 700))*rng.choice((1, -1)))
    if k < 0.80:
        return rng.getrandbits(rng.randint(0, 500))*rng.choice((1, -1))
    if k < 0.86:
        return rng.choice((0, G.mpz(0), 1, -1))
    return rng.choice((True, 1.5, 'x', None, G.mpfr(2), (1, 2)))


def integer(rng):
    v = operand(rng)
    return v if type(v) in (int, MPZ) else G.mpz(rng.getrandbits(64)+1)


def make(m, cls=None, cancel=None):
    w = Work()
    return (cls or m.Arithmetic)(w, G, scalar_slots=77, container_bytes=999, initial_bits=8, cancelled=cancel), w


class TransformTests(unittest.TestCase):
    def test_anchor_and_refusals(self):
        compile(AFTER_C, 'x.py', 'exec')
        with self.assertRaises(ValueError):
            H1C.transform(SOURCE)                      # must follow H1a r3
        with self.assertRaises(ValueError):
            H1C.transform(AFTER_C, allow_unreviewed_input=True)

    def test_only_reserve_q_rational_and_h1_names_change(self):
        a, c = ast.parse(SOURCE), ast.parse(AFTER_C)
        ca = next(n for n in a.body if isinstance(n, ast.ClassDef))
        cc = next(n for n in c.body if isinstance(n, ast.ClassDef))
        ma = {n.name: ast.dump(n) for n in ca.body if isinstance(n, ast.FunctionDef)}
        mc = {n.name: ast.dump(n) for n in cc.body if isinstance(n, ast.FunctionDef)}
        self.assertEqual(sorted(k for k in ma if ma[k] != mc[k]), ['q', 'rational', 'reserve'])
        self.assertEqual(sorted(mc), sorted(ma))
        self.assertEqual([ast.unparse(n) for n in cc.body if isinstance(n, ast.Assign)], ['_envelope = None'])
        old_top = {ast.dump(n) for n in a.body}
        added = [ast.unparse(n).splitlines()[0] for n in c.body if ast.dump(n) not in old_top
                 and not isinstance(n, ast.ClassDef)]
        self.assertEqual(added, [
            '_BASE_INTEGER, _BASE_SHAPE = (Arithmetic._integer, Arithmetic._shape)',
            'from hashlib import sha256 as _sha256', 'from pathlib import Path as _Path',
            'from types import MethodType as _MethodType',
            "_INLINE_RESOURCES_SHA256 = '5ada7b86bc189393d74b20aad1f5eb312b0398f25dd74710f6209dfb94f2edca'",
            '_inline_verified = [(object(), object())]', '_inline_checked = []', 'def _inline_pair(resources):'])


class Differential(unittest.TestCase):
    def run_pair(self, seed, steps, old_cls=None, new_cls=None):
        rng = random.Random(seed)
        flags = [False]
        cancel = lambda: flags[0]          # noqa: E731
        a, wa = make(OLD, old_cls, cancel)
        b, wb = make(NEW, new_cls, cancel)
        hits = dict(q=0, rational=0, raise_=0)
        for step in range(steps):
            k = rng.random()
            if k < 0.45:
                op = rng.choice(('add', 'subtract', 'multiply', 'divide')*6+('pow', '', None, 'Add', 1))
                x, y = operand(rng), operand(rng)
                ra, rb = outcome(lambda: a.rational(op, x, y)), outcome(lambda: b.rational(op, x, y))
                hits['rational'] += 1
            elif k < 0.70:
                x = operand(rng)
                ra, rb = outcome(lambda: a.q(x)), outcome(lambda: b.q(x))
                hits['q'] += 1
            elif k < 0.80:
                name = rng.choice(('imul', 'isub', 'idiv', 'divmod', 'gcd', 'lcm'))
                x, y = integer(rng), integer(rng)
                if name in ('idiv', 'divmod') and y == 0:
                    y = 3
                ra, rb = outcome(lambda: getattr(a, name)(x, y)), outcome(lambda: getattr(b, name)(x, y))
            elif k < 0.85:
                n = rng.randint(0, wa.lease.count)
                wa.lease.count = wb.lease.count = n
                continue
            elif k < 0.90:
                d = rng.randint(1, 40)
                a.slots += d
                b.slots += d
                ra, rb = outcome(lambda: a.reserve(a.peak_bits)), outcome(lambda: b.reserve(b.peak_bits))
            elif k < 0.93:
                d = rng.randint(1, 1 << 16)
                a.containers += d
                b.containers += d
                ra, rb = outcome(lambda: a.reserve(a.peak_bits)), outcome(lambda: b.reserve(b.peak_bits))
            elif k < 0.95:
                flags[0] = True
                x = operand(rng)
                ra, rb = outcome(lambda: a.rational('add', x, x)), outcome(lambda: b.rational('add', x, x))
                flags[0] = False
            else:
                big = G.mpq(1 << rng.choice((1 << 20, 1 << 23, (1 << 24)+3)), 3)
                ra, rb = outcome(lambda: a.q(big)), outcome(lambda: b.q(big))
            self.assertEqual(ra, rb, (seed, step))
            hits['raise_'] += ra[0] == 'raise'
            self.assertEqual((a.peak_bits, a.operations, wa.lease.count), (b.peak_bits, b.operations, wb.lease.count),
                             (seed, step))
            self.assertEqual(wa.log, wb.log, (seed, step))
        return hits

    def test_random(self):
        total = dict(q=0, rational=0, raise_=0)
        for seed in range(40):
            for k, v in self.run_pair(seed, 400).items():
                total[k] += v
        self.assertGreater(total['rational'], 5500)
        self.assertGreater(total['q'], 3000)
        self.assertGreater(total['raise_'], 1000)

    def test_rank_like_subclass_takes_inline_route(self):
        def sub(m):
            class _Arithmetic(m.Arithmetic):
                def iadd(self, a, b):
                    self.reserve(max(self._integer(a), self._integer(b))+1)
                    self.operations += 1
                    return a+b
            return _Arithmetic
        self.run_pair(991, 1500, sub(OLD), sub(NEW))
        self.assertEqual(NEW._inline_pair(R), (R, G))


class RefuterRegressions(unittest.TestCase):
    def both(self, setup, call, cls_old=None, cls_new=None):
        res = []
        for m, cls in ((OLD, cls_old), (NEW, cls_new)):
            a, w = make(m, cls)
            setup(a)
            res.append((outcome(lambda: call(a)), a.peak_bits, a.operations, w.log[:]))
        self.assertEqual(res[0], res[1])
        return res[0]

    def test_metaclass_equal_to_int(self):
        class Meta(type):
            def __eq__(cls, other):
                return other is int or type.__eq__(cls, other)
            __hash__ = type.__hash__

        class FakeInt(metaclass=Meta):
            def bit_length(self):
                return 9

            def __add__(self, other):
                return 7

            def __radd__(self, other):
                return 7
        x = FakeInt()
        self.both(lambda a: None, lambda a: a.rational('add', x, 1))
        self.both(lambda a: None, lambda a: a.rational('add', 1, x))
        self.both(lambda a: None, lambda a: a.q(x))

    def test_instance_shape_override(self):
        def setup(a):
            a._shape = lambda v: type(a)._shape(a, v).__class__(500, 1, True)
        self.both(setup, lambda a: a.q(G.mpq(3, 7)))
        self.both(setup, lambda a: a.rational('multiply', G.mpq(3, 7), 5))

    def test_instance_integer_override(self):
        def setup(a):
            a._integer = lambda v: 300
        self.both(setup, lambda a: a.q(5))
        self.both(setup, lambda a: a.rational('subtract', 5, G.mpz(9)))

    def test_R_deleted_or_replaced(self):
        def delete(a):
            del a.R
        self.both(delete, lambda a: a.rational('add', 1, 2))
        self.both(delete, lambda a: a.q(G.mpq(1, 3)))
        self.both(delete, lambda a: a.reserve(a.peak_bits))
        self.both(lambda a: setattr(a, 'R', None), lambda a: a.rational('add', 1, 2))
        self.both(lambda a: setattr(a, 'R', None), lambda a: a.reserve(a.peak_bits))
        self.both(lambda a: setattr(a, 'R', None), lambda a: a.q(G.mpq(1, 3)))

    def test_staticmethod_and_classmethod_shape(self):
        for wrap in (staticmethod, classmethod):
            self.both(lambda a: None, lambda a: a.q(5),
                      type('S', (OLD.Arithmetic,), {'_shape': wrap(OLD.Arithmetic._shape)}),
                      type('S', (NEW.Arithmetic,), {'_shape': wrap(NEW.Arithmetic._shape)}))
            self.both(lambda a: None, lambda a: a.rational('add', 5, 6),
                      type('S', (OLD.Arithmetic,), {'_integer': wrap(OLD.Arithmetic._integer)}),
                      type('S', (NEW.Arithmetic,), {'_integer': wrap(NEW.Arithmetic._integer)}))

    def test_G_without_mpz(self):
        class NoMpz:
            mpq = G.mpq
        self.both(lambda a: setattr(a, 'G', NoMpz()), lambda a: a.q(5))
        self.both(lambda a: setattr(a, 'G', NoMpz()), lambda a: a.rational('add', 5, G.mpq(1, 3)))

    def test_R_none_at_first_use_and_other_content(self):
        saved = list(NEW._inline_checked), NEW._inline_verified[0]
        try:
            del NEW._inline_checked[:]
            NEW._inline_verified[0] = (object(), object())   # as at import: nothing verified yet
            self.both(lambda a: setattr(a, 'R', None), lambda a: a.rational('multiply', 3, 4))
            # A module registered under the reviewed name whose file differs by one byte.
            fake = types.ModuleType('private_heat_gmp_resources_r1')
            fake.__dict__.update({k: v for k, v in vars(R).items() if not k.startswith('__')})
            path = Path(tempfile.mkdtemp())/'private_heat_gmp_resources_r1.py'
            path.write_bytes((LAYOUT/'helpers'/'private_heat_gmp_resources_r1.py').read_bytes()+b'\n')
            fake.__file__ = str(path)
            calls = []

            def counted(*args, **kw):
                calls.append(1)
                return R.operation_growth(*args, **kw)
            fake.operation_growth = counted
            sys.modules['private_heat_gmp_resources_r1'] = fake
            try:
                self.both(lambda a: setattr(a, 'R', fake), lambda a: a.rational('divide', G.mpq(3, 5), 7))
            finally:
                sys.modules['private_heat_gmp_resources_r1'] = R
            self.assertEqual(len(calls), 2)                 # both arms ran operation_growth
            self.assertIsNone(NEW._inline_pair(fake))
        finally:
            NEW._inline_checked[:] = saved[0]
            NEW._inline_verified[0] = saved[1]

    def test_inline_route_skips_operation_growth(self):
        a, _ = make(NEW)
        saved = R.operation_growth
        try:
            R.operation_growth = None                      # the inline route must not touch it
            a.rational('add', G.mpq(1, 3), 5)
        finally:
            R.operation_growth = saved


def load_file(name, text):
    # The loaded-identity guard hashes the module's file, so this module needs a real one.
    path = Path(tempfile.mkdtemp())/(name+'.py')
    path.write_bytes(text.encode('utf8'))
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(text, module.__file__, 'exec'), module.__dict__)
    return module


class R3Regressions(unittest.TestCase):
    def both(self, setup, call, cls_old=None, cls_new=None, new=NEW):
        res = []
        for m, cls in ((OLD, cls_old), (new, cls_new)):
            a, w = make(m, cls)
            setup(a)
            res.append((outcome(lambda: call(a)), a.peak_bits, a.operations, w.log[:]))
        self.assertEqual(res[0], res[1])
        return res[0]

    def test_loaded_identity_stable_across_inlined_calls(self):
        import private_heat_loaded_identity_r1 as LOADED
        upper = AFTER_C.replace('_inline_checked', '_INLINE_CHECKED')
        for label, text, drifts in (('h1r3_identity_new', AFTER_C, False), ('h1r3_identity_upper', upper, True)):
            m = load_file(label, text)
            guard = LOADED.LoadedIdentity([m])                   # before any q()/rational()
            a, _ = make(m)
            a.q(5)
            a.rational('add', G.mpq(1, 3), 2)
            a.rational('multiply', G.mpz(7), G.mpq(2, 9))
            self.assertIs(m._inline_verified[0][0], R)           # the inline route was taken
            if drifts:                                           # negative control: the guard sees it
                with self.assertRaises(ValueError):
                    guard.verify([m])
            else:
                guard.verify([m])
                a.q(G.mpq(4, 5))
                guard.verify([m])

    def test_G_replaced_by_namespace(self):
        class Q:
            numerator, denominator = G.mpz(3), G.mpz(0)

            def __init__(self, value=None):
                pass

            def __repr__(self):
                return 'Q()'

            def __truediv__(self, other):
                return 1

            __add__ = __sub__ = __mul__ = __radd__ = __rsub__ = __rmul__ = __rtruediv__ = __truediv__

        class Namespace:
            mpz, mpq = G.mpz, Q
        for call in (lambda a: a.rational('add', Q(), 1), lambda a: a.rational('divide', 2, Q()),
                     lambda a: a.q(Q()), lambda a: a.q(5), lambda a: a.rational('multiply', 3, 4)):
            self.both(lambda a: setattr(a, 'G', Namespace), call)

    def test_G_equivalent_but_other_object_takes_original_route(self):
        calls = []
        saved = R.operation_growth

        def counted(*args, **kw):
            calls.append(1)
            return saved(*args, **kw)
        try:
            R.operation_growth = counted
            ns = types.SimpleNamespace(mpz=G.mpz, mpq=G.mpq)
            self.both(lambda a: setattr(a, 'G', ns), lambda a: a.rational('subtract', G.mpq(5, 3), 7))
            self.assertEqual(len(calls), 2)                      # NEW ran the original body too
        finally:
            R.operation_growth = saved

    def test_raising_integer_property(self):
        def sub(m):
            class S(m.Arithmetic):
                @property
                def _integer(self):
                    raise LookupError('no integer reader')
            return S
        for call in (lambda a: a.q(G.mpq(3, 7)), lambda a: a.rational('multiply', G.mpq(3, 7), G.mpq(5, 2)),
                     lambda a: a.q(5), lambda a: a.rational('add', 5, G.mpq(1, 3)),
                     lambda a: a.rational('add', G.mpq(1, 3), G.mpz(5)),
                     lambda a: a.rational('pow', G.mpq(1, 3), G.mpq(2))):
            self.both(lambda a: None, call, sub(OLD), sub(NEW))

    def test_reserve_read_order(self):
        def drop(*names):
            def setup(a):
                for name in names:
                    delattr(a, name)
            return setup
        for new in (NEW, ONLY_A):
            for setup in (drop('slots'), drop('containers'), drop('slots', 'containers')):
                for call in (lambda a: a.reserve(a.peak_bits), lambda a: a.reserve(10), lambda a: a.reserve(10.5),
                             lambda a: a.reserve(8.0), lambda a: a.q(G.mpq(1, 3))):
                    self.both(setup, call, new=new)
            self.both(lambda a: None, lambda a: a.reserve(10.5), new=new)
            self.both(lambda a: setattr(a, 'slots', 3.5), lambda a: a.reserve(a.peak_bits), new=new)

    def test_cache_keeps_only_the_registered_module(self):
        make(NEW)[0].rational('add', 1, 2)                       # R itself is verified and cached
        before = [m for m, _ in NEW._inline_checked]
        self.assertIn(R, before)
        for other in (None, object(), types.ModuleType('private_heat_gmp_resources_r1')):
            self.assertIsNone(NEW._inline_pair(other))
            a, _ = make(NEW)
            a.R = other
            outcome(lambda: a.rational('add', 1, 2))
        self.assertEqual([m for m, _ in NEW._inline_checked], before)


if __name__ == '__main__':
    unittest.main()
