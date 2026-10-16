"""Tests for transforms/h1c_growth_inline.py (H1c), applied after H1a.

Run: <.r44-env python> -B -m unittest test_h1c_growth_inline   (from T/hs/tests; PYTHONHASHSEED=0)

Differential: the ORIGINAL helper (94dfc016) against H1a+H1c, on random sequences of q(),
rational() (all four operations plus invalid ones) and the integer methods. Operands are
int, mpz and mpq (zero, negative, huge, dyadic and not) plus invalid types. The sequences
also cover cancellation, a lease shrunk by others, and slot/container changes. After
every step these must be equal: the result value and type, the exception type and
message, peak_bits, operations, the lease and the full resize log.
Subclass routes: one that overrides _shape keeps the original route, and an
_Arithmetic like private_heat_rank_resources_r1's (iadd/ratio only) takes the inline route
with identical results.
"""
import ast
import json
import random
import sys
import types
import unittest
from pathlib import Path

HS = Path(__file__).resolve().parents[1]
LAYOUT = HS/'lw'
sys.path[:0] = json.loads((LAYOUT/'control.json').read_text(encoding='utf8'))['paths']
sys.path.insert(0, str(HS/'transforms'))
import h1_growth_reserve as H1A  # noqa: E402
import h1c_growth_inline as H1C  # noqa: E402
import gmpy2 as G  # noqa: E402

SOURCE = (LAYOUT/'helpers'/'private_heat_exact_growth_r1.py').read_bytes().decode('utf8')
AFTER_A = H1A.transform(SOURCE)
AFTER_C = H1C.transform(AFTER_A)


def load(name, text):
    module = types.ModuleType(name)
    module.__file__ = str(LAYOUT/'helpers'/(name+'.py'))
    exec(compile(text, module.__file__, 'exec'), module.__dict__)
    return module


OLD = load('h1c_old_growth', SOURCE)
NEW = load('h1c_new_growth', AFTER_C)


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
    return v if type(v) in (int, type(G.mpz(0))) else G.mpz(rng.getrandbits(64)+1)


class TransformTests(unittest.TestCase):
    def test_anchor_and_refusals(self):
        compile(AFTER_C, 'x.py', 'exec')
        with self.assertRaises(ValueError):
            H1C.transform(SOURCE)                      # must follow H1a
        with self.assertRaises(ValueError):
            H1C.transform(AFTER_C, allow_unreviewed_input=True)

    def test_only_q_rational_and_tail_change(self):
        a, c = ast.parse(AFTER_A), ast.parse(AFTER_C)
        ca = next(n for n in a.body if isinstance(n, ast.ClassDef))
        cc = next(n for n in c.body if isinstance(n, ast.ClassDef))
        ma = {n.name: ast.dump(n) for n in ca.body if isinstance(n, ast.FunctionDef)}
        mc = {n.name: ast.dump(n) for n in cc.body if isinstance(n, ast.FunctionDef)}
        self.assertEqual(sorted(k for k in ma if ma[k] != mc[k]), ['q', 'rational'])
        self.assertEqual(len(c.body), len(a.body)+1)
        self.assertEqual(ast.unparse(c.body[-1]), '_BASE_INTEGER, _BASE_SHAPE = (Arithmetic._integer, Arithmetic._shape)')


class Differential(unittest.TestCase):
    def make(self, m, cls=None, cancel=None):
        w = Work()
        return (cls or m.Arithmetic)(w, G, scalar_slots=77, container_bytes=999, initial_bits=8, cancelled=cancel), w

    def run_pair(self, seed, steps, old_cls=None, new_cls=None):
        rng = random.Random(seed)
        flags = [False]
        cancel = lambda: flags[0]          # noqa: E731
        a, wa = self.make(OLD, old_cls, cancel)
        b, wb = self.make(NEW, new_cls, cancel)
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
                ra, rb = outcome(lambda: a.rational('add', x, x)), outcome(lambda: b.q(x) if False else b.rational('add', x, x))
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
        for seed in range(60):
            for k, v in self.run_pair(seed, 400).items():
                total[k] += v
        self.assertGreater(total['rational'], 8000)
        self.assertGreater(total['q'], 4000)
        self.assertGreater(total['raise_'], 1500)

    def test_rank_like_subclass_takes_inline_route(self):
        def sub(m):
            class _Arithmetic(m.Arithmetic):
                def iadd(self, a, b):
                    self.reserve(max(self._integer(a), self._integer(b))+1)
                    self.operations += 1
                    return a+b
            return _Arithmetic
        s_old, s_new = sub(OLD), sub(NEW)
        self.run_pair(991, 1500, s_old, s_new)
        self.assertIs(s_new._shape, NEW._BASE_SHAPE)

    def test_overriding_subclass_keeps_original_route(self):
        calls = []

        def sub(m):
            class Over(m.Arithmetic):
                def _shape(self, value):
                    calls.append(1)
                    return super()._shape(value)
            return Over
        a, _ = self.make(OLD, sub(OLD))
        b, _ = self.make(NEW, sub(NEW))
        x, y = G.mpq(5, 7), G.mpz(9)
        self.assertEqual(outcome(lambda: a.rational('divide', x, y)), outcome(lambda: b.rational('divide', x, y)))
        self.assertEqual(outcome(lambda: a.q(x)), outcome(lambda: b.q(x)))
        self.assertEqual(len(calls), 6)            # 2+1 in each arm: both took the original route


if __name__ == '__main__':
    unittest.main()
