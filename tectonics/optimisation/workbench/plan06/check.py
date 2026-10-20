"""D5 proof: the installed twins against the unchanged reference code, call by call.

Usage: python -B check.py MODE --scripts DIR --runtime TREE --base TREE [--capture DIR] --out PATH [--seed N]
  MODE all      captured calls (every one, with and without an arena for _clip2), seeded fuzz, the
                instrumentation test, planted mutants (each must be caught), primitives (ceiling boundary,
                dyadic rounding), import order and backend tests (subprocesses); writes OUT (json)
  MODE backend  (subprocess) every twin must decline and gmpy2 must stay unloaded; writes OUT
  MODE imports  (subprocess) import one module first (--first NAME); writes OUT
--scripts is the geometry scripts folder holding rc1_env; --runtime the D5 test composition; --base the
composition it was built from, whose integration_wall_measures.py is loaded beside it as the reference (same
integration_volume/_overlap modules, its own recursion). PYTHONHASHSEED=0.

A call passes only if both routes raise the same (type, text) or neither does and: pickle bytes of
(inputs, result) are equal at protocols 2-5 (values, types, identity relations to the inputs such as `poly`
returned itself or kept vertex objects, shared objects); the deep type shape is equal, including the int type
inside every Fraction; the ordered trace of arena.work(n) and reserve/release (amount, category) is equal
once the twin's NATIVE_RETAINED entries are removed; those entries are positive, balanced and appear only in
_rotated_normal; both budgets are released afterwards; a captured reference result is the captured bytes.
"""
import argparse
import gc
import importlib.util
import json
import os
import pickle
import random
import subprocess
import sys
import time
from hashlib import sha256
from contextlib import contextmanager
from fractions import Fraction as Q
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument('mode', choices=('all', 'backend', 'imports'))
ap.add_argument('--scripts', required=True)
ap.add_argument('--runtime', required=True)
ap.add_argument('--base', required=True)
ap.add_argument('--capture')
ap.add_argument('--out', required=True)
ap.add_argument('--seed', type=int, default=20261016)
ap.add_argument('--fuzz', type=int, default=3000)
ap.add_argument('--mutant-sample', type=int, default=1500)
ap.add_argument('--first', default='integration_wall_measures')
args = ap.parse_args()
if os.environ.get('PYTHONHASHSEED') != '0' or sys.flags.isolated:
    raise SystemExit('requires PYTHONHASHSEED=0 and non-isolated runtime')
out = Path(args.out)
def fail_report(kind, value, tb):
    import traceback
    failure = dict(globals().get('report', {}))
    failure.update(verdict='FAIL', unhandled=repr(value), traceback=''.join(traceback.format_exception(kind, value, tb)))
    out.write_text(json.dumps(failure, indent=1, default=str), encoding='utf8')
    sys.__excepthook__(kind, value, tb)
sys.excepthook = fail_report
REL = 'atlas_tectonics/integration_wall_measures.py'
NAMES = dict(clip2='_clip2', rotated_normal='_rotated_normal', line='_line')

sys.path.insert(0, str(Path(args.scripts).resolve()))
if os.environ.get('D5_BLOCK_GMPY2') == '1':
    sys.modules['gmpy2'] = None     # import gmpy2 fails as if it were absent
import rc1_env  # noqa: E402


def loaded(name):
    return sys.modules.get(name) is not None


if args.mode == 'imports':
    import importlib
    rc1_env.install('test:%s' % Path(args.runtime).resolve().as_posix())
    first = importlib.import_module('atlas_tectonics.' + args.first)
    from atlas_tectonics import exact_arithmetic as X  # noqa: E402
    from atlas_tectonics import integration_wall_measures as W  # noqa: E402
    D5 = sys.modules.get('atlas_tectonics.integration_wall_measures_gmp')
    out.write_text(json.dumps(dict(first=first.__name__, backend=X.selection()['backend'],
                                   attached=D5 is not None and D5._module is W,
                                   resident=D5 is not None and bool(D5._resident()),
                                   gmpy2_loaded=loaded('gmpy2'),
                                   exact_gmp_loaded=loaded('atlas_tectonics.integration_exact_gmp'))),
                   encoding='utf8')
    sys.exit(0)

