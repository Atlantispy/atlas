"""D1 (transforms/incidence_constant.py) and D2 (transforms/rotated_hoist.py): exact own-file transforms.

Usage: python -B -I test_d1_d2.py WORK SUPPORTS DEEP_DIR
  WORK must not exist; small lane (one child process at a time, no timing). The children import the
  runtime, so they start as production does: PYTHONHASHSEED=0 in a cleaned environment (-s -P, not -I,
  which would ignore it), and each refuses unless sys.flags.hash_randomization is 0. Work units follow
  set order (exact_start_zero stops at its first proof), so the in-situ parity needs the pin.
  SUPPORTS: the IV2 supports file the jets-r1 deep stage read (gzip JSONL, header line first).
  DEEP_DIR: that run's evidence folder; its met iv2-deep-base-s*.jsonl rows, cheapest first, are the
  in-situ candidates.

What it checks, and what each check protects:
1. transform() refusals (second application, unreviewed input, missing or doubled anchors), so a
   stacked or stale input never silently gets a different module.
2. Runtimes from compose_test_runtime.py: pair A is the cand-jets-r1 stack (moving-face input
   c5f2a123, the jets run's candidate) without and with d1det+d2rot; pair B is RC1 without and with
   them. Each pair must differ in exactly the two module files. It prints D2's output sha for c5f2a123.
3. Value identity on a seeded corpus in all four runtimes. D1's helper is compared with coefficient 0
   of the full expression, and D2's _rotated with the original loop (rebuilt from the transform's own
   OLD text). Comparison is by repr, so signed zeros and Decimal exponents count, and it includes
   exception type and message. Logging subclasses of the jets, the interval algebras and omega must
   leave matching call logs, which shows the fast paths are not taken for them. The ref runtime's own
   module (no helper) must give the same outcome hashes as the cand runtime's helper. The branch taken
   is also observed, case by case, with a call counter set on the exact instance (J.sub for D1,
   J.I.point for D2), and it must equal the guard (transforms/D1-D2-KNOWN.md, K2).
4. Mutants of each helper: coefficient 1 read, sign or operand swap, dropped add-of-zero, widened type
   guards and others. Every gating mutant must be caught; mutants proved equivalent are only reported.
5. In situ (pair A): real IV2 deep interface queries run with D1 and D2 instrumented in the cand
   runtime, until both fast paths have run. Every helper call is checked against the full expression,
   and every _rotated call against the original loop on the same posed boxes, without charging the
   arena twice. The ref runtime then runs the same queries, and the records (source digests blanked)
   must be byte-identical.
Accounting: neither helper calls an arena, work or budget method. That is checked by reading the
helpers, and the in-situ records carry work_units and leaves, which must match.
Writes WORK/result.json; exit 0 only if every check holds.
"""
import contextlib
import gzip
import importlib.util
import inspect
import json
import os
import random
import re
import subprocess
import sys
from decimal import Decimal as D
from fractions import Fraction as Q
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
GG = HERE.parent
RC1 = GG.parent/'composed-r1'/'runtime-src'
IM_FILE = 'atlas_tectonics/integration_moving_interface_moments.py'
FM_FILE = 'atlas_tectonics/integration_moving_face_moments.py'
STACK_A = ['growth', 'wp20', 'items_off', 'wp23rot', 'cpcut', 'cpadopt', 'q2fast', 'jetsfast']
NEW = ['d1det', 'd2rot']
D1_INPUT = '23fb1565e2d1d11e9d29835ad99e4ca63a24af53843149f47dd01f8357906c9b'
D2_RC1 = '42f2777f4f514b0c34036357aebc7a020aa431b46a43e7c23653897dcdd07dd3'
D2_JETS = 'c5f2a1230f9e13633ad92f9a251ee01e08bac0b2905d9fed90c042402adb8075'
W2 = ('0xef6aca6e197d9db2f69d62da0b', '0xc6ae51dc48000000000000000000000000000000000000')
SEED = 20261016


def load(rel):
    spec = importlib.util.spec_from_file_location(Path(rel).stem, GG/rel)
    assert spec is not None and spec.loader is not None, rel
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(text):
    return sha256(text.encode() if isinstance(text, str) else text).hexdigest()


