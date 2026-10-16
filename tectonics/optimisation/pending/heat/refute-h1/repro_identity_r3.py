"""LoadedIdentity stability for r3 across q/rational/reserve and every route switch, with the
original, H1a r3 alone, and a negative control (r3 with the cache renamed to upper case)."""
import importlib.util
import sys
from pathlib import Path

import common_r3 as C
import private_heat_loaded_identity_r1 as LOADED

G, RES = C.G, C.RES
OUT = Path(__file__).resolve().parent/'loaded_r3'


class SameG:
    def __getattr__(self, name):
        return getattr(G, name)


class ProxyR:
    def __getattr__(self, name):
        return getattr(RES, name)


def steps(module):
    class Over(module.Arithmetic):
        def _integer(self, value):
            return super()._integer(value)
    a = module.Arithmetic(C.Work(), G, scalar_slots=77, container_bytes=999, initial_bits=8)
    b = Over(C.Work(), G, scalar_slots=77, container_bytes=999, initial_bits=8)
    yield 'q int/mpz/mpq', lambda: (a.q(5), a.q(G.mpz(-9)), a.q(G.mpq(3, 8)))
    yield 'q bad', lambda: C.outcome(lambda: a.q(1.5))
    yield 'rational x4+bogus', lambda: [C.outcome(lambda op=op: a.rational(op, G.mpq(1, 3), 7))
                                        for op in ('add', 'subtract', 'multiply', 'divide', 'bogus')]
    yield 'reserve hit/miss', lambda: (a.reserve(a.peak_bits), a.reserve(a.peak_bits+100), a.reserve(1))
    yield 'slots/containers change', lambda: (setattr(a, 'slots', a.slots+20), a.reserve(a.peak_bits))
    yield 'G replaced', lambda: (setattr(a, 'G', SameG()), a.q(G.mpq(1, 9)), a.rational('add', 1, 2),
                                 setattr(a, 'G', G))
    yield 'R proxy', lambda: (setattr(a, 'R', ProxyR()), a.rational('multiply', 3, 4), a.reserve(a.peak_bits),
                              setattr(a, 'R', RES))
    yield 'override subclass', lambda: (b.q(7), b.rational('add', G.mpq(2, 3), 5))
    yield 'sys.modules churn', lambda: churn(a)


def churn(a):
    saved = sys.modules.pop('private_heat_gmp_resources_r1')
    try:
        a.q(G.mpq(4, 5))
        a.rational('divide', 2, 3)
    finally:
        sys.modules['private_heat_gmp_resources_r1'] = saved


variants = (('original', C.SOURCE), ('h1a_r3', C.AFTER_A), ('h1a_h1c_r3', C.AFTER_C),
            ('negative_control_upper_cache', C.AFTER_C.replace('_inline_checked', '_INLINE_CHECKED')))
for label, text in variants:
    name = 'refute_identity3_'+label
    path = OUT/(name+'.py')
    path.write_bytes(text.encode('utf8'))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    guard = LOADED.LoadedIdentity([module])
    first_bad = None
    for step, fn in steps(module):
        fn()
        r = C.outcome(lambda: guard.verify([module]))
        if r[0] != 'ok' and first_bad is None:
            first_bad = (step, r[1:])
    print('%-30s identity stable through all steps: %-5s first failure: %s' % (label, first_bad is None, first_bad))