rc1_env.install('test:%s' % Path(args.runtime).resolve().as_posix())
from atlas_tectonics import exact_arithmetic as X  # noqa: E402
from atlas_tectonics import integration_volume as V  # noqa: E402
from atlas_tectonics import integration_volume_overlap as O  # noqa: E402
from atlas_tectonics import integration_wall_measures as W  # noqa: E402
from atlas_tectonics import integration_exact_twin as E  # noqa: E402
from atlas_tectonics import integration_wall_measures_gmp as D5  # noqa: E402
from atlas_tectonics.integration_volume_bounds import NATIVE_RETAINED  # noqa: E402
from atlas_tectonics.resources import WorkBudget  # noqa: E402

spec = importlib.util.spec_from_file_location('atlas_tectonics._d5_reference_wall_measures',
                                              Path(args.base).resolve()/REL)
REF = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = REF
spec.loader.exec_module(REF)
LOG = []


class Recording(WorkBudget):
    @contextmanager
    def reserve(self, count, *, category='work'):
        LOG.append(('reserve', count, category))
        try:
            with super().reserve(count, category=category):
                yield
        finally:
            LOG.append(('release', count, category))


class Arena:
    def __init__(self, resource, log=True):
        self.resource, self.log = resource, log

    def work(self, count):
        if self.log:
            LOG.append(('work', count))


def shape(v):
    t = type(v)
    if t is tuple or t is list:
        return (t.__name__, tuple(shape(x) for x in v))
    if t is Q:
        return ('Fraction', type(v._numerator).__name__, type(v._denominator).__name__)
    return t.__name__


def run(fn, call):
    LOG.clear()
    try:
        result, error = fn(*call), None
    except Exception as exc:  # compared below, never swallowed
        result, error = None, (type(exc).__name__, str(exc))
    return result, error, list(LOG)


def build(kind, a, budget, arena=True):
    if kind == 'line':
        return a
    if kind == 'clip2' and not arena:
        return a
    return (*a, Arena(budget))


TWIN = dict(clip2=D5.clip2, rotated_normal=D5.rotated_normal, line=D5.line)
USED = dict(clip2=0, rotated_normal=0, line=0)


def counting(kind):
    def call(*a):
        result = TWIN[kind](*a)
        if result is not D5.DECLINED:
            USED[kind] += 1
        return result
    return call


D5.clip2, D5.rotated_normal, D5.line = counting('clip2'), counting('rotated_normal'), counting('line')
NR = dict(calls=0, max=0, total=0)


def compare(kind, a, captured=None, arena=True):
    """Problems (empty list = identical) for one call."""
    b_ref, b_run = Recording(16 << 30), Recording(16 << 30)
    r_res, r_err, r_log = run(getattr(REF, NAMES[kind]), build(kind, a, b_ref, arena))
    t_res, t_err, t_log = run(getattr(W, NAMES[kind]), build(kind, a, b_run, arena))
    problems = []
    if r_err != t_err:
        problems.append('errors %r / %r' % (r_err, t_err))
    if captured is not None and r_err is None and pickle.dumps(r_res, protocol=5) != captured:
        problems.append('reference differs from the captured result')
    for protocol in (2, 3, 4, 5):
        if pickle.dumps((a, r_res), protocol=protocol) != pickle.dumps((a, t_res), protocol=protocol):
            problems.append('pickle(inputs, result) differs at protocol %d' % protocol)
            break
    if shape(r_res) != shape(t_res):
        problems.append('type shape differs')
    native = [e for e in t_log if e[0] != 'work' and e[2] == NATIVE_RETAINED]
    if [e for e in t_log if e[0] == 'work' or e[2] != NATIVE_RETAINED] != r_log:
        problems.append('trace differs')
    if native:
        held = [e[1] for e in native if e[0] == 'reserve']
        if (kind != 'rotated_normal' or min(held) <= 0
                or sorted(held) != sorted(e[1] for e in native if e[0] == 'release')):
            problems.append('NATIVE_RETAINED entries wrong')
        NR['calls'] += 1
        NR['max'] = max(NR['max'], sum(held))
        NR['total'] += sum(held)
    if b_ref.reserved_bytes or b_run.reserved_bytes:
        problems.append('budget not released')
    return problems


def batch(cases, label, report):
    bad, examples = 0, []
    for index, (kind, a, captured, arena) in enumerate(cases):
        problems = compare(kind, a, captured, arena)
        if problems:
            bad += 1
            examples.append(dict(case=index, kind=kind, problems=problems))
    report[label] = dict(cases=len(cases), bad=bad, examples=examples)
    return bad