# ---------------------------------------------------------------------------------------------- child
D1_MUTANTS = [   # (name, old, new, gating)
    ('coef1-inputs (coordinator condition)', 'p, q, r, s = a[0][0], b[1][0], a[1][0], b[0][0]',
     'p, q, r, s = a[0][1], b[1][1], a[1][1], b[0][1]', True),
    ('coef1-fallback', 'return J.sub(J.mul(a[0],b[1]),J.mul(a[1],b[0]))[0]',
     'return J.sub(J.mul(a[0],b[1]),J.mul(a[1],b[0]))[1]', True),
    ('sign swap', 'return I.add(left, I.neg(right))', 'return I.add(right, I.neg(left))', True),
    ('operand swap', 'right = I.add(zero, I.mul(r, s))', 'right = I.add(zero, I.mul(r, q))', True),
    ('no add of zero', 'left = I.add(zero, I.mul(p, q))', 'left = I.mul(p, q)', True),
    ('isinstance jets', 'type(J) is T._Jets', 'isinstance(J, T._Jets)', True),
    ('no intervals guard', ' and type(J.I) is T._Intervals', '', True),
    ('isinstance intervals', 'type(J.I) is T._Intervals', 'isinstance(J.I, T._Intervals)', True),
    ('no budget guard (equivalent: q2 never takes the budget route)', ' and J._convolution_budget is None', '', False),
    ('no lead-zero check (equivalent: a zero lead makes left zero)',
     'if p != zero and q != zero and r != zero and s != zero:', 'if True:', False),
]
D2_MUTANTS = [
    ('rates index swap', 'sub(mul(rates[(j+1) % 3], previous[(j+2) % 3]),',
     'sub(mul(rates[(j+2) % 3], previous[(j+2) % 3]),', True),
    ('inverse 1/(k+1)', 'inverse = point(Q(1, k))', 'inverse = point(Q(1, k+1))', True),
    ('previous hoisted out of k',
     '    for k in range(1, ORDER+1):\n        previous = [c[-1] for c in columns]\n        inverse',
     '    previous = [c[-1] for c in columns]\n    for k in range(1, ORDER+1):\n        inverse', True),
    ('isinstance algebra', 'type(J.I) is _Intervals or type(J.I) is _RationalIntervals',
     'isinstance(J.I, (_Intervals, _RationalIntervals))', True),
    ('no omega type check', ' and all(type(w) is Q for w in omega)', '', True),
    ('isinstance omega', 'type(omega) is tuple', 'isinstance(omega, tuple)', True),
    ('no length check (equivalent: 4-tuples use the first three, 2-tuples raise the same error)',
     ' and len(omega) == 3', '', False),
]


