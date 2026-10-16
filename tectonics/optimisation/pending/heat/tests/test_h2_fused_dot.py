"""Tests for transforms/h2_fused_dot.py (H2).

Run: <.r44-env python> -B -m unittest test_h2_fused_dot   (from T/hs/tests; PYTHONHASHSEED=0)
Uses the reviewed helpers and runtime of the prepared layout T/hs/lw (read-only).

1. Anchoring, refusals, the AST shows only dot() changed, and repin replaces exactly one pin.
2. Differential: the original and transformed Arithmetic.dot run on the same random
   interval vectors at every ladder precision, including zeros, signed zeros, mixed signs,
   degenerate and wide intervals, and exponents near the overflow/underflow traps. Also a
   cancellation at a random check, the evidence phase sequence, list intervals and
   non-pair intervals (fallback path), length mismatch, and a subclass (fallback path).
   Results must match bit for bit (value, sign of zero, precision); exceptions must match
   in type and message; the full sequence of check phases must be equal.
3. solve_enclosure and physical_bounds, end to end on random rational systems, give
   bit-identical bounds and proofs with both kernels.
"""
import ast
import json
import random
import sys
import types
import unittest
from hashlib import sha256
from pathlib import Path

HS = Path(__file__).resolve().parents[1]
LAYOUT = HS/'lw'
sys.path[:0] = json.loads((LAYOUT/'control.json').read_text(encoding='utf8'))['paths']
sys.path.insert(0, str(HS/'transforms'))
import h2_fused_dot as X  # noqa: E402

KSRC = (LAYOUT/'helpers'/'private_heat_certification_kernel_r1.py').read_bytes().decode('utf8')
RSRC = (LAYOUT/'helpers'/'private_heat_certification_resources_r1.py').read_bytes().decode('utf8')


def load(name, text):
    module = types.ModuleType(name)
    module.__file__ = str(LAYOUT/'helpers'/(name+'.py'))
    exec(compile(text, module.__file__, 'exec'), module.__dict__)
    return module


OLD = load('h2_old_cert', KSRC)
NEW = load('h2_new_cert', X.transform(KSRC))
G = OLD.G


def bits(v):
    if isinstance(v, tuple):
        return tuple(bits(x) for x in v)
    if isinstance(v, list):
        return [bits(x) for x in v]
    if type(v) is type(G.mpfr(0)):
        # Exact serialisation (value, sign of zero, precision); no huge integers for 2**30 exponents.
        return ('mpfr', v.precision, G.is_signed(v), G.to_binary(v))
    if isinstance(v, dict):
        return {k: bits(x) for k, x in v.items()}
    return repr(v)


class Log(dict):
    def __init__(self):
        super().__init__()
        self.trail = []

    def __setitem__(self, key, value):
        self.trail.append(value)
        super().__setitem__(key, value)


def outcome(fn):
    try:
        return ('ok', bits(fn()))
    except BaseException as error:          # noqa: B036
        return ('raise', type(error).__name__, str(error))


def rand_mpfr(rng, ar):
    kind = rng.random()
    with ar.near:
        if kind < 0.08:
            return G.mpfr(0) if rng.random() < 0.5 else -G.mpfr(0)
        if kind < 0.12:
            return G.mul_2exp(G.mpfr(rng.choice((1, -1, 3, -5))), rng.choice((1073741000, 1073741800, -1073741000,
                                                                              -1073741800, 536870000)))
        num = rng.getrandbits(rng.randint(1, 400)) * rng.choice((1, -1))
        return G.mpfr(G.mpq(num, rng.getrandbits(rng.randint(1, 300))+1))


def rand_interval(rng, ar):
    a, b = rand_mpfr(rng, ar), rand_mpfr(rng, ar)
    if rng.random() < 0.2:
        b = a
    return (a, b) if a <= b else (b, a)