# ---------------------------------------------------------------- inputs
def captured_cases():
    cases = []
    for kind in NAMES:
        for a_bytes, r_bytes, _ in pickle.loads((Path(args.capture)/('calls-%s.pkl' % kind)).read_bytes()):
            a = pickle.loads(a_bytes)
            cases.append((kind, a, r_bytes, True))
            if kind == 'clip2':
                cases.append((kind, a, r_bytes, False))     # the reference's inner, arena-less call
    return cases


def fuzz_cases(seed, n):
    rng = random.Random(seed)

    def value(scale=1):
        c = rng.random()
        if c < 0.10:
            return rng.choice((0, Q(0)))
        if c < 0.30:
            return rng.randint(-5, 5)*scale
        if c < 0.70:
            return Q(rng.randint(-60, 60)*scale, rng.randint(1, 40))
        if c < 0.90:
            return Q(rng.getrandbits(200)-(1 << 199), rng.getrandbits(160)+1)
        return Q(rng.getrandbits(10000)-(1 << 9999), rng.getrandbits(9000)+1)

    def small():
        # |value| <= 16/7: with |omega| <= 2.3 the Taylor loop ends after a few dozen steps
        return Q(rng.randint(-16, 16), rng.choice((7, 8, 24)) << rng.randint(0, 50))

    cases = []
    for _ in range(n):
        # _clip2: polygons with duplicates and collinear runs, lines through vertices (exact-zero signs)
        size = rng.choice((0, 1, 2, 3, 3, 4, 5, 6, 7))
        poly = []
        for _ in range(size):
            c = rng.random()
            if poly and c < 0.15:
                poly.append(poly[-1])
            elif len(poly) > 1 and c < 0.25:
                (x0, y0), (x1, y1) = poly[-2], poly[-1]
                t = Q(rng.randint(-3, 5), rng.randint(1, 4))
                poly.append((x0+t*(x1-x0), y0+t*(y1-y0)))
            else:
                poly.append((value(), value()))
        poly = tuple(poly)
        if poly and rng.random() < 0.4:
            (x0, y0), (x1, y1) = rng.choice(poly), rng.choice(poly)
            line = (Q(y1-y0), Q(x0-x1), Q(-((y1-y0)*x0+(x0-x1)*y0)))
        else:
            line = tuple(Q(value()) if rng.random() < 0.85 else Q(0) for _ in range(3))
        cases.append(('clip2', (poly, line), None, rng.random() < 0.8))
        # _rotated_normal: moderate rotation (the loop ends), any normal, levels -16..10, zero derivatives
        normal = tuple(value() for _ in range(3))
        c = rng.random()
        if c < 0.08:
            omega = (0, Q(0), 0)
        elif c < 0.14:
            k = Q(rng.randint(-3, 3), rng.randint(1, 5))
            omega = tuple(k*q for q in normal) if all(abs(q) < (1 << 300) for q in normal) else normal
        else:
            omega = tuple(rng.choice((small(), rng.randint(-2, 2))) for _ in range(3))
        t0 = small()
        t1 = t0 if rng.random() < 0.1 else small()
        cases.append(('rotated_normal', (normal, omega, t0, t1, rng.randint(-16, 10)), None, True))
        # _line: faces of 3-4 triples, equal dot products, int/Fraction offsets
        face = tuple(tuple(value() for _ in range(3)) for _ in range(rng.choice((3, 3, 4))))
        if rng.random() < 0.2:
            face = (face[0], face[1], face[1], *face[3:])
        cases.append(('line', (face, tuple(value() for _ in range(3)), rng.choice((0, 3, Q(1, 3), value()))),
                      None, True))
    # declined shapes: the reference's own results and errors through the hook
    for a in (((((1, 2), (3, 4), (0, 5)), (1, 2, 3))), ((((1, 2), (3, 4), (0, 5)), (Q(1), 2.0, Q(0)))),
              (([(Q(1), Q(2)), (Q(3), Q(4)), (Q(0), Q(5))], (Q(1), Q(-2), Q(3)))),
              ((((True, Q(2)), (Q(3), Q(4)), (Q(0), Q(5))), (Q(1), Q(-2), Q(3)))),
              ((((Q(1), Q(2), Q(9)), (Q(3), Q(4)), (Q(0), Q(5))), (Q(1), Q(-2), Q(3)))),
              ((((Q(1), Q(2)), (Q(3), Q(4)), (Q(0), Q(5))), (Q(1), Q(-2)))), ((((Q(1), 2.5),), (Q(1), Q(1), Q(1))))):
        cases.append(('clip2', a, None, True))
    for a in (((1, 2, 3), (Q(1), 0, 0), 0, 1, 0), ((1, 2, 3), (Q(1), 0, 0), Q(0), Q(1), -17),
              ((1, 2, 3), (Q(1), 0, 0), Q(0), Q(1), -600), ((1, 2, 3), (Q(1), 0, 0), Q(1, 3), Q(1), -16),
              ([1, 2, 3], (Q(1), 0, 0), Q(0), Q(1), 0), ((1.5, 2, 3), (Q(1), 0, 0), Q(0), Q(1), 0),
              ((1, 2, 3), (Q(1), 0, 0), Q(0), Q(1), True), ((1, 2, 3), (Q(1), 0), Q(0), Q(1), 0)):
        cases.append(('rotated_normal', a, None, True))
    for a in ((((1, 2, 3), (4, 5, 6), (7, 8, 9)), (1, 0, 2), 0.5), ([(1, 2, 3), (4, 5, 6), (7, 8, 9)], (1, 0, 2), 0),
              (((1, 2, 3), (4, 5, 6)), (1, 0, 2), 0), (((1, 2, 3), (4, 5, 6), (7, 8, 9)), (1, 0), 0),
              (((1, 2, 3), (4, 5, 6), (7, 8, 9)), (1, 0, 2), True)):
        cases.append(('line', a, None, True))
    return cases


