"""Refuter probes for D5 (twins vs reference). Each probe prints REF vs RUN outcome.

Usage: python -B r1.py SCRIPTS RUNTIME BASE
"""
import importlib.util
import json
import sys
import traceback
from contextlib import contextmanager
from fractions import Fraction as Q
from pathlib import Path

scripts, runtime, base = sys.argv[1:4]
sys.path.insert(0, scripts)
import rc1_env  # noqa: E402
rc1_env.install('test:%s' % Path(runtime).resolve().as_posix())
from atlas_tectonics import integration_volume as V  # noqa: E402
from atlas_tectonics import integration_volume_overlap as O  # noqa: E402
from atlas_tectonics import integration_wall_measures as W  # noqa: E402
from atlas_tectonics import integration_wall_measures_gmp as D5  # noqa: E402
from atlas_tectonics import exact_arithmetic as X  # noqa: E402
from atlas_tectonics.resources import WorkBudget  # noqa: E402

REL = 'atlas_tectonics/integration_wall_measures.py'
spec = importlib.util.spec_from_file_location('atlas_tectonics._r1_ref_wm', Path(base).resolve()/REL)
REF = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = REF
spec.loader.exec_module(REF)
print('backend', X.selection()['backend'], 'resident', D5._resident())
LOG = []
USED = []
_orig_twins = dict(clip2=D5.clip2, rotated_normal=D5.rotated_normal, line=D5.line)


def counting(kind):
    def call(*a):
        r = _orig_twins[kind](*a)
        if r is not D5.DECLINED:
            USED.append(kind)
        return r
    return call


D5.clip2, D5.rotated_normal, D5.line = counting('clip2'), counting('rotated_normal'), counting('line')


class Recording(WorkBudget):
    @contextmanager
    def reserve(self, count, *, category='work'):
        LOG.append(('reserve', count, category))
        try:
            with super().reserve(count, category=category):
                yield
        finally:
            LOG.append(('release', count, category))


def outcome(fn, *a):
    LOG.clear()
    USED.clear()
    try:
        r = fn(*a)
        res = ('ok', repr(r)[:120])
    except Exception as exc:
        res = ('raise', type(exc).__name__, str(exc)[:120])
    return res, [e for e in LOG if not (len(e) == 3 and e[2] == 'exact-native-retained')], list(USED)


def pair(label, name, make_args):
    r = outcome(getattr(REF, name), *make_args())
    t = outcome(getattr(W, name), *make_args())
    same = r[0] == t[0] and r[1] == t[1]
    print('==', label, 'SAME' if same else 'DIFFERENT')
    print('   REF', r[0], r[1][:6])
    print('   RUN', t[0], t[1][:6], 'twin used:', t[2])


# P1: arena with no 'resource'; order-0 call (t0 == t1 == 0, derivative nonzero)
class Bare:
    def work(self, n):
        LOG.append(('work', n))


pair('P1 arena without resource, order 0', '_rotated_normal',
     lambda: ((1, 0, 0), (0, 0, 1), Q(0), Q(0), 0, Bare()))


# P2: arena whose resource is not a WorkBudget; order >= 1 call
class BadRes:
    resource = 7

    def work(self, n):
        LOG.append(('work', n))


pair('P2 arena.resource not a budget, order>=1', '_rotated_normal',
     lambda: ((1, 0, 0), (0, 0, 1), Q(0), Q(1), 0, BadRes()))


# P3: arena.resource as a property with side effects (access count), order-0 call
class Prop:
    def __init__(self):
        self.reads = 0
        self.b = Recording(16 << 30)

    @property
    def resource(self):
        self.reads += 1
        LOG.append(('resource-read',))
        return self.b

    def work(self, n):
        LOG.append(('work', n))


pair('P3 arena.resource reads, order 0', '_rotated_normal',
     lambda: ((1, 0, 0), (0, 0, 1), Q(0), Q(0), 0, Prop()))

# P4: ceiling with an admitting budget over 16 GiB (clip2: reference returns poly)
big = Q(1 << (1 << 27))
poly4 = ((0, 0), (1, 0), (0, 1))


class Arena:
    def __init__(self, b):
        self.resource = b

    def work(self, n):
        LOG.append(('work', n))


