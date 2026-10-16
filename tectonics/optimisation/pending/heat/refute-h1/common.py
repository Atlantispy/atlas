"""Shared loader for the H1 refutation probes (read-only use of T/hs/lw and T/hs/transforms)."""
import json
import sys
import types
from pathlib import Path

HS = Path(__file__).resolve().parents[1]
LAYOUT = HS/'lw'
sys.path[:0] = json.loads((LAYOUT/'control.json').read_text(encoding='utf8'))['paths']
sys.path.insert(0, str(HS/'transforms'))
import h1_growth_reserve as H1A  # noqa: E402
import h1c_growth_inline as H1C  # noqa: E402
import gmpy2 as G  # noqa: E402
import private_heat_gmp_resources_r1 as RES  # noqa: E402

SOURCE = (LAYOUT/'helpers'/'private_heat_exact_growth_r1.py').read_bytes().decode('utf8')
AFTER_A = H1A.transform(SOURCE)
AFTER_C = H1C.transform(AFTER_A)


def load(name, text):
    module = types.ModuleType(name)
    module.__file__ = str(LAYOUT/'helpers'/(name+'.py'))
    exec(compile(text, module.__file__, 'exec'), module.__dict__)
    return module


OLD = load('refute_old_growth', SOURCE)
MID = load('refute_mid_growth', AFTER_A)
NEW = load('refute_new_growth', AFTER_C)


class Lease:
    def __init__(self):
        self.count = 0


class Work:
    def __init__(self, limit=1 << 42):
        self.lease, self.log, self.limit = Lease(), [], limit

    def resize_before_allocation_or_after_drop(self, count):
        self.log.append((type(count).__name__, count))
        if count > self.limit:
            raise MemoryError('fake refusal %d' % count)
        self.lease.count = count


def outcome(fn):
    try:
        value = fn()
        return ('ok', type(value).__name__, repr(value))
    except BaseException as error:          # noqa: B036 - compared, never swallowed silently
        return ('raise', type(error).__name__, str(error))


def make(module, cls=None, **kw):
    w = Work(kw.pop('limit', 1 << 42))
    args = dict(scalar_slots=77, container_bytes=999, initial_bits=8)
    args.update(kw)
    return (cls or module.Arithmetic)(w, G, **args), w


def state(a, w):
    return (a.peak_bits, type(a.peak_bits).__name__, a.operations, w.lease.count, tuple(w.log))
