"""Tests for transforms/l1_low_ledger_op.py (L1 proposal).

Run: <.r44-env python> -B -m unittest test_l1_low_ledger_op   (from T/hs/tests; PYTHONHASHSEED=0)
Uses the reviewed helpers and runtime of the prepared layout T/hs/lw (read-only).

1. Anchoring, refusals; the AST shows only op and slot changed, plus one module constant.
2. Differential: the original and transformed RationalGrowth on the same random sequences of
   op() (all operations plus invalid ones, divisor_power_two, dyadic shapes), slot(), total(),
   choice() and scalar_work(). Shapes include zero numerators, zero/negative/non-int widths,
   bools, mpz, floats, huge widths and missing attributes. After every step these must be
   equal: the result (repr of the Shape or int), the exception type and message, and
   expression_bits. Cancellation is included.
3. polygon_moment_inventory_r1's _Growth subclass gives identical retained bytes and counts.
4. Another resources object (a copy of the module's namespace) keeps the original route.
5. repin_cascade on a scratch copy: each pinner names its pinned file's new digest, and only
   that one line changed.
"""
import ast
import json
import random
import shutil
import sys
import tempfile
import types
import unittest
from fractions import Fraction
from hashlib import sha256
from pathlib import Path

HS = Path(__file__).resolve().parents[1]
LAYOUT = HS/'lw'
sys.path[:0] = json.loads((LAYOUT/'control.json').read_text(encoding='utf8'))['paths']
sys.path.insert(0, str(HS/'transforms'))
import l1_low_ledger_op as X  # noqa: E402
import gmpy2 as G  # noqa: E402
import private_heat_gmp_resources_r1 as R  # noqa: E402
import private_heat_interval_inventory_r1 as I  # noqa: E402

NAME = 'private_heat_low_ledger_inventory_r1.py'
SOURCE = (LAYOUT/'helpers'/NAME).read_bytes().decode('utf8')
AFTER = X.transform(SOURCE)


def load(name, text):
    module = types.ModuleType(name)
    module.__file__ = str(LAYOUT/'helpers'/(name+'.py'))
    exec(compile(text, module.__file__, 'exec'), module.__dict__)
    return module


OLD = load('l1_old_low_ledger', SOURCE)
NEW = load('l1_new_low_ledger', AFTER)


def outcome(fn):
    try:
        value = fn()
        return ('ok', type(value).__name__, repr(value))
    except BaseException as error:          # noqa: B036
        return ('raise', type(error).__name__, str(error))


class Odd:
    """A shape-like object with a missing or odd attribute."""
    def __init__(self, **kw):
        self.__dict__.update(kw)


def width(rng):
    k = rng.random()
    if k < 0.12:
        return 0
    if k < 0.70:
        return rng.randint(1, 3000)
    if k < 0.80:
        return rng.randint(1, 1 << 40)
    if k < 0.84:
        return 1
    return rng.choice((-1, -7, True, False, 2.0, G.mpz(5), None, '3', 1 << 70))


def shape(rng):
    k = rng.random()
    if k < 0.03:
        return Odd(numerator=width(rng))                # no denominator
    if k < 0.05:
        return Odd(denominator=rng.randint(1, 9))       # no numerator
    if k < 0.75:
        return I.Shape(rng.randint(0, 4000) if rng.random() < 0.9 else 0, rng.randint(1, 3000), rng.random() < 0.4)
    return I.Shape(width(rng), width(rng), rng.random() < 0.5)