pair('P4 width>2**27, budget 1 TiB', '_clip2', lambda: (poly4, (Q(0), Q(0), big), Arena(Recording(1 << 40))))
del big

# P5: kernel wrapped mid-call (by arena.work): instrumentation count of O._cross
counts = {}


class Instrumenting:
    def __init__(self):
        self.resource = Recording(16 << 30)
        self.saved = None

    def work(self, n):
        if self.saved is None:
            self.saved = O._cross

            def wrapped(*a):
                counts['cross'] = counts.get('cross', 0)+1
                return self.saved(*a)
            O._cross = wrapped


for name, mod in (('REF', REF), ('RUN', W)):
    counts.clear()
    USED.clear()
    a = Instrumenting()
    try:
        mod._rotated_normal((1, 0, 0), (0, 0, 1), Q(0), Q(1), 0, a)
    finally:
        if a.saved is not None:
            O._cross = a.saved
    print('== P5 O._cross wrapped from arena.work', name, 'wrapper saw', counts.get('cross', 0), 'calls; twin used', USED)

# P6: a second load of the transformed module re-attaches; the first module's wrapped _clip2 is not seen
spec2 = importlib.util.spec_from_file_location('atlas_tectonics._r1_copy_wm', Path(runtime).resolve()/REL)
COPY = importlib.util.module_from_spec(spec2)
sys.modules[spec2.name] = COPY
spec2.loader.exec_module(COPY)
print('P6 attached module now', D5._module.__name__)
poly6 = ((Q(0), Q(0)), (Q(2), Q(0)), (Q(2), Q(2)), (Q(0), Q(2)))
line6 = (Q(1), Q(0), Q(-1))
for name, mod in (('REF', REF), ('RUN', W)):
    original = mod._clip2
    seen = []

    def wrapper(*a, _o=original, _s=seen):
        _s.append(1)
        return _o(*a)
    mod._clip2 = wrapper
    USED.clear()
    try:
        original(poly6, line6, Arena(Recording(16 << 30)))
    finally:
        mod._clip2 = original
    print('== P6 module _clip2 wrapped', name, 'wrapper saw', len(seen), 'inner calls; twin used', USED)
D5.attach('atlas_tectonics.integration_wall_measures')

# P7: non-canonical Fraction input (private constructor): _line value
nc = Q._from_coprime_ints(4, 2)
for name, mod in (('REF', REF), ('RUN', W)):
    USED.clear()
    r = mod._line(((1, 0, 0), (1, 0, 0), (1, 0, 0)), (nc, 0, 0), 0)
    print('== P7 non-canonical', name, [(x.numerator, x.denominator) for x in r], 'twin used', USED)


# P8: revoker on the budget: order-0 call, no reference reservation at all
class Revoker:
    def __init__(self, cm):
        self.cm, self.calls = cm, 0

    def revoke(self):
        self.calls += 1
        if self.cm is not None:
            self.cm.__exit__(None, None, None)
            self.cm = None


for name, mod in (('REF', REF), ('RUN', W)):
    b = WorkBudget(1 << 20)
    hold = b.reserve((1 << 20)-500, category='optional')
    hold.__enter__()
    b._revoker = rv = Revoker(hold)
    USED.clear()
    try:
        r = mod._rotated_normal((1, 0, 0), (0, 0, 1), Q(0), Q(0), 0, Arena(b))
        res = 'ok'
    except Exception as exc:
        res = type(exc).__name__
    b._revoker = None
    print('== P8 revoker', name, res, 'revoke calls', rv.calls, 'twin used', USED)

# P9: category inventory: 61 categories in use; after the call a new category is labelled 'other'?
for name, mod in (('REF', REF), ('RUN', W)):
    b = WorkBudget(1 << 34)
    for i in range(61):
        with b.reserve(1, category='c%d' % i):
            pass
    mod._rotated_normal((1, 0, 0), (0, 0, 1), Q(0), Q(1), 0, Arena(b))
    with b.reserve(1, category='later'):
        pass
    cats = b.statistics()['categories']
    print('== P9 categories', name, 'later' in cats, 'other' in cats, len(cats))