def child():
    if sys.flags.hash_randomization:
        raise SystemExit('the child must start with PYTHONHASHSEED=0, as production does (work units follow set order)')
    mode, runtime, out = sys.argv[2], sys.argv[3], Path(sys.argv[4])
    sys.path.insert(0, str(HERE))
    import rc1_env
    rc1_env.install(runtime)
    from atlas_tectonics import integration_moving_face_moments as FM
    from atlas_tectonics import integration_moving_interface_moments as IM
    from atlas_tectonics import integration_differential_geometry as DG
    d2 = load('transforms/rotated_hoist.py')
    has_d1, has_d2 = hasattr(IM, '_incidence_constant'), d2.NEW in inspect.getsource(FM)

    def d1_ref(a, b, J):
        return J.sub(J.mul(a[0], b[1]), J.mul(a[1], b[0]))[0]

    def d1_fast(a, b, J):   # the helper's own fast-path condition, restated
        if not (type(J) is FM._Jets and J._convolution_budget is None and type(J.I) is FM._Intervals):
            return False
        I, zero = J.I, J.zero
        if any(x == zero for x in (a[0][0], b[1][0], a[1][0], b[0][0])):
            return False
        return I.add(zero, I.mul(a[0][0], b[1][0])) != zero and I.add(zero, I.mul(a[1][0], b[0][0])) != zero

    def d2_fast(omega, J):
        return ((type(J.I) is FM._Intervals or type(J.I) is FM._RationalIntervals) and type(omega) is tuple
                and len(omega) == 3 and all(type(w) is Q for w in omega))

    @contextlib.contextmanager
    def counting(owner, method):
        """Counts calls of owner.<method> with a wrapper set on the instance. The instance keeps its
        exact type, so the guards take the branch they take on a real route (KNOWN K2). This observes the
        branch taken; d1_fast and d2_fast only restate the guard."""
        real, n = getattr(owner, method), [0]

        def wrapper(*a, **k):
            n[0] += 1
            return real(*a, **k)
        if method in vars(owner):
            raise SystemExit('%s already has an instance %s' % (type(owner).__name__, method))
        setattr(owner, method, wrapper)
        try:
            yield n
        finally:
            delattr(owner, method)

    def counted(owner, method, f, *args):
        """Calls of owner.<method> during f(*args), whether or not it raises."""
        with counting(owner, method) as n:
            try:
                f(*args)
            except Exception:
                pass
        return n[0]

    def rebuilt(fn, text_old=None, text_new=None, swap=None):
        """fn rebuilt from its source in a copy of its module's namespace, optionally with one
        replacement (which must occur exactly once)."""
        src = inspect.getsource(fn)
        if swap is not None:
            old, new = swap
            if src.count(old) != 1:
                return None
            src = src.replace(old, new)
        ns = dict(sys.modules[fn.__module__].__dict__)
        exec(compile(src, '<rebuilt %s>' % fn.__name__, 'exec'), ns)
        return ns[fn.__name__]

    if mode == 'insitu' or mode == 'replay':
        return insitu(mode, out, FM, IM, DG, d2, has_d1, has_d2, d1_ref, d1_fast, d2_fast, rebuilt, counting)

    LOG = []

    def logging(base):
        """A subclass of an interval algebra that logs every call (so its type is not the base's)."""
        class Log(base):
            def point(self, q):
                LOG.append(('point', q))
                return base.point(self, q)

            def add(self, a, b):
                LOG.append(('add', a, b))
                return base.add(self, a, b)

            def neg(self, a):
                LOG.append(('neg', a))
                return base.neg(self, a)

            def sub(self, a, b):
                LOG.append(('sub', a, b))
                return base.sub(self, a, b)

            def mul(self, a, b):
                LOG.append(('mul', a, b))
                return base.mul(self, a, b)
        return Log

    LogIntervals, LogRational = logging(FM._Intervals), logging(FM._RationalIntervals)

    class LogJets(FM._Jets):
        def mul(self, a, b):
            LOG.append(('J.mul', a, b))
            return super().mul(a, b)

        def sub(self, a, b):
            LOG.append(('J.sub', a, b))
            return super().sub(a, b)

    class LogTuple(tuple):
        def __getitem__(self, i):
            LOG.append(('omega', i))
            return super().__getitem__(i)

    class FakeBudget:
        @contextlib.contextmanager
        def try_reserve(self, count, *, category='work'):
            LOG.append(('reserve', count, category))
            yield True

    rng = random.Random(SEED)

    def number(mag):
        v = Q(rng.randint(1, 10**6), rng.randint(1, 10**6))*Q(10)**mag
        return -v if rng.random() < 0.5 else v

    def interval(I, mag, kind):
        if kind == 'zero':
            return I.point(0)
        if kind == 'negzero':
            z = I.point(0)
            return (D('-0'), D('-0')) if type(z[0]) is D else z
        if kind == 'expo':   # a short coefficient with a positive exponent (Decimal algebras only)
            z = I.point(0)
            return (D('3E+5'), D('7E+5')) if type(z[0]) is D else I.point(3*10**5)
        x = number(mag)
        if kind == 'point':
            return I.point(x)
        # One endpoint exactly zero: a product with an opposite-sign partner has a -0 upper endpoint,
        # which only the add of zero in J.mul turns into +0 (round 1 run: 'no add of zero' survived).
        if kind == 'lozero':
            return I.point(0)[0], I.point(abs(x))[1]
        if kind == 'hizero':
            return I.point(-abs(x))[0], I.point(0)[1]
        y = abs(number(mag)) if kind == 'straddle' else x + abs(number(mag - 2))
        lo, hi = (-abs(x), y) if kind == 'straddle' else (x, y)
        return I.point(lo)[0], I.point(hi)[1]

    def jet(J, mag, lead):
        if lead == 'jz':
            return J.z
        coefs = [interval(J.I, mag, lead)]
        for _ in range(12):
            kind = rng.choice(('zero', 'zero', 'point', 'point', 'wide', 'straddle'))
            coefs.append(interval(J.I, mag, kind))
        return tuple(coefs)

    def algebras_d1():
        return [('q2', FM._Jets()), ('rational', FM._Jets(FM._RationalIntervals())),
                ('q2+budget', FM._Jets(budget=FakeBudget())),
                ('rational+budget', FM._Jets(FM._RationalIntervals(), budget=FakeBudget())),
                ('logjets', LogJets()), ('log q2', FM._Jets(LogIntervals())), ('log rational', FM._Jets(LogRational()))]

    def corpus_d1():
        cases = []
        for name, J in algebras_d1():
            for n in range(140):
                mag = rng.choice((0, 1, 3, 20, -20, 200, -200))
                leads = ['point']*4
                pick = rng.random()
                if pick < 0.12:
                    leads[rng.randrange(4)] = rng.choice(('zero', 'negzero'))
                elif pick < 0.18:
                    leads[rng.randrange(4)] = 'jz'
                elif pick < 0.35:
                    leads = [rng.choice(('point', 'wide', 'straddle')) for _ in range(4)]
                elif pick < 0.75:   # weighted to zero endpoints: 2/980 cases caught 'no add of zero' at 0.15
                    leads = [rng.choice(('lozero', 'hizero', 'lozero', 'hizero', 'expo', 'point')) for _ in range(4)]
                a0, b1, a1, b0 = (jet(J, mag, lead) for lead in leads)
                if rng.random() < 0.08:   # cancelling products: a0 == a1 and b0 == b1
                    a1, b0 = a0, b1
                cases.append((name, J, (a0, a1, J.z), (b0, b1, J.z)))
        # Signed-zero leads only, on q2 (the fast-path algebra): a -0 upper endpoint of one product survives
        # only without the add of zero, and shows only when the other product has a zero lower endpoint.
        # The weighted band above gave 6 catches (r4); this keeps the 'no add of zero' margin.
        J = FM._Jets()
        for n in range(60):
            mag = rng.choice((0, 1, 3, 20, -20))
            a0, b1, a1, b0 = (jet(J, mag, rng.choice(('lozero', 'hizero'))) for _ in range(4))
            cases.append(('q2 signed-zero', J, (a0, a1, J.z), (b0, b1, J.z)))
        return cases

    def corpus_d2():
        cases = []
        for name, J in [('q2', FM._Jets()), ('rational', FM._Jets(FM._RationalIntervals())),
                        ('log q2', FM._Jets(LogIntervals())), ('log rational', FM._Jets(LogRational()))]:
            for n in range(24):
                mag = rng.choice((0, 2, -3, 30))
                posed = tuple((lo, lo + abs(number(mag - 1))) for lo in (number(mag) for _ in range(3)))
                w = tuple(number(rng.choice((-9, -3, 0, 1))) for _ in range(3))
                kind = ('tuple', 'tuple', 'list', 'ints', 'decimals', 'floats', 'logtuple', 'four', 'two',
                        'bad', 'zero-rate')[n % 11]
                omega = {'tuple': w, 'list': list(w), 'ints': (3, -1, 2), 'decimals': tuple(D('0.125')*k for k in (1, -2, 3)),
                         'floats': (0.5, -0.25, 1.0), 'logtuple': LogTuple(w), 'four': w + (Q(7),), 'two': w[:2],
                         'bad': ('x', None, Q(1)), 'zero-rate': (Q(0), w[1], Q(0))}[kind]
                cases.append((name + '/' + kind, J, posed, omega))
        return cases

    def outcome(f, *args):
        LOG.clear()
        try:
            value = repr(f(*args))
        except Exception as exc:
            value = 'raise %s: %s' % (type(exc).__name__, exc)
        return value + ' | log ' + sha(repr(LOG))[:16]

    real_boxes = DG._rotation_boxes

    def run_d2(f, cases):
        res = []
        for name, J, posed, omega in cases:
            calls = []
            DG._rotation_boxes = lambda *a, posed=posed: (calls.append(len(a)), posed)[1]
            try:
                res.append(outcome(f, ('vector',), omega, (Q(0), Q(1)), J, None) + ' | boxes %s' % calls)
            finally:
                DG._rotation_boxes = real_boxes
        return res

    c1, c2 = corpus_d1(), corpus_d2()
    f1 = IM._incidence_constant if has_d1 else d1_ref
    r1 = [outcome(f1, a, b, J) for _, J, a, b in c1]
    r2 = run_d2(FM._rotated, c2)
    result: dict = dict(runtime=runtime, has_d1=has_d1, has_d2=has_d2, d1_cases=len(c1), d2_cases=len(c2),
                  d1=[sha(x)[:16] for x in r1], d2=[sha(x)[:16] for x in r2],
                  d1_fast=sum(d1_fast(a, b, J) for _, J, a, b in c1), d2_fast=sum(d2_fast(o, J) for _, J, _, o in c2),
                  d1_raises=sum(x.startswith('raise') for x in r1), d2_raises=sum(x.startswith('raise') for x in r2))
    if has_d1 or has_d2:
        # In this process: the helper against the full expression, _rotated against the original loop.
        ref1 = [outcome(d1_ref, a, b, J) for _, J, a, b in c1]
        original = rebuilt(FM._rotated, swap=(d2.NEW, d2.OLD)) if has_d2 else FM._rotated
        ref2 = run_d2(original, c2)
        result['d1_mismatch'] = [c1[i][0] for i in range(len(c1)) if r1[i] != ref1[i]]
        result['d2_mismatch'] = [c2[i][0] for i in range(len(c2)) if r2[i] != ref2[i]]
        # The branch taken, observed: D1's fallback calls J.sub and its fast path never does; D2's fast
        # path makes fewer J.I.point calls than the original loop on the same case.
        if has_d1:
            seen1 = [counted(J, 'sub', f1, a, b, J) == 0 for _, J, a, b in c1]
            result['d1_fast_observed'] = sum(seen1)
            result['d1_fast_disagree'] = [c1[i][0] for i in range(len(c1)) if seen1[i] != d1_fast(c1[i][2], c1[i][3], c1[i][1])]
        if has_d2:
            seen2 = []
            for _, J, posed, omega in c2:
                counts = []
                for f in (FM._rotated, original):
                    DG._rotation_boxes = lambda *a, posed=posed: posed
                    try:
                        counts.append(counted(J.I, 'point', f, ('vector',), omega, (Q(0), Q(1)), J, None))
                    finally:
                        DG._rotation_boxes = real_boxes
                seen2.append(counts[0] < counts[1])
            result['d2_fast_observed'] = sum(seen2)
            result['d2_fast_disagree'] = [c2[i][0] for i in range(len(c2)) if seen2[i] != d2_fast(c2[i][3], c2[i][1])]
        mutants = {}
        for label, fn, table, run, ref in (('D1', IM._incidence_constant if has_d1 else None, D1_MUTANTS,
                                            lambda f: [outcome(f, a, b, J) for _, J, a, b in c1], ref1),
                                           ('D2', FM._rotated if has_d2 else None, D2_MUTANTS,
                                            lambda f: run_d2(f, c2), ref2)):
            if fn is None:
                continue
            for name, old, new, gating in table:
                f = rebuilt(fn, swap=(old, new))
                if f is None:
                    mutants['%s %s' % (label, name)] = dict(applied=False, caught=False, gating=gating)
                    continue
                got = run(f)
                diff = [i for i in range(len(ref)) if got[i] != ref[i]]
                mutants['%s %s' % (label, name)] = dict(applied=True, caught=bool(diff), gating=gating, differ=len(diff))
        result['mutants'] = mutants
    out.write_text(json.dumps(result, indent=1), encoding='utf8')


