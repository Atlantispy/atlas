"""Minimal, import-light reproducer: L1 r2 inlines when resources is None.

Takes the EXACT source text of RationalGrowth (+ _check, _size and the L1 module names) from the
original low_ledger (lw, 42054fb2) and from X.transform() of it, plus Shape/add_shape/multiply_shape
from interval_inventory_r1, via ast, and execs them without importing the heavy helper chain.
"""
import ast
import sys
from hashlib import sha256
from pathlib import Path

HS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HS/'transforms'))
import l1_low_ledger_op as X  # noqa: E402

HELPERS = HS/'lw'/'helpers'
SOURCE = (HELPERS/'private_heat_low_ledger_inventory_r1.py').read_bytes().decode('utf8')
assert sha256(SOURCE.encode()).hexdigest().startswith('42054fb2')
AFTER = X.transform(SOURCE)
SHAPES = (HELPERS/'private_heat_interval_inventory_r1.py').read_bytes().decode('utf8')

KEEP = {'_check', '_size', 'ZERO', 'RationalGrowth', '_inline_resources', '_FRACTION_ZERO_SIZE',
        '_INLINE_RESOURCES_SHA256', '_INLINE_CHECKED', '_inline_checked', '_NO_INLINE', '_py_int', 'Shape', 'add_shape', 'multiply_shape'}


def pick(text):
    out = []
    for node in ast.parse(text).body:
        name = getattr(node, 'name', None) or (isinstance(node, ast.Assign) and ast.unparse(node.targets[0]))
        if name in KEEP:
            decorators = ''.join('@%s\n' % ast.unparse(d) for d in getattr(node, 'decorator_list', ()))
            out.append(decorators+ast.get_source_segment(text, node, padded=True))
    return '\n\n'.join(out)


def build(text, label):
    import types
    I = types.ModuleType('I')
    exec('from dataclasses import dataclass\n'+pick(SHAPES), I.__dict__)
    ns = {'__name__': label, 'I': I}
    exec('import sys\nfrom fractions import Fraction\nfrom pathlib import Path\nfrom hashlib import sha256\n'
         'from concurrent.futures import CancelledError\n'+pick(text), ns)
    return ns, I


OLD, I = build(SOURCE, 'old')
NEW, _ = build(AFTER, 'new')


def outcome(fn):
    try:
        v = fn()
        return ('ok', type(v).__name__, repr(v))
    except BaseException as e:  # noqa: B036
        return ('raise', type(e).__name__, str(e))


x, y = I.Shape(5, 3, False), I.Shape(7, 2, True)
print('gmp module in sys.modules:', 'private_heat_gmp_resources_r1' in sys.modules)
a, b = OLD['RationalGrowth'](None, None, None), NEW['RationalGrowth'](None, None, None)
print('NEW._inline:', b._inline, '| resources is _inline:', b.resources is b._inline)
for label, call in (('op multiply', lambda g: g.op('multiply', x, y)),
                    ('op divide', lambda g: g.op('divide', x, y, divisor_power_two=True)),
                    ('total', lambda g: g.total([x, y])),
                    ('slot', lambda g: g.slot(x))):
    ra, rb = outcome(lambda: call(a)), outcome(lambda: call(b))
    print(('DIFF ' if ra != rb else 'same ')+label)
    print('   OLD', ra, 'expression_bits', a.expression_bits)
    print('   NEW', rb, 'expression_bits', b.expression_bits)
