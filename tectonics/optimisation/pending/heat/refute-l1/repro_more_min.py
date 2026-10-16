"""Import-light secondary reproducers for L1 r2 (slot read order/count, skipped native_slot_allowance,
file-content binding vs loaded code). Same ast extraction as repro_none_min.py. The resources module is a
module object registered as private_heat_gmp_resources_r1 whose __file__ is the REAL reviewed file
(sha 5ada7b86) and whose code is the real _count/RationalShape/_product_bits/Growth/operation_growth/
_installed_policy/native_slot_allowance source (only the heavy atlas_tectonics imports are left out).
"""
import ast
import sys
import types
from hashlib import sha256
from pathlib import Path

HS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HS/'transforms'))
import l1_low_ledger_op as X  # noqa: E402
import gmpy2 as G  # noqa: E402

HELPERS = HS/'lw'/'helpers'
SOURCE = (HELPERS/'private_heat_low_ledger_inventory_r1.py').read_bytes().decode('utf8')
AFTER = X.transform(SOURCE)
SHAPES = (HELPERS/'private_heat_interval_inventory_r1.py').read_bytes().decode('utf8')
GMP_PATH = HELPERS/'private_heat_gmp_resources_r1.py'
GMP = GMP_PATH.read_bytes().decode('utf8')
assert sha256(GMP.encode()).hexdigest().startswith('5ada7b86')


def pick(text, keep):
    out = []
    for node in ast.parse(text).body:
        name = getattr(node, 'name', None) or (isinstance(node, ast.Assign) and ast.unparse(node.targets[0]))
        if name in keep:
            decorators = ''.join('@%s\n' % ast.unparse(d) for d in getattr(node, 'decorator_list', ()))
            out.append(decorators+ast.get_source_segment(text, node, padded=True))
    return '\n\n'.join(out)


I = types.ModuleType('I')
exec('from dataclasses import dataclass\n'+pick(SHAPES, {'Shape', 'add_shape', 'multiply_shape'}), I.__dict__)
LKEEP = {'_check', '_size', 'ZERO', 'RationalGrowth', '_inline_resources', '_FRACTION_ZERO_SIZE',
         '_INLINE_RESOURCES_SHA256', '_INLINE_CHECKED', '_inline_checked', '_NO_INLINE', '_py_int'}
PRE = ('import sys\nfrom fractions import Fraction\nfrom pathlib import Path\nfrom hashlib import sha256\n'
       'from concurrent.futures import CancelledError\n')


def build(text):
    ns = {'__name__': 'l', 'I': I}
    exec(PRE+pick(text, LKEEP), ns)
    return types.SimpleNamespace(**ns)


GKEEP = {'_count', 'RationalShape', '_product_bits', 'Growth', 'operation_growth', '_installed_policy',
         'native_slot_allowance'}


def gmp_module(text):
    m = types.ModuleType('private_heat_gmp_resources_r1')
    m.__file__ = str(GMP_PATH)
    exec('import sys\nimport gmpy2 as G\nfrom dataclasses import dataclass\n'+pick(text, GKEEP), m.__dict__)
    return m


def outcome(fn):
    try:
        v = fn()
        return ('ok', type(v).__name__, repr(v))
    except BaseException as e:  # noqa: B036
        return ('raise', type(e).__name__, str(e))


def show(label, a, b):
    print(('DIFF ' if a != b else 'same ')+label)
    print('   OLD', a)
    print('   NEW', b)


OLD, NEW = build(SOURCE), build(AFTER)
R = gmp_module(GMP)
sys.modules['private_heat_gmp_resources_r1'] = R
x = I.Shape(5, 3, False)
print('NEW inlines with R:', NEW.RationalGrowth(G, R, None)._inline is R)
show('sanity slot', outcome(lambda: OLD.RationalGrowth(G, R, None).slot(x)), outcome(lambda: NEW.RationalGrowth(G, R, None).slot(x)))


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


for n in (40, G.mpz(40)):
    va, vb = Counting(n, 9), Counting(n, 9)
    ra, rb = outcome(lambda: OLD.RationalGrowth(G, R, None).slot(va)), outcome(lambda: NEW.RationalGrowth(G, R, None).slot(vb))
    show('case2 slot result, numerator %r' % (n,), ra, rb)
    show('case2 slot attribute reads, numerator %r' % (n,), ''.join(va.reads), ''.join(vb.reads))


class Drifting:
    denominator = 9

    def __init__(self):
        self.k = 0

    @property
    def numerator(self):
        self.k += 1
        return 10 if self.k == 1 else -1