def insitu(mode, out, FM, IM, DG, d2, has_d1, has_d2, d1_ref, d1_fast, d2_fast, rebuilt, counting):
    """mode insitu (cand, instrumented): run deep queries cheapest first until both fast paths ran and
    at least six queries are done (CPU cap 240 s); mode replay (ref): run exactly that list."""
    import time
    from atlas_tectonics import integration_wall_measures as W
    from atlas_tectonics.resources import WorkBudget
    supports, source = Path(sys.argv[5]), Path(sys.argv[6])
    if mode == 'insitu':
        rows = []
        for p in sorted(source.glob('iv2-deep-base-s*.jsonl')):
            for line in p.read_text(encoding='utf8').splitlines():
                r = json.loads(line)
                if 'support_index' in r and r.get('status') == 'met' and r['cpu_s'] <= 30:
                    rows.append(r)
        rows.sort(key=lambda r: (r['cpu_s'], r['support_index'], r['cell'], r['constraint_name']))
        queries = rows[:40]
    else:
        queries = json.loads(source.read_text(encoding='utf8'))['queries']
    needed = {q['support_index'] for q in queries}
    lines = {}
    with gzip.open(supports, 'rt', encoding='utf8') as f:
        f.readline()
        for index, line in enumerate(f):
            if index in needed:
                lines[index] = line
    stats = dict(d1_calls=0, d1_fast=0, d1_mismatch=0, d1_budgeted=0, d2_calls=0, d2_fast=0, d2_mismatch=0,
                 d1_fast_observed=0, d1_disagree=0, d2_fast_observed=0, d2_disagree=0)
    if mode == 'insitu':
        if not (has_d1 and has_d2):
            raise SystemExit('insitu needs the candidate runtime')
        real_d1, real_rot, real_boxes = IM._incidence_constant, FM._rotated, DG._rotation_boxes
        original_rot = rebuilt(FM._rotated, swap=(d2.NEW, d2.OLD))

        def checked_d1(a, b, J):
            with counting(J, 'sub') as n:   # the fallback calls J.sub; the fast path never does
                value = real_d1(a, b, J)
            stats['d1_calls'] += 1
            stats['d1_fast'] += d1_fast(a, b, J)
            stats['d1_fast_observed'] += n[0] == 0
            stats['d1_disagree'] += (n[0] == 0) != d1_fast(a, b, J)
            if J._convolution_budget is None:   # then the full expression touches no budget
                stats['d1_mismatch'] += repr(d1_ref(a, b, J)) != repr(value)
            else:
                stats['d1_budgeted'] += 1
            return value

        def checked_rot(vector, omega, bounds, J, arena):
            seen = []
            DG._rotation_boxes = lambda *a: (seen.append(real_boxes(*a)), seen[-1])[1]
            try:
                with counting(J.I, 'point') as n_new:
                    value = real_rot(vector, omega, bounds, J, arena)
            finally:
                DG._rotation_boxes = real_boxes
            stats['d2_calls'] += 1
            stats['d2_fast'] += d2_fast(omega, J)
            DG._rotation_boxes = lambda *a: seen[0]   # replay the same posed boxes; no second charge
            try:
                with counting(J.I, 'point') as n_old:
                    again = original_rot(vector, omega, bounds, J, arena)
            finally:
                DG._rotation_boxes = real_boxes
            stats['d2_fast_observed'] += n_new[0] < n_old[0]   # the fast path makes fewer point calls
            stats['d2_disagree'] += (n_new[0] < n_old[0]) != d2_fast(omega, J)
            stats['d2_mismatch'] += len(seen) != 1 or repr(again) != repr(value)
            return value

        IM._incidence_constant, FM._rotated = checked_d1, checked_rot

    def blank(value):
        if isinstance(value, dict):
            return {k: (None if k == 'source_sha256' else blank(v)) for k, v in value.items()}
        if isinstance(value, list):
            return [blank(v) for v in value]
        return value

    budget = WorkBudget(16 << 30, max_predicate_work_units=1 << 44)
    width = W._decode(list(W2))
    done, cpu0 = [], time.process_time()
    for q in queries:
        if mode == 'insitu' and len(done) >= 6 and stats['d1_fast_observed'] and stats['d2_fast_observed']:
            break
        if mode == 'insitu' and time.process_time() - cpu0 > 600:
            break
        row = json.loads(lines[q['support_index']])
        support = DG._issue(DG.DifferentialSupport, row, budget)
        ids = [p['logical_cell_id'] for p in row['components']]

        def full(prefix):
            match = [i for i in ids if i.startswith(prefix)]
            if len(match) != 1:
                raise SystemExit('cell prefix %s matches %d components' % (prefix, len(match)))
            return match[0]
        pair = {} if not q['other'] else dict(other_support=support, other_logical_cell_id=full(q['other']))
        t = time.process_time()
        measure = DG.enclose_component_interface(support, full(q['cell']), q['constraint_name'], max_width_m3=width,
                                                 max_leaves=524288, budget=budget, **pair)
        rec = measure.record()
        done.append(dict({k: q[k] for k in ('support_index', 'cell', 'other', 'constraint_name')},
                         record_sha256=sha(DG._encoded(blank(rec))), measure_sha_nodigest=sha(DG._encoded(blank(rec)))[:16],
                         jets_r1_base_nodigest=q.get('jets_r1_base_nodigest', q.get('measure_sha_nodigest')),
                         work_units=rec.get('work_units'), leaves=rec.get('leaves'), cpu_s=round(time.process_time()-t, 2)))
        print('query', len(done), done[-1]['cpu_s'], 's', stats, flush=True)
    out.write_text(json.dumps(dict(mode=mode, queries=done, stats=stats), indent=1), encoding='utf8')