class TransformTests(unittest.TestCase):
    def test_anchor_and_refusals(self):
        compile(AFTER, 'x.py', 'exec')
        with self.assertRaises(ValueError):
            X.transform(AFTER, allow_unreviewed_input=True)
        with self.assertRaises(ValueError):
            X.transform(SOURCE+'\n')

    def test_only_init_op_slot_and_l1_names_change(self):
        a, b = ast.parse(SOURCE), ast.parse(AFTER)
        old_top = {ast.dump(n) for n in a.body}
        added = [n for n in b.body if ast.dump(n) not in old_top]
        # The changed class plus the L1 module names; every other top-level statement is unchanged.
        self.assertEqual(len(b.body), len(a.body)+6)
        self.assertEqual(sorted(getattr(n, 'name', None) or ast.unparse(n.targets[0]) for n in added),
                         ['RationalGrowth', '_FRACTION_ZERO_SIZE', '_INLINE_RESOURCES_SHA256', '_NO_INLINE',
                          '_inline_checked', '_inline_resources', '_py_int'])
        ca = next(n for n in a.body if isinstance(n, ast.ClassDef) and n.name == 'RationalGrowth')
        cb = next(n for n in b.body if isinstance(n, ast.ClassDef) and n.name == 'RationalGrowth')
        ma = {n.name: ast.dump(n) for n in ca.body if isinstance(n, ast.FunctionDef)}
        mb = {n.name: ast.dump(n) for n in cb.body if isinstance(n, ast.FunctionDef)}
        self.assertEqual(sorted(k for k in ma if ma[k] != mb[k]), ['__init__', 'op', 'slot'])
        self.assertEqual(sorted(mb), sorted(ma))
        self.assertEqual([ast.unparse(n) for n in cb.body if isinstance(n, ast.Assign)], ['_inline = _NO_INLINE'])
        self.assertEqual(NEW._FRACTION_ZERO_SIZE, sys.getsizeof(Fraction(0)))

    def test_bound_digest_is_the_reviewed_resources(self):
        self.assertEqual(NEW._INLINE_RESOURCES_SHA256,
                         sha256((LAYOUT/'helpers'/'private_heat_gmp_resources_r1.py').read_bytes()).hexdigest())
        self.assertIs(NEW._inline_resources(R), R)


