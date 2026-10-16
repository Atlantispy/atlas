"""Adversarial differential check of the T/ps P3 coupling candidate against the base module.

Compares value, exact type (including Fraction numerator/denominator types), exception type,
message and notes, and the identity relation of every returned node to the inputs. Identity
relations to the module's own constants are reported separately (expected to differ).
Usage: micro.py [mutant_module_path]   (default: the real candidate in T/ps/c/full)
"""
import contextvars
import hashlib
import importlib.util
import itertools
import math
import pickle
import random
import sys
from fractions import Fraction as Q
from pathlib import Path

import numpy as np

T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
BASE = (T/'fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1'
        /'composed-r2/src/atlas_tectonics/integration_pressure_coupling.py')
sys.path.insert(0, str(T/'ps'/'scripts'))
import rc1_env  # noqa: E402

rc1_env.install('frozen:'+str(T/'ps'/'c'/'full'))
from atlas_tectonics import integration_pressure_coupling as C  # noqa: E402


def load(name, path):
    spec = importlib.util.spec_from_file_location('atlas_tectonics.'+name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


O = load('ps_base_coupling', BASE)
if len(sys.argv) > 1:
    C = load('ps_mutant_coupling', Path(sys.argv[1]))
print('base', hashlib.sha256(BASE.read_bytes()).hexdigest()[:16],
      'candidate', hashlib.sha256(Path(C.__file__).read_bytes()).hexdigest()[:16], flush=True)
assert hasattr(C, '_ZERO_PAIR') and not hasattr(O, '_ZERO_PAIR')

COUNTS = {}
VALUE_DIFFS = []
IDENTITY_DIFFS = {}
OUT_OF_CONTRACT = []


class QS(Q):
    """Fraction subclass, inherits arithmetic."""


class QL(Q):
    """Fraction subclass with a lying comparison."""
    def __lt__(self, other):
        return True


def sig(x, depth=0):
    t = type(x)
    if isinstance(x, Q):
        return (t.__name__, type(x._numerator).__name__, int(x._numerator),
                type(x._denominator).__name__, int(x._denominator))
    if t in (int, bool) or x is None or t is str:
        return (t.__name__, x)
    if t is float:
        return ('float', x.hex() if math.isfinite(x) else repr(x))
    if isinstance(x, np.ndarray):
        return ('ndarray', str(x.dtype), x.shape, x.tobytes())
    if isinstance(x, np.generic):
        return (t.__name__, repr(x))
    if isinstance(x, (tuple, list)):
        out = (t.__name__, tuple(sig(v, depth+1) for v in x))
        if hasattr(x, 'expression'):
            out += (sig(x.expression, depth+1),)
        return out
    return (t.__name__, repr(x))


def nodes(x, out):
    out.append(x)
    if isinstance(x, (tuple, list)):
        for v in x:
            nodes(v, out)
    return out


def alias(result, inputs, constants):
    """Per result node: index of the identical input node, or a constant name, or -1."""
    flat = nodes(inputs, [])
    rel_in, rel_const = [], []
    for node in nodes(result, []):
        rel_in.append(next((i for i, v in enumerate(flat) if v is node), -1))
        rel_const.append(next((k for k, v in constants.items() if v is node), None))
    return tuple(rel_in), tuple(rel_const)


CONST_C = {k: getattr(C, k) for k in ('_ZERO', '_ONE', '_HALF', '_THIRD', '_QUARTER', '_MINUS_QUARTER',
                                      '_ZERO_PAIR', '_JET_ZERO', '_JET_ONE')}


def outcome(fn, make):
    args = make()
    try:
        result = fn(*args)
    except Exception as error:  # noqa: BLE001
        return ('raise', type(error).__name__, str(error), tuple(getattr(error, '__notes__', ()))), None
    return ('ok', sig(result)), (result, args)


def convert(x, module):
    """Rebuild every _RadialJet with the given module's own class (each module copy has its own)."""
    if hasattr(x, 'expression') and isinstance(x, tuple):
        return module._RadialJet(tuple(convert(v, module) for v in x), x.expression)
    if type(x) is tuple:
        return tuple(convert(v, module) for v in x)
    return x


def agree(name, fc, fo, make, contract=True):
    COUNTS[name] = COUNTS.get(name, 0)+1
    a, ra = outcome(fc, lambda: convert(make(), C))
    b, rb = outcome(fo, lambda: convert(make(), O))
    if a != b:
        (VALUE_DIFFS if contract else OUT_OF_CONTRACT).append((name, make(), a, b))
        return
    if ra is not None and contract:
        # Identity relation to the (fresh, equal) inputs of each call, by position.
        ia, ca = alias(ra[0], ra[1], CONST_C)
        ib, _ = alias(rb[0], rb[1], {})
        if ia != ib:
            IDENTITY_DIFFS.setdefault(name+' (input aliasing)', []).append((make(), ia, ib))
        if any(c is not None for c in ca):
            IDENTITY_DIFFS.setdefault(name+' (shares a module constant)', []).append(1)


def nc(n, d):
    return Q._from_coprime_ints(n, d)


rng = random.Random(16102026)
canon = [Q(0), Q(1), Q(-1), Q(1, 2), Q(-1, 2), Q(1, 3), Q(-7, 3), Q(10**40+1, 3**30), Q(-(10**40), 7**20),
         Q(1, 2**200), Q(-1, 2**200), Q(5)]
weird = [0, 1, -1, 2, True, False, 0.0, -0.0, 1.5, float('nan'), float('inf'), np.int64(3), np.float64(0.5),
         QS(1, 2), QS(-3), QL(1, 3), QL(-1, 3), nc(2, 4), nc(-1, -2), nc(1, -2), nc(0, 5), nc(0, -1), nc(3, 1),
         Q(np.int64(3)), Q(np.int64(-2)), 10**50]
pool = canon+weird

# _mul: exhaustive over ordered/unordered canonical pairs, then mixed types and containers.
pairs = list(itertools.product(canon, repeat=2))
for a in pairs:
    for b in pairs:
        agree('_mul canon', C._mul, O._mul, lambda a=a, b=b: (tuple(a), tuple(b)))
for _ in range(40000):
    a = (rng.choice(pool), rng.choice(pool)); b = (rng.choice(pool), rng.choice(pool))
    agree('_mul mixed', C._mul, O._mul, lambda a=a, b=b: (tuple(a), tuple(b)))
containers = [lambda p: tuple(p), lambda p: list(p), lambda p: (x for x in p), lambda p: tuple(p)+(Q(2),),
              lambda p: tuple(p[:1]), lambda p: (), lambda p: O._RadialJet(tuple(p), ('e',)),
              lambda p: C._RadialJet(tuple(p), ('e',))]
for _ in range(20000):
    a = (rng.choice(pool), rng.choice(pool)); b = (rng.choice(pool), rng.choice(pool))
    ka, kb = rng.choice(containers), rng.choice(containers)
    agree('_mul containers', C._mul, O._mul, lambda a=a, b=b, ka=ka, kb=kb: (ka(a), kb(b)))

# _scale
qs = pool+[0, 1, -1, 2, -2, 3, 10**60, -(10**60)]
for a in pairs:
    for q in qs:
        agree('_scale canon', C._scale, O._scale, lambda a=a, q=q: (tuple(a), q))
for _ in range(40000):
    a = (rng.choice(pool), rng.choice(pool)); q = rng.choice(qs); k = rng.choice(containers)
    agree('_scale mixed', C._scale, O._scale, lambda a=a, q=q, k=k: (k(a), q))

# _jet_is_constant
zs = [(0, 0), (Q(0), Q(0)), (0.0, -0.0), (Q(0), 0), (Q(1), Q(0)), [0, 0], (float('nan'),)*2, (False, False),
      (QS(0), QS(0)), (nc(0, -1), nc(0, 5)), (np.int64(0), np.int64(0)), (0,), ()]
for _ in range(30000):
    x = rng.choice(pool); y = x if rng.random() < 0.4 else rng.choice(pool)
    if rng.random() < 0.2 and isinstance(x, Q) and type(x) is Q:
        y = Q(x)  # equal value, distinct object
    z1, z2 = rng.choice(zs), rng.choice(zs)
    agree('_jet_is_constant', C._jet_is_constant, O._jet_is_constant, lambda x=x, y=y, z1=z1, z2=z2: (((x, y), z1, z2),))
agree('_jet_is_constant short', C._jet_is_constant, O._jet_is_constant, lambda: (((Q(1),), (0, 0), (0, 0)),))
agree('_jet_is_constant empty', C._jet_is_constant, O._jet_is_constant, lambda: ((),))

# _dyadic_outward: contract denominators (positive powers of two, as every caller passes) and others.
dens = [1, 2, 4, 1 << 64, 1 << 96, 1 << 128, 1 << 300]
bad_dens = [0, -2, 3, 6, True, np.int64(4), Q(4)]
for x, y in itertools.product(pool, repeat=2):
    for d in dens:
        agree('_dyadic_outward', C._dyadic_outward, O._dyadic_outward, lambda x=x, y=y, d=d: ((x, y), d))
    for d in bad_dens:
        agree('_dyadic_outward out-of-contract', C._dyadic_outward, O._dyadic_outward,
              lambda x=x, y=y, d=d: ((x, y), d), contract=False)

# _jet_outward under several precisions (the ContextVar callers set).
for precision in (0, 1, 7, 96, 128, 400):
    def run(module, jet, precision=precision):
        ctx = contextvars.copy_context()
        def go():
            module._JET_PRECISION.set(precision)
            return module._jet_outward(jet)
        return ctx.run(go)
    for _ in range(1500):
        jet = tuple((rng.choice(pool), rng.choice(pool)) for _ in range(3))
        agree('_jet_outward p%d' % precision, lambda j: run(C, j), lambda j: run(O, j), lambda jet=jet: (jet,))


# Composite jet arithmetic, through each module's own helpers.
def rjet(allow_weird=False):
    src = pool if allow_weird else canon
    kind = rng.random()
    if kind < 0.25:
        v = rng.choice(src)
        return ((v, v), (Q(0), Q(0)), (Q(0), Q(0)))
    if kind < 0.3:
        return ((Q(0), Q(0)), (Q(0), Q(0)), (Q(0), Q(0)))
    if kind < 0.35:
        return ((Q(1), Q(1)), (0, 0), (0, 0))
    jet = tuple(tuple(sorted((rng.choice(canon), rng.choice(canon)))) for _ in range(3))
    if rng.random() < 0.2:
        jet = O._RadialJet(jet, ('sqrt-quadratic', rng.choice(canon)))
    return jet


for _ in range(3000):
    a, b = rjet(), rjet()
    q = rng.choice(canon+[0, 1, -1, 2, 3])
    agree('_jet_add', C._jet_add, O._jet_add, lambda a=a, b=b: (a, b))
    agree('_jet_scale', C._jet_scale, O._jet_scale, lambda a=a, q=q: (a, q))
    agree('_jet_mul', C._jet_mul, O._jet_mul, lambda a=a, b=b: (a, b))
    agree('_jet_reciprocal', C._jet_reciprocal, O._jet_reciprocal, lambda a=a: (a,))
    e = rng.randint(0, 4)
    agree('_jet_power', C._jet_power, O._jet_power, lambda a=a, e=e: (a, e))
    m = rng.random() < 0.5
    agree('_jet_extreme', lambda x, y: C._jet_extreme(x, y, maximum=m), lambda x, y: O._jet_extreme(x, y, maximum=m),
          lambda a=a, b=b: (a, b))
    agree('_same_radial', C._same_radial, O._same_radial, lambda a=a, b=b: (a, b))
    agree('_positive_interval_primitive',
          lambda x, y: C._positive_interval_primitive(x, y, lambda r: C._jet_scale(C._jet_power(r, 3), C._THIRD)),
          lambda x, y: O._positive_interval_primitive(x, y, lambda r: O._jet_scale(O._jet_power(r, 3), Q(1, 3))),
          lambda a=a, b=b: (a, b))
    c, d = rjet(), rjet()
    agree('_donor_radial_pressure', C._donor_radial_pressure, O._donor_radial_pressure,
          lambda a=a, b=b, c=c, d=d: (a, b, c, d))
for _ in range(500):
    a, b = rjet(True), rjet(True)
    q = rng.choice(qs)
    agree('_jet_add weird', C._jet_add, O._jet_add, lambda a=a, b=b: (a, b))
    agree('_jet_scale weird', C._jet_scale, O._jet_scale, lambda a=a, q=q: (a, q))
    agree('_jet_mul weird', C._jet_mul, O._jet_mul, lambda a=a, b=b: (a, b))

# Scalar helpers with replaced literals.
for _ in range(400):
    pts = tuple(tuple(Q(rng.randint(-9, 9), rng.randint(1, 5)) for _ in range(3)) for _ in range(3))
    radial = tuple(sorted((Q(rng.randint(1, 9), rng.randint(1, 3)), Q(rng.randint(1, 9), rng.randint(1, 3)))))
    normal = tuple(Q(rng.randint(-3, 3)) for _ in range(3))
    agree('_radial_linear_mean default rc', C._radial_linear_mean, O._radial_linear_mean, lambda: (pts, radial, normal))
    tri = tuple((Q(rng.randint(0, 9), rng.randint(1, 4)), Q(rng.randint(0, 9), rng.randint(1, 4))) for _ in range(3))
    a3 = tuple(Q(rng.randint(-5, 5)) for _ in range(3)); b3 = tuple(Q(rng.randint(-5, 5)) for _ in range(3))
    agree('_triangle', C._triangle, O._triangle, lambda: (tri, a3, b3, 72))
    planes = [tuple(Q(rng.randint(-3, 3)) for _ in range(4)) for _ in range(rng.randint(0, 4))]
    bottom = Q(rng.randint(0, 5)); top = bottom+Q(rng.randint(0, 5))
    agree('_ray_length', C._ray_length, O._ray_length, lambda: (planes, pts, radial, bottom, top))
    poly = tuple((Q(rng.randint(0, 9)), Q(rng.randint(0, 9))) for _ in range(rng.randint(0, 5)))
    agree('_angular_wedges', C._angular_wedges, O._angular_wedges, lambda: (poly,))

# Pickle bytes of a shared-constant result (identity-only effect, for the report).
pc = pickle.dumps(C._jet_scale(((Q(1), Q(2)), (Q(1), Q(2)), (Q(1), Q(2))), 0))
po = pickle.dumps(O._jet_scale(((Q(1), Q(2)), (Q(1), Q(2)), (Q(1), Q(2))), 0))
print('pickle bytes equal for _jet_scale(...,0):', pc == po, len(pc), len(po))
print('unpickled equal:', pickle.loads(pc) == pickle.loads(po))

print('calls per check:', sum(COUNTS.values()), {k: v for k, v in sorted(COUNTS.items())})
print('VALUE/TYPE/EXCEPTION DIFFS (in contract):', len(VALUE_DIFFS))
for item in VALUE_DIFFS[:12]:
    print('  ', item)
print('OUT-OF-CONTRACT DIFFS (_dyadic_outward with a non-power-of-two/zero/negative denominator):', len(OUT_OF_CONTRACT))
seen = set()
for name, args, a, b in OUT_OF_CONTRACT:
    key = (repr(args[1]), a[0], b[0])
    if key not in seen:
        seen.add(key)
        print('   d=%r pair=%r\n      cand=%r\n      base=%r' % (args[1], args[0], a, b))
for key, items in IDENTITY_DIFFS.items():
    print('IDENTITY-ONLY:', key, len(items), items[0] if 'aliasing' in key else '')
print('MICRO', 'PASS' if not VALUE_DIFFS else 'FAIL', flush=True)
