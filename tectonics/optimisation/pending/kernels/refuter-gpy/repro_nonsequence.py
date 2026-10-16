"""Original vs G-PY _Jets.mul/div when a jet argument is an iterable without len() (or None).

Usage: python -B repro_nonsequence.py ORIG_ROOT CAND_FILE
The candidate's _gpy_mul/_gpy_div call len(a) before the original route runs, so a generator,
map/zip/iterator or None changes the exception message, and an all-zero iterator turns the
original's valid all-zero product into a TypeError.
"""
import importlib.util
import sys
from decimal import Decimal as D

ROOT, FILE = sys.argv[1], sys.argv[2]
sys.path.insert(0, ROOT)
from atlas_tectonics import integration_moving_face_moments as MF  # noqa: E402

spec = importlib.util.spec_from_file_location('atlas_tectonics._gpy_refuter_cand', FILE)
NEW = importlib.util.module_from_spec(spec)
spec.loader.exec_module(NEW)
assert hasattr(NEW, '_gpy_mul') and not hasattr(MF, '_gpy_mul')
N = MF.ORDER + 1
ZERO = (D(0), D(0))
ONE = (D(1), D(1))
b = (ONE,) + (ZERO,) * (N - 1)


def outcome(module, op, make_a, make_b):
    J = module._Jets()
    try:
        r = getattr(J, op)(make_a(), make_b())
        return 'returns %r' % (r[:2],) + ' ...'
    except Exception as e:  # noqa: BLE001
        return 'raises %s(%r)' % (type(e).__name__, str(e))


cases = [
    ('mul(all-zero generator, jet)', 'mul', lambda: (ZERO for _ in range(N)), lambda: b),
    ('mul(iter(nonzero jet), jet)', 'mul', lambda: iter(b), lambda: b),
    ('mul(None, jet)', 'mul', lambda: None, lambda: b),
    ('div(generator, jet)', 'div', lambda: (ONE for _ in range(N)), lambda: b),
    ('div(None, jet)', 'div', lambda: None, lambda: b),
]
diff = 0
for name, op, ma, mb in cases:
    o, n = outcome(MF, op, ma, mb), outcome(NEW, op, ma, mb)
    diff += o != n
    print('%-30s %s\n%-30s original: %s\n%-30s G-PY:     %s' % (name, 'DIFFERS' if o != n else 'same', '', o, '', n))
print('differing cases:', diff)