class Differential(unittest.TestCase):
    def pair(self, cancel=None, resources=R, old_cls=None, new_cls=None):
        return ((old_cls or OLD.RationalGrowth)(G, resources, cancel),
                (new_cls or NEW.RationalGrowth)(G, resources, cancel))

    def run_pair(self, seed, steps, **kw):
        rng = random.Random(seed)
        flag = [False]
        a, b = self.pair(lambda: flag[0], **kw)
        hits = dict(op=0, ok=0, slot=0, raise_=0)
        for step in range(steps):
            k = rng.random()
            if k < 0.65:
                op = rng.choice(('add', 'subtract', 'multiply', 'divide')*6+('pow', '', None, 'Add', 1))
                x, y = shape(rng), shape(rng)
                p2 = rng.random() < 0.3
                ra = outcome(lambda: a.op(op, x, y, divisor_power_two=p2))
                rb = outcome(lambda: b.op(op, x, y, divisor_power_two=p2))
                hits['op'] += 1
                hits['ok'] += ra[0] == 'ok'
            elif k < 0.82:
                x = shape(rng)
                ra, rb = outcome(lambda: a.slot(x)), outcome(lambda: b.slot(x))
                hits['slot'] += 1
            elif k < 0.88:
                xs = [shape(rng) for _ in range(rng.randint(0, 5))]
                ra, rb = outcome(lambda: a.total(xs)), outcome(lambda: b.total(xs))
            elif k < 0.93:
                xs = [I.Shape(rng.randint(1, 900), rng.randint(1, 900), rng.random() < 0.5)
                      for _ in range(rng.randint(1, 5))]
                ra, rb = outcome(lambda: a.choice(xs)), outcome(lambda: b.choice(xs))
            elif k < 0.97:
                n = rng.choice((1, 3, 12, 0, -1))
                ra = outcome(lambda: a.scalar_work(rational_slots=n))
                rb = outcome(lambda: b.scalar_work(rational_slots=n))
            else:
                flag[0] = True
                x = shape(rng)
                ra, rb = outcome(lambda: a.op('add', x, x)), outcome(lambda: b.op('add', x, x))
                flag[0] = False
            self.assertEqual(ra, rb, (seed, step))
            hits['raise_'] += ra[0] == 'raise'
            self.assertEqual(a.expression_bits, b.expression_bits, (seed, step))
        return hits

    def test_random(self):
        total = dict(op=0, ok=0, slot=0, raise_=0)
        for seed in range(40):
            for k, v in self.run_pair(seed, 600).items():
                total[k] += v
        self.assertGreater(total['op'], 14000)
        self.assertGreater(total['ok'], 9000)
        self.assertGreater(total['slot'], 3500)
        self.assertGreater(total['raise_'], 2000)

    def test_polygon_moment_subclass(self):
        def sub(m):
            class _Growth(m.RationalGrowth):
                def __init__(self, gmp, resources, cancel):
                    super().__init__(gmp, resources, cancel)
                    self.generated_bytes = self.operations = 0

                def retain(self, shape):
                    self.generated_bytes = self.generated_bytes+self.slot(shape)
                    return shape

                def op(self, operation, left, right, **kwargs):
                    shape = super().op(operation, left, right, **kwargs)
                    self.operations += 1
                    return self.retain(shape)
            return _Growth
        rng = random.Random(77)
        a, b = self.pair(old_cls=sub(OLD), new_cls=sub(NEW))
        for _ in range(3000):
            op = rng.choice(('add', 'subtract', 'multiply', 'divide'))
            x, y = shape(rng), shape(rng)
            self.assertEqual(outcome(lambda: a.op(op, x, y)), outcome(lambda: b.op(op, x, y)))
            self.assertEqual((a.expression_bits, a.generated_bytes, a.operations),
                             (b.expression_bits, b.generated_bytes, b.operations))

    def test_other_resources_keep_original_route(self):
        calls = []
        copy = types.ModuleType('resources_copy')
        copy.__dict__.update({k: v for k, v in vars(R).items() if not k.startswith('__')})

        def counted(*args, **kw):
            calls.append(1)
            return R.operation_growth(*args, **kw)
        copy.operation_growth = counted
        self.run_pair(5, 400, resources=copy)
        self.assertGreater(len(calls), 300)        # both arms called operation_growth: original route

    def test_module_not_loaded_keeps_original_route(self):
        # Fallback when the reviewed module is not in sys.modules (sys.modules.get returns None).
        calls = []
        saved_module, saved_growth = sys.modules.pop('private_heat_gmp_resources_r1'), R.operation_growth

        def counted(*args, **kw):
            calls.append(1)
            return saved_growth(*args, **kw)
        try:
            R.operation_growth = counted
            hits = self.run_pair(6, 1200)
        finally:
            R.operation_growth = saved_growth
            sys.modules['private_heat_gmp_resources_r1'] = saved_module
        self.assertGreater(hits['ok'], 300)
        # Each successful op runs operation_growth in BOTH arms: the new arm took the original route.
        self.assertGreaterEqual(len(calls), 2*hits['ok'])

    def fake_resources(self, content, calls, with_file=True):
        """A module registered under the reviewed name whose file has other content (or none)."""
        fake = types.ModuleType('private_heat_gmp_resources_r1')
        fake.__dict__.update({k: v for k, v in vars(R).items() if not k.startswith('__')})
        if with_file:
            path = Path(tempfile.mkdtemp())/'private_heat_gmp_resources_r1.py'
            path.write_bytes(content)
            fake.__file__ = str(path)

        def counted(*args, **kw):
            calls.append(1)
            return R.operation_growth(*args, **kw)
        fake.operation_growth = counted
        return fake

    def check_fallback(self, fake, calls):
        saved = sys.modules['private_heat_gmp_resources_r1']
        try:
            sys.modules['private_heat_gmp_resources_r1'] = fake
            self.assertIs(NEW._inline_resources(fake), NEW._NO_INLINE)
            hits = self.run_pair(8, 1200, resources=fake)
        finally:
            sys.modules['private_heat_gmp_resources_r1'] = saved
        self.assertGreater(hits['ok'], 300)
        self.assertGreaterEqual(len(calls), 2*hits['ok'])     # both arms took the original route

    def test_other_content_keeps_original_route(self):
        # The reviewed module name, but the file differs by one byte (a later revision, say H1b).
        calls = []
        content = (LAYOUT/'helpers'/'private_heat_gmp_resources_r1.py').read_bytes()+b'\n'
        self.check_fallback(self.fake_resources(content, calls), calls)

    def test_unreadable_or_missing_file_keeps_original_route(self):
        calls = []
        self.check_fallback(self.fake_resources(b'', calls, with_file=False), calls)
        fake = self.fake_resources(b'', calls)
        fake.__file__ = str(Path(fake.__file__).parent/'missing.py')
        calls.clear()
        self.check_fallback(fake, calls)

    def test_reassigned_resources_and_subclass_without_init(self):
        calls = []
        copy = self.fake_resources(b'x', calls)
        a, b = self.pair()
        a.resources = b.resources = copy                   # reassigned after __init__
        x, y = I.Shape(5, 3, False), I.Shape(7, 2, True)
        self.assertEqual(outcome(lambda: a.op('divide', x, y)), outcome(lambda: b.op('divide', x, y)))
        self.assertEqual(len(calls), 2)

        class NoInit(NEW.RationalGrowth):
            def __init__(self, gmp, resources, cancel):    # skips super().__init__
                self.gmp, self.resources, self.cancel, self.expression_bits = gmp, resources, cancel, 1
        saved = R.operation_growth
        real_calls = []

        def counted_real(*args, **kw):                     # calls the saved original: no recursion
            real_calls.append(1)
            return saved(*args, **kw)
        try:
            R.operation_growth = counted_real
            c, d = NoInit(G, R, None), OLD.RationalGrowth(G, R, None)
            self.assertIs(c._inline, NEW._NO_INLINE)
            self.assertEqual(outcome(lambda: c.op('divide', x, y)), outcome(lambda: d.op('divide', x, y)))
            self.assertEqual(len(real_calls), 2)           # NoInit took the original route, as OLD does
        finally:
            R.operation_growth = saved

    def test_inline_route_counts(self):
        # With the module loaded, only the OLD arm calls operation_growth: the new arm is inline.
        calls = []
        saved = R.operation_growth

        def counted(*args, **kw):
            calls.append(1)
            return saved(*args, **kw)
        try:
            R.operation_growth = counted
            a, b = self.pair()
            for _ in range(50):
                b.op('multiply', I.Shape(5, 3, False), I.Shape(7, 2, True))
            self.assertEqual(calls, [])
            a.op('multiply', I.Shape(5, 3, False), I.Shape(7, 2, True))
            self.assertEqual(len(calls), 1)
        finally:
            R.operation_growth = saved

    def test_resources_none_keeps_original_route(self):
        # L1 refuter r2 finding: resources=None matched a None "no inline" marker.
        a, b = self.pair(resources=None)
        self.assertIs(b._inline, NEW._NO_INLINE)
        x, y = I.Shape(5, 3, False), I.Shape(7, 2, True)
        for call in (lambda g: g.op('multiply', x, y), lambda g: g.op('divide', x, y),
                     lambda g: g.total([x, y]), lambda g: g.slot(x), lambda g: g.choice([x, y])):
            self.assertEqual(outcome(lambda: call(a)), outcome(lambda: call(b)))
            self.assertEqual(a.expression_bits, b.expression_bits)

    def test_loaded_identity_stable_across_inline_calls(self):
        # L1 r4: the loaded-implementation identity records upper-case module values (lists included)
        # as constants; the per-process cache is lower case so the first inline call cannot change it.
        # Negative control: the same module with the cache upper-cased does drift.
        import private_heat_loaded_identity_r1 as LOADED
        upper = AFTER.replace('_inline_checked', '_INLINE_CHECKED')
        x, y = I.Shape(5, 3, False), I.Shape(7, 2, True)
        for label, text, drifts in (('l1_identity_new', AFTER, False), ('l1_identity_upper', upper, True)):
            path = Path(tempfile.mkdtemp())/(label+'.py')
            path.write_bytes(text.encode('utf8'))         # the guard hashes the module's file
            m = types.ModuleType(label)
            m.__file__ = str(path)
            exec(compile(text, m.__file__, 'exec'), m.__dict__)
            guard = LOADED.LoadedIdentity([m])             # before any RationalGrowth exists
            g = m.RationalGrowth(G, R, None)
            self.assertIs(g._inline, R)                    # the inline route is live
            g.op('multiply', x, y)
            g.slot(Fraction(3, 4))
            if drifts:
                with self.assertRaises(ValueError):
                    guard.verify([m])
            else:
                guard.verify([m])
                m.RationalGrowth(G, R, None).op('add', x, y)
                guard.verify([m])

    def test_sentinel_as_resources_keeps_original_route(self):
        # L1 refuter r3 residual: resources set to the private sentinel itself matched self._inline.
        x, y = I.Shape(5, 3, False), I.Shape(7, 2, True)
        calls = (lambda g: g.op('multiply', x, y), lambda g: g.op('add', x, y), lambda g: g.slot(x),
                 lambda g: g.total([x, y]), lambda g: g.choice([x, y]))
        a, b = self.pair(resources=NEW._NO_INLINE)
        self.assertIs(b._inline, NEW._NO_INLINE)
        c, d = self.pair()
        c.resources = d.resources = NEW._NO_INLINE           # reassigned; d._inline is the real module
        d._inline = NEW._NO_INLINE                           # and the marker forced to the sentinel
        for old, new in ((a, b), (c, d)):
            for call in calls:
                self.assertEqual(outcome(lambda: call(old)), outcome(lambda: call(new)))
                self.assertEqual(old.expression_bits, new.expression_bits)
        self.assertEqual(outcome(lambda: b.op('multiply', x, x))[0], 'raise')

    def test_slot_reads_in_original_order_and_number(self):
        # L1 refuter r2 finding: slot read value attributes a different number of times.
        class Flaky:
            def __init__(self, seq_n, seq_d, log):
                self.n, self.d, self.log = list(seq_n), list(seq_d), log

            @property
            def numerator(self):
                self.log.append('n')
                return self.n.pop(0) if len(self.n) > 1 else self.n[0]

            @property
            def denominator(self):
                self.log.append('d')
                return self.d.pop(0) if len(self.d) > 1 else self.d[0]
        cases = [((10, -1), (3,)), ((10,), (3, 0)), ((10, 2.0), (3,)), ((5,), (2,)), (('x',), (2,)),
                 ((7,), ('y',)), ((1 << 70,), (3,)), ((10, 11), (3, 4))]
        for seq_n, seq_d in cases:
            res = []
            for m in (OLD, NEW):
                log = []
                g = m.RationalGrowth(G, R, None)
                res.append((outcome(lambda: g.slot(Flaky(seq_n, seq_d, log))), log))
            self.assertEqual(res[0], res[1], (seq_n, seq_d))

    def test_resources_attribute_reads(self):
        # slot/op read self.resources the same number of times, in the same place.
        def build(m):
            class C(m.RationalGrowth):
                @property
                def resources(self):
                    self.reads.append('r')
                    return self._r

                @resources.setter
                def resources(self, value):
                    self._r = value
            g = C(G, R, None)
            g.reads = []
            return g
        x, y = I.Shape(5, 3, False), I.Shape(7, 2, True)
        for call in (lambda g: g.slot(x), lambda g: g.op('add', x, y), lambda g: g.slot(Odd(numerator=3))):
            a, b = build(OLD), build(NEW)
            self.assertEqual(outcome(lambda: call(a)), outcome(lambda: call(b)))
            self.assertEqual(a.reads, b.reads)

    def test_inline_route_skips_operation_growth(self):
        b = NEW.RationalGrowth(G, R, None)
        saved = R.operation_growth
        try:
            R.operation_growth = None              # the inline route must not touch it
            b.op('add', I.Shape(5, 3, False), I.Shape(7, 2, True))
        finally:
            R.operation_growth = saved


class Cascade(unittest.TestCase):
    def test_repin_cascade(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            names = {NAME} | {p for pair in X.CASCADE for p in pair}
            for n in names:
                shutil.copyfile(LAYOUT/'helpers'/n, tmp/n)
            before = {n: (tmp/n).read_bytes().decode('utf8') for n in names}
            (tmp/NAME).write_bytes(AFTER.encode('utf8'))
            log = X.repin_cascade(lambda n: (tmp/n).read_bytes().decode('utf8'),
                                  lambda n, t: (tmp/n).write_bytes(t.encode('utf8')))
            self.assertEqual([r[0] for r in log], [p for p, _ in X.CASCADE])
            for pinner, pinned in X.CASCADE:
                text = (tmp/pinner).read_bytes().decode('utf8')
                self.assertIn("'%s': '%s'" % (pinned, sha256((tmp/pinned).read_bytes()).hexdigest()), text)
                diff = [(x, y) for x, y in zip(before[pinner].splitlines(), text.splitlines(), strict=True) if x != y]
                self.assertEqual(len(diff), 1, pinner)
                compile(text, pinner, 'exec')


if __name__ == '__main__':
    unittest.main()