# --------------------------------------------------------------------------------------------- parent
def parent():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__.split('\n\n')[1])
    work, supports, deep = Path(sys.argv[1]), Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
    if work.exists():
        raise SystemExit('WORK exists')
    work.mkdir(parents=True)
    checks = {}

    def check(name, ok, detail=''):
        checks[name] = dict(ok=bool(ok), detail=detail)
        print('%-72s %s  %s' % (name, 'ok' if ok else 'FAIL', str(detail)[:150]), flush=True)

    def refuses(f, src, want, **k):
        try:
            f(src, **k)
        except ValueError as exc:
            return want in str(exc), str(exc)
        return False, 'no error'

    # 1. transform refusals.
    t1, t2 = load('transforms/incidence_constant.py'), load('transforms/rotated_hoist.py')
    im = (RC1/IM_FILE).read_bytes().decode('utf8')
    fm = (RC1/FM_FILE).read_bytes().decode('utf8')
    check('RC1 inputs are the reviewed ones', sha(im) == D1_INPUT and sha(fm) == D2_RC1, (sha(im)[:8], sha(fm)[:8]))
    o1 = t1.transform(im)
    check('D1 applies to RC1: call replaced once, helper added once',
          o1.count(t1.CALL_NEW) == 1 and t1.CALL_OLD not in o1 and o1.count('\ndef _incidence_constant(') == 1, sha(o1)[:16])
    check('D1 refuses a second application', *refuses(t1.transform, o1, 'already applied', allow_unreviewed_input=True))
    check('D1 refuses an unreviewed input', *refuses(t1.transform, im + '\n', 'not the reviewed'))
    check('D1 refuses a missing call', *refuses(t1.transform, im.replace(t1.CALL_OLD, ''), 'exactly once', allow_unreviewed_input=True))
    check('D1 refuses a doubled call', *refuses(t1.transform, im + t1.CALL_OLD, 'exactly once', allow_unreviewed_input=True))
    check('D1 refuses a missing helper anchor', *refuses(t1.transform, im.replace(t1.HELPER_ANCHOR, '\n\ndef _ray2(ray, bounds, J, arena):\n'),
                                                         'helper anchor', allow_unreviewed_input=True))
    check('D1 refuses a doubled helper anchor', *refuses(t1.transform, im + t1.HELPER_ANCHOR, 'helper anchor', allow_unreviewed_input=True))
    o2 = t2.transform(fm)
    check('D2 applies to RC1: loop replaced once', o2.count(t2.NEW) == 1 and t2.OLD not in o2, sha(o2)[:16])
    check('D2 refuses a second application', *refuses(t2.transform, o2, 'already applied', allow_unreviewed_input=True))
    check('D2 refuses an unreviewed input', *refuses(t2.transform, fm + '\n', 'not a reviewed'))
    check('D2 refuses a missing loop', *refuses(t2.transform, fm.replace(t2.OLD, ''), 'exactly once', allow_unreviewed_input=True))
    check('D2 refuses a doubled loop', *refuses(t2.transform, fm + t2.OLD, 'exactly once', allow_unreviewed_input=True))

    # 2. runtimes.
    def compose(name, names):
        target = work/name
        run = subprocess.run([sys.executable, '-B', '-I', str(HERE/'compose_test_runtime.py'), str(target), *names],
                             capture_output=True, text=True)
        if run.returncode:
            raise SystemExit('compose %s failed: %s' % (name, run.stderr[-400:]))
        return target, json.loads((target/'TEST_COMPOSITION.json').read_text(encoding='utf8'))
    ra, ma = compose('ra', STACK_A)
    rb, mb = compose('rb', STACK_A + NEW)
    rc, mc = compose('rc', NEW)
    rc1_files = {str(p.relative_to(RC1)).replace('\\', '/'): sha(p.read_bytes()) for p in sorted(RC1.rglob('*.py'))}
    step = {m: {t['transform']: t for t in man['transforms']} for m, man in (('a', ma), ('b', mb), ('c', mc))}

    def differ(x, y):
        return sorted(k for k in set(x) | set(y) if x.get(k) != y.get(k))
    check('pair A ref: jetsfast output is c5f2a123', step['a']['jetsfast']['output_sha256'] == D2_JETS)
    check('pair A cand: D1 input 23fb1565, output as on RC1', step['b']['d1det']['input_sha256'] == D1_INPUT
          and step['b']['d1det']['output_sha256'] == sha(o1))
    check('pair A cand: D2 input c5f2a123', step['b']['d2rot']['input_sha256'] == D2_JETS, step['b']['d2rot']['output_sha256'])
    jets_text = (ra/FM_FILE).read_bytes().decode('utf8')
    o2j = t2.transform(jets_text)
    check('D2 on c5f2a123 is reviewed input and matches the composed file',
          sha(o2j) == step['b']['d2rot']['output_sha256'] == sha((rb/FM_FILE).read_bytes()), sha(o2j))
    check('pair A differs in exactly the two modules', differ(ma['files'], mb['files']) == sorted([IM_FILE, FM_FILE]),
          differ(ma['files'], mb['files']))
    check('pair B cand: inputs 23fb1565 / 42f2777f, outputs as above', step['c']['d1det']['input_sha256'] == D1_INPUT
          and step['c']['d2rot']['input_sha256'] == D2_RC1 and step['c']['d2rot']['output_sha256'] == sha(o2))
    check('pair B differs in exactly the two modules', differ(rc1_files, mc['files']) == sorted([IM_FILE, FM_FILE]),
          differ(rc1_files, mc['files']))
    def code_only(text):
        text = re.sub(r'"""[\s\S]*?"""', '', text)
        return '\n'.join(line.split('#')[0] for line in text.splitlines())
    words = [w for w in ('arena', 'reserve', 'charge', 'work', 'budget.', 'spend')
             if w in code_only(t1.HELPER) + code_only(t2.NEW)]
    check('helpers make no arena, work or budget call (code without docstrings and comments)', not words, words)

    # -I would ignore PYTHONHASHSEED, so the children get -s -P and an environment without PYTHON* variables.
    child_env = {k: v for k, v in os.environ.items() if not k.upper().startswith('PYTHON')}
    child_env['PYTHONHASHSEED'] = '0'

    def child_run(mode, runtime, name, *extra):
        p = work/(name + '.json')
        run = subprocess.run([sys.executable, '-B', '-s', '-P', str(Path(__file__).resolve()), '--child', mode, runtime,
                              str(p), *map(str, extra)], capture_output=True, text=True, env=child_env)
        (work/(name + '.log')).write_text(run.stdout + run.stderr, encoding='utf8')
        if run.returncode or not p.exists():
            check('child %s ran' % name, False, (run.stdout + run.stderr)[-300:])
            return None
        return json.loads(p.read_text(encoding='utf8'))

    # 3-4. corpus and mutants.
    for pair, ref_rt, cand_rt in (('A', 'test:%s' % ra, 'test:%s' % rb), ('B', 'rc1', 'test:%s' % rc)):
        ref, cand = child_run('corpus', ref_rt, 'corpus-%s-ref' % pair), child_run('corpus', cand_rt, 'corpus-%s-cand' % pair)
        if ref is None or cand is None:
            continue
        check('pair %s: ref has neither change, cand has both' % pair,
              (ref['has_d1'], ref['has_d2'], cand['has_d1'], cand['has_d2']) == (False, False, True, True))
        check('pair %s: D1 corpus outcomes identical across runtimes (%d cases)' % (pair, cand['d1_cases']),
              ref['d1'] == cand['d1'], sum(x != y for x, y in zip(ref['d1'], cand['d1'])))
        check('pair %s: D2 corpus outcomes identical across runtimes (%d cases)' % (pair, cand['d2_cases']),
              ref['d2'] == cand['d2'], sum(x != y for x, y in zip(ref['d2'], cand['d2'])))
        check('pair %s: in-process helper vs full expression, no mismatch' % pair,
              cand['d1_mismatch'] == [] and cand['d2_mismatch'] == [], (cand['d1_mismatch'][:4], cand['d2_mismatch'][:4]))
        check('pair %s: corpus takes both fast paths and the fallbacks' % pair,
              50 < cand['d1_fast'] < cand['d1_cases'] and 10 < cand['d2_fast'] < cand['d2_cases'] and cand['d2_raises'] > 0,
              'D1 fast %d/%d, D2 fast %d/%d, D2 raises %d' % (cand['d1_fast'], cand['d1_cases'], cand['d2_fast'],
                                                              cand['d2_cases'], cand['d2_raises']))
        check('pair %s: the branch observed (J.sub and point counts) is the guard, case by case' % pair,
              cand.get('d1_fast_disagree') == [] and cand.get('d2_fast_disagree') == []
              and cand.get('d1_fast_observed') == cand['d1_fast'] and cand.get('d2_fast_observed') == cand['d2_fast'],
              'observed D1 %s D2 %s; disagree %s %s' % (cand.get('d1_fast_observed'), cand.get('d2_fast_observed'),
                                                       (cand.get('d1_fast_disagree') or [])[:4], (cand.get('d2_fast_disagree') or [])[:4]))
        for name, m in cand['mutants'].items():
            if m['gating']:
                # 'no add of zero' needs a margin: at 2 of 980 cases a corpus change could lose it silently.
                need = 10 if name == 'D1 no add of zero' else 1
                check('pair %s: mutant %s caught in >= %d cases' % (pair, name, need),
                      m['applied'] and m.get('differ', 0) >= need, m)
            else:
                check('pair %s: equivalent mutant %s applied (informational)' % (pair, name), m['applied'],
                      'caught' if m['caught'] else 'not caught, as expected')

    # 5. in situ, pair A.
    cand = child_run('insitu', 'test:%s' % rb, 'insitu-cand', supports, deep)
    if cand is not None:
        s = cand['stats']
        check('in situ: both helpers observed on the fast path, observation = guard, no mismatch',
              s['d1_fast_observed'] > 0 and s['d2_fast_observed'] > 0 and s['d1_disagree'] == s['d2_disagree'] == 0
              and s['d1_mismatch'] == s['d2_mismatch'] == 0, s)
        listed = work/'insitu-cand.json'
        ref = child_run('replay', 'test:%s' % ra, 'insitu-ref', supports, listed)
        if ref is not None:
            same = [x['record_sha256'] == y['record_sha256'] for x, y in zip(cand['queries'], ref['queries'])]
            check('in situ: %d records byte-identical (digests blanked), work and leaves equal' % len(same),
                  len(same) == len(cand['queries']) == len(ref['queries']) >= 6 and all(same)
                  and all((x['work_units'], x['leaves']) == (y['work_units'], y['leaves'])
                          for x, y in zip(cand['queries'], ref['queries'])), same)
            agree = [x['measure_sha_nodigest'] == x['jets_r1_base_nodigest'] for x in ref['queries']]
            check('in situ (informational): ref records equal the jets-r1 base rows', True, '%d/%d' % (sum(agree), len(agree)))
    ok = all(c['ok'] for c in checks.values())
    d2_out = step['b']['d2rot']['output_sha256']
    (work/'result.json').write_text(json.dumps(dict(ok=ok, checks=checks, d1_output_sha256=sha(o1),
                                                    d2_output_sha256_rc1=sha(o2), d2_output_sha256_on_c5f2a123=d2_out,
                                                    script_sha256=sha(Path(__file__).read_bytes())), indent=1), encoding='utf8')
    print('D1+D2', 'PASS' if ok else 'FAIL', '%d/%d checks' % (sum(c['ok'] for c in checks.values()), len(checks)))
    print('D2 output sha on c5f2a123:', d2_out)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    child() if sys.argv[1:2] == ['--child'] else parent()