# ---------------------------------------------------------------- instrumentation sees every call
def instrumented(cases):
    """Wrap V._work, O._dot, O._cross and each module's _clip2 with counters; both routes must make the
    same calls of them (the twins decline while anything is wrapped)."""
    counts = {}

    def wrap(owner, name, key):
        original = getattr(owner, name)

        def call(*a, **k):
            counts[key] = counts.get(key, 0)+1
            return original(*a, **k)
        setattr(owner, name, call)
        return owner, name, original

    bad = 0
    for kind, a, _, arena in cases:
        seen = []
        for module in (REF, W):
            counts.clear()
            saved = [wrap(V, '_work', 'work'), wrap(O, '_dot', 'dot'), wrap(O, '_cross', 'cross'),
                     wrap(module, '_clip2', 'clip2')]
            try:
                b = Recording(16 << 30)
                run(getattr(module, NAMES[kind]), build(kind, a, b, arena))
            finally:
                for owner, name, original in reversed(saved):
                    setattr(owner, name, original)
            seen.append(dict(counts))
        bad += seen[0] != seen[1]
    return bad


# ---------------------------------------------------------------- planted mutants
SOURCE = Path(D5.__file__).read_text(encoding='utf8')
MUTANTS = (
    ('no dedupe', 'return tuple(p for k, p in enumerate(out) if kept[k] != kept[k-1])', 'return tuple(out)'),
    ('dedupe wrong neighbour', 'kept[k] != kept[k-1]', 'kept[k] != kept[(k+1) % len(kept)]'),
    ('copy of poly', '    if min(signs) >= 0:\n        return poly\n',
     '    if min(signs) >= 0:\n        return tuple(list(poly))\n'),
    ('clip lease count', 'E._work(width, 3+2*len(poly), budget)', 'E._work(width, 4+2*len(poly), budget)'),
    ('step-0 width from natives', 'term_width = sum(V._bits(v) for v in normal)',
     'term_width = sum(E.bits(E.native(v)) for v in normal)'),
    ('no arena.work', '            arena.work(64)\n', '            pass\n'),
    ('early return copies normal', 'return normal, Q(0)', 'return tuple(list(normal)), Q(0)'),
    ('order 0 returns normal', 'return tuple(list(normal)), error', 'return normal, error'),
    ('shared result object', 'return fraction(out[0]), fraction(out[1]), fraction(out[2]-native(offset))',
     'first = fraction(out[0])\n    return first, (first if out[1] == out[0] else fraction(out[1])), fraction(out[2]-native(offset))'),
    ('no offset guard', ' or not E.exact(offset) or', ' or'),
    ('no level guard', ' or level < -16 or', ' or'),
    ('no poly-point guard', 'type(p) is tuple and len(p) == 2 and exact(p[0]) and exact(p[1])', 'True'),
    ('resident ignores wrapped kernels',
     'return not _closed and E.available() and _module is not None and all(map(is_, _current(), _loaded))',
     'return E.available()'),
    ('arena.work after resource', '            arena.work(64)\n            budget = arena.resource\n',
     '            budget = arena.resource\n            arena.work(64)\n'),
    ('surcharge leaked', '    with ExitStack() as retained_stack:\n',
     '    retained_stack = ExitStack()\n    globals().setdefault("_LEAK", []).append(retained_stack)\n    if retained_stack:\n'),
)



