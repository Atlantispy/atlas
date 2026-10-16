"""S1 tests: closed_owned_r4 against r5 (exact endpoint certificate reuse), plus stale-reuse mutants.

Run: <.r44-env python> -B test_s1_closed_reuse.py LAYOUT S1_DIR   (PYTHONHASHSEED=0; prints CASE lines, exit 0 = PASS)
LAYOUT is a prepared control layout (its control.json paths are put on sys.path, read-only); S1_DIR holds the
generated private_heat_closed_owned_r5.py and private_heat_finish_kernel_r11.py.

1. Small synthetic CLOSED systems, each run through r4 and r5 on fresh budgets:
   full (theta 1), same (candidate = low), bisect (64 refinements), zero (bisection that stays at theta 0) and
   refused (both endpoints fail). The returned guard values (energies, faces, theta, selection, three certificates)
   or the SupplyGuardRefused evidence must be deeply equal (exact rationals, float bits). Every budget returns to 0
   (a refusal's lease is released once its error is collected).
2. Certificate/admissible evaluations, counted by the existing geometry observer's tick mechanism on the two closure
   code objects (the M proposal): r4 4/1, 70/67, 70/67, 4/2; r5 2/1, 67/67, 66/67, 2/2. Operations and retained bytes
   of r5's stage inventory are no higher than r4's.
3. Mutants generated from r5's text (exact-once edits): theta confusion at 1 and at 0, energies changed after the
   endpoint certificates, face transfers changed after them. Each must refuse with its stale-certificate message. A last
   mutant (theta confusion with the staleness check removed) shows that the check is what refuses: it returns a
   wrong certificate without refusing.
4. finish_kernel_r11 differs from r10 only in its docstring and its Q import, and binds r5.
"""
import difflib
import gc
from fractions import Fraction as F
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types

LAYOUT, S1 = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
sys.path[:0] = [str(S1)] + json.loads((LAYOUT/'control.json').read_text(encoding='utf8'))['paths']
import gmpy2 as G  # noqa: E402
from atlas_tectonics.resources import WorkBudget  # noqa: E402
import private_heat_closed_owned_r4 as Q4  # noqa: E402
import private_heat_closed_owned_r5 as Q5  # noqa: E402
import private_heat_finish_arithmetic_r1 as A  # noqa: E402
import private_heat_geometry_observer_r1 as OBS  # noqa: E402

REPORT = []


def case(name, ok, detail=''):
    REPORT.append((name, bool(ok)))
    print('CASE %s %s %s' % (name, 'PASS' if ok else 'FAIL', detail))


