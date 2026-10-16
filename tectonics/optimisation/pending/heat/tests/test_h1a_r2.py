"""Tests for transforms/h1a_growth_reserve_r2.py (H1a r2); a copy of test_h1_growth_reserve.py with the r2 import.

Run: <.r44-env python> -B -m unittest test_h1a_r2   (from T/hs/tests; PYTHONHASHSEED=0)
Uses the reviewed helper and runtime from the prepared layout T/hs/lw (read-only).

1. The transform anchors once on the reviewed input, refuses others and double application.
2. Differential: the original and transformed Arithmetic run the same random call sequences
   on fake workspaces that record every resize. The sequences cover reserves below, at and
   above the peak, slot/container mutations, the lease shrunk by others, cancellation,
   the 2**27-bit ceiling, non-int widths and the overflow check. The resize log, the
   exception types and messages, peak_bits, operations and the lease must be equal after
   every step.
3. The same with the real OwnedWorkspace on a WorkBudget, plus every arithmetic method.
"""
import importlib.util
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
import h1a_growth_reserve_r2 as X  # noqa: E402
import gmpy2 as G  # noqa: E402
import private_heat_gmp_resources_r1 as RES  # noqa: E402

SOURCE = (LAYOUT/'helpers'/'private_heat_exact_growth_r1.py').read_bytes().decode('utf8')


def load(name, text):
    module = types.ModuleType(name)
    module.__file__ = str(LAYOUT/'helpers'/(name+'.py'))
    exec(compile(text, module.__file__, 'exec'), module.__dict__)
    return module


OLD = load('h1_old_growth', SOURCE)
NEW = load('h1_new_growth', X.transform(SOURCE))


class Lease:
    def __init__(self):
        self.count = 0


class FakeWorkspace:
    def __init__(self, log):
        self.lease, self.log = Lease(), log

    def resize_before_allocation_or_after_drop(self, count):
        self.log.append(count)
        if count > 1 << 40:
            raise MemoryError('fake budget refused %d' % count)
        self.lease.count = count


class Cancel:
    def __init__(self):
        self.now = False

    def __call__(self):
        return self.now


def outcome(fn):
    try:
        return ('ok', fn())
    except BaseException as error:          # noqa: B036 - compared, never swallowed silently
        return ('raise', type(error).__name__, str(error))


class TransformTests(unittest.TestCase):
    def test_reviewed_input(self):
        self.assertEqual(sha256(SOURCE.encode()).hexdigest(), next(iter(X.KNOWN_INPUT_SHA256)))
        out = X.transform(SOURCE)
        compile(out, 'x.py', 'exec')
        self.assertEqual(out.count('_envelope = None'), 1)

    def test_refusals(self):
        with self.assertRaises(ValueError):
            X.transform(SOURCE+'\n')
        with self.assertRaises(ValueError):
            X.transform(X.transform(SOURCE), allow_unreviewed_input=True)
        with self.assertRaises(ValueError):
            X.transform(SOURCE.replace('        self.peak_bits = peak\n', '        self.peak_bits = peak  \n'),
                        allow_unreviewed_input=True)

    def test_only_reserve_and_class_attribute_change(self):
        out = X.transform(SOURCE)
        import ast
        old, new = ast.parse(SOURCE), ast.parse(out)
        oc = next(n for n in old.body if isinstance(n, ast.ClassDef))
        nc = next(n for n in new.body if isinstance(n, ast.ClassDef))
        om = {n.name: ast.dump(n) for n in oc.body if isinstance(n, ast.FunctionDef)}
        nm = {n.name: ast.dump(n) for n in nc.body if isinstance(n, ast.FunctionDef)}
        self.assertEqual(set(om), set(nm))
        self.assertEqual([k for k in om if om[k] != nm[k]], ['reserve'])
        self.assertEqual([ast.dump(n) for n in old.body if not isinstance(n, ast.ClassDef)],
                         [ast.dump(n) for n in new.body if not isinstance(n, ast.ClassDef)])


