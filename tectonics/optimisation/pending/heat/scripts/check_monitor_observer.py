"""Pre-use checks for ab_heat_r2's sys.monitoring proof observer (coordinator conditions, 16 Oct).

1. Same captures as r1. A toy issuer file (basename private_heat_native_issuer_r13.py) runs one
   flow under r1's sys.setprofile observer and once under r2's. The flow includes:
   - a capture function that raises;
   - an advance() that returns None;
   - the legacy capture;
   - a non-issuer function named advance;
   - the r13 capture that ends observation;
   - a later legacy call that must NOT be captured.
   The files written must be byte-identical and non-empty.
2. The real issuer's two capture functions contain no yield. setprofile reports a yield as a
   'return', but PY_RETURN does not, so a yield would make r2 differ from r1. Neither touches
   threads (setprofile is per thread; sys.monitoring is global).
3. Loaded-identity code digests stay unchanged. Real lw helpers run while r2's observer is
   active: exact_growth, gmp_resources, low_ledger and the issuer module. Then:
   - LoadedIdentity.verify passes;
   - every function's normalised marshal digest and co_code equal those taken before the
     observer;
   - after stop() no monitoring tool is left registered.
Exit code 0 only if every check passes.
"""
import ast
import hashlib
import importlib.util
import json
import marshal
import sys
import tempfile
import types
from pathlib import Path

HS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HS/'scripts'))
import ab_heat as A1  # noqa: E402
import ab_heat_r2 as A2  # noqa: E402

LAYOUT = HS/'lw'
sys.path[:0] = json.loads((LAYOUT/'control.json').read_text(encoding='utf8'))['paths']
failures = []


def check(ok, what):
    print(('PASS ' if ok else 'FAIL ')+what)
    if not ok:
        failures.append(what)


TOY = '''
import numpy as np


class Snap:
    def __init__(self, data):
        self._metadata = bytearray(data)


class Legacy:
    def __init__(self, data):
        self._snapshot = Snap(data)


class Result:
    def __init__(self, arrays):
        self._arrays = arrays
        self.array_names = tuple(arrays)

    def array(self, name):
        return self._arrays[name]


def advance_legacy_packaging(data, fail=False):
    if fail:
        raise RuntimeError('planned')
    return Legacy(data)


def advance(n):
    if n == 0:
        return None
    return Result({'temperature_k': np.arange(n, dtype=np.float64)*1.5,
                   'enthalpy_j': np.array([[1, 2], [3, 4]], dtype=np.int64)*n})
'''
OTHER = '''
def advance():
    return 7
'''


def load(path, name, text):
    path.write_text(text, encoding='utf8')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tmp = Path(tempfile.mkdtemp())
(tmp/'toy').mkdir()
toy = load(tmp/'toy'/A1.ISSUER, 'toy_issuer_r13', TOY)
other = load(tmp/'toy'/'other_module.py', 'toy_other', OTHER)


def flow():
    try:
        toy.advance_legacy_packaging(b'{"never": 1}', fail=True)
    except RuntimeError:
        pass
    toy.advance(0)
    toy.advance_legacy_packaging(b'{"k": 1, "v": [1, 2, 3]}')
    other.advance()
    toy.advance(5)
    toy.advance_legacy_packaging(b'{"after": "end"}')


out1, out2 = tmp/'r1', tmp/'r2'
sys.setprofile(A1._observer(out1))
try:
    flow()
finally:
    sys.setprofile(None)
stop = A2._observer(out2)
try:
    flow()
finally:
    stop()
files1 = {p.name: p.read_bytes() for p in sorted(out1.iterdir())}
files2 = {p.name: p.read_bytes() for p in sorted(out2.iterdir())}
check(sorted(files1) == ['arrays.json', 'enthalpy_j.npy', 'legacy_metadata.json', 'temperature_k.npy'],
      'r1 toy captures are the expected 4 files: %s' % sorted(files1))
check(files1 == files2, 'r2 toy captures byte-identical to r1 (%d files)' % len(files2))
check(files1.get('legacy_metadata.json') == b'{"k": 1, "v": [1, 2, 3]}', 'legacy capture is the pre-end call')
check(all(sys.monitoring.get_tool(i) is None for i in range(6)), 'no monitoring tool left after stop()')

issuer_file = LAYOUT/'helpers'/A1.ISSUER
tree = ast.parse(issuer_file.read_text(encoding='utf8'))
caps = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in ('advance', 'advance_legacy_packaging')]
check(len(caps) == 2 and not any(isinstance(x, (ast.Yield, ast.YieldFrom)) for n in caps for x in ast.walk(n)),
      'real issuer: %d capture functions, none yields' % len(caps))
check('threading' not in issuer_file.read_text(encoding='utf8'), 'real issuer does not use threading')

import gmpy2 as G  # noqa: E402
import private_heat_loaded_identity_r1 as LOADED  # noqa: E402
import private_heat_exact_growth_r1 as EG  # noqa: E402
import private_heat_gmp_resources_r1 as RES  # noqa: E402
import private_heat_interval_inventory_r1 as I  # noqa: E402
import private_heat_low_ledger_inventory_r1 as LL  # noqa: E402
import private_heat_native_issuer_r13 as ISS  # noqa: E402
from atlas_tectonics import reuse as REUSE  # noqa: E402

modules = [EG, RES, LL, ISS]
guard = LOADED.LoadedIdentity(modules)


def functions():
    out = {}
    for m in modules:
        for label, f in LOADED._members(m):
            if type(f) is types.FunctionType:
                out[m.__name__+'.'+label] = (hashlib.sha256(marshal.dumps(REUSE._normal_code(f.__code__), 2)).hexdigest(),
                                             f.__code__.co_code)
    return out


before = functions()


class Lease:
    count = 0


class Work:
    lease = Lease()

    def resize_before_allocation_or_after_drop(self, count):
        self.lease.count = count


stop = A2._observer(tmp/'r2-identity')
try:
    a = EG.Arithmetic(Work(), G, scalar_slots=16, container_bytes=256, initial_bits=8)
    for k in range(200):
        a.rational(('add', 'subtract', 'multiply', 'divide')[k % 4], G.mpq(k+1, 7), G.mpz(k+3))
        a.q(G.mpq(k, 3))
    g = LL.RationalGrowth(G, RES, None)
    for k in range(200):
        g.op(('add', 'subtract', 'multiply', 'divide')[k % 4], I.Shape(5+k % 7, 3, False), I.Shape(7, 2, True))
    after_active = functions()
    guard.verify(modules)
    check(True, 'LoadedIdentity.verify passes while the r2 observer is active (after %d calls)' % 800)
finally:
    stop()
check(after_active == before, 'normalised marshal digests and co_code unchanged for %d functions' % len(before))
guard.verify(modules)
check(functions() == before, 'digests unchanged after stop()')
check(all(sys.monitoring.get_tool(i) is None for i in range(6)), 'no monitoring tool left after the identity run')
print('RESULT', 'PASS' if not failures else 'FAIL %d' % len(failures))
sys.exit(1 if failures else 0)