show('case2c slot, numerator 10 on first read then -1', outcome(lambda: OLD.RationalGrowth(G, R, None).slot(Drifting())),
     outcome(lambda: NEW.RationalGrowth(G, R, None).slot(Drifting())))


class NoNum:
    denominator = 3


a, b = OLD.RationalGrowth(G, R, None), NEW.RationalGrowth(G, R, None)
del a.resources, b.resources
show('case3 slot, resources deleted and value lacks numerator', outcome(lambda: a.slot(NoNum())), outcome(lambda: b.slot(NoNum())))

calls = []
saved = R.native_slot_allowance
R.native_slot_allowance = lambda shape: calls.append(1) or saved(shape)
OLD.RationalGrowth(G, R, None).slot(x)
k = len(calls)
NEW.RationalGrowth(G, R, None).slot(x)
show('case4 R.native_slot_allowance calls in one slot()', k, len(calls)-k)
R.native_slot_allowance = saved

revised = GMP.replace('    return 160+8*limbs\n', '    return 168+8*limbs\n')
assert revised != GMP
M = gmp_module(revised)                    # file on disk is 5ada7b86; loaded code is a later revision
sys.modules['private_heat_gmp_resources_r1'] = M
print('case5a NEW inlines with M:', NEW.RationalGrowth(G, M, None)._inline is M)
show('case5a slot, loaded code differs from the hashed file', outcome(lambda: OLD.RationalGrowth(G, M, None).slot(x)),
     outcome(lambda: NEW.RationalGrowth(G, M, None).slot(x)))
M2 = gmp_module(GMP)
sys.modules['private_heat_gmp_resources_r1'] = M2
NEW.RationalGrowth(G, M2, None)            # verdict cached for M2
exec('import sys\nimport gmpy2 as G\nfrom dataclasses import dataclass\n'+pick(revised, GKEEP), M2.__dict__)  # reload in place
show('case5b slot after in-place re-execution of M2 (reload)', outcome(lambda: OLD.RationalGrowth(G, M2, None).slot(x)),
     outcome(lambda: NEW.RationalGrowth(G, M2, None).slot(x)))
print('case6 instance attrs OLD', sorted(vars(OLD.RationalGrowth(G, R, None))), 'NEW', sorted(vars(NEW.RationalGrowth(G, R, None))))

# ---- r3 additions -------------------------------------------------------------------------------
sys.modules['private_heat_gmp_resources_r1'] = R


class Flip:
    """RationalGrowth subclass whose resources property alternates between R and a copy namespace."""


def flipping(m, seq):
    class F(m.RationalGrowth):
        @property
        def resources(self):
            self.log.append('r')
            return seq[(len(self.log)-1) % len(seq)]

        @resources.setter
        def resources(self, value):
            pass
    f = F(G, R, None)
    f.log = []
    f._inline = R if hasattr(m, '_NO_INLINE') else None
    return f


copy = types.SimpleNamespace(**{k: getattr(R, k) for k in GKEEP})
copy.native_slot_allowance = lambda shape: 7+R.native_slot_allowance(shape)
for seq, label in (([R, copy], 'R then copy'), ([copy, R], 'copy then R'), ([R, R], 'R, R')):
    a, b = flipping(OLD, seq), flipping(NEW, seq)
    show('case7 slot with resources property %s' % label, (outcome(lambda: a.slot(x)), a.log), (outcome(lambda: b.slot(x)), b.log))

for v in (I.Shape(True, 3, False), I.Shape(5, 0, False), I.Shape(5, G.mpz(3), False), I.Shape(-1, 3, False),
          I.Shape(1 << 70, 3, False), I.Shape(0, 1, True), I.Shape(5, 3.0, False), I.Shape('3', 3, False)):
    show('case8 slot %r' % (v,), outcome(lambda: OLD.RationalGrowth(G, R, None).slot(v)),
         outcome(lambda: NEW.RationalGrowth(G, R, None).slot(v)))

for res, label in ((None, 'None'), (object(), 'object()'), (NEW._NO_INLINE, 'NEW._NO_INLINE itself')):
    a, b = OLD.RationalGrowth(G, res, None), NEW.RationalGrowth(G, res, None)
    show('case9 op(multiply) with resources=%s' % label, outcome(lambda: a.op('multiply', x, x)), outcome(lambda: b.op('multiply', x, x)))
del sys.modules['private_heat_gmp_resources_r1']
a, b = OLD.RationalGrowth(G, None, None), NEW.RationalGrowth(G, None, None)
show('case9b op with resources=None, module unloaded', outcome(lambda: a.op('multiply', x, x)), outcome(lambda: b.op('multiply', x, x)))
