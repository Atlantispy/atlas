"""r2 refuter: original vs G-PY r2 _Jets.mul/div when J.zero is replaced on the instance, plus the r2 deltas.

Usage: python -B repro_zero_replaced.py ORIG_ROOT CAND_FILE
Compares per call: result values (as_tuple), 'is J.zero' pattern, pickle bytes, exception type+text,
lo/hi/thread context flags.
"""
import decimal
import importlib.util
import pickle
import sys
from decimal import Decimal as D

ROOT, FILE = sys.argv[1], sys.argv[2]
sys.path.insert(0, ROOT)
from atlas_tectonics import integration_moving_face_moments as MF  # noqa: E402

spec = importlib.util.spec_from_file_location('atlas_tectonics._gpy_refuter_r2', FILE)
NEW = importlib.util.module_from_spec(spec)
spec.loader.exec_module(NEW)
assert hasattr(NEW, '_gpy_mul') and not hasattr(MF, '_gpy_mul')
N = MF.ORDER + 1
Z = (D(0), D(0))
ONE = (D(1), D(1))
SIG = [decimal.InvalidOperation, decimal.DivisionByZero, decimal.Overflow, decimal.Inexact, decimal.Rounded]


class NeZero(tuple):
    """A zero that reports every coefficient as different from it (custom __ne__ only)."""
    def __ne__(self, other):
        return True


class IterZero(tuple):
    """A zero whose iteration differs from its indexing (unpacking vs zero[0], zero[1])."""
    def __iter__(self):
        return iter((D(5), D(7)))


def flags(ctx):
    return tuple(s.__name__ for s in SIG if ctx.flags[s])


def outcome(module, op, a, b, zero):
    J = module._Jets()
    if zero is not None:
        J.zero = zero
    decimal.getcontext().clear_flags()
    try:
        r = getattr(J, op)(a, b)
        res = ('ok', [tuple(x.as_tuple() for x in p) for p in r], [p is J.zero for p in r],
               pickle.dumps(r, 4).hex()[:0] + str(len(pickle.dumps(r, 4))), pickle.dumps(r, 4))
    except Exception as e:  # noqa: BLE001
        res = ('raise', type(e).__name__, str(e))
    return res, flags(J.I.lo), flags(J.I.hi), flags(decimal.getcontext())


a = (ONE, Z, (D(2), D(3))) + (Z,) * (N - 3)
b = (ONE, (D('-1'), D(4)), Z) + (Z,) * (N - 3)
cases = [
    ('mul, zero kept', 'mul', a, b, None),
    ('mul, zero := equal plain (-0, 0)', 'mul', a, b, (D('-0'), D(0))),
    ('mul, zero := (0, 0) ints', 'mul', a, b, (0, 0)),
    ('mul, zero := NeZero subclass', 'mul', a, b, NeZero(Z)),
    ('div, zero := IterZero subclass', 'div', a, b, IterZero(Z)),
    ('mul, zero := (sNaN, sNaN)', 'mul', a, b, (D('sNaN'), D('sNaN'))),
    ('div, zero := (sNaN, sNaN)', 'div', a, b, (D('sNaN'), D('sNaN'))),
    ('mul, tuple-subclass jet', 'mul', NeZero(a), b, None),
    ('mul, list jet', 'mul', list(a), b, None),
    ('mul, 12-long jet', 'mul', a[:-1], b, None),
    ('div, 14-long jet', 'div', a + (Z,), b, None),
]
diff = 0
for name, op, x, y, zero in cases:
    o, n = outcome(MF, op, x, y, zero), outcome(NEW, op, x, y, zero)
    same = o == n
    diff += not same
    print('%-36s %s' % (name, 'same' if same else 'DIFFERS'))
    if not same:
        for tag, v in (('original', o), ('G-PY r2', n)):
            r = v[0]
            print('   %-8s %s | flags lo %s hi %s thread %s' % (
                tag, (r[0], r[2][:4], 'pickle', r[3]) if r[0] == 'ok' else r, v[1], v[2], v[3]))
print('differing cases:', diff)