class Differential(unittest.TestCase):
    def pair(self, slots, containers, initial, cancel_old=None, cancel_new=None):
        logs = [], []
        made = [outcome(lambda m=m, log=log, c=c: m.Arithmetic(FakeWorkspace(log), G, scalar_slots=slots,
                        container_bytes=containers, initial_bits=initial, cancelled=c))
                for m, log, c in ((OLD, logs[0], cancel_old), (NEW, logs[1], cancel_new))]
        return made, logs

    def state(self, a):
        return (a.peak_bits, type(a.peak_bits), a.operations, a.slots, a.containers, a.workspace.lease.count)

    def test_random_sequences(self):
        rng = random.Random(20261016)
        steps = 0
        for trial in range(400):
            cancels = Cancel(), Cancel()
            made, logs = self.pair(rng.randint(1, 5000), rng.randint(1, 1 << 20), rng.randint(1, 300), *cancels)
            self.assertEqual(made[0][0], made[1][0])
            if made[0][0] != 'ok':
                self.assertEqual(made[0], made[1])
                continue
            a, b = made[0][1], made[1][1]
            self.assertEqual(logs[0], logs[1])
            for _ in range(rng.randint(1, 120)):
                kind = rng.random()
                if kind < 0.55:
                    width = rng.choice((rng.randint(-3, a.peak_bits), a.peak_bits, a.peak_bits,
                                        rng.randint(a.peak_bits, a.peak_bits+400)))
                    if rng.random() < 0.02:
                        width = rng.choice((1 << 24, (1 << 24)+1, 1 << 27, 7.5, G.mpz(a.peak_bits+5),
                                            G.mpz(max(1, a.peak_bits-1)), True, 10**30))
                    ra, rb = outcome(lambda: a.reserve(width)), outcome(lambda: b.reserve(width))
                    self.assertEqual(ra, rb, (trial, width))
                elif kind < 0.65:
                    d = rng.randint(1, 64)
                    a.slots += d
                    b.slots += d
                    self.assertEqual(outcome(lambda: a.reserve(a.peak_bits)), outcome(lambda: b.reserve(b.peak_bits)))
                elif kind < 0.75:
                    d = rng.randint(-1000, 100000)
                    a.containers += d
                    b.containers += d
                    self.assertEqual(outcome(lambda: a.reserve(a.peak_bits)), outcome(lambda: b.reserve(b.peak_bits)))
                elif kind < 0.85:
                    shrink = rng.randint(0, a.workspace.lease.count)
                    a.workspace.lease.count = shrink
                    b.workspace.lease.count = shrink
                elif kind < 0.88:
                    big = rng.choice((1 << 61, 1 << 70, 1 << 40))
                    a.containers += big
                    b.containers += big
                    self.assertEqual(outcome(lambda: a.reserve(a.peak_bits)), outcome(lambda: b.reserve(b.peak_bits)))
                    a.containers -= big
                    b.containers -= big
                elif kind < 0.90:
                    for c in cancels:
                        c.now = True
                    self.assertEqual(outcome(lambda: a.reserve(1)), outcome(lambda: b.reserve(1)))
                    for c in cancels:
                        c.now = False
                elif kind < 0.93:
                    v = rng.choice((G.mpz(rng.getrandbits(rng.randint(1, 900))), rng.getrandbits(300)))
                    w = rng.choice((G.mpz(rng.getrandbits(rng.randint(1, 900))+1), rng.getrandbits(200)+1))
                    for op in ('imul', 'isub', 'idiv', 'divmod', 'gcd', 'lcm'):
                        self.assertEqual(outcome(lambda: getattr(a, op)(v, w)), outcome(lambda: getattr(b, op)(v, w)))
                else:
                    p = G.mpq(rng.getrandbits(rng.randint(1, 700)), rng.getrandbits(rng.randint(1, 500))+1)
                    q = G.mpq(-rng.getrandbits(rng.randint(1, 700)), rng.getrandbits(rng.randint(1, 500))+1)
                    if q == 0:
                        q = G.mpq(1, 3)
                    for op in ('add', 'subtract', 'multiply', 'divide'):
                        self.assertEqual(outcome(lambda: a.rational(op, p, q)), outcome(lambda: b.rational(op, p, q)))
                    self.assertEqual(outcome(lambda: a.q(p)), outcome(lambda: b.q(p)))
                steps += 1
                self.assertEqual(self.state(a), self.state(b))
                self.assertEqual(logs[0], logs[1])
        self.assertGreater(steps, 10000)

    def test_cache_actually_hits(self):
        calls = []
        real = RES.native_slot_allowance

        class Counting:
            def __getattr__(self, name):
                return getattr(RES, name)

            def native_slot_allowance(self, shape):
                calls.append(shape)
                return real(shape)
        a = NEW.Arithmetic(FakeWorkspace([]), G, scalar_slots=10, container_bytes=100, initial_bits=50)
        a.R = Counting()
        for _ in range(100):
            a.reserve(10)
        self.assertEqual(len(calls), 0)
        a.reserve(51)
        a.reserve(51)
        a.slots += 1
        a.reserve(a.peak_bits)
        a.reserve(a.peak_bits)
        self.assertEqual(len(calls), 2)


class RealWorkspace(unittest.TestCase):
    def test_owned_workspace(self):
        from atlas_tectonics.resources import WorkBudget
        rng = random.Random(7)
        results = []
        for m in (OLD, NEW):
            budget = WorkBudget(1 << 34)
            trace = []
            with RES.OwnedWorkspace(budget, 4096) as work:
                a = m.Arithmetic(work, G, scalar_slots=300, container_bytes=5000, initial_bits=64)
                r2 = random.Random(11)
                for _ in range(3000):
                    w = r2.choice((r2.randint(1, a.peak_bits), r2.randint(1, a.peak_bits+64)))
                    trace.append(outcome(lambda: a.reserve(w)))
                    if r2.random() < 0.05:
                        a.containers += r2.randint(1, 4096)
                        trace.append(outcome(lambda: a.reserve(a.peak_bits)))
                    if r2.random() < 0.05:
                        trace.append(outcome(lambda: work.resize_before_allocation_or_after_drop(
                            r2.randint(4096, work.lease.count))))
                    trace.append((a.peak_bits, a.operations, work.lease.count))
            results.append((trace, budget.statistics() if hasattr(budget, 'statistics') else None))
        del rng
        self.assertEqual(results[0][0], results[1][0])
        self.assertEqual(repr(results[0][1]), repr(results[1][1]))


if __name__ == '__main__':
    unittest.main()
