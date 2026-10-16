"""Refuter reproducers for L1 r2 (transforms/l1_low_ledger_op.py). Read-only on everything outside refute-l1.

Each case prints OLD and NEW outcomes; 'DIFF' marks an observable divergence.
"""
import json
import sys
import types
from fractions import Fraction
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


OLD, NEW = load('l1_old', SOURCE), load('l1_new', AFTER)


def outcome(fn):
    try:
        v = fn()
        return ('ok', type(v).__name__, repr(v))
    except BaseException as e:  # noqa: B036
        return ('raise', type(e).__name__, str(e))


def show(label, a, b, extra=''):
    print(('DIFF ' if a != b else 'same ')+label+extra)
    print('   OLD', a)
    print('   NEW', b)


x, y = I.Shape(5, 3, False), I.Shape(7, 2, True)

# --- Case 1: resources=None. _inline defaults to / is computed as None, so `R is self._inline` holds.
a, b = OLD.RationalGrowth(G, None, None), NEW.RationalGrowth(G, None, None)
print('case1 NEW._inline =', b._inline)
show('case1 op(multiply) with resources=None', outcome(lambda: a.op('multiply', x, y)),
     outcome(lambda: b.op('multiply', x, y)), '  expression_bits old=%r new=%r' % (a.expression_bits, b.expression_bits))
show('case1 slot with resources=None', outcome(lambda: a.slot(x)), outcome(lambda: b.slot(x)))
show('case1 scalar_work with resources=None', outcome(lambda: a.scalar_work()), outcome(lambda: b.scalar_work()))

# --- Case 1b: same with the reviewed module NOT in sys.modules (the r1 guard also failed here).
saved = sys.modules.pop('private_heat_gmp_resources_r1')
try:
    a, b = OLD.RationalGrowth(G, None, None), NEW.RationalGrowth(G, None, None)
    show('case1b op(divide), resources=None, module unloaded', outcome(lambda: a.op('divide', x, y)),
         outcome(lambda: b.op('divide', x, y)))
finally:
    sys.modules['private_heat_gmp_resources_r1'] = saved

# --- Case 1c: resources reassigned to None after __init__ with the reviewed module -> _inline is R, so falls back (safe).
a, b = OLD.RationalGrowth(G, R, None), NEW.RationalGrowth(G, R, None)
a.resources = b.resources = None
show('case1c reassigned to None after init', outcome(lambda: a.op('add', x, y)), outcome(lambda: b.op('add', x, y)))

# --- Case 1d: subclass that skips __init__ and leaves resources None (class default _inline = None).
def noinit(m):
    class N(m.RationalGrowth):
        def __init__(self):
            self.gmp, self.resources, self.cancel, self.expression_bits = G, None, None, 1
    return N()
a, b = noinit(OLD), noinit(NEW)
show('case1d subclass skipping __init__, resources None', outcome(lambda: a.op('subtract', x, y)),
     outcome(lambda: b.op('subtract', x, y)))


# --- Case 2: slot attribute read counts / non-idempotent Shape-like value.
class Counting:
    def __init__(self, n, d):
        self._n, self._d, self.reads = n, d, []

    @property
    def numerator(self):
        self.reads.append('n')
        return self._n

    @property
    def denominator(self):
        self.reads.append('d')
        return self._d


va, vb = Counting(40, 9), Counting(40, 9)
ra, rb = outcome(lambda: OLD.RationalGrowth(G, R, None).slot(va)), outcome(lambda: NEW.RationalGrowth(G, R, None).slot(vb))
show('case2a slot result (deterministic properties)', ra, rb)
show('case2a slot attribute reads', ''.join(va.reads), ''.join(vb.reads))
va, vb = Counting(G.mpz(40), 9), Counting(G.mpz(40), 9)
outcome(lambda: OLD.RationalGrowth(G, R, None).slot(va)), outcome(lambda: NEW.RationalGrowth(G, R, None).slot(vb))
show('case2b slot attribute reads, fall-through (mpz numerator)', ''.join(va.reads), ''.join(vb.reads))