def canon(value):
    if isinstance(value, dict):
        return ('d', tuple((k, canon(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return (type(value).__name__, tuple(canon(v) for v in value))
    if type(value) is type(G.mpq(0)):
        return ('q', int(value.numerator), int(value.denominator))
    if type(value) is float:
        return ('f', value.hex())
    if value is None or type(value) in (bool, int, str):
        return (type(value).__name__, value)
    raise TypeError('uncanonical %r' % type(value))


def q(x):
    return G.mpq(x.numerator, x.denominator)


def system(kind):
    """old, capacity, low, candidate, low_faces, candidate_faces, bounds for a 6-cell closed chain."""
    dyadic = kind in ('zero', 'refused')
    caps = [F(2)]*6 if dyadic else [F(3+i, 2) for i in range(6)]
    temps = [F(t) for t in (288, 296, 300, 304, 312, 320)] if dyadic else \
        [F(2881, 10), F(2963, 10), F(3007, 10), F(3041, 10), F(3119, 10), F(3203, 10)]
    old = [c*t for c, t in zip(caps, temps, strict=True)]
    pairs = [(i, i+1) for i in range(5)] + [(0, 2), (3, 5)]
    k = F(1, 4) if dyadic else F(1, 13)
    low_q = [k*(temps[i]-temps[j]) for i, j in pairs]
    scale = dict(full=F(3, 2), same=F(1), bisect=F(40), zero=F(-1), refused=F(-1))[kind]
    high_q = [scale*v for v in low_q]

    def energies(qs):
        e = list(old)
        for (i, j), v in zip(pairs, qs, strict=True):
            e[i] -= v
            e[j] += v
        return e
    low, high = energies(low_q), energies(high_q)
    low_t = [e/c for e, c in zip(low, caps, strict=True)]
    if kind == 'zero':
        bounds = (min(low_t), F(400))          # low sits exactly on the lower bound
    elif kind == 'refused':
        bounds = (min(low_t)+F(1, 8), F(400))  # low already violates it
    else:
        bounds = (min(temps)-1, max(temps)+1)
    faces = lambda qs: [(i, j, q(v)) for (i, j), v in zip(pairs, qs, strict=True)] + [(0, None, G.mpq(0))]
    return ([q(v) for v in old], [q(c) for c in caps], [q(v) for v in low], [q(v) for v in high],
            faces(low_q), faces(high_q), [q(b) for b in bounds])


class Guard:
    def __init__(self):
        self.counts = {}

    def phase(self, name):
        pass

    def check(self, force=False):
        return False


def closures(module):
    found = {}
    for const in module._guard.__code__.co_consts:
        if isinstance(const, types.CodeType) and const.co_name in ('certificate', 'admissible'):
            if const.co_name in found:
                raise AssertionError('two closures named ' + const.co_name)
            found[const.co_name] = const
    return found


def geometry():
    pass


def run(module, kind):
    """(kind of outcome, canonical value, counts, inventory) on a fresh budget, observed by the r1 observer."""
    shim = closures(module)
    guard = Guard()
    observer = OBS._Observer(guard, [(geometry, 'geometry')],
                             [(types.SimpleNamespace(__code__=shim['certificate']), 'certificates'),
                              (types.SimpleNamespace(__code__=shim['admissible']), 'admissible')], geometry)
    budget = WorkBudget(1 << 34)
    args = system(kind)
    observer.install()
    try:
        try:
            owner = module.closed_guard(*args, budget=budget)
        except A.SupplyGuardRefused as error:
            outcome = ('refused', str(error), canon(error.evidence))
            inventory = None
        else:
            try:
                outcome = ('passed', canon(owner.value))
                inventory = dict(owner.inventory)
            finally:
                owner.close()
    finally:
        observer.remove()
    # A refusal keeps its workspace charged while the error and its frames live (the existing
    # failure-path policy); the lease is released by a finalizer once that cycle is collected.
    gc.collect()
    return outcome, dict(guard.counts), inventory, budget._used


EXPECTED = {  # kind: (r4 certificates, r5 certificates, admissible, outcome)
    'full': (4, 2, 1, 'passed'), 'same': (4, 2, 1, 'passed'), 'bisect': (70, 67, 67, 'passed'),
    'zero': (70, 66, 67, 'passed'), 'refused': (4, 2, 2, 'refused')}


def differential():
    for kind, (c4, c5, adm, how) in EXPECTED.items():
        o4, n4, i4, u4 = run(Q4, kind)
        o5, n5, i5, u5 = run(Q5, kind)
        theta = None
        if how == 'passed':
            theta = dict(o4[1][1])['theta']
        case('equal-%s' % kind, o4 == o5 and o4[0] == how, 'theta %r' % (theta,))
        case('counts-%s' % kind, n4 == {'certificates': c4, 'admissible': adm} and
             n5 == {'certificates': c5, 'admissible': adm}, 'r4 %s r5 %s' % (n4, n5))
        case('released-%s' % kind, u4 == 0 and u5 == 0, 'used %d %d' % (u4, u5))
        if i4 is not None and i5 is not None:
            lower = (i5['operations'] <= i4['operations'] and i5['retained_array_bytes'] <= i4['retained_array_bytes']
                     and i5['reserved_bytes'] <= i4['reserved_bytes'])
            case('inventory-%s' % kind, lower and (kind not in ('full', 'same') or i5['operations'] < i4['operations']),
                 'ops %d->%d retained %d->%d reserved %d->%d' % (
                     i4['operations'], i5['operations'], i4['retained_array_bytes'], i5['retained_array_bytes'],
                     i4['reserved_bytes'], i5['reserved_bytes']))


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


MUTANTS = {
    'theta-confusion': ([("one: (*states[one], full_check)}", "one: (*states[zero], low_check)}")],
                        'full', 'computed at another theta'),
    'energies-after': ([("    del states\n", "    del states\n    ar.put(difference, 0, ar.op('add', difference[1][0], G.mpq(1, 7)))\n")],
                       'full', 'certified energies differ'),
    'faces-after': ([("    del states\n", "    del states\n    ar.put(dq, 0, ar.op('add', dq[1][0], G.mpq(1, 7)))\n")],
                    'full', 'certified face transfers differ'),
    'zero-theta-confusion': ([("zero: (*states[zero], low_check)", "zero: (*states[one], full_check)")],
                             'zero', 'computed at another theta'),
}


def mutants():
    text = (S1/'private_heat_closed_owned_r5.py').read_text(encoding='utf8')
    with tempfile.TemporaryDirectory() as folder:
        for k, (name, (edits, kind, message)) in enumerate(MUTANTS.items()):
            mutated = text
            for old, new in edits:
                mutated = once(mutated, old, new)
            path = Path(folder)/('mutant_%d.py' % k)
            path.write_bytes(mutated.encode('utf8'))
            try:
                run(load(path, 'closed_mutant_%d' % k), kind)
                case('mutant-' + name, False, 'did not refuse')
            except ArithmeticError as error:
                case('mutant-' + name, 'Stale closed-guard certificate: ' + message == str(error), str(error))
        # The check is load-bearing: theta confusion WITHOUT it returns the low certificate at theta 1.
        mutated = once(text, "one: (*states[one], full_check)}", "one: (*states[zero], low_check)}")
        mutated = once(mutated, 'checked = _reused_certificate(ar, theta, reused, energies, faces)',
                       'checked = dict(reused[3])')
        path = Path(folder)/'mutant_unchecked.py'
        path.write_bytes(mutated.encode('utf8'))
        silent, _, _, _ = run(load(path, 'closed_mutant_unchecked'), 'full')
        honest, _, _, _ = run(Q4, 'full')
        case('mutant-unchecked-is-silent', silent[0] == 'passed' and silent != honest,
             'without the check a stale certificate is returned')


def finish_kernel():
    r10 = (LAYOUT/'helpers/private_heat_finish_kernel_r10.py').read_text(encoding='utf8')
    r11 = (S1/'private_heat_finish_kernel_r11.py').read_text(encoding='utf8')
    changed = sorted(x for x in difflib.ndiff(r10.split('\n'), r11.split('\n')) if x[:2] in ('- ', '+ '))
    expected = sorted(['+ ', '+ R11 is R10 on closed owned r5 (exact endpoint certificate reuse in the closed',
                       '+ guard). Nothing else differs.', '- import private_heat_closed_owned_r4 as Q',
                       '+ import private_heat_closed_owned_r5 as Q'])
    case('r11-diff', changed == expected, repr(changed))
    K = load(S1/'private_heat_finish_kernel_r11.py', 'private_heat_finish_kernel_r11')
    r5 = str((S1/'private_heat_closed_owned_r5.py').resolve())
    case('r11-binds-r5', K.Q is Q5 and K._SOURCES.get(r5) == sha256(Path(r5).read_bytes()).hexdigest() and
         not any(p.endswith('private_heat_closed_owned_r4.py') for p in K._SOURCES))


if __name__ == '__main__':
    differential()
    mutants()
    finish_kernel()
    bad = [name for name, ok in REPORT if not ok]
    print('S1 RESULT', 'PASS' if not bad else 'FAIL %s' % bad, len(REPORT), 'cases')
    sys.exit(1 if bad else 0)
