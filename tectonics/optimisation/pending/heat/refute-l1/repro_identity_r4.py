"""L1 r4: LoadedIdentity (private_heat_loaded_identity_r1) stability across __init__/op/slot, with the
issuer-style _functions() binding check too. Negative control: the r3b transform (upper-case cache).

The low-ledger module is a real ModuleType whose __file__ is the lw low-ledger file and whose body is
the ast-picked subset (all L1 names, RationalGrowth, _check, _size, ZERO, PUBLIC_BINARY64) of the
transformed source; the gmp module is registered under its reviewed name with the real file as
__file__ and the real function source (as in repro_more_min.py).
"""
import ast
import importlib.util
import json
import sys
import types
from hashlib import sha256
from pathlib import Path

HS = Path(__file__).resolve().parents[1]
sys.path[:0] = json.loads((HS/'lw'/'control.json').read_text(encoding='utf8'))['paths']
import gmpy2 as G  # noqa: E402
import private_heat_loaded_identity_r1 as LI  # noqa: E402

HELPERS = HS/'lw'/'helpers'
LEDGER = HELPERS/'private_heat_low_ledger_inventory_r1.py'
SOURCE = LEDGER.read_bytes().decode('utf8')
SHAPES = (HELPERS/'private_heat_interval_inventory_r1.py').read_bytes().decode('utf8')
GMP_PATH = HELPERS/'private_heat_gmp_resources_r1.py'
GMP = GMP_PATH.read_bytes().decode('utf8')


def transform_module(path):
    spec = importlib.util.spec_from_file_location('l1x_'+path.stem.replace('.', '_'), path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


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
R = types.ModuleType('private_heat_gmp_resources_r1')
R.__file__ = str(GMP_PATH)
exec('import sys\nimport gmpy2 as G\nfrom dataclasses import dataclass\n'+pick(GMP, {
    '_count', 'RationalShape', '_product_bits', 'Growth', 'operation_growth', '_installed_policy',
    'native_slot_allowance', 'native_workspace_allowance'}), R.__dict__)
KEEP = {'_check', '_size', 'ZERO', 'PUBLIC_BINARY64', 'RationalGrowth', '_inline_resources', '_FRACTION_ZERO_SIZE',
        '_INLINE_RESOURCES_SHA256', '_INLINE_CHECKED', '_inline_checked', '_NO_INLINE', '_py_int'}


def ledger(text, name):
    m = types.ModuleType(name)
    m.__file__ = str(LEDGER)
    m.I = I
    exec(compile('import sys\nfrom fractions import Fraction\nfrom pathlib import Path\nfrom hashlib import sha256\n'
                 'from concurrent.futures import CancelledError\n'+pick(text, KEEP), str(LEDGER), 'exec'), m.__dict__)
    return m


def functions(module):   # private_heat_native_issuer_r13._functions, restricted to one module
    out = []
    for name, value in tuple(vars(module).items()):
        if type(value) is types.FunctionType:
            out.append((module, name, value, value.__code__, repr(value.__defaults__), repr(value.__kwdefaults__)))
        elif isinstance(value, type) and value.__module__ == module.__name__:
            for key, method in tuple(vars(value).items()):
                if type(method) is types.FunctionType:
                    out.append((value, key, method, method.__code__, repr(method.__defaults__), repr(method.__kwdefaults__)))
    return out


def exercise(m):
    sys.modules['private_heat_gmp_resources_r1'] = R
    x, y = I.Shape(5, 3, False), I.Shape(7, 2, True)
    a = m.RationalGrowth(G, R, None)
    assert a._inline is R, 'not on the inline route'
    for op in ('add', 'subtract', 'multiply', 'divide'):
        a.op(op, x, y, divisor_power_two=True)
    a.slot(x); a.scalar_work(); a.total([x, y]); a.choice([x, y])
    for res in (None, object(), m._NO_INLINE, types.SimpleNamespace(**vars(R))):
        b = m.RationalGrowth(G, res, None)
        for call in (lambda: b.op('add', x, y), lambda: b.slot(x)):
            try:
                call()
            except Exception:
                pass
    del sys.modules['private_heat_gmp_resources_r1']
    m.RationalGrowth(G, None, None); m.RationalGrowth(G, R, None)
    sys.modules['private_heat_gmp_resources_r1'] = R
    a2 = m.RationalGrowth(G, R, None)
    a2.resources = None
    try:
        a2.op('add', x, y)
    except Exception:
        pass


def check(label, text):
    m = ledger(text, 'private_heat_low_ledger_inventory_r1')
    guard = LI.LoadedIdentity([m])
    rec = json.loads(guard._encoded)
    l1_constants = sorted(k for k in rec['constants'] if k.split('.')[-1] in KEEP - {'RationalGrowth', '_check', '_size'})
    before_funcs = functions(m)
    snapshot = {k: (v, repr(v)) for k, v in vars(m).items() if not k.startswith('__')}
    exercise(m)
    try:
        guard.verify([m])
        verdict = 'verify PASSED'
    except ValueError as e:
        verdict = 'verify REFUSED: %s' % e
    bad = [(mod, n) for mod, n, f, c, d, k in before_funcs
           if getattr(mod, n) is not f or f.__code__ is not c or repr(f.__defaults__) != d or repr(f.__kwdefaults__) != k]
    changed = sorted(k for k, (v, r) in snapshot.items() if vars(m).get(k) is not v or repr(vars(m).get(k)) != r)
    class_inline = m.RationalGrowth.__dict__.get('_inline') is m.__dict__.get('_NO_INLINE')
    print('%s: %s | issuer _functions drift: %s | module values changed: %s | class _inline is sentinel: %s'
          % (label, verdict, bad, changed, class_inline))
    print('   captured L1 constants:', l1_constants)


X4 = transform_module(HS/'transforms'/'l1_low_ledger_op.py')
X3 = transform_module(HS/'transforms'/'history'/'l1_low_ledger_op.r3b.py')
print('r4 transform sha', sha256((HS/'transforms'/'l1_low_ledger_op.py').read_bytes()).hexdigest()[:12])
check('r4 ', X4.transform(SOURCE))
check('r3b (negative control)', X3.transform(SOURCE))
print("isupper:", {n: n.isupper() for n in ('_FRACTION_ZERO_SIZE', '_INLINE_RESOURCES_SHA256', '_NO_INLINE', '_py_int',
                                           '_inline_checked', '_inline_resources', '_INLINE_CHECKED')})