class TransformTests(unittest.TestCase):
    def test_reviewed_inputs(self):
        self.assertIn(sha256(KSRC.encode()).hexdigest(), X.KERNEL_INPUT_SHA256)
        self.assertIn(sha256(RSRC.encode()).hexdigest(), X.RESOURCES_INPUT_SHA256)
        out = X.transform(KSRC)
        compile(out, 'k.py', 'exec')
        with self.assertRaises(ValueError):
            X.transform(out, allow_unreviewed_input=True)
        with self.assertRaises(ValueError):
            X.transform(KSRC+'\n')

    def test_only_dot_changes(self):
        old, new = ast.parse(KSRC), ast.parse(X.transform(KSRC))
        self.assertEqual(len(old.body), len(new.body))
        changed = []
        for a, b in zip(old.body, new.body, strict=True):
            if ast.dump(a) != ast.dump(b):
                self.assertIsInstance(a, ast.ClassDef)
                self.assertEqual(a.name, 'Arithmetic')
                for m, n in zip(a.body, b.body, strict=True):
                    if ast.dump(m) != ast.dump(n):
                        changed.append(m.name)
        self.assertEqual(changed, ['dot'])

    def test_repin(self):
        before = sha256(KSRC.encode()).hexdigest()
        after = sha256(X.transform(KSRC).encode()).hexdigest()
        out = X.repin(RSRC, before, after)
        self.assertEqual(out.count(after), 1)
        self.assertNotIn(before, out)
        diff = [(x, y) for x, y in zip(RSRC.splitlines(), out.splitlines(), strict=True) if x != y]
        self.assertEqual(len(diff), 1)
        compile(out, 'r.py', 'exec')
        with self.assertRaises(ValueError):
            X.repin(RSRC+'#', before, after)


class Differential(unittest.TestCase):
    def arms(self, precision, cancel_at=None):
        out = []
        for m in (OLD, NEW):
            count = [0]

            def cancelled(count=count):
                count[0] += 1
                return cancel_at is not None and count[0] >= cancel_at
            log = Log()
            out.append((m.Arithmetic(precision, cancelled, log), log, count))
        return out

    def test_random_dots(self):
        rng = random.Random(161016)
        n_ok = n_raise = 0
        for trial in range(1500):
            precision = rng.choice(OLD.PRECISIONS)
            length = rng.choice((0, 1, 2, 3, 5, 8, 17))
            cancel_at = rng.choice((None,)*6+(1, 2, 3, 5, 9, 20))
            (a0, l0, c0), (a1, l1, c1) = self.arms(precision, cancel_at)
            u = [rand_interval(rng, a0) for _ in range(length)]
            v = [rand_interval(rng, a0) for _ in range(length)]
            if rng.random() < 0.05 and length:
                v = v[:-1]                       # strict zip mismatch
            if rng.random() < 0.05 and length:
                u[0] = list(u[0])                # a list interval: fallback for that element
            r0, r1 = outcome(lambda: a0.dot(u, v)), outcome(lambda: a1.dot(u, v))
            self.assertEqual(r0, r1, trial)
            self.assertEqual(l0.trail, l1.trail, trial)
            self.assertEqual(c0[0], c1[0], trial)
            n_ok += r0[0] == 'ok'
            n_raise += r0[0] == 'raise'
        self.assertGreater(n_ok, 800)
        self.assertGreater(n_raise, 50)

    def test_non_pair_interval_and_subclass(self):
        (a0, l0, _), (a1, l1, _) = self.arms(320)
        with a0.near:
            tri = (G.mpfr(-1), G.mpfr(2), G.mpfr(3))
            pair = (G.mpfr(-2), G.mpfr(5))
        self.assertEqual(outcome(lambda: a0.dot([tri, pair], [pair, tri])),
                         outcome(lambda: a1.dot([tri, pair], [pair, tri])))
        self.assertEqual(l0.trail, l1.trail)

        class Sub(NEW.Arithmetic):
            def mul(self, a, b):
                self.check('sub-mul')
                return super().mul(a, b)
        s = Sub(320, None, Log())
        s.dot([pair], [pair])
        self.assertEqual(s.evidence.trail, ['sub-mul', 'interval-product', 'interval-add'])


class EndToEnd(unittest.TestCase):
    def test_solve_enclosure(self):
        rng = random.Random(5)
        done = 0
        for trial in range(60):
            n, rows = rng.randint(1, 6), rng.randint(1, 9)
            matrix = [[G.mpq(rng.randint(-50, 50), rng.randint(1, 30)) for _ in range(n)] for _ in range(rows+n)]
            rhs = [G.mpq(rng.randint(-99, 99), rng.randint(1, 7)) for _ in range(n)]
            precision = rng.choice(OLD.PRECISIONS)
            res = []
            for m in (OLD, NEW):
                log = Log()

                def run(m=m, log=log):
                    bounds, ar, proof = m.solve_enclosure(matrix, rhs, precision=precision, evidence=log)
                    keys = [('cell', i) for i in range(len(matrix))]
                    phys = m.physical_bounds(matrix, bounds, keys, (('cell', 0), ('cell', 1)) if len(matrix) > 1
                                             else (('cell', 0), ('wall', 0)), G.mpq(1, 3),
                                             [G.mpq(1)]*len(matrix), ar)
                    return bounds, proof, phys
                res.append((outcome(run), log.trail))
            self.assertEqual(res[0], res[1], trial)
            done += res[0][0][0] == 'ok'
        self.assertGreater(done, 20)


if __name__ == '__main__':
    unittest.main()