def mutant_namespace(old, new):
    if SOURCE.count(old) != 1:
        raise RuntimeError('mutant anchor not unique: %r' % old)
    ns = dict(__name__=D5.__name__, __package__=D5.__package__, __file__=D5.__file__)
    exec(compile(SOURCE.replace(old, new), D5.__file__, 'exec'), ns)
    # the hooks compare against the installed module's sentinel and attachment
    ns['_module'], ns['_loaded'], ns['_closed'], ns['DECLINED'] = D5._module, D5._loaded, D5._closed, D5.DECLINED
    return ns


def mutants(cases, sample_of_instrumented):
    caught = {}
    reference = dict(TWIN)
    for name, old, new in MUTANTS:
        ns = mutant_namespace(old, new)
        TWIN.update(clip2=ns['clip2'], rotated_normal=ns['rotated_normal'], line=ns['line'])
        try:
            # 1-based index of the first case that tells the mutant apart; 'instrumentation' if only that does
            first = next((i+1 for i, c in enumerate(cases) if compare(*c)), 0)
            if not first:
                class BadResource:
                    @property
                    def resource(self):
                        LOG.append(('resource-read',))
                        return 7
                    def work(self, n):
                        LOG.append(('work', n))
                a = ((1,0,0), (0,0,1), Q(0), Q(1), 0)
                rr = run(REF._rotated_normal, (*a, BadResource()))
                tt = run(W._rotated_normal, (*a, BadResource()))
                if rr[1:] != tt[1:]:
                    first = 'work-resource-order'
            if not first and instrumented(sample_of_instrumented):
                first = 'instrumentation'
        finally:
            TWIN.update(reference)
            # a leaked lease released later by the cyclic collector would write into another call's trace
            for kept in ns.get('_LEAK', ()):
                (kept._stack if hasattr(kept, '_stack') else kept).close()
            ns.clear()
            gc.collect()
        caught[name] = first
    original = E.fraction
    E.fraction = lambda q: int(q) if E._denom(q) == 1 else original(q)   # int for integral values
    try:
        caught['int for integral values'] = next((i+1 for i, c in enumerate(cases) if compare(*c)), 0)
    finally:
        E.fraction = original
    return caught


# ---------------------------------------------------------------- primitives
def primitives(seed):
    report = {}
    # D2 ceiling eligibility is exercised at callers in focused checks. D8 has no invented post-reserve error.
    report['lease_alias'] = E.lease is E._work
    from atlas_tectonics.integration_pressure_coupling import _dyadic_outward
    rng = random.Random(seed+1)
    bad = 0
    for _ in range(20000):
        lo = rng.choice((rng.randint(-10**6, 10**6), Q(rng.getrandbits(90)-(1 << 89), rng.getrandbits(70)+1)))
        hi = rng.choice((rng.randint(-10**6, 10**6), Q(rng.getrandbits(90)-(1 << 89), rng.getrandbits(70)+1)))
        d = 1 << rng.randint(0, 96)
        ref = _dyadic_outward((lo, hi), d)
        got = E.dyadic_outward(E.native(lo), E.native(hi), d)
        bad += (E.fraction(got[0]), E.fraction(got[1])) != ref
    report['dyadic_outward mismatches of 20000'] = bad
    return report


def subprocess_json(mode, env_extra, extra=(), runtime=None, tag=''):
    target = out.with_name('%s-%s%s-%s.json' % (out.stem, mode, tag, '-'.join(env_extra.values()) or 'auto'))
    env = {k:v for k,v in os.environ.items() if not k.upper().startswith('PYTHON')}
    env.update(PYTHONHASHSEED='0', **env_extra)
    cmd = [sys.executable, '-B', __file__, mode, '--scripts', args.scripts, '--runtime', runtime or args.runtime,
           '--base', args.base, '--out', str(target), *extra]
    done = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if done.returncode != 0:
        return dict(exit=done.returncode, stderr=done.stderr, stdout=done.stdout)
    return json.loads(target.read_text(encoding='utf8'))