class Drifting:
    """numerator is 10 on the first read, -1 afterwards."""
    def __init__(self):
        self.k = 0
        self.denominator = 9

    @property
    def numerator(self):
        self.k += 1
        return 10 if self.k == 1 else -1


show('case2c slot on a non-idempotent numerator', outcome(lambda: OLD.RationalGrowth(G, R, None).slot(Drifting())),
     outcome(lambda: NEW.RationalGrowth(G, R, None).slot(Drifting())))

# --- Case 3: slot reads self.resources before value.numerator (original: value first).
a, b = OLD.RationalGrowth(G, R, None), NEW.RationalGrowth(G, R, None)
del a.resources, b.resources
class NoNum:
    denominator = 3
show('case3 slot, resources deleted and value lacks numerator', outcome(lambda: a.slot(NoNum())), outcome(lambda: b.slot(NoNum())))

# --- Case 4: native_slot_allowance is a resources call the NEW slot skips (not in the accepted exemption list).
calls = []
saved_nsa = R.native_slot_allowance
try:
    R.native_slot_allowance = lambda shape: calls.append(1) or saved_nsa(shape)
    a, b = OLD.RationalGrowth(G, R, None), NEW.RationalGrowth(G, R, None)
    a.slot(x); n_old = len(calls); b.slot(x); n_new = len(calls)-n_old
    show('case4 R.native_slot_allowance calls per slot()', n_old, n_new)
finally:
    R.native_slot_allowance = saved_nsa

# --- Case 5: the content binding hashes the FILE once; it does not bind the loaded code.
# (a) A module object registered under the reviewed name whose __file__ is the reviewed file but whose
#     executed code is a later revision (custom loader / stale bytecode / reload-after-check analogue).
text = Path(R.__file__).read_bytes().decode('utf8')
revised = text.replace('    return 160+8*limbs\n', '    return 168+8*limbs\n')
assert revised != text
M = types.ModuleType('private_heat_gmp_resources_r1')
M.__file__ = R.__file__
exec(compile(revised, R.__file__, 'exec'), M.__dict__)
saved = sys.modules['private_heat_gmp_resources_r1']
try:
    sys.modules['private_heat_gmp_resources_r1'] = M
    a, b = OLD.RationalGrowth(G, M, None), NEW.RationalGrowth(G, M, None)
    print('case5a NEW._inline is M:', b._inline is M)
    show('case5a slot with loaded code != file content', outcome(lambda: a.slot(x)), outcome(lambda: b.slot(x)))
    # (b) reload-in-place after the check was cached: same module object, new code.
    M2 = types.ModuleType('private_heat_gmp_resources_r1')
    M2.__file__ = R.__file__
    exec(compile(text, R.__file__, 'exec'), M2.__dict__)
    sys.modules['private_heat_gmp_resources_r1'] = M2
    NEW.RationalGrowth(G, M2, None)                     # verdict cached: M2 -> inline
    exec(compile(revised, R.__file__, 'exec'), M2.__dict__)   # what importlib.reload does with new file bytes
    a, b = OLD.RationalGrowth(G, M2, None), NEW.RationalGrowth(G, M2, None)
    show('case5b slot after in-place re-execution (reload)', outcome(lambda: a.slot(x)), outcome(lambda: b.slot(x)))
finally:
    sys.modules['private_heat_gmp_resources_r1'] = saved

# --- Case 6: instance dict gains a key (only matters if something measures RationalGrowth instances).
print('case6 instance attrs OLD', sorted(vars(OLD.RationalGrowth(G, R, None))), 'NEW', sorted(vars(NEW.RationalGrowth(G, R, None))))
print('case6 getsizeof(vars()) OLD', sys.getsizeof(vars(OLD.RationalGrowth(G, R, None))),
      'NEW', sys.getsizeof(vars(NEW.RationalGrowth(G, R, None))))
print('fraction size const', NEW._FRACTION_ZERO_SIZE, sys.getsizeof(Fraction(0)), sys.getsizeof(Fraction(10**50, 3)))