if args.mode == 'backend':
    block = os.environ.get('D5_BLOCK_GMPY2') == '1'
    cases = fuzz_cases(args.seed, 300)
    bad = sum(1 for c in cases if compare(*c))
    out.write_text(json.dumps(dict(selection=X.selection(), available=E.available(), used=USED, bad=bad,
                                   cases=len(cases), blocked=block),
                              default=str), encoding='utf8')
    sys.exit(0)

# ---------------------------------------------------------------- MODE all
t0 = time.time()
report: dict = dict(selection=X.selection(), from_coprime=E._from_coprime is not None,
                    resident=D5._resident(), attached=D5._module is W)
cases = captured_cases()
report['captured_bad'] = batch(cases, 'captured', report)
report['captured_used'] = dict(USED)
for k in USED:
    USED[k] = 0
fuzz = fuzz_cases(args.seed, args.fuzz)
report['fuzz_bad'] = batch(fuzz, 'fuzz', report)
report['fuzz_used'] = dict(USED)
report['native_retained'] = dict(NR, mean=round(NR['total']/NR['calls']) if NR['calls'] else 0)
sample = cases[::max(1, len(cases)//args.mutant_sample)]+fuzz
inst = sample[::4]
report['instrumentation_bad'] = instrumented(inst)
report['mutants_caught'] = mutants(sample, inst)
report['primitives'] = primitives(args.seed)
report['imports'] = [subprocess_json('imports', {}, ('--first', first), tag='-'+first.split('_', 1)[1])
                     for first in ('integration_wall_measures', 'integration_differential_geometry',
                                   'integration_exact_twin', 'integration_wall_measures_gmp')]
# the Python route: D5 loads gmpy2 and the GMP module exactly when the base composition does
python = dict(ATLAS_EXACT_ARITHMETIC='python')
report['python_route_imports'] = dict(
    d5=subprocess_json('imports', python, ('--first', 'integration_wall_measures'), tag='-d5'),
    base=subprocess_json('imports', python, ('--first', 'integration_wall_measures'), runtime=args.base,
                         tag='-base'))
report['backend_python'] = subprocess_json('backend', python)
report['backend_blocked'] = subprocess_json('backend', dict(D5_BLOCK_GMPY2='1', ATLAS_EXACT_ARITHMETIC='auto'))
report['explicit_native_unavailable'] = subprocess_json(
    'imports', dict(D5_BLOCK_GMPY2='1', ATLAS_EXACT_ARITHMETIC='gmpy2'), tag='-explicit-unavailable')
from focused import checks
report['focused'] = checks(globals())
report['checker_sha256'] = sha256(Path(__file__).read_bytes()).hexdigest()
report['focused_sha256'] = sha256(Path(__file__).with_name('focused.py').read_bytes()).hexdigest()
report['seconds'] = round(time.time()-t0, 1)
ok = (report['captured']['cases'] > 0 and report['captured_bad'] == 0 and report['fuzz_bad'] == 0 and report['instrumentation_bad'] == 0
      and all(report['mutants_caught'].values()) and report['resident'] and report['attached']
      and sum(report['captured_used'].values()) > 0
      and report['primitives']['lease_alias']
      and all(v.get('ok') is True for k,v in report['focused'].items() if k != 'source_hashes')
      and report['primitives']['dyadic_outward mismatches of 20000'] == 0
      and all(r.get('attached') and r.get('resident') for r in report['imports'])
      and {k: v for k, v in report['python_route_imports']['d5'].items() if k not in ('attached', 'resident')}
      == {k: v for k, v in report['python_route_imports']['base'].items() if k not in ('attached', 'resident')}
      and report['python_route_imports']['d5'].get('attached')
      and not report['python_route_imports']['d5'].get('resident')
      and report['python_route_imports']['d5'].get('gmpy2_loaded') is False
      and report['explicit_native_unavailable'].get('exit', 0) != 0
      and 'requested gmpy2 exact arithmetic is unavailable' in report['explicit_native_unavailable'].get('stderr', '')
      and all(r.get('bad') == 0 and r.get('available') is False and r.get('selection', {}).get('backend') == 'python'
              and not any(r.get('used', {1: 1}).values())
              for r in (report['backend_python'], report['backend_blocked'])))
report['verdict'] = 'PASS' if ok else 'FAIL'
out.write_text(json.dumps(report, indent=1, default=str), encoding='utf8')
print(json.dumps({k: report[k] for k in ('captured_bad', 'captured_used', 'fuzz_bad', 'fuzz_used',
                                         'instrumentation_bad', 'mutants_caught', 'native_retained',
                                         'verdict', 'seconds')}))
sys.exit(0 if ok else 1)
